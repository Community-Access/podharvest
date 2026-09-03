"""Reading a transcript without leaving podHarvest.

The words were always there — written to disk as Markdown and plain text — and
podHarvest's answer to "let me read that" was "open it in something else".
That is a poor answer for the person most likely to want it: somebody who has
just heard something and wants to find where it was said.

So: a reader. Read-only, keyboard-driven, and searchable, because a transcript
is an hour of speech and the useful operation on it is *find*, not *scroll*.

Two things it deliberately does not do. It does not edit — the transcript is a
record of what was said, and a text box that let you change it would invite
you to, with nothing to say the file no longer matches the audio. And it does
not reformat: what is on disk is what you see, so what you read here and what
you paste elsewhere are the same words.
"""

from __future__ import annotations

from pathlib import Path

import wx

from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name, size_for_text
from podharvest.util import LOG

#: How much text to load. A transcript of a very long episode is still small,
#: but a mis-selected file could be anything, and a reader that hangs on a
#: gigabyte is worse than one that says no.
MAX_BYTES = 8 * 1024 * 1024


class TranscriptDialog(wx.Dialog):
    """One transcript, read-only and searchable."""

    def __init__(self, parent: wx.Window, path: Path, *, title: str = "") -> None:
        self.path = Path(path)
        heading = title or self.path.stem
        super().__init__(
            parent,
            title=f"Transcript - {heading}",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        help_mod.install(self)
        self._matches: list[int] = []
        self._match_index = -1

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label=heading), 0, wx.ALL, 10)

        # Label before control, so a screen reader pairs the two.
        find_row = wx.BoxSizer(wx.HORIZONTAL)
        find_row.Add(wx.StaticText(self, label="&Find:"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.find_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.find_ctrl.SetToolTip(
            "Type what you are looking for and press Enter. Enter again goes "
            "to the next time it appears; the count beside it says how many "
            "there are."
        )
        set_accessible_name(self.find_ctrl, "Find in the transcript")
        self.find_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda _e: self._on_find_next())
        find_row.Add(self.find_ctrl, 1, wx.RIGHT, 6)

        next_btn = wx.Button(self, label="&Next")
        next_btn.SetToolTip("Goes to the next time your text appears.")
        next_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_find_next())
        find_row.Add(next_btn, 0, wx.RIGHT, 6)

        self.find_status = wx.StaticText(self, label="")
        set_accessible_name(self.find_status, "Search result")
        find_row.Add(self.find_status, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(find_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.text = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.text.SetToolTip(
            "The transcript, exactly as it was written to disk. Read-only: "
            "arrow through it, or select and copy. Find above jumps to a word."
        )
        set_accessible_name(self.text, "Transcript")
        size_for_text(self.text, lines=20)
        root.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        copy_btn = wx.Button(self, label="&Copy all")
        copy_btn.SetToolTip("Puts the whole transcript on the clipboard.")
        copy_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_copy())
        row.Add(copy_btn, 0, wx.RIGHT, 6)

        open_btn = wx.Button(self, label="&Open the file")
        open_btn.SetToolTip(
            "Opens the transcript file in whatever your system uses for text, "
            "so you can keep it open beside something else."
        )
        open_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_open_file())
        row.Add(open_btn, 0, wx.RIGHT, 12)

        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(680, 600))
        self.Fit()
        self.CentreOnParent()
        self._load()
        self.find_ctrl.SetFocus()

    # -- loading ---------------------------------------------------------

    def _load(self) -> None:
        """Read the file, or say plainly why it could not be read."""
        try:
            size = self.path.stat().st_size
        except OSError as exc:
            self.text.SetValue(f"Could not open this transcript: {exc}")
            return
        if size > MAX_BYTES:
            self.text.SetValue(
                f"This file is {size // (1024 * 1024)} MB, which is far larger "
                "than a transcript. Use Open the file to look at it in "
                "something built for large files."
            )
            return
        try:
            self.text.SetValue(self.path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            self.text.SetValue(f"Could not read this transcript: {exc}")

    # -- finding ---------------------------------------------------------

    def _on_find_next(self) -> None:
        """Jump to the next occurrence, wrapping, and say where you are.

        Said out loud because moving the caret in a read-only box is silent:
        without a count, a search that found nothing and a search that found
        forty look identical.
        """
        needle = self.find_ctrl.GetValue().strip().lower()
        if not needle:
            self.find_status.SetLabel("")
            return
        haystack = self.text.GetValue().lower()
        matches = []
        start = haystack.find(needle)
        while start != -1:
            matches.append(start)
            start = haystack.find(needle, start + 1)
        if not matches:
            self.find_status.SetLabel("Not found.")
            return
        if matches != self._matches:
            self._matches = matches
            self._match_index = -1
        self._match_index = (self._match_index + 1) % len(matches)
        position = matches[self._match_index]
        self.text.SetSelection(position, position + len(needle))
        self.text.ShowPosition(position)
        self.find_status.SetLabel(
            f"{self._match_index + 1} of {len(matches)}")

    # -- actions ---------------------------------------------------------

    def _on_copy(self) -> None:
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self.text.GetValue()))
            finally:
                wx.TheClipboard.Close()
            self.find_status.SetLabel("Copied.")

    def _on_open_file(self) -> None:
        try:
            wx.LaunchDefaultApplication(str(self.path))
        except Exception as exc:  # noqa: BLE001 - no handler for .md is common
            LOG.info("Could not open %s (%s).", self.path.name, exc)
            self.find_status.SetLabel("Nothing on this machine opens that file.")
