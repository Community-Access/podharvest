"""Shared helpers: logging, slugs, safe filenames, dates, sizes, hashing."""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import os
import re
import sys
import unicodedata
from collections.abc import Iterable
from email.utils import parsedate_to_datetime
from pathlib import Path

LOG = logging.getLogger("podharvest")

# Windows reserved device names; also unusable as filenames on some tooling elsewhere.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")

MAX_NAME = 120


class HarvestError(Exception):
    """Fatal, user-facing error."""


def setup_logging(verbosity: int = 0, quiet: bool = False, logfile: Path | None = None) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbosity > 1 else logging.INFO if verbosity else logging.INFO)
    LOG.setLevel(logging.DEBUG)
    LOG.handlers.clear()

    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(level)
    stream.setFormatter(logging.Formatter("%(message)s"))
    LOG.addHandler(stream)

    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        LOG.addHandler(fh)


def slugify(text: str, max_len: int = MAX_NAME, fallback: str = "untitled") -> str:
    """ASCII, lowercase, hyphen-separated slug that is safe on every OS."""
    if not text:
        return fallback
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if not text:
        return fallback
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0] or text[:max_len]
    return text.strip("-") or fallback


def safe_filename(name: str, default: str = "file", max_len: int = MAX_NAME) -> str:
    """Sanitise an arbitrary string (often taken from a URL) into a filename.

    Guards against path traversal, illegal characters, reserved device names,
    trailing dots/spaces and over-long names.
    """
    name = name.replace("\\", "/").split("/")[-1]
    name = _ILLEGAL.sub("_", name)
    name = _WS.sub(" ", name).strip().strip(".")
    if not name:
        name = default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    if len(stem) > max_len:
        stem = stem[:max_len]
    out = f"{stem}.{ext}" if ext else stem
    return out.strip(". ") or default


def unique_path(path: Path) -> Path:
    """Return `path` or `path` with a numeric suffix so nothing is clobbered."""
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    for i in range(2, 10000):
        cand = path.with_name(f"{stem}-{i}{ext}")
        if not cand.exists():
            return cand
    return path.with_name(f"{stem}-{os.getpid()}{ext}")


def parse_date(value: str | None) -> _dt.datetime | None:
    """Parse RFC 822 (RSS), ISO 8601 (Atom) and a few common malformed variants."""
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return _ensure_tz(dt)
    except (TypeError, ValueError, IndexError):
        pass
    iso = value.replace("Z", "+00:00")
    for candidate in (iso, iso.split(".")[0], iso[:19]):
        try:
            return _ensure_tz(_dt.datetime.fromisoformat(candidate))
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%m/%d/%Y"):
        try:
            return _ensure_tz(_dt.datetime.strptime(value[:len(fmt) + 6].strip(), fmt))
        except ValueError:
            continue
    return None


def _ensure_tz(dt: _dt.datetime) -> _dt.datetime:
    return dt.replace(tzinfo=_dt.timezone.utc) if dt.tzinfo is None else dt


def iso(dt: _dt.datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def date_prefix(dt: _dt.datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "0000-00-00"


def parse_duration(value: str | None) -> int | None:
    """`HH:MM:SS`, `MM:SS` or bare seconds -> seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    parts = value.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return int(total)


def human_duration(seconds: int | None) -> str:
    if not seconds or seconds < 0:
        return "unknown"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def human_size(num: int | None) -> str:
    if not num or num < 0:
        return "unknown"
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
