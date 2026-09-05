"""Installing the ASR engines, and the bug that stopped it in every build.

The frozen build's `sys.executable` is `podharvest.exe`, not a Python
interpreter. `ensure_package` ran `[sys.executable, "-m", "pip", "install",
...]`, so in every packaged copy that became `podharvest.exe -m pip install
...` -- which reached podHarvest's own argument parser and died with
``invalid choice: 'pip'``. Every engine download failed with exit 2, and the
only symptom a user saw was "skipping transcription".

The source checkout was fine, which is why it survived to release: nothing in
a developer's environment reproduces it. So these tests are written against
the frozen case specifically, and against the seam that makes it testable at
all -- `pip_command`, which exists so the decision has a name.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from podharvest import acquire


class TestReachingPip:
    def test_a_source_checkout_runs_pip_as_a_module(self, monkeypatch):
        monkeypatch.setattr(acquire.sys, "frozen", False, raising=False)
        cmd = acquire.pip_command("T", [], "faster-whisper")
        assert cmd[:3] == [sys.executable, "-m", "pip"]

    def test_a_frozen_build_does_not(self, monkeypatch):
        """The regression. `-m pip` here means `podharvest.exe -m pip`."""
        monkeypatch.setattr(acquire.sys, "frozen", True, raising=False)
        cmd = acquire.pip_command("T", [], "faster-whisper")
        assert "-m" not in cmd, "this is what reached podHarvest's own parser"
        assert cmd[1] == acquire.PIP_SUBCOMMAND

    def test_the_two_halves_of_the_passthrough_agree(self):
        """acquire builds the command; cli reads it. One name, two files."""
        from podharvest.cli import PIP_PASSTHROUGH

        assert acquire.PIP_SUBCOMMAND == PIP_PASSTHROUGH

    @pytest.mark.parametrize("frozen", [False, True])
    def test_the_install_arguments_survive_either_way(self, monkeypatch, frozen):
        monkeypatch.setattr(acquire.sys, "frozen", frozen, raising=False)
        cmd = acquire.pip_command("/tmp/pydeps", ["--extra-index-url", "u"], "vosk")
        assert cmd[-1] == "vosk"
        assert "--target" in cmd and "/tmp/pydeps" in cmd
        assert "--extra-index-url" in cmd and "u" in cmd
        assert "install" in cmd

    def test_pip_is_handled_before_the_argument_parser(self):
        """A subcommand would have had argparse eat --target and --index-url."""
        from podharvest import cli

        source = inspect.getsource(cli.main)
        assert "PIP_PASSTHROUGH" in source
        assert source.index("PIP_PASSTHROUGH") < source.index("build_parser()")

    def test_the_passthrough_is_not_advertised_as_a_command(self):
        """It is plumbing. It must not appear in the usage screen."""
        from podharvest.cli import build_parser

        help_text = build_parser().format_help()
        assert "_pip" not in help_text
        assert "SUPPRESS" not in help_text


class TestWhenPipIsNotThere:
    def test_a_missing_pip_is_explained_rather_than_attempted(self, monkeypatch):
        import builtins

        real = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "pip":
                raise ImportError("no pip")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        monkeypatch.setattr(acquire.sys, "frozen", True, raising=False)
        ok, why = acquire.pip_available()
        assert ok is False
        assert "packaging fault" in why, "a user cannot fix a build problem"

    def test_a_missing_pip_stops_the_install_before_it_runs(self, monkeypatch, tmp_path):
        """Better a clear sentence than a subprocess that cannot work."""
        from podharvest.appspace import AppSpace

        ran = []
        monkeypatch.setattr(acquire, "pip_available", lambda: (False, "no pip here"))
        monkeypatch.setattr(acquire.subprocess, "run",
                            lambda *a, **k: ran.append(a) or None)
        app = AppSpace(tmp_path).ensure()
        assert acquire.ensure_package(app, "nothing-real-xyz", "nothing_real_xyz") is False
        assert ran == [], "no subprocess should have been attempted"

    def test_pip_is_present_in_this_checkout(self):
        """Guards the test above from passing for the wrong reason."""
        assert acquire.pip_available()[0] is True


class TestKnowingBeforeYouStart:
    """The other half of the report: say what is missing before a run, not
    three minutes into one."""

    def test_a_package_that_is_not_installed_is_reported_missing(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        missing = acquire.missing_packages(
            app, [("definitely-not-real", "definitely_not_real_xyz")])
        assert missing == ["definitely-not-real"]

    def test_a_package_that_is_installed_is_not(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        assert acquire.missing_packages(app, [("json-ish", "json")]) == []

    def test_every_engine_can_be_asked(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        for engine in acquire.ENGINE_PACKAGES:
            assert isinstance(acquire.engine_packages_missing(app, engine), list)

    def test_an_unknown_engine_needs_nothing_rather_than_raising(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        assert acquire.engine_packages_missing(app, "no-such-engine") == []

    def test_diarization_backends_can_be_asked_too(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        for backend in acquire.DIARIZATION_PACKAGES:
            assert isinstance(acquire.diarization_packages_missing(app, backend), list)


class TestSayingSoHonestly:
    """A run that transcribed nothing must not report that it finished."""

    def test_the_batch_reports_whether_it_ran(self):
        """Both answers, explicitly. Falling off the end returns None, which
        is falsy -- and would have reported every good run as a failed one."""
        from podharvest import harvest

        source = inspect.getsource(harvest.transcribe_all)
        assert "return False" in source, "the could-not-start answer"
        # The success answer is computed from the tally rather than hard-coded,
        # so that a run where every file failed is not called a success.
        assert "return finished > 0 or not failed" in source

    def test_a_batch_with_transcription_off_still_counts_as_run(self, tmp_path):
        from podharvest import harvest
        from podharvest.appspace import AppSpace
        from podharvest.config import Settings

        # No episodes and no model wanted: nothing to do, but nothing failed.
        result = harvest.transcribe_all(
            [], tmp_path, app=AppSpace(tmp_path).ensure(),
            settings=Settings(), model=None)
        assert result is not None, "None is falsy and would read as failure"

    def test_a_run_where_every_file_failed_is_not_a_success(self):
        """"All done." over a pile of failures is not a true sentence."""
        from podharvest import harvest

        source = inspect.getsource(harvest.transcribe_all)
        assert "None of the %d file(s) could be transcribed" in source
        assert 'outcomes.count("failed")' in source

    def test_a_partial_failure_says_how_many(self):
        from podharvest import harvest

        source = inspect.getsource(harvest.transcribe_all)
        assert "%d of %d transcribed" in source

    def test_a_failed_engine_setup_is_not_called_done(self):
        from podharvest import harvest

        source = inspect.getsource(harvest.run_harvest)
        assert "if not transcribed:" in source
        assert "Finished without transcripts" in source

    def test_the_local_route_says_your_files_are_untouched(self):
        from podharvest import localfiles

        source = inspect.getsource(localfiles.run_local)
        assert "if not transcribed:" in source
        assert "Nothing was transcribed" in source
        assert "still listed" in source, "you can still play and edit them"

    def test_the_engine_failure_names_what_happened(self):
        from podharvest import harvest

        source = inspect.getsource(harvest.transcribe_all)
        assert "Nothing was transcribed" in source
        assert "could not be set up" in source
        assert "files were changed" in source


class TestPackaging:
    def test_pip_travels_with_the_frozen_build(self):
        """Without this the passthrough has nothing to hand to."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "_pip_tree()" in spec
        assert "pip_datas" in spec

    def test_pip_is_shipped_unfrozen_and_both_sides_agree_where(self):
        """Frozen, pip's vendored distlib cannot find a resource finder for
        PyInstaller's loader and every install dies. Plain files fix it -- so
        the spec must not go back to freezing it, and the runtime must look
        where the spec puts it."""
        from pathlib import Path

        from podharvest.cli import PIP_RUNTIME_DIR

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert 'collect_all("pip")' not in spec, "frozen pip cannot install"
        assert f'PIP_RUNTIME_DIR = "{PIP_RUNTIME_DIR}"' in spec

    def test_a_source_checkout_has_no_bundled_pip_directory(self):
        from podharvest.cli import bundled_pip_dir

        assert bundled_pip_dir() is None


class TestSeeingWhatWasJustInstalled:
    """A successful install that cannot then be imported is a failed install.

    Python caches what it found in each `sys.path` entry. The app-space pydeps
    folder goes on the path *before* the install, when it is empty or absent,
    so the freshly written package is invisible afterwards unless the cache is
    dropped. The symptom was "faster-whisper installed but still not
    importable" -- with the package plainly sitting on disk.
    """

    def test_the_import_cache_is_dropped_after_installing(self):
        source = inspect.getsource(acquire.ensure_package)
        assert "importlib.invalidate_caches()" in source
        # And after the install, not before, or it would cache the empty state
        # all over again.
        assert source.index("pip_command") < source.index("invalidate_caches")

    def test_a_package_written_after_the_path_was_set_is_found(self, tmp_path):
        """The real mechanism, without a network: put the folder on the path
        while it is empty, write a module into it, and it must be importable."""
        import importlib
        import sys

        pydeps = tmp_path / "pydeps"
        pydeps.mkdir()
        sys.path.insert(0, str(pydeps))
        try:
            # Prime the cache the way app.activate() does before an install.
            with pytest.raises(ImportError):
                importlib.import_module("late_arrival_xyz")
            (pydeps / "late_arrival_xyz.py").write_text("VALUE = 1", encoding="utf-8")

            importlib.invalidate_caches()
            module = importlib.import_module("late_arrival_xyz")
            assert module.VALUE == 1
        finally:
            sys.path.remove(str(pydeps))
            sys.modules.pop("late_arrival_xyz", None)

    def test_the_failure_message_points_at_the_likely_cause(self):
        """If it still cannot import, the next suspect is an ABI mismatch."""
        source = inspect.getsource(acquire.ensure_package)
        assert "different" in source and "Python" in source


class TestTheDoctor:
    """`podharvest doctor` -- the answer to "is this actually going to work?"

    Written because the only way to find out used to be to start a run and
    wait. "Installed" and "loads" are separate questions, and the gap between
    them is where the awkward failures live.
    """

    def test_it_is_a_command(self):
        from podharvest.cli import _HANDLERS, build_parser

        assert "doctor" in _HANDLERS
        args = build_parser().parse_args(["doctor"])
        assert args.command == "doctor"

    def test_it_can_be_narrowed_to_one_engine(self):
        from podharvest.cli import build_parser

        args = build_parser().parse_args(["doctor", "--engine", "vosk"])
        assert args.engine == "vosk"

    def test_a_missing_package_is_reported_as_not_downloaded(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        report = acquire.check_package(app, "nope-xyz", "nope_xyz_module")
        assert report.ok is False
        assert report.installed is False
        assert "not downloaded" in report.sentence()

    def test_a_working_package_is_reported_ready(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        report = acquire.check_package(app, "json-ish", "json")
        assert report.ok is True
        assert report.sentence().endswith("ready")

    def test_a_package_that_will_not_load_is_not_called_ready(self, tmp_path):
        """The important case: on disk, passes a file check, cannot import.

        A DLL that will not load looks exactly like a healthy install to
        anything that only checks the filesystem.
        """
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        broken = app.python_packages_dir / "brokenmod_xyz"
        broken.mkdir(parents=True, exist_ok=True)
        (broken / "__init__.py").write_text(
            "raise ImportError('DLL load failed while importing _core')",
            encoding="utf-8")
        report = acquire.check_package(app, "brokenmod-xyz", "brokenmod_xyz")
        assert report.installed is True
        assert report.importable is False
        assert "will not load" in report.sentence()
        assert "DLL load failed" in report.error

    def test_every_engine_can_be_checked(self, tmp_path):
        from podharvest.appspace import AppSpace

        app = AppSpace(tmp_path).ensure()
        for engine in acquire.ENGINE_PACKAGES:
            reports = acquire.check_engine(app, engine)
            assert len(reports) == len(acquire.ENGINE_PACKAGES[engine])


class TestStableAbiWheels:
    """`python3.dll` must travel with the frozen build.

    Wheels built against the limited API link their extension against
    `python3.dll`, the forwarder to the real `python313.dll`. CPython ships
    both, so nothing in development shows this. PyInstaller bundles only the
    versioned one, so an abi3 wheel installs perfectly and then fails to
    import with "DLL load failed ... The specified module could not be found"
    -- naming the extension, never the DLL it actually wanted.

    faster-whisper depends on PyAV, PyAV is abi3, so this broke the default
    engine in every packaged copy.
    """

    def test_the_spec_ships_the_forwarder(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "python3.dll" in spec
        assert "abi3_binaries" in spec
        assert "*abi3_binaries" in spec, "collected but never added to the build"

    def test_it_says_so_loudly_when_it_cannot_find_it(self):
        """A silent skip here produces a build that looks fine and is not."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")
        assert "WARNING" in spec


class TestTheFrozenBuildIsACompleteHost:
    """podHarvest pip-installs third-party code into itself at runtime.

    That makes the frozen build a *host*, not just a program, and a host has
    to be a complete Python. PyInstaller's analysis only sees what podHarvest
    itself imports, so without help the standard library arrives with holes --
    and the packages installed later fall into them. `No module named
    'asyncio'`, reported against faster-whisper, was one.
    """

    def _spec(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        return (root / "packaging" / "podharvest.spec").read_text(encoding="utf-8")

    def test_the_whole_standard_library_ships(self):
        spec = self._spec()
        assert "sys.stdlib_module_names" in spec
        assert "stdlib_hiddenimports" in spec
        assert "*stdlib_hiddenimports" in spec, "collected but never used"

    def test_submodules_are_collected_not_just_top_levels(self):
        """Importing `asyncio` does not bring `asyncio.events` with it."""
        spec = self._spec()
        assert "collect_submodules" in spec

    def test_the_reason_is_written_down(self):
        """This looks like over-bundling until you know why it is not."""
        spec = self._spec()
        assert "host" in spec.lower()

    def test_the_skip_list_holds_only_things_nothing_would_import(self):
        """A skip list is where a fix like this quietly goes wrong."""
        import sys

        from podharvest import acquire

        spec = self._spec()
        start = spec.index("_STDLIB_SKIP")
        block = spec[start:spec.index("def _whole_stdlib")]
        skipped = {word.strip('",\n ') for word in block.split()
                   if word.startswith('"')}
        # Nothing an ASR engine could plausibly need.
        for risky in ("asyncio", "sqlite3", "multiprocessing", "email",
                      "http", "xml", "ctypes", "json", "logging", "ssl",
                      "concurrent", "importlib", "typing", "dataclasses"):
            assert risky not in skipped, f"{risky} is needed by real packages"
        # And everything skipped is genuinely part of the standard library, so
        # the list cannot rot into naming something that never existed. The
        # two exceptions are deliberate belt-and-braces entries the spec
        # documents: they are not stdlib module names at all.
        for name in skipped - {"test", "tests"}:
            assert name in sys.stdlib_module_names, f"{name} is not stdlib"
        assert acquire.ENGINE_PACKAGES, "sanity: engines exist to be hosted"


class TestTheReadinessReadout:
    """The GUI half of "is this going to work?" -- answered before Start."""

    @pytest.fixture
    def frame(self, wx_app, tmp_path):
        from podharvest import gui

        window = gui.MainFrame()
        # A private app space, so the answer is about the test and not about
        # whatever this developer happens to have installed.
        from podharvest.appspace import AppSpace

        window.app_space = AppSpace(tmp_path).ensure()
        yield window
        window._alive = False
        if getattr(window, "_tray", None) is not None:
            try:
                window._tray.Destroy()
            except Exception:
                pass
        window.Destroy()

    def _choice(self, **kwargs):
        from podharvest.hardware import ModelChoice

        base = {"engine": "vosk", "model": "vosk-small", "min_ram_gb": 1.0,
                "label": "Vosk small"}
        base.update(kwargs)
        return ModelChoice(**base)

    def test_a_model_that_needs_everything_says_so(self, frame, monkeypatch):
        """Both halves named. Which one is missing decides what you do next.

        The engine's packages are checked by importing them, which is a
        process-wide question rather than a per-app-space one -- so this says
        what is missing rather than depending on what this machine happens to
        have installed.
        """
        monkeypatch.setattr(acquire, "engine_packages_missing",
                            lambda _app, _engine: ["vosk"])
        monkeypatch.setattr(acquire, "is_downloaded", lambda _app, _choice: False)
        ready, sentence = frame._model_readiness(self._choice())
        assert ready is False
        assert "Not downloaded yet" in sentence
        assert "vosk" in sentence, "name the engine, not just 'something'"
        assert "the model itself" in sentence

    def test_a_model_whose_engine_is_ready_asks_only_for_the_weights(self, frame,
                                                                    monkeypatch):
        monkeypatch.setattr(acquire, "engine_packages_missing",
                            lambda _app, _engine: [])
        monkeypatch.setattr(acquire, "is_downloaded", lambda _app, _choice: False)
        _ready, sentence = frame._model_readiness(self._choice())
        assert "the model itself" in sentence
        assert "engine" not in sentence, "do not ask for what is already here"

    def test_everything_present_reads_as_ready(self, frame, monkeypatch):
        monkeypatch.setattr(acquire, "engine_packages_missing",
                            lambda _app, _engine: [])
        monkeypatch.setattr(acquire, "is_downloaded", lambda _app, _choice: True)
        ready, sentence = frame._model_readiness(self._choice())
        assert ready is True
        assert sentence.startswith("Ready:")
        assert "vosk-small" in sentence

    def test_it_says_how_to_fix_it(self, frame, monkeypatch):
        monkeypatch.setattr(acquire, "is_downloaded", lambda _app, _choice: False)
        _ready, sentence = frame._model_readiness(self._choice())
        assert "Download" in sentence
        assert "Start" in sentence, "pressing Start also works; say so"

    def test_a_cloud_model_needs_no_download(self, frame):
        ready, sentence = frame._model_readiness(
            self._choice(engine="openai", model="whisper-1", location="cloud"))
        assert ready is True
        assert "nothing to download" in sentence
        assert "API key" in sentence, "say what it does need"

    def test_the_main_window_offers_only_models_that_can_run(self, frame):
        """A picker whose entries then refuse to run has to be explained
        every time. Setting up is a separate errand, in its own window."""
        import inspect

        source = inspect.getsource(frame._visible_models.__func__)
        assert "_ready_models" in source

    def test_ready_means_nothing_is_missing(self, frame):
        import inspect

        source = inspect.getsource(frame._ready_models.__func__)
        assert "engine_packages_missing" in source
        assert "is_downloaded" in source
        assert "_cloud_models" in source, "a cloud model with a key is ready too"

    def test_downloading_uses_the_same_calls_a_run_does(self, frame):
        """Otherwise Download and Start could disagree about "downloaded".

        The work moved into `model_download.ModelDownloadDialog` so it could
        report both of its phases; the rule it has to keep did not move.
        """
        import inspect

        from podharvest.model_download import ModelDownloadDialog

        source = inspect.getsource(ModelDownloadDialog._run)
        assert "ensure_engine_packages" in source
        assert "acquire_asr_model" in source

    def test_both_phases_of_a_download_are_reported(self, frame):
        """The silence in phase one is what made this look like a dead button.

        Setting up the engine's Python packages produces no percentage and
        can take minutes. Naming the step is the only thing standing between
        that and "nothing is happening".
        """
        import inspect

        from podharvest.model_download import ModelDownloadDialog

        source = inspect.getsource(ModelDownloadDialog._run)
        assert "Step 1 of 2" in source
        assert "Step 2 of 2" in source
        assert "progress=" in source, (
            "ensure_engine_packages takes a progress callback and the window "
            "must pass one, or phase one reports nothing")

    def test_downloading_leaves_the_run_gauge_alone(self, frame):
        """The main window's gauge is for runs. A download is not a run."""
        import inspect

        source = inspect.getsource(frame._on_download_model.__func__)
        assert "ModelDownloadDialog" in source
        for borrowed in ("self.progress.SetValue", "_set_columns",
                         "_reset_progress"):
            assert borrowed not in source, (
                f"the download must not touch {borrowed}")


class TestTheModelSourceFilter:
    """Which models the picker offers, and which filters are worth offering.

    An option that is present but cannot work is worse than one that is
    absent: by keyboard it is a stop that accepts your selection and then
    shows an empty list, with nothing saying why. So each option is switched
    on or off on its own terms.
    """

    @pytest.fixture
    def frame(self, wx_app, tmp_path):
        from podharvest import gui
        from podharvest.appspace import AppSpace

        window = gui.MainFrame()
        window.app_space = AppSpace(tmp_path).ensure()
        window.chk_transcribe.SetValue(True)
        yield window
        window._alive = False
        if getattr(window, "_tray", None) is not None:
            try:
                window._tray.Destroy()
            except Exception:
                pass
        window.Destroy()

    def _model(self, engine="faster-whisper", model="tiny.en"):
        from podharvest.hardware import ModelChoice

        return ModelChoice(engine=engine, model=model, min_ram_gb=1.0,
                           label=f"{engine} {model}")

    def test_the_picker_offers_only_what_can_run(self, frame, monkeypatch):
        """The heart of the redesign.

        Offering a model that then refuses to run means explaining the
        refusal every time. The main window offers what is ready; Set up
        models is where everything else lives, with a word on each saying
        what it needs.
        """
        ready = self._model(model="tiny.en")
        not_ready = self._model(model="large-v3")
        frame._local_models = [ready, not_ready]
        frame._cloud_models = []
        monkeypatch.setattr(acquire, "engine_packages_missing",
                            lambda _app, _engine: [])
        monkeypatch.setattr(acquire, "is_downloaded",
                            lambda _app, choice: choice.model == "tiny.en")
        assert frame._visible_models() == [ready]

    def test_a_cloud_model_with_a_key_counts_as_ready(self, frame, monkeypatch):
        """There is nothing to download for one, so waiting would be absurd."""
        cloud = self._model(engine="openai", model="whisper-1")
        frame._local_models = []
        frame._cloud_models = [cloud]
        monkeypatch.setattr(acquire, "is_downloaded", lambda _a, _c: False)
        assert frame._ready_models() == [cloud]

    def test_nothing_ready_is_an_honest_empty_list(self, frame, monkeypatch):
        """And the window says so rather than offering something that fails."""
        frame._local_models = [self._model()]
        frame._cloud_models = []
        monkeypatch.setattr(acquire, "is_downloaded", lambda _a, _c: False)
        assert frame._ready_models() == []
        frame._populate_models()
        assert frame.model_info.GetValue().startswith("No model is ready")
        assert "Set up models" in frame.model_ready.GetLabel()

    def test_the_setup_button_carries_the_count(self, frame, monkeypatch):
        """A button's label is what a screen reader reads on arrival."""
        monkeypatch.setattr(acquire, "engine_packages_missing",
                            lambda _app, _engine: [])
        monkeypatch.setattr(acquire, "is_downloaded", lambda _a, _c: True)
        frame._local_models = [self._model(), self._model(model="base.en")]
        frame._cloud_models = []
        frame._refresh_source_options()
        assert "2 ready" in frame.setup_btn.GetLabel()

    def test_the_setup_button_says_nothing_is_ready_when_nothing_is(
            self, frame, monkeypatch):
        monkeypatch.setattr(acquire, "is_downloaded", lambda _a, _c: False)
        frame._local_models = [self._model()]
        frame._cloud_models = []
        frame._refresh_source_options()
        assert "ready" not in frame.setup_btn.GetLabel()
        assert "No model can run yet" in frame.setup_btn.GetToolTip().GetTip()

    def test_an_unreadable_manifest_reads_as_not_ready(self, frame, monkeypatch):
        def explode(_app, _choice):
            raise OSError("manifest is gibberish")

        frame._local_models = [self._model()]
        frame._cloud_models = []
        monkeypatch.setattr(acquire, "is_downloaded", explode)
        assert frame._ready_models() == []

    def test_cloud_models_are_never_called_downloaded(self, frame, monkeypatch):
        """There is nothing to download for them, so the word would mislead."""
        frame._local_models = []
        frame._cloud_models = [self._model(engine="openai", model="whisper-1")]
        monkeypatch.setattr(acquire, "is_downloaded", lambda _a, _c: True)
        assert frame._downloaded_models() == []

    def test_an_unreadable_manifest_reads_as_not_downloaded(self, frame, monkeypatch):
        def explode(_app, _choice):
            raise OSError("manifest is gibberish")

        frame._local_models = [self._model()]
        monkeypatch.setattr(acquire, "is_downloaded", explode)
        assert frame._downloaded_models() == []


class TestDoctorTellsProblemsFromNormality:
    """Not downloaded is not the same as broken.

    Every engine you did not choose is undownloaded -- that is the normal
    state of a healthy install. Counting those as problems had `doctor`
    reporting "6 problem(s) found" and exiting 1 on a machine where everything
    worked, which is exactly the sort of false alarm that teaches people to
    ignore the tool.
    """

    def _source(self):
        from podharvest import cli

        return inspect.getsource(cli._cmd_doctor)

    def test_the_two_are_counted_separately(self):
        source = self._source()
        assert "broken = 0" in source and "absent = 0" in source

    def test_only_a_thing_that_will_not_load_fails_the_command(self):
        source = self._source()
        # The non-zero exit lives under the broken branch, not the absent one.
        assert "if broken:" in source
        assert source.index("if broken:") < source.index("return 1")
        assert source.index("if absent:") < source.index("if broken:")

    def test_undownloaded_packages_are_described_as_normal(self):
        source = self._source()
        assert "That is normal" in source

    def test_the_all_clear_does_not_claim_everything_is_downloaded(self):
        """"No problems found" would be a lie next to four undownloaded ones."""
        source = self._source()
        assert "Nothing is broken." in source
        assert "No problems found" not in source


class TestWhereEachKindOfModelLives:
    """One answer to "where is this model", for every kind of model.

    `acquire_enrichment_model` writes to `models/enrichment/`, but `_model_dir`
    only knew about engines and answered `models/llama-cpp/`. So
    `is_downloaded()` said no about every enrichment model that had in fact
    been downloaded -- permanently, no matter how many times you fetched it.
    Nothing asked that question yet, which is the only reason it had not
    surfaced. It was a bug waiting for a caller.
    """

    def _app(self, tmp_path):
        from podharvest.appspace import AppSpace

        return AppSpace(tmp_path).ensure()

    def _enrichment(self):
        from podharvest.hardware import ENRICHMENT_CHOICES

        return ENRICHMENT_CHOICES[0]

    def test_an_enrichment_model_is_found_where_it_is_written(self, tmp_path):
        from podharvest import acquire

        app = self._app(tmp_path)
        choice = self._enrichment()
        assert acquire._model_dir(app, choice) == (
            app.models_dir / "enrichment" / choice.model)

    def test_the_writer_and_the_reader_agree(self, tmp_path):
        """They used to disagree, which is the whole failure."""
        import inspect

        from podharvest import acquire

        source = inspect.getsource(acquire.acquire_enrichment_model)
        assert "_model_dir(app, choice)" in source
        assert 'models_dir / "enrichment"' not in source, (
            "the path is spelled once, in _model_dir")

    def test_is_downloaded_can_say_yes_about_an_enrichment_model(self, tmp_path):
        from podharvest import acquire

        app = self._app(tmp_path)
        choice = self._enrichment()
        model_dir = acquire._model_dir(app, choice)
        model_dir.mkdir(parents=True)
        # A plausible GGUF: the magic bytes, and big enough to pass the floor.
        weights = model_dir / choice.filename
        weights.write_bytes(acquire.GGUF_MAGIC + b"\0" * 4096)
        acquire._write_manifest(model_dir, choice, [choice.filename])
        assert acquire.is_downloaded(app, choice) is True

    def test_every_asr_engine_still_lands_where_it_did(self, tmp_path):
        from podharvest import acquire
        from podharvest.hardware import ASR_CATALOGUE

        app = self._app(tmp_path)
        expected = {
            "faster-whisper": app.whisper_models_dir,
            "parakeet": app.parakeet_models_dir,
            "nemo-canary": app.parakeet_models_dir,
            "parakeet-onnx": app.parakeet_models_dir / "onnx",
            "vosk": app.models_dir / "vosk",
            "moonshine": app.models_dir / "moonshine",
        }
        for engine, choices in ASR_CATALOGUE.items():
            for choice in choices:
                assert acquire._model_dir(app, choice) == (
                    expected[engine] / choice.model), engine

    def test_no_two_models_share_a_folder(self, tmp_path):
        """A shared folder would have one model verifying against another."""
        from podharvest import acquire
        from podharvest.hardware import ASR_CATALOGUE, ENRICHMENT_CHOICES

        app = self._app(tmp_path)
        everything = [c for choices in ASR_CATALOGUE.values() for c in choices]
        everything += list(ENRICHMENT_CHOICES)
        dirs = [acquire._model_dir(app, c) for c in everything]
        assert len(dirs) == len(set(dirs))


class TestOneModelStoreForEveryEngine:
    """acquire and the engines must agree about where models live.

    They did not, for four of six engines, and the symptoms were expensive:
    a model fetched with the Download button was downloaded a second time on
    first use (faster-whisper, NeMo), a model the engine had fetched read as
    "not downloaded" in the window forever, and for Moonshine the button
    downloaded the *PyTorch* weights -- a hundred megabytes of perfectly
    verified files the ONNX engine could never open. Every engine now loads
    through `acquire_asr_model`, the way Vosk always did.
    """

    def test_every_local_engine_loads_through_acquire(self):
        import inspect

        from podharvest import transcribe

        for engine_class in (transcribe.FasterWhisperEngine,
                             transcribe.ParakeetEngine,
                             transcribe.MoonshineEngine,
                             transcribe.VoskEngine):
            source = inspect.getsource(engine_class._load)
            assert "acquire_asr_model" in source, engine_class.__name__

    def test_whisper_loads_the_directory_not_the_name(self):
        """Loading by name asked faster-whisper's own registry, which knows a
        different cache layout and re-downloads. Loading the directory also
        frees the catalogue to offer converted models the registry has never
        heard of."""
        import inspect

        from podharvest.transcribe import FasterWhisperEngine

        source = inspect.getsource(FasterWhisperEngine._load)
        assert "str(acquired.model_dir)" in source
        # The code, not the comment explaining why the old way was wrong.
        code = "\n".join(line for line in source.splitlines()
                         if not line.strip().startswith("#"))
        assert "download_root" not in code

    def test_nemo_restores_the_local_checkpoint_when_there_is_one(self):
        import inspect

        from podharvest.transcribe import ParakeetEngine

        source = inspect.getsource(ParakeetEngine._load)
        assert "restore_from" in source
        assert '.glob("*.nemo")' in source
        assert "from_pretrained" in source, "still the fallback for no .nemo"

    def test_moonshine_downloads_the_onnx_repo_not_the_weights_repo(self):
        import inspect

        from podharvest import acquire

        source = inspect.getsource(acquire.acquire_asr_model)
        assert "MOONSHINE_ONNX_REPO" in source
        assert acquire.MOONSHINE_ONNX_REPO == "UsefulSensors/moonshine"

    def test_moonshine_paths_are_the_repos_own_nesting(self):
        from pathlib import Path

        from podharvest import acquire

        assert acquire.moonshine_variant("moonshine-tiny") == "tiny"
        assert acquire.moonshine_variant("moonshine-base") == "base"
        nested = acquire.moonshine_onnx_dir(Path("m"), "moonshine-tiny")
        assert nested == Path("m") / "onnx" / "merged" / "tiny" / "float"

    def test_moonshine_verification_wants_the_files_the_engine_opens(self, tmp_path):
        from podharvest import acquire
        from podharvest.hardware import MOONSHINE_CHOICES

        choice = next(c for c in MOONSHINE_CHOICES if c.model == "moonshine-tiny")
        model_dir = tmp_path / "moonshine-tiny"
        nested = acquire.moonshine_onnx_dir(model_dir, choice.model)
        nested.mkdir(parents=True)
        ok, reason = acquire.verify_model(model_dir, choice)
        assert not ok and "encoder_model.onnx" in reason
        (nested / "encoder_model.onnx").write_bytes(b"\0" * 4096)
        (nested / "decoder_model_merged.onnx").write_bytes(b"\0" * 4096)
        assert acquire.verify_model(model_dir, choice) == (True, "ok")


class TestFfmpegSurvivesAWingetUpgrade:
    """winget names its install folder after the version and writes that path
    into PATH. On upgrade the folder is replaced but open shells keep the old
    PATH, `shutil.which` fails, and every FFmpeg feature silently degrades.
    This happened on the development machine mid-session -- FFmpeg 9.0 became
    9.0.1 and podHarvest lost it without podHarvest changing at all.
    """

    def _plant(self, tmp_path, version: str):
        exe = (tmp_path / "Microsoft" / "WinGet" / "Packages"
               / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
               / f"ffmpeg-{version}-full_build" / "bin" / "ffmpeg.exe")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
        return exe

    def test_the_package_folder_is_found_when_path_is_stale(self, tmp_path,
                                                            monkeypatch):
        from podharvest import hardware

        planted = self._plant(tmp_path, "9.0.1")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.delenv("PODHARVEST_FFMPEG", raising=False)
        monkeypatch.setattr(hardware.shutil, "which", lambda _n: None)
        assert hardware.find_ffmpeg() == str(planted)

    def test_the_newest_version_wins(self, tmp_path, monkeypatch):
        from podharvest import hardware

        self._plant(tmp_path, "9.0")
        newest = self._plant(tmp_path, "9.0.1")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setattr(hardware.shutil, "which", lambda _n: None)
        assert hardware._winget_ffmpeg() == str(newest)

    def test_path_still_wins_when_it_works(self, monkeypatch, tmp_path):
        """The fallback is a rescue, not a preference."""
        from podharvest import hardware

        monkeypatch.delenv("PODHARVEST_FFMPEG", raising=False)
        monkeypatch.setattr(hardware.shutil, "which",
                            lambda _n: r"C:\on\path\ffmpeg.exe")
        assert hardware.find_ffmpeg() == r"C:\on\path\ffmpeg.exe"

    def test_no_winget_folder_is_quietly_nothing(self, tmp_path, monkeypatch):
        from podharvest import hardware

        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert hardware._winget_ffmpeg() == ""


class TestSherpaInt8Filenames:
    """The v3 Parakeet export is int8-quantised and names its files so.

    The loader and the verifier both have to accept either spelling, or the
    Download button fetches files the readiness line then calls missing --
    the exact wiring bug the September review fixed everywhere else.
    """

    def _choice(self):
        from podharvest.hardware import PARAKEET_ONNX_CHOICES

        by_name = {c.model: c for c in PARAKEET_ONNX_CHOICES}
        return by_name["parakeet-tdt-0.6b-v3"]

    def test_the_catalogue_carries_v3(self):
        choice = self._choice()
        assert "int8" in choice.source
        assert not choice.requires_cuda, "the whole point is plain CPU"

    def test_verify_accepts_int8_names(self, tmp_path):
        from podharvest import acquire

        for name in ("encoder.int8.onnx", "decoder.int8.onnx",
                     "joiner.int8.onnx", "tokens.txt"):
            (tmp_path / name).write_bytes(b"x" * 4096)
        ok, reason = acquire.verify_model(tmp_path, self._choice())
        assert ok, reason

    def test_verify_still_accepts_plain_names(self, tmp_path):
        from podharvest import acquire
        from podharvest.hardware import PARAKEET_ONNX_CHOICES

        v2 = {c.model: c for c in PARAKEET_ONNX_CHOICES}["parakeet-tdt-0.6b-v2"]
        for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx",
                     "tokens.txt"):
            (tmp_path / name).write_bytes(b"x" * 4096)
        ok, reason = acquire.verify_model(tmp_path, v2)
        assert ok, reason

    def test_a_missing_component_is_still_missing(self, tmp_path):
        from podharvest import acquire

        for name in ("encoder.int8.onnx", "tokens.txt"):
            (tmp_path / name).write_bytes(b"x" * 4096)
        ok, reason = acquire.verify_model(tmp_path, self._choice())
        assert not ok
        assert "decoder" in reason

    def test_the_engine_resolves_either_spelling(self, tmp_path):
        from podharvest.transcribe import SherpaOnnxParakeetEngine

        (tmp_path / "encoder.onnx").write_bytes(b"x")
        assert SherpaOnnxParakeetEngine._component(
            tmp_path, "encoder").name == "encoder.onnx"
        assert SherpaOnnxParakeetEngine._component(
            tmp_path, "decoder").name == "decoder.int8.onnx"

    def test_the_download_skips_the_test_wavs(self):
        """The repo carries smoke-test audio; users' disks do not need it."""
        import inspect

        from podharvest import acquire

        source = inspect.getsource(acquire.acquire_asr_model)
        assert '"*.onnx"' in source
