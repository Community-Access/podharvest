# Supported on-device models

Full technical detail behind the summary table in [`README.md`](../README.md). All prices are in disk space and RAM/VRAM, not money — everything here runs locally, for free, forever, with no API keys.

Source of truth in code: `podharvest/hardware.py` (`WHISPER_CHOICES`, `PARAKEET_CHOICES`, `PARAKEET_ONNX_CHOICES`, `CANARY_CHOICES`, `VOSK_CHOICES`, `MOONSHINE_CHOICES`, `ENRICHMENT_CHOICES`). Acquisition and download verification logic lives in `podharvest/acquire.py`; engine implementations live in `podharvest/transcribe.py`.

**Want to measure which one is actually best for your use case instead of trusting this table?** Run `podharvest benchmark` - see ["Validating accuracy and comparing models"](../README.md#validating-accuracy-and-comparing-models) in the README for real timing + Word Error Rate comparisons.

## Speech-to-text (ASR) engines

### faster-whisper (default, most portable)

CTranslate2 re-implementation of OpenAI Whisper. Runs on CPU (`int8`) or any GPU (`float16`). No hard hardware requirement — always available as the universal fallback.

| Model | Approx. size | Min RAM/VRAM | Notes |
|---|---|---|---|
| `tiny.en` | 0.1 GB | 1 GB | Fastest, lowest accuracy |
| `base.en` | 0.15 GB | 1 GB | Fast, good for clear speech |
| `small.en` | 0.5 GB | 2 GB | **Recommended default balance** |
| `distil-medium.en` | 1.5 GB | 3 GB | Distilled — near-medium accuracy, faster |
| `medium.en` | 1.5 GB | 5 GB | High accuracy |
| `distil-large-v3` | 1.5 GB | 4 GB | Near-large-v3 accuracy, notably faster |
| `large-v3-turbo` | 1.6 GB | 6 GB | OpenAI's 2024 pruned large model - ~8x faster than large-v3 for a small accuracy cost |
| `large-v3` | 3.0 GB | 10 GB | Best accuracy, slowest |

License: MIT (both the `faster-whisper`/CTranslate2 code and the underlying Whisper weights).

### Parakeet (NVIDIA NeMo) - CUDA + PyTorch

TDT (Token-and-Duration Transducer) models. The fastest and most accurate English ASR you can run locally today when you have an NVIDIA GPU - but genuinely **CUDA-only**: it needs a working CUDA build of PyTorch plus the multi-GB `nemo_toolkit[asr]` stack, and there is no practical CPU path. If you don't have an NVIDIA GPU, use **Parakeet-ONNX** below instead of this engine.

| Model | Approx. size | Min VRAM |
|---|---|---|
| `parakeet-tdt-0.6b-v2` | 2.4 GB | 3 GB |
| `parakeet-tdt-1.1b` | 4.4 GB | 5 GB |

License: CC-BY-4.0. English only. **There is no smaller official Parakeet checkpoint** - 0.6B is NVIDIA's smallest public release; the 1.1B is larger, not smaller. A CTC/RNNT-head variant exists at the same 0.6B size (different decoder, not a size reduction).

### Parakeet-ONNX (sherpa-onnx) - the PyTorch-free path

The *same* NVIDIA Parakeet TDT 0.6B checkpoint, exported to ONNX and run through [k2-fsa's sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) + plain `onnxruntime`. No PyTorch, no NeMo, no CUDA required - this is the answer if you want Parakeet's accuracy without the heavy dependency chain or a GPU.

| Model | Approx. size | Hardware |
|---|---|---|
| `parakeet-tdt-0.6b-v2` (ONNX) | 2.4 GB | Any CPU (or GPU via `onnxruntime-gpu`) |

License: CC-BY-4.0 (same weights as native Parakeet). Long audio is automatically split into ~25-second windows, since sherpa-onnx's offline recognizer is designed for single utterances rather than hour-long files.

### Canary (NVIDIA NeMo)

Multilingual alternative to Parakeet with built-in punctuation/casing and English/Spanish/German/French support. Heavier and CUDA-only.

| Model | Approx. size | Min VRAM |
|---|---|---|
| `canary-1b-flash` | 4.0 GB | 6 GB |

License: CC-BY-NC-4.0 (**non-commercial** — check before shipping a commercial product built on it).

### Vosk

Pure-CPU, Kaldi-based recognizer with a tiny footprint. No AVX2 or GPU required — the right choice for very old or low-power hardware where even `tiny.en` is too slow.

| Model | Approx. size |
|---|---|
| `vosk-model-small-en-us-0.15` | 0.04 GB |
| `vosk-model-en-us-0.22` | 1.8 GB |

License: Apache-2.0. Lowest accuracy of the catalogue, but it will run on essentially anything.

### Moonshine (Useful Sensors)

Extremely fast CPU inference, tuned for short-form speech but perfectly usable on full episodes at a small accuracy cost versus Whisper.

| Model | Approx. size |
|---|---|
| `moonshine-tiny` | 0.1 GB |
| `moonshine-base` | 0.4 GB |

License: MIT.

## Optional transcript enrichment (post-processing LLM)

Runs after transcription via `llama.cpp` (CPU-friendly, GPU-accelerated if available) to clean up punctuation/casing, generate summaries, or propose chapter titles. Entirely optional — never required for transcription itself. Fully wired into `podharvest/harvest.py`: enable with `settings --set enrichment_enabled=true`, and each transcribed episode gets a `<slug>.summary.md` alongside its transcript.

| Model | Approx. size (Q4_K_M) | Min RAM | License |
|---|---|---|---|
| Phi-3.5 Mini Instruct | 2.4 GB | 4 GB | MIT |
| Llama 3.2 3B Instruct | 2.0 GB | 4 GB | Llama 3.2 Community License |
| **Nemotron-Mini 4B Instruct** | 2.6 GB | 5 GB | NVIDIA Open Model License |
| Mistral 7B Instruct v0.3 | 4.4 GB | 8 GB | Apache-2.0 |

**Windows note:** `llama-cpp-python` cannot be *built from source* on Windows in most environments — not because of a missing C++ compiler, but because its vendored `llama.cpp` source tree (which includes a full web UI) has paths deep enough to exceed Windows' default 260-character `MAX_PATH` limit, producing a confusing `OSError: [Errno 2] No such file or directory`. `podharvest.acquire.ensure_package` handles this automatically: for `llama-cpp-python` specifically, it installs the maintainer's prebuilt CPU wheel from `https://abetlen.github.io/llama-cpp-python/whl/cpu` first (no source build at all), falling back to a plain source build only if that ever becomes unavailable. This is live-tested and confirmed working end to end (model download → load → real generated summary → written to disk).

### A note on Megatron

NVIDIA **Megatron-LM**/Megatron-Core is a *training* framework for large language models — it isn't a deployable model you can download and run, so it isn't offered as an engine option here. **Nemotron** models are Megatron-lineage models NVIDIA actually ships as deployable checkpoints, which is why Nemotron-Mini is in the enrichment catalogue above instead.

## How acquisition works

1. When you pick a model (CLI `settings --set asr_model=...` or the GUI's model dropdown) and start a job, `podharvest.acquire` checks whether it's already downloaded (a `manifest.json` next to the model files).
2. If missing, it installs any required Python packages into the isolated `AppSpace.python_packages_dir` (never your system Python) via `pip install --target`, trying a package-specific list of install strategies in order (e.g. a prebuilt wheel before a from-source build) so a single fragile build doesn't block the whole feature.
3. It then downloads the model:
   - Hugging-Face-hosted repos use `huggingface_hub.snapshot_download`/`hf_hub_download` when available (resumable, deduplicated) or fall back to plain HTTPS via `podharvest.net`.
   - Vosk's zipped releases are streamed and extracted in place.
4. A manifest is written recording the engine, model, source, license, and files, so subsequent runs skip re-downloading.
5. **Verification, not just presence:** every cache hit is re-checked by `podharvest.acquire.verify_model()` before being trusted - GGUF files must start with the `GGUF` magic bytes, sherpa-onnx models must have all four required files above a minimum size, Vosk archives must have extracted a plausible number of files, and everything else must have every recorded file present and non-trivially sized. A corrupted or truncated cache is detected and automatically re-downloaded rather than silently reused.

All progress is reported through `podharvest.progress.ProgressReporter` — the same throttled, percentage-based progress bar used for enclosure downloads.

## Validating accuracy, not just availability

Downloading and running a model isn't the same as knowing it's *good enough* for your feed. `podharvest benchmark` (see `podharvest/benchmark.py` and `podharvest/accuracy.py`) transcribes the same audio with multiple engine/model combinations and reports:

- **Speed** — real-time factor, measured directly (not estimated).
- **Word Error Rate (WER) and accuracy** — computed via classic DP word-level alignment (the same family of metric used by academic ASR leaderboards), when you supply a reference transcript with `--reference`/`--reference-dir`.

See [the README's benchmarking section](../README.md#validating-accuracy-and-comparing-models) for usage and a real example run.
