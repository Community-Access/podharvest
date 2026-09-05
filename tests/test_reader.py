"""The reader, and where the caret is in the audio.

Finding a phrase should end with being able to hear it. These hold the
three ways that happens -- play from the caret, follow the playhead, and cut
a clip -- and the rule that following is never on unless it was asked for.
"""

from __future__ import annotations

import inspect

import pytest

wx = pytest.importorskip("wx")

from podharvest.reader import TranscriptDialog  # noqa: E402


class TestPlayFromHere:
    def test_the_dialog_accepts_the_hooks_it_needs(self):
        parameters = inspect.signature(TranscriptDialog.__init__).parameters
        for wanted in ("on_play_at", "audio_path", "follow_along", "playhead"):
            assert wanted in parameters, wanted

    def test_it_asks_the_timeline_where_the_caret_is(self):
        source = inspect.getsource(TranscriptDialog)
        assert "load_timeline" in source
        assert "time_at_char" in source

    def test_the_shortcut_is_documented_on_the_control(self):
        """A keystroke nobody can discover is not a feature."""
        source = inspect.getsource(TranscriptDialog)
        assert "Control+Enter" in source

    def test_the_caret_is_mapped_through_a_line_map(self):
        """The box carries markers and headings; the timeline does not.

        Using the raw offset drifted by however many markers and headings
        came before the caret, which on a long transcript is minutes.
        The behaviour is covered by TestTheLineMap; this holds the seam.
        """
        source = inspect.getsource(TranscriptDialog._segment_at_caret)
        assert "_segment_lines" in source


class TestFollowAlongIsOptIn:
    """It ships off. A reader that moves your caret unasked is unusable."""

    def test_the_setting_defaults_to_off(self):
        from podharvest.config import Settings

        assert Settings().follow_along is False

    def test_it_survives_a_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.follow_along = True
        assert Settings.from_dict(settings.to_dict()).follow_along is True

    def test_the_reader_starts_no_timer_unless_asked(self):
        source = inspect.getsource(TranscriptDialog.__init__)
        assert "if follow_along" in source, (
            "following must be gated on the setting, not on whether a "
            "timeline happens to exist")

    def test_following_moves_the_caret_and_nothing_else(self):
        """Selecting would make a screen reader re-read on every tick."""
        source = inspect.getsource(TranscriptDialog._follow_playhead)
        assert "SetInsertionPoint" in source
        assert "SetSelection" not in source

    def test_following_does_nothing_when_the_sentence_has_not_changed(self):
        source = inspect.getsource(TranscriptDialog._follow_playhead)
        assert "_last_follow_offset" in source

    def test_the_settings_dialog_offers_it(self):
        from podharvest import gui

        source = inspect.getsource(gui.SettingsDialog)
        assert "chk_follow_along" in source
        assert "follow playback" in source


class TestTheLineMap:
    """The box and the timeline are different coordinate systems.

    The box shows the file -- headings, blank lines, and the markers
    themselves. The timeline holds only the spoken segments with the markers
    stripped. Assuming box line N is segment N put the caret on the wrong
    sentence, which is worse than not moving it at all.
    """

    @pytest.fixture
    def reader(self, wx_app, tmp_path):
        transcript = tmp_path / "ep.md"
        transcript.write_text(
            "# An Episode\n\n"
            "[00:00:01.000] Welcome to the show.\n"
            "[00:01:05.000] The badger census showed a sharp rise.\n"
            "[00:02:30.000] And that is all we have time for.\n",
            encoding="utf-8")
        frame = wx.Frame(None)
        dialog = TranscriptDialog(
            frame, transcript, title="An Episode",
            on_play_at=lambda _ms: None, follow_along=False,
            playhead=lambda: 0)
        yield dialog
        dialog.Destroy()
        frame.Destroy()

    def test_the_map_skips_headings_and_blank_lines(self, reader):
        assert reader._segment_lines == [2, 3, 4]

    def test_the_caret_finds_the_segment_it_is_in(self, reader):
        body = reader.text.GetValue()
        reader.text.SetInsertionPoint(body.index("The badger"))
        assert reader._segment_at_caret() == 1

    def test_a_caret_in_the_heading_is_before_every_segment(self, reader):
        reader.text.SetInsertionPoint(0)
        assert reader._segment_at_caret() is None

    def test_a_segment_maps_back_to_its_own_line(self, reader):
        body = reader.text.GetValue()
        offset = reader._box_offset_of_segment(1)
        assert body[offset:].startswith("[00:01:05.000] The badger")

    def test_following_lands_on_the_sentence_being_spoken(self, reader):
        body = reader.text.GetValue()
        for where, expected in ((1_000, "Welcome"), (65_000, "badger"),
                                (150_000, "all we have")):
            reader._playhead = lambda w=where: w
            reader._last_follow_offset = -1
            reader._follow_playhead()
            position = reader.text.GetInsertionPoint()
            # How many newlines precede the caret, not how many lines
            # splitlines() makes of the prefix: those differ by one at a
            # line start, which is exactly where the caret lands.
            line = body.splitlines()[body[:position].count("\n")]
            assert expected in line, f"{where} landed on {line!r}"

    def test_a_transcript_whose_lines_do_not_match_is_left_alone(
            self, wx_app, tmp_path):
        """Better to do nothing than to move the caret somewhere wrong.

        A sidecar can describe a transcript whose markers were switched
        off, so the box has no marked lines to map onto.
        """
        transcript = tmp_path / "ep.md"
        transcript.write_text("Welcome to the show.\n", encoding="utf-8")
        (tmp_path / "ep.words.json").write_text(
            '{"version": 1, "segments": [{"text": "Welcome to the show.", '
            '"start_ms": 1000, "end_ms": 2000, "words": []}]}',
            encoding="utf-8")
        frame = wx.Frame(None)
        dialog = TranscriptDialog(frame, transcript, on_play_at=lambda _m: None)
        try:
            assert dialog._segment_lines == []
            assert dialog._segment_at_caret() is None
        finally:
            dialog.Destroy()
            frame.Destroy()


class TestClips:
    def test_a_clip_needs_a_selection(self):
        source = inspect.getsource(TranscriptDialog._on_save_clip)
        assert "Select the part" in source

    def test_it_checks_for_ffmpeg_before_promising_anything(self):
        source = inspect.getsource(TranscriptDialog._on_save_clip)
        assert "media_health" in source
