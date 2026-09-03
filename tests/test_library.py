"""The library: what is already on disk, read back so you can go to it.

The Episodes list used to empty when podHarvest closed, which made it a
progress view and nothing else. These cover the half that turns it into a
library — and, deliberately, the fallbacks, because the interesting cases are
a folder that was interrupted and a folder somebody assembled by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from podharvest import library


def _make_show(root: Path, *, title="The Show", folder="the-show",
               episodes=None, with_feed_json=True) -> Path:
    show = root / folder
    (show / "transcripts").mkdir(parents=True, exist_ok=True)
    (show / "audio").mkdir(parents=True, exist_ok=True)
    entries = []
    for spec in episodes or []:
        stem = spec["stem"]
        if spec.get("audio", True):
            (show / "audio" / f"{stem}.mp3").write_bytes(b"x" * 100)
        if spec.get("transcript"):
            (show / "transcripts" / f"{stem}.md").write_text("y" * 500, encoding="utf-8")
        if spec.get("summary"):
            (show / "transcripts" / f"{stem}.summary.md").write_text("s", encoding="utf-8")
        entries.append({
            "title": spec["title"],
            "published": spec.get("published", "2026-09-01T10:00:00+00:00"),
            "duration_seconds": spec.get("duration"),
            "enclosures": ([{"local_path": str(show / "audio" / f"{stem}.mp3")}]
                           if spec.get("audio", True) else []),
        })
    if with_feed_json:
        (show / "feed.json").write_text(
            json.dumps({"title": title, "episodes": entries}), encoding="utf-8")
    return show


class TestReadingAHarvest:
    def test_it_reads_the_real_titles_from_feed_json(self, tmp_path):
        """Not guessed from slugs: the naming template is configurable."""
        _make_show(tmp_path, episodes=[
            {"stem": "0001-first", "title": "An Episode With: Punctuation!"},
        ])
        episodes = library.all_episodes(tmp_path)
        assert [e.title for e in episodes] == ["An Episode With: Punctuation!"]
        assert episodes[0].show == "The Show"

    def test_it_finds_what_came_with_each_episode(self, tmp_path):
        _make_show(tmp_path, episodes=[
            {"stem": "a", "title": "Everything", "transcript": True, "summary": True},
            {"stem": "b", "title": "Audio only"},
        ])
        by_title = {e.title: e for e in library.all_episodes(tmp_path)}
        assert by_title["Everything"].what_it_has() == "audio, transcript and summary"
        assert by_title["Audio only"].what_it_has() == "audio"

    def test_an_episode_that_was_never_downloaded_says_so(self, tmp_path):
        _make_show(tmp_path, episodes=[
            {"stem": "c", "title": "Skipped", "audio": False},
        ])
        episode = library.all_episodes(tmp_path)[0]
        assert episode.has_audio is False
        assert episode.what_it_has() == "nothing downloaded"

    def test_a_deleted_file_is_not_offered(self, tmp_path):
        """A Play button that cannot work is worse than an honest gap."""
        show = _make_show(tmp_path, episodes=[{"stem": "gone", "title": "Deleted"}])
        (show / "audio" / "gone.mp3").unlink()
        assert library.all_episodes(tmp_path)[0].has_audio is False

    def test_newest_first(self, tmp_path):
        _make_show(tmp_path, episodes=[
            {"stem": "old", "title": "Older", "published": "2026-01-01T00:00:00+00:00"},
            {"stem": "new", "title": "Newer", "published": "2026-09-01T00:00:00+00:00"},
        ])
        assert [e.title for e in library.all_episodes(tmp_path)] == ["Newer", "Older"]

    def test_undated_episodes_sort_last_rather_than_pretending_to_be_old(self, tmp_path):
        _make_show(tmp_path, episodes=[
            {"stem": "no-date", "title": "Undated", "published": None},
            {"stem": "dated", "title": "Dated", "published": "2020-01-01T00:00:00+00:00"},
        ])
        assert [e.title for e in library.all_episodes(tmp_path)] == ["Dated", "Undated"]

    def test_several_shows_are_all_read(self, tmp_path):
        _make_show(tmp_path, title="One", folder="one",
                   episodes=[{"stem": "a", "title": "A"}])
        _make_show(tmp_path, title="Two", folder="two",
                   episodes=[{"stem": "b", "title": "B"}])
        shows = {s.title for s in library.scan(tmp_path)}
        assert shows == {"One", "Two"}


class TestFallbacks:
    def test_a_folder_with_no_feed_json_still_lists_its_audio(self, tmp_path):
        """An interrupted first run should not read as an empty library."""
        _make_show(tmp_path, with_feed_json=False,
                   episodes=[{"stem": "0001-something", "title": "ignored"}])
        episodes = library.all_episodes(tmp_path)
        assert len(episodes) == 1
        assert episodes[0].title == "0001-something"
        assert episodes[0].has_audio

    def test_a_broken_feed_json_falls_back_rather_than_failing(self, tmp_path):
        show = _make_show(tmp_path, episodes=[{"stem": "x", "title": "Real Title"}])
        (show / "feed.json").write_text("{not json", encoding="utf-8")
        episodes = library.all_episodes(tmp_path)
        assert len(episodes) == 1
        assert episodes[0].has_audio

    def test_an_empty_output_folder_is_empty_not_an_error(self, tmp_path):
        assert library.all_episodes(tmp_path) == []

    def test_a_missing_output_folder_is_empty_not_an_error(self, tmp_path):
        assert library.all_episodes(tmp_path / "never-made") == []

    def test_a_folder_with_nothing_in_it_is_not_a_show(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert library.scan(tmp_path) == []

    def test_a_stub_transcript_does_not_count(self, tmp_path):
        """An interrupted write should not read as a transcript you can open."""
        show = _make_show(tmp_path, episodes=[
            {"stem": "s", "title": "Stub", "transcript": True}])
        (show / "transcripts" / "s.md").write_text("", encoding="utf-8")
        assert library.all_episodes(tmp_path)[0].has_transcript is False


class TestTheReader:
    @pytest.fixture
    def app(self, wx_app):
        """The session-wide wx.App -- see tests/conftest.py."""
        return wx_app

    @pytest.fixture
    def transcript(self, tmp_path):
        path = tmp_path / "episode.md"
        path.write_text(
            "Welcome to the show.\nToday we talk about badgers.\n"
            "Badgers are nocturnal.\nGoodbye.\n", encoding="utf-8")
        return path

    def test_it_shows_the_words_as_written(self, app, transcript):
        wx = pytest.importorskip("wx")
        from podharvest.reader import TranscriptDialog

        frame = wx.Frame(None)
        dlg = TranscriptDialog(frame, transcript, title="An Episode")
        try:
            assert "badgers" in dlg.text.GetValue()
            assert dlg.text.IsEditable() is False, "a transcript is a record"
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_find_reports_which_occurrence_you_are_on(self, app, transcript):
        """Moving the caret in a read-only box is silent without this."""
        wx = pytest.importorskip("wx")
        from podharvest.reader import TranscriptDialog

        frame = wx.Frame(None)
        dlg = TranscriptDialog(frame, transcript, title="An Episode")
        try:
            dlg.find_ctrl.SetValue("badgers")
            dlg._on_find_next()
            assert dlg.find_status.GetLabel() == "1 of 2"
            dlg._on_find_next()
            assert dlg.find_status.GetLabel() == "2 of 2"
            dlg._on_find_next()
            assert dlg.find_status.GetLabel() == "1 of 2", "it must wrap"
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_find_says_when_there_is_nothing(self, app, transcript):
        wx = pytest.importorskip("wx")
        from podharvest.reader import TranscriptDialog

        frame = wx.Frame(None)
        dlg = TranscriptDialog(frame, transcript)
        try:
            dlg.find_ctrl.SetValue("aardvark")
            dlg._on_find_next()
            assert dlg.find_status.GetLabel() == "Not found."
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_find_is_case_insensitive(self, app, transcript):
        wx = pytest.importorskip("wx")
        from podharvest.reader import TranscriptDialog

        frame = wx.Frame(None)
        dlg = TranscriptDialog(frame, transcript)
        try:
            dlg.find_ctrl.SetValue("BADGERS")
            dlg._on_find_next()
            assert "of" in dlg.find_status.GetLabel()
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_a_missing_file_says_why_rather_than_showing_nothing(self, app, tmp_path):
        wx = pytest.importorskip("wx")
        from podharvest.reader import TranscriptDialog

        frame = wx.Frame(None)
        dlg = TranscriptDialog(frame, tmp_path / "gone.md")
        try:
            assert "Could not open" in dlg.text.GetValue()
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_an_absurdly_large_file_is_refused_with_a_reason(self, app, tmp_path):
        wx = pytest.importorskip("wx")
        from podharvest import reader
        from podharvest.reader import TranscriptDialog

        huge = tmp_path / "huge.md"
        huge.write_bytes(b"x" * (reader.MAX_BYTES + 1))
        frame = wx.Frame(None)
        dlg = TranscriptDialog(frame, huge)
        try:
            assert "larger than a transcript" in dlg.text.GetValue()
        finally:
            dlg.Destroy()
            frame.Destroy()


class TestWiring:
    def test_the_library_is_the_list_when_nothing_is_running(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.MainFrame)
        assert "refresh_library" in source
        # Built at startup and rebuilt when a run ends, so the list is never
        # stale and never empty just because the app was restarted.
        assert source.count("self.refresh_library()") >= 2

    def test_the_columns_change_with_what_the_list_holds(self):
        """A reader hears the heading with every cell; it must be true."""
        from podharvest.gui import _LIBRARY_COLUMNS, _RUN_COLUMNS

        assert len(_LIBRARY_COLUMNS) == len(_RUN_COLUMNS)
        assert [h for h, _w in _LIBRARY_COLUMNS] != [h for h, _w in _RUN_COLUMNS]

    def test_the_transcript_reader_is_reachable(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui)
        assert "TranscriptDialog" in source
        assert "Read the &transcript" in source
