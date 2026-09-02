# ASR model benchmark

Hardware: Intel64 Family 6 Model 197 Stepping 2, GenuineIntel | 63.5 GB RAM | accelerator: cpu

## Summary (total audio processed vs. total time taken)

| Engine:Model | Audio processed | Time taken | Speed | Avg WER | Avg accuracy | Failures |
|---|---|---|---|---|---|---|
| faster-whisper:tiny.en | 5:00 | 11.3s | 26.61x real-time | 4.2% | 95.8% | 0 |
| faster-whisper:small.en | 5:01 | 49.3s | 6.12x real-time | 3.4% | 96.6% | 0 |
| parakeet-onnx:parakeet-tdt-0.6b-v2 | 5:00 | 17.5s | 17.18x real-time | 2.0% | 98.0% | 0 |

## Per-file detail

| Engine:Model | File | Audio | Elapsed | Speed | WER | Notes |
|---|---|---|---|---|---|---|
| faster-whisper:tiny.en | ep1-clip.mp3 | 5:00 | 11.3s | 26.61x | 4.2% | "The opinions expressed on the ACB Media Network are those of the content providers and should not be viewed as an endors..." |
| faster-whisper:small.en | ep1-clip.mp3 | 5:01 | 49.3s | 6.12x | 3.4% | "The opinions expressed on the ACB Media Network are those of the content providers and should not be viewed as an endors..." |
| parakeet-onnx:parakeet-tdt-0.6b-v2 | ep1-clip.mp3 | 5:00 | 17.5s | 17.18x | 2.0% | "The opinions expressed on the ACB Media Network are those of the content providers and should not be viewed as an endors..." |
