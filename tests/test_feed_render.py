"""Feed parsing and output rendering."""

import datetime as dt

import pytest

from podharvest import render
from podharvest.config import Settings
from podharvest.feed import discover_feed_url, parse_feed
from podharvest.models import Enclosure, Episode, Feed, Person
from podharvest.util import HarvestError

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Test Show</title>
  <link>https://example.org/</link>
  <language>pt-BR</language>
  <description>A show.</description>
  <item>
    <title>Episode One</title>
    <link>https://example.org/1</link>
    <guid>guid-1</guid>
    <pubDate>Tue, 05 Mar 2024 10:00:00 +0000</pubDate>
    <description>Short summary.</description>
    <content:encoded>&lt;p&gt;Full body text.&lt;/p&gt;</content:encoded>
    <itunes:duration>1:02:05</itunes:duration>
    <itunes:season>2</itunes:season>
    <itunes:episode>7</itunes:episode>
    <enclosure url="https://cdn.example.org/1.mp3" type="audio/mpeg" length="51300000"/>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="ja">
  <title>Atom Show</title>
  <link rel="alternate" href="https://example.org/"/>
  <entry>
    <title>Entry One</title>
    <id>urn:1</id>
    <updated>2024-03-05T10:00:00Z</updated>
    <link rel="enclosure" type="audio/mpeg" href="https://cdn.example.org/a.mp3" length="100"/>
    <link rel="alternate" href="https://example.org/post-1"/>
    <content type="html">&lt;p&gt;Body&lt;/p&gt;</content>
  </entry>
</feed>"""


class TestFeedParsing:
    def test_rss_basics(self):
        feed = parse_feed(RSS, "https://example.org/feed")
        assert feed.title == "Test Show"
        assert feed.language == "pt-BR"
        assert len(feed.episodes) == 1
        ep = feed.episodes[0]
        assert ep.title == "Episode One"
        assert ep.duration_seconds == 3725
        assert ep.season == 2 and ep.number == 7
        assert ep.enclosures[0].kind == "audio"

    def test_rss_prefers_full_content_over_summary(self):
        ep = parse_feed(RSS, "u").episodes[0]
        assert "Full body text" in ep.best_html

    def test_atom_alternate_link_is_selected(self):
        # Element truthiness is False for a childless element, so `find(a) or
        # find(b)` used to silently pick the wrong link.
        ep = parse_feed(ATOM, "https://example.org/feed").episodes[0]
        assert ep.link == "https://example.org/post-1"

    def test_atom_enclosure_is_captured(self):
        ep = parse_feed(ATOM, "u").episodes[0]
        assert ep.enclosures[0].url == "https://cdn.example.org/a.mp3"

    def test_atom_language_comes_from_xml_lang(self):
        # Without this every Atom feed archived as lang="en", so a Japanese
        # show was read aloud by an English speech synthesiser.
        assert parse_feed(ATOM, "u").language == "ja"

    def test_unknown_root_element_is_rejected_clearly(self):
        with pytest.raises(HarvestError, match="Unrecognized feed root"):
            parse_feed("<html><body/></html>", "u")

    def test_leading_junk_before_the_declaration_is_tolerated(self):
        assert parse_feed("﻿\n  " + RSS, "u").title == "Test Show"

    def test_a_malformed_item_does_not_sink_the_feed(self):
        broken = RSS.replace("<itunes:duration>1:02:05</itunes:duration>",
                             "<itunes:duration>not-a-duration</itunes:duration>")
        assert len(parse_feed(broken, "u").episodes) == 1


class TestFeedDiscovery:
    def test_link_rel_alternate_is_found(self):
        html = ('<html><head><link rel="alternate" type="application/rss+xml" '
                'href="/feed"></head></html>')
        assert discover_feed_url(html, "https://ex.test/show") == "https://ex.test/feed"

    def test_absolute_href_is_kept(self):
        html = '<link rel="alternate" type="application/atom+xml" href="https://other.test/f">'
        assert discover_feed_url(html, "https://ex.test/") == "https://other.test/f"

    def test_page_without_a_feed_link_returns_none(self):
        assert discover_feed_url("<html><head></head></html>", "https://ex.test/") is None


def _episode(**kw) -> Episode:
    base = {
        "title": "Episode One",
        "link": "https://example.org/1",
        "published": dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc),
        "duration_seconds": 3725,
        "content_html": "<p>Body.</p>",
        "index": 0,
    }
    base.update(kw)
    return Episode(**base)


class TestRenderEscaping:
    """Feed values reach the page without passing through the sanitizer."""

    def test_author_markup_is_escaped(self):
        ep = _episode()
        ep.authors = [Person(name="A <script>alert(1)</script>")]
        html = render.render_episode_html(ep, Feed(title="F"))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_category_markup_is_escaped(self):
        ep = _episode(categories=["<img src=x onerror=alert(1)>"])
        html = render.render_episode_html(ep, Feed(title="F"))
        assert "<img src=x" not in html

    def test_title_ampersand_is_escaped(self):
        html = render.render_episode_html(_episode(title="Q&A"), Feed(title="F"))
        assert "Q&amp;A" in html
        assert "Q&A<" not in html

    def test_original_post_is_a_real_link(self):
        # This used to emit `<https://...>`, which the HTML tokenizer read as
        # a bogus start tag, so the link rendered as nothing at all.
        html = render.render_episode_html(_episode(), Feed(title="F"))
        assert '<a href="https://example.org/1"' in html


class TestRenderStructure:
    def test_single_h1_and_no_skipped_levels(self):
        ep = _episode(content_html="<h1>Feed heading</h1><p>x</p><h3>Deep</h3><h2></h2>")
        html = render.render_episode_html(ep, Feed(title="F"))
        assert html.count("<h1>") == 1
        assert "<h2>Feed heading</h2>" in html
        assert "<h3>Deep</h3>" in html

    def test_main_landmark_and_back_link(self):
        html = render.render_episode_html(_episode(), Feed(title="F"))
        assert "<main>" in html
        assert 'href="../index.html"' in html

    def test_enclosures_are_linked_in_html(self):
        ep = _episode()
        ep.enclosures = [Enclosure(url="https://cdn.test/1.mp3", mime="audio/mpeg", length=1024)]
        html = render.render_episode_html(ep, Feed(title="F"))
        assert 'href="https://cdn.test/1.mp3"' in html

    def test_metadata_uses_a_description_list(self):
        html = render.render_episode_html(_episode(), Feed(title="F"))
        assert "<dt>Published</dt>" in html

    def test_episode_without_metadata_emits_no_empty_list(self):
        html = render.render_episode_html(
            Episode(title="Bare", content_html="<p>x</p>"), Feed(title="F"))
        assert "<dl" not in html
        assert "<ul>\n</ul>" not in html

    def test_index_html_links_every_episode(self):
        feed = Feed(title="F", language="en")
        feed.episodes = [_episode(), _episode(title="Episode Two", index=1)]
        html = render.render_feed_index_html(feed, Settings())
        assert html.count("<li>") == 2
        assert 'href="html/' in html


class TestLanguage:
    @pytest.mark.parametrize("raw,expected", [
        ("en_US", "en-US"), ("en-GB", "en-GB"), ("pt-BR", "pt-BR"),
        ("English", "en"), ("", "en"), ("ja", "ja"),
    ])
    def test_normalisation(self, raw, expected):
        assert render.normalize_lang(raw) == expected

    def test_attribute_injection_is_neutralised(self):
        feed = Feed(title="F", language='en" onload="alert(1)')
        html = render.render_episode_html(_episode(), feed)
        assert "onload" not in html


class TestNamingTemplate:
    @pytest.mark.parametrize("template,expected", [
        ("{date}-{slug}", "2024-03-05-episode-one"),
        ("S{season}E{number}-{slug}", "S02E007-episode-one"),
        ("{index}-{slug}", "001-episode-one"),
        ("{year}{month}{day}-{slug}", "20240305-episode-one"),
    ])
    def test_templates(self, template, expected):
        ep = _episode(season=2, number=7)
        assert render.episode_slug(ep, Settings(naming_template=template)) == expected

    def test_invalid_template_falls_back_instead_of_raising(self):
        assert render.episode_slug(_episode(), Settings(naming_template="{nope}"))

    def test_an_already_named_episode_keeps_its_name(self):
        ep = _episode(slug="already-set")
        assert render.episode_slug(ep, Settings(naming_template="{index}")) == "already-set"
