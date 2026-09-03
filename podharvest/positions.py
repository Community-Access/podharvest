"""Where you stopped listening, so you can pick the episode up again.

A podcast episode is an hour long and nobody hears one in a sitting. Losing
your place because you closed a window is the kind of small, repeated
annoyance that decides whether a tool gets used, so podHarvest remembers the
playhead per file and offers it back the next time you press Play.

Three decisions worth stating:

* **Keyed by the file, not by the episode.** The episode list is a progress
  view that empties between runs; the file on disk is the durable thing. Move
  the file and the position is forgotten, which is the honest outcome -- it is
  a different file now as far as anything here can tell.
* **Bounded.** A store that grows forever is a slow leak nobody notices. The
  oldest entries are dropped past a cap, because a position from two hundred
  episodes ago is not one you were coming back to.
* **Near the end means finished.** Stopping four seconds from the end is
  finishing, and resuming there would play four seconds of outro and stop.
  Positions within the last thirty seconds are not stored, so the next Play
  starts from the beginning, which is what somebody replaying an episode
  wanted anyway.

Writes are atomic (temp file plus replace), so a crash mid-write leaves the
previous store rather than a truncated one.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from podharvest.util import LOG

#: How many positions to keep. Well past a normal backlog, small enough that
#: the file stays trivial to read and write.
MAX_ENTRIES = 500

#: A position this close to the end counts as finished, not as a place to
#: return to.
END_MARGIN_MS = 30_000

#: Below this, nothing has really been listened to yet.
MIN_POSITION_MS = 10_000


def _store_path(config_dir: Path) -> Path:
    return Path(config_dir) / "playback-positions.json"


def _key(audio_path: Path) -> str:
    """The stable identity of a file: its resolved path, as text."""
    try:
        return str(Path(audio_path).resolve())
    except OSError:  # pragma: no cover - an unresolvable path is still a key
        return str(audio_path)


def load_all(config_dir: Path) -> dict[str, dict]:
    """Every stored position. An unreadable store reads as empty, not as an error."""
    path = _store_path(config_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOG.debug("Could not read saved playback positions (%s); starting fresh.", exc)
        return {}
    return data if isinstance(data, dict) else {}


def load(config_dir: Path, audio_path: Path) -> int:
    """Where this file was left, in milliseconds. Zero when there is nothing."""
    entry = load_all(config_dir).get(_key(audio_path))
    if not isinstance(entry, dict):
        return 0
    try:
        return max(0, int(entry.get("position_ms", 0)))
    except (TypeError, ValueError):
        return 0


def save(config_dir: Path, audio_path: Path, position_ms: int, length_ms: int = 0) -> None:
    """Remember where this file was left. Never raises.

    A position in the first few seconds, or within the last half minute, is
    dropped rather than stored: neither is a place anybody wants brought back.
    Dropping also *clears* any earlier position for that file, so finishing an
    episode forgets where you were in it.
    """
    position_ms = max(0, int(position_ms))
    finished = length_ms > 0 and position_ms >= length_ms - END_MARGIN_MS
    store = load_all(config_dir)
    key = _key(audio_path)

    if position_ms < MIN_POSITION_MS or finished:
        if store.pop(key, None) is None:
            return
    else:
        store[key] = {"position_ms": position_ms, "at": int(time.time())}

    if len(store) > MAX_ENTRIES:
        oldest = sorted(store.items(), key=lambda kv: kv[1].get("at", 0))
        for stale_key, _entry in oldest[: len(store) - MAX_ENTRIES]:
            store.pop(stale_key, None)

    path = _store_path(config_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        LOG.debug("Could not save the playback position (%s).", exc)


def forget(config_dir: Path, audio_path: Path) -> None:
    """Drop this file's stored position, so the next Play starts at the top."""
    save(config_dir, audio_path, 0)
