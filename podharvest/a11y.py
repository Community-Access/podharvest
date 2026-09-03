"""Making controls announce themselves, and be big enough to read.

Lifted out of `podharvest.gui` when the Tag and Chapter Editor arrived and
needed the same helper without importing the whole main window. `gui` still
re-exports both names, so nothing that used them before had to change.

The same helper, with the same signature, now lives in QUILL Audio Studio
(`quill/ui/audio_studio/pages_base.py`) -- part of the alignment work in
docs/ALIGNMENT-audio-tags-and-chapters.md. It went that way rather than the
other because this is the stronger of the two implementations: it states the
name outright instead of leaving the platform to derive one.

`size_for_text` joined it for the same audience and the same reason. A text
box sized in raw pixels is sized for one font at one scaling factor: set
Windows text scaling to 200% and a 90-pixel box that used to show five lines
shows one, with the rest behind a scrollbar. Sizing by the control's own font
metrics means the box grows with the text it has to hold, which is what
somebody who scaled their text up was asking for.
"""

from __future__ import annotations

import wx


class _Named(wx.Accessible):
    """Gives a control a real accessible name.

    `wx.Window.SetName()` only sets the internal `FindWindowByName` key; it
    reaches neither MSAA/UIA, AT-SPI nor NSAccessibility. Controls that have
    no adjacent `wx.StaticText` to borrow a name from need this instead.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def GetName(self, childId):  # noqa: N802 - wx API casing
        return (wx.ACC_OK, self._name)


def set_accessible_name(ctrl: wx.Window, name: str) -> None:
    """Attach an accessible name to `ctrl` and keep it alive.

    `SetAccessible` does not take ownership, so the helper is stashed on the
    control; without that reference it is garbage collected and the name
    silently disappears.
    """
    ctrl.SetName(name)                  # still useful for FindWindowByName
    try:
        helper = _Named(name)
        ctrl.SetAccessible(helper)
        ctrl._a11y_helper = helper      # noqa: SLF001 - keep a strong reference
    except (AttributeError, NotImplementedError):
        # wx.Accessible is Windows-only; elsewhere the label heuristic and
        # the platform's own defaults apply.
        pass


def size_for_text(ctrl: wx.Window, *, lines: int, chars: int = 0) -> None:
    """Size *ctrl* to hold *lines* lines of its own font, and grow with it.

    Pixels are the wrong unit for a box that holds text. The same 90 pixels is
    five comfortable lines at 100% scaling and barely one at 200%, so a box
    specified that way quietly stops working for exactly the people most likely
    to have turned scaling up. Asking the control how tall its own characters
    are costs nothing and tracks the font, the theme and the display.

    Sets the *minimum* size rather than the size, so sizers can still stretch
    the control to fill space -- the floor is "enough to read", not a ceiling.
    Passing *chars* also sets a minimum width in characters, for a box whose
    line length matters.
    """
    try:
        char_height = ctrl.GetCharHeight()
        char_width = ctrl.GetCharWidth()
    except Exception:  # noqa: BLE001 - a control that will not measure itself
        return
    if char_height <= 0:
        return
    # A little vertical padding: wx puts a border and internal margin inside a
    # text control, and a box measured to the exact glyph height clips the last
    # line's descenders.
    height = char_height * max(1, int(lines)) + char_height
    width = char_width * int(chars) if chars else -1
    ctrl.SetMinSize(wx.Size(width, height))
