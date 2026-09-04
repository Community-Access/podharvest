"""Finding a podcast, keeping the ones worth keeping, and looking inside one.

Three windows, one job: getting from "I know the name of a show" to "these are
its episodes" without leaving podHarvest or hunting for a feed address.

* `SearchDialog` -- search Apple's directory, see what came back, take a feed.
* `FavoritesDialog` -- the shows you marked, to come back to.
* Browsing itself lives on the main window: it reads a feed and lists the
  episodes without downloading anything.

Everything here is keyboard-first, because that is how this program is used:
type a name, press Enter, arrow the results, press Enter again. No step needs
a mouse and no result is conveyed by colour or position alone.
"""

from __future__ import annotations

import threading

import wx

from podharvest import directory as directory_mod
from podharvest import favorites as favorites_mod
from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name, size_for_text
from podharvest.util import LOG

#: Columns for the results list. The heading is read with every cell, so each
#: has to be true of what is actually in that column.
_RESULT_COLUMNS = (
    ("Podcast", 280), ("By", 190), ("What it is", 230), ("Latest", 96),
)

#: Columns for the favourites list.
_FAVORITE_COLUMNS = (
    ("Podcast", 300), ("By", 210), ("Added", 120),
)


class SearchDialog(wx.Dialog):
    """Search Apple's podcast directory and take a feed address from it."""

    def __init__(self, parent, app_space, settings) -> None:
        super().__init__(parent, title="Find a podcast",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self.app_space = app_space
        self.settings = settings
        self.chosen: directory_mod.SearchResult | None = None
        self._results: list[directory_mod.SearchResult] = []
        self._worker: threading.Thread | None = None
        self._alive = True

        root = wx.BoxSizer(wx.VERTICAL)

        # -- what to search for ------------------------------------------
        term_row = wx.BoxSizer(wx.HORIZONTAL)
        term_row.Add(wx.StaticText(self, label="&Podcast name:"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.term_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.term_ctrl.SetToolTip(
            "The name of the show, its presenter, or a word from what it is "
            "about. Press Enter to search."
        )
        self.term_ctrl.SetHint("a show, a presenter, or a subject")
        set_accessible_name(self.term_ctrl, "Podcast name")
        self.term_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda _e: self.on_search())
        term_row.Add(self.term_ctrl, 1, wx.RIGHT, 6)

        self.search_btn = wx.Button(self, label="&Search")
        self.search_btn.SetToolTip("Ask the directory for shows matching what "
                                   "you typed.")
        self.search_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_search())
        term_row.Add(self.search_btn, 0)
        root.Add(term_row, 0, wx.EXPAND | wx.ALL, 10)

        # -- how to search -----------------------------------------------
        options = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Search options")
        holder = options.GetStaticBox()

        options.Add(wx.StaticText(holder, label="Match &against:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.field_choice = wx.Choice(
            holder, choices=[label for _key, label in directory_mod.SEARCH_FIELDS])
        self.field_choice.SetToolTip(
            "What your words are matched against. Everything is the usual "
            "answer; the others help when a show's name is a common word, or "
            "when you want everything by one presenter."
        )
        set_accessible_name(self.field_choice, "Match against")
        self.field_choice.SetSelection(0)
        options.Add(self.field_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        options.Add(wx.StaticText(holder, label="&Country:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.country_choice = wx.Choice(
            holder, choices=[name for _code, name in directory_mod.STOREFRONTS])
        self.country_choice.SetToolTip(
            "Which of Apple's stores to search. They carry different shows, "
            "so a local podcast may only appear in its own country's store. "
            "The default comes from Settings."
        )
        set_accessible_name(self.country_choice, "Country")
        self._select_country(getattr(settings, "itunes_country",
                                     directory_mod.DEFAULT_STOREFRONT))
        options.Add(self.country_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        options.Add(wx.StaticText(holder, label="&How many:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.limit_ctrl = wx.SpinCtrl(
            holder, min=1, max=directory_mod.MAX_LIMIT,
            initial=int(getattr(settings, "search_limit",
                                directory_mod.DEFAULT_LIMIT)))
        self.limit_ctrl.SetToolTip(
            "How many results to ask for, up to "
            f"{directory_mod.MAX_LIMIT}. More takes no longer to fetch but "
            "makes a longer list to read."
        )
        set_accessible_name(self.limit_ctrl, "How many results")
        options.Add(self.limit_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        self.chk_explicit = wx.CheckBox(holder, label="Include e&xplicit shows")
        self.chk_explicit.SetValue(True)
        self.chk_explicit.SetToolTip(
            "On, the directory returns everything. Off, it leaves out shows "
            "marked explicit by their publisher."
        )
        options.Add(self.chk_explicit, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(options, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # -- results -----------------------------------------------------
        self.status = wx.StaticText(self, label="Type a name and press Enter.")
        set_accessible_name(self.status, "Search status")
        root.Add(self.status, 0, wx.ALL, 10)

        results_label = wx.StaticText(self, label="&Results:")
        root.Add(results_label, 0, wx.LEFT | wx.RIGHT, 10)
        self.results_list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        for heading, width in _RESULT_COLUMNS:
            self.results_list.AppendColumn(heading, width=width)
        self.results_list.SetToolTip(
            "The shows that matched. Arrow through them; Enter takes the "
            "highlighted one and closes this window."
        )
        set_accessible_name(self.results_list, "Search results")
        self.results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED,
                               lambda _e: self.on_use())
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED,
                               lambda _e: self._on_selected())
        self.results_list.Bind(wx.EVT_LIST_ITEM_DESELECTED,
                               lambda _e: self._on_selected())
        root.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 10)

        self.detail = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.detail.SetToolTip(
            "Everything the directory knows about the highlighted show, "
            "including its feed address. Read-only."
        )
        set_accessible_name(self.detail, "About the highlighted show")
        size_for_text(self.detail, lines=4)
        root.Add(self.detail, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # -- actions ------------------------------------------------------
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.use_btn = wx.Button(self, wx.ID_OK, label="&Use this podcast")
        self.use_btn.SetToolTip(
            "Puts this show's feed address into the main window, ready to "
            "browse or harvest."
        )
        self.use_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_use())
        self.use_btn.Enable(False)
        row.Add(self.use_btn, 0, wx.RIGHT, 6)

        self.fav_btn = wx.Button(self, label="Add to &favourites")
        self.fav_btn.SetToolTip(
            "Remembers this show so you can find it again without searching. "
            "It is a bookmark, not a subscription: nothing is downloaded and "
            "nothing is checked for you."
        )
        self.fav_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_favorite())
        self.fav_btn.Enable(False)
        row.Add(self.fav_btn, 0, wx.RIGHT, 12)

        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window without taking anything.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(860, 620))
        self.Fit()
        self.CentreOnParent()
        self.term_ctrl.SetFocus()
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # -- helpers ---------------------------------------------------------

    def _select_country(self, code: str) -> None:
        wanted = directory_mod.clean_storefront(code)
        for index, (candidate, _name) in enumerate(directory_mod.STOREFRONTS):
            if candidate == wanted:
                self.country_choice.SetSelection(index)
                return
        self.country_choice.SetSelection(0)

    def country(self) -> str:
        index = self.country_choice.GetSelection()
        if 0 <= index < len(directory_mod.STOREFRONTS):
            return directory_mod.STOREFRONTS[index][0]
        return directory_mod.DEFAULT_STOREFRONT

    def field_name(self) -> str:
        index = self.field_choice.GetSelection()
        if 0 <= index < len(directory_mod.SEARCH_FIELDS):
            return directory_mod.SEARCH_FIELDS[index][0]
        return ""

    def selected(self) -> directory_mod.SearchResult | None:
        row = self.results_list.GetFirstSelected()
        return self._results[row] if 0 <= row < len(self._results) else None

    # -- searching --------------------------------------------------------

    def on_search(self) -> None:
        """Run the search on a worker thread, so the window stays alive."""
        term = self.term_ctrl.GetValue().strip()
        if not term:
            self.status.SetLabel("Type the name of a podcast first.")
            self.term_ctrl.SetFocus()
            return
        if self._worker is not None and self._worker.is_alive():
            return
        query = directory_mod.SearchQuery(
            term=term, country=self.country(),
            limit=self.limit_ctrl.GetValue(), field_name=self.field_name(),
            include_explicit=self.chk_explicit.GetValue())
        self.search_btn.Disable()
        self.status.SetLabel(
            f"Searching the {directory_mod.storefront_name(query.country)} "
            f"store for '{term}'...")
        self._worker = threading.Thread(
            target=self._run_search, args=(query,), daemon=True)
        self._worker.start()

    def _run_search(self, query) -> None:
        try:
            results = query.run(settings=self.settings)
            error = ""
        except directory_mod.DirectoryError as exc:
            results, error = [], str(exc)
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            results, error = [], str(exc)
            LOG.exception("The podcast search failed: %s", exc)
        wx.CallAfter(self._show_results, results, error, query.term)

    def _show_results(self, results, error: str, term: str) -> None:
        if not self._alive:
            return
        self.search_btn.Enable()
        self._results = list(results)
        self.results_list.DeleteAllItems()
        for result in self._results:
            row = self.results_list.InsertItem(
                self.results_list.GetItemCount(), result.title)
            self.results_list.SetItem(row, 1, result.artist)
            self.results_list.SetItem(row, 2, result.summary())
            self.results_list.SetItem(row, 3, result.released)

        if error:
            self.status.SetLabel(error)
        elif not self._results:
            self.status.SetLabel(
                f"Nothing matched '{term}'. Try fewer words, a different "
                "country, or matching against Everything.")
        else:
            self.status.SetLabel(
                f"{len(self._results)} show(s) found. Arrow through the list; "
                "Enter takes the one you are on.")
            self.results_list.Select(0)
            self.results_list.Focus(0)
            self.results_list.SetFocus()
        self._on_selected()

    def _on_selected(self) -> None:
        result = self.selected()
        self.use_btn.Enable(result is not None)
        self.fav_btn.Enable(result is not None)
        if result is None:
            self.detail.SetValue("")
            return
        lines = [result.display_name]
        if result.genre:
            lines.append(f"Category: {result.genre}")
        if result.episode_count:
            lines.append(f"Episodes in the directory: {result.episode_count}")
        if result.released:
            lines.append(f"Most recent episode: {result.released}")
        lines.append(f"Feed: {result.feed_url}")
        if result.homepage:
            lines.append(f"Page: {result.homepage}")
        self.detail.SetValue("\n".join(lines))
        self.detail.SetInsertionPoint(0)

    # -- actions ----------------------------------------------------------

    def on_use(self) -> None:
        result = self.selected()
        if result is None:
            return
        self.chosen = result
        self.EndModal(wx.ID_OK)

    def on_favorite(self) -> None:
        result = self.selected()
        if result is None:
            return
        changed, message = favorites_mod.add(
            self.app_space, favorites_mod.Favorite.from_result(result))
        self.status.SetLabel(message)
        LOG.info("%s", message)
        if not changed:
            wx.Bell()

    def _on_close(self, event) -> None:
        self._alive = False
        event.Skip()


class FavoritesDialog(wx.Dialog):
    """The shows you marked, to come back to without searching again."""

    def __init__(self, parent, app_space) -> None:
        super().__init__(parent, title="Favourite podcasts",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        help_mod.install(self)
        self.library = favorites_mod.Library(app=app_space)
        self.chosen: favorites_mod.Favorite | None = None

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(
            self,
            label="Bookmarks, not subscriptions: nothing here is checked or\n"
                  "downloaded for you."), 0, wx.ALL, 10)

        list_label = wx.StaticText(self, label="&Favourites:")
        root.Add(list_label, 0, wx.LEFT | wx.RIGHT, 10)
        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        for heading, width in _FAVORITE_COLUMNS:
            self.list.AppendColumn(heading, width=width)
        self.list.SetToolTip(
            "The shows you have marked. Arrow through them; Enter takes the "
            "highlighted one back to the main window."
        )
        set_accessible_name(self.list, "Favourite podcasts")
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self.on_use())
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _e: self._on_selected())
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda _e: self._on_selected())
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        self.status = wx.StaticText(self, label="")
        set_accessible_name(self.status, "Favourites status")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.use_btn = wx.Button(self, wx.ID_OK, label="&Use this podcast")
        self.use_btn.SetToolTip(
            "Puts this show's feed address into the main window.")
        self.use_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_use())
        self.use_btn.Enable(False)
        row.Add(self.use_btn, 0, wx.RIGHT, 6)

        self.remove_btn = wx.Button(self, label="&Remove")
        self.remove_btn.SetToolTip(
            "Takes this show off the list. Nothing you have already harvested "
            "from it is deleted or changed."
        )
        self.remove_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_remove())
        self.remove_btn.Enable(False)
        row.Add(self.remove_btn, 0, wx.RIGHT, 12)

        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.SetToolTip("Closes this window.")
        row.AddStretchSpacer()
        row.Add(close_btn, 0)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(720, 480))
        self.Fit()
        self.CentreOnParent()
        self.refresh()
        self.list.SetFocus()

    def refresh(self) -> None:
        entries = self.library.refresh()
        self.list.DeleteAllItems()
        for favorite in entries:
            row = self.list.InsertItem(self.list.GetItemCount(), favorite.title)
            self.list.SetItem(row, 1, favorite.artist)
            self.list.SetItem(row, 2, favorite.added_at[:10])
        if entries:
            self.status.SetLabel(f"{len(entries)} favourite(s).")
            self.list.Select(0)
            self.list.Focus(0)
        else:
            self.status.SetLabel(
                "Nothing here yet. Find a podcast, then use Add to favourites.")
        self._on_selected()

    def selected(self) -> favorites_mod.Favorite | None:
        row = self.list.GetFirstSelected()
        entries = self.library.entries
        return entries[row] if 0 <= row < len(entries) else None

    def _on_selected(self) -> None:
        found = self.selected()
        self.use_btn.Enable(found is not None)
        self.remove_btn.Enable(found is not None)

    def on_use(self) -> None:
        found = self.selected()
        if found is None:
            return
        self.chosen = found
        self.EndModal(wx.ID_OK)

    def on_remove(self) -> None:
        found = self.selected()
        if found is None:
            return
        changed, message = self.library.remove(found.feed_url)
        LOG.info("%s", message)
        self.refresh()
        self.status.SetLabel(message)
        if not changed:
            wx.Bell()
