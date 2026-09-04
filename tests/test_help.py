"""F1 answers everywhere: the engine, the catalogue, and the coverage gate.

The gate is the part that matters over time. Every control has help today; the
question this file settles is whether the next one will, and the answer is that
a control with nothing authored fails the build rather than shipping with an
F1 that says only its name.
"""

from __future__ import annotations

import pytest

from podharvest import help as help_mod
from podharvest import help_audit


class TestCoverage:
    def test_every_control_explains_itself(self):
        """A new control is `missing` until somebody writes a sentence."""
        snapshot = help_audit.build_snapshot(help_audit.scan(), help_audit.load_snapshot())
        missing = sorted(k for k, v in snapshot.items() if v == help_audit.MISSING)
        assert not missing, (
            "These controls answer F1 with nothing of their own:\n  "
            + "\n  ".join(missing)
            + "\nWrite a sentence at the construction site, or classify the "
              "site opt-out in tests/help_inventory.json with a reason."
        )

    def test_the_snapshot_matches_the_code(self):
        """A control that vanished or appeared must be reviewed, not assumed."""
        live = help_audit.build_snapshot(help_audit.scan(), help_audit.load_snapshot())
        recorded = help_audit.load_snapshot()
        assert recorded, "run: python -m podharvest.help_audit --write"
        assert set(live) == set(recorded), (
            "The control inventory changed. Re-run "
            "`python -m podharvest.help_audit --write` and review the diff."
        )

    def test_it_scans_every_module_that_builds_a_window(self):
        from pathlib import Path

        package = Path(help_audit.__file__).parent
        with_wx = {
            path.name
            for path in package.glob("*.py")
            if "import wx" in path.read_text(encoding="utf-8")
        }
        # a11y.py and help.py hold helpers; cli.py imports wx only to launch
        # the GUI; cues.py imports it only to ring the system bell where there
        # is no tone generator. None of the four builds a control. Everything
        # else must be scanned, or a whole window could go undocumented
        # unnoticed -- which is what this gate is for, so the exception list
        # earns its keep only while every entry has a reason written beside it.
        allowed = {"a11y.py", "help.py", "cli.py", "cues.py"}
        assert with_wx - set(help_audit.SCAN_FILES) <= allowed


class TestWindowPurposes:
    def test_every_window_says_what_it_is_for(self):
        for title in ("podHarvest", "Settings", "Media tools", "Edit chapter",
                      "Find a podcast", "Favourite podcasts", "Transcript",
                      "Tags and chapters", "About"):
            assert help_mod.purpose_for_title(title) != help_mod.GENERIC_PURPOSE

    def test_every_window_the_program_builds_has_one(self):
        """The gate that would have caught the two windows that did not.

        A new dialog is easy to add and easy to forget here, and forgetting is
        invisible: F1 still answers, just with the generic sentence, which
        reads as though nobody thought about that window. So the titles are
        read out of the source rather than listed by hand.
        """
        import ast
        from pathlib import Path

        package = Path(help_mod.__file__).parent
        titles: set[str] = set()
        for name in ("discover.py", "reader.py", "editor.py", "gui.py"):
            tree = ast.parse((package / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # super().__init__(parent, title="Find a podcast", ...)
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "title" and isinstance(
                            keyword.value, ast.Constant) and isinstance(
                            keyword.value.value, str):
                        titles.add(keyword.value.value)
        missing = {t for t in titles
                   if t and help_mod.purpose_for_title(t) == help_mod.GENERIC_PURPOSE}
        assert not missing, (
            f"these windows have no authored purpose in help.PURPOSES: "
            f"{sorted(missing)}")

    def test_a_title_carrying_live_data_still_resolves(self):
        """"Tags and chapters - 0042-an-episode.mp3" is still the tag editor."""
        resolved = help_mod.purpose_for_title("Tags and chapters - 0042-an-episode.mp3")
        assert resolved == help_mod.PURPOSES["Tags and chapters"]

    def test_an_unknown_window_falls_back_rather_than_saying_nothing(self):
        assert help_mod.purpose_for_title("Some Window") == help_mod.GENERIC_PURPOSE
        assert help_mod.purpose_for_title("") == help_mod.GENERIC_PURPOSE

    def test_the_purposes_are_sentences_not_labels(self):
        for title, purpose in help_mod.PURPOSES.items():
            assert purpose.endswith("."), f"{title} does not end in a full stop"
            assert len(purpose.split()) >= 12, f"{title} is a label, not a purpose"


class TestComposition:
    def test_a_control_with_nothing_authored_still_answers(self):
        """A silent F1 cannot be told from a broken one."""
        body = help_mod.compose_control_body(accessible_name="", help_text="", usage="")
        assert body

    def test_the_name_comes_first_then_the_help_then_the_keys(self):
        body = help_mod.compose_control_body(
            accessible_name="Feed URL",
            help_text="The podcast's address.",
            usage="A text field: type into it.",
        )
        assert body.index("Feed URL") < body.index("The podcast's address.")
        assert body.index("The podcast's address.") < body.index("A text field")

    def test_a_help_text_that_is_the_name_is_not_said_twice(self):
        body = help_mod.compose_control_body(
            accessible_name="Start", help_text="Start the run.", usage=""
        )
        assert body.count("Start") == 1

    def test_every_role_has_its_own_keys(self):
        for role in ("Button", "CheckBox", "TextCtrl", "ListCtrl", "Choice", "Slider"):
            assert help_mod.role_usage(role) != help_mod.GENERIC_USAGE

    def test_an_unknown_role_still_says_something_useful(self):
        assert help_mod.role_usage("SomeFutureWidget") == help_mod.GENERIC_USAGE


class TestTheWxHalf:
    @pytest.fixture
    def app(self, wx_app):
        """The session-wide wx.App -- see tests/conftest.py."""
        wx = pytest.importorskip("wx")
        help_mod.ensure_help_provider(wx)
        return wx_app

    def test_the_help_provider_makes_set_help_text_live(self, app):
        """Without a provider every SetHelpText stores nothing and says so to nobody."""
        wx = pytest.importorskip("wx")
        frame = wx.Frame(None)
        try:
            button = wx.Button(frame, label="Start")
            button.SetHelpText("Begins the run.")
            assert button.GetHelpText() == "Begins the run."
        finally:
            frame.Destroy()

    def test_explain_sets_both_the_tooltip_and_the_help(self, app):
        wx = pytest.importorskip("wx")
        frame = wx.Frame(None)
        try:
            button = wx.Button(frame, label="Start")
            help_mod.explain(button, "Begins the run.")
            assert button.GetHelpText() == "Begins the run."
            assert button.GetToolTip().GetTip() == "Begins the run."
        finally:
            frame.Destroy()

    def test_a_tooltip_alone_is_read_as_help(self, app):
        """podHarvest wrote its explanations as tooltips before it had F1."""
        wx = pytest.importorskip("wx")
        frame = wx.Frame(None)
        try:
            button = wx.Button(frame, label="Start")
            button.SetToolTip("Begins the run.")
            assert help_mod.help_text_of(button) == "Begins the run."
        finally:
            frame.Destroy()

    def test_f1_answers_with_the_window_then_the_control(self, app):
        wx = pytest.importorskip("wx")
        frame = wx.Frame(None, title="podHarvest")
        try:
            button = wx.Button(frame, label="&Start")
            help_mod.explain(button, "Begins the run with the settings above.")
            heading, body = help_mod.help_for(frame, button, wx)
            assert "Start" in heading
            assert help_mod.PURPOSES["podHarvest"] in body
            assert "Begins the run with the settings above." in body
            assert "A button:" in body
        finally:
            frame.Destroy()

    def test_an_unhelped_control_still_gets_a_real_answer(self, app):
        wx = pytest.importorskip("wx")
        frame = wx.Frame(None, title="podHarvest")
        try:
            box = wx.CheckBox(frame, label="Something")
            _heading, body = help_mod.help_for(frame, box, wx)
            assert "Something" in body
            assert "A checkbox:" in body
        finally:
            frame.Destroy()


class TestWiring:
    def test_every_window_installs_f1(self):
        """Every window, not a count of them.

        Written against the rule rather than a number so that adding a window
        fails this test by *name* -- which is what happened when the bug
        reporter arrived, and is the point of having it.
        """
        import ast
        from pathlib import Path

        package = Path(help_audit.__file__).parent
        unwired: list[str] = []
        for name in ("gui.py", "editor.py"):
            tree = ast.parse((package / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {
                    b.attr for b in node.bases if isinstance(b, ast.Attribute)
                }
                if not bases & {"Dialog", "Frame"}:
                    continue
                body = ast.dump(node)
                if "help_mod" not in body or "install" not in body:
                    unwired.append(f"{name}::{node.name}")
        assert not unwired, (
            "These windows do not answer F1: "
            + ", ".join(unwired)
            + ". Add help_mod.install(self) in the constructor."
        )


class TestReadableSizing:
    """A text box sized in pixels is sized for one font at one scaling factor.

    Set Windows text scaling to 200% and a 90-pixel box that showed five lines
    shows one, with the rest behind a scrollbar -- which fails exactly the
    people who turned the scaling up.
    """

    @pytest.fixture
    def app(self, wx_app):
        """The session-wide wx.App -- see tests/conftest.py."""
        return wx_app

    def test_a_box_is_tall_enough_for_the_lines_asked_for(self, app):
        wx = pytest.importorskip("wx")
        from podharvest.a11y import size_for_text

        frame = wx.Frame(None)
        try:
            ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE)
            size_for_text(ctrl, lines=5)
            assert ctrl.GetMinSize().GetHeight() >= ctrl.GetCharHeight() * 5
        finally:
            frame.Destroy()

    def test_asking_for_more_lines_gives_a_taller_box(self, app):
        wx = pytest.importorskip("wx")
        from podharvest.a11y import size_for_text

        frame = wx.Frame(None)
        try:
            ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE)
            size_for_text(ctrl, lines=4)
            short = ctrl.GetMinSize().GetHeight()
            size_for_text(ctrl, lines=12)
            assert ctrl.GetMinSize().GetHeight() > short
        finally:
            frame.Destroy()

    def test_the_height_tracks_the_font_not_a_pixel_count(self, app):
        """The whole point: scale the text up and the box grows with it."""
        wx = pytest.importorskip("wx")
        from podharvest.a11y import size_for_text

        frame = wx.Frame(None)
        try:
            ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE)
            size_for_text(ctrl, lines=5)
            at_normal = ctrl.GetMinSize().GetHeight()

            font = ctrl.GetFont()
            font.SetPointSize(font.GetPointSize() * 2)
            ctrl.SetFont(font)
            size_for_text(ctrl, lines=5)
            assert ctrl.GetMinSize().GetHeight() > at_normal
        finally:
            frame.Destroy()

    def test_it_sets_a_floor_not_a_ceiling(self, app):
        """Sizers must still be able to stretch the control to fill space."""
        wx = pytest.importorskip("wx")
        from podharvest.a11y import size_for_text

        frame = wx.Frame(None)
        try:
            ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE)
            size_for_text(ctrl, lines=5)
            assert ctrl.GetMaxSize().GetHeight() in (-1, wx.DefaultCoord)
        finally:
            frame.Destroy()

    def test_a_control_that_will_not_measure_itself_is_left_alone(self, app):
        from podharvest.a11y import size_for_text

        class _Stubborn:
            def GetCharHeight(self):  # noqa: N802 - wx API casing
                raise RuntimeError("no font here")

        size_for_text(_Stubborn(), lines=5)  # must not raise

    def test_a_prose_box_cannot_be_crushed_to_a_word_a_line(self, app):
        """Width, not just height. With no width floor, a resized window can
        squeeze a read-only box until every line holds one word -- the
        degenerate wrapping the floor exists to prevent."""
        wx = pytest.importorskip("wx")
        from podharvest.a11y import MIN_PROSE_CHARS, size_for_text

        frame = wx.Frame(None)
        try:
            ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY)
            size_for_text(ctrl, lines=5)
            floor = ctrl.GetCharWidth() * MIN_PROSE_CHARS
            assert ctrl.GetMinSize().GetWidth() >= floor
        finally:
            frame.Destroy()

    def test_the_width_floor_is_a_readable_line_length(self):
        """Typography puts comfortable prose at 45-90 characters a line."""
        pytest.importorskip("wx")
        from podharvest.a11y import MIN_PROSE_CHARS

        assert 45 <= MIN_PROSE_CHARS <= 90

    def test_the_width_floor_tracks_the_font_too(self, app):
        wx = pytest.importorskip("wx")
        from podharvest.a11y import size_for_text

        frame = wx.Frame(None)
        try:
            ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE)
            size_for_text(ctrl, lines=5)
            at_normal = ctrl.GetMinSize().GetWidth()

            font = ctrl.GetFont()
            font.SetPointSize(font.GetPointSize() * 2)
            ctrl.SetFont(font)
            size_for_text(ctrl, lines=5)
            assert ctrl.GetMinSize().GetWidth() > at_normal
        finally:
            frame.Destroy()

    def test_the_main_window_cannot_be_sized_below_its_prose(self):
        """The per-box floors are only promises if the window itself has a
        minimum. Without one, wx squeezes the sizers proportionally and the
        model description ends up showing eleven characters a line."""
        pytest.importorskip("wx")
        import inspect

        from podharvest import gui

        assert "_respect_the_text_floors" in inspect.getsource(gui.MainFrame)
        guard = inspect.getsource(gui.MainFrame._respect_the_text_floors)
        assert "SetMinClientSize" in guard
        assert "0.9" in guard, "capped to the screen, so small displays still work"

    def test_no_call_site_opts_out_of_the_width_floor(self):
        """chars=0 turns the floor off. Nothing in the app has a reason to."""
        import re
        from pathlib import Path

        package = Path(__file__).resolve().parent.parent / "podharvest"
        for path in sorted(package.glob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                call = re.search(r"size_for_text\(.*chars=(\d+)", line)
                if call:
                    assert int(call.group(1)) > 0, f"{path.name}: {line.strip()}"

    def test_no_read_only_box_is_sized_in_raw_pixels(self):
        """The defect this guards: a hardcoded height beside TE_READONLY."""
        import re
        from pathlib import Path

        package = Path(__file__).resolve().parent.parent / "podharvest"
        for name in ("gui.py", "editor.py"):
            source = (package / name).read_text(encoding="utf-8")
            for match in re.finditer(r"wx\.TextCtrl\((?:[^()]|\([^()]*\))*\)", source):
                call = match.group(0)
                if "TE_MULTILINE" not in call:
                    continue
                assert "size=(" not in call and "size=wx.Size" not in call, (
                    f"{name}: a multi-line box is sized in pixels:\n{call}\n"
                    "Use size_for_text(ctrl, lines=N) so it scales with the font."
                )

    def test_the_activity_log_wraps_rather_than_scrolling_sideways(self):
        """Its lines are prose sentences, not columns.

        Checks the style flag rather than the word, so the comment explaining
        the choice does not trip the test that enforces it.
        """
        import re
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent
                  / "podharvest" / "gui.py").read_text(encoding="utf-8")
        for match in re.finditer(r"wx\.TextCtrl\((?:[^()]|\([^()]*\))*\)", source):
            assert "TE_DONTWRAP" not in match.group(0), match.group(0)


class TestPackaging:
    """A module reached only from a menu handler is invisible to PyInstaller.

    The spec already says so in a comment and lists the lazy modules by hand.
    This keeps that list honest: a new module that the GUI reaches lazily but
    the spec does not name ships as a window that raises when opened, which is
    not something a unit test run from source can otherwise notice.
    """

    def test_every_gui_module_is_named_in_the_spec(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        package = root / "podharvest"
        missing = [
            f"podharvest.{path.stem}"
            for path in sorted(package.glob("*.py"))
            # help_audit is a build-time gate, not runtime code: it is run
            # from a checkout and has no business inside the shipped app.
            if path.stem not in {"__init__", "__main__", "help_audit"}
            and f'"podharvest.{path.stem}"' not in spec
        ]
        assert not missing, (
            "These modules are not in packaging/podharvest.spec, so a built "
            "app may not contain them: " + ", ".join(missing)
        )

    def test_the_libraries_the_gui_needs_are_named(self):
        from pathlib import Path

        spec = (Path(__file__).resolve().parent.parent
                / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        for module in ("wx.media", "mutagen"):
            assert f'"{module}"' in spec, f"{module} is not bundled"
