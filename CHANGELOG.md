# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-03

First public release.

<!-- Everything below was folded into 1.0.0 rather than shipped as a
     separate version, at the maintainer's direction. -->

### Added

- **A second source: audio you already have.** A **Source** radio box at the
  top of the main window switches between **Podcast feed** and **Local**
  **files**. Add files or a folder and podHarvest transcribes them,
  summarises them, works out chapter markers and writes them into the file --
  and plays them and edits every tag on them. This makes podHarvest usable as
  a keyboard-driven, screen-reader-friendly MP3 tag and chapter editor with
  transcription attached, with no feed involved. `podharvest local <paths>`
  on the command line. The choice is remembered between launches.
  - Transcripts are written beside the audio by default, so a file and its
    transcript stay together; `local_transcripts_beside_file` puts them in
    `<output>/Local files` instead.
  - Files are never copied, moved, renamed or converted. Remove takes a file
    out of the list, not off the disk.
  - `harvest.transcribe_all` was extracted from `run_harvest` so both routes
    run the *same* batch: same model selection, same reuse rules, same
    summaries and chapter inference, same progress reporting and
    cancellation. Two implementations would have drifted within a release.
- **Playback speeds are a setting, and go past 2x.** The player now offers
  0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x and 3x out of the box, and
  the list is yours to change in Settings -- anything from 0.25x to 5x. 1x is
  always kept, so there is always a way back to normal. A backend that
  refuses a particular speed is now reported per speed rather than once ever,
  since a backend can allow 2x and refuse 3x.
- **A Tag and Chapter Editor.** Select an episode and press Ctrl+T (or Enter on its row) for six pages: every tag the audio file can carry — twenty-six fields including track and disc numbers, composer, publisher, copyright, language, the four sort-order fields, the compilation flag and embedded cover art — plus a chapter editor with add, delete, exact-time editing and preview. Ctrl+Tab moves between pages.
- **Nudging a chapter marker by ear.** Alt+Left and Alt+Right move the selected chapter's start by one step, Shift with them moves ten, and **Hear boundary** plays three seconds before the marker and two after it. The step runs from a tenth of a second to ten seconds. A nudge speaks only the new time, because a whole sentence at key-repeat speed is unusable; the full description follows once the run goes quiet, and running a marker into its neighbour says so once rather than refusing on every press.
- **Your library, not just a progress bar.** With nothing running, the Episodes list is everything you have harvested: the podcast, the episode, what you have for each, when it was published and how long it is. Read back from each show's own `feed.json`, so titles are the publisher's rather than guessed from filenames; a folder with no `feed.json` still lists its audio. Rebuilt at startup and when a run ends, or on demand with Ctrl+Shift+R. Its column headings change with what it is holding, because a screen reader reads the heading with every cell.
- **Read a transcript in podHarvest** (Ctrl+Shift+T). Read-only, with a Find box that says which occurrence of your text you are on and wraps at the end. Copy all, or hand the file to whatever your system uses for text.
- **Play an episode from the main window.** Select it and press Ctrl+P — no need to open anything. The player sits under the episode list with Rewind and Forward (Ctrl+B and Ctrl+F), volume, mute, and speed. Rewind and forward are configured separately, because going back is about a sentence you missed and going forward is about clearing an advert break.
- **Where you stopped is remembered**, per episode, and offered back next time with a spoken note that it happened. An episode played to the end starts from the beginning again. Switchable off, bounded so the store cannot grow forever, and written a few seconds at a time so a pulled power cable still leaves a usable place.
- **Minimise to the notification area** (Ctrl+Shift+M), so a hundred-episode run can get out of the way. Closing the window still quits.
- **Report a bug** (Help ▸ Report a bug). Gathers the version, the platform, whether FFmpeg is present, the hardware summary, the settings that differ from the defaults, and the recent log — then shows you all of it. **Nothing is sent.** API keys, home folder names and email addresses are removed first, and you choose whether to copy it, save it, or open a pre-filled message to support@community-access.org.
- **The support address** is on Help ▸ About, alongside the full shortcut list.
- **A built-in transport**, with a remembered volume and a mute that keeps the level you set. Used for judging chapter boundaries, and now for listening.
- **Documentation as a first-class part of the release.** Five documents, each with a stated job and audience — a first-run walkthrough, the README for everyday use, a technical reference, a model catalogue, and an accessibility statement — all installed alongside the program and listed in its Start Menu group, because documentation you cannot reach offline is documentation you do not have. Support is at support@community-access.org, named in the app's About box, the README, the guide, the reference, the accessibility statement and the security policy.
- **F1 answers everywhere.** Every window says what it is for, and every control — all sixty-one of them — says what it does, with units and defaults where those matter. A `help_audit` gate fails the build if a new control ships without a sentence.
- **Existing transcripts are never regenerated.** A re-run picks up where it left off. If the publisher shipped a `<podcast:transcript>`, podHarvest fetches that instead of transcribing at all, choosing the most capable format when a feed offers several. Both are switchable in Settings.
- **Existing chapter markers are kept.** Markers already in the file, or timestamps written in the show notes, are used as they are instead of being replaced by a model's guesses — they carry titles a person wrote. HTML notes, trailing timestamps and `1h05m` forms are all understood.
- **Media tools check.** Every FFmpeg feature fails by producing a plausible result — the episode downloads and simply never gains chapter markers — so a missing FFmpeg is said once at startup, and Help → Media tools answers when asked.
- **Shared with QUILL Audio Studio.** The tag model, the chapter operations, the transcript-format ranking and the show-notes reader live in two modules vendored byte-identical into both projects, each guarded by a SHA-256 drift test. The two apps read and write the same files the same way.

### Added (previously)

- **Optional cloud transcription and summaries.** OpenAI and Google Gemini can transcribe; those two plus OpenRouter and Ollama Cloud can write summaries and chapter markers. Strictly opt-in: with no API key configured nothing is uploaded and no request is made. Keys are stored via DPAPI on Windows or the macOS Keychain, never in `settings.json`, with an environment variable override that is never overwritten from the UI.
- **Gemini labels speakers as part of transcription**, so no separate diarization pass and no Hugging Face token is needed for that path.
- **Chapter markers** with real start and end times, taken from the transcript's own segment timestamps. Written above the summary and, optionally, into the audio file itself, where a podcast player shows them as a navigable list. The audio is copied rather than re-encoded, so it is lossless and costs about eighty bytes.
- **Per-model time and cost estimates** shown in a read-only description box beside the model picker, answering "how long will this take" before a run starts rather than after. Figures are marked as measured or estimated.
- **A model source filter** (all / this machine / cloud), disabled entirely when no cloud key exists rather than left as a dead control.
- **Full-episode summaries.** Previously only the first 24,000 characters were summarised, about 44% of an hour-long episode. Long transcripts are now summarised in sections and the section notes combined.
- **A live episode list in the GUI** showing each episode's state, percentage and elapsed time, plus a status line, a completion dialog that takes focus, and a Cancel button that becomes "Open output folder" when a run ends.
- **Configurable log file location**, and a Settings dialog reachable with Ctrl+comma.
- Audio destined for a cloud provider is re-encoded to 16 kHz mono Opus, taking a 54 MB episode to about 7 MB so it fits in one request; anything still oversized is split at natural pauses found by silence detection and stitched back onto one timeline.

### Changed

- **The Windows installer now needs Inno Setup 7.** It builds as a genuine 64-bit installer (`SetupArchitecture=x64`) to match the 64-bit application, and picks up 7's extended-length path support, which removes the `MAX_PATH` limit that this program's deep output trees can otherwise run into. It also closes a running copy through the Restart Manager before upgrading, declares Windows 10 as the minimum, and ships the technical reference and accessibility statement alongside the getting-started guide.

- **MP3 chapter markers are written in place instead of re-muxing the episode.** Adding about a hundred bytes of chapter frames used to copy the whole file through FFmpeg; it now edits the ID3 tag block directly, so a sixty-megabyte episode is chaptered instantly and the audio bytes are provably untouched. The other containers still take the lossless FFmpeg path.
- **Chapter element ids are now `ch0`, `ch1`, …** with a `toc` table of contents, matching FFmpeg's convention and QUILL's, so a file passes between the two apps unchanged.
- `mutagen` joins `wxPython` in the **`gui`** extra. The command line still runs on the standard library alone.

### Fixed

- **A cover image this build cannot decode no longer interrupts you.** wx reports an unreadable image by logging an error, which surfaces as a modal "Unknown image data format" box — not as an exception, so the `try`/`except` around the decode never stopped it. The decode now runs under `wx.LogNull` and the thumbnail hides instead of being handed a null bitmap, which asserted. The words describing the art were always correct and still are.

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
