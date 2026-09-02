"""Typed data model for a harvested feed."""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any

from podharvest.util import human_duration, human_size, iso

AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wav", ".wma", ".m4b", ".aiff"}
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".wmv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".avif"}
DOC_EXT = {".pdf", ".epub", ".txt", ".doc", ".docx", ".rtf", ".odt", ".zip", ".srt", ".vtt", ".json"}


def classify_media(mime: str, url: str) -> str:
    """Bucket an enclosure into audio / video / image / document / other."""
    mime = (mime or "").lower().split(";")[0].strip()
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith(("application/pdf", "application/epub", "text/", "application/zip", "application/x-subrip")):
        return "document"

    path = url.split("?")[0].split("#")[0].lower()
    dot = path.rfind(".")
    ext = path[dot:] if dot != -1 else ""
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in DOC_EXT:
        return "document"
    return "other"


@dataclass
class Person:
    name: str = ""
    email: str = ""
    role: str = ""
    uri: str = ""

    def display(self) -> str:
        parts = [p for p in (self.name, f"<{self.email}>" if self.email else "") if p]
        return " ".join(parts) or self.email or "unknown"


@dataclass
class Enclosure:
    url: str
    mime: str = ""
    length: int | None = None
    title: str = ""
    kind: str = "other"          # audio | video | image | document | other
    role: str = "enclosure"      # enclosure | transcript | chapters | artwork | media
    local_path: str | None = None
    sha256: str | None = None
    bytes_downloaded: int | None = None
    status: str = "pending"      # pending | ok | skipped | failed

    def __post_init__(self) -> None:
        if self.kind == "other":
            self.kind = classify_media(self.mime, self.url)

    @property
    def human_length(self) -> str:
        return human_size(self.length)


@dataclass
class Episode:
    guid: str = ""
    title: str = "(untitled)"
    link: str = ""
    published: _dt.datetime | None = None
    updated: _dt.datetime | None = None
    summary_html: str = ""
    content_html: str = ""
    subtitle: str = ""
    authors: list[Person] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    duration_seconds: int | None = None
    explicit: bool | None = None
    season: int | None = None
    number: int | None = None
    episode_type: str = ""
    image_url: str = ""
    comments_url: str = ""
    source_feed: str = ""
    enclosures: list[Enclosure] = field(default_factory=list)
    transcripts: list[Enclosure] = field(default_factory=list)
    chapters_url: str = ""
    funding: list[dict[str, str]] = field(default_factory=list)
    soundbites: list[dict[str, Any]] = field(default_factory=list)
    location: str = ""
    license: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    raw_xml: str = ""

    # Filled in by the renderer / downloader.
    index: int = 0
    slug: str = ""
    markdown_path: str = ""
    html_path: str = ""
    text_path: str = ""
    json_path: str = ""

    @property
    def best_html(self) -> str:
        """Prefer full content over the truncated summary."""
        if len(self.content_html) >= len(self.summary_html):
            return self.content_html or self.summary_html
        return self.summary_html or self.content_html

    @property
    def human_duration(self) -> str:
        return human_duration(self.duration_seconds)

    @property
    def primary_audio(self) -> Enclosure | None:
        for enc in self.enclosures:
            if enc.kind == "audio":
                return enc
        return self.enclosures[0] if self.enclosures else None

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["published"] = iso(self.published)
        data["updated"] = iso(self.updated)
        data["duration_human"] = self.human_duration
        if not include_raw:
            data.pop("raw_xml", None)
        return data


@dataclass
class Feed:
    url: str = ""
    self_url: str = ""
    title: str = "Untitled Feed"
    subtitle: str = ""
    description_html: str = ""
    link: str = ""
    language: str = ""            # "" = the feed did not declare one
    copyright: str = ""
    generator: str = ""
    published: _dt.datetime | None = None
    updated: _dt.datetime | None = None
    image_url: str = ""
    authors: list[Person] = field(default_factory=list)
    owner: Person | None = None
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    explicit: bool | None = None
    feed_type: str = "rss"       # rss | atom | rdf
    complete: bool = False
    new_feed_url: str = ""
    funding: list[dict[str, str]] = field(default_factory=list)
    locked: bool | None = None
    guid: str = ""
    license: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    episodes: list[Episode] = field(default_factory=list)
    next_page_url: str = ""
    prev_archive_url: str = ""
    fetched_at: _dt.datetime | None = None
    source_documents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("episodes", None)
        data["published"] = iso(self.published)
        data["updated"] = iso(self.updated)
        data["fetched_at"] = iso(self.fetched_at)
        data["episode_count"] = len(self.episodes)
        return data
