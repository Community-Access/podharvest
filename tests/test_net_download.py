"""HTTP layer: verified resume, truncation detection, and the download manifest.

These are regression tests for a data-corruption bug. `HttpClient.stream`
retried a failed transfer by re-requesting the same byte range and writing it
into the same open, append-mode file handle, splicing duplicate bytes into the
middle of the download. Separately, a response that ended early was accepted
silently, and the short file was recorded in the manifest as complete so it
was never re-fetched.
"""

import io
import socket
import struct
import threading

import pytest

from podharvest.net import HttpClient
from podharvest.util import HarvestError

BODY = bytes((i % 251) for i in range(400_000))


class FlakyServer:
    """Serves `BODY`, failing the first `fail_times` requests part-way."""

    def __init__(self, fail_times: int = 1, truncate: bool = False, honour_range: bool = True):
        self.fail_times = fail_times
        self.truncate = truncate
        self.honour_range = honour_range
        self.requests: list[str] = []
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/file.bin"

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            try:
                self._handle(conn)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn):
        request = conn.recv(65535).decode("latin1")
        rng = next((line for line in request.split("\r\n")
                    if line.lower().startswith("range:")), "")
        self.requests.append(rng)

        start = 0
        if rng and self.honour_range:
            start = int(rng.split("=")[1].split("-")[0])
            conn.sendall(
                b"HTTP/1.0 206 Partial Content\r\n"
                b"Content-Length: %d\r\n"
                b"Content-Range: bytes %d-%d/%d\r\n\r\n"
                % (len(BODY) - start, start, len(BODY) - 1, len(BODY)))
        else:
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\n\r\n" % (len(BODY) - start))

        payload = BODY[start:]
        if len(self.requests) <= self.fail_times:
            conn.sendall(payload[: len(payload) // 2])
            if not self.truncate:
                # Hard reset mid-body, so the client raises rather than
                # seeing a clean EOF.
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                struct.pack("ii", 1, 0))
            return
        conn.sendall(payload)

    def close(self):
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def client():
    return HttpClient(retries=4, backoff=0.01, timeout=10)


def test_interrupted_transfer_resumes_without_duplicating_bytes(client):
    server = FlakyServer(fail_times=1)
    try:
        sink = io.BytesIO()
        written, _headers, _appended = client.stream(server.url, sink)
    finally:
        server.close()

    assert sink.getvalue() == BODY, "resumed download does not match the source"
    assert len(sink.getvalue()) == len(BODY)
    assert written == len(BODY)


def test_retry_requests_the_remaining_range_not_the_whole_file(client):
    server = FlakyServer(fail_times=1)
    try:
        client.stream(server.url, io.BytesIO())
    finally:
        server.close()

    assert len(server.requests) >= 2
    # The second attempt must ask for a non-zero offset, otherwise it is
    # re-downloading bytes it already has.
    assert "bytes=" in server.requests[1].lower()
    assert "bytes=0-" not in server.requests[1].lower()


def test_truncated_response_raises_instead_of_returning_a_short_file(client):
    # A clean EOF before Content-Length is exhausted must not be reported as
    # success - that is what let corrupt audio into the manifest as "ok".
    server = FlakyServer(fail_times=99, truncate=True)
    try:
        with pytest.raises(HarvestError, match="Incomplete"):
            client.stream(server.url, io.BytesIO())
    finally:
        server.close()


def test_server_ignoring_range_restarts_cleanly(client):
    server = FlakyServer(fail_times=1, honour_range=False)
    try:
        sink = io.BytesIO()
        client.stream(server.url, sink)
    finally:
        server.close()
    assert sink.getvalue() == BODY, "restart after an ignored Range duplicated data"


def test_size_cap_is_enforced(client):
    server = FlakyServer(fail_times=0)
    try:
        with pytest.raises(HarvestError, match="exceeds the size cap"):
            client.stream(server.url, io.BytesIO(), max_bytes=1000)
    finally:
        server.close()


def test_non_http_schemes_are_refused(client):
    for url in ("file:///etc/passwd", "ftp://example.org/x", "gopher://x"):
        with pytest.raises(HarvestError, match="Refusing non-HTTP"):
            client.get(url)
