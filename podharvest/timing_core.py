"""Where a character in a transcript is in the audio.

Every engine podHarvest supports can return word-level timings, and until
now every one of them was thrown away: the transcript went to disk as text,
search returned text, and seeking was chapter-level. This module is the
container that keeps the timings and answers the two questions any
timing-aware feature asks -- "what time is this character?" and "what
characters are this stretch of audio?".

Two design points worth keeping:

**Segments without words are first-class.** The common case is not a fresh
transcription: it is a transcript already sitting on somebody's disk, whose
only timing information is the ``[HH:MM:SS.mmm]`` marker at the start of
each segment. Everything here works at segment granularity when that is all
there is, so the features built on it work on a library harvested last year
rather than only on new runs.

**This file is shared byte-for-byte with QUILL**, the same way
``reuse_core.py`` and ``audio_tags_core.py`` are, with a SHA-256 drift test
in each repo. So: standard library only, no wx, and no imports from
``podharvest``. If you change it here, copy it there and update both
digests, or the two have silently diverged.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TimedWord:
    """One word, and when it is said. Times are whole milliseconds.

    Milliseconds rather than the float seconds the engines hand back:
    seeking, tag frames and chapter markers are all integer milliseconds, so
    converting once here means no float creeps into a filename or a frame.
    """

    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class TimedSegment:
    """One spoken stretch -- usually a sentence -- and its words if known.

    ``words`` is empty for a transcript that carries segment timings only,
    which is most of them. That is not a degraded state to be guarded
    against at every call site; it is the ordinary case, and every method
    here answers sensibly for it.
    """

    text: str
    start_ms: int
    end_ms: int
    words: tuple[TimedWord, ...] = ()


@dataclass(frozen=True)
class Timeline:
    """A whole transcript's timings, and the character offsets that match.

    ``source`` names where the timings came from -- "words", "captions",
    "markers" or "none" -- so a window can say how precise it is being
    rather than implying word accuracy it does not have.

    Character offsets are computed once at construction against the text
    this timeline would render, and every lookup is a binary search over
    them. A transcript is read once and then asked thousands of questions as
    somebody arrows through it, so the cost belongs at the front.
    """

    segments: tuple[TimedSegment, ...]
    source: str
    _starts: list[int] = field(default_factory=list, repr=False, compare=False)
    _text: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        starts: list[int] = []
        pieces: list[str] = []
        offset = 0
        for segment in self.segments:
            starts.append(offset)
            pieces.append(segment.text)
            offset += len(segment.text) + 1      # +1 for the joining newline
        object.__setattr__(self, "_starts", starts)
        object.__setattr__(self, "_text", "\n".join(pieces))

    def is_empty(self) -> bool:
        return not self.segments

    def text(self) -> str:
        """The transcript as this timeline understands it, one segment a line."""
        return self._text

    def _segment_index(self, offset: int) -> int | None:
        """Which segment character *offset* falls in, or None."""
        if offset < 0 or not self.segments or offset > len(self._text):
            return None
        index = bisect_right(self._starts, offset) - 1
        return index if index >= 0 else None

    def time_at_char(self, offset: int) -> int | None:
        """The audio position of character *offset*, in milliseconds.

        Word-accurate when words are known, segment-accurate otherwise.
        None when the offset is outside the transcript.
        """
        index = self._segment_index(offset)
        if index is None:
            return None
        segment = self.segments[index]
        local = offset - self._starts[index]
        if not segment.words:
            return segment.start_ms
        # Word offsets are found by walking the segment text rather than
        # being stored: a segment is one sentence, the walk is short, and
        # storing them would double the memory of every transcript for a
        # lookup that is already fast enough.
        best = segment.start_ms
        cursor = 0
        for word in segment.words:
            position = segment.text.find(word.text, cursor)
            if position < 0:
                continue
            cursor = position + len(word.text)
            if position <= local < cursor:
                return word.start_ms
            if position <= local:
                # Between words -- a space, punctuation -- so the last word
                # that has already started is the honest answer.
                best = word.start_ms
        return best

    def word_at_char(self, offset: int) -> TimedWord | None:
        """The word at *offset*, or None when word timings are not known."""
        index = self._segment_index(offset)
        if index is None:
            return None
        segment = self.segments[index]
        local = offset - self._starts[index]
        cursor = 0
        for word in segment.words:
            position = segment.text.find(word.text, cursor)
            if position < 0:
                continue
            cursor = position + len(word.text)
            if position <= local < cursor:
                return word
        return None

    def char_span_for_range(self, start_ms: int, end_ms: int) -> tuple[int, int] | None:
        """The characters spoken between *start_ms* and *end_ms*.

        The inverse of `time_at_char`, for turning a stretch of audio back
        into the text of it. None when nothing overlaps.
        """
        first: int | None = None
        last: int | None = None
        for index, segment in enumerate(self.segments):
            if segment.end_ms <= start_ms or segment.start_ms >= end_ms:
                continue
            begin = self._starts[index]
            if first is None:
                first = begin
            last = begin + len(segment.text)
        if first is None or last is None:
            return None
        return (first, last)
