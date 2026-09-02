# podharvest technical reference

This is the full reference: every command, flag, setting and model. If you just want to use the app, start with the [README](../README.md) instead.

[![CI](https://github.com/community-access/podharvest/actions/workflows/ci.yml/badge.svg)](https://github.com/community-access/podharvest/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](../LICENSE)
[![Accessibility statement](https://img.shields.io/badge/accessibility-statement-blueviolet)](ACCESSIBILITY.md)

**Archive any RSS/Atom/podcast feed as Markdown, HTML, plain text and JSON — download every enclosure, and transcribe the audio entirely on your own machine.** No cloud APIs, no accounts, no data leaving your computer unless you ask it to.

Built and tested against real-world feeds such as [ACB Diabetics in Action](https://acbda.org/podcast) (`https://acbda.org/feed`).

> **Project status:** the full pipeline described below - feed discovery, parsing, rendering, downloading, transcription, and accuracy benchmarking - is implemented and has been run end-to-end against real feeds. See [Roadmap](#roadmap) for what's still open.

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Command-line usage](#command-line-usage)
- [The desktop GUI](#the-desktop-gui)
- [Supported on-device models](#supported-on-device-models)
- [Validating accuracy and comparing models](#validating-accuracy-and-comparing-models)
- [Settings reference](#settings-reference)
- [Portable app space](#portable-app-space)
- [Accessibility](#accessibility)
- [Building a standalone installer](#building-a-standalone-installer)
- [Contributing](#contributing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

## Features

- **Rich feed extraction** — full episode text (not just the truncated summary), authors, categories, chapters, funding links, and every enclosure. Point it at a show's web page and it finds the feed; paginated archives are followed and merged.
- **Four output formats per episode** — Markdown, sanitized HTML, plain text, and structured JSON (CSV export too).
- **Verified enclosure downloads** — audio, video, images and documents are sorted into separate folders per feed. Transfers are resumable across runs, rate-limitable, and checked against the length the server declared, so a truncated or duplicated download fails loudly instead of being recorded as complete.
- **On-device transcription** — pick from multiple ASR engines (Whisper, Parakeet, Canary, Vosk, Moonshine); the app recommends the best one for *your* hardware automatically.
- **Speaker diarization & timestamps** — toggle "who's speaking" labels and per-line/per-word timestamps independently, with a choice of three diarization backends (`pyannote`, PyTorch-free `sherpa-onnx`, or NVIDIA `nemo-msdd`).
- **Optional transcript enrichment** — an on-device LLM pass (Phi-3.5, Llama 3.2, Nemotron-Mini, Mistral) for punctuation cleanup, summaries, and chapter titles.
- **Hardware-aware model advisor** — probes your CPU, RAM, and GPU (CUDA/ROCm/Metal) and recommends a model that will actually run well, with a CPU-only fallback always available.
- **Fully portable** — models, caches, logs, and config all live in one self-contained folder that can travel on a USB stick; nothing is installed into your home directory or global Python environment unless you choose the default location.
- **Two front ends, one engine** — a full wxPython desktop GUI and a scriptable CLI, both driven by the same settings file and pipeline.
- **Rich, persistent settings** — output folder, episode limits (a number, or "all"), download filters, ASR/enrichment choices, and output formats all persist between runs, shared by the CLI and the GUI.
- **Keyboard-first and screen-reader-aware** — with an [accessibility statement](ACCESSIBILITY.md) that states plainly what has been verified and what has not.

## Quick start

### Windows, zero setup

```bat
run.bat gui
```

The first run creates a local virtual environment (`.venv`) next to the script, installs the minimal base requirements (just wxPython — everything else installs on demand), and launches the app. Re-run `run.bat` any time; it only sets up once.

### Install with pip

```powershell
python -m pip install podharvest          # CLI only
python -m pip install "podharvest[gui]"   # plus the desktop app
```

That gives you a `podharvest` command (and `podharvest-gui`, which opens the window without a console):

```powershell
podharvest gui              # desktop app
podharvest hardware         # what will transcription look like on this machine?
podharvest fetch https://acbda.org/podcast --limit 5
```

### From a source checkout

```powershell
python -m pip install -e ".[gui]"
python main.py gui
```

Requires Python 3.10+. The core pipeline runs on the standard library alone — `wxPython` is only needed for the GUI, and every ASR engine installs on demand the first time you use it.

**Paste the show's web page, not just its feed.** podharvest looks for a feed link on any HTML page you give it, so `https://acbda.org/podcast` works as well as `https://acbda.org/feed`.

**New to podharvest?** [`GETTING_STARTED.md`](GETTING_STARTED.md) walks through installing, your first fetch, and your first transcription step by step.

## Command-line usage

Running `podharvest`/`main.py` with no arguments always prints full usage instead of doing anything surprising:

```text
python main.py
usage: podharvest [-h] [--version] [--app-dir PATH] [-v] [-q] [--log-file PATH] <command> ...

  fetch       Download and convert a feed (and its enclosures).
  hardware    Detect hardware and recommend an on-device transcription model.
  gui         Launch the wxPython desktop application.
  info        Show the portable app-space paths in use.
  benchmark   Compare ASR models/engines on the same audio file(s).
  settings    View or change saved defaults (output folder, limits, ASR options...).
```

Common examples:

```powershell
# Harvest every episode, converting content only (no downloads)
python main.py fetch https://acbda.org/feed --no-download

# Grab only the 5 most recent episodes, with on-device transcription
python main.py fetch https://acbda.org/feed --limit 5 --transcribe

# Explicitly fetch everything (overrides any saved episode limit)
python main.py fetch https://acbda.org/feed --limit all

# Re-use the last feed URL and saved settings
python main.py fetch

# See what hardware you have and which ASR model podharvest recommends
python main.py hardware
python main.py hardware --json

# View or change persisted defaults
python main.py settings --show
python main.py settings --set output_dir=D:\Podcasts --set episode_limit=10
python main.py settings --reset
```

Every subcommand accepts `-v`/`-vv` for more detailed logs, `-q` for warnings-only, `--log-file PATH` for a persistent log, and `--app-dir PATH` to point at a different portable app space.

## The desktop GUI

`python main.py gui` (or `run.bat gui`) opens a resizable window with:

- A **feed** section (URL + output folder, with a folder browser).
- An **options** section: download enclosures on/off, transcribe on/off, and an episode limit spinner (0 = all).
- A **transcript options** panel: model picker (auto-populated from the hardware advisor), timestamps toggle, and speaker-identification toggle — all disabled until transcription is turned on.
- A **hardware** panel showing your CPU/RAM/GPU summary and the recommended model, with a re-detect button (Ctrl+D). If detection fails, transcription is switched off with an explanation and the rest of the app keeps working.
- **Start/Cancel** buttons, a progress bar, and a readable activity log (Ctrl+L). The log does not announce itself — see [Accessibility](#accessibility).

A File/View/Help menu bar lists every action and its shortcut: **Ctrl+R** start, **Esc** cancel, **Ctrl+L** activity log, **Ctrl+D** re-detect hardware.

Every field you change is remembered (via the same `settings.json` the CLI uses) and restored the next time you open the app.

## Supported on-device models

Everything below runs locally and is downloaded on first use straight into the portable app space. Cloud providers are available too but are strictly opt-in and need your own API key: see the "Optional cloud models" section. With no key configured, podharvest makes no call to any transcription service (see [`MODELS.md`](MODELS.md) for the full catalogue, licenses, and technical notes).

### Speech-to-text (ASR)

| Engine | Models | Hardware | Best for |
|---|---|---|---|
| **faster-whisper** | tiny.en → large-v3, incl. large-v3-turbo and distilled sizes (8 total) | Any CPU or GPU | The default, most portable choice |
| **Parakeet** (NVIDIA NeMo) | TDT 0.6B, TDT 1.1B | NVIDIA GPU (CUDA) + PyTorch/NeMo | Fastest + most accurate English ASR available |
| **Parakeet-ONNX** (sherpa-onnx) | TDT 0.6B | Any CPU (no PyTorch/NeMo/CUDA needed) | Same Parakeet accuracy, without the heavy ML stack |
| **Canary** (NVIDIA NeMo) | 1B Flash | NVIDIA GPU (CUDA) | Multilingual (en/es/de/fr) with built-in punctuation |
| **Vosk** | small / standard (English) | Any CPU, no AVX2 required | Old or very low-power machines |
| **Moonshine** | tiny / base | Any CPU | Fastest CPU-only inference for short-form audio |

### Optional transcript enrichment (post-processing LLM)

| Model | Size (quantized) | Notes |
|---|---|---|
| Phi-3.5 Mini Instruct | ~2.4 GB | Small, fast, strong at summarizing |
| Llama 3.2 3B Instruct | ~2.0 GB | Solid general-purpose default |
| **Nemotron-Mini 4B Instruct** | ~2.6 GB | NVIDIA's deployable, Megatron-LM-derived model |
| Mistral 7B Instruct | ~4.4 GB | Most capable, needs the most RAM |

> Asked about NVIDIA **Megatron** directly: Megatron-LM/Megatron-Core is a training framework, not a shippable model, so it isn't listed as an ASR or enrichment engine itself. Its deployable descendant, **Nemotron**, is offered above for anyone who specifically wants a Megatron-lineage model.

The hardware advisor (`podharvest hardware`, or the GUI's Hardware panel) always picks a model that fits your machine's CPU/RAM/GPU budget, and every engine has a CPU-only fallback so transcription never *requires* a GPU. Every model listed above is backed by an implemented engine — the catalogue and the dispatcher are kept in step, and there is a test asserting it.

Measured on a CPU-only machine against a 5-minute clip: Vosk small runs at about **20x real-time** and produces word-level timestamps.

## Validating accuracy and comparing models

Don't just guess which model is best for your feed - measure it. `podharvest benchmark` transcribes the same audio file(s) with as many engine/model combinations as you like and reports timing, throughput, and (with a reference transcript) Word Error Rate:

```powershell
# Timing only
podharvest benchmark clip.mp3 --model faster-whisper:tiny.en --model faster-whisper:small.en

# Timing + accuracy against a known-good reference transcript
podharvest benchmark clip.mp3 --reference-dir path\to\references --model faster-whisper:tiny.en --model faster-whisper:small.en
```

Each run prints a comparison table and saves a durable Markdown report (default `<app-dir>/logs/benchmark.md`, or `--report PATH`) with:

- **Speed** — real-time factor (e.g. `26.9x` means an hour of audio transcribes in about 2m14s).
- **WER / accuracy** — Word Error Rate and its complement, computed via classic DP word-alignment (substitutions + deletions + insertions ÷ reference word count), the same metric used by academic ASR benchmarks like LibriSpeech leaderboards.

Real example from this machine (CPU-only, same 5-minute clip, scored against a human-checked reference transcript):

| Engine / model | Speed | WER | Accuracy |
|---|---|---|---|
| **parakeet-onnx** parakeet-tdt-0.6b-v2 | **17.2x real-time** | **2.0%** | **98.0%** |
| faster-whisper tiny.en | 26.6x real-time | 4.2% | 95.8% |
| faster-whisper small.en | 6.1x real-time | 3.4% | 96.6% |

Parakeet is both the most accurate of the three and nearly three times faster than the most
accurate Whisper size, which is why it is the recommendation on CPU-only machines where a
GPU is not available. See `bench/comparison-report.md` for the generated report and
`bench/README.md` for how to reproduce it on your own audio.

No reference transcript handy? Use `--reference "some text"` to apply the same reference to every file (useful for repeated clips of one recording), or generate a pseudo-reference with a larger/slower model first and benchmark faster models against it, as shown above.

## Optional cloud models

podharvest runs entirely on your machine by default and needs no account with anyone. If you
want to, you can add your own API key for a cloud provider and pick its models instead.
Nothing is uploaded unless you add a key **and** select a cloud model.

Add keys in **Settings** (`Ctrl+,`), or set an environment variable such as
`PODHARVEST_OPENAI_KEY` — the variable always wins, and is never overwritten from the UI.
Keys are stored encrypted for your Windows account (DPAPI) or in the macOS login Keychain,
never in `settings.json`.

| Provider | Transcripts | Summaries & chapters | Notes |
|---|---|---|---|
| OpenAI | yes | yes | `whisper-1` is the only OpenAI model returning timestamps |
| Google Gemini | yes | yes | Labels speakers in the same pass, no separate step |
| OpenRouter | no | yes | One key, hundreds of text models |
| Ollama Cloud | no | yes | Hosted open models |

OpenRouter and Ollama Cloud have no speech-to-text endpoint, so they appear as summary
providers only rather than as transcription options that would fail when used.

Measured against the same 5-minute clip and human reference as the local models:

| Model | Where | Speed | WER | Speakers | Timestamps |
|---|---|---|---|---|---|
| **parakeet-tdt-0.6b-v2** | local | 17.2x | **2.0%** | separate step | yes |
| gpt-4o-mini-transcribe | OpenAI | **30.4x** | 2.9% | no | no |
| whisper-1 | OpenAI | 17.5x | 2.8% | no | yes |
| gpt-4o-transcribe | OpenAI | 19.4x | 3.5% | no | no |
| gemini-2.5-flash | Gemini | 13.5x | 4.2% | **yes, named** | yes |
| gemini-pro-latest | Gemini | 6.5x | 3.0% | **yes, named** | yes |

The local Parakeet model was the most accurate of everything tested. Cloud models are worth
it for speed on a slow machine, or for Gemini's speaker labelling — which worked out a
speaker's actual name from the audio rather than numbering the voices.

**On upload size.** Audio is re-encoded to 16 kHz mono Opus before upload, which is the
format these models listen to anyway, and which turns a 54 MB episode into about 7 MB — so a
normal episode is a single request. Anything still over a provider's limit is split at
natural pauses found with silence detection, never mid-word, and the pieces are stitched back
onto one timeline. Forcing a 5-minute clip into three pieces moved the error rate from 2.77%
to 3.02%, a difference of two words in 794.

## Chapter markers

Turn on **Write chapter markers with start and end times** to get a chapter list at the top
of each episode summary:

```markdown
## Chapters

- **00:00:00 - 00:00:34**  Welcome to ACB Diabetics in Action
- **00:00:34 - 00:01:09**  Introducing Deborah Erickson and The Blind Kitchen
- **00:01:09 - 00:01:30**  Deborah's Disclaimer and Three Categories of Help
```

The times come from the transcript's own segment timestamps, not from the model's guesswork —
anything outside the episode's length is discarded. Chapters need a model that returns
timestamps, so the OpenAI GPT-4o transcribe models cannot produce them.

## Chapter markers

`write_chapters` works out where each topic starts and ends, from the transcript's own segment
timestamps rather than from the model's guesswork; any time falling outside the episode is
discarded. The result is written above the summary in `<episode>.summary.md`.

`chapters_into_audio` (default on) additionally writes them into the audio file as chapter
metadata, which podcast players expose as a navigable list. Supported for `.mp3`, `.m4a`,
`.m4b`, `.mp4`, `.ogg` and `.opus`; other containers are skipped rather than re-muxed.

The audio stream is copied with `-codec copy`, so the rewrite is lossless and adds roughly
eighty bytes. It goes to a scratch file that only replaces the original once ffmpeg has
succeeded, so an interrupted write cannot truncate an episode.

Chapters need a model that returns per-segment timestamps. The OpenAI GPT-4o transcribe models
return plain text only and are skipped with a log line saying so.

## Settings reference

`podharvest settings --show` prints the full, self-describing settings file. Highlights:

| Setting | Meaning |
|---|---|
| `output_dir` | Where harvested feeds are written (default: `<app-dir>/feeds`) |
| `episode_limit` | A number, or `null`/`all` for every episode |
| `download_enclosures`, `download_kinds` | Whether to download enclosures, and which kinds (audio/video/image/document/other) |
| `concurrent_downloads`, `download_retries`, `download_rate_limit_kbps`, `max_enclosure_mb` | Network tuning |
| `on_duplicate_file` | `overwrite`/`rename`/`skip` when a download's destination name already exists for a different source URL |
| `transcribe`, `asr_engine`, `asr_model`, `concurrent_transcriptions` | Transcription defaults |
| `include_timestamps`, `identify_speakers`, `diarization_backend` | Timestamps/speaker labels, and which diarization engine (`pyannote`/`sherpa-onnx`/`nemo-msdd`) |
| `transcript_timestamp_style`, `transcript_speaker_style`, `transcript_paragraph_mode`, `transcript_max_line_chars` | Exactly how timestamps/speakers/paragraphs/line-wrapping are rendered |
| `follow_pagination` | Follow `<link rel="next">` across paginated feed archives (default on) |
| `hf_token` | Hugging Face token for the gated pyannote models (or `$PODHARVEST_HF_TOKEN`) |
| `enrichment_enabled`, `enrichment_model` | Optional LLM post-processing |
| `write_markdown`/`write_html`/`write_text`/`write_json`/`write_csv`/`write_srt`/`write_vtt` | Which output formats to generate |
| `naming_template` | Per-episode file naming. Placeholders: `{date}` `{slug}` `{title}` `{index}` `{season}` `{number}` `{year}` `{month}` `{day}` |
| `log_verbosity` | Default `-v` level when none is given on the command line |

Change any of them with `podharvest settings --set key=value` (repeatable). The GUI exposes the most commonly changed subset and writes to the same file; settings it does not show (download filters, concurrency, enrichment, output formats) are CLI-only for now.

## Portable app space

Run `podharvest info` to see exactly where things live:

```text
App root          : C:\Users\you\.podharvest
Models            : ...\models          (Whisper / Parakeet / Canary / Vosk / Moonshine / enrichment)
Isolated packages : ...\pydeps          (optional heavy pip packages, never your global site-packages)
HTTP cache        : ...\cache\http
Config            : ...\config          (settings.json, cached hardware probe)
Logs              : ...\logs
Default output    : ...\feeds
```

Resolution order: `--app-dir` flag → `PODHARVEST_HOME` env var → a `.podharvest-home` folder next to the app (portable/USB mode, used automatically by the PyInstaller build) → `~/.podharvest`.

## Accessibility

Accessibility is a functional requirement here, and this section is deliberately specific about what has been verified versus what has not. **No manual screen reader pass has been performed yet** — [`ACCESSIBILITY.md`](ACCESSIBILITY.md) says so plainly and lists every known gap. Running one and reporting what you find is the most useful contribution anyone could make to this project right now.

What works today:

- **Keyboard-first.** Every control is reachable with Tab; no action needs a mouse. Primary actions have frame-level shortcuts (**Ctrl+R** start, **Esc** cancel, **Ctrl+L** activity log, **Ctrl+D** re-detect hardware), and a File/View/Help menu bar gives an Alt entry point for exploring the app.
- **Named, grouped controls.** Related controls sit in labeled `StaticBox` regions that expose a real grouping role. Controls without an adjacent label get an accessible name through `wx.Accessible`.
- **System theming.** No colors, fonts, or custom drawing anywhere in the GUI, so high-contrast themes, focus indicators, and text scaling all work natively.
- **Errors are never color-only.** Validation problems show a modal dialog with a text explanation and move focus to the offending field. A failed hardware probe disables transcription and explains why, rather than leaving the app unusable.
- **The CLI never assumes a color terminal** and never requires interaction it can't also accept via flags.
- **Archived output is semantic.** Generated pages have a `<main>` landmark, exactly one `<h1>`, normalized heading levels, a `<dl>` for metadata, real download links for enclosures, a validated `lang` attribute, and an `index.html` so the archive is navigable. Caption tracks on media are preserved.

The most important limitation to know about: **the activity log does not announce new lines.** wxWidgets has no live-region API on any platform, so no screen reader speaks progress automatically during a run. Read it on demand with Ctrl+L, or the status bar with NVDA+End / JAWS Insert+Page Down. An earlier version of this README claimed otherwise; that claim was wrong and has been removed.

## Building a standalone installer

```powershell
./scripts/build_installer.ps1          # portable .zip via PyInstaller
./scripts/build_installer.ps1 -Clean   # force a from-scratch rebuild
./scripts/build_installer.ps1 -Inno    # also build a conventional Windows installer
```

The base command creates an isolated build environment, runs PyInstaller against [`packaging/podharvest.spec`](../packaging/podharvest.spec) (a one-folder build so ASR models keep installing on demand rather than bloating the executable), marks the output as portable, and zips it as `dist/podharvest-<version>-win64-portable.zip`.

Passing `-Inno` additionally compiles [`installer/podharvest.iss`](../installer/podharvest.iss) with [Inno Setup](https://jrsoftware.org/isinfo.php) into `dist/installer/podharvest-<version>-setup.exe` — a conventional installer with a Start Menu entry, optional desktop icon, and uninstaller. Unlike the portable zip, the installed copy correctly stores its models/cache/config under the current user's profile rather than trying to write into Program Files.

The resulting `podharvest.exe` (either build) keeps all of its models/cache/config in one folder — for the portable build, copy that folder anywhere (including a USB drive) and it keeps working.

## Project structure

```text
main.py                    Standalone entry point (python main.py ...)
podharvest/
  cli.py                   argparse CLI with full usage screens
  gui.py                   wxPython desktop application
  appspace.py              Portable app-space resolution (models/cache/config/logs)
  config.py                Persistent, rich Settings (shared by CLI + GUI)
  hardware.py              CPU/RAM/GPU probing + ASR/enrichment model catalogue
  acquire.py               On-demand, verified, resumable model + package acquisition
  feed.py                  RSS/Atom/RDF feed discovery and parsing
  render.py                Episode -> Markdown/HTML/text/JSON/CSV rendering
  download.py              Concurrent, resumable enclosure downloading
  transcribe.py            ASR engines (faster-whisper/Parakeet/Parakeet-ONNX), diarization (pyannote/sherpa-onnx/nemo-msdd), transcript formatting
  enrich.py                Optional LLM transcript enrichment (summary + chapter titles) via llama-cpp-python
  accuracy.py              Word Error Rate (WER) scoring
  benchmark.py             Side-by-side engine/model timing + accuracy comparison
  harvest.py               Orchestrates feed -> render -> download -> transcribe (what fetch/GUI Start call)
  net.py                   Resilient HTTP client (retries, resume, rate limiting)
  convert.py               Dependency-free HTML <-> Markdown/plain-text conversion
  models.py                Feed/Episode/Enclosure data model
  progress.py               Throttled progress bars for downloads & transcription
  util.py                  Slugs, safe filenames, date/duration parsing, logging
packaging/podharvest.spec  PyInstaller build spec
installer/podharvest.iss   Inno Setup installer script
scripts/build_installer.ps1  One-command portable + Inno Setup installer build
requirements*.txt          Core / optional-ASR / build-only dependency sets
run.bat                    Zero-setup Windows launcher
docs/GETTING_STARTED.md    Step-by-step first-run guide
docs/MODELS.md             Full model catalogue, licenses, acquisition details
docs/ACCESSIBILITY.md      Accessibility statement: verified, unverified, and known gaps
pyproject.toml             Packaging metadata and the podharvest console scripts
tests/                     Test suite (pytest)
.github/workflows/ci.yml   Tests + lint on Linux/macOS/Windows, Python 3.10-3.13
```

## Roadmap

- [x] Core utilities, HTTP client, HTML↔Markdown conversion, data model
- [x] Portable app space, rich settings, hardware advisor, model catalogue/acquisition (with download verification)
- [x] CLI with full usage screens; wxPython GUI
- [x] PyInstaller packaging + Inno Setup installer
- [x] Feed discovery/parsing (RSS/Atom/RDF) → `podharvest.feed`
- [x] Episode rendering to Markdown/HTML/text/JSON/CSV → `podharvest.render`
- [x] Enclosure downloader with per-kind folders and a resumable manifest → `podharvest.download`
- [x] Transcription engines (faster-whisper, Parakeet via NeMo, Parakeet via sherpa-onnx) → `podharvest.transcribe`
- [x] Accuracy validation (WER) and model comparison → `podharvest.accuracy` / `podharvest.benchmark`
- [x] `podharvest.harvest.run_harvest(...)` tying it all together (what `fetch`/the GUI's Start button call)
- [x] Speaker diarization with a choice of backend: `pyannote` (default), PyTorch-free `sherpa-onnx` (live-tested, ~120MB download), or NVIDIA `nemo-msdd` (needs the full NeMo/PyTorch stack)
- [x] Transcript enrichment pipeline wired into `harvest.py` (`podharvest/enrich.py`) - installs `llama-cpp-python` via a prebuilt CPU wheel on Windows (avoiding a from-source build that hits Windows' path-length limit on its vendored source tree), and is live-tested end to end: model download -> load -> real generated summary -> written to disk as `<slug>.summary.md`.
- [x] Vosk and Moonshine engines implemented, so every catalogued model has a working engine
- [x] Feed auto-discovery from a podcast's web page, and RFC 5005 pagination
- [x] Packaging (`pip install podharvest`), test suite, and CI
- [ ] NVIDIA Canary: routed through the NeMo engine but not yet verified on CUDA hardware
- [ ] A manual screen reader pass over the GUI and the generated HTML (see `docs/ACCESSIBILITY.md`)
- [ ] Spoken progress announcements in the GUI via a screen-reader speech bridge
- [ ] Harden XML parsing against entity-expansion denial of service
- [ ] Cryptographic hash pinning for downloaded models

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md) for setup, guidelines, and what needs doing. Security issues should go through [SECURITY.md](../SECURITY.md) rather than a public issue.

## License

podharvest is [MIT licensed](../LICENSE). Models it can download each carry their own license — see [`MODELS.md`](MODELS.md) before using any of them commercially.
