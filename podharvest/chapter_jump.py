"""Jumping to a chapter while an episode plays.

podHarvest reads and writes chapter markers, and the transport can seek --
but until now the two never met: the markers were visible only in the Tag
and Chapter Editor, and getting to minute forty of a two-hour episode meant
holding down Forward. For the person most likely to use this app by ear,
that is the difference between "the interview starts at chapter three" being
useful and being trivia.

So: a chapter list for the loaded episode. Arrow to a chapter, press Enter,
and playback continues from there. The list is plain rows -- number, title,
start time -- because that is what a screen reader can read fast, and the
row you land on when the list opens is the chapter you are currently in.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx

from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name
from podharvest.util import LOG

#: One chapter as `chapters.read_chapters` returns it.
Chapter = tuple[float, float, str]


def spoken_time(seconds: float) -> str:
    """A start time as a person says it: "10:00", or "1:02:05" past an hour.

    Not `format_time_precise`: milliseconds are for the editor, where frames
    matter. A row a screen reader speaks wants the shortest true form.
    """
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def row_label(index: int, chapter: Chapter) -> str:
    """One list row: number, title, start time. Spoken in that order.

    The number first because "chapter three" is how people refer to them;
    the time last because it is the detail, not the identity.
    """
    start, _end, title = chapter
    name = str(title or "").strip() or "(untitled chapter)"
    return f"{index + 1}. {name} - {spoken_time(start)}"


def chapter_index_at(chapters: list[Chapter], seconds: float) -> int:
    """Which chapter the playhead is in: the last one starting at or before it.

    Before the first chapter counts as the first, so the list never opens on
    nothing. An empty list is -1, the caller's cue that there is nothing to
    show.
    """
    if not chapters:
        return -1
    found = 0
    for index, (start, _end, _title) in enumerate(chapters):
        if start <= seconds:
            found = index
        else:
            break
    return found


class ChapterJumpDialog(wx.Dialog):
    """The loaded episode's chapters; Enter continues playback from one."""

    def __init__(self, parent: wx.Window, *, chapters: list[Chapter],
                 position_ms: int, episode: str,
                 on_jump: Callable[[int], None]) -> None:
        super().__init__(parent, title=f"Chapters - {episode}",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self._chapters = list(chapters)
        self._on_jump = on_jump

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label="&Chapters in this episode:"), 0,
                 wx.ALL, 10)
        self.list = wx.ListBox(
            self, choices=[row_label(i, c) for i, c in enumerate(self._chapters)])
        self.list.SetToolTip(
            "Every chapter marker in the loaded episode, with its start "
            "time. Enter continues playback from the highlighted chapter; "
            "the row selected when this opened is the chapter playing now.")
        set_accessible_name(self.list, "Chapters in this episode")
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda _e: self._jump())
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        go_btn = wx.Button(self, wx.ID_OK, label="&Go to chapter")
        go_btn.SetToolTip("Continues playback from the highlighted chapter.")
        go_btn.Bind(wx.EVT_BUTTON, lambda _e: self._jump())
        go_btn.SetDefault()
        row.Add(go_btn, 0, wx.RIGHT, 12)
        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window without moving playback.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(480, 400))
        self.Fit()
        self.CentreOnParent()

        current = chapter_index_at(self._chapters, position_ms / 1000.0)
        if current >= 0:
            self.list.SetSelection(current)
        self.list.SetFocus()

    def _jump(self) -> None:
        index = self.list.GetSelection()
        if not 0 <= index < len(self._chapters):
            return
        start, _end, title = self._chapters[index]
        self._on_jump(int(start * 1000))
        LOG.info("Jumped to chapter %d: %s.", index + 1,
                 str(title or "").strip() or "(untitled)")
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Close()


def chapters_for(audio_path: Path) -> list[Chapter]:
    """The chapter markers in *audio_path*, oldest first. Never raises."""
    from podharvest import chapters as chapters_mod

    try:
        found = chapters_mod.read_chapters(Path(audio_path))
    except Exception as exc:  # noqa: BLE001 - a bad file is "no chapters"
        LOG.debug("Could not read chapters from %s: %s", audio_path, exc)
        return []
    return sorted(found, key=lambda chapter: chapter[0])
