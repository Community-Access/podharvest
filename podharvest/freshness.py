"""Asking, when told to, whether the favourites have anything new.

The favourites are bookmarks, and the design line drawn in
`podharvest.favorites` stays drawn: nothing here polls, schedules, notifies
or downloads. What this module adds is an *answer to a question the user
asks*: "since I last looked, which of my shows published something?" One
menu choice, one pass over the list, one report -- and then it is quiet
again until asked again.

What "since I last looked" means is recorded per show in a small JSON file:
the newest episode seen at the end of each check. The first check of a show
has no baseline, and the report says so instead of guessing -- "first look"
is a different fact from "three new episodes", and pretending otherwise
would make the first report a lie.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

from podharvest.favorites import Favorite, _key
from podharvest.util import LOG, HarvestError

#: Where the per-show baselines live, beside the favourites file itself.
SEEN_FILE_NAME = "favorites_seen.json"

#: The long spelling of datetime.UTC, which is 3.11+; podHarvest supports 3.10.
_UTC = _dt.timezone.utc


def _aware(when: _dt.datetime | None) -> _dt.datetime | None:
    """A comparable datetime: naive publication dates are read as UTC.

    Two publishers, two date formats, one sort -- the same trade the library
    makes: wrong by at most half a day, where a crash (or a show forever
    "new") is wrong by everything.
    """
    if when is None:
        return None
    if when.tzinfo is None:
        return when.replace(tzinfo=_UTC)
    return when


@dataclass
class ShowReport:
    """What one check of one favourite found."""

    favorite: Favorite
    newest_title: str = ""
    newest_published: _dt.datetime | None = None
    #: How many episodes are newer than the recorded baseline. -1 means
    #: there is no baseline yet: a first look, not "nothing new".
    new_count: int = 0
    error: str = ""

    @property
    def is_first_look(self) -> bool:
        return self.new_count < 0 and not self.error

    def describe(self) -> str:
        """One spoken line: the show, then what matters about it."""
        name = self.favorite.display_name
        if self.error:
            return f"{name} - could not check: {self.error}"
        newest = self.newest_title or "(untitled)"
        when = ""
        if self.newest_published is not None:
            when = f", {self.newest_published.date().isoformat()}"
        if self.is_first_look:
            return f"{name} - first look. Newest: {newest}{when}"
        if self.new_count == 0:
            return f"{name} - nothing new"
        plural = "episode" if self.new_count == 1 else "episodes"
        return f"{name} - {self.new_count} new {plural}. Newest: {newest}{when}"


def seen_path(app) -> Path:
    return Path(app.config_dir) / SEEN_FILE_NAME


def load_seen(app) -> dict:
    """The recorded baselines, keyed the way favourites are keyed."""
    try:
        raw = json.loads(seen_path(app).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        LOG.warning("Could not read the last-seen records (%s); every show "
                    "will read as a first look.", exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def save_seen(app, records: dict) -> None:
    """Write the baselines the way the favourites file is written: through a
    temporary file, so an interrupted write cannot destroy the history."""
    destination = seen_path(app)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(records, indent=1), encoding="utf-8")
    temporary.replace(destination)


def check_one(favorite: Favorite, records: dict, *, client=None) -> ShowReport:
    """Fetch one favourite's feed and compare it with its baseline.

    Errors are folded into the report rather than raised: one show's server
    having a bad afternoon must not hide what the other nineteen published.
    """
    from podharvest.feed import fetch_feed_text, parse_feed

    report = ShowReport(favorite=favorite)
    try:
        final_url, xml_text = fetch_feed_text(favorite.feed_url, client)
        feed = parse_feed(xml_text, final_url)
    except HarvestError as exc:
        report.error = str(exc)
        return report
    except Exception as exc:  # noqa: BLE001 - surfaced per-show, never fatal
        report.error = str(exc)
        LOG.debug("Checking %s failed: %s", favorite.feed_url, exc)
        return report

    episodes = list(feed.episodes)
    dated = [(e, _aware(e.published)) for e in episodes]
    with_dates = [(e, when) for e, when in dated if when is not None]
    if with_dates:
        newest, newest_when = max(with_dates, key=lambda pair: pair[1])
    elif episodes:
        newest, newest_when = episodes[0], None
    else:
        report.error = "the feed has no episodes"
        return report
    report.newest_title = newest.title
    report.newest_published = newest_when

    record = records.get(_key(favorite.feed_url))
    baseline = _aware(_parse_when(record)) if record else None
    if baseline is None:
        report.new_count = -1
    else:
        report.new_count = sum(1 for _e, when in with_dates if when > baseline)
    return report


def _parse_when(record: object) -> _dt.datetime | None:
    if not isinstance(record, dict):
        return None
    text = str(record.get("latest_published") or "")
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def check_all(app, favorites: list[Favorite], *, client=None,
              on_progress=None) -> list[ShowReport]:
    """Check every favourite, one after another, and report on each.

    Sequential on purpose: this runs on somebody's home connection against
    twenty small servers, and a polite queue finishes in seconds anyway.
    """
    records = load_seen(app)
    reports: list[ShowReport] = []
    for index, favorite in enumerate(favorites):
        if on_progress is not None:
            on_progress(index, len(favorites), favorite.display_name)
        reports.append(check_one(favorite, records, client=client))
    return reports


def mark_seen(app, reports: list[ShowReport]) -> int:
    """Record each successfully-checked show's newest episode as seen.

    Returns how many records were written. Shows that errored keep their old
    baseline: "could not check" must not quietly become "nothing new".
    """
    records = load_seen(app)
    written = 0
    for report in reports:
        if report.error:
            continue
        entry = {
            "latest_title": report.newest_title,
            "checked_at": _dt.datetime.now(_UTC).isoformat(timespec="seconds"),
        }
        if report.newest_published is not None:
            entry["latest_published"] = report.newest_published.isoformat()
        records[_key(report.favorite.feed_url)] = entry
        written += 1
    if written:
        save_seen(app, records)
    return written
