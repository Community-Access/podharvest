"""A status bar you can actually get to, read, and act on.

wx's own status bar is a strip of text nothing can reach. It cannot take
focus, so a screen reader user can only read it by hunting with a review
cursor, and nothing announces when it changes. podHarvest used one, wrote
"Detecting hardware..." into it, and then never wrote anything else -- so the
window sat claiming it was detecting hardware long after it had finished.
That is the failure mode of a control nobody can look at: nobody notices it
lying.

QUILL solved this in its editor and repeated it in Radio and Audio Studio
(`quill/ui/audio_studio/status_bar.py`). This is podHarvest's version of the
same idea, and the behaviour is deliberately identical so the programs feel
like a set:

* **F6** moves focus into the bar, and again (or Escape) hands it back to
  wherever it came from.
* **Left and Right** move between cells; **Home** and **End** jump to the ends.
* **Enter** or **Space** activates the cell -- each one does the useful thing
  for what it shows, rather than all of them doing nothing.
* **The context menu key** offers that action plus copying the value and
  hiding the bar.
* **Tab** treats the whole bar as one stop in the window's tab order, not one
  stop per cell, so tabbing past it does not mean pressing Tab six times.

Every cell is a real button, which is what makes all of the above work: a
button has a name, a role, a help string and a focus event, and every screen
reader already knows what to do with one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CellSpec:
    """One cell: a stable key, a spoken name, live text, and what Enter does.

    `text` returns the current value, or "" for "nothing to say" -- in which
    case the cell reads as just its name rather than as a name and an empty
    string.
    """

    key: str
    name: str
    text: Callable[[], str]
    activate: Callable[[], None]
    help: str


@dataclass
class _Cell:
    spec: CellSpec
    button: Any


def clamp_index(index: int, count: int) -> int:
    """Hold *index* inside the bar. Wraps at neither end, on purpose.

    Arrowing off the end of a toolbar and reappearing at the other end is
    disorienting when you cannot see it happen: you lose track of where you
    are. Stopping is quieter and more predictable.
    """
    if count <= 0:
        return 0
    return max(0, min(index, count - 1))


class StatusBar:
    """The focusable, arrow-navigable status bar for the main window."""

    def __init__(self, host: Any, wx: Any) -> None:
        self._host = host
        self._wx = wx
        self._panel: Any = None
        self._cells: list[_Cell] = []
        self._active_index = 0
        #: Where focus was before F6, so Escape hands it straight back rather
        #: than guessing at somewhere reasonable.
        self._return_focus: Any = None
        self._entering = False
        self._specs = self._build_specs()

    # -- construction -----------------------------------------------------

    def _cell_button_class(self) -> Any:
        """A button that F6 can reach but Tab cannot.

        The bar is a review surface, not a step in the workflow. Left in the
        tab order it adds five stops between the last real control and the
        end of the window, every time round, for information the user asked
        to be able to *check* rather than to walk through. F6 is the way in
        and out, which is where a status bar belongs on Windows.

        `AcceptsFocusFromKeyboard` is the right lever: it takes the control
        out of tab traversal while leaving `SetFocus` working, so F6 and the
        arrow keys inside the bar are unaffected. Built lazily against the
        injected `wx` so the module stays importable without it.
        """
        wx = self._wx
        cached = getattr(self, "_button_class", None)
        if cached is not None:
            return cached

        class _StatusCellButton(wx.Button):
            def AcceptsFocusFromKeyboard(self):  # noqa: N802 - wx API casing
                return False

        self._button_class = _StatusCellButton
        return _StatusCellButton

    def build(self, parent: Any) -> Any:
        """Build the bar as a child of *parent* and return the panel."""
        wx = self._wx
        panel = wx.Panel(parent, style=wx.TAB_TRAVERSAL)
        panel.SetName("Status bar")
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._panel = panel
        self._cells = []
        context_event = getattr(wx, "EVT_CONTEXT_MENU", None)
        button_class = self._cell_button_class()
        for spec in self._specs:
            button = button_class(panel, label=self._label(spec),
                                  style=wx.BU_EXACTFIT)
            button.SetName(self._name(spec))
            button.SetHelpText(spec.help)
            button.SetToolTip(spec.help)
            button.Bind(wx.EVT_BUTTON, lambda _e, s=spec: self._activate(s))
            button.Bind(wx.EVT_KEY_DOWN, lambda e, s=spec: self._on_key(e, s))
            button.Bind(wx.EVT_SET_FOCUS, lambda e, s=spec: self._on_focus(e, s))
            if context_event is not None:
                button.Bind(context_event,
                            lambda e, s=spec: self._on_context_menu(e, s))
            sizer.Add(button, 0, wx.EXPAND | wx.ALL, 2)
            self._cells.append(_Cell(spec=spec, button=button))
        panel.SetSizer(sizer)
        return panel

    # -- what the cells are -----------------------------------------------

    def _build_specs(self) -> list[CellSpec]:
        host = self._host
        return [
            CellSpec(
                key="activity",
                name="Activity",
                text=lambda: _value(host, "status_activity", "Ready"),
                activate=lambda: _call(host, "_on_focus_log", None),
                help=("What podHarvest is doing right now. Enter jumps to the "
                      "activity log, which has the detail."),
            ),
            CellSpec(
                key="progress",
                name="Progress",
                text=lambda: _value(host, "status_progress", ""),
                activate=lambda: _call(
                    host, "_announce",
                    _value(host, "status_progress_detail", "Nothing is running.")),
                help=("How far along a run is. Enter says the whole thing: "
                      "which episode, how far through, and how much is left."),
            ),
            CellSpec(
                key="source",
                name="Source",
                text=lambda: _value(host, "status_source", ""),
                activate=lambda: _call(host, "_focus_source"),
                help=("Whether you are working from a search, a feed, or your "
                      "own files. Enter jumps to that box."),
            ),
            CellSpec(
                key="model",
                name="Model",
                text=lambda: _value(host, "status_model", ""),
                activate=lambda: _call(host, "_status_model_action"),
                help=("The transcription model and whether it is downloaded. "
                      "Enter downloads it if it is not, or jumps to the "
                      "picker if it is."),
            ),
            CellSpec(
                key="library",
                name="Library",
                text=lambda: _value(host, "status_library", ""),
                activate=lambda: _call(host, "_focus_episodes"),
                help=("How much is in the Episodes list. Enter jumps to the "
                      "list."),
            ),
            CellSpec(
                key="clock",
                name="Time",
                text=self._clock,
                activate=self._say_clock,
                help="The time. Enter says the full date and time.",
            ),
        ]

    def _clock(self) -> str:
        try:
            return datetime.now().strftime("%H:%M")
        except Exception:  # noqa: BLE001 - a status cell must never raise
            return ""

    def _say_clock(self) -> None:
        try:
            stamp = datetime.now().strftime("%A %d %B, %H:%M")
        except Exception:  # noqa: BLE001
            return
        _call(self._host, "_announce", stamp)

    # -- keeping it current -----------------------------------------------

    def _label(self, spec: CellSpec) -> str:
        value = spec.text()
        return f"{spec.name}: {value}" if value else spec.name

    def _name(self, spec: CellSpec) -> str:
        # Comma rather than colon: a screen reader pauses at a comma, which is
        # what makes "Model, small.en, ready" read as three facts.
        value = spec.text()
        return f"{spec.name}, {value}" if value else spec.name

    def refresh(self) -> None:
        """Repaint every cell from live state. Safe on a destroyed window."""
        changed = False
        for cell in self._cells:
            try:
                label = self._label(cell.spec)
                if cell.button.GetLabel() != label:
                    cell.button.SetLabel(label)
                    cell.button.SetName(self._name(cell.spec))
                    changed = True
            except RuntimeError:
                continue
        if changed and self._panel is not None:
            try:
                self._panel.Layout()
            except RuntimeError:
                pass

    def is_shown(self) -> bool:
        return bool(self._panel is not None and self._panel.IsShown())

    def set_visible(self, shown: bool) -> None:
        if self._panel is None:
            return
        self._panel.Show(shown)
        parent = self._panel.GetParent()
        if parent is not None:
            parent.Layout()

    # -- getting into and out of it ---------------------------------------

    def has_focus(self) -> bool:
        wx = self._wx
        if wx is None or not self._cells:
            return False
        focused = wx.Window.FindFocus()
        return any(cell.button is focused for cell in self._cells)

    def focus_bar(self, return_focus: Any = None) -> None:
        """Move focus into the bar, remembering where to hand it back."""
        if not self._cells or not self.is_shown():
            return
        self._return_focus = return_focus
        self._entering = True
        self._focus_cell(self._active_index)

    def toggle_focus(self, return_focus: Any = None) -> None:
        """F6: into the bar, or back out of it if already there."""
        if self.has_focus():
            self._leave()
        else:
            self.focus_bar(return_focus)

    def _focus_cell(self, index: int) -> None:
        if not self._cells:
            return
        self._active_index = clamp_index(index, len(self._cells))
        try:
            self._cells[self._active_index].button.SetFocus()
        except RuntimeError:
            pass

    def _index_of(self, spec: CellSpec) -> int:
        for index, cell in enumerate(self._cells):
            if cell.spec.key == spec.key:
                return index
        return 0

    def _on_focus(self, event: Any, spec: CellSpec) -> None:
        self._active_index = self._index_of(spec)
        entering = self._entering
        self._entering = False
        # "Status bar," only on the way in. Repeating the region name on every
        # arrow press is the kind of thing that makes people stop using a
        # feature.
        value = spec.text()
        prefix = "Status bar, " if entering else ""
        _call(self._host, "_announce",
              f"{prefix}{spec.name}, {value}" if value else f"{prefix}{spec.name}")
        event.Skip()

    def _on_key(self, event: Any, spec: CellSpec) -> None:
        wx = self._wx
        code = event.GetKeyCode()
        index = self._index_of(spec)
        if code == wx.WXK_LEFT:
            self._focus_cell(index - 1)
            return
        if code == wx.WXK_RIGHT:
            self._focus_cell(index + 1)
            return
        if code == wx.WXK_HOME:
            self._focus_cell(0)
            return
        if code == wx.WXK_END:
            self._focus_cell(len(self._cells) - 1)
            return
        if code == wx.WXK_TAB:
            # One stop in the tab order for the whole bar, not one per cell.
            forward = not event.ShiftDown()
            flag = (wx.NavigationKeyEvent.IsForward if forward
                    else wx.NavigationKeyEvent.IsBackward)
            self._panel.Navigate(flag)
            return
        if code == wx.WXK_ESCAPE:
            self._leave()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self._activate(spec)
            return
        event.Skip()

    def _leave(self) -> None:
        target = self._return_focus
        self._return_focus = None
        if target is not None:
            try:
                target.SetFocus()
                _call(self._host, "_announce", "Left the status bar")
                return
            except RuntimeError:
                pass
        _call(self._host, "_focus_episodes")

    # -- acting on a cell --------------------------------------------------

    def _activate(self, spec: CellSpec) -> None:
        try:
            spec.activate()
        except Exception:  # noqa: BLE001 - a bad cell must not take the bar down
            _call(self._host, "_announce", f"Could not act on {spec.name}")

    def _on_context_menu(self, _event: Any, spec: CellSpec) -> None:
        wx = self._wx
        menu = wx.Menu()

        activate_id = wx.NewIdRef()
        menu.Append(activate_id, "&Activate")
        menu.Bind(wx.EVT_MENU, lambda _e: self._activate(spec), id=activate_id)

        copy_id = wx.NewIdRef()
        menu.Append(copy_id, "&Copy this value")
        menu.Bind(wx.EVT_MENU, lambda _e: self._copy(spec), id=copy_id)

        say_id = wx.NewIdRef()
        menu.Append(say_id, "&Say it again")
        menu.Bind(wx.EVT_MENU,
                  lambda _e: _call(self._host, "_announce", self._name(spec)),
                  id=say_id)

        menu.AppendSeparator()
        hide_id = wx.NewIdRef()
        menu.Append(hide_id, "&Hide the status bar")
        menu.Bind(wx.EVT_MENU,
                  lambda _e: _call(self._host, "_toggle_status_bar"), id=hide_id)

        target = next((c.button for c in self._cells
                       if c.spec.key == spec.key), None)
        (target or self._panel).PopupMenu(menu)
        menu.Destroy()

    def _copy(self, spec: CellSpec) -> None:
        wx = self._wx
        value = spec.text() or spec.name
        if not wx.TheClipboard.Open():
            _call(self._host, "_announce", "Could not reach the clipboard")
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(value))
        finally:
            wx.TheClipboard.Close()
        _call(self._host, "_announce", f"Copied: {value}")

    # -- for tests ---------------------------------------------------------

    def cell_keys(self) -> list[str]:
        return [spec.key for spec in self._specs]

    def cell_text(self, key: str) -> str:
        for spec in self._specs:
            if spec.key == key:
                return spec.text()
        return ""

    def activate(self, key: str) -> None:
        for spec in self._specs:
            if spec.key == key:
                self._activate(spec)
                return


def _call(host: Any, name: str, *args: Any) -> None:
    method = getattr(host, name, None)
    if callable(method):
        method(*args)


def _value(host: Any, name: str, default: str) -> str:
    method = getattr(host, name, None)
    if not callable(method):
        return default
    try:
        value = method()
    except Exception:  # noqa: BLE001 - a status cell must never raise
        return default
    return value if isinstance(value, str) else default
