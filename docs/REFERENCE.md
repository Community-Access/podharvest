# podHarvest technical reference

This is the full reference: every command, flag, setting and model. If you just want to use the app, start with the [README](../README.md) instead.

[![CI](https://github.com/community-access/podharvest/actions/workflows/ci.yml/badge.svg)](https://github.com/community-access/podharvest/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](../LICENSE)
[![Accessibility statement](https://img.shields.io/badge/accessibility-statement-blueviolet)](ACCESSIBILITY.md)

**Archive any RSS/Atom/podcast feed as Markdown, HTML, plain text and JSON, download every enclosure, and transcribe the audio on your own machine.** No account and no data leaving your computer by default. Cloud providers are available if you want them, but only with your own API key and only when you pick a cloud model.

Built and tested against real-world feeds such as [ACB Diabetics in Action](https://acbda.org/podcast) (`https://acbda.org/feed`).

> **Project status:** the full pipeline described below - feed discovery, parsing, rendering, downloading, transcription, and accuracy benchmarking - is implemented and has been run end-to-end against real feeds. See [Roadmap](#roadmap) for what's still open.

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Command-line usage](#command-line-usage)
- [Finding a podcast](#finding-a-podcast)
- [Working on local files](#working-on-local-files)
- [The desktop GUI](#the-desktop-gui)
  - [Two sources](#two-sources)
  - [The library](#the-library)
  - [Reading a transcript](#reading-a-transcript)
  - [The Tag and Chapter Editor](#the-tag-and-chapter-editor)
  - [Not doing the same work twice](#not-doing-the-same-work-twice)
- [Supported on-device models](#supported-on-device-models)
- [The September 2026 review](#the-september-2026-review)
- [Validating accuracy and comparing models](#validating-accuracy-and-comparing-models)
- [Checking an install](#checking-an-install)
- [Settings reference](#settings-reference)
- [Portable app space](#portable-app-space)
- [Accessibility](#accessibility)
- [Building a standalone installer](#building-a-standalone-installer)
- [In-app help](#in-app-help)
- [The rest of the documentation](#the-rest-of-the-documentation)
- [Support](#support)
- [Contributing](#contributing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

## Features

- **Rich feed extraction** - full episode text (not just the truncated summary), authors, categories, chapters, funding links, and every enclosure. Point it at a show's web page and it finds the feed; paginated archives are followed and merged.
- **Four output formats per episode** - Markdown, sanitized HTML, plain text, and structured JSON (CSV export too).
- **Verified enclosure downloads** - audio, video, images and documents are sorted into separate folders per feed. Transfers are resumable across runs, rate-limitable, and checked against the length the server declared, so a truncated or duplicated download fails loudly instead of being recorded as complete.
- **On-device transcription** - pick from multiple ASR engines (Whisper, Parakeet, Canary, Vosk, Moonshine); the app recommends the best one for *your* hardware automatically.
- **Speaker diarization & timestamps** - toggle "who's speaking" labels and per-line/per-word timestamps independently, with a choice of three diarization backends (`pyannote`, PyTorch-free `sherpa-onnx`, or NVIDIA `nemo-msdd`).
- **Optional transcript enrichment** - an on-device LLM pass (Phi-3.5, Llama 3.2, Nemotron-Mini, Mistral) for punctuation cleanup, summaries, and chapter titles.
- **Hardware-aware model advisor** - probes your CPU, RAM, and GPU (CUDA/ROCm/Metal) and recommends a model that will actually run well, with a CPU-only fallback always available.
- **Fully portable** - models, caches, logs, and config all live in one self-contained folder that can travel on a USB stick; nothing is installed into your home directory or global Python environment unless you choose the default location.
- **Two front ends, one engine** - a full wxPython desktop GUI and a scriptable CLI, both driven by the same settings file and pipeline.
- **Two sources, one pipeline** - a podcast feed, or audio already on your machine. Local files go through the same model selection, transcription, summarising, chapter inference and reuse rules as a harvested episode; `harvest.transcribe_all` is shared by both routes rather than reimplemented for either. This makes podHarvest usable as a standalone MP3 tag and chapter editor with transcription attached.
- **Rich, persistent settings** - output folder, episode limits (a number, or "all"), download filters, ASR/enrichment choices, and output formats all persist between runs, shared by the CLI and the GUI.
- **A library you can come back to** - open podHarvest and everything you have harvested is listed: the podcast, the episode, what you have for each. Play it, read its transcript, or edit its tags and chapters, without a run in progress.
- **A player, not just a transcriber** - play any episode or local file from the main window with rewind, forward, volume, mute and speed. The speed list is a setting: 0.25x to 5x, defaulting to 0.5x-3x. Where you stopped is remembered per file and offered back.
- **Full tag and chapter editing** - twenty-six tag fields plus cover art, and chapter markers you can add, delete, retime and nudge by ear against the audio.
- **Nothing is generated twice** - a re-run keeps existing transcripts, takes the publisher's own when a feed offers one, and keeps chapter markers a person already wrote.
- **Keyboard-first and screen-reader-aware** - every window answers F1, every control explains itself, and there is an [accessibility statement](ACCESSIBILITY.md) that states plainly what has been verified and what has not.

## Quick start

### Windows, zero setup

```bat
run.bat gui
```

The first run creates a local virtual environment (`.venv`) next to the script, installs the minimal base requirements (just wxPython - everything else installs on demand), and launches the app. Re-run `run.bat` any time; it only sets up once.

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

Requires Python 3.10+. The core pipeline runs on the standard library alone - `wxPython` is only needed for the GUI, and every ASR engine installs on demand the first time you use it.

**Paste the show's web page, not just its feed.** podHarvest looks for a feed link on any HTML page you give it, so `https://acbda.org/podcast` works as well as `https://acbda.org/feed`.

**New to podHarvest?** [`GETTING_STARTED.md`](GETTING_STARTED.md) walks through installing, your first fetch, and your first transcription step by step.

## Command-line usage

Running `podharvest`/`main.py` with no arguments always prints full usage instead of doing anything surprising:

```text
python main.py
usage: podharvest [-h] [--version] [--app-dir PATH] [-v] [-q] [--log-file PATH] <command> ...

  fetch       Download and convert a feed (and its enclosures).
  local       Transcribe, summarise and chapter audio you already have.
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

# Work on audio already on this machine: a folder, subfolders included
python main.py local "D:\Lectures"

# Specific files, with a chosen model
python main.py local one.mp3 two.m4b --engine faster-whisper --model small.en

# Transcripts into <output>/Local files instead of beside each audio file
python main.py local "D:\Audio" --no-beside -o D:\Library

# Just list what is there and what it already has; write nothing
python main.py local "D:\Audio" --no-transcribe

# See what hardware you have and which ASR model podharvest recommends
python main.py hardware
python main.py hardware --json

# View or change persisted defaults
python main.py settings --show
python main.py settings --set output_dir=D:\Podcasts --set episode_limit=10
python main.py settings --reset
```

Every subcommand accepts `-v`/`-vv` for more detailed logs, `-q` for warnings-only, `--log-file PATH` for a persistent log, and `--app-dir PATH` to point at a different portable app space.

## Finding a podcast

### Searching

`podharvest.directory` is a client for Apple's iTunes Search API — free,
keyless, and the same directory the podcast apps use. It is adapted from QUILL
Cast's (`quill/core/podcasts/itunes_search.py`), with the storefront list from
`quill/core/podcasts/apple_podcasts.py`, so the two programs find the same
shows. Requests go through podHarvest's own `net.HttpClient` rather than
urllib, which brings the retries, timeout, rate limit and user agent every
other request in the program already uses. HTTPS is checked before every call.

| Control | What it sets |
|---|---|
| Podcast name | Apple's `term` |
| Match against | `attribute`: unset (everything), `titleTerm`, `authorTerm`, `keywordsTerm`, `descriptionTerm` |
| Country | `country`, the storefront code |
| How many | `limit`, 1-200 |
| Include explicit shows | Off sends `explicit=No`; on sends nothing, because filtering unasked is its own kind of wrong |

Twenty-five storefronts are offered by name, defaulting to the United States.
Apple has far more; any two-letter code it recognises can be put straight into
`itunes_country` in the settings file and will be used, so the menu is a
convenience rather than a limit.

A `podcasts.apple.com` link is recognised and resolved to a feed address via
`lookup`, so a shared web link works anywhere a feed address is asked for.

### Browsing without harvesting

**Show episodes** parses the feed and lists its episodes — number, title,
publication date, length, and whether each has audio or a published transcript
— and downloads nothing. The list uses its own column headings
(`_BROWSE_COLUMNS`), because these episodes are not on disk and a heading
promising what you have would be wrong in every row. The transport is switched
off for the same reason. The episode filter is applied here too, so what the
list shows is what Start would actually take.

### Importing an OPML list

`podharvest.opml` reads the format podcast apps use to exchange lists of
shows. The parsing rules come from QUILL Cast's importer
(`quill/core/podcasts/opml.py`), so both programs read the same files the same
way -- including the parts of the format that are easy to get wrong:

- `isComment="true"` means the author parked that entry, and the spec says to
  skip it. Importing one turns somebody's disabled feed back on behind their
  back. Only the literal `"true"` counts; the attribute is a string.
- An outline with no `xmlUrl` is a folder, not a show. Its name joins the
  folder path of everything under it.
- `title` beats `text`, and the feed address is the last resort, so a row is
  never blank.
- `description` is OPML's spelling and `summary` is what some exporters write.
  Whichever is present is taken.
- `category` is kept verbatim rather than split, because OPML allows both it
  and nested outlines, and splitting loses the difference between one category
  written `/News/Local` and two separate ones.

Duplicates are removed by feed address -- case-folded, trailing slash ignored
-- which is the same rule the favourites list uses, so a show imported here and
one added there are recognised as the same show.

**Refused rather than parsed:** a document carrying a `DOCTYPE` (the doorway to
entity-expansion and external-entity attacks; no genuine podcast list has one),
a list fetched over plain HTTP (a list of feed addresses that can be rewritten
in transit is one that can point podHarvest somewhere else), and a file larger
than 16 MB.

### Favourites

`podharvest.favorites` keeps a list in `<app-space>/config/favorites.json`,
written atomically via a temporary file so an interrupted write cannot destroy
it. Entries are identified by feed address, case-folded and with any trailing
slash removed — the same show under two names is one favourite.

**It is deliberately not a subscription list.** Nothing in the module imports
an HTTP client, and a test asserts that: no polling, no scheduling, no
downloading, no notifications. Removing a favourite removes the bookmark and
touches nothing on disk.

## Working on local files

podHarvest's second source. Everything after the download is file-level work --
transcribe, summarise, infer chapters, write tags -- and none of it needs a
feed, so none of it requires one.

**In the GUI:** set **Source** to **Local files** (or press Ctrl+O / Ctrl+Shift+F,
which switch for you), add files or a folder, and press **Start on these files**.
The added files appear in the Episodes list straight away with what each already
has, so playing and editing work before any run.

**On the command line:** `podharvest local <paths...>`.

| Option | Meaning |
|---|---|
| `--no-transcribe` | List what was found and stop; write nothing |
| `--engine`, `--model` | Which ASR engine and model to use |
| `--beside` / `--no-beside` | Transcript next to the audio (default), or in `<output>/Local files/transcripts` |
| `--no-recurse` | Given a folder, do not look in its subfolders |
| `-o DIR` | Library folder; only used with `--no-beside` |
| `--timestamps` / `--no-timestamps` | Timestamps in the transcript |
| `--speakers` / `--no-speakers` | Speaker labels via diarization |
| `--hf-token` | Hugging Face token for the gated pyannote models |

### What it accepts

`.mp3 .m4a .m4b .mp4 .aac .ogg .oga .opus .flac .wav .wma .aiff .aif .webm`

Wider than the set podHarvest can *tag* (`.mp3 .m4a .m4b .mp4`): transcribing a
`.wav` is perfectly reasonable even though there is nowhere on it to store a
chapter marker. Files it does not recognise are skipped with a line in the log,
never silently.

A folder is walked depth-first in sorted order, subfolders included unless
`local_recurse_folders` is off. Duplicates are dropped, so adding both a folder
and a file inside it processes that file once. A folder holding more than
`localfiles.MAX_SCAN` (5000) audio files stops at that many and says so in the
log rather than walking what may be a whole drive.

### Where the output goes

Beside the audio by default: `lecture.mp3` produces `lecture.md`, `lecture.txt`
and, if enabled, `lecture.srt` / `lecture.vtt` in the same folder. That keeps a
file and its transcript together if the folder is later moved.

With `local_transcripts_beside_file` off, they go to
`<output_dir>/Local files/transcripts/<slug>.md` instead, and podHarvest never
writes into your own folders. The name is slugified there because that folder is
shared; beside the audio it is the audio file's own stem.

Chapter markers and tags are written into the audio file either way -- that is
where they belong, and for an MP3 only the tag block is rewritten.

### What it never does

Copy, move, rename, convert or delete your files. **Remove** takes a file out of
the list, not off the disk. The only writes to your audio are the tag and
chapter edits you ask for.

### Shared with the feed route

`podharvest.localfiles.run_local` builds `LocalEpisode` objects -- the minimal
duck-type `transcribe_all` reads -- and hands them to
`podharvest.harvest.transcribe_all`, the same function `run_harvest` calls. The
only local-specific piece is the `layout` hook, which answers "where does this
transcript go, and what is it called". Reuse, summaries, chapter inference,
progress reporting, cancellation and per-file error isolation are therefore
identical by construction rather than by intention.

## The desktop GUI

`python main.py gui` (or `run.bat gui`) opens a resizable window with:

- A **feed** section (URL + output folder, with a folder browser).
- An **options** section: download enclosures on/off, transcribe on/off, and an episode limit spinner (0 = all).
- A **transcript options** panel: model picker (auto-populated from the hardware advisor), timestamps toggle, and speaker-identification toggle - all disabled until transcription is turned on.
- A **hardware** panel showing your CPU/RAM/GPU summary and the recommended model, with a re-detect button (Ctrl+D). If detection fails, transcription is switched off with an explanation and the rest of the app keeps working.
- **Start/Cancel** buttons, a progress bar, and a readable activity log (Ctrl+L). The log does not announce itself - see [Accessibility](#accessibility).

- A **Tag and Chapter Editor** (**Ctrl+T**, or Enter on an episode row): six pages holding every tag the audio file can carry plus its chapter markers, with a player for judging boundaries by ear. See below.

A File/View/Help menu bar lists every action and its shortcut: **Ctrl+R** start, **Esc** cancel, **Ctrl+L** activity log, **Ctrl+D** re-detect hardware, **Ctrl+T** edit tags and chapters. **F1** anywhere explains the window you are in and the control you are on.

Every field you change is remembered (via the same `settings.json` the CLI uses) and restored the next time you open the app.

### Two sources

At the top of the window, a `wx.RadioBox` labelled **Source** with **Podcast
feed** and **Local files**. A radio box rather than tabs or check boxes: it is
announced as one named group with a position ("Source, Podcast feed, 1 of 2"),
arrow keys move between the two, and there is no state where both or neither is
chosen.

Changing it swaps three things together, so the window never describes work it
is not about to do:

- the input box below (Feed URL, or the Add/Remove buttons),
- the Start button's label and its accessible name,
- what the Episodes list is showing, and the list's column headings.

The choice is saved as `source_mode` and restored at launch.

### The library

With no run in progress, the Episodes list is your library rather than a
progress view. It is built at startup, rebuilt when a run finishes, and can be
rebuilt on demand with **Ctrl+Shift+R**.

Each show folder's `feed.json` is the source: a harvest already writes it, and
it records every episode with the path of what was downloaded. That beats
scanning filenames, because the naming template is configurable and a scanner
inferring titles from slugs would get them wrong for exactly the shows with
interesting titles. A folder with no `feed.json` — an interrupted first run, or
one assembled by hand — still lists its audio, named from the file.

The columns are Podcast, Episode, What you have, Published and Length. The
headings change when a run takes the list over (to #, Episode, Status, Progress,
Time), because a screen reader reads the heading with every cell.

An episode whose file has since been deleted is listed without audio rather than
offering a Play button that cannot work.

### Reading a transcript

**Ctrl+Shift+T** on a library row opens its transcript. Read-only — the
transcript is a record of what was said, and an editable box would invite
changes with nothing to say the file no longer matches the audio — with a Find
box that reports which occurrence you are on and wraps at the end. **Copy all**
puts the whole thing on the clipboard; **Open the file** hands it to whatever
your system uses for text.

Files larger than 8 MB are refused with a reason rather than loaded: that is far
past any real transcript, and a reader that hangs is worse than one that says no.

### The Tag and Chapter Editor

Opened with **Ctrl+T**, or Enter on a row in the Episodes list. With no episode
selected — including after a restart, when the list is empty — it opens a file
picker on the output folder instead, so it always reaches a file.

Six pages, moved between with Control+Tab:

| Page | What is on it |
|---|---|
| Main | Title, subtitle, artist, album, album artist, track and disc (number of total), genre, year |
| Details | Original release date, comment, lyrics or transcript, grouping, language, BPM, compilation flag |
| Publishing | Composer, conductor, publisher, copyright, encoded by, ISRC |
| Sort order | Sort title, artist, album and album artist — these change filing order, not what is displayed, and writing one moves the file to ID3v2.4 |
| Cover art | The embedded image: described in words first, then shown; load, save out or remove |
| Chapters | The chapter list, the transport, and the editing tools |

Chapter operations: **Add** (at the playhead or a typed time; past the last
chapter's end it appends), **Delete** (the marker only — the audio is never
cut, and unlike a merge it works on the first and last chapters),
**Edit** (title and exact start and end, plus the Podcasting 2.0 link and
image), **Preview** (play this chapter and stop at its end), and **nudge**:
Alt+Left and Alt+Right move the selected chapter's start by one step,
Alt+Shift with them moves ten, and **Hear boundary** plays three seconds
before the marker and two after it. The step is chosen from 100 ms to 10 s and
remembered for next time.

The transport: Play, Stop, Rewind and Forward ten seconds, volume, mute, and
speed — the same list `playback_rates` gives the main window, so the two agree.
Where the platform's media backend will not play at a particular speed,
podHarvest says so, naming that speed, rather than leaving the control looking
as though it worked.

Formats: MP3 in full, and M4A/M4B/MP4 for every tag those containers have an
atom for. Anything else is refused rather than half-supported.

### Not doing the same work twice

| Setting | Default | What it does |
|---|---|---|
| `reuse_transcripts` | `true` | Skips an episode whose transcript is already on disk. A re-run carries on where it stopped. The file is size-checked, so an interrupted run is redone rather than treated as finished. |
| `use_feed_transcripts` | `true` | Takes the publisher's own `<podcast:transcript>` when the feed offers one, instead of transcribing words that already exist. When several formats are offered, the most capable wins — JSON, then WebVTT, then SRT, then HTML — rather than whichever the publisher happened to list first. |
| `reuse_chapters` | `true` | Keeps chapter markers already in the file, or timestamps written in the show notes, instead of asking a model for new ones. Those carry titles a person wrote. |

Turn any of them off to force a fresh pass — a better ASR model, changed
settings, or a transcript you did not like. Reusing a transcript never skips
the *summary*: an episode whose transcript already existed may never have had
one, so the enrichment step still runs.

| Setting | Default | What it does |
|---|---|---|
| `preview_volume` | `70` | Playback volume, 0 to 100. Shared by the main window's player and the editor's. |
| `preview_muted` | `false` | Whether playback starts muted. |
| `skip_back_ms` | `10000` | How far Rewind and Ctrl+B jump back, in milliseconds. Clamped 1000-300000. |
| `skip_forward_ms` | `10000` | How far Forward and Ctrl+F jump on. Separate from rewind: skipping an advert break usually wants a bigger jump than re-hearing a sentence. |
| `remember_playback_position` | `true` | Remember the playhead per file and offer it back. Positions in the first ten seconds or the last thirty are not stored -- neither is a place you were coming back to. Kept in `playback-positions.json` beside the settings, bounded to 500 entries. |
| `media_health_last_notice` | `""` | The FFmpeg state already reported, so a missing tool is mentioned once rather than at every launch — and again if it comes back and goes missing a second time. |

## The September 2026 review

A full review of the engines, the acquisition pipeline and the window flows
is written up in [CODE-REVIEW-2026-09.md](CODE-REVIEW-2026-09.md): what was
found, what was fixed, which models were added and — as importantly — which
were considered and not added, and why. It is the record to read before
proposing a new provider.

## Supported on-device models

Everything below runs locally and is downloaded on first use straight into the portable app space. Cloud providers are available too but are strictly opt-in and need your own API key: see the "Optional cloud models" section. With no key configured, podHarvest makes no call to any transcription service (see [`MODELS.md`](MODELS.md) for the full catalogue, licenses, and technical notes).

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

The hardware advisor (`podharvest hardware`, or the GUI's Hardware panel) always picks a model that fits your machine's CPU/RAM/GPU budget, and every engine has a CPU-only fallback so transcription never *requires* a GPU. Every model listed above is backed by an implemented engine - the catalogue and the dispatcher are kept in step, and there is a test asserting it.

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

- **Speed** - real-time factor (e.g. `26.9x` means an hour of audio transcribes in about 2m14s).
- **WER / accuracy** - Word Error Rate and its complement, computed via classic DP word-alignment (substitutions + deletions + insertions ÷ reference word count), the same metric used by academic ASR benchmarks like LibriSpeech leaderboards.

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

## Azure MAI-Transcribe-2 (preview)

Microsoft's MAI-Transcribe-2 through the Azure Fast Transcription API, for
English and Spanish. It labels speakers and returns word-level timings in the
same request, and takes a list of terms to bias recognition towards -- worth
setting for a show with recurring guests, where every engine mangles the same
handful of names.

Implemented from `MAI-TRANSCRIBE-2-PRD.md`, and its preview posture is the
design rather than a caveat:

- **Off until you turn it on**, and it stays off across updates. A key left
  over from trying it once does not put a preview service back in the picker.
- **Never a default and never a silent fallback.** Unticking one box removes
  it from the model list immediately, which is the quick way out if the
  preview regresses.
- **No price or speed is claimed.** Microsoft has not published a MAI-specific
  rate, so podHarvest shows none rather than a confident wrong number.
- **The API version is a setting**, pinned rather than floating, so a change
  to a preview API can be answered without waiting for a new release.
- **It does not degrade silently.** If speaker labels or word timings were
  asked for and did not come back, the log says so.

### What it needs

Azure wants more than a key: the endpoint of *your* Speech resource and a
region that offers the model. **Settings ▸ Azure MAI-Transcribe** asks for
both, and **Check this is set up** names everything still missing at once --
switch, key, endpoint, region -- rather than letting you discover them one
failed request at a time. It sends nothing to Azure; it is a configuration
check, not a connection test.

| Setting | Meaning |
|---|---|
| `azure_mai_enabled` | The switch. Off by default |
| `azure_speech_endpoint` | `https://your-resource.cognitiveservices.azure.com` |
| `azure_speech_region` | Microsoft lists `eastus`, `northeurope`, `southeastasia`, `westus`. Another region is warned about, not refused -- availability changes |
| `azure_speech_api_version` | Pinned; default `2025-10-15` |
| `mai_language` | `auto`, `en` or `es`. Automatic sends no locale at all, because a strong hint towards the wrong language is worse than none |
| `mai_transcribe_style` | `clean` reads well; `verbatim` keeps every false start |
| `mai_diarize` | Ask for speaker labels |
| `mai_word_timestamps` | Word-level rather than phrase-level timings |
| `mai_phrases` | Terms to bias towards. Hints, not substitutions |

The key goes in the operating system's credential store with every other
provider's, never in the settings file.

### Reliability

Throttling, gateway errors and timeouts are retried with exponential backoff,
up to four attempts. Nothing else is: a bad key, a wrong region, malformed
audio or an oversized file all give the same answer more slowly the second
time, so they fail at once. Audio over Azure's documented limit is refused
before the upload starts rather than after it.

## Optional cloud models

podHarvest runs entirely on your machine by default and needs no account with anyone. If you
want to, you can add your own API key for a cloud provider and pick its models instead.
Nothing is uploaded unless you add a key **and** select a cloud model.

Add keys in **Settings** (`Ctrl+,`), or set an environment variable such as
`PODHARVEST_OPENAI_KEY` - the variable always wins, and is never overwritten from the UI.
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
it for speed on a slow machine, or for Gemini's speaker labelling - which worked out a
speaker's actual name from the audio rather than numbering the voices.

**On upload size.** Audio is re-encoded to 16 kHz mono Opus before upload, which is the
format these models listen to anyway, and which turns a 54 MB episode into about 7 MB - so a
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

`write_chapters` works out where each topic starts and ends from the transcript's own segment
timestamps rather than from the model's guesswork; any time falling outside the episode is
discarded. The result is written above the summary in `<episode>.summary.md`.

A model that does not understand the task emits one chapter per fixed interval, producing
something that looks like a contents list while carrying no information. Chapters are spaced
to roughly one per four minutes, and a set where 70% or more of the gaps are identical is
discarded entirely with a log line explaining why. The on-device model frequently fails this
bar; the cloud summary models do noticeably better.

`chapters_into_audio` (default on) additionally writes them into the audio file as chapter
metadata, which podcast players expose as a navigable list. Supported for `.mp3`, `.m4a`,
`.m4b`, `.mp4`, `.ogg` and `.opus`; other containers are skipped rather than re-muxed.

The audio stream is copied with `-codec copy`, so the rewrite is lossless and adds roughly
eighty bytes. It goes to a scratch file that only replaces the original once ffmpeg has
succeeded, so an interrupted write cannot truncate an episode.

Chapters need a model that returns per-segment timestamps. The OpenAI GPT-4o transcribe models
return plain text only and are skipped with a log line saying so.

## Where the prices come from

Cloud cost estimates are indicative, not a quote. Only OpenRouter publishes prices through an
API; OpenAI, Google and Ollama Cloud do not, so their per-minute rates are copied by hand and
go stale silently when a provider changes them. `cloud.PRICES_CHECKED` records when.

Because of that:

- Costs are rounded to the precision the input actually supports. "$10", not "$9.72", which
  would imply an accuracy a hand-copied rate does not have. Small amounts read as "a few
  cents" rather than a false decimal.
- Every stale figure states the date it was checked and links to the provider's current
  pricing page.
- Where a provider does publish prices (OpenRouter), they are read at runtime, cached for the
  session, and the description says the figure came from the provider. A failed lookup falls
  back to the stored value rather than breaking the model list.

If you are about to spend real money on a large back catalogue, check the provider's own page.
The estimate exists to stop you being surprised, not to be a bill.

## A note on the name

The product is written **podHarvest**. The capital H is deliberate: a screen
reader given "podharvest" pronounces it as one unpronounceable run of letters,
while "podHarvest" is spoken as the two words it actually is.

The lowercase form is kept everywhere the name is typed rather than spoken, and
changing it would break something:

| Lowercase, unchanged | Why |
|---|---|
| `import podharvest` | Python package name |
| `podharvest` command | Case-sensitive on Linux and macOS |
| `~/.podharvest` | Renaming would orphan downloaded models and settings |
| `PODHARVEST_*` | Environment variables are conventionally uppercase |
| The repository URL | Already published |

In code, `podharvest.DISPLAY_NAME` holds the spoken form so it is defined once.

## Checking every model downloads

`scripts/check_model_downloads.py` downloads every model in the catalogue and
checks each one three ways: it arrives, `verify_model` accepts it, and
`is_downloaded` still says yes on a *second* look from the manifest -- which
is the check that used to fail, because the download verified a list it had
just built while everything afterwards read the manifest instead.

It is not a unit test. It talks to Hugging Face and Alphacephei, moves tens of
gigabytes, and takes about an hour. It exists because the interesting failures
in model acquisition are exactly the ones a mocked test cannot see: the bug
that prompted it -- a healthy download rejected as "missing or truncated
.gitignore" -- passed every unit test in the suite.

```bash
PODHARVEST_HOME=S:/model-test python scripts/check_model_downloads.py
PODHARVEST_HOME=S:/model-test python scripts/check_model_downloads.py --only vosk
PODHARVEST_HOME=S:/model-test python scripts/check_model_downloads.py --max-gb 2
```

Point `PODHARVEST_HOME` at somewhere with room; the whole catalogue is about
37 GB before deduplication.

### Last full run

All 20 models in the catalogue downloaded and verified: 8 faster-whisper, 2
Parakeet, 1 Parakeet-ONNX, 1 NeMo Canary, 2 Vosk, 2 Moonshine and 4 llama-cpp
enrichment models. That covers all seven distinct routes through `acquire` --
whole-repo snapshot, single named file, zip archive, the ONNX triple-file
layout, and the three verification branches they land in.

## Checking an install

### `podharvest doctor`

```
podharvest doctor [--engine ENGINE]
```

Prints, in order: the version; whether this is a frozen build; the Python
version; the app-space and isolated-package paths; whether pip can be reached
at all; whether FFmpeg is present; and then, per engine, each package with one
of three answers.

| Answer | Meaning |
|---|---|
| `ready` | Downloaded and imports cleanly |
| `not downloaded yet` | Run that engine once, or press **Download model** |
| `downloaded but will not load - <error>` | A packaging bug. The error is the import's own words |

Exit status is 1 only for the third answer. `not downloaded yet` is the normal
state of every engine you have not used, so counting it as a fault would report
problems on a perfectly healthy install; it is reported as information instead.
The third answer is the one worth sending in: it means a file is on disk,
passes every filesystem check, and still cannot run.

### Narrowing the model list

The **Show models that run** group filters the picker: **All**, **On this
machine**, **In the cloud**, or **Already downloaded**. The last is the quick
way back to a model you have used before, with nothing to wait for.

Each option is enabled on its own terms rather than the group as a whole, and
the group itself stays disabled until hardware detection has found any model at
all. **In the cloud** needs an API key; **Already downloaded** needs something
to have been downloaded; **All** only means something once more than one source
exists. An option that is offered and then cannot work is worse than one that is
absent: by keyboard it is a stop that accepts your selection and then shows an
empty list with nothing saying why. If a filter you are sitting on is switched
off — a key removed, say — the selection moves rather than silently emptying the
list.

### In the GUI

A line beside the model description says whether the selected model is ready,
and names what is missing when it is not — the engine's packages and the model
weights are separate downloads and either can be absent on its own. The
**Download model** button fetches both, on a background thread, using the same
calls a run makes so the two cannot disagree about what "downloaded" means.

### What had to be fixed to make any of this work

Three faults, each of which made on-demand downloads impossible in the packaged
build while being invisible in a source checkout. They are recorded here
because each is an easy mistake to make again.

**`sys.executable` is not a Python interpreter in a frozen build.** It is
`podharvest.exe`. `[sys.executable, "-m", "pip", ...]` therefore ran
`podharvest.exe -m pip install ...`, which reached podHarvest's own argument
parser and failed with `invalid choice: 'pip'` — logged as pip output, so it
read as a pip problem. `acquire.pip_command` now branches on `sys.frozen` and
the frozen build routes installs through a `_pip` passthrough handled before
argparse (pip's own `--target` and `--index-url` would otherwise be eaten).

**pip cannot be frozen.** Bundled into the PyInstaller archive it imports fine
and then dies on the first install: its vendored `distlib` looks up a resource
finder by the type of the loader that imported it, and PyInstaller's
`FrozenImporter` is not a loader type it knows. pip is therefore shipped as
plain files in `_internal/pip_runtime` and put on `sys.path` at the moment it
is needed.

**A frozen build is a host, not just a program.** It pip-installs
faster-whisper, NeMo, Vosk and their dependencies into a folder PyInstaller's
analysis never sees, and those packages import whatever they like. Two
consequences: the whole standard library is bundled (`No module named
'asyncio'`, reported against faster-whisper, was the first symptom), and
`python3.dll` ships alongside `python313.dll` because wheels built against the
limited API — PyAV, and so faster-whisper — link against the forwarder that
CPython installs but PyInstaller does not.

There is a fourth, smaller one. Python caches what it finds in each `sys.path`
entry, and the isolated package folder goes on the path *before* the install,
when it is empty. `importlib.invalidate_caches()` after installing is what
stops a perfectly good install being reported as "installed but still not
importable".

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
| `source_mode` | Which source the main window opens on: `feed` or `local` |
| `itunes_country` | Which of Apple's stores podcast searches ask. Any two-letter code Apple recognises; default `us` |
| `search_limit` | How many results a search asks for, 1-200 |
| `episode_match` | Only episodes whose titles contain these words (any order, case insensitive). Applied before `episode_limit` |
| `sound_cues` | Short tones as a run proceeds. Off by default |
| `local_transcripts_beside_file` | Local-file transcripts next to the audio (default), or in `<output>/Local files` |
| `local_recurse_folders` | Adding a folder includes its subfolders (default on) |
| `playback_rates` | The speeds the player offers, as a list. 0.25-5.0; 1.0 is always kept. Default `[0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]` |
| `preview_volume`, `preview_muted` | Player volume, remembered across sessions and shared with the editor |
| `skip_back_ms`, `skip_forward_ms` | How far Rewind and Forward jump, separately |
| `remember_playback_position` | Pick an episode up where you left it |
| `reuse_transcripts`, `use_feed_transcripts`, `reuse_chapters` | Whether existing work is kept rather than redone |

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

Accessibility is a functional requirement here, and this section is deliberately specific about what has been verified versus what has not. **Version 1.0.0 has been through a manual screen reader pass with NVDA, JAWS and Narrator, covering the desktop app, a full run, the generated HTML and the command line, with no problems reported.** That is one tester on Windows; VoiceOver on macOS has not been exercised. [`ACCESSIBILITY.md`](ACCESSIBILITY.md) records exactly what was covered and what remains untested.

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

Passing `-Inno` additionally compiles [`installer/podharvest.iss`](../installer/podharvest.iss) with [Inno Setup](https://jrsoftware.org/isinfo.php) into `dist/installer/podharvest-<version>-setup.exe` - a conventional installer with a Start Menu entry, optional desktop icon, and uninstaller. Unlike the portable zip, the installed copy correctly stores its models/cache/config under the current user's profile rather than trying to write into Program Files.

**Inno Setup 7 is required**, not 6, for two reasons that are about this program in particular:

- `SetupArchitecture=x64` produces a genuine 64-bit installer to match the 64-bit application it wraps, and brings high-entropy ASLR with it. Inno Setup 6 has no such directive and would fail on it.
- Extended-length path support removes the `MAX_PATH` limit throughout Setup and Uninstall. podharvest builds deep trees out of titles a publisher chose — `<output>/<show>/transcripts/<long-episode-slug>.md` — and long-path limits are named in [SECURITY.md](../SECURITY.md) as a real source of bugs here.

The build script checks the version with `ISCC --version` (itself a 7-only option) and says so plainly rather than letting the compile fail later on an unknown directive. It compiles with `--messages-jsonl`, which puts errors and warnings on stderr as JSON Lines for a CI job to read without parsing prose.

Version 7 installs alongside 6 rather than replacing it, and winget puts it under `%LOCALAPPDATA%\Programs\Inno Setup 7`; the script looks there first.

The resulting `podharvest.exe` (either build) keeps all of its models/cache/config in one folder - for the portable build, copy that folder anywhere (including a USB drive) and it keeps working.

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
  harvest.py               Orchestrates feed -> render -> download -> transcribe (what fetch/GUI Start call); transcribe_all is shared with the local-files route
  localfiles.py            The second source: audio already on this machine, given the same treatment as an episode
  library.py               Reads the output folder back as a browsable library
  reader.py                Read-only, searchable transcript window
  editor.py                The Tag and Chapter Editor
  player.py                The transport: play/pause, rewind, forward, volume, speed
  tags.py                  Tag and chapter reading/writing (adapter over audio_tags_core)
  audio_tags_core.py       Vendored byte-identical from QUILL: tag fields, cover art, CHAP/CTOC
  reuse.py                 What already exists, so nothing is produced twice
  reuse_core.py            Vendored byte-identical from QUILL: transcript ranking, show-note chapters
  positions.py             Where you stopped in each file
  help.py                  F1 help: what this window is for, what this control does
  help_audit.py            The build gate that keeps every control explained
  a11y.py                  Accessible names and font-relative sizing
  feedback.py              The bug report the Help menu builds
  media_health.py          Whether FFmpeg is present, and what its absence costs
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

## In-app help

**F1** answers anywhere in the program: what the window is for, then the focused
control's name, the sentence written for it, and how to drive a control of that
kind. Every focusable control carries a sentence, units and defaults included --
84 construction sites at the time of writing, and the audit prints the count so
the figure never has to be guessed from a document.

The implementation is worth knowing if you are extending the program:

- `podharvest/help.py` holds the engine and `PURPOSES`, the catalogue of window
  purposes keyed by title (prefix-matched, so a title carrying live data still
  resolves). A window with no authored purpose falls back to an honest generic
  sentence rather than to silence.
- Help is authored **inline at the construction site**, with
  `SetToolTip`/`SetHelpText` or `help.explain(ctrl, text)`, which sets both.
  That is the only place an audit can verify it.
- `podharvest/help_audit.py` AST-scans the wx modules and fails the build on a
  control with nothing authored. Run it with
  `python -m podharvest.help_audit`, and re-record the reviewed snapshot with
  `--write`.
- `help.ensure_help_provider()` is called by `help.install()`. Without a
  `wx.HelpProvider`, every `SetHelpText` in the program silently stores nothing
  and `GetHelpText` answers `""` — measured, not assumed.

Adding a window means calling `help.install(self)` in its constructor and adding
its title to `PURPOSES`. A test enforces the first by walking every
`wx.Dialog`/`wx.Frame` subclass.

## The rest of the documentation

| Document | What it is for |
|---|---|
| [Your first podcast](GETTING_STARTED.md) | One complete run, start to finish, for somebody who has just installed it |
| [README](../README.md) | Everyday use: playing, reading, the keyboard, common problems |
| This reference | Every command, flag, setting and output format; the library, the editor, the reuse rules; building an installer |
| [Model catalogue](MODELS.md) | Each model's accuracy, speed, size and licence |
| [Accessibility statement](ACCESSIBILITY.md) | What has been verified with which screen reader, and what has not |
| [Security policy](../SECURITY.md) | The trust model, and where the real risk is |
| [Contributing](../CONTRIBUTING.md) | How to help, and the gates a change has to pass |
| [Changelog](../CHANGELOG.md) | What changed, and why |

All of them are installed with the program and listed in its Start Menu group.

## Support

**support@community-access.org.**

**Help ▸ Report a bug** builds the report for you — version, platform, FFmpeg,
hardware, the settings that differ from the defaults, and the tail of the
activity log — redacts keys, home folder names and email addresses, and shows
you the whole thing before anything is sent. Nothing leaves the machine unless
you choose to send it; `podharvest/feedback.py` contains no network code and a
test asserts it imports nothing that could reach the network.

Bugs and feature requests can also go to
[GitHub issues](https://github.com/community-access/podharvest/issues).
Security problems go through
[GitHub Security Advisories](https://github.com/community-access/podharvest/security/advisories/new)
instead — see the [security policy](../SECURITY.md).

## Contributing

Contributions are welcome - see [CONTRIBUTING.md](../CONTRIBUTING.md) for setup, guidelines, and what needs doing. Security issues should go through [SECURITY.md](../SECURITY.md) rather than a public issue.

## License

podHarvest is [MIT licensed](../LICENSE). Models it can download each carry their own license - see [`MODELS.md`](MODELS.md) before using any of them commercially.
