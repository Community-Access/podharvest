"""The Help-menu update check: manual, anonymous, honest about failure.

The rules under test are the privacy rules: nothing checks automatically,
the one request is made because the user chose the menu item, and it goes
over HTTPS to a public API carrying nothing about the user or their library.
"""

from __future__ import annotations

import inspect

import pytest

from podharvest import updates


class TestComparingVersions:
    @pytest.mark.parametrize("current,latest,expected", [
        ("1.0.0", "1.1.0", "newer"),
        ("1.0.0", "2.0.0", "newer"),
        ("1.0.0", "1.0.1", "newer"),
        ("1.0.0", "1.0.0", "same"),
        ("1.1.0", "1.0.0", "older"),
        ("1.0", "1.0.0", "same"),
        ("1.0.0", "v1.0.0", "same"),
        ("1.9.0", "1.10.0", "newer"),
    ])
    def test_the_obvious_cases(self, current, latest, expected):
        assert updates.compare(current, latest) == expected

    def test_garbage_never_says_upgrade(self):
        """"You should upgrade" is not a claim to make on unparseable input."""
        assert updates.compare("1.0.0", "not-a-version") == "same"
        assert updates.compare("", "1.0.0") == "same"

    def test_a_suffix_is_ignored_not_guessed_about(self):
        assert updates.compare("1.0.0", "1.1.0-beta") == "newer"


class TestReadingTheApi:
    def test_a_real_looking_response(self):
        tag, url = updates.parse_release(
            b'{"tag_name": "v1.2.0", "html_url": "https://x/releases/v1.2.0"}')
        assert tag == "v1.2.0"
        assert url == "https://x/releases/v1.2.0"

    def test_no_tag_is_an_error_not_a_silent_success(self):
        with pytest.raises(updates.UpdateError, match="version tag"):
            updates.parse_release(b'{"html_url": "https://x"}')

    def test_not_json_says_so(self):
        with pytest.raises(updates.UpdateError, match="not JSON"):
            updates.parse_release(b"<html>rate limited</html>")

    def test_check_builds_a_report(self):
        class _Response:
            status = 200
            body = b'{"tag_name": "v9.9.9", "html_url": "https://x/r"}'

        class _Client:
            def get(self, url):
                assert url.startswith("https://"), "never plain http"
                return _Response()

        report = updates.check(_Client(), current="1.0.0")
        assert report.standing == "newer"
        assert "9.9.9" in report.describe()

    def test_a_bad_status_is_an_error(self):
        class _Client:
            def get(self, url):
                class _R:
                    status = 403
                    body = b"{}"
                return _R()

        with pytest.raises(updates.UpdateError, match="403"):
            updates.check(_Client())


class TestThePrivacyRules:
    def test_the_module_says_nothing_checks_automatically(self):
        assert "Nothing checks automatically" in (updates.__doc__ or "")

    def test_nothing_in_it_schedules_or_polls(self):
        source = inspect.getsource(updates)
        body = source.split('"""', 2)[-1]
        for forbidden in ("Timer", "schedule", "threading"):
            assert forbidden not in body

    def test_the_address_is_https(self):
        assert updates.LATEST_URL.startswith("https://")
        assert updates.RELEASES_PAGE.startswith("https://")

    def test_the_gui_calls_check_only_from_the_menu_handler(self):
        """The one call site is the handler the user invokes. A second call
        site is a place an automatic check could creep in."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui)
        assert source.count("updates_mod.check()") == 1
        handler = inspect.getsource(gui.MainFrame._on_check_updates)
        assert "updates_mod.check()" in handler

    def test_it_is_reachable_from_the_help_menu(self):
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._build_menubar)
        assert "Check for &updates" in source

    def test_the_open_page_question_defaults_to_no(self):
        """Enter pressed reflexively must not open a browser."""
        pytest.importorskip("wx")
        from podharvest import gui

        source = inspect.getsource(gui.MainFrame._show_update_result)
        assert "wx.NO_DEFAULT" in source

    def test_the_module_ships(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "podharvest.updates" in spec
