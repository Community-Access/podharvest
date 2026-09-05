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

import re
from pathlib import Path

import wx

from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name, size_for_text
from podharvest.util import LOG

#: How much text to load. A transcript of a very long episode is still small,
#: but a mis-selected file could be anything, and a reader that hangs on a
#: gigabyte is worse than one that says no.
MAX_BYTES = 8 * 1024 * 1024

#: How often the caret checks where playback has got to, when following is
#: switched on. Twice a second: often enough that the caret is never a
#: sentence behind, rare enough that a screen reader is not interrupted
#: mid-word by a position change.
FOLLOW_TICK_MS = 500


#: A transcript line that starts with a timing marker, in either style and
#: with or without markdown bold. Matches what `timing_core` parses, because
#: the two have to agree on which lines are segments.
_MARKED_LINE = re.compile(
    r"^\s*(?:\*\*)?[\[(]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?[\])]")


def _spoken_time(ms: int) -> str:
    """A position read aloud: "1 minute 5 seconds", not "00:01:05.000"."""
    total = max(0, ms) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    parts.append(f"{seconds} second" + ("s" if seconds != 1 else ""))
    return " ".join(parts)


class TranscriptDialog(wx.Dialog):
    """One transcript, read-only and searchable."""

    def __init__(self, parent: wx.Window, path: Path, *, title: str = "",
                 find: str = "", on_play_at=None, audio_path: Path | None = None,
                 follow_along: bool = False, playhead=None) -> None:
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
        # Given by the main window so the reader can drive playback without
        # knowing anything about the transport. All None when there is no
        # player to talk to, and every feature that needs one says so.
        self._on_play_at = on_play_at
        self._audio_path = Path(audio_path) if audio_path else None
        self._playhead = playhead
        self._episode_title = title
        self._timeline = None
        self._follow_timer = None
        self._last_follow_offset = -1

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
        size_for_text(self.text, lines=20, chars=72)
        root.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_here_btn = wx.Button(self, label="Play from &here")
        self.play_here_btn.SetToolTip(
            "Plays the episode from the point in the audio where the caret "
            "is. Control+Enter in the transcript does the same. Off when "
            "this transcript carries no timings."
        )
        self.play_here_btn.Bind(wx.EVT_BUTTON, lambda _e: self._play_from_caret())
        row.Add(self.play_here_btn, 0, wx.RIGHT, 6)

        self.clip_btn = wx.Button(self, label="Save as a c&lip...")
        self.clip_btn.SetToolTip(
            "Saves the audio for the text you have selected as its own file, "
            "with a short fade at each end and a name made from the words "
            "that were said. Select some transcript first. Needs FFmpeg."
        )
        self.clip_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_save_clip())
        row.Add(self.clip_btn, 0, wx.RIGHT, 12)

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
        # Read once, when the transcript is: a reader is opened and then
        # arrowed through, so the cost belongs at the front.
        from podharvest import timing_core

        self._timeline = timing_core.load_timeline(self.path)
        self._build_line_map()
        has_times = not self._timeline.is_empty()
        self.play_here_btn.Enable(has_times and on_play_at is not None)
        self.clip_btn.Enable(has_times and self._audio_path is not None)
        self.text.Bind(wx.EVT_KEY_DOWN, self._on_text_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # Following is off unless the setting says otherwise, so the timer
        # is not even created when it is off: there is then nothing running
        # that could be forgotten about.
        if follow_along and has_times and playhead is not None:
            self._follow_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda _e: self._follow_playhead(),
                      self._follow_timer)
            self._follow_timer.Start(FOLLOW_TICK_MS)
        self.find_ctrl.SetFocus()
        if find:
            # Arriving from Search all transcripts: run the search that got
            # here, so the first Enter is already walking the matches.
            self.find_ctrl.SetValue(find)
            self._on_find_next()

    # -- the caret's place in the audio ------------------------------------

    def _on_text_key(self, event) -> None:
        """Control+Enter plays from the caret; everything else is the box's."""
        if (event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and event.ControlDown()):
            self._play_from_caret()
            return
        event.Skip()

    def _build_line_map(self) -> None:
        """Line numbers in the box that carry a timing, one per segment.

        The box shows the file: headings, blank lines, and the
        `[HH:MM:SS.mmm]` markers themselves. The timeline holds only the
        spoken segments with the markers stripped. So box line 5 is not
        timeline segment 5, and assuming it was put the caret on the wrong
        sentence in both directions -- verified, before this existed.

        Both features work in segment indices now, and this is the only
        place the two coordinate systems meet.
        """
        self._segment_lines = []
        if self._timeline is None or self._timeline.is_empty():
            return
        for number, line in enumerate(self.text.GetValue().splitlines()):
            if _MARKED_LINE.match(line):
                self._segment_lines.append(number)
        # A transcript whose markers were switched off has none of these; the
        # timeline then came from a sidecar or captions, and there is no
        # honest mapping to the box. Leaving the list empty makes both
        # features say so rather than guess.
        if len(self._segment_lines) != len(self._timeline.segments):
            self._segment_lines = []

    def _segment_at_caret(self) -> int | None:
        """Which timeline segment the caret is in, or None."""
        if not self._segment_lines:
            return None
        caret_line = len(
            self.text.GetValue()[:self.text.GetInsertionPoint()].splitlines()) - 1
        found = None
        for index, line_no in enumerate(self._segment_lines):
            if line_no <= caret_line:
                found = index
            else:
                break
        return found

    def _box_offset_of_segment(self, index: int) -> int | None:
        """Where segment *index* starts in the box, as a character offset."""
        if not 0 <= index < len(self._segment_lines):
            return None
        lines = self.text.GetValue().splitlines()
        wanted = self._segment_lines[index]
        return sum(len(line) + 1 for line in lines[:wanted])

    def _play_from_caret(self) -> None:
        """Start the audio at whatever the caret is sitting on.

        Says what it did: moving a playhead is invisible, and an
        announcement is the only way anybody knows it worked.
        """
        if self._on_play_at is None or self._timeline is None:
            return
        if self._timeline.is_empty():
            self.find_status.SetLabel(
                "This transcript has no timings, so there is nothing to play "
                "from. Transcripts made with timestamps on do have them.")
            return
        index = self._segment_at_caret()
        if index is None:
            self.find_status.SetLabel(
                "The timings for this transcript cannot be matched to the "
                "text on screen, so there is nothing to play from here.")
            return
        when = self._timeline.segments[index].start_ms
        self._on_play_at(when)
        self.find_status.SetLabel(f"Playing from {_spoken_time(when)}.")

    def _follow_playhead(self) -> None:
        """Move the caret to the sentence being spoken, and no further.

        Only the caret moves, and only when the sentence changes. Selecting
        the text would make a screen reader re-read it on every tick, and
        moving on every tick would fight anybody who has scrolled back to
        read something again.
        """
        if self._playhead is None or self._timeline is None:
            return
        try:
            where = self._playhead()
        except Exception:  # noqa: BLE001 - a closed player is not an error
            return
        index = None
        for number, segment in enumerate(self._timeline.segments):
            if segment.start_ms <= where < segment.end_ms:
                index = number
                break
        if index is None or index == self._last_follow_offset:
            return
        offset = self._box_offset_of_segment(index)
        if offset is None:
            return
        self._last_follow_offset = index
        self.text.SetInsertionPoint(offset)
        self.text.ShowPosition(offset)

    def _on_save_clip(self) -> None:
        """Turn the selected text into an audio file of exactly that."""
        import re

        from podharvest import clips, media_health

        if self._timeline is None or self._timeline.is_empty():
            self.find_status.SetLabel(
                "This transcript has no timings, so a clip cannot be cut "
                "from it.")
            return
        if self._audio_path is None:
            self.find_status.SetLabel("There is no audio file for this episode.")
            return
        if not media_health.check().healthy:
            self.find_status.SetLabel(
                "Saving a clip needs FFmpeg, which is not installed. Help "
                "then Media tools says how to get it.")
            return
        first, last = self.text.GetSelection()
        if first == last:
            self.find_status.SetLabel(
                "Select the part of the transcript you want as a clip first.")
            return
        said = re.sub(r"\s+", " ", self.text.GetValue()[first:last]).strip()
        position = re.sub(r"\s+", " ", self._timeline.text()).find(said)
        if position < 0 or not said:
            self.find_status.SetLabel(
                "That selection could not be matched to the timings. Try "
                "selecting whole sentences.")
            return
        start = self._timeline.time_at_char(position)
        end = self._timeline.time_at_char(position + len(said))
        if start is None or end is None or end <= start:
            self.find_status.SetLabel("There is no timing for that selection.")
            return
        suggested = clips.clip_filename(
            self._episode_title or self.path.stem, said)
        with wx.FileDialog(
            self, "Save this passage as a clip", defaultFile=suggested,
            wildcard="Audio (*.mp3)|*.mp3|All files|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            destination = Path(dlg.GetPath())
        try:
            clips.export_clip(self._audio_path, destination, start, end)
        except (RuntimeError, ValueError, OSError) as exc:
            self.find_status.SetLabel(f"That clip could not be written: {exc}")
            return
        self.find_status.SetLabel(
            f"Saved {destination.name}, {(end - start) / 1000:.1f} seconds.")

    def _on_close(self, event) -> None:
        if self._follow_timer is not None:
            self._follow_timer.Stop()
            self._follow_timer = None
        event.Skip()

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
