"""Polite, resilient HTTP layer built on the standard library.

Features: retries with exponential backoff and jitter, `Retry-After` support,
per-host rate limiting, gzip/deflate/brotli decoding, conditional requests
backed by an on-disk ETag/Last-Modified cache, verified range-resume streaming
downloads, per-transfer rate limiting and scheme allow-listing.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field

from podharvest import HOMEPAGE, __version__
from podharvest.util import LOG, HarvestError

try:  # optional, only used if the interpreter has it
    import brotli  # type: ignore
except ImportError:  # pragma: no cover
    brotli = None

DEFAULT_UA = f"podharvest/{__version__} (+{HOMEPAGE}) Python-urllib RSS archiver"
ALLOWED_SCHEMES = {"http", "https"}
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504, 522, 524}


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes = b""
    from_cache: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def charset(self) -> str | None:
        ctype = self.headers.get("content-type", "")
        for part in ctype.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset":
                return value.strip('"\' ')
        return None

    def text(self) -> str:
        return decode_bytes(self.body, self.charset)


def decode_bytes(data: bytes, charset: str | None = None) -> str:
    """Decode with the declared charset, then XML/HTML declarations, then UTF-8."""
    candidates: list[str] = []
    if charset:
        candidates.append(charset)
    head = data[:2048].lower()
    for marker in (b'encoding="', b"encoding='", b'charset="', b"charset='"):
        idx = head.find(marker)
        if idx != -1:
            end_char = marker[-1:]
            end = head.find(end_char, idx + len(marker))
            if end != -1:
                candidates.append(head[idx + len(marker):end].decode("ascii", "ignore"))
    candidates += ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    for enc in candidates:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


class _RateLimiter:
    """Minimum interval between requests to the same host."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        if self.delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            earliest = self._last.get(host, 0.0) + self.delay
            sleep_for = max(0.0, earliest - now)
            self._last[host] = now + sleep_for
        if sleep_for:
            time.sleep(sleep_for)


class _TruncatedResponse(Exception):
    """The server closed the connection before sending everything it declared."""


def _rewind(sink, position: int) -> None:
    """Discard anything written past `position` so a retry can start cleanly."""
    try:
        sink.seek(position)
        sink.truncate()
    except (OSError, ValueError) as exc:  # unseekable sink: caller gave us a pipe
        raise HarvestError(
            "Cannot resume this download: the destination file is not seekable "
            f"({exc}). Open it with mode 'r+b'/'w+b' rather than 'ab'.") from exc


def _expected_length(headers: dict[str, str], ranged: bool, offset: int) -> int | None:
    """Total size of the resource, from Content-Range or Content-Length.

    Returns None when the server declares neither (e.g. a chunked response),
    in which case completeness cannot be checked at this layer.
    """
    if ranged:
        # "bytes 200-1023/1024" - the part after the slash is the full size.
        content_range = headers.get("content-range", "")
        _, _, total = content_range.partition("/")
        total = total.strip()
        if total.isdigit():
            return int(total)
    declared = headers.get("content-length", "").strip()
    if declared.isdigit():
        return int(declared) + (offset if ranged else 0)
    return None


class _Throttle:
    """Simple byte-rate limiter: sleeps just enough to hold an average rate."""

    def __init__(self, bytes_per_second: float | None) -> None:
        self.rate = bytes_per_second or 0.0
        self._start = time.monotonic()
        self._sent = 0.0

    def consume(self, count: int) -> None:
        if self.rate <= 0:
            return
        self._sent += count
        earliest = self._start + self._sent / self.rate
        sleep_for = earliest - time.monotonic()
        if sleep_for > 0:
            time.sleep(min(sleep_for, 5.0))


class HttpCache:
    """On-disk ETag/Last-Modified cache for conditional GETs.

    Feeds are re-fetched often (re-running a harvest to pick up new episodes),
    and most podcast hosts support conditional requests. Storing the validators
    alongside the body turns an unchanged feed into a 304 with no payload,
    which is both faster and considerably politer to the host.
    """

    def __init__(self, directory) -> None:
        self.dir = directory

    def _paths(self, url: str):
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.dir / f"{key}.meta.json", self.dir / f"{key}.body"

    def validators(self, url: str) -> dict[str, str]:
        """Conditional request headers for `url`, or {} if nothing is cached."""
        meta_path, body_path = self._paths(url)
        if not (meta_path.exists() and body_path.exists()):
            return {}
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        headers = {}
        if etag := meta.get("etag"):
            headers["If-None-Match"] = etag
        if modified := meta.get("last_modified"):
            headers["If-Modified-Since"] = modified
        return headers

    def load_body(self, url: str) -> bytes | None:
        _, body_path = self._paths(url)
        try:
            return body_path.read_bytes()
        except OSError:
            return None

    def store(self, url: str, headers: dict[str, str], body: bytes) -> None:
        etag, modified = headers.get("etag", ""), headers.get("last-modified", "")
        if not (etag or modified):
            return   # nothing to revalidate against later; don't waste the disk
        meta_path, body_path = self._paths(url)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(body)
            meta_path.write_text(
                json.dumps({"url": url, "etag": etag, "last_modified": modified,
                            "stored_at": time.time()}),
                encoding="utf-8")
        except OSError as exc:
            LOG.debug("Could not write HTTP cache entry for %s: %s", url, exc)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


@dataclass
class HttpClient:
    user_agent: str = DEFAULT_UA
    timeout: float = 45.0
    retries: int = 4
    backoff: float = 1.5
    delay: float = 0.0
    max_redirects: int = 8
    insecure: bool = False
    proxy: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cache: HttpCache | None = None
    _limiter: _RateLimiter = field(init=False, repr=False)
    _opener: urllib.request.OpenerDirector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._limiter = _RateLimiter(self.delay)
        handlers: list[urllib.request.BaseHandler] = []
        if self.insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        if self.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
        handlers.append(urllib.request.HTTPCookieProcessor())
        self._opener = urllib.request.build_opener(*handlers)
        self._opener.addheaders = []

    # -- internals ---------------------------------------------------------

    def _validate(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise HarvestError(f"Refusing non-HTTP(S) URL: {url!r}")
        if not parsed.netloc:
            raise HarvestError(f"URL has no host: {url!r}")
        return url

    def _request(self, url: str, extra: dict[str, str] | None = None, method: str = "GET"):
        self._validate(url)
        host = urllib.parse.urlsplit(url).netloc
        self._limiter.wait(host)
        hdrs = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate" + (", br" if brotli else ""),
            "Accept-Language": "en-US,en;q=0.8",
            **self.headers,
            **(extra or {}),
        }
        req = urllib.request.Request(url, headers=hdrs, method=method)
        return self._opener.open(req, timeout=self.timeout)

    @staticmethod
    def _decompress(raw: bytes, encoding: str) -> bytes:
        encoding = (encoding or "").lower()
        try:
            if encoding == "gzip":
                return gzip.decompress(raw)
            if encoding == "deflate":
                try:
                    return zlib.decompress(raw)
                except zlib.error:
                    return zlib.decompress(raw, -zlib.MAX_WBITS)
            if encoding == "br" and brotli:
                return brotli.decompress(raw)
        except Exception as exc:  # pragma: no cover - corrupt payloads
            LOG.debug("Decompression (%s) failed: %s", encoding, exc)
        return raw

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        wait = self.backoff ** attempt + random.uniform(0, 0.4)
        if retry_after:
            try:
                wait = max(wait, min(float(retry_after), 60.0))
            except ValueError:
                pass
        LOG.debug("Retrying in %.1fs", wait)
        time.sleep(wait)

    # -- public API --------------------------------------------------------

    def get(self, url: str, extra_headers: dict[str, str] | None = None,
            allow_304: bool = True, revalidate: bool = False) -> Response:
        """Fetch a URL fully into memory with retries.

        When `revalidate` is set and a cache is configured, a stored
        ETag/Last-Modified is sent as a conditional request; an unchanged
        resource comes back as a 304 and is served from disk.
        """
        conditional = dict(extra_headers or {})
        if revalidate and self.cache is not None:
            conditional.update(self.cache.validators(url))

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with self._request(url, conditional) as resp:
                    raw = resp.read()
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    body = self._decompress(raw, headers.get("content-encoding", ""))
                    if self.cache is not None:
                        self.cache.store(url, headers, body)
                    return Response(resp.geturl(), resp.status, headers, body)
            except urllib.error.HTTPError as exc:
                headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
                if exc.code == 304 and allow_304:
                    cached = self.cache.load_body(url) if self.cache is not None else None
                    if cached is not None:
                        LOG.debug("%s is unchanged since the last fetch; using the cached copy.", url)
                        return Response(url, 200, headers, cached, from_cache=True)
                    return Response(url, 304, headers, b"", from_cache=True)
                last_error = exc
                if exc.code in RETRY_STATUS and attempt < self.retries:
                    LOG.warning("HTTP %s for %s (attempt %d/%d)", exc.code, url, attempt + 1, self.retries)
                    self._sleep(attempt, headers.get("retry-after"))
                    continue
                raise HarvestError(f"HTTP {exc.code} {exc.reason} for {url}") from exc
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    LOG.warning("Network error for %s: %s (attempt %d/%d)", url, exc, attempt + 1, self.retries)
                    self._sleep(attempt, None)
                    continue
                raise HarvestError(f"Network failure for {url}: {exc}") from exc
        raise HarvestError(f"Unreachable: {url} ({last_error})")

    def head(self, url: str) -> Response | None:
        try:
            with self._request(url, method="HEAD") as resp:
                return Response(resp.geturl(), resp.status,
                                {k.lower(): v for k, v in resp.headers.items()})
        except Exception as exc:
            LOG.debug("HEAD failed for %s: %s", url, exc)
            return None

    def stream(self, url: str, sink: io.BufferedWriter, *, resume_from: int = 0,
               on_chunk: Callable[[int], None] | None = None,
               max_bytes: int | None = None,
               rate_limit_bps: float | None = None,
               chunk_size: int = 1 << 16) -> tuple[int, dict[str, str], bool]:
        """Stream a URL into `sink`, retrying and resuming across failures.

        Returns (bytes_written, response_headers, appended) where `written`
        counts only the bytes this call added to `sink`, and `appended`
        indicates the transfer started from a non-zero offset.

        `sink` must be seekable and opened for update (``r+b``/``w+b``), not
        append mode: when a transfer is interrupted part-way, the retry has to
        be able to rewind the file to a known-good offset. Writing into an
        append-mode handle would splice duplicate bytes into the middle of the
        file instead.

        A transfer is only considered successful if the number of bytes
        received matches what the server declared. A truncated response raises
        `HarvestError` rather than silently returning a short file, so callers
        never record a partial download as complete.
        """
        start_offset = resume_from
        written = 0                       # bytes this call has committed to `sink`
        expected_total: int | None = None
        headers: dict[str, str] = {}
        last_error: Exception | None = None
        throttle = _Throttle(rate_limit_bps)

        for attempt in range(self.retries + 1):
            offset = start_offset + written        # where this attempt must begin
            extra = {"Accept": "*/*"}
            if offset > 0:
                extra["Range"] = f"bytes={offset}-"
            try:
                with self._request(url, extra) as resp:
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    ranged = resp.status == 206

                    # The server ignored our Range and is replaying the whole
                    # body. Rewind to the original offset and take it from the
                    # top, otherwise we would append a second copy.
                    if offset > 0 and not ranged:
                        LOG.debug("Server ignored Range for %s; restarting from %d.", url, start_offset)
                        _rewind(sink, start_offset)
                        written = 0

                    expected_total = _expected_length(headers, ranged, start_offset + written)
                    if max_bytes and expected_total and expected_total > max_bytes:
                        raise HarvestError(
                            f"Refusing {url}: {expected_total} bytes exceeds the size cap")

                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        sink.write(chunk)
                        written += len(chunk)
                        if max_bytes and start_offset + written > max_bytes:
                            raise HarvestError(f"Refusing {url}: exceeded the size cap while streaming")
                        if on_chunk:
                            on_chunk(len(chunk))
                        throttle.consume(len(chunk))

                total = start_offset + written
                if expected_total is not None and total < expected_total:
                    # A short read is indistinguishable from a clean EOF at this
                    # layer, so compare against the declared length and retry.
                    raise _TruncatedResponse(
                        f"received {total} of {expected_total} bytes")
                return written, headers, start_offset > 0

            except _TruncatedResponse as exc:
                last_error = exc
                if attempt < self.retries:
                    LOG.warning("Truncated response for %s: %s (attempt %d/%d)",
                                url, exc, attempt + 1, self.retries)
                    self._sleep(attempt, None)
                    continue
                raise HarvestError(f"Incomplete download for {url}: {exc}") from exc
            except urllib.error.HTTPError as exc:
                if exc.code == 416:  # requested range past EOF: already complete
                    return written, headers, True
                last_error = exc
                if exc.code in RETRY_STATUS and attempt < self.retries:
                    self._sleep(attempt, (exc.headers or {}).get("Retry-After"))
                    continue
                raise HarvestError(f"HTTP {exc.code} downloading {url}") from exc
            except HarvestError:
                raise
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    LOG.warning("Transfer of %s failed after %d byte(s): %s (attempt %d/%d)",
                                url, written, exc, attempt + 1, self.retries)
                    self._sleep(attempt, None)
                    continue
                raise HarvestError(f"Download failed for {url}: {exc}") from exc
        raise HarvestError(f"Download failed for {url} ({last_error})")
