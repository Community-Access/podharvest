"""The timing model: where a character in a transcript is in the audio.

podHarvest has always computed word timings and thrown them away. This is
the container that keeps them, and the thing every timing-aware feature
asks. It is stdlib-only and shared byte-for-byte with QUILL, so it must
never import wx or anything from podharvest.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from podharvest import timing_core
from podharvest.timing_core import (
    TimedSegment,
    TimedWord,
    Timeline,
    SIDECAR_SUFFIX,
    load_timeline,
    timeline_from_captions,
    timeline_from_json,
    timeline_from_markers,
    timeline_from_result,
    timeline_to_json,
)


MODULE = Path(timing_core.__file__)
DIGEST_FILE = MODULE.with_suffix(".sha256")


class TestVendoring:
    """This module is shared byte-for-byte with QUILL, like reuse_core."""

    def test_the_shared_module_has_not_drifted(self):
        expected = DIGEST_FILE.read_text(encoding="utf-8").split()[0].strip()
        actual = hashlib.sha256(MODULE.read_bytes()).hexdigest()
        assert actual == expected, (
            "timing_core.py has changed. Copy the new file to QUILL, update "
            "the digest in both repos, or the two have silently diverged."
        )

    def test_it_imports_nothing_from_the_app_around_it(self):
        """A shared module that reaches back into one app is not shared."""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("podharvest"), (
                    f"timing_core imports from podharvest at line {node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("podharvest")
                    assert alias.name != "wx", "timing_core must stay wx-free"


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


class TestMarkersInTranscriptText:
    """The common case: a transcript already on disk.

    podHarvest writes `[HH:MM:SS.mmm]` at the head of every segment when
    `include_timestamps` is on, which is the default. Parsing those back is
    what makes every timing feature work on a library harvested last year.
    """

    def test_bracket_style_is_parsed(self):
        line = timeline_from_markers(
            "[00:00:01.000] the quick badger\n"
            "[00:00:03.500] ran away home\n")
        assert line.source == "markers"
        assert len(line.segments) == 2
        assert line.segments[0].start_ms == 1000
        assert line.segments[0].text == "the quick badger"
        assert line.segments[1].start_ms == 3500

    def test_paren_style_is_parsed(self):
        line = timeline_from_markers("(00:01:02.250) hello there\n")
        assert line.segments[0].start_ms == 62_250

    def test_a_segment_ends_where_the_next_begins(self):
        line = timeline_from_markers(
            "[00:00:01.000] one\n[00:00:04.000] two\n")
        assert line.segments[0].end_ms == 4000

    def test_the_last_segment_gets_a_reasonable_end(self):
        line = timeline_from_markers("[00:00:01.000] one\n")
        assert line.segments[0].end_ms > 1000

    def test_bold_markdown_around_the_stamp_is_tolerated(self):
        """Markdown output writes **[00:00:01.000]** in some styles."""
        line = timeline_from_markers("**[00:00:01.000]** one\n")
        assert line.segments[0].start_ms == 1000
        assert line.segments[0].text == "one"

    def test_speaker_labels_survive_in_the_text(self):
        line = timeline_from_markers("[00:00:01.000] **Ann:** hello\n")
        assert "Ann" in line.segments[0].text

    def test_lines_without_a_stamp_are_ignored(self):
        line = timeline_from_markers("# A heading\n\n[00:00:02.000] one\n")
        assert len(line.segments) == 1
        assert line.segments[0].start_ms == 2000

    def test_a_transcript_with_no_stamps_is_empty(self):
        line = timeline_from_markers("just some prose\nwith no times\n")
        assert line.is_empty()
        assert line.source == "none"

    def test_a_timestamp_quoted_mid_sentence_is_not_a_marker(self):
        """Otherwise a transcript discussing times grows phantom segments."""
        line = timeline_from_markers(
            "[00:00:01.000] he said [00:05:00.000] was the deadline\n")
        assert len(line.segments) == 1


_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:03.000
the quick badger

2
00:00:03.000 --> 00:00:05.000
ran away home
"""

_SRT = """1
00:00:01,000 --> 00:00:03,000
the quick badger
"""


class TestCaptions:
    """A publisher's own captions, or podHarvest's optional .vtt output.

    More precise than segment markers because the cue carries a real end
    time rather than one inferred from the next line's start.
    """

    def test_vtt_is_parsed(self):
        line = timeline_from_captions(_VTT)
        assert line.source == "captions"
        assert len(line.segments) == 2
        assert line.segments[0].start_ms == 1000
        assert line.segments[0].end_ms == 3000
        assert line.segments[0].text == "the quick badger"

    def test_srt_comma_millis_are_parsed(self):
        line = timeline_from_captions(_SRT)
        assert line.segments[0].start_ms == 1000
        assert line.segments[0].end_ms == 3000

    def test_a_multi_line_cue_becomes_one_segment(self):
        line = timeline_from_captions(
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nfirst line\nsecond line\n")
        assert line.segments[0].text == "first line second line"

    def test_something_that_is_not_captions_is_empty(self):
        assert timeline_from_captions("just prose\n").is_empty()


class TestTheSidecar:
    """Word-level precision, for runs made from now on.

    Segment markers are enough to seek to a sentence. A sidecar is what
    makes "play from this word" and an accurate clip boundary possible.
    """

    def test_a_timeline_round_trips(self):
        original = _timeline()
        restored = timeline_from_json(timeline_to_json(original))
        assert restored.segments == original.segments
        assert restored.source == "words"

    def test_the_words_survive(self):
        restored = timeline_from_json(timeline_to_json(_timeline()))
        assert restored.word_at_char(11).text == "badger"

    def test_the_suffix_is_what_the_writer_uses(self):
        assert SIDECAR_SUFFIX == ".words.json"

    def test_rubbish_gives_an_empty_timeline_rather_than_raising(self):
        """A damaged sidecar must not stop an episode being read."""
        assert timeline_from_json("{not json").is_empty()
        assert timeline_from_json("{}").is_empty()

    def test_a_future_version_is_declined_rather_than_guessed_at(self):
        text = timeline_to_json(_timeline()).replace('"version": 1',
                                                     '"version": 99')
        assert timeline_from_json(text).is_empty()


class TestFromAnEngineResult:
    def test_float_seconds_become_whole_milliseconds(self):
        class Segment:
            start, end, text = 1.5, 3.25, "hello there"
            words = [(1.5, 2.0, "hello"), (2.0, 3.25, "there")]

        line = timeline_from_result([Segment()])
        assert line.source == "words"
        assert line.segments[0].start_ms == 1500
        assert line.segments[0].words[1] == TimedWord("there", 2000, 3250)

    def test_an_engine_that_returns_no_words_still_gives_segments(self):
        class Segment:
            start, end, text = 0.0, 2.0, "hello"
            words = []

        line = timeline_from_result([Segment()])
        assert line.segments[0].words == ()

    def test_nothing_at_all_is_empty(self):
        assert timeline_from_result([]).is_empty()


class TestLoadTimeline:
    """One entry point, best source first."""

    def test_the_sidecar_wins(self, tmp_path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("[00:00:09.000] wrong\n", encoding="utf-8")
        (tmp_path / "ep.words.json").write_text(
            timeline_to_json(_timeline()), encoding="utf-8")
        line = load_timeline(transcript)
        assert line.source == "words"
        assert line.segments[0].start_ms == 1000

    def test_captions_come_next(self, tmp_path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("[00:00:09.000] wrong\n", encoding="utf-8")
        (tmp_path / "ep.vtt").write_text(_VTT, encoding="utf-8")
        assert load_timeline(transcript).source == "captions"

    def test_markers_are_the_fallback(self, tmp_path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("[00:00:01.000] hello\n", encoding="utf-8")
        line = load_timeline(transcript)
        assert line.source == "markers"
        assert line.segments[0].start_ms == 1000

    def test_a_dotted_episode_slug_still_finds_its_sidecar(self, tmp_path):
        """`with_suffix` would have turned ep.2.md into ep.words.json."""
        transcript = tmp_path / "ep.2.md"
        transcript.write_text("[00:00:09.000] wrong\n", encoding="utf-8")
        (tmp_path / "ep.2.words.json").write_text(
            timeline_to_json(_timeline()), encoding="utf-8")
        assert load_timeline(transcript).source == "words"

    def test_a_transcript_with_no_timings_is_empty_not_an_error(self, tmp_path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("no times here\n", encoding="utf-8")
        assert load_timeline(transcript).is_empty()

    def test_a_missing_file_is_empty_not_an_error(self, tmp_path):
        assert load_timeline(tmp_path / "nope.md").is_empty()


class TestSegmentsWithoutWords:
    """Most transcripts on disk have segment times only, not word times."""

    def test_a_segment_with_no_words_still_answers(self):
        line = Timeline(
            segments=(TimedSegment("hello there", 4000, 6000, words=()),),
            source="test")
        assert line.time_at_char(0) == 4000
        assert line.time_at_char(7) == 4000, "any char in the segment is the segment"
        assert line.word_at_char(0) is None
