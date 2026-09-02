"""HTML conversion: to Markdown, to plain text, and to sanitised HTML.

Implemented on top of `html.parser` so the tool has no third-party dependency.
Handles headings, emphasis, links, images, lists (nested), block quotes, code,
tables, horizontal rules, and captures media URLs found in `audio`, `video`,
`source` and `iframe` elements.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "figure", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre",
    "table", "tr", "hr", "aside", "main", "nav", "dl", "dt", "dd",
}
SKIP_TAGS = {"script", "style", "head", "noscript", "template", "svg"}
VOID_TAGS = {"br", "hr", "img", "source", "input", "meta", "link", "area", "base", "col", "embed", "param", "track", "wbr"}

# Attributes that may carry script; stripped from sanitised output.
_EVENT_ATTR = re.compile(r"^on", re.I)
_DANGEROUS_SCHEME = re.compile(r"^(javascript|vbscript|livescript|mocha|data:text/html)", re.I)
# Characters a browser strips from a URL before resolving its scheme. Leaving
# them in means an obfuscated payload reads as harmless to a naive prefix
# check but still executes, so they are removed before the scheme is tested.
_URL_NOISE = re.compile(r"[\x00-\x20\x7f\u00a0\u2000-\u200f\u2028\u2029\ufeff]")


def is_dangerous_url(value: str) -> bool:
    """True if `value` would execute script when used as an href/src.

    Normalises the way a browser does - decoding HTML entities and stripping
    control characters, whitespace and zero-width marks - before testing the
    scheme, so obfuscated payloads do not slip past.
    """
    if not value:
        return False
    candidate = html.unescape(value)
    candidate = _URL_NOISE.sub("", candidate)
    return bool(_DANGEROUS_SCHEME.match(candidate))

ALLOWED_HTML_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "code", "pre", "blockquote",
    "ul", "ol", "li", "a", "img", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "table", "thead", "tbody", "tfoot", "colgroup", "col", "tr", "th", "td",
    "caption", "figure", "figcaption", "audio", "video", "source", "track",
    "span", "div", "dl", "dt", "dd", "small", "sub", "sup", "abbr", "cite",
    "q", "time", "mark", "details", "summary",
}
ALLOWED_HTML_ATTRS = {
    "href", "src", "alt", "title", "controls", "lang", "dir", "datetime",
    "colspan", "rowspan", "scope", "type", "headers", "id", "start",
    # <track> carries the caption/subtitle files. Dropping these would strip
    # captions out of archived media, which for this tool is the one kind of
    # data loss least acceptable.
    "kind", "srclang", "label", "default", "span", "open",
}


@dataclass
class Extracted:
    markdown: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)   # (text, url)
    images: list[tuple[str, str]] = field(default_factory=list)  # (alt, url)
    media: list[tuple[str, str]] = field(default_factory=list)   # (kind, url)


class _MarkdownParser(HTMLParser):
    """Streaming HTML to Markdown converter."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.images: list[tuple[str, str]] = []
        self.media: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._list_stack: list[dict] = []
        self._quote_depth = 0
        self._pre = 0
        self._href: str | None = None
        self._link_buf: list[str] = []
        self._in_table = False
        self._row: list[str] = []
        self._cell: list[str] | None = None
        self._table_rows: list[list[str]] = []
        self._header_row = False
        self._had_header = False

    # -- emit helpers ------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._cell is not None:
            self._cell.append(text)
        elif self._href is not None:
            self._link_buf.append(text)
        else:
            self.out.append(text)

    def _newline(self, count: int = 1) -> None:
        if self._cell is not None:
            return
        buf = "".join(self.out[-4:])
        existing = len(buf) - len(buf.rstrip("\n")) if buf else 99
        for _ in range(max(0, count - existing)):
            self.out.append("\n")

    def _prefix(self) -> str:
        return "> " * self._quote_depth

    # -- table state -------------------------------------------------------
    #
    # </td>, </th> and </tr> are all optional in HTML. Rather than trusting
    # them to arrive, every transition that *implies* a close calls these,
    # and they are safe to call when nothing is open.

    def _close_cell(self) -> None:
        if self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row:
            self._table_rows.append(self._row)
            if self._header_row:
                self._had_header = True
        self._row = []
        self._header_row = False

    def _reset_table(self) -> None:
        self._in_table = False
        self._table_rows = []
        self._row = []
        self._cell = None
        self._header_row = False
        self._had_header = False

    # -- HTMLParser hooks --------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: C901
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "br":
            self._emit("  \n" if self._cell is None else " ")
            return
        if tag == "hr":
            self._newline(2)
            self._emit("---")
            self._newline(2)
            return
        if tag in {"strong", "b"}:
            self._emit("**")
            return
        if tag in {"em", "i"}:
            self._emit("*")
            return
        if tag in {"del", "s", "strike"}:
            self._emit("~~")
            return
        if tag == "code" and not self._pre:
            self._emit("`")
            return
        if tag == "pre":
            self._pre += 1
            self._newline(2)
            self._emit("```\n")
            return
        if tag == "a":
            self._href = a.get("href", "")
            self._link_buf = []
            return
        if tag == "img":
            src, alt = a.get("src", ""), a.get("alt", "")
            if src:
                self.images.append((alt, src))
                self._emit(f"![{alt or 'image'}]({src})")
            return
        if tag in {"audio", "video", "source", "iframe", "embed"}:
            src = a.get("src", "")
            if src:
                kind = "video" if tag in {"video", "iframe", "embed"} else "audio"
                self.media.append((kind, src))
                self._newline(2)
                self._emit(f"[Media ({kind}): {src}]({src})")
                self._newline(2)
            return
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            self._newline(2)
            self._emit(self._prefix() + "#" * min(6, int(tag[1])) + " ")
            return
        if tag in {"ul", "ol"}:
            start_attr = (a.get("start") or "1").strip()
            start = int(start_attr) if start_attr.lstrip("-").isdigit() else 1
            self._list_stack.append({"ordered": tag == "ol", "n": start})
            self._newline(2 if len(self._list_stack) == 1 else 1)
            return
        if tag == "li":
            self._newline(1)
            depth = max(0, len(self._list_stack) - 1)
            indent = "  " * depth
            if self._list_stack and self._list_stack[-1]["ordered"]:
                n = self._list_stack[-1]["n"]
                self._list_stack[-1]["n"] = n + 1
                self._emit(f"{self._prefix()}{indent}{n}. ")
            else:
                self._emit(f"{self._prefix()}{indent}- ")
            return
        if tag == "blockquote":
            self._quote_depth += 1
            self._newline(2)
            self._emit(self._prefix())
            return
        if tag == "table":
            self._in_table = True
            self._table_rows = []
            self._had_header = False
            self._newline(2)
            return
        if tag == "tr" and self._in_table:
            self._close_row()      # a new row implies the previous one ended
            return
        if tag in {"td", "th"} and self._in_table:
            self._close_cell()     # a new cell implies the previous one ended
            self._cell = []
            if tag == "th":
                self._header_row = True
            return
        if tag == "caption" and self._in_table:
            self._close_cell()
            self._cell = []
            return
        if tag in BLOCK_TAGS:
            self._newline(2)
            if self._quote_depth:
                self._emit(self._prefix())

    def handle_endtag(self, tag: str) -> None:  # noqa: C901
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag in {"del", "s", "strike"}:
            self._emit("~~")
        elif tag == "code" and not self._pre:
            self._emit("`")
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self._emit("\n```")
            self._newline(2)
        elif tag == "a":
            label = "".join(self._link_buf).strip()
            href = (self._href or "").strip()
            self._href = None
            self._link_buf = []
            if href and not is_dangerous_url(href):
                self.links.append((label or href, href))
                self._emit(f"[{label or href}]({href})" if label != href else f"<{href}>")
            else:
                self._emit(label)
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
            self._newline(2 if not self._list_stack else 1)
        elif tag == "li":
            pass
        elif tag == "blockquote":
            self._quote_depth = max(0, self._quote_depth - 1)
            self._newline(2)
        elif tag in {"td", "th", "caption"} and self._in_table:
            self._close_cell()
        elif tag == "tr" and self._in_table:
            self._close_row()
        elif tag == "table":
            self._flush_table()
        elif tag.startswith("h") and len(tag) == 2 and tag[1].isdigit() or tag in BLOCK_TAGS:
            self._newline(2)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._pre:
            self._emit(data)
            return
        if not data.strip():
            if data and self.out and not self.out[-1].endswith((" ", "\n")):
                self._emit(" ")
            return
        text = re.sub(r"\s+", " ", data)
        # A literal '|' inside a cell would otherwise be read as a column
        # separator and break the grid. (This test used to be inverted, so
        # pipes were escaped everywhere *except* where it mattered.)
        if self._cell is not None:
            text = text.replace("|", "\\|")
        self._emit(text)

    def _flush_table(self) -> None:
        # Drain any cell/row the markup never closed, then clear *all* table
        # state unconditionally. Leaving self._cell set here is what used to
        # swallow the rest of the document.
        self._close_row()
        rows, had_header = self._table_rows, self._had_header
        self._reset_table()
        self._had_header = had_header
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        header = rows[0] if self._had_header else [f"Column {i + 1}" for i in range(width)]
        body = rows[1:] if self._had_header else rows
        self._newline(2)
        self._emit("| " + " | ".join(header) + " |\n")
        self._emit("| " + " | ".join(["---"] * width) + " |\n")
        for row in body:
            self._emit("| " + " | ".join(row) + " |\n")
        self._newline(2)


    def close(self) -> None:
        # A feed that opens <table> and never closes it would otherwise strand
        # every row - and every following paragraph - in the table buffer.
        if self._in_table:
            self._flush_table()
        super().close()


def _tidy(md: str) -> str:
    md = md.replace("\u00a0", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"(?m)^[ \t]+$", "", md)
    return md.strip()


def html_to_markdown(source: str) -> Extracted:
    """Convert an HTML fragment to Markdown plus extracted link/media inventory."""
    if not source:
        return Extracted()
    parser = _MarkdownParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception:  # malformed markup: fall back to a naive strip
        stripped = re.sub(r"<[^>]+>", " ", source)
        text = _tidy(html.unescape(stripped))
        return Extracted(markdown=text, text=text)
    md = _tidy("".join(parser.out))
    return Extracted(
        markdown=md,
        text=markdown_to_text(md),
        links=parser.links,
        images=parser.images,
        media=parser.media,
    )


def markdown_to_text(md: str) -> str:
    """Flatten Markdown into readable plain text, keeping link targets visible."""
    if not md:
        return ""
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"[image: \1 (\2)]", md)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: (
        m.group(1) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})"), text)
    text = re.sub(r"<((?:https?)://[^>\s]+)>", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__|~~)", "", text)
    text = re.sub(r"(?<!\w)[*_](?=\S)([^*_]+)(?<=\S)[*_](?!\w)", r"\1", text)
    text = text.replace("```", "").replace("`", "")
    text = re.sub(r"^>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*---+\s*$", "-" * 40, text, flags=re.M)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_text(source: str) -> str:
    return html_to_markdown(source).text


class _Sanitizer(HTMLParser):
    """Allow-list sanitiser so feed HTML can be safely embedded in our pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0
        self._open: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip or tag not in ALLOWED_HTML_TAGS:
            return
        safe = []
        for key, value in attrs:
            key = key.lower()
            value = value or ""
            if _EVENT_ATTR.match(key) or key not in ALLOWED_HTML_ATTRS:
                continue
            if key in {"href", "src"} and is_dangerous_url(value):
                continue
            safe.append(f' {key}="{html.escape(value, quote=True)}"')
        if tag == "a":
            safe.append(' rel="noopener noreferrer"')
        if tag == "img" and not any(k.lower() == "alt" for k, _ in attrs):
            safe.append(' alt=""')
        self.out.append(f"<{tag}{''.join(safe)}>")
        if tag not in VOID_TAGS:
            self._open.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip or tag not in ALLOWED_HTML_TAGS or tag in VOID_TAGS:
            return
        if tag in self._open:
            while self._open:
                open_tag = self._open.pop()
                self.out.append(f"</{open_tag}>")
                if open_tag == tag:
                    break

    def handle_data(self, data):
        if not self._skip:
            self.out.append(html.escape(data, quote=False))

    def close(self):
        super().close()
        while self._open:
            self.out.append(f"</{self._open.pop()}>")


def sanitize_html(source: str) -> str:
    if not source:
        return ""
    s = _Sanitizer()
    try:
        s.feed(source)
        s.close()
    except Exception:
        return html.escape(re.sub(r"<[^>]+>", " ", source))
    return "".join(s.out).strip()


def first_sentences(text: str, limit: int = 320) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:stop + 1] if stop > limit * 0.5 else cut.rsplit(" ", 1)[0]) + " ..."

_HEADING_RE = re.compile(r"<(/?)(h[1-6])\b([^>]*)>", re.I)
_EMPTY_HEADING_RE = re.compile(r"<(h[1-6])\b[^>]*>\s*</\1>", re.I)


def drop_empty_headings(fragment: str) -> str:
    """Remove headings with no text.

    An empty heading is worse than no heading: screen-reader heading
    navigation stops on it and announces a level followed by silence.
    """
    previous = None
    while previous != fragment:      # nested empties need more than one pass
        previous = fragment
        fragment = _EMPTY_HEADING_RE.sub("", fragment)
    return fragment


def demote_headings(fragment: str, min_level: int = 2) -> str:
    """Re-rank a fragment's headings to start at `min_level`.

    Feed bodies routinely contain their own <h1>, which collides with the
    page title, and often skip levels. Rank-mapping the distinct levels that
    are actually present fixes both at once and preserves relative nesting.
    """
    levels = sorted({int(m.group(2)[1]) for m in _HEADING_RE.finditer(fragment)})
    if not levels:
        return fragment
    mapping = {level: min(6, min_level + i) for i, level in enumerate(levels)}

    def _remap(match: re.Match) -> str:
        closing, tag, attrs = match.group(1), match.group(2).lower(), match.group(3)
        return f"<{closing}h{mapping[int(tag[1])]}{attrs if not closing else ''}>"

    return _HEADING_RE.sub(_remap, fragment)

