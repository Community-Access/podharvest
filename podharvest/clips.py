"""Cutting a passage out of an episode, by reading rather than by scrubbing.

The usual way to make a clip is to drag across a waveform, which is no way
at all if you cannot see one. Here the selection is made in the transcript --
the text you can read, search and arrow through -- and the audio follows
from the timings.

Re-encoding rather than stream-copying is deliberate: a copy can only cut on
a keyframe, so the clip would begin up to several seconds away from the word
you chose, which is exactly the precision this exists to provide.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from podharvest.util import LOG

#: Fade applied to both ends, in milliseconds. Short enough not to swallow a
#: word, long enough that the clip does not begin with a click.
DEFAULT_FADE_MS = 120

#: The longest a generated filename may be before its extension. Windows
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
    stem = f"{episode_title} - {words}" if words else (episode_title or "clip")
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
