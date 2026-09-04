"""Rich, on-demand acquisition of ASR/enrichment models and optional packages.

Everything lands inside the portable `AppSpace` (never the user's home
directory or global site-packages), with resumable, progress-reported
downloads, checksum-friendly manifests, and graceful fallbacks:

- Hugging Face repos (faster-whisper, Parakeet, Canary, GGUF enrichment
  models) are fetched with `huggingface_hub` when it is installed, or via
  plain HTTPS `resolve/main/<file>` URLs through `podharvest.net` otherwise.
- Plain HTTPS archives (e.g. Vosk's `.zip` releases) stream straight through
  `podharvest.net.HttpClient` and are extracted in place.
- Optional heavy Python packages (faster-whisper, nemo_toolkit, llama-cpp-python,
  vosk, huggingface_hub...) are installed with `pip --target` into the
  isolated `AppSpace.python_packages_dir`, never touching the system/global
  Python environment.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from podharvest.appspace import AppSpace
from podharvest.hardware import ModelChoice
from podharvest.net import HttpClient
from podharvest.progress import ProgressReporter
from podharvest.util import LOG, HarvestError

MANIFEST_NAME = "manifest.json"

# Maps each engine to the pip package(s) it needs and the module used to
# check whether it is already importable.
ENGINE_PACKAGES: dict[str, list[tuple[str, str]]] = {
    "faster-whisper": [("faster-whisper", "faster_whisper")],
    "parakeet": [("nemo_toolkit[asr]", "nemo"), ("huggingface_hub", "huggingface_hub")],
    "parakeet-onnx": [("sherpa-onnx", "sherpa_onnx"), ("huggingface_hub", "huggingface_hub")],
    "nemo-canary": [("nemo_toolkit[asr]", "nemo"), ("huggingface_hub", "huggingface_hub")],
    "vosk": [("vosk", "vosk")],
    "moonshine": [("useful-moonshine-onnx", "moonshine_onnx"),
                  ("huggingface_hub", "huggingface_hub")],
    "llama-cpp": [("llama-cpp-python", "llama_cpp")],
}
DIARIZATION_PACKAGES: dict[str, list[tuple[str, str]]] = {
    "pyannote": [("pyannote.audio", "pyannote.audio"), ("huggingface_hub", "huggingface_hub")],
    "sherpa-onnx": [("sherpa-onnx", "sherpa_onnx")],
    "nemo-msdd": [("nemo_toolkit[asr]", "nemo"), ("omegaconf", "omegaconf")],
}


def _model_dir(app: AppSpace, choice: ModelChoice) -> Path:
    """Where this model lives. The one answer, for every kind of model.

    Enrichment models are the reason this checks `kind` first.
    `acquire_enrichment_model` puts them in `models/enrichment/`, but this
    function only knew about engines -- so it answered `models/llama-cpp/` and
    `is_downloaded()` said no about every enrichment model that had in fact
    been downloaded. Nothing asked that question yet, which is the only reason
    it was not a visible bug; it was one waiting for a caller.
    """
    if choice.kind == "enrichment":
        return app.models_dir / "enrichment" / choice.model
    base = {
        "faster-whisper": app.whisper_models_dir,
        "parakeet": app.parakeet_models_dir,
        "nemo-canary": app.parakeet_models_dir,
        "parakeet-onnx": app.parakeet_models_dir / "onnx",
    }.get(choice.engine, app.models_dir / choice.engine)
    return base / choice.model


def _manifest_path(model_dir: Path) -> Path:
    return model_dir / MANIFEST_NAME


# Minimum plausible size for a *part* of a real model file, in bytes. Catches
# the classic failure mode of a truncated/interrupted download or an error
# page saved with the right filename - "present" but not "working".
_MIN_PLAUSIBLE_BYTES = 1024

#: Directories inside a downloaded snapshot that are not model content.
#: `huggingface_hub` keeps its own bookkeeping in `.cache/`, including a
#: one-byte `.gitignore`. Recording those as model files meant every
#: verification failed on a perfectly good download -- "missing or truncated
#: .gitignore" -- which is a sentence about a file nobody was ever going to
#: load.
_NOT_MODEL_DIRS: frozenset[str] = frozenset({".cache", "__pycache__"})

#: Extensions that carry the actual weights. Only these have to be *big*.
#: Everything else in a repo -- config.json, tokenizer.json, .gitattributes,
#: a README -- is legitimately small, and a size floor applied to all of them
#: rejects healthy downloads.
_WEIGHT_SUFFIXES: frozenset[str] = frozenset({
    ".bin", ".safetensors", ".onnx", ".pt", ".pth", ".ckpt", ".nemo",
    ".gguf", ".ggml", ".tflite", ".mlmodel",
})


def is_model_content(relative: str) -> bool:
    """Whether *relative* is part of the model rather than bookkeeping.

    Excludes the tool's own manifest and the downloader's cache. Both used to
    be recorded as model files: the manifest because it is written into the
    same folder before the file list is taken on a re-download, and the cache
    because a full-repo snapshot walks everything.
    """
    parts = PurePosixPath(relative).parts
    if not parts:
        return False
    if parts[-1] == MANIFEST_NAME:
        return False
    return not any(part in _NOT_MODEL_DIRS for part in parts)


def model_files(model_dir: Path) -> list[str]:
    """Every real model file in *model_dir*, as paths relative to it.

    Relative paths rather than bare names, because a snapshot has
    subdirectories and `p.name` flattens them -- so `model_dir / name` could
    not find the file again, and two files sharing a name in different folders
    collapsed into one.
    """
    found = []
    for path in sorted(model_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(model_dir).as_posix()
        if is_model_content(relative):
            found.append(relative)
    return found
GGUF_MAGIC = b"GGUF"


def verify_model(model_dir: Path, choice: ModelChoice, files: list[str] | None = None) -> tuple[bool, str]:
    """Sanity-check that downloaded files are real and structurally intact -
    not just present. This is deliberately cheap (magic bytes, size floors,
    required filenames) rather than a full model load, so it is safe to run
    on every cache hit without materially slowing anything down.
    """
    if not model_dir.exists():
        return False, "model directory does not exist"

    if choice.engine in {"parakeet-onnx", "zipformer-onnx"}:
        required = ["encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"]
        for name in required:
            path = model_dir / name
            if not path.exists() or path.stat().st_size < _MIN_PLAUSIBLE_BYTES:
                return False, f"missing or truncated {name}"
        return True, "ok"

    if choice.engine == "llama-cpp":
        path = model_dir / choice.filename
        if not path.exists() or path.stat().st_size < _MIN_PLAUSIBLE_BYTES:
            return False, f"missing or truncated {choice.filename}"
        with path.open("rb") as fh:
            if fh.read(4) != GGUF_MAGIC:
                return False, f"{choice.filename} does not start with the GGUF magic bytes"
        return True, "ok"

    if choice.engine == "vosk":
        found = list(model_dir.rglob("*"))
        real_files = [p for p in found if p.is_file() and p.name != MANIFEST_NAME]
        total = sum(p.stat().st_size for p in real_files)
        if len(real_files) < 3 or total < _MIN_PLAUSIBLE_BYTES * 10:
            return False, "extracted Vosk model looks incomplete (too few/small files)"
        return True, "ok"

    # faster-whisper / NeMo full-repo snapshots and anything else: every file
    # the manifest recorded must still be there, and the ones carrying weights
    # must still be a plausible size.
    #
    # A fresh download passes its own list; anything else is asked of the disk
    # rather than of the manifest.
    #
    # That is deliberate. An older version recorded bare filenames flattened
    # out of their folders, including the downloader's own `.cache` -- so a
    # perfectly good model carried a manifest naming `.gitignore` at the top
    # level, where no such file has ever existed. Trusting that list meant
    # failing forever on a file that was never model content, with a message
    # telling the reader to delete a model that is entirely intact. The real
    # question is "is there an intact model in this folder", and the folder is
    # what can answer it.
    names = list(files) if files is not None else model_files(model_dir)
    names = [name for name in names if is_model_content(name)]
    if not names:
        return False, "nothing was downloaded for this model"

    weights = 0
    for name in names:
        path = model_dir / name
        if not path.exists():
            return False, f"missing {name}"
        if Path(name).suffix.lower() in _WEIGHT_SUFFIXES:
            weights += 1
            if path.stat().st_size < _MIN_PLAUSIBLE_BYTES:
                return False, f"truncated {name}"
    if not weights:
        # Nothing that could hold a model. A snapshot of only config files is
        # not a download anybody can transcribe with.
        return False, "no model weights among the downloaded files"
    return True, "ok"


def _read_manifest_files(model_dir: Path) -> list[str]:
    try:
        data = json.loads(_manifest_path(model_dir).read_text(encoding="utf-8"))
        return data.get("files", [])
    except (OSError, ValueError):
        return []


def is_downloaded(app: AppSpace, choice: ModelChoice) -> bool:
    model_dir = _model_dir(app, choice)
    manifest = _manifest_path(model_dir)
    if not manifest.exists():
        return False
    ok, reason = verify_model(model_dir, choice)
    if not ok:
        LOG.warning("Cached %s:%s failed verification (%s) - it will be re-downloaded, "
                   "not silently reused.", choice.engine, choice.model, reason)
        return False
    return True


def _write_manifest(model_dir: Path, choice: ModelChoice, files: list[str], *, verified: bool = True) -> None:
    _manifest_path(model_dir).write_text(json.dumps({
        "engine": choice.engine, "model": choice.model, "source": choice.source,
        "license": choice.license, "files": files, "verified": verified,
    }, indent=2), encoding="utf-8")


@dataclass
class AcquisitionResult:
    model_dir: Path
    already_present: bool
    files: list[str]


#: The hidden subcommand the frozen build uses to reach pip. See
#: `pip_command` for why it has to exist at all.
PIP_SUBCOMMAND = "_pip"


def running_frozen() -> bool:
    """Whether this is the PyInstaller build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def pip_available() -> tuple[bool, str]:
    """Whether pip can be reached at all, and a sentence saying why not.

    In a source checkout pip lives in the interpreter running podHarvest. In
    the frozen build it is bundled, and its absence means the build was made
    without it -- which is worth saying plainly, because the symptom otherwise
    is every model download failing for no visible reason.
    """
    if running_frozen():
        # The frozen build ships pip as plain files beside the executable
        # rather than importing it, so `import pip` here would answer the
        # wrong question -- see `cli.bundled_pip_dir`.
        from podharvest.cli import bundled_pip_dir

        if bundled_pip_dir() is None:
            return False, (
                "This build of podHarvest was made without pip bundled, so it "
                "cannot download the transcription engines. Please report this "
                "with the version number - it is a packaging fault, not "
                "something you can fix from here."
            )
        return True, ""

    try:
        import pip  # noqa: F401
    except ImportError:
        return False, (
            "pip is not available in the Python running podHarvest, so extra "
            "packages cannot be installed. Install pip, or use a Python that "
            "has it."
        )
    return True, ""


def pip_command(target: str, extra_args: list[str], pip_name: str) -> list[str]:
    """The command line that installs *pip_name* into *target*.

    Frozen builds are the whole reason this is a function. `sys.executable` is
    normally the Python interpreter, so `-m pip` reaches pip -- but in the
    PyInstaller build it is `podharvest.exe`, which is not an interpreter, and
    `-m pip` reached podHarvest's own argument parser instead. The result was
    an argparse error logged as pip output, every install failing with exit 2,
    and transcription quietly unavailable in every packaged copy. So the frozen
    build calls a hidden subcommand that hands straight to pip.
    """
    arguments = ["install", "--target", target, "--no-warn-script-location",
                 "--disable-pip-version-check", *extra_args, pip_name]
    if running_frozen():
        return [sys.executable, PIP_SUBCOMMAND, *arguments]
    return [sys.executable, "-m", "pip", *arguments]


def is_importable(import_name: str) -> bool:
    """Whether *import_name* can be imported right now."""
    try:
        __import__(import_name.split(".")[0])
    except ImportError:
        return False
    return True


def missing_packages(app: AppSpace, packages: list[tuple[str, str]]) -> list[str]:
    """The pip names in *packages* that are not importable yet."""
    app.activate()
    return [pip_name for pip_name, import_name in packages
            if not is_importable(import_name)]


def engine_packages_missing(app: AppSpace, engine: str) -> list[str]:
    """What *engine* still needs downloading. Empty means it is ready to run."""
    return missing_packages(app, ENGINE_PACKAGES.get(engine, []))


def diarization_packages_missing(app: AppSpace, backend: str) -> list[str]:
    """What speaker identification still needs. Empty means ready."""
    return missing_packages(app, DIARIZATION_PACKAGES.get(backend, []))


@dataclass
class PackageReport:
    """One package: is it there, does it import, and if not, why not."""

    pip_name: str
    import_name: str
    installed: bool
    importable: bool
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.importable

    def sentence(self) -> str:
        if self.importable:
            return f"{self.pip_name}: ready"
        if not self.installed:
            return f"{self.pip_name}: not downloaded yet"
        return f"{self.pip_name}: downloaded but will not load - {self.error}"


def check_package(app: AppSpace, pip_name: str, import_name: str) -> PackageReport:
    """Try the import for real and report exactly what happened.

    "Installed" and "usable" are different questions and the gap between them
    is where the hard failures live -- a wheel whose native library will not
    load is on disk, passes any file check, and still cannot run. So this
    imports it, and keeps the error when it cannot.
    """
    app.activate()
    importlib.invalidate_caches()
    top_level = import_name.split(".")[0]
    installed = any((Path(entry) / top_level).exists()
                    or (Path(entry) / f"{top_level}.py").exists()
                    for entry in (str(app.python_packages_dir),))
    try:
        __import__(top_level)
    except Exception as exc:  # noqa: BLE001 - any failure is a failure to report
        return PackageReport(pip_name, import_name, installed, False,
                             f"{type(exc).__name__}: {exc}")
    return PackageReport(pip_name, import_name, True, True)


def check_engine(app: AppSpace, engine: str) -> list[PackageReport]:
    """Every package *engine* needs, each answered honestly."""
    return [check_package(app, pip_name, import_name)
            for pip_name, import_name in ENGINE_PACKAGES.get(engine, [])]


def ensure_package(app: AppSpace, pip_name: str, import_name: str) -> bool:
    """Import `import_name`, installing `pip_name` into the isolated
    pydeps folder on first use. Returns True if it is importable afterward.

    Tries every strategy in `PIP_INSTALL_STRATEGIES.get(pip_name, [[]])` in
    order (e.g. a prebuilt-wheel index before a from-source build), so a
    package that fails to *build* on Windows (llama-cpp-python's vendored
    `llama.cpp` tree exceeds Windows' default 260-character path limit
    during a source build) still installs cleanly via a prebuilt wheel
    instead of surfacing a confusing low-level OSError.
    """
    app.activate()
    top_level = import_name.split(".")[0]
    try:
        __import__(top_level)
        return True
    except ImportError:
        pass

    ok, why = pip_available()
    if not ok:
        LOG.error("Cannot install '%s'. %s", pip_name, why)
        return False

    target = str(app.python_packages_dir)
    strategies = PIP_INSTALL_STRATEGIES.get(pip_name, [[]])
    last_output = ""
    for i, extra_args in enumerate(strategies):
        label = "prebuilt wheel" if extra_args else "standard"
        LOG.info("Setting up '%s'. This is a one-time download (into %s; try %d of %d, %s)...",
                 pip_name, target, i + 1, len(strategies), label)
        cmd = pip_command(target, list(extra_args), pip_name)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            LOG.error("Could not run pip to install %s: %s", pip_name, exc)
            return False

        last_output = (proc.stdout or "") + (proc.stderr or "")
        for line in last_output.splitlines():
            LOG.debug("pip: %s", line.rstrip())
        if proc.returncode == 0:
            break
        LOG.warning("Install attempt %d/%d for '%s' failed (exit %s); %s.",
                    i + 1, len(strategies), pip_name, proc.returncode,
                    "trying the next strategy" if i + 1 < len(strategies) else "no strategies left")
    else:
        _log_install_failure(pip_name, last_output)
        return False

    # Python caches what it found (or did not find) in each sys.path entry.
    # pydeps was on the path before the install and was empty or absent then,
    # so without this the freshly written package is invisible and a perfectly
    # good install is reported as "installed but still not importable".
    importlib.invalidate_caches()
    app.activate()
    try:
        __import__(top_level)
        return True
    except ImportError as exc:
        LOG.error("%s installed into %s but still could not be imported: %s. "
                  "This usually means the wheel was built for a different "
                  "Python than the one running podHarvest.",
                  pip_name, target, exc)
        return False


# Packages known to fail a plain `pip install` on at least one platform, and
# the ordered list of extra pip arguments to retry with. Each inner list is
# a set of *additional* CLI args appended before the package name; `[]`
# means "the plain install" (always included as the last, most-compatible
# fallback in case the maintainer's wheel index is ever unavailable).
PIP_INSTALL_STRATEGIES: dict[str, list[list[str]]] = {
    # llama-cpp-python vendors the full llama.cpp source tree (including a
    # Svelte web UI with very deeply nested paths); building that sdist on
    # Windows routinely fails with OSError: [Errno 2] No such file or
    # directory once the path exceeds Windows' default 260-character limit.
    # The maintainer publishes prebuilt CPU wheels precisely to avoid this;
    # use `--extra-index-url` (not `--index-url`) so pip can still resolve
    # ordinary transitive dependencies like numpy/typing_extensions from PyPI.
    "llama-cpp-python": [
        ["--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu", "--only-binary=:all:"],
        [],
    ],
}

_PATH_LENGTH_MARKERS = ("no such file or directory", "filename too long", "path too long")


def _log_install_failure(pip_name: str, output: str) -> None:
    LOG.error("Could not set up '%s'. Every install method was tried and none worked.", pip_name)
    lowered = output.lower()
    if any(marker in lowered for marker in _PATH_LENGTH_MARKERS):
        LOG.error(
            "This looks like a Windows path-length limit failure while building '%s' from source "
            "(its vendored source tree has very deeply nested paths). If a prebuilt-wheel strategy "
            "wasn't tried or is unavailable, you can also enable Windows long path support once, as "
            "Administrator: 'reg add HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem "
            "/v LongPathsEnabled /t REG_DWORD /d 1 /f', then restart the machine.", pip_name)
    tail = "\n".join(output.strip().splitlines()[-15:])
    if tail:
        LOG.debug("Final pip output for '%s':\n%s", pip_name, tail)


def ensure_engine_packages(app: AppSpace, engine: str,
                           progress: Callable[[str], None] | None = None) -> bool:
    ok = True
    for pip_name, import_name in ENGINE_PACKAGES.get(engine, []):
        if progress:
            progress(f"Checking {pip_name}...")
        ok = ensure_package(app, pip_name, import_name) and ok
    return ok


def ensure_diarization_packages(app: AppSpace, backend: str = "pyannote") -> bool:
    packages = DIARIZATION_PACKAGES.get(backend, DIARIZATION_PACKAGES["pyannote"])
    return all(ensure_package(app, pip_name, import_name) for pip_name, import_name in packages)


def _hf_url(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


def _download_via_http(client: HttpClient, url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    resume_from = tmp.stat().st_size if tmp.exists() else 0
    with ProgressReporter(f"Downloading {dest.name}", unit="B") as reporter, \
            tmp.open("ab" if resume_from else "wb") as fh:
        written, headers, appended = client.stream(
            url, fh, resume_from=resume_from,
            on_chunk=reporter.update)
        total = headers.get("content-length")
        if total and total.isdigit():
            reporter.set_total(resume_from + int(total) if appended else int(total))
    tmp.replace(dest)
    return dest.stat().st_size


def _reporting_tqdm(on_progress: Callable[[float, str], None] | None):
    """A tqdm class that reports to *on_progress* as well as to the console.

    `huggingface_hub` draws its own progress bars with tqdm, which is exactly
    right on a terminal and invisible in a window -- so the Download model
    button appeared to do nothing at all for several minutes. Handing
    snapshot_download a tqdm subclass is the supported way in; every bar it
    would have drawn calls back here instead.

    Returns None when there is nobody to report to, so the ordinary console
    behaviour is left completely alone.
    """
    if on_progress is None:
        return None
    try:
        from tqdm.auto import tqdm as _tqdm
    except ImportError:  # pragma: no cover - hub ships tqdm; belt and braces
        return None

    class _Reporting(_tqdm):  # type: ignore[misc, valid-type]
        def update(self, n=1):  # noqa: D102 - tqdm's own signature
            result = super().update(n)
            try:
                total = float(getattr(self, "total", 0) or 0)
                done = float(getattr(self, "n", 0) or 0)
                percent = (100.0 * done / total) if total > 0 else 0.0
                on_progress(percent, str(getattr(self, "desc", "") or ""))
            except Exception:  # noqa: BLE001 - a progress bar must never fail a download
                pass
            return result

    return _Reporting


def acquire_asr_model(app: AppSpace, choice: ModelChoice, *, client: HttpClient | None = None,
                      force: bool = False,
                      on_progress: Callable[[float, str], None] | None = None) -> AcquisitionResult:
    """Download (or confirm already present) everything `choice` needs.

    Hugging-Face-hosted engines (faster-whisper, parakeet, nemo-canary,
    moonshine) are fetched with `huggingface_hub.snapshot_download` when
    available, which understands resumable, parallel, deduplicated repo
    downloads; we fall back to plain HTTPS otherwise. Vosk ships as a single
    zip archive and is extracted after downloading.
    """
    model_dir = _model_dir(app, choice)
    if not force and is_downloaded(app, choice):
        return AcquisitionResult(model_dir, True, [])

    def say(percent: float, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(percent, detail)

    say(0.0, f"setting up the {choice.engine} engine")
    if not ensure_engine_packages(app, choice.engine):
        raise HarvestError(
            f"Could not install the Python packages required for engine '{choice.engine}'. "
            "Check your internet connection and try again, or pick a different engine.")
    say(0.0, f"downloading {choice.model}")

    model_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    if choice.engine == "vosk":
        client = client or HttpClient()
        archive = model_dir.with_suffix(".zip")
        _download_via_http(client, choice.source, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(model_dir.parent)
        archive.unlink(missing_ok=True)
        files = [choice.source.rsplit("/", 1)[-1]]

    elif choice.filename:  # a single named file inside an HF repo (e.g. a GGUF)
        try:
            from huggingface_hub import hf_hub_download  # type: ignore
            path = hf_hub_download(repo_id=choice.source, filename=choice.filename,
                                    local_dir=str(model_dir), local_dir_use_symlinks=False)
            files = [Path(path).name]
        except ImportError:
            client = client or HttpClient()
            dest = model_dir / choice.filename
            _download_via_http(client, _hf_url(choice.source, choice.filename), dest)
            files = [choice.filename]

    else:  # a full HF repo snapshot (faster-whisper CT2 dirs, NeMo checkpoints)
        try:
            from huggingface_hub import snapshot_download  # type: ignore
            reporting = _reporting_tqdm(on_progress)
            kwargs = {"repo_id": choice.source, "local_dir": str(model_dir),
                      "local_dir_use_symlinks": False}
            if reporting is not None:
                kwargs["tqdm_class"] = reporting
            try:
                snapshot_download(**kwargs)
            except TypeError:
                # An older hub without tqdm_class. Losing the progress bar is
                # not a reason to lose the download.
                kwargs.pop("tqdm_class", None)
                snapshot_download(**kwargs)
            files = model_files(model_dir)
        except ImportError as exc:
            raise HarvestError(
                f"'huggingface_hub' is required to download {choice.source} as a full repo "
                f"snapshot; run 'podharvest hardware' first to auto-install it. ({exc})") from exc

    say(100.0, "checking what was downloaded")
    _write_manifest(model_dir, choice, files)
    ok, reason = verify_model(model_dir, choice, files)
    if not ok:
        raise HarvestError(
            f"Downloaded {choice.engine}:{choice.model} but it failed verification ({reason}). "
            "This usually means the download was interrupted or corrupted; delete "
            f"'{model_dir}' and try again.")
    return AcquisitionResult(model_dir, False, files)


def acquire_enrichment_model(app: AppSpace, choice: ModelChoice, *,
                             client: HttpClient | None = None, force: bool = False) -> AcquisitionResult:
    model_dir = _model_dir(app, choice)
    if not force and _manifest_path(model_dir).exists():
        ok, reason = verify_model(model_dir, choice)
        if ok:
            return AcquisitionResult(model_dir, True, [])
        LOG.warning("Cached enrichment model %s failed verification (%s); re-downloading.",
                   choice.model, reason)
    if not ensure_package(app, "llama-cpp-python", "llama_cpp"):
        raise HarvestError("Could not install llama-cpp-python for enrichment models.")
    model_dir.mkdir(parents=True, exist_ok=True)
    dest = model_dir / choice.filename
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
        path = hf_hub_download(repo_id=choice.source, filename=choice.filename,
                               local_dir=str(model_dir), local_dir_use_symlinks=False)
        dest = Path(path)
    except ImportError:
        client = client or HttpClient()
        _download_via_http(client, _hf_url(choice.source, choice.filename), dest)
    _write_manifest(model_dir, choice, [dest.name])
    ok, reason = verify_model(model_dir, choice, [dest.name])
    if not ok:
        raise HarvestError(
            f"Downloaded enrichment model {choice.model} but it failed verification ({reason}). "
            f"Delete '{model_dir}' and try again.")
    return AcquisitionResult(model_dir, False, [dest.name])
