"""wxPython desktop front-end for podHarvest.

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
import time
from pathlib import Path

from podharvest import DISPLAY_NAME, SUPPORT_EMAIL, __version__, cues
from podharvest import appspace as appspace_mod
from podharvest import config as config_mod
from podharvest import hardware as hardware_mod
from podharvest import help as help_mod
from podharvest.a11y import _Named, set_accessible_name, size_for_text  # noqa: F401
from podharvest.keystore import load_key as keystore_load
from podharvest.player import PlayerPanel
from podharvest.util import LOG, spoken_duration

#: How often the playhead is written to disk while playing. The transport
#: ticks ten times a second; recording that would be a great deal of disk
#: for a number nobody needs to the tenth of a second.
POSITION_SAVE_SECONDS = 5.0

#: The episode list is two things at different times, and its column headings
#: say which. A reader hears the heading with every cell, so they have to be
#: true for what is actually in the row.
_LIBRARY_COLUMNS = (
    ("Podcast", 200), ("Episode", 340), ("What you have", 170),
    ("Published", 100), ("Length", 90),
)
_RUN_COLUMNS = (
    ("#", 50), ("Episode", 380), ("Status", 150),
    ("Progress", 90), ("Time", 110),
)
#: Headings for the local-files list. Same five slots, different questions:
#: a file you already had is identified by its name and where it sits, not by
#: which podcast it came from or when it was published.
#: Headings for a feed being browsed rather than harvested. The list is
#: showing what a publisher offers, not what you have, so "What you
#: have" would be a lie in every row.
_BROWSE_COLUMNS = (
    ("#", 50), ("Episode", 400), ("Published", 110), ("Length", 90),
    ("Has", 150),
)
_LOCAL_COLUMNS = (
    ("File", 240), ("Title", 300), ("What you have", 180),
    ("Folder", 200), ("Length", 90),
)

try:
    import wx
    import wx.adv
except ImportError:  # pragma: no cover - surfaced to the caller
    raise


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
        help_mod.install(self)
        self.app = app
        self.settings = settings
        outer = wx.BoxSizer(wx.VERTICAL)

        # -- activity log ------------------------------------------------
        log_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Activity log")
        holder = log_box.GetStaticBox()
        self.chk_log_file = wx.CheckBox(holder, label="&Save a log file for every run")
        self.chk_log_file.SetToolTip(
            "Keeps a record of every run in a file, so a problem can be looked at after the "
            "fact rather than only while it is on screen."
        )
        self.chk_log_file.SetValue(settings.log_to_file)
        self.chk_log_file.Bind(wx.EVT_CHECKBOX, self._on_toggle_log)
        log_box.Add(self.chk_log_file, 0, wx.ALL, 6)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(holder, label="Log &folder:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.log_dir_ctrl = wx.TextCtrl(
            holder, value=config_mod.resolved_log_dir(app, settings), size=(320, -1))
        self.log_dir_ctrl.SetToolTip(
            "Where the log file is written. Leave it as it is unless you want "
            "the log somewhere particular."
        )
        set_accessible_name(self.log_dir_ctrl, "Log folder")
        browse = wx.Button(holder, label="Br&owse...")
        browse.SetToolTip(
            "Picks the folder for the log file with the system folder chooser."
        )
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
        # The trailing note is rewritten by _update_summary_note when the model
        # changes: 12 minutes is the truth for the on-device model and nonsense
        # for a cloud one, and a checkbox label is the part a screen reader
        # reads on focus, so it has to stay accurate.
        self.chk_summaries = wx.CheckBox(
            sholder, label="&Write a summary for each episode")
        self.chk_summaries.SetToolTip(
            "Writes a short summary of each episode beside its transcript. The box below says "
            "how long that adds per episode on this machine."
        )
        self.chk_summaries.SetValue(settings.enrichment_enabled)
        self.chk_summaries.Bind(wx.EVT_CHECKBOX, self._on_toggle_summaries)
        self.chk_full_episode = wx.CheckBox(
            sholder, label="Summarise the w&hole episode, not just the beginning")
        self.chk_full_episode.SetValue(settings.enrichment_full_episode)
        self.chk_full_episode.Bind(wx.EVT_CHECKBOX, self._on_summary_model_changed)
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
        self.summary_model_choice.SetToolTip(
            "Which model writes the summaries. The box underneath says what this one will "
            "cost you in time on this machine, for the podcast you have loaded."
        )
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
        self.summary_model_choice.Bind(wx.EVT_CHOICE, self._on_summary_model_changed)
        model_row.Add(self.summary_model_choice, 1, wx.EXPAND)
        sum_box.Add(model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Read-only and multi-line so it is a real tab stop that can be read
        # line by line. Summaries are far and away the slowest thing podharvest
        # does, and nobody should discover that only after starting a run.
        self.summary_note = wx.TextCtrl(
            sholder, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        # Sized in lines of its own font rather than in pixels, so it still
        # shows five lines when the text is scaled up rather than one.
        size_for_text(self.summary_note, lines=5)
        self.summary_note.SetToolTip(
            "What the chosen summary model will actually cost you in time on this machine, "
            "for the podcast you have loaded. Read-only."
        )
        set_accessible_name(self.summary_note, "How long summaries will take")
        sum_box.Add(self.summary_note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
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
        self.chk_srt.SetToolTip(
            "Writes a .srt subtitle track beside each transcript. Useful for video editors "
            "and media players; the transcript itself is written either way."
        )
        self.chk_srt.SetValue(settings.write_srt)
        self.chk_vtt = wx.CheckBox(subholder, label="Write a .&vtt subtitle file")
        self.chk_vtt.SetToolTip(
            "Writes a .vtt subtitle track beside each transcript. WebVTT is what web players "
            "use; the transcript itself is written either way."
        )
        self.chk_vtt.SetValue(settings.write_vtt)
        sub_box.Add(self.chk_srt, 0, wx.LEFT | wx.RIGHT, 6)
        sub_box.Add(self.chk_vtt, 0, wx.ALL, 6)
        outer.Add(sub_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # -- cloud providers -----------------------------------------------
        outer.Add(self._build_directory_settings(), 0,
                  wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self._build_local_settings(), 0,
                  wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self._build_playback_settings(), 0,
                  wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(self._build_keys_box(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # -- finishing -----------------------------------------------------
        fin_box = wx.StaticBoxSizer(wx.VERTICAL, self, "When a run finishes")
        fholder = fin_box.GetStaticBox()
        self.chk_finished_dialog = wx.CheckBox(
            fholder, label="Show a &dialog saying the run has finished")
        self.chk_finished_dialog.SetToolTip(
            "Shows a message when the whole run finishes, and takes focus so a screen reader "
            "announces it. Turn it off if you would rather watch the log."
        )
        self.chk_finished_dialog.SetValue(settings.show_finished_dialog)
        fin_box.Add(self.chk_finished_dialog, 0, wx.ALL, 6)
        outer.Add(fin_box, 0, wx.EXPAND | wx.ALL, 10)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self._on_toggle_log(None)
        self._on_toggle_summaries(None)

    def _build_directory_settings(self) -> wx.StaticBoxSizer:
        """Where podcast searches look, and how much they bring back."""
        from podharvest import directory as directory_mod

        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Finding podcasts")
        holder = box.GetStaticBox()
        grid = wx.FlexGridSizer(2, 2, 8, 8)
        grid.AddGrowableCol(1)

        # Label before control, so a screen reader pairs the two.
        grid.Add(wx.StaticText(holder, label="Search &Apple's store for:"), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        self.country_choice = wx.Choice(
            holder,
            choices=[name for _code, name in directory_mod.STOREFRONTS])
        self.country_choice.SetToolTip(
            "Which of Apple's stores podcast searches ask. They carry "
            "different shows, so a local podcast may only appear in its own "
            "country's store. The United States store is the largest and is "
            "the default. Any other two-letter country code Apple recognises "
            "can be put straight into the settings file."
        )
        set_accessible_name(self.country_choice, "Podcast store country")
        wanted = directory_mod.clean_storefront(self.settings.itunes_country)
        codes = [code for code, _name in directory_mod.STOREFRONTS]
        self.country_choice.SetSelection(
            codes.index(wanted) if wanted in codes else 0)
        grid.Add(self.country_choice, 0)

        grid.Add(wx.StaticText(holder, label="&Results to fetch:"), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        self.search_limit_ctrl = wx.SpinCtrl(
            holder, min=1, max=directory_mod.MAX_LIMIT,
            initial=int(self.settings.search_limit))
        self.search_limit_ctrl.SetToolTip(
            "How many shows a search asks for, up to "
            f"{directory_mod.MAX_LIMIT}. More costs nothing extra to fetch "
            "but makes a longer list to read through."
        )
        set_accessible_name(self.search_limit_ctrl, "Results to fetch")
        grid.Add(self.search_limit_ctrl, 0)
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        return box

    def _build_local_settings(self) -> wx.StaticBoxSizer:
        """How podHarvest treats audio you already have."""
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Local files")
        holder = box.GetStaticBox()

        self.chk_local_beside = wx.CheckBox(
            holder, label="Write transcripts &beside the audio file")
        self.chk_local_beside.SetValue(
            self.settings.local_transcripts_beside_file)
        self.chk_local_beside.SetToolTip(
            "On: lecture.mp3 gets lecture.md next to it, so a file and its "
            "transcript stay together if you move the folder later. Off: "
            "transcripts go into a \"Local files\" folder inside your output "
            "folder instead, and podHarvest never writes into your own "
            "folders. Chapter markers and tags are written into the audio "
            "either way, because that is where they belong."
        )
        box.Add(self.chk_local_beside, 0, wx.ALL, 6)

        self.chk_sound_cues = wx.CheckBox(
            holder, label="Play a short &sound as each episode finishes")
        self.chk_sound_cues.SetValue(self.settings.sound_cues)
        self.chk_sound_cues.SetToolTip(
            "One short tone per episode, a rising pair when the run ends, a "
            "low tone if something failed. This is the only thing that reports "
            "progress without you reading the activity log, which cannot "
            "announce itself to a screen reader. Off by default because a "
            "sound nobody asked for is an intrusion."
        )
        box.Add(self.chk_sound_cues, 0, wx.ALL, 6)

        self.chk_local_recurse = wx.CheckBox(
            holder, label="Include su&bfolders when I add a folder")
        self.chk_local_recurse.SetValue(self.settings.local_recurse_folders)
        self.chk_local_recurse.SetToolTip(
            "On: adding a folder takes the audio in it and in everything under "
            "it, which is what an album or a series of lectures usually needs. "
            "Off: only the folder you picked."
        )
        box.Add(self.chk_local_recurse, 0, wx.ALL, 6)
        return box

    def _build_playback_settings(self) -> wx.StaticBoxSizer:
        """How the transport behaves: skip amounts, and whether to resume."""
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Playback")
        holder = box.GetStaticBox()
        grid = wx.FlexGridSizer(3, 2, 8, 8)
        grid.AddGrowableCol(1)

        # Label before control, so a screen reader pairs the two.
        grid.Add(wx.StaticText(holder, label="Rewind by (seconds):"), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        self.skip_back_ctrl = wx.SpinCtrl(
            holder, min=1, max=300,
            initial=max(1, self.settings.skip_back_ms // 1000))
        self.skip_back_ctrl.SetToolTip(
            "How far the Rewind button and Ctrl+B jump back. Ten seconds is "
            "about a sentence, which is usually what you missed."
        )
        set_accessible_name(self.skip_back_ctrl, "Rewind by, in seconds")
        grid.Add(self.skip_back_ctrl, 0)

        grid.Add(wx.StaticText(holder, label="Forward by (seconds):"), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        self.skip_forward_ctrl = wx.SpinCtrl(
            holder, min=1, max=300,
            initial=max(1, self.settings.skip_forward_ms // 1000))
        self.skip_forward_ctrl.SetToolTip(
            "How far the Forward button and Ctrl+F jump on. Separate from "
            "rewind on purpose: skipping an advert break usually wants a "
            "bigger jump than re-hearing a sentence."
        )
        set_accessible_name(self.skip_forward_ctrl, "Forward by, in seconds")
        grid.Add(self.skip_forward_ctrl, 0)

        grid.Add(wx.StaticText(holder, label="Playback &speeds:"), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        self.rates_ctrl = wx.TextCtrl(
            holder, value=_rates_text(self.settings.playback_rates))
        self.rates_ctrl.SetToolTip(
            "The speeds the Speed box offers, separated by commas. Go as fast "
            f"as {config_mod.MAX_RATE:g}x or as slow as {config_mod.MIN_RATE:g}x: "
            "3x is a normal way through a backlog, and 0.5x makes a fast "
            "speaker followable. Anything outside that range, or that is not a "
            "number, is dropped; 1x is always kept so there is a way back to "
            "normal speed."
        )
        set_accessible_name(
            self.rates_ctrl, "Playback speeds, separated by commas")
        grid.Add(self.rates_ctrl, 1, wx.EXPAND)
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        self.chk_remember_position = wx.CheckBox(
            holder, label="&Remember where I stopped in each episode")
        self.chk_remember_position.SetValue(self.settings.remember_playback_position)
        self.chk_remember_position.SetToolTip(
            "Picks an episode up where you left it, and says so when it does. "
            "An episode you played to the end starts from the beginning next "
            "time, because finishing is not a place to come back to."
        )
        box.Add(self.chk_remember_position, 0, wx.ALL, 6)
        return box

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
            field.SetToolTip(
                "The API key for this provider. It is stored in the operating system's "
                "credential vault, never in podHarvest's settings file, and only ever sent to "
                "the provider it belongs to."
            )
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

        # Without this, a wrong key is only discovered part-way through a long
        # run, as a failure that could equally mean the key was never saved,
        # was rejected, or the network was down. One button removes the guessing.
        self.test_keys_btn = wx.Button(holder, label="&Test these keys now")
        self.test_keys_btn.SetToolTip(
            "Checks each key you have entered against its provider, right now, and reports "
            "which ones work. Nothing is transcribed and nothing is charged."
        )
        self.test_keys_btn.Bind(wx.EVT_BUTTON, self._on_test_keys)
        self.test_keys_btn.SetToolTip(
            "Contacts each provider you have entered a key for and reports whether it "
            "works. Only lists the available models, so it costs nothing.")
        box.Add(self.test_keys_btn, 0, wx.LEFT | wx.BOTTOM, 6)

        # Read-only and multi-line so the result is a real tab stop that can be
        # read back line by line, not a label that is announced once and lost.
        self.key_status = wx.TextCtrl(
            holder, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        # One line per provider tested, plus room for a sentence about each.
        size_for_text(self.key_status, lines=6)
        self.key_status.SetToolTip(
            "The result of the last key test: which providers answered and which did not. "
            "Read-only."
        )
        set_accessible_name(self.key_status, "Key test results")
        self.key_status.SetValue(
            "Keys have not been tested. Press \"Test these keys now\" to check them "
            "before starting a run.")
        box.Add(self.key_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        return box

    def _entered_key(self, provider: str) -> str | None:
        """The key to test: what is typed now, or None to use what is stored."""
        field = self.key_fields[provider]
        value = field.GetValue().strip()
        if not field.IsEditable():          # environment variable owns it
            return None
        if not value or set(value) == {"*"}:  # untouched placeholder
            return None
        return value

    def _on_test_keys(self, _evt) -> None:
        """Check every configured key, off the UI thread."""
        from podharvest import cloud as cloud_mod

        providers = [p for p in cloud_mod.ALL_PROVIDERS
                     if self._entered_key(p) or keystore_load(self.app, p)]
        if not providers:
            self.key_status.SetValue(
                "No keys to test. Enter at least one key above first.")
            self.key_status.SetInsertionPoint(0)
            return

        self.test_keys_btn.Disable()
        self.key_status.SetValue("Testing...")
        pending = {p: self._entered_key(p) for p in providers}

        def work():
            lines = []
            for provider, typed in pending.items():
                ok, message = cloud_mod.verify_key(self.app, provider, typed)
                lines.append(("OK: " if ok else "FAILED: ") + message)
            wx.CallAfter(self._show_key_results, lines)

        threading.Thread(target=work, daemon=True).start()

    def _show_key_results(self, lines: list[str]) -> None:
        self.test_keys_btn.Enable()
        failed = sum(1 for line in lines if line.startswith("FAILED"))
        header = ("All keys are working." if not failed else
                  f"{failed} of {len(lines)} keys did not work.")
        self.key_status.SetValue(header + "\n\n" + "\n".join(lines))
        self.key_status.SetInsertionPoint(0)
        # Move focus to the result so it is read out rather than sitting unnoticed
        # on a button that now says nothing new.
        self.key_status.SetFocus()

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
        self._update_summary_note()

    def _on_summary_model_changed(self, _evt) -> None:
        self._update_summary_note()

    def _update_summary_note(self) -> None:
        """Say plainly how long summaries will take, for the current choice.

        The figures are real: measured on a 59-minute episode on a CPU-only
        machine during development, not estimated from model size.
        """
        if not self.chk_summaries.GetValue():
            self.summary_note.SetValue(
                "Summaries are off. Transcripts are still written; there is just no "
                "summary or chapter list alongside them.")
            self.summary_note.SetInsertionPoint(0)
            return

        picked = self.summary_model_choice.GetClientData(
            self.summary_model_choice.GetSelection())
        whole = self.chk_full_episode.GetValue()

        # Keep the cost in the label itself, because that is what gets read out
        # when focus lands on the checkbox.
        self.chk_summaries.SetLabel(
            "&Write a summary for each episode (about two seconds each, "
            f"using {picked.provider})" if picked else
            "&Write a summary for each episode (slow on this machine: about "
            "12 minutes per hour-long episode)")

        if picked is None:
            lines = [
                "WARNING: this is the slow part of podharvest.",
                "",
                "The on-device model runs on your own processor, so nothing is uploaded, "
                "but it is not quick. On a one-hour episode on a machine with no graphics "
                "card, writing the summary and its chapter markers took 12 minutes. "
                "Transcribing the same episode took 3 and a half minutes, so the summary "
                "is roughly three times the cost of the transcript itself.",
                "",
                "For a hundred episodes that is most of a day rather than an afternoon. "
                "It runs unattended, so that may be perfectly fine. It is only a problem "
                "if you were not expecting it.",
            ]
            if whole:
                lines += [
                    "",
                    "\"Summarise the whole episode\" is on, which is what makes it this "
                    "slow. Turning it off is two to three times faster, but the summary "
                    "then only covers the opening stretch of a long episode.",
                ]
            lines += [
                "",
                "If you have an API key, choosing a cloud model above does the same work "
                "in about two seconds an episode. The transcript text is sent to that "
                "provider; your audio is not.",
            ]
        else:
            provider = picked.provider
            lines = [
                f"About two seconds an episode, measured against {provider}.",
                "",
                "That is roughly four hundred times faster than the on-device model, which "
                "takes about 12 minutes on a one-hour episode.",
                "",
                "The transcript text is sent to the provider and charged to your API key. "
                "Your audio file is not uploaded for this: only the words.",
            ]
            if not whole:
                lines += [
                    "",
                    "\"Summarise the whole episode\" is off, so summaries will only cover "
                    "the beginning of a long episode. With a cloud model there is little "
                    "reason to leave it off; it costs seconds, not minutes.",
                ]
        self.summary_note.SetValue("\n".join(lines))
        self.summary_note.SetInsertionPoint(0)

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
        settings.skip_back_ms = self.skip_back_ctrl.GetValue() * 1000
        settings.skip_forward_ms = self.skip_forward_ctrl.GetValue() * 1000
        settings.remember_playback_position = self.chk_remember_position.GetValue()
        settings.playback_rates = config_mod.clean_rates(
            _parse_rates(self.rates_ctrl.GetValue()))
        settings.local_transcripts_beside_file = self.chk_local_beside.GetValue()
        settings.local_recurse_folders = self.chk_local_recurse.GetValue()
        settings.sound_cues = self.chk_sound_cues.GetValue()
        from podharvest import directory as directory_mod

        index = self.country_choice.GetSelection()
        if 0 <= index < len(directory_mod.STOREFRONTS):
            settings.itunes_country = directory_mod.STOREFRONTS[index][0]
        settings.search_limit = self.search_limit_ctrl.GetValue()


def _rates_text(rates) -> str:
    """``[0.75, 1.0, 2.0]`` -> ``0.75, 1, 2``, for the settings field."""
    return ", ".join(f"{float(r):g}" for r in rates)


def _parse_rates(text: str) -> list[float]:
    """Whatever was typed, as numbers. Separators are generous on purpose.

    Somebody typing a list of speeds should not have to think about whether
    commas or spaces are wanted, and an "x" after each is the obvious thing to
    write. Validation proper is `config.clean_rates`; this only splits.
    """
    rates: list[float] = []
    for chunk in text.replace("x", " ").replace(",", " ").split():
        try:
            rates.append(float(chunk))
        except ValueError:
            continue
    return rates


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title=f"{DISPLAY_NAME} {__version__}", size=(880, 720))
        self.app_space = appspace_mod.resolve()
        self.app_space.activate()
        self.settings = config_mod.load(self.app_space)
        self._worker: threading.Thread | None = None
        # The local-files source: what has been added, and the row -> file map
        # the Episodes list is built from. Buttons are collected so they can be
        # disabled together during a run.
        self._local_paths: list[Path] = []
        self._local_rows: dict = {}
        self._local_buttons: list = []
        #: A feed read with Show episodes, by row. Separate from the
        #: library and the local list because these episodes are not
        #: on disk at all.
        self._browsed_rows: dict = {}
        #: The name the last chosen or browsed feed gives itself, so a
        #: favourite is saved under something better than its address.
        self._browsed_title: str = ""
        self._cancel_event = threading.Event()
        self._episode_rows: dict[int, int] = {}
        #: Which episode the transport currently holds open, so pressing
        #: Play twice does not reload the same file.
        self._loaded_audio_title: str = ""
        self._loaded_audio_path = None
        self._position_saved_at = 0.0
        #: The library rows currently shown, by row index. Empty while a
        #: run is in progress, when the list is a progress view instead.
        self._library_rows: dict[int, object] = {}
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
        # F1 anywhere answers with what this window is for and what the focused
        # control does. This also installs the help provider, without which
        # every SetHelpText in the program silently stores nothing.
        help_mod.install(self)
        self._setup_tray()
        # After the log handler is wired, so the notice lands where a screen
        # reader can go and read it (Ctrl+L).
        self._report_media_health()
        # The list starts as your library -- or, if Local files was the source
        # last time, as that -- rather than as an empty box: what you were
        # doing last time is the most likely reason you opened this.
        self._apply_source_mode()
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
        screen reader; without one there is no Alt/F10 entry point at all.

        Five menus rather than three, grouped by what you are acting *on*
        rather than by what happens to be implemented near what. File is the
        podcast or the files; Episode is whatever is highlighted; View is
        where focus goes; Tools is the machine and its models; Help explains.
        A menu that has become a list of everything is as hard to search by
        ear as no menu at all.
        """
        bar = wx.MenuBar()

        # -- File: choosing what to work on, and starting -------------------
        file_menu = wx.Menu()
        self._menu_find = file_menu.Append(
            wx.ID_ANY, "&Find a podcast...\tCtrl+K",
            "Search Apple's podcast directory by name")
        self._menu_favorites = file_menu.Append(
            wx.ID_ANY, "Fa&vourite podcasts...\tCtrl+Shift+K",
            "The shows you have marked, to come back to")
        self._menu_add_favorite = file_menu.Append(
            wx.ID_ANY, "Add this feed to favou&rites",
            "Remember the feed address currently in the box")
        file_menu.AppendSeparator()
        self._menu_browse = file_menu.Append(
            wx.ID_ANY, "Show &episodes in this feed\tCtrl+Shift+E",
            "Read the feed and list its episodes, downloading nothing")
        file_menu.AppendSeparator()
        self._menu_add_files = file_menu.Append(
            wx.ID_ANY, "&Add local files...\tCtrl+O",
            "Choose audio already on this machine to transcribe, tag or edit")
        self._menu_add_folder = file_menu.Append(
            wx.ID_ANY, "Add a local f&older...\tCtrl+Shift+F",
            "Take every audio file in a folder")
        file_menu.AppendSeparator()
        self._menu_start = file_menu.Append(
            wx.ID_ANY, "&Start\tCtrl+R", "Begin harvesting, or transcribing")
        self._menu_cancel = file_menu.Append(
            wx.ID_ANY, "&Cancel\tEsc", "Stop the run in progress")
        self._menu_cancel.Enable(False)
        file_menu.AppendSeparator()
        self._menu_open_out = file_menu.Append(
            wx.ID_ANY, "Open out&put folder\tCtrl+Shift+O",
            "Open the folder holding the results")
        self._menu_open_log = file_menu.Append(
            wx.ID_ANY, "Open &log folder",
            "Open the folder holding the saved log file")
        file_menu.AppendSeparator()
        self._menu_settings = file_menu.Append(
            wx.ID_PREFERENCES, "Se&ttings...\tCtrl+,",
            "Everything podHarvest remembers between runs")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", f"Close {DISPLAY_NAME}")
        bar.Append(file_menu, "&File")

        # -- Episode: whatever is highlighted in the list -------------------
        episode_menu = wx.Menu()
        self._menu_play = episode_menu.Append(
            wx.ID_ANY, "&Play or pause\tCtrl+P",
            "Play the highlighted episode, or pause it if it is playing")
        self._menu_rewind = episode_menu.Append(
            wx.ID_ANY, "&Rewind\tCtrl+B",
            "Jump back by the amount set in Settings")
        self._menu_forward = episode_menu.Append(
            wx.ID_ANY, "&Forward\tCtrl+F",
            "Jump on by the amount set in Settings")
        episode_menu.AppendSeparator()
        self._menu_transcript = episode_menu.Append(
            wx.ID_ANY, "Read the &transcript...\tCtrl+Shift+T",
            "Open the highlighted episode's transcript, with a search box")
        self._menu_edit_tags = episode_menu.Append(
            wx.ID_ANY, "Edit tags and &chapters...\tCtrl+T",
            "Open the highlighted episode's audio in the Tag and Chapter Editor")
        episode_menu.AppendSeparator()
        self._menu_reveal = episode_menu.Append(
            wx.ID_ANY, "Open the folder it is &in",
            "Open the folder holding the highlighted episode's audio")
        bar.Append(episode_menu, "&Episode")

        # -- View: where focus goes, and what the list is showing -----------
        view_menu = wx.Menu()
        self._menu_focus_episodes = view_menu.Append(
            wx.ID_ANY, "Go to &episode list\tCtrl+E",
            "Move focus to the list of episodes")
        self._menu_focus_log = view_menu.Append(
            wx.ID_ANY, "Go to activity &log\tCtrl+L",
            "Move focus to the activity log")
        view_menu.AppendSeparator()
        self._menu_refresh_library = view_menu.Append(
            wx.ID_ANY, "Re&fresh the library\tCtrl+Shift+R",
            "Read the output folder again and list what is in it")
        view_menu.AppendSeparator()
        self._menu_tray = view_menu.Append(
            wx.ID_ANY, "&Minimise to the notification area\tCtrl+Shift+M",
            "Hide the window; the run carries on and the tray icon brings it back")
        bar.Append(view_menu, "&View")

        # -- Tools: this machine, and the models on it ----------------------
        tools_menu = wx.Menu()
        self._menu_download_model = tools_menu.Append(
            wx.ID_ANY, "&Download the selected model",
            "Fetch everything the chosen model needs, before a run needs it")
        self._menu_check_install = tools_menu.Append(
            wx.ID_ANY, "&Check what is installed...",
            "Which engines are downloaded, and whether they actually load")
        tools_menu.AppendSeparator()
        self._menu_redetect = tools_menu.Append(
            wx.ID_ANY, "&Re-detect hardware\tCtrl+D",
            "Probe the processor, memory and graphics again")
        self._menu_media_tools = tools_menu.Append(
            wx.ID_ANY, "&Media tools...",
            "Whether FFmpeg is installed, and what it is used for")
        bar.Append(tools_menu, "&Tools")

        # -- Help -----------------------------------------------------------
        help_menu = wx.Menu()
        self._menu_help_here = help_menu.Append(
            wx.ID_ANY, "Explain this &window and control\tF1",
            "What this window is for, and what the control you are on does")
        help_menu.AppendSeparator()
        self._menu_docs = help_menu.Append(
            wx.ID_ANY, "Open the &documentation",
            "The guides that ship with podHarvest, in your file browser")
        self._menu_report_bug = help_menu.Append(
            wx.ID_ANY, "&Report a bug...",
            "Build a report you can read before anything is sent")
        help_menu.AppendSeparator()
        help_menu.Append(wx.ID_ABOUT, f"&About {DISPLAY_NAME}",
                         "Version and project information")
        bar.Append(help_menu, "&Help")

        self.SetMenuBar(bar)

        self.Bind(wx.EVT_MENU, self._on_start, self._menu_start)
        self.Bind(wx.EVT_MENU, self._on_cancel, self._menu_cancel)
        self.Bind(wx.EVT_MENU, self._on_settings, self._menu_settings)
        self.Bind(wx.EVT_MENU, self._on_find_podcast, self._menu_find)
        self.Bind(wx.EVT_MENU, self._on_favorites, self._menu_favorites)
        self.Bind(wx.EVT_MENU, self._on_add_favorite, self._menu_add_favorite)
        self.Bind(wx.EVT_MENU, self._on_browse_feed, self._menu_browse)
        self.Bind(wx.EVT_MENU, self._on_add_files, self._menu_add_files)
        self.Bind(wx.EVT_MENU, self._on_add_folder, self._menu_add_folder)
        self.Bind(wx.EVT_MENU, lambda evt: self._open_folder(
            self._run_output_dir or self.output_ctrl.GetValue().strip()),
            self._menu_open_out)
        self.Bind(wx.EVT_MENU, lambda evt: self._open_folder(
            config_mod.resolved_log_dir(self.app_space, self.settings)),
            self._menu_open_log)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=wx.ID_EXIT)

        self.Bind(wx.EVT_MENU, lambda _e: self._on_play_selected(), self._menu_play)
        self.Bind(wx.EVT_MENU, lambda _e: self.player.skip_back(), self._menu_rewind)
        self.Bind(wx.EVT_MENU, lambda _e: self.player.skip_forward(), self._menu_forward)
        self.Bind(wx.EVT_MENU, lambda _e: self._on_read_transcript(),
                  self._menu_transcript)
        self.Bind(wx.EVT_MENU, self._on_edit_tags, self._menu_edit_tags)
        self.Bind(wx.EVT_MENU, self._on_reveal_episode, self._menu_reveal)

        self.Bind(wx.EVT_MENU, self._on_focus_log, self._menu_focus_log)
        self.Bind(wx.EVT_MENU, lambda evt: self.episode_list.SetFocus(),
                  self._menu_focus_episodes)
        self.Bind(wx.EVT_MENU, lambda _e: self.refresh_library(),
                  self._menu_refresh_library)
        self.Bind(wx.EVT_MENU, self._on_minimise_to_tray, self._menu_tray)

        self.Bind(wx.EVT_MENU, self._on_download_model, self._menu_download_model)
        self.Bind(wx.EVT_MENU, self._on_check_install, self._menu_check_install)
        self.Bind(wx.EVT_MENU, lambda evt: self.refresh_hardware(force=True),
                  self._menu_redetect)
        self.Bind(wx.EVT_MENU, self._on_media_tools, self._menu_media_tools)

        self.Bind(wx.EVT_MENU, self._on_help_here, self._menu_help_here)
        self.Bind(wx.EVT_MENU, self._on_open_docs, self._menu_docs)
        self.Bind(wx.EVT_MENU, self._on_report_bug, self._menu_report_bug)
        self.Bind(wx.EVT_MENU, self._on_about, id=wx.ID_ABOUT)

    # -- menu actions that had nowhere else to live -----------------------

    def _on_reveal_episode(self, _evt=None) -> None:
        """Open the folder holding the highlighted episode's audio."""
        path = self._selected_episode_audio()
        if path is None:
            LOG.info("Highlight an episode that has been downloaded first.")
            return
        self._open_folder(str(Path(path).parent))

    def _on_check_install(self, _evt=None) -> None:
        """Say which engines are downloaded and whether they actually load.

        The same two questions `podharvest doctor` answers, because "it is on
        disk" and "it will run" are different and the gap between them is
        where the awkward failures live.
        """
        from podharvest import acquire

        lines: list[str] = []
        broken = 0
        for engine in sorted(acquire.ENGINE_PACKAGES):
            reports = acquire.check_engine(self.app_space, engine)
            if not reports:
                continue
            lines.append(engine)
            for report in reports:
                lines.append(f"    {report.sentence()}")
                if not report.ok and report.installed:
                    broken += 1
        tail = ("\n\nSomething is downloaded but will not load. That is a bug: "
                "Help then Report a bug builds a report to send."
                if broken else
                "\n\nAnything not downloaded is fetched the first time you use "
                "it, or by Tools then Download the selected model.")
        wx.MessageBox("\n".join(lines) + tail, "What is installed",
                      wx.OK | wx.ICON_INFORMATION, self)

    def _on_help_here(self, _evt=None) -> None:
        """Answer F1 from the menu, for anyone who never found the key."""
        help_mod.show_help(self.FindFocus() or self)

    def _on_open_docs(self, _evt=None) -> None:
        """Open the shipped documentation in the file browser.

        Next to the executable in a packaged copy, and in the source tree
        otherwise; whichever exists is opened, and if neither does the log
        says where to read it online rather than opening nothing.
        """
        from podharvest import HOMEPAGE

        here = Path(__file__).resolve().parent
        for candidate in (here.parent / "docs", here.parent.parent / "docs"):
            if candidate.is_dir():
                self._open_folder(str(candidate))
                return
        LOG.info("The documentation did not ship with this copy. It is at %s",
                 HOMEPAGE)

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
            (wx.ACCEL_CTRL, ord("T"), self._menu_edit_tags.GetId()),
            (wx.ACCEL_CTRL, ord("P"), self._menu_play.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("R"),
             self._menu_refresh_library.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("T"),
             self._menu_transcript.GetId()),
            (wx.ACCEL_CTRL, ord("B"), self._menu_rewind.GetId()),
            (wx.ACCEL_CTRL, ord("F"), self._menu_forward.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("M"), self._menu_tray.GetId()),
        ]))

    def _on_focus_log(self, _evt) -> None:
        self.log_ctrl.SetFocus()

    def _on_report_bug(self, _evt) -> None:
        """Build a bug report, show it, and let the person decide what to do.

        Nothing is sent. podHarvest's promise is that what you listen to stays
        on your machine, and a bug reporter that uploaded on your behalf would
        break that promise in the one place people would least expect it.
        """
        from podharvest import feedback

        report = feedback.build_report(
            settings=self.settings,
            hardware_summary=self.hw_text.GetLabel(),
            log_text="\n".join(
                self.log_ctrl.GetValue().splitlines()[-feedback.LOG_TAIL_LINES:]),
            log_path=config_mod.resolved_log_file(self.app_space, self.settings),
        )
        dlg = _BugReportDialog(self, report)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _set_columns(self, columns) -> None:
        """Re-label the list's columns for what it is about to show."""
        for index, (heading, width) in enumerate(columns):
            item = wx.ListItem()
            item.SetText(heading)
            item.SetWidth(width)
            self.episode_list.SetColumn(index, item)
            self.episode_list.SetColumnWidth(index, width)

    def refresh_library(self) -> None:
        """List what is already in the output folder.

        The Episodes list is two things at different times: a progress view
        while a run is going, and the library the rest of the time. This is
        the library half -- read from each show's own feed.json, so the titles
        are the publisher's rather than guessed from filenames.
        """
        from podharvest import library

        if self._worker is not None and self._worker.is_alive():
            return  # a run owns the list; do not pull it out from under it
        if self.source_mode() == "local":
            # The list belongs to the local files while that source is chosen.
            self.refresh_local_list()
            return

        output = Path(self.output_ctrl.GetValue().strip() or ".")
        episodes = library.all_episodes(output)
        self.episode_list.DeleteAllItems()
        self._episode_rows = {}
        self._library_rows = {}
        self._set_columns(_LIBRARY_COLUMNS)
        for episode in episodes:
            row = self.episode_list.InsertItem(
                self.episode_list.GetItemCount(), episode.show)
            self.episode_list.SetItem(row, 1, episode.title)
            self.episode_list.SetItem(row, 2, episode.what_it_has())
            when = episode.published.strftime("%Y-%m-%d") if episode.published else ""
            self.episode_list.SetItem(row, 3, when)
            self.episode_list.SetItem(
                row, 4, spoken_duration(episode.duration_seconds or 0)
                if episode.duration_seconds else "")
            self._library_rows[row] = episode
        if episodes:
            LOG.info("Your library has %d episode(s) in it. Arrow through the "
                     "list; Ctrl+P plays one, Ctrl+Shift+T reads its "
                     "transcript, Ctrl+T edits its tags and chapters.",
                     len(episodes))
        elif self.source_mode() != "local":
            LOG.info("Nothing in %s yet. Paste a feed address above and press "
                     "Start.", output)
        self._on_episode_selected()

    def _selected_library_episode(self):
        """The library row highlighted, or None during a run or with no row."""
        row = self.episode_list.GetFirstSelected()
        return self._library_rows.get(row) if row >= 0 else None

    def _selected_local_file(self):
        """The local file highlighted, or None. Only ever set in local mode."""
        row = self.episode_list.GetFirstSelected()
        return self._local_rows.get(row) if row >= 0 else None

    def _on_read_transcript(self) -> None:
        """Open the selected episode's transcript in the reader."""
        from podharvest.reader import TranscriptDialog

        local = self._selected_local_file()
        if local is not None:
            from podharvest import localfiles
            from podharvest import reuse as reuse_mod

            out_dir, slug = localfiles.transcript_location(
                local.path,
                beside=self.settings.local_transcripts_beside_file,
                output_dir=Path(self.output_ctrl.GetValue().strip() or "."))
            found = reuse_mod.transcript_in(out_dir, slug)
            if found is None:
                LOG.info("There is no transcript for %s yet. Press Start to "
                         "make one.", local.path.name)
                return
            dlg = TranscriptDialog(self, found, title=local.display_title)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()
            return
        episode = self._selected_library_episode()
        if episode is None:
            LOG.info("Select an episode in the library first. Press "
                     "Ctrl+Shift+R to list what you have.")
            return
        if episode.transcript is None:
            LOG.info("There is no transcript for '%s'. Tick \"Transcribe "
                     "downloaded audio\" and run it again to make one.",
                     episode.title)
            return
        dlg = TranscriptDialog(self, episode.transcript, title=episode.title)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _on_media_tools(self, _evt) -> None:
        """Answer the question, whichever way the answer goes."""
        from podharvest import media_health

        wx.MessageBox(media_health.check().readout(), "Media tools",
                      wx.OK | wx.ICON_INFORMATION, self)

    def _report_media_health(self) -> None:
        """Say once that FFmpeg is missing, and what that costs.

        Every FFmpeg feature here fails by producing a plausible result -- the
        episode downloads and simply has no chapter markers -- so nobody
        notices and nobody reports it. Saying nothing on a healthy install is
        the other half: a startup that reports good news every time is one
        people learn to talk over.
        """
        from podharvest import media_health

        health = media_health.check()
        signature = health.signature()
        if health.healthy or signature == getattr(self.settings, "media_health_last_notice", ""):
            return
        LOG.warning("%s", health.notice())
        self.settings.media_health_last_notice = signature
        config_mod.save(self.app_space, self.settings)

    def _selected_episode_title(self) -> str:
        """The title in the highlighted episode row, or "" when none is."""
        row = self.episode_list.GetFirstSelected()
        if row < 0:
            return ""
        return self.episode_list.GetItemText(row, 1).strip()

    def _episode_audio_to_edit(self):
        """The audio file to open: the selected episode's, or one you pick.

        The on-disk name comes from a configurable template, so the selected
        row is matched by the slug of its title. When that finds exactly one
        file it opens straight away; otherwise -- no selection, no run yet, or
        two files that both match -- a file picker opens on the output folder,
        which always works and never opens the wrong episode.
        """
        from pathlib import Path

        from podharvest import tags as tags_mod

        local = self._selected_local_file()
        if local is not None:
            return local.path
        output = Path(self.output_ctrl.GetValue().strip() or ".")
        title = self._selected_episode_title()
        if title:
            found = tags_mod.find_episode_audio(output, title)
            if found is not None:
                return found
        with wx.FileDialog(
            self,
            "Choose an audio file to edit",
            defaultDir=str(output) if output.is_dir() else "",
            wildcard="Audio (*.mp3;*.m4a;*.m4b;*.mp4)|*.mp3;*.m4a;*.m4b;*.mp4",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            return Path(dlg.GetPath())

    def _on_edit_tags(self, _evt) -> None:
        """Open an episode's audio in the Tag and Chapter Editor."""
        from podharvest import tags as tags_mod
        from podharvest.editor import edit_file

        path = self._episode_audio_to_edit()
        if path is None:
            return
        if not tags_mod.is_taggable(path):
            wx.MessageBox(
                f"{path.name} is not a file type this editor can tag. MP3, M4A, "
                "M4B and MP4 can be edited; the others are left alone rather "
                "than half-supported.",
                "Cannot edit this file", wx.OK | wx.ICON_INFORMATION, self)
            return
        edit_file(
            self,
            path,
            settings=self.settings,
            on_settings_changed=lambda: config_mod.save(self.app_space, self.settings),
        )

    def _on_about(self, _evt) -> None:
        from podharvest import HOMEPAGE, SUPPORT_EMAIL
        wx.MessageBox(
            f"{DISPLAY_NAME} {__version__}\n\n"
            "Archive any RSS/Atom/podcast feed as Markdown, HTML, plain text and "
            "JSON, download every enclosure, and transcribe the audio on this "
            "machine. Optional cloud providers are available with your own API "
            "key.\n\n"
            "It also works on audio you already have. Switch Source to Local "
            "files to transcribe, summarise, chapter, tag and play your own "
            "recordings -- podHarvest is a full MP3 tag and chapter editor "
            "whether or not a feed is involved.\n\n"
            f"{HOMEPAGE}\n"
            f"Support: {SUPPORT_EMAIL}\n\n"
            "When writing in, the activity log (Ctrl+L) is the single most "
            "useful thing to include: it says in plain words what happened.\n\n"
            "The menu bar (Alt or F10) groups everything by what it acts on: "
            "File chooses the podcast or the files, Episode acts on whichever "
            "one is highlighted, View moves focus, and Tools looks after the "
            "models and this machine.\n\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+R        Start\n"
            "  Esc           Cancel\n"
            "  Ctrl+K        Find a podcast\n"
            "  Ctrl+Shift+K  Favourite podcasts\n"
            "  Ctrl+Shift+E  Show the episodes in this feed\n"
            "  Ctrl+O        Add local files\n"
            "  Ctrl+Shift+F  Add a local folder\n"
            "  Ctrl+E        Go to episode list\n"
            "  Ctrl+L        Go to activity log\n"
            "  Ctrl+P        Play or pause the selected episode\n"
            "  Ctrl+B        Rewind\n"
            "  Ctrl+F        Forward\n"
            "  Ctrl+T        Edit tags and chapters\n"
            "  Ctrl+D        Re-detect hardware\n"
            "  Ctrl+comma    Settings\n"
            "  Ctrl+Shift+O  Open output folder\n"
            "  Ctrl+Shift+M  Minimise to the notification area\n"
            "  Ctrl+Shift+R  Refresh the library\n"
            "  Ctrl+Shift+T  Read the transcript\n"
            "  F1            Explain this window and the control you are on",
            f"About {DISPLAY_NAME}", wx.OK | wx.ICON_INFORMATION, self)

    # -- UI construction -----------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(self._build_source_box(panel), 0, wx.EXPAND | wx.ALL, 10)
        self._feed_box = self._build_feed_box(panel)
        outer.Add(self._feed_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self._local_box = self._build_local_box(panel)
        outer.Add(self._local_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self._build_output_box(panel), 0, wx.EXPAND | wx.ALL, 10)
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
        # Five columns whose *headings* change with what the list is showing.
        # A screen reader reads the heading with each cell, so leaving them on
        # "Status, Progress" while the list holds a library would have it
        # announce the wrong thing on every row.
        for heading, width in _LIBRARY_COLUMNS:
            self.episode_list.AppendColumn(heading, width=width)
        set_accessible_name(self.episode_list, "Episodes")
        # Enter or a double-click on a row opens that episode in the editor,
        # which is where somebody who has just heard a rough chapter boundary
        # will reach first.
        self.episode_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED,
                               lambda _e: self._on_edit_tags(None))
        # Selecting a row arms the transport below; it does not open the file.
        self.episode_list.Bind(wx.EVT_LIST_ITEM_SELECTED,
                               lambda _e: self._on_episode_selected())
        self.episode_list.Bind(wx.EVT_LIST_ITEM_DESELECTED,
                               lambda _e: self._on_episode_selected())
        self.episode_list.SetToolTip("Every episode in this run and how far along it is. "
                                     "Arrow up and down to review them at any time.")
        outer.Add(self.episode_list, 1, wx.EXPAND | wx.ALL, 10)

        outer.Add(self._build_playback_box(panel), 0,
                  wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        log_label = wx.StaticText(panel, label="Activity log:")
        outer.Add(log_label, 0, wx.LEFT | wx.RIGHT, 10)
        # Word-wrapped, not TE_DONTWRAP: every line here is a prose sentence
        # ("Episode 3 of 40: starting on '...'. This can take a few minutes."),
        # and making somebody scroll sideways to read the end of a sentence is
        # a poor trade for the column alignment a log like this never had.
        self.log_ctrl = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.log_ctrl.SetToolTip("Everything podHarvest is doing, in ordinary words, "
                                 "including anything that went wrong. Read-only: arrow "
                                 "through it, or select and copy. Ctrl+L jumps here "
                                 "from anywhere.")
        # A floor, not a ceiling: the sizer still stretches it to fill the
        # window, but it never collapses to a two-line slot in a short one.
        size_for_text(self.log_ctrl, lines=8)
        set_accessible_name(self.log_ctrl, "Activity log")
        outer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # A text line beside the gauge: a wx.Gauge reports a bare number, which
        # says nothing about which episode is running or how much is left.
        self.progress_text = wx.StaticText(panel, label="Nothing running yet.")
        outer.Add(self.progress_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.progress = wx.Gauge(panel, range=100)
        self.progress.SetToolTip("How far through the whole run you are. The line just "
                                 "above says which episode is being worked on and how "
                                 "much is left, which a bare percentage cannot.")
        set_accessible_name(self.progress, "Overall progress")
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(outer)
        self._outer = outer
        # Both source boxes are built; only one is ever shown. Doing it here,
        # after the sizer is set, means the window opens on whichever source
        # was last used rather than flickering through the other one.
        self._apply_source_mode(refresh=False)

    def _build_playback_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        """Play the selected episode, without opening anything.

        Listening to what you just downloaded should not require going through
        an editor. The transport is the same one the Tag and Chapter Editor
        uses -- play, stop, rewind and forward ten seconds, volume, mute and
        speed -- so the two behave alike, and the volume you set in one is the
        volume you get in the other.

        Everything here is disabled until an episode is selected, because a
        transport with nothing loaded is a row of controls that lie about what
        they will do.
        """
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Playback")
        holder = box.GetStaticBox()

        self.now_playing = wx.StaticText(
            holder, label="Select an episode to play it.")
        set_accessible_name(self.now_playing, "Now playing")
        box.Add(self.now_playing, 0, wx.ALL, 6)

        self.player = PlayerPanel(
            holder,
            announce=self._announce_playback,
            volume=self.settings.preview_volume,
            muted=self.settings.preview_muted,
            on_volume=self._remember_playback_volume,
            skip_back_ms=self.settings.skip_back_ms,
            skip_forward_ms=self.settings.skip_forward_ms,
            rates=self.settings.playback_rates,
        )
        box.Add(self.player, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.player.Enable(False)
        # Stored as it plays rather than only on close, so a crash or a pulled
        # power cable still leaves a usable place to come back to.
        self.player.set_tick_handler(self._remember_playback_position)
        return box

    def _announce_playback(self, text: str) -> None:
        """Playback has nowhere to speak but the log, which is where it goes."""
        LOG.info("%s", text)

    def _remember_playback_volume(self, level: int, muted: bool) -> None:
        """Keep the level across sessions, and across the two players."""
        self.settings.preview_volume = level
        self.settings.preview_muted = muted
        config_mod.save(self.app_space, self.settings)

    def _on_episode_selected(self) -> None:
        """Enable the transport for the highlighted episode, or disable it.

        The file is not opened here. Arrowing down a list of forty episodes
        should not touch the disk forty times, and an episode still downloading
        has nothing to open yet -- so loading waits for Play.
        """
        local = self._selected_local_file()
        if local is not None:
            # A local row is the file, so the readout says the file's name --
            # two recordings can easily share a title, and the name is what
            # tells them apart.
            there = local.path.is_file()
            self.player.Enable(there)
            self.now_playing.SetLabel(
                f"Ready to play: {local.path.name}" if there
                else f"That file is no longer there: {local.path}")
            return
        episode = self._selected_library_episode()
        if episode is not None:
            # A library row knows exactly what it has, so the readout can be
            # specific rather than hopeful.
            self.player.Enable(episode.has_audio)
            self.now_playing.SetLabel(
                f"Ready to play: {episode.title}" if episode.has_audio
                else f"No audio downloaded for: {episode.title}")
            return
        title = self._selected_episode_title()
        if not title:
            self.player.Enable(False)
            self.now_playing.SetLabel("Select an episode to play it.")
            return
        self.player.Enable(True)
        if self._loaded_audio_title != title:
            self.now_playing.SetLabel(f"Ready to play: {title}")

    def _on_play_selected(self) -> None:
        """Load the selected episode if it is not loaded, then play or pause."""
        local = self._selected_local_file()
        title = local.path.name if local is not None else self._selected_episode_title()
        if not title:
            LOG.info("Select an episode first, then press Play.")
            return
        # A local file is identified by its path: two recordings can share a
        # title, and reloading the wrong one because the titles matched would
        # play the wrong audio.
        already = (self._loaded_audio_path == local.path if local is not None
                   else self._loaded_audio_title == title)
        if not already:
            # Leaving one episode for another: keep the place in the old one.
            self._remember_playback_position(force=True)
            path = local.path if local is not None else self._selected_episode_audio()
            if path is None:
                LOG.info("There is no audio file for '%s' yet. It may still be "
                         "downloading, or this run did not download it.", title)
                self.now_playing.SetLabel(f"No audio yet for: {title}")
                return
            if not self.player.load(path):
                self.now_playing.SetLabel(f"Cannot play: {path.name}")
                return
            self._loaded_audio_title = title
            self._loaded_audio_path = path
            self.now_playing.SetLabel(f"Playing: {title}")
            self._resume_if_remembered(path, title)
        self.player.toggle()

    def _resume_if_remembered(self, path, title: str) -> None:
        """Pick the episode up where it was left, and say so.

        Said out loud because it is a surprise otherwise: playback starting
        forty minutes in looks like a bug unless something tells you why.
        """
        if not self.settings.remember_playback_position:
            return
        from podharvest import positions

        resume_ms = positions.load(self.app_space.config_dir, path)
        if resume_ms <= 0:
            return
        self.player.seek_to(resume_ms)
        from podharvest.audio_tags_core import format_time_precise

        where = format_time_precise(resume_ms)
        self.now_playing.SetLabel(f"Playing: {title} (resumed at {where})")
        LOG.info("Picking '%s' up where you left off, at %s.", title, where)

    def _remember_playback_position(self, *, force: bool = False) -> None:
        """Store the playhead for the loaded file. Never raises.

        Throttled: the transport ticks ten times a second, and writing a file
        at that rate to record something that changes by a tenth of a second is
        a lot of disk for no benefit. Every few seconds is close enough to
        return to, and *force* covers closing and switching episodes, where the
        last few seconds actually matter.
        """
        if not self.settings.remember_playback_position:
            return
        path = getattr(self, "_loaded_audio_path", None)
        if path is None:
            return
        now = time.monotonic()
        if not force and now - self._position_saved_at < POSITION_SAVE_SECONDS:
            return
        self._position_saved_at = now
        from podharvest import positions

        positions.save(self.app_space.config_dir, path,
                       self.player.playhead_ms(), self.player.length_ms())

    def _selected_episode_audio(self):
        """The audio for the highlighted episode, or None. Never asks.

        A library row already knows its path, recorded when it was downloaded,
        so it is used directly. Only a progress row -- mid-run, before the
        library has been rebuilt -- has to be matched by title.
        """
        from pathlib import Path

        from podharvest import tags as tags_mod

        local = self._selected_local_file()
        if local is not None:
            return local.path
        episode = self._selected_library_episode()
        if episode is not None:
            return episode.audio
        title = self._selected_episode_title()
        if not title:
            return None
        output = Path(self.output_ctrl.GetValue().strip() or ".")
        return tags_mod.find_episode_audio(output, title)

    def _build_source_box(self, panel: wx.Panel) -> wx.BoxSizer:
        """Feed, or files you already have. The choice that shapes the window.

        A radio box rather than a tab control or a pair of check boxes: it is
        announced as one named group with a count ("Source, Podcast feed, 1 of
        2"), arrow keys move between the two, and there is no way to end up
        with both or neither. Changing it swaps the box below and relabels the
        Start button, so the window always describes what it is about to do.
        """
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.mode_radio = wx.RadioBox(
            panel, label="Source",
            choices=["Podcast &feed", "&Local files"],
            majorDimension=2, style=wx.RA_SPECIFY_COLS)
        self.mode_radio.SetToolTip(
            "Podcast feed harvests a show from the internet. Local files works "
            "on audio already on this machine -- a folder of recordings, an "
            "audiobook, anything you have -- transcribing it, summarising it, "
            "and letting you edit its tags and chapter markers. Everything "
            "below applies to whichever you pick."
        )
        set_accessible_name(self.mode_radio, "Source")
        self.mode_radio.SetSelection(
            1 if self.settings.source_mode == "local" else 0)
        self.mode_radio.Bind(wx.EVT_RADIOBOX, self._on_source_mode)
        row.Add(self.mode_radio, 0, wx.RIGHT, 12)
        return row

    def source_mode(self) -> str:
        """Which source the window is on: ``"feed"`` or ``"local"``."""
        return "local" if self.mode_radio.GetSelection() == 1 else "feed"

    def _build_local_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        """Adding and removing the files to work on.

        There is no second list here on purpose. The files you add appear in
        the Episodes list below -- the same list that shows a harvest, and the
        same list Play, Edit and Read the transcript already read from. A box
        with its own list would mean two places to look and two things to keep
        in step.
        """
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Local files")
        holder = box.GetStaticBox()

        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler, tip in (
            ("&Add files...",
             self._on_add_files,
             "Choose one or more audio files. They appear in the Episodes list "
             "below, where you can play them or edit their tags straight away "
             "-- you do not have to press Start first."),
            ("Add a &folder...",
             self._on_add_folder,
             "Choose a folder and take the audio in it. Subfolders are "
             "included unless you turn that off in Settings."),
            ("&Remove",
             self._on_remove_files,
             "Takes the highlighted file out of this list. Your file is not "
             "deleted, moved or changed."),
            ("&Clear list",
             self._on_clear_files,
             "Empties the list. Your files are not touched."),
        ):
            btn = wx.Button(holder, label=label)
            btn.SetToolTip(tip)
            btn.Bind(wx.EVT_BUTTON, handler)
            row.Add(btn, 0, wx.RIGHT, 6)
            self._local_buttons.append(btn)
        box.Add(row, 0, wx.ALL, 8)

        self.local_summary = wx.StaticText(
            holder, label="No files added yet.")
        set_accessible_name(self.local_summary, "Files added")
        box.Add(self.local_summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        return box

    # -- adding and removing local files ----------------------------------

    def _on_add_files(self, _evt=None) -> None:
        from podharvest import localfiles

        with wx.FileDialog(
            self, "Choose audio files", wildcard=localfiles.WILDCARD,
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            self._add_local([Path(p) for p in dlg.GetPaths()])

    def _on_add_folder(self, _evt=None) -> None:
        with wx.DirDialog(
            self, "Choose a folder of audio",
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            self._add_local([Path(dlg.GetPath())])

    def _add_local(self, paths) -> None:
        """Take what was chosen, expand folders, and say what arrived.

        Said in the log rather than a dialog: adding files is something you do
        several times in a row, and a modal after each one would be in the way.
        """
        from podharvest import localfiles

        before = len(self._local_paths)
        found = localfiles.collect(paths, recursive=self.settings.local_recurse_folders)
        known = {str(p).lower() for p in self._local_paths}
        added = [p for p in found if str(p).lower() not in known]
        self._local_paths.extend(added)
        if not added:
            LOG.info("Nothing new to add: %s",
                     "podHarvest found no audio it recognises there."
                     if not found else "those files are already in the list.")
        else:
            LOG.info("Added %d file(s); %d in the list.", len(added),
                     len(self._local_paths))
        if len(self._local_paths) != before:
            if self.source_mode() != "local":
                self.mode_radio.SetSelection(1)
                self._apply_source_mode()
            else:
                self.refresh_local_list()

    def _on_remove_files(self, _evt=None) -> None:
        item = self._local_rows.get(self.episode_list.GetFirstSelected())
        if item is None:
            LOG.info("Highlight a file in the Episodes list first, then press "
                     "Remove. Your files are never deleted by this.")
            return
        self._local_paths = [p for p in self._local_paths if p != item.path]
        LOG.info("Removed %s from the list. The file itself is untouched.",
                 item.path.name)
        self.refresh_local_list()

    def _on_clear_files(self, _evt=None) -> None:
        if not self._local_paths:
            return
        count = len(self._local_paths)
        self._local_paths = []
        LOG.info("Cleared %d file(s) from the list. None of them were touched.",
                 count)
        self.refresh_local_list()

    def refresh_local_list(self) -> None:
        """Show the added files in the Episodes list, with what each has.

        Reads each file's tags, length and chapter count, and looks for a
        transcript beside it -- so somebody who has run podHarvest over this
        folder before can see that at a glance and skip it.
        """
        from podharvest import localfiles

        if self._worker is not None and self._worker.is_alive():
            return  # a run owns the list
        beside = self.settings.local_transcripts_beside_file
        output = Path(self.output_ctrl.GetValue().strip() or ".")
        self.episode_list.DeleteAllItems()
        self._episode_rows = {}
        self._library_rows = {}
        self._local_rows = {}
        self._set_columns(_LOCAL_COLUMNS)
        for path in self._local_paths:
            item = localfiles.describe(path, beside=beside, output_dir=output)
            row = self.episode_list.InsertItem(
                self.episode_list.GetItemCount(), path.name)
            self.episode_list.SetItem(row, 1, item.display_title)
            self.episode_list.SetItem(row, 2, item.what_it_has())
            self.episode_list.SetItem(row, 3, str(path.parent))
            self.episode_list.SetItem(
                row, 4, spoken_duration(item.duration_seconds)
                if item.duration_seconds else "")
            self._local_rows[row] = item
        count = len(self._local_paths)
        self.local_summary.SetLabel(
            "No files added yet." if not count else
            f"{count} file{'s' if count != 1 else ''} ready. "
            "They are listed below; press Start to transcribe them.")
        self._on_episode_selected()

    def _on_source_mode(self, _evt=None) -> None:
        self._apply_source_mode()
        self.settings.source_mode = self.source_mode()
        config_mod.save(self.app_space, self.settings)

    def _apply_source_mode(self, *, refresh: bool = True) -> None:
        """Swap the window over to whichever source is chosen.

        Three things change together, and they have to: the input box above,
        the Start button's wording, and what the Episodes list is showing.
        Leaving any one of them behind would have the window describing work
        it is not about to do.
        """
        local = self.source_mode() == "local"
        self._outer.Show(self._feed_box, not local, recursive=True)
        self._outer.Show(self._local_box, local, recursive=True)
        # Downloading is a feed idea; a local file is already here.
        self.chk_download.Enable(not local)
        self.start_btn.SetLabel("&Start" if not local else "&Start on these files")
        set_accessible_name(self.start_btn,
                            self.start_btn.GetLabel().replace("&", ""))
        self.start_btn.SetToolTip(
            "Begin the harvest. Everything above is saved first."
            if not local else
            "Transcribe the files in the list, summarise them and add chapter "
            "markers, following the options above. Files that already have a "
            "transcript are left alone."
        )
        # Skipped while the window is still being built: the output folder
        # has not been read out of the settings yet, so a refresh then would
        # scan the wrong folder and say so in the log.
        self._describe_output()
        if refresh:
            if local:
                self.refresh_local_list()
            else:
                self.refresh_library()
        self._outer.Layout()
        self.Layout()

    def _build_feed_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Feed")
        holder = box.GetStaticBox()
        grid = wx.FlexGridSizer(2, 3, 8, 8)
        grid.AddGrowableCol(1, 1)

        url_label = wx.StaticText(holder, label="Feed &URL:")
        self.url_ctrl = wx.TextCtrl(holder, value="")
        self.url_ctrl.SetToolTip(
            "The podcast's address. The show's ordinary web page usually works too -- "
            "podHarvest will find the feed itself."
        )
        set_accessible_name(self.url_ctrl, "Feed URL")
        # The tooltip belongs on the control, not the label: a StaticText never
        # takes focus, so a keyboard user would never encounter it there.
        self.url_ctrl.SetToolTip("The RSS or Atom feed to harvest. A podcast's web "
                                 "page usually works too - its feed is discovered "
                                 "automatically.")
        self.url_ctrl.SetHint("https://example.com/feed")
        find_btn = wx.Button(holder, label="&Find...")
        find_btn.SetToolTip(
            "Search Apple's podcast directory by name, so you do not "
            "have to hunt for a feed address. Ctrl+K opens it from "
            "anywhere."
        )
        find_btn.Bind(wx.EVT_BUTTON, self._on_find_podcast)
        grid.Add(url_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.url_ctrl, 1, wx.EXPAND)
        grid.Add(find_btn, 0)

        # Label before control, so a screen reader pairs the two.
        match_label = wx.StaticText(holder, label="Only episodes &matching:")
        self.match_ctrl = wx.TextCtrl(holder, value="")
        self.match_ctrl.SetToolTip(
            "Leave empty for every episode. Otherwise only episodes whose "
            "title contains what you type -- all of the words, in any order, "
            "ignoring case. Applied before the episode limit, so \"5 episodes "
            "matching badger\" means five about badgers rather than any "
            "badgers among the five most recent."
        )
        self.match_ctrl.SetHint("part of an episode title")
        set_accessible_name(self.match_ctrl, "Only episodes matching")
        grid.Add(match_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.match_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(holder, label=""))

        box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.browse_btn = wx.Button(holder, label="Show &episodes")
        self.browse_btn.SetToolTip(
            "Reads the feed and lists its episodes below, without "
            "downloading anything. The way to see what a show has "
            "before deciding to harvest it."
        )
        self.browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_feed)
        row.Add(self.browse_btn, 0, wx.RIGHT, 6)

        fav_btn = wx.Button(holder, label="Fa&vourites...")
        fav_btn.SetToolTip(
            "The shows you have marked, to come back to without "
            "searching again. Bookmarks, not subscriptions: nothing "
            "is checked or downloaded for you."
        )
        fav_btn.Bind(wx.EVT_BUTTON, self._on_favorites)
        row.Add(fav_btn, 0, wx.RIGHT, 6)

        self.add_fav_btn = wx.Button(holder, label="&Add to favourites")
        self.add_fav_btn.SetToolTip(
            "Remembers the feed address above, under the name the "
            "feed gives itself once it has been read."
        )
        self.add_fav_btn.Bind(wx.EVT_BUTTON, self._on_add_favorite)
        row.Add(self.add_fav_btn, 0)
        box.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        return box

    # -- finding a podcast ------------------------------------------------

    def _on_find_podcast(self, _evt=None) -> None:
        """Search the directory, and take whatever was chosen.

        Switches to the feed source first: choosing a podcast while the window
        is on Local files would put an address into a box nobody can see.
        """
        from podharvest.discover import SearchDialog

        if self.source_mode() != "feed":
            self.mode_radio.SetSelection(0)
            self._apply_source_mode()
        dlg = SearchDialog(self, self.app_space, self.settings)
        try:
            if dlg.ShowModal() != wx.ID_OK or dlg.chosen is None:
                return
            chosen = dlg.chosen
        finally:
            dlg.Destroy()
        self.url_ctrl.SetValue(chosen.feed_url)
        self._browsed_title = chosen.title
        LOG.info("Chose '%s'. Press Show episodes to see what it has, or "
                 "Start to harvest it.", chosen.display_name)
        self.browse_btn.SetFocus()

    def _on_favorites(self, _evt=None) -> None:
        """Open the favourites list and take whatever was chosen."""
        from podharvest.discover import FavoritesDialog

        dlg = FavoritesDialog(self, self.app_space)
        try:
            if dlg.ShowModal() != wx.ID_OK or dlg.chosen is None:
                return
            chosen = dlg.chosen
        finally:
            dlg.Destroy()
        if self.source_mode() != "feed":
            self.mode_radio.SetSelection(0)
            self._apply_source_mode()
        self.url_ctrl.SetValue(chosen.feed_url)
        self._browsed_title = chosen.title
        LOG.info("Chose '%s' from your favourites.", chosen.display_name)
        self.browse_btn.SetFocus()

    def _on_add_favorite(self, _evt=None) -> None:
        """Remember whatever feed address is in the box.

        Saved under the feed's own name when one is known -- from a search
        result or from having browsed it -- and under the address otherwise,
        which is at least honest about what it is.
        """
        from podharvest import favorites as favorites_mod

        url = self.url_ctrl.GetValue().strip()
        if not url:
            LOG.info("Put a feed address in the box first, or use Find to "
                     "search the directory for one.")
            self.url_ctrl.SetFocus()
            return
        favorite = favorites_mod.Favorite(
            title=getattr(self, "_browsed_title", "") or url, feed_url=url)
        _changed, message = favorites_mod.add(self.app_space, favorite)
        LOG.info("%s", message)

    # -- browsing a feed ---------------------------------------------------

    def _on_browse_feed(self, _evt=None) -> None:
        """Read the feed and list its episodes, downloading nothing."""
        url = self.url_ctrl.GetValue().strip()
        if not url:
            wx.MessageBox(
                "Put a feed address in the box first, or use Find to search "
                "the podcast directory for one.",
                "Nothing to read", wx.OK | wx.ICON_WARNING, self)
            self.url_ctrl.SetFocus()
            return
        if self._worker is not None and self._worker.is_alive():
            LOG.info("Something is already running; wait for it to finish.")
            return
        self.browse_btn.Disable()
        self.start_btn.Disable()
        self._set_progress_text("Reading " + url + "...")
        LOG.info("Reading the feed at %s. Nothing is downloaded by this.", url)
        self._worker = threading.Thread(
            target=self._run_browse_worker, args=(url,), daemon=True)
        self._worker.start()

    def _run_browse_worker(self, url: str) -> None:
        from podharvest import directory as directory_mod

        episodes, title, error = [], "", ""
        try:
            from podharvest.feed import fetch_and_parse
            from podharvest.net import HttpClient

            # A pasted Apple show link is a reasonable thing to try, so turn
            # it into a feed address rather than failing to parse a web page.
            resolved = directory_mod.feed_url_for(
                url, country=self.settings.itunes_country,
                settings=self.settings) or url

            client = HttpClient(retries=max(0, self.settings.download_retries))
            feed = fetch_and_parse(
                resolved, client,
                follow_pagination=self.settings.follow_pagination)
            title = feed.title
            episodes = list(feed.episodes)
        except Exception as exc:  # noqa: BLE001 - surfaced to the log pane
            error = str(exc)
            LOG.exception("Could not read the feed: %s", exc)
        wx.CallAfter(self._show_browsed, episodes, title, error)

    def _show_browsed(self, episodes, title: str, error: str) -> None:
        """Put a browsed feed's episodes in the list.

        A third thing the list can be, after the library and the local files,
        so the columns change again: these episodes are not on disk, and a
        heading promising what you have would be wrong in every row.
        """
        from podharvest.harvest import match_episodes

        self._worker = None
        self.browse_btn.Enable()
        self.start_btn.Enable()
        if error:
            self._set_progress_text("Could not read that feed.")
            wx.MessageBox(
                "Could not read that feed.\n\n" + error + "\n\nThe activity "
                "log has the details.",
                "Could not read the feed", wx.OK | wx.ICON_ERROR, self)
            return

        self._browsed_title = title
        self.episode_list.DeleteAllItems()
        self._episode_rows = {}
        self._library_rows = {}
        self._local_rows = {}
        self._browsed_rows = {}
        self._set_columns(_BROWSE_COLUMNS)

        # Shown through the same filter a run would use, so what you see here
        # is what Start would actually take.
        shown = match_episodes(episodes, self.settings.episode_match)
        for number, episode in enumerate(shown, 1):
            row = self.episode_list.InsertItem(
                self.episode_list.GetItemCount(), str(number))
            self.episode_list.SetItem(row, 1, episode.title)
            when = (episode.published.strftime("%Y-%m-%d")
                    if episode.published else "")
            self.episode_list.SetItem(row, 2, when)
            self.episode_list.SetItem(
                row, 3, spoken_duration(episode.duration_seconds)
                if episode.duration_seconds else "")
            has = []
            if episode.enclosures:
                has.append("audio")
            if episode.transcripts:
                has.append("a published transcript")
            self.episode_list.SetItem(
                row, 4, ", ".join(has) or "nothing to download")
            self._browsed_rows[row] = episode

        filtered = len(episodes) - len(shown)
        note = ", " + str(filtered) + " filtered out" if filtered else ""
        self._set_progress_text(
            "'" + title + "' has " + str(len(episodes)) + " episode(s)" + note
            + ". Nothing has been downloaded; press Start when you want to.")
        LOG.info("'%s': %d episode(s)%s. Nothing downloaded yet.",
                 title, len(episodes), note)
        # Nothing here is on disk, so the transport has nothing to open.
        self.player.Enable(False)
        self.now_playing.SetLabel(
            "These episodes are not downloaded yet, so there is nothing to "
            "play. Press Start to harvest them.")
        if shown:
            self.episode_list.Select(0)
            self.episode_list.Focus(0)
        self.episode_list.SetFocus()

    def _build_output_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        """Where the library lives. Shown for both sources, because both use it.

        A harvest is written here. Local files are not -- their transcripts go
        beside the audio unless you say otherwise in Settings -- but this is
        still the folder the Episodes list reads when it is showing your
        library, so it never goes away.
        """
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Library folder")
        self._output_holder = holder = box.GetStaticBox()
        grid = wx.FlexGridSizer(1, 3, 8, 8)
        grid.AddGrowableCol(1, 1)

        out_label = wx.StaticText(holder, label="&Output folder:")
        self.output_ctrl = wx.TextCtrl(holder, value=str(self.app_space.default_output_dir))
        self.output_ctrl.SetToolTip(
            "The folder your library is built in. One subfolder per podcast, one entry per "
            "episode; everything stays a normal file you own."
        )
        set_accessible_name(self.output_ctrl, "Output folder")
        browse = wx.Button(holder, label="B&rowse...")
        browse.SetToolTip(
            "Picks the folder with the system folder chooser."
        )
        browse.Bind(wx.EVT_BUTTON, self._on_browse_output)
        grid.Add(out_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.output_ctrl, 1, wx.EXPAND)
        grid.Add(browse, 0)

        # Where the output actually lands, in words, because "Output folder"
        # answers a different question in each source and a box that means two
        # things without saying which is worse than two boxes.
        self.output_note = wx.StaticText(holder, label="")
        set_accessible_name(self.output_note, "Where the output goes")
        box.Add(self.output_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        return box

    def _describe_output(self) -> None:
        """Say where this source's output goes, and label the box to match.

        In local mode the feeds folder is not where anything lands -- the
        transcript goes next to the audio -- and leaving a box labelled
        "Library folder" as the only visible destination invited the
        reasonable conclusion that podHarvest was about to write there.
        """
        local = self.source_mode() == "local"
        beside = self.settings.local_transcripts_beside_file
        if not local:
            self._output_holder.SetLabel("Library folder")
            self.output_note.SetLabel(
                "Each podcast gets a folder here, with its audio, transcripts "
                "and notes.")
        elif beside:
            self._output_holder.SetLabel("Library folder (feeds)")
            self.output_note.SetLabel(
                "Local files: each transcript is written next to its own audio "
                "file, not here. This folder is only your harvested library, "
                "which the Episodes list reads when the source is a feed.")
        else:
            self._output_holder.SetLabel("Library folder")
            self.output_note.SetLabel(
                'Local files: transcripts go into a "Local files" folder here, '
                'because "Write transcripts beside the audio file" is turned '
                "off in Settings.")

    def _build_options_box(self, panel: wx.Panel) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.HORIZONTAL, panel, "Options")
        holder = box.GetStaticBox()

        left = wx.BoxSizer(wx.VERTICAL)
        self.chk_download = wx.CheckBox(holder, label="&Download enclosures (audio/video/etc.)")
        self.chk_download.SetToolTip(
            "Downloads each episode's audio. Without it you get the show notes and feed data "
            "but nothing to listen to or transcribe."
        )
        self.chk_download.SetValue(True)
        self.chk_transcribe = wx.CheckBox(holder, label="&Transcribe downloaded audio on-device")
        self.chk_transcribe.SetToolTip(
            "Turns each downloaded episode into a written transcript on this machine. This is "
            "the slow part of a run; the model picker beside it says how slow."
        )
        self.chk_transcribe.Bind(wx.EVT_CHECKBOX, self._on_toggle_transcribe)
        limit_row = wx.BoxSizer(wx.HORIZONTAL)
        limit_row.Add(wx.StaticText(holder, label="Limit episodes (0 = all):"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.limit_ctrl = wx.SpinCtrl(holder, min=0, max=100000, initial=0)
        self.limit_ctrl.SetToolTip(
            "How many episodes to fetch, newest first. Zero means every episode in the feed."
        )
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
            choices=["&All", "On this &machine", "In the c&loud",
                     "Already &downloaded"],
            majorDimension=4, style=wx.RA_SPECIFY_COLS)
        self.source_radio.SetToolTip(
            "Which models the picker offers: everything, only those that run "
            "on this machine, only cloud ones, or only the ones already "
            "downloaded here. \"Already downloaded\" is the quick way back to "
            "a model you have used before, with nothing to wait for. Options "
            "that cannot apply are switched off rather than offered and then "
            "refused - cloud needs an API key, and Already downloaded needs "
            "something to have been downloaded."
        )
        # Nothing is known about this machine yet, so there is no honest
        # choice to offer. It is switched on once hardware detection has said
        # what is available -- see `_refresh_source_options`.
        self.source_radio.Enable(False)
        set_accessible_name(self.source_radio, "Show models that run")
        self.source_radio.Bind(wx.EVT_RADIOBOX, self._on_source_changed)

        self.model_choice = wx.Choice(right_holder)
        self.model_choice.SetToolTip(
            "Which model writes the transcripts. The box below says what it will cost you in "
            "time for the podcast you have loaded."
        )
        set_accessible_name(self.model_choice, "Transcription model")
        self.model_choice.Bind(wx.EVT_CHOICE, self._on_model_changed)

        # Read-only and multi-line so it is a real tab stop that can be arrowed
        # through line by line. A tooltip cannot be read that way, and a
        # StaticText cannot take focus at all.
        self.model_info = wx.TextCtrl(
            right_holder, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        # The longest of the three: it holds several sentences about speed,
        # accuracy and download size, and scrolling to read an answer you
        # asked for is worse than a slightly taller box.
        size_for_text(self.model_info, lines=10)
        self.model_info.SetToolTip(
            "What the selected transcription model will cost you in time for the podcast you "
            "have loaded, measured on this machine where possible. Read-only."
        )
        set_accessible_name(self.model_info, "About the selected model")

        # Whether this model can actually run, answered before you press Start
        # rather than several minutes into a run. A model is two separate
        # downloads -- the engine's Python packages and the model weights --
        # and either can be missing, so the readout names which.
        self.model_ready = wx.StaticText(right_holder, label="Checking...")
        set_accessible_name(self.model_ready, "Whether this model is ready")
        self.download_btn = wx.Button(right_holder, label="&Download model")
        self.download_btn.SetToolTip(
            "Fetches everything the selected model needs -- the engine's "
            "Python packages and the model itself -- so the first run does not "
            "stop to do it. Safe to press at any time: anything already here "
            "is kept, and nothing else is touched. It can take several minutes "
            "and a few gigabytes on a first run."
        )
        self.download_btn.Bind(wx.EVT_BUTTON, self._on_download_model)

        self.chk_timestamps = wx.CheckBox(right_holder, label="&Include timestamps")
        self.chk_timestamps.SetToolTip(
            "Puts a clock time against each line of the transcript, so a passage can be found "
            "in the audio."
        )
        self.chk_timestamps.SetValue(True)
        self.chk_timestamps.Bind(wx.EVT_CHECKBOX, self._on_toggle_timestamp_style)
        self.chk_speakers = wx.CheckBox(right_holder, label="Identify spea&kers (diarization)")
        self.chk_speakers.SetToolTip(
            "Works out who is speaking and labels each line. Adds time, and needs a Hugging "
            "Face token for the pyannote models unless you use a cloud provider that labels "
            "speakers itself."
        )
        self.chk_speakers.Bind(wx.EVT_CHECKBOX, self._on_toggle_speaker_style)

        ts_row = wx.BoxSizer(wx.HORIZONTAL)
        ts_row.Add(wx.StaticText(right_holder, label="Timestamp style:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.timestamp_style_choice = wx.Choice(right_holder, choices=["[00:00:00] bracket", "(00:00:00) paren"])
        self.timestamp_style_choice.SetToolTip(
            "How a timestamp is written in the transcript: in square brackets or in "
            "parentheses."
        )
        set_accessible_name(self.timestamp_style_choice, "Timestamp style")
        self.timestamp_style_choice.SetSelection(0)
        ts_row.Add(self.timestamp_style_choice, 1)

        sp_row = wx.BoxSizer(wx.HORIZONTAL)
        sp_row.Add(wx.StaticText(right_holder, label="Speaker label style:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.speaker_style_choice = wx.Choice(
            right_holder, choices=["**Speaker:** bold", "Speaker: plain", "(Speaker) inline"])
        self.speaker_style_choice.SetToolTip(
            "How a speaker's name is written in the transcript: bold, plain, or inline in the "
            "line."
        )
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
        self.chk_paragraphs.SetToolTip(
            "Merges consecutive lines from the same speaker into paragraphs, which reads "
            "better than one line per phrase."
        )

        width_row = wx.BoxSizer(wx.HORIZONTAL)
        width_row.Add(wx.StaticText(right_holder, label="Wrap plain text at (0 = no wrap):"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.line_width_ctrl = wx.SpinCtrl(right_holder, min=0, max=400, initial=0)
        self.line_width_ctrl.SetToolTip(
            "Wraps the plain-text transcript at this many characters. Zero leaves the lines "
            "unwrapped."
        )
        set_accessible_name(self.line_width_ctrl, "Plain text line width")
        width_row.Add(self.line_width_ctrl, 0)

        right_box.Add(self.source_radio, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(wx.StaticText(right_holder, label="Model:"), 0, wx.BOTTOM, 2)
        right_box.Add(self.model_choice, 0, wx.EXPAND | wx.BOTTOM, 6)
        right_box.Add(wx.StaticText(right_holder, label="About this model:"), 0, wx.BOTTOM, 2)
        right_box.Add(self.model_info, 1, wx.EXPAND | wx.BOTTOM, 6)
        # Label before button, so a screen reader reaches the sentence that
        # explains why the button is there before it reaches the button.
        ready_row = wx.BoxSizer(wx.HORIZONTAL)
        ready_row.Add(self.model_ready, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        ready_row.Add(self.download_btn, 0)
        right_box.Add(ready_row, 0, wx.EXPAND | wx.BOTTOM, 6)
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
        refresh_btn.SetToolTip(
            "Probes this machine's processor, memory and graphics again, and refreshes which "
            "models it recommends."
        )
        refresh_btn.Bind(wx.EVT_BUTTON, lambda evt: self.refresh_hardware(force=True))
        row.Add(self.hw_text, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(refresh_btn, 0)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        return box

    def _build_action_row(self, panel: wx.Panel) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn = wx.Button(panel, label="&Start")
        self.start_btn.SetToolTip(
            "Begins the run with the settings above. The Episodes list fills in as it goes, "
            "and this button becomes Open output folder when it finishes."
        )
        self.start_btn.Bind(wx.EVT_BUTTON, self._on_start)
        self.start_btn.Disable()  # re-enabled once the first hardware probe completes
        self.cancel_btn = wx.Button(panel, label="&Cancel")
        self.cancel_btn.SetToolTip(
            "Stops the run at the next safe point. Work already finished stays on disk."
        )
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
        self.match_ctrl.SetValue(s.episode_match)
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
        s.episode_match = self.match_ctrl.GetValue().strip()
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
        s.source_mode = self.source_mode()
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
        # The transport reads its skip amounts and its speeds at construction,
        # so tell it about both.
        self.player.set_skip_steps(
            self.settings.skip_back_ms, self.settings.skip_forward_ms)
        self.player.set_rates(self.settings.playback_rates)
        # Where local transcripts go decides both what the list says each file
        # already has and what the Library folder box means, so both are
        # rebuilt rather than left saying the old answer.
        self._describe_output()
        if self.source_mode() == "local":
            self.refresh_local_list()
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
        # The source picker has its own per-option rules -- a cloud key, and
        # something actually downloaded -- so it is re-decided rather than
        # simply switched back on. If it ends up disabled while it had focus,
        # focus has to go somewhere: back to the checkbox that turned it off.
        had_focus = self.source_radio.HasFocus()
        self._refresh_source_options()
        if had_focus and not self.source_radio.IsEnabled():
            self.chk_transcribe.SetFocus()
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

    _SOURCES = ("all", "local", "cloud", "downloaded")

    def _refresh_cloud_availability(self) -> None:
        """Work out which cloud models could run, then re-offer the choices."""
        from podharvest import cloud as cloud_mod
        self._cloud_models = cloud_mod.available_cloud_models(self.app_space, kind="asr")
        self._refresh_source_options()

    def _refresh_source_options(self) -> None:
        """Offer only the filters that could return something.

        Each option is switched on or off individually rather than the group
        as a whole. An option that is present but cannot work is worse than one
        that is absent: by keyboard it is a stop that accepts the selection and
        then shows an empty model list, with nothing saying why.

        The group itself stays off until hardware detection has found any model
        at all, because before that every option is equally meaningless.
        """
        cloud = list(getattr(self, "_cloud_models", []))
        local = list(getattr(self, "_local_models", []))
        transcribing = self.chk_transcribe.GetValue()
        downloaded = self._downloaded_models() if local else []

        # There is nothing to filter until something is known.
        self.source_radio.Enable(bool(local or cloud) and transcribing)

        self.source_radio.EnableItem(self._SOURCES.index("local"), bool(local))
        self.source_radio.EnableItem(self._SOURCES.index("cloud"), bool(cloud))
        self.source_radio.EnableItem(
            self._SOURCES.index("downloaded"), bool(downloaded))
        # "All" is only a distinct answer when there is more than one source.
        self.source_radio.EnableItem(
            self._SOURCES.index("all"), bool(local and cloud))

        # A selection that has just been switched off would silently filter the
        # list to nothing, so move off it rather than leaving it standing.
        if not self.source_radio.IsItemEnabled(self.source_radio.GetSelection()):
            fallback = "local" if local else ("cloud" if cloud else "all")
            self.source_radio.SetSelection(self._SOURCES.index(fallback))

        parts = []
        if cloud:
            names = ", ".join(sorted({c.provider for c in cloud}))
            parts.append(f"Cloud models are available for: {names}.")
        else:
            parts.append(
                "Add an OpenAI or Google Gemini API key in Settings to use "
                "cloud models. Until then everything runs on this machine.")
        if downloaded:
            parts.append(
                f"{len(downloaded)} model(s) are already downloaded here; "
                "\"Already downloaded\" narrows the list to those, which start "
                "with nothing to wait for.")
        else:
            parts.append(
                "Nothing is downloaded yet, so \"Already downloaded\" is off. "
                "Use Download model, or just start a run.")
        self.source_radio.SetToolTip(" ".join(parts))

    def _downloaded_models(self) -> list:
        """Every on-device model whose weights are already here.

        Cloud models are excluded on purpose: there is nothing to download for
        them, so calling them "downloaded" would be answering a different
        question from the one asked.
        """
        from podharvest import acquire

        found = []
        for choice in self._local_models:
            try:
                if acquire.is_downloaded(self.app_space, choice):
                    found.append(choice)
            except Exception:  # noqa: BLE001 - an unreadable manifest is "no"
                continue
        return found

    def _visible_models(self) -> list:
        source = self._SOURCES[self.source_radio.GetSelection()]
        local = list(self._local_models)
        cloud = list(getattr(self, "_cloud_models", []))
        if not self.source_radio.IsEnabled():
            return local
        if source == "downloaded":
            return self._downloaded_models()
        if source == "local":
            return local
        if source == "cloud":
            return cloud
        if not cloud:
            return local
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
            self.model_ready.SetLabel("No model selected.")
            self.download_btn.Enable(False)
            return
        text = estimate_mod.describe_model(choice, self._estimated_audio_seconds,
                                           getattr(self, "_hw", None), self.app_space)
        self.model_info.SetValue(text)
        self._refresh_model_ready()
        # The first line is the model name; keep the caret at the top so a
        # screen reader starts reading from the beginning.
        self.model_info.SetInsertionPoint(0)

    def _model_readiness(self, choice) -> tuple[bool, str]:
        """Whether *choice* can run right now, and a sentence saying so.

        Two separate things have to be present and either can be missing on its
        own: the engine's Python packages, and the model weights. Naming which
        one is absent is the difference between "press Download" and a support
        email. Cloud models need neither -- they need a key, which the key test
        in Settings answers.
        """
        from podharvest import acquire

        if getattr(choice, "is_cloud", False):
            return True, ("This is a cloud model: nothing to download. It needs "
                          "an API key, which Settings can test.")
        missing = acquire.engine_packages_missing(self.app_space, choice.engine)
        weights = acquire.is_downloaded(self.app_space, choice)
        if not missing and weights:
            return True, f"Ready: {choice.model} is downloaded and can run now."

        wants = []
        if missing:
            wants.append("the " + choice.engine + " engine")
        if not weights:
            wants.append("the model itself")
        return False, ("Not downloaded yet: podHarvest still needs "
                       + " and ".join(wants)
                       + ". Press Download model, or just press Start and it "
                         "will fetch them first.")

    def _refresh_model_ready(self) -> None:
        """Update the readiness line for whatever is selected now."""
        choice = self._selected_model()
        if choice is None:
            self.model_ready.SetLabel("No model selected.")
            self.download_btn.Enable(False)
            return
        running = self._worker is not None and self._worker.is_alive()
        ready, sentence = self._model_readiness(choice)
        self.model_ready.SetLabel(sentence)
        self.download_btn.Enable(not ready and not running)

    def _on_download_model(self, _evt=None) -> None:
        """Fetch the selected model's packages and weights, on a worker thread.

        Deliberately the same calls a run makes, so pressing this and pressing
        Start cannot end up with different ideas of what "downloaded" means.
        """
        choice = self._selected_model()
        if choice is None:
            return
        if self._worker is not None and self._worker.is_alive():
            LOG.info("Something is already running; wait for it to finish.")
            return
        self.download_btn.Disable()
        self.start_btn.Disable()
        self.model_ready.SetLabel(f"Downloading {choice.model}...")
        LOG.info("Downloading everything %s needs. This is a one-time cost and "
                 "can take several minutes.", choice.model)
        self._worker = threading.Thread(
            target=self._run_download_worker, args=(choice,), daemon=True)
        self._worker.start()

    def _run_download_worker(self, choice) -> None:
        from podharvest import acquire

        ok = True
        try:
            if not acquire.ensure_engine_packages(self.app_space, choice.engine):
                ok = False
                LOG.error("Could not set up the %s engine. The lines above say "
                          "why. Nothing was changed.", choice.engine)
            else:
                acquire.acquire_asr_model(self.app_space, choice)
        except Exception as exc:  # noqa: BLE001 - surfaced to the log pane
            ok = False
            LOG.exception("The download stopped with an error: %s", exc)
        finally:
            wx.CallAfter(self._finish_download, ok, choice)

    def _finish_download(self, ok: bool, choice) -> None:
        self._worker = None
        self.start_btn.Enable()
        self._refresh_model_ready()
        # Something just became downloaded, which can turn "Already
        # downloaded" from an impossible filter into a useful one.
        self._refresh_source_options()
        if ok:
            LOG.info("%s is ready. Press Start when you are.", choice.model)
        # Focus goes back to the button that started this, which is where it
        # was: a download that finishes silently with focus somewhere else is
        # a download nobody knows finished.
        target = self.start_btn if ok else self.download_btn
        if target.IsEnabled():
            target.SetFocus()

    def _on_browse_output(self, _evt) -> None:
        with wx.DirDialog(self, "Choose an output folder", defaultPath=self.output_ctrl.GetValue()) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.output_ctrl.SetValue(dlg.GetPath())

    # -- run progress -----------------------------------------------------

    def _run_noun(self, count: int = 1) -> str:
        """"episode" or "file", whichever this run is actually about.

        A run over a folder of recordings that reports "12 episodes finished"
        is describing something that did not happen. The word is read aloud
        with every progress update, so it is worth getting right.
        """
        word = "file" if self.source_mode() == "local" else "episode"
        return word if count == 1 else word + "s"

    def _reset_progress(self) -> None:
        self.episode_list.DeleteAllItems()
        self._episode_rows = {}
        self._episode_percent = {}
        # The list stops being the library -- or the local file list -- the
        # moment a run owns it.
        self._library_rows = {}
        self._local_rows = {}
        self._set_columns(_RUN_COLUMNS)
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
            # The log cannot announce itself, so this is the only thing that
            # reports an episode finishing without you watching for it.
            cues.play("failed" if prog.state == "failed" else "episode",
                      enabled=self.settings.sound_cues)
            self.episode_list.SetItem(row, 4, spoken_duration(prog.elapsed))
            # Keep the newest finished row in view without stealing focus.
            self.episode_list.EnsureVisible(row)
            finished = sum(self._counts.values())
            self._set_progress_text(
                f"{finished} of {prog.total} {self._run_noun(prog.total)} finished, "
                f"{overall}% of everything. "
                f"Last: '{prog.title}' - {prog.state_label.lower()} in "
                f"{spoken_duration(prog.elapsed)}.")
        elif prog.state in {"transcribing", "summarising"}:
            doing = ("transcribing" if prog.state == "transcribing"
                     else "writing the summary for")
            extra = f" ({prog.detail})" if prog.detail else ""
            noun = self._run_noun()
            self._set_progress_text(
                f"{noun.capitalize()} {prog.index} of {prog.total} - {doing} "
                f"'{prog.title}'{extra} - {prog.percent:.0f}% of this {noun}, "
                f"{overall}% of everything.")
        self.SetTitle(f"{overall}% - {DISPLAY_NAME} {__version__}")

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
        # Now that the machine's models are known there is something to
        # filter, so the picker can finally offer honest choices.
        self._refresh_cloud_availability()
        saved = (self.settings.asr_engine, self.settings.asr_model)
        self._populate_models(prefer=saved if saved != ("", "") else None)
        for note in hw.notes:
            LOG.info("Hardware note: %s", note)
        if not self._worker or not self._worker.is_alive():
            self.start_btn.Enable()
        self.GetTopLevelParent().Layout()

    def _on_start(self, _evt) -> None:
        if self.source_mode() == "local":
            self._start_local()
            return
        url = self.url_ctrl.GetValue().strip()
        if not url:
            wx.MessageBox("Please enter a feed URL.", "Missing URL", wx.OK | wx.ICON_WARNING)
            self.url_ctrl.SetFocus()
            return

        model_choice = self._model_for_run()
        if model_choice is False:
            return

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

    def _start_local(self) -> None:
        """Start on the files in the list.

        The same run as a harvest from here on: the same models, the same
        options, the same progress reporting, the same cancel button. What
        differs is only that there is nothing to fetch.
        """
        if not self._local_paths:
            wx.MessageBox(
                "There are no files in the list yet.\n\n"
                "Use \"Add files...\" to choose audio, or \"Add a folder...\" "
                "to take everything in a folder.",
                "Nothing to work on", wx.OK | wx.ICON_WARNING, self)
            self._local_buttons[0].SetFocus()
            return

        model_choice = self._model_for_run()
        if model_choice is False:
            return

        self._save_settings()
        self.log_ctrl.Clear()
        self._reset_progress()
        # "Open output folder" afterwards should land somewhere useful. With
        # transcripts written beside the audio, the first file's folder is that
        # place; otherwise it is the library folder like any other run.
        self._run_output_dir = (
            str(self._local_paths[0].parent)
            if self.settings.local_transcripts_beside_file
            else self.output_ctrl.GetValue().strip()
            or str(self.app_space.default_output_dir))
        self._run_failed = None
        self.start_btn.Disable()
        for btn in self._local_buttons:
            btn.Disable()
        self._set_cancel_mode("cancel")
        self.cancel_btn.Enable()
        self._menu_cancel.Enable(True)
        count = len(self._local_paths)
        self._set_progress_text(
            f"Starting on {count} file{'s' if count != 1 else ''}")
        self._cancel_event.clear()

        self._worker = threading.Thread(
            target=self._run_local_worker,
            args=(list(self._local_paths), self.chk_transcribe.GetValue(),
                  model_choice, self.chk_timestamps.GetValue(),
                  self.chk_speakers.GetValue()),
            daemon=True,
        )
        self._worker.start()

    def _model_for_run(self):
        """The transcription model to use, None when not transcribing.

        Returns False -- not None -- when the run must not start, so "no model
        wanted" and "no model available" stay distinguishable to the caller.
        """
        if not self.chk_transcribe.GetValue():
            return None
        selection = self.model_choice.GetSelection()
        if selection == wx.NOT_FOUND or not self.model_choice.GetCount():
            wx.MessageBox(
                "Transcription is enabled but no model is selected yet.\n\n"
                "Hardware detection may still be running, or it found no model "
                "that fits this machine. Click \"Re-detect\" and wait for the "
                "hardware summary to update, or uncheck \"Transcribe "
                "downloaded audio\" to continue without it.",
                "No transcription model selected", wx.OK | wx.ICON_WARNING)
            self.model_choice.SetFocus()
            return False
        return self.model_choice.GetClientData(selection)

    def _run_local_worker(self, paths, transcribe, model_choice,
                          timestamps, speakers) -> None:
        try:
            from podharvest.localfiles import run_local

            run_local(
                paths,
                app=self.app_space,
                settings=self.settings,
                transcribe=transcribe,
                model=model_choice,
                include_timestamps=timestamps,
                identify_speakers=speakers,
                cancel_event=self._cancel_event,
                progress_callback=lambda pct: wx.CallAfter(
                    self.progress.SetValue, int(pct)),
                episode_callback=lambda prog: self._ui(
                    self._on_episode_progress, prog),
            )
        except Exception as exc:  # noqa: BLE001 - surface everything to the log
            LOG.exception("The run stopped with an error: %s", exc)
            self._run_failed = str(exc)
        finally:
            wx.CallAfter(self._finish_worker)

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
                match=self.settings.episode_match,
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
        self._refresh_model_ready()
        for btn in self._local_buttons:
            btn.Enable()
        self._menu_cancel.Enable(False)
        # The run is over, so the list goes back to being the library -- or
        # the local file list -- which now includes everything this run just
        # produced.
        self._worker = None
        if self.source_mode() == "local":
            self.refresh_local_list()
        else:
            self.refresh_library()
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
            body = (f"You stopped the run. {done} {self._run_noun(done)} finished "
                    "before it stopped, and those files are complete.")
            icon = wx.ICON_INFORMATION
        else:
            headline = "Finished."
            parts = [f"{done} {self._run_noun(done)} finished"]
            if failed:
                parts.append(f"{failed} failed")
            if skipped:
                parts.append(f"{skipped} skipped")
            where = (self._run_output_dir if self._run_output_dir
                     else "the folders your files are in")
            body = ", ".join(parts) + (
                f".\n\nEverything is in:\n{where}"
                if self.source_mode() != "local"
                or not self.settings.local_transcripts_beside_file
                else ".\n\nEach transcript is beside its audio file. The first "
                     f"of them is in:\n{where}")
            icon = wx.ICON_WARNING if failed else wx.ICON_INFORMATION

        cues.play(
            "failed" if self._run_failed else
            ("cancelled" if cancelled else "finished"),
            enabled=self.settings.sound_cues)
        self.progress.SetValue(100 if not cancelled and not self._run_failed
                               else self.progress.GetValue())
        self._set_progress_text(f"{headline} {body.splitlines()[0]}")
        self.SetTitle(f"{DISPLAY_NAME} {__version__}")
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

    # -- system tray -------------------------------------------------------

    def _setup_tray(self) -> None:
        """A tray icon, so a long run can get out of the way.

        A hundred episodes is an afternoon. Leaving a window on the taskbar for
        an afternoon to watch a progress bar is not a good use of it, so the
        window can be tucked away and the run carries on regardless -- closing
        to the tray is *not* the default, because a window that vanishes when
        you press the close button is a window people think they have quit.
        """
        try:
            self._tray = _TrayIcon(self)
        except Exception as exc:  # noqa: BLE001 - no tray on this desktop
            self._tray = None
            LOG.debug("No system tray available here (%s); the window stays "
                      "on the taskbar.", exc)

    def _on_minimise_to_tray(self, _evt=None) -> None:
        """Hide the window; the tray icon brings it back."""
        if self._tray is None:
            LOG.info("There is no system tray on this desktop, so the window "
                     "stays where it is.")
            return
        self.Hide()
        LOG.info("podHarvest is still running, in the notification area. "
                 "Double-click its icon, or use its menu, to bring it back.")

    def restore_from_tray(self) -> None:
        """Bring the window back and put focus somewhere useful."""
        if not self.IsShown():
            self.Show()
        if self.IsIconized():
            self.Iconize(False)
        self.Raise()
        self.episode_list.SetFocus()

    def _on_close(self, evt) -> None:
        # The last few seconds matter here, so this write is not throttled.
        self._remember_playback_position(force=True)
        self.player.shutdown()
        if getattr(self, "_tray", None) is not None:
            self._tray.RemoveIcon()
            self._tray.Destroy()
            self._tray = None
        self._cancel_event.set()
        self._save_settings()
        if self._log_handler in LOG.handlers:
            LOG.removeHandler(self._log_handler)
        if self._file_log_handler is not None:
            LOG.removeHandler(self._file_log_handler)
            self._file_log_handler.close()
            self._file_log_handler = None
        evt.Skip()


class _BugReportDialog(wx.Dialog):
    """The report, in full, before anything leaves the machine.

    Read-only and multi-line so it is a real tab stop that can be arrowed
    through line by line -- somebody should be able to check what they are
    about to send, and a wall of text nobody can review is not consent.

    Three ways out, none of which is "send": copy it, save it, or open a
    pre-filled email. Closing the window does nothing at all.
    """

    def __init__(self, parent: wx.Window, report: str) -> None:
        super().__init__(parent, title="Report a bug",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self._report = report

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label=(
            "This is everything the report contains. Nothing has been sent, and "
            "nothing will be unless you choose to send it. API keys, home folder "
            "names and email addresses have been removed.")),
            0, wx.ALL, 10)

        root.Add(wx.StaticText(self, label="What went wrong (optional):"), 0,
                 wx.LEFT | wx.RIGHT, 10)
        self.what_happened = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.what_happened.SetToolTip(
            "What you did, and what you expected instead. The most useful "
            "sentence in any bug report, and the one only you can write."
        )
        set_accessible_name(self.what_happened, "What went wrong")
        size_for_text(self.what_happened, lines=4)
        self.what_happened.Bind(wx.EVT_TEXT, lambda _e: self._refresh())
        root.Add(self.what_happened, 0, wx.EXPAND | wx.ALL, 10)

        root.Add(wx.StaticText(self, label="The report:"), 0, wx.LEFT | wx.RIGHT, 10)
        self.preview = wx.TextCtrl(
            self, value=report, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.preview.SetToolTip(
            "The whole report, exactly as it would be sent. Read-only: arrow "
            "through it, or select and copy."
        )
        set_accessible_name(self.preview, "The report")
        size_for_text(self.preview, lines=14)
        root.Add(self.preview, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        copy_btn = wx.Button(self, label="&Copy to clipboard")
        copy_btn.SetToolTip("Puts the whole report on the clipboard, ready to paste.")
        copy_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_copy())
        row.Add(copy_btn, 0, wx.RIGHT, 6)

        save_btn = wx.Button(self, label="&Save to a file...")
        save_btn.SetToolTip("Writes the report to a text file you choose.")
        save_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_save())
        row.Add(save_btn, 0, wx.RIGHT, 6)

        email_btn = wx.Button(self, label="Open an &email...")
        email_btn.SetToolTip(
            f"Copies the report and opens a message to {SUPPORT_EMAIL} in your "
            "mail program, ready for you to paste it in and send. Mail programs "
            "truncate long links, so the report goes via the clipboard."
        )
        email_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_email())
        row.Add(email_btn, 0, wx.RIGHT, 12)

        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window. Nothing is sent.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.status = wx.StaticText(self, label="")
        set_accessible_name(self.status, "Report status")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(640, 560))
        self.Fit()
        self.CentreOnParent()

    def _refresh(self) -> None:
        """Rebuild the report so the preview always matches what would be sent."""
        from podharvest import feedback

        described = self.what_happened.GetValue().strip()
        if not described:
            self.preview.SetValue(self._report)
            return
        head, sep, tail = self._report.partition("(describe what you did")
        if sep:
            _skip, _nl, rest = tail.partition("\n")
            self.preview.SetValue(feedback.redact(head + described + "\n" + rest))
        else:
            self.preview.SetValue(self._report)

    def _text(self) -> str:
        return self.preview.GetValue()

    def _say(self, message: str) -> None:
        """Status changes on an unfocused label are what a reader misses."""
        self.status.SetLabel(message)
        LOG.info("%s", message)

    def _on_copy(self) -> None:
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self._text()))
            finally:
                wx.TheClipboard.Close()
            self._say("The report is on the clipboard.")
        else:
            self._say("Could not reach the clipboard.")

    def _on_save(self) -> None:
        from pathlib import Path

        with wx.FileDialog(
            self, "Save the bug report", defaultFile="podharvest-bug-report.txt",
            wildcard="Text files (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            path.write_text(self._text(), encoding="utf-8")
        except OSError as exc:
            self._say(f"Could not save the report: {exc}")
            return
        self._say(f"Saved to {path.name}.")

    def _on_email(self) -> None:
        from podharvest import feedback

        self._on_copy()
        wx.LaunchDefaultBrowser(feedback.mailto_url(self._text()))
        self._say(
            f"Opened a message to {SUPPORT_EMAIL}. The report is on your "
            "clipboard -- paste it into the message before sending."
        )


class _TrayIcon(wx.adv.TaskBarIcon):
    """The notification-area icon: restore, and quit.

    Deliberately two items and no more. A tray menu is a place people go when
    the window is not in front of them, which is the worst moment to offer
    them a choice they have to think about.
    """

    def __init__(self, frame: MainFrame) -> None:
        super().__init__()
        self._frame = frame
        icon = wx.ArtProvider.GetIcon(wx.ART_INFORMATION, wx.ART_OTHER, (16, 16))
        self.SetIcon(icon, f"{DISPLAY_NAME} -- still running")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda _e: self._frame.restore_from_tray())

    def CreatePopupMenu(self) -> wx.Menu:  # noqa: N802 - wx API casing
        menu = wx.Menu()
        show = menu.Append(wx.ID_ANY, f"&Show {DISPLAY_NAME}")
        menu.AppendSeparator()
        quit_item = menu.Append(wx.ID_EXIT, "&Quit")
        self.Bind(wx.EVT_MENU, lambda _e: self._frame.restore_from_tray(), show)
        self.Bind(wx.EVT_MENU, lambda _e: self._frame.Close(), quit_item)
        return menu


def run_gui() -> int:
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
    return 0
