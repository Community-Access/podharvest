# ASR model benchmark

Hardware: Intel64 Family 6 Model 197 Stepping 2, GenuineIntel | 63.5 GB RAM | accelerator: cpu

## Summary (total audio processed vs. total time taken)

| Engine:Model | Audio processed | Time taken | Speed | Avg WER | Avg accuracy | Failures |
|---|---|---|---|---|---|---|
| faster-whisper:tiny.en | 5:00 | 11.0s | 27.24x real-time | 4.2% | 95.8% | 0 |
| faster-whisper:small.en | 5:01 | 47.9s | 6.29x real-time | 3.4% | 96.6% | 0 |
| parakeet-onnx:parakeet-tdt-0.6b-v2 | 5:00 | 17.7s | 16.93x real-time | 6.6% | 93.5% | 0 |

## Per-file detail

| Engine:Model | File | Audio | Elapsed | Speed | WER | Notes |
|---|---|---|---|---|---|---|
| faster-whisper:tiny.en | ep1-clip.mp3 | 5:00 | 11.0s | 27.24x | 4.2% | "The opinions expressed on the ACB Media Network are those of the content providers and should not be viewed as an endors..." |
| faster-whisper:small.en | ep1-clip.mp3 | 5:01 | 47.9s | 6.29x | 3.4% | "The opinions expressed on the ACB Media Network are those of the content providers and should not be viewed as an endors..." |
| parakeet-onnx:parakeet-tdt-0.6b-v2 | ep1-clip.mp3 | 5:00 | 17.7s | 16.93x | 6.6% | "The opinions expressed on the ACB Media Network are those of the content providers and should not be viewed as an endors..." |
