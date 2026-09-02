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
from podharvest.util import LOG, spoken_duration

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


class SettingsDialog(wx.Dialog):
    """The settings that are not part of setting up a single run.

    Everything here is checkbox-or-folder simple on purpose; the transcript
    options that change run to run stay on the main window where they are
    visible without opening anything.
    """

    def __init__(self, parent: wx.Window, app, settings) -> None:
        super().__init__(parent, title="Settings", style=wx.DEFAULT_DIALOG_STYLE)
        self.app = app
        self.settings = settings
        outer = wx.BoxSizer(wx.VERTICAL)

        # -- activity log ------------------------------------------------
        log_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Activity log")
        holder = log_box.GetStaticBox()
        self.chk_log_file = wx.CheckBox(holder, label="&Save a log file for every run")
        self.chk_log_file.SetValue(settings.log_to_file)
        self.chk_log_file.Bind(wx.EVT_CHECKBOX, self._on_toggle_log)
        log_box.Add(self.chk_log_file, 0, wx.ALL, 6)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(holder, label="Log &folder:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.log_dir_ctrl = wx.TextCtrl(
            holder, value=config_mod.resolved_log_dir(app, settings), size=(320, -1))
        set_accessible_name(self.log_dir_ctrl, "Log folder")
        browse = wx.Button(holder, label="Br&owse...")
        browse.Bind(wx.EVT_BUTTON, self._on_browse_log)
        row.Add(self.log_dir_ctrl, 1, wx.EXPAND | wx.RIGHT, 6)
        row.Add(browse, 0)
        log_box.Add(row, 0, wx.EXPAND | wx.ALL, 6)
        self.log_hint = wx.StaticText(
            holder, label="The log is written to podharvest.log in that folder.")
        log_box.Add(self.log_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        outer.Add(log_box, 0, wx.EXPAND | wx.ALL, 10)

        # -- summaries -----------------------------------------------------
        sum_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Episode summaries")
        sholder = sum_box.GetStaticBox()
        self.chk_summaries = wx.CheckBox(
            sholder, label="&Write a summary for each episode (slow: adds minutes per episode)")
        self.chk_summaries.SetValue(settings.enrichment_enabled)
        self.chk_summaries.Bind(wx.EVT_CHECKBOX, self._on_toggle_summaries)
        self.chk_full_episode = wx.CheckBox(
            sholder, label="Summarise the w&hole episode, not just the beginning")
        self.chk_full_episode.SetValue(settings.enrichment_full_episode)
        self.chk_full_episode.SetToolTip(
            "The summary model can only read about 24,000 characters at once, which is "
            "roughly half an hour-long episode. With this on, the transcript is summarised "
            "in sections and the sections are combined, so the summary covers all of it. "
            "That takes two to three times as long.")
        sum_box.Add(self.chk_summaries, 0, wx.ALL, 6)
        sum_box.Add(self.chk_full_episode, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Which model writes the summaries and chapter markers. The on-device
        # model is always offered; cloud entries appear only where a key exists.
        from podharvest import cloud as cloud_mod
        model_row = wx.BoxSizer(wx.HORIZONTAL)
        model_row.Add(wx.StaticText(sholder, label="Summaries written &by:"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.summary_model_choice = wx.Choice(sholder)
        set_accessible_name(self.summary_model_choice, "Model that writes summaries")
        self.summary_model_choice.Append("On this machine (nothing uploaded)", None)
        for entry in cloud_mod.available_cloud_models(app, kind="enrichment"):
            self.summary_model_choice.Append(str(entry), entry)
        selected = 0
        if settings.enrichment_provider:
            for i in range(1, self.summary_model_choice.GetCount()):
                entry = self.summary_model_choice.GetClientData(i)
                if entry and entry.provider == settings.enrichment_provider:
                    selected = i
                    break
        self.summary_model_choice.SetSelection(selected)
        self.summary_model_choice.SetToolTip(
            "The on-device model is private but slow - a couple of minutes an episode. "
            "A cloud model does the same work in a couple of seconds, but the transcript "
            "text is sent to that provider.")
        model_row.Add(self.summary_model_choice, 1, wx.EXPAND)
        sum_box.Add(model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        outer.Add(sum_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # -- subtitle files ------------------------------------------------
        sub_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Subtitle files")
        subholder = sub_box.GetStaticBox()
        sub_box.Add(wx.StaticText(
            subholder,
            label="Subtitle files always contain timestamps - that is what the format is.\n"
                  "\"Include timestamps\" on the main window applies to the transcript\n"
                  "itself (the .md and .txt files), not to these."),
            0, wx.ALL, 6)
        self.chk_srt = wx.CheckBox(subholder, label="Write a .s&rt subtitle file")
        self.chk_srt.SetValue(settings.write_srt)
        self.chk_vtt = wx.CheckBox(subholder, label="Write a .&vtt subtitle file")
        self.chk_vtt.SetValue(settings.write_vtt)
        sub_box.Add(self.chk_srt, 0, wx.LEFT | wx.RIGHT, 6)
        sub_box.Add(self.chk_vtt, 0, wx.ALL, 6)
        outer.Add(sub_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # -- cloud providers -----------------------------------------------
        outer.Add(self._build_keys_box(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # -- finishing -----------------------------------------------------
        fin_box = wx.StaticBoxSizer(wx.VERTICAL, self, "When a run finishes")
        fholder = fin_box.GetStaticBox()
        self.chk_finished_dialog = wx.CheckBox(
            fholder, label="Show a &dialog saying the run has finished")
        self.chk_finished_dialog.SetValue(settings.show_finished_dialog)
        fin_box.Add(self.chk_finished_dialog, 0, wx.ALL, 6)
        outer.Add(fin_box, 0, wx.EXPAND | wx.ALL, 10)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self._on_toggle_log(None)
        self._on_toggle_summaries(None)

    def _build_keys_box(self) -> wx.StaticBoxSizer:
        """One masked field per cloud provider.

        Keys are never written to settings.json - they go to the platform's
        encrypted store (see podharvest.keystore). A field showing a key that
        came from an environment variable is read-only, because saving over it
        would do nothing and silently pretending otherwise is worse than saying
        so.
        """
        from podharvest import cloud as cloud_mod
        from podharvest import keystore

        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Cloud provider API keys (optional)")
        holder = box.GetStaticBox()
        box.Add(wx.StaticText(
            holder,
            label="Leave these empty to keep everything on this machine. A key here lets you\n"
                  "pick that provider's models for transcription or summaries. Keys are stored\n"
                  "encrypted for your Windows account, never in the settings file."),
            0, wx.ALL, 6)

        self.key_fields: dict[str, wx.TextCtrl] = {}
        grid = wx.FlexGridSizer(len(cloud_mod.ALL_PROVIDERS), 2, 6, 8)
        grid.AddGrowableCol(1, 1)
        for name in cloud_mod.ALL_PROVIDERS:
            provider = cloud_mod.PROVIDERS[name]
            can = "transcripts and summaries" if provider.can_transcribe else "summaries only"
            label = wx.StaticText(holder, label=f"{provider.label} ({can}):")
            field = wx.TextCtrl(holder, style=wx.TE_PASSWORD, size=(300, -1))
            set_accessible_name(field, f"{provider.label} API key, {can}")

            env_name = keystore.env_var_for(name)
            import os
            if os.environ.get(env_name, "").strip():
                field.SetValue("(set by the environment variable " + env_name + ")")
                field.SetEditable(False)
                field.SetToolTip(f"This key comes from {env_name} and cannot be changed here. "
                                 "Unset that variable to manage it in this window.")
            else:
                existing = keystore.load_key(self.app, name)
                if existing:
                    # Never render the secret back into a field it could be
                    # read out of; show that one is set and let it be replaced.
                    field.SetValue("*" * 24)
                    field.SetToolTip(f"A key is saved. {provider.key_hint} "
                                     "Type a new one to replace it, or clear the field to "
                                     "remove it.")
                else:
                    field.SetHint("not set")
                    field.SetToolTip(f"{provider.key_hint} Get one at {provider.key_url}")
            self.key_fields[name] = field
            grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(field, 1, wx.EXPAND)
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return box

    def _save_keys(self) -> None:
        """Persist any key field the user actually changed."""
        from podharvest import keystore
        for name, field in self.key_fields.items():
            if not field.IsEditable():
                continue                      # environment variable owns it
            value = field.GetValue().strip()
            if set(value) == {"*"}:
                continue                      # untouched placeholder for a saved key
            keystore.save_key(self.app, name, value)

    def _on_toggle_log(self, _evt) -> None:
        on = self.chk_log_file.GetValue()
        self.log_dir_ctrl.Enable(on)

    def _on_toggle_summaries(self, _evt) -> None:
        on = self.chk_summaries.GetValue()
        self.chk_full_episode.Enable(on)
        self.summary_model_choice.Enable(on)

    def _on_browse_log(self, _evt) -> None:
        with wx.DirDialog(self, "Choose a folder for the log file",
                          defaultPath=self.log_dir_ctrl.GetValue()) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.log_dir_ctrl.SetValue(dlg.GetPath())

    def apply_to(self, settings) -> None:
        self._save_keys()
        settings.log_to_file = self.chk_log_file.GetValue()
        chosen = self.log_dir_ctrl.GetValue().strip()
        # Store "" when the folder is the built-in one, so the setting keeps
        # following the app directory if that ever moves.
        settings.log_dir = "" if chosen == str(self.app.logs_dir) else chosen
        settings.enrichment_enabled = self.chk_summaries.GetValue()
        settings.enrichment_full_episode = self.chk_full_episode.GetValue()
        picked = self.summary_model_choice.GetClientData(
            self.summary_model_choice.GetSelection())
        settings.enrichment_provider = picked.provider if picked else ""
        if picked:
            settings.enrichment_model = picked.model
        settings.write_srt = self.chk_srt.GetValue()
        settings.write_vtt = self.chk_vtt.GetValue()
        settings.show_finished_dialog = self.chk_finished_dialog.GetValue()


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title=f"podharvest {__version__}", size=(880, 720))
        self.app_space = appspace_mod.resolve()
        self.app_space.activate()
        self.settings = config_mod.load(self.app_space)
        self._worker: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._episode_rows: dict[int, int] = {}
        self._episode_percent: dict[int, tuple[str, int]] = {}
        self._counts: dict[str, int] = {}
        self._run_output_dir = ""
        self._run_failed: str | None = None
        self._cancel_mode = "cancel"
        self._file_log_handler: logging.Handler | None = None
        self._hw = None
        self._local_models: list = []
        self._cloud_models: list = []
        self._recommended = None
        #: Total audio the current feed is expected to hold, so the model
        #: description can say how long this run will actually take. Filled in
        #: once a feed has been read; a typical feed until then.
        self._estimated_audio_seconds = 0.0

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
        self._menu_settings = file_menu.Append(wx.ID_PREFERENCES, "Se&ttings...\tCtrl+,",
                                               "Log file location, summaries and subtitle files")
        self._menu_open_out = file_menu.Append(wx.ID_ANY, "Open &output folder\tCtrl+Shift+O",
                                               "Open the folder holding the results")
        self._menu_open_log = file_menu.Append(wx.ID_ANY, "Open log &folder",
                                               "Open the folder holding the saved log file")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Close podharvest")
        bar.Append(file_menu, "&File")

        view_menu = wx.Menu()
        self._menu_focus_episodes = view_menu.Append(wx.ID_ANY, "Go to &episode list\tCtrl+E",
                                                     "Move focus to the list of episodes")
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
        self.Bind(wx.EVT_MENU, self._on_settings, self._menu_settings)
        self.Bind(wx.EVT_MENU, lambda evt: self._open_folder(
            self._run_output_dir or self.output_ctrl.GetValue().strip()), self._menu_open_out)
        self.Bind(wx.EVT_MENU, lambda evt: self._open_folder(
            config_mod.resolved_log_dir(self.app_space, self.settings)), self._menu_open_log)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_focus_log, self._menu_focus_log)
        self.Bind(wx.EVT_MENU, lambda evt: self.episode_list.SetFocus(),
                  self._menu_focus_episodes)
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
            (wx.ACCEL_CTRL, ord(","), self._menu_settings.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("O"), self._menu_open_out.GetId()),
            (wx.ACCEL_CTRL, ord("E"), self._menu_focus_episodes.GetId()),
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
            "  Ctrl+R        Start harvest\n"
            "  Esc           Cancel harvest\n"
            "  Ctrl+E        Go to episode list\n"
            "  Ctrl+L        Go to activity log\n"
            "  Ctrl+D        Re-detect hardware\n"
            "  Ctrl+comma    Settings\n"
            "  Ctrl+Shift+O  Open output folder",
            "About podharvest", wx.OK | wx.ICON_INFORMATION, self)

    # -- UI construction -----------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(self._build_feed_box(panel), 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self._build_options_box(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self._build_hardware_box(panel), 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self._build_action_row(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # The episode list is the answer to "what is it doing right now?". It is
        # a real focusable list rather than a redrawn label, so it can be
        # reviewed row by row at any point in a run without waiting for an
        # announcement to happen to arrive.
        episodes_label = wx.StaticText(panel, label="&Episodes:")
        outer.Add(episodes_label, 0, wx.LEFT | wx.RIGHT, 10)
        self.episode_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.episode_list.AppendColumn("#", width=50)
        self.episode_list.AppendColumn("Episode", width=380)
        self.episode_list.AppendColumn("Status", width=150)
        self.episode_list.AppendColumn("Progress", width=90)
        self.episode_list.AppendColumn("Time", width=110)
        set_accessible_name(self.episode_list, "Episodes")
        self.episode_list.SetToolTip("Every episode in this run and how far along it is. "
                                     "Arrow up and down to review them at any time.")
        outer.Add(self.episode_list, 1, wx.EXPAND | wx.ALL, 10)

        log_label = wx.StaticText(panel, label="Activity log:")
        outer.Add(log_label, 0, wx.LEFT | wx.RIGHT, 10)
        self.log_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        set_accessible_name(self.log_ctrl, "Activity log")
        outer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # A text line beside the gauge: a wx.Gauge reports a bare number, which
        # says nothing about which episode is running or how much is left.
        self.progress_text = wx.StaticText(panel, label="Nothing running yet.")
        outer.Add(self.progress_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

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

        # Where models may come from. Disabled outright until a cloud provider
        # has a key: an enabled control that can only ever hold one value wastes
        # a stop in the tab order and invites the question "why can't I pick
        # cloud?" every single time.
        self.source_radio = wx.RadioBox(
            right_holder, label="Show models that run",
            choices=["&All", "On this &machine", "In the c&loud"],
            majorDimension=3, style=wx.RA_SPECIFY_COLS)
        set_accessible_name(self.source_radio, "Show models that run")
        self.source_radio.Bind(wx.EVT_RADIOBOX, self._on_source_changed)

        self.model_choice = wx.Choice(right_holder)
        set_accessible_name(self.model_choice, "Transcription model")
        self.model_choice.Bind(wx.EVT_CHOICE, self._on_model_changed)

        # Read-only and multi-line so it is a real tab stop that can be arrowed
        # through line by line. A tooltip cannot be read that way, and a
        # StaticText cannot take focus at all.
        self.model_info = wx.TextCtrl(
            right_holder, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            size=(-1, 150))
        set_accessible_name(self.model_info, "About the selected model")
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

        self.chk_chapters = wx.CheckBox(
            right_holder, label="Write chapter &markers with start and end times")
        self.chk_chapters.SetToolTip(
            "Works out where each topic starts and ends. Needs a model that produces "
            "timestamps, and adds a minute or two per episode.")
        self.chk_chapters.Bind(wx.EVT_CHECKBOX, self._on_toggle_chapters)
        self.chk_chapters_audio = wx.CheckBox(
            right_holder, label="Also add the chapters to the a&udio file")
        self.chk_chapters_audio.SetValue(True)
        self.chk_chapters_audio.SetToolTip(
            "Writes the chapters into the audio file itself, so a podcast player shows "
            "them as a list you can jump through. The audio is copied, not re-encoded, "
            "so nothing is lost and the file barely changes size.")
        self.chk_paragraphs = wx.CheckBox(right_holder, label="Group into &paragraphs (merge same-speaker lines)")

        width_row = wx.BoxSizer(wx.HORIZONTAL)
        width_row.Add(wx.StaticText(right_holder, label="Wrap plain text at (0 = no wrap):"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.line_width_ctrl = wx.SpinCtrl(right_holder, min=0, max=400, initial=0)
        set_accessible_name(self.line_width_ctrl, "Plain text line width")
        width_row.Add(self.line_width_ctrl, 0)

        right_box.Add(self.source_radio, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(wx.StaticText(right_holder, label="Model:"), 0, wx.BOTTOM, 2)
        right_box.Add(self.model_choice, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(wx.StaticText(right_holder, label="About this model:"), 0, wx.BOTTOM, 2)
        right_box.Add(self.model_info, 1, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(self.chk_chapters, 0, wx.BOTTOM, 4)
        right_box.Add(self.chk_chapters_audio, 0, wx.LEFT | wx.BOTTOM, 18)
        right_box.Add(self.chk_timestamps, 0, wx.BOTTOM, 4)
        right_box.Add(ts_row, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(self.chk_speakers, 0, wx.BOTTOM, 4)
        right_box.Add(sp_row, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(self.chk_paragraphs, 0, wx.BOTTOM, 6)
        right_box.Add(width_row, 0, wx.EXPAND)

        box.Add(left, 1, wx.EXPAND | wx.ALL, 8)
        box.Add(right_box, 1, wx.EXPAND | wx.ALL, 8)
        # The source picker is left out on purpose: whether it is usable depends
        # on having a cloud key, which _refresh_cloud_availability decides. Being
        # in this list would let the transcribe toggle switch it back on.
        self._transcript_controls = [
            self.model_choice, self.model_info, self.chk_timestamps, self.chk_speakers,
            self.timestamp_style_choice, self.speaker_style_choice, self.chk_paragraphs,
            self.chk_chapters, self.chk_chapters_audio, self.line_width_ctrl,
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
        self.chk_chapters.SetValue(s.write_chapters)
        self.chk_chapters_audio.SetValue(s.chapters_into_audio)
        if s.model_filter in self._SOURCES:
            self.source_radio.SetSelection(self._SOURCES.index(s.model_filter))
        self.line_width_ctrl.SetValue(s.transcript_max_line_chars or 0)
        self._on_toggle_transcribe(None)
        self._on_toggle_timestamp_style(None)
        self._on_toggle_speaker_style(None)
        self._on_toggle_chapters(None)

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
        s.write_chapters = self.chk_chapters.GetValue()
        s.chapters_into_audio = self.chk_chapters_audio.GetValue()
        s.model_filter = self._SOURCES[self.source_radio.GetSelection()]
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
        self._wire_file_logging()

    def _wire_file_logging(self) -> None:
        """Attach (or move, or remove) the on-disk log to match the settings."""
        if self._file_log_handler is not None:
            LOG.removeHandler(self._file_log_handler)
            self._file_log_handler.close()
            self._file_log_handler = None

        path = config_mod.resolved_log_file(self.app_space, self.settings)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
        except OSError as exc:
            LOG.error("Could not write the log file to %s (%s). The run still works; "
                      "only the saved copy of the log is missing.", path, exc)
            return
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        LOG.addHandler(handler)
        self._file_log_handler = handler
        LOG.info("Saving this log to %s", path)

    def _on_settings(self, _evt) -> None:
        with SettingsDialog(self, self.app_space, self.settings) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            dlg.apply_to(self.settings)
        config_mod.save(self.app_space, self.settings)
        self._wire_file_logging()
        # A key may have just been added or removed, which changes whether the
        # source picker is usable and which models the list can offer.
        was_available = bool(self._cloud_models)
        self._refresh_cloud_availability()
        if bool(self._cloud_models) != was_available:
            LOG.info("Cloud models are now %s.",
                     "available" if self._cloud_models else "unavailable")
        self._populate_models()
        LOG.info("Settings saved.")

    # -- behaviour --------------------------------------------------------

    def _set_enabled(self, ctrls, enabled: bool, fallback: wx.Window) -> None:
        """Enable/disable a group, rescuing focus if it is inside the group."""
        focused = wx.Window.FindFocus()
        for ctrl in ctrls:
            ctrl.Enable(enabled)
        if not enabled and focused in ctrls:
            fallback.SetFocus()

    def _on_toggle_transcribe(self, _evt) -> None:
        on = self.chk_transcribe.GetValue()
        self._set_enabled(self._transcript_controls, on, fallback=self.chk_transcribe)
        # The source picker is only usable when transcription is on *and* a
        # cloud key exists, so it is never simply re-enabled here.
        self._set_enabled([self.source_radio],
                          on and bool(getattr(self, "_cloud_models", [])),
                          fallback=self.chk_transcribe)
        # These have their own conditions on top of this one, so re-apply them
        # or they end up enabled while their parent is off.
        self._on_toggle_timestamp_style(None)
        self._on_toggle_speaker_style(None)
        self._on_toggle_chapters(None)

    def _on_toggle_chapters(self, _evt) -> None:
        self._set_enabled([self.chk_chapters_audio],
                          self.chk_transcribe.GetValue() and self.chk_chapters.GetValue(),
                          fallback=self.chk_chapters)

    def _on_toggle_timestamp_style(self, _evt) -> None:
        enabled = self.chk_transcribe.GetValue() and self.chk_timestamps.GetValue()
        self._set_enabled([self.timestamp_style_choice], enabled, fallback=self.chk_timestamps)

    def _on_toggle_speaker_style(self, _evt) -> None:
        enabled = self.chk_transcribe.GetValue() and self.chk_speakers.GetValue()
        self._set_enabled([self.speaker_style_choice], enabled, fallback=self.chk_speakers)

    # -- model picker -----------------------------------------------------

    _SOURCES = ("all", "local", "cloud")

    def _refresh_cloud_availability(self) -> None:
        """Enable the source picker only when a cloud model could actually run.

        Without a key there is exactly one possible answer, so the control is
        disabled rather than left as a dead stop in the tab order.
        """
        from podharvest import cloud as cloud_mod
        self._cloud_models = cloud_mod.available_cloud_models(self.app_space, kind="asr")
        available = bool(self._cloud_models)
        self.source_radio.Enable(available and self.chk_transcribe.GetValue())
        if not available:
            # Local is the only truthful answer, so say so rather than leaving
            # a stale "cloud" selection pointing at nothing.
            self.source_radio.SetSelection(self._SOURCES.index("local"))
            self.source_radio.SetToolTip(
                "Add an OpenAI or Google Gemini API key in Settings to use cloud models. "
                "Until then everything runs on this machine.")
        else:
            names = ", ".join(sorted({c.provider for c in self._cloud_models}))
            self.source_radio.SetToolTip(f"Cloud models are available for: {names}.")

    def _visible_models(self) -> list:
        source = self._SOURCES[self.source_radio.GetSelection()]
        local = list(self._local_models)
        cloud = list(getattr(self, "_cloud_models", []))
        if not cloud or not self.source_radio.IsEnabled():
            return local
        if source == "local":
            return local
        if source == "cloud":
            return cloud
        return local + cloud

    def _populate_models(self, prefer: tuple[str, str] | None = None) -> None:
        """Refill the model list for the current filter, keeping the selection."""
        wanted = prefer or self._selected_model_key()
        self.model_choice.Clear()
        models = self._visible_models()
        for choice in models:
            self.model_choice.Append(str(choice), choice)

        index = wx.NOT_FOUND
        for i, choice in enumerate(models):
            if wanted and (choice.engine, choice.model) == wanted:
                index = i
                break
        if index == wx.NOT_FOUND and models:
            best = getattr(self, "_recommended", None)
            index = next((i for i, c in enumerate(models)
                          if best and c.model == best.model), 0)
        if index != wx.NOT_FOUND:
            self.model_choice.SetSelection(index)
        self.model_choice.Enable(bool(models))
        self._update_model_info()

    def _selected_model_key(self) -> tuple[str, str] | None:
        index = self.model_choice.GetSelection()
        if index == wx.NOT_FOUND:
            return None
        choice = self.model_choice.GetClientData(index)
        return (choice.engine, choice.model) if choice else None

    def _selected_model(self):
        index = self.model_choice.GetSelection()
        return self.model_choice.GetClientData(index) if index != wx.NOT_FOUND else None

    def _on_source_changed(self, _evt) -> None:
        self._populate_models()

    def _on_model_changed(self, _evt) -> None:
        self._update_model_info()

    def _update_model_info(self) -> None:
        """Rewrite the description box for whatever is selected now."""
        from podharvest import estimate as estimate_mod
        choice = self._selected_model()
        if choice is None:
            self.model_info.SetValue(
                "No transcription model is available yet. Hardware detection may still "
                "be running.")
            return
        text = estimate_mod.describe_model(choice, self._estimated_audio_seconds,
                                           getattr(self, "_hw", None))
        self.model_info.SetValue(text)
        # The first line is the model name; keep the caret at the top so a
        # screen reader starts reading from the beginning.
        self.model_info.SetInsertionPoint(0)

    def _on_browse_output(self, _evt) -> None:
        with wx.DirDialog(self, "Choose an output folder", defaultPath=self.output_ctrl.GetValue()) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.output_ctrl.SetValue(dlg.GetPath())

    # -- run progress -----------------------------------------------------

    def _reset_progress(self) -> None:
        self.episode_list.DeleteAllItems()
        self._episode_rows = {}
        self._episode_percent = {}
        self._counts = {"done": 0, "failed": 0, "skipped": 0}
        self.progress.SetValue(0)
        self._set_progress_text("Starting...")

    def _set_progress_text(self, text: str) -> None:
        self.progress_text.SetLabel(text)
        self.SetStatusText(text)

    def _on_episode_progress(self, prog) -> None:
        """Fold one EpisodeProgress into the list, the gauge caption and the title.

        Called on the UI thread. The engines report progress every audio chunk,
        so the row is only rewritten when something a reader would notice has
        actually changed.
        """
        row = self._episode_rows.get(prog.index)
        if row is None:
            row = self.episode_list.InsertItem(self.episode_list.GetItemCount(), str(prog.index))
            self._episode_rows[prog.index] = row
            self.episode_list.SetItem(row, 1, prog.title)

        previous = self._episode_percent.get(prog.index)
        key = (prog.state, int(prog.percent))
        if previous == key:
            return
        self._episode_percent[prog.index] = key

        status = prog.state_label
        if prog.detail:
            status = f"{status} ({prog.detail})"
        self.episode_list.SetItem(row, 2, status)
        self.episode_list.SetItem(row, 3,
                                  "" if prog.state == "waiting" else f"{prog.percent:.0f}%")

        overall = self.progress.GetValue()
        if prog.state in {"done", "failed", "skipped"}:
            self._counts[prog.state] = self._counts.get(prog.state, 0) + 1
            self.episode_list.SetItem(row, 4, spoken_duration(prog.elapsed))
            # Keep the newest finished row in view without stealing focus.
            self.episode_list.EnsureVisible(row)
            finished = sum(self._counts.values())
            self._set_progress_text(
                f"{finished} of {prog.total} episodes finished, {overall}% of everything. "
                f"Last: '{prog.title}' - {prog.state_label.lower()} in "
                f"{spoken_duration(prog.elapsed)}.")
        elif prog.state in {"transcribing", "summarising"}:
            doing = ("transcribing" if prog.state == "transcribing"
                     else "writing the summary for")
            extra = f" ({prog.detail})" if prog.detail else ""
            self._set_progress_text(
                f"Episode {prog.index} of {prog.total} - {doing} '{prog.title}'{extra} - "
                f"{prog.percent:.0f}% of this episode, {overall}% of everything.")
        self.SetTitle(f"{overall}% - podharvest {__version__}")

    def _open_folder(self, path: str) -> None:
        try:
            if not wx.LaunchDefaultApplication(path):
                raise OSError("the system declined to open the folder")
        except Exception as exc:  # noqa: BLE001 - never let this end the session
            LOG.error("Could not open %s: %s", path, exc)
            wx.MessageBox(f"Could not open that folder.\n\n{path}\n\n{exc}",
                          "Could not open the folder", wx.OK | wx.ICON_ERROR, self)

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
        self._hw = hw
        self._local_models = hardware_mod.available_models(hw)
        self._recommended = hardware_mod.recommend_model(hw)
        self._refresh_cloud_availability()
        saved = (self.settings.asr_engine, self.settings.asr_model)
        self._populate_models(prefer=saved if saved != ("", "") else None)
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
        self._reset_progress()
        self._run_output_dir = output_dir
        self._run_failed = None
        self.start_btn.Disable()
        self._set_cancel_mode("cancel")
        self.cancel_btn.Enable()
        self._menu_cancel.Enable(True)
        self._set_progress_text(f"Starting on {url}")
        self._cancel_event.clear()

        self._worker = threading.Thread(
            target=self._run_harvest_worker,
            args=(url, output_dir, self.chk_download.GetValue(), self.chk_transcribe.GetValue(),
                  model_choice, self.chk_timestamps.GetValue(), self.chk_speakers.GetValue(), limit),
            daemon=True,
        )
        self._worker.start()

    def _set_cancel_mode(self, mode: str) -> None:
        """The second button is 'Cancel' during a run and 'Open output folder'
        once one has finished - the same key spot in the tab order, relabelled,
        so the change is announced when focus reaches it."""
        self._cancel_mode = mode
        if mode == "cancel":
            self.cancel_btn.SetLabel("&Cancel")
            self.cancel_btn.SetToolTip("Stop the run in progress.")
        else:
            self.cancel_btn.SetLabel("Open &output folder")
            self.cancel_btn.SetToolTip("Open the folder holding everything this run produced.")
        set_accessible_name(self.cancel_btn, self.cancel_btn.GetLabel().replace("&", ""))

    def _run_harvest_worker(self, url, output_dir, download, transcribe, model_choice,
                             timestamps, speakers, limit) -> None:
        try:
            try:
                from podharvest.harvest import run_harvest
            except ImportError as exc:
                LOG.error("The fetch/render/download pipeline is not wired up yet in this workspace (%s).", exc)
                LOG.error("Hardware detection and this UI are functional; feed harvesting is still being assembled.")
                self._run_failed = str(exc)
                return
            run_harvest(
                url,
                app=self.app_space,
                settings=self.settings,
                output_dir=output_dir,
                download=download,
                transcribe=transcribe,
                model=model_choice,
                include_timestamps=timestamps,
                identify_speakers=speakers,
                limit=limit,
                cancel_event=self._cancel_event,
                progress_callback=lambda pct: wx.CallAfter(self.progress.SetValue, int(pct)),
                episode_callback=lambda prog: self._ui(self._on_episode_progress, prog),
            )
        except Exception as exc:  # noqa: BLE001 - surface everything to the log pane
            LOG.exception("The run stopped with an error: %s", exc)
            self._run_failed = str(exc)
        finally:
            wx.CallAfter(self._finish_worker)

    def _finish_worker(self) -> None:
        self.start_btn.Enable()
        self._menu_cancel.Enable(False)
        cancelled = self._cancel_event.is_set()
        done = self._counts.get("done", 0)
        failed = self._counts.get("failed", 0)
        skipped = self._counts.get("skipped", 0)

        if self._run_failed:
            headline = "The run stopped with an error."
            body = (f"{self._run_failed}\n\nThe activity log has the details. "
                    "Anything finished before the error is still in the output folder.")
            icon = wx.ICON_ERROR
        elif cancelled:
            headline = "Run cancelled."
            body = (f"You stopped the run. {done} episode(s) finished before it stopped "
                    "and those files are complete.")
            icon = wx.ICON_INFORMATION
        else:
            headline = "Finished."
            parts = [f"{done} episode(s) finished"]
            if failed:
                parts.append(f"{failed} failed")
            if skipped:
                parts.append(f"{skipped} skipped")
            body = ", ".join(parts) + f".\n\nEverything is in:\n{self._run_output_dir}"
            icon = wx.ICON_WARNING if failed else wx.ICON_INFORMATION

        self.progress.SetValue(100 if not cancelled and not self._run_failed
                               else self.progress.GetValue())
        self._set_progress_text(f"{headline} {body.splitlines()[0]}")
        self.SetTitle(f"podharvest {__version__}")
        LOG.info("%s %s", headline, body.replace("\n\n", " ").replace("\n", " "))

        # The button that stopped the run becomes the way into the results, so
        # the same place in the tab order stays useful instead of going dead.
        self._set_cancel_mode("open")
        self.cancel_btn.Enable(bool(self._run_output_dir))

        if self.settings.show_finished_dialog:
            # A modal dialog takes focus, which is the only reliable way to
            # announce the end of a long run to someone who is not watching the
            # window. It is a setting because that is also intrusive.
            wx.MessageBox(body, headline, wx.OK | icon, self)
        self.start_btn.SetFocus()

    def _on_cancel(self, _evt) -> None:
        if getattr(self, "_cancel_mode", "cancel") == "open":
            if self._run_output_dir:
                self._open_folder(self._run_output_dir)
            return
        self._cancel_event.set()
        self._set_progress_text("Stopping after the current episode...")
        LOG.warning("Stopping at your request. The episode in progress will finish first.")

    def _on_close(self, evt) -> None:
        self._cancel_event.set()
        self._save_settings()
        if self._log_handler in LOG.handlers:
            LOG.removeHandler(self._log_handler)
        if self._file_log_handler is not None:
            LOG.removeHandler(self._file_log_handler)
            self._file_log_handler.close()
            self._file_log_handler = None
        evt.Skip()


def run_gui() -> int:
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
    return 0
