"""Audio you already have, given the same treatment as a harvested episode.

podHarvest was built around a feed: give it a URL, get back a library. But
everything it does after the download is about *a file* -- transcribe it,
summarise it, work out chapter markers, write them into the tags, play it back,
edit what is on it. None of that needs a feed, and requiring one shut out the
obvious use: a folder of recordings, an audiobook that came without chapters, a
podcast downloaded years ago, a lecture off a memory card.

So this module is the second way in. Point podHarvest at files or a folder and
they become the same episodes the rest of the app already knows how to handle.

**What it deliberately reuses.** The transcription batch, the summary pass, the
chapter inference, the reuse rules that skip work already done, the tag and
chapter editor, the transport -- all of it is the harvest code path, unchanged.
`podharvest.harvest.transcribe_all` was pulled out of `run_harvest` for exactly
this. Two implementations of "transcribe a batch of audio" would have drifted
within a release, and the local-files one would have been the poor relation.

**Where the output goes.** Beside the audio by default: ``lecture.mp3`` gets
``lecture.md``, ``lecture.txt`` and, if asked for, ``lecture.srt``. That is what
somebody who is tidying up their own files expects, and it keeps a file and its
transcript together when the folder is later moved. The alternative -- a
``Local files`` folder inside the harvest output directory -- is a setting, for
people who would rather podHarvest never wrote into their own folders.

**What it is not.** It does not copy, move, rename or convert your files. The
only writes to the audio itself are the tag and chapter edits you ask for, and
those rewrite the tag block rather than the audio.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from podharvest import tags as tags_mod
from podharvest.appspace import AppSpace
from podharvest.util import LOG, slugify

#: Everything worth offering in the file picker. Wider than the set podHarvest
#: can *tag* (`tags.TAGGABLE_SUFFIXES`) because transcribing a .wav is perfectly
#: reasonable even though there is nowhere on it to put a chapter marker.
AUDIO_SUFFIXES: tuple[str, ...] = (
    ".mp3", ".m4a", ".m4b", ".mp4", ".aac", ".ogg", ".oga", ".opus",
    ".flac", ".wav", ".wma", ".aiff", ".aif", ".webm",
)

#: The file-dialog wildcard, built from the list above so the two never differ.
WILDCARD = (
    "Audio files|" + ";".join(f"*{s}" for s in AUDIO_SUFFIXES)
    + "|All files|*.*"
)

#: The folder used when transcripts are not written beside the audio.
LOCAL_FOLDER_NAME = "Local files"

#: Refuse to walk a folder past this many files. A folder chosen by mistake
#: can be a whole drive, and a file dialog gives no warning about that.
MAX_SCAN = 5000


def is_audio(path: Path) -> bool:
    """Whether podHarvest will treat this file as audio."""
    return Path(path).suffix.lower() in AUDIO_SUFFIXES


def collect(paths: Iterable[Path], *, recursive: bool = True) -> list[Path]:
    """Every audio file in *paths*, expanding folders.

    Order is stable and predictable -- sorted, folders walked depth-first --
    because the list this produces is what the episode list shows, and a list
    that reorders itself between runs is hard to work with by keyboard.

    Duplicates are dropped: dragging in both a folder and a file inside it is
    an easy thing to do and should not transcribe that file twice.
    """
    found: list[Path] = []
    seen: set[str] = set()

    def add(candidate: Path) -> None:
        if not is_audio(candidate):
            return
        try:
            key = str(candidate.resolve()).lower()
        except OSError:  # pragma: no cover - an unresolvable path is still a path
            key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        found.append(candidate)

    for entry in paths:
        entry = Path(entry)
        if entry.is_dir():
            pattern = "**/*" if recursive else "*"
            try:
                for child in sorted(entry.glob(pattern)):
                    if len(found) >= MAX_SCAN:
                        LOG.warning(
                            "Stopping at %d files: '%s' holds more than podHarvest "
                            "will take in one go. Add a smaller folder, or a "
                            "selection of files.", MAX_SCAN, entry.name)
                        return found
                    if child.is_file():
                        add(child)
            except OSError as exc:
                LOG.warning("Could not read the folder '%s' (%s).", entry, exc)
        elif entry.is_file():
            add(entry)
        else:
            LOG.warning("There is nothing at '%s'; skipping it.", entry)
    return found


@dataclass
class LocalFile:
    """One local audio file, and what it already has.

    Built for the episode list: every field is something the list shows or the
    transport needs, so a row can be drawn without touching the disk again.
    """

    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_seconds: float = 0.0
    has_transcript: bool = False
    has_summary: bool = False
    chapter_count: int = 0
    taggable: bool = False

    @property
    def display_title(self) -> str:
        """What to call it. The tag if there is one, else the filename."""
        return self.title or self.path.stem

    def what_it_has(self) -> str:
        """A spoken-word summary for the episode list.

        Prose rather than a row of ticks: a screen reader reads this cell aloud
        with its column heading, and "transcript and 12 chapters" says more in
        the same breath than three columns of "yes" would.
        """
        parts: list[str] = []
        if self.has_transcript:
            parts.append("transcript")
        if self.has_summary:
            parts.append("summary")
        if self.chapter_count == 1:
            parts.append("1 chapter")
        elif self.chapter_count:
            parts.append(f"{self.chapter_count} chapters")
        if not parts:
            return "audio only"
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]


def describe(path: Path, *, beside: bool = True,
             output_dir: Path | None = None) -> LocalFile:
    """Read what *path* already carries, without ever raising.

    A file that cannot be read is still listed -- as itself, with nothing
    claimed about it. Dropping it silently would leave somebody looking for a
    file they know they added.
    """
    path = Path(path)
    item = LocalFile(path=path, taggable=tags_mod.is_taggable(path))
    try:
        tags = tags_mod.read_tags(path)
        item.title = tags.get("title")
        item.artist = tags.get("artist")
        item.album = tags.get("album")
    except Exception as exc:  # noqa: BLE001 - an unreadable tag block is not fatal
        LOG.debug("Could not read tags on %s: %s", path.name, exc)
    try:
        item.chapter_count = len(tags_mod.read_chapters(path))
    except Exception:  # noqa: BLE001
        item.chapter_count = 0
    item.duration_seconds = duration_of(path)

    out_dir, slug = transcript_location(
        path, beside=beside, output_dir=output_dir)
    from podharvest import reuse as reuse_mod

    item.has_transcript = reuse_mod.transcript_in(out_dir, slug) is not None
    item.has_summary = (out_dir / f"{slug}.summary.md").is_file()
    return item


def duration_of(path: Path) -> float:
    """How long the audio runs, in seconds. 0.0 when it cannot be read.

    Read from the file's own header via mutagen, which is a header read rather
    than a decode -- fast enough to do for every file in a folder as it is
    listed.
    """
    try:
        from mutagen import File as MutagenFile
    except ImportError:  # pragma: no cover - mutagen ships with podHarvest
        return 0.0
    try:
        media = MutagenFile(str(path))
        return float(getattr(getattr(media, "info", None), "length", 0.0) or 0.0)
    except Exception as exc:  # noqa: BLE001 - a header that will not parse is 0
        LOG.debug("Could not read the length of %s: %s", Path(path).name, exc)
        return 0.0


def transcript_location(path: Path, *, beside: bool = True,
                        output_dir: Path | None = None) -> tuple[Path, str]:
    """Where this file's transcript belongs, as ``(directory, slug)``.

    Beside the audio by default, under the audio file's own name, so the two
    stay together. Otherwise under ``<output>/Local files/transcripts``, with
    the name slugified because that folder is shared and a slug is safe on
    every filesystem podHarvest runs on.
    """
    path = Path(path)
    if beside or output_dir is None:
        return path.parent, path.stem
    folder = Path(output_dir) / LOCAL_FOLDER_NAME / "transcripts"
    return folder, slugify(path.stem) or "audio"


# -- the shape the transcription pipeline expects -------------------------
#
# `harvest.transcribe_all` reads a handful of attributes off each episode. A
# local file is not a feed episode and pretending otherwise in the pipeline
# would spread feed concepts into it, so the adaptation happens here instead:
# two small objects with exactly the attributes that are read.


@dataclass
class _Enclosure:
    """Stands in for a feed enclosure: the audio, already on disk."""

    local_path: str
    status: str = "ok"
    mime: str = ""
    url: str = ""


@dataclass
class LocalEpisode:
    """A local file dressed as an episode, for the transcription pipeline."""

    title: str
    primary_audio: _Enclosure
    index: int = 0
    description: str = ""
    transcripts: tuple = ()
    published: str = ""
    #: Where this episode's transcript goes. Read through `transcribe_all`'s
    #: *layout* hook rather than by the pipeline itself.
    out_dir: Path = field(default_factory=Path)
    slug: str = ""


def as_episodes(items: Iterable[LocalFile], *, beside: bool = True,
                output_dir: Path | None = None) -> list[LocalEpisode]:
    """Turn described files into episodes the transcription batch can take."""
    episodes: list[LocalEpisode] = []
    for n, item in enumerate(items):
        out_dir, slug = transcript_location(
            item.path, beside=beside, output_dir=output_dir)
        episodes.append(LocalEpisode(
            title=item.display_title,
            primary_audio=_Enclosure(local_path=str(item.path)),
            index=n,
            out_dir=out_dir,
            slug=slug,
        ))
    return episodes


def run_local(paths: Iterable[Path], *, app: AppSpace, settings=None,
              transcribe: bool = True, model=None,
              include_timestamps: bool = True, identify_speakers: bool = False,
              cancel_event: threading.Event | None = None,
              progress_callback: Callable[[float], None] | None = None,
              episode_callback: Callable | None = None,
              hf_token: str | None = None) -> int:
    """Process local audio files: transcribe, summarise, add chapter markers.

    The same work `run_harvest` does after the download, minus the feed and the
    download. Returns 0; failures are logged per file, because one unreadable
    file must not end a run over a folder of two hundred.
    """
    from podharvest import config as config_mod
    from podharvest.harvest import transcribe_all

    settings = settings or config_mod.load(app)
    beside = bool(getattr(settings, "local_transcripts_beside_file", True))
    output_dir = Path(config_mod.resolved_output_dir(app, settings))

    files = collect(paths, recursive=bool(
        getattr(settings, "local_recurse_folders", True)))
    if not files:
        LOG.warning("None of what you added is audio podHarvest recognises. "
                    "It handles %s.", ", ".join(AUDIO_SUFFIXES))
        if progress_callback:
            progress_callback(100.0)
        return 0

    LOG.info("%d file(s) to work through.", len(files))
    described = [describe(p, beside=beside, output_dir=output_dir) for p in files]
    episodes = as_episodes(described, beside=beside, output_dir=output_dir)

    if not beside:
        folder = output_dir / LOCAL_FOLDER_NAME / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        LOG.info("Transcripts will be written to %s", folder)
    else:
        LOG.info("Transcripts will be written beside each audio file.")

    if not transcribe:
        LOG.info("Transcription is switched off, so nothing more to do. The "
                 "files are listed and ready to play or edit.")
        if progress_callback:
            progress_callback(100.0)
        return 0

    transcribe_all(
        episodes, output_dir / LOCAL_FOLDER_NAME, app=app, settings=settings,
        model=model, include_timestamps=include_timestamps,
        identify_speakers=identify_speakers, hf_token=hf_token,
        cancel_event=cancel_event, progress_callback=progress_callback,
        episode_callback=episode_callback,
        layout=lambda ep: (ep.out_dir, ep.slug),
    )
    if progress_callback:
        progress_callback(100.0)
    LOG.info("All done.")
    return 0
