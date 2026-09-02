"""wxPython desktop front-end for podharvest.

Accessibility notes, stated precisely because overstating them helps nobody:

- Controls get their accessible name from a preceding `wx.StaticText`, which
  is how Win32 names an edit field. `wx.Window.SetName()` does *not* set an
  accessible name on any platform, so controls that have no adjacent label
  (the gauge, the spin controls, the model choice) get one from the
  `_Named` helper below, which implements `wx.Accessible`.
- Every action is reachable from the keyboard through the accelerator table
  built in `_build_accelerators`. Those are used in preference to `&`
  mnemonics because mnemonics are matched case-insensitively (so `&Start`
  and `&speakers` collide) and, more importantly, because `IsDialogMessage`
  scopes its mnemonic search to the enclosing `wx.StaticBox`, which means a
  mnemonic is unreachable from a field in a different box.
- Related controls are grouped in `wx.StaticBox` regions, which do expose a
  proper grouping role with a name.
- No colours, fonts or custom drawing are set anywhere, so high-contrast
  themes, focus rings and text scaling all behave natively.

Known gap: there is no live region. wxWidgets exposes no live-region API on
any platform, so the activity log does not auto-announce. Progress and
milestones are therefore also written to the log as text and reflected in
the window title, both of which a screen reader can be asked to read.

The GUI never touches the network or filesystem directly - it always calls
into the same `podharvest.harvest.run_harvest` pipeline the CLI uses, on a
background thread, and reports progress via the standard logging module.
"""

from __future__ import annotations

import logging
import threading

from podharvest import __version__
from podharvest import appspace as appspace_mod
from podharvest import config as config_mod
from podharvest import hardware as hardware_mod
from podharvest.util import LOG

try:
    import wx
except ImportError:  # pragma: no cover - surfaced to the caller
    raise


class _Named(wx.Accessible):
    """Gives a control a real accessible name.

    `wx.Window.SetName()` only sets the internal `FindWindowByName` key; it
    reaches neither MSAA/UIA, AT-SPI nor NSAccessibility. Controls that have
    no adjacent `wx.StaticText` to borrow a name from need this instead.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def GetName(self, childId):  # noqa: N802 - wx API casing
        return (wx.ACC_OK, self._name)


def set_accessible_name(ctrl: wx.Window, name: str) -> None:
    """Attach an accessible name to `ctrl` and keep it alive.

    `SetAccessible` does not take ownership, so the helper is stashed on the
    control; without that reference it is garbage collected and the name
    silently disappears.
    """
    ctrl.SetName(name)                  # still useful for FindWindowByName
    try:
        helper = _Named(name)
        ctrl.SetAccessible(helper)
        ctrl._a11y_helper = helper      # noqa: SLF001 - keep a strong reference
    except (AttributeError, NotImplementedError):
        # wx.Accessible is Windows-only; elsewhere the label heuristic and
        # the platform's own defaults apply.
        pass


class _LogToTextCtrl(logging.Handler):
    """Forwards log records to a wx.TextCtrl safely from any thread."""

    def __init__(self, ctrl: wx.TextCtrl) -> None:
        super().__init__()
        self.ctrl = ctrl
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        wx.CallAfter(self._append, msg)

    def _append(self, msg: str) -> None:
        if not self.ctrl:
            return
        # Reading the log is the only way to follow a run, so don't yank the
        # caret to the end while the user is reviewing earlier lines. Only
        # auto-scroll when they are already at the bottom.
        at_end = self.ctrl.GetInsertionPoint() >= self.ctrl.GetLastPosition()
        if at_end:
            self.ctrl.AppendText(msg)
        else:
            pos = self.ctrl.GetInsertionPoint()
            self.ctrl.Freeze()
            self.ctrl.SetInsertionPointEnd()
            self.ctrl.WriteText(msg)
            self.ctrl.SetInsertionPoint(pos)
            self.ctrl.Thaw()


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title=f"podharvest {__version__}", size=(880, 720))
        self.app_space = appspace_mod.resolve()
        self.app_space.activate()
        self.settings = config_mod.load(self.app_space)
        self._worker: threading.Thread | None = None
        self._cancel_event = threading.Event()

        self._alive = True

        self._build_menubar()
        self._build_ui()
        self._build_accelerators()
        self._apply_settings()
        self._wire_logging()
        self.CreateStatusBar()
        self.SetStatusText("Ready.")
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.refresh_hardware()

    # -- thread-safe UI updates -------------------------------------------

    def _ui(self, func, *args) -> None:
        """Run `func(*args)` on the UI thread, unless the frame is gone.

        Worker threads outlive the frame when the window is closed mid-run,
        and touching a destroyed wx object raises RuntimeError.
        """
        def _call():
            if self._alive:
                try:
                    func(*args)
                except RuntimeError:
                    pass      # the frame went away between the check and the call
        wx.CallAfter(_call)

    # -- menus and accelerators -------------------------------------------

    def _build_menubar(self) -> None:
        """A menu bar is the standard way to explore an unfamiliar app with a
        screen reader; without one there is no Alt/F10 entry point at all."""
        bar = wx.MenuBar()

        file_menu = wx.Menu()
        self._menu_start = file_menu.Append(wx.ID_ANY, "&Start harvest\tCtrl+R",
                                            "Begin harvesting the feed")
        self._menu_cancel = file_menu.Append(wx.ID_ANY, "&Cancel harvest\tEsc",
                                             "Stop the harvest in progress")
        self._menu_cancel.Enable(False)
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Close podharvest")
        bar.Append(file_menu, "&File")

        view_menu = wx.Menu()
        self._menu_focus_log = view_menu.Append(wx.ID_ANY, "Go to activity &log\tCtrl+L",
                                                "Move focus to the activity log")
        self._menu_redetect = view_menu.Append(wx.ID_ANY, "&Re-detect hardware\tCtrl+D",
                                               "Probe the hardware again")
        bar.Append(view_menu, "&View")

        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, "&About podharvest", "Version and project information")
        bar.Append(help_menu, "&Help")

        self.SetMenuBar(bar)
        self.Bind(wx.EVT_MENU, self._on_start, self._menu_start)
        self.Bind(wx.EVT_MENU, self._on_cancel, self._menu_cancel)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_focus_log, self._menu_focus_log)
        self.Bind(wx.EVT_MENU, lambda evt: self.refresh_hardware(force=True), self._menu_redetect)
        self.Bind(wx.EVT_MENU, self._on_about, id=wx.ID_ABOUT)

    def _build_accelerators(self) -> None:
        """Frame-level shortcuts.

        These are dispatched by the frame, so unlike `&` mnemonics they work
        from anywhere in the window regardless of which StaticBox holds focus.
        """
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord("R"), self._menu_start.GetId()),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self._menu_cancel.GetId()),
            (wx.ACCEL_CTRL, ord("L"), self._menu_focus_log.GetId()),
            (wx.ACCEL_CTRL, ord("D"), self._menu_redetect.GetId()),
        ]))

    def _on_focus_log(self, _evt) -> None:
        self.log_ctrl.SetFocus()

    def _on_about(self, _evt) -> None:
        from podharvest import HOMEPAGE
        wx.MessageBox(
            f"podharvest {__version__}\n\n"
            "Archive any RSS/Atom/podcast feed as Markdown, HTML, plain text and "
            "JSON, download every enclosure, and transcribe the audio on this "
            "machine.\n\n"
            f"{HOMEPAGE}\n\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+R  Start harvest\n"
            "  Esc     Cancel harvest\n"
            "  Ctrl+L  Go to activity log\n"
            "  Ctrl+D  Re-detect hardware",
            "About podharvest", wx.OK | wx.ICON_INFORMATION, self)

    # -- UI construction -----------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(self._build_feed_box(panel), 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self._build_options_box(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self._build_hardware_box(panel), 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self._build_action_row(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        log_label = wx.StaticText(panel, label="Activity log:")
        outer.Add(log_label, 0, wx.LEFT | wx.RIGHT, 10)
        self.log_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        set_accessible_name(self.log_ctrl, "Activity log")
        outer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        self.progress = wx.Gauge(panel, range=100)
        set_accessible_name(self.progress, "Overall progress")
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(outer)

    def _build_feed_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Feed")
        holder = box.GetStaticBox()
        grid = wx.FlexGridSizer(2, 3, 8, 8)
        grid.AddGrowableCol(1, 1)

        url_label = wx.StaticText(holder, label="Feed &URL:")
        self.url_ctrl = wx.TextCtrl(holder, value="")
        set_accessible_name(self.url_ctrl, "Feed URL")
        # The tooltip belongs on the control, not the label: a StaticText never
        # takes focus, so a keyboard user would never encounter it there.
        self.url_ctrl.SetToolTip("The RSS or Atom feed to harvest. A podcast's web "
                                 "page usually works too - its feed is discovered "
                                 "automatically.")
        self.url_ctrl.SetHint("https://example.com/feed")
        grid.Add(url_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.url_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(holder, label=""))

        out_label = wx.StaticText(holder, label="&Output folder:")
        self.output_ctrl = wx.TextCtrl(holder, value=str(self.app_space.default_output_dir))
        set_accessible_name(self.output_ctrl, "Output folder")
        browse = wx.Button(holder, label="B&rowse...")
        browse.Bind(wx.EVT_BUTTON, self._on_browse_output)
        grid.Add(out_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.output_ctrl, 1, wx.EXPAND)
        grid.Add(browse, 0)

        box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        return box

    def _build_options_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.HORIZONTAL, panel, "Options")
        holder = box.GetStaticBox()

        left = wx.BoxSizer(wx.VERTICAL)
        self.chk_download = wx.CheckBox(holder, label="&Download enclosures (audio/video/etc.)")
        self.chk_download.SetValue(True)
        self.chk_transcribe = wx.CheckBox(holder, label="&Transcribe downloaded audio on-device")
        self.chk_transcribe.Bind(wx.EVT_CHECKBOX, self._on_toggle_transcribe)
        limit_row = wx.BoxSizer(wx.HORIZONTAL)
        limit_row.Add(wx.StaticText(holder, label="Limit episodes (0 = all):"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.limit_ctrl = wx.SpinCtrl(holder, min=0, max=100000, initial=0)
        set_accessible_name(self.limit_ctrl, "Episode limit")
        limit_row.Add(self.limit_ctrl, 0)
        left.Add(self.chk_download, 0, wx.BOTTOM, 6)
        left.Add(self.chk_transcribe, 0, wx.BOTTOM, 6)
        left.Add(limit_row, 0)

        right_box = wx.StaticBoxSizer(wx.VERTICAL, holder, "Transcript options")
        right_holder = right_box.GetStaticBox()
        self.model_choice = wx.Choice(right_holder)
        set_accessible_name(self.model_choice, "Transcription model")
        self.chk_timestamps = wx.CheckBox(right_holder, label="&Include timestamps")
        self.chk_timestamps.SetValue(True)
        self.chk_timestamps.Bind(wx.EVT_CHECKBOX, self._on_toggle_timestamp_style)
        self.chk_speakers = wx.CheckBox(right_holder, label="Identify spea&kers (diarization)")
        self.chk_speakers.Bind(wx.EVT_CHECKBOX, self._on_toggle_speaker_style)

        ts_row = wx.BoxSizer(wx.HORIZONTAL)
        ts_row.Add(wx.StaticText(right_holder, label="Timestamp style:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.timestamp_style_choice = wx.Choice(right_holder, choices=["[00:00:00] bracket", "(00:00:00) paren"])
        set_accessible_name(self.timestamp_style_choice, "Timestamp style")
        self.timestamp_style_choice.SetSelection(0)
        ts_row.Add(self.timestamp_style_choice, 1)

        sp_row = wx.BoxSizer(wx.HORIZONTAL)
        sp_row.Add(wx.StaticText(right_holder, label="Speaker label style:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.speaker_style_choice = wx.Choice(
            right_holder, choices=["**Speaker:** bold", "Speaker: plain", "(Speaker) inline"])
        set_accessible_name(self.speaker_style_choice, "Speaker label style")
        self.speaker_style_choice.SetSelection(0)
        sp_row.Add(self.speaker_style_choice, 1)

        self.chk_paragraphs = wx.CheckBox(right_holder, label="Group into &paragraphs (merge same-speaker lines)")

        width_row = wx.BoxSizer(wx.HORIZONTAL)
        width_row.Add(wx.StaticText(right_holder, label="Wrap plain text at (0 = no wrap):"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.line_width_ctrl = wx.SpinCtrl(right_holder, min=0, max=400, initial=0)
        set_accessible_name(self.line_width_ctrl, "Plain text line width")
        width_row.Add(self.line_width_ctrl, 0)

        right_box.Add(wx.StaticText(right_holder, label="Model:"), 0, wx.BOTTOM, 2)
        right_box.Add(self.model_choice, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(self.chk_timestamps, 0, wx.BOTTOM, 4)
        right_box.Add(ts_row, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(self.chk_speakers, 0, wx.BOTTOM, 4)
        right_box.Add(sp_row, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(self.chk_paragraphs, 0, wx.BOTTOM, 6)
        right_box.Add(width_row, 0, wx.EXPAND)

        box.Add(left, 1, wx.EXPAND | wx.ALL, 8)
        box.Add(right_box, 1, wx.EXPAND | wx.ALL, 8)
        self._transcript_controls = [
            self.model_choice, self.chk_timestamps, self.chk_speakers, self.timestamp_style_choice,
            self.speaker_style_choice, self.chk_paragraphs, self.line_width_ctrl,
        ]
        self._on_toggle_transcribe(None)
        return box

    def _build_hardware_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Hardware")
        holder = box.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.hw_text = wx.StaticText(holder, label="Probing hardware...")
        self._refresh_btn = refresh_btn = wx.Button(holder, label="R&e-detect")
        refresh_btn.Bind(wx.EVT_BUTTON, lambda evt: self.refresh_hardware(force=True))
        row.Add(self.hw_text, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(refresh_btn, 0)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        return box

    def _build_action_row(self, panel: wx.Panel) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn = wx.Button(panel, label="&Start")
        self.start_btn.Bind(wx.EVT_BUTTON, self._on_start)
        self.start_btn.Disable()  # re-enabled once the first hardware probe completes
        self.cancel_btn = wx.Button(panel, label="&Cancel")
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.cancel_btn.Disable()
        self.start_btn.SetDefault()
        self.SetDefaultItem(self.start_btn)
        row.Add(self.start_btn, 0, wx.RIGHT, 8)
        row.Add(self.cancel_btn, 0)
        return row

    def _apply_settings(self) -> None:
        s = self.settings
        self.url_ctrl.SetValue(s.last_feed_url or self.url_ctrl.GetValue())
        self.output_ctrl.SetValue(config_mod.resolved_output_dir(self.app_space, s))
        self.limit_ctrl.SetValue(s.episode_limit or 0)
        self.chk_download.SetValue(s.download_enclosures)
        self.chk_transcribe.SetValue(s.transcribe)
        self.chk_timestamps.SetValue(s.include_timestamps)
        self.chk_speakers.SetValue(s.identify_speakers)
        self.timestamp_style_choice.SetSelection(
            {"bracket": 0, "paren": 1}.get(s.transcript_timestamp_style, 0))
        self.speaker_style_choice.SetSelection(
            {"bold": 0, "plain": 1, "inline": 2}.get(s.transcript_speaker_style, 0))
        self.chk_paragraphs.SetValue(s.transcript_paragraph_mode)
        self.line_width_ctrl.SetValue(s.transcript_max_line_chars or 0)
        self._on_toggle_transcribe(None)
        self._on_toggle_timestamp_style(None)
        self._on_toggle_speaker_style(None)

    def _save_settings(self) -> None:
        s = self.settings
        s.last_feed_url = self.url_ctrl.GetValue().strip()
        s.output_dir = self.output_ctrl.GetValue().strip()
        s.episode_limit = self.limit_ctrl.GetValue() or None
        s.download_enclosures = self.chk_download.GetValue()
        s.transcribe = self.chk_transcribe.GetValue()
        s.include_timestamps = self.chk_timestamps.GetValue()
        s.identify_speakers = self.chk_speakers.GetValue()
        s.transcript_timestamp_style = ["bracket", "paren"][self.timestamp_style_choice.GetSelection()]
        s.transcript_speaker_style = ["bold", "plain", "inline"][self.speaker_style_choice.GetSelection()]
        s.transcript_paragraph_mode = self.chk_paragraphs.GetValue()
        s.transcript_max_line_chars = self.line_width_ctrl.GetValue() or None
        selection = self.model_choice.GetSelection()
        if selection != wx.NOT_FOUND:
            choice = self.model_choice.GetClientData(selection)
            s.asr_engine, s.asr_model = choice.engine, choice.model
        config_mod.save(self.app_space, s)

    def _wire_logging(self) -> None:
        handler = _LogToTextCtrl(self.log_ctrl)
        handler.setLevel(logging.INFO)
        LOG.addHandler(handler)
        self._log_handler = handler

    # -- behaviour --------------------------------------------------------

    def _set_enabled(self, ctrls, enabled: bool, fallback: wx.Window) -> None:
        """Enable/disable a group, rescuing focus if it is inside the group."""
        focused = wx.Window.FindFocus()
        for ctrl in ctrls:
            ctrl.Enable(enabled)
        if not enabled and focused in ctrls:
            fallback.SetFocus()

    def _on_toggle_transcribe(self, _evt) -> None:
        self._set_enabled(self._transcript_controls, self.chk_transcribe.GetValue(),
                          fallback=self.chk_transcribe)
        # The two style pickers have their own conditions on top of this one,
        # so re-apply them or they end up enabled while their parent is off.
        self._on_toggle_timestamp_style(None)
        self._on_toggle_speaker_style(None)

    def _on_toggle_timestamp_style(self, _evt) -> None:
        enabled = self.chk_transcribe.GetValue() and self.chk_timestamps.GetValue()
        self._set_enabled([self.timestamp_style_choice], enabled, fallback=self.chk_timestamps)

    def _on_toggle_speaker_style(self, _evt) -> None:
        enabled = self.chk_transcribe.GetValue() and self.chk_speakers.GetValue()
        self._set_enabled([self.speaker_style_choice], enabled, fallback=self.chk_speakers)

    def _on_browse_output(self, _evt) -> None:
        with wx.DirDialog(self, "Choose an output folder", defaultPath=self.output_ctrl.GetValue()) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.output_ctrl.SetValue(dlg.GetPath())

    def refresh_hardware(self, force: bool = False) -> None:
        self.hw_text.SetLabel("Detecting hardware, please wait...")
        self._refresh_btn.Disable()
        self.SetStatusText("Detecting hardware...")

        def work():
            try:
                hw = hardware_mod.probe(refresh=force)
            except Exception as exc:  # noqa: BLE001 - must never strand the UI
                LOG.exception("Hardware detection failed: %s", exc)
                self._ui(self._hardware_failed, exc)
                return
            self._ui(self._apply_hardware, hw)

        threading.Thread(target=work, daemon=True).start()

    def _hardware_failed(self, exc: Exception) -> None:
        """Degrade to download-and-convert rather than leaving Start dead.

        Transcription is the only thing that needs the hardware probe, so a
        failure here must not block the rest of the app.
        """
        message = (f"Hardware detection failed: {exc}. Transcription is unavailable, "
                   "but downloading and conversion still work.")
        self.hw_text.SetLabel(message)
        self._refresh_btn.Enable()
        self.chk_transcribe.SetValue(False)
        self.chk_transcribe.Disable()
        self._on_toggle_transcribe(None)
        self.start_btn.Enable()
        self.SetStatusText("Hardware detection failed - transcription disabled.")
        LOG.error("%s", message)

    def _apply_hardware(self, hw) -> None:
        gpu = hw.best_gpu
        gpu_desc = f"{gpu.name} ({gpu.vram_gb} GB)" if gpu else "none (CPU only)"
        self.hw_text.SetLabel(
            f"{hw.cpu_name}  |  {hw.ram_gb} GB RAM  |  GPU: {gpu_desc}  |  "
            f"backend: {hw.accelerator}  |  model budget: ~{hw.usable_accel_memory_gb} GB"
        )
        self.model_choice.Clear()
        for choice in hardware_mod.available_models(hw):
            self.model_choice.Append(str(choice), choice)
        saved = (self.settings.asr_engine, self.settings.asr_model)
        best = hardware_mod.recommend_model(hw)
        target_index = None
        for i in range(self.model_choice.GetCount()):
            choice = self.model_choice.GetClientData(i)
            if (choice.engine, choice.model) == saved and saved != ("", ""):
                target_index = i
                break
            if choice is best or choice.model == best.model:
                target_index = target_index if target_index is not None else i
        if target_index is None and self.model_choice.GetCount():
            target_index = 0
        if target_index is not None:
            self.model_choice.SetSelection(target_index)
        for note in hw.notes:
            LOG.info("Hardware note: %s", note)
        if not self._worker or not self._worker.is_alive():
            self.start_btn.Enable()
        self.GetTopLevelParent().Layout()

    def _on_start(self, _evt) -> None:
        url = self.url_ctrl.GetValue().strip()
        if not url:
            wx.MessageBox("Please enter a feed URL.", "Missing URL", wx.OK | wx.ICON_WARNING)
            self.url_ctrl.SetFocus()
            return

        model_choice = None
        if self.chk_transcribe.GetValue():
            selection = self.model_choice.GetSelection()
            if selection == wx.NOT_FOUND or not self.model_choice.GetCount():
                wx.MessageBox(
                    "Transcription is enabled but no model is selected yet.\n\n"
                    "Hardware detection may still be running, or it found no model that fits "
                    "this machine. Click \"Re-detect\" and wait for the hardware summary to "
                    "update, or uncheck \"Transcribe downloaded audio\" to continue without it.",
                    "No transcription model selected", wx.OK | wx.ICON_WARNING)
                self.model_choice.SetFocus()
                return
            model_choice = self.model_choice.GetClientData(selection)

        output_dir = self.output_ctrl.GetValue().strip() or str(self.app_space.default_output_dir)
        limit = self.limit_ctrl.GetValue() or None
        self._save_settings()

        self.log_ctrl.Clear()
        self.progress.SetValue(0)
        self.start_btn.Disable()
        self.cancel_btn.Enable()
        self.SetStatusText(f"Harvesting {url} ...")
        self._cancel_event.clear()

        self._worker = threading.Thread(
            target=self._run_harvest_worker,
            args=(url, output_dir, self.chk_download.GetValue(), self.chk_transcribe.GetValue(),
                  model_choice, self.chk_timestamps.GetValue(), self.chk_speakers.GetValue(), limit),
            daemon=True,
        )
        self._worker.start()

    def _run_harvest_worker(self, url, output_dir, download, transcribe, model_choice,
                             timestamps, speakers, limit) -> None:
        try:
            try:
                from podharvest.harvest import run_harvest
            except ImportError as exc:
                LOG.error("The fetch/render/download pipeline is not wired up yet in this workspace (%s).", exc)
                LOG.error("Hardware detection and this UI are functional; feed harvesting is still being assembled.")
                return
            run_harvest(
                url,
                app=self.app_space,
                output_dir=output_dir,
                download=download,
                transcribe=transcribe,
                model=model_choice,
                include_timestamps=timestamps,
                identify_speakers=speakers,
                limit=limit,
                cancel_event=self._cancel_event,
                progress_callback=lambda pct: wx.CallAfter(self.progress.SetValue, int(pct)),
            )
        except Exception as exc:  # noqa: BLE001 - surface everything to the log pane
            LOG.exception("Harvest failed: %s", exc)
        finally:
            wx.CallAfter(self._finish_worker)

    def _finish_worker(self) -> None:
        self.start_btn.Enable()
        self.cancel_btn.Disable()
        self.SetStatusText("Ready.")

    def _on_cancel(self, _evt) -> None:
        self._cancel_event.set()
        self.SetStatusText("Cancelling...")
        LOG.warning("Cancellation requested by user.")

    def _on_close(self, evt) -> None:
        self._cancel_event.set()
        self._save_settings()
        if self._log_handler in LOG.handlers:
            LOG.removeHandler(self._log_handler)
        evt.Skip()


def run_gui() -> int:
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
    return 0
