"""Checking the favourites for new episodes -- only when asked.

The rules under test are the design rules: nothing polls or schedules, a
first look is reported as a first look rather than as "everything is new",
one broken feed cannot hide the others, and "could not check" never quietly
becomes "nothing new".
"""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

from podharvest import freshness
from podharvest.favorites import Favorite

UTC = dt.timezone.utc


class _AppSpace:
    def __init__(self, tmp_path):
        self.config_dir = tmp_path


def _favorite(url="https://a/feed"):
    return Favorite(title="A Show", feed_url=url)


def _feed_xml(*items):
    rows = "".join(
        f"<item><title>{title}</title><pubDate>{when}</pubDate>"
        f"<guid>g{i}</guid></item>"
        for i, (title, when) in enumerate(items))
    return ("<rss version=\"2.0\"><channel><title>A Show</title>"
            f"{rows}</channel></rss>")


class _Client:
    """A fake HttpClient serving one canned feed."""

    def __init__(self, xml, status=200):
        self._xml, self._status = xml, status

    def get(self, url, **kwargs):
        class _R:
            status = self._status
            url = "https://a/feed"
            content_type = "application/rss+xml"

            def text(_self):
                return self._xml
        return _R()


class TestCheckingOneShow:
    def test_a_first_look_is_not_reported_as_new(self, tmp_path):
        report = freshness.check_one(_favorite(), {}, client=_Client(
            _feed_xml(("Ep 2", "Tue, 02 Sep 2026 10:00:00 GMT"),
                      ("Ep 1", "Mon, 01 Sep 2026 10:00:00 GMT"))))
        assert report.is_first_look
        assert report.new_count == -1
        assert "first look" in report.describe()
        assert report.newest_title == "Ep 2"

    def test_episodes_after_the_baseline_count_as_new(self, tmp_path):
        records = {"https://a/feed": {
            "latest_published": "2026-09-01T10:00:00+00:00"}}
        report = freshness.check_one(_favorite(), records, client=_Client(
            _feed_xml(("Ep 3", "Thu, 03 Sep 2026 10:00:00 GMT"),
                      ("Ep 2", "Wed, 02 Sep 2026 10:00:00 GMT"),
                      ("Ep 1", "Mon, 01 Sep 2026 10:00:00 GMT"))))
        assert report.new_count == 2
        assert "2 new episodes" in report.describe()

    def test_nothing_new_says_so(self):
        records = {"https://a/feed": {
            "latest_published": "2026-09-03T10:00:00+00:00"}}
        report = freshness.check_one(_favorite(), records, client=_Client(
            _feed_xml(("Ep 3", "Thu, 03 Sep 2026 10:00:00 GMT"))))
        assert report.new_count == 0
        assert "nothing new" in report.describe()

    def test_a_naive_date_cannot_make_a_show_forever_new(self):
        """The same trade the library makes: naive dates read as UTC."""
        records = {"https://a/feed": {
            "latest_published": "2026-09-03T10:00:00"}}
        report = freshness.check_one(_favorite(), records, client=_Client(
            _feed_xml(("Ep 3", "Thu, 03 Sep 2026 10:00:00 GMT"))))
        assert report.new_count == 0

    def test_a_broken_feed_is_a_report_not_an_exception(self):
        report = freshness.check_one(_favorite(), {}, client=_Client(
            "this is not xml", status=500))
        assert report.error
        assert "could not check" in report.describe()

    def test_an_empty_feed_says_so(self):
        report = freshness.check_one(_favorite(), {}, client=_Client(
            _feed_xml()))
        assert "no episodes" in report.error


class TestTheBaseline:
    def test_mark_seen_round_trips(self, tmp_path):
        app = _AppSpace(tmp_path)
        report = freshness.ShowReport(
            favorite=_favorite(), newest_title="Ep 2",
            newest_published=dt.datetime(2026, 9, 2, 10, tzinfo=UTC),
            new_count=-1)
        assert freshness.mark_seen(app, [report]) == 1
        records = freshness.load_seen(app)
        assert records["https://a/feed"]["latest_published"].startswith("2026-09-02")

    def test_an_errored_show_keeps_its_old_baseline(self, tmp_path):
        """"Could not check" must not quietly become "nothing new"."""
        app = _AppSpace(tmp_path)
        good = freshness.ShowReport(favorite=_favorite(), newest_title="Ep")
        bad = freshness.ShowReport(
            favorite=_favorite("https://b/feed"), error="server on fire")
        assert freshness.mark_seen(app, [good, bad]) == 1
        assert "https://b/feed" not in freshness.load_seen(app)

    def test_a_corrupt_seen_file_degrades_to_first_looks(self, tmp_path):
        app = _AppSpace(tmp_path)
        freshness.seen_path(app).write_text("{broken", encoding="utf-8")
        assert freshness.load_seen(app) == {}

    def test_the_keys_match_how_favourites_tell_shows_apart(self, tmp_path):
        """A show marked seen under one spelling of its address must be
        found again under another."""
        app = _AppSpace(tmp_path)
        report = freshness.ShowReport(
            favorite=_favorite("https://A/Feed/"), newest_title="Ep")
        freshness.mark_seen(app, [report])
        assert "https://a/feed" in freshness.load_seen(app)


class TestItIsNotASubscription:
    def test_the_module_says_the_line_stays_drawn(self):
        assert "polls" in (freshness.__doc__ or "")

    def test_nothing_in_it_schedules_or_downloads(self):
        source = inspect.getsource(freshness)
        body = source.split('"""', 2)[-1]
        for forbidden in ("Timer", "schedule", "download", "run_harvest",
                          "threading"):
            assert forbidden not in body, f"freshness must not {forbidden}"


class TestTheWindow:
    def test_it_is_reachable_from_the_menu(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "Check favourites for" in source

    def test_checking_happens_off_the_ui_thread(self):
        pytest.importorskip("wx")
        from podharvest.discover import FreshnessDialog

        source = inspect.getsource(FreshnessDialog.on_check)
        assert "threading.Thread" in source

    def test_marking_seen_is_a_button_not_automatic(self):
        """"I saw the report" stays a decision the user makes."""
        pytest.importorskip("wx")
        from podharvest.discover import FreshnessDialog

        shown = inspect.getsource(FreshnessDialog._show_reports)
        assert "mark_seen" not in shown

    def test_the_window_says_what_it_is_for(self):
        from podharvest import help as help_mod

        purpose = help_mod.purpose_for_title("New episodes in your favourites")
        assert purpose != help_mod.GENERIC_PURPOSE
        assert "nothing polls" in purpose.lower()

    def test_the_module_ships(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.freshness" in spec
