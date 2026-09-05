"""Finding a phrase anywhere in the library's transcripts.

The reader answers "where in *this* episode was that said?"; this window
answers the question that comes first: "which episode was it said in at
all?" Every transcript in the output folder is read and searched, and each
episode that matches gets one row -- show, episode, how many times, and the
first place it appears. Enter on a row opens that transcript in the reader
with the search already run, so the next Enter is already walking the
matches.

One row per episode rather than per occurrence, because a phrase that
appears eighty times in one episode is one answer, not eighty rows to arrow
through.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

import wx

from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name
from podharvest.util import LOG

#: The same ceiling the reader applies: a file this large is not a transcript.
MAX_BYTES = 8 * 1024 * 1024

#: How much text around the first match to show in the row.
SNIPPET_CHARS = 90

#: Stop after this many matching episodes. Nobody arrows through more.
MAX_RESULTS = 200


@dataclass
class EpisodeMatch:
    """One episode with the phrase in it, where it appears, and when.

    `start_ms` is None when the transcript carries no timings at all -- an
    older run with timestamps switched off, or a publisher's plain-text
    transcript. The row then simply does not offer to play, rather than
    offering and landing at the beginning.
    """

    episode: object  # a library.LibraryEpisode
    count: int
    snippet: str
    start_ms: int | None = None

    def when(self) -> str:
        """The position as a clock time, or "" when it is not known."""
        if self.start_ms is None:
            return ""
        total = max(0, self.start_ms) // 1000
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        return (f"{hours}:{minutes:02d}:{seconds:02d}" if hours
                else f"{minutes:02d}:{seconds:02d}")

    def describe(self) -> str:
        times = "once" if self.count == 1 else f"{self.count} times"
        stamp = self.when()
        when = f" at {stamp}" if stamp else ""
        return (f"{self.episode.show} - {self.episode.title} - {times}{when}: "
                f"...{self.snippet}...")


def _snippet(text: str, position: int, query_length: int) -> str:
    """A single collapsed line of context around the first match."""
    start = max(0, position - SNIPPET_CHARS // 2)
    end = min(len(text), position + query_length + SNIPPET_CHARS // 2)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _time_of(path: Path, needle: str) -> int | None:
    """Where in the audio *needle* is first said, or None if unknowable.

    Only called for transcripts that already matched, so a search across a
    large library does not open a timing file for every episode it rejects.

    The offset from the file itself cannot be reused: the file includes the
    timestamp markers, and the timeline's text has them stripped, so the two
    disagree by however many markers came before the match. The phrase is
    found again in the timeline's own text instead.
    """
    from podharvest import timing_core

    timeline = timing_core.load_timeline(path)
    if timeline.is_empty():
        return None
    position = timeline.text().lower().find(needle)
    return timeline.time_at_char(position) if position >= 0 else None


def search_transcripts(episodes, query: str) -> list[EpisodeMatch]:
    """Every episode whose transcript contains *query*, case-insensitively.

    Reads each transcript once; unreadable or over-sized files are skipped
    with a log line rather than failing the whole search -- one damaged file
    must not hide the library.
    """
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    found: list[EpisodeMatch] = []
    for episode in episodes:
        transcript = getattr(episode, "transcript", None)
        if transcript is None:
            continue
        path = Path(transcript)
        try:
            if path.stat().st_size > MAX_BYTES:
                LOG.debug("Skipping %s: larger than a transcript should be.", path)
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            LOG.debug("Skipping %s: %s", path, exc)
            continue
        lowered = text.lower()
        count = lowered.count(needle)
        if not count:
            continue
        first = lowered.find(needle)
        found.append(EpisodeMatch(
            episode=episode, count=count,
            snippet=_snippet(text, first, len(needle)),
            start_ms=_time_of(path, needle)))
        if len(found) >= MAX_RESULTS:
            LOG.info("Stopping at %d matching episodes; narrow the search "
                     "to see the rest.", MAX_RESULTS)
            break
    return found


class TranscriptSearchDialog(wx.Dialog):
    """Search every transcript; Enter opens the match in the reader."""

    def __init__(self, parent, output_dir: Path, *, on_cue=None) -> None:
        super().__init__(parent, title="Search all transcripts",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self.output_dir = Path(output_dir)
        self._matches: list[EpisodeMatch] = []
        self._alive = True
        # Given by the main window so a match can cue the transport there.
        # None when nobody is listening, which is how the tests build it.
        self._on_cue = on_cue

        root = wx.BoxSizer(wx.VERTICAL)
        find_row = wx.BoxSizer(wx.HORIZONTAL)
        find_row.Add(wx.StaticText(self, label="&Search for:"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.query_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query_ctrl.SetToolTip(
            "A word or phrase to look for in every transcript in the "
            "library. Press Enter to search; capitalisation does not "
            "matter.")
        set_accessible_name(self.query_ctrl, "Search every transcript for")
        self.query_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda _e: self.on_search())
        find_row.Add(self.query_ctrl, 1, wx.RIGHT, 6)
        search_btn = wx.Button(self, label="Searc&h")
        search_btn.SetToolTip("Searches every transcript in the library.")
        search_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_search())
        find_row.Add(search_btn, 0)
        root.Add(find_row, 0, wx.EXPAND | wx.ALL, 10)

        self.status = wx.StaticText(
            self, label="Type a word or phrase and press Enter.")
        set_accessible_name(self.status, "Search status")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        root.Add(wx.StaticText(self, label="&Episodes that mention it:"), 0,
                 wx.LEFT | wx.RIGHT, 10)
        self.list = wx.ListBox(self, choices=[])
        self.list.SetToolTip(
            "One row per episode that contains your phrase: the show, the "
            "episode, how many times it appears, and the first place it "
            "does. Enter opens that transcript in the reader with the "
            "search already run.")
        set_accessible_name(self.list, "Episodes that mention it")
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda _e: self.on_open())
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.open_btn = wx.Button(self, wx.ID_OK, label="&Open in reader")
        self.open_btn.SetToolTip(
            "Opens the highlighted episode's transcript with this search "
            "already run, so Enter walks the matches.")
        self.open_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_open())
        self.open_btn.Enable(False)
        row.Add(self.open_btn, 0, wx.RIGHT, 12)
        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(760, 520))
        self.Fit()
        self.CentreOnParent()
        self.query_ctrl.SetFocus()
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # -- searching --------------------------------------------------------

    def on_search(self) -> None:
        query = self.query_ctrl.GetValue().strip()
        if not query:
            self.status.SetLabel("Type a word or phrase first.")
            self.query_ctrl.SetFocus()
            return
        self.status.SetLabel(f"Searching for '{query}'...")

        def worker() -> None:
            from podharvest import library

            episodes = library.all_episodes(self.output_dir)
            matches = search_transcripts(episodes, query)
            with_transcripts = sum(1 for e in episodes if e.transcript)
            wx.CallAfter(self._show_matches, matches, with_transcripts)

        threading.Thread(target=worker, daemon=True).start()

    def _show_matches(self, matches: list[EpisodeMatch],
                      searched: int) -> None:
        if not self._alive:
            return
        self._matches = matches
        self.list.Set([m.describe() for m in matches])
        self.open_btn.Enable(bool(matches))
        if not searched:
            self.status.SetLabel(
                "The library has no transcripts yet. Run a harvest with "
                "transcription on, then search.")
        elif not matches:
            self.status.SetLabel(
                f"Not found in any of the {searched} transcript(s).")
        else:
            self.status.SetLabel(
                f"Found in {len(matches)} of {searched} transcript(s). "
                "Enter opens the reader at the match.")
            self.list.SetSelection(0)
            self.list.SetFocus()

    # -- opening ----------------------------------------------------------

    def selected(self) -> EpisodeMatch | None:
        index = self.list.GetSelection()
        return self._matches[index] if 0 <= index < len(self._matches) else None

    def on_open(self) -> None:
        match = self.selected()
        if match is None:
            return
        from podharvest.reader import TranscriptDialog

        # Cue the audio before the reader opens, so the episode is already
        # sitting at the phrase when the reader is closed again. Cued and
        # not started: audio beginning unasked, over a screen reader still
        # reading the row you chose, is startling.
        if match.start_ms is not None and self._on_cue is not None:
            self._on_cue(match.episode, match.start_ms)
        dlg = TranscriptDialog(
            self, match.episode.transcript, title=match.episode.title,
            find=self.query_ctrl.GetValue().strip())
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _on_close(self, event) -> None:
        self._alive = False
        event.Skip()
