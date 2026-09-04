"""Hardware probing and model recommendation.

Detects CPU, RAM, GPU (NVIDIA CUDA, AMD ROCm, Apple Silicon Metal), free disk
space and installed acceleration libraries, then recommends the best on-device
speech recognition model that will actually fit and run well.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from podharvest.util import LOG

GB = 1024 ** 3


@dataclass
class Gpu:
    vendor: str = ""          # nvidia | amd | apple | intel
    name: str = ""
    vram_bytes: int = 0
    driver: str = ""
    compute: str = ""         # cuda | rocm | metal | none

    @property
    def vram_gb(self) -> float:
        return round(self.vram_bytes / GB, 1)


@dataclass
class Hardware:
    os_name: str = ""
    os_version: str = ""
    arch: str = ""
    cpu_name: str = ""
    physical_cores: int = 0
    logical_cores: int = 0
    ram_total_bytes: int = 0
    ram_available_bytes: int = 0
    disk_free_bytes: int = 0
    gpus: list[Gpu] = field(default_factory=list)
    has_torch: bool = False
    has_cuda: bool = False
    has_mlx: bool = False
    has_ffmpeg: bool = False
    ffmpeg_path: str = ""
    python_version: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ram_gb(self) -> float:
        return round(self.ram_total_bytes / GB, 1)

    @property
    def ram_free_gb(self) -> float:
        return round(self.ram_available_bytes / GB, 1)

    @property
    def disk_free_gb(self) -> float:
        return round(self.disk_free_bytes / GB, 1)

    @property
    def best_gpu(self) -> Gpu | None:
        return max(self.gpus, key=lambda g: g.vram_bytes) if self.gpus else None

    @property
    def accelerator(self) -> str:
        """Preferred compute backend: cuda, rocm, metal or cpu."""
        gpu = self.best_gpu
        if gpu and gpu.compute in {"cuda", "rocm", "metal"}:
            return gpu.compute
        return "cpu"

    @property
    def usable_accel_memory_gb(self) -> float:
        """Memory budget an ASR model may use, in gigabytes."""
        gpu = self.best_gpu
        if self.accelerator == "metal":
            # Apple unified memory: assume roughly two thirds is addressable.
            return round(self.ram_total_bytes * 0.66 / GB, 1)
        if gpu and gpu.vram_bytes:
            return round(gpu.vram_bytes * 0.85 / GB, 1)
        return round(max(self.ram_available_bytes, self.ram_total_bytes * 0.6) / GB, 1)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            ram_gb=self.ram_gb,
            ram_free_gb=self.ram_free_gb,
            disk_free_gb=self.disk_free_gb,
            accelerator=self.accelerator,
            usable_accel_memory_gb=self.usable_accel_memory_gb,
        )
        return data

    def summary_lines(self) -> list[str]:
        lines = [
            f"Operating system : {self.os_name} {self.os_version} ({self.arch})",
            f"Python           : {self.python_version}",
            f"CPU              : {self.cpu_name or 'unknown'}",
            f"CPU cores        : {self.physical_cores or '?'} physical / {self.logical_cores or '?'} logical",
            f"Memory           : {self.ram_gb} GB total, {self.ram_free_gb} GB available",
            f"Free disk space  : {self.disk_free_gb} GB",
        ]
        if self.gpus:
            for gpu in self.gpus:
                vram = f"{gpu.vram_gb} GB VRAM" if gpu.vram_bytes else "shared memory"
                lines.append(f"Accelerator      : {gpu.name} ({gpu.vendor}, {gpu.compute}, {vram})")
        else:
            lines.append("Accelerator      : none detected, transcription will run on the CPU")
        lines.append(f"Compute backend  : {self.accelerator}")
        lines.append(f"Model budget     : about {self.usable_accel_memory_gb} GB")
        lines.append(f"ffmpeg           : {self.ffmpeg_path or 'not found (podharvest can install a private copy)'}")
        for note in self.notes:
            lines.append(f"Note             : {note}")
        return lines


# -- individual probes -----------------------------------------------------

def _ram() -> tuple[int, int]:
    """Return (total, available) bytes, best effort across platforms."""
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except Exception:
        pass

    if sys.platform == "win32":
        class _MemStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = _MemStatus()
        status.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys), int(status.ullAvailPhys)

    if sys.platform == "darwin":
        try:
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                       text=True, timeout=5).stdout.strip())
            return total, int(total * 0.5)
        except Exception:
            pass

    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
        return int(total), int(avail)
    except (ValueError, OSError, AttributeError):
        return 0, 0


def _cpu_name() -> str:
    try:
        if sys.platform == "win32":
            name = os.environ.get("PROCESSOR_IDENTIFIER", "")
            if name:
                return name
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        if sys.platform.startswith("linux"):
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception as exc:
        LOG.debug("CPU name probe failed: %s", exc)
    return platform.processor() or platform.machine()


def _physical_cores() -> int:
    try:
        import psutil  # type: ignore
        return int(psutil.cpu_count(logical=False) or 0)
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True,
                                      text=True, timeout=5).stdout.strip())
        if sys.platform.startswith("linux"):
            ids = set()
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
                core, phys = None, None
                for line in fh:
                    if line.startswith("core id"):
                        core = line.split(":")[1].strip()
                    elif line.startswith("physical id"):
                        phys = line.split(":")[1].strip()
                    elif not line.strip() and core is not None:
                        ids.add((phys, core))
                        core = phys = None
            if ids:
                return len(ids)
    except Exception:
        pass
    return 0


def _nvidia_gpus() -> list[Gpu]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return []
        gpus = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[1].replace(".", "").isdigit():
                gpus.append(Gpu(vendor="nvidia", name=parts[0],
                                vram_bytes=int(float(parts[1]) * 1024 * 1024),
                                driver=parts[2] if len(parts) > 2 else "",
                                compute="cuda"))
        return gpus
    except Exception as exc:
        LOG.debug("nvidia-smi probe failed: %s", exc)
        return []


def _torch_gpus() -> tuple[list[Gpu], bool, bool]:
    """Return (gpus, has_torch, has_cuda) using torch when it is installed."""
    try:
        import torch  # type: ignore
    except Exception:
        return [], False, False
    gpus: list[Gpu] = []
    has_cuda = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    if has_cuda:
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            vendor = "amd" if "hip" in str(getattr(torch.version, "hip", "") or "").lower() else "nvidia"
            gpus.append(Gpu(vendor=vendor, name=props.name, vram_bytes=int(props.total_memory),
                            compute="rocm" if vendor == "amd" else "cuda"))
    if not gpus and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        gpus.append(Gpu(vendor="apple", name="Apple Silicon GPU", compute="metal"))
    return gpus, True, has_cuda


def _apple_gpu() -> list[Gpu]:
    if sys.platform == "darwin" and platform.machine() in {"arm64", "aarch64"}:
        chip = _cpu_name() or "Apple Silicon"
        return [Gpu(vendor="apple", name=chip, compute="metal")]
    return []


def _winget_ffmpeg() -> str:
    """FFmpeg from winget's own package folder, surviving version upgrades.

    winget installs Gyan.FFmpeg into a folder named after the version
    (``ffmpeg-9.0-full_build``) and writes that versioned path into the user's
    PATH. On upgrade the folder is replaced (``ffmpeg-9.0.1-full_build``) but
    open shells and services keep the old PATH -- so ``shutil.which`` fails,
    and every FFmpeg feature silently degrades in exactly the way
    media_health.py warns about. Caught in the act on the development machine:
    winget upgraded mid-session and podHarvest lost FFmpeg without anything
    changing in podHarvest. Globbing the package directory finds whatever
    version is actually there, regardless of what PATH believes.
    """
    base = os.environ.get("LOCALAPPDATA", "")
    if not base:
        return ""
    root = Path(base) / "Microsoft" / "WinGet" / "Packages"
    try:
        found = sorted(root.glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"), reverse=True)
    except OSError:
        return ""
    return str(found[0]) if found else ""


def find_ffmpeg() -> str:
    """Locate ffmpeg on PATH, in winget's folder, or via imageio-ffmpeg."""
    env = os.environ.get("PODHARVEST_FFMPEG")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget = _winget_ffmpeg()
    if winget:
        return winget
    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return ""


def find_ffprobe() -> str:
    """Locate ffprobe, which ships beside ffmpeg.

    Deriving it with `find_ffmpeg().replace("ffmpeg", "ffprobe")` looks obvious
    and is wrong: it rewrites the first "ffmpeg" anywhere in the path, so a
    perfectly normal install directory like `ffmpeg-9.0.1-full_build\\bin` turns
    into `ffprobe-9.0.1-full_build\\bin` and nothing is found. Only the
    filename may be substituted.
    """
    env = os.environ.get("PODHARVEST_FFPROBE")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return ""
    directory, name = os.path.split(ffmpeg)
    # Keep the original casing of the extension: "ffmpeg.EXE" -> "ffprobe.EXE".
    stem, ext = os.path.splitext(name)
    candidate = os.path.join(directory, stem.replace("ffmpeg", "ffprobe") + ext)
    return candidate if os.path.isfile(candidate) else ""


def probe(refresh: bool = False) -> Hardware:
    """Inspect the machine. Result is cached for the life of the process."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    total_ram, avail_ram = _ram()
    torch_gpus, has_torch, has_cuda = _torch_gpus()
    gpus = torch_gpus or _nvidia_gpus() or _apple_gpu()

    has_mlx = False
    if sys.platform == "darwin" and platform.machine() in {"arm64", "aarch64"}:
        try:
            import mlx.core  # type: ignore  # noqa: F401
            has_mlx = True
        except Exception:
            has_mlx = False

    ffmpeg = find_ffmpeg()
    hw = Hardware(
        os_name=platform.system(),
        os_version=platform.release(),
        arch=platform.machine(),
        cpu_name=_cpu_name(),
        physical_cores=_physical_cores(),
        logical_cores=os.cpu_count() or 0,
        ram_total_bytes=total_ram,
        ram_available_bytes=avail_ram or int(total_ram * 0.5),
        disk_free_bytes=shutil.disk_usage(os.getcwd()).free,
        gpus=gpus,
        has_torch=has_torch,
        has_cuda=has_cuda,
        has_mlx=has_mlx,
        has_ffmpeg=bool(ffmpeg),
        ffmpeg_path=ffmpeg,
        python_version=platform.python_version(),
    )

    if hw.accelerator == "cpu" and hw.logical_cores and hw.logical_cores < 4:
        hw.notes.append("Few CPU cores detected. Prefer a small model or expect slow transcription.")
    if hw.disk_free_gb < 5:
        hw.notes.append("Less than 5 GB of free disk space. Model downloads may fail.")
    if sys.platform == "darwin" and platform.machine() in {"arm64", "aarch64"} and not has_mlx:
        hw.notes.append("Apple Silicon detected. Installing the MLX backend gives the fastest local transcription.")
    if hw.best_gpu and hw.best_gpu.vendor == "nvidia" and not has_torch:
        hw.notes.append("An NVIDIA GPU is present but PyTorch is not installed. podharvest can install a CUDA build for you.")

    _CACHE = hw
    return hw


_CACHE: Hardware | None = None


# -- model recommendation ---------------------------------------------------

@dataclass
class ModelChoice:
    engine: str          # faster-whisper | parakeet | nemo-canary | vosk | moonshine | llama-cpp
    model: str
    min_ram_gb: float
    label: str                 # human-friendly menu entry
    kind: str = "asr"          # asr | enrichment
    requires_cuda: bool = False
    source: str = ""           # HF repo id, or a direct download URL
    filename: str = ""         # specific file to fetch from an HF repo (e.g. a .bin/.gguf)
    license: str = ""
    size_gb: float = 0.0       # approximate on-disk size once downloaded
    notes: str = ""

    # -- where it runs -------------------------------------------------
    location: str = "local"    # local | cloud
    provider: str = ""         # cloud only: openai | gemini | openrouter | ollama-cloud

    #: Rough real-time factor on a mid-range CPU - 17.0 means an hour of audio
    #: takes about 3.5 minutes. Used for the time estimates shown next to each
    #: model. `speed_measured` marks the figures that came from an actual
    #: `podharvest benchmark` run rather than an informed guess.
    speed_x: float = 0.0
    speed_measured: bool = False
    #: Cloud only: approximate USD per minute of audio, for the cost estimate.
    cost_per_audio_minute: float = 0.0
    #: Cloud only: the model can label speakers itself, with no separate
    #: diarization pass.
    speakers_built_in: bool = False
    #: Whether the engine returns per-segment times. Without them there are no
    #: chapter markers and no subtitle files - only a wall of text.
    provides_timestamps: bool = True

    @property
    def is_cloud(self) -> bool:
        return self.location == "cloud"

    def __str__(self) -> str:  # used directly as a wx.Choice label
        return self.label


# Ordered smallest/fastest -> largest/most-accurate. Kept as plain data so the
# CLI, GUI, acquisition and transcription layers all agree on one catalogue.
#
# ASR engines
# -----------
# faster-whisper  - CTranslate2 Whisper build; best all-round portable choice,
#                    runs well on CPU (int8) or any GPU (fp16).
# parakeet        - NVIDIA NeMo TDT models; fastest + most accurate English
#                    ASR available, but CUDA-only.
# nemo-canary     - NVIDIA NeMo Canary; multilingual (en/es/de/fr) with
#                    punctuation + translation, CUDA-only, heavier than Parakeet.
# vosk            - Kaldi-based, pure-CPU, tiny footprint, no GPU/AVX2 needed;
#                    the right fallback for very old or low-power machines.
# moonshine       - Useful Sensors' Moonshine; tiny, extremely fast on CPU,
#                    tuned for short-form speech (voice commands, clips) but
#                    works fine on podcast-length audio at a small accuracy cost.
WHISPER_CHOICES: list[ModelChoice] = [
    ModelChoice("faster-whisper", "tiny.en", 1.0, "Whisper tiny.en - fastest, lowest accuracy",
                source="Systran/faster-whisper-tiny.en", license="MIT", size_gb=0.1,
                speed_x=26.6, speed_measured=True),
    ModelChoice("faster-whisper", "base.en", 1.0, "Whisper base.en - fast, good for clear speech",
                source="Systran/faster-whisper-base.en", license="MIT", size_gb=0.15,
                speed_x=16.6, speed_measured=True),
    ModelChoice("faster-whisper", "small.en", 2.0, "Whisper small.en - balanced (recommended default)",
                source="Systran/faster-whisper-small.en", license="MIT", size_gb=0.5,
                speed_x=6.1, speed_measured=True),
    ModelChoice("faster-whisper", "distil-medium.en", 3.0, "Whisper distil-medium.en - accurate, still quick",
                source="Systran/faster-distil-whisper-medium.en", license="MIT", size_gb=1.5,
                speed_x=4.0, speed_measured=False),
    ModelChoice("faster-whisper", "medium.en", 5.0, "Whisper medium.en - high accuracy",
                source="Systran/faster-whisper-medium.en", license="MIT", size_gb=1.5,
                speed_x=2.5, speed_measured=False),
    ModelChoice("faster-whisper", "distil-large-v3", 4.0,
                "Whisper distil-large-v3 - near large-v3 accuracy, faster",
                source="Systran/faster-distil-whisper-large-v3", license="MIT", size_gb=1.5,
                speed_x=3.2, speed_measured=False),
    ModelChoice(
        "faster-whisper", "distil-large-v3.5", 4.0,
        "Distil-Whisper large v3.5 - the newest distillation, English only",
        source="distil-whisper/distil-large-v3.5-ct2", size_gb=1.5,
        license="MIT",
        notes="The successor to distil-large-v3, distilled from four times as "
              "much audio: measurably more accurate at the same speed and "
              "size. English only, like every distilled Whisper. Loads from "
              "podHarvest's own model store, so it works even though "
              "faster-whisper's built-in list has never heard of it."),
    ModelChoice("faster-whisper", "large-v3-turbo", 6.0,
                "Whisper large-v3-turbo - OpenAI's 2024 pruned large model, ~8x faster than large-v3",
                source="mobiuslabsgmbh/faster-whisper-large-v3-turbo", license="MIT", size_gb=1.6,
                notes="Best accuracy-per-second of any Whisper size; a strong alternative to small.en.",
                speed_x=5.0, speed_measured=False),
    ModelChoice("faster-whisper", "large-v3", 10.0, "Whisper large-v3 - best accuracy, slowest",
                source="Systran/faster-whisper-large-v3", license="MIT", size_gb=3.0,
                speed_x=1.2, speed_measured=False),
]
PARAKEET_CHOICES: list[ModelChoice] = [
    ModelChoice("parakeet", "parakeet-tdt-0.6b-v2", 3.0, "Parakeet TDT 0.6B - fast, NVIDIA GPU only (NeMo/PyTorch)",
                requires_cuda=True, source="nvidia/parakeet-tdt-0.6b-v2",
                license="CC-BY-4.0", size_gb=2.4,
                notes="English only. Best speed/accuracy ratio of any local ASR model on CUDA. "
                      "Needs the full NeMo/PyTorch stack - see parakeet-onnx for a lighter alternative.",
                speed_x=60.0, speed_measured=False),
    ModelChoice(
        "parakeet", "parakeet-tdt-0.6b-v3", 3.0,
        "NVIDIA Parakeet TDT 0.6B v3 - 25 languages, needs an NVIDIA GPU",
        kind="asr", requires_cuda=True, source="nvidia/parakeet-tdt-0.6b-v3",
        size_gb=2.4, license="CC-BY-4.0",
        notes="The multilingual successor to v2: the same size and speed, "
              "covering 25 European languages including Spanish, French and "
              "German, with automatic language detection. v2 remains the "
              "better pick for English-only work; this one is for a library "
              "that is not all in English."),
    ModelChoice("parakeet", "parakeet-tdt-1.1b", 5.0, "Parakeet TDT 1.1B - most accurate, NVIDIA GPU only (NeMo/PyTorch)",
                requires_cuda=True, source="nvidia/parakeet-tdt-1.1b",
                license="CC-BY-4.0", size_gb=4.4, notes="English only.",
                speed_x=40.0, speed_measured=False),
]
PARAKEET_ONNX_CHOICES: list[ModelChoice] = [
    ModelChoice("parakeet-onnx", "parakeet-tdt-0.6b-v2", 2.5,
                "Parakeet TDT 0.6B (ONNX) - same model, no PyTorch/NeMo required, runs on CPU",
                source="csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2",
                license="CC-BY-4.0", size_gb=2.4,
                notes="Runs via sherpa-onnx (k2-fsa) + onnxruntime only - a genuine PyTorch-free way "
                      "to run Parakeet on CPU (or GPU via onnxruntime-gpu). Slower than native CUDA "
                      "NeMo but far lighter to install and works without an NVIDIA GPU.",
                speed_x=17.2, speed_measured=True),
]
CANARY_CHOICES: list[ModelChoice] = [
    ModelChoice("nemo-canary", "canary-1b-flash", 6.0,
                "Canary 1B Flash - multilingual + punctuation, NVIDIA GPU only",
                requires_cuda=True, source="nvidia/canary-1b-flash",
                license="CC-BY-NC-4.0", size_gb=4.0,
                notes="English/Spanish/German/French with built-in punctuation and casing.",
                speed_x=30.0, speed_measured=False),
]
VOSK_CHOICES: list[ModelChoice] = [
    ModelChoice("vosk", "vosk-model-small-en-us-0.15", 0.5,
                "Vosk small (English) - tiny, pure CPU, works on any machine",
                source="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
                license="Apache-2.0", size_gb=0.04,
                notes="Lowest accuracy of the bunch, but needs no AVX2/GPU and starts instantly.",
                speed_x=20.0, speed_measured=True),
    ModelChoice("vosk", "vosk-model-en-us-0.22", 2.0,
                "Vosk standard (English) - CPU, better accuracy than the small model",
                source="https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
                license="Apache-2.0", size_gb=1.8,
                speed_x=12.0, speed_measured=False),
]
MOONSHINE_CHOICES: list[ModelChoice] = [
    ModelChoice("moonshine", "moonshine-tiny", 0.5,
                "Moonshine tiny - very fast CPU inference, short-form tuned",
                source="UsefulSensors/moonshine-tiny", license="MIT", size_gb=0.1,
                speed_x=40.0, speed_measured=False),
    ModelChoice("moonshine", "moonshine-base", 1.0,
                "Moonshine base - fast CPU inference, better accuracy",
                source="UsefulSensors/moonshine-base", license="MIT", size_gb=0.4,
                speed_x=25.0, speed_measured=False),
]

ASR_CATALOGUE: dict[str, list[ModelChoice]] = {
    "faster-whisper": WHISPER_CHOICES,
    "parakeet": PARAKEET_CHOICES,
    "parakeet-onnx": PARAKEET_ONNX_CHOICES,
    "nemo-canary": CANARY_CHOICES,
    "vosk": VOSK_CHOICES,
    "moonshine": MOONSHINE_CHOICES,
}

# Enrichment (optional, post-transcription) LLMs: punctuation/casing cleanup,
# summarization, chapter titling, action-item extraction. These run through
# llama.cpp-style GGUF inference so no GPU is required, though one helps.
# Megatron-LM itself is a training framework, not a deployable model - so
# "Megatron support" here means its distilled/deployable descendants
# (NVIDIA Nemotron) rather than Megatron-LM directly.
ENRICHMENT_CHOICES: list[ModelChoice] = [
    ModelChoice("llama-cpp", "phi-3.5-mini-instruct-q4", 4.0,
                "Phi-3.5 Mini Instruct (Q4_K_M) - small, fast, great at summarizing",
                kind="enrichment", source="bartowski/Phi-3.5-mini-instruct-GGUF",
                filename="Phi-3.5-mini-instruct-Q4_K_M.gguf", license="MIT", size_gb=2.4),
    ModelChoice("llama-cpp", "llama-3.2-3b-instruct-q4", 4.0,
                "Llama 3.2 3B Instruct (Q4_K_M) - solid general-purpose option",
                kind="enrichment", source="bartowski/Llama-3.2-3B-Instruct-GGUF",
                filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
                license="Llama 3.2 Community License", size_gb=2.0),
    ModelChoice("llama-cpp", "nemotron-mini-4b-instruct-q4", 5.0,
                "Nemotron-Mini 4B Instruct (Q4_K_M) - NVIDIA/Megatron-derived",
                kind="enrichment", source="bartowski/Nemotron-Mini-4B-Instruct-GGUF",
                filename="Nemotron-Mini-4B-Instruct-Q4_K_M.gguf",
                license="NVIDIA Open Model License", size_gb=2.6,
                notes="Deployable descendant of NVIDIA's Megatron-LM training stack."),
    ModelChoice("llama-cpp", "mistral-7b-instruct-q4", 8.0,
                "Mistral 7B Instruct (Q4_K_M) - most capable, needs more RAM",
                kind="enrichment", source="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
                filename="Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
                license="Apache-2.0", size_gb=4.4),
]


def available_models(hw: Hardware, app=None, *, include_cloud: bool = False) -> list[ModelChoice]:
    """Models this machine can run, optionally plus configured cloud models.

    Cloud models are left out unless asked for, so nothing that needs a network
    call and an API key ever turns up by accident in a local-only listing.
    """
    local = _local_models(hw)
    if not include_cloud or app is None:
        return local
    from podharvest.cloud import available_cloud_models
    return local + available_cloud_models(app, kind="asr")


def _local_models(hw: Hardware) -> list[ModelChoice]:
    """All ASR models that should comfortably fit the detected hardware."""
    budget = max(hw.usable_accel_memory_gb, 1.0)
    choices = [c for c in VOSK_CHOICES + MOONSHINE_CHOICES if c.min_ram_gb <= budget]
    choices += [c for c in WHISPER_CHOICES if c.min_ram_gb <= budget]
    ram_budget = max(hw.ram_available_bytes / GB, 1.0)
    choices += [c for c in PARAKEET_ONNX_CHOICES if c.min_ram_gb <= ram_budget]
    if hw.has_cuda:
        choices += [c for c in PARAKEET_CHOICES + CANARY_CHOICES if c.min_ram_gb <= budget]
    return choices or [VOSK_CHOICES[0]]


def recommend_model(hw: Hardware) -> ModelChoice:
    """The single best default: prefer Parakeet on CUDA, else the largest
    Whisper distil/standard model that fits comfortably in the budget."""
    choices = available_models(hw)
    if hw.has_cuda:
        parakeet = [c for c in choices if c.engine == "parakeet"]
        if parakeet:
            return parakeet[-1]
    whisper = [c for c in choices if c.engine == "faster-whisper"]
    return whisper[-1] if whisper else choices[-1]


def available_enrichment_models(hw: Hardware) -> list[ModelChoice]:
    """Optional post-processing LLMs that fit in the detected RAM budget.

    These run on CPU via llama.cpp, so we size against total system RAM
    (not just the GPU/accelerator budget) with headroom for the OS and the
    ASR model that may already be resident.
    """
    budget = max(hw.ram_available_bytes / GB, hw.ram_gb * 0.5, 2.0)
    return [c for c in ENRICHMENT_CHOICES if c.min_ram_gb <= budget]


def recommend_enrichment_model(hw: Hardware) -> ModelChoice | None:
    """Best default enrichment model, or None if RAM is too tight to bother."""
    choices = available_enrichment_models(hw)
    return choices[len(choices) // 2] if choices else None

