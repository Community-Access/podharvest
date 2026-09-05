"""Saying out loud what a run is doing.

podHarvest's oldest and worst limitation is that the activity log cannot
announce itself. wxWidgets exposes MSAA only: it has no live-region API on
any platform, ships no UI Automation provider, and cannot raise a UIA
notification. Appending to a read-only text control fires a value-change
event that NVDA, JAWS and Narrator all deliberately ignore for a control
without focus. So a run could finish, or fail, in silence.

The fix is to stop asking the toolkit and speak to the screen reader
directly. `accessible_output2` does that -- NVDA and JAWS through their own
controller libraries, SAPI when neither is running -- and it reaches a
braille display through the same interface.

Three rules hold this together:

**Nothing here may raise.** Every entry point returns a bool and swallows
its own failures. An app that dies because a screen reader was restarted
mid-run is worse than one that goes quiet.

**Nothing is installed without being asked.** The component arrives through
`acquire`, into the app space, on first use, with consent. Without it every
function returns False and Settings says why.

**Nothing speaks unless it was turned on.** Announcements are off by default
and chosen per category, because an app that talks over you is a worse
companion than one that stays quiet.
"""

from __future__ import annotations

from podharvest.util import LOG

#: The package that does the talking, and roughly how large it is, for the
#: sentence that asks permission to fetch it.
PACKAGE = "accessible_output2"
APPROXIMATE_MB = 2

#: Which settings flag governs which kind of message. A category not in
#: here is never spoken -- a typo at a call site should be silence, not a
#: surprise announcement.
CATEGORIES = {
    "completions": "announce_completions",
    "progress": "announce_progress",
    "errors": "announce_errors",
}

_cached_output = None
_looked_for_output = False


def _output():
    """The speech object, or None. Imported lazily, never at start-up.

    Importing at module scope would make an optional component a hard
    dependency of the module, which is exactly what `dependencies = []`
    forbids.
    """
    global _cached_output, _looked_for_output
    if _looked_for_output:
        return _cached_output
    _looked_for_output = True
    try:
        import accessible_output2.outputs.auto

        _cached_output = accessible_output2.outputs.auto.Auto()
    except Exception as exc:  # noqa: BLE001 - any failure means "no speech"
        LOG.debug("Spoken announcements are not available: %s", exc)
        _cached_output = None
    return _cached_output


def is_available() -> bool:
    """Whether anything can be spoken right now."""
    return _output() is not None


def forget() -> None:
    """Drop the cached speech object, so the next call looks again.

    Called after installing the component, so it becomes usable without a
    restart.
    """
    global _cached_output, _looked_for_output
    _cached_output = None
    _looked_for_output = False


def ensure_installed(app_space) -> bool:
    """Install the speech component into the app space. True when ready."""
    if is_available():
        return True
    from podharvest import acquire

    # `ensure_package` takes the pip name and the import name separately,
    # because they differ for plenty of packages. Here they are the same.
    if not acquire.ensure_package(app_space, PACKAGE, PACKAGE):
        return False
    forget()
    return is_available()


def speak(text: str, *, interrupt: bool = False) -> bool:
    """Say *text*. False when nothing could say it.

    *interrupt* cuts off whatever is being spoken, which is right for an
    error and wrong for a progress note.
    """
    output = _output()
    if output is None or not text:
        return False
    try:
        output.output(text, interrupt=interrupt)
        return True
    except Exception as exc:  # noqa: BLE001 - a reader that went away
        LOG.debug("Could not speak: %s", exc)
        return False


def braille(text: str) -> bool:
    """Send *text* to a braille display. False when nothing could."""
    output = _output()
    if output is None or not text:
        return False
    try:
        output.braille(text)
        return True
    except Exception as exc:  # noqa: BLE001 - not every output does braille
        LOG.debug("Could not braille: %s", exc)
        return False


def say(text: str, *, category: str, settings) -> None:
    """Announce *text* if this category is turned on. Never raises.

    This is what the rest of the app calls. It is deliberately a no-op in
    every uncertain case: an unknown category, a missing setting, no
    component installed.
    """
    flag = CATEGORIES.get(category)
    if flag is None:
        return
    if not getattr(settings, flag, False):
        return
    spoke = speak(text, interrupt=(category == "errors"))
    if spoke and getattr(settings, "announce_braille", False):
        braille(text)
