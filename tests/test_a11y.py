"""Naming a control must not cost it its native accessibility.

`set_accessible_name` attaches a `wx.Accessible` to a control. On Windows that
object also answers for the control's *children*, which is fine for an edit
field with none and actively harmful for anything composite: list rows read as
bare index numbers, every notebook tab takes the notebook's own name, and a
checkbox stops announcing its state.

That is not hypothetical -- all three shipped. These tests hold the line,
because the helper reads like something you would want to apply to everything.
"""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")

from podharvest.a11y import _COMPOSITE, set_accessible_name  # noqa: E402


@pytest.fixture
def frame(wx_app):
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()


class TestNativeAccessibilityIsKept:
    """Composite controls keep the accessible object the platform gave them."""

    def test_a_list_keeps_its_own_accessibility(self, frame):
        ctrl = wx.ListCtrl(frame, style=wx.LC_REPORT)
        set_accessible_name(ctrl, "Episodes")
        assert getattr(ctrl, "_a11y_helper", None) is None
        assert ctrl.GetName() == "Episodes"

    def test_a_notebook_keeps_its_own_accessibility(self, frame):
        """Otherwise every tab announces as the notebook's name."""
        ctrl = wx.Notebook(frame)
        set_accessible_name(ctrl, "Tag and chapter pages")
        assert getattr(ctrl, "_a11y_helper", None) is None

    def test_a_checkbox_keeps_its_own_accessibility(self, frame):
        """The native object is what announces checked and not checked."""
        ctrl = wx.CheckBox(frame, label="Save a log file")
        set_accessible_name(ctrl, "Save a log file")
        assert getattr(ctrl, "_a11y_helper", None) is None

    def test_a_radio_box_keeps_its_own_accessibility(self, frame):
        ctrl = wx.RadioBox(frame, label="Source", choices=["One", "Two"])
        set_accessible_name(ctrl, "Source")
        assert getattr(ctrl, "_a11y_helper", None) is None

    def test_the_composite_list_covers_what_it_should(self):
        for cls in (wx.ListCtrl, wx.ListBox, wx.Notebook, wx.RadioBox, wx.CheckBox):
            assert cls in _COMPOSITE


class TestPlainControlsStillGetNamed:
    """A control with no label to borrow still needs the helper."""

    def test_a_text_field_is_named(self, frame):
        ctrl = wx.TextCtrl(frame)
        set_accessible_name(ctrl, "Feed URL")
        assert ctrl.GetName() == "Feed URL"
        helper = getattr(ctrl, "_a11y_helper", None)
        if helper is not None:      # wx.Accessible is Windows-only
            assert helper.GetName(wx.ACC_SELF) == (wx.ACC_OK, "Feed URL")

    def test_children_are_left_to_the_platform(self, frame):
        """The helper answers for the control itself and nothing else.

        A helper that names every child id makes each child announce as its
        parent, which is exactly the tab bug.
        """
        ctrl = wx.TextCtrl(frame)
        set_accessible_name(ctrl, "Feed URL")
        helper = getattr(ctrl, "_a11y_helper", None)
        if helper is None:
            pytest.skip("wx.Accessible is not available on this platform")
        status, _name = helper.GetName(1)
        assert status == wx.ACC_NOT_IMPLEMENTED
