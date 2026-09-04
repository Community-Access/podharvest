"""Importing a list of podcasts from an OPML file.

OPML is how podcast apps hand each other a list of shows: an XML outline where
every entry carries a name and a feed address, optionally nested in folders.
Every podcast app can export one, most directories publish one, and a network
of shows usually has a single OPML holding all of them.

That makes it the right way to bring a *list* into podHarvest, and podHarvest
has a specific use for a list: a set of shows to work through, and a way to
fill the favourites without typing forty addresses.

**Importing is not subscribing.** Nothing here polls, downloads, schedules or
notifies. An import reads a file and gives you a list you can pick from; what
you harvest from it is a separate decision, made afterwards, by you. That is
the same line `podharvest.favorites` draws, and for the same reason.

The parsing rules come from QUILL Cast's importer
(`quill/core/podcasts/opml.py`), so the two programs read the same files the
same way -- including the ones the format gets subtly wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from podharvest.util import LOG, HarvestError

#: A well-known network OPML, offered as an example because a first-time
#: importer needs something to try and "find an OPML file" is not a useful
#: instruction. ACB Media publish theirs and QUILL Cast already reads it.
EXAMPLE_NAME = "ACB Media network"
EXAMPLE_URL = ("https://pinecast.com/network/"
               "d6beadf5-05de-49dd-bd82-066af8baae4a/opml")

#: A ceiling. An OPML is a hand-curated list; a file with more entries than
#: this is either a mistake or something that should be split up.
MAX_SHOWS = 5000

#: Refuse a file bigger than this before parsing it. An outline of a few
#: hundred shows is tens of kilobytes.
MAX_BYTES = 16 * 1024 * 1024


class OpmlError(HarvestError):
    """An OPML file could not be read."""


@dataclass
class ImportedShow:
    """One show from an OPML file, with where it sat in the outline."""

    title: str
    feed_url: str
    homepage: str = ""
    folder_path: list[str] = field(default_factory=list)
    #: The OPML 2.0 attributes the spec calls optional and describes, in as
    #: many words, as useful when presenting a list to a person -- which is
    #: exactly what the import window does with them.
    description: str = ""
    language: str = ""
    category: str = ""

    @property
    def folder(self) -> str:
        """The outline folders this show sat under, as one readable string."""
        return " / ".join(self.folder_path)

    def summary(self) -> str:
        """A spoken-word line for the import list.

        A screen reader reads this with its column heading, so it is prose
        rather than a row of codes, and it says the most identifying thing
        first: which folder it came from, then what it says it is about.
        """
        parts = [p for p in (self.folder, self.category, self.language) if p]
        if self.description:
            first = self.description.strip().split(". ")[0]
            parts.append(first[:80] + ("..." if len(first) > 80 else ""))
        return ", ".join(parts) if parts else "no details"


def _is_commented_out(element) -> bool:
    """Whether OPML says to ignore this outline and everything under it.

    `isComment="true"` means the author parked it. The spec tells processors
    to skip it, and QUILL learned the hard way that importing one turns
    somebody's disabled feed back on behind their back. Only the literal
    "true" counts: the attribute is defined as a string, and an absent one
    means false.
    """
    return (element.get("isComment") or "").strip().lower() == "true"


def _walk(element, path: list[str], found: list[ImportedShow]) -> None:
    """Collect every show under *element*, remembering the folders above it."""
    for child in element.findall("outline"):
        if len(found) >= MAX_SHOWS:
            return
        if _is_commented_out(child):
            continue
        feed_url = (child.get("xmlUrl") or "").strip()
        if feed_url:
            title = (child.get("title") or child.get("text") or feed_url).strip()
            found.append(ImportedShow(
                title=title,
                feed_url=feed_url,
                homepage=(child.get("htmlUrl") or "").strip(),
                folder_path=list(path),
                # OPML 2.0 spells it "description"; some exporters write RSS's
                # "summary" instead. Take whichever is there.
                description=(child.get("description")
                             or child.get("summary") or "").strip(),
                language=(child.get("language") or "").strip(),
                # Kept verbatim rather than split: it is the file's own
                # grouping, and OPML allows both this and nested outlines, so
                # splitting would lose the difference between one category
                # written "/News/Local" and two separate ones.
                category=(child.get("category") or "").strip(),
            ))
            continue
        # No feed address: a folder. Recurse with the name added to the path.
        name = (child.get("text") or child.get("title") or "").strip()
        _walk(child, [*path, name] if name else path, found)


#: A DOCTYPE is the doorway to entity expansion attacks -- the billion-laughs
#: bomb and external-entity reads both arrive through one. No legitimate
#: podcast OPML has one, so the cheapest safe answer is to refuse the file.
_DOCTYPE = re.compile(r"<!DOCTYPE", re.IGNORECASE)


def parse(text: str) -> list[ImportedShow]:
    """Every show in an OPML document, flattened, folders remembered.

    Never raises for a file that is merely odd -- an outline with no body, or
    with folders and no feeds, is an empty list. It raises only when the file
    is not XML at all, or carries a DOCTYPE.
    """
    if _DOCTYPE.search(text or ""):
        raise OpmlError(
            "That file carries a DOCTYPE, which podHarvest will not process: "
            "it is how XML files smuggle in entity expansion attacks, and no "
            "genuine podcast list needs one.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise OpmlError(f"That file could not be read as OPML: {exc}") from exc
    body = root.find("body")
    if body is None:
        return []
    found: list[ImportedShow] = []
    _walk(body, [], found)
    return found


def decode(data: bytes) -> str:
    """Decode an OPML document defensively.

    UTF-8 with an optional byte-order mark is the overwhelming real-world
    case. A latin-1 fallback means one stray byte cannot fail a whole
    directory import; the worst case is one mangled character in one title.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def read_file(path: Path) -> list[ImportedShow]:
    """Read an OPML file from disk."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise OpmlError(f"Could not open that file: {exc}") from exc
    if size > MAX_BYTES:
        raise OpmlError(
            f"That file is {size // (1024 * 1024)} MB, which is far larger "
            "than any list of podcasts. It is probably not an OPML file.")
    try:
        return parse(decode(path.read_bytes()))
    except OSError as exc:
        raise OpmlError(f"Could not read that file: {exc}") from exc


def fetch(url: str, *, settings=None, client=None) -> list[ImportedShow]:
    """Read an OPML document published on the web.

    HTTPS is required. A list of feed addresses fetched over plain HTTP can be
    rewritten in transit, and the whole point of the list is that podHarvest
    will go and fetch what is in it.
    """
    address = str(url or "").strip()
    if not address.lower().startswith("https://"):
        raise OpmlError(
            "Podcast lists are only fetched over https. An address that can "
            "be rewritten in transit is one that can point podHarvest "
            "somewhere else.")
    if client is None:
        from podharvest.net import HttpClient

        kwargs: dict = {"retries": 2, "timeout": 30.0}
        agent = str(getattr(settings, "user_agent", "") or "")
        if agent:
            kwargs["user_agent"] = agent
        client = HttpClient(**kwargs)

    LOG.info("Reading the podcast list at %s", address)
    try:
        response = client.get(address)
    except Exception as exc:  # noqa: BLE001 - every network failure reads alike
        raise OpmlError(f"Could not fetch that list: {exc}") from exc
    body = getattr(response, "body", b"") or b""
    if len(body) > MAX_BYTES:
        raise OpmlError("That list is far larger than any list of podcasts.")
    shows = parse(decode(body))
    LOG.info("%d show(s) in that list.", len(shows))
    return shows


def load(source: str, *, settings=None, client=None) -> list[ImportedShow]:
    """Read an OPML list from wherever it is -- a web address or a file."""
    text = str(source or "").strip()
    if text.lower().startswith(("http://", "https://")):
        return fetch(text, settings=settings, client=client)
    return read_file(Path(text))


def without_duplicates(shows: list[ImportedShow]) -> list[ImportedShow]:
    """The same list with repeats removed, keeping the first of each.

    A network OPML can list one show under two folders, and a merged file can
    list it twice outright. The feed address is the identity, case-folded and
    without a trailing slash -- the same rule the favourites list uses, so a
    show imported here and a show added there are recognised as one.
    """
    seen: set[str] = set()
    kept: list[ImportedShow] = []
    for show in shows:
        key = show.feed_url.strip().rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(show)
    return kept


# -- writing a list back out ------------------------------------------------

def to_opml(favorites, *, title: str = "podHarvest favourites") -> str:
    """The favourites as an OPML 2.0 document, ready for any podcast app.

    Export is the other half of import: the list you built here should not be
    trapped here. The output is the plain dialect every app reads -- one
    ``outline type="rss"`` per show, no folders -- because favourites have no
    folders and inventing some would only give importers something to trip on.

    Titles and addresses are escaped by the XML writer, so a show called
    "Q&A" survives the round trip.
    """
    root = ElementTree.Element("opml", version="2.0")
    head = ElementTree.SubElement(root, "head")
    ElementTree.SubElement(head, "title").text = title
    body = ElementTree.SubElement(root, "body")
    for favorite in favorites:
        feed_url = str(getattr(favorite, "feed_url", "") or "").strip()
        if not feed_url:
            continue
        attributes = {
            "type": "rss",
            "text": str(getattr(favorite, "title", "") or "").strip() or feed_url,
            "xmlUrl": feed_url,
        }
        homepage = str(getattr(favorite, "homepage", "") or "").strip()
        if homepage:
            attributes["htmlUrl"] = homepage
        ElementTree.SubElement(body, "outline", attributes)
    document = ElementTree.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + document + "\n"


def export_file(path: Path, favorites, *, title: str = "podHarvest favourites") -> int:
    """Write the favourites to *path* as OPML. Returns how many were written.

    Written through a temporary file and moved into place, the same way the
    favourites file itself is saved, so an interrupted export cannot leave a
    half-written list where a good one used to be.
    """
    kept = [f for f in favorites if str(getattr(f, "feed_url", "") or "").strip()]
    text = to_opml(kept, title=title)
    destination = Path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(destination)
    return len(kept)
