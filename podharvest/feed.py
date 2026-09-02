"""Feed discovery and parsing: RSS 2.0, RDF/RSS 1.0, and Atom.

Pure standard-library (`xml.etree.ElementTree`) implementation - no
`feedparser` dependency. Handles the namespaces podcasts actually use
(`itunes`, `content`, `media`, `atom`, `dc`) plus the plain-RSS fallbacks.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from podharvest.models import Enclosure, Episode, Feed, Person
from podharvest.net import HttpClient
from podharvest.util import LOG, HarvestError, parse_date, parse_duration

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss1": "http://purl.org/rss/1.0/",
    "podcast": "https://podcastindex.org/namespace/1.0",
}

#: `xml:lang` is in the reserved XML namespace, not one of the feed's own.
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _find(el: ET.Element, *paths: str) -> ET.Element | None:
    for path in paths:
        found = el.find(path, NS)
        if found is not None:
            return found
    return None


#: <link rel="alternate"> types that identify a feed on an HTML page.
FEED_LINK_TYPES = (
    "application/rss+xml", "application/atom+xml", "application/feed+json",
    "application/rdf+xml", "text/xml", "application/xml",
)

#: Paths worth trying when an HTML page advertises no feed at all. Ordered by
#: how common they are across the podcast hosts people actually use.
FEED_GUESS_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml", "/feed/podcast")


def discover_feed_url(html: str, base_url: str) -> str | None:
    """Find a feed URL advertised by an HTML page's <link rel="alternate">."""
    import re
    import urllib.parse

    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.I):
        attrs = dict(re.findall(r"""([a-zA-Z-]+)\s*=\s*["']([^"']*)["']""", tag))
        rel = attrs.get("rel", "").lower()
        type_ = attrs.get("type", "").lower()
        href = attrs.get("href", "").strip()
        if href and "alternate" in rel and type_ in FEED_LINK_TYPES:
            return urllib.parse.urljoin(base_url, href)
    return None


def fetch_feed_text(url: str, client: HttpClient | None = None) -> tuple[str, str]:
    """Fetch a feed URL. Returns (final_url, xml_text).

    People paste the podcast's *web page* far more often than its feed, so an
    HTML response is not treated as an error: the page is searched for a
    `<link rel="alternate">` feed, then a short list of conventional feed
    paths is tried, before giving up with a message that says what happened.
    """
    import urllib.parse

    client = client or HttpClient()
    resp = client.get(url, revalidate=True)
    if resp.status >= 400:
        raise HarvestError(f"Feed request failed with HTTP {resp.status}: {url}")

    body = resp.text()
    if not _looks_like_xml(body, resp.content_type):
        LOG.info("%s looks like a web page rather than a feed; looking for a feed link.", url)
        found = discover_feed_url(body, resp.url)
        if found and found != resp.url:
            LOG.info("Discovered feed: %s", found)
            return fetch_feed_text(found, client)
        for path in FEED_GUESS_PATHS:
            candidate = urllib.parse.urljoin(resp.url, path)
            if candidate == resp.url:
                continue
            try:
                probe = client.get(candidate)
            except HarvestError:
                continue
            if probe.status < 400 and _looks_like_xml(probe.text(), probe.content_type):
                LOG.info("Found a feed at %s", candidate)
                return probe.url, probe.text()
        raise HarvestError(
            f"{url} returned a web page, not a feed, and no feed link was found on it. "
            "Open the page and look for its RSS/subscribe link, then pass that URL instead.")
    return resp.url, body


def _looks_like_xml(body: str, content_type: str = "") -> bool:
    if content_type in {"text/html", "application/xhtml+xml"}:
        return False
    head = body.lstrip("\ufeff \t\r\n")[:512].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return False
    return head.startswith("<?xml") or "<rss" in head or "<feed" in head or "<rdf:rdf" in head


def _detect_root(xml_text: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        # Some feeds ship a stray BOM or leading whitespace/garbage before '<'.
        stripped = xml_text.lstrip("\ufeff \t\r\n")
        start = stripped.find("<")
        if start > 0:
            stripped = stripped[start:]
        try:
            return ET.fromstring(stripped)
        except ET.ParseError:
            raise HarvestError(f"Could not parse feed XML: {exc}") from exc


def _element_html(el: ET.Element | None) -> str:
    """Inner HTML of an Atom <content>/<summary> element.

    Atom carries content three ways: escaped text (type="html"/"text"), or
    live XHTML child elements (type="xhtml"). Reading `.text` alone loses
    everything after the first nested tag, and returns nothing at all for
    the xhtml form, so serialise any children back out.
    """
    if el is None:
        return ""
    if len(el) == 0:
        return el.text or ""
    parts = [el.text or ""]
    for child in el:
        parts.append(ET.tostring(child, encoding="unicode", method="html"))
    return "".join(parts)


def _parse_person(text: str) -> Person:
    text = text.strip()
    if "<" in text and ">" in text and "@" in text:
        name, _, rest = text.partition("<")
        email = rest.rstrip(">").strip()
        return Person(name=name.strip(), email=email)
    if "@" in text and " " not in text:
        return Person(email=text)
    return Person(name=text)


def _rss_enclosures(item: ET.Element) -> list[Enclosure]:
    encs: list[Enclosure] = []
    for enc in item.findall("enclosure"):
        url = enc.get("url", "").strip()
        if not url:
            continue
        length_raw = enc.get("length", "0")
        length = int(length_raw) if length_raw.isdigit() and int(length_raw) > 0 else None
        encs.append(Enclosure(url=url, mime=enc.get("type", ""), length=length))
    for media in item.findall("media:content", NS):
        url = media.get("url", "").strip()
        if not url or any(e.url == url for e in encs):
            continue
        length_raw = media.get("fileSize", "0")
        length = int(length_raw) if length_raw.isdigit() and int(length_raw) > 0 else None
        encs.append(Enclosure(url=url, mime=media.get("type", ""), length=length))
    return encs


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def _parse_explicit(text: str) -> bool | None:
    text = text.strip().lower()
    if text in {"yes", "true", "explicit"}:
        return True
    if text in {"no", "false", "clean"}:
        return False
    return None


def _rss_item_to_episode(item: ET.Element, source_feed: str) -> Episode:
    title = _text(_find(item, "title")) or "(untitled)"
    itunes_image = _find(item, "itunes:image")
    ep = Episode(
        guid=_text(_find(item, "guid")) or _text(_find(item, "link")) or title,
        title=title,
        link=_text(_find(item, "link")),
        published=parse_date(_text(_find(item, "pubDate", "dc:date"))),
        summary_html=_text(_find(item, "description")),
        content_html=_text(_find(item, "content:encoded")),
        subtitle=_text(_find(item, "itunes:subtitle")),
        categories=[_text(c) for c in item.findall("category") if _text(c)],
        keywords=[k.strip() for k in _text(_find(item, "itunes:keywords")).split(",") if k.strip()],
        duration_seconds=parse_duration(_text(_find(item, "itunes:duration"))),
        image_url=itunes_image.get("href", "") if itunes_image is not None else "",
        comments_url=_text(_find(item, "comments")),
        source_feed=source_feed,
        episode_type=_text(_find(item, "itunes:episodeType")),
        season=_int_or_none(_text(_find(item, "itunes:season"))),
        number=_int_or_none(_text(_find(item, "itunes:episode"))),
        explicit=_parse_explicit(_text(_find(item, "itunes:explicit"))),
    )
    ep.enclosures = _rss_enclosures(item)
    author_text = _text(_find(item, "author", "itunes:author", "dc:creator"))
    if author_text:
        ep.authors = [_parse_person(author_text)]
    for chapters in item.findall("podcast:chapters", NS):
        ep.chapters_url = chapters.get("url", "")
    for transcript in item.findall("podcast:transcript", NS):
        url = transcript.get("url", "")
        if url:
            ep.transcripts.append(Enclosure(url=url, mime=transcript.get("type", ""), role="transcript"))
    for soundbite in item.findall("podcast:soundbite", NS):
        try:
            ep.soundbites.append({
                "start": float(soundbite.get("startTime", "0")),
                "duration": float(soundbite.get("duration", "0")),
                "title": _text(soundbite),
            })
        except ValueError:
            pass
    return ep


def _parse_rss(root: ET.Element, source_url: str) -> Feed:
    channel = root.find("channel")
    if channel is None:
        raise HarvestError("RSS feed has no <channel> element.")

    self_link = _find(channel, "atom:link[@rel='self']")
    feed = Feed(
        url=source_url,
        self_url=self_link.get("href", "") if self_link is not None else source_url,
        title=_text(_find(channel, "title")) or "Untitled Feed",
        subtitle=_text(_find(channel, "itunes:subtitle")),
        description_html=_text(_find(channel, "description")),
        link=_text(_find(channel, "link")),
        language=_text(_find(channel, "language")),
        copyright=_text(_find(channel, "copyright")),
        generator=_text(_find(channel, "generator")),
        published=parse_date(_text(_find(channel, "pubDate"))),
        updated=parse_date(_text(_find(channel, "lastBuildDate"))),
        explicit=_parse_explicit(_text(_find(channel, "itunes:explicit"))),
        feed_type="rss",
    )
    image = _find(channel, "itunes:image")
    if image is not None and image.get("href"):
        feed.image_url = image.get("href", "")
    elif _find(channel, "image/url") is not None:
        feed.image_url = _text(_find(channel, "image/url"))

    owner = _find(channel, "itunes:owner")
    if owner is not None:
        feed.owner = Person(name=_text(_find(owner, "itunes:name")), email=_text(_find(owner, "itunes:email")))

    feed.categories = [c.get("text", "") for c in channel.findall("itunes:category", NS) if c.get("text")]
    author_text = _text(_find(channel, "itunes:author", "managingEditor", "dc:creator"))
    if author_text:
        feed.authors = [_parse_person(author_text)]

    for item in channel.findall("item"):
        try:
            feed.episodes.append(_rss_item_to_episode(item, source_url))
        except Exception as exc:  # noqa: BLE001 - one bad item shouldn't sink the feed
            LOG.warning("Skipping a malformed feed item: %s", exc)

    next_page = _find(channel, "atom:link[@rel='next']")
    if next_page is not None:
        feed.next_page_url = next_page.get("href", "")
    return feed


def _parse_atom(root: ET.Element, source_url: str) -> Feed:
    feed = Feed(
        url=source_url,
        title=_text(_find(root, "atom:title")) or "Untitled Feed",
        subtitle=_text(_find(root, "atom:subtitle")),
        description_html=_text(_find(root, "atom:subtitle")),
        updated=parse_date(_text(_find(root, "atom:updated"))),
        language=root.get(XML_LANG, "").strip(),
        feed_type="atom",
    )
    self_link = root.find("atom:link[@rel='self']", NS)
    alt_link = root.find("atom:link[@rel='alternate']", NS)
    feed.self_url = self_link.get("href", "") if self_link is not None else source_url
    feed.link = alt_link.get("href", "") if alt_link is not None else ""

    author = _find(root, "atom:author/atom:name")
    if author is not None:
        feed.authors = [Person(name=_text(author))]

    for entry in root.findall("atom:entry", NS):
        title = _text(_find(entry, "atom:title")) or "(untitled)"
        content_el = _find(entry, "atom:content")
        summary_el = _find(entry, "atom:summary")
        link_el = entry.find("atom:link[@rel='alternate']", NS)
        if link_el is None:
            link_el = entry.find("atom:link", NS)
        ep = Episode(
            guid=_text(_find(entry, "atom:id")) or title,
            title=title,
            link=link_el.get("href", "") if link_el is not None else "",
            published=parse_date(_text(_find(entry, "atom:published", "atom:updated"))),
            updated=parse_date(_text(_find(entry, "atom:updated"))),
            summary_html=_text(summary_el),
            content_html=_element_html(content_el),
            source_feed=source_url,
        )
        entry_lang = entry.get(XML_LANG, "").strip()
        if entry_lang:
            ep.extra["language"] = entry_lang
        author_el = _find(entry, "atom:author/atom:name")
        if author_el is not None:
            ep.authors = [Person(name=_text(author_el))]
        for link in entry.findall("atom:link", NS):
            rel = link.get("rel", "alternate")
            href = link.get("href", "")
            if rel == "enclosure" and href:
                length_raw = link.get("length", "0")
                length = int(length_raw) if length_raw.isdigit() and int(length_raw) > 0 else None
                ep.enclosures.append(Enclosure(url=href, mime=link.get("type", ""), length=length))
        feed.episodes.append(ep)
    return feed


def _parse_rdf(root: ET.Element, source_url: str) -> Feed:
    """Very old RSS 1.0/RDF feeds: a flat list of <rdf:RDF><channel/><item/>*."""
    channel = _find(root, "rss1:channel")
    feed = Feed(
        url=source_url,
        title=_text(_find(channel, "rss1:title")) if channel is not None else "Untitled Feed",
        link=_text(_find(channel, "rss1:link")) if channel is not None else "",
        description_html=_text(_find(channel, "rss1:description")) if channel is not None else "",
        language=_text(_find(channel, "dc:language")) if channel is not None else "",
        feed_type="rdf",
    )
    for item in root.findall("rss1:item", NS):
        title = _text(_find(item, "rss1:title")) or "(untitled)"
        feed.episodes.append(Episode(
            guid=_text(_find(item, "rss1:link")) or title,
            title=title,
            link=_text(_find(item, "rss1:link")),
            published=parse_date(_text(_find(item, "dc:date"))),
            summary_html=_text(_find(item, "rss1:description")),
            source_feed=source_url,
        ))
    return feed


def parse_feed(xml_text: str, source_url: str) -> Feed:
    root = _detect_root(xml_text)
    tag = root.tag.lower()
    if tag.endswith("rss"):
        feed = _parse_rss(root, source_url)
    elif tag.endswith("feed"):
        feed = _parse_atom(root, source_url)
    elif tag.endswith("rdf"):
        feed = _parse_rdf(root, source_url)
    else:
        raise HarvestError(f"Unrecognized feed root element: <{root.tag}>")

    for i, ep in enumerate(feed.episodes):
        ep.index = i

    from datetime import datetime, timezone
    feed.fetched_at = datetime.now(timezone.utc)
    feed.source_documents = [source_url]
    return feed


#: Hard stop on how many `<link rel="next">` hops to follow, so a feed that
#: points at itself (or a host that paginates forever) cannot loop us.
MAX_FEED_PAGES = 50


def fetch_and_parse(url: str, client: HttpClient | None = None,
                    follow_pagination: bool = True) -> Feed:
    """Fetch and parse a feed, optionally following RFC 5005 pagination.

    Large archives are commonly split across pages joined by
    `<link rel="next">`. Without following those you silently get only the
    most recent page's episodes, which looks like a complete harvest but
    isn't. Pages are merged into one Feed, de-duplicated by GUID.
    """
    final_url, xml_text = fetch_feed_text(url, client)
    feed = parse_feed(xml_text, final_url)

    if follow_pagination and feed.next_page_url:
        client = client or HttpClient()
        seen_pages = {final_url}
        seen_guids = {ep.guid for ep in feed.episodes if ep.guid}
        next_url = feed.next_page_url

        while next_url and next_url not in seen_pages and len(seen_pages) < MAX_FEED_PAGES:
            seen_pages.add(next_url)
            LOG.info("The feed continues on another page; reading %s", next_url)
            try:
                page_url, page_xml = fetch_feed_text(next_url, client)
                page = parse_feed(page_xml, page_url)
            except HarvestError as exc:
                # A broken later page shouldn't discard the episodes we already
                # have - report it and keep what was collected.
                LOG.warning("Stopping pagination at %s: %s", next_url, exc)
                break
            added = 0
            for ep in page.episodes:
                if ep.guid and ep.guid in seen_guids:
                    continue
                if ep.guid:
                    seen_guids.add(ep.guid)
                feed.episodes.append(ep)
                added += 1
            feed.source_documents.append(page_url)
            LOG.info("Read another page of the feed: %d more episode(s), %d so far.", added, len(feed.episodes))
            next_url = page.next_page_url

        if next_url and len(seen_pages) >= MAX_FEED_PAGES:
            LOG.warning("Stopped after %d feed pages; there may be more episodes at %s.",
                        MAX_FEED_PAGES, next_url)
        for i, ep in enumerate(feed.episodes):
            ep.index = i

    LOG.info("Found %d episode(s) in '%s'.", len(feed.episodes), feed.title)
    return feed
