"""Announcements have to survive being frozen.

The failure this guards against is the quiet one: `accessible_output2`
imports perfectly well in a frozen build and then says nothing, because the
screen reader client DLLs it talks through were not bundled, or were
bundled somewhere it does not look. Nothing raises. The app simply never
speaks, and the only way to find out is to install it and listen.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
BUILD_REQS = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
LOCK = (ROOT / "requirements-build.lock").read_text(encoding="utf-8")


class TestItShipsWithTheApp:
    def test_the_build_requires_it(self):
        """The shipped app carries it; a pip install still fetches on demand."""
        assert "accessible_output2" in BUILD_REQS

    def test_it_is_pinned_with_a_hash(self):
        assert "accessible-output2==" in LOCK
        # And so are the two packages it needs to find its own libraries.
        assert "platform-utils==" in LOCK
        assert "libloader==" in LOCK

    def test_the_library_itself_stays_dependency_free(self):
        """`dependencies = []` is a promise about `pip install podharvest`."""
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "dependencies = []" in pyproject
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "accessible_output2" not in requirements


class TestTheSpecCollectsWhatItNeeds:
    def test_the_data_files_are_collected(self):
        """The DLLs are data, not binaries: they must land at
        accessible_output2/lib/, which is the only place the frozen
        `load_library` looks."""
        assert "collect_data_files" in SPEC
        assert '"accessible_output2"' in SPEC

    def test_the_output_backends_are_collected(self):
        """They are found by walking a module dict, so nothing static sees
        nvda, jaws, sapi5 and the rest."""
        assert "collect_submodules" in SPEC

    def test_its_own_dependencies_come_too(self):
        assert "platform_utils" in SPEC
        assert "libloader" in SPEC

    def test_the_collected_files_reach_the_analysis(self):
        """Collecting them and then not passing them on is a silent no-op."""
        assert "*announce_datas" in SPEC
        assert "*announce_hiddenimports" in SPEC

    def test_a_build_without_it_still_succeeds(self):
        """A contributor's machine need not have it to build podHarvest."""
        assert "except ImportError:" in SPEC
        assert "fetch it on demand" in SPEC


class TestTheRuntimeHook:
    """PyInstaller 6 moved bundled data; the library still looks the old way.

    `accessible_output2.load_library` asks `embedded_data_path()` for the
    data folder and gets the executable's directory, which was right up to
    PyInstaller 5. PyInstaller 6 puts data in `_internal` instead. Verified
    against a real build: the folder was not beside the exe, so every DLL
    load would have failed -- silently, because nothing raises until a
    library is actually wanted.
    """

    HOOK = ROOT / "packaging" / "rthook_accessible_output2.py"

    def test_the_hook_exists_and_is_registered(self):
        assert self.HOOK.is_file()
        assert "runtime_hooks=" in SPEC
        assert "rthook_accessible_output2.py" in SPEC

    def test_it_points_at_the_bundle_data_directory(self):
        source = self.HOOK.read_text(encoding="utf-8")
        assert "_MEIPASS" in source
        assert "embedded_data_path" in source

    def test_it_only_redirects_when_the_library_is_really_there(self):
        """A build that shipped without it keeps whatever behaviour it had."""
        source = self.HOOK.read_text(encoding="utf-8")
        assert "isdir" in source

    def test_it_cannot_stop_podharvest_starting(self):
        """A fix-up for one optional feature must never be fatal."""
        source = self.HOOK.read_text(encoding="utf-8")
        assert "except Exception" in source

    def test_it_runs_without_a_bundle_present(self):
        """Imported outside a frozen app it must simply do nothing."""
        import runpy

        runpy.run_path(str(self.HOOK))      # raises if it is not safe
