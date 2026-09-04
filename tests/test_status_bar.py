"""A status bar you can reach, read, and act on.

wx's own status bar cannot take focus. A screen reader user can only find it
by hunting with a review cursor, and nothing announces when it changes -- so
podHarvest wrote "Detecting hardware..." into it and then never wrote anything
again. The window sat claiming it was detecting hardware indefinitely, and
nobody noticed, because nobody could look at it. That is the failure mode of a
control nobody can reach.

These cover the replacement: real buttons, arrow navigation, activation, a
context menu, and above all cells whose text is *derived* rather than written
once and forgotten.
"""

from __future__ import annotations

import inspect

import pytest

from podharvest.status_bar import CellSpec, StatusBar, clamp_index


class _Host:
    """A main window, reduced to what the bar actually asks of it."""

    def __init__(self, **values) -> None:
        self.values = {
            "status_activity": "Ready",
            "status_progress": "",
            "status_progress_detail": "Nothing is running.",
            "status_source": "No feed yet",
            "status_model": "small.en, ready",
            "status_library": "3 episodes",
        }
        self.values.update(values)
        self.said: list[str] = []
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name in self.__dict__.get("values", {}):
            return lambda: self.values[name]
        raise AttributeError(name)

    def _announce(self, message):
        self.said.append(message)

    def _focus_episodes(self):
        self.calls.append("episodes")

    def _focus_source(self):
        self.calls.append("source")

    def _on_focus_log(self, _evt=None):
        self.calls.append("log")

    def _status_model_action(self):
        self.calls.append("model")

    def _toggle_status_bar(self):
        self.calls.append("toggle")


class TestWhatItShows:
    def test_it_has_a_cell_for_each_thing_worth_knowing(self):
        bar = StatusBar(_Host(), wx=None)
        assert bar.cell_keys() == [
            "activity", "progress", "source", "model", "library", "clock"]

    def test_each_cell_reads_live_state(self):
        host = _Host(status_library="7 episodes")
        bar = StatusBar(host, wx=None)
        assert bar.cell_text("library") == "7 episodes"
        host.values["status_library"] = "8 episodes"
        assert bar.cell_text("library") == "8 episodes", (
            "a cell that caches is a cell that lies")

    def test_a_cell_with_nothing_to_say_says_nothing(self):
        """Better an absent value than "Progress: none"."""
        bar = StatusBar(_Host(status_progress=""), wx=None)
        assert bar.cell_text("progress") == ""

    def test_the_clock_is_a_time(self):
        bar = StatusBar(_Host(), wx=None)
        text = bar.cell_text("clock")
        assert len(text) == 5 and text[2] == ":"

    def test_a_host_that_cannot_answer_falls_back(self):
        """A status bar must never be the thing that breaks a window."""

        class Silent:
            pass

        bar = StatusBar(Silent(), wx=None)
        assert bar.cell_text("activity") == "Ready"
        assert bar.cell_text("library") == ""

    def test_a_host_that_raises_is_survived(self):
        class Exploding:
            def status_activity(self):
                raise RuntimeError("boom")

        bar = StatusBar(Exploding(), wx=None)
        assert bar.cell_text("activity") == "Ready"


class TestHowItReadsAloud:
    def test_a_cell_is_named_then_valued(self):
        """The comma matters: a screen reader pauses at it."""
        bar = StatusBar(_Host(), wx=None)
        spec = next(s for s in bar._specs if s.key == "model")
        assert bar._name(spec) == "Model, small.en, ready"

    def test_a_cell_with_no_value_is_just_its_name(self):
        bar = StatusBar(_Host(status_progress=""), wx=None)
        spec = next(s for s in bar._specs if s.key == "progress")
        assert bar._name(spec) == "Progress"

    def test_the_label_uses_a_colon_and_the_name_a_comma(self):
        bar = StatusBar(_Host(), wx=None)
        spec = next(s for s in bar._specs if s.key == "library")
        assert bar._label(spec) == "Library: 3 episodes"
        assert bar._name(spec) == "Library, 3 episodes"

    def test_every_cell_explains_itself(self):
        bar = StatusBar(_Host(), wx=None)
        for spec in bar._specs:
            assert spec.help.strip(), spec.key
            assert spec.help.endswith("."), spec.key

    def test_every_help_says_what_enter_does(self):
        """A focusable cell that does something must say what."""
        bar = StatusBar(_Host(), wx=None)
        for spec in bar._specs:
            assert "Enter" in spec.help, spec.key


class TestMovingAcrossIt:
    def test_it_stops_at_the_ends_rather_than_wrapping(self):
        """Wrapping loses you when you cannot see it happen."""
        assert clamp_index(-1, 6) == 0
        assert clamp_index(6, 6) == 5
        assert clamp_index(3, 6) == 3

    def test_an_empty_bar_does_not_divide_by_zero(self):
        assert clamp_index(4, 0) == 0

    def test_the_arrows_move_and_home_and_end_jump(self):
        source = inspect.getsource(StatusBar._on_key)
        for key in ("WXK_LEFT", "WXK_RIGHT", "WXK_HOME", "WXK_END"):
            assert key in source, key

    def test_enter_and_space_both_activate(self):
        source = inspect.getsource(StatusBar._on_key)
        assert "WXK_RETURN" in source and "WXK_SPACE" in source

    def test_escape_leaves(self):
        assert "WXK_ESCAPE" in inspect.getsource(StatusBar._on_key)

    def test_tab_treats_the_bar_as_one_stop(self):
        """Six cells would otherwise mean six presses to tab past it."""
        source = inspect.getsource(StatusBar._on_key)
        assert "WXK_TAB" in source
        assert "Navigate" in source

    def test_f6_goes_in_and_comes_back_out(self):
        source = inspect.getsource(StatusBar.toggle_focus)
        assert "has_focus()" in source
        assert "_leave" in source and "focus_bar" in source


class TestActingOnACell:
    def test_each_cell_does_something_useful(self):
        host = _Host()
        bar = StatusBar(host, wx=None)
        bar.activate("library")
        bar.activate("source")
        bar.activate("model")
        bar.activate("activity")
        assert host.calls == ["episodes", "source", "model", "log"]

    def test_progress_says_the_whole_thing(self):
        host = _Host(status_progress_detail="Episode 3 of 40, 22% of this one.")
        bar = StatusBar(host, wx=None)
        bar.activate("progress")
        assert host.said == ["Episode 3 of 40, 22% of this one."]

    def test_a_cell_whose_action_fails_does_not_take_the_bar_with_it(self):
        host = _Host()
        bar = StatusBar(host, wx=None)
        bar._specs = [CellSpec(
            key="bad", name="Bad", text=lambda: "",
            activate=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            help="Enter breaks.")]
        bar.activate("bad")
        assert any("Could not act on Bad" in said for said in host.said)

    def test_the_region_is_named_only_on_the_way_in(self):
        """Repeating "Status bar" on every arrow press is what makes people
        stop using a feature."""
        source = inspect.getsource(StatusBar._on_focus)
        assert "Status bar, " in source
        assert "entering" in source


class TestTheContextMenu:
    def test_it_offers_the_action_a_copy_and_a_way_out(self):
        source = inspect.getsource(StatusBar._on_context_menu)
        for entry in ("&Activate", "&Copy this value", "&Say it again",
                      "&Hide the status bar"):
            assert entry in source, entry

    def test_copying_puts_the_value_on_the_clipboard(self):
        source = inspect.getsource(StatusBar._copy)
        assert "TheClipboard" in source
        assert "TextDataObject" in source

    def test_a_clipboard_that_will_not_open_says_so(self):
        source = inspect.getsource(StatusBar._copy)
        assert "Could not reach the clipboard" in source


class TestTheWindowUsesIt:
    @pytest.fixture
    def frame(self, wx_app):
        from podharvest import gui

        window = gui.MainFrame()
        yield window
        if getattr(window, "_status_timer", None) is not None:
            window._status_timer.Stop()
        window._alive = False
        if getattr(window, "_tray", None) is not None:
            try:
                window._tray.Destroy()
            except Exception:
                pass
        window.Destroy()

    def test_the_dead_wx_status_bar_is_gone(self):
        """It could not take focus, and it is what told the lie."""
        pytest.importorskip("wx")
        from podharvest import gui

        # The code, not the comment explaining why it is not there.
        source = "\n".join(
            line for line in inspect.getsource(gui.MainFrame).splitlines()
            if not line.strip().startswith("#"))
        assert "self.CreateStatusBar()" not in source
        assert "SetStatusText" not in source

    def test_the_bar_is_built_and_reachable(self, frame):
        assert frame.status_bar is not None
        assert frame.status_bar.cell_keys()

    def test_f6_moves_focus_in_and_out(self, frame):
        frame._on_status_focus()
        assert frame.status_bar.has_focus()
        frame._on_status_focus()
        assert not frame.status_bar.has_focus()

    def test_f6_has_a_menu_entry_and_an_accelerator(self, frame):
        bar = frame.GetMenuBar()
        labels = [item.GetItemLabel()
                  for index in range(bar.GetMenuCount())
                  for item in bar.GetMenu(index).GetMenuItems()
                  if not item.IsSeparator()]
        assert any("F6" in label for label in labels)

    def test_it_can_be_hidden_and_the_choice_remembered(self, frame):
        assert frame.status_bar.is_shown()
        frame._toggle_status_bar()
        assert not frame.status_bar.is_shown()
        assert frame.settings.show_status_bar is False
        frame._toggle_status_bar()
        assert frame.status_bar.is_shown()

    def test_activity_stops_saying_checking_once_it_has_checked(self, frame):
        """The reported bug: the window claimed to be detecting hardware
        forever, because nothing ever wrote to the bar again."""
        frame._hw = None
        assert "Checking" in frame.status_activity()
        frame._hw = object()
        frame._worker = None
        assert frame.status_activity() == "Ready"

    def test_the_bar_is_repainted_on_a_timer(self, frame):
        """Nothing pushes to it when nothing is running, and a clock that
        stops is worse than no clock."""
        assert frame._status_timer is not None
        assert frame._status_timer.IsRunning()

    def test_every_cell_answers_on_a_real_window(self, frame):
        for key in frame.status_bar.cell_keys():
            assert isinstance(frame.status_bar.cell_text(key), str)

    def test_the_source_cell_follows_the_source(self, frame):
        from podharvest.gui import _SOURCE_MODES

        frame.mode_radio.SetSelection(_SOURCE_MODES.index("local"))
        assert "local file" in frame.status_source()
        frame.mode_radio.SetSelection(_SOURCE_MODES.index("find"))
        frame.url_ctrl.SetValue("")
        assert frame.status_source() == "Find a podcast"

    def test_the_library_cell_counts_what_is_listed(self, frame):
        assert frame.status_library().endswith("episodes")


class TestTheSettingsDialogFitsOnAScreen:
    """The settings outgrew any laptop: 1,750 pixels of content on a
    955-pixel display, with OK and Cancel below the bottom edge -- a dialog a
    keyboard user could enter and not leave. The content now scrolls and the
    buttons stay put.
    """

    @pytest.fixture
    def dialog(self, wx_app):
        import wx

        from podharvest import gui

        frame = gui.MainFrame()
        dlg = gui.SettingsDialog(frame, frame.app_space, frame.settings)
        yield dlg, frame, wx
        dlg.Destroy()
        if getattr(frame, "_status_timer", None) is not None:
            frame._status_timer.Stop()
        frame._alive = False
        if getattr(frame, "_tray", None) is not None:
            try:
                frame._tray.Destroy()
            except Exception:
                pass
        frame.Destroy()

    def test_it_is_no_taller_than_the_screen(self, dialog):
        dlg, _frame, wx = dialog
        display = wx.Display(0).GetClientArea()
        assert dlg.GetSize().height <= display.height

    def test_the_content_scrolls_rather_than_being_cut(self, dialog):
        dlg, _frame, _wx = dialog
        assert dlg._content.GetVirtualSize().height > dlg.GetClientSize().height

    def test_ok_and_cancel_never_scroll_away(self, dialog):
        """They sit on the dialog, outside the scroller, so leaving the
        dialog never requires finding the bottom of a long page first."""
        dlg, _frame, wx = dialog
        # Direct children only: FindWindowById searches globally, and another
        # window in the shared test session may also own a wx.ID_OK.
        direct = {child.GetId(): child for child in dlg.GetChildren()
                  if isinstance(child, wx.Button)}
        assert wx.ID_OK in direct and wx.ID_CANCEL in direct

    def test_applying_still_reaches_every_section(self, dialog):
        """Reparenting eight boxes must not have detached any control from
        the code that reads it."""
        dlg, frame, _wx = dialog
        dlg.chk_sound_cues.SetValue(True)
        dlg.mai_region_ctrl.SetValue("eastus")
        dlg.search_limit_ctrl.SetValue(30)
        dlg.apply_to(frame.settings)
        assert frame.settings.sound_cues is True
        assert frame.settings.azure_speech_region == "eastus"
        assert frame.settings.search_limit == 30

    def test_key_captions_promise_only_what_the_key_unlocks(self, dialog):
        """Groq and ElevenLabs transcribe and cannot summarise; the caption
        used to promise both for any provider that could transcribe."""
        import wx

        dlg, _frame, _wx = dialog
        labels = [w.GetLabel()
                  for box in dlg._content.GetChildren()
                  for w in ([box] + list(box.GetChildren()))
                  if isinstance(w, wx.StaticText)]
        joined = " | ".join(labels)
        assert "Groq (transcripts only):" in joined
        assert "ElevenLabs (transcripts only):" in joined
        assert "OpenRouter (summaries only):" in joined
        assert "OpenAI (transcripts and summaries):" in joined
