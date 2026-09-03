"""Reading and writing an episode's tags, the way podHarvest likes to fail.

The rules about what a tag is, which frame it lives in and how it is written
all live in `podharvest.audio_tags_core`, shared byte-for-byte with QUILL
Audio Studio so the two apps cannot drift. This module is the thin layer
around it: it finds the audio file belonging to an episode, and it turns the
shared module's exceptions into a logged warning and a False, because a tag
edit that failed should never take the app down with it.

mutagen is imported only inside the shared module's functions, and only the
GUI ever calls in here, so `podharvest fetch` still runs on the standard
library alone.
"""

from __future__ import annotations

from pathlib import Path

from podharvest import audio_tags_core as core
from podharvest.util import LOG, slugify

#: The audio extensions a harvested episode can arrive in, best first.
AUDIO_SUFFIXES = (".mp3", ".m4a", ".m4b", ".mp4", ".ogg", ".opus", ".wav")

#: The subset this editor can actually tag. The rest are left alone rather
#: than half-supported: an editor that silently drops half of what you typed
#: is worse than one that says it cannot help.
TAGGABLE_SUFFIXES = (".mp3", ".m4a", ".m4b", ".mp4")


def audio_for_episode(folder: Path, stem: str) -> Path | None:
    """The audio file for an episode, given its folder and the shared stem.

    podHarvest names an episode's audio, transcript and notes from one stem,
    so the audio is found by trying the known extensions in order rather than
    by guessing from a directory listing.
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

    An unreadable tag block is logged and read as empty rather than raised: a
    file nobody has tagged yet is exactly the one somebody opens the editor to
    fix, and refusing to show it would be the wrong answer.
    """
    try:
        return core.read_tags(Path(path))
    except core.AudioTagError as exc:
        LOG.warning("Could not read the tags on %s: %s", Path(path).name, exc)
        return core.AudioTags()


def write_tags(path: Path, tags: core.AudioTags) -> bool:
    """Write *tags* onto *path*. True when written, False when it could not be.

    Frames this editor does not model -- the chapter markers above all -- are
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


def find_episode_audio(folder: Path, title: str) -> Path | None:
    """The audio file for the episode called *title*, somewhere under *folder*.

    The on-disk name comes from a configurable template (`{date}-{slug}` by
    default), so it cannot be reconstructed from the title alone. What is
    stable is that the slug of the title appears in the stem, so that is what
    this looks for. Returns None rather than guessing when nothing matches or
    when more than one file does -- the caller then asks, which is better than
    opening the wrong episode.
    """
    slug = slugify(title)
    if not slug:
        return None
    matches = [
        path
        for path in sorted(Path(folder).rglob("*"))
        if path.is_file()
        and path.suffix.lower() in AUDIO_SUFFIXES
        and slug in path.stem.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        LOG.debug("%d audio files match %r; not guessing between them.",
                  len(matches), title)
    return None
