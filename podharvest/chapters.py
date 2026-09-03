"""Writing chapter markers into the audio file itself.

A chapter list in a summary file is useful to read. A chapter list *inside the
MP3* is useful to listen to: podcast players (Apple Podcasts, Overcast, Pocket
Casts, VLC, and anything else that reads ID3) show it as a navigable list, so
an episode can be skimmed by topic with the player's own next-chapter control
rather than by scrubbing a progress bar. For someone using a screen reader,
that is the difference between a browsable episode and an hour-long blob.

For an MP3 the markers go straight into the ID3 tag block: adding a hundred
bytes does not justify copying a sixty-megabyte episode, and the frames are
written by the model shared byte-for-byte with QUILL Audio Studio (see
docs/ALIGNMENT-audio-tags-and-chapters.md), so a file chaptered here and a
file chaptered there are the same file.

Every other container still goes through a lossless ffmpeg re-mux -- the audio
stream is copied, never re-encoded -- to a temporary file that only replaces
the original once ffmpeg has succeeded, so an interrupted write cannot leave a
truncated podcast episode behind.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from podharvest.util import LOG

#: Containers whose metadata can carry chapters. Anything else is left alone
#: rather than silently re-muxed into a format the user did not ask for.
SUPPORTED_SUFFIXES = {".mp3", ".m4a", ".m4b", ".mp4", ".ogg", ".opus"}


def _escape(value: str) -> str:
    """Escape the characters ffmpeg's metadata format treats as special."""
    out = []
    for char in value:
        if char in "=;#\\\n":
            out.append("\\")
        out.append(char)
    return "".join(out)


def build_metadata(chapters: list[tuple[int, str]], total_seconds: float,
                   title: str = "") -> str:
    """Render chapters into ffmpeg's FFMETADATA format."""
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={_escape(title)}")
    for index, (start, name) in enumerate(chapters):
        end = chapters[index + 1][0] if index + 1 < len(chapters) else int(total_seconds)
        if end <= start:
            continue
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000",
                  f"START={int(start * 1000)}", f"END={int(end * 1000)}",
                  f"title={_escape(name)}"]
    return "\n".join(lines) + "\n"


#: Containers mutagen can chapter in place. Everything else in
#: SUPPORTED_SUFFIXES still takes the ffmpeg route.
IN_PLACE_SUFFIXES = {".mp3"}


def _embed_in_place(audio_path: Path, chapters: list[tuple[int, str]],
                    total_seconds: float) -> bool:
    """Write ID3 chapter frames straight into the tag block. No re-mux.

    Returns False (never raises) when mutagen is missing, which is the case on
    a command-line-only install: a podcast that failed to gain chapter markers
    is still a perfectly good podcast.
    """
    from podharvest import audio_tags_core as core

    marks: list = []
    for index, (start, name) in enumerate(chapters):
        end = (chapters[index + 1][0] if index + 1 < len(chapters)
               else int(total_seconds))
        if end <= start:
            continue
        marks.append(core.Chapter(index=len(marks), title=name,
                                  start_ms=int(start * 1000),
                                  end_ms=int(end * 1000)))
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


def embed_chapter_objects(audio_path: Path, chapters: list) -> bool:
    """Write a `Chapter` list -- the editor's shape -- into *audio_path*.

    Deliberately not routed through `embed_chapters`: that entry point takes
    whole seconds, which is right for chapters a language model proposed from
    a transcript and wrong for a boundary somebody nudged to the half second
    by ear. Same never-raises contract.
    """
    audio_path = Path(audio_path)
    if not chapters or not audio_path.exists():
        return False
    if audio_path.suffix.lower() not in IN_PLACE_SUFFIXES:
        pairs = [(c.start_ms // 1000, c.title) for c in chapters]
        return embed_chapters(audio_path, pairs, chapters[-1].end_ms / 1000.0)
    from podharvest import audio_tags_core as core

    try:
        core.write_mp3_chapters(audio_path, list(chapters))
    except Exception as exc:  # noqa: BLE001 - a chapterless podcast is still fine
        LOG.warning("Could not write chapter markers to %s: %s", audio_path.name, exc)
        return False
    LOG.info("Wrote %d chapter marker(s) to %s.", len(chapters), audio_path.name)
    return True


def embed_chapters(audio_path: Path, chapters: list[tuple[int, str]],
                   total_seconds: float, *, title: str = "") -> bool:
    """Write `chapters` into `audio_path` in place. Returns True when written.

    Never raises: a podcast that failed to gain chapter markers is still a
    perfectly good podcast, so every failure is logged and shrugged off.
    """
    if not chapters:
        return False
    audio_path = Path(audio_path)
    if audio_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        LOG.info("Not adding chapters to %s: that file type does not carry them.",
                 audio_path.name)
        return False
    if not audio_path.exists():
        return False
    if audio_path.suffix.lower() in IN_PLACE_SUFFIXES:
        return _embed_in_place(audio_path, chapters, total_seconds)

    from podharvest.hardware import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        LOG.warning("ffmpeg is needed to add chapter markers to the audio; skipping.")
        return False

    meta_path = audio_path.with_suffix(audio_path.suffix + ".chapters.txt")
    # The scratch file keeps the real extension: ffmpeg picks its output format
    # from the filename, and a name ending in ".tmp" makes it give up with
    # "Unable to choose an output format".
    temp_path = audio_path.with_name(f"{audio_path.stem}.chaptered{audio_path.suffix}")
    try:
        meta_path.write_text(build_metadata(chapters, total_seconds, title),
                             encoding="utf-8", newline="\n")
        proc = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(audio_path), "-i", str(meta_path),
             "-map_metadata", "1", "-map_chapters", "1", "-codec", "copy",
             str(temp_path)],
            capture_output=True, text=True)
        if proc.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
            LOG.warning("Could not add chapter markers to %s: %s",
                        audio_path.name, (proc.stderr or "").strip()[:200])
            return False
        # Only now is it safe to lose the original.
        os.replace(temp_path, audio_path)
        LOG.info("Added %d chapter marker(s) to %s, so a podcast player can jump "
                 "between topics.", len(chapters), audio_path.name)
        return True
    except OSError as exc:
        LOG.warning("Could not add chapter markers to %s: %s", audio_path.name, exc)
        return False
    finally:
        meta_path.unlink(missing_ok=True)
        temp_path.unlink(missing_ok=True)


def read_chapters(audio_path: Path) -> list[tuple[float, float, str]]:
    """Read chapters back out of an audio file, for checking what was written.

    MP3s are read from their own ID3 frames rather than through ffprobe. They
    are *written* that way -- `_embed_in_place` rewrites the tag block with
    mutagen and never touches the audio -- so reading them any other way made
    this asymmetric: a file whose markers had just been written successfully
    read back as having none on a machine with no FFmpeg. Everything else
    still goes through ffprobe, which is the only thing that understands the
    other containers.
    """
    import json

    audio_path = Path(audio_path)
    if audio_path.suffix.lower() in IN_PLACE_SUFFIXES:
        try:
            from podharvest import audio_tags_core as core

            return [(chapter.start_ms / 1000.0, chapter.end_ms / 1000.0,
                     chapter.title)
                    for chapter in core.read_mp3_chapters(audio_path)]
        except Exception as exc:  # noqa: BLE001 - fall through to ffprobe
            LOG.debug("Could not read ID3 chapters from %s (%s); trying ffprobe.",
                      audio_path.name, exc)

    from podharvest.hardware import find_ffprobe
    ffprobe = find_ffprobe()
    if not ffprobe:
        return []
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_chapters",
         str(audio_path)], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    try:
        found = json.loads(proc.stdout).get("chapters", [])
    except ValueError:
        return []
    return [(float(c.get("start_time", 0)), float(c.get("end_time", 0)),
             c.get("tags", {}).get("title", "")) for c in found]
