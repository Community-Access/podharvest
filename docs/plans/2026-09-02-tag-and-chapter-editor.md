# podHarvest Tag and Chapter Editor — Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give podHarvest a full audio tag editor and complete chapter editing — add, delete, preview, alter, nudge — sharing its logic byte-identically with QUILL Audio Studio, so a file edited in either app is indistinguishable from one edited in the other.

**Architecture:** One vendored pure-Python module, `podharvest/audio_tags_core.py`, holds the 26-field tag table, the mutagen-backed readers and writers, and every chapter operation. It is the same file, byte for byte, as `quill/core/speech/audio_tags_core.py`, with a drift test in each repo. `podharvest/tags.py` is podHarvest's thin adapter; `podharvest/chapters.py` keeps its harvest-time entry points but writes MP3 chapters through the shared writer instead of an ffmpeg re-mux. A new `podharvest/editor.py` holds the dialog.

**Tech Stack:** Python 3.10+, wxPython (the `gui` extra), mutagen (added to the `gui` extra), ffmpeg for the non-MP3 containers, pytest.

**Governing contract:** `docs/ALIGNMENT-audio-tags-and-chapters.md`. Read it first. Anything in this plan that contradicts it is a bug in this plan.

## Global Constraints

- **The CLI stays standard-library only.** podHarvest's stated promise is that `fetch`/`hardware`/`info`/`settings` run on the standard library alone, with the desktop GUI as the one exception. mutagen goes in the **`gui` extra**, is imported **lazily inside functions**, and is never reached from a CLI path. `podharvest/cli.py` must not gain a mutagen import, directly or transitively.
- **`audio_tags_core.py` is vendored.** Do not edit it in this repo alone. Every change is a two-repo change plus a digest update in both, enforced by the drift test. It imports nothing from `podharvest`.
- **Accessibility, per the alignment contract:** create the `wx.StaticText` label *before* the control it labels; name every control with `set_accessible_name` (which already does both `SetName` and a `wx.Accessible` helper in `podharvest/gui.py`); use `FlexGridSizer` rows rather than `wx.StaticBox` groups in the new dialogs, so `&` mnemonics are reachable; keep mnemonics unique case-insensitively within each notebook page; and add the chapter keys to an accelerator table as well.
- **`embed_chapters` never raises.** A podcast that failed to gain chapter markers is still a perfectly good podcast. That contract is load-bearing for the harvest pipeline and must survive the rewrite.
- Follow the house docstring voice: say what the thing is for and why it is that way, in plain words, addressed to the reader.
- **Commits:** the repository owner does not want commits created unless explicitly asked. Each task ends with a commit step; if commits have not been authorised for this run, stage and report instead.

---

## File Structure

| File | State | Responsibility |
| --- | --- | --- |
| `podharvest/audio_tags_core.py` | create (vendored) | tag table, `AudioTags`, `CoverArt`, read/write, `Chapter`, every chapter operation |
| `podharvest/audio_tags_core.sha256` | create | the digest the drift test checks |
| `podharvest/tags.py` | create | podHarvest's adapter: find an episode's audio, read/write with logging |
| `podharvest/chapters.py` | modify | MP3 chapters through the shared writer; ffmpeg re-mux for the rest |
| `podharvest/player.py` | create | a minimal `wx.media.MediaCtrl` transport, for judging a marker by ear |
| `podharvest/editor.py` | create | the Tag and Chapter Editor dialog |
| `podharvest/gui.py` | modify | open the editor from the Episodes list and the menu; accelerators |
| `pyproject.toml`, `requirements.txt` | modify | mutagen in the `gui` extra |
| `tests/test_audio_tags.py` | create | tag round-trips, cover art, drift gate |
| `tests/test_chapter_ops.py` | create | add/delete/bounds/nudge |
| `tests/test_chapters.py` | modify | the rewritten `embed_chapters` |

---

### Task 1: Vendor the shared module, and prove it has not drifted

**Files:**
- Create: `podharvest/audio_tags_core.py`, `podharvest/audio_tags_core.sha256`
- Modify: `pyproject.toml`, `requirements.txt`
- Test: `tests/test_audio_tags.py`

**Interfaces:**
- Produces: everything the alignment contract lists under "The shared module"

This task cannot run before QUILL's Tasks 1–7 have produced the module. If you are implementing podHarvest first, build the module here to the alignment contract's specification and copy it into QUILL instead — the direction does not matter, byte-identity does.

- [ ] **Step 1: Write the failing test**

Create `tests/test_audio_tags.py`:

```python
"""The shared tag model: the table, the container, and the vendoring gate."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from podharvest import audio_tags_core as core

MODULE = Path(core.__file__)
DIGEST_FILE = MODULE.with_suffix(".sha256")


class TestVendoring:
    def test_the_shared_module_has_not_drifted(self):
        """Vendored from QUILL. Edit it in both repos or neither."""
        expected = DIGEST_FILE.read_text(encoding="utf-8").split()[0].strip()
        actual = hashlib.sha256(MODULE.read_bytes()).hexdigest()
        assert actual == expected, (
            "audio_tags_core.py has changed. Copy the new file into "
            "quill/core/speech/audio_tags_core.py, update the digest in both "
            "repos, or the two apps have silently diverged."
        )

    def test_it_imports_nothing_from_podharvest(self):
        """Byte-identity is only possible while it depends on neither host."""
        source = MODULE.read_text(encoding="utf-8")
        assert "podharvest" not in source
        assert "quill" not in source

    def test_it_imports_mutagen_lazily(self):
        """The CLI promise: importing this module must not need mutagen."""
        for line in MODULE.read_text(encoding="utf-8").splitlines():
            if line.startswith(("import mutagen", "from mutagen")):
                pytest.fail(f"top-level mutagen import: {line!r}")


class TestFieldTable:
    def test_there_are_twenty_six_fields(self):
        assert len(core.TAG_FIELDS) == 26

    def test_keys_and_id3_frames_are_unique(self):
        assert len({f.key for f in core.TAG_FIELDS}) == 26
        assert len({f.id3 for f in core.TAG_FIELDS}) == 26

    def test_mnemonics_are_unique_within_each_page(self):
        for group, _label in core.GROUPS:
            letters = [f.label[f.label.index("&") + 1].lower()
                       for f in core.fields_in(group) if "&" in f.label]
            assert len(letters) == len(set(letters)), f"duplicate in {group}"

    def test_every_field_explains_itself(self):
        for field in core.TAG_FIELDS:
            assert field.help.endswith("."), f"{field.key} help is not a sentence"


class TestAudioTags:
    def test_values_are_stripped_and_empty_clears(self):
        tags = core.AudioTags()
        tags.set("album", "  My Show  ")
        assert tags.get("album") == "My Show"
        tags.set("album", "")
        assert tags.get("album") == ""

    def test_copy_is_independent(self):
        tags = core.AudioTags()
        tags.set("album", "First")
        clone = tags.copy()
        clone.set("album", "Second")
        assert tags.get("album") == "First"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_audio_tags.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'podharvest.audio_tags_core'`

- [ ] **Step 3: Vendor the module**

Copy `quill/core/speech/audio_tags_core.py` to `podharvest/audio_tags_core.py` unchanged, then prepend the vendoring banner **inside** the existing module docstring (do not add a second docstring — that would change the bytes relative to QUILL's copy, so the banner must be identical in both files):

The first paragraph of the shared docstring must read:

```
"""The shared audio tag and chapter model, vendored into two repositories.

This file is byte-identical in QUILL (quill/core/speech/audio_tags_core.py)
and podHarvest (podharvest/audio_tags_core.py). Editing one copy without the
other is what the drift test in each repo exists to catch. It imports nothing
from either host package, and imports mutagen lazily inside functions, which
is what makes both of those things possible.
...
```

- [ ] **Step 4: Record the digest**

```bash
python -c "import hashlib,pathlib; p=pathlib.Path('podharvest/audio_tags_core.py'); print(hashlib.sha256(p.read_bytes()).hexdigest())" > podharvest/audio_tags_core.sha256
```

Copy the same digest into QUILL's `quill/core/speech/audio_tags_core.sha256`. If the two files differ by so much as a line ending, the digests will not match — check `.gitattributes` in both repos and make sure this file is treated the same way in each.

- [ ] **Step 5: Add mutagen to the GUI extra**

In `pyproject.toml`:

```toml
[project.optional-dependencies]
gui = ["wxPython>=4.2", "mutagen>=1.48.1"]
```

In `requirements.txt`, beneath the existing wxPython line, extend the comment rather than adding a bare line — the comment there is load-bearing documentation of the zero-dependency promise:

```
# podharvest's CLI (fetch/hardware/info/settings) is deliberately built on
# the Python standard library only, so it runs anywhere Python 3.10+ runs
# with zero installs. The two exceptions are both parts of the optional
# desktop GUI: wxPython draws it, and mutagen reads and writes the tag and
# chapter frames the Tag and Chapter Editor edits. Neither is imported from
# any CLI path.
wxPython>=4.2
mutagen>=1.48.1
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_audio_tags.py -q`
Expected: PASS.

Run: `python -m pytest -q`
Expected: PASS — no regressions.

- [ ] **Step 7: Prove the CLI promise still holds**

```bash
python -c "
import subprocess, sys, json
code = 'import sys; import podharvest.cli; print(\"mutagen\" in sys.modules)'
print(subprocess.run([sys.executable, '-c', code], capture_output=True, text=True).stdout)
"
```

Expected: `False`. If it prints `True`, something on the CLI import path pulls mutagen in — find it and make the import lazy.

- [ ] **Step 8: Commit**

```bash
git add podharvest/audio_tags_core.py podharvest/audio_tags_core.sha256 pyproject.toml requirements.txt tests/test_audio_tags.py
git commit -m "feat: vendor the shared audio tag and chapter model from QUILL"
```

---

### Task 2: Tag reading and writing, end to end

**Files:**
- Create: `podharvest/tags.py`
- Test: `tests/test_audio_tags.py`

**Interfaces:**
- Consumes: `core.read_tags`, `core.write_tags`, `core.AudioTags`, `core.load_cover`
- Produces: `read_tags(path) -> AudioTags`, `write_tags(path, tags) -> bool`, `audio_for_episode(folder, stem) -> Path | None`

The adapter is thin on purpose: it adds podHarvest's logging voice and its never-raise-at-the-boundary habit, and nothing else. Every rule about what a tag *is* lives in the shared module, where both apps read it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audio_tags.py`:

```python
mutagen = pytest.importorskip("mutagen")

from podharvest import tags as tags_mod  # noqa: E402

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fdff03fd0000000049454e44ae"
    "426082"
)


@pytest.fixture
def episode_mp3(tmp_path):
    """A minimal valid MP3, standing in for a downloaded episode."""
    path = tmp_path / "0001 - An Episode.mp3"
    path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 4)
    return path


class TestRoundTrip:
    def test_every_text_field_survives_a_write(self, episode_mp3):
        tags = core.AudioTags()
        for field in core.TAG_FIELDS:
            if field.kind in {"text", "multiline"}:
                tags.set(field.key, f"value for {field.key}")
        tags.set("year", "2026")
        tags.set("track", "7/40")
        tags.set("bpm", "90")
        tags.set("compilation", "1")
        assert tags_mod.write_tags(episode_mp3, tags) is True
        back = tags_mod.read_tags(episode_mp3)
        for field in core.TAG_FIELDS:
            assert back.get(field.key) == tags.get(field.key), field.key

    def test_cover_art_survives(self, episode_mp3):
        tags = core.AudioTags()
        tags.cover = core.CoverArt(data=_PNG, mime="image/png")
        tags_mod.write_tags(episode_mp3, tags)
        back = tags_mod.read_tags(episode_mp3).cover
        assert back is not None and back.data == _PNG

    def test_an_untagged_file_reads_as_empty_not_an_error(self, episode_mp3):
        assert tags_mod.read_tags(episode_mp3).values == {}

    def test_a_write_to_a_missing_file_is_reported_not_raised(self, tmp_path):
        assert tags_mod.write_tags(tmp_path / "gone.mp3", core.AudioTags()) is False


class TestAudioForEpisode:
    def test_finds_the_audio_beside_the_transcript(self, tmp_path):
        (tmp_path / "0001 - An Episode.mp3").write_bytes(b"x")
        found = tags_mod.audio_for_episode(tmp_path, "0001 - An Episode")
        assert found is not None and found.suffix == ".mp3"

    def test_returns_none_when_there_is_no_audio(self, tmp_path):
        assert tags_mod.audio_for_episode(tmp_path, "0001 - An Episode") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_audio_tags.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'podharvest.tags'`

- [ ] **Step 3: Write the adapter**

Create `podharvest/tags.py`:

```python
"""Reading and writing an episode's tags, the way podHarvest likes to fail.

The rules about what a tag is, which frame it lives in and how it is written
all live in `podharvest.audio_tags_core`, which is shared byte-for-byte with
QUILL Audio Studio so the two apps cannot drift. This module is the thin
layer around it: it finds the audio file belonging to an episode, and it
turns the shared module's exceptions into a logged warning and a False,
because a tag edit that failed should never take the app down with it.

mutagen is imported only inside the shared module's functions, and only the
GUI ever calls this, so the command line still runs on the standard library
alone.
"""

from __future__ import annotations

from pathlib import Path

from podharvest import audio_tags_core as core
from podharvest.util import LOG

#: The audio extensions a harvested episode can arrive in, best first.
AUDIO_SUFFIXES = (".mp3", ".m4a", ".m4b", ".mp4", ".ogg", ".opus", ".wav")

#: The subset this editor can actually tag. The rest are left alone rather
#: than half-supported.
TAGGABLE_SUFFIXES = (".mp3", ".m4a", ".m4b", ".mp4")


def audio_for_episode(folder: Path, stem: str) -> Path | None:
    """The audio file for an episode, given the folder and the shared stem.

    podHarvest names an episode's audio, transcript and notes from the same
    stem, so the audio is found by trying the known extensions in order
    rather than by guessing from a listing.
    """
    for suffix in AUDIO_SUFFIXES:
        candidate = Path(folder) / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def is_taggable(path: Path) -> bool:
    """Whether this editor can read and write tags on *path*."""
    return Path(path).suffix.lower() in TAGGABLE_SUFFIXES


def read_tags(path: Path) -> core.AudioTags:
    """Every tag on *path*. A file with no tags at all reads as empty tags.

    An unreadable tag block is logged and read as empty rather than raised:
    a file nobody has tagged yet is exactly the one somebody opens the editor
    to fix, and refusing to show it would be the wrong answer.
    """
    try:
        return core.read_tags(Path(path))
    except core.AudioTagError as exc:
        LOG.warning("Could not read the tags on %s: %s", Path(path).name, exc)
        return core.AudioTags()


def write_tags(path: Path, tags: core.AudioTags) -> bool:
    """Write *tags* onto *path*. True when written, False when it could not be.

    Frames this editor does not model -- including the chapter frames -- are
    left exactly as they were.
    """
    try:
        core.write_tags(Path(path), tags)
    except core.AudioTagError as exc:
        LOG.warning("Could not write the tags on %s: %s", Path(path).name, exc)
        return False
    LOG.info("Saved tags to %s", Path(path).name)
    return True


def read_chapters(path: Path) -> list[core.Chapter]:
    """The chapter list on *path*, or an empty list when it carries none."""
    try:
        return core.read_mp3_chapters(Path(path))
    except Exception as exc:  # noqa: BLE001 - absent/unreadable frames read as none
        LOG.debug("No readable chapters on %s: %s", Path(path).name, exc)
        return []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_audio_tags.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check podharvest/tags.py tests/test_audio_tags.py
git add podharvest/tags.py tests/test_audio_tags.py
git commit -m "feat: read and write full audio tags through the shared model"
```

---

### Task 3: Stop re-muxing MP3s to add chapters

**Files:**
- Modify: `podharvest/chapters.py`
- Test: `tests/test_chapters.py`

**Interfaces:**
- Consumes: `core.write_mp3_chapters`, `core.Chapter`
- Produces: `embed_chapters` unchanged in signature and contract; new `embed_chapter_objects(path, chapters) -> bool`

`embed_chapters` currently copies the whole episode through ffmpeg to add about a hundred bytes of chapter frames. For MP3 — which is what podcasts actually are — the shared mutagen writer edits the tag block in place. A 60 MB episode goes from a full file copy to instant, the temp-file dance is no longer needed, and the frames it writes become byte-identical to QUILL's. The ffmpeg path stays for `.ogg`, `.opus` and the MP4 family, which mutagen cannot chapter in place.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chapters.py`:

```python
from pathlib import Path

import pytest

from podharvest import chapters as chapters_mod


@pytest.fixture
def episode_mp3(tmp_path):
    path = tmp_path / "episode.mp3"
    path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
    return path


class TestEmbedChapters:
    def test_mp3_chapters_are_written_in_place_without_a_remux(self, episode_mp3):
        """The audio bytes must be untouched -- only the tag block changes."""
        pytest.importorskip("mutagen")
        before = episode_mp3.read_bytes()
        assert chapters_mod.embed_chapters(
            episode_mp3, [(0, "Opening"), (600, "The interview")], 1200.0) is True
        after = episode_mp3.read_bytes()
        assert before in after, "the audio frames were re-encoded or re-muxed"

    def test_written_chapters_read_back(self, episode_mp3):
        pytest.importorskip("mutagen")
        chapters_mod.embed_chapters(
            episode_mp3, [(0, "Opening"), (600, "The interview")], 1200.0)
        found = chapters_mod.read_chapters(episode_mp3)
        assert [name for _s, _e, name in found] == ["Opening", "The interview"]

    def test_element_ids_match_the_alignment_contract(self, episode_mp3):
        """ch0, ch1, toc -- the same ids QUILL writes, so files interchange."""
        mutagen_id3 = pytest.importorskip("mutagen.id3")
        chapters_mod.embed_chapters(
            episode_mp3, [(0, "Opening"), (600, "The interview")], 1200.0)
        frames = mutagen_id3.ID3(str(episode_mp3))
        assert sorted(f.element_id for f in frames.getall("CHAP")) == ["ch0", "ch1"]
        assert [f.element_id for f in frames.getall("CTOC")] == ["toc"]

    def test_an_empty_chapter_list_is_a_no_op(self, episode_mp3):
        assert chapters_mod.embed_chapters(episode_mp3, [], 1200.0) is False

    def test_a_missing_file_is_shrugged_off_not_raised(self, tmp_path):
        assert chapters_mod.embed_chapters(
            tmp_path / "gone.mp3", [(0, "One")], 60.0) is False

    def test_an_unsupported_container_is_left_alone(self, tmp_path):
        path = tmp_path / "episode.wav"
        path.write_bytes(b"RIFF....WAVE")
        assert chapters_mod.embed_chapters(path, [(0, "One")], 60.0) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_chapters.py -q`
Expected: FAIL — `test_mp3_chapters_are_written_in_place_without_a_remux` fails because the current ffmpeg path rewrites the whole file, so the original bytes are not a substring of the result.

- [ ] **Step 3: Route MP3 through the shared writer**

In `podharvest/chapters.py`, add above `embed_chapters`:

```python
#: Containers mutagen can chapter in place. Everything else in
#: SUPPORTED_SUFFIXES still goes the ffmpeg route.
IN_PLACE_SUFFIXES = {".mp3"}


def _embed_in_place(audio_path: Path, chapters: list[tuple[int, str]],
                    total_seconds: float) -> bool:
    """Write ID3 chapter frames straight into the tag block. No re-mux.

    Adding a hundred bytes of chapter markers does not justify copying a
    sixty-megabyte episode, and the shared writer produces exactly the frames
    QUILL Audio Studio writes, so a file edited in either app is the same
    file. Returns False (never raises) if mutagen is missing, which is the
    case on a command-line-only install.
    """
    from podharvest import audio_tags_core as core

    marks: list[core.Chapter] = []
    for index, (start, name) in enumerate(chapters):
        end = (chapters[index + 1][0] if index + 1 < len(chapters)
               else int(total_seconds))
        if end <= start:
            continue
        marks.append(core.Chapter(index=len(marks), title=name,
                                  start_ms=int(start * 1000), end_ms=int(end * 1000)))
    if not marks:
        return False
    try:
        core.write_mp3_chapters(audio_path, marks)
    except Exception as exc:  # noqa: BLE001 - a chapterless podcast is still fine
        LOG.warning("Could not add chapter markers to %s: %s", audio_path.name, exc)
        return False
    LOG.info("Added %d chapter marker(s) to %s in place, so a podcast player "
             "can jump between topics.", len(marks), audio_path.name)
    return True
```

and in `embed_chapters`, immediately after the existing `if not audio_path.exists(): return False` guard, add:

```python
    if audio_path.suffix.lower() in IN_PLACE_SUFFIXES:
        return _embed_in_place(audio_path, chapters, total_seconds)
```

Leave the rest of `embed_chapters` — the ffmpeg re-mux — exactly as it is. It now serves `.m4a`, `.m4b`, `.mp4`, `.ogg` and `.opus` only, and its temp-file safety still matters for those.

Update the module docstring's second paragraph, which currently claims every write is a re-mux:

```
For an MP3 the markers go straight into the ID3 tag block: adding a hundred
bytes does not justify copying a sixty-megabyte episode, and the frames are
written by the model shared with QUILL Audio Studio, so a file edited in
either app is the same file. Every other container still goes through a
lossless ffmpeg re-mux to a temporary file that only replaces the original
once ffmpeg has succeeded, so an interrupted write cannot leave a truncated
podcast episode behind.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_chapters.py -q`
Expected: PASS.

- [ ] **Step 5: Verify against a real episode**

The in-place claim deserves a real file, not only a synthetic one. Take any MP3 from an existing harvest, note its size and modification time, run `embed_chapters` on it, and confirm the file size grew by roughly the size of the chapter block and that a player still plays it from the start.

- [ ] **Step 6: Commit**

```bash
git add podharvest/chapters.py tests/test_chapters.py
git commit -m "perf: write MP3 chapter markers in place instead of re-muxing the episode"
```

---

### Task 4: Chapter operations, and the shared drift they must not break

**Files:**
- Test: `tests/test_chapter_ops.py`

**Interfaces:**
- Consumes: `core.add_chapter`, `core.delete_chapter`, `core.set_chapter_bounds`, `core.nudge_chapter_start`, `core.NUDGE_STEPS_MS`

No implementation: the operations live in the vendored module. What this task adds is podHarvest's own coverage of them, so a bad vendoring is caught here and not in the dialog.

- [ ] **Step 1: Write the test**

Create `tests/test_chapter_ops.py`:

```python
"""The chapter operations, exercised from podHarvest's side of the vendoring."""

from __future__ import annotations

import pytest

from podharvest import audio_tags_core as core


def three():
    return [
        core.Chapter(index=0, title="One", start_ms=0, end_ms=10_000),
        core.Chapter(index=1, title="Two", start_ms=10_000, end_ms=20_000),
        core.Chapter(index=2, title="Three", start_ms=20_000, end_ms=30_000),
    ]


class TestAdd:
    def test_splits_the_chapter_holding_the_point(self):
        result = core.add_chapter(three(), 15_000, title="Middle")
        assert [c.title for c in result] == ["One", "Two", "Middle", "Three"]
        assert result[2].start_ms == 15_000

    def test_appends_past_the_end(self):
        result = core.add_chapter(three(), 30_000, title="Outro")
        assert result[-1].title == "Outro"

    def test_refuses_a_sliver(self):
        with pytest.raises(core.ChapterEditError):
            core.add_chapter(three(), 10_500, min_part_ms=1000)


class TestDelete:
    def test_first_chapter_pulls_the_next_back_to_zero(self):
        result = core.delete_chapter(three(), 0)
        assert [c.title for c in result] == ["Two", "Three"]
        assert result[0].start_ms == 0

    def test_middle_chapter_extends_the_previous(self):
        result = core.delete_chapter(three(), 1)
        assert result[0].end_ms == 20_000

    def test_last_chapter_extends_the_previous(self):
        result = core.delete_chapter(three(), 2)
        assert result[-1].end_ms == 30_000

    def test_the_only_chapter_cannot_be_deleted(self):
        with pytest.raises(core.ChapterEditError):
            core.delete_chapter([core.Chapter(0, "All", 0, 10_000)], 0)


class TestBounds:
    def test_moves_both_edges_and_the_neighbours(self):
        result = core.set_chapter_bounds(three(), 1, 8_000, 22_000)
        assert (result[0].end_ms, result[1].start_ms) == (8_000, 8_000)
        assert (result[1].end_ms, result[2].start_ms) == (22_000, 22_000)

    def test_rejects_an_inverted_range(self):
        with pytest.raises(core.ChapterEditError):
            core.set_chapter_bounds(three(), 1, 20_000, 10_000)


class TestNudge:
    def test_moves_the_boundary_and_reports_the_delta(self):
        result, applied = core.nudge_chapter_start(three(), 1, -500)
        assert applied == -500
        assert result[1].start_ms == 9_500

    def test_clamps_instead_of_raising(self):
        result, applied = core.nudge_chapter_start(three(), 1, -60_000)
        assert applied == -9_500
        assert result[1].start_ms == 500

    def test_reports_zero_when_it_cannot_move(self):
        pinned = [core.Chapter(0, "One", 0, 500), core.Chapter(1, "Two", 500, 1_000)]
        _result, applied = core.nudge_chapter_start(pinned, 1, -1_000)
        assert applied == 0

    def test_the_first_chapter_is_pinned_to_the_beginning(self):
        with pytest.raises(core.ChapterEditError):
            core.nudge_chapter_start(three(), 0, 500)

    def test_the_steps_are_the_ones_the_contract_names(self):
        assert core.NUDGE_STEPS_MS == (100, 250, 500, 1000, 2000, 5000, 10_000)
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_chapter_ops.py -q`
Expected: PASS if the vendored module is correct. A failure here means the vendoring is wrong or QUILL's module does not match the contract — fix the module in **both** repos and re-record both digests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_chapter_ops.py
git commit -m "test: cover the shared chapter operations from podHarvest"
```

---

### Task 5: A minimal player, so a marker can be judged by ear

**Files:**
- Create: `podharvest/player.py`
- Test: manual (see step 4)

**Interfaces:**
- Produces: `PlayerPanel(parent, *, announce=None)` with `load(path)`, `play()`, `pause()`, `playhead_ms()`, `seek_to(ms)`, `length_ms()`, `stop_at(ms)`, `shutdown()`

Nudging a marker and previewing a chapter are both operations you perform *by ear*; podHarvest has no player at all today. `wx.media.MediaCtrl` gives one with no new dependency — it uses the platform's own backend, which on Windows reads MP3 and MP4 without help.

- [ ] **Step 1: Write the implementation**

Create `podharvest/player.py`:

```python
"""A small transport, because a chapter marker is judged by ear.

Nudging a boundary half a second at a time only means something if you can
hear the result, so the editor needs playback. `wx.media.MediaCtrl` provides
it through the platform's own media backend, which costs no new dependency
and reads the containers podcasts actually arrive in.

The panel deliberately holds no chapter knowledge. It plays, it seeks, it
reports where it is, and it can be told to stop at a point -- which is all
the preview and the boundary audition need, and it keeps the chapter rules
in the shared model where both apps read them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx
import wx.media

from podharvest.gui import set_accessible_name
from podharvest.util import LOG

#: How often the transport re-reads the playhead, in milliseconds. Fast
#: enough that a stop-at point lands within a frame of where it was asked
#: for, slow enough to cost nothing.
TICK_MS = 100


class PlayerPanel(wx.Panel):
    """Play, pause, stop, and a position readout, with a stop-at point."""

    def __init__(self, parent: wx.Window, *,
                 announce: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._announce_fn = announce
        self._stop_at: int | None = None
        self._on_tick_cb: Callable[[], None] | None = None

        self._media = wx.media.MediaCtrl(self, szBackend=wx.media.MEDIABACKEND_WMP10)
        self._media.Hide()  # audio only; the controls below are the interface

        row = wx.BoxSizer(wx.HORIZONTAL)
        self._play_btn = wx.Button(self, label="&Play")
        self._play_btn.Bind(wx.EVT_BUTTON, lambda _e: self.toggle())
        row.Add(self._play_btn, 0, wx.RIGHT, 6)
        stop_btn = wx.Button(self, label="Sto&p")
        stop_btn.Bind(wx.EVT_BUTTON, lambda _e: self.stop())
        row.Add(stop_btn, 0, wx.RIGHT, 12)

        # Label before control: screen readers pair them by creation order.
        row.Add(wx.StaticText(self, label="Position:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._position = wx.StaticText(self, label="0:00:00.000")
        set_accessible_name(self._position, "Playback position")
        row.Add(self._position, 0, wx.ALIGN_CENTER_VERTICAL)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(row, 0, wx.ALL, 6)
        self.SetSizer(root)

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self._tick(), self._timer)

    def set_tick_handler(self, handler: Callable[[], None] | None) -> None:
        """Call *handler* on every tick -- how the editor watches its stop point."""
        self._on_tick_cb = handler

    def load(self, path: Path) -> bool:
        """Open *path*. False when the platform backend will not play it."""
        if not self._media.Load(str(path)):
            LOG.warning("Could not open %s for playback. Editing still works; "
                        "only the preview does not.", Path(path).name)
            return False
        return True

    def play(self) -> None:
        self._media.Play()
        self._timer.Start(TICK_MS)
        self._play_btn.SetLabel("&Pause")

    def pause(self) -> None:
        self._media.Pause()
        self._timer.Stop()
        self._play_btn.SetLabel("&Play")

    def toggle(self) -> None:
        if self._media.GetState() == wx.media.MEDIASTATE_PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._media.Stop()
        self._timer.Stop()
        self._stop_at = None
        self._play_btn.SetLabel("&Play")

    def playhead_ms(self) -> int:
        return int(self._media.Tell())

    def length_ms(self) -> int:
        return int(self._media.Length())

    def seek_to(self, ms: int) -> None:
        self._media.Seek(max(0, int(ms)))
        self._refresh_position()

    def stop_at(self, ms: int | None) -> None:
        """Stop playback once the playhead passes *ms*. None disarms it."""
        self._stop_at = ms

    def shutdown(self) -> None:
        """Release the file, so it can be rewritten while the editor is open."""
        self._timer.Stop()
        self._media.Stop()
        self._media.Load("")

    def _refresh_position(self) -> None:
        from podharvest import audio_tags_core as core

        self._position.SetLabel(core.format_timestamp(self.playhead_ms()))

    def _tick(self) -> None:
        self._refresh_position()
        if self._stop_at is not None and self.playhead_ms() >= self._stop_at:
            self._stop_at = None
            self.pause()
        if self._on_tick_cb is not None:
            self._on_tick_cb()
```

Check the correct `szBackend` for the platform before pinning `MEDIABACKEND_WMP10`; on a non-Windows build, pass no backend and let wx choose.

- [ ] **Step 2: Guard the import**

`podharvest/player.py` imports `set_accessible_name` from `podharvest.gui`, and `gui.py` will import the editor, which imports the player. Break the cycle by moving `_Named` and `set_accessible_name` out of `gui.py` into a new `podharvest/a11y.py` and re-exporting them from `gui.py` so nothing that imports them today breaks:

```python
# podharvest/gui.py
from podharvest.a11y import _Named, set_accessible_name  # noqa: F401
```

- [ ] **Step 3: Run the suite**

Run: `python -m pytest -q`
Expected: PASS — the move is a pure relocation, and the re-export keeps every existing caller working.

- [ ] **Step 4: Verify by hand**

There is no useful automated test for a platform media backend. Open a harvested MP3 through a throwaway script, press Play, confirm audio comes out and the position readout advances, then call `stop_at` and confirm it stops there. Report what actually happened.

- [ ] **Step 5: Commit**

```bash
git add podharvest/player.py podharvest/a11y.py podharvest/gui.py
git commit -m "feat: add a minimal transport so chapter markers can be judged by ear"
```

---

### Task 6: The Tag and Chapter Editor dialog

**Files:**
- Create: `podharvest/editor.py`
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces: `EditorDialog(parent, path, *, announce=None)` with `result_tags()`, `result_chapters()`; `TagPage(parent, group)`; `CoverPage(parent, cover)`; `ChapterPage(parent, chapters, player, *, announce=None)`

Six notebook pages: Main, Details, Publishing, Sort order, Cover art, Chapters. The first five match QUILL's Tag Editor field for field, because they are generated from the same table. The sixth is podHarvest's equivalent of QUILL's Chapter Workbench, reduced to what fits one page: the list, the player, and the operations.

- [ ] **Step 1: Write the failing test**

Create `tests/test_editor.py`:

```python
"""The editor dialog: it builds, it is accessible, and it round-trips."""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")

from podharvest import audio_tags_core as core  # noqa: E402
from podharvest.editor import EditorDialog, TagPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application


@pytest.fixture
def episode(tmp_path):
    path = tmp_path / "episode.mp3"
    path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
    return path


class TestBuild:
    def test_every_field_gets_a_control(self, app, episode):
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            for field in core.TAG_FIELDS:
                assert field.key in dlg.controls, field.key
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_every_control_is_named_and_explained(self, app, episode):
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            for key, ctrl in dlg.controls.items():
                assert ctrl.GetName(), f"{key} has no accessible name"
                assert ctrl.GetToolTip() is not None, f"{key} has no explanation"
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_mnemonics_are_unique_within_each_page(self, app, episode):
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            for group, _label in core.GROUPS:
                letters = []
                for child in dlg.pages[group].GetChildren():
                    label = child.GetLabel()
                    if "&" in label:
                        letters.append(label[label.index("&") + 1].lower())
                assert len(letters) == len(set(letters)), group
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_no_page_uses_a_static_box(self, app, episode):
        """StaticBox scopes mnemonic search; the grid rows are why they work."""
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            for page in dlg.pages.values():
                for child in page.GetChildren():
                    assert not isinstance(child, wx.StaticBox)
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_each_label_precedes_its_control(self, app, episode):
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            for group, _label in core.GROUPS:
                children = list(dlg.pages[group].GetChildren())
                for i, child in enumerate(children):
                    if isinstance(child, wx.StaticText) and child.GetLabel().endswith(":"):
                        assert i + 1 < len(children)
                        assert not isinstance(children[i + 1], wx.StaticText)
        finally:
            dlg.Destroy()
            frame.Destroy()


class TestRoundTrip:
    def test_values_come_back_out(self, app, episode):
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            dlg.controls["album"].SetValue("The Show")
            dlg.controls["copyright"].SetValue("2026 Example")
            tags = dlg.result_tags()
            assert tags.get("album") == "The Show"
            assert tags.get("copyright") == "2026 Example"
        finally:
            dlg.Destroy()
            frame.Destroy()

    def test_a_pair_field_joins_number_and_total(self, app, episode):
        frame = wx.Frame(None)
        dlg = EditorDialog(frame, episode)
        try:
            dlg.controls["track"].SetValue("7")
            dlg.totals["track"].SetValue("40")
            assert dlg.result_tags().get("track") == "7/40"
        finally:
            dlg.Destroy()
            frame.Destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_editor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'podharvest.editor'`

- [ ] **Step 3: Write the dialog**

Create `podharvest/editor.py` with the page classes and the dialog. The
shape mirrors QUILL's `tag_editor.py` — deliberately, since the two apps are
meant to feel the same — with podHarvest's conventions substituted: no `_()`
wrapper, `SetToolTip` where QUILL uses `SetHelpText`, `LOG` for logging, and
`set_accessible_name` from `podharvest.a11y`.

```python
"""Every tag and every chapter of one episode, on six keyboard-reachable pages.

The five tag pages are generated from `podharvest.audio_tags_core.TAG_FIELDS`,
the table shared byte-for-byte with QUILL Audio Studio, so the two apps show
the same fields with the same names and the same explanations without either
of them having to remember to. The sixth page is the chapter editor: the
list, the transport, and the operations for reshaping a chapter list by ear.

Three things about the layout are deliberate rather than incidental:

- Each page is a `FlexGridSizer` of label-then-control rows and **not** a
  `wx.StaticBox` group. `IsDialogMessage` scopes its mnemonic search to the
  enclosing StaticBox, which is why the main window avoids `&` mnemonics
  entirely; without the boxes the problem does not arise, so these pages get
  mnemonics *and* the frame-level accelerator table.
- Mnemonics are unique within a page, case-insensitively. Only the visible
  notebook page's controls can be reached, so pages may reuse letters.
- The label is created before the control it labels, because that creation
  order is what Win32 uses to pair them.

The dialog is a pure editor: it hands back the edited tags and chapter list.
Writing is the caller's job, so a slow save never happens inside a modal.
"""
```

Build, in this order:

1. `_plain(label)` — strips `&` and the trailing colon, for accessible names.
2. `TagPage(wx.Panel)` — takes a group name, iterates `core.fields_in(group)`,
   and for each field adds the label then the control: a `wx.CheckBox` for
   `bool`, two `wx.TextCtrl`s joined by an "of" label for `pair`, a
   multi-line `wx.TextCtrl` for `multiline`, a one-line one otherwise. Each
   control gets `SetToolTip(field.help)` and `set_accessible_name`. Exposes
   `controls`, `totals`, `seed(tags)` and `collect(tags)`.
3. `CoverPage(wx.Panel)` — `core.describe_cover` as a `wx.StaticText` first, a
   `wx.StaticBitmap` thumbnail second, then Load, Save as and Remove buttons.
   The text is the primary readout because a picture tells a screen-reader
   user nothing. Exposes `cover`, `set_cover`, `remove_cover`.
4. `ChapterPage(wx.Panel)` — a `wx.ListBox` of
   `"{n}. {title} - starts {start}, runs {dur}"`, the `PlayerPanel`, and two
   button rows: Add, Delete, Edit, Preview; then Nudge back, Nudge forward, a
   step `wx.Choice` over `core.NUDGE_STEPS_MS`, Hear boundary, and a "Hear
   after each nudge" checkbox. Binds `EVT_KEY_DOWN` on the list for
   Alt+Left/Right and Alt+Shift+Left/Right. Calls
   `player.set_tick_handler(self._check_stop)`.
5. `ChapterDetailsDialog(wx.Dialog)` — title, start, end, link and image, with
   the allowed range stated in a sentence above the fields.
6. `EditorDialog(wx.Dialog)` — the notebook, the six pages, OK and Cancel, and
   `result_tags()` / `result_chapters()`.

Announcements follow the alignment contract exactly: a nudge speaks the bare
new time, the full sentence follows 600 ms after the run stops, and the wall
is announced once per run. Reuse the constants rather than restating them:

```python
NUDGE_SETTLE_MS = 600
BOUNDARY_LEAD_MS = 3_000
BOUNDARY_TAIL_MS = 2_000
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check podharvest/editor.py tests/test_editor.py
git add podharvest/editor.py tests/test_editor.py
git commit -m "feat: add the Tag and Chapter Editor"
```

---

### Task 7: Open it from the Episodes list

**Files:**
- Modify: `podharvest/gui.py` (`_build_menubar`, `_build_accelerators`, the episode list binding)
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: `EditorDialog`, `tags.audio_for_episode`, `tags.write_tags`, `chapters.embed_chapter_objects`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_editor.py`:

```python
class TestReachability:
    def test_the_editor_is_reachable_from_the_main_window(self):
        """A surface nobody can open is a surface nobody has."""
        import inspect

        from podharvest import gui

        source = inspect.getsource(gui)
        assert "EditorDialog" in source
        assert "Edit tags and chap" in source

    def test_the_editor_has_an_accelerator(self):
        import inspect

        from podharvest import gui

        accelerators = inspect.getsource(gui.MainFrame._build_accelerators)
        assert "_menu_edit_tags" in accelerators
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_editor.py -q -k Reachability`
Expected: FAIL — neither name appears in `gui.py`.

- [ ] **Step 3: Add the menu item and the accelerator**

In `_build_menubar`, in the menu that already holds "Go to episode list", add:

```python
        self._menu_edit_tags = view_menu.Append(
            wx.ID_ANY, "&Edit tags and chapters...\tCtrl+T",
            "Open the selected episode's audio in the Tag and Chapter Editor")
        self.Bind(wx.EVT_MENU, self._on_edit_tags, self._menu_edit_tags)
```

In `_build_accelerators`, add to the table:

```python
            (wx.ACCEL_CTRL, ord("T"), self._menu_edit_tags.GetId()),
```

Ctrl+T is free today — confirm against the whole table before committing to it.

- [ ] **Step 4: Open the editor on the selected episode**

Bind activation on the list, beside where it is created:

```python
        self.episode_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED,
                               lambda _e: self._on_edit_tags(None))
```

and add the handler:

```python
    def _on_edit_tags(self, _evt) -> None:
        """Open the highlighted episode's audio in the Tag and Chapter Editor."""
        from podharvest import chapters as chapters_mod
        from podharvest import tags as tags_mod
        from podharvest.editor import EditorDialog

        path = self._selected_episode_audio()
        if path is None:
            wx.MessageBox(
                "Select an episode that has been downloaded first. The editor "
                "works on the audio file, so there has to be one.",
                "Nothing to edit", wx.OK | wx.ICON_INFORMATION, self)
            return
        if not tags_mod.is_taggable(path):
            wx.MessageBox(
                f"{path.name} is not a file type this editor can tag. MP3, "
                "M4A, M4B and MP4 can be edited; the others are left alone "
                "rather than half-supported.",
                "Cannot edit this file", wx.OK | wx.ICON_INFORMATION, self)
            return
        with EditorDialog(self, path) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            tags_mod.write_tags(path, dlg.result_tags())
            chapters_mod.embed_chapter_objects(path, dlg.result_chapters())
```

Add `_selected_episode_audio`, which reads the highlighted row's index out of `self._episode_rows`, resolves the episode's folder and stem from the run's output directory, and calls `tags_mod.audio_for_episode`. Follow whatever the existing progress plumbing already knows about an episode's on-disk name rather than re-deriving it.

- [ ] **Step 5: Add `embed_chapter_objects`**

In `podharvest/chapters.py`:

```python
def embed_chapter_objects(audio_path: Path, chapters: list) -> bool:
    """Write a `Chapter` list (the editor's shape) into *audio_path*.

    `embed_chapters` takes the (seconds, name) pairs the harvest pipeline
    produces; the editor works in `Chapter` objects with real end times. This
    is the same write, entered from the other side, and it keeps the same
    never-raises contract.
    """
    if not chapters:
        return False
    pairs = [(c.start_ms // 1000, c.title) for c in chapters]
    total_seconds = chapters[-1].end_ms / 1000.0
    return embed_chapters(Path(audio_path), pairs, total_seconds)
```

Note the lossy step: `embed_chapters` works in whole seconds, so a marker nudged to 9.5 s would round to 9 s. For the editor path that is wrong — the whole point of the nudge is sub-second precision. So `embed_chapter_objects` must **not** go through the pair-based API. Write it against the shared writer directly instead:

```python
def embed_chapter_objects(audio_path: Path, chapters: list) -> bool:
    """Write a `Chapter` list into *audio_path*, keeping millisecond precision.

    Deliberately not routed through `embed_chapters`: that entry point takes
    whole seconds, which is right for chapters a language model proposed and
    wrong for a boundary somebody nudged to the half second by ear.
    """
    audio_path = Path(audio_path)
    if not chapters or not audio_path.is_file():
        return False
    if audio_path.suffix.lower() not in IN_PLACE_SUFFIXES:
        seconds = [(c.start_ms // 1000, c.title) for c in chapters]
        return embed_chapters(audio_path, seconds, chapters[-1].end_ms / 1000.0)
    from podharvest import audio_tags_core as core

    try:
        core.write_mp3_chapters(audio_path, list(chapters))
    except Exception as exc:  # noqa: BLE001 - a chapterless podcast is still fine
        LOG.warning("Could not write chapter markers to %s: %s", audio_path.name, exc)
        return False
    LOG.info("Wrote %d chapter marker(s) to %s.", len(chapters), audio_path.name)
    return True
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add podharvest/gui.py podharvest/chapters.py tests/test_editor.py
git commit -m "feat: open the Tag and Chapter Editor from the episode list"
```

---

### Task 8: Prove the two apps agree, and say so in the docs

**Files:**
- Create: `tests/test_alignment.py`
- Modify: `README.md`, `CHANGELOG.md`, `docs/GETTING_STARTED.md`

The alignment claim is only worth anything if something checks it. This task writes the check and then documents the feature for the people who will use it.

- [ ] **Step 1: Write the conformance test**

Create `tests/test_alignment.py`:

```python
"""Proof that podHarvest writes what QUILL Audio Studio writes.

The alignment contract (docs/ALIGNMENT-audio-tags-and-chapters.md) promises
that a file edited in either app is indistinguishable from one edited in the
other. These are the assertions behind that sentence.
"""

from __future__ import annotations

import pytest

from podharvest import audio_tags_core as core

mutagen_id3 = pytest.importorskip("mutagen.id3")


@pytest.fixture
def episode(tmp_path):
    path = tmp_path / "episode.mp3"
    path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 40)
    return path


def _chapters():
    return [
        core.Chapter(index=0, title="Opening", start_ms=0, end_ms=9_500),
        core.Chapter(index=1, title="The interview", start_ms=9_500, end_ms=30_000),
    ]


class TestChapterFrames:
    def test_element_ids_follow_the_contract(self, episode):
        core.write_mp3_chapters(episode, _chapters())
        frames = mutagen_id3.ID3(str(episode))
        assert sorted(f.element_id for f in frames.getall("CHAP")) == ["ch0", "ch1"]
        assert [f.element_id for f in frames.getall("CTOC")] == ["toc"]

    def test_millisecond_precision_survives(self, episode):
        core.write_mp3_chapters(episode, _chapters())
        assert core.read_mp3_chapters(episode)[1].start_ms == 9_500

    def test_writing_twice_is_idempotent(self, episode):
        core.write_mp3_chapters(episode, _chapters())
        first = episode.read_bytes()
        core.write_mp3_chapters(episode, _chapters())
        assert episode.read_bytes() == first


class TestId3Version:
    def test_stays_at_2_3_for_ordinary_tags(self, episode):
        tags = core.AudioTags()
        tags.set("album", "The Show")
        core.write_tags(episode, tags)
        assert episode.read_bytes()[3] == 3

    def test_moves_to_2_4_once_a_sort_field_is_set(self, episode):
        tags = core.AudioTags()
        tags.set("album", "The Show")
        tags.set("album_sort", "Show, The")
        core.write_tags(episode, tags)
        assert episode.read_bytes()[3] == 4


class TestTagsAndChaptersCoexist:
    def test_writing_tags_does_not_disturb_the_chapters(self, episode):
        core.write_mp3_chapters(episode, _chapters())
        tags = core.AudioTags()
        tags.set("album", "The Show")
        core.write_tags(episode, tags)
        assert [c.title for c in core.read_mp3_chapters(episode)] == [
            "Opening", "The interview"]

    def test_writing_chapters_does_not_disturb_the_tags(self, episode):
        tags = core.AudioTags()
        tags.set("album", "The Show")
        core.write_tags(episode, tags)
        core.write_mp3_chapters(episode, _chapters())
        assert core.read_tags(episode).get("album") == "The Show"
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_alignment.py -q`
Expected: PASS. `test_writing_twice_is_idempotent` is the one most likely to fail — if mutagen stamps anything varying into the block, relax that assertion to compare the parsed chapter frames rather than raw bytes, and say so in the test's docstring.

- [ ] **Step 3: Document the feature**

In `README.md`, under "What you get", add a bullet after the chapter-markers one:

```markdown
- **Editable tags and chapters.** Select any downloaded episode and press
  Ctrl+T to open the Tag and Chapter Editor: every tag the file can carry,
  cover art included, and a chapter editor that lets you add, delete, retime
  and preview markers — nudging a boundary half a second at a time while you
  listen, until it lands where the sentence actually starts.
```

Add a short section explaining the alignment, because it is a promise to the user and not only to the code:

```markdown
## Shared with QUILL Audio Studio

podHarvest's tag and chapter editor is the same editor QUILL Audio Studio
has, sharing the same code: the same fields, the same operations, the same
keys. A file edited in one app is a file the other reads back exactly as it
was left. If you use both, you only have to learn this once.
```

In `CHANGELOG.md`, add an entry under the unreleased heading covering: the
editor, the tag support, the in-place MP3 chapter write (with its speed
consequence), and mutagen joining the GUI extra.

In `docs/GETTING_STARTED.md`, add a short "Fixing up an episode" section at
the point where the guide has finished the first run — that is when somebody
first has a file worth editing.

- [ ] **Step 4: Run everything**

```bash
python -m pytest -q
ruff check .
```

Expected: PASS and clean. Report the real counts.

- [ ] **Step 5: Commit**

```bash
git add tests/test_alignment.py README.md CHANGELOG.md docs/GETTING_STARTED.md
git commit -m "test: prove podHarvest and QUILL write identical tags and chapters"
```

---

## Manual verification

The gates prove the code is well-formed. Only this proves the two apps agree.

1. Harvest one episode in podHarvest with chapters enabled.
2. Open it with Ctrl+T. Set a title, an album, a sort album and a cover
   image. Add a chapter, nudge its start back half a second five times, press
   Hear boundary, then save.
3. Open the *same file* in QUILL Audio Studio's Chapter Workbench. Confirm
   every tag reads back, the cover art is there, and the chapter you added
   sits at the exact millisecond podHarvest left it.
4. Change one field in QUILL, save, and reopen in podHarvest. Confirm the
   round trip is clean in that direction too.
5. Confirm the ID3 version went to 2.4 (because of the sort field) and that
   both apps are content with it.

If step 3 or 4 shows any difference, the shared module has drifted or an
adapter is doing something the other's is not. Fix it in the shared module,
re-record both digests, and re-run this list.
