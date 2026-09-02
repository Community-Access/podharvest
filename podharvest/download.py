"""Concurrent, resumable enclosure downloading with a JSON state manifest.

Enclosures are sorted into per-kind folders under the feed's output
directory (`audio/`, `video/`, `images/`, `documents/`, `other/`) so text
artifacts and media never mix. Downloads run on a bounded thread pool
(`Settings.concurrent_downloads`) and are individually retried/resumed by
`podharvest.net.HttpClient`; a `downloads.json` manifest records what has
already completed so re-running a fetch is a fast no-op.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from podharvest.models import Enclosure, Episode, Feed
from podharvest.net import HttpClient
from podharvest.progress import ProgressReporter
from podharvest.util import LOG, human_size, safe_filename, sha256_file, slugify, unique_path

KIND_DIRS = {
    "audio": "audio", "video": "video", "image": "images",
    "document": "documents", "other": "other",
}
MANIFEST_NAME = "downloads.json"


def kind_dir(feed_dir: Path, kind: str) -> Path:
    return feed_dir / KIND_DIRS.get(kind, "other")


def enclosure_filename(ep: Episode, enc: Enclosure, index: int) -> str:
    url_name = safe_filename(enc.url.split("?")[0])
    ext = Path(url_name).suffix or {"audio": ".mp3", "video": ".mp4", "image": ".jpg"}.get(enc.kind, ".bin")
    base = slugify(ep.title) or f"episode-{ep.index}"
    suffix = "" if index == 0 else f"-{index + 1}"
    return f"{base}{suffix}{ext}"


@dataclass
class DownloadPlanItem:
    episode: Episode
    enclosure: Enclosure
    dest: Path


def _load_manifest(feed_dir: Path) -> dict:
    path = feed_dir / MANIFEST_NAME
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            LOG.warning("Ignoring unreadable download manifest at %s", path)
    return {}


def _save_manifest(feed_dir: Path, manifest: dict) -> None:
    (feed_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def plan_downloads(feed: Feed, feed_dir: Path, allowed_kinds: list[str]) -> list[DownloadPlanItem]:
    plan: list[DownloadPlanItem] = []
    for ep in feed.episodes:
        seen_per_kind: dict[str, int] = {}
        for enc in ep.enclosures:
            if enc.kind not in allowed_kinds:
                enc.status = "skipped"
                continue
            idx = seen_per_kind.get(enc.kind, 0)
            seen_per_kind[enc.kind] = idx + 1
            dest = kind_dir(feed_dir, enc.kind) / enclosure_filename(ep, enc, idx)
            plan.append(DownloadPlanItem(ep, enc, dest))
    return plan


class AggregateProgress:
    """Aggregates per-file byte progress into one overall percentage."""

    def __init__(self, total_bytes: int | None, total_files: int,
                on_progress: Callable[[float], None] | None = None) -> None:
        self.total_bytes = total_bytes
        self.total_files = max(1, total_files)
        self.done_bytes = 0
        self.done_files = 0
        self.failed = 0
        self.on_progress = on_progress
        self._lock = threading.Lock()
        self._reporter = ProgressReporter("Downloading enclosures", total=total_bytes or None, unit="B")

    def update(self, n: int) -> None:
        with self._lock:
            self.done_bytes += n
        self._reporter.update(n)
        self._emit()

    def skip(self, n: int) -> None:
        with self._lock:
            self.done_bytes += n
            self.done_files += 1
        self._emit()

    def fail(self) -> None:
        with self._lock:
            self.failed += 1
            self.done_files += 1
        self._emit()

    def file_done(self) -> None:
        with self._lock:
            self.done_files += 1
        self._emit()

    def _emit(self) -> None:
        if not self.on_progress:
            return
        if self.total_bytes:
            pct = min(100.0, self.done_bytes / self.total_bytes * 100)
        else:
            pct = min(100.0, self.done_files / self.total_files * 100)
        self.on_progress(pct)

    def close(self) -> None:
        self._reporter.close(f"{self.done_files}/{self.total_files} file(s), {self.failed} failed")


PARTIAL_SUFFIX = ".part"


def _resolve_destination(dest: Path, url: str, record: dict | None, on_duplicate: str) -> Path | None:
    """Decide where this enclosure should land.

    `dest` is the name derived from the episode title. It may already be taken
    by a *different* source URL (two feeds, or two episodes that slugify the
    same way), which is what `Settings.on_duplicate_file` governs:

    - ``overwrite`` - reuse the name and replace whatever is there
    - ``rename``    - pick ``name-2.ext``, ``name-3.ext``, ... instead
    - ``skip``      - leave the existing file alone and skip this download

    Returns None to mean "skip". A record for this exact URL always wins: we
    keep downloading to the same path we used last time, which is what makes
    resume work across runs.
    """
    if record and record.get("path"):
        return Path(record["path"])
    if not dest.exists():
        return dest
    if on_duplicate == "overwrite":
        return dest
    if on_duplicate == "skip":
        LOG.info("Skipping %s: %s already exists (on_duplicate_file=skip).", url, dest.name)
        return None
    return unique_path(dest)


def _download_one(client: HttpClient, item: DownloadPlanItem, manifest: dict,
                  manifest_lock: threading.Lock, cancel_event: threading.Event | None,
                  reporter: AggregateProgress, settings, feed_dir: Path) -> None:
    enc, dest = item.enclosure, item.dest
    if cancel_event is not None and cancel_event.is_set():
        enc.status = "skipped"
        return

    key = enc.url
    with manifest_lock:
        record = manifest.get(key)

    # A completed record only counts if the file is still there *and* still the
    # size we recorded. Anything else (truncated by an old buggy run, edited,
    # partially synced) is re-downloaded rather than trusted.
    if record and record.get("status") == "ok":
        existing = Path(record.get("path", ""))
        expected = record.get("bytes")
        if existing.exists() and (not expected or existing.stat().st_size == expected):
            enc.local_path, enc.sha256, enc.status = str(existing), record.get("sha256"), "ok"
            enc.bytes_downloaded = expected or existing.stat().st_size
            reporter.skip(enc.bytes_downloaded or 0)
            return
        LOG.warning("Re-downloading %s: the cached copy is missing or the wrong size.", existing.name)

    resolved = _resolve_destination(dest, enc.url, record, getattr(settings, "on_duplicate_file", "overwrite"))
    if resolved is None:
        enc.status = "skipped"
        reporter.skip(0)
        return
    dest = resolved
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Download into a ".part" file so an interrupted transfer can never be
    # mistaken for a finished one, and only rename into place once the byte
    # count checks out.
    partial = dest.with_name(dest.name + PARTIAL_SUFFIX)
    rate_limit_bps = (settings.download_rate_limit_kbps * 1024
                      if getattr(settings, "download_rate_limit_kbps", None) else None)
    max_bytes = (settings.max_enclosure_mb * 1024 * 1024
                 if getattr(settings, "max_enclosure_mb", None) else None)

    LOG.info("Downloading %s -> %s", enc.url, dest)
    try:
        resume_from = partial.stat().st_size if partial.exists() else 0
        if resume_from:
            LOG.info("Resuming %s at %s.", dest.name, human_size(resume_from))
        # "r+b" (not "ab") so an interrupted transfer can rewind the file to a
        # known-good offset before retrying. Append mode would splice duplicate
        # bytes into the middle of the file.
        with partial.open("r+b" if resume_from else "w+b") as fh:
            fh.seek(resume_from)
            written, headers, appended = client.stream(
                enc.url, fh, resume_from=resume_from,
                on_chunk=lambda n: reporter.update(n),
                max_bytes=max_bytes, rate_limit_bps=rate_limit_bps)

        final_size = partial.stat().st_size
        if enc.length is None:
            enc.length = final_size
        elif enc.length != final_size:
            # The feed's declared length is advisory and often wrong, so this
            # is a note rather than a failure - net.stream() has already
            # verified the transfer against what the server actually declared.
            LOG.debug("%s: feed declared %d bytes, received %d.", dest.name, enc.length, final_size)

        partial.replace(dest)
        enc.local_path = str(dest)
        enc.bytes_downloaded = final_size
        enc.sha256 = sha256_file(dest)
        enc.status = "ok"
        reporter.file_done()
    except Exception as exc:  # noqa: BLE001 - one failed file shouldn't sink the whole run
        LOG.error("Failed to download %s: %s", enc.url, exc)
        # Leave the .part file in place: the next run resumes from it.
        enc.status = "failed"
        reporter.fail()
        return

    with manifest_lock:
        manifest[key] = {"path": str(dest), "sha256": enc.sha256, "bytes": enc.bytes_downloaded,
                         "status": "ok", "episode": item.episode.title}
        # Flush after every file so a run that is killed mid-way still knows
        # what it already has, rather than starting over.
        _save_manifest(feed_dir, manifest)


def download_all(feed: Feed, feed_dir: Path, settings, *, client: HttpClient | None = None,
                 cancel_event: threading.Event | None = None,
                 progress_callback: Callable[[float], None] | None = None) -> tuple[int, int]:
    """Download every enclosure allowed by `settings.download_kinds`.

    Returns (succeeded, failed). Runs up to `settings.concurrent_downloads`
    transfers in parallel via a thread pool.
    """
    feed_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_downloads(feed, feed_dir, settings.download_kinds)
    if settings.max_enclosure_mb:
        cap = settings.max_enclosure_mb * 1024 * 1024
        before = len(plan)
        plan = [p for p in plan if not p.enclosure.length or p.enclosure.length <= cap]
        skipped = before - len(plan)
        if skipped:
            LOG.warning("Skipping %d enclosure(s) over the %s MB size cap.", skipped, settings.max_enclosure_mb)

    manifest = _load_manifest(feed_dir)
    manifest_lock = threading.Lock()
    total_bytes = sum(p.enclosure.length or 0 for p in plan) or None
    reporter = AggregateProgress(total_bytes, len(plan), progress_callback)

    client = client or HttpClient(delay=0.0)
    workers = max(1, min(settings.concurrent_downloads, len(plan) or 1))
    LOG.info("Downloading %d enclosure(s) with %d worker(s)...", len(plan), workers)

    ok = failed = 0
    if plan:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dl") as pool:
            futures = {pool.submit(_download_one, client, item, manifest, manifest_lock,
                                   cancel_event, reporter, settings, feed_dir): item for item in plan}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    LOG.error("Unexpected download error for %s: %s", item.enclosure.url, exc)
                    item.enclosure.status = "failed"
                if item.enclosure.status == "ok":
                    ok += 1
                elif item.enclosure.status == "failed":
                    failed += 1
    reporter.close()
    _save_manifest(feed_dir, manifest)
    LOG.info("Downloads complete: %d ok, %d failed, %d skipped.", ok, failed, len(plan) - ok - failed)
    return ok, failed
