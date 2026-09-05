"""Importing a list of podcasts from an OPML file.

OPML is how podcast apps hand each other a list of shows, which makes it the
right way to bring one into podHarvest -- and podHarvest has a specific use
for a list: a set of shows to work through, and a way to fill the favourites
without typing forty addresses.

The rules come from QUILL Cast's importer, including the ones the format gets
subtly wrong, so both programs read the same files the same way.

Nothing here touches the network. The one test that would is marked and does
not run by default.
"""

from __future__ import annotations

import inspect

import pytest

from podharvest import opml


def _document(body: str) -> str:
    return f'<opml version="2.0"><head><title>A list</title></head><body>{body}</body></opml>'


class TestReadingAList:
    def test_a_flat_list_of_shows(self):
        shows = opml.parse(_document(
            '<outline type="rss" text="One" xmlUrl="https://a/f"/>'
            '<outline type="rss" text="Two" xmlUrl="https://b/f"/>'))
        assert [s.title for s in shows] == ["One", "Two"]
        assert shows[0].feed_url == "https://a/f"

    def test_title_wins_over_text_and_the_address_is_the_last_resort(self):
        shows = opml.parse(_document(
            '<outline title="Titled" text="Texted" xmlUrl="https://a/f"/>'
            '<outline xmlUrl="https://b/f"/>'))
        assert shows[0].title == "Titled"
        assert shows[1].title == "https://b/f", "never a blank row"

    def test_folders_are_remembered_not_flattened_away(self):
        shows = opml.parse(_document(
            '<outline text="News">'
            '  <outline text="Local"><outline text="A" xmlUrl="https://a/f"/></outline>'
            '</outline>'))
        assert shows[0].folder_path == ["News", "Local"]
        assert shows[0].folder == "News / Local"

    def test_an_entry_with_no_feed_is_a_folder_not_a_show(self):
        shows = opml.parse(_document('<outline text="Empty"/>'))
        assert shows == []

    def test_a_commented_out_entry_is_skipped(self):
        """OPML says isComment means the author parked it. Importing one turns
        somebody's disabled feed back on behind their back."""
        shows = opml.parse(_document(
            '<outline text="Parked" xmlUrl="https://a/f" isComment="true"/>'
            '<outline text="Live" xmlUrl="https://b/f"/>'))
        assert [s.title for s in shows] == ["Live"]

    def test_only_the_literal_true_counts_as_commented_out(self):
        """The attribute is a string, and an absent one means false."""
        shows = opml.parse(_document(
            '<outline text="A" xmlUrl="https://a/f" isComment="false"/>'
            '<outline text="B" xmlUrl="https://b/f" isComment="maybe"/>'))
        assert len(shows) == 2

    def test_a_commented_folder_takes_its_children_with_it(self):
        shows = opml.parse(_document(
            '<outline text="Parked" isComment="true">'
            '  <outline text="Inside" xmlUrl="https://a/f"/>'
            '</outline>'))
        assert shows == []

    def test_the_optional_attributes_are_kept(self):
        shows = opml.parse(_document(
            '<outline text="A" xmlUrl="https://a/f" htmlUrl="https://a" '
            'description="About it." language="en-GB" category="/Arts/Books"/>'))
        show = shows[0]
        assert show.homepage == "https://a"
        assert show.description == "About it."
        assert show.language == "en-GB"
        assert show.category == "/Arts/Books", "kept verbatim, not split"

    def test_summary_is_used_when_description_is_missing(self):
        """OPML spells it description; some exporters write RSS's summary."""
        shows = opml.parse(_document(
            '<outline text="A" xmlUrl="https://a/f" summary="From summary."/>'))
        assert shows[0].description == "From summary."

    def test_a_document_with_no_body_is_empty_not_an_error(self):
        assert opml.parse('<opml version="2.0"><head/></opml>') == []

    def test_a_huge_list_is_capped(self, monkeypatch):
        monkeypatch.setattr(opml, "MAX_SHOWS", 3)
        body = "".join(f'<outline text="S{n}" xmlUrl="https://x/{n}"/>'
                       for n in range(50))
        assert len(opml.parse(_document(body))) == 3


class TestRefusingBadInput:
    def test_a_doctype_is_refused(self):
        """It is the doorway to entity expansion and external entity reads,
        and no genuine podcast list has one."""
        with pytest.raises(opml.OpmlError, match="DOCTYPE"):
            opml.parse('<!DOCTYPE opml [<!ENTITY x "y">]><opml/>')

    def test_a_lowercase_doctype_is_refused_too(self):
        with pytest.raises(opml.OpmlError):
            opml.parse('<!doctype opml><opml/>')

    def test_something_that_is_not_xml_says_so(self):
        with pytest.raises(opml.OpmlError, match="could not be read"):
            opml.parse("this is not xml at all")

    def test_a_plain_http_address_is_refused(self):
        """A list of feeds that can be rewritten in transit is one that can
        point podHarvest somewhere else."""
        with pytest.raises(opml.OpmlError, match="https"):
            opml.fetch("http://example.com/list.opml")

    def test_a_missing_file_says_so(self, tmp_path):
        with pytest.raises(opml.OpmlError, match="Could not open"):
            opml.read_file(tmp_path / "nothing.opml")

    def test_an_absurdly_large_file_is_refused_before_parsing(self, tmp_path):
        path = tmp_path / "huge.opml"
        path.write_bytes(b"<opml/>" + b"\0" * (opml.MAX_BYTES + 1))
        with pytest.raises(opml.OpmlError, match="larger than"):
            opml.read_file(path)


class TestEncodings:
    def test_utf8_with_a_byte_order_mark(self):
        """The mark is consumed rather than left at the front, where it would
        make the document unparseable as XML."""
        raw = b"\xef\xbb\xbf" + _document(
            '<outline text="Café" xmlUrl="https://a/f"/>').encode("utf-8")
        text = opml.decode(raw)
        assert not text.startswith("﻿")
        assert opml.parse(text)[0].title == "Café"

    def test_a_stray_byte_does_not_fail_the_whole_import(self):
        """Worst case is one mangled character in one title."""
        assert opml.decode(b"<opml>\xff</opml>")


class TestDuplicates:
    def _shows(self, *urls):
        return [opml.ImportedShow(title=f"S{n}", feed_url=u)
                for n, u in enumerate(urls)]

    def test_the_same_feed_twice_is_one_show(self):
        """A network list can put one show under two folders."""
        kept = opml.without_duplicates(self._shows("https://a/f", "https://a/f"))
        assert len(kept) == 1

    def test_a_trailing_slash_is_the_same_show(self):
        kept = opml.without_duplicates(self._shows("https://a/f", "https://a/f/"))
        assert len(kept) == 1

    def test_case_does_not_make_it_a_different_show(self):
        kept = opml.without_duplicates(self._shows("https://A/F", "https://a/f"))
        assert len(kept) == 1

    def test_the_first_of_each_is_the_one_kept(self):
        shows = [opml.ImportedShow(title="First", feed_url="https://a/f"),
                 opml.ImportedShow(title="Second", feed_url="https://a/f")]
        assert opml.without_duplicates(shows)[0].title == "First"

    def test_it_matches_how_favourites_tell_shows_apart(self):
        """A show imported here and one added there must be recognised as one."""
        from podharvest import favorites

        assert favorites._key("https://A/F/") == "https://a/f"
        kept = opml.without_duplicates(self._shows("https://A/F/", "https://a/f"))
        assert len(kept) == 1


class TestHowItReadsAloud:
    def test_a_show_summary_leads_with_where_it_came_from(self):
        show = opml.ImportedShow(
            title="A", feed_url="https://a/f", folder_path=["News"],
            category="/Arts", language="en", description="About it. More text.")
        summary = show.summary()
        assert summary.startswith("News")
        assert "About it" in summary

    def test_a_long_description_is_cut_at_the_first_sentence(self):
        show = opml.ImportedShow(
            title="A", feed_url="https://a/f",
            description="First sentence. " + "x" * 500)
        assert len(show.summary()) < 120

    def test_a_show_with_nothing_known_still_says_something(self):
        show = opml.ImportedShow(title="A", feed_url="https://a/f")
        assert show.summary() == "no details"


class TestItIsNotASubscription:
    def test_the_module_says_what_it_is_not(self):
        assert "not subscribing" in (opml.__doc__ or "").lower()

    def test_nothing_in_it_schedules_or_downloads(self):
        source = inspect.getsource(opml)
        body = source.split('"""', 2)[-1]
        for forbidden in ("Timer", "schedule", "download_all", "run_harvest"):
            assert forbidden not in body, f"importing must not {forbidden}"


class TestTheWindow:
    def test_it_is_reachable_from_the_menu(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "Import a list of podcasts" in source

    def test_it_offers_an_example_worth_trying(self):
        """"Find an OPML file" is not a useful instruction to a first-timer."""
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog)
        assert "EXAMPLE_NAME" in source
        assert opml.EXAMPLE_URL.startswith("https://")

    def test_checking_the_new_ones_skips_what_is_already_kept(self):
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog.on_check_new)
        assert "favorites_mod.contains" in source

    def test_adding_saves_bookmarks_rather_than_subscribing(self):
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog.on_add)
        assert "favorites_mod.Favorite" in source
        for forbidden in ("run_harvest", "download", "Timer"):
            assert forbidden not in source

    def test_reading_happens_off_the_ui_thread(self):
        """Forty feeds over a slow link must not freeze the window."""
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog.on_read)
        assert "threading.Thread" in source

    def test_the_window_says_what_it_is_for(self):
        from podharvest import help as help_mod

        purpose = help_mod.purpose_for_title("Import a list of podcasts")
        assert purpose != help_mod.GENERIC_PURPOSE
        assert "OPML" in purpose

    def test_the_module_ships(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.opml" in spec


class TestCheckingStaysInTheWindow:
    """Space checks a box. It must never also leave the window.

    On Windows a checkable `wx.ListCtrl` reports Space as an item
    *activation* as well as a check -- verified against wx 4.3.1, where one
    Space produced ACTIVATED and CHECKED in that order. Binding activation
    straight to "use this show and close" therefore threw you out of the
    window on the very keystroke the window exists for.
    """

    def test_activation_ignores_the_space_key(self):
        pytest.importorskip("wx")
        import wx

        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog._on_activated)
        assert "WXK_SPACE" in source
        assert wx.WXK_SPACE == 32

    def test_enter_adds_rather_than_leaving(self):
        """The primary action of a checklist is adding what you checked."""
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog._on_list_key)
        assert "WXK_RETURN" in source
        assert "self.on_add()" in source

    def test_use_this_one_is_not_the_dialog_affirmative(self):
        """wx.ID_OK there would make Enter close the window from anywhere."""
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog.__init__)
        use_line = next(line for line in source.splitlines()
                        if "self.use_btn = wx.Button" in line)
        assert "wx.ID_OK" not in use_line

    def test_the_add_button_carries_the_count(self):
        """A status line is silent; a button's own label is not."""
        pytest.importorskip("wx")
        from podharvest.discover import OpmlImportDialog

        source = inspect.getsource(OpmlImportDialog._sync_add_button)
        assert "checked to &favourites" in source
        assert "Enable(count > 0)" in source


@pytest.mark.skip(reason="talks to the network; run by hand when changing the parser")
def test_the_real_example_list_still_parses():
    """The ACB Media network list, which is what the example button loads.

    Skipped by default: somebody else's server having a bad afternoon should
    not fail this suite. Verified by hand on 2026-09-04, 41 shows.
    """
    shows = opml.without_duplicates(opml.load(opml.EXAMPLE_URL))
    assert len(shows) > 20
    assert all(s.feed_url.startswith("https://") for s in shows)


class TestExport:
    def _favorites(self):
        from podharvest.favorites import Favorite

        return [
            Favorite(title="Q&A Show", feed_url="https://a/f",
                     homepage="https://a"),
            Favorite(title="Plain", feed_url="https://b/f"),
        ]

    def test_a_round_trip_survives(self):
        """What export writes, import reads back unchanged."""
        text = opml.to_opml(self._favorites())
        shows = opml.parse(text)
        assert [s.title for s in shows] == ["Q&A Show", "Plain"]
        assert shows[0].feed_url == "https://a/f"
        assert shows[0].homepage == "https://a"

    def test_special_characters_are_escaped_not_mangled(self):
        text = opml.to_opml(self._favorites())
        assert "Q&amp;A" in text
        assert opml.parse(text)[0].title == "Q&A Show"

    def test_a_favourite_with_no_address_is_left_out(self):
        from podharvest.favorites import Favorite

        favorites = self._favorites() + [Favorite(title="Broken", feed_url="")]
        assert len(opml.parse(opml.to_opml(favorites))) == 2

    def test_a_titleless_favourite_still_gets_a_text_attribute(self):
        """OPML readers show text; a blank one is an invisible row."""
        from podharvest.favorites import Favorite

        text = opml.to_opml([Favorite(title="", feed_url="https://a/f")])
        assert opml.parse(text)[0].title == "https://a/f"

    def test_export_file_writes_and_counts(self, tmp_path):
        path = tmp_path / "list.opml"
        written = opml.export_file(path, self._favorites())
        assert written == 2
        assert path.exists()
        assert not path.with_suffix(".opml.tmp").exists(), "moved, not left"
        assert len(opml.parse(path.read_text(encoding="utf-8"))) == 2

    def test_the_document_declares_utf8(self):
        assert opml.to_opml([]).startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_it_is_reachable_from_the_menu(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "xport favourites to OPML" in source
