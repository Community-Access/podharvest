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

import json
import re
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


# -- reading timings back out of what is already on disk -----------------------

#: A segment marker as podHarvest writes it: `[HH:MM:SS.mmm]` or the same in
#: parentheses, optionally wrapped in markdown bold. Anchored to the start of
#: the line, because a timestamp quoted mid-sentence is prose, not a marker.
_MARKER_RE = re.compile(
    r"^\s*(?:\*\*)?[\[(](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?[\])](?:\*\*)?\s*")

#: How long the final segment is assumed to run when nothing follows it.
#: Only ever an end bound for the last line, whose true end is the audio's
#: length -- which this module deliberately does not know, because it never
#: opens the audio.
_TAIL_MS = 5_000


def timeline_from_markers(text: str) -> Timeline:
    """Read the timings podHarvest already wrote into a transcript.

    This is the fallback that matters most. A `.words.json` sidecar only
    exists for runs made after it was introduced, and captions are optional,
    but almost every transcript on disk carries these markers because
    `include_timestamps` defaults to on. Parsing them back means the timing
    features work on a library somebody harvested a year ago.

    Segment-level only, by nature: the marker says when the segment began
    and nothing about the words inside it.
    """
    starts: list[int] = []
    bodies: list[str] = []
    for line in text.splitlines():
        match = _MARKER_RE.match(line)
        if match is None:
            continue
        hours, minutes, seconds, millis = match.groups()
        start = (int(hours) * 3_600_000 + int(minutes) * 60_000
                 + int(seconds) * 1000 + int((millis or "0").ljust(3, "0")))
        body = line[match.end():].strip()
        if not body:
            continue
        starts.append(start)
        bodies.append(body)
    segments = [
        TimedSegment(
            text=body,
            start_ms=start,
            end_ms=(starts[index + 1] if index + 1 < len(starts)
                    else start + _TAIL_MS))
        for index, (start, body) in enumerate(zip(starts, bodies))
    ]
    return Timeline(segments=tuple(segments),
                    source="markers" if segments else "none")


#: A WebVTT or SRT timing line. The two formats differ only in whether the
#: millisecond separator is a dot or a comma, so one pattern reads both.
_CUE_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")


def _cue_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return (int(hours) * 3_600_000 + int(minutes) * 60_000
            + int(seconds) * 1000 + int(millis))


def timeline_from_captions(text: str) -> Timeline:
    """Read a WebVTT or SRT file into a timeline.

    Better than segment markers where it exists, because a cue carries a
    real end time rather than one guessed from where the next line starts.
    `reuse_core` already parses these to strip the timings out; this keeps
    them, which is the whole point.
    """
    segments: list[TimedSegment] = []
    start = end = 0
    body: list[str] = []
    started = False

    def flush() -> None:
        if started and body:
            segments.append(TimedSegment(
                text=" ".join(body).strip(), start_ms=start, end_ms=end))

    for raw in text.splitlines():
        line = raw.strip()
        match = _CUE_RE.match(line)
        if match is not None:
            flush()
            body = []
            groups = match.groups()
            start = _cue_ms(*groups[:4])
            end = _cue_ms(*groups[4:])
            started = True
            continue
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        if started:
            body.append(line)
    flush()
    return Timeline(segments=tuple(segments),
                    source="captions" if segments else "none")


# -- the sidecar a run writes --------------------------------------------------

#: What the timing sidecar is called, beside the transcript it belongs to.
#: Two extensions rather than one so it sorts next to `<slug>.md`, is
#: obviously secondary to it, and leaves `Path.stem` naming the episode.
SIDECAR_SUFFIX = ".words.json"

#: Bumped only when the shape changes incompatibly. A reader finding a
#: version it does not know returns an empty timeline and lets the caller
#: fall back to markers, rather than guessing.
SIDECAR_VERSION = 1


def timeline_to_json(line: Timeline) -> str:
    """Serialise a timeline for the sidecar beside a transcript."""
    return json.dumps({
        "version": SIDECAR_VERSION,
        "segments": [
            {
                "text": segment.text,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "words": [[word.text, word.start_ms, word.end_ms]
                          for word in segment.words],
            }
            for segment in line.segments
        ],
    }, ensure_ascii=False)


def timeline_from_json(text: str) -> Timeline:
    """Read a sidecar. Never raises: a damaged file is an empty timeline.

    Anything wrong here means the caller falls back to the markers in the
    transcript, which is a coarser answer but still a working one. Refusing
    to open an episode because a secondary file is corrupt would not be.
    """
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return Timeline(segments=(), source="none")
    if not isinstance(raw, dict) or raw.get("version") != SIDECAR_VERSION:
        return Timeline(segments=(), source="none")
    segments: list[TimedSegment] = []
    for entry in raw.get("segments") or []:
        if not isinstance(entry, dict):
            continue
        words = tuple(
            TimedWord(str(w[0]), int(w[1]), int(w[2]))
            for w in (entry.get("words") or [])
            if isinstance(w, (list, tuple)) and len(w) == 3
        )
        try:
            segments.append(TimedSegment(
                text=str(entry.get("text", "")),
                start_ms=int(entry.get("start_ms", 0)),
                end_ms=int(entry.get("end_ms", 0)),
                words=words))
        except (TypeError, ValueError):
            continue
    return Timeline(segments=tuple(segments),
                    source="words" if segments else "none")


def timeline_from_result(segments) -> Timeline:
    """Build a timeline from what a transcription engine just returned.

    Takes segment objects duck-typed -- `.start`, `.end`, `.text` in float
    seconds and `.words` as (start, end, text) tuples -- so this module
    keeps its promise not to import anything from the app around it.
    """
    built: list[TimedSegment] = []
    for segment in segments or []:
        words = tuple(
            TimedWord(str(text), int(float(start) * 1000), int(float(end) * 1000))
            for start, end, text in (getattr(segment, "words", None) or [])
        )
        built.append(TimedSegment(
            text=str(getattr(segment, "text", "")).strip(),
            start_ms=int(float(getattr(segment, "start", 0.0)) * 1000),
            end_ms=int(float(getattr(segment, "end", 0.0)) * 1000),
            words=words))
    return Timeline(segments=tuple(built), source="words" if built else "none")


# -- the one way in ------------------------------------------------------------

#: How large a timing file may be. The same ceiling the reader and the
#: search apply to transcripts: past this, it is not what it claims to be.
MAX_TIMING_BYTES = 16 * 1024 * 1024


def _read(path) -> str:
    """Read a file, or return "" for anything that goes wrong.

    Timings are always secondary to the transcript they describe, so no
    failure here is worth raising: the caller falls back to a coarser source
    or to nothing, and the feature says it is being less precise.
    """
    try:
        if path.stat().st_size > MAX_TIMING_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_timeline(transcript_path) -> Timeline:
    """The timings for a transcript, from the best source available.

    In order: the `.words.json` sidecar (word-accurate, written by runs from
    now on), a `.vtt` or `.srt` beside it (cue-accurate, either the
    publisher's or podHarvest's own), then the `[HH:MM:SS.mmm]` markers in
    the transcript itself (segment-accurate, and present in almost every
    transcript already on disk).

    Always returns a Timeline. `is_empty()` and `source` are how a caller
    finds out how much it got.
    """
    from pathlib import Path

    path = Path(transcript_path)
    # Built from the stem rather than with `with_suffix`, which would eat a
    # dotted episode slug: `ep.2.md` must give `ep.2.words.json`.
    sidecar = path.with_name(path.stem + SIDECAR_SUFFIX)
    if sidecar.is_file():
        line = timeline_from_json(_read(sidecar))
        if not line.is_empty():
            return line
    for suffix in (".vtt", ".srt"):
        captions = path.with_name(path.stem + suffix)
        if captions.is_file():
            line = timeline_from_captions(_read(captions))
            if not line.is_empty():
                return line
    return timeline_from_markers(_read(path))
