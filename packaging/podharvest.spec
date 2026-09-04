# PyInstaller spec for podharvest.
#
# Builds a one-folder ("onedir") distribution rather than one-file: ASR
# engines are installed on demand into the app space at *runtime*, so the
# frozen bundle itself stays small and starts instantly. Console is kept on
# so the CLI works normally when the exe is run from a terminal, and so the
# GUI's log pane has a companion console for screen-reader-friendly output.
#
# Build with:  pyinstaller packaging/podharvest.spec --noconfirm
# (or just run scripts/build_installer.ps1, which also zips the result.)

import sys
from pathlib import Path

block_cipher = None

# pip has to travel with the build. podHarvest installs the ASR engines on
# demand at runtime, and in a frozen build sys.executable is podharvest.exe
# rather than a Python interpreter -- so there is no pip on the machine to
# borrow, and `podharvest _pip` (see cli._run_pip) has nothing to hand to.
#
# It is shipped as *plain files on disk* rather than frozen into the archive,
# and that is not a stylistic choice. Frozen, pip imports fine and then dies
# the moment it installs anything: its vendored distlib looks up a "finder"
# for a package by the type of the loader that imported it, and PyInstaller's
# FrozenImporter is not one of the loader types distlib knows, so it raises
# `Unable to locate finder for 'pip._vendor.distlib'`. Loaded from a real
# directory the loader is an ordinary SourceFileLoader and distlib is happy.
# cli._run_pip puts this directory on sys.path before handing over.
def _pip_tree():
    """Every file of the build environment's pip, as (source, dest) pairs."""
    import pip

    root = Path(pip.__file__).resolve().parent
    pairs = []
    for item in root.rglob("*"):
        if not item.is_file() or "__pycache__" in item.parts:
            continue
        dest = Path(PIP_RUNTIME_DIR) / "pip" / item.parent.relative_to(root)
        pairs.append((str(item), str(dest)))
    return pairs


#: Where the unfrozen pip lands inside the build. Kept in step with
#: `podharvest.cli.PIP_RUNTIME_DIR`, which is what looks for it.
PIP_RUNTIME_DIR = "pip_runtime"
pip_datas = _pip_tree()
pip_binaries = []
pip_hiddenimports = []


def _stable_abi_dll():
    """`python3.dll`, without which every abi3 wheel fails to load.

    Packages built against the limited API -- PyAV, and a growing share of the
    ecosystem -- link their extension against `python3.dll`, the forwarder
    that redirects to the real `python313.dll`. A normal CPython install ships
    both, so this never shows up in development. PyInstaller bundles only
    `python313.dll`, so in the frozen build those wheels install perfectly and
    then fail to import with "DLL load failed ... The specified module could
    not be found" -- naming the extension, never the DLL it actually wanted.

    That was faster-whisper's failure: it pulls in PyAV, and PyAV is abi3.
    """
    candidate = Path(sys.base_prefix) / "python3.dll"
    if not candidate.is_file():
        print(f"WARNING: {candidate} not found; abi3 wheels (PyAV, and so "
              "faster-whisper) will not load in this build.")
        return []
    return [(str(candidate), ".")]


abi3_binaries = _stable_abi_dll()


#: Standard-library packages that are large, never needed by anything
#: podHarvest installs, and in some cases actively unwanted in a frozen app.
#: `test` and `tests` are not in `sys.stdlib_module_names` and so are never
#: reached by the loop below; they are named anyway because a future Python
#: could expose them and nothing here should ever ship a test suite.
_STDLIB_SKIP = frozenset({
    "antigravity", "this", "idlelib", "pydoc_data", "tkinter",
    "turtle", "turtledemo", "test", "tests", "ensurepip", "venv",
})


def _whole_stdlib():
    """Every standard-library module, as hidden imports.

    Normally you would name the handful of modules a program uses and let
    PyInstaller's analysis find the rest. That reasoning does not hold here,
    because this program is a *host*: it pip-installs faster-whisper, NeMo,
    Vosk and whatever those depend on at runtime, into a folder the analysis
    never sees. Those packages import whatever they like from the standard
    library, and anything not bundled is simply absent.

    The symptom is misleading, too. faster-whisper installs cleanly and then
    fails with `No module named 'asyncio'` -- reported against the engine,
    which is not what is missing. Chasing them one at a time would be a slow
    rediscovery of the standard library, so the whole thing ships.
    """
    from PyInstaller.utils.hooks import collect_submodules

    names = []
    for name in sorted(sys.stdlib_module_names):
        if name.startswith("_") or name in _STDLIB_SKIP:
            continue
        names.append(name)
        # Packages need their submodules named individually; a bare top-level
        # import of `asyncio` does not bring `asyncio.events` with it.
        try:
            names.extend(collect_submodules(name))
        except Exception:  # noqa: BLE001 - not importable on this platform
            continue
    return sorted(set(names))


stdlib_hiddenimports = _whole_stdlib()
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - injected by PyInstaller

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[*pip_binaries, *abi3_binaries],
    datas=[*pip_datas],
    hiddenimports=[
        *pip_hiddenimports,
        *stdlib_hiddenimports,
        "wx",
        "wx.adv",
        # wx.media backs the player. It is imported at the top of
        # podharvest/player.py, but player.py itself is only reached lazily, so
        # the tracer never sees either -- and a build without it has a Playback
        # section that raises the moment you press Play.
        "wx.media",
        # Every tag and chapter operation runs on mutagen, and every one of its
        # imports is lazy and inside a function (so the modules load without
        # the extra). That is precisely what static analysis cannot follow.
        "mutagen",
        "mutagen.id3",
        "mutagen.mp4",
        "podharvest.cli",
        "podharvest.gui",
        "podharvest.appspace",
        "podharvest.config",
        "podharvest.hardware",
        "podharvest.acquire",
        "podharvest.net",
        "podharvest.convert",
        "podharvest.progress",
        "podharvest.util",
        "podharvest.models",
        # Imported lazily inside functions, so list them explicitly rather than
        # relying on PyInstaller's static analysis reaching them.
        "podharvest.feed",
        "podharvest.render",
        "podharvest.download",
        "podharvest.harvest",
        "podharvest.transcribe",
        "podharvest.enrich",
        "podharvest.accuracy",
        "podharvest.benchmark",
        "podharvest.chapters",
        # Also reached lazily and also missing until now: without these, a
        # built app cannot use a cloud provider, cannot show a time estimate,
        # and cannot read a stored API key.
        "podharvest.cloud",
        "podharvest.estimate",
        "podharvest.keystore",
        # The tag and chapter editor, its player, and everything they stand on.
        # All reached lazily from menu handlers, which is why they have to be
        # named here: a build without them opens a window that raises.
        "podharvest.a11y",
        "podharvest.audio_tags_core",
        "podharvest.editor",
        "podharvest.feedback",
        "podharvest.help",
        "podharvest.library",
        "podharvest.localfiles",
        "podharvest.cues",
        "podharvest.directory",
        "podharvest.discover",
        "podharvest.favorites",
        "podharvest.status_bar",
        "podharvest.azure_mai",
        "podharvest.reader",
        "podharvest.media_health",
        "podharvest.player",
        "podharvest.positions",
        "podharvest.reuse",
        "podharvest.reuse_core",
        "podharvest.tags",
    ],
    hookspath=[],
    excludes=[
        # Heavy/optional ML deps are installed on demand at runtime into the
        # portable app space (see podharvest/acquire.py) - never bundle them.
        "torch", "nemo", "nemo_toolkit", "llama_cpp", "vosk", "pyannote",
        "transformers", "tensorflow",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="podharvest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="podharvest",
)
