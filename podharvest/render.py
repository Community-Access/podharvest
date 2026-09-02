"""Render an Episode/Feed into Markdown, sanitized HTML, plain text, JSON, and CSV."""

from __future__ import annotations

import csv
import io
import json
import re
from html import escape
from pathlib import Path

from podharvest.convert import (
    demote_headings,
    drop_empty_headings,
    first_sentences,
    html_to_markdown,
    sanitize_html,
)
from podharvest.models import Episode, Feed
from podharvest.util import LOG, date_prefix, human_duration, iso, safe_filename, slugify, write_text

HTML_DOC = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
/* Deliberately minimal. No colours and no font sizes are set, so the
   reader's own theme, contrast settings and text size all win; the only
   thing constrained is line length, which is unreadable at full width on a
   wide monitor. `color-scheme` opts the page into the OS dark theme rather
   than forcing stark white. */
:root {{ color-scheme: light dark; }}
body {{ max-width: 70ch; margin: 0 auto; padding: 1rem; }}
img, video {{ max-width: 100%; height: auto; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid; padding: 0.25rem 0.5rem; text-align: left; }}
</style>
</head>
<body>
<header>
<a href="../index.html">All episodes of {feed_title}</a>
</header>
<main>
<article>
<h1>{title}</h1>
{meta}
{body}
{enclosures}
</article>
</main>
</body>
</html>
"""


#: Placeholders accepted by `Settings.naming_template`.
NAMING_PLACEHOLDERS = ("date", "slug", "title", "index", "season", "number",
                       "year", "month", "day")

DEFAULT_NAMING_TEMPLATE = "{date}-{slug}"


def naming_fields(ep: Episode) -> dict[str, str]:
    """Values available to `Settings.naming_template` for one episode."""
    published = ep.published
    return {
        "date": date_prefix(published),
        "year": published.strftime("%Y") if published else "0000",
        "month": published.strftime("%m") if published else "00",
        "day": published.strftime("%d") if published else "00",
        "slug": slugify(ep.title),
        "title": slugify(ep.title),
        "index": f"{ep.index + 1:03d}",
        "season": f"{ep.season:02d}" if ep.season else "00",
        "number": f"{ep.number:03d}" if ep.number else "000",
    }


def episode_slug(ep: Episode, settings=None) -> str:
    """Filename stem for an episode, honouring `Settings.naming_template`.

    An episode that has already been named keeps that name, so re-running a
    harvest after changing the template does not orphan the files written by
    the previous run.
    """
    if ep.slug:
        return ep.slug
    template = getattr(settings, "naming_template", "") or DEFAULT_NAMING_TEMPLATE
    if "/" in template or chr(92) in template:
        LOG.warning("naming_template %r contains a path separator, but it names a file, "
                    "not a folder. The separator will be stripped.", template)
    fields = naming_fields(ep)
    try:
        name = template.format(**fields)
    except (KeyError, IndexError, ValueError) as exc:
        LOG.warning("Ignoring invalid naming_template %r (%s). Placeholders: %s",
                    template, exc, ", ".join("{" + k + "}" for k in NAMING_PLACEHOLDERS))
        name = DEFAULT_NAMING_TEMPLATE.format(**fields)
    # The template controls the shape of the name; safe_filename guarantees the
    # result is still a legal filename on every platform.
    return safe_filename(name, default=fields["date"]) or fields["date"]


_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def normalize_lang(value: str) -> str:
    """Coerce a feed's language into something valid for `lang=`.

    Feeds supply `en_US` and `English` as often as `en-US`. An ill-formed
    value makes assistive technology fall back to its default voice, so
    anything that cannot be repaired becomes plain `en`.
    """
    candidate = (value or "").strip().replace("_", "-")
    if _LANG_RE.match(candidate):
        return candidate
    if candidate[:2].isalpha() and len(candidate) >= 2:
        prefix = candidate[:2].lower()
        if _LANG_RE.match(prefix):
            return prefix
    return "en"


def _episode_meta_items(ep: Episode) -> list[tuple[str, str, str]]:
    """Episode metadata as (label, value, url) triples.

    Kept as structured data rather than pre-formatted strings so each output
    format can escape and mark it up correctly. The previous string-based
    version leaked Markdown syntax into the HTML output and, because feed
    values were interpolated raw, let a feed inject arbitrary markup into
    every archived page.
    """
    items: list[tuple[str, str, str]] = []
    if ep.published:
        items.append(("Published", ep.published.strftime("%B %d, %Y"), ""))
    if ep.authors:
        items.append(("By", ", ".join(a.display() for a in ep.authors), ""))
    if ep.duration_seconds:
        items.append(("Duration", human_duration(ep.duration_seconds), ""))
    if ep.categories:
        items.append(("Categories", ", ".join(ep.categories), ""))
    if ep.link:
        items.append(("Original post", ep.link, ep.link))
    return items


def _episode_meta_lines(ep: Episode) -> list[str]:
    """Metadata rendered as Markdown, one bold-labelled line per item."""
    lines = []
    for label, value, url in _episode_meta_items(ep):
        lines.append(f"**{label}:** <{url}>" if url else f"**{label}:** {value}")
    return lines


def _episode_meta_text(ep: Episode) -> list[str]:
    """Metadata rendered as plain text."""
    return [f"{label}: {value}" for label, value, _ in _episode_meta_items(ep)]


def _episode_meta_html(ep: Episode) -> str:
    """Metadata rendered as an escaped HTML list.

    Every value is escaped: feed content is untrusted, and this list is the one
    place episode metadata reaches the page without passing through
    `sanitize_html`.
    """
    items = _episode_meta_items(ep)
    if not items:
        return ""     # an empty <ul> announces as "list, 0 items"
    rows = []
    for label, value, url in items:
        safe_value = escape(value)
        if url:
            safe_url = escape(url, quote=True)
            safe_value = f'<a href="{safe_url}" rel="noopener noreferrer">{safe_value}</a>'
        # <dl> carries the label-to-value relationship programmatically;
        # a <ul> leaves it implied by a colon in a flat text node.
        rows.append(f"<dt>{escape(label)}</dt><dd>{safe_value}</dd>")
    return '<dl class="episode-meta">\n' + "\n".join(rows) + "\n</dl>"


def render_episode_markdown(ep: Episode, feed: Feed) -> str:
    extracted = html_to_markdown(ep.best_html)
    parts = [f"# {ep.title}", ""]
    meta = _episode_meta_lines(ep)
    if meta:
        parts += meta + [""]
    parts.append(extracted.markdown or "*(no content)*")
    if ep.enclosures:
        parts += ["", "## Enclosures", ""]
        for enc in ep.enclosures:
            parts.append(f"- [{enc.kind}] [{enc.url}]({enc.url}) ({enc.human_length}, {enc.mime or 'unknown type'})")
    parts += ["", "---", f"*Source feed: {feed.title}. GUID: `{ep.guid}`*"]
    return "\n".join(parts).strip() + "\n"


def _enclosures_html(ep: Episode) -> str:
    """Download links for an episode's enclosures.

    The Markdown output has always had these; the HTML output had none, so an
    HTML-only reader got the show notes with no way to reach the audio.
    """
    if not ep.enclosures:
        return ""
    rows = []
    for enc in ep.enclosures:
        label = f"{enc.kind.capitalize()}: {ep.title}"
        detail = ", ".join(part for part in (enc.mime or "", enc.human_length) if part and part != "unknown")
        text = escape(label) + (f" ({escape(detail)})" if detail else "")
        rows.append(f'<li><a href="{escape(enc.url, quote=True)}" rel="noopener noreferrer">{text}</a></li>')
    return ('<section aria-labelledby="enclosures-heading">\n'
            '<h2 id="enclosures-heading">Downloads</h2>\n<ul>\n'
            + "\n".join(rows) + "\n</ul>\n</section>")


def render_episode_html(ep: Episode, feed: Feed) -> str:
    body = sanitize_html(ep.best_html)
    # The feed body brings its own headings, which would otherwise collide
    # with the page <h1> and skip levels.
    # Drop empties first: an empty heading still occupies a rank, so demoting
    # before removing it leaves a gap in the sequence.
    body = demote_headings(drop_empty_headings(body), min_level=2) or "<p><em>(no content)</em></p>"
    return HTML_DOC.format(
        lang=escape(normalize_lang(feed.language), quote=True),
        title=escape(ep.title),
        feed_title=escape(feed.title),
        meta=_episode_meta_html(ep),
        body=body,
        enclosures=_enclosures_html(ep),
    )


def render_episode_text(ep: Episode) -> str:
    extracted = html_to_markdown(ep.best_html)
    lines = [ep.title, "=" * min(len(ep.title), 72), ""]
    lines.extend(_episode_meta_text(ep))
    if lines[-1] != "":
        lines.append("")
    lines.append(extracted.text or "(no content)")
    return "\n".join(lines).strip() + "\n"


def render_episode_json(ep: Episode) -> str:
    return json.dumps(ep.to_dict(), indent=2, ensure_ascii=False)


def write_episode_outputs(ep: Episode, feed: Feed, feed_dir: Path, settings) -> None:
    """Write every enabled output format for one episode, each into its own
    per-format subfolder under `feed_dir` (markdown/, html/, text/, json/)."""
    slug = episode_slug(ep, settings)
    ep.slug = slug
    if getattr(settings, "write_markdown", True):
        ep.markdown_path = str(write_text(feed_dir / "markdown" / f"{slug}.md", render_episode_markdown(ep, feed)))
    if getattr(settings, "write_html", True):
        ep.html_path = str(write_text(feed_dir / "html" / f"{slug}.html", render_episode_html(ep, feed)))
    if getattr(settings, "write_text", True):
        ep.text_path = str(write_text(feed_dir / "text" / f"{slug}.txt", render_episode_text(ep)))
    if getattr(settings, "write_json", True):
        ep.json_path = str(write_text(feed_dir / "json" / f"{slug}.json", render_episode_json(ep)))


def render_feed_index_markdown(feed: Feed, settings=None) -> str:
    lines = [f"# {feed.title}", ""]
    if feed.description_html:
        lines.append(first_sentences(html_to_markdown(feed.description_html).text, 400))
        lines.append("")
    lines.append(f"- **Link:** <{feed.link}>" if feed.link else "")
    lines.append(f"- **Language:** {feed.language}")
    lines.append(f"- **Episodes:** {len(feed.episodes)}")
    lines.append(f"- **Fetched:** {iso(feed.fetched_at)}")
    lines = [line for line in lines if line != ""] + ["", "## Episodes", ""]
    for ep in feed.episodes:
        date = ep.published.strftime("%Y-%m-%d") if ep.published else "unknown date"
        rel = f"markdown/{episode_slug(ep, settings)}.md"
        lines.append(f"- {date} - [{ep.title}]({rel})")
    return "\n".join(lines).strip() + "\n"


INDEX_DOC = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ max-width: 70ch; margin: 0 auto; padding: 1rem; }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
{description}
<dl>
{meta}
</dl>
<h2>Episodes</h2>
<ol>
{episodes}
</ol>
</main>
</body>
</html>
"""


def render_feed_index_html(feed: Feed, settings=None) -> str:
    """An index page linking every episode's HTML output.

    Without this the HTML tree is a set of orphan pages with no inbound or
    outbound links - the Markdown index only ever pointed at `markdown/`.
    """
    meta = []
    if feed.link:
        safe = escape(feed.link, quote=True)
        meta.append(f'<dt>Link</dt><dd><a href="{safe}" rel="noopener noreferrer">{escape(feed.link)}</a></dd>')
    meta.append(f"<dt>Language</dt><dd>{escape(normalize_lang(feed.language))}</dd>")
    meta.append(f"<dt>Episodes</dt><dd>{len(feed.episodes)}</dd>")
    if feed.fetched_at:
        meta.append(f"<dt>Fetched</dt><dd>{escape(iso(feed.fetched_at) or '')}</dd>")

    items = []
    for ep in feed.episodes:
        date = ep.published.strftime("%Y-%m-%d") if ep.published else "unknown date"
        href = escape(f"html/{episode_slug(ep, settings)}.html", quote=True)
        items.append(f'<li><a href="{href}">{escape(ep.title)}</a> '
                     f'<span class="date">({escape(date)})</span></li>')

    description = ""
    if feed.description_html:
        summary = first_sentences(html_to_markdown(feed.description_html).text, 400)
        description = f"<p>{escape(summary)}</p>"

    return INDEX_DOC.format(
        lang=escape(normalize_lang(feed.language), quote=True),
        title=escape(feed.title),
        description=description,
        meta="\n".join(meta),
        episodes="\n".join(items) or "<li>No episodes found.</li>",
    )


def render_feed_csv(feed: Feed) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["index", "title", "published", "duration_seconds", "link", "guid",
                     "num_enclosures", "primary_audio_url"])
    for ep in feed.episodes:
        primary = ep.primary_audio
        writer.writerow([ep.index, ep.title, iso(ep.published), ep.duration_seconds or "",
                         ep.link, ep.guid, len(ep.enclosures), primary.url if primary else ""])
    return buf.getvalue()


def write_feed_outputs(feed: Feed, feed_dir: Path, settings) -> None:
    write_text(feed_dir / "index.md", render_feed_index_markdown(feed, settings))
    if getattr(settings, "write_html", True):
        write_text(feed_dir / "index.html", render_feed_index_html(feed, settings))
    write_text(feed_dir / "feed.json", json.dumps(feed.to_dict(), indent=2, ensure_ascii=False))
    if getattr(settings, "write_csv", False):
        write_text(feed_dir / "episodes.csv", render_feed_csv(feed))
