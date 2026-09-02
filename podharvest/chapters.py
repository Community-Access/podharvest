"""Writing chapter markers into the audio file itself.

A chapter list in a summary file is useful to read. A chapter list *inside the
MP3* is useful to listen to: podcast players (Apple Podcasts, Overcast, Pocket
Casts, VLC, and anything else that reads ID3) show it as a navigable list, so
an episode can be skimmed by topic with the player's own next-chapter control
rather than by scrubbing a progress bar. For someone using a screen reader,
that is the difference between a browsable episode and an hour-long blob.

The audio stream is copied, never re-encoded, so this is lossless and costs
about a hundred bytes. The rewrite goes to a temporary file that only replaces
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
    """Read chapters back out of an audio file, for checking what was written."""
    import json

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
