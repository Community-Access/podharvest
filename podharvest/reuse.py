"""What this episode already has, so nothing is produced twice.

Transcribing an hour of audio costs minutes; asking a language model for
chapter markers costs minutes more. Doing either when the answer already
exists is pure waste, and doing it to a chapter list a publisher wrote by hand
is worse than waste -- an inferred list replacing an authored one is a
downgrade.

Three sources of "we already have this", cheapest first:

1. **On disk.** A previous run's transcript, sitting next to the audio. This is
   the one that matters on a re-run: point podHarvest at the same feed again
   and it should pick up where it left off, not spend the afternoon
   regenerating what is already there.
2. **In the feed.** A Podcasting 2.0 ``<podcast:transcript>`` the publisher
   provided. podHarvest has always parsed these tags and then ignored them,
   which meant transcribing an episode whose exact words were one HTTP GET
   away. When a feed offers several, the most capable representation wins --
   the ranking is shared with QUILL Cast, where it was worked out.
3. **In the file.** ID3 chapter frames already on the audio, or timestamps in
   the show notes. Both carry titles a person wrote.

The rules live in `podharvest.reuse_core`, vendored byte-identical from QUILL
(`quill/core/speech/reuse_core.py`), so both apps recognise the same show-note
shapes and prefer the same transcript formats. This module is the podHarvest
side of it: where files live, how to fetch, and what to log.
"""

from __future__ import annotations

from pathlib import Path

from podharvest import reuse_core
from podharvest.util import LOG

#: Transcript files a previous run may have left. The Markdown one is the
#: transcript proper; the rest are side-cars, so finding only a side-car does
#: not count as having the transcript.
TRANSCRIPT_SUFFIXES = (".md", ".txt")

#: A file this small is a stub or a failed write, not a transcript.
MIN_TRANSCRIPT_BYTES = 64


def existing_transcript(feed_dir: Path, slug: str) -> Path | None:
    """A transcript a previous run already wrote for this episode, if any.

    The feed layout: ``<feed_dir>/transcripts/<slug>``. For a transcript that
    lives somewhere else -- beside a local audio file, say -- use
    `transcript_in`, which this is a thin wrapper around.
    """
    return transcript_in(Path(feed_dir) / "transcripts", slug)


def transcript_in(directory: Path, slug: str) -> Path | None:
    """A usable transcript named *slug* in *directory*, if there is one.

    Size-checked rather than merely existence-checked: an empty or truncated
    file from an interrupted run should be redone, not treated as done.
    """
    for suffix in TRANSCRIPT_SUFFIXES:
        candidate = Path(directory) / f"{slug}{suffix}"
        try:
            if candidate.is_file() and candidate.stat().st_size >= MIN_TRANSCRIPT_BYTES:
                return candidate
        except OSError:  # pragma: no cover - a stat that fails is "not there"
            continue
    return None


def feed_transcript(episode) -> tuple[str, str] | None:
    """The best ``(url, mime)`` transcript the feed offers, or None.

    "Best" is by what the format can do, not by the order the publisher
    happened to write the elements in -- see `reuse_core.transcript_rank`.
    """
    offered = [
        (str(getattr(enc, "mime", "") or ""), str(getattr(enc, "url", "") or ""))
        for enc in getattr(episode, "transcripts", []) or []
    ]
    best = reuse_core.best_transcript(offered)
    if best is None:
        return None
    mime, url = best
    return str(url), str(mime)


def fetch_feed_transcript(url: str, mime: str, *, user_agent: str = "") -> str | None:
    """Fetch and read the publisher's transcript. None when it cannot be used.

    Never raises: a transcript that will not download is a reason to fall back
    to transcribing, not a reason to fail the episode.
    """
    from podharvest.net import HttpClient

    try:
        client = HttpClient(user_agent=user_agent) if user_agent else HttpClient()
        response = client.get(url)
        raw = response.body
    except Exception as exc:  # noqa: BLE001 - any failure means "transcribe instead"
        LOG.info("Could not fetch the published transcript (%s); transcribing instead.", exc)
        return None
    # A declared type beats a guessed one, but plenty of hosts serve a
    # transcript as octet-stream, so the URL's own extension is the fallback.
    served = str(response.headers.get("content-type", "")).split(";", 1)[0].strip()
    if served and "octet-stream" not in served:
        mime = mime or served
    try:
        text = reuse_core.parse_transcript(raw, mime)
    except reuse_core.TranscriptParseError as exc:
        LOG.info("The published transcript could not be read (%s); transcribing instead.", exc)
        return None
    if len(text.strip()) < MIN_TRANSCRIPT_BYTES:
        LOG.info("The published transcript was empty; transcribing instead.")
        return None
    return text


def existing_chapters(
    audio_path: Path | None,
    *,
    show_notes: str = "",
    total_ms: int = 0,
) -> reuse_core.ChapterSource:
    """Chapters this episode already has, from the file or the show notes.

    Empty means nothing free was found and the caller may spend a model on it.
    A non-empty result carries its own label, so the summary can say where the
    list came from instead of implying podHarvest worked it out.
    """

    def from_file() -> list[tuple[int, str]]:
        if audio_path is None or not Path(audio_path).is_file():
            return []
        from podharvest import audio_tags_core as core

        return [(c.start_ms, c.title) for c in core.read_mp3_chapters(Path(audio_path))]

    return reuse_core.free_chapters(
        from_file=from_file, show_notes=show_notes, total_ms=total_ms
    )
