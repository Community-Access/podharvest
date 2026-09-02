#!/usr/bin/env python3
"""Ad-hoc ASR benchmark harness used to produce the figures in the README.

For ordinary use prefer the built-in command, which also scores accuracy:

    podharvest benchmark bench/*.mp3 --reference-dir bench \\
        --model faster-whisper:tiny.en --model faster-whisper:small.en

This script stays around because it exercises the engine classes directly,
which is useful when adding a new engine and you want load time separated
from transcription time.

The audio clips are not committed - see bench/README.md for how to make your
own. Any clips in this folder are picked up automatically.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent

# Run against this checkout rather than whatever podharvest happens to be
# installed, so benchmark numbers describe the code in front of you.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from podharvest.appspace import resolve  # noqa: E402
from podharvest.hardware import ModelChoice  # noqa: E402
from podharvest.transcribe import FasterWhisperEngine, ParakeetEngine  # noqa: E402

WHISPER_MODELS = ["tiny.en", "small.en"]


def find_clips() -> list[Path]:
    clips = sorted(p for p in BENCH_DIR.glob("*.mp3"))
    if not clips:
        sys.exit(
            f"No .mp3 clips found in {BENCH_DIR}.\n"
            "The benchmark audio is not committed - see bench/README.md for how to\n"
            "fetch a feed and cut your own clips."
        )
    return clips


def benchmark_whisper(app, clips: list[Path]) -> None:
    print("=" * 70)
    print("WHISPER (faster-whisper) BENCHMARK")
    print("=" * 70)

    for model_name in WHISPER_MODELS:
        choice = ModelChoice("faster-whisper", model_name, 1.0, model_name)
        engine = FasterWhisperEngine(app, choice, device="cpu", compute_type="int8")

        t_load0 = time.monotonic()
        engine._load()  # noqa: SLF001 - measuring load time is the point
        load_s = time.monotonic() - t_load0
        print(f"\n--- Model: {model_name} (load time {load_s:.1f}s) ---")

        total_audio = total_elapsed = 0.0
        for clip in clips:
            t0 = time.monotonic()
            result = engine.transcribe(clip, include_word_timestamps=True)
            elapsed = time.monotonic() - t0
            total_audio += result.audio_seconds
            total_elapsed += elapsed
            preview = result.text[:100].replace("\n", " ")
            print(f"  {clip.name}: {result.audio_seconds:.1f}s audio -> {elapsed:.1f}s "
                  f'({result.speed_x_realtime}x real-time) | "{preview}..."')

        if total_elapsed:
            print(f"  TOTAL: {total_audio:.1f}s audio in {total_elapsed:.1f}s "
                  f"({round(total_audio / total_elapsed, 2)}x real-time overall)")


def check_parakeet(app, clip: Path) -> None:
    """Parakeet needs CUDA. On a CPU-only machine this should fail with a clear
    message naming what is missing, not a low-level traceback - which is itself
    worth checking."""
    print("\n" + "=" * 70)
    print("PARAKEET (NVIDIA NeMo) - feasibility check")
    print("=" * 70)
    choice = ModelChoice("parakeet", "parakeet-tdt-0.6b-v2", 3.0,
                         "parakeet-tdt-0.6b-v2", requires_cuda=True)
    engine = ParakeetEngine(app, choice)
    try:
        result = engine.transcribe(clip, include_word_timestamps=False)
    except Exception as exc:  # noqa: BLE001 - reporting the message is the test
        print(f"  Unavailable on this machine: {exc}")
    else:
        print(f"  {clip.name}: {result.speed_x_realtime}x real-time")


def main() -> int:
    app = resolve()
    app.activate()
    clips = find_clips()
    print(f"Benchmarking {len(clips)} clip(s) from {BENCH_DIR}\n")
    benchmark_whisper(app, clips)
    check_parakeet(app, clips[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
