"""Finding a podcast by name, using Apple's public directory.

podHarvest could only ever be pointed at a feed address you had already found
somewhere else. That is a fine way to work if you keep a list of URLs, and a
poor one otherwise: most people know a show by its name.

Apple's iTunes Search API is the standard answer -- free, keyless, and the same
directory the podcast apps use. The client here is adapted from QUILL Cast's
(`quill/core/podcasts/itunes_search.py`), with the storefront list from
`quill/core/podcasts/apple_podcasts.py`, so the two programs find the same
shows. It goes through podHarvest's own HTTP client rather than urllib
directly, which brings the retry, timeout, rate limit and user agent every
other request in this program already uses.

**Searching is not subscribing.** Nothing here polls, schedules or downloads.
A search returns a feed address; what you do with it is a separate decision.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field

from podharvest.util import LOG, HarvestError

#: Apple's search endpoint. HTTPS only, and checked before every request:
#: a directory lookup is not worth doing in the clear.
SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"

#: The storefronts worth offering, code first. Taken from QUILL Cast so the
#: two programs agree. Apple has around 175; these are the ones with enough
#: English-language podcast coverage to be a sensible menu, and any other
#: two-letter code can still be typed into the setting by hand.
STOREFRONTS: tuple[tuple[str, str], ...] = (
    ("us", "United States"),
    ("gb", "United Kingdom"),
    ("ca", "Canada"),
    ("au", "Australia"),
    ("ie", "Ireland"),
    ("nz", "New Zealand"),
    ("za", "South Africa"),
    ("de", "Germany"),
    ("fr", "France"),
    ("es", "Spain"),
    ("it", "Italy"),
    ("nl", "Netherlands"),
    ("se", "Sweden"),
    ("no", "Norway"),
    ("dk", "Denmark"),
    ("fi", "Finland"),
    ("pl", "Poland"),
    ("mx", "Mexico"),
    ("br", "Brazil"),
    ("ar", "Argentina"),
    ("jp", "Japan"),
    ("kr", "South Korea"),
    ("cn", "China"),
    ("in", "India"),
    ("sg", "Singapore"),
)

#: The default. Apple's directory is largest here and it is what the API
#: assumes when no country is given, so it is the least surprising choice.
DEFAULT_STOREFRONT = "us"

#: What a search term is matched against. "Everything" is Apple's own default
#: and the right answer most of the time; the others are for when it is not --
#: a show whose name is a common word, or everything by one presenter.
SEARCH_FIELDS: tuple[tuple[str, str], ...] = (
    ("", "Everything"),
    ("titleTerm", "The show's name"),
    ("authorTerm", "The author or presenter"),
    ("keywordsTerm", "Keywords"),
    ("descriptionTerm", "The description"),
)

#: Apple accepts 1-200. More than this is a list nobody reads.
MAX_LIMIT = 200
DEFAULT_LIMIT = 25


class DirectoryError(HarvestError):
    """A directory search could not be completed."""


@dataclass
class SearchResult:
    """One show found in the directory -- enough to decide and to harvest."""

    title: str
    feed_url: str
    artist: str = ""
    artwork_url: str = ""
    homepage: str = ""
    collection_id: str = ""
    genre: str = ""
    episode_count: int = 0
    country: str = ""
    explicit: bool = False
    released: str = ""

    @property
    def display_name(self) -> str:
        """Title and author together, which is how people recognise a show."""
        return f"{self.title} - {self.artist}" if self.artist else self.title

    def summary(self) -> str:
        """A spoken-word line for the results list.

        Prose rather than columns of codes: a screen reader reads this with
        its heading, and "342 episodes, Society & Culture" says more in one
        breath than three narrow columns would.
        """
        parts: list[str] = []
        if self.episode_count:
            parts.append(f"{self.episode_count} episode"
                         + ("s" if self.episode_count != 1 else ""))
        if self.genre:
            parts.append(self.genre)
        if self.explicit:
            parts.append("explicit")
        return ", ".join(parts) if parts else "no details"


def storefront_name(code: str) -> str:
    """A storefront's display name, or the code itself when it is not listed."""
    lowered = str(code or "").strip().lower()
    for candidate, name in STOREFRONTS:
        if candidate == lowered:
            return name
    return lowered.upper() or DEFAULT_STOREFRONT.upper()


def clean_storefront(code: str) -> str:
    """A usable two-letter storefront code, falling back to the default.

    Any two letters are allowed through, not only the listed ones: Apple has
    far more storefronts than are worth putting in a menu, and somebody who
    knows theirs should be able to type it into the settings file.
    """
    lowered = str(code or "").strip().lower()
    if len(lowered) == 2 and lowered.isalpha():
        return lowered
    return DEFAULT_STOREFRONT


def _client(settings=None):
    """podHarvest's HTTP client, configured the way the rest of the app is."""
    from podharvest.net import HttpClient

    kwargs: dict[str, object] = {"delay": 0.0, "retries": 2, "timeout": 15.0}
    agent = str(getattr(settings, "user_agent", "") or "")
    if agent:
        kwargs["user_agent"] = agent
    return HttpClient(**kwargs)


def _fetch_json(url: str, *, settings=None, client=None) -> dict:
    """One HTTPS GET returning decoded JSON. Raises `DirectoryError`."""
    if not url.startswith("https://"):
        raise DirectoryError("Refusing to search over an insecure connection.")
    try:
        response = (client or _client(settings)).get(url)
    except Exception as exc:  # noqa: BLE001 - every network failure reads alike
        raise DirectoryError(
            f"Could not reach the podcast directory: {exc}") from exc
    # `Response.text` is a method here, not a property -- calling it is the
    # point, and reading it as an attribute silently yields the function.
    try:
        text = response.text()
    except Exception:  # noqa: BLE001 - fall back to the raw bytes
        text = (getattr(response, "body", b"") or b"").decode("utf-8", "replace")
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise DirectoryError(
            "The podcast directory sent back something unreadable.") from exc
    return data if isinstance(data, dict) else {}


def result_from_entry(entry: dict) -> SearchResult | None:
    """One search result, or None when the entry cannot be used.

    A directory row with no feed address is not a podcast anybody here can do
    anything with, so it is dropped rather than shown and then refused.
    """
    if not isinstance(entry, dict):
        return None
    title = str(entry.get("collectionName") or "").strip()
    feed_url = str(entry.get("feedUrl") or "").strip()
    if not title or not feed_url:
        return None
    try:
        count = int(entry.get("trackCount") or 0)
    except (TypeError, ValueError):
        count = 0
    return SearchResult(
        title=title,
        feed_url=feed_url,
        artist=str(entry.get("artistName") or ""),
        artwork_url=str(entry.get("artworkUrl600")
                        or entry.get("artworkUrl100") or ""),
        homepage=str(entry.get("collectionViewUrl") or ""),
        collection_id=str(entry.get("collectionId") or ""),
        genre=str(entry.get("primaryGenreName") or ""),
        episode_count=count,
        country=str(entry.get("country") or ""),
        explicit=str(entry.get("collectionExplicitness") or "").lower() == "explicit",
        released=str(entry.get("releaseDate") or "")[:10],
    )


def results_from_json(data: object) -> list[SearchResult]:
    """Every usable result in a directory reply. Tolerant of anything."""
    entries = data.get("results") if isinstance(data, dict) else None
    found = []
    for entry in entries if isinstance(entries, list) else []:
        result = result_from_entry(entry)
        if result is not None:
            found.append(result)
    return found


def search(term: str, *, country: str = DEFAULT_STOREFRONT,
           limit: int = DEFAULT_LIMIT, field_name: str = "",
           explicit: bool | None = None, settings=None,
           client=None) -> list[SearchResult]:
    """Shows matching *term* in the chosen storefront.

    *field_name* narrows what the term is matched against -- see
    `SEARCH_FIELDS`. Empty means Apple's own default, which searches
    everything and is usually right.

    *explicit* of False asks Apple to leave explicit shows out. None, the
    default, does not ask either way: filtering something nobody asked to
    filter is its own kind of wrong.

    An empty term returns nothing rather than everything, because a directory
    search with no term is not a question.
    """
    if not str(term or "").strip():
        return []
    params: dict[str, object] = {
        "term": str(term).strip(),
        "media": "podcast",
        "entity": "podcast",
        "country": clean_storefront(country),
        "limit": max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT)),
    }
    if field_name:
        params["attribute"] = field_name
    if explicit is False:
        params["explicit"] = "No"

    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    LOG.info("Searching the %s podcast directory for '%s'...",
             storefront_name(params["country"]), params["term"])
    results = results_from_json(_fetch_json(url, settings=settings, client=client))
    LOG.info("%d show(s) found.", len(results))
    return results


def lookup(collection_id: str, *, country: str = DEFAULT_STOREFRONT,
           settings=None, client=None) -> SearchResult | None:
    """One show by its Apple id, for turning a shared link into a feed."""
    ident = str(collection_id or "").strip()
    if not ident.isdigit():
        return None
    params = {"id": ident, "entity": "podcast",
              "country": clean_storefront(country)}
    url = f"{LOOKUP_URL}?{urllib.parse.urlencode(params)}"
    results = results_from_json(_fetch_json(url, settings=settings, client=client))
    return results[0] if results else None


#: Apple show links look like
#: https://podcasts.apple.com/us/podcast/some-name/id1234567890
_ID_MARKER = "/id"


def collection_id_from_url(url: str) -> str:
    """The Apple id in a podcasts.apple.com link, or "".

    People share the web link, not the feed address. Recognising it means a
    pasted Apple link works where a feed address is asked for, instead of
    failing as an unparseable feed.
    """
    text = str(url or "").strip()
    if "podcasts.apple.com" not in text and "itunes.apple.com" not in text:
        return ""
    marker = text.rfind(_ID_MARKER)
    if marker == -1:
        return ""
    digits = ""
    for character in text[marker + len(_ID_MARKER):]:
        if character.isdigit():
            digits += character
        else:
            break
    return digits


def feed_url_for(url_or_term: str, *, country: str = DEFAULT_STOREFRONT,
                 settings=None, client=None) -> str:
    """Turn an Apple show link into its feed address. "" if it is not one."""
    ident = collection_id_from_url(url_or_term)
    if not ident:
        return ""
    found = lookup(ident, country=country, settings=settings, client=client)
    return found.feed_url if found else ""


@dataclass
class SearchQuery:
    """Everything a search needs, so it can be handed to a worker thread."""

    term: str = ""
    country: str = DEFAULT_STOREFRONT
    limit: int = DEFAULT_LIMIT
    field_name: str = ""
    include_explicit: bool = True
    results: list[SearchResult] = field(default_factory=list)

    def run(self, *, settings=None, client=None) -> list[SearchResult]:
        """Perform this search and keep the results on the query."""
        self.results = search(
            self.term, country=self.country, limit=self.limit,
            field_name=self.field_name,
            explicit=None if self.include_explicit else False,
            settings=settings, client=client)
        return self.results
