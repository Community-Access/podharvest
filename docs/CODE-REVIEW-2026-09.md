# Code review, September 2026

A full-depth review of podHarvest after the 1.0.0 feature push: every engine,
the acquisition pipeline, the network layer, and the window flows. This
document records what was found, what was done about it, and what was
deliberately left alone — because a review whose findings live only in a
commit message is a review the next reader has to re-do.

## Summary

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Four of six engines ignored the model store: double downloads, wrong-repo downloads, readiness lies | High | Fixed |
| 2 | Mixed timezone-aware and naive dates crashed the library sort at startup | High | Fixed |
| 3 | A winget FFmpeg upgrade silently removed FFmpeg from podHarvest | High | Fixed |
| 4 | The Settings dialog outgrew every laptop screen; OK sat below the bottom edge | High | Fixed |
| 5 | API-key captions promised summaries from providers that cannot write them | Low | Fixed |
| 6 | Only `whisper-1` ever asked a cloud provider for timestamps | Medium | Fixed |
| 7 | No sherpa-onnx export offered for Parakeet v3 | — | Recorded as future work |

Alongside the fixes, the model catalogue grew by four: two on-device
(Distil-Whisper large v3.5, Parakeet TDT 0.6B v3) and two cloud (Groq's
Whisper large-v3-turbo, ElevenLabs Scribe).

## Finding 1: one model store, honoured by nobody

`podharvest.acquire` owns downloading: the Download-model button, the doctor,
the readiness line and the "Already downloaded" filter all ask it. But only
two of the six engines actually *loaded* from where acquire wrote.

- **faster-whisper** was handed a model *name* and a `download_root`, which
  makes it use Hugging Face's cache layout (`models--Systran--…`). Acquire
  wrote a plain folder (`whisper/small.en/`). Result: press Download model,
  wait for 1.5 GB, press Start — and watch the same 1.5 GB download again
  into a folder the button never checks. In the other order, a model the
  engine had fetched read as "not downloaded" in the window forever.
- **Parakeet and Canary (NeMo)** called `from_pretrained`, which downloads
  into NeMo's own cache. Acquire's multi-gigabyte snapshot — which contains
  the very `.nemo` checkpoint NeMo wants — was never opened by anything.
- **Moonshine** was the worst of the four: the catalogue's source repos
  (`UsefulSensors/moonshine-tiny`) hold the *PyTorch* weights, and the ONNX
  engine loads different files from a different repo. The Download button
  fetched a hundred megabytes of perfectly verified files that no code path
  could ever open.
- **Vosk** and **parakeet-onnx** were correct, which is what proved the
  design was fine and the wiring was not.

**The fix** is architectural rather than case-by-case: every engine now loads
through `acquire_asr_model`, the way Vosk always did. faster-whisper is given
the downloaded *directory* (which also frees the catalogue from
faster-whisper's built-in name registry — see the v3.5 addition below), NeMo
`restore_from`s the local `.nemo` with `from_pretrained` as the fallback, and
Moonshine's acquisition now fetches the actual ONNX pair from
`UsefulSensors/moonshine`, keeping the repo's own nesting so nothing needs
moving after download.

Verified empirically, not just by tests: moonshine-tiny, tiny.en and the new
distil-large-v3.5 were each downloaded through acquire and then transcribed
audio through their engine from those exact files, and `is_downloaded` agreed
afterwards in both directions.

## Finding 2: two podcasts with different date formats crashed the app

`refresh_library` sorts every episode newest-first. One feed writing
`2026-09-01T10:00:00+00:00` next to one writing `2026-09-01T10:00:00` raised
`TypeError: can't compare offset-naive and offset-aware datetimes` — and the
sort runs at startup, so the window failed to open over a formatting
difference between two publishers. Naive dates are now read as UTC: wrong by
at most half a day, where a crash is wrong by everything.

## Finding 3: winget upgraded FFmpeg and podHarvest lost it

Caught live on the development machine mid-review. winget installs FFmpeg
into a folder named after the version (`ffmpeg-9.0-full_build`) and writes
that versioned path into PATH. On upgrade the folder is replaced
(`ffmpeg-9.0.1-full_build`), open shells keep the old PATH, `shutil.which`
finds nothing — and every FFmpeg feature silently degrades in exactly the way
`media_health.py` warns about. This will happen to real users on every winget
upgrade, forever.

`find_ffmpeg` now falls back to globbing winget's package directory for
whatever version is actually installed. PATH still wins when it works; the
glob is a rescue, not a preference.

## Finding 4: a Settings dialog taller than any screen

1,753 pixels of content on a 955-pixel display. OK and Cancel sat below the
bottom edge of the screen: a keyboard user could enter the dialog and not
leave it, and a magnifier user had no way to know the rest existed. The
content now lives in a scrolled panel capped to 90% of the screen it opens
on; OK and Cancel sit outside the scroller and never move. Tab still reaches
everything — the panel scrolls the focused control into view — so keyboard
navigation is unchanged; only the geometry is.

## Finding 5 and 6: small lies

The API-key captions derived from one flag, so any provider that could
transcribe was labelled "transcripts and summaries" — promising summaries
that Groq, ElevenLabs and Azure cannot write. Now derived from both flags,
with "preview" appended where it applies.

And the OpenAI engine decided whether to request timestamps by checking
`model == "whisper-1"` — a hardcoded name that would have made Groq's Whisper
silently timestamp-less. It now reads `provides_timestamps` from the
catalogue entry, which is where that fact was already recorded.

## The catalogue: what was added, and why

The question asked was "what other transcription models should be added?"
The answer was filtered hard: a model earns a place only if it is
meaningfully better than an existing entry on some axis a listener would
notice — accuracy, speed, price, or language coverage — and only if its
download path could be verified here.

**Added:**

- **Distil-Whisper large v3.5** (on-device, English) — the successor to
  distil-large-v3 already in the catalogue, distilled from four times as much
  audio: measurably more accurate at the same size and speed. Notably, it
  only works because of the Finding-1 fix: faster-whisper's built-in registry
  has never heard of it, and loading by directory is what makes
  registry-unknown conversions usable at all. Downloaded and transcribed here
  as verification.
- **Parakeet TDT 0.6B v3** (on-device, CUDA) — the multilingual successor to
  v2: same size and speed, 25 European languages with automatic detection.
  v2 stays in the catalogue because it remains the better pick for
  English-only work. Download and `.nemo` presence verified here; the engine
  load path needs an NVIDIA GPU this machine does not have.
- **Groq Whisper large-v3-turbo** (cloud) — full-size Whisper quality at
  roughly four cents per hour of audio with a free tier, behind an
  OpenAI-compatible endpoint. Implemented as the OpenAI engine with two
  constants changed, which is one code path tested once rather than a
  near-copy that drifts. Real per-segment timestamps, so chapters and
  subtitles work.
- **ElevenLabs Scribe** (cloud) — benchmarks among the most accurate
  transcription available anywhere, and labels speakers in the same pass with
  no Hugging Face token. Scribe returns a flat word list rather than
  segments, so segments are assembled at speaker changes and natural pauses —
  where a human transcriber would break the line too. The price (several
  times OpenAI's rate) is stated plainly in the model notes; it is the
  accuracy-first option, not the default.

Groq and ElevenLabs are also the two cloud transcribers QUILL already vetted,
so the family now offers the same choices everywhere.

**Considered and not added:**

- **Parakeet v3 via sherpa-onnx** (CPU multilingual): an export exists
  (`csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`) but ships
  int8-named files the engine's loader does not yet expect. Worth doing;
  needs a small loader change and a real accuracy check first.
  *Done since this review:* the loader learned both spellings, the
  catalogue carries the model, and it was downloaded, loaded and used to
  transcribe the benchmark audio at a measured 7.9x real-time.
- **Deepgram, AssemblyAI, Speechmatics**: capable services, but each would be
  a new request shape and key flow for capabilities the catalogue now already
  covers (speed: Groq; accuracy plus speakers: ElevenLabs/Gemini; preview
  bleeding edge: Azure MAI). More providers is not more value once every axis
  is served.
- **Whisper large-v3 via other runtimes** (whisper.cpp, MLX): redundant with
  faster-whisper on this project's supported platforms.

## What was deliberately left alone

- The activity log still cannot announce itself; that is a wxWidgets limit,
  documented in the accessibility statement, and the sound cues and status
  bar are the mitigations.
- `estimate.describe_model` shows "Time unknown" for the new cloud models
  rather than a guessed speed. Numbers appear when they have been measured,
  and not before.
- The four pre-existing QUILL test failures (a Yes-default dialog in
  untracked work-in-progress, a stale generated help reference, two module
  size budgets) belong to work in flight in that repo and were not touched.

## How this was verified

- 739 → 772 tests, run locally and in a CI-equivalent virtualenv without
  wxPython, mutagen or FFmpeg on PATH.
- Every fixed bug has a regression test that failed against the old code.
- The three on-device additions/changes were exercised against the real
  network: downloaded through acquire, loaded by their engine, and used to
  transcribe audio, with `is_downloaded` checked after both orders of
  operations.
