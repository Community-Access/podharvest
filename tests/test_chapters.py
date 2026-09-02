"""Chapter marker parsing, spacing and the mechanical-grid guard."""

from __future__ import annotations

from podharvest.enrich import (
    _looks_mechanical,
    _parse_chapters,
    format_chapters,
    timestamped_text,
)


class _Seg:
    def __init__(self, start: float, text: str) -> None:
        self.start = start
        self.text = text


class TestTimestampedText:
    def test_renders_clock_times(self):
        out = timestamped_text([_Seg(0, "Hello"), _Seg(3725, "Later")])
        assert out.splitlines() == ["[00:00:00] Hello", "[01:02:05] Later"]

    def test_skips_empty_segments(self):
        assert timestamped_text([_Seg(0, "   "), _Seg(5, "Real")]) == "[00:00:05] Real"


class TestParseChapters:
    def test_accepts_the_shapes_models_actually_emit(self):
        reply = (
            "Here are the chapters:\n"
            "- 00:00:00 - Introduction\n"
            "* 3:02 - Portion control\n"
            "2. [00:15:30] Audience questions\n"
        )
        assert _parse_chapters(reply, 1800) == [
            (0, "Introduction"), (182, "Portion control"), (930, "Audience questions")]

    def test_leading_digits_of_a_timestamp_are_not_eaten_as_a_bullet(self):
        # Regression: stripping "0123456789" from the left destroyed the hour.
        assert _parse_chapters("00:05:00 - Something", 1800) == [(300, "Something")]

    def test_drops_times_past_the_end_of_the_episode(self):
        assert _parse_chapters("99:00:00 - Impossible", 1800) == []

    def test_drops_near_duplicates(self):
        reply = "00:10:00 - First\n00:10:05 - Practically the same moment"
        assert len(_parse_chapters(reply, 1800)) == 1


class TestMechanicalGuard:
    def test_a_chapter_every_minute_is_rejected(self):
        # The real failure: a weak model listed the timeline instead of finding
        # topic changes, producing 34 chapters exactly 60 seconds apart.
        grid = [(60 * i, f"Topic {i}") for i in range(1, 35)]
        assert _looks_mechanical(grid) is True

    def test_genuine_uneven_boundaries_are_kept(self):
        real = [(0, "Welcome"), (34, "Guest"), (69, "Disclaimer"),
                (90, "Kitchens"), (312, "Portions"), (930, "Questions")]
        assert _looks_mechanical(real) is False

    def test_too_few_chapters_to_judge(self):
        assert _looks_mechanical([(0, "a"), (60, "b"), (120, "c")]) is False


class TestFormatChapters:
    def test_each_chapter_ends_where_the_next_begins(self):
        out = format_chapters([(0, "One"), (60, "Two")], 180)
        assert "**00:00:00 - 00:01:00**  One" in out
        assert "**00:01:00 - 00:03:00**  Two" in out

    def test_empty_list_produces_nothing(self):
        assert format_chapters([], 180) == ""
