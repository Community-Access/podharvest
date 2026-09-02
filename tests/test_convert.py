"""HTML conversion and sanitisation.

The regression tests here cover defects that caused silent data loss or
security problems in earlier versions, so each one names what it guards.
"""

from podharvest.convert import (
    demote_headings,
    drop_empty_headings,
    html_to_markdown,
    html_to_text,
    is_dangerous_url,
    markdown_to_text,
    sanitize_html,
)


class TestTables:
    """A table with implied end tags used to swallow the rest of the episode.

    `</td>` and `</tr>` are both optional in HTML and feeds omit them freely.
    The parser only closed a cell on an explicit `</td>`, so an open cell
    diverted every subsequent character into a buffer that was never drained,
    and the whole document rendered as an empty string.
    """

    def test_implied_cell_and_row_end_tags_keep_the_table(self):
        md = html_to_markdown("<table><tr><td>a</td><td>b</table>").markdown
        assert "| a | b |" in md

    def test_content_after_an_unclosed_table_survives(self):
        md = html_to_markdown(
            "<table><tr><td>a</td><td>b</table><p>after the table</p>").markdown
        assert "after the table" in md

    def test_implied_end_tags_mid_row(self):
        md = html_to_markdown(
            "<table><tr><td>a<td>b<tr><td>c<td>d</table><p>tail</p>").markdown
        assert "| a | b |" in md
        assert "| c | d |" in md
        assert "tail" in md

    def test_table_that_is_never_closed_still_flushes(self):
        md = html_to_markdown("<table><tr><td>x</td></tr>").markdown
        assert "| x |" in md

    def test_header_row_is_used_when_th_is_present(self):
        md = html_to_markdown(
            "<table><tr><th>H1</th><th>H2</th></tr><tr><td>a</td><td>b</td></tr></table>").markdown
        assert md.splitlines()[0] == "| H1 | H2 |"

    def test_pipe_inside_a_cell_is_escaped(self):
        # An unescaped '|' reads as a column separator and shifts every
        # following cell one column left.
        md = html_to_markdown("<table><tr><td>a|b</td><td>c</td></tr></table>").markdown
        assert r"a\|b" in md

    def test_non_numeric_ol_start_does_not_sink_the_document(self):
        md = html_to_markdown('<ol start="abc"><li>one</li></ol><p>after</p>').markdown
        assert "one" in md
        assert "after" in md


class TestSanitizer:
    def test_script_and_style_are_removed_with_their_contents(self):
        out = sanitize_html("<p>ok</p><script>alert(1)</script><style>p{color:red}</style>")
        assert "alert" not in out
        assert "color:red" not in out
        assert "<p>ok</p>" in out

    def test_event_handlers_are_stripped(self):
        out = sanitize_html('<p onclick="alert(1)">text</p>')
        assert "onclick" not in out

    def test_caption_tracks_are_preserved(self):
        # Stripping <track> would delete captions from archived media - the
        # least acceptable kind of loss for this tool.
        out = sanitize_html(
            '<video controls><source src="v.mp4">'
            '<track kind="captions" src="c.vtt" srclang="en" label="English"></video>')
        assert "<track" in out
        assert 'kind="captions"' in out
        assert 'srclang="en"' in out

    def test_table_semantics_survive(self):
        out = sanitize_html(
            '<table><caption>C</caption><thead><tr><th scope="col">H</th></tr></thead>'
            '<tbody><tr><td>v</td></tr></tbody><tfoot><tr><td>t</td></tr></tfoot></table>')
        for fragment in ("<caption>", "<thead>", "<tbody>", "<tfoot>", 'scope="col"'):
            assert fragment in out

    def test_images_without_alt_get_an_empty_alt(self):
        assert 'alt=""' in sanitize_html('<img src="x.png">')

    def test_existing_alt_is_kept(self):
        assert 'alt="a cat"' in sanitize_html('<img src="x.png" alt="a cat">')

    def test_unclosed_tags_are_balanced(self):
        out = sanitize_html("<p>one<p>two")
        assert out.count("<p>") == out.count("</p>")


class TestDangerousUrls:
    """Obfuscated scheme payloads a naive prefix check would let through."""

    def test_plain_javascript_scheme_is_blocked(self):
        assert is_dangerous_url("javascript:alert(1)")

    def test_embedded_control_characters_are_blocked(self):
        # A browser strips the tab before resolving the scheme, so this runs.
        assert is_dangerous_url("java" + chr(9) + "script:alert(1)")
        assert is_dangerous_url("java" + chr(0) + "script:alert(1)")
        assert is_dangerous_url(chr(10) + "javascript:alert(1)")

    def test_html_entities_are_decoded_before_the_check(self):
        assert is_dangerous_url("java&#09;script:alert(1)")

    def test_case_and_leading_space_do_not_help(self):
        assert is_dangerous_url("  JaVaScript:alert(1)")

    def test_other_dangerous_schemes(self):
        assert is_dangerous_url("vbscript:msgbox(1)")
        assert is_dangerous_url("data:text/html,<script>")

    def test_ordinary_urls_are_allowed(self):
        for safe in ("https://example.org/x", "/relative", "mailto:a@b.c",
                     "data:image/png;base64,AAA", ""):
            assert not is_dangerous_url(safe), safe

    def test_dangerous_href_is_dropped_but_text_kept(self):
        out = sanitize_html('<a href="java&#09;script:alert(1)">label</a>')
        assert "javascript" not in out.lower().replace("&#9;", "")
        assert "label" in out


class TestHeadings:
    def test_empty_headings_are_dropped(self):
        assert drop_empty_headings("<h2></h2><p>x</p>") == "<p>x</p>"
        assert drop_empty_headings("<h3>   </h3>") == ""

    def test_headings_are_demoted_below_the_page_title(self):
        # A feed's own <h1> would otherwise collide with the page <h1>.
        assert "<h2>T</h2>" in demote_headings("<h1>T</h1>", min_level=2)

    def test_relative_nesting_is_preserved(self):
        out = demote_headings("<h1>A</h1><h2>B</h2>", min_level=2)
        assert "<h2>A</h2>" in out
        assert "<h3>B</h3>" in out

    def test_skipped_levels_are_closed_up(self):
        out = demote_headings("<h1>A</h1><h3>B</h3>", min_level=2)
        assert "<h2>A</h2>" in out
        assert "<h3>B</h3>" in out

    def test_no_headings_is_a_no_op(self):
        assert demote_headings("<p>x</p>") == "<p>x</p>"


class TestTextConversion:
    def test_headings_and_lists_convert(self):
        md = html_to_markdown("<h2>Title</h2><ul><li>one</li><li>two</li></ul>").markdown
        assert "## Title" in md
        assert "- one" in md

    def test_nested_lists_are_indented(self):
        md = html_to_markdown("<ul><li>a<ul><li>b</li></ul></li></ul>").markdown
        assert "- a" in md
        assert "  - b" in md

    def test_links_keep_their_target_visible_in_plain_text(self):
        assert "show notes (https://ex.test/a)" in html_to_text(
            '<a href="https://ex.test/a">show notes</a>')

    def test_images_are_described_in_plain_text(self):
        assert "[image: a cat" in markdown_to_text("![a cat](cat.png)")

    def test_malformed_markup_falls_back_instead_of_raising(self):
        assert html_to_markdown("<p>unclosed <b>bold").markdown

    def test_empty_input(self):
        assert html_to_markdown("").markdown == ""
        assert sanitize_html("") == ""
