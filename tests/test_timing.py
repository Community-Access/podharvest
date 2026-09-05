"""The timing model: where a character in a transcript is in the audio.

podHarvest has always computed word timings and thrown them away. This is
the container that keeps them, and the thing every timing-aware feature
asks. It is stdlib-only and shared byte-for-byte with QUILL, so it must
never import wx or anything from podharvest.
"""

from __future__ import annotations

from podharvest.timing_core import TimedSegment, TimedWord, Timeline


def _timeline() -> Timeline:
    """Two segments, six words. 'badger' starts at 2500 ms."""
    first = TimedSegment(
        text="the quick badger",
        start_ms=1000, end_ms=3000,
        words=(TimedWord("the", 1000, 1200),
               TimedWord("quick", 1200, 2500),
               TimedWord("badger", 2500, 3000)))
    second = TimedSegment(
        text="ran away home",
        start_ms=3000, end_ms=5000,
        words=(TimedWord("ran", 3000, 3500),
               TimedWord("away", 3500, 4200),
               TimedWord("home", 4200, 5000)))
    return Timeline(segments=(first, second), source="test")


class TestTheText:
    def test_the_text_is_the_segments_joined(self):
        assert _timeline().text() == "the quick badger\nran away home"

    def test_an_empty_timeline_knows_it(self):
        assert Timeline(segments=(), source="none").is_empty()
        assert not _timeline().is_empty()


class TestTimeAtChar:
    def test_the_first_character_is_the_first_word(self):
        assert _timeline().time_at_char(0) == 1000

    def test_a_character_inside_a_word_gives_that_word(self):
        # "badger" begins at offset 10 in "the quick badger".
        assert _timeline().time_at_char(11) == 2500

    def test_a_character_in_the_second_segment_gives_its_word(self):
        # "away" begins at offset 17 + 4 = 21.
        assert _timeline().time_at_char(22) == 3500

    def test_a_character_past_the_end_gives_nothing(self):
        assert _timeline().time_at_char(10_000) is None

    def test_a_negative_offset_gives_nothing(self):
        assert _timeline().time_at_char(-1) is None


class TestWordAtChar:
    def test_it_returns_the_word_itself(self):
        word = _timeline().word_at_char(11)
        assert word is not None
        assert word.text == "badger"
        assert (word.start_ms, word.end_ms) == (2500, 3000)


class TestCharSpanForRange:
    def test_a_time_range_maps_back_to_characters(self):
        span = _timeline().char_span_for_range(2500, 3500)
        assert span is not None
        start, end = span
        assert _timeline().text()[start:end].startswith("the quick badger")

    def test_a_range_with_nothing_in_it_gives_nothing(self):
        assert _timeline().char_span_for_range(90_000, 95_000) is None


class TestSegmentsWithoutWords:
    """Most transcripts on disk have segment times only, not word times."""

    def test_a_segment_with_no_words_still_answers(self):
        line = Timeline(
            segments=(TimedSegment("hello there", 4000, 6000, words=()),),
            source="test")
        assert line.time_at_char(0) == 4000
        assert line.time_at_char(7) == 4000, "any char in the segment is the segment"
        assert line.word_at_char(0) is None
