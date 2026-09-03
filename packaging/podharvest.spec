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
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - injected by PyInstaller

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
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
