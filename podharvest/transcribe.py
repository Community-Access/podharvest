"""On-device speech-to-text engines, transcript formatting, and diarization.

Two engines are implemented end-to-end:

- `FasterWhisperEngine` - CTranslate2 Whisper, CPU (int8) or GPU (float16).
  Works everywhere; this is the default.
- `ParakeetEngine` - NVIDIA NeMo TDT models. Requires a CUDA GPU and the
  heavy `nemo_toolkit[asr]` + `torch` stack; raises a clear `HarvestError`
  naming exactly what's missing when it can't run, rather than pretending
  to work on unsupported hardware.

Diarization (`identify_speakers=True`) is optional and uses `pyannote.audio`
when installed; if it isn't (or no Hugging Face token is configured for the
gated pyannote models), transcripts are produced without speaker labels and
a clear note is logged instead of failing the whole transcription.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from podharvest.appspace import AppSpace
from podharvest.hardware import ModelChoice
from podharvest.progress import ProgressReporter
from podharvest.util import LOG, HarvestError, spoken_duration


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[tuple[float, float, str]] = field(default_factory=list)


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str
    engine: str
    model: str
    audio_seconds: float
    transcribe_seconds: float

    @property
    def speed_x_realtime(self) -> float:
        return round(self.audio_seconds / self.transcribe_seconds, 2) if self.transcribe_seconds else 0.0

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())


class Engine(Protocol):
    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                   on_progress: Callable[[float], None] | None = None) -> TranscriptResult: ...


def _pcm16_to_float32(raw: bytes):
    """Turn raw little-endian 16-bit PCM into normalised float samples.

    An hour of 16 kHz audio is ~57 million samples, and building a Python list
    of that many floats costs both tens of seconds and well over a gigabyte of
    memory. NumPy does the same work in one vectorised pass, so it is used
    whenever it is importable (every ASR engine here already pulls it in), with
    the pure-Python path kept as a fallback.
    """
    try:
        import numpy as np
    except ImportError:
        import array
        samples = array.array("h")
        samples.frombytes(raw)
        return [s / 32768.0 for s in samples]
    usable = len(raw) - (len(raw) % 2)
    return np.frombuffer(raw[:usable], dtype="<i2").astype("float32") / 32768.0


def _probe_duration_seconds(audio_path: Path) -> float:
    """Best-effort audio duration without extra dependencies (falls back to 0)."""
    try:
        import wave
        with wave.open(str(audio_path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        pass
    try:
        import subprocess

        from podharvest.hardware import find_ffprobe
        ffprobe = find_ffprobe()
        if not ffprobe:
            return 0.0
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except Exception:
        pass
    return 0.0


class FasterWhisperEngine:
    def __init__(self, app: AppSpace, choice: ModelChoice, device: str = "cpu",
                compute_type: str = "int8") -> None:
        self.app = app
        self.choice = choice
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise HarvestError(
                "faster-whisper is not installed. Run 'podharvest hardware' once "
                "(or let a fetch/transcribe job run) to install it automatically."
            ) from exc
        # One downloader, one location. `acquire` fetches the CTranslate2
        # snapshot into whisper/<model>/ and the engine loads that directory.
        # These used to be two different layouts: the Download button filled
        # whisper/<model>/ while WhisperModel(name, download_root=...) looked
        # for the Hugging Face cache layout (models--Systran--...) -- so a
        # freshly downloaded model was downloaded a second time on first use,
        # and a model the engine had fetched read as "not downloaded" in the
        # window forever. Loading by directory also frees the catalogue from
        # faster-whisper's built-in name registry, which is what lets it offer
        # converted models the registry has never heard of.
        from podharvest.acquire import acquire_asr_model

        acquired = acquire_asr_model(self.app, self.choice)
        LOG.info("Loading the speech model '%s' (%s, %s)...", self.choice.model, self.device, self.compute_type)
        t0 = time.monotonic()
        self._model = WhisperModel(
            str(acquired.model_dir), device=self.device, compute_type=self.compute_type,
        )
        LOG.info("Speech model ready (took %.1f seconds).", time.monotonic() - t0)
        return self._model

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                  on_progress: Callable[[float], None] | None = None) -> TranscriptResult:
        model = self._load()
        duration = _probe_duration_seconds(audio_path)
        t0 = time.monotonic()
        segments_iter, info = model.transcribe(
            str(audio_path), beam_size=5, word_timestamps=include_word_timestamps, vad_filter=True)

        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            words = [(w.start, w.end, w.word.strip()) for w in (seg.words or [])] if include_word_timestamps else []
            segments.append(TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip(), words=words))
            if on_progress and duration:
                on_progress(min(100.0, seg.end / duration * 100))
        elapsed = time.monotonic() - t0
        return TranscriptResult(
            segments=segments, language=getattr(info, "language", "en") or "en",
            engine="faster-whisper", model=self.choice.model,
            audio_seconds=duration or (segments[-1].end if segments else 0.0),
            transcribe_seconds=elapsed,
        )


class ParakeetEngine:
    """NVIDIA NeMo Parakeet/Canary. CUDA-only; installs `nemo_toolkit[asr]`."""

    def __init__(self, app: AppSpace, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import torch  # type: ignore
        except ImportError as exc:
            raise HarvestError("PyTorch is required for the Parakeet/Canary (NeMo) engine.") from exc
        if not torch.cuda.is_available():
            raise HarvestError(
                f"Engine '{self.choice.engine}' requires an NVIDIA CUDA GPU, which was not detected "
                "on this machine. Choose a faster-whisper/Vosk/Moonshine model instead, or run "
                "'podharvest hardware' to see what this machine actually supports.")
        try:
            import nemo.collections.asr as nemo_asr  # type: ignore
        except ImportError as exc:
            raise HarvestError(
                "nemo_toolkit[asr] is not installed. It is a large (multi-GB) dependency; "
                "install it manually with 'pip install nemo_toolkit[asr]' if you want to use "
                f"{self.choice.engine}."
            ) from exc
        # The snapshot `acquire` fetched carries the .nemo checkpoint, and
        # restore_from loads it directly. from_pretrained is the fallback for
        # a repo that ships no .nemo -- but going through it first meant NeMo
        # re-downloaded into its own cache and the Download button's gigabytes
        # were never opened by anything.
        from podharvest.acquire import acquire_asr_model

        acquired = acquire_asr_model(self.app, self.choice)
        checkpoint = next(iter(acquired.model_dir.glob("*.nemo")), None)
        LOG.info("Loading the speech model '%s'...", self.choice.model)
        t0 = time.monotonic()
        if checkpoint is not None:
            self._model = nemo_asr.models.ASRModel.restore_from(str(checkpoint))
        else:
            self._model = nemo_asr.models.ASRModel.from_pretrained(model_name=self.choice.source)
        LOG.info("Speech model ready (took %.1f seconds).", time.monotonic() - t0)
        return self._model

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                  on_progress: Callable[[float], None] | None = None) -> TranscriptResult:
        model = self._load()
        duration = _probe_duration_seconds(audio_path)
        t0 = time.monotonic()
        output = model.transcribe([str(audio_path)], timestamps=include_word_timestamps)
        elapsed = time.monotonic() - t0
        if on_progress:
            on_progress(100.0)

        segments: list[TranscriptSegment] = []
        result = output[0] if output else None
        text = getattr(result, "text", None) or (result if isinstance(result, str) else "") or ""
        seg_stamps = getattr(getattr(result, "timestamp", None), "get", lambda *_: None)("segment") \
            if include_word_timestamps and result is not None else None
        if seg_stamps:
            for s in seg_stamps:
                segments.append(TranscriptSegment(start=s.get("start", 0.0), end=s.get("end", 0.0),
                                                  text=s.get("segment", "").strip()))
        else:
            segments.append(TranscriptSegment(start=0.0, end=duration, text=text.strip()))

        return TranscriptResult(
            segments=segments, language="en", engine=self.choice.engine, model=self.choice.model,
            audio_seconds=duration, transcribe_seconds=elapsed,
        )


class SherpaOnnxParakeetEngine:
    """Parakeet TDT via k2-fsa's `sherpa-onnx` - the same NeMo checkpoint,
    exported to ONNX, running on plain `onnxruntime`. No PyTorch, no NeMo,
    no CUDA required; works on CPU (or GPU via onnxruntime-gpu).

    Sherpa-onnx's offline recognizer is designed for single utterances, not
    hour-long files, so long audio is split into fixed windows (with a small
    overlap trimmed from each boundary) and recognized one window at a time.
    """

    # Measured on bench/ep1-3 (15 minutes) against both a human reference and a
    # whole-file no-boundary decode. 30s/no-overlap had the lowest error against
    # the human transcript (2.02%) and was the fastest of the low-error settings.
    # Overlap is 0 because a window that re-reads audio costs time and, even with
    # the duplicate tokens trimmed, scored worse than not overlapping at all.
    CHUNK_SECONDS = 30.0
    OVERLAP_SECONDS = 0.0
    SAMPLE_RATE = 16000
    #: A window shorter than this yields no feature frames and the model errors
    #: out on the empty input. One frame is 25 ms; this leaves generous margin.
    MIN_WINDOW_SECONDS = 0.2

    def __init__(self, app: AppSpace, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice
        self._recognizer = None

    def _model_dir(self) -> Path:
        return self.app.parakeet_models_dir / "onnx" / self.choice.model

    @staticmethod
    def _component(model_dir: Path, stem: str) -> Path:
        """The encoder/decoder/joiner file, whichever precision shipped.

        The v2 export names its files plainly (`encoder.onnx`); the v3 export
        is int8-quantised and says so in the name (`encoder.int8.onnx`).
        Same graph either way -- sherpa-onnx does not care what the file is
        called -- so the loader takes the one that exists rather than
        insisting on a spelling.
        """
        plain = model_dir / f"{stem}.onnx"
        return plain if plain.exists() else model_dir / f"{stem}.int8.onnx"

    def _load(self):
        if self._recognizer is not None:
            return self._recognizer
        try:
            import sherpa_onnx  # type: ignore
        except ImportError as exc:
            raise HarvestError(
                "sherpa-onnx is not installed. It has no PyTorch/CUDA dependency; install it with "
                "'pip install sherpa-onnx'."
            ) from exc

        model_dir = self._model_dir()
        required = [self._component(model_dir, stem)
                    for stem in ("encoder", "decoder", "joiner")]
        required.append(model_dir / "tokens.txt")
        if not all(path.exists() for path in required):
            try:
                from huggingface_hub import snapshot_download  # type: ignore
            except ImportError as exc:
                raise HarvestError(
                    "'huggingface_hub' is required to download the sherpa-onnx Parakeet files."
                ) from exc
            LOG.info("Downloading sherpa-onnx Parakeet files from %s (about %.1f GB)...",
                     self.choice.source, self.choice.size_gb)
            snapshot_download(
                repo_id=self.choice.source, local_dir=str(model_dir), local_dir_use_symlinks=False,
                allow_patterns=["*.onnx", "encoder.weights", "tokens.txt"],
            )

        import os
        LOG.info("Loading the speech model '%s'...", self.choice.model)
        t0 = time.monotonic()
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(self._component(model_dir, "encoder")),
            decoder=str(self._component(model_dir, "decoder")),
            joiner=str(self._component(model_dir, "joiner")),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=min(4, os.cpu_count() or 4),
            sample_rate=self.SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
        )
        LOG.info("Speech model ready (took %.1f seconds).", time.monotonic() - t0)
        return self._recognizer

    def _read_pcm16k(self, audio_path: Path):
        """Decode any audio file to 16kHz mono float32 PCM via ffmpeg."""
        import subprocess

        from podharvest.hardware import find_ffmpeg
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise HarvestError("ffmpeg is required to decode audio for the sherpa-onnx engine.")
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1",
             "-ar", str(self.SAMPLE_RATE), "-"],
            capture_output=True, check=True,
        )
        return _pcm16_to_float32(proc.stdout)

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                  on_progress: Callable[[float], None] | None = None) -> TranscriptResult:
        recognizer = self._load()
        samples = self._read_pcm16k(audio_path)
        duration = len(samples) / self.SAMPLE_RATE
        chunk_n = int(self.CHUNK_SECONDS * self.SAMPLE_RATE)
        overlap_n = int(self.OVERLAP_SECONDS * self.SAMPLE_RATE)

        stride_n = max(1, chunk_n - overlap_n)
        min_n = int(self.MIN_WINDOW_SECONDS * self.SAMPLE_RATE)

        segments: list[TranscriptSegment] = []
        t0 = time.monotonic()
        pos = 0
        first = True
        while pos < len(samples):
            window = samples[pos:pos + chunk_n]
            # Anything shorter than a feature frame produces no frames at all,
            # and the model's convolution stack rejects an empty input outright.
            # A trailing sliver is silence-length audio; dropping it loses
            # nothing and is the difference between finishing and crashing.
            if len(window) < min_n:
                break
            stream = recognizer.create_stream()
            stream.accept_waveform(self.SAMPLE_RATE, window)
            recognizer.decode_stream(stream)

            # Each window re-reads the last `overlap` seconds of the previous
            # one so the model has context across the join. Those seconds were
            # already transcribed, so their tokens are dropped here - keeping
            # them duplicates a word or two at every single boundary.
            skip_before = 0.0 if first else self.OVERLAP_SECONDS
            tokens = list(getattr(stream.result, "tokens", None) or [])
            stamps = list(getattr(stream.result, "timestamps", None) or [])
            if skip_before and tokens and len(stamps) == len(tokens):
                # strict=True: the lengths are checked equal just above, so a
                # mismatch here would mean the recognizer changed its contract
                # and should fail loudly rather than silently drop tokens.
                text = "".join(tok for tok, ts in zip(tokens, stamps, strict=True)
                               if ts >= skip_before).strip()
            else:
                text = stream.result.text.strip()

            if text:
                segments.append(TranscriptSegment(
                    start=pos / self.SAMPLE_RATE + skip_before,
                    end=(pos + len(window)) / self.SAMPLE_RATE, text=text))
            first = False
            pos += stride_n
            if on_progress and duration:
                on_progress(min(100.0, pos / len(samples) * 100))
        elapsed = time.monotonic() - t0

        return TranscriptResult(
            segments=segments, language="en", engine=self.choice.engine, model=self.choice.model,
            audio_seconds=duration, transcribe_seconds=elapsed,
        )


class VoskEngine:
    """Kaldi-based Vosk. Pure CPU, no AVX2 requirement, tiny footprint.

    This is the fallback for machines too old or too small for Whisper: the
    small English model is about 40 MB and starts instantly. Accuracy is the
    lowest of the engines on offer, which is the trade being made.

    Vosk consumes 16 kHz mono PCM and emits one JSON result per detected
    utterance, with per-word start/end times, so segments and word timestamps
    both come straight from the recognizer.
    """

    SAMPLE_RATE = 16000
    _READ_SAMPLES = 8000       # 0.5s of audio per AcceptWaveform call

    def __init__(self, app: AppSpace, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import vosk  # type: ignore
        except ImportError as exc:
            raise HarvestError(
                "vosk is not installed. It is a small, pure-CPU package; install it with "
                "'pip install vosk', or let podharvest install it on demand."
            ) from exc

        from podharvest.acquire import acquire_asr_model
        result = acquire_asr_model(self.app, self.choice)

        # Vosk ships a zip with a single top-level folder. Depending on the
        # archive that folder may be the model directory itself or sit one
        # level inside it, so accept either shape rather than guessing.
        model_dir = result.model_dir
        if not (model_dir / "am").exists() and not (model_dir / "conf").exists():
            nested = [d for d in model_dir.iterdir() if d.is_dir()] if model_dir.exists() else []
            if len(nested) == 1:
                model_dir = nested[0]

        vosk.SetLogLevel(-1)     # Vosk logs very noisily to stderr by default
        LOG.info("Loading the speech model '%s'...", self.choice.model)
        t0 = time.monotonic()
        self._model = vosk.Model(str(model_dir))
        LOG.info("Speech model ready (took %.1f seconds).", time.monotonic() - t0)
        return self._model

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                   on_progress: Callable[[float], None] | None = None) -> TranscriptResult:

        import vosk  # type: ignore

        model = self._load()
        samples = _read_pcm16k_generic(audio_path, self.SAMPLE_RATE)
        duration = len(samples) / self.SAMPLE_RATE

        recognizer = vosk.KaldiRecognizer(model, float(self.SAMPLE_RATE))
        recognizer.SetWords(True)

        segments: list[TranscriptSegment] = []
        t0 = time.monotonic()
        for pos in range(0, len(samples), self._READ_SAMPLES):
            window = samples[pos:pos + self._READ_SAMPLES]
            if len(window) == 0:
                break
            if recognizer.AcceptWaveform(_to_pcm16_bytes(window)):
                _append_vosk_result(segments, recognizer.Result(), include_word_timestamps)
            if on_progress and len(samples):
                on_progress(min(100.0, (pos + len(window)) / len(samples) * 100))
        _append_vosk_result(segments, recognizer.FinalResult(), include_word_timestamps)
        elapsed = time.monotonic() - t0

        return TranscriptResult(
            segments=segments, language="en", engine="vosk", model=self.choice.model,
            audio_seconds=duration, transcribe_seconds=elapsed,
        )


def _append_vosk_result(segments: list, raw: str, include_words: bool) -> None:
    """Turn one Vosk JSON result into a TranscriptSegment, if it has text."""
    import json

    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return
    text = (data.get("text") or "").strip()
    if not text:
        return
    words = [(w["start"], w["end"], w["word"])
             for w in data.get("result", []) if "start" in w and "end" in w]
    start = words[0][0] if words else (segments[-1].end if segments else 0.0)
    end = words[-1][1] if words else start
    segments.append(TranscriptSegment(start=start, end=end, text=text,
                                      words=words if include_words else []))


def _to_pcm16_bytes(samples) -> bytes:
    """Float PCM in [-1, 1] back to the signed 16-bit bytes Vosk expects."""
    try:
        import numpy as np
    except ImportError:
        import array
        clipped = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
        return clipped.tobytes()
    arr = np.asarray(samples, dtype="float32")
    return (np.clip(arr, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class MoonshineEngine:
    """Useful Sensors' Moonshine, via the ONNX runtime build.

    The `useful-moonshine-onnx` distribution runs on plain `onnxruntime` with
    no PyTorch, Keras or TensorFlow, which is what makes Moonshine worth
    offering here: it is the fastest CPU option in the catalogue.

    Moonshine is trained on short utterances and degrades on long input, so
    podcast-length audio is decoded in overlapping windows and stitched back
    together, the same approach the sherpa-onnx engine takes.
    """

    SAMPLE_RATE = 16000
    CHUNK_SECONDS = 20.0
    OVERLAP_SECONDS = 0.5

    #: Catalogue model name -> the repo id moonshine-onnx expects.
    _MODEL_NAMES = {
        "moonshine-tiny": "moonshine/tiny",
        "moonshine-base": "moonshine/base",
    }

    def __init__(self, app: AppSpace, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice
        self._model = None
        self._tokenizer = None

    def _load(self):
        if self._model is not None:
            return self._model, self._tokenizer
        try:
            from moonshine_onnx import MoonshineOnnxModel, load_tokenizer  # type: ignore
        except ImportError as exc:
            raise HarvestError(
                "moonshine-onnx is not installed. Install it with "
                "'pip install useful-moonshine-onnx', or let podharvest install it on demand."
            ) from exc

        name = self._MODEL_NAMES.get(self.choice.model)
        if name is None:
            raise HarvestError(f"Unknown Moonshine model {self.choice.model!r}.")

        # `acquire` puts the ONNX pair where the download button, the doctor
        # and the readiness line all look; models_dir points the engine at
        # exactly those files. model_name is still passed because the engine
        # sizes its decoder limits from it.
        from podharvest.acquire import acquire_asr_model, moonshine_onnx_dir

        acquired = acquire_asr_model(self.app, self.choice)
        onnx_dir = moonshine_onnx_dir(acquired.model_dir, self.choice.model)
        LOG.info("Loading the speech model '%s'...", self.choice.model)
        t0 = time.monotonic()
        self._model = MoonshineOnnxModel(models_dir=str(onnx_dir), model_name=name)
        self._tokenizer = load_tokenizer()
        LOG.info("Speech model ready (took %.1f seconds).", time.monotonic() - t0)
        return self._model, self._tokenizer

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                   on_progress: Callable[[float], None] | None = None) -> TranscriptResult:
        try:
            import numpy as np  # type: ignore
        except ImportError as exc:
            raise HarvestError("numpy is required by the Moonshine engine.") from exc

        model, tokenizer = self._load()
        samples = _read_pcm16k_generic(audio_path, self.SAMPLE_RATE)
        duration = len(samples) / self.SAMPLE_RATE
        audio = np.asarray(samples, dtype=np.float32)

        chunk_n = int(self.CHUNK_SECONDS * self.SAMPLE_RATE)
        step_n = max(1, chunk_n - int(self.OVERLAP_SECONDS * self.SAMPLE_RATE))

        segments: list[TranscriptSegment] = []
        t0 = time.monotonic()
        pos = 0
        while pos < len(audio):
            window = audio[pos:pos + chunk_n]
            if window.size == 0:
                break
            tokens = model.generate(window[np.newaxis, :])
            text = tokenizer.decode_batch(tokens)[0].strip()
            if text:
                segments.append(TranscriptSegment(
                    start=pos / self.SAMPLE_RATE,
                    end=(pos + window.size) / self.SAMPLE_RATE,
                    text=text))
            pos += step_n
            if on_progress:
                on_progress(min(100.0, pos / max(1, len(audio)) * 100))
        elapsed = time.monotonic() - t0

        if include_word_timestamps:
            # Moonshine returns text only. Saying so once is better than
            # emitting per-line timestamps that imply word-level precision.
            LOG.info("Moonshine does not produce word-level timestamps; "
                     "transcript timings are per decoded window.")

        return TranscriptResult(
            segments=segments, language="en", engine="moonshine", model=self.choice.model,
            audio_seconds=duration, transcribe_seconds=elapsed,
        )


# One engine is kept alive between runs so that starting a second harvest does
# not pay the model load again. Only the most recent configuration is held: ASR
# models run to several gigabytes, and keeping every engine anyone selected
# during a session would accumulate all of them.
_ENGINE_LOCK = threading.Lock()
_ENGINE_CACHE: dict[tuple, Engine] = {}


def build_engine(app: AppSpace, choice: ModelChoice, *, device: str = "cpu",
                 compute_type: str = "int8", reuse: bool = True) -> Engine:
    """Build the engine for `choice`, reusing the last one when it matches.

    `reuse=False` forces a fresh engine, which the benchmark needs: it times
    model load as part of the comparison and a warm cache would flatter
    whichever engine happened to run second.
    """
    key = (choice.engine, choice.model, device, compute_type)
    if reuse:
        with _ENGINE_LOCK:
            cached = _ENGINE_CACHE.get(key)
            if cached is not None:
                LOG.info("Reusing the speech model already in memory.")
                return cached

    engine = _make_engine(app, choice, device=device, compute_type=compute_type)
    if reuse:
        with _ENGINE_LOCK:
            _ENGINE_CACHE.clear()      # hold one engine, not one per model tried
            _ENGINE_CACHE[key] = engine
    return engine


def release_engines() -> None:
    """Drop the cached engine and its model from memory."""
    with _ENGINE_LOCK:
        _ENGINE_CACHE.clear()


def _make_engine(app: AppSpace, choice: ModelChoice, *, device: str = "cpu",
                 compute_type: str = "int8") -> Engine:
    if choice.engine == "faster-whisper":
        return FasterWhisperEngine(app, choice, device=device, compute_type=compute_type)
    if choice.engine in {"parakeet", "nemo-canary"}:
        return ParakeetEngine(app, choice)
    if choice.engine == "parakeet-onnx":
        return SherpaOnnxParakeetEngine(app, choice)
    if choice.engine == "vosk":
        return VoskEngine(app, choice)
    if choice.engine == "moonshine":
        return MoonshineEngine(app, choice)
    raise HarvestError(
        f"Engine '{choice.engine}' is not implemented. Run 'podharvest hardware' "
        "to see the engines available on this machine.")


# -- diarization -------------------------------------------------------------

DIARIZATION_BACKENDS = ("pyannote", "sherpa-onnx", "nemo-msdd")

_SHERPA_SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
_SHERPA_EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B.onnx"
)


def _diarize_pyannote(audio_path: Path, hf_token: str | None) -> list[tuple[float, float, str]] | None:
    try:
        from pyannote.audio import Pipeline  # type: ignore
    except ImportError:
        LOG.info("Speaker identification requested but 'pyannote.audio' is not installed; "
                "producing the transcript without speaker labels.")
        return None
    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
    except Exception as exc:
        LOG.warning("Could not load the diarization model (%s). A Hugging Face token with access to "
                   "pyannote/speaker-diarization-3.1 is required. Continuing without speaker labels.", exc)
        return None
    diarization = pipeline(str(audio_path))
    return [(turn.start, turn.end, speaker) for turn, _, speaker in diarization.itertracks(yield_label=True)]


def _sherpa_diarization_dir(app: AppSpace) -> Path:
    return app.diarization_models_dir / "sherpa-onnx"


def _ensure_sherpa_diarization_models(app: AppSpace) -> tuple[Path, Path]:
    """Download the pyannote segmentation + WeSpeaker English embedding
    models sherpa-onnx needs, if not already present. Both come from
    k2-fsa's GitHub releases (not Hugging Face), so we fetch them directly
    via `podharvest.net` rather than `huggingface_hub`."""
    import tarfile

    base = _sherpa_diarization_dir(app)
    seg_dir = base / "sherpa-onnx-pyannote-segmentation-3-0"
    seg_model = seg_dir / "model.onnx"
    emb_model = base / "wespeaker_en_voxceleb_CAM++.onnx"

    if not seg_model.exists():
        base.mkdir(parents=True, exist_ok=True)
        archive = base / "segmentation.tar.bz2"
        LOG.info("Downloading speaker segmentation model (sherpa-onnx-pyannote-segmentation-3-0)...")
        from podharvest.net import HttpClient as _HttpClient
        _download_via_stream(_HttpClient(), _SHERPA_SEGMENTATION_URL, archive)
        with tarfile.open(archive) as tf:
            tf.extractall(base)
        archive.unlink(missing_ok=True)
        if not seg_model.exists():
            raise HarvestError(f"Segmentation model archive did not contain {seg_model.name}.")

    if not emb_model.exists():
        from podharvest.net import HttpClient as _HttpClient
        LOG.info("Downloading speaker embedding model (wespeaker_en_voxceleb_CAM++)...")
        _download_via_stream(_HttpClient(), _SHERPA_EMBEDDING_URL, emb_model)

    return seg_model, emb_model


def _download_via_stream(client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    reporter = ProgressReporter(f"Downloading {dest.name}", unit="B")
    with dest.open("wb") as fh:
        written, headers, _ = client.stream(url, fh, on_chunk=reporter.update)
        total = headers.get("content-length")
        if total and total.isdigit():
            reporter.set_total(int(total))
    reporter.close()


def _diarize_sherpa_onnx(app: AppSpace, audio_path: Path,
                         num_speakers: int = -1, cluster_threshold: float = 0.5,
                         ) -> list[tuple[float, float, str]] | None:
    """PyTorch-free diarization via sherpa-onnx (pyannote segmentation model +
    WeSpeaker English embeddings + clustering). Downloads ~120MB on first use."""
    try:
        import sherpa_onnx  # type: ignore
    except ImportError:
        LOG.info("Speaker identification requested but 'sherpa-onnx' is not installed; "
                "producing the transcript without speaker labels.")
        return None
    try:
        seg_model, emb_model = _ensure_sherpa_diarization_models(app)
    except HarvestError as exc:
        LOG.warning("Could not fetch sherpa-onnx diarization models (%s); "
                   "producing the transcript without speaker labels.", exc)
        return None

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(seg_model), window_shift_ratio=0.1),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model)),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers, threshold=cluster_threshold),
        min_duration_on=0.3, min_duration_off=0.5,
    )
    if not config.validate():
        LOG.warning("sherpa-onnx diarization config failed validation; "
                   "producing the transcript without speaker labels.")
        return None

    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    samples = _read_pcm16k_generic(audio_path, diarizer.sample_rate)
    result = diarizer.process(samples).sort_by_start_time()
    return [(seg.start, seg.end, f"speaker_{seg.speaker:02d}") for seg in result]


def _read_pcm16k_generic(audio_path: Path, sample_rate: int):
    """Decode any audio file to mono float32 PCM at `sample_rate` via ffmpeg."""
    import subprocess

    from podharvest.hardware import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise HarvestError(
            "FFmpeg is required to decode audio for this engine and was not "
            "found. Help > Media tools says where podHarvest looked.")
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1",
         "-ar", str(sample_rate), "-"],
        capture_output=True, check=True,
    )
    return _pcm16_to_float32(proc.stdout)


def _diarize_nemo_msdd(audio_path: Path) -> list[tuple[float, float, str]] | None:
    """NVIDIA NeMo's Multi-Scale Diarization Decoder (MSDD). Requires the
    full nemo_toolkit[asr]+PyTorch stack (the same heavy dependency chain as
    the Parakeet/Canary ASR engines); prefer the 'sherpa-onnx' backend if you
    don't already have NeMo installed for another reason."""
    try:
        import torch  # type: ignore  # noqa: F401
        from nemo.collections.asr.models import ClusteringDiarizer  # type: ignore
    except ImportError as exc:
        LOG.info("Speaker identification via NeMo MSDD requires 'nemo_toolkit[asr]' and PyTorch, "
                "which are not installed (%s); producing the transcript without speaker labels.", exc)
        return None
    try:
        from omegaconf import OmegaConf  # type: ignore
    except ImportError:
        LOG.info("NeMo MSDD diarization also requires 'omegaconf'; "
                "producing the transcript without speaker labels.")
        return None

    # NeMo's diarizer is driven by a YAML/OmegaConf config naming an audio
    # manifest rather than accepting a file path directly. This mirrors the
    # standard NeMo offline-diarization inference recipe.
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({
            "audio_filepath": str(audio_path), "offset": 0, "duration": None,
            "label": "infer", "text": "-", "num_speakers": None, "rttm_filepath": None,
        }) + "\n", encoding="utf-8")

        cfg = OmegaConf.create({
            "diarizer": {
                "manifest_filepath": str(manifest),
                "out_dir": str(tmp_path),
                "oracle_vad": False,
                "collar": 0.25,
                "ignore_overlap": True,
                "vad": {"model_path": "vad_multilingual_marblenet"},
                "speaker_embeddings": {"model_path": "titanet_large"},
                "msdd_model": {"model_path": "diar_msdd_telephonic"},
            }
        })
        diarizer = ClusteringDiarizer(cfg=cfg)
        diarizer.diarize()

        rttm_path = tmp_path / "pred_rttms" / f"{audio_path.stem}.rttm"
        if not rttm_path.exists():
            LOG.warning("NeMo MSDD produced no RTTM output; continuing without speaker labels.")
            return None
        turns: list[tuple[float, float, str]] = []
        for line in rttm_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 8 and parts[0] == "SPEAKER":
                start, dur, speaker = float(parts[3]), float(parts[4]), parts[7]
                turns.append((start, start + dur, speaker))
        return turns


def diarize(audio_path: Path, *, app: AppSpace | None = None, backend: str = "pyannote",
           hf_token: str | None = None, num_speakers: int = -1) -> list[tuple[float, float, str]] | None:
    """Return [(start, end, speaker_label), ...] or None if unavailable.

    `backend` selects the diarization engine:
      - "pyannote"   - the default; needs `pyannote.audio` + a HF token with
                       access to the gated pyannote model.
      - "sherpa-onnx" - PyTorch-free; needs only `sherpa-onnx` (already used
                       for Parakeet-ONNX) plus ~120MB of segmentation/
                       embedding models downloaded on first use.
      - "nemo-msdd"  - NVIDIA's MSDD diarizer; needs the full
                       `nemo_toolkit[asr]` + PyTorch stack.
    """
    if backend == "sherpa-onnx":
        if app is None:
            raise HarvestError("The 'sherpa-onnx' diarization backend requires an AppSpace.")
        return _diarize_sherpa_onnx(app, audio_path, num_speakers=num_speakers)
    if backend == "nemo-msdd":
        return _diarize_nemo_msdd(audio_path)
    return _diarize_pyannote(audio_path, hf_token)


def apply_speakers(result: TranscriptResult, turns: list[tuple[float, float, str]] | None) -> None:
    if not turns:
        return
    for seg in result.segments:
        mid = (seg.start + seg.end) / 2
        for start, end, speaker in turns:
            if start <= mid <= end:
                seg.speaker = speaker
                break


# -- formatting ---------------------------------------------------------------

TIMESTAMP_STYLES = ("bracket", "paren", "none")     # [00:00:00] | (00:00:00) | no timestamp
SPEAKER_STYLES = ("bold", "plain", "inline", "none")  # **A:** text | A: text | (A) text | no label


@dataclass
class FormatOptions:
    """Every knob for how a transcript is laid out, shared by all four
    output formats (Markdown/text always honor all fields; SRT/VTT ignore
    `paragraph_mode` and `max_line_chars`, which don't apply to caption
    files, but do honor timestamp/speaker styling)."""

    include_timestamps: bool = True
    timestamp_style: str = "bracket"      # see TIMESTAMP_STYLES
    include_speakers: bool = False
    speaker_style: str = "bold"           # see SPEAKER_STYLES
    paragraph_mode: bool = False           # merge consecutive same-speaker segments into one paragraph
    max_line_chars: int | None = None  # wrap plain-text output at this width; None = no wrapping
    include_boilerplate: bool = True       # keep sponsor/disclaimer-style filler segments verbatim

    def __post_init__(self) -> None:
        if self.timestamp_style not in TIMESTAMP_STYLES:
            self.timestamp_style = "bracket"
        if self.speaker_style not in SPEAKER_STYLES:
            self.speaker_style = "bold"


def _ts(seconds: float) -> str:
    h, rem = divmod(max(0.0, seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def _ts_srt(seconds: float) -> str:
    return _ts(seconds).replace(".", ",")


def _timestamp_prefix(seconds: float, opt: FormatOptions, *, bold: bool = False) -> str:
    if not opt.include_timestamps or opt.timestamp_style == "none":
        return ""
    stamp = _ts(seconds)
    text = f"[{stamp}]" if opt.timestamp_style == "bracket" else f"({stamp})"
    return f"**{text}** " if bold else f"{text} "


def _speaker_prefix(speaker: str | None, opt: FormatOptions, *, markdown: bool = False) -> str:
    if not opt.include_speakers or not speaker or opt.speaker_style == "none":
        return ""
    if opt.speaker_style == "bold" and markdown:
        return f"**{speaker}:** "
    if opt.speaker_style == "inline":
        return f"({speaker}) "
    return f"{speaker}: "


def _group_paragraphs(segments: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
    """Group consecutive segments that share a speaker into paragraphs."""
    groups: list[list[TranscriptSegment]] = []
    for seg in segments:
        if groups and groups[-1][-1].speaker == seg.speaker:
            groups[-1].append(seg)
        else:
            groups.append([seg])
    return groups


def _wrap(text: str, width: int | None) -> str:
    if not width or width <= 0:
        return text
    import textwrap
    return "\n".join(textwrap.wrap(text, width=width)) or text


def format_markdown(result: TranscriptResult, opt: FormatOptions | None = None, **legacy) -> str:
    opt = opt or FormatOptions(**_legacy_kwargs(legacy))
    # Joined with a blank line below, so no empty entries here - they turn into
    # three blank lines between every paragraph.
    lines = ["# Transcript"]
    # Deliberately not "59:19" - a clock-shaped number at the top of a transcript
    # reads as a timestamp, which is confusing when timestamps are turned off.
    lines.append(f"*This recording is {spoken_duration(result.audio_seconds)} long. "
                 f"The transcript took {spoken_duration(result.transcribe_seconds)} to write, "
                 f"using {result.model}.*")
    if opt.paragraph_mode:
        for group in _group_paragraphs(result.segments):
            prefix = _timestamp_prefix(group[0].start, opt, bold=True)
            speaker = _speaker_prefix(group[0].speaker, opt, markdown=True)
            body = " ".join(s.text.strip() for s in group if s.text.strip())
            lines.append(f"{prefix}{speaker}{body}".strip())
    else:
        for seg in result.segments:
            prefix = _timestamp_prefix(seg.start, opt, bold=True)
            speaker = _speaker_prefix(seg.speaker, opt, markdown=True)
            lines.append(f"{prefix}{speaker}{seg.text}".strip())
    return "\n\n".join(lines).strip() + "\n"


def format_text(result: TranscriptResult, opt: FormatOptions | None = None, **legacy) -> str:
    opt = opt or FormatOptions(**_legacy_kwargs(legacy))
    lines = []
    if opt.paragraph_mode:
        for group in _group_paragraphs(result.segments):
            prefix = _timestamp_prefix(group[0].start, opt)
            speaker = _speaker_prefix(group[0].speaker, opt)
            body = " ".join(s.text.strip() for s in group if s.text.strip())
            lines.append(_wrap(f"{prefix}{speaker}{body}".strip(), opt.max_line_chars))
    else:
        for seg in result.segments:
            prefix = _timestamp_prefix(seg.start, opt)
            speaker = _speaker_prefix(seg.speaker, opt)
            lines.append(_wrap(f"{prefix}{speaker}{seg.text}".strip(), opt.max_line_chars))
    sep = "\n\n" if opt.paragraph_mode else "\n"
    return sep.join(lines).strip() + "\n"


def format_srt(result: TranscriptResult, opt: FormatOptions | None = None, **legacy) -> str:
    opt = opt or FormatOptions(**_legacy_kwargs(legacy))
    out = []
    for i, seg in enumerate(result.segments, start=1):
        speaker = _speaker_prefix(seg.speaker, opt)
        out.append(f"{i}\n{_ts_srt(seg.start)} --> {_ts_srt(seg.end)}\n{speaker}{seg.text}\n")
    return "\n".join(out).strip() + "\n"


def format_vtt(result: TranscriptResult, opt: FormatOptions | None = None, **legacy) -> str:
    opt = opt or FormatOptions(**_legacy_kwargs(legacy))
    out = ["WEBVTT", ""]
    for seg in result.segments:
        speaker = f"<v {seg.speaker}>" if opt.include_speakers and seg.speaker and opt.speaker_style != "none" else ""
        out.append(f"{_ts(seg.start)} --> {_ts(seg.end)}\n{speaker}{seg.text}\n")
    return "\n".join(out).strip() + "\n"


def _legacy_kwargs(legacy: dict) -> dict:
    """Back-compat shim for the old include_timestamps=/include_speakers= call style."""
    out = {}
    if "include_timestamps" in legacy:
        out["include_timestamps"] = legacy["include_timestamps"]
    if "include_speakers" in legacy:
        out["include_speakers"] = legacy["include_speakers"]
    return out
