# podHarvest: Word Timings, Announcements, and Shared Foundations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make podHarvest use the timing data it already computes and discards, so a phrase found in a transcript can be heard, read along with, clipped, or turned into a chapter marker — and give a run a voice, so it can say what it is doing.

**Architecture:** One new stdlib-only module, `podharvest/timing_core.py`, owns the timing model and every way of loading it. It is written share-ready from day one (byte-identical vendoring with a SHA-256 drift test, exactly as `reuse_core.py` and `audio_tags_core.py` already are), because QUILL will adopt it in a later cycle. Timings are loaded from the best available source in priority order — a new `.words.json` sidecar, then a `.vtt`/`.srt` caption file, then the `[HH:MM:SS.mmm]` markers podHarvest already writes into every transcript. That last fallback is what makes all four features work **retroactively on transcripts already on disk**, rather than requiring a re-transcribe. A second new module, `podharvest/announce.py`, provides opt-in spoken and braille output through a component installed on demand, so `dependencies = []` stays literally true.

**Tech Stack:** Python 3.10+, standard library only in the core path. wxPython for UI. `accessible_output2` installed on demand into the app space via the existing `podharvest/acquire.py` mechanism. No new hard dependencies.

## Global Constraints

- **`dependencies = []` in `pyproject.toml` stays literally true.** Anything needing a package installs on demand through `podharvest/acquire.py` into the app space, never into system Python. Every feature degrades to a clear, spoken-readable explanation when its component is absent.
- **Follow-along reading is opt-in and off by default.** It must never activate without the user turning it on. This is an explicit instruction from the maintainer.
- **Announcements are opt-in and off by default**, per category (completions, progress, errors), with braille as a separate box.
- **No timers, no background work, nothing downloaded without the user pressing something.** The favourites prompt is one refusable question at launch and nothing else.
- **Accessibility rules** (`CLAUDE.md`, `docs/ACCESSIBILITY.md`): create the `wx.StaticText` label *before* the control it labels; never call `set_accessible_name` on a `wx.ListCtrl`, `wx.ListBox`, `wx.Notebook`, `wx.RadioBox` or `wx.CheckBox` (it replaces the native accessible and breaks row/tab/state announcements); every focusable control gets an inline `SetToolTip` at its construction site or `python -m podharvest.help_audit` fails the build.
- **Screen-reader output style:** no emoji, no decorative Unicode, plain ASCII punctuation, hyphen bullets.
- **After any UI change:** run `python -m podharvest.help_audit --write` and review the diff before committing.
- **Test command:** `python -m pytest tests -q --no-header -p no:randomly`. Full suite must pass before each commit.
- **Commits:** frequent, one per task minimum. Never push unless asked.

---

## Progress

Update this table as tasks land. It is the single answer to "what is done and what remains".

| # | Task | Status |
|---|---|---|
| 1 | `timing_core.py`: the timing model | Done |
| 2 | Load timings from bracketed transcript text | Done |
| 3 | Load timings from VTT/SRT | Done |
| 4 | The `.words.json` sidecar (writing) | Done |
| 5 | `load_timeline`: source priority and the public entry point | Done |
| 6 | Share-ready: digest, gitattributes, drift test | Done |
| 7 | Search then hear it | Done |
| 8 | Play from here, in the reader | Done |
| 9 | Follow-along reading (opt-in) | Done |
| 10 | Clip export | Done |
| 11 | Place a chapter by phrase | Done |
| 12 | `announce.py`: the bridge | Done |
| 13 | Announcements wired into runs, opt-in | Done |
| 14 | Braille output | Done |
| 15 | Ask-once-per-launch favourites check | Done |
| 16 | Documentation and the release | Done (build unsigned) |

### Done outside this plan, asked for during it

| Task | Status |
|---|---|
| Alt+T reaches the Tools menu; no control claims a menu letter | Done |
| Tab no longer enters the status bar; F6 only | Done |
| Model acquisition in its own window, naming both phases | Done |
| Model list no longer varies with free memory | Done |
| Set up models: the full inventory, nothing hidden | Done |
| The model description box is sized to hold a description | Done |

### Found and fixed while building this

- `Settings.from_dict` did not know about the `opml` source mode, so
  choosing Podcast list and reopening silently landed back on Podcast feed.
- The reader's box and the timeline are different coordinate systems;
  assuming box line N was segment N put the caret on the wrong sentence in
  both directions. Both now go through one explicit line map.
- Subclassing a wx control hid it from the help gate, so the gate follows
  subclasses now and cannot be dodged by wrapping a control.
- The chapter page's new phrase field collided with the transport's Play
  mnemonic; the editor's own test caught it.

**Deferred to a later cycle (QUILL):** de-esser and noise gate as ffmpeg fragments, dereverb, breath softening, the music bed with sidechain ducking, the preset rework, word timings from QUILL's local ASR providers, Edge TTS, and QUILL's adoption of the four shared modules. None of it is in this plan.

---

## File Structure

**New files:**

- `podharvest/timing_core.py` — the timing model and every loader. Pure stdlib, no wx, no podHarvest imports. Vendored share-ready.
- `podharvest/timing_core.sha256` — the drift digest.
- `podharvest/announce.py` — spoken and braille output. Imports wx only for `wx.CallAfter`; degrades to no-op without the component.
- `podharvest/clips.py` — cutting a passage out of an audio file with ffmpeg.
- `tests/test_timing.py`
- `tests/test_announce.py`
- `tests/test_clips.py`

**Modified files:**

- `podharvest/transcribe.py` — write the `.words.json` sidecar
- `podharvest/harvest.py` — call the sidecar writer
- `podharvest/transcript_search.py` — carry a time on every match
- `podharvest/reader.py` — play from here, follow-along
- `podharvest/gui.py` — wiring, the launch prompt, the clip action
- `podharvest/editor.py` — place a chapter by phrase
- `podharvest/config.py` — new settings
- `podharvest/help.py` — F1 text for new controls
- `.gitattributes` — pin the new shared file's line endings
- `docs/REFERENCE.md`, `docs/ACCESSIBILITY.md`, `README.md`, `CHANGELOG.md`

---

## Task 1: `timing_core.py` — the timing model

**Files:**
- Create: `S:\code\pod\podharvest\timing_core.py`
- Test: `S:\code\pod\tests\test_timing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TimedWord(text: str, start_ms: int, end_ms: int)`, `TimedSegment(text: str, start_ms: int, end_ms: int, words: tuple[TimedWord, ...])`, `Timeline(segments: tuple[TimedSegment, ...], source: str)` with methods `is_empty() -> bool`, `time_at_char(offset: int) -> int | None`, `char_span_for_range(start_ms, end_ms) -> tuple[int, int] | None`, `text() -> str`, and `word_at_char(offset: int) -> TimedWord | None`.

- [ ] **Step 1: Write the failing test**

Create `S:\code\pod\tests\test_timing.py`:

```python
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
        assert _timeline().text()[start:end].startswith("badger")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: No module named 'podharvest.timing_core'`

- [ ] **Step 3: Write the implementation**

Create `S:\code\pod\podharvest\timing_core.py`:

```python
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
    "markers" or "none" -- so the window can say how precise it is being
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
        for word in segment.words:
            # Word offsets are not stored; they are found by walking the
            # segment text, which is short. Storing them would double the
            # memory for a lookup that is already fast enough.
            position = segment.text.find(word.text)
            if position >= 0 and position <= local < position + len(word.text):
                return word.start_ms
        if segment.words:
            # Between words -- punctuation, a space -- so the nearest word
            # that has already started is the honest answer.
            best = segment.start_ms
            for word in segment.words:
                position = segment.text.find(word.text)
                if 0 <= position <= local:
                    best = word.start_ms
            return best
        return segment.start_ms

    def word_at_char(self, offset: int) -> TimedWord | None:
        """The word at *offset*, or None when word timings are not known."""
        index = self._segment_index(offset)
        if index is None:
            return None
        segment = self.segments[index]
        local = offset - self._starts[index]
        for word in segment.words:
            position = segment.text.find(word.text)
            if position >= 0 and position <= local < position + len(word.text):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add podharvest/timing_core.py tests/test_timing.py
git commit -m "Add the timing model that keeps what transcription already knew"
```

---

## Task 2: Load timings from bracketed transcript text

**Files:**
- Modify: `S:\code\pod\podharvest\timing_core.py`
- Test: `S:\code\pod\tests\test_timing.py`

**Interfaces:**
- Consumes: `TimedSegment`, `Timeline` from Task 1.
- Produces: `timeline_from_markers(text: str) -> Timeline` — parses `[HH:MM:SS.mmm]` and `(HH:MM:SS.mmm)` prefixes, the two styles `transcribe.FormatOptions` writes.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_timing.py`:

```python
from podharvest.timing_core import timeline_from_markers


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing.py -k Markers -q --no-header -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'timeline_from_markers'`

- [ ] **Step 3: Write the implementation**

Append to `S:\code\pod\podharvest\timing_core.py`:

```python
import re

#: A segment marker as podHarvest writes it: `[HH:MM:SS.mmm]` or the same in
#: parentheses, optionally wrapped in markdown bold. Anchored to the start of
#: the line, because a timestamp quoted mid-sentence is prose, not a marker.
_MARKER_RE = re.compile(
    r"^\s*(?:\*\*)?[\[(](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?[\])](?:\*\*)?\s*")

#: How long the final segment is assumed to run when nothing follows it.
#: Only ever used as an end bound for the last line, where the true end is
#: whatever the audio's length is -- which this module deliberately does not
#: know, because it never opens the audio.
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
    segments: list[TimedSegment] = []
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
    for index, (start, body) in enumerate(zip(starts, bodies)):
        end = starts[index + 1] if index + 1 < len(starts) else start + _TAIL_MS
        segments.append(TimedSegment(text=body, start_ms=start, end_ms=end))
    return Timeline(segments=tuple(segments),
                    source="markers" if segments else "none")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: PASS, 19 tests.

- [ ] **Step 5: Commit**

```bash
git add podharvest/timing_core.py tests/test_timing.py
git commit -m "Read timings back out of the transcripts already on disk"
```

---

## Task 3: Load timings from VTT and SRT

**Files:**
- Modify: `S:\code\pod\podharvest\timing_core.py`
- Test: `S:\code\pod\tests\test_timing.py`

**Interfaces:**
- Consumes: `TimedSegment`, `Timeline`.
- Produces: `timeline_from_captions(text: str) -> Timeline`.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_timing.py`:

```python
from podharvest.timing_core import timeline_from_captions

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing.py -k Captions -q --no-header -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'timeline_from_captions'`

- [ ] **Step 3: Write the implementation**

Append to `S:\code\pod\podharvest\timing_core.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: PASS, 23 tests.

- [ ] **Step 5: Commit**

```bash
git add podharvest/timing_core.py tests/test_timing.py
git commit -m "Read timings from captions, which carry real end times"
```

---

## Task 4: The `.words.json` sidecar

**Files:**
- Modify: `S:\code\pod\podharvest\timing_core.py`
- Modify: `S:\code\pod\podharvest\harvest.py:245-252`
- Test: `S:\code\pod\tests\test_timing.py`

**Interfaces:**
- Consumes: `Timeline`, `TimedSegment`, `TimedWord`.
- Produces: `timeline_to_json(line: Timeline) -> str`, `timeline_from_json(text: str) -> Timeline`, and `SIDECAR_SUFFIX = ".words.json"`.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_timing.py`:

```python
from podharvest.timing_core import (SIDECAR_SUFFIX, timeline_from_json,
                                    timeline_to_json)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing.py -k Sidecar -q --no-header -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'SIDECAR_SUFFIX'`

- [ ] **Step 3: Write the implementation**

Append to `S:\code\pod\podharvest\timing_core.py`:

```python
import json

#: What the timing sidecar is called, beside the transcript it belongs to.
#: Two extensions rather than one so it sorts next to `<slug>.md` and is
#: obviously secondary to it, and so `Path.stem` still names the episode.
SIDECAR_SUFFIX = ".words.json"

#: Bumped only when the shape changes incompatibly. A reader that finds a
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
    transcript, which is a worse answer but still a working one. Refusing to
    open an episode because a secondary file is corrupt would not be.
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

    Takes `transcribe.TranscriptSegment` objects duck-typed -- `.start`,
    `.end`, `.text` in float seconds, and `.words` as (start, end, text)
    tuples -- so this module keeps its promise not to import podharvest.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: PASS, 27 tests.

- [ ] **Step 5: Write the sidecar during a run**

In `S:\code\pod\podharvest\harvest.py`, find the block that writes the optional caption files (around line 245-252, beginning with the comment about `write_srt` / `write_vtt`). Add immediately after that block:

```python
    # The timings the engine just produced, kept beside the transcript.
    # Written unconditionally rather than behind a setting: it is a few
    # kilobytes, it is what makes "play from this word" possible, and a
    # setting nobody knows to turn on would leave the feature dark for
    # everyone who did not read the release notes.
    from podharvest import timing_core

    timeline = timing_core.timeline_from_result(result.segments)
    if not timeline.is_empty():
        write_text(out_dir / f"{slug}{timing_core.SIDECAR_SUFFIX}",
                   timing_core.timeline_to_json(timeline))
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add podharvest/timing_core.py podharvest/harvest.py tests/test_timing.py
git commit -m "Keep the word timings a run produced, beside its transcript"
```

---

## Task 5: `load_timeline` — source priority

**Files:**
- Modify: `S:\code\pod\podharvest\timing_core.py`
- Test: `S:\code\pod\tests\test_timing.py`

**Interfaces:**
- Consumes: all three loaders.
- Produces: `load_timeline(transcript_path) -> Timeline` — the single entry point every feature calls.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_timing.py`:

```python
from pathlib import Path

from podharvest.timing_core import load_timeline


class TestLoadTimeline:
    """One entry point, best source first."""

    def test_the_sidecar_wins(self, tmp_path: Path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("[00:00:09.000] wrong\n", encoding="utf-8")
        (tmp_path / "ep.words.json").write_text(
            timeline_to_json(_timeline()), encoding="utf-8")
        line = load_timeline(transcript)
        assert line.source == "words"
        assert line.segments[0].start_ms == 1000

    def test_captions_come_next(self, tmp_path: Path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("[00:00:09.000] wrong\n", encoding="utf-8")
        (tmp_path / "ep.vtt").write_text(_VTT, encoding="utf-8")
        assert load_timeline(transcript).source == "captions"

    def test_markers_are_the_fallback(self, tmp_path: Path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("[00:00:01.000] hello\n", encoding="utf-8")
        line = load_timeline(transcript)
        assert line.source == "markers"
        assert line.segments[0].start_ms == 1000

    def test_a_transcript_with_no_timings_is_empty_not_an_error(self, tmp_path: Path):
        transcript = tmp_path / "ep.md"
        transcript.write_text("no times here\n", encoding="utf-8")
        assert load_timeline(transcript).is_empty()

    def test_a_missing_file_is_empty_not_an_error(self, tmp_path: Path):
        assert load_timeline(tmp_path / "nope.md").is_empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing.py -k LoadTimeline -q --no-header -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'load_timeline'`

- [ ] **Step 3: Write the implementation**

Append to `S:\code\pod\podharvest\timing_core.py`:

```python
#: How large a timing file is allowed to be. The same ceiling the reader and
#: the search apply to transcripts: past this, it is not what it claims.
MAX_TIMING_BYTES = 16 * 1024 * 1024


def _read(path) -> str:
    """Read a file, or return "" for anything that goes wrong.

    Timings are always secondary to the transcript they describe, so no
    failure here is worth raising: the caller falls back to a coarser source
    or to nothing, and the feature says it is less precise.
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
    sidecar = path.with_suffix("").with_suffix(SIDECAR_SUFFIX) \
        if path.suffix else path.with_name(path.name + SIDECAR_SUFFIX)
    # `.with_suffix` twice would eat a dotted episode slug, so build it from
    # the stem directly: `ep.md` -> `ep.words.json`, never `ep.the.words.json`.
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
```

Note: delete the first `sidecar = ...` assignment and keep only the
`path.with_name(path.stem + SIDECAR_SUFFIX)` form — the comment explains
why. It is written this way so the reason survives; do not leave both lines.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: PASS, 32 tests.

- [ ] **Step 5: Commit**

```bash
git add podharvest/timing_core.py tests/test_timing.py
git commit -m "One way in to a transcript's timings, best source first"
```

---

## Task 6: Make `timing_core` share-ready

**Files:**
- Create: `S:\code\pod\podharvest\timing_core.sha256`
- Modify: `S:\code\pod\.gitattributes`
- Modify: `S:\code\pod\tests\test_timing.py`
- Modify: `S:\code\pod\podharvest\help_audit.py` (no change needed — confirm `timing_core.py` is not in `SCAN_FILES`, which is correct: it builds no controls)

**Interfaces:** none new.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_timing.py`:

```python
import hashlib

from podharvest import timing_core

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

    def test_it_imports_nothing_from_podharvest(self):
        """A shared module that reaches back into one app is not shared."""
        import ast

        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("podharvest"), (
                    f"timing_core imports from podharvest at line {node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("podharvest")
                    assert alias.name != "wx", "timing_core must stay wx-free"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing.py -k Vendoring -q --no-header -p no:randomly`
Expected: FAIL — the digest file does not exist.

- [ ] **Step 3: Pin the line endings**

Append to `S:\code\pod\.gitattributes`, in the existing shared-module block:

```
podharvest/timing_core.py -text
podharvest/timing_core.sha256 -text
```

- [ ] **Step 4: Write the digest**

Run:

```bash
python -c "import hashlib,pathlib; p=pathlib.Path('podharvest/timing_core.py'); pathlib.Path('podharvest/timing_core.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'\n', encoding='utf-8')"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_timing.py -q --no-header -p no:randomly`
Expected: PASS, 34 tests.

- [ ] **Step 6: Record the sharing contract**

Create `S:\code\pod\docs\SHARED.md`:

```markdown
# Modules shared with QUILL

Some files exist byte-for-byte in both podHarvest and QUILL. They are not a
library and not a submodule: each repo carries its own copy, and a SHA-256
drift test in each fails the build when the two stop matching. That is
deliberate. Both apps ship standalone, neither may depend on the other, and
a silent divergence in shared logic is the failure worth engineering
against.

| File here | File in QUILL | Test that holds it |
|---|---|---|
| `podharvest/audio_tags_core.py` | `quill/core/speech/audio_tags_core.py` | `tests/test_audio_tags.py` |
| `podharvest/reuse_core.py` | `quill/core/speech/reuse_core.py` | `tests/test_reuse.py` |
| `podharvest/timing_core.py` | *(not yet adopted)* | `tests/test_timing.py` |

## The rules

- Standard library only. No wx, no third-party packages, no imports from
  `podharvest` or `quill`. A test enforces this for `timing_core`.
- Line endings are pinned with `-text` in `.gitattributes`. Without that,
  `* text=auto eol=lf` rewrites the file on checkout and the two copies
  hash differently on different machines.
- To change one: edit here, copy the file to QUILL, regenerate both
  digests, commit both repos. There is no shortcut, and the test is what
  stops there being one.

## Candidates not yet shared

These exist here and QUILL has no equivalent. They are written to be
portable; adoption is a later cycle's work.

- `podharvest/a11y.py` — `set_accessible_name` and the rule that composite
  controls keep their native accessibility, with `tests/test_a11y.py`.
- `podharvest/help_audit.py` — the AST gate that fails the build when a
  focusable control ships with no help authored at its construction site.
- `scripts/code_signing.py` — Authenticode via Azure Trusted Signing.
- `installer/podharvest.iss` `[Code]` section — native `TNewCheckBox`
  instead of `[Tasks]`, because Inno's own check list never reports its
  checked state to a screen reader.
```

- [ ] **Step 7: Commit**

```bash
git add podharvest/timing_core.sha256 .gitattributes tests/test_timing.py docs/SHARED.md
git commit -m "Pin timing_core as a shared module and write the sharing contract"
```

---

## Task 7: Search, then hear it

**Files:**
- Modify: `S:\code\pod\podharvest\transcript_search.py:39-96`
- Modify: `S:\code\pod\podharvest\gui.py` (`_on_search_transcripts`)
- Test: `S:\code\pod\tests\test_transcript_search.py`

**Interfaces:**
- Consumes: `load_timeline` from Task 5.
- Produces: `EpisodeMatch` gains `start_ms: int | None`; `TranscriptSearchDialog.chosen` continues to be the episode, and gains `chosen_ms: int | None`.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_transcript_search.py`:

```python
class TestMatchesCarryATime:
    """Finding a phrase should end with hearing it, not with reading a row."""

    def test_a_match_in_a_timestamped_transcript_knows_its_time(self, tmp_path):
        from podharvest.transcript_search import search_transcripts

        transcript = tmp_path / "ep.md"
        transcript.write_text(
            "[00:00:01.000] nothing here\n"
            "[00:01:05.000] the badger census showed\n",
            encoding="utf-8")

        class Episode:
            show, title = "A Show", "Ep 1"
            transcript_path = transcript

        episode = Episode()
        episode.transcript = transcript
        found = search_transcripts([episode], "badger census")
        assert len(found) == 1
        assert found[0].start_ms == 65_000

    def test_a_transcript_without_times_still_matches(self, tmp_path):
        """No timings is not a failure; it just cannot offer to play."""
        from podharvest.transcript_search import search_transcripts

        transcript = tmp_path / "ep.md"
        transcript.write_text("the badger census showed\n", encoding="utf-8")

        class Episode:
            show, title = "A Show", "Ep 1"

        episode = Episode()
        episode.transcript = transcript
        found = search_transcripts([episode], "badger")
        assert len(found) == 1
        assert found[0].start_ms is None

    def test_the_row_says_when_it_knows(self, tmp_path):
        from podharvest.transcript_search import EpisodeMatch

        class Episode:
            show, title = "A Show", "Ep 1"

        described = EpisodeMatch(
            episode=Episode(), count=1, snippet="...", start_ms=65_000).describe()
        assert "01:05" in described
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transcript_search.py -k CarryATime -q --no-header -p no:randomly`
Expected: FAIL — `TypeError: EpisodeMatch.__init__() got an unexpected keyword argument 'start_ms'`

- [ ] **Step 3: Write the implementation**

In `S:\code\pod\podharvest\transcript_search.py`, replace the `EpisodeMatch` dataclass and the body of `search_transcripts` that builds it:

```python
@dataclass
class EpisodeMatch:
    """One episode that contains the phrase, where it first appears, and when.

    `start_ms` is None when the transcript carries no timings at all -- an
    older run with timestamps switched off, or a publisher's plain-text
    transcript. The row then simply does not offer to play, rather than
    offering and landing at zero.
    """

    episode: object  # a library.LibraryEpisode
    count: int
    snippet: str
    start_ms: int | None = None

    def describe(self) -> str:
        times = "once" if self.count == 1 else f"{self.count} times"
        when = ""
        if self.start_ms is not None:
            total = self.start_ms // 1000
            hours, rem = divmod(total, 3600)
            minutes, seconds = divmod(rem, 60)
            stamp = (f"{hours}:{minutes:02d}:{seconds:02d}" if hours
                     else f"{minutes:02d}:{seconds:02d}")
            when = f" at {stamp}"
        return (f"{self.episode.show} - {self.episode.title} - {times}{when}: "
                f"...{self.snippet}...")
```

Then, inside `search_transcripts`, replace the `found.append(...)` call with:

```python
        # The timings are read only for transcripts that actually matched,
        # so a search across a large library does not open a sidecar for
        # every episode it rejects.
        from podharvest import timing_core

        timeline = timing_core.load_timeline(path)
        start_ms = None
        if not timeline.is_empty():
            # The match position is an offset into the file, which includes
            # the timestamp markers themselves; the timeline's own text has
            # them stripped. Re-find the phrase in the timeline's text so the
            # offsets agree.
            in_timeline = timeline.text().lower().find(needle)
            if in_timeline >= 0:
                start_ms = timeline.time_at_char(in_timeline)
        found.append(EpisodeMatch(
            episode=episode, count=count,
            snippet=_snippet(text, first, len(needle)),
            start_ms=start_ms))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_transcript_search.py -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 5: Carry the time back to the window**

In `S:\code\pod\podharvest\transcript_search.py`, in the dialog, wherever `self.chosen` is set from the selected row, set alongside it:

```python
        # The time travels with the choice, so the main window can cue the
        # player without searching the transcript a second time.
        self.chosen_ms = match.start_ms
```

Initialise `self.chosen_ms = None` in `__init__` beside `self.chosen`.

- [ ] **Step 6: Cue the player in the main window**

In `S:\code\pod\podharvest\gui.py`, in `_on_search_transcripts`, after the dialog returns a chosen episode and the reader is opened, add:

```python
        # Finding a phrase should end with hearing it. The episode is loaded
        # and cued but not played: starting audio unasked, over a screen
        # reader that is still speaking the row you chose, is startling.
        start_ms = getattr(dlg, "chosen_ms", None)
        if start_ms is not None and getattr(chosen, "has_audio", False):
            if self.player.load(chosen.audio):
                self._loaded_audio_title = chosen.title
                self._loaded_audio_path = chosen.audio
                self.player.seek_to(start_ms)
                self.now_playing.SetLabel(
                    f"Cued: {chosen.title} at the match")
                LOG.info("Cued '%s' at the match. Press Play or Ctrl+P to "
                         "hear it.", chosen.title)
```

- [ ] **Step 7: Run the full suite and the help audit**

Run: `python -m podharvest.help_audit && python -m pytest tests -q --no-header -p no:randomly`
Expected: help audit reports no missing controls; suite passes.

- [ ] **Step 8: Commit**

```bash
git add podharvest/transcript_search.py podharvest/gui.py tests/test_transcript_search.py
git commit -m "Searching a phrase now ends with the audio cued to it"
```

---

## Task 8: Play from here, in the reader

**Files:**
- Modify: `S:\code\pod\podharvest\reader.py`
- Test: `S:\code\pod\tests\test_reader.py` (create if absent)

**Interfaces:**
- Consumes: `load_timeline`.
- Produces: `TranscriptDialog(..., on_play_at: Callable[[int], None] | None = None)`; the dialog calls it with a millisecond position.

- [ ] **Step 1: Write the failing test**

Create or append to `S:\code\pod\tests\test_reader.py`:

```python
"""The reader, and the caret's position in the audio."""

from __future__ import annotations

import inspect

import pytest

wx = pytest.importorskip("wx")


class TestPlayFromHere:
    def test_the_dialog_accepts_a_play_handler(self):
        from podharvest.reader import TranscriptDialog

        signature = inspect.signature(TranscriptDialog.__init__)
        assert "on_play_at" in signature.parameters

    def test_it_asks_the_timeline_where_the_caret_is(self):
        from podharvest.reader import TranscriptDialog

        source = inspect.getsource(TranscriptDialog)
        assert "load_timeline" in source
        assert "time_at_char" in source

    def test_the_shortcut_is_documented_on_the_control(self):
        """A keystroke nobody can discover is not a feature."""
        from podharvest.reader import TranscriptDialog

        source = inspect.getsource(TranscriptDialog)
        assert "Ctrl+Enter" in source or "Control+Enter" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reader.py -q --no-header -p no:randomly`
Expected: FAIL — `on_play_at` is not a parameter.

- [ ] **Step 3: Write the implementation**

In `S:\code\pod\podharvest\reader.py`:

Add `on_play_at` to `__init__`'s keyword arguments and store it:

```python
        # Given by the main window so the reader can start playback without
        # knowing anything about the transport. None in the editor's preview,
        # where there is no player to talk to.
        self._on_play_at = on_play_at
        # Read once when the transcript is loaded: a reader is opened and
        # then arrowed through, so the cost belongs at the front.
        self._timeline = None
```

After the transcript text is loaded into `self.text`, add:

```python
        from podharvest import timing_core

        self._timeline = timing_core.load_timeline(self.path)
```

Add a button beside Find, created after its label as the alignment rule
requires:

```python
        self.play_here_btn = wx.Button(self, label="Play from &here")
        self.play_here_btn.SetToolTip(
            "Plays the episode from the point in the audio where the caret "
            "is. Control+Enter does the same from inside the transcript. "
            "Unavailable when this transcript has no timings in it."
        )
        self.play_here_btn.Bind(wx.EVT_BUTTON, lambda _e: self._play_from_caret())
```

Bind the shortcut on the text control:

```python
        self.text.Bind(wx.EVT_KEY_DOWN, self._on_text_key)
```

And add:

```python
    def _on_text_key(self, event) -> None:
        """Control+Enter plays from the caret; everything else is the box's."""
        if (event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and event.ControlDown()):
            self._play_from_caret()
            return
        event.Skip()

    def _play_from_caret(self) -> None:
        """Start the audio at whatever the caret is sitting on.

        Says what it did in the status line rather than silently seeking:
        moving a playhead is invisible, and an announcement is the only way
        somebody knows it worked.
        """
        if self._on_play_at is None or self._timeline is None:
            return
        if self._timeline.is_empty():
            self.find_status.SetLabel(
                "This transcript has no timings in it, so there is nothing "
                "to play from. Transcripts made by podHarvest with timestamps "
                "switched on do have them.")
            return
        position = self.text.GetInsertionPoint()
        # The box shows the file, which includes the timestamp markers; the
        # timeline's text has them stripped. Map through the line the caret
        # is on rather than trusting the two offsets to agree.
        line_no = len(self.text.GetValue()[:position].splitlines()) - 1
        stripped = self._timeline.text().splitlines()
        if 0 <= line_no < len(stripped):
            offset = sum(len(s) + 1 for s in stripped[:line_no])
        else:
            offset = 0
        when = self._timeline.time_at_char(offset)
        if when is None:
            self.find_status.SetLabel("There is no timing for this part.")
            return
        self._on_play_at(when)
        self.find_status.SetLabel(f"Playing from {_spoken_time(when)}.")
```

Add the helper at module level:

```python
def _spoken_time(ms: int) -> str:
    """A position read aloud: "1 minute 5 seconds", not "00:01:05.000"."""
    total = max(0, ms) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    parts.append(f"{seconds} second" + ("s" if seconds != 1 else ""))
    return " ".join(parts)
```

The reader already has `self.find_status` (`reader.py:72`), a `wx.StaticText`
beside the Find box with the accessible name "Search result". Reuse it rather
than adding a second status line — two places that report are two places to
look. Widen its accessible name to "Reader status" as part of this task, since
it now reports more than searching:

```python
        set_accessible_name(self.find_status, "Reader status")
```

- [ ] **Step 4: Pass the handler from the main window**

In `S:\code\pod\podharvest\gui.py`, both places that construct
`TranscriptDialog` (`_on_read_transcript`, and the local-file branch above
it), add:

```python
            on_play_at=self._play_episode_at,
```

And add the method to `MainFrame`:

```python
    def _play_episode_at(self, ms: int) -> None:
        """Play the loaded episode from *ms*, loading it first if needed."""
        if self._loaded_audio_path is None:
            self._on_play_selected()
        if self._loaded_audio_path is None:
            LOG.info("There is no audio for this episode to play.")
            return
        self.player.seek_to(ms)
        self.player.play()
```

- [ ] **Step 5: Run tests and the help audit**

Run: `python -m podharvest.help_audit --write && python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS. Review the `help_inventory.json` diff — it should show only the new button.

- [ ] **Step 6: Commit**

```bash
git add podharvest/reader.py podharvest/gui.py tests/test_reader.py tests/help_inventory.json
git commit -m "Play the episode from wherever the caret is in its transcript"
```

---

## Task 9: Follow-along reading, opt-in

**Files:**
- Modify: `S:\code\pod\podharvest\config.py`
- Modify: `S:\code\pod\podharvest\reader.py`
- Modify: `S:\code\pod\podharvest\gui.py` (Settings dialog)
- Test: `S:\code\pod\tests\test_reader.py`

**Interfaces:**
- Consumes: `Timeline`, the player's `playhead_ms()`.
- Produces: `Settings.follow_along: bool = False`.

> **Constraint, from the maintainer:** this is opt-in only and must never be
> the default experience. It ships off. The setting is the only way it turns
> on, and turning it off must stop it immediately.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_reader.py`:

```python
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

    def test_the_reader_checks_the_setting_before_following(self):
        import inspect

        from podharvest.reader import TranscriptDialog

        source = inspect.getsource(TranscriptDialog)
        assert "follow_along" in source, (
            "following must be gated on the setting, not on whether a "
            "timeline happens to exist")

    def test_the_settings_dialog_offers_it(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.SettingsDialog)
        assert "follow" in source.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reader.py -k FollowAlong -q --no-header -p no:randomly`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'follow_along'`

- [ ] **Step 3: Add the setting**

In `S:\code\pod\podharvest\config.py`, add to `Settings` beside the other
playback fields:

```python
    #: Move the reader's caret to keep pace with playback. Off by default
    #: and deliberately so: a caret that moves on its own takes the text
    #: out from under somebody who is reading it at their own pace, and for
    #: a screen reader user that is not a nicety but a loss of control.
    #: Only ever turned on from Settings.
    follow_along: bool = False
```

Nothing else is needed for persistence: `Settings.to_dict` is `asdict(self)`
and `from_dict` keeps every key matching a dataclass field, so a new field
round-trips as soon as it is declared. Only add to `from_dict`'s body when a
value needs *validating* — as `source_mode` does, and a bool does not.

- [ ] **Step 4: Implement following in the reader**

In `S:\code\pod\podharvest\reader.py`, add to `__init__` after the timeline
is loaded:

```python
        # Following is off unless the setting says otherwise. The timer is
        # not even created when it is off, so there is nothing running to
        # forget to stop.
        self._follow_timer = None
        if follow_along and self._timeline is not None and not self._timeline.is_empty():
            self._follow_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda _e: self._follow_playhead(),
                      self._follow_timer)
            self._follow_timer.Start(FOLLOW_TICK_MS)
```

Add `follow_along: bool = False` and `playhead: Callable[[], int] | None = None`
to the constructor's keyword arguments, and at module level:

```python
#: How often the caret checks where playback has got to. Twice a second:
#: often enough that the caret is never a sentence behind, rare enough that
#: a screen reader is not interrupted mid-word by a selection change.
FOLLOW_TICK_MS = 500
```

Add the method:

```python
    def _follow_playhead(self) -> None:
        """Move the caret to the sentence being spoken, and no further.

        Only the caret moves, and only when the sentence changes. Selecting
        the text would make a screen reader re-read it on every tick, and
        moving on every tick would fight anybody scrolling back to reread
        something.
        """
        if self._playhead is None or self._timeline is None:
            return
        where = self._playhead()
        span = self._timeline.char_span_for_range(where, where + 1)
        if span is None:
            return
        start, _end = span
        if start == self._last_follow_offset:
            return
        self._last_follow_offset = start
        self.text.SetInsertionPoint(start)
        self.text.ShowPosition(start)
```

Initialise `self._last_follow_offset = -1` and `self._playhead = playhead`
in `__init__`, and stop the timer on close:

```python
    def _on_close(self, event) -> None:
        if self._follow_timer is not None:
            self._follow_timer.Stop()
        event.Skip()
```

Bind `self.Bind(wx.EVT_CLOSE, self._on_close)` in `__init__`.

- [ ] **Step 5: Pass it from the main window**

In `S:\code\pod\podharvest\gui.py`, at both `TranscriptDialog` construction
sites, add:

```python
            follow_along=self.settings.follow_along,
            playhead=self.player.playhead_ms,
```

- [ ] **Step 6: Offer it in Settings**

In `S:\code\pod\podharvest\gui.py`, in `SettingsDialog._build_playback_settings`,
add after the remember-position checkbox:

```python
        self.chk_follow_along = wx.CheckBox(
            holder, label="Move the &transcript caret to follow playback")
        self.chk_follow_along.SetValue(self.settings.follow_along)
        self.chk_follow_along.SetToolTip(
            "Off by default. With this on, opening a transcript while an "
            "episode plays moves the caret to the sentence being spoken, so "
            "you can read along. Only the caret moves and only when the "
            "sentence changes, so it does not interrupt you mid-word. Turn "
            "it off to read at your own pace."
        )
        box.Add(self.chk_follow_along, 0, wx.ALL, 6)
```

And in the method that saves settings from the dialog:

```python
        settings.follow_along = self.chk_follow_along.GetValue()
```

- [ ] **Step 7: Run tests and the help audit**

Run: `python -m podharvest.help_audit --write && python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add podharvest/config.py podharvest/reader.py podharvest/gui.py tests/test_reader.py tests/help_inventory.json
git commit -m "Follow the playhead in the transcript, only when asked to"
```

---

## Task 10: Clip export

**Files:**
- Create: `S:\code\pod\podharvest\clips.py`
- Create: `S:\code\pod\tests\test_clips.py`
- Modify: `S:\code\pod\podharvest\reader.py`

**Interfaces:**
- Consumes: `Timeline`, `media_health` for the ffmpeg check.
- Produces: `build_clip_command(source, destination, start_ms, end_ms, fade_ms=120) -> list[str]`, `clip_filename(title, text) -> str`, `export_clip(...) -> Path`.

- [ ] **Step 1: Write the failing test**

Create `S:\code\pod\tests\test_clips.py`:

```python
"""Cutting a passage out of an episode by reading rather than by scrubbing."""

from __future__ import annotations

from pathlib import Path

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
        assert "5.000" in command[command.index("-t") + 1]

    def test_it_fades_both_ends(self):
        """A clip that starts mid-syllable at full volume sounds broken."""
        command = build_clip_command(
            Path("in.mp3"), Path("out.mp3"), 0, 10_000, fade_ms=120)
        filters = command[command.index("-af") + 1]
        assert "afade=t=in" in filters and "afade=t=out" in filters

    def test_a_backwards_span_is_refused(self):
        import pytest

        with pytest.raises(ValueError):
            build_clip_command(Path("in.mp3"), Path("out.mp3"), 5000, 1000)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_clips.py -q --no-header -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: No module named 'podharvest.clips'`

- [ ] **Step 3: Write the implementation**

Create `S:\code\pod\podharvest\clips.py`:

```python
"""Cutting a passage out of an episode, by reading rather than by scrubbing.

The usual way to make a clip is to drag across a waveform, which is no way
at all if you cannot see one. Here the selection is made in the transcript --
the text you can read, search and arrow through -- and the audio follows
from the timings.

Re-encoding rather than stream-copying is deliberate: a copy can only cut on
a keyframe, so the clip would start up to several seconds away from the word
you chose, which is exactly the precision this feature exists to provide.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from podharvest.util import LOG

#: Fade applied to both ends, in milliseconds. Short enough not to swallow a
#: word, long enough that the clip does not begin with a click.
DEFAULT_FADE_MS = 120

#: The longest a generated filename may be, before the extension. Windows
#: still has a path ceiling and a clip is often saved somewhere deep.
MAX_NAME_CHARS = 90


def build_clip_command(source: Path, destination: Path, start_ms: int,
                       end_ms: int, fade_ms: int = DEFAULT_FADE_MS) -> list[str]:
    """The ffmpeg command that cuts *start_ms* to *end_ms* out of *source*.

    Built as a list and never a string: a show title with a quote in it
    would otherwise end the argument and the rest would be read as flags.
    """
    if end_ms <= start_ms:
        raise ValueError("A clip must end after it starts.")
    duration = (end_ms - start_ms) / 1000.0
    fade = max(0, min(fade_ms, (end_ms - start_ms) // 4)) / 1000.0
    filters = (f"afade=t=in:st=0:d={fade:.3f},"
               f"afade=t=out:st={duration - fade:.3f}:d={fade:.3f}")
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        # -ss before -i: ffmpeg seeks to the point instead of decoding up to
        # it, which is the difference between instant and a minute.
        "-ss", f"{start_ms / 1000.0:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-af", filters,
        str(destination),
    ]


def clip_filename(episode_title: str, said: str) -> str:
    """A filename made of the words that were said.

    "the badger census showed" is findable six months later; "clip_003" is
    not. The episode title leads so clips from one show sort together.
    """
    words = re.sub(r"\s+", " ", said or "").strip()
    stem = f"{episode_title} - {words}" if words else episode_title
    stem = re.sub(r'[\\/:*?"<>|]', "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if len(stem) > MAX_NAME_CHARS:
        stem = stem[:MAX_NAME_CHARS].rsplit(" ", 1)[0]
    return f"{stem or 'clip'}.mp3"


def export_clip(source: Path, destination: Path, start_ms: int, end_ms: int,
                fade_ms: int = DEFAULT_FADE_MS) -> Path:
    """Write the clip. Raises RuntimeError with what ffmpeg said on failure."""
    command = build_clip_command(source, destination, start_ms, end_ms, fade_ms)
    LOG.info("Writing a clip of %.1f seconds to %s.",
             (end_ms - start_ms) / 1000.0, destination.name)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg could not write that clip.\n"
            + (result.stderr or "").strip()[-800:])
    return destination
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_clips.py -q --no-header -p no:randomly`
Expected: PASS, 7 tests.

- [ ] **Step 5: Add the reader action**

In `S:\code\pod\podharvest\reader.py`, add a button beside "Play from here":

```python
        self.clip_btn = wx.Button(self, label="Save as a &clip...")
        self.clip_btn.SetToolTip(
            "Saves the audio for the text you have selected as its own file, "
            "with a short fade at each end and a name made from the words "
            "that were said. Select some transcript first. Needs FFmpeg."
        )
        self.clip_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_save_clip())
```

And the handler:

```python
    def _on_save_clip(self) -> None:
        """Turn the selected text into an audio file."""
        from podharvest import clips, media_health

        if self._timeline is None or self._timeline.is_empty():
            self.find_status.SetLabel(
                "This transcript has no timings in it, so a clip cannot be "
                "cut from it.")
            return
        if self._audio_path is None:
            self.find_status.SetLabel("There is no audio file for this episode.")
            return
        health = media_health.check()
        if not health.healthy:
            self.find_status.SetLabel(
                "Saving a clip needs FFmpeg, which is not installed. "
                "Help then Media tools says how to get it.")
            return
        first, last = self.text.GetSelection()
        if first == last:
            self.find_status.SetLabel(
                "Select the part of the transcript you want as a clip first.")
            return
        said = self.text.GetValue()[first:last]
        stripped = self._timeline.text()
        needle = re.sub(r"\s+", " ", said).strip()
        position = re.sub(r"\s+", " ", stripped).find(needle)
        if position < 0:
            self.find_status.SetLabel(
                "That selection could not be matched to the timings. Try "
                "selecting whole sentences.")
            return
        start = self._timeline.time_at_char(position)
        end = self._timeline.time_at_char(position + len(needle))
        if start is None or end is None or end <= start:
            self.find_status.SetLabel("There is no timing for that selection.")
            return
        suggested = clips.clip_filename(self._episode_title or self.path.stem, needle)
        with wx.FileDialog(
            self, "Save this passage as a clip", defaultFile=suggested,
            wildcard="Audio (*.mp3)|*.mp3|All files|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            destination = Path(dlg.GetPath())
        try:
            clips.export_clip(self._audio_path, destination, start, end)
        except (RuntimeError, ValueError, OSError) as exc:
            self.find_status.SetLabel(f"That clip could not be written: {exc}")
            return
        self.find_status.SetLabel(f"Saved {destination.name}.")
```

Add `audio_path: Path | None = None` and `episode_title: str = ""` to the
constructor's keyword arguments, stored as `self._audio_path` and
`self._episode_title`, and pass them from `gui.py` at both construction
sites (`audio_path=episode.audio` / `local.path`, `episode_title=...`).

- [ ] **Step 6: Run tests and the help audit**

Run: `python -m podharvest.help_audit --write && python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add podharvest/clips.py podharvest/reader.py podharvest/gui.py tests/test_clips.py tests/help_inventory.json
git commit -m "Save a passage of an episode as a clip, chosen by reading it"
```

---

## Task 11: Place a chapter by phrase

**Files:**
- Modify: `S:\code\pod\podharvest\editor.py` (`ChapterPage`)
- Test: `S:\code\pod\tests\test_editor.py`

**Interfaces:**
- Consumes: `load_timeline`.
- Produces: a "Find a phrase" control on the chapter page that places a marker at the matched word's time.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_editor.py`:

```python
class TestChaptersByPhrase:
    """Placing a marker by what was said, not only by ear.

    Nudging by ear stays -- it is the right tool for fine work. This is for
    the coarse move that precedes it: get within a word of the right place
    in one action, then nudge.
    """

    def test_the_page_offers_a_phrase_search(self):
        import inspect

        from podharvest.editor import ChapterPage

        source = inspect.getsource(ChapterPage)
        assert "phrase" in source.lower()
        assert "load_timeline" in source

    def test_it_says_when_there_are_no_timings(self):
        import inspect

        from podharvest.editor import ChapterPage

        source = inspect.getsource(ChapterPage)
        assert "no timings" in source.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_editor.py -k ByPhrase -q --no-header -p no:randomly`
Expected: FAIL.

- [ ] **Step 3: Write the implementation**

In `S:\code\pod\podharvest\editor.py`, in `ChapterPage.__init__`, add a row
after the chapter list, label first:

```python
        phrase_row = wx.BoxSizer(wx.HORIZONTAL)
        phrase_row.Add(wx.StaticText(self, label="Find a &phrase:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.phrase_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.phrase_ctrl.SetToolTip(
            "Type words from the transcript and press Enter to move the "
            "playhead to where they were said. Add chapter puts a marker "
            "there. Quicker than nudging when the marker is a long way from "
            "where it should be; nudging is still the way to get it exact."
        )
        self.phrase_ctrl.SetHint("words from the transcript")
        set_accessible_name(self.phrase_ctrl, "Find a phrase")
        self.phrase_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda _e: self._on_find_phrase())
        phrase_row.Add(self.phrase_ctrl, 1, wx.RIGHT, 6)

        find_phrase_btn = wx.Button(self, label="&Go to it")
        find_phrase_btn.SetToolTip(
            "Moves the playhead to where that phrase was said.")
        find_phrase_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_find_phrase())
        phrase_row.Add(find_phrase_btn, 0)
        root.Add(phrase_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
```

And the handler:

```python
    def _on_find_phrase(self) -> None:
        """Move the playhead to where a phrase was said."""
        from podharvest import timing_core

        needle = self.phrase_ctrl.GetValue().strip().lower()
        if not needle:
            return
        if self._timeline is None:
            self._timeline = (timing_core.load_timeline(self._transcript_path)
                              if self._transcript_path else
                              timing_core.Timeline(segments=(), source="none"))
        if self._timeline.is_empty():
            self._announce(
                "This episode has no timings, so a phrase cannot be found in "
                "it. Transcribe it with timestamps switched on and the "
                "phrase search will work.")
            return
        position = self._timeline.text().lower().find(needle)
        if position < 0:
            self._announce(f"'{needle}' is not in this transcript.")
            return
        when = self._timeline.time_at_char(position)
        if when is None:
            self._announce("There is no timing for that phrase.")
            return
        self.player.seek_to(when)
        self._announce(f"Moved to {format_time_precise(when)}. "
                       "Add chapter puts a marker here.")
```

Initialise `self._timeline = None` in `__init__`, and add a
`transcript_path: Path | None = None` keyword argument stored as
`self._transcript_path`. Pass it from `EditorDialog` where the chapter page
is constructed, resolving it the same way `_on_read_transcript` does in
`gui.py` — or `None` when no transcript is found.

- [ ] **Step 4: Run tests and the help audit**

Run: `python -m podharvest.help_audit --write && python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add podharvest/editor.py tests/test_editor.py tests/help_inventory.json
git commit -m "Place a chapter marker by the words that were said"
```

---

## Task 12: `announce.py` — the bridge

**Files:**
- Create: `S:\code\pod\podharvest\announce.py`
- Create: `S:\code\pod\tests\test_announce.py`
- Modify: `S:\code\pod\podharvest\acquire.py`

**Interfaces:**
- Consumes: `acquire` for on-demand installation.
- Produces: `is_available() -> bool`, `ensure_installed(app_space) -> bool`, `speak(text: str, *, interrupt: bool = False) -> bool`, `braille(text: str) -> bool`, `say(text, *, category, settings) -> None`.

- [ ] **Step 1: Write the failing test**

Create `S:\code\pod\tests\test_announce.py`:

```python
"""Giving a run a voice, without breaking the no-dependencies promise."""

from __future__ import annotations

from podharvest import announce


class TestItIsSafeWithoutTheComponent:
    """Nothing here may raise, ever. An app that crashes because a screen
    reader is not running is worse than one that says nothing."""

    def test_speaking_without_the_component_returns_false(self, monkeypatch):
        monkeypatch.setattr(announce, "_output", lambda: None)
        assert announce.speak("hello") is False

    def test_brailling_without_the_component_returns_false(self, monkeypatch):
        monkeypatch.setattr(announce, "_output", lambda: None)
        assert announce.braille("hello") is False

    def test_availability_is_answerable_without_installing_anything(self):
        assert isinstance(announce.is_available(), bool)


class TestCategories:
    def test_a_category_that_is_off_says_nothing(self, monkeypatch):
        spoken = []
        monkeypatch.setattr(announce, "speak",
                            lambda text, **_k: spoken.append(text) or True)

        class Settings:
            announce_completions = False
            announce_progress = False
            announce_errors = True
            announce_braille = False

        announce.say("done", category="completions", settings=Settings())
        assert spoken == []

    def test_a_category_that_is_on_speaks(self, monkeypatch):
        spoken = []
        monkeypatch.setattr(announce, "speak",
                            lambda text, **_k: spoken.append(text) or True)

        class Settings:
            announce_completions = True
            announce_progress = False
            announce_errors = True
            announce_braille = False

        announce.say("done", category="completions", settings=Settings())
        assert spoken == ["done"]

    def test_an_unknown_category_is_ignored_rather_than_spoken(self, monkeypatch):
        spoken = []
        monkeypatch.setattr(announce, "speak",
                            lambda text, **_k: spoken.append(text) or True)

        class Settings:
            announce_completions = True
            announce_progress = True
            announce_errors = True
            announce_braille = False

        announce.say("hm", category="nonsense", settings=Settings())
        assert spoken == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_announce.py -q --no-header -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: No module named 'podharvest.announce'`

- [ ] **Step 3: Write the implementation**

Create `S:\code\pod\podharvest\announce.py`:

```python
"""Saying out loud what a run is doing.

podHarvest's oldest and worst limitation is that the activity log cannot
announce itself. wxWidgets exposes MSAA only: it has no live-region API on
any platform, ships no UI Automation provider, and cannot raise a UIA
notification. Appending to a read-only text control fires a value-change
event that NVDA, JAWS and Narrator all deliberately ignore for a control
without focus. So a run can finish, or fail, in silence.

The fix is to stop asking the toolkit and talk to the screen reader
directly. `accessible_output2` does that -- NVDA and JAWS through their own
controller libraries, SAPI as a fallback when neither is running -- and it
speaks braille through the same interface.

Three rules hold this together:

**Nothing here may raise.** Every entry point returns a bool and swallows
its own failures. An app that crashes because a screen reader was restarted
mid-run is worse than one that goes quiet.

**Nothing is installed without being asked.** The component arrives through
`acquire`, into the app space, on first use, with the user's consent.
Without it every function returns False and the Settings box says why.

**Nothing speaks unless it was turned on.** Announcements are off by
default and chosen per category, because an app that talks over you is a
worse companion than one that stays quiet.
"""

from __future__ import annotations

from podharvest.util import LOG

#: The package that does the talking, and roughly how large it is, for the
#: sentence that asks permission to fetch it.
PACKAGE = "accessible_output2"
APPROXIMATE_MB = 2

#: Which settings flag governs which kind of message. A category not in here
#: is never spoken -- a typo in a call site should be silence, not a
#: surprise announcement.
CATEGORIES = {
    "completions": "announce_completions",
    "progress": "announce_progress",
    "errors": "announce_errors",
}

_cached_output = None
_looked_for_output = False


def _output():
    """The speech object, or None. Imported once, lazily, never at start-up.

    Importing at module scope would make an optional component a hard
    dependency of the module, which is exactly what `dependencies = []`
    forbids.
    """
    global _cached_output, _looked_for_output
    if _looked_for_output:
        return _cached_output
    _looked_for_output = True
    try:
        import accessible_output2.outputs.auto

        _cached_output = accessible_output2.outputs.auto.Auto()
    except Exception as exc:  # noqa: BLE001 - any failure means "no speech"
        LOG.debug("Spoken announcements are not available: %s", exc)
        _cached_output = None
    return _cached_output


def is_available() -> bool:
    """Whether anything can be spoken right now."""
    return _output() is not None


def forget() -> None:
    """Drop the cached speech object, so the next call looks again.

    Called after installing the component, so it becomes usable without a
    restart.
    """
    global _cached_output, _looked_for_output
    _cached_output = None
    _looked_for_output = False


def ensure_installed(app_space) -> bool:
    """Install the speech component into the app space. True when ready."""
    if is_available():
        return True
    from podharvest import acquire

    # `ensure_package` takes the pip name and the import name separately,
    # because they differ for plenty of packages. Here they are the same.
    if not acquire.ensure_package(app_space, PACKAGE, PACKAGE):
        return False
    forget()
    return is_available()


def speak(text: str, *, interrupt: bool = False) -> bool:
    """Say *text*. False when nothing could say it.

    *interrupt* cuts off whatever is being spoken, which is right for an
    error and wrong for a progress note.
    """
    output = _output()
    if output is None or not text:
        return False
    try:
        output.output(text, interrupt=interrupt)
        return True
    except Exception as exc:  # noqa: BLE001 - a reader that went away
        LOG.debug("Could not speak: %s", exc)
        return False


def braille(text: str) -> bool:
    """Send *text* to a braille display. False when nothing could."""
    output = _output()
    if output is None or not text:
        return False
    try:
        output.braille(text)
        return True
    except Exception as exc:  # noqa: BLE001 - not every output does braille
        LOG.debug("Could not braille: %s", exc)
        return False


def say(text: str, *, category: str, settings) -> None:
    """Announce *text* if this category is turned on. Never raises.

    This is what the rest of the app calls. It is deliberately a no-op in
    every uncertain case: an unknown category, a missing setting, no
    component installed.
    """
    flag = CATEGORIES.get(category)
    if flag is None:
        return
    if not getattr(settings, flag, False):
        return
    spoke = speak(text, interrupt=(category == "errors"))
    if spoke and getattr(settings, "announce_braille", False):
        braille(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_announce.py -q --no-header -p no:randomly`
Expected: PASS, 6 tests.

- [ ] **Step 5: Confirm the acquire call matches**

`acquire.ensure_package(app, pip_name, import_name) -> bool` is at
`podharvest/acquire.py:423`. It calls `app.activate()`, tries the import,
and installs into `app.python_packages_dir` only when that fails — which is
exactly the contract needed here. Do not add a second mechanism.

- [ ] **Step 6: Commit**

```bash
git add podharvest/announce.py tests/test_announce.py
git commit -m "Add a speech and braille bridge that stays silent until asked"
```

---

## Task 13: Announcements wired into runs

**Files:**
- Modify: `S:\code\pod\podharvest\config.py`
- Modify: `S:\code\pod\podharvest\gui.py`
- Test: `S:\code\pod\tests\test_announce.py`

**Interfaces:**
- Consumes: `announce.say`.
- Produces: `Settings.announce_completions`, `.announce_progress`, `.announce_errors`, `.announce_braille`, all `False` by default.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_announce.py`:

```python
class TestTheSettings:
    def test_every_announcement_setting_defaults_to_off(self):
        from podharvest.config import Settings

        settings = Settings()
        assert settings.announce_completions is False
        assert settings.announce_progress is False
        assert settings.announce_errors is False
        assert settings.announce_braille is False

    def test_they_survive_a_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.announce_errors = True
        settings.announce_braille = True
        restored = Settings.from_dict(settings.to_dict())
        assert restored.announce_errors is True
        assert restored.announce_braille is True

    def test_the_window_announces_a_finished_run(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.MainFrame)
        assert "announce" in source
        assert 'category="completions"' in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_announce.py -k Settings -q --no-header -p no:randomly`
Expected: FAIL — `AttributeError: announce_completions`

- [ ] **Step 3: Add the settings**

In `S:\code\pod\podharvest\config.py`, add to `Settings`:

```python
    #: Spoken announcements, per kind of message, all off until asked for.
    #: An app that talks over you is a worse companion than a quiet one, so
    #: nothing here is on by default and each is chosen separately.
    announce_completions: bool = False
    announce_progress: bool = False
    announce_errors: bool = False
    #: Send the same messages to a braille display as well as speaking them.
    announce_braille: bool = False
```

No persistence work is needed — see the note in Task 9. `asdict` picks them
up automatically.

- [ ] **Step 4: Announce the things worth announcing**

In `S:\code\pod\podharvest\gui.py`:

At the point a run finishes (where the finished dialog is shown or the
final log line is written), add:

```python
        from podharvest import announce

        announce.say(finished_message, category="completions",
                     settings=self.settings)
```

Where an episode finishes inside a run, add:

```python
        announce.say(f"{done} of {total} finished.", category="progress",
                     settings=self.settings)
```

Where a run fails, add:

```python
        announce.say(f"The run stopped: {reason}", category="errors",
                     settings=self.settings)
```

- [ ] **Step 5: Offer them in Settings**

In `SettingsDialog`, add a new `wx.StaticBoxSizer` titled "Announcements",
placed before the Finished box:

```python
        ann_box = wx.StaticBoxSizer(wx.VERTICAL, self._content, "Announcements")
        aholder = ann_box.GetStaticBox()
        note = wx.StaticText(
            aholder,
            label="podHarvest cannot make the activity log announce itself --\n"
                  "wxWidgets has no way to do that. These speak instead.")
        ann_box.Add(note, 0, wx.ALL, 6)

        self.chk_ann_completions = wx.CheckBox(
            aholder, label="Speak when an episode or a &run finishes")
        self.chk_ann_completions.SetValue(settings.announce_completions)
        self.chk_ann_completions.SetToolTip(
            "Says so out loud when a run ends, so you do not have to watch "
            "for it. Off by default.")
        ann_box.Add(self.chk_ann_completions, 0, wx.ALL, 6)

        self.chk_ann_progress = wx.CheckBox(
            aholder, label="Speak &progress as a run goes along")
        self.chk_ann_progress.SetValue(settings.announce_progress)
        self.chk_ann_progress.SetToolTip(
            "Says how far through a run is as each episode finishes. Useful "
            "on a long run, chatty on a short one. Off by default.")
        ann_box.Add(self.chk_ann_progress, 0, wx.ALL, 6)

        self.chk_ann_errors = wx.CheckBox(
            aholder, label="Speak &errors and warnings")
        self.chk_ann_errors.SetValue(settings.announce_errors)
        self.chk_ann_errors.SetToolTip(
            "Says so when something goes wrong, interrupting whatever is "
            "being read. The one worth turning on first. Off by default.")
        ann_box.Add(self.chk_ann_errors, 0, wx.ALL, 6)

        self.chk_ann_braille = wx.CheckBox(
            aholder, label="Send the same to a &braille display")
        self.chk_ann_braille.SetValue(settings.announce_braille)
        self.chk_ann_braille.SetToolTip(
            "Also sends each announcement to a braille display, through "
            "whichever screen reader is running. Harmless with no display "
            "connected. Off by default.")
        ann_box.Add(self.chk_ann_braille, 0, wx.ALL, 6)

        self.ann_status = wx.StaticText(aholder, label="")
        set_accessible_name(self.ann_status, "Announcement component status")
        ann_box.Add(self.ann_status, 0, wx.ALL, 6)

        self.ann_install_btn = wx.Button(aholder, label="&Set up announcements")
        self.ann_install_btn.SetToolTip(
            f"Downloads the small component ({APPROXIMATE_MB} MB) that lets "
            "podHarvest speak, into podHarvest's own folder. Nothing is "
            "installed into your system Python.")
        self.ann_install_btn.Bind(wx.EVT_BUTTON, self._on_install_announcer)
        ann_box.Add(self.ann_install_btn, 0, wx.ALL, 6)
        outer.Add(ann_box, 0, wx.EXPAND | wx.ALL, 10)
```

Import `APPROXIMATE_MB` from `podharvest.announce` at the top of the method,
and add:

```python
    def _on_install_announcer(self, _evt) -> None:
        """Fetch the speech component, and say whether it worked."""
        from podharvest import announce

        self.ann_install_btn.Disable()
        self.ann_status.SetLabel("Setting up...")
        wx.Yield()
        ready = announce.ensure_installed(self.app)
        self.ann_status.SetLabel(
            "Ready. Announcements will be spoken." if ready else
            "Could not set that up. The activity log has the details.")
        self.ann_install_btn.Enable(not ready)
        if ready:
            announce.speak("Announcements are ready.")

    def _sync_announcement_status(self) -> None:
        """Say whether announcements can work, before anything is ticked."""
        from podharvest import announce

        ready = announce.is_available()
        self.ann_status.SetLabel(
            "Ready. Announcements will be spoken." if ready else
            "Not set up yet. The boxes above do nothing until you press "
            "Set up announcements.")
        self.ann_install_btn.Enable(not ready)
```

Call `self._sync_announcement_status()` at the end of `__init__`, beside the
existing `_on_toggle_log(None)` calls. Save the four values in the settings-
saving method.

- [ ] **Step 6: Run tests and the help audit**

Run: `python -m podharvest.help_audit --write && python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add podharvest/config.py podharvest/gui.py tests/test_announce.py tests/help_inventory.json
git commit -m "Let a run say what it is doing, when asked to"
```

---

## Task 14: Braille output verified

**Files:**
- Modify: `S:\code\pod\podharvest\announce.py`
- Test: `S:\code\pod\tests\test_announce.py`

**Interfaces:** no new public names.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_announce.py`:

```python
class TestBrailleIsSeparate:
    """Braille follows speech but is its own choice."""

    def test_braille_is_not_sent_when_its_box_is_off(self, monkeypatch):
        brailled = []
        monkeypatch.setattr(announce, "speak", lambda text, **_k: True)
        monkeypatch.setattr(announce, "braille",
                            lambda text: brailled.append(text) or True)

        class Settings:
            announce_completions = True
            announce_progress = False
            announce_errors = False
            announce_braille = False

        announce.say("done", category="completions", settings=Settings())
        assert brailled == []

    def test_braille_is_sent_when_its_box_is_on(self, monkeypatch):
        brailled = []
        monkeypatch.setattr(announce, "speak", lambda text, **_k: True)
        monkeypatch.setattr(announce, "braille",
                            lambda text: brailled.append(text) or True)

        class Settings:
            announce_completions = True
            announce_progress = False
            announce_errors = False
            announce_braille = True

        announce.say("done", category="completions", settings=Settings())
        assert brailled == ["done"]

    def test_braille_is_not_attempted_when_speech_failed(self, monkeypatch):
        """No speech means no screen reader, which means no braille either."""
        brailled = []
        monkeypatch.setattr(announce, "speak", lambda text, **_k: False)
        monkeypatch.setattr(announce, "braille",
                            lambda text: brailled.append(text) or True)

        class Settings:
            announce_completions = True
            announce_progress = False
            announce_errors = False
            announce_braille = True

        announce.say("done", category="completions", settings=Settings())
        assert brailled == []
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_announce.py -q --no-header -p no:randomly`
Expected: PASS — Task 12's `say` already implements this. If any fail, fix
`say` rather than the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_announce.py
git commit -m "Hold the rule that braille follows speech but is chosen separately"
```

---

## Task 15: Ask-once-per-launch favourites check

**Files:**
- Modify: `S:\code\pod\podharvest\config.py`
- Modify: `S:\code\pod\podharvest\gui.py`
- Test: `S:\code\pod\tests\test_freshness.py`

**Interfaces:**
- Produces: `Settings.ask_to_check_favourites: bool = True`, `Settings.favourites_checked_at: str = ""`.

- [ ] **Step 1: Write the failing test**

Append to `S:\code\pod\tests\test_freshness.py`:

```python
class TestTheLaunchPrompt:
    """One refusable question, and nothing that runs on its own."""

    def test_asking_is_on_by_default_but_checking_is_not_automatic(self):
        from podharvest.config import Settings

        settings = Settings()
        assert settings.ask_to_check_favourites is True

    def test_stop_asking_is_remembered(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.ask_to_check_favourites = False
        restored = Settings.from_dict(settings.to_dict())
        assert restored.ask_to_check_favourites is False

    def test_nothing_schedules_or_downloads(self):
        """The promise the docs make, held by a test."""
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._maybe_offer_favourites_check)
        for forbidden in ("Timer", "schedule", "download", "_start_harvest"):
            assert forbidden not in source, (
                f"the launch prompt must not {forbidden}")

    def test_it_does_not_ask_when_there_are_no_favourites(self):
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._maybe_offer_favourites_check)
        assert "favorites_mod.load" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_freshness.py -k LaunchPrompt -q --no-header -p no:randomly`
Expected: FAIL — `AttributeError: ask_to_check_favourites`

- [ ] **Step 3: Add the settings**

In `S:\code\pod\podharvest\config.py`:

```python
    #: Offer, once per launch, to check favourites for new episodes. This is
    #: a question, not a schedule: nothing runs while podHarvest is closed,
    #: and nothing is downloaded by answering yes. Saying no is remembered
    #: for that launch; "Stop asking" turns this off for good.
    ask_to_check_favourites: bool = True
    #: When the favourites were last checked, ISO 8601, so the question can
    #: say how long it has been rather than asking every single launch.
    favourites_checked_at: str = ""
```

- [ ] **Step 4: Ask, once, on the way in**

In `S:\code\pod\podharvest\gui.py`, add to `MainFrame`:

```python
    #: How long since the last check before the question is worth asking.
    FAVOURITES_STALE_DAYS = 7

    def _maybe_offer_favourites_check(self) -> None:
        """Offer once, on the way in, to see what is new. Never acts alone.

        Deliberately a question and not a schedule. podHarvest is not a
        subscription: nothing runs while it is closed, nothing is fetched
        without an answer, and nothing is downloaded by answering yes -- the
        check reads feeds and reports, and Start is still a separate press.
        """
        from datetime import datetime, timedelta, timezone

        from podharvest import favorites as favorites_mod

        if not self.settings.ask_to_check_favourites:
            return
        favourites = favorites_mod.load(self.app_space)
        if not favourites:
            return
        last = self.settings.favourites_checked_at
        if last:
            try:
                when = datetime.fromisoformat(last)
                if datetime.now(timezone.utc) - when < timedelta(
                        days=self.FAVOURITES_STALE_DAYS):
                    return
            except ValueError:
                pass          # an unreadable date is a reason to ask, not to crash
        count = len(favourites)
        message = (
            f"{count} favourite{'s' if count != 1 else ''} "
            f"{'have' if count != 1 else 'has'} not been checked for new "
            f"episodes in over {self.FAVOURITES_STALE_DAYS} days.\n\n"
            "Check now? This reads each feed and tells you what is new. "
            "Nothing is downloaded, and nothing runs while podHarvest is "
            "closed."
        )
        dlg = wx.MessageDialog(self, message, "Check your favourites?",
                               wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        dlg.SetYesNoCancelLabels("&Check now", "&Not now", "&Stop asking")
        try:
            answer = dlg.ShowModal()
        finally:
            dlg.Destroy()
        if answer == wx.ID_CANCEL:
            self.settings.ask_to_check_favourites = False
            config_mod.save(self.app_space, self.settings)
            LOG.info("podHarvest will not offer to check your favourites "
                     "again. Settings can turn it back on.")
            return
        if answer != wx.ID_YES:
            return
        self.settings.favourites_checked_at = (
            datetime.now(timezone.utc).isoformat(timespec="seconds"))
        config_mod.save(self.app_space, self.settings)
        self._on_check_favorites()
```

Call it once, after the window is shown and the library has been refreshed,
via `wx.CallAfter(self._maybe_offer_favourites_check)` at the end of
`__init__` — after, not during, so the main window is on screen and has
focus before a dialog appears over it.

- [ ] **Step 5: Offer the switch in Settings**

In `SettingsDialog`, in the Finished box or beside it:

```python
        self.chk_ask_favourites = wx.CheckBox(
            fholder, label="&Offer to check favourites when podHarvest opens")
        self.chk_ask_favourites.SetValue(settings.ask_to_check_favourites)
        self.chk_ask_favourites.SetToolTip(
            "Asks once, when the window opens, whether to look for new "
            "episodes of your favourite shows. It is only ever a question: "
            "nothing runs while podHarvest is closed and nothing is "
            "downloaded by saying yes."
        )
        fin_box.Add(self.chk_ask_favourites, 0, wx.ALL, 6)
```

Save it with the others.

- [ ] **Step 6: Run tests and the help audit**

Run: `python -m podharvest.help_audit --write && python -m pytest tests -q --no-header -p no:randomly`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add podharvest/config.py podharvest/gui.py tests/test_freshness.py tests/help_inventory.json
git commit -m "Offer once at launch to see what is new, and never act alone"
```

---

## Task 16: Documentation and the release

**Files:**
- Modify: `S:\code\pod\docs\REFERENCE.md`
- Modify: `S:\code\pod\docs\ACCESSIBILITY.md`
- Modify: `S:\code\pod\README.md`
- Modify: `S:\code\pod\CHANGELOG.md`

- [ ] **Step 1: Document the timing model in REFERENCE.md**

Add a section after "The library":

```markdown
### Timings

Every transcription engine can return word-level timings, and podHarvest now
keeps them. `podharvest/timing_core.py` holds the model — `TimedWord`,
`TimedSegment`, `Timeline` — and `load_timeline(transcript_path)` is the one
way in. It reads the best source available, in order:

1. `<slug>.words.json` beside the transcript — word-accurate, written by
   every run from this version onwards.
2. `<slug>.vtt` or `<slug>.srt` — cue-accurate, either the publisher's own
   or podHarvest's optional caption output.
3. The `[HH:MM:SS.mmm]` markers in the transcript itself — segment-accurate,
   and present in almost every transcript already on disk, which is what
   makes the timing features work on a library harvested before this
   version existed.

`Timeline.source` names which of the three it got, so a window can say how
precise it is being rather than implying word accuracy it does not have.

The module is standard-library-only and shared byte-for-byte with QUILL; see
[SHARED.md](SHARED.md).
```

- [ ] **Step 2: Update ACCESSIBILITY.md**

Replace the "activity log does not announce" paragraph's closing sentence
("Adding real spoken announcements would require...") with:

```markdown
Since this version podHarvest can speak instead. **Settings ▸ Announcements**
offers spoken output for completions, progress and errors, each chosen
separately, plus braille through the same screen reader. All four are off by
default, and the component that does the talking is downloaded only when you
press **Set up announcements** — nothing is installed without being asked.
The limitation itself is unchanged: the log control still cannot announce
itself, and this speaks around it rather than fixing it.
```

Add to the "what works" table:

```markdown
| Finding a phrase ends with hearing it | Ctrl+Shift+S searches every transcript and each result carries a time. Enter opens the reader at the match and cues the player there — loaded but not started, because audio beginning unasked over a screen reader mid-sentence is startling. In the reader, Control+Enter plays from wherever the caret is. |
| Reading along, only if you ask | Settings can move the transcript caret to keep pace with playback. It is off by default and deliberately so: a caret that moves on its own takes the text out from under somebody reading at their own pace. Only the caret moves, and only when the sentence changes. |
| Clips are chosen by reading, not by scrubbing | Select a passage of transcript and save exactly that audio, with short fades and a filename made from the words that were said. The usual way to make a clip is to drag across a waveform, which is no way at all if you cannot see one. |
| Chapters can be placed by phrase | The chapter editor takes words from the transcript and moves the playhead to where they were said. Nudging by ear stays for the fine work; this is the coarse move that precedes it. |
```

- [ ] **Step 3: Update README.md**

Add after the "Finding a podcast" section:

```markdown
## Finding a moment

**Ctrl+Shift+S** searches every transcript in your library at once. Each
result says which episode, how many times, and *when* — and pressing Enter
opens the transcript at the match with the audio cued to it. In the reader,
**Control+Enter** plays from wherever the caret is.

Select a passage and **Save as a clip** writes exactly that audio to its own
file, named after the words that were said. The chapter editor will also take
a phrase and move the playhead to where it was spoken, which beats hunting
for a boundary by ear.

These work on transcripts you already have. podHarvest writes timings into
every transcript it makes, so a library harvested a year ago is searchable
this way today.
```

- [ ] **Step 4: Update CHANGELOG.md**

Add a new section at the top of the current release's entry, following the
existing "Added" / "Fixed" style used in that file.

- [ ] **Step 5: Run everything one last time**

Run: `python -m podharvest.help_audit && python -m pytest tests -q --no-header -p no:randomly`
Expected: help audit clean; full suite passes.

- [ ] **Step 6: Commit**

```bash
git add docs/ README.md CHANGELOG.md
git commit -m "Document the timing features and the announcements"
```

- [ ] **Step 7: Build and publish (only when the maintainer asks)**

```powershell
./scripts/build_installer.ps1 -Clean -Inno -Sign
```

Then rebuild the wheel and sdist, regenerate `dist/SHA256SUMS.txt` over all
four artifacts, and upload with `gh release upload`. Do not push or publish
without being asked.

---

## Notes for whoever picks this up

- **The fallback is the feature.** It would be easy to build all of this on
  the `.words.json` sidecar alone and ship something that works only for
  transcripts made after today. Reading the `[HH:MM:SS.mmm]` markers back
  out is what makes it work for somebody's existing library, and that is
  most of the value.
- **Follow-along is off. Keep it off.** The maintainer asked for this
  explicitly. If a later change makes it convenient to default it on,
  that is not a judgement call to make on your own.
- **`timing_core.py` is shared.** Editing it means copying to QUILL and
  regenerating both digests. The drift test will fail otherwise, and it is
  supposed to.
- **Check `announce` degrades.** Test with the component absent as well as
  present. The failure mode that matters is not "no speech"; it is "podHarvest
  will not start because a screen reader was closed".
```
