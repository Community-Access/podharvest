# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-02

### Added

- **Optional cloud transcription and summaries.** OpenAI and Google Gemini can transcribe; those two plus OpenRouter and Ollama Cloud can write summaries and chapter markers. Strictly opt-in: with no API key configured nothing is uploaded and no request is made. Keys are stored via DPAPI on Windows or the macOS Keychain, never in `settings.json`, with an environment variable override that is never overwritten from the UI.
- **Gemini labels speakers as part of transcription**, so no separate diarization pass and no Hugging Face token is needed for that path.
- **Chapter markers** with real start and end times, taken from the transcript's own segment timestamps. Written above the summary and, optionally, into the audio file itself, where a podcast player shows them as a navigable list. The audio is copied rather than re-encoded, so it is lossless and costs about eighty bytes.
- **Per-model time and cost estimates** shown in a read-only description box beside the model picker, answering "how long will this take" before a run starts rather than after. Figures are marked as measured or estimated.
- **A model source filter** (all / this machine / cloud), disabled entirely when no cloud key exists rather than left as a dead control.
- **Full-episode summaries.** Previously only the first 24,000 characters were summarised, about 44% of an hour-long episode. Long transcripts are now summarised in sections and the section notes combined.
- **A live episode list in the GUI** showing each episode's state, percentage and elapsed time, plus a status line, a completion dialog that takes focus, and a Cancel button that becomes "Open output folder" when a run ends.
- **Configurable log file location**, and a Settings dialog reachable with Ctrl+comma.
- Audio destined for a cloud provider is re-encoded to 16 kHz mono Opus, taking a 54 MB episode to about 7 MB so it fits in one request; anything still oversized is split at natural pauses found by silence detection and stitched back onto one timeline.

### Fixed

- **Parakeet was losing most of its accuracy to a chunking bug.** The window overlap was documented as trimmed but never was, so both windows decoded the shared audio and both copies of the words were kept: 33 insertions against 7 substitutions and 12 deletions. Word error rate on the benchmark clip went from 6.55% to 2.02%, making Parakeet the most accurate engine tested and 2.8x faster than the most accurate Whisper size. The README's previous recommendation to prefer `tiny.en` was wrong and has been corrected.
- **Parakeet could crash on certain audio lengths.** A trailing window shorter than one 25 ms feature frame produced no frames and the model rejected the empty input.
- **`ffprobe` was never found.** It was derived by replacing the first "ffmpeg" anywhere in the path, which corrupts any install directory named like `ffmpeg-9.0.1-full_build`.
- **The summary model was reloaded from disk for every episode.** A 2.4 GB file, 54 times over a feed. It is now loaded once per process, and ASR engines are reused across runs rather than only within one.
- **Audio decoding built a Python list of 57 million floats per episode**, costing 2.8 seconds and 1.7 GB. Vectorised: 0.14 seconds and 220 MB.
- **A run looked frozen for minutes.** Nothing was logged for an episode until both its transcript and its summary had finished. Progress is now reported as work happens.
- **Chapter markers that merely list the timeline are rejected.** A weak on-device model emitted 34 chapters exactly 60 seconds apart, which looks like a table of contents while carrying no information. Spacing is enforced and an evenly spaced set is discarded with an explanation.
- **A transcript's header line always showed a clock-shaped duration** even with timestamps turned off, which read as a timestamp that the setting had failed to suppress.

### Changed

- **The product is written podHarvest.** The capital H is deliberate: a screen reader given "podharvest" pronounces it as one unpronounceable run of letters. The lowercase form remains the import name, the console command, the app directory and the environment variable prefix, where it is typed rather than spoken.
- **The README is now written for end users** in plain language; the previous technical README moved to `docs/REFERENCE.md`, and the getting-started guide was rewritten for complete beginners.
- Every user-facing log message rewritten in plain language.
- Parakeet's default window is 30 seconds with no overlap, chosen by measuring every combination against both a human reference transcript and a whole-file no-boundary decode.
- Settings warns, with measured figures, that on-device summaries take about 12 minutes per hour-long episode against roughly two seconds for a cloud model.

## [1.0.0] - 2026-09-02

First public release.

### Added

- Feed archiving for RSS 2.0, Atom, and RDF/RSS 1.0, rendered to Markdown, sanitized HTML, plain text, JSON, and CSV.
- **Feed auto-discovery**: pasting a podcast's web page now finds its feed via `<link rel="alternate">`, falling back to conventional feed paths, instead of failing with a parse error.
- **Feed pagination**: RFC 5005 `<link rel="next">` chains are followed and merged, so a paginated archive no longer silently yields only its most recent page.
- **Vosk and Moonshine ASR engines**, which were previously catalogued and offered in the model picker but raised "not implemented" when selected.
- On-device transcription via faster-whisper, Parakeet (NeMo and ONNX), Vosk, and Moonshine, with a hardware advisor that recommends a model the machine can actually run.
- Speaker diarization with a choice of `pyannote`, `sherpa-onnx`, or `nemo-msdd` backends, and `--hf-token` / `$PODHARVEST_HF_TOKEN` to supply the token pyannote requires - previously there was no way to provide one.
- Optional on-device LLM transcript enrichment (Phi-3.5, Llama 3.2, Nemotron-Mini, Mistral).
- Accuracy benchmarking with Word Error Rate scoring (`podharvest benchmark`).
- A wxPython desktop GUI and a scriptable CLI over one shared pipeline and settings file.
- An HTTP cache using ETag/Last-Modified conditional requests, so re-fetching an unchanged feed costs a 304.
- `index.html` generation, so the HTML archive is navigable rather than a set of orphan pages.
- Packaging metadata: `pip install podharvest` provides the `podharvest` and `podharvest-gui` commands.
- A test suite and CI across Linux, macOS, and Windows on Python 3.10–3.13.

### Fixed

- **Downloads could be silently corrupted.** An interrupted transfer was retried by re-requesting the same byte range into the same append-mode file handle, splicing duplicate bytes into the middle of the file. A 400,000-byte resource could land on disk as 596,608 bytes, be hashed, and be recorded in the manifest as complete - so it was never re-fetched, and transcription then ran against corrupt audio.
- **Truncated downloads were accepted as complete.** A response that ended early was never compared against the declared length. Transfers are now verified, staged through a `.part` file, and only renamed into place once the byte count checks out.
- **Resume did not work across runs.** A partial file from an interrupted run was skipped rather than resumed, leaving an orphaned fragment behind and re-downloading from scratch.
- **Stored HTML injection in generated pages.** Episode metadata - author names, categories - was interpolated into archived HTML with no escaping at all, bypassing the sanitizer that guards the episode body.
- **A table with omitted `</td>`/`</tr>` discarded the entire episode body.** Both end tags are optional in HTML and feeds omit them routinely; an unclosed cell diverted all subsequent text into a buffer that was never drained, so the Markdown and plain-text archives came out empty with no error and no log line.
- **Caption tracks were stripped from archived media.** `<track>` was not in the sanitizer's allow-list, so captions were deleted from captioned video and audio.
- **Every Atom feed was labelled `lang="en"`.** The Atom parser never read `xml:lang`, so a Japanese or Arabic feed archived as English and would be read aloud by the wrong speech synthesizer. Language is now parsed for Atom and RDF, validated as a language tag, and normalized (`en_US` becomes `en-US`).
- **The "Original post" link was invisible in HTML output.** Markdown autolink syntax leaked into the HTML path, where the tokenizer consumed the URL as a bogus tag and rendered nothing.
- **`Alt+S` did not start a harvest.** Windows mnemonics are case-insensitive, so `&Start` and `&speakers` collided and the key cycled focus instead of activating. Mnemonics are de-conflicted, and frame-level shortcuts (Ctrl+R, Esc, Ctrl+L, Ctrl+D) plus a menu bar were added.
- **A failing hardware probe left the GUI permanently unusable.** The probe ran with no exception handling and the Start button was only ever enabled from its callback, so any failure disabled Start forever with nothing logged. The app now degrades to download-and-convert and explains why.
- Pressing Start or Cancel destroyed keyboard focus, because the focused button was disabled without moving focus elsewhere first.
- The `javascript:` scheme check could be evaded with embedded control characters or HTML entities.
- The Atom `<link>` selector picked the wrong link, because a childless XML element is falsy.
- Atom `type="xhtml"` content was dropped after the first nested tag.
- Pipe characters inside table cells were not escaped, breaking the column grid.
- `<ol start="abc">` raised, dropping the whole episode to unstructured text.
- Empty headings and duplicate `<h1>` elements in generated pages.

### Changed

- Settings that were documented but read by no code are now implemented: `naming_template`, `on_duplicate_file`, `write_srt`, `write_vtt`, `download_rate_limit_kbps`, `download_retries`, and `log_verbosity`. `theme` and `confirm_before_overwrite` are removed rather than left as no-ops.
- The HTTP User-Agent identifies the project honestly instead of pointing at `example.invalid`.
- `docs/ACCESSIBILITY.md` is rewritten. The previous version claimed the activity log was "a live region announced via wx's built-in accessibility support"; wxWidgets has no live-region API on any platform, and no screen reader announces those updates. Claims are now separated into verified, implemented-but-unverified, and known gaps.
- Generated episode pages gained a `<main>` landmark, a back-link to the index, a description list for metadata, enclosure download links, and heading normalization.
- The GUI no longer ships a hard-coded third-party feed URL as its default value.

[1.0.0]: https://github.com/community-access/podharvest/releases/tag/v1.0.0
