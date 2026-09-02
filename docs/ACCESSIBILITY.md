# Accessibility statement

podharvest is built for people who rely on assistive technology, and accessibility is treated as a functional requirement rather than a visual afterthought.

This document is deliberately specific about **what has been verified, what is implemented but unverified, and what does not work**. An overstated accessibility claim is worse than a missing feature: it tells someone to rely on something that will not be there. Where an earlier version of this document made a claim the code did not support, the claim has been removed and the gap is listed below.

**No manual screen reader pass has yet been performed against either the GUI or the generated output.** Everything below is derived from source review and Windows MSAA inspection. Volunteers to run a real NVDA/JAWS/VoiceOver session are very welcome — see [Reporting an accessibility issue](#reporting-an-accessibility-issue).

## Desktop GUI (wxPython)

### What works

| Requirement | Implementation |
|---|---|
| Labeled groupings | Related controls sit inside `wx.StaticBoxSizer` regions ("Feed", "Options", "Transcript options", "Hardware"), and child controls are parented to the actual `wx.StaticBox` rather than the panel. This produces a genuine grouping role with a name in the accessibility tree, and it is the part of the GUI that holds up best under inspection. |
| Accessible names | Controls with an adjacent `wx.StaticText` take their name from it, which is how Windows names an edit field. Controls with no adjacent label — the progress gauge, the spin controls, the model picker — are given a name through a `wx.Accessible` subclass (`set_accessible_name` in `gui.py`). |
| Keyboard access | Every control is reachable with Tab/Shift+Tab, and no action requires a mouse. Primary actions also have frame-level shortcuts: **Ctrl+R** start, **Esc** cancel, **Ctrl+L** go to the activity log, **Ctrl+D** re-detect hardware. |
| Menu bar | A File/View/Help menu bar gives an Alt/F10 entry point, which is the conventional way to explore an unfamiliar application with a screen reader. Shortcuts are published in the menus and in Help ▸ About. |
| Default action | Enter activates Start, so typing a feed URL and pressing Enter works as expected. |
| No color-only signaling | Validation errors (missing feed URL, no transcription model selected) appear as a modal dialog with a full text explanation, parented to the main window, and focus moves to the field that needs attention. |
| System theming | No colors, fonts, or custom drawing are set anywhere in the GUI. High-contrast themes, focus indicators, and text scaling are all handled natively by the platform. |
| Non-blocking UI | Long-running work happens on a background thread, so focus and keyboard input stay responsive throughout a run. |
| Failure never strands you | If hardware detection fails, transcription is disabled with a spoken-readable explanation and the rest of the app stays usable. It previously left the Start button permanently disabled with no message. |

### Known gaps

**The activity log does not announce new lines.** This is the most important limitation to understand, and an earlier version of this document wrongly claimed otherwise.

wxWidgets exposes MSAA/`IAccessible` only. It has no live-region API on any platform, ships no UI Automation provider, and cannot raise UIA notification events. The activity log is a standard read-only multi-line text control; appending to it fires a value-change event that NVDA, JAWS, and Narrator all deliberately ignore for controls that do not have focus.

In practice this means **a run does not announce its own progress or completion**. What you can do instead:

- Focus the log (**Ctrl+L**) and read it with arrow keys or the screen reader review cursor. Appending no longer moves your caret while you are reading back through it.
- Read the status bar on demand: **NVDA+End**, or **JAWS Insert+Page Down**.
- Progress percentages are written into the log as text, so they are readable on demand even though they are not spoken automatically.

Adding real spoken announcements would require a screen-reader speech bridge (`accessible_output2`, `cytolk`, or the NVDA controller client). That is tracked as an open enhancement, not implemented.

Also outstanding:

- The window uses a fixed default size in raw pixels with no scrolled container, so at very high display scaling some content can be clipped.
- Tab order inside "Transcript options" follows control creation order, which differs from the visual order for one pair of controls.
- macOS strips `&` mnemonics entirely; the Ctrl-based shortcuts are the portable path.

## Command-line interface

Verified against `cli.py`:

- No command requires interactive or TTY-only input. Anything the CLI can prompt for also has a corresponding flag, so it is fully scriptable and behaves identically under a screen reader, a CI runner, or a plain terminal. `--no-gui-prompt` (or `PODHARVEST_NO_GUI=1`) suppresses the optional GUI offer.
- Running with no arguments always prints full usage text — never a stack trace, never silent behavior.
- Output never depends on color; no ANSI escapes are emitted anywhere. `-q`/`-v`/`-vv` control verbosity and `--log-file` gives a persistent plain-text record.
- Errors are specific and actionable — naming the exact missing dependency and the command that fixes it — wherever podharvest controls the error path.

The progress bar drawn on a TTY is a `\r`-updated ASCII bar, which reads poorly. It is suppressed automatically when output is not a terminal, and `--log-file` always receives plain percentage lines instead.

## Generated output

This matters as much as the tool's own interface — the point of podharvest is to produce durable, accessible archives.

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

- Images with no `alt` attribute are given `alt=""`, which marks them decorative. That is a claim the sanitizer cannot actually verify — it is a safe default, not preservation of information the feed never supplied.
- Inline `<svg>` and `<iframe>` embeds are removed for safety, currently without leaving a placeholder saying something was there.
- A Markdown pipe table cannot express `scope`, `headers`, `<caption>`, or merged cells. Tables with those features lose that structure in the Markdown and plain-text outputs; the HTML output keeps it.
- Tables whose header row is not the first row, or that use row headers only, are not detected correctly by the Markdown converter.
- Relative URLs in feed content are not resolved against the feed's base URL.

## Reporting an accessibility issue

Please open a GitHub issue describing:

- the assistive technology and version you were using,
- the control or output you were interacting with,
- what you expected to hear or see, and
- what actually happened.

Accessibility issues are treated as high priority. If you are able to run a screen reader pass against the GUI or the generated HTML and report what you find, that is the single most useful contribution to this project right now.
