"""Lightweight progress reporting for downloads and transcription.

No third-party dependency (no tqdm) - writes a single, throttled, carriage-
return-updated line to stderr via the shared logger's stream, and emits
periodic percentage log lines to the logfile so headless/CI runs still get
progress history.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from podharvest.util import LOG, human_size

_BAR_WIDTH = 28


def _bar(pct: float) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(_BAR_WIDTH * pct / 100)
    return "#" * filled + "-" * (_BAR_WIDTH - filled)


@dataclass
class ProgressReporter:
    """Tracks bytes/units done vs. total and prints a throttled progress line.

    Works for both byte-based downloads and unit-based work (e.g. audio
    seconds transcribed). Safe to call `update()` at high frequency; screen
    output is throttled to `min_interval` seconds so it stays responsive for
    screen readers and log files alike.
    """

    label: str
    total: float | None = None
    unit: str = "B"
    min_interval: float = 0.5
    quiet: bool = False
    _done: float = field(default=0.0, init=False)
    _start: float = field(default_factory=time.monotonic, init=False)
    _last_emit: float = field(default=0.0, init=False)
    _last_pct_logged: int = field(default=-1, init=False)
    _closed: bool = field(default=False, init=False)

    def update(self, amount: float) -> None:
        self._done += amount
        self._maybe_emit()

    def set_total(self, total: float | None) -> None:
        self.total = total

    def _fmt(self, value: float) -> str:
        if self.unit == "B":
            return human_size(int(value))
        return f"{value:,.1f} {self.unit}"

    def _maybe_emit(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_emit) < self.min_interval:
            return
        self._last_emit = now
        elapsed = max(1e-6, now - self._start)
        rate = self._done / elapsed

        if self.total and self.total > 0:
            pct = min(100.0, self._done / self.total * 100)
            eta = (self.total - self._done) / rate if rate > 0 else 0
            line = (f"{self.label}: [{_bar(pct)}] {pct:5.1f}%  "
                    f"{self._fmt(self._done)}/{self._fmt(self.total)}  "
                    f"{self._fmt(rate)}/s  ETA {eta:0.0f}s")
            pct_int = int(pct)
            if pct_int != self._last_pct_logged and pct_int % 5 == 0:
                LOG.debug("%s progress %d%%", self.label, pct_int)
                self._last_pct_logged = pct_int
        else:
            line = f"{self.label}: {self._fmt(self._done)}  {self._fmt(rate)}/s"

        if not self.quiet and sys.stderr.isatty():
            sys.stderr.write("\r" + line + " " * 6)
            sys.stderr.flush()
        elif not self.quiet:
            LOG.info(line)

    def close(self, message: str | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._maybe_emit(force=True)
        if not self.quiet and sys.stderr.isatty():
            sys.stderr.write("\n")
            sys.stderr.flush()
        elapsed = time.monotonic() - self._start
        LOG.info("%s: %s (%.1fs)", self.label, message or "done", elapsed)

    def __enter__(self) -> ProgressReporter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close("failed" if exc_type else None)
