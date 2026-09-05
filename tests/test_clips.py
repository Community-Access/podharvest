"""Cutting a passage out of an episode by reading rather than by scrubbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from podharvest.clips import build_clip_command, clip_filename


class TestTheCommand:
    def test_it_seeks_before_the_input_for_speed(self):
        """-ss before -i makes ffmpeg seek rather than decode to the point."""
        command = build_clip_command(
            Path("in.mp3"), Path("out.mp3"), 60_000, 65_000)
        assert command.index("-ss") < command.index("-i")

    def test_the_duration_is_the_span(self):
        command = build_clip_command(
            Path("in.mp3"), Path("out.mp3"), 60_000, 65_000)
        assert command[command.index("-t") + 1] == "5.000"

    def test_it_fades_both_ends(self):
        """A clip that starts mid-syllable at full volume sounds broken."""
        command = build_clip_command(
            Path("in.mp3"), Path("out.mp3"), 0, 10_000, fade_ms=120)
        filters = command[command.index("-af") + 1]
        assert "afade=t=in" in filters and "afade=t=out" in filters

    def test_a_very_short_clip_does_not_fade_over_itself(self):
        """A 200 ms clip with a 120 ms fade each end would be all fade."""
        command = build_clip_command(
            Path("in.mp3"), Path("out.mp3"), 0, 200, fade_ms=120)
        filters = command[command.index("-af") + 1]
        assert "d=0.050" in filters

    def test_a_backwards_span_is_refused(self):
        with pytest.raises(ValueError):
            build_clip_command(Path("in.mp3"), Path("out.mp3"), 5000, 1000)

    def test_it_is_a_list_so_a_quoted_title_cannot_become_a_flag(self):
        command = build_clip_command(
            Path('a "show".mp3'), Path("out.mp3"), 0, 1000)
        assert isinstance(command, list)
        assert 'a "show".mp3' in command


class TestTheFilename:
    def test_it_uses_the_words_that_were_said(self):
        name = clip_filename("My Show Episode 3", "the badger census showed")
        assert "badger" in name
        assert name.endswith(".mp3")

    def test_it_is_safe_on_windows(self):
        name = clip_filename('Show: "one"', 'a/b\\c *? <d>')
        for bad in '\\/:*?"<>|':
            assert bad not in name

    def test_it_does_not_run_away(self):
        name = clip_filename("Show", "word " * 200)
        assert len(name) < 120

    def test_it_never_returns_an_empty_name(self):
        assert clip_filename("", "").endswith(".mp3")
        assert len(clip_filename("", "")) > 4
