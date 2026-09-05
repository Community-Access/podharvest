"""Getting a model, in a window that says what it is doing.

Downloading a model was the most opaque thing podHarvest did. It borrowed
the main window's gauge, blanked the episode list, and then went quiet for
minutes at a time -- because the work has two phases and only the second one
ever reported anything. Phase one installs the engine's Python packages,
which can take several minutes and produces no percentage at all; phase two
fetches the weights, which does. From outside, both looked like nothing
happening, and the honest reading of a button that goes silent for five
minutes is that it is broken.

This window fixes that by being specific rather than by being prettier:

* **Both phases are named.** "Step 1 of 2, setting up the engine" is a
  different sentence from "Step 2 of 2, downloading the model", and either
  is better than a gauge that has not moved.
* **There is always a most recent line**, in a read-only box that takes
  focus, so a screen reader user can read the current state on demand
  instead of waiting to be told. The activity log on the main window cannot
  do that -- it cannot announce, and it is behind this window anyway.
* **The main window is left alone.** Its gauge is for runs, its list is for
  episodes, and a download is neither.
* **Closing is always available**, and says plainly that the work carries on
  -- because a download you cannot get out of is worse than a slow one.

Nothing here decides *what* to fetch. That is `acquire`'s job, and this
calls exactly the functions a run calls, so pressing Download and pressing
Start can never disagree about what "downloaded" means.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import wx

from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name, size_for_text
from podharvest.util import LOG

#: How many lines of history the progress box keeps. Enough to see what the
#: last few steps were without becoming a second activity log.
HISTORY_LINES = 200


class ModelDownloadDialog(wx.Dialog):
    """Fetch one model's packages and weights, saying so throughout."""

    def __init__(self, parent: wx.Window, app_space, choice,
                 *, announce: Callable[[str], None] | None = None) -> None:
        super().__init__(
            parent, title=f"Getting {choice.model}",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self.app_space = app_space
        self.choice = choice
        self._announce_fn = announce
        self._worker: threading.Thread | None = None
        self._alive = True
        self._done = False
        self.succeeded = False
        self._last_percent = -1
        self._lines: list[str] = []

        root = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(
            self,
            label=f"Getting everything {choice.model} needs.\n"
                  "This is a one-time cost. You can close this window and it "
                  "carries on.")
        root.Add(heading, 0, wx.ALL, 10)

        # Label before control, so a screen reader pairs the two.
        root.Add(wx.StaticText(self, label="&Step:"), 0, wx.LEFT | wx.RIGHT, 10)
        self.phase_ctrl = wx.TextCtrl(
            self, value="Starting...", style=wx.TE_READONLY)
        self.phase_ctrl.SetToolTip(
            "Which of the two steps is running: setting up the engine's "
            "Python packages, then downloading the model itself. Read-only."
        )
        set_accessible_name(self.phase_ctrl, "Current step")
        root.Add(self.phase_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.gauge = wx.Gauge(self, range=100)
        self.gauge.SetToolTip(
            "How far the current step has got. The first step has no "
            "percentage to report -- pip does not give one -- so the bar "
            "pulses instead of filling."
        )
        set_accessible_name(self.gauge, "Download progress")
        root.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Label before control, so a screen reader pairs the two.
        root.Add(wx.StaticText(self, label="&What has happened:"), 0,
                 wx.LEFT | wx.RIGHT, 10)
        # Read-only and multi-line so it is a real tab stop that can be read
        # a line at a time. This is the answer to "what is it doing?" and it
        # has to be readable on demand, not only when something speaks.
        self.detail = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.detail.SetToolTip(
            "Every step so far, most recent last. Read-only: arrow through "
            "it at any time to find out where things have got to."
        )
        set_accessible_name(self.detail, "Download details")
        size_for_text(self.detail, lines=10, chars=64)
        root.Add(self.detail, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.close_btn = wx.Button(self, wx.ID_CANCEL, label="&Close")
        self.close_btn.SetToolTip(
            "Closes this window. The download carries on, and the activity "
            "log on the main window keeps reporting it."
        )
        row.AddStretchSpacer()
        row.Add(self.close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(620, 460))
        self.Fit()
        self.CentreOnParent()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # Focus the running commentary rather than Close: the first thing
        # somebody wants here is to know what is happening, and the button
        # that abandons the window is a poor thing to land on.
        self.detail.SetFocus()

    # -- saying what is happening -----------------------------------------

    def _say(self, text: str, *, speak: bool = False) -> None:
        """Add a line to the history, and optionally announce it."""
        if not self._alive:
            return
        self._lines.append(text)
        del self._lines[:-HISTORY_LINES]
        self.detail.SetValue("\n".join(self._lines))
        # Keep the newest line in view without stealing the caret from
        # somebody reading back through the history.
        self.detail.ShowPosition(self.detail.GetLastPosition())
        if speak and self._announce_fn is not None:
            self._announce_fn(text)

    def _set_phase(self, text: str) -> None:
        if not self._alive:
            return
        self.phase_ctrl.SetValue(text)
        self._say(text, speak=True)

    # -- running it --------------------------------------------------------

    def start(self) -> None:
        """Begin the work on a worker thread."""
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self) -> None:
        from podharvest import acquire

        ok = True
        try:
            wx.CallAfter(self._set_phase,
                         "Step 1 of 2: setting up the engine's Python packages.")
            wx.CallAfter(self._pulse_on)
            if not acquire.ensure_engine_packages(
                    self.app_space, self.choice.engine,
                    progress=lambda text: wx.CallAfter(self._say, text)):
                ok = False
                wx.CallAfter(
                    self._say,
                    f"The {self.choice.engine} engine could not be set up. "
                    "The activity log on the main window says why. Nothing "
                    "was changed.", speak=True)
            else:
                wx.CallAfter(self._say, "The engine is ready.")
                wx.CallAfter(self._pulse_off)
                wx.CallAfter(self._set_phase,
                             "Step 2 of 2: downloading the model itself.")
                acquire.acquire_asr_model(
                    self.app_space, self.choice, on_progress=self._on_progress)
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            ok = False
            LOG.exception("Getting %s stopped with an error: %s",
                          self.choice.model, exc)
            wx.CallAfter(self._say, f"It stopped with an error: {exc}",
                         speak=True)
        finally:
            wx.CallAfter(self._finish, ok)

    def _on_progress(self, percent: float, detail: str) -> None:
        """Called from the worker by the hub's tqdm shim."""
        whole = int(max(0.0, min(100.0, percent)))
        if whole == self._last_percent:
            return
        self._last_percent = whole
        wx.CallAfter(self._show_percent, whole, detail)

    def _show_percent(self, whole: int, detail: str) -> None:
        if not self._alive:
            return
        self.gauge.SetValue(whole)
        said = f" - {detail}" if detail else ""
        self.phase_ctrl.SetValue(f"Step 2 of 2: downloading, {whole}%{said}")
        # Every ten percent in the history, so the box is a record of
        # progress rather than a thousand near-identical lines.
        if whole % 10 == 0:
            self._say(f"Downloaded {whole}%.")

    def _pulse_on(self) -> None:
        """A gauge with no percentage to show still has to look alive.

        pip reports nothing a percentage can be made of, and a bar frozen at
        zero for four minutes is the single clearest way to tell somebody
        the program has hung when it has not.
        """
        if not self._alive:
            return
        self._pulse_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self.gauge.Pulse(), self._pulse_timer)
        self._pulse_timer.Start(120)

    def _pulse_off(self) -> None:
        timer = getattr(self, "_pulse_timer", None)
        if timer is not None:
            timer.Stop()
            self._pulse_timer = None
        if self._alive:
            self.gauge.SetValue(0)

    def _finish(self, ok: bool) -> None:
        self._done = True
        self.succeeded = ok
        self._pulse_off()
        if not self._alive:
            return
        self.gauge.SetValue(100 if ok else 0)
        self._set_phase(
            f"{self.choice.model} is ready." if ok else
            f"{self.choice.model} could not be fetched.")
        self.close_btn.SetLabel("&Done" if ok else "&Close")
        self.close_btn.SetToolTip(
            "Closes this window and goes back to the main window."
            if ok else
            "Closes this window. The activity log on the main window says "
            "what went wrong.")
        self.Layout()
        self.close_btn.SetFocus()

    def _on_close(self, event) -> None:
        """Closing never cancels the work; it only stops watching it.

        Killing a half-finished pip install or a part-downloaded model is
        how a model space ends up in a state nothing can explain. Letting it
        finish is both safer and what people mean when they close a window
        that is taking a long time.
        """
        self._alive = False
        self._pulse_off()
        if not self._done:
            LOG.info("Still getting %s. It carries on; this log keeps "
                     "reporting it.", self.choice.model)
        event.Skip()
