import sys
import time
from pathlib import Path

sys.path.insert(0, "D:/code/pod")

from podharvest.appspace import resolve
from podharvest.hardware import ModelChoice
from podharvest.transcribe import FasterWhisperEngine, ParakeetEngine

app = resolve()
app.activate()

clips = [
    Path("D:/code/pod/bench/ep1-clip.mp3"),
    Path("D:/code/pod/bench/ep2-clip.mp3"),
    Path("D:/code/pod/bench/ep3-clip.mp3"),
]

print("=" * 70)
print("WHISPER (faster-whisper) BENCHMARK")
print("=" * 70)

for model_name in ["tiny.en", "small.en"]:
    choice = ModelChoice("faster-whisper", model_name, 1.0, model_name)
    engine = FasterWhisperEngine(app, choice, device="cpu", compute_type="int8")
    t_load0 = time.monotonic()
    engine._load()
    load_s = time.monotonic() - t_load0
    print(f"\n--- Model: {model_name} (load time {load_s:.1f}s) ---")
    total_audio = 0.0
    total_elapsed = 0.0
    for clip in clips:
        t0 = time.monotonic()
        result = engine.transcribe(clip, include_word_timestamps=True)
        elapsed = time.monotonic() - t0
        total_audio += result.audio_seconds
        total_elapsed += elapsed
        preview = result.text[:100].replace("\n", " ")
        print(f"  {clip.name}: {result.audio_seconds:.1f}s audio -> {elapsed:.1f}s "
              f"({result.speed_x_realtime}x real-time) | \"{preview}...\"")
    print(f"  TOTAL: {total_audio:.1f}s audio in {total_elapsed:.1f}s "
          f"({round(total_audio/total_elapsed, 2)}x real-time overall)")

print("\n" + "=" * 70)
print("PARAKEET (NVIDIA NeMo) - feasibility check")
print("=" * 70)
choice = ModelChoice("parakeet", "parakeet-tdt-0.6b-v2", 3.0, "parakeet-tdt-0.6b-v2", requires_cuda=True)
engine = ParakeetEngine(app, choice)
try:
    engine.transcribe(clips[0], include_word_timestamps=False)
except Exception as exc:
    print(f"  Parakeet failed as expected on this machine: {exc}")
