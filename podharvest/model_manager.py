"""Setting up the models podHarvest can transcribe with.

The main window used to carry all of this: a filter, a list of everything
the machine could theoretically run, a description, a readiness line and a
Download button, all beside the options for the run you were about to
start. Two things went wrong with that. The main window offered models that
could not run without saying so, and models that could not run were
sometimes hidden instead -- so a model you had read about simply was not
there, with nothing to explain it.

This window separates the two questions. **Setting up** happens here, once,
and shows *everything* podHarvest knows about with an honest word on each:
ready, needs downloading, needs a key, will not fit. **Choosing** happens on
the main window, from the short list of models that will actually run right
now.

The rules it keeps:

* **Nothing is hidden.** A model too large for this machine is listed with
  the numbers -- "needs about 6 GB; this machine can give about 4.5" -- so
  you know it exists and why it is not on offer.
* **Status is a word, not a colour.** Every row says Ready, Not downloaded,
  Needs an API key, or Will not fit, in its own column, because a colour is
  not information to a screen reader and "unavailable" is not information to
  anybody.
* **One recommended model is marked**, so a first-time user has an answer
  rather than a menu.
* **Downloading happens in the window that reports it**, not silently in the
  background.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import wx

from podharvest import hardware as hardware_mod
from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name, size_for_text
from podharvest.util import LOG

#: What a row can say about a model. Ordered by how much use it is to you:
#: what you can run now comes before what you could run after a download,
#: which comes before what this machine cannot run at all.
READY = "Ready"
NOT_DOWNLOADED = "Not downloaded"
NEEDS_KEY = "Needs an API key"
WILL_NOT_FIT = "Will not fit"

_STATUS_ORDER = {READY: 0, NOT_DOWNLOADED: 1, NEEDS_KEY: 2, WILL_NOT_FIT: 3}

#: Columns. The heading is read with every cell, so each has to be true of
#: what is actually in that column.
_COLUMNS = (
    ("Model", 250), ("Where it runs", 150), ("Status", 150), ("Size", 90),
)

#: The filters on offer, and the settings value each stores.
_FILTERS = ("all", "ready", "local", "cloud")
_FILTER_LABELS = ["&All", "&Ready to use", "On this &machine", "In the c&loud"]


@dataclass(frozen=True)
class ModelEntry:
    """One model, and everything a person needs to decide about it."""

    choice: object
    status: str
    where: str
    sentence: str
    recommended: bool = False

    @property
    def is_ready(self) -> bool:
        return self.status == READY

    def size_text(self) -> str:
        size = getattr(self.choice, "size_gb", 0) or 0
        return f"{size} GB" if size else ""

    def describe(self) -> str:
        """The row as one spoken phrase, for the accessible name."""
        name = getattr(self.choice, "model", "")
        star = "Recommended. " if self.recommended else ""
        return f"{star}{name}, {self.where}, {self.status}"


def catalog(app, hw, settings) -> list[ModelEntry]:
    """Every model podHarvest knows about, with an honest status on each.

    Deliberately not filtered. The main window's list is the filtered one;
    this is the inventory, and a model missing from an inventory reads as a
    model that does not exist.
    """
    from podharvest import acquire
    from podharvest import cloud as cloud_mod

    entries: list[ModelEntry] = []
    recommended = None
    try:
        recommended = hardware_mod.recommend_model(hw) if hw is not None else None
    except Exception:  # noqa: BLE001 - a recommendation is a nicety
        recommended = None

    for choice in hardware_mod.all_local_models():
        # Two engines ship the same Parakeet weights -- one through
        # sherpa-onnx on plain CPU, one through NeMo on an NVIDIA card. With
        # only the model name on the row they read as one model listed
        # twice with contradictory statuses, so the column says which
        # hardware each wants.
        where = ("NVIDIA GPU" if hardware_mod.needs_cuda(choice)
                 else "This machine")
        if hw is not None and not hardware_mod.fits(hw, choice):
            entries.append(ModelEntry(
                choice=choice, status=WILL_NOT_FIT, where=where,
                sentence=hardware_mod.why_not(hw, choice)))
            continue
        missing = acquire.engine_packages_missing(app, choice.engine)
        weights = acquire.is_downloaded(app, choice)
        if not missing and weights:
            status, sentence = READY, "Downloaded and ready to run now."
        else:
            wants = []
            if missing:
                wants.append(f"the {choice.engine} engine")
            if not weights:
                wants.append("the model itself")
            status = NOT_DOWNLOADED
            sentence = ("Still needs " + " and ".join(wants)
                        + ". Press Download and this window will say how it "
                          "is getting on.")
        entries.append(ModelEntry(
            choice=choice, status=status, where=where,
            sentence=sentence,
            recommended=bool(recommended
                             and choice.model == recommended.model
                             and choice.engine == recommended.engine)))

    # Cloud models that already have a key. Providers without one are listed
    # below, so the window says what could be turned on rather than only
    # what is.
    configured = set()
    try:
        for choice in cloud_mod.available_cloud_models(app, kind="asr",
                                                       settings=settings):
            configured.add(getattr(choice, "provider", ""))
            entries.append(ModelEntry(
                choice=choice, status=READY, where="Cloud",
                sentence=("A key for this provider is set, so it can run "
                          "now. Audio is sent to the provider.")))
    except Exception as exc:  # noqa: BLE001 - a bad key must not empty the list
        LOG.debug("Could not list cloud models: %s", exc)

    for entry in _unconfigured_cloud(app, settings, configured):
        entries.append(entry)

    entries.sort(key=lambda e: (_STATUS_ORDER.get(e.status, 9),
                                not e.recommended,
                                getattr(e.choice, "model", "")))
    return entries


def _unconfigured_cloud(app, settings, configured: set[str]) -> list[ModelEntry]:
    """Cloud providers with no key yet, so they can be discovered at all.

    A provider you have never configured is invisible everywhere else in
    podHarvest, which makes "you can use a cloud model" a fact you have to
    already know. Listing them here, greyed by status rather than absent, is
    how somebody finds out.
    """
    from podharvest import cloud as cloud_mod

    found: list[ModelEntry] = []
    for choice in getattr(cloud_mod, "CLOUD_ASR_CHOICES", []):
        if getattr(choice, "provider", "") in configured:
            continue
        found.append(ModelEntry(
            choice=choice, status=NEEDS_KEY, where="Cloud",
            sentence=("No API key for this provider yet. Settings, then "
                      "API keys, is where one goes. Nothing is sent "
                      "anywhere until there is a key and you choose this "
                      "model.")))
    return found


class ModelManagerDialog(wx.Dialog):
    """The inventory of models, and the place to set one up."""

    def __init__(self, parent, app_space, settings, hw,
                 *, on_choose: Callable[[object], None] | None = None) -> None:
        super().__init__(parent, title="Set up models",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self.app_space = app_space
        self.settings = settings
        self.hw = hw
        self._on_choose = on_choose
        self.chosen = None
        self._entries: list[ModelEntry] = []
        self._shown: list[ModelEntry] = []

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(
            self,
            label="Everything podHarvest can transcribe with, and whether it "
                  "can run here.\nNothing is downloaded or sent anywhere "
                  "until you say so."), 0, wx.ALL, 10)

        self.filter_radio = wx.RadioBox(
            self, label="Show", choices=_FILTER_LABELS,
            majorDimension=4, style=wx.RA_SPECIFY_COLS)
        self.filter_radio.SetToolTip(
            "Which models to list. All is the inventory, including models "
            "this machine cannot run -- they are listed with the reason "
            "rather than hidden. Ready to use is the same list the main "
            "window offers."
        )
        set_accessible_name(self.filter_radio, "Show")
        chosen_filter = getattr(settings, "model_filter", "all")
        self.filter_radio.SetSelection(
            _FILTERS.index(chosen_filter) if chosen_filter in _FILTERS else 0)
        self.filter_radio.Bind(wx.EVT_RADIOBOX, lambda _e: self.refresh())
        root.Add(self.filter_radio, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Label before control, so a screen reader pairs the two.
        root.Add(wx.StaticText(self, label="&Models:"), 0,
                 wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        for heading, width in _COLUMNS:
            self.list.AppendColumn(heading, width=width)
        self.list.SetToolTip(
            "Every model, what it needs, and whether it can run here. Arrow "
            "through them; the box below says more about the one you are on. "
            "Enter uses the highlighted model if it is ready."
        )
        set_accessible_name(self.list, "Models")
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _e: self._on_selected())
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda _e: self._on_selected())
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self.on_use())
        size_for_text(self.list, lines=9, chars=0)
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        # Read-only and multi-line so it is a real tab stop that can be read
        # a line at a time. This is where a model actually gets explained,
        # and it is sized to hold the explanation rather than to fit a gap.
        self.detail = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.detail.SetToolTip(
            "What the highlighted model is, how fast it is on this machine, "
            "how much it downloads, and what it needs before it can run. "
            "Read-only."
        )
        set_accessible_name(self.detail, "About the highlighted model")
        size_for_text(self.detail, lines=12, chars=70)
        root.Add(self.detail, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.use_btn = wx.Button(self, label="&Use this model")
        self.use_btn.SetToolTip(
            "Makes this the model the main window will transcribe with, and "
            "closes this window.")
        self.use_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_use())
        self.use_btn.Enable(False)
        row.Add(self.use_btn, 0, wx.RIGHT, 6)

        self.download_btn = wx.Button(self, label="&Download")
        self.download_btn.SetToolTip(
            "Fetches everything this model needs -- the engine's Python "
            "packages and the model itself. A window opens saying how it is "
            "getting on, and closing that window does not stop it.")
        self.download_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_download())
        self.download_btn.Enable(False)
        row.Add(self.download_btn, 0, wx.RIGHT, 6)

        self.keys_btn = wx.Button(self, label="API &keys...")
        self.keys_btn.SetToolTip(
            "Opens Settings at the API keys, where a cloud provider's key "
            "goes. Cloud models cannot run without one.")
        self.keys_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_keys())
        row.Add(self.keys_btn, 0, wx.RIGHT, 12)

        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window without changing anything.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.status = wx.StaticText(self, label="")
        set_accessible_name(self.status, "Model setup status")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(820, 640))
        self.Fit()
        self.CentreOnParent()
        self.refresh()
        self.list.SetFocus()

    # -- filling it in -----------------------------------------------------

    def _filter(self) -> str:
        index = self.filter_radio.GetSelection()
        return _FILTERS[index] if 0 <= index < len(_FILTERS) else "all"

    def refresh(self, *, keep: object = None) -> None:
        """Re-read every model's status and rebuild the list."""
        self._entries = catalog(self.app_space, self.hw, self.settings)
        wanted = self._filter()
        self.settings.model_filter = wanted
        self._shown = [e for e in self._entries if self._matches(e, wanted)]
        self.list.DeleteAllItems()
        for entry in self._shown:
            row = self.list.InsertItem(
                self.list.GetItemCount(),
                ("* " if entry.recommended else "")
                + getattr(entry.choice, "model", ""))
            self.list.SetItem(row, 1, entry.where)
            self.list.SetItem(row, 2, entry.status)
            self.list.SetItem(row, 3, entry.size_text())
        ready = sum(1 for e in self._entries if e.is_ready)
        self.status.SetLabel(
            f"{len(self._shown)} shown, {ready} ready to use out of "
            f"{len(self._entries)} known.")
        if self._shown:
            index = 0
            if keep is not None:
                for i, entry in enumerate(self._shown):
                    if (getattr(entry.choice, "model", None)
                            == getattr(keep, "model", None)):
                        index = i
                        break
            self.list.Select(index)
            self.list.Focus(index)
        self._on_selected()

    def _matches(self, entry: ModelEntry, wanted: str) -> bool:
        if wanted == "ready":
            return entry.is_ready
        if wanted == "local":
            return entry.where != "Cloud"
        if wanted == "cloud":
            return entry.where == "Cloud"
        return True

    # -- the highlighted row ----------------------------------------------

    def selected(self) -> ModelEntry | None:
        row = self.list.GetFirstSelected()
        return self._shown[row] if 0 <= row < len(self._shown) else None

    def _on_selected(self) -> None:
        entry = self.selected()
        self.use_btn.Enable(entry is not None and entry.is_ready)
        self.download_btn.Enable(
            entry is not None and entry.status == NOT_DOWNLOADED)
        self.keys_btn.Enable(True)
        if entry is None:
            self.detail.SetValue("")
            return
        self.detail.SetValue(self._describe(entry))
        # Keep the caret at the top so a screen reader starts at the name.
        self.detail.SetInsertionPoint(0)

    def _describe(self, entry: ModelEntry) -> str:
        """Everything known about a model, most useful first."""
        from podharvest import estimate as estimate_mod

        lines = [getattr(entry.choice, "model", ""), ""]
        if entry.recommended:
            lines.append("Recommended for this machine.")
        lines.append(f"Status: {entry.status}. {entry.sentence}")
        lines.append("")
        try:
            described = estimate_mod.describe_model(
                entry.choice, 0.0, self.hw, self.app_space)
        except Exception as exc:  # noqa: BLE001 - a description is not vital
            LOG.debug("Could not describe %s: %s", entry.choice, exc)
            described = ""
        if described:
            lines.append(described)
        return "\n".join(lines).strip()

    # -- acting ------------------------------------------------------------

    def on_use(self) -> None:
        entry = self.selected()
        if entry is None or not entry.is_ready:
            if entry is not None:
                self.status.SetLabel(
                    f"{getattr(entry.choice, 'model', 'That model')} is not "
                    f"ready: {entry.sentence}")
            return
        self.chosen = entry.choice
        if self._on_choose is not None:
            self._on_choose(entry.choice)
        self.EndModal(wx.ID_OK)

    def on_download(self) -> None:
        """Fetch the highlighted model, then re-read every status."""
        from podharvest.model_download import ModelDownloadDialog

        entry = self.selected()
        if entry is None or entry.status != NOT_DOWNLOADED:
            return
        dlg = ModelDownloadDialog(self, self.app_space, entry.choice)
        try:
            dlg.start()
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        # Re-read rather than assume: the download may have half-succeeded,
        # and the row should say what is actually on disk now.
        self.refresh(keep=entry.choice)
        after = self.selected()
        if after is not None and after.is_ready:
            self.status.SetLabel(
                f"{getattr(after.choice, 'model', '')} is ready. Use this "
                "model makes it the one the main window transcribes with.")
            self.use_btn.SetFocus()

    def on_keys(self) -> None:
        """Send the user to where a cloud key actually goes."""
        self.status.SetLabel(
            "Close this window, then Settings, then API keys. A cloud model "
            "needs a key from its provider before it can run.")
        LOG.info("Cloud models need an API key. Settings, then API keys.")
