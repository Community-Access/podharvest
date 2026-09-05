# Accessibility statement

podHarvest is built for people who rely on assistive technology, and accessibility is treated as a functional requirement rather than a visual afterthought.

This document is deliberately specific about **what has been verified, what is implemented but unverified, and what does not work**. An overstated accessibility claim is worse than a missing feature: it tells someone to rely on something that will not be there. Where an earlier version of this document made a claim the code did not support, the claim has been removed and the gap is listed below.

## Testing status

**A manual screen reader pass has been performed against version 1.0.0 and found no problems.**

| | |
|---|---|
| Screen readers | NVDA, JAWS and Narrator |
| Covered | The desktop app, a full harvest run from start to finish, the generated HTML output, and the command line |
| Tested by | A screen reader user, against the 1.0.0 release build |
| Result | No problems reported |

That covers every part of the application, including the controls added in 1.0.0: the episode list, the model source filter, the read-only model and summary description fields, the API key test, and the run-finished dialog.

**The Local files source is not covered by that pass.** The Source radio box,
the Add/Remove buttons and the local-file listing were added after it. They are
built the same way as everything the pass covered — a `wx.RadioBox` for the
source, label-before-control ordering, accessible names set explicitly, an F1
sentence on every control enforced by the build gate — and they are exercised by
automated tests, but they have not been through a screen reader by hand. Treat
them as implemented-but-unverified until a pass says otherwise.

Two honest limits on that result. It is one tester on Windows, so it establishes that the application works rather than that it works for everyone; and VoiceOver on macOS has not been exercised, so the macOS notes below remain source review only. Further reports, particularly from macOS, are very welcome - see [Reporting an accessibility issue](#reporting-an-accessibility-issue).

The rest of this document was originally derived from source review and Windows MSAA inspection. The pass corroborates it, including the known gaps: "no problems reported" means the application was usable throughout, not that the limitations listed below have gone away. The activity log still does not announce new lines, because wxWidgets has no API that would let it.

## Desktop GUI (wxPython)

### What works

| Requirement | Implementation |
|---|---|
| Labeled groupings | Related controls sit inside `wx.StaticBoxSizer` regions ("Feed", "Options", "Transcript options", "Hardware"), and child controls are parented to the actual `wx.StaticBox` rather than the panel. This produces a genuine grouping role with a name in the accessibility tree, and it is the part of the GUI that holds up best under inspection. |
| Accessible names | Controls with an adjacent `wx.StaticText` take their name from it, which is how Windows names an edit field. Controls with no adjacent label - the progress gauge, the spin controls, the model picker - are given a name through a `wx.Accessible` subclass (`set_accessible_name` in `gui.py`). |
| Keyboard access | Every control is reachable with Tab/Shift+Tab, and no action requires a mouse. Primary actions also have frame-level shortcuts: **Ctrl+R** start, **Esc** cancel, **Ctrl+L** go to the activity log, **Ctrl+D** re-detect hardware. |
| Menu bar | A File/View/Help menu bar gives an Alt/F10 entry point, which is the conventional way to explore an unfamiliar application with a screen reader. Shortcuts are published in the menus and in Help ▸ About. |
| Default action | Enter activates Start, so typing a feed URL and pressing Enter works as expected. |
| No color-only signaling | Validation errors (missing feed URL, no transcription model selected) appear as a modal dialog with a full text explanation, parented to the main window, and focus moves to the field that needs attention. |
| System theming | No colors, fonts, or custom drawing are set anywhere in the GUI. High-contrast themes, focus indicators, and text scaling are all handled natively by the platform. |
| Non-blocking UI | Long-running work happens on a background thread, so focus and keyboard input stay responsive throughout a run. |
| Failure never strands you | If hardware detection fails, transcription is disabled with a spoken-readable explanation and the rest of the app stays usable. It previously left the Start button permanently disabled with no message. |
| F1 explains everything | Every window answers F1 with what that window is for, then the focused control's own name, its authored sentence, and how to drive a control of that kind. Every focusable control carries a sentence, with units and defaults where those matter -- 84 construction sites across the four window modules, all of them authored rather than defaulted. A control with nothing authored still answers with its name and its role, because a silent F1 cannot be told from a broken one. `podharvest/help_audit.py` fails the build if a new control ships without one, so the coverage cannot quietly rot. |
| Silent failures are spoken | Every FFmpeg feature fails by producing a plausible result — the episode downloads and simply never gains chapter markers, which looks exactly like an episode that had none. A missing FFmpeg is therefore said once at startup, and **Help ▸ Media tools** answers on demand. A healthy install says nothing, because a startup that reports good news every time trains you to talk over the one that does not. |
| Editing by ear | The Tag and Chapter Editor's chapter page is built for placing markers without seeing a waveform: Alt+Left and Alt+Right nudge a boundary by a step you choose, Hear boundary plays a few seconds either side, and the speed control goes down to 0.75x, which is the direction that helps. Each nudge speaks only the new time, because a full sentence repeated at key-repeat speed is unusable; the whole sentence follows once you stop. |
| Pictures are described in words | Embedded cover art is read out as its format, size and description before any thumbnail is shown, because a picture tells a sighted person everything and a screen-reader user nothing. |
| Listening does not mean editing | The player is on the main window: select an episode and press Ctrl+P. Rewind, forward, volume, mute and speed are all keyboard-reachable, rewind and forward are configured separately, and where you stopped in each episode is remembered and announced when it is used. |
| A long episode is navigable by ear | Ctrl+J lists the playing episode's chapter markers -- number first ("3. The interview - 10:00"), because "chapter three" is how people refer to them -- opening on the chapter playing now. Enter continues playback from the chosen one. |
| The library is searchable as speech | Ctrl+Shift+S finds a phrase in every transcript at once, one spoken row per episode ("A Show - Episode - 3 times: ...context..."), and Enter opens the reader with the search already run, so the next Enter is walking the matches. |
| Text boxes are sized in lines, not pixels | Every multi-line box asks its own font how tall a line is. A box specified in pixels shows five lines at 100% scaling and one at 200%, which fails exactly the people who scaled their text up. A test fails the build if a pixel height reappears. |
| The activity log wraps | It used to need horizontal scrolling to reach the end of a sentence. Its lines are prose, not columns. |
| A bug report shows you everything first | Help then Report a bug builds the report, redacts keys, home folder names and email addresses, and shows the whole thing in a read-only box you can arrow through. Nothing is sent; you choose to copy, save, or open a pre-filled message. |
| A long run can get out of the way | Ctrl+Shift+M minimises to the notification area and the run carries on. Closing the window still quits, because a window that disappears on close reads as having quit. |
| The list is your library, not just a progress bar | With nothing running it lists every episode you have harvested — podcast, title, what you have for each, when it was published, how long it is — read back from each show's own `feed.json` so the titles are the publisher's rather than guessed from filenames. Its column headings change with what it is holding, because a screen reader reads the heading with every cell and the wrong one on every row is worse than none. |
| Four sources, announced as one choice | The Source selector is a `wx.RadioBox`, so it is read as one named group with a position ("Source, Podcast feed, 2 of 4") and arrowed between, rather than as four unrelated check boxes with a state that can be several or none. Each option owns the box below it — a search field and its results, a feed address, an OPML list, or the local file buttons — so there is one place to be for whatever you are doing. Changing it relabels the Start button *and* its accessible name, swaps the box, and re-headings the Episodes list, so the window never describes work it is not about to do. |
| Nothing offers to act on a podcast you have not chosen | The episode filter, Show episodes and Add to favourites are greyed until something is chosen, and the Chosen podcast line above them says what that is. Greyed rather than hidden: a control that appears and vanishes moves the tab order under you mid-session, while a disabled one keeps its place and announces as unavailable. Favourites stays enabled throughout, because it is how you *get* a podcast. |
| A local file is a first-class row | Files you add appear in the same Episodes list, with the same keys: Ctrl+P plays, Ctrl+T edits tags and chapters, Ctrl+Shift+T reads the transcript. The "What you have" cell is prose — "transcript and 12 chapters" — rather than a row of ticks, because a screen reader reads it aloud with its column heading and one phrase says more than three columns of "yes". |
| Destructive-sounding words are checked | The Local files box has **Remove** and **Clear list**. Neither touches a file. Both the tooltip and the log line say so explicitly, because "Remove" beside a list of your own files reads as "delete" until something says otherwise. |
| Progress says what it is actually about | A run over local files reports "12 files finished", not "12 episodes". The word is read aloud with every progress update. |
| The status bar is reachable | wx's own status bar cannot take focus, so it can only be found by hunting with a review cursor and nothing announces when it changes. podHarvest's is a row of real buttons: F6 in and out, arrows between cells, Home and End to the ends, Enter for a per-cell action, a context menu, and one Tab stop for the whole bar rather than one per cell. Every cell derives its text from live state, so it cannot go stale — which is what the old one did, sitting on "Detecting hardware..." indefinitely because nothing ever wrote to it again. |
| The menu bar is grouped, not a pile | Five menus by what each acts on -- File the podcast or the files, Episode whichever row is highlighted, View where focus goes, Tools the models and this machine, Help. Every entry carries a status-bar sentence, which is what a screen reader reads as you arrow through, and a mnemonic that does not collide with its neighbours. All three are tested, which is how a collision introduced while writing them was caught before it shipped. |
| A podcast can be found by name | Ctrl+K searches Apple's directory, so a feed address is no longer something you have to obtain elsewhere. Results are a real list to arrow through, each row a spoken phrase ("829 episodes, Design") rather than columns of codes, with the whole entry -- including the feed address -- in a read-only box below. |
| Looking is separate from fetching | Show episodes lists what a feed holds and downloads none of it, with its own column headings, because the library headings promise what you have and none of it is on disk yet. The transport is switched off for the same reason, rather than left armed over files that do not exist. |
| Favourites are honest about what they are not | Bookmarks, not subscriptions. Nothing checks them, downloads from them or notifies you, the window says so in as many words, and removing one says plainly that your harvested files are untouched. |
| Transcripts can be read in place | Ctrl+Shift+T opens the selected episode's transcript with a Find box that says which occurrence you are on — the useful operation on an hour of speech is find, not scroll, and moving the caret in a read-only box is otherwise silent. |
| Finding a phrase ends with hearing it | Ctrl+Shift+S searches every transcript and each result carries a time. Choosing one opens the transcript at the match and cues the player there — loaded but not started, because audio beginning unasked over a screen reader that is still reading the row you chose is startling. In the reader, Control+Enter plays from wherever the caret is. |
| Reading along, only if you ask for it | Settings can move the transcript caret to keep pace with playback. It is off by default and deliberately so: a caret that moves on its own takes the text out from under somebody reading at their own pace, which is a loss of control rather than a nicety. Only the caret moves, and only when the sentence changes. |
| Clips are chosen by reading, not by scrubbing | Select a passage of transcript and save exactly that audio, with short fades and a filename made from the words that were said. The usual way to make a clip is to drag across a waveform, which is no way at all if you cannot see one. |
| Chapters can be placed by phrase | The chapter editor takes words from the transcript and moves the playhead to where they were said. Nudging by ear stays for the last half second; this is the coarse move that used to mean scrubbing. |
| A run can say what it is doing | Errors, completions and progress can each be spoken, and sent to a braille display, working around the activity log's inability to announce itself. All off until asked for. |
| Models are listed, not hidden | Set up models shows every model podHarvest knows with an honest word on each, including the ones this machine cannot run and why. A model that is absent with no explanation is indistinguishable from one that was never added. |
| Every podcast list has the same menu | Right-click, Shift+F10 or the Applications key on any list of podcasts — the inline search results, the inline OPML list, the search window, favourites, or the import window — offers the same actions in the same words: use or check this show, add or remove it, copy the feed address, open its page. One builder produces all five, so they cannot drift apart, and entries a row cannot support are dimmed rather than missing. |
| Every row has a menu of what it can do | Right-click, Shift+F10 or the Applications key on the episode list offers play, jump to a chapter, read the transcript, edit tags and chapters, open the containing folder, and — for local files — remove from the list. Entries the highlighted row cannot use are dimmed rather than hidden, in the menu bar as well, so the menu answers "is there a transcript for this?" before you ask it. |
| The installer announces its own checkboxes | Inno Setup's wizard draws its task list itself and reports every box as unchecked no matter its state. podHarvest's installer builds the desktop-icon and launch choices from native Windows checkboxes instead, so they announce as checked and not checked. The installer is the first thing a new user meets; it is not a good place to start guessing. |
| Downloads are signed and hashed | The application, everything in its bundle, and the installer carry Authenticode signatures through Azure Trusted Signing, so Windows names the publisher instead of raising a SmartScreen warning — a warning that reads especially badly aloud. Each release also publishes SHA-256 sums. |

### Known gaps

**The activity log does not announce new lines.** This is the most important limitation to understand, and an earlier version of this document wrongly claimed otherwise.

wxWidgets exposes MSAA/`IAccessible` only. It has no live-region API on any platform, ships no UI Automation provider, and cannot raise UIA notification events. The activity log is a standard read-only multi-line text control; appending to it fires a value-change event that NVDA, JAWS, and Narrator all deliberately ignore for controls that do not have focus.

In practice this means **a run does not announce its own progress or completion**. What you can do instead:

- Focus the log (**Ctrl+L**) and read it with arrow keys or the screen reader review cursor. Appending no longer moves your caret while you are reading back through it.
- Read the status bar on demand: **NVDA+End**, or **JAWS Insert+Page Down**.
- Progress percentages are written into the log as text, so they are readable on demand even though they are not spoken automatically.

**Since this version podHarvest can speak instead.** **Settings ▸ Announcements** offers spoken output for errors, run completions and per-episode progress, each chosen separately, and braille through the same screen reader. All four are off by default, and the component that does the talking is downloaded only when you press **Set up announcements** — nothing is installed without being asked, and nothing is spoken that you did not turn on.

The limitation itself is unchanged: the log control still cannot announce itself, and this speaks around it rather than fixing it. If no screen reader is running and SAPI is unavailable, announcements silently do nothing rather than failing.

**A note on accessible names, since it caused real bugs.** `set_accessible_name` attaches a `wx.Accessible` to a control, and on Windows that object also answers for the control's *children*. Applied to a list, a notebook or a radio group, it therefore overrode what the native control knew: rows announced as bare index numbers, every notebook tab took the notebook's own name, and checkbox state changes went unspoken. Those controls now keep their native accessibility and are named the ordinary way — their own label, or the `wx.StaticText` created immediately before them. The helper is for controls that genuinely have no label to borrow. Anything list-like, tabbed, grouped or checkable should be left to the platform, which knows more about it than we do.

For the same reason the OPML import list is a `wx.ListCtrl` with `EnableCheckBoxes`, not a `wx.CheckListBox`: the check list box is owner-drawn on Windows and exposes neither its rows nor its check states.

Also outstanding:

- The window uses a fixed default size in raw pixels with no scrolled container, so at very high display scaling some content can be clipped.
- Playback speed depends on the platform's own media backend. The speeds offered are a setting (0.25x to 5x, defaulting to 0.5x-3x), and a backend can accept one and refuse another — so a refusal is reported per speed, naming it, rather than once ever. It is still a refusal: podHarvest cannot make a backend go faster than it will.
- The Local files source has not been through a manual screen reader pass; see [Testing status](#testing-status).
- Tab order inside "Transcript options" follows control creation order, which differs from the visual order for one pair of controls.
- macOS strips `&` mnemonics entirely; the Ctrl-based shortcuts are the portable path.

## Command-line interface

Verified against `cli.py`:

- No command requires interactive or TTY-only input. Anything the CLI can prompt for also has a corresponding flag, so it is fully scriptable and behaves identically under a screen reader, a CI runner, or a plain terminal. `--no-gui-prompt` (or `PODHARVEST_NO_GUI=1`) suppresses the optional GUI offer.
- Running with no arguments always prints full usage text - never a stack trace, never silent behavior.
- Output never depends on color; no ANSI escapes are emitted anywhere. `-q`/`-v`/`-vv` control verbosity and `--log-file` gives a persistent plain-text record.
- Errors are specific and actionable - naming the exact missing dependency and the command that fixes it - wherever podHarvest controls the error path.

The progress bar drawn on a TTY is a `\r`-updated ASCII bar, which reads poorly. It is suppressed automatically when output is not a terminal, and `--log-file` always receives plain percentage lines instead.

## Generated output

This matters as much as the tool's own interface - the point of podHarvest is to produce durable, accessible archives.

- **HTML** is produced by an allow-list sanitizer (`podharvest/convert.py`). It preserves real `<h1>`–`<h6>` headings, `<ul>`/`<ol>`/`<li>`, `<dl>`, `<table>` with `<caption>`, `<th>`, `scope` and `headers`, `<figure>`/`<figcaption>`, and `<track>` caption tracks on media.
- Each episode page has a `<main>` landmark, exactly one `<h1>`, and a link back to the feed index. Headings supplied by the feed are demoted so they nest under the page title instead of competing with it, and empty headings are dropped.
- An `index.html` is generated alongside `index.md`, so the HTML archive is navigable rather than a set of orphan files.
- Episode metadata is emitted as a `<dl>`, so each label is programmatically associated with its value.
- The page `lang` attribute is validated as a language tag and normalized (`en_US` → `en-US`); a feed that declares nothing falls back to `en`.
- The only CSS is a line-length limit, image scaling, table borders, and `color-scheme: light dark`. No colors or font sizes are set, so your own theme, contrast settings, and text size all win.
- **Markdown** preserves heading levels, list nesting, and descriptive link text. Tables are emitted as pipe tables.
- **Plain text** flattens Markdown into a linear document with link targets kept visible (`link text (https://...)`), suitable for braille displays.
- **Transcripts** support toggling timestamps and speaker labels independently, plus timestamp style, speaker-label style, paragraph grouping, and line-wrap width, so you can choose the least noisy format that still meets your needs.

### Known gaps in generated output

- Images with no `alt` attribute are given `alt=""`, which marks them decorative. That is a claim the sanitizer cannot actually verify - it is a safe default, not preservation of information the feed never supplied.
- Inline `<svg>` and `<iframe>` embeds are removed for safety, currently without leaving a placeholder saying something was there.
- A Markdown pipe table cannot express `scope`, `headers`, `<caption>`, or merged cells. Tables with those features lose that structure in the Markdown and plain-text outputs; the HTML output keeps it.
- Tables whose header row is not the first row, or that use row headers only, are not detected correctly by the Markdown converter.
- Relative URLs in feed content are not resolved against the feed's base URL.

## Reporting an accessibility issue

Write to **support@community-access.org**, or open a GitHub issue — whichever suits you. **Help ▸ Report a bug** inside the app assembles the useful context for you, shows you all of it, and removes anything private before you send it.

Please describe:

- the assistive technology and version you were using,
- the control or output you were interacting with,
- what you expected to hear or see, and
- what actually happened.

If you are reporting something you heard rather than saw, quoting what the screen reader actually said is worth more than a description of it.

Accessibility issues are treated as high priority. Version 1.0.0 has been tested with NVDA, JAWS and Narrator on Windows with no problems found, so the most useful reports now are from anywhere that pass did not reach: VoiceOver on macOS, Orca on Linux, braille displays, or any workflow that behaves differently from the one tested.
