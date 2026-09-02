"""Portable, self-contained application space.

Everything podharvest needs at runtime - downloaded ASR models, pip-installed
optional engines, HTTP cache, config, logs - lives under a single root folder
that travels with the app, so it can run from a USB stick or a synced folder
without touching the user's home directory or global site-packages caches.

Resolution order for the root folder:
  1. `--app-dir` CLI flag (highest priority)
  2. `PODHARVEST_HOME` environment variable
  3. `<install-dir>/.podharvest-home` (a folder next to the code = portable mode)
  4. `~/.podharvest` (fallback, e.g. when installed system-wide via pip)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _install_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller/py2exe style bundle
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppSpace:
    root: Path

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def whisper_models_dir(self) -> Path:
        return self.models_dir / "whisper"

    @property
    def parakeet_models_dir(self) -> Path:
        return self.models_dir / "parakeet"

    @property
    def diarization_models_dir(self) -> Path:
        return self.models_dir / "diarization"

    @property
    def python_packages_dir(self) -> Path:
        """Isolated site-packages for optional heavy deps (torch, nemo, etc.)."""
        return self.root / "pydeps"

    @property
    def http_cache_dir(self) -> Path:
        return self.root / "cache" / "http"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def temp_dir(self) -> Path:
        return self.root / "tmp"

    @property
    def default_output_dir(self) -> Path:
        return self.root / "feeds"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def hardware_cache_file(self) -> Path:
        return self.config_dir / "hardware.json"

    def ensure(self) -> AppSpace:
        for d in (self.models_dir, self.whisper_models_dir, self.parakeet_models_dir,
                  self.diarization_models_dir, self.python_packages_dir,
                  self.http_cache_dir, self.config_dir, self.logs_dir,
                  self.temp_dir, self.default_output_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def env_overrides(self) -> dict[str, str]:
        """Environment variables that force ML libraries to cache inside our root."""
        self.ensure()
        return {
            "PODHARVEST_HOME": str(self.root),
            "HF_HOME": str(self.models_dir / "huggingface"),
            "HF_HUB_CACHE": str(self.models_dir / "huggingface" / "hub"),
            "TRANSFORMERS_CACHE": str(self.models_dir / "huggingface" / "transformers"),
            "TORCH_HOME": str(self.models_dir / "torch"),
            "XDG_CACHE_HOME": str(self.models_dir / "xdg-cache"),
            "WHISPER_MODELS_DIR": str(self.whisper_models_dir),
            "NEMO_CACHE_DIR": str(self.parakeet_models_dir / "nemo_cache"),
            "PYANNOTE_CACHE": str(self.diarization_models_dir),
            "PIP_CACHE_DIR": str(self.root / "cache" / "pip"),
            "TOKENIZERS_PARALLELISM": "false",
        }

    def activate(self) -> None:
        """Point ML caches + import path at this app space for the current process."""
        for key, value in self.env_overrides().items():
            os.environ.setdefault(key, value)
        pkgs = str(self.python_packages_dir)
        if pkgs not in sys.path:
            sys.path.insert(0, pkgs)


def resolve(app_dir: str | None = None) -> AppSpace:
    if app_dir:
        return AppSpace(Path(app_dir).expanduser().resolve()).ensure()
    if env_home := os.environ.get("PODHARVEST_HOME"):
        return AppSpace(Path(env_home).expanduser().resolve()).ensure()

    install_marker = _install_dir() / ".podharvest-home"
    if install_marker.exists() or _is_portable_layout():
        return AppSpace(install_marker).ensure()

    return AppSpace(Path.home() / ".podharvest").ensure()


def _is_portable_layout() -> bool:
    """True when this copy is meant to keep its data next to itself.

    `portable.flag` is written by the PyInstaller build; `pyvenv.cfg` means the
    app sits directly inside its own virtual environment. A `.git` directory is
    deliberately *not* treated as a signal - it would make every clone behave
    differently from a downloaded copy of the same code, and quietly fill a
    contributor's working tree with multi-gigabyte model downloads.
    """
    d = _install_dir()
    return (d / "portable.flag").exists() or (d / "pyvenv.cfg").exists()
