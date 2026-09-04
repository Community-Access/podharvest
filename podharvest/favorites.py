"""Podcasts worth coming back to, kept in a list you own.

Finding a show once and then having to find it again is the small friction
that makes a tool tiring. So: a favourites list. Mark a show, and it is there
next time.

**This is not a subscription list, and the difference is the whole design.**
A subscription implies podHarvest checks for new episodes, downloads them, and
otherwise acts on its own. It does none of that and is not going to: nothing
here polls, schedules, notifies, or fetches anything you did not ask for. A
favourite is a bookmark. It remembers a name and a feed address so you do not
have to, and that is all it does.

The list is a plain JSON file in the app space, so it travels with a portable
install, can be read without podHarvest, and can be edited or deleted by hand
without breaking anything.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from podharvest.util import LOG

#: `datetime.UTC` is Python 3.11 and up, and podHarvest supports 3.10 -- so
#: the long spelling, which works everywhere. See `tests/test_directory.py`
#: for the gate that stops this being reintroduced.
_UTC = timezone.utc

#: The file, inside the app space's config folder.
FILE_NAME = "favorites.json"

#: A ceiling, so a runaway loop or a bad import cannot grow the file forever.
#: Far above any hand-curated list.
MAX_FAVORITES = 2000


@dataclass
class Favorite:
    """One remembered show. A name, an address, and when it was added."""

    title: str
    feed_url: str
    artist: str = ""
    homepage: str = ""
    collection_id: str = ""
    added_at: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.title} - {self.artist}" if self.artist else self.title

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Favorite | None:
        """One favourite from stored JSON, or None when it is unusable.

        A row with no feed address cannot be acted on, so it is dropped rather
        than shown as an entry that does nothing when chosen.
        """
        if not isinstance(data, dict):
            return None
        feed_url = str(data.get("feed_url") or "").strip()
        if not feed_url:
            return None
        return cls(
            title=str(data.get("title") or "").strip() or feed_url,
            feed_url=feed_url,
            artist=str(data.get("artist") or ""),
            homepage=str(data.get("homepage") or ""),
            collection_id=str(data.get("collection_id") or ""),
            added_at=str(data.get("added_at") or ""),
        )

    @classmethod
    def from_result(cls, result) -> Favorite:
        """A favourite from a directory search result."""
        return cls(
            title=getattr(result, "title", "") or "",
            feed_url=getattr(result, "feed_url", "") or "",
            artist=getattr(result, "artist", "") or "",
            homepage=getattr(result, "homepage", "") or "",
            collection_id=str(getattr(result, "collection_id", "") or ""),
            added_at=datetime.now(_UTC).isoformat(timespec="seconds"),
        )


def path_for(app) -> Path:
    """Where the list lives for this app space."""
    return Path(app.config_dir) / FILE_NAME


def _key(feed_url: str) -> str:
    """How two entries are told apart: the feed address, case-folded.

    The address is the identity, not the title. The same show under two names
    is one favourite; two shows sharing a name are two.
    """
    return str(feed_url or "").strip().rstrip("/").lower()


def load(app) -> list[Favorite]:
    """The saved favourites, newest addition last. Never raises.

    A missing file is an empty list, which is the correct answer the first
    time anybody runs this. A corrupt one is also an empty list, with a line
    in the log -- refusing to start because a bookmark file is malformed
    would be a poor trade.
    """
    path = path_for(app)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        LOG.warning("Could not read your favourites (%s); carrying on with an "
                    "empty list. The file is at %s if you want to look.",
                    exc, path)
        return []
    entries = raw.get("favorites") if isinstance(raw, dict) else raw
    found: list[Favorite] = []
    seen: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        favorite = Favorite.from_dict(entry)
        if favorite is None or _key(favorite.feed_url) in seen:
            continue
        seen.add(_key(favorite.feed_url))
        found.append(favorite)
    return found


def save(app, favorites: list[Favorite]) -> bool:
    """Write the list. True when it was written.

    Written to a temporary file and moved into place, so an interrupted write
    cannot leave a half-file where a list of bookmarks used to be.
    """
    path = path_for(app)
    trimmed = list(favorites)[:MAX_FAVORITES]
    payload = {"favorites": [f.to_dict() for f in trimmed]}
    temporary = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        LOG.warning("Could not save your favourites (%s).", exc)
        return False
    return True


def contains(favorites: list[Favorite], feed_url: str) -> bool:
    """Whether this feed is already a favourite."""
    wanted = _key(feed_url)
    return any(_key(f.feed_url) == wanted for f in favorites)


def add(app, favorite: Favorite) -> tuple[bool, str]:
    """Remember a show. Returns (changed, a sentence saying what happened).

    Adding one twice is not an error and not a duplicate -- it is a no-op with
    a sentence saying so, because pressing the button again is a reasonable
    thing to do when you cannot see whether it worked the first time.
    """
    if not str(favorite.feed_url or "").strip():
        return False, "That show has no feed address, so there is nothing to save."
    favorites = load(app)
    if contains(favorites, favorite.feed_url):
        return False, f"{favorite.title} is already in your favourites."
    if len(favorites) >= MAX_FAVORITES:
        return False, (f"Your favourites list is full ({MAX_FAVORITES}). "
                       "Remove something first.")
    if not favorite.added_at:
        favorite.added_at = datetime.now(_UTC).isoformat(timespec="seconds")
    favorites.append(favorite)
    if not save(app, favorites):
        return False, "Could not save your favourites; nothing was changed."
    return True, f"{favorite.title} added to your favourites."


def remove(app, feed_url: str) -> tuple[bool, str]:
    """Forget a show. Returns (changed, a sentence saying what happened).

    Only the bookmark goes. Anything already harvested from that feed stays
    exactly where it is -- this list has never had anything to do with the
    files on disk.
    """
    favorites = load(app)
    wanted = _key(feed_url)
    kept = [f for f in favorites if _key(f.feed_url) != wanted]
    if len(kept) == len(favorites):
        return False, "That show is not in your favourites."
    gone = next((f for f in favorites if _key(f.feed_url) == wanted), None)
    if not save(app, kept):
        return False, "Could not save your favourites; nothing was changed."
    name = gone.title if gone else "That show"
    return True, (f"{name} removed from your favourites. Anything you have "
                  "already harvested from it is untouched.")


@dataclass
class Library:
    """The favourites list held in memory, for a window to work against.

    A thin thing on purpose: the file is the truth, and every change writes
    through to it immediately. A window that batched changes and saved on
    close would lose them when something else closed it.
    """

    app: object
    entries: list[Favorite] = field(default_factory=list)

    def refresh(self) -> list[Favorite]:
        self.entries = load(self.app)
        return self.entries

    def add(self, favorite: Favorite) -> tuple[bool, str]:
        changed, message = add(self.app, favorite)
        self.refresh()
        return changed, message

    def remove(self, feed_url: str) -> tuple[bool, str]:
        changed, message = remove(self.app, feed_url)
        self.refresh()
        return changed, message

    def contains(self, feed_url: str) -> bool:
        return contains(self.entries, feed_url)
