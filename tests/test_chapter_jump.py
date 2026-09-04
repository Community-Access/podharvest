"""Jumping to a chapter during playback.

The list has one job: get a listener from "the interview starts at chapter
three" to hearing the interview, without holding down Forward. The rules
under test are the ones that make that work by ear: rows read number first,
the list opens on the chapter playing now, and Enter both seeks and plays.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("wx")  # the module under test builds wx controls
from podharvest.chapter_jump import chapter_index_at, row_label

CHAPTERS = [
    (0.0, 60.0, "Welcome"),
    (60.0, 600.0, "The news"),
    (600.0, 3600.0, "The interview"),
]


class TestRowLabels:
    def test_number_then_title_then_time(self):
        assert row_label(2, CHAPTERS[2]) == "3. The interview - 10:00"

    def test_an_untitled_chapter_still_has_a_name(self):
        assert "(untitled chapter)" in row_label(0, (0.0, 5.0, "  "))

    def test_numbers_are_one_based(self):
        """"Chapter three" is how people refer to them; nobody says chapter
        zero."""
        assert row_label(0, CHAPTERS[0]).startswith("1.")


class TestFindingTheCurrentChapter:
    def test_the_playhead_lands_in_the_right_chapter(self):
        assert chapter_index_at(CHAPTERS, 0.0) == 0
        assert chapter_index_at(CHAPTERS, 59.9) == 0
        assert chapter_index_at(CHAPTERS, 60.0) == 1
        assert chapter_index_at(CHAPTERS, 700.0) == 2

    def test_past_the_last_chapter_is_still_the_last_chapter(self):
        assert chapter_index_at(CHAPTERS, 99999.0) == 2

    def test_no_chapters_is_minus_one_not_a_crash(self):
        assert chapter_index_at([], 10.0) == -1


class TestTheWindow:
    @pytest.fixture
    def app(self, wx_app):
        return wx_app

    def test_enter_seeks_and_plays(self, app):
        """The jump callback receives milliseconds and the dialog closes."""
        wx = pytest.importorskip("wx")
        from podharvest.chapter_jump import ChapterJumpDialog

        frame = wx.Frame(None)
        jumped: list[int] = []
        try:
            dlg = ChapterJumpDialog(
                frame, chapters=CHAPTERS, position_ms=90_000,
                episode="ep", on_jump=jumped.append)
            try:
                assert dlg.list.GetSelection() == 1, "opens on the playing chapter"
                dlg.list.SetSelection(2)
                dlg._jump()
                assert jumped == [600_000]
            finally:
                dlg.Destroy()
        finally:
            frame.Destroy()

    def test_the_handler_plays_after_seeking(self):
        """Jumping to a chapter and hearing silence is a broken promise."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._on_jump_to_chapter)
        assert "seek_to" in source
        assert "play()" in source

    def test_it_is_reachable_from_the_menu(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "Jump to chapter" in source

    def test_the_window_says_what_it_is_for(self):
        from podharvest import help as help_mod

        purpose = help_mod.purpose_for_title("Chapters - some-episode.mp3")
        assert purpose != help_mod.GENERIC_PURPOSE
        assert "chapter" in purpose.lower()

    def test_the_module_ships(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.chapter_jump" in spec

    def test_chapters_for_never_raises_on_a_bad_file(self, tmp_path):
        pytest.importorskip("wx")
        from podharvest.chapter_jump import chapters_for

        assert chapters_for(tmp_path / "nothing.mp3") == []


class TestSpokenTimes:
    def test_short_times_stay_short(self):
        from podharvest.chapter_jump import spoken_time

        assert spoken_time(0) == "0:00"
        assert spoken_time(90) == "1:30"
        assert spoken_time(600) == "10:00"

    def test_hours_appear_only_past_an_hour(self):
        from podharvest.chapter_jump import spoken_time

        assert spoken_time(3725) == "1:02:05"

    def test_no_milliseconds_ever(self):
        """Milliseconds are for the editor; a spoken row wants the shortest
        true form."""
        from podharvest.chapter_jump import spoken_time

        assert "." not in spoken_time(90.75)
