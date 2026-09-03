"""Shared test fixtures.

The important one is `wx_app`. A process gets exactly one `wx.App`, ever --
creating a second one after the first is destroyed leaves wx in a state where
every later window construction fails with "No wx.App created yet". Several
test modules need a wx window, so each used to make its own, and the suite
passed only because they happened to run in an order where that worked.

Under a shuffled test order it stopped happening reliably, and the symptom was
maddening: a failure reported against `test_util_config` or `test_net_download`
-- modules with no user interface at all -- because those were simply the next
tests to run after the App went away.

So: one App, made once, never destroyed.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def wx_app():
    """The one and only `wx.App` for the whole test session.

    Skips the test if wxPython is not installed, so the non-GUI half of the
    suite still runs on a machine without it.
    """
    wx = pytest.importorskip("wx")
    # `GetApp` rather than an unconditional constructor: if anything has
    # already made one, reuse it instead of making the second one that breaks
    # everything afterwards.
    application = wx.GetApp()
    if application is None:
        application = wx.App()
    yield application
    # Deliberately not destroyed. There is nothing after the session that
    # needs it gone, and destroying it is the thing that causes the damage.
