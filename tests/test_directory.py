"""Finding a podcast by name, and keeping the ones worth keeping.

Two things podHarvest could not do: find a show without you already having its
feed address, and remember one you found. Both are covered here, along with
the third that makes them useful -- looking inside a feed before deciding to
harvest it.

No test here touches the network. Apple's directory is somebody else's
service; a suite that depends on it fails when they have a bad afternoon, and
that failure teaches nothing. The parsing, the query building, the storefront
handling and the favourites file are all exercised against fixed data.
"""

from __future__ import annotations

import inspect
import json

import pytest

from podharvest import directory as directory_mod
from podharvest import favorites as favorites_mod


def _entry(**overrides) -> dict:
    entry = {
        "collectionName": "99% Invisible",
        "feedUrl": "https://feeds.example.com/99pi",
        "artistName": "Roman Mars",
        "artworkUrl600": "https://img.example.com/600.jpg",
        "collectionViewUrl": "https://podcasts.apple.com/us/podcast/id1",
        "collectionId": 1,
        "primaryGenreName": "Design",
        "trackCount": 829,
        "country": "USA",
        "collectionExplicitness": "cleaned",
        "releaseDate": "2026-08-30T07:00:00Z",
    }
    entry.update(overrides)
    return entry


class _FakeResponse:
    def __init__(self, payload) -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers = {"content-type": "application/json"}

    def text(self) -> str:
        return self.body.decode("utf-8")


class _FakeClient:
    """Stands in for the HTTP client, and records what was asked for."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get(self, url: str):
        self.urls.append(url)
        return _FakeResponse(self.payload)


class TestReadingWhatCameBack:
    def test_a_full_entry_becomes_a_result(self):
        result = directory_mod.result_from_entry(_entry())
        assert result is not None
        assert result.title == "99% Invisible"
        assert result.artist == "Roman Mars"
        assert result.feed_url == "https://feeds.example.com/99pi"
        assert result.episode_count == 829
        assert result.genre == "Design"
        assert result.released == "2026-08-30", "the date, not the timestamp"

    def test_an_entry_with_no_feed_is_dropped(self):
        """Showing it and then refusing it is worse than not showing it."""
        assert directory_mod.result_from_entry(_entry(feedUrl="")) is None

    def test_an_entry_with_no_name_is_dropped(self):
        assert directory_mod.result_from_entry(_entry(collectionName="")) is None

    def test_junk_is_dropped_rather_than_raised(self):
        assert directory_mod.result_from_entry("not a dict") is None
        assert directory_mod.result_from_entry({}) is None

    def test_a_nonsense_episode_count_is_zero(self):
        assert directory_mod.result_from_entry(
            _entry(trackCount="lots")).episode_count == 0

    def test_explicit_is_recognised(self):
        assert directory_mod.result_from_entry(
            _entry(collectionExplicitness="explicit")).explicit is True
        assert directory_mod.result_from_entry(_entry()).explicit is False

    def test_a_reply_with_no_results_is_an_empty_list(self):
        assert directory_mod.results_from_json({"results": []}) == []
        assert directory_mod.results_from_json({}) == []
        assert directory_mod.results_from_json("nonsense") == []

    def test_usable_entries_survive_unusable_neighbours(self):
        data = {"results": [_entry(), "junk", {}, _entry(collectionName="Two")]}
        assert [r.title for r in directory_mod.results_from_json(data)] == [
            "99% Invisible", "Two"]


class TestHowItReadsAloud:
    def test_a_show_is_named_with_its_author(self):
        result = directory_mod.result_from_entry(_entry())
        assert result.display_name == "99% Invisible - Roman Mars"

    def test_a_show_with_no_author_is_just_its_name(self):
        result = directory_mod.result_from_entry(_entry(artistName=""))
        assert result.display_name == "99% Invisible"

    def test_the_summary_is_a_sentence_not_a_row_of_codes(self):
        result = directory_mod.result_from_entry(_entry())
        assert result.summary() == "829 episodes, Design"

    def test_one_episode_is_singular(self):
        assert "1 episode," in directory_mod.result_from_entry(
            _entry(trackCount=1)).summary()

    def test_a_show_with_nothing_known_still_says_something(self):
        result = directory_mod.result_from_entry(
            _entry(trackCount=0, primaryGenreName=""))
        assert result.summary() == "no details"


class TestStorefronts:
    def test_the_default_is_the_united_states(self):
        assert directory_mod.DEFAULT_STOREFRONT == "us"
        assert directory_mod.STOREFRONTS[0][0] == "us"

    def test_a_code_is_named(self):
        assert directory_mod.storefront_name("gb") == "United Kingdom"
        assert directory_mod.storefront_name("US") == "United States"

    def test_an_unlisted_code_is_shown_as_itself(self):
        """Apple has far more storefronts than are worth listing."""
        assert directory_mod.storefront_name("pt") == "PT"

    def test_an_unlisted_code_is_still_usable(self):
        assert directory_mod.clean_storefront("pt") == "pt"

    def test_nonsense_falls_back_to_the_default(self):
        for junk in ("", "   ", "nonsense", "u", "1234", None):
            assert directory_mod.clean_storefront(junk) == "us"

    def test_codes_are_unique_and_two_letters(self):
        codes = [code for code, _name in directory_mod.STOREFRONTS]
        assert len(codes) == len(set(codes))
        assert all(len(code) == 2 and code.islower() for code in codes)


class TestBuildingTheQuery:
    def test_an_empty_term_asks_nothing(self):
        """A search with no term is not a question."""
        client = _FakeClient({"results": [_entry()]})
        assert directory_mod.search("", client=client) == []
        assert client.urls == [], "it must not have asked"

    def test_the_country_reaches_the_request(self):
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", country="gb", client=client)
        assert "country=gb" in client.urls[0]

    def test_a_nonsense_country_becomes_the_default(self):
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", country="nonsense", client=client)
        assert "country=us" in client.urls[0]

    def test_the_field_narrows_the_match(self):
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", field_name="titleTerm", client=client)
        assert "attribute=titleTerm" in client.urls[0]

    def test_everything_sends_no_attribute_at_all(self):
        """Apple's own default searches everything; do not second-guess it."""
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", field_name="", client=client)
        assert "attribute" not in client.urls[0]

    def test_the_limit_is_held_inside_what_apple_accepts(self):
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", limit=99999, client=client)
        assert f"limit={directory_mod.MAX_LIMIT}" in client.urls[0]

    def test_no_limit_means_the_default_rather_than_none(self):
        """A spin control at zero is "I did not choose", not "fetch nothing"."""
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", limit=0, client=client)
        assert f"limit={directory_mod.DEFAULT_LIMIT}" in client.urls[0]

    def test_explicit_is_only_mentioned_when_it_is_being_excluded(self):
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", explicit=None, client=client)
        assert "explicit" not in client.urls[0], "do not filter unasked"
        directory_mod.search("badgers", explicit=False, client=client)
        assert "explicit=No" in client.urls[1]

    def test_it_only_asks_for_podcasts(self):
        client = _FakeClient({"results": []})
        directory_mod.search("badgers", client=client)
        assert "media=podcast" in client.urls[0]

    def test_the_search_runs_over_https(self):
        assert directory_mod.SEARCH_URL.startswith("https://")
        assert directory_mod.LOOKUP_URL.startswith("https://")

    def test_a_plain_http_request_is_refused(self):
        with pytest.raises(directory_mod.DirectoryError):
            directory_mod._fetch_json("http://itunes.apple.com/search")


class TestWhenTheDirectoryMisbehaves:
    def test_an_unreachable_directory_says_so(self):
        class Broken:
            def get(self, _url):
                raise OSError("the network is down")

        with pytest.raises(directory_mod.DirectoryError, match="Could not reach"):
            directory_mod.search("badgers", client=Broken())

    def test_an_unreadable_reply_says_so(self):
        class Garbled:
            def get(self, _url):
                class R:
                    body = b"<html>not json</html>"

                    def text(self):
                        return "<html>not json</html>"

                return R()

        with pytest.raises(directory_mod.DirectoryError, match="unreadable"):
            directory_mod.search("badgers", client=Garbled())


class TestApplePageLinks:
    def test_an_apple_show_link_yields_its_id(self):
        """People share the web link, not the feed address."""
        assert directory_mod.collection_id_from_url(
            "https://podcasts.apple.com/us/podcast/99-invisible/id394775318"
        ) == "394775318"

    def test_a_query_string_after_the_id_is_ignored(self):
        assert directory_mod.collection_id_from_url(
            "https://podcasts.apple.com/gb/podcast/x/id123?i=1000"
        ) == "123"

    def test_an_ordinary_feed_address_is_not_one(self):
        assert directory_mod.collection_id_from_url(
            "https://feeds.example.com/99pi") == ""

    def test_nothing_at_all_is_not_one(self):
        assert directory_mod.collection_id_from_url("") == ""

    def test_a_lookup_needs_a_number(self):
        client = _FakeClient({"results": [_entry()]})
        assert directory_mod.lookup("not-a-number", client=client) is None
        assert client.urls == []

    def test_a_lookup_returns_the_show(self):
        client = _FakeClient({"results": [_entry()]})
        found = directory_mod.lookup("394775318", client=client)
        assert found is not None and found.title == "99% Invisible"
        assert "id=394775318" in client.urls[0]

    def test_an_apple_link_resolves_to_a_feed(self):
        client = _FakeClient({"results": [_entry()]})
        assert directory_mod.feed_url_for(
            "https://podcasts.apple.com/us/podcast/x/id394775318",
            client=client) == "https://feeds.example.com/99pi"

    def test_something_that_is_not_an_apple_link_resolves_to_nothing(self):
        client = _FakeClient({"results": [_entry()]})
        assert directory_mod.feed_url_for(
            "https://feeds.example.com/99pi", client=client) == ""
        assert client.urls == [], "no point asking Apple about a feed address"


class TestFavourites:
    @pytest.fixture
    def app(self, tmp_path):
        from podharvest.appspace import AppSpace

        return AppSpace(tmp_path).ensure()

    def _fav(self, **overrides):
        data = {"title": "A Show", "feed_url": "https://x.example/feed",
                "artist": "Someone"}
        data.update(overrides)
        return favorites_mod.Favorite(**data)

    def test_a_new_list_is_empty_not_an_error(self, app):
        assert favorites_mod.load(app) == []

    def test_one_can_be_added_and_read_back(self, app):
        changed, message = favorites_mod.add(app, self._fav())
        assert changed is True
        assert "added" in message
        assert [f.title for f in favorites_mod.load(app)] == ["A Show"]

    def test_adding_the_same_show_twice_is_a_no_op_that_says_so(self, app):
        favorites_mod.add(app, self._fav())
        changed, message = favorites_mod.add(app, self._fav())
        assert changed is False
        assert "already" in message
        assert len(favorites_mod.load(app)) == 1

    def test_the_feed_address_is_the_identity_not_the_title(self, app):
        """The same show under two names is one favourite."""
        favorites_mod.add(app, self._fav(title="A Show"))
        changed, _ = favorites_mod.add(app, self._fav(title="Renamed"))
        assert changed is False

    def test_a_trailing_slash_is_the_same_show(self, app):
        favorites_mod.add(app, self._fav(feed_url="https://x.example/feed"))
        changed, _ = favorites_mod.add(app, self._fav(feed_url="https://x.example/feed/"))
        assert changed is False

    def test_one_can_be_removed(self, app):
        favorites_mod.add(app, self._fav())
        changed, message = favorites_mod.remove(app, "https://x.example/feed")
        assert changed is True
        assert favorites_mod.load(app) == []
        assert "untouched" in message, "say the files are safe"

    def test_removing_something_absent_says_so(self, app):
        changed, message = favorites_mod.remove(app, "https://nope.example/f")
        assert changed is False
        assert "not in your favourites" in message

    def test_a_show_with_no_feed_cannot_be_saved(self, app):
        changed, message = favorites_mod.add(app, self._fav(feed_url=""))
        assert changed is False
        assert "no feed address" in message

    def test_a_corrupt_file_is_an_empty_list_not_a_crash(self, app):
        favorites_mod.path_for(app).write_text("{not json", encoding="utf-8")
        assert favorites_mod.load(app) == []

    def test_a_row_with_no_feed_is_skipped_on_load(self, app):
        favorites_mod.path_for(app).write_text(
            json.dumps({"favorites": [{"title": "Broken"},
                                      {"title": "Fine", "feed_url": "https://a/b"}]}),
            encoding="utf-8")
        assert [f.title for f in favorites_mod.load(app)] == ["Fine"]

    def test_duplicates_in_the_file_collapse_on_load(self, app):
        row = {"title": "A", "feed_url": "https://a/b"}
        favorites_mod.path_for(app).write_text(
            json.dumps({"favorites": [row, dict(row)]}), encoding="utf-8")
        assert len(favorites_mod.load(app)) == 1

    def test_the_list_cannot_grow_without_limit(self, app, monkeypatch):
        monkeypatch.setattr(favorites_mod, "MAX_FAVORITES", 2)
        for n in range(2):
            favorites_mod.add(app, self._fav(feed_url=f"https://x/{n}"))
        changed, message = favorites_mod.add(app, self._fav(feed_url="https://x/3"))
        assert changed is False
        assert "full" in message

    def test_it_is_built_from_a_search_result(self):
        result = directory_mod.result_from_entry(_entry())
        favorite = favorites_mod.Favorite.from_result(result)
        assert favorite.title == "99% Invisible"
        assert favorite.feed_url == result.feed_url
        assert favorite.added_at, "when it was added is worth keeping"

    def test_the_library_writes_through_rather_than_batching(self, app):
        """A window that saved on close would lose them when something else
        closed it."""
        library = favorites_mod.Library(app=app)
        library.add(self._fav())
        assert len(favorites_mod.load(app)) == 1, "already on disk"
        assert library.contains("https://x.example/feed")


class TestItIsNotASubscription:
    """The distinction is the design, so it is worth a test that says so."""

    def test_nothing_in_favourites_polls_or_downloads(self):
        """The code, not the prose. The docstring says these words on purpose,
        so searching the whole file would match its own explanation."""
        source = inspect.getsource(favorites_mod)
        body = source.split('"""', 2)[-1]
        for forbidden in ("HttpClient", "urllib", "requests", "schedule",
                          "Timer", "download"):
            assert forbidden not in body, f"favourites must not {forbidden}"

    def test_the_module_says_what_it_is_not(self):
        assert "not a subscription" in (favorites_mod.__doc__ or "").lower()

    def test_the_directory_says_the_same(self):
        assert "not subscribing" in (directory_mod.__doc__ or "").lower()


class TestTheWindow:
    def test_the_search_window_exists_and_is_reachable(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame)
        assert "SearchDialog" in source
        assert "&Find a podcast..." in source

    def test_favourites_are_reachable(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame)
        assert "FavoritesDialog" in source
        assert "Fa&vourite podcasts..." in source

    def test_a_feed_can_be_browsed_without_downloading(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._run_browse_worker)
        assert "fetch_and_parse" in source
        for forbidden in ("download_all", "run_harvest", "transcribe"):
            assert forbidden not in source, f"browsing must not {forbidden}"

    def test_browsing_uses_its_own_column_headings(self):
        """These episodes are not on disk; "What you have" would be a lie."""
        pytest.importorskip("wx")
        from podharvest.gui import _BROWSE_COLUMNS, _LIBRARY_COLUMNS

        assert len(_BROWSE_COLUMNS) == len(_LIBRARY_COLUMNS)
        headings = [h for h, _w in _BROWSE_COLUMNS]
        assert headings != [h for h, _w in _LIBRARY_COLUMNS]

    def test_browsing_shows_what_a_run_would_actually_take(self):
        """It applies the same episode filter, or the list would mislead."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._show_browsed)
        assert "match_episodes" in source

    def test_a_pasted_apple_link_is_resolved_rather_than_parsed(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._run_browse_worker)
        assert "feed_url_for" in source

    def test_the_transport_is_switched_off_for_a_browsed_feed(self):
        """Nothing in the list is on disk, so there is nothing to play."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._show_browsed)
        assert "self.player.Enable(False)" in source


class TestSettings:
    def test_the_default_store_is_the_us(self):
        from podharvest.config import Settings

        assert Settings().itunes_country == "us"

    def test_a_nonsense_store_falls_back(self):
        from podharvest.config import Settings

        assert Settings.from_dict({"itunes_country": "nonsense"}).itunes_country == "us"

    def test_an_unlisted_but_valid_store_is_kept(self):
        from podharvest.config import Settings

        assert Settings.from_dict({"itunes_country": "PT"}).itunes_country == "pt"

    def test_the_result_count_is_clamped(self):
        from podharvest.config import Settings

        assert Settings.from_dict({"search_limit": 99999}).search_limit == 200
        assert Settings.from_dict({"search_limit": 0}).search_limit == 1
        assert Settings.from_dict({"search_limit": "lots"}).search_limit == 25

    def test_both_survive_a_round_trip(self):
        from podharvest.config import Settings

        settings = Settings()
        settings.itunes_country = "gb"
        settings.search_limit = 50
        restored = Settings.from_dict(settings.to_dict())
        assert restored.itunes_country == "gb"
        assert restored.search_limit == 50


class TestPackaging:
    def test_the_new_modules_ship(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        for module in ("directory", "discover", "favorites"):
            assert f"podharvest.{module}" in spec


class TestTheMenuBar:
    """A menu bar is how an unfamiliar program is explored with a screen
    reader, so it has to be navigable by ear: grouped by what each entry acts
    on, and with every entry actually wired to something."""

    @pytest.fixture
    def frame(self, wx_app):
        from podharvest import gui

        window = gui.MainFrame()
        yield window
        window._alive = False
        if getattr(window, "_tray", None) is not None:
            try:
                window._tray.Destroy()
            except Exception:
                pass
        window.Destroy()

    def test_it_is_grouped_rather_than_one_long_list(self, frame):
        bar = frame.GetMenuBar()
        names = [bar.GetMenuLabelText(i) for i in range(bar.GetMenuCount())]
        assert names == ["File", "Episode", "View", "Tools", "Help"]

    def test_no_menu_has_grown_into_a_list_of_everything(self, frame):
        """Past about a dozen, a menu stops being searchable by ear."""
        bar = frame.GetMenuBar()
        for index in range(bar.GetMenuCount()):
            menu = bar.GetMenu(index)
            items = [i for i in menu.GetMenuItems() if not i.IsSeparator()]
            assert len(items) <= 13, bar.GetMenuLabelText(index)

    def test_every_entry_says_what_it_does(self, frame):
        """The status-bar help is read aloud as you arrow through a menu."""
        bar = frame.GetMenuBar()
        for index in range(bar.GetMenuCount()):
            for item in bar.GetMenu(index).GetMenuItems():
                if item.IsSeparator():
                    continue
                assert item.GetHelp().strip(), item.GetItemLabelText()

    def test_every_entry_has_a_mnemonic(self, frame):
        """Alt-letter navigation is the point of a menu bar."""
        bar = frame.GetMenuBar()
        for index in range(bar.GetMenuCount()):
            for item in bar.GetMenu(index).GetMenuItems():
                if item.IsSeparator():
                    continue
                assert "&" in item.GetItemLabel(), item.GetItemLabelText()

    def test_mnemonics_do_not_collide_within_a_menu(self, frame):
        """Two entries on the same letter make Alt-letter ambiguous."""
        bar = frame.GetMenuBar()
        for index in range(bar.GetMenuCount()):
            letters = []
            for item in bar.GetMenu(index).GetMenuItems():
                if item.IsSeparator():
                    continue
                label = item.GetItemLabel()
                position = label.find("&")
                if 0 <= position < len(label) - 1:
                    letters.append(label[position + 1].lower())
            assert len(letters) == len(set(letters)), (
                f"{bar.GetMenuLabelText(index)}: {sorted(letters)}")

    def test_the_new_entries_are_wired_to_real_handlers(self, frame):
        for name in ("_on_reveal_episode", "_on_check_install",
                     "_on_help_here", "_on_open_docs", "_on_add_favorite"):
            assert callable(getattr(frame, name, None)), name

    def test_finding_and_favourites_are_in_the_menu_too(self, frame):
        """Not everyone finds a button; the menu is the discoverable path."""
        bar = frame.GetMenuBar()
        labels = [item.GetItemLabelText()
                  for index in range(bar.GetMenuCount())
                  for item in bar.GetMenu(index).GetMenuItems()
                  if not item.IsSeparator()]
        joined = " | ".join(labels)
        for wanted in ("Find a podcast", "Favourite podcasts",
                       "Show episodes in this feed", "Download the selected",
                       "Check what is installed"):
            assert wanted in joined, wanted

    def test_asking_for_help_from_the_menu_reaches_the_help(self, frame):
        """Checked without calling it: `show_help` ends in a modal message
        box, and a test that opens one waits for a person who is not there --
        which on CI is a hang rather than a failure."""
        import inspect

        source = inspect.getsource(frame._on_help_here.__func__)
        assert "help_mod.show_help" in source
        assert "FindFocus()" in source, "help must be about the focused control"
