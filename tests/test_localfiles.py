"""Audio you already have, treated like an episode.

The interesting risk in this feature is not "does it transcribe" -- that is the
harvest pipeline, already covered -- but everything around it: which files are
picked up, where the output lands, whether a second run does the work again,
and whether the window still describes what it is about to do once the source
changes. So that is what these cover.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from podharvest import localfiles


def _audio(folder: Path, name: str, size: int = 4096) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


class TestFindingFiles:
    def test_it_takes_the_audio_and_leaves_the_rest(self, tmp_path):
        _audio(tmp_path, "talk.mp3")
        _audio(tmp_path, "notes.txt")
        _audio(tmp_path, "cover.jpg")
        found = localfiles.collect([tmp_path])
        assert [p.name for p in found] == ["talk.mp3"]

    def test_a_folder_brings_its_subfolders(self, tmp_path):
        _audio(tmp_path, "one.mp3")
        _audio(tmp_path / "part two", "two.m4b")
        found = localfiles.collect([tmp_path])
        assert {p.name for p in found} == {"one.mp3", "two.m4b"}

    def test_subfolders_can_be_left_out(self, tmp_path):
        _audio(tmp_path, "one.mp3")
        _audio(tmp_path / "deeper", "two.mp3")
        found = localfiles.collect([tmp_path], recursive=False)
        assert [p.name for p in found] == ["one.mp3"]

    def test_a_file_added_twice_is_processed_once(self, tmp_path):
        """Adding a folder and a file inside it is an easy thing to do."""
        one = _audio(tmp_path, "one.mp3")
        found = localfiles.collect([tmp_path, one])
        assert len(found) == 1

    def test_the_order_is_stable(self, tmp_path):
        for name in ("c.mp3", "a.mp3", "b.mp3"):
            _audio(tmp_path, name)
        first = [p.name for p in localfiles.collect([tmp_path])]
        assert first == sorted(first)
        assert first == [p.name for p in localfiles.collect([tmp_path])]

    def test_a_path_that_is_not_there_is_skipped_not_fatal(self, tmp_path):
        _audio(tmp_path, "real.mp3")
        found = localfiles.collect([tmp_path / "real.mp3", tmp_path / "ghost.mp3"])
        assert [p.name for p in found] == ["real.mp3"]

    def test_a_single_file_can_be_added_directly(self, tmp_path):
        one = _audio(tmp_path, "one.mp3")
        assert localfiles.collect([one]) == [one]

    def test_it_stops_rather_than_walking_a_whole_drive(self, tmp_path, monkeypatch):
        monkeypatch.setattr(localfiles, "MAX_SCAN", 3)
        for i in range(10):
            _audio(tmp_path, f"{i:02d}.mp3")
        assert len(localfiles.collect([tmp_path])) == 3

    def test_the_wildcard_matches_the_suffix_list(self):
        """Otherwise the file dialog would hide types podHarvest handles."""
        for suffix in localfiles.AUDIO_SUFFIXES:
            assert f"*{suffix}" in localfiles.WILDCARD


class TestWhereTheOutputGoes:
    def test_beside_the_audio_by_default(self, tmp_path):
        path = _audio(tmp_path / "lectures", "week one.mp3")
        folder, slug = localfiles.transcript_location(path)
        assert folder == path.parent
        assert slug == "week one", "the file's own name, so the two stay together"

    def test_into_the_library_folder_when_asked(self, tmp_path):
        path = _audio(tmp_path, "Week One: Intro.mp3")
        folder, slug = localfiles.transcript_location(
            path, beside=False, output_dir=tmp_path / "library")
        assert folder == tmp_path / "library" / "Local files" / "transcripts"
        assert slug == "week-one-intro", "a shared folder needs a safe name"

    def test_with_nowhere_else_to_put_it_it_goes_beside(self, tmp_path):
        """Never invent a folder: no output dir means beside the audio."""
        path = _audio(tmp_path, "a.mp3")
        folder, _slug = localfiles.transcript_location(
            path, beside=False, output_dir=None)
        assert folder == path.parent


class TestDescribingAFile:
    def test_a_bare_file_says_audio_only(self, tmp_path):
        path = _audio(tmp_path, "plain.mp3")
        item = localfiles.describe(path)
        assert item.what_it_has() == "audio only"
        assert item.display_title == "plain", "the filename, with no tag to use"

    def test_an_existing_transcript_is_noticed(self, tmp_path):
        """The whole point of noticing: a second run must not redo the work."""
        path = _audio(tmp_path, "talk.mp3")
        (tmp_path / "talk.md").write_text("x" * 500, encoding="utf-8")
        item = localfiles.describe(path)
        assert item.has_transcript
        assert "transcript" in item.what_it_has()

    def test_a_stub_transcript_does_not_count(self, tmp_path):
        path = _audio(tmp_path, "talk.mp3")
        (tmp_path / "talk.md").write_text("", encoding="utf-8")
        assert localfiles.describe(path).has_transcript is False

    def test_a_summary_is_noticed_too(self, tmp_path):
        path = _audio(tmp_path, "talk.mp3")
        (tmp_path / "talk.md").write_text("x" * 500, encoding="utf-8")
        (tmp_path / "talk.summary.md").write_text("s", encoding="utf-8")
        assert localfiles.describe(path).what_it_has() == "transcript and summary"

    def test_a_transcript_in_the_library_folder_is_found(self, tmp_path):
        path = _audio(tmp_path / "audio", "talk.mp3")
        out = tmp_path / "library" / "Local files" / "transcripts"
        out.mkdir(parents=True)
        (out / "talk.md").write_text("x" * 500, encoding="utf-8")
        item = localfiles.describe(
            path, beside=False, output_dir=tmp_path / "library")
        assert item.has_transcript

    def test_an_unreadable_file_is_still_listed(self, tmp_path):
        """Dropping it silently leaves somebody hunting for a file they added."""
        path = _audio(tmp_path, "broken.mp3", size=8)
        item = localfiles.describe(path)
        assert item.path == path
        assert item.display_title == "broken"

    def test_a_wav_is_listed_but_not_taggable(self, tmp_path):
        """Transcribing a .wav is reasonable; there is nowhere to tag it."""
        item = localfiles.describe(_audio(tmp_path, "raw.wav"))
        assert item.taggable is False

    def test_the_length_of_an_unreadable_file_is_zero_not_an_error(self, tmp_path):
        assert localfiles.duration_of(_audio(tmp_path, "x.mp3", size=8)) == 0.0

    def test_chapter_counts_read_aloud_correctly(self, tmp_path):
        one = localfiles.LocalFile(path=Path("a.mp3"), chapter_count=1)
        many = localfiles.LocalFile(path=Path("a.mp3"), chapter_count=9)
        assert one.what_it_has() == "1 chapter"
        assert many.what_it_has() == "9 chapters"


class TestTheRun:
    def test_files_become_episodes_the_pipeline_understands(self, tmp_path):
        path = _audio(tmp_path, "talk.mp3")
        episodes = localfiles.as_episodes([localfiles.describe(path)])
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.primary_audio.local_path == str(path)
        assert ep.primary_audio.status == "ok", "or the batch would skip it"
        assert ep.out_dir == tmp_path
        assert ep.slug == "talk"

    def test_nothing_usable_is_reported_not_raised(self, tmp_path):
        from podharvest import appspace as appspace_mod
        from podharvest.config import Settings

        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
        app = appspace_mod.resolve()
        seen: list[float] = []
        result = localfiles.run_local(
            [tmp_path], app=app, settings=Settings(),
            progress_callback=seen.append)
        assert result == 0
        assert seen and seen[-1] == 100.0, "the bar must not be left half-drawn"

    def test_listing_without_transcribing_writes_nothing(self, tmp_path):
        from podharvest import appspace as appspace_mod
        from podharvest.config import Settings

        _audio(tmp_path, "talk.mp3")
        before = sorted(p.name for p in tmp_path.iterdir())
        localfiles.run_local(
            [tmp_path], app=appspace_mod.resolve(), settings=Settings(),
            transcribe=False)
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    def test_it_hands_the_batch_to_the_shared_pipeline(self, tmp_path, monkeypatch):
        """Not a reimplementation: the same function a harvest calls."""
        from podharvest import appspace as appspace_mod
        from podharvest import harvest as harvest_mod
        from podharvest.config import Settings

        path = _audio(tmp_path, "talk.mp3")
        captured = {}

        def fake(episodes, feed_dir, **kwargs):
            captured["episodes"] = list(episodes)
            captured["layout"] = kwargs.get("layout")

        monkeypatch.setattr(harvest_mod, "transcribe_all", fake)
        localfiles.run_local([path], app=appspace_mod.resolve(),
                             settings=Settings(), transcribe=True)
        assert [e.title for e in captured["episodes"]] == ["talk"]
        # And the layout hook sends the transcript beside the audio.
        assert captured["layout"](captured["episodes"][0]) == (tmp_path, "talk")


class TestThePipelineSharing:
    def test_the_batch_runner_is_shared_rather_than_copied(self):
        from podharvest import harvest

        assert callable(harvest.transcribe_all)
        # run_harvest must go through it too, or the two routes would drift.
        assert "transcribe_all(" in inspect.getsource(harvest.run_harvest)

    def test_a_transcript_beside_the_audio_is_reused(self, tmp_path):
        """The reuse check has to look where local transcripts actually live."""
        from podharvest import reuse as reuse_mod

        (tmp_path / "talk.md").write_text("x" * 500, encoding="utf-8")
        assert reuse_mod.transcript_in(tmp_path, "talk") is not None

    def test_the_feed_layout_still_works(self, tmp_path):
        from podharvest import reuse as reuse_mod

        (tmp_path / "transcripts").mkdir()
        (tmp_path / "transcripts" / "ep.md").write_text("x" * 500, encoding="utf-8")
        assert reuse_mod.existing_transcript(tmp_path, "ep") is not None


class TestTheWindow:
    """Source-shaped behaviour, checked at the source rather than by clicking.

    These are deliberately structural. The window cannot be driven end to end
    in a test without a display, but the failure mode worth catching -- the
    window saying one thing and doing another after the source changes -- is
    visible in the code that switches it.
    """

    def test_the_source_is_a_radio_box(self):
        """Announced as a named group with a count; no way to pick neither."""
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_source_box)
        assert "wx.RadioBox" in source
        assert "Podcast &feed" in source and "&Local files" in source

    def test_switching_source_swaps_the_box_and_relabels_start(self):
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._apply_source_mode)
        assert "self._feed_box" in source and "self._local_box" in source
        assert "self.start_btn.SetLabel" in source
        assert "set_accessible_name(self.start_btn" in source, (
            "a relabelled button whose accessible name is stale reads as the "
            "old button")

    def test_starting_a_run_goes_down_the_right_road(self):
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._on_start)
        assert '_start_local()' in source

    def test_the_local_run_uses_the_shared_module(self):
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._run_local_worker)
        assert "from podharvest.localfiles import run_local" in source

    def test_progress_says_file_rather_than_episode(self):
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._run_noun)
        assert '"file"' in source and '"episode"' in source

    def test_a_highlighted_local_file_is_what_play_and_edit_open(self):
        from podharvest import gui

        for name in ("_selected_episode_audio", "_episode_audio_to_edit"):
            source = inspect.getsource(getattr(gui.MainFrame, name))
            assert "_selected_local_file()" in source, name

    def test_the_columns_change_with_what_the_list_holds(self):
        from podharvest.gui import _LIBRARY_COLUMNS, _LOCAL_COLUMNS, _RUN_COLUMNS

        assert len(_LOCAL_COLUMNS) == len(_LIBRARY_COLUMNS) == len(_RUN_COLUMNS)
        headings = [h for h, _w in _LOCAL_COLUMNS]
        assert headings != [h for h, _w in _LIBRARY_COLUMNS]
        assert "File" in headings

    def test_removing_a_file_never_deletes_it(self):
        """The label and the log line both have to make that plain."""
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._on_remove_files)
        assert "never deleted" in source or "untouched" in source

    def test_the_chosen_source_is_remembered(self):
        from podharvest import gui

        assert "s.source_mode = self.source_mode()" in inspect.getsource(
            gui.MainFrame._save_settings)

    def test_the_menu_offers_a_way_in_without_the_radio(self):
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "&Add local files..." in source
        assert "Add a local f&older..." in source


class TestSettings:
    def test_the_defaults_keep_files_together(self):
        from podharvest.config import Settings

        settings = Settings()
        assert settings.local_transcripts_beside_file is True
        assert settings.local_recurse_folders is True

    def test_a_nonsense_source_mode_falls_back_to_feed(self):
        from podharvest.config import Settings

        assert Settings.from_dict({"source_mode": "sideways"}).source_mode == "feed"

    def test_the_source_mode_survives_a_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.source_mode = "local"
        assert Settings.from_dict(settings.to_dict()).source_mode == "local"


class TestTheCommandLine:
    def test_local_is_a_command(self):
        from podharvest.cli import build_parser

        args = build_parser().parse_args(["local", "a.mp3", "b.mp3"])
        assert args.command == "local"
        assert args.paths == ["a.mp3", "b.mp3"]

    def test_it_can_be_told_where_to_put_transcripts(self):
        from podharvest.cli import build_parser

        parser = build_parser()
        assert parser.parse_args(["local", "a.mp3"]).beside is None, (
            "unset means 'use the saved setting', not 'beside'")
        assert parser.parse_args(["local", "a.mp3", "--no-beside"]).beside is False
        assert parser.parse_args(["local", "a.mp3", "--beside"]).beside is True

    def test_it_is_wired_to_a_handler(self):
        from podharvest.cli import _HANDLERS

        assert "local" in _HANDLERS


class TestPackaging:
    def test_the_new_module_ships(self):
        """It is imported lazily, so PyInstaller cannot see it by itself."""
        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.localfiles" in spec


@pytest.mark.parametrize("suffix", [".mp3", ".m4b", ".flac", ".opus", ".wav"])
def test_the_formats_people_actually_have(suffix):
    assert localfiles.is_audio(Path(f"x{suffix}"))


@pytest.mark.parametrize("suffix", [".txt", ".pdf", ".jpg", ".md"])
def test_and_the_ones_that_are_not_audio(suffix):
    assert not localfiles.is_audio(Path(f"x{suffix}"))


class TestPlayingALocalFile:
    """A local row is a file, and the transport has to treat it as one."""

    def test_a_local_file_is_identified_by_its_path_not_its_title(self):
        """Two recordings can share a title; loading the wrong one is worse
        than any amount of extra reloading."""
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._on_play_selected)
        assert "self._loaded_audio_path == local.path" in source

    def test_a_file_that_has_gone_says_so_before_you_press_play(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._on_episode_selected)
        assert "local.path.is_file()" in source
        assert "no longer there" in source


class TestWithoutMutagen:
    """`podharvest local` must still run on a bare standard-library install.

    mutagen is what reads a title, a length and a chapter count off a file. It
    is optional, and the CLI's whole promise is that it runs anywhere Python
    does -- so its absence has to cost detail, not the command.
    """

    @pytest.fixture
    def no_mutagen(self, monkeypatch):
        import builtins
        import sys

        real = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "mutagen" or name.startswith("mutagen."):
                raise ImportError("no mutagen (simulated)")
            return real(name, *args, **kwargs)

        for module in [m for m in sys.modules if m.startswith("mutagen")]:
            monkeypatch.delitem(sys.modules, module)
        monkeypatch.setattr(builtins, "__import__", blocked)

    def test_a_file_is_still_listed_by_its_filename(self, no_mutagen, tmp_path):
        item = localfiles.describe(_audio(tmp_path, "a lecture.mp3"))
        assert item.display_title == "a lecture"
        assert item.what_it_has() == "audio only"

    def test_the_length_is_unknown_rather_than_an_error(self, no_mutagen, tmp_path):
        assert localfiles.duration_of(_audio(tmp_path, "x.mp3")) == 0.0

    def test_finding_files_never_needed_it_anyway(self, no_mutagen, tmp_path):
        _audio(tmp_path, "one.mp3")
        assert len(localfiles.collect([tmp_path])) == 1

    def test_an_existing_transcript_is_still_noticed(self, no_mutagen, tmp_path):
        """Reuse is a filesystem question, so it must not depend on mutagen."""
        path = _audio(tmp_path, "talk.mp3")
        (tmp_path / "talk.md").write_text("x" * 500, encoding="utf-8")
        assert localfiles.describe(path).has_transcript
