# Getting started with podharvest

This is the fastest path from "just downloaded this" to a fully archived, transcribed podcast feed. For the full feature reference see [README.md](../README.md); for the model catalogue see [MODELS.md](MODELS.md); for accessibility details see [ACCESSIBILITY.md](ACCESSIBILITY.md).

## 1. Install

**Windows, no Python experience needed:**

1. Download and unzip the portable release (`podharvest-<version>-win64-portable.zip`), or run the installer (`podharvest-setup.exe`) if you were given one.
2. Double-click `podharvest.exe` (or, if you have the source instead of a build, run `run.bat`).
3. That's it — no separate Python install, no `pip install` required for basic use.

**From source (developers):**

```powershell
git clone <this repo>
cd pod
python -m pip install -r requirements.txt   # just wxPython, for the GUI
python main.py gui
```

Requires Python 3.10+.

## 2. Check your hardware

Before transcribing anything, see what your machine can do:

```powershell
python main.py hardware
```

This prints your CPU/RAM/GPU and the ASR model podharvest recommends for you. Nothing is downloaded yet — models are fetched the first time you actually use them.

## 3. Harvest your first feed

Using the GUI: run `python main.py gui`, paste a feed URL (e.g. `https://acbda.org/feed`) into the **Feed URL** box, and click **Start**.

Using the CLI:

```powershell
python main.py fetch https://acbda.org/feed -o D:\Podcasts
```

When it finishes, look in `D:\Podcasts\<feed-name>\`:

```text
markdown/    html/    text/    json/     <- one file per episode, per format
audio/       video/   images/  documents/  other/   <- downloaded enclosures, sorted by kind
transcripts/                                          <- populated once you transcribe (see below)
index.md    feed.json    downloads.json
```

## 4. Transcribe some audio

```powershell
python main.py fetch https://acbda.org/feed --limit 3 --transcribe
```

- `--limit 3` processes only the 3 most recent episodes (omit it, or use `--limit all`, for everything).
- The first time you transcribe, podharvest installs the ASR engine's Python package automatically (e.g. `faster-whisper`) into its own isolated folder — this can take a minute.
- Control the model with `--engine`/`--model`, e.g. `--engine faster-whisper --model small.en`. See `python main.py hardware` for what's recommended, and [MODELS.md](MODELS.md) for the full catalogue.
- Control transcript layout with `--timestamps`/`--no-timestamps`, `--speakers`/`--no-speakers`, `--timestamp-style`, `--speaker-style`, `--paragraphs`, `--line-width`.

## 5. Compare models before committing to one

Not sure which model is right for your hardware? Benchmark a few directly:

```powershell
python main.py benchmark my-clip.mp3 --model faster-whisper:tiny.en --model faster-whisper:small.en
```

Add `--reference-dir path\to\reference\transcripts` (one `<clip-name>.txt` per audio file) to also get Word Error Rate (WER) and accuracy percentages, not just timing - see the "Validating accuracy" section of [README.md](../README.md#validating-accuracy-and-comparing-models).

## 6. Save your preferences

Whatever you set in the GUI, or pass on the CLI, is remembered:

```powershell
python main.py settings --show
python main.py settings --set output_dir=D:\Podcasts --set episode_limit=10
```

## 7. (Optional) Build a standalone installer

If you're distributing podharvest to other people:

```powershell
./scripts/build_installer.ps1          # portable .zip via PyInstaller
./scripts/build_installer.ps1 -Inno    # also builds a proper Windows installer (requires Inno Setup)
```

See [installer/podharvest.iss](../installer/podharvest.iss) for the Inno Setup script itself.

## Troubleshooting

| Problem | What's happening |
|---|---|
| `fetch` says the pipeline "is not wired up yet" | You're on an old build; update to a version where `podharvest.harvest` exists. |
| Transcription is very slow | Run `python main.py hardware` - you may be on a large/slow model. Try a smaller one with `--model`. |
| GUI says "no transcription model selected" | Hardware detection may still be running; click **Re-detect** and wait for the hardware summary to populate. |
| A model download fails partway | Just re-run the command - downloads resume, and corrupted partial downloads are detected and retried automatically (see `podharvest/acquire.py`'s verification step). |
