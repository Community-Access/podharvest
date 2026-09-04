"""Searching every transcript in the library at once.

The rules under test: matching ignores capitalisation, one episode is one
row no matter how many times the phrase appears in it, a damaged file skips
rather than fails, and the reader opens with the search already run.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("wx")  # the module under test builds wx controls
from podharvest.transcript_search import (
    MAX_RESULTS,
    search_transcripts,
)


@dataclass
class _Episode:
    title: str
    show: str
    transcript: Path | None


def _library(tmp_path, **texts):
    episodes = []
    for name, text in texts.items():
        path = tmp_path / f"{name}.txt"
        path.write_text(text, encoding="utf-8")
        episodes.append(_Episode(title=name, show="A Show", transcript=path))
    return episodes


class TestMatching:
    def test_case_does_not_matter(self, tmp_path):
        episodes = _library(tmp_path, ep1="They discussed Accessibility today.")
        assert len(search_transcripts(episodes, "accessibility")) == 1

    def test_one_episode_is_one_row_however_often_it_appears(self, tmp_path):
        episodes = _library(tmp_path, ep1="cats and cats and cats")
        matches = search_transcripts(episodes, "cats")
        assert len(matches) == 1
        assert matches[0].count == 3
        assert "3 times" in matches[0].describe()

    def test_a_single_match_reads_as_once(self, tmp_path):
        episodes = _library(tmp_path, ep1="one lonely match")
        assert "once" in search_transcripts(episodes, "lonely")[0].describe()

    def test_the_snippet_is_one_collapsed_line(self, tmp_path):
        episodes = _library(
            tmp_path, ep1="before\n\n   the   needle\n\nafter")
        snippet = search_transcripts(episodes, "needle")[0].snippet
        assert "\n" not in snippet
        assert "the needle" in snippet

    def test_an_episode_without_a_transcript_is_skipped(self, tmp_path):
        episodes = [_Episode(title="none", show="S", transcript=None)]
        assert search_transcripts(episodes, "anything") == []

    def test_a_missing_file_skips_not_fails(self, tmp_path):
        episodes = [_Episode(title="gone", show="S",
                             transcript=tmp_path / "gone.txt")]
        assert search_transcripts(episodes, "anything") == []

    def test_a_blank_query_finds_nothing(self, tmp_path):
        episodes = _library(tmp_path, ep1="words")
        assert search_transcripts(episodes, "   ") == []

    def test_results_are_capped(self, tmp_path):
        episodes = _library(tmp_path, **{
            f"ep{n}": "the phrase" for n in range(MAX_RESULTS + 5)})
        assert len(search_transcripts(episodes, "phrase")) == MAX_RESULTS


class TestTheWindow:
    def test_it_is_reachable_from_the_menu(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "Search all transcrip" in source

    def test_searching_happens_off_the_ui_thread(self):
        pytest.importorskip("wx")
        from podharvest.transcript_search import TranscriptSearchDialog

        source = inspect.getsource(TranscriptSearchDialog.on_search)
        assert "threading.Thread" in source

    def test_opening_hands_the_query_to_the_reader(self):
        """The point of the handoff: the next Enter walks the matches."""
        pytest.importorskip("wx")
        from podharvest.transcript_search import TranscriptSearchDialog

        source = inspect.getsource(TranscriptSearchDialog.on_open)
        assert "find=" in source

    def test_the_reader_accepts_and_runs_a_search(self):
        pytest.importorskip("wx")
        from podharvest.reader import TranscriptDialog

        signature = inspect.signature(TranscriptDialog.__init__)
        assert "find" in signature.parameters
        source = inspect.getsource(TranscriptDialog.__init__)
        assert "_on_find_next" in source

    def test_the_window_says_what_it_is_for(self):
        from podharvest import help as help_mod

        purpose = help_mod.purpose_for_title("Search all transcripts")
        assert purpose != help_mod.GENERIC_PURPOSE
        assert "every transcript" in purpose

    def test_the_module_ships(self):
        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.transcript_search" in spec
