"""The Tag and Chapter Editor: it builds, it is accessible, and it round-trips.

The accessibility assertions are the point of this file. podHarvest's main
window deliberately avoids `&` mnemonics because `IsDialogMessage` scopes them
to the enclosing `wx.StaticBox`; these pages use plain grid rows precisely so
the mnemonics work, and a test has to hold that line or somebody will
reasonably "tidy" the fields into boxes and silently break every access key.
"""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")
pytest.importorskip("mutagen")

from podharvest import audio_tags_core as core  # noqa: E402
from podharvest.editor import (  # noqa: E402
    ChapterPage,
    CoverPage,
    EditorDialog,
    TagPage,
)

_PNG_1X1 = bytes.fromhex(
    # A real 1x1 red PNG. The hex that used to sit here had a truncated
    # IDAT, so wx refused it and every cover-art test popped an
    # "Unknown image data format" box -- which is how the modal was found.
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae426082"
)


@pytest.fixture
def app(wx_app):
    """The session-wide wx.App (see tests/conftest.py).

    This module used to make its own. So did two others, and a process only
    ever gets one -- whichever ran second left wx unusable for everything
    after it.
    """
    return wx_app


@pytest.fixture
def episode(tmp_path):
    path = tmp_path / "0001 - An Episode.mp3"
    path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
    tags = core.AudioTags()
    tags.set("album", "The Show")
    tags.set("publisher", "Example Press")
    tags.set("track", "7/40")
    core.write_tags(path, tags)
    core.write_mp3_chapters(path, [
        core.Chapter(index=0, title="Opening", start_ms=0, end_ms=9_500),
        core.Chapter(index=1, title="The interview", start_ms=9_500, end_ms=30_000),
    ])
    return path


@pytest.fixture
def dialog(app, episode):
    frame = wx.Frame(None)
    dlg = EditorDialog(frame, episode)
    yield dlg
    dlg.release_audio()
    dlg.Destroy()
    frame.Destroy()


class TestBuild:
    def test_every_field_gets_a_control(self, dialog):
        for field in core.TAG_FIELDS:
            assert field.key in dialog.controls, field.key

    def test_there_is_a_page_per_group_plus_cover_and_chapters(self, dialog):
        expected = {key for key, _label in core.GROUPS} | {"cover", "chapters"}
        assert set(dialog.pages) == expected

    def test_the_existing_tags_are_shown(self, dialog):
        assert dialog.controls["album"].GetValue() == "The Show"
        assert dialog.controls["publisher"].GetValue() == "Example Press"

    def test_the_existing_chapters_are_shown(self, dialog):
        titles = [c.title for c in dialog.chapter_page.chapters]
        assert titles == ["Opening", "The interview"]


class TestAccessibility:
    def test_every_control_explains_itself(self, dialog):
        for key, ctrl in dialog.controls.items():
            assert ctrl.GetToolTip() is not None, f"{key} has no explanation"

    def test_every_control_names_itself(self, dialog):
        for key, ctrl in dialog.controls.items():
            assert ctrl.GetName() not in {"", "panel", "control"}, f"{key} is unnamed"

    def test_mnemonics_are_unique_within_each_page(self, dialog):
        for name, page in dialog.pages.items():
            letters = []
            for child in page.GetChildren():
                label = child.GetLabel()
                if "&" in label:
                    letters.append(label[label.index("&") + 1].lower())
            assert len(letters) == len(set(letters)), f"duplicate mnemonic on {name}"

    def test_no_page_uses_a_static_box(self, dialog):
        """StaticBox scopes the mnemonic search; grid rows are why keys work."""
        for name, page in dialog.pages.items():
            for child in page.GetChildren():
                assert not isinstance(child, wx.StaticBox), name

    def test_each_label_precedes_its_control(self, dialog):
        """Win32 pairs a label with the control created after it."""
        for group, _label in core.GROUPS:
            children = list(dialog.pages[group].GetChildren())
            for i, child in enumerate(children):
                if isinstance(child, wx.StaticText) and child.GetLabel().endswith(":"):
                    assert i + 1 < len(children)
                    assert not isinstance(children[i + 1], wx.StaticText)


class TestRoundTrip:
    def test_values_come_back_out(self, dialog):
        dialog.controls["album"].SetValue("Renamed")
        dialog.controls["copyright"].SetValue("2026 Example")
        tags = dialog.result_tags()
        assert tags.get("album") == "Renamed"
        assert tags.get("copyright") == "2026 Example"
        assert tags.get("publisher") == "Example Press"

    def test_a_pair_field_joins_number_and_total(self, dialog):
        assert dialog.controls["track"].GetValue() == "7"
        assert dialog.totals["track"].GetValue() == "40"
        dialog.totals["track"].SetValue("41")
        assert dialog.result_tags().get("track") == "7/41"

    def test_a_checkbox_round_trips(self, dialog):
        dialog.controls["compilation"].SetValue(True)
        assert dialog.result_tags().get("compilation") == "1"

    def test_the_cover_edit_reaches_the_result(self, dialog):
        dialog.cover_page.set_cover(core.CoverArt(data=_PNG_1X1, mime="image/png"))
        result = dialog.result_tags()
        assert result.cover is not None
        assert result.cover.data == _PNG_1X1


class TestChapterPage:
    @pytest.fixture
    def page(self, app):
        frame = wx.Frame(None)
        chapters = [
            core.Chapter(index=0, title="One", start_ms=0, end_ms=10_000),
            core.Chapter(index=1, title="Two", start_ms=10_000, end_ms=20_000),
            core.Chapter(index=2, title="Three", start_ms=20_000, end_ms=30_000),
        ]
        spoken: list[str] = []
        p = ChapterPage(frame, chapters, 30_000, announce=spoken.append)
        p.spoken = spoken
        p.list.SetSelection(1)
        yield p
        frame.Destroy()

    def test_the_list_shows_times_and_lengths(self, page):
        assert "starts 0:00:10.000" in page.list.GetString(1)
        assert "runs 0:00:10.000" in page.list.GetString(1)

    def test_delete_removes_the_marker(self, page):
        page.on_delete()
        assert [c.title for c in page.chapters] == ["One", "Three"]

    def test_delete_says_the_audio_is_unchanged(self, page):
        page.spoken.clear()
        page.on_delete()
        assert any("audio is unchanged" in s for s in page.spoken)

    def test_nudge_moves_the_boundary(self, page):
        page.nudge(-1)
        assert page.chapters[1].start_ms == 9_500
        assert page.chapters[0].end_ms == 9_500

    def test_nudge_speaks_the_bare_time(self, page):
        """A sentence at key-repeat speed is noise, not feedback."""
        page.spoken.clear()
        page.nudge(-1)
        assert page.spoken[0] == "0:00:09.500"

    def test_nudge_uses_the_chosen_step(self, page):
        page.step_choice.SetSelection(core.NUDGE_STEPS_MS.index(2000))
        page._on_step_changed()
        page.nudge(1)
        assert page.chapters[1].start_ms == 12_000

    def test_the_multiplier_moves_ten_steps(self, page):
        page.nudge(1, 10)
        assert page.chapters[1].start_ms == 15_000

    def test_the_wall_is_announced_once(self, page):
        page.chapters = [
            core.Chapter(index=0, title="One", start_ms=0, end_ms=500),
            core.Chapter(index=1, title="Two", start_ms=500, end_ms=1_000),
        ]
        page.refresh(1)
        page.spoken.clear()
        page.nudge(-1)
        page.nudge(-1)
        page.nudge(-1)
        assert page.spoken == ["Cannot move further."]

    def test_preview_arms_the_stop_at_the_chapter_end(self, page):
        page.on_preview()
        assert page._stop_at_ms == 20_000

    def test_hear_boundary_plays_a_window_around_the_marker(self, page):
        page.hear_boundary()
        assert page._stop_at_ms == 12_000

    def test_hear_boundary_clamps_the_tail_at_the_end_of_the_file(self, page):
        page.list.SetSelection(2)
        page.total_ms = 21_000
        page.hear_boundary()
        assert page._stop_at_ms == 21_000


class TestCoverPage:
    def test_absent_art_is_described_in_words(self, app):
        frame = wx.Frame(None)
        try:
            page = CoverPage(frame, None)
            assert "No cover art" in page.summary.GetLabel()
        finally:
            frame.Destroy()

    def test_removing_art_says_so(self, app):
        frame = wx.Frame(None)
        spoken: list[str] = []
        try:
            page = CoverPage(
                frame,
                core.CoverArt(data=_PNG_1X1, mime="image/png"),
                announce=spoken.append,
            )
            page.remove_cover()
            assert page.cover is None
            assert spoken == ["Cover art removed."]
        finally:
            frame.Destroy()

    def test_every_button_explains_itself(self, app):
        frame = wx.Frame(None)
        try:
            page = CoverPage(frame, None)
            buttons = [c for c in page.GetChildren() if isinstance(c, wx.Button)]
            assert len(buttons) == 3
            for button in buttons:
                assert button.GetToolTip() is not None
        finally:
            frame.Destroy()


class TestTagPageOnItsOwn:
    def test_seed_and_collect_round_trip(self, app):
        frame = wx.Frame(None)
        try:
            page = TagPage(frame, "publishing")
            tags = core.AudioTags()
            tags.set("composer", "A Composer")
            page.seed(tags)
            assert page.controls["composer"].GetValue() == "A Composer"
            page.controls["isrc"].SetValue("GBAYE0000001")
            out = core.AudioTags()
            page.collect(out)
            assert out.get("isrc") == "GBAYE0000001"
            assert out.get("composer") == "A Composer"
        finally:
            frame.Destroy()


class TestReachability:
    def test_the_editor_is_reachable_from_the_main_window(self):
        """A surface nobody can open is a surface nobody has."""
        import inspect

        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui)
        assert "edit_file" in source
        assert "Edit tags and chap" in source

    def test_the_editor_has_an_accelerator(self):
        import inspect

        pytest.importorskip("wx")
        from podharvest import gui

        accelerators = inspect.getsource(gui.MainFrame._build_accelerators)
        assert "_menu_edit_tags" in accelerators


class TestPreviewVolume:
    """Judging a boundary means replaying the same seconds over and over.

    Having to reset the volume each time is the kind of small tax that stops
    people using the feature, so it is remembered — and mute keeps the level
    you set rather than dropping you to a default when you come back.
    """

    @pytest.fixture
    def player(self, app):
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        seen: list[tuple[int, bool]] = []
        spoken: list[str] = []
        p = PlayerPanel(
            frame, announce=spoken.append, volume=40, muted=False,
            on_volume=lambda v, m: seen.append((v, m)),
        )
        p.seen = seen
        p.spoken = spoken
        yield p
        frame.Destroy()

    def test_it_opens_at_the_remembered_level(self, player):
        assert player.volume() == 40
        assert player.volume_slider.GetValue() == 40
        assert player.is_muted() is False

    def test_moving_the_slider_sets_and_remembers_the_level(self, player):
        player.volume_slider.SetValue(85)
        player._on_slider()
        assert player.volume() == 85
        assert player.seen[-1] == (85, False)

    def test_the_level_is_clamped(self, player):
        player.set_volume(500)
        assert player.volume() == 100
        player.set_volume(-20)
        assert player.volume() == 0

    def test_mute_keeps_the_level_and_restores_it(self, player):
        player.set_volume(65)
        player.toggle_mute()
        assert player.is_muted() is True
        assert player.volume() == 65, "muting must not forget the level"
        player.toggle_mute()
        assert player.is_muted() is False
        assert player.volume() == 65

    def test_unmuting_from_silence_restores_something_audible(self, player):
        """Otherwise the button appears to do nothing."""
        player.set_volume(0)
        player.toggle_mute()
        player.toggle_mute()
        assert player.volume() > 0

    def test_moving_the_slider_off_zero_unmutes(self, player):
        player.toggle_mute()
        assert player.is_muted() is True
        player.volume_slider.SetValue(50)
        player._on_slider()
        assert player.is_muted() is False

    def test_the_mute_button_says_which_way_it_will_go(self, player):
        assert player.mute_btn.GetLabel() == "&Mute"
        player.toggle_mute()
        assert player.mute_btn.GetLabel() == "Un&mute"

    def test_muting_says_so(self, player):
        player.spoken.clear()
        player.toggle_mute()
        assert player.spoken == ["Muted"]
        player.spoken.clear()
        player.toggle_mute()
        assert "Unmuted" in player.spoken[0]

    def test_a_slider_move_is_not_announced(self, player):
        """The slider announces its own value; saying it again is chatter."""
        player.spoken.clear()
        player.volume_slider.SetValue(30)
        player._on_slider()
        assert player.spoken == []

    def test_the_transport_and_the_page_share_one_key_namespace(self, app):
        """The player sits inside the Chapters page, so their letters collide."""
        frame = wx.Frame(None)
        try:
            page = ChapterPage(frame, [
                core.Chapter(index=0, title="One", start_ms=0, end_ms=10_000),
                core.Chapter(index=1, title="Two", start_ms=10_000, end_ms=20_000),
            ], 20_000)
            letters: list[str] = []
            for widget in (page, page.player):
                for child in widget.GetChildren():
                    label = child.GetLabel()
                    if "&" in label:
                        letters.append(label[label.index("&") + 1].lower())
            assert len(letters) == len(set(letters)), sorted(letters)
        finally:
            frame.Destroy()


class TestVolumeSetting:
    def test_it_round_trips_and_clamps(self):
        from podharvest.config import Settings

        assert Settings().preview_volume == 70
        assert Settings.from_dict({"preview_volume": 35}).preview_volume == 35
        assert Settings.from_dict({"preview_volume": 999}).preview_volume == 100
        assert Settings.from_dict({"preview_volume": "loud"}).preview_volume == 70

    def test_edit_file_writes_the_level_back(self, app, episode, tmp_path):
        """Closing the window must not lose the level you set."""
        from podharvest.config import Settings
        pytest.importorskip("wx")
        from podharvest.editor import EditorDialog

        settings = Settings()
        saved: list[int] = []
        frame = wx.Frame(None)
        dlg = EditorDialog(
            frame, episode, volume=settings.preview_volume,
            on_volume=lambda v, m: (
                setattr(settings, "preview_volume", v),
                setattr(settings, "preview_muted", m),
                saved.append(v),
            ),
        )
        try:
            dlg.chapter_page.player.set_volume(25)
            assert settings.preview_volume == 25
            assert saved[-1] == 25
        finally:
            dlg.release_audio()
            dlg.Destroy()
            frame.Destroy()


class TestTransport:
    """Rewind, forward and speed: what you need to place a marker by ear.

    Slowing down is the useful direction. At 0.75x it is far easier to hear
    exactly where a sentence starts, which is the whole job.
    """

    @pytest.fixture
    def player(self, app):
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        spoken: list[str] = []
        p = PlayerPanel(frame, announce=spoken.append)
        p.spoken = spoken
        yield p
        frame.Destroy()

    def test_the_defaults_go_past_two_times(self, player):
        """The point of the setting: 2x is not the top of the range."""
        pytest.importorskip("wx")
        from podharvest.player import DEFAULT_RATES

        assert max(DEFAULT_RATES) > 2.0
        assert min(DEFAULT_RATES) < 0.75, "slow matters as much as fast"
        assert 1.0 in DEFAULT_RATES

    def test_it_starts_at_normal_speed(self, player):
        assert player.rate() == 1.0

    def test_the_labels_read_cleanly(self):
        """Spoken aloud, so no trailing zero and no bare number."""
        pytest.importorskip("wx")
        from podharvest.player import rate_label

        assert rate_label(2.0) == "2x"
        assert rate_label(1.25) == "1.25x"
        assert rate_label(0.5) == "0.5x"

    def test_choosing_a_speed_reports_it(self, player):
        player.rate_choice.SetSelection(player.rates().index(0.75))
        assert player.rate() == 0.75

    def test_set_rate_moves_the_control_too(self, player):
        """Otherwise the box would disagree with what is playing."""
        player.set_rate(1.5)
        assert player.rate() == 1.5

    def test_a_backend_that_refuses_is_reported_once_per_speed(self, player):
        """A control that silently does nothing is worse than one that says so.

        Once per speed rather than once ever: a backend can allow 2x and refuse
        3x, and one early refusal must not silence every later one.
        """
        player._media.SetPlaybackRate = lambda _v: False
        player.set_rates([1.0, 2.0, 3.0])
        player.spoken.clear()

        player.rate_choice.SetSelection(player.rates().index(3.0))
        player._on_rate()
        player._on_rate()
        assert len(player.spoken) == 1
        assert "3x" in player.spoken[0]

        player.rate_choice.SetSelection(player.rates().index(2.0))
        player._on_rate()
        assert len(player.spoken) == 2
        assert "2x" in player.spoken[1]

    def test_rewind_clamps_at_the_start(self, player):
        """At four seconds in, Rewind should reach the beginning, not refuse."""
        player.seek_to = lambda ms: setattr(player, "_sought", ms)
        player.playhead_ms = lambda: 4_000
        player.length_ms = lambda: 600_000
        player.skip(-10_000)
        assert player._sought == 0

    def test_forward_clamps_at_the_end(self, player):
        player.seek_to = lambda ms: setattr(player, "_sought", ms)
        player.playhead_ms = lambda: 595_000
        player.length_ms = lambda: 600_000
        player.skip(10_000)
        assert player._sought == 600_000

    def test_a_skip_in_the_middle_is_exactly_the_step(self, player):
        pytest.importorskip("wx")
        from podharvest.player import SKIP_MS

        player.seek_to = lambda ms: setattr(player, "_sought", ms)
        player.playhead_ms = lambda: 300_000
        player.length_ms = lambda: 600_000
        player.skip(SKIP_MS)
        assert player._sought == 300_000 + SKIP_MS

    def test_every_transport_control_explains_itself(self, player):
        for child in player.GetChildren():
            if isinstance(child, (wx.Button, wx.Choice, wx.Slider)):
                assert child.GetToolTip() is not None, child.GetLabel()


class TestSkipSettings:
    """Rewind and forward are separate on purpose.

    Going back is about a sentence you missed; going forward is about clearing
    an advert break. One number cannot serve both, and plenty of people want
    them different.
    """

    def test_they_default_the_same_but_are_separate_fields(self):
        from podharvest.config import Settings

        s = Settings()
        assert s.skip_back_ms == 10_000
        assert s.skip_forward_ms == 10_000
        s.skip_forward_ms = 30_000
        assert s.skip_back_ms == 10_000

    def test_they_are_clamped_to_something_sane(self):
        from podharvest.config import Settings

        assert Settings.from_dict({"skip_back_ms": 5}).skip_back_ms == 1_000
        assert Settings.from_dict({"skip_forward_ms": 10**9}).skip_forward_ms == 300_000
        assert Settings.from_dict({"skip_back_ms": "lots"}).skip_back_ms == 10_000

    def test_the_player_uses_each_in_its_own_direction(self, app):
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        try:
            player = PlayerPanel(frame, skip_back_ms=5_000, skip_forward_ms=45_000)
            player.seek_to = lambda ms: setattr(player, "_sought", ms)
            player.playhead_ms = lambda: 100_000
            player.length_ms = lambda: 600_000
            player.skip_back()
            assert player._sought == 95_000
            player.skip_forward()
            assert player._sought == 145_000
        finally:
            frame.Destroy()

    def test_changing_them_updates_the_buttons_too(self, app):
        """Otherwise Settings says one thing and the button says another."""
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        try:
            player = PlayerPanel(frame)
            player.set_skip_steps(15_000, 45_000)
            assert "15 seconds" in player._rewind_btn.GetToolTip().GetTip()
            assert "45 seconds" in player._forward_btn.GetToolTip().GetTip()
        finally:
            frame.Destroy()


class TestRememberingWhereYouStopped:
    """An hour-long episode is not heard in one sitting."""

    def test_a_position_round_trips(self, tmp_path):
        from podharvest import positions

        audio = tmp_path / "episode.mp3"
        audio.write_bytes(b"x")
        positions.save(tmp_path, audio, 300_000, length_ms=3_600_000)
        assert positions.load(tmp_path, audio) == 300_000

    def test_the_first_few_seconds_are_not_worth_returning_to(self, tmp_path):
        from podharvest import positions

        audio = tmp_path / "episode.mp3"
        audio.write_bytes(b"x")
        positions.save(tmp_path, audio, 3_000, length_ms=3_600_000)
        assert positions.load(tmp_path, audio) == 0

    def test_finishing_forgets_where_you_were(self, tmp_path):
        """Resuming four seconds from the end would play the outro and stop."""
        from podharvest import positions

        audio = tmp_path / "episode.mp3"
        audio.write_bytes(b"x")
        positions.save(tmp_path, audio, 300_000, length_ms=3_600_000)
        positions.save(tmp_path, audio, 3_596_000, length_ms=3_600_000)
        assert positions.load(tmp_path, audio) == 0

    def test_an_unknown_file_has_no_position(self, tmp_path):
        from podharvest import positions

        assert positions.load(tmp_path, tmp_path / "never-played.mp3") == 0

    def test_an_unreadable_store_reads_as_empty_not_as_an_error(self, tmp_path):
        from podharvest import positions

        (tmp_path / "playback-positions.json").write_text("{not json", encoding="utf-8")
        assert positions.load_all(tmp_path) == {}

    def test_the_store_is_bounded(self, tmp_path):
        """A store that grows forever is a slow leak nobody notices."""
        from podharvest import positions

        for index in range(positions.MAX_ENTRIES + 25):
            positions.save(tmp_path, tmp_path / f"ep{index}.mp3", 60_000)
        assert len(positions.load_all(tmp_path)) <= positions.MAX_ENTRIES

    def test_forget_clears_one_file(self, tmp_path):
        from podharvest import positions

        audio = tmp_path / "episode.mp3"
        positions.save(tmp_path, audio, 300_000)
        positions.forget(tmp_path, audio)
        assert positions.load(tmp_path, audio) == 0

    def test_saving_is_atomic_enough_to_survive_a_bad_write(self, tmp_path):
        from podharvest import positions

        positions.save(tmp_path, tmp_path / "a.mp3", 60_000)
        assert not list(tmp_path.glob("*.tmp")), "the temp file must be replaced, not left"


class TestCoverArtNeverInterrupts:
    """A cover this build cannot decode must be shrugged at, not announced.

    wx reports an unreadable image by *logging an error*, which surfaces as a
    modal "Unknown image data format" box. That is not an exception, so a
    try/except does not stop it -- which is how a corrupt test fixture came to
    pop a dialog on every cover-art test run before anybody noticed.
    """

    def test_a_corrupt_image_produces_no_thumbnail_and_no_dialog(self, app):
        pytest.importorskip("wx")
        from podharvest.editor import CoverPage

        # A PNG header with a truncated IDAT: structurally a PNG, undecodable.
        corrupt = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c6360000002000100fdff03fd"
            "0000000049454e44ae426082"
        )
        frame = wx.Frame(None)
        try:
            page = CoverPage(frame, core.CoverArt(data=corrupt, mime="image/png"))
            assert page._thumbnail_of(page.cover) is None
            assert not page.thumbnail.IsShown(), (
                "with nothing to show, the thumbnail hides rather than being "
                "handed a null bitmap, which asserts"
            )
            # The words still describe it, which is the part that matters.
            assert "PNG" in page.summary.GetLabel()
        finally:
            frame.Destroy()

    def test_a_real_image_does_produce_a_thumbnail(self, app):
        """The other half: the fixture must actually be decodable, or the
        test above passes for the wrong reason."""
        pytest.importorskip("wx")
        from podharvest.editor import CoverPage

        frame = wx.Frame(None)
        try:
            page = CoverPage(frame, core.CoverArt(data=_PNG_1X1, mime="image/png"))
            bitmap = page._thumbnail_of(page.cover)
            assert bitmap is not None and bitmap.IsOk()
            assert page.thumbnail.IsShown()
        finally:
            frame.Destroy()

    def test_no_cover_hides_the_thumbnail(self, app):
        pytest.importorskip("wx")
        from podharvest.editor import CoverPage

        frame = wx.Frame(None)
        try:
            page = CoverPage(frame, None)
            assert not page.thumbnail.IsShown()
        finally:
            frame.Destroy()



class TestChoosingYourOwnSpeeds:
    """The speeds on offer are a setting, not a fixed list."""

    def test_the_player_offers_what_it_was_given(self, app):
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        try:
            player = PlayerPanel(frame, rates=[1.0, 4.0])
            assert player.rates() == [1.0, 4.0]
            labels = [player.rate_choice.GetString(i)
                      for i in range(player.rate_choice.GetCount())]
            assert labels == ["1x", "4x"]
        finally:
            frame.Destroy()

    def test_normal_speed_is_always_offered(self, app):
        """A speed control with no way back to normal is a trap."""
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        try:
            player = PlayerPanel(frame, rates=[2.0, 3.0])
            assert 1.0 in player.rates()
            assert player.rate() == 1.0
        finally:
            frame.Destroy()

    def test_changing_the_setting_keeps_the_speed_you_were_on(self, app):
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        try:
            player = PlayerPanel(frame, rates=[1.0, 1.5, 2.0])
            player.set_rate(1.5)
            player.set_rates([1.0, 1.5, 3.0])
            assert player.rate() == 1.5, "it survived the change"
        finally:
            frame.Destroy()

    def test_losing_the_speed_you_were_on_falls_back_to_normal(self, app):
        pytest.importorskip("wx")
        from podharvest.player import PlayerPanel

        frame = wx.Frame(None)
        try:
            player = PlayerPanel(frame, rates=[1.0, 1.5])
            player.set_rate(1.5)
            player.set_rates([1.0, 3.0])
            assert player.rate() == 1.0
        finally:
            frame.Destroy()

    def test_settings_default_past_two_times(self):
        from podharvest.config import Settings

        assert max(Settings().playback_rates) > 2.0

    def test_absurd_and_unreadable_entries_are_dropped(self):
        """A hand-edited settings file must not break the transport."""
        from podharvest.config import clean_rates

        assert clean_rates([0.5, "fast", 500, -2, None, 2.0]) == [0.5, 1.0, 2.0]

    def test_normal_speed_survives_being_removed(self):
        from podharvest.config import clean_rates

        assert 1.0 in clean_rates([2.0, 3.0])
        assert clean_rates([]) == [1.0]

    def test_duplicates_collapse_and_the_list_is_ordered(self):
        from podharvest.config import clean_rates

        assert clean_rates([3.0, 1.0, 3.0, 0.75]) == [0.75, 1.0, 3.0]

    def test_the_settings_field_is_forgiving_about_how_you_type_it(self):
        """Commas, spaces, and a trailing x are all the obvious thing to write."""
        pytest.importorskip("wx")
        from podharvest.gui import _parse_rates

        assert _parse_rates("0.5, 1x, 1.5 x, 3") == [0.5, 1.0, 1.5, 3.0]
        assert _parse_rates("2 3 4") == [2.0, 3.0, 4.0]
        assert _parse_rates("") == []

    def test_it_round_trips_through_the_settings_field(self):
        from podharvest.config import clean_rates
        pytest.importorskip("wx")
        from podharvest.gui import _parse_rates, _rates_text

        text = _rates_text(clean_rates(_parse_rates("4x, 1x, 0.5x")))
        assert text == "0.5, 1, 4"
        assert clean_rates(_parse_rates(text)) == [0.5, 1.0, 4.0]

    def test_the_setting_survives_a_save_and_load(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.playback_rates = [1.0, 3.5]
        assert Settings.from_dict(settings.to_dict()).playback_rates == [1.0, 3.5]

    def test_the_main_window_hands_its_speeds_to_the_transport(self):
        import inspect

        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame)
        assert "rates=self.settings.playback_rates" in source
        # And tells it again when the setting changes, or the box would go on
        # offering speeds that were just removed.
        assert "self.player.set_rates(self.settings.playback_rates)" in source
