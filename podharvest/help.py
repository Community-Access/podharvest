"""F1 answers everywhere: what this window is for, then what this control does.

The same contract every QUILL app keeps (`quill/ui/app_context_help.py` and
`quill/core/control_help.py`), brought here because podHarvest is the same kind
of program for the same people and there is no reason pressing F1 should do
nothing in one of them.

Two halves, in the order they are read out:

1. **The window's purpose.** One authored paragraph per surface, keyed by
   title, saying what this window is for and the one fact that saves an email.
   `PURPOSES` below is the catalogue; a window missing from it falls back to an
   honest generic sentence rather than to silence.
2. **The control under focus.** Its name, whatever help was authored on it, and
   how to drive a control of that kind. Composed so it is **never empty**: even
   a control nobody has written a sentence for still answers with its name and
   its role, because "F1 did nothing" is indistinguishable from "F1 is broken".

Three things learned in QUILL that are repeated here rather than rediscovered:

* **`SetHelpText` stores nothing without a `wx.HelpProvider`.** Install one at
  startup or every help sentence ever written is dead and nothing says so.
  `ensure_help_provider` is called from `install`, so wiring F1 wires this too.
* **Authored help belongs at the construction site**, which is the only place
  an audit can verify it. `explain` sets the tooltip and the help text together
  so one call does both, and `help_audit.py` checks the coverage.
* **A tooltip is authored help too.** podHarvest wrote its explanations as
  tooltips long before it had F1, and those sentences are good. The reader
  falls back to the tooltip rather than pretending the control is undocumented.
"""

from __future__ import annotations

from typing import Any

#: The honest fallback for a window with no authored purpose yet. Deliberately
#: plain: it is the floor every surface stands on, and the catalogue lifts it.
GENERIC_PURPOSE = (
    "A window in podHarvest. Tab moves between its controls, Escape closes it, "
    "and F1 on any control explains that control."
)

#: How to *use* a control, by wx class name -- the closing line, so even a
#: control with nothing authored still answers with its name, role and keys.
ROLE_USAGE: dict[str, str] = {
    "Button": "A button: press Enter or Space to press it.",
    "ToggleButton": (
        "A toggle button: press Space to switch it, and it stays pressed "
        "until you switch it back."
    ),
    "CheckBox": "A checkbox: press Space to check or uncheck it.",
    "TextCtrl": (
        "A text field: type into it, or arrow through it to review what it "
        "says. If it is read-only, the text is there to be read and copied."
    ),
    "SearchCtrl": "A search field: type what you are looking for.",
    "ListCtrl": (
        "A list: Up and Down move between rows, and Enter acts on the row."
    ),
    "ListBox": "A list: Up and Down move between rows, and Enter acts on the row.",
    "CheckListBox": (
        "A list of checkboxes: Up and Down move between rows, Space checks or "
        "unchecks the row."
    ),
    "Choice": "A dropdown: Alt+Down opens it, Up and Down choose, Enter picks.",
    "ComboBox": "A combo box: type a value, or Alt+Down to open the list and choose.",
    "Slider": (
        "A slider: Left and Right nudge it, Page Up and Page Down move it in "
        "bigger steps, Home and End jump to the ends."
    ),
    "SpinCtrl": "A number field: type a value, or Up and Down to step it.",
    "RadioBox": (
        "A group of choices: arrow between them; landing on one selects it."
    ),
    "RadioButton": (
        "One choice in a group: arrow between the options; landing on one "
        "selects it."
    ),
    "Gauge": "A progress readout; it fills as the work completes.",
    "Notebook": (
        "A set of pages: Control+Tab moves to the next page, "
        "Control+Shift+Tab to the previous one."
    ),
    "StaticText": "A label; it names what sits next to it.",
}

GENERIC_USAGE = "Tab moves on to the next control; Shift+Tab goes back."

#: wx's own default names, which say nothing about the control.
_DEFAULT_WX_NAMES = frozenset({
    "", "panel", "control", "dialog", "frame", "staticText", "button",
    "checkBox", "check", "listCtrl", "listBox", "textCtrl", "text", "choice",
    "slider", "gauge", "notebook", "radioBox", "radioButton", "spinCtrl",
    "comboBox", "message", "scrolledWindow",
})

#: What each window is *for*, keyed by title (prefix-matched, so a title that
#: carries live data still resolves). One to three sentences: the first says
#: what the window is for, the rest say what somebody actually does here.
PURPOSES: dict[str, str] = {
    "Report a bug": (
        "Builds a report you can read before any of it goes anywhere. It "
        "gathers the version, this machine's platform and hardware, whether "
        "FFmpeg is present, the settings that differ from the defaults, and "
        "the recent activity log, then removes API keys, your home folder "
        "name and email addresses. Nothing is sent by this window: you choose "
        "whether to copy it, save it to a file, or open a pre-filled message."
    ),
    "Find a podcast": (
        "Searches Apple's podcast directory by name, so you do not have to "
        "hunt for a feed address. Type the show, a presenter or a subject and "
        "press Enter; the results list can be arrowed through, and Enter on "
        "one takes its feed back to the main window. Search options narrow "
        "what your words are matched against and which country's store is "
        "asked, since stores carry different shows. Add to favourites "
        "remembers a show without harvesting it; nothing here downloads "
        "anything or subscribes you to anything."
    ),
    "Import a list of podcasts": (
        "Reads an OPML file -- the format podcast apps use to hand each other "
        "a list of shows -- and lets you pick which of them to keep. Give a "
        "web address or choose a file, press Read the list, then check what "
        "you want and press Add checked to favourites. Check the new ones skips "
        "anything already in your favourites, which is what you usually want "
        "when re-reading a list. Importing adds bookmarks and nothing else: "
        "no subscription, no checking for new episodes, no downloading. Use "
        "this one now takes the highlighted show straight to the main window "
        "instead."
    ),
    "Chapters - ": (
        "Lists the loaded episode's chapter markers with their start times, "
        "so a two-hour episode can be navigated by ear instead of held-down "
        "Forward. The row highlighted when this opens is the chapter playing "
        "now. Arrow to another and press Enter or Go to chapter, and playback "
        "continues from there; Close leaves playback where it was. Episodes "
        "without markers say so -- the Tag and Chapter Editor can add them."
    ),
    "New episodes in your favourites": (
        "Asks each favourite's feed what it has published since you last "
        "marked the list as seen, and reports one line per show: how many "
        "episodes are new, or that nothing is, or that the show could not "
        "be checked. The check runs only when you open this window or press "
        "Check again -- nothing polls in the background, and nothing is "
        "downloaded. Enter on a show takes its feed to the main window; "
        "Mark all as seen makes now the starting point for the next check."
    ),
    "Search all transcripts": (
        "Finds a word or phrase in every transcript in the library, and "
        "lists one row per episode that contains it: the show, the episode, "
        "how many times it appears, and the first place it does. "
        "Capitalisation does not matter. Enter on a row opens that "
        "transcript in the reader with the search already run, so the next "
        "Enter is already walking the matches. Nothing is downloaded or "
        "changed; this reads what is on disk."
    ),
    "Favourite podcasts": (
        "The shows you have marked, so you can come back to one without "
        "searching for it again. Arrow through the list; Enter takes the "
        "highlighted show's feed back to the main window, and Remove takes it "
        "off this list without touching anything you have already harvested "
        "from it. These are bookmarks rather than subscriptions: podHarvest "
        "never checks them for new episodes or downloads anything on its own."
    ),
    "podHarvest": (
        "The main window. Paste a podcast's address into Feed URL, choose "
        "whether you want transcripts, and press Start; everything else has a "
        "sensible default. The Episodes list shows each episode and how far "
        "along it is, and Control+L jumps to the activity log, which explains "
        "in ordinary words what is happening and anything that went wrong. "
        "Control+T opens the selected episode's tags and chapters. "
        "Control+K searches Apple's directory when you know a show's name but "
        "not its address, and Control+Shift+E lists what a feed holds without "
        "downloading any of it."
    ),
    "Settings": (
        "Everything podHarvest remembers between runs: where files go and how "
        "they are named, how transcripts are formatted, which optional cloud "
        "provider to use, and where the log is written. Nothing here starts a "
        "run; it changes what the next one does."
    ),
    "Tags and chapters": (
        "Every tag this episode's audio file can carry, over six pages, plus "
        "its chapter markers. Control+Tab moves between pages. On the Chapters "
        "page, Alt with Left or Right nudges the selected chapter's start by "
        "one step and Hear boundary plays a few seconds either side, which is "
        "how a marker gets put where the sentence actually starts. Nothing is "
        "written to the file until you press Save."
    ),
    "Edit chapter": (
        "This chapter's title and its exact start and end, typed rather than "
        "set by ear, plus the optional link and image a Podcasting 2.0 player "
        "can show. Moving the start moves the end of the chapter before it, so "
        "the episode stays gapless; the sentence at the top tells you the "
        "range this chapter is allowed to occupy."
    ),
    "Transcript": (
        "The words of this episode, exactly as they were written to disk. "
        "Find at the top jumps to a word and says which occurrence you are "
        "on, which is the useful operation on an hour of speech; the text "
        "itself is read-only, so arrow through it or select and copy. Open "
        "the file hands it to whatever your system uses for text."
    ),
    "Media tools": (
        "Whether FFmpeg is installed, and what podHarvest uses it for. Every "
        "one of those features fails quietly without it -- the episode still "
        "downloads, it just never gains chapter markers -- which is why this "
        "window exists to be asked."
    ),
    "About": (
        "Which version of podHarvest this is, where the project lives, and the "
        "keyboard shortcuts for everything the main window can do."
    ),
}


def purpose_for_title(title: str) -> str:
    """The authored purpose for a window title, never empty.

    Prefix-matched, because plenty of titles carry live data after the name --
    "Tags and chapters - 0042-an-episode.mp3" is still the tag editor.
    """
    stripped = str(title or "").strip()
    if stripped in PURPOSES:
        return PURPOSES[stripped]
    for prefix, purpose in PURPOSES.items():
        if stripped.startswith(prefix):
            return purpose
    return GENERIC_PURPOSE


def role_usage(class_name: str) -> str:
    """One sentence on driving a control of wx class *class_name*."""
    return ROLE_USAGE.get(class_name, GENERIC_USAGE)


def compose_control_body(*, accessible_name: str, help_text: str, usage: str) -> str:
    """The control section, from whichever pieces exist. Never empty.

    With nothing authored it still says what the control is called and how to
    drive its kind, because a silent F1 cannot be told from a broken one.
    Pieces are never repeated: help text that *is* the name appears once.
    """
    parts: list[str] = []
    name = str(accessible_name or "").strip()
    body = str(help_text or "").strip()
    if body:
        parts.append(body)
    if name and name.lower() not in body.lower():
        parts.insert(0, f"{name}.")
    if usage:
        parts.append(usage)
    return "\n\n".join(parts) if parts else GENERIC_USAGE


# ------------------------------------------------------------ the wx half


def ensure_help_provider(wx: Any = None) -> None:
    """Install a help provider once, so ``SetHelpText`` actually stores text.

    Without one, every ``SetHelpText`` in the program silently stores nothing
    and ``GetHelpText`` answers "" -- measured in QUILL, not assumed. Idempotent
    and safe before any window exists.
    """
    if wx is None:
        import wx as wx_module

        wx = wx_module
    if wx.HelpProvider.Get() is None:
        wx.HelpProvider.Set(wx.SimpleHelpProvider())


def explain(ctrl: Any, text: str) -> None:
    """Author one control's help, as both a tooltip and F1 help.

    One call rather than two because they are the same sentence, and because a
    control that has one and not the other is the failure this prevents.
    """
    try:
        ctrl.SetToolTip(text)
    except Exception:  # noqa: BLE001 - not every widget takes a tooltip
        pass
    try:
        ctrl.SetHelpText(text)
    except Exception:  # noqa: BLE001 - nor a help text
        pass


def _clean_label(control: Any) -> str:
    get_label = getattr(control, "GetLabel", None)
    label = get_label() if callable(get_label) else ""
    if not isinstance(label, str):
        return ""
    return label.replace("&", "").split("\t")[0].strip()


def _accessible_name(control: Any) -> str:
    """What to call this control: its visible label, else its set name.

    The label comes first because a control that has one is best identified by
    it -- a button reads as "Start", not as whatever name the code gave it --
    and because wx hands out its own default names ("check", "button", "text")
    that say nothing and are easy to mistake for authored ones. Listing every
    wx default was the first attempt and it missed several, which is how a
    checkbox came to introduce itself as "check".
    """
    label = _clean_label(control)
    if label:
        return label
    get_name = getattr(control, "GetName", None)
    name = get_name() if callable(get_name) else ""
    if not isinstance(name, str) or name.strip() in _DEFAULT_WX_NAMES:
        return ""
    return name.strip()


def help_text_of(control: Any) -> str:
    """The authored help on *control*: its help text, or its tooltip.

    The tooltip is a real fallback, not a consolation: podHarvest wrote its
    explanations as tooltips before it had F1, and those sentences are the
    documentation. Reading them is how F1 arrived already covered.
    """
    get_help = getattr(control, "GetHelpText", None)
    text = get_help() if callable(get_help) else ""
    if isinstance(text, str) and text.strip():
        return text.strip()
    get_tip = getattr(control, "GetToolTip", None)
    tip = get_tip() if callable(get_tip) else None
    if tip is not None:
        try:
            tip_text = tip.GetTip()
        except Exception:  # noqa: BLE001 - a tooltip that will not answer
            return ""
        if isinstance(tip_text, str) and tip_text.strip():
            return tip_text.strip()
    return ""


def help_for(window: Any, control: Any = None, wx: Any = None) -> tuple[str, str]:
    """``(heading, body)`` for F1 pressed on *control* inside *window*."""
    if wx is None:
        import wx as wx_module

        wx = wx_module
    if control is None:
        control = wx.Window.FindFocus() or window
    title = ""
    top = window
    while top is not None and not isinstance(top, (wx.Frame, wx.Dialog)):
        top = top.GetParent()
    if top is not None:
        try:
            title = top.GetTitle()
        except Exception:  # noqa: BLE001 - a window without a title
            title = ""

    name = _accessible_name(control)
    body = compose_control_body(
        accessible_name=name,
        help_text=help_text_of(control),
        usage=role_usage(type(control).__name__),
    )
    heading = f"Help: {name}" if name else "Help"
    return heading, f"{purpose_for_title(title)}\n\n{body}"


def show_help(window: Any, wx: Any = None) -> None:
    """Answer F1: the window's purpose, then the focused control's own help."""
    if wx is None:
        import wx as wx_module

        wx = wx_module
    heading, body = help_for(window, wx=wx)
    wx.MessageBox(body, heading, wx.OK | wx.ICON_INFORMATION, window)


def install(window: Any, wx: Any = None) -> None:
    """Turn F1 on for *window*. Every other key falls through untouched.

    Also installs the help provider, so wiring F1 on the first window is what
    makes every ``SetHelpText`` in the program live.
    """
    if wx is None:
        import wx as wx_module

        wx = wx_module
    ensure_help_provider(wx)

    def _on_char_hook(event: Any) -> None:
        if event.GetKeyCode() == wx.WXK_F1 and not event.HasAnyModifiers():
            show_help(window, wx)
            return
        event.Skip()

    window.Bind(wx.EVT_CHAR_HOOK, _on_char_hook)
