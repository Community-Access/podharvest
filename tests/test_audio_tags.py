"""The shared tag and chapter model: the table, the files, and the vendoring gate.

`podharvest/audio_tags_core.py` is vendored byte-identical from QUILL
(`S:\\quill\\quill\\core\\speech\\audio_tags_core.py`). Most of what it does is
covered here from podHarvest's side too, deliberately rather than wastefully:
a bad copy is caught by the digest, but a *stale* copy that still hashes
correctly against a stale digest is caught only by tests that exercise the
behaviour both apps depend on.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from podharvest import audio_tags_core as core

MODULE = Path(core.__file__)
DIGEST_FILE = MODULE.with_suffix(".sha256")

_PNG_1X1 = bytes.fromhex(
    # A real 1x1 red PNG. The hex that used to sit here had a truncated
    # IDAT, so wx refused it and every cover-art test popped an
    # "Unknown image data format" box -- which is how the modal was found.
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae426082"
)
_JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def episode_mp3(tmp_path):
    """A minimal valid MP3, standing in for a downloaded episode."""
    path = tmp_path / "0001 - An Episode.mp3"
    path.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 4)
    return path


def three():
    return [
        core.Chapter(index=0, title="One", start_ms=0, end_ms=10_000),
        core.Chapter(index=1, title="Two", start_ms=10_000, end_ms=20_000),
        core.Chapter(index=2, title="Three", start_ms=20_000, end_ms=30_000),
    ]


class TestVendoring:
    """The module is copied, not imported. Something has to notice drift."""

    def test_the_shared_module_has_not_drifted(self):
        expected = DIGEST_FILE.read_text(encoding="utf-8").split()[0].strip()
        actual = hashlib.sha256(MODULE.read_bytes()).hexdigest()
        assert actual == expected, (
            "audio_tags_core.py has changed. Copy the new file to "
            "quill/core/speech/audio_tags_core.py, update the digest in both "
            "repos, or podHarvest and QUILL have silently diverged."
        )

    def test_it_imports_nothing_from_either_host(self):
        """Byte-identity only holds while it depends on neither package.

        Checks import statements, not mentions: the docstring names both
        repositories on purpose, and should.
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in {"quill", "podharvest"}, name

    def test_it_imports_mutagen_lazily(self):
        """The CLI promise: importing this module must not need mutagen."""
        for line in MODULE.read_text(encoding="utf-8").splitlines():
            if line.startswith(("import mutagen", "from mutagen")):
                pytest.fail(f"top-level mutagen import: {line!r}")

    def test_the_line_endings_are_pinned(self):
        """`* text=auto eol=lf` would rewrite this file and break the digest."""
        attributes = (MODULE.parent.parent / ".gitattributes").read_text(encoding="utf-8")
        assert "podharvest/audio_tags_core.py -text" in attributes


class TestFieldTable:
    def test_there_are_twenty_six_fields(self):
        assert len(core.TAG_FIELDS) == 26

    def test_keys_and_frames_and_atoms_are_unique(self):
        assert len({f.key for f in core.TAG_FIELDS}) == 26
        assert len({f.id3 for f in core.TAG_FIELDS}) == 26
        atoms = [f.mp4 for f in core.TAG_FIELDS if f.mp4]
        assert len(atoms) == len(set(atoms))

    def test_mnemonics_are_unique_within_each_page(self):
        for group, _label in core.GROUPS:
            letters = [
                f.label[f.label.index("&") + 1].lower()
                for f in core.fields_in(group)
                if "&" in f.label
            ]
            assert len(letters) == len(set(letters)), f"duplicate in {group}"

    def test_every_field_explains_itself(self):
        for field in core.TAG_FIELDS:
            assert field.help.endswith("."), f"{field.key} help is not a sentence"
            assert field.kind in {"text", "number", "pair", "multiline", "bool"}


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

    def test_an_unknown_key_is_rejected(self):
        with pytest.raises(KeyError):
            core.AudioTags().set("not_a_tag", "x")


class TestTimeFormatting:
    def test_the_precise_format_shows_milliseconds(self):
        assert core.format_time_precise(9_500) == "0:00:09.500"
        assert core.format_time_precise(3_725_010) == "1:02:05.010"

    def test_parse_accepts_what_a_person_types(self):
        assert core.parse_time("0:00:09.500") == 9_500
        assert core.parse_time("2:30") == 150_000
        assert core.parse_time("90") == 90_000

    def test_parse_rejects_what_is_not_a_time(self):
        assert core.parse_time("banana") is None
        assert core.parse_time("") is None


class TestChapterOperations:
    def test_add_splits_the_chapter_holding_the_point(self):
        result = core.add_chapter(three(), 15_000, title="Middle")
        assert [c.title for c in result] == ["One", "Two", "Middle", "Three"]
        assert result[2].start_ms == 15_000

    def test_add_appends_past_the_end(self):
        assert core.add_chapter(three(), 30_000, title="Outro")[-1].title == "Outro"

    def test_add_refuses_a_sliver(self):
        with pytest.raises(core.ChapterEditError):
            core.add_chapter(three(), 10_500, min_part_ms=1000)

    def test_delete_keeps_the_timeline_covered(self):
        for index in range(3):
            result = core.delete_chapter(three(), index)
            assert result[0].start_ms == 0
            assert result[-1].end_ms == 30_000
            for a, b in zip(result, result[1:], strict=False):
                assert a.end_ms == b.start_ms

    def test_the_only_chapter_cannot_be_deleted(self):
        with pytest.raises(core.ChapterEditError):
            core.delete_chapter([core.Chapter(0, "All", 0, 10_000)], 0)

    def test_bounds_move_both_edges_and_the_neighbours(self):
        result = core.set_chapter_bounds(three(), 1, 8_000, 22_000)
        assert (result[0].end_ms, result[1].start_ms) == (8_000, 8_000)
        assert (result[1].end_ms, result[2].start_ms) == (22_000, 22_000)

    def test_bounds_reject_an_inverted_range(self):
        with pytest.raises(core.ChapterEditError):
            core.set_chapter_bounds(three(), 1, 20_000, 10_000)


class TestNudge:
    def test_the_steps_are_the_ones_the_contract_names(self):
        assert core.NUDGE_STEPS_MS == (100, 250, 500, 1000, 2000, 5000, 10_000)

    def test_it_moves_the_boundary_and_reports_the_delta(self):
        result, applied = core.nudge_chapter_start(three(), 1, -500)
        assert applied == -500
        assert result[1].start_ms == 9_500
        assert result[0].end_ms == 9_500

    def test_it_clamps_instead_of_raising(self):
        """A nudge is a held key: running into the wall stops, it does not throw."""
        result, applied = core.nudge_chapter_start(three(), 1, -60_000)
        assert applied == -9_500
        assert result[1].start_ms == 500

    def test_it_reports_zero_when_it_cannot_move(self):
        pinned = [core.Chapter(0, "One", 0, 500), core.Chapter(1, "Two", 500, 1_000)]
        _result, applied = core.nudge_chapter_start(pinned, 1, -1_000)
        assert applied == 0

    def test_the_first_chapter_is_pinned_to_the_beginning(self):
        with pytest.raises(core.ChapterEditError):
            core.nudge_chapter_start(three(), 0, 500)


class TestCoverArt:
    def test_the_bytes_are_sniffed_not_the_extension(self, tmp_path):
        path = tmp_path / "actually_a_png.jpg"
        path.write_bytes(_PNG_1X1)
        assert core.load_cover(path).mime == "image/png"

    def test_jpeg_is_accepted(self, tmp_path):
        path = tmp_path / "art.jpg"
        path.write_bytes(_JPEG_HEAD)
        assert core.load_cover(path).mime == "image/jpeg"

    def test_a_non_image_is_refused(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_bytes(b"this is not a picture")
        with pytest.raises(core.TagReadError, match="JPEG or PNG"):
            core.load_cover(path)

    def test_an_oversized_image_is_refused(self, tmp_path):
        path = tmp_path / "huge.png"
        path.write_bytes(_PNG_1X1 + b"\x00" * core.MAX_COVER_BYTES)
        with pytest.raises(core.TagReadError, match="8 MB"):
            core.load_cover(path)

    def test_describe_is_something_a_screen_reader_can_use(self):
        assert core.describe_cover(None) == "No cover art."
        text = core.describe_cover(core.CoverArt(data=_PNG_1X1, mime="image/png"))
        assert "PNG" in text and "bytes" in text


class TestFileRoundTrip:
    """Everything below needs mutagen, which is part of the GUI extra."""

    def test_every_text_field_survives_a_write(self, episode_mp3):
        pytest.importorskip("mutagen")
        tags = core.AudioTags()
        for field in core.TAG_FIELDS:
            if field.kind in {"text", "multiline"}:
                tags.set(field.key, f"value for {field.key}")
        tags.set("year", "2026")
        tags.set("original_date", "1998")
        tags.set("track", "7/40")
        tags.set("disc", "1/2")
        tags.set("bpm", "90")
        tags.set("compilation", "1")
        core.write_tags(episode_mp3, tags)
        back = core.read_tags(episode_mp3)
        for field in core.TAG_FIELDS:
            assert back.get(field.key) == tags.get(field.key), field.key

    def test_an_untagged_episode_reads_as_empty_not_an_error(self, episode_mp3):
        pytest.importorskip("mutagen")
        assert core.read_tags(episode_mp3).values == {}

    def test_cover_art_survives(self, episode_mp3):
        pytest.importorskip("mutagen")
        tags = core.AudioTags()
        tags.cover = core.CoverArt(data=_PNG_1X1, mime="image/png")
        core.write_tags(episode_mp3, tags)
        back = core.read_tags(episode_mp3).cover
        assert back is not None and back.data == _PNG_1X1

    def test_a_missing_file_is_refused_not_created(self, tmp_path):
        pytest.importorskip("mutagen")
        with pytest.raises(core.TagReadError):
            core.read_tags(tmp_path / "gone.mp3")
        with pytest.raises(core.TagWriteError):
            core.write_tags(tmp_path / "gone.mp3", core.AudioTags())


class TestAlignment:
    """The promise: a file edited in either app is the same file."""

    def _two(self):
        return [
            core.Chapter(index=0, title="Opening", start_ms=0, end_ms=9_500),
            core.Chapter(index=1, title="The interview", start_ms=9_500, end_ms=30_000),
        ]

    def test_element_ids_match_what_ffmpeg_and_quill_write(self, episode_mp3):
        id3mod = pytest.importorskip("mutagen.id3")
        core.write_mp3_chapters(episode_mp3, self._two())
        frames = id3mod.ID3(str(episode_mp3))
        assert sorted(f.element_id for f in frames.getall("CHAP")) == ["ch0", "ch1"]
        assert [f.element_id for f in frames.getall("CTOC")] == ["toc"]

    def test_millisecond_precision_survives(self, episode_mp3):
        pytest.importorskip("mutagen")
        core.write_mp3_chapters(episode_mp3, self._two())
        assert core.read_mp3_chapters(episode_mp3)[1].start_ms == 9_500

    def test_ordinary_tags_stay_at_id3_2_3(self, episode_mp3):
        pytest.importorskip("mutagen")
        tags = core.AudioTags()
        tags.set("album", "The Show")
        core.write_tags(episode_mp3, tags)
        assert episode_mp3.read_bytes()[3] == 3

    def test_a_sort_field_moves_the_file_to_2_4(self, episode_mp3):
        pytest.importorskip("mutagen")
        tags = core.AudioTags()
        tags.set("album", "The Show")
        tags.set("album_sort", "Show, The")
        core.write_tags(episode_mp3, tags)
        assert episode_mp3.read_bytes()[3] == 4

    def test_tags_and_chapters_do_not_disturb_each_other(self, episode_mp3):
        pytest.importorskip("mutagen")
        core.write_mp3_chapters(episode_mp3, self._two())
        tags = core.AudioTags()
        tags.set("album", "The Show")
        core.write_tags(episode_mp3, tags)
        assert [c.title for c in core.read_mp3_chapters(episode_mp3)] == [
            "Opening",
            "The interview",
        ]
        core.write_mp3_chapters(episode_mp3, self._two())
        assert core.read_tags(episode_mp3).get("album") == "The Show"
