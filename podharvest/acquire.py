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

import json
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    # the manifest recorded must still exist and be non-trivially sized.
    names = files if files is not None else _read_manifest_files(model_dir)
    if not names:
        return False, "no files recorded for this model"
    for name in names:
        path = model_dir / name
        if not path.exists() or path.stat().st_size < _MIN_PLAUSIBLE_BYTES:
            return False, f"missing or truncated {name}"
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

    target = str(app.python_packages_dir)
    strategies = PIP_INSTALL_STRATEGIES.get(pip_name, [[]])
    last_output = ""
    for i, extra_args in enumerate(strategies):
        label = "prebuilt wheel" if extra_args else "standard"
        LOG.info("Setting up '%s'. This is a one-time download (into %s; try %d of %d, %s)...",
                 pip_name, target, i + 1, len(strategies), label)
        cmd = [sys.executable, "-m", "pip", "install", "--target", target,
               "--no-warn-script-location", "--disable-pip-version-check", *extra_args, pip_name]
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

    try:
        __import__(top_level)
        return True
    except ImportError as exc:
        LOG.error("%s installed but still not importable: %s", pip_name, exc)
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


def acquire_asr_model(app: AppSpace, choice: ModelChoice, *, client: HttpClient | None = None,
                      force: bool = False) -> AcquisitionResult:
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

    if not ensure_engine_packages(app, choice.engine):
        raise HarvestError(
            f"Could not install the Python packages required for engine '{choice.engine}'. "
            "Check your internet connection and try again, or pick a different engine.")

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
            snapshot_download(repo_id=choice.source, local_dir=str(model_dir),
                              local_dir_use_symlinks=False)
            files = [p.name for p in model_dir.rglob("*") if p.is_file()]
        except ImportError as exc:
            raise HarvestError(
                f"'huggingface_hub' is required to download {choice.source} as a full repo "
                f"snapshot; run 'podharvest hardware' first to auto-install it. ({exc})") from exc

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
    model_dir = app.models_dir / "enrichment" / choice.model
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
