"""What is already in your library, so you can go back to it.

The Episodes list was a progress view: it filled as a run went and emptied when
podHarvest closed. That is fine while you are watching a harvest and useless
the next day, when what you want is the thing you harvested. This module reads
the output folder back.

The source of truth is each show folder's `feed.json`, which a harvest already
writes and which records every episode with its downloaded path. Reading that
beats guessing from filenames: the naming template is configurable, so two
installs can produce different names for the same episode, and a scanner that
inferred titles from slugs would get them subtly wrong for exactly the shows
with interesting titles.

A folder with no `feed.json` -- an interrupted first run, or a folder somebody
assembled by hand -- still yields its audio files, named from the file. Half a
library is better than an empty one, and the honest thing is to show what is
actually there.

Nothing here is expensive: it reads one JSON file per show and stats a handful
of paths. wx-free and testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from podharvest.util import LOG

#: Audio extensions a harvest can leave behind, best first.
AUDIO_SUFFIXES = (".mp3", ".m4a", ".m4b", ".mp4", ".ogg", ".opus", ".wav")

#: Where a harvest puts each kind of thing, relative to the show folder.
TRANSCRIPTS_DIR = "transcripts"

#: A transcript file this small is a stub, not a transcript.
MIN_TRANSCRIPT_BYTES = 64


@dataclass(slots=True)
class LibraryEpisode:
    """One episode as it exists on disk, and what came with it."""

    title: str
    show: str
    slug: str = ""
    published: datetime | None = None
    audio: Path | None = None
    transcript: Path | None = None
    summary: Path | None = None
    duration_seconds: int | None = None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def has_transcript(self) -> bool:
        return self.transcript is not None

    def what_it_has(self) -> str:
        """A short readout of what exists for this episode.

        Read aloud on every row, so it is words rather than ticks and crosses,
        and it says what is *there* rather than what is missing -- a list of
        absences on every row is a list nobody wants read to them.
        """
        parts = [name for name, present in (
            ("audio", self.has_audio),
            ("transcript", self.has_transcript),
            ("summary", self.summary is not None),
        ) if present]
        if not parts:
            return "nothing downloaded"
        if len(parts) == 1:
            return parts[0]
        return f"{', '.join(parts[:-1])} and {parts[-1]}"


@dataclass(slots=True)
class Show:
    """One podcast folder, and the episodes in it."""

    title: str
    folder: Path
    episodes: list[LibraryEpisode] = field(default_factory=list)


def _parse_when(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _first_existing(folder: Path, stem: str, suffixes: tuple[str, ...]) -> Path | None:
    for suffix in suffixes:
        candidate = folder / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _transcript_for(show_folder: Path, stem: str) -> Path | None:
    """The transcript for this episode, if a real one was written."""
    folder = show_folder / TRANSCRIPTS_DIR
    for suffix in (".md", ".txt"):
        candidate = folder / f"{stem}{suffix}"
        try:
            if candidate.is_file() and candidate.stat().st_size >= MIN_TRANSCRIPT_BYTES:
                return candidate
        except OSError:  # pragma: no cover - a stat that fails is "not there"
            continue
    return None


def _summary_for(show_folder: Path, stem: str) -> Path | None:
    """The summary file, which enrichment writes beside the transcript."""
    folder = show_folder / TRANSCRIPTS_DIR
    for name in (f"{stem}.summary.md", f"{stem}-summary.md"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def _audio_from_entry(entry: dict, show_folder: Path) -> Path | None:
    """The downloaded audio a feed.json entry points at, if it is still there.

    The recorded path is trusted first and checked second: a library that
    silently listed files that have been deleted would offer a Play button
    that cannot work.
    """
    for enclosure in entry.get("enclosures") or []:
        if not isinstance(enclosure, dict):
            continue
        local = str(enclosure.get("local_path") or "")
        if local and Path(local).is_file():
            return Path(local)
    return None


def _episodes_from_feed_json(show_folder: Path, show_title: str) -> list[LibraryEpisode]:
    path = show_folder / "feed.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOG.debug("Could not read %s (%s); falling back to a file scan.", path, exc)
        return []
    entries = data.get("episodes")
    if not isinstance(entries, list):
        return []

    episodes: list[LibraryEpisode] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "(untitled)")
        audio = _audio_from_entry(entry, show_folder)
        stem = audio.stem if audio is not None else ""
        transcript = _transcript_for(show_folder, stem) if stem else None
        summary = _summary_for(show_folder, stem) if stem else None
        duration = entry.get("duration_seconds")
        episodes.append(LibraryEpisode(
            title=title,
            show=show_title,
            slug=stem,
            published=_parse_when(entry.get("published")),
            audio=audio,
            transcript=transcript,
            summary=summary,
            duration_seconds=duration if isinstance(duration, int) else None,
        ))
    return episodes


def _episodes_from_files(show_folder: Path, show_title: str) -> list[LibraryEpisode]:
    """Whatever audio is in the folder, named from the file.

    The fallback for a folder with no `feed.json`. Titles come out as the file
    stem, which is worse than the real title and much better than nothing.
    """
    episodes: list[LibraryEpisode] = []
    for path in sorted(show_folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        episodes.append(LibraryEpisode(
            title=path.stem,
            show=show_title,
            slug=path.stem,
            audio=path,
            transcript=_transcript_for(show_folder, path.stem),
            summary=_summary_for(show_folder, path.stem),
        ))
    return episodes


def scan_show(show_folder: Path) -> Show | None:
    """One show folder, or None when it does not look like one."""
    folder = Path(show_folder)
    if not folder.is_dir():
        return None
    title = folder.name
    feed_json = folder / "feed.json"
    if feed_json.is_file():
        try:
            data = json.loads(feed_json.read_text(encoding="utf-8"))
            title = str(data.get("title") or title)
        except (OSError, ValueError):
            pass
    episodes = _episodes_from_feed_json(folder, title)
    if not episodes:
        episodes = _episodes_from_files(folder, title)
    if not episodes:
        return None
    return Show(title=title, folder=folder, episodes=episodes)


def scan(output_dir: Path) -> list[Show]:
    """Every show in the output folder, newest-titled first. Never raises."""
    root = Path(output_dir)
    if not root.is_dir():
        return []
    shows: list[Show] = []
    try:
        candidates = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError as exc:
        LOG.debug("Could not read the output folder (%s).", exc)
        return []
    for folder in candidates:
        try:
            show = scan_show(folder)
        except Exception as exc:  # noqa: BLE001 - one bad folder is not fatal
            LOG.debug("Skipping %s (%s).", folder, exc)
            continue
        if show is not None:
            shows.append(show)
    return shows


def all_episodes(output_dir: Path) -> list[LibraryEpisode]:
    """Every episode across every show, newest first.

    Newest first because the thing you want is almost always the thing you
    harvested most recently. Episodes with no date sort last rather than
    pretending to be old.
    """
    episodes: list[LibraryEpisode] = []
    for show in scan(output_dir):
        episodes.extend(show.episodes)
    dated = [e for e in episodes if e.published is not None]
    undated = [e for e in episodes if e.published is None]
    dated.sort(key=lambda e: e.published, reverse=True)
    return dated + undated
