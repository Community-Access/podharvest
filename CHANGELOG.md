# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-03

First public release.

<!-- Everything below was folded into 1.0.0 rather than shipped as a
     separate version, at the maintainer's direction. -->

### Added

- **Jump to chapter during playback** (Ctrl+J): the loaded episode's chapter
  markers as a list -- number, title, start time -- opening on the chapter
  playing now. Enter continues playback from the chosen one. Two hours of
  audio stops being a wall.
- **Search all transcripts** (Ctrl+Shift+S): find a word or phrase in every
  transcript in the library, one row per episode that contains it, and Enter
  opens the reader with the search already run.
- **Check favourites for new episodes** (Ctrl+Shift+N): fetches each
  favourite's feed once, when you ask, and reports what appeared since you
  last marked the list as seen. Still not a subscription: no timers, no
  downloads, nothing automatic.
- **Export favourites to OPML**: the other half of import -- your list as a
  file any podcast app can read. The favourites family now lives together
  under File > Favourites.
- **Parakeet TDT 0.6B v3 via sherpa-onnx** (int8): the multilingual Parakeet
  on plain CPU -- 25 European languages, no PyTorch, no NVIDIA GPU, 0.7 GB
  on disk, measured at 7.9x real-time here. Downloaded, loaded and used to
  transcribe real audio as verification.
- **Help > Check for updates**: asks GitHub's public releases API for the
  newest version and says how yours compares. Only when chosen -- nothing
  checks automatically and the request carries nothing about you.

- **Four new transcription models**, each earning its place on an axis a
  listener would notice. On-device: Distil-Whisper large v3.5 (the newer,
  more accurate distillation, English) and Parakeet TDT 0.6B v3 (25 European
  languages, NVIDIA GPUs). Cloud: Groq's Whisper large-v3-turbo (full-size
  Whisper at about four cents an hour, with a free tier and real timestamps)
  and ElevenLabs Scribe (accuracy-first, speakers labelled in the same pass).
  Groq and ElevenLabs are the same two cloud transcribers QUILL already
  vetted, so the family offers the same choices everywhere.
  docs/CODE-REVIEW-2026-09.md records what was considered and not added.

### Added (finding a moment, and being told things)

- **Search, then hear it.** Ctrl+Shift+S results now carry a time, and
  choosing one cues the player at the phrase before the transcript opens.
  In the reader, Control+Enter plays from wherever the caret is.
- **Save a passage as a clip.** Select some transcript and get exactly that
  audio, with short fades and a filename made from the words that were
  said. The usual way to make a clip is to drag across a waveform, which is
  no way at all if you cannot see one.
- **Place a chapter by phrase.** The chapter editor takes words from the
  transcript and moves the playhead to where they were said. Nudging by ear
  stays for the last half second.
- **Follow the playhead while reading** -- off unless you turn it on, in
  Settings. A caret that moves on its own takes the text out from under
  somebody reading at their own pace.
- **Announcements.** Errors, run completions and per-episode progress can
  each be spoken, and sent to a braille display, working around the
  activity log's long-standing inability to announce itself. All four are
  off by default, but the shipped app carries the component that does the
  talking, so they are ready to switch on rather than ready to install --
  this app's audience is screen reader users, and hunting for a setup
  button before the app can say "the run finished" is not a reasonable
  first experience. `pip install podharvest` still declares no
  dependencies and fetches it on first use instead.
- **Offer to check favourites at launch** -- once, after a week, with Stop
  asking as one of the three answers. Still not a subscription: nothing
  runs while podHarvest is closed and saying yes downloads nothing.

All of this works on transcripts already on disk. podHarvest has always
written `[HH:MM:SS.mmm]` markers into transcripts, and reading those back is
what makes a library harvested a year ago searchable to the second today; a
new `.words.json` sidecar adds word-level precision for runs from now on.

### Added (where the big files go)

- **Models and downloads can live on another drive.** Settings shows what
  each folder costs, the total, and how much is free, then moves what is
  already there. Until now the only ways to move them were a CLI flag, an
  environment variable or portable mode -- none discoverable, and all of
  them moved the settings too.
- **Settings and logs never move.** A settings file that moves is one you
  can lose, and the log has to be readable when the thing you are
  reporting is that the other folder broke.
- **A move copies, checks, and only then deletes**, so an interruption
  leaves the existing copy working. It refuses a folder inside the current
  one, a path that is a file, or a drive without room, and says which.

### Changed (models)

- **The main window offers only models that can actually run**, and says so
  when none can. **Set up models** is a new window listing every model
  podHarvest knows -- Ready, Not downloaded, Needs an API key, or Will not
  fit, with the numbers on that last one. Nothing is hidden any more.
- **The model list no longer changes with free memory.** It was sized
  against available RAM, so models appeared and disappeared depending on
  what else was open; the one most often lost was the CPU Parakeet, on the
  machines with no GPU that need it most.
- **Downloading a model names both of its phases.** The first -- installing
  the engine's Python packages -- reports no percentage and can take
  minutes, so it used to look exactly like a dead button.

### Fixed (keyboard)

- **Alt+T opens the Tools menu.** A checkbox in the client area was
  claiming it; no control on the main window may now claim any of the five
  menu letters.
- **Tab no longer walks into the status bar.** It is a review surface
  reached with F6, not five stops between the last control and the end of
  the window.

### Changed (choosing a podcast)

- **Four sources, each with its own box.** The Source group was doing two
  jobs: "Podcast feed" and "Local files" said what you were working on,
  while "Find a podcast" said how you would get an address -- which is why
  Find and Feed shared a box and importing a list was buried in a menu.
  It is now Find a podcast, Podcast feed, Podcast list and Local files,
  and each owns the box below it. Searching and reading an OPML list happen
  in the window rather than in a dialog over the top of it, so the show you
  are choosing and the run you are setting up are on screen together.
- **A Chosen podcast line, and nothing enabled before there is one.** All
  three feed sources end in the same place, so what to do next -- the
  episode filter, Show episodes, Add to favourites -- moved out of the Feed
  box into a row of its own, greyed until something is chosen. Favourites
  stays enabled, because it is how you get a podcast in the first place.
- **The same context menu on every list of podcasts.** The inline results,
  the inline list, the search window, favourites and the import window all
  build their menu from one function: use or check this show, add or remove
  it, copy the feed address, open its page. Entries a row cannot support are
  dimmed rather than absent.

### Fixed (accessibility and release hardening)

- **Space checks a box and stays where it is.** On Windows a checkable list
  reports Space as an item *activation* as well as a check, and activation
  was bound to "use this show and close" -- so the one keystroke the import
  window exists for threw you out of it. Space now only ever checks. Enter
  does the window's actual job, adding everything checked, and the Add
  button carries the count ("Add 12 checked to favourites") so tabbing to it
  answers how many you have without going back to count.
- **Favourites got a filter box and a detail pane.** A favourites list only
  grows; typing three letters of a name is a faster route than arrowing
  through forty. The box below the list gives the highlighted show's feed
  address, which is the thing no column can show, and Delete removes an
  entry -- a bookmark, so nothing harvested is touched, and the status line
  says so.

- **Screen readers can read the lists again.** The helper that gives a control
  an accessible name was replacing the native accessibility object, which on
  Windows also answers for the control's children. List rows read as bare
  index numbers, every tab in the Tag and Chapter Editor announced as "Tag
  and chapter pages", and checkbox state changes went unspoken. Lists, tabs,
  radio groups and checkboxes now keep their native accessibility, which
  knows their rows, titles and states.
- **The import list announces its checkboxes.** Reading an OPML list used a
  check list box, which Windows draws itself and screen readers cannot see
  into. It is a native list with real checkboxes now: rows read, Space
  announces checked and unchecked, and a running count follows every change.
  "Tick" became "Check" throughout, which is what the control is called.
- **The Play button plays.** It called a bare toggle on a player with nothing
  loaded, which does nothing and says nothing; loading only happened via
  Ctrl+P. The button now loads the highlighted row first, exactly as the
  menu does.
- **Local files are no longer described as episodes.** In local mode the list
  is labelled Files, prompts say file, and the episode limit -- which caps
  what a feed fetches -- is greyed out.
- **The episode list has a context menu**, on right-click, Shift+F10 or the
  Applications key: play, jump to a chapter, read the transcript, edit tags
  and chapters, open the containing folder, and remove from the list. Entries
  the highlighted row cannot use are dimmed rather than hidden, in the menu
  bar as well, so the menu answers "is there a transcript?" before it is
  asked.
- **The installer's checkboxes announce their state.** Inno Setup's wizard
  draws its task list itself, and it reports every box as unchecked to a
  screen reader. The desktop icon and launch choices are native Windows
  checkboxes now.
- **Releases are reproducible and signed.** The build installs from a lock
  file pinning every package, direct and transitive, to one version and one
  SHA-256 -- a swapped or tampered wheel fails the build instead of entering
  a release quietly. Binaries and the installer are Authenticode-signed
  through Azure Trusted Signing, and every download is published with its
  SHA-256.

### Fixed (September review)

- **No text box can be squeezed into a column of single words.** Every
  read-only text area now declares a minimum readable width in characters of
  its own font (45 at least, more for reading surfaces), and the main window
  refuses to shrink below what its text needs -- capped to 90% of the screen,
  so small displays still work. Before this, resizing the window could crush
  the model description to eleven characters a line.
- **Every engine now loads models from the same store the Download button
  fills.** Four of six did not: faster-whisper and NeMo re-downloaded
  gigabytes the button had already fetched, a model the engine had fetched
  read as "not downloaded" forever, and Moonshine's button downloaded the
  PyTorch weights its ONNX engine could never open. Loading by directory
  also unlocks models faster-whisper's own registry has never heard of,
  which is what makes the v3.5 addition possible at all.
- **Two podcasts with different date formats no longer crash startup.** One
  feed writing dates without a timezone next to one writing them with one
  raised a TypeError in the newest-first sort, which runs when the window
  opens. Zoneless dates are read as UTC.
- **A winget FFmpeg upgrade no longer silently removes FFmpeg.** winget
  names its install folder after the version and PATH keeps the old name
  after an upgrade, so every FFmpeg feature quietly degraded. podHarvest now
  finds whatever version winget actually installed. Caught happening live
  during the review.
- **The Settings window fits on a screen.** Its content had grown to 1,750
  pixels on a 955-pixel display, with OK and Cancel below the bottom edge --
  enterable but not leavable by keyboard. Everything scrolls now except OK
  and Cancel, which never move.
- **Cloud timestamps are decided by the catalogue, not a hardcoded model
  name**, and API-key captions promise only what each key actually unlocks.

### Fixed

- **`is_downloaded()` was permanently false for every enrichment model.**
  `acquire_enrichment_model` writes to `models/enrichment/`, but `_model_dir`
  only knew about engines and answered `models/llama-cpp/`, so nothing could
  ever see a summary model that had in fact been downloaded. No caller asked
  yet, which is the only reason it had not surfaced -- it was a bug waiting
  for one. The path is now spelled once.
- **A downloaded model could fail verification and be re-downloaded forever.**
  A full-repo snapshot recorded every file it found as model content --
  including `huggingface_hub`'s own `.cache` bookkeeping, which contains a
  one-byte `.gitignore`, and podHarvest's own `manifest.json`. Both then failed
  a size floor meant for catching truncated weights, so a perfectly intact
  model reported "missing or truncated .gitignore" and told you to delete it.
  The recorded list also flattened subdirectories, so a nested file could never
  be found again. Verification now asks the folder rather than a possibly stale
  list, ignores bookkeeping, records relative paths, and applies the size floor
  only to files that actually carry weights. A model broken by the old code
  heals without being downloaded again.
- **Transcription could not work at all in the packaged build.** Every attempt
  to set up an engine failed with `invalid choice: 'pip'`, and the run reported
  only "skipping transcription". Four separate faults, none of which are
  reproducible in a source checkout:
  - `sys.executable` is `podharvest.exe` in a frozen build, not a Python
    interpreter, so `-m pip` reached podHarvest's own argument parser. Installs
    now route through a `_pip` passthrough handled before argparse.
  - pip cannot be frozen: its vendored `distlib` cannot find a resource finder
    for PyInstaller's loader, so it imports and then dies on the first install.
    It now ships as plain files beside the executable.
  - The standard library was bundled only as far as podHarvest's own imports
    reached, but the build *hosts* pip-installed packages that import anything
    they like -- so faster-whisper failed with `No module named 'asyncio'`. The
    whole standard library now ships.
  - `python3.dll` was missing. Wheels built against the limited API (PyAV, and
    so faster-whisper) link against it; CPython installs it, PyInstaller did
    not. They installed cleanly and failed to import with "DLL load failed ...
    The specified module could not be found", naming the extension rather than
    the DLL it wanted.
- **A good install could be reported as a failure.** The isolated package
  folder goes on `sys.path` before the install, when it is empty, and Python
  caches that. Without `importlib.invalidate_caches()` afterwards the new
  package was invisible: "installed but still not importable", with the files
  plainly on disk.
- **A run that transcribed nothing said "All done."** `transcribe_all` now
  reports whether it ran, counts outcomes, and says "None of the N file(s)
  could be transcribed" or "N of M transcribed; K failed" instead. The local
  route adds that your files are untouched and still playable and editable.
- **The empty-library advice appeared in Local files mode**, telling you to
  paste a feed address when a feed was not what you were working on. The
  Library folder box now says what it actually means for the source you are
  on -- and that local transcripts are written next to the audio, not there.
- **The test suite was order-dependent.** Three test modules each created their
  own `wx.App`; a process only ever gets one, and under a shuffled order the
  second attempt left failures reported against modules with no user interface
  at all. One shared session fixture now.

### Added
- **Know whether a model will work before you start it.** A line beside the
  model description says whether the selected model is ready, or names what is
  still missing -- the engine's packages and the model weights are separate
  downloads and either can be absent on its own -- and a **Download model**
  button fetches them on the spot, using the same calls a run makes.
- **Azure MAI-Transcribe-2, as an option you turn on.** Microsoft's
  MAI-Transcribe-2 through Fast Transcription, for English and Spanish: it
  labels speakers and returns word-level timings in one request, and takes a
  list of terms to bias recognition towards -- worth setting for a show with
  recurring guests. Implemented from `MAI-TRANSCRIBE-2-PRD.md`, and its
  preview posture is the design rather than a caveat: off until you turn it
  on and off again after updates, never a default, never a silent fallback,
  no price or speed claimed because Microsoft has published neither, the API
  version pinned in a setting, and an explicit warning rather than silence
  when speaker labels or word timings were asked for and did not come back.
  Everything is configurable in Settings, and "Check this is set up" names
  every missing piece at once without sending anything to Azure.
- **A status bar you can reach.** F6 moves focus into it, arrows move between
  its cells, Home and End jump to the ends, Enter does the useful thing for
  whichever cell you are on, and the context menu offers that plus copying the
  value. Six cells -- activity, progress, source, model, library, time -- each
  deriving its text from live state. Modelled on QUILL's, so the programs
  behave alike.
  - This replaces wx's own status bar, which cannot take focus at all. That is
    why the window used to sit claiming it was detecting hardware long after it
    had finished: nothing could read the message and nothing announced that it
    had changed, so nobody noticed it was stale.
- **Find a podcast by name.** Ctrl+K searches Apple's podcast directory --
  free, no account, the same one the podcast apps use -- so you no longer need
  a feed address to start. Narrow what your words match against (name,
  presenter, keywords, description), choose which country's store to ask, and
  set how many results to fetch. Twenty-five storefronts are offered by name,
  defaulting to the United States; any other code Apple recognises can go
  straight into `itunes_country`. A pasted `podcasts.apple.com` link is
  resolved to its feed address. Adapted from QUILL Cast's client so the two
  programs find the same shows.
- **Show episodes** (Ctrl+Shift+E) reads a feed and lists what is in it --
  titles, dates, lengths, and whether each episode has audio or a published
  transcript -- without downloading anything. The way to see what a show has
  before deciding to harvest it.
- **Import a list of podcasts** (Ctrl+Shift+I). Reads an OPML file -- the
  format podcast apps use to hand each other a list of shows -- and shows it
  as a tick list. "Tick the new ones" skips anything already in your
  favourites. A button loads the ACB Media network's real public list, because
  "find an OPML file" is not a useful instruction to somebody who has never
  seen one. The parsing rules come from QUILL Cast's importer, including the
  awkward parts: a parked `isComment` entry is skipped rather than quietly
  switched back on, folders are remembered, and duplicates are removed by the
  same rule favourites use. A DOCTYPE or a plain-HTTP address is refused
  rather than parsed. Importing adds bookmarks; it subscribes to nothing.
- **Favourite podcasts** (Ctrl+Shift+K). Mark a show, come back to it later.
  Bookmarks rather than subscriptions, and the difference is the design:
  nothing polls, schedules, notifies or downloads, and a test asserts the
  module cannot. Removing one removes the bookmark only.
- **A third source: Find a podcast**, beside Podcast feed and Local files, so
  the search is a place you can be rather than only a button. Selecting it puts
  focus on Find Podcast; the search field and its button are now labelled for
  what they do.
- **A richer menu bar**, grouped by what each entry acts on rather than by
  what happened to be implemented near what: File chooses the podcast or the
  files, Episode acts on whichever is highlighted, View moves focus, Tools
  looks after the models and this machine, Help explains. Thirty entries
  across five menus, every one with a status-bar sentence and a mnemonic that
  does not collide with its neighbours -- all three checked by tests, which is
  how a collision introduced writing them was caught.
- **Take only the episodes you want.** **Only episodes matching** takes a word
  or two and keeps the episodes whose titles contain them -- all of them, any
  order, ignoring case. It runs before the episode limit, so "5 episodes
  matching badger" means five about badgers rather than however many badgers
  are in the latest five. `--match TERM` on the command line.
- **Hear a run without watching it.** The activity log cannot announce itself
  to a screen reader -- a toolkit limitation, documented, not fixable here --
  so a long run is otherwise silent. Optional short tones now report it: one
  per episode, a rising pair at the end, a low tone for a failure and a falling
  pair when you stop it. Told apart by pitch and shape rather than by counting,
  played off the UI thread, and off by default.
  - Both ideas come from the small script this program grew out of, by Michael
    Babcock, which filtered by search term and beeped as each download landed.
- **An "Already downloaded" filter** on the model picker, so getting back to a
  model you have used before does not mean reading the whole list. Each filter
  is now enabled on its own terms -- cloud needs an API key, "Already
  downloaded" needs something downloaded, "All" needs more than one source --
  and the group stays dark until hardware detection has found anything at all.
  A filter you are sitting on that stops applying moves the selection rather
  than silently emptying the list.
- **Downloading a model shows its progress.** The button appeared to do
  nothing for several minutes, because `huggingface_hub` draws its progress
  with tqdm, which is right on a terminal and invisible in a window. The gauge
  and the status line now move as it downloads.
- **`podharvest doctor`**, which answers the same question from the command
  line and more: where everything lives, whether FFmpeg is there, whether
  packages can be installed at all, and per engine whether each package is
  downloaded *and whether it actually loads*. Written to be pasted into a bug
  report; exits 1 if anything is wrong.

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
