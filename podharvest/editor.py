"""Every tag and every chapter of one episode, on six keyboard-reachable pages.

The five tag pages are generated from `podharvest.audio_tags_core.TAG_FIELDS`,
the table shared byte-for-byte with QUILL Audio Studio, so the two apps show
the same fields under the same names with the same explanations without either
having to remember to. The sixth page is the chapter editor: the list, the
transport, and the tools for reshaping a chapter list by ear.

Three things about the layout are deliberate rather than incidental:

- Each page is a `FlexGridSizer` of label-then-control rows and **not** a
  `wx.StaticBox` group. `IsDialogMessage` scopes its mnemonic search to the
  enclosing StaticBox, which is why the main window avoids `&` mnemonics
  altogether; without the boxes that problem does not arise, so these pages
  get mnemonics *and* the keys below.
- Mnemonics are unique within a page. Only the visible notebook page's
  controls can be reached, so pages may reuse letters between them.
- The label is created before the control it labels, because that creation
  order is what Win32 uses to pair the two.

The dialog is a pure editor: it hands back the edited tags and chapter list.
Writing is the caller's job, so a slow save never happens inside a modal.

The chapter keys, identical to QUILL's: Alt with Left or Right nudges the
selected chapter's start by one step, Shift as well moves ten steps, and Enter
on the list opens the chapter for editing.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import wx

from podharvest import audio_tags_core as core
from podharvest import help as help_mod
from podharvest.a11y import set_accessible_name, size_for_text
from podharvest.player import PlayerPanel
from podharvest.util import LOG

#: How long a run of nudges must go quiet before the full sentence is spoken.
NUDGE_SETTLE_MS = 600
#: The window "Hear boundary" plays: this much before the marker, and after.
BOUNDARY_LEAD_MS = 3_000
BOUNDARY_TAIL_MS = 2_000
#: The longest edge of the cover thumbnail, in pixels.
THUMBNAIL_PX = 160


def _transcript_beside(audio: Path) -> Path | None:
    """The transcript for an audio file, when one sits next to it.

    podHarvest writes `<slug>.md` beside `<slug>.mp3` for a local file, and
    into the show's transcripts folder for a harvested episode. Only the
    first is findable from the audio path alone, which is enough: the
    phrase search says plainly when there is no transcript, and that is a
    better answer than opening a file dialog nobody asked for.
    """
    for suffix in (".md", ".txt"):
        candidate = audio.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def _plain(label: str) -> str:
    """A label as a screen reader should hear it: no ampersand, no colon."""
    return label.replace("&", "").rstrip(": ").strip()


class TagPage(wx.Panel):
    """One notebook page: every field of one group, as label-then-control rows."""

    def __init__(self, parent: wx.Window, group: str) -> None:
        super().__init__(parent)
        self.controls: dict[str, wx.Window] = {}
        self.totals: dict[str, wx.TextCtrl] = {}
        self._fields = core.fields_in(group)

        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1, 1)
        for field in self._fields:
            self._add_field(grid, field)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(root)

    def _add_field(self, grid: wx.FlexGridSizer, field) -> None:
        """Add one row: the label first, then the control. The order is the point."""
        if field.kind == "bool":
            # A checkbox carries its own label, so there is no StaticText to
            # order against; the empty cell keeps the two columns aligned.
            grid.Add(wx.StaticText(self, label=""), 0)
            check = wx.CheckBox(self, label=field.label)
            check.SetToolTip(field.help)
            set_accessible_name(check, _plain(field.label))
            grid.Add(check, 0, wx.EXPAND)
            self.controls[field.key] = check
            return

        grid.Add(wx.StaticText(self, label=field.label), 0, wx.ALIGN_CENTER_VERTICAL)
        if field.kind == "pair":
            row = wx.BoxSizer(wx.HORIZONTAL)
            number = wx.TextCtrl(self, size=wx.Size(70, -1))
            number.SetToolTip(field.help)
            set_accessible_name(number, f"{_plain(field.label)}, number")
            row.Add(number, 0, wx.RIGHT, 6)
            row.Add(
                wx.StaticText(self, label="of"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6
            )
            total = wx.TextCtrl(self, size=wx.Size(70, -1))
            total.SetToolTip(field.help)
            set_accessible_name(total, f"{_plain(field.label)}, total")
            row.Add(total, 0)
            grid.Add(row, 0, wx.EXPAND)
            self.controls[field.key] = number
            self.totals[field.key] = total
            return

        style = wx.TE_MULTILINE if field.kind == "multiline" else 0
        ctrl = wx.TextCtrl(self, style=style)
        if field.kind == "multiline":
            # Lines of this control's own font, not pixels: a lyrics or comment
            # box specified in pixels shows one line once text is scaled up.
            size_for_text(ctrl, lines=5)
        ctrl.SetToolTip(field.help)
        set_accessible_name(ctrl, _plain(field.label))
        grid.Add(ctrl, 0, wx.EXPAND)
        self.controls[field.key] = ctrl

    def seed(self, tags: core.AudioTags) -> None:
        """Fill every control on this page from *tags*."""
        for field in self._fields:
            value = tags.get(field.key)
            ctrl = self.controls[field.key]
            if field.kind == "bool":
                ctrl.SetValue(bool(value))
            elif field.kind == "pair":
                number, _sep, total = value.partition("/")
                ctrl.SetValue(number)
                self.totals[field.key].SetValue(total)
            else:
                ctrl.SetValue(value)

    def collect(self, tags: core.AudioTags) -> None:
        """Write every control on this page back into *tags*."""
        for field in self._fields:
            ctrl = self.controls[field.key]
            if field.kind == "bool":
                tags.set(field.key, "1" if ctrl.GetValue() else "")
            elif field.kind == "pair":
                number = ctrl.GetValue().strip()
                total = self.totals[field.key].GetValue().strip()
                tags.set(field.key, f"{number}/{total}" if total else number)
            else:
                tags.set(field.key, ctrl.GetValue())


class CoverPage(wx.Panel):
    """The embedded cover image: what it is, and how to change it.

    The description is a text readout first and a thumbnail second, in that
    order, because a picture tells a sighted person everything about the art
    and a screen-reader user nothing at all.
    """

    def __init__(
        self,
        parent: wx.Window,
        cover: core.CoverArt | None,
        *,
        announce: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.cover = cover
        self._announce_fn = announce

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label="Current cover art:"), 0, wx.LEFT | wx.TOP, 10)
        self.summary = wx.StaticText(self, label=core.describe_cover(cover))
        set_accessible_name(self.summary, "Cover art description")
        root.Add(self.summary, 0, wx.EXPAND | wx.ALL, 10)

        self.thumbnail = wx.StaticBitmap(self)
        root.Add(self.thumbnail, 0, wx.LEFT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(self, label="&Load image...")
        load_btn.SetToolTip(
            "Chooses a JPEG or PNG image to embed as this episode's cover art. "
            "The file is checked by its real contents rather than its name, and "
            "images over 8 MB are refused."
        )
        load_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_load())
        row.Add(load_btn, 0, wx.RIGHT, 6)

        save_btn = wx.Button(self, label="&Save image as...")
        save_btn.SetToolTip(
            "Writes the embedded cover art out to a picture file of its own, "
            "leaving the audio file untouched."
        )
        save_btn.Bind(wx.EVT_BUTTON, lambda _e: self._on_save())
        row.Add(save_btn, 0, wx.RIGHT, 6)

        remove_btn = wx.Button(self, label="&Remove image")
        remove_btn.SetToolTip(
            "Takes the cover art off this episode when you save, not before."
        )
        remove_btn.Bind(wx.EVT_BUTTON, lambda _e: self.remove_cover())
        row.Add(remove_btn, 0)
        root.Add(row, 0, wx.LEFT | wx.BOTTOM, 10)

        self.SetSizer(root)
        self.refresh()

    def _announce(self, text: str) -> None:
        if self._announce_fn is not None:
            self._announce_fn(text)

    def refresh(self) -> None:
        """Re-read the summary label and the thumbnail from `self.cover`."""
        self.summary.SetLabel(core.describe_cover(self.cover))
        bitmap = self._thumbnail_of(self.cover)
        if bitmap is None:
            # Hiding beats handing SetBitmap a null one, which asserts, and an
            # empty image placeholder is noise on a page that already says in
            # words what the art is.
            self.thumbnail.Hide()
        else:
            self.thumbnail.SetBitmap(bitmap)
            self.thumbnail.Show()
        self.Layout()

    @staticmethod
    def _thumbnail_of(cover):
        """A scaled bitmap of *cover*, or None when it cannot be decoded.

        The decode runs under `wx.LogNull`. wx reports an image it cannot read
        by *logging an error*, which surfaces as a modal "Unknown image data
        format" box -- not as an exception, so a try/except does not stop it.
        A cover somebody else's tagger wrote in a format this build has no
        handler for is a thing to shrug at, not a dialog to interrupt with.
        """
        if cover is None:
            return None
        no_log = wx.LogNull()
        try:
            image = wx.Image(io.BytesIO(cover.data))
            if not image.IsOk():
                return None
            longest = max(image.GetWidth(), image.GetHeight(), 1)
            scale = min(1.0, THUMBNAIL_PX / longest)
            return image.Scale(
                max(1, int(image.GetWidth() * scale)),
                max(1, int(image.GetHeight() * scale)),
                wx.IMAGE_QUALITY_HIGH,
            ).ConvertToBitmap()
        except Exception:  # noqa: BLE001 - an undecodable image is not fatal
            return None
        finally:
            del no_log

    def set_cover(self, cover: core.CoverArt) -> None:
        self.cover = cover
        self.refresh()
        self._announce(f"Cover art loaded. {core.describe_cover(cover)}")

    def remove_cover(self) -> None:
        if self.cover is None:
            self._announce("There is no cover art to remove.")
            return
        self.cover = None
        self.refresh()
        self._announce("Cover art removed.")

    def _on_load(self) -> None:
        with wx.FileDialog(
            self,
            "Choose a cover image",
            wildcard="Images (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            chosen = Path(dlg.GetPath())
        try:
            self.set_cover(core.load_cover(chosen))
        except core.AudioTagError as exc:
            wx.MessageBox(str(exc), "Cannot use that image", wx.OK | wx.ICON_ERROR, self)

    def _on_save(self) -> None:
        if self.cover is None:
            self._announce("There is no cover art to save.")
            return
        suffix = core.cover_extension(self.cover)
        with wx.FileDialog(
            self,
            "Save the cover image as",
            defaultFile=f"cover{suffix}",
            wildcard=f"*{suffix}|*{suffix}",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            out = Path(dlg.GetPath())
        try:
            out.write_bytes(self.cover.data)
        except OSError as exc:
            wx.MessageBox(
                f"Could not save the image: {exc}",
                "Cannot save",
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return
        self._announce(f"Saved {out.name}")


class ChapterDetailsDialog(wx.Dialog):
    """Type a chapter's title and its exact start and end, plus its extras."""

    def __init__(
        self, parent: wx.Window, chapter: core.Chapter, *, lower_ms: int, upper_ms: int
    ) -> None:
        super().__init__(parent, title="Edit chapter")
        help_mod.install(self)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(
                self,
                label=(
                    "Times are hours:minutes:seconds.milliseconds. This chapter "
                    f"may run between {core.format_time_precise(lower_ms)} and "
                    f"{core.format_time_precise(upper_ms)}."
                ),
            ),
            0,
            wx.ALL,
            10,
        )
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1, 1)

        def row(label: str, value: str, tip: str) -> wx.TextCtrl:
            # Label first, then the control -- the pairing screen readers use.
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            ctrl = wx.TextCtrl(self, value=value)
            ctrl.SetToolTip(tip)
            set_accessible_name(ctrl, _plain(label))
            grid.Add(ctrl, 0, wx.EXPAND)
            return ctrl

        self._title = row(
            "&Title:", chapter.title, "The chapter's name, as a player will announce it."
        )
        self._start = row(
            "&Start:",
            core.format_time_precise(chapter.start_ms),
            "Where this chapter begins. Moving it moves the end of the chapter "
            "before it, so the episode stays gapless.",
        )
        self._end = row(
            "&End:",
            core.format_time_precise(chapter.end_ms),
            "Where this chapter ends. Moving it moves the start of the chapter "
            "after it.",
        )
        self._url = row(
            "&Link:",
            chapter.url,
            "An optional web link for this chapter, carried in the Podcasting "
            "2.0 chapters file.",
        )
        self._image = row(
            "&Image:",
            chapter.image,
            "An optional image address for this chapter, carried in the "
            "Podcasting 2.0 chapters file.",
        )
        root.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self, wx.ID_OK, label="OK")
        ok_btn.SetToolTip("Applies these chapter details to the list.")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        cancel_btn.SetToolTip("Leaves the chapter exactly as it was.")
        buttons.AddStretchSpacer()
        buttons.Add(ok_btn, 0, wx.RIGHT, 6)
        buttons.Add(cancel_btn, 0)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

    def values(self) -> tuple[str, int | None, int | None, str, str]:
        """Title, start ms, end ms, link, image. An unparseable time reads None."""
        return (
            self._title.GetValue().strip(),
            core.parse_time(self._start.GetValue()),
            core.parse_time(self._end.GetValue()),
            self._url.GetValue().strip(),
            self._image.GetValue().strip(),
        )


class ChapterPage(wx.Panel):
    """The chapter list, the transport, and the tools for reshaping by ear.

    Nudging is why the transport is here. Setting a boundary means listening,
    moving the marker a little, and listening again, so the step size, the
    audition and the audition-automatically switch sit together.
    """

    def __init__(
        self,
        parent: wx.Window,
        chapters: list[core.Chapter],
        total_ms: int,
        *,
        audio_path: Path | None = None,
        transcript_path: Path | None = None,
        announce: Callable[[str], None] | None = None,
        volume: int = 70,
        muted: bool = False,
        on_volume: Callable[[int, bool], None] | None = None,
        rates: list[float] | None = None,
    ) -> None:
        super().__init__(parent)
        self.chapters = list(chapters)
        self.total_ms = total_ms
        self._announce_fn = announce
        # Read lazily, the first time a phrase is looked for: most sessions
        # here are nudging by ear and never ask for it.
        self._transcript_path = transcript_path
        self._timeline = None
        self._stop_at_ms: int | None = None
        self._wall_announced = False
        self._settle_timer = None
        self.nudge_ms = 500

        root = wx.BoxSizer(wx.VERTICAL)
        # Label before control.
        root.Add(wx.StaticText(self, label="C&hapters:"), 0, wx.LEFT | wx.TOP, 10)
        self.list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.list.SetToolTip(
            "Every chapter, with where it starts and how long it runs. Alt with "
            "Left or Right arrow nudges the highlighted chapter's start earlier "
            "or later by one step; hold Shift as well to move ten steps. Enter "
            "opens the chapter for editing."
        )
        set_accessible_name(self.list, "Chapters")
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda _e: self.on_edit())
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        self.player = PlayerPanel(
            self, announce=announce, volume=volume, muted=muted,
            on_volume=on_volume, rates=rates,
        )
        self.player.set_tick_handler(self._check_stop)
        if audio_path is not None:
            self.player.load(audio_path)
        root.Add(self.player, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        edit_row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler, tip in (
            (
                "&Add chapter...",
                self.on_add,
                "Puts a new chapter marker at the playhead, or at a time you "
                "type, and asks what to call it. The audio is not cut.",
            ),
            (
                "De&lete chapter",
                self.on_delete,
                "Removes the highlighted chapter's marker. The audio is "
                "untouched -- it joins the neighbouring chapter.",
            ),
            (
                "&Edit chapter...",
                self.on_edit,
                "Opens a window to type this chapter's title and its exact "
                "start and end, plus its optional link and image.",
            ),
            (
                "Previe&w chapter",
                self.on_preview,
                "Plays the highlighted chapter from its start and stops at its "
                "end, instead of running on into the next one.",
            ),
        ):
            btn = wx.Button(self, label=label)
            btn.SetToolTip(tip)
            btn.Bind(wx.EVT_BUTTON, lambda _e, h=handler: h())
            edit_row.Add(btn, 0, wx.RIGHT, 6)
        root.Add(edit_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Finding the place by what was said, rather than by ear. Nudging
        # stays for the fine work -- this is the coarse move that precedes
        # it, and gets you within a sentence in one action instead of
        # scrubbing for a minute.
        phrase_row = wx.BoxSizer(wx.HORIZONTAL)
        # Label before control, so a screen reader pairs the two.
        # Alt+I, not Alt+P: the transport's Play owns P, and the page and
        # the player share one key namespace because the player sits inside
        # the page. A test holds that.
        phrase_row.Add(wx.StaticText(self, label="F&ind a phrase:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.phrase_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.phrase_ctrl.SetToolTip(
            "Type words from the transcript and press Enter to move the "
            "playhead to where they were said. Add chapter then puts a "
            "marker there. Needs a transcript with timings, which is what "
            "podHarvest writes unless timestamps were switched off."
        )
        self.phrase_ctrl.SetHint("words from the transcript")
        set_accessible_name(self.phrase_ctrl, "Find a phrase")
        self.phrase_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda _e: self.on_find_phrase())
        phrase_row.Add(self.phrase_ctrl, 1, wx.RIGHT, 6)

        goto_btn = wx.Button(self, label="&Go to it")
        goto_btn.SetToolTip(
            "Moves the playhead to where that phrase was said.")
        goto_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_find_phrase())
        phrase_row.Add(goto_btn, 0)
        root.Add(phrase_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        nudge_row = wx.BoxSizer(wx.HORIZONTAL)
        back_btn = wx.Button(self, label="N&udge back")
        back_btn.SetToolTip(
            "Moves the highlighted chapter's start earlier by one step. Alt "
            "with Left arrow does the same from the list; add Shift for ten."
        )
        back_btn.Bind(wx.EVT_BUTTON, lambda _e: self.nudge(-1))
        nudge_row.Add(back_btn, 0, wx.RIGHT, 6)

        fwd_btn = wx.Button(self, label="Nudge f&orward")
        fwd_btn.SetToolTip(
            "Moves the highlighted chapter's start later by one step. Alt with "
            "Right arrow does the same from the list; add Shift for ten."
        )
        fwd_btn.Bind(wx.EVT_BUTTON, lambda _e: self.nudge(1))
        nudge_row.Add(fwd_btn, 0, wx.RIGHT, 6)

        nudge_row.Add(
            wx.StaticText(self, label="Step si&ze:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4
        )
        self.step_choice = wx.Choice(
            self, choices=[core.format_time_precise(ms) for ms in core.NUDGE_STEPS_MS]
        )
        self.step_choice.SetToolTip("How far one nudge moves a marker.")
        set_accessible_name(self.step_choice, "Nudge step")
        self.step_choice.SetSelection(core.NUDGE_STEPS_MS.index(500))
        self.step_choice.Bind(wx.EVT_CHOICE, lambda _e: self._on_step_changed())
        nudge_row.Add(self.step_choice, 0, wx.RIGHT, 12)

        hear_btn = wx.Button(self, label="Hear &boundary")
        hear_btn.SetToolTip(
            "Plays three seconds before the highlighted chapter's start and two "
            "seconds after it, then stops -- the quickest way to judge a marker."
        )
        hear_btn.Bind(wx.EVT_BUTTON, lambda _e: self.hear_boundary())
        nudge_row.Add(hear_btn, 0, wx.RIGHT, 6)

        self.hear_after = wx.CheckBox(self, label="Hear after each &nudge")
        self.hear_after.SetToolTip(
            "Plays the boundary automatically after every nudge. Off by "
            "default, because audio on every keypress is something to ask for."
        )
        set_accessible_name(self.hear_after, "Hear after each nudge")
        nudge_row.Add(self.hear_after, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(nudge_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 10)

        self.SetSizer(root)
        self.refresh()

    # -- helpers ---------------------------------------------------------------

    def _announce(self, text: str) -> None:
        if self._announce_fn is not None:
            self._announce_fn(text)

    def _error(self, message: str) -> None:
        wx.MessageBox(message, "Cannot do that", wx.OK | wx.ICON_INFORMATION, self)

    def _selected(self) -> int:
        index = self.list.GetSelection()
        return index if 0 <= index < len(self.chapters) else -1

    def refresh(self, select: int = -1) -> None:
        self.list.Set([
            f"{c.index + 1}. {c.title} - starts {core.format_time_precise(c.start_ms)}, "
            f"runs {core.format_time_precise(c.duration_ms)}"
            for c in self.chapters
        ])
        if self.chapters:
            self.list.SetSelection(max(0, min(select, len(self.chapters) - 1)))

    def _apply(self, chapters: list[core.Chapter], select: int, spoken: str) -> None:
        self.chapters = chapters
        self.refresh(select)
        self._announce(spoken)

    def _on_step_changed(self) -> None:
        selection = self.step_choice.GetSelection()
        if 0 <= selection < len(core.NUDGE_STEPS_MS):
            self.nudge_ms = core.NUDGE_STEPS_MS[selection]

    # -- operations ------------------------------------------------------------

    def on_add(self) -> None:
        default = core.format_time_precise(self.player.playhead_ms())
        with wx.TextEntryDialog(
            self,
            "Where should the new chapter start? Times are "
            "hours:minutes:seconds.milliseconds; the playhead's position is "
            "filled in.",
            "Add chapter",
            default,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            at_ms = core.parse_time(dlg.GetValue())
        if at_ms is None:
            self._error("That is not a time. Use hours:minutes:seconds.milliseconds.")
            return
        with wx.TextEntryDialog(
            self, "What is the new chapter called?", "Add chapter", "New chapter"
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            title = dlg.GetValue().strip() or "New chapter"
        try:
            chapters = core.add_chapter(self.chapters, at_ms, title=title)
        except core.ChapterEditError as exc:
            self._error(str(exc))
            return
        index = next(
            (i for i, c in enumerate(chapters) if c.title == title and c.start_ms <= at_ms),
            len(chapters) - 1,
        )
        self._apply(
            chapters, index, f"Added {title} at {core.format_time_precise(at_ms)}"
        )

    def on_delete(self) -> None:
        index = self._selected()
        if index < 0:
            self._error("No chapter is selected.")
            return
        title = self.chapters[index].title
        try:
            chapters = core.delete_chapter(self.chapters, index)
        except core.ChapterEditError as exc:
            self._error(str(exc))
            return
        self._apply(
            chapters, max(0, index - 1), f"Deleted {title}. The audio is unchanged."
        )

    def on_edit(self) -> None:
        index = self._selected()
        if index < 0:
            self._error("No chapter is selected.")
            return
        chapter = self.chapters[index]
        lower = self.chapters[index - 1].start_ms if index > 0 else chapter.start_ms
        upper = (
            self.chapters[index + 1].end_ms
            if index + 1 < len(self.chapters)
            else chapter.end_ms
        )
        dlg = ChapterDetailsDialog(self, chapter, lower_ms=lower, upper_ms=upper)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            title, start_ms, end_ms, url, image = dlg.values()
        finally:
            dlg.Destroy()
        if start_ms is None or end_ms is None:
            self._error("Start and end must be times, as hours:minutes:seconds.milliseconds.")
            return
        try:
            updated = core.set_chapter_bounds(self.chapters, index, start_ms, end_ms)
        except core.ChapterEditError as exc:
            self._error(str(exc))
            return
        updated[index].title = title or chapter.title
        updated[index].url = url
        updated[index].image = image
        self._apply(
            updated,
            index,
            f"{updated[index].title} now runs "
            f"{core.format_time_precise(updated[index].start_ms)} to "
            f"{core.format_time_precise(updated[index].end_ms)}",
        )

    def on_find_phrase(self) -> None:
        """Move the playhead to where a phrase was said.

        Says where it went, in words: moving a playhead is invisible, and a
        silent jump is indistinguishable from a control that did nothing.
        """
        from podharvest import timing_core

        needle = self.phrase_ctrl.GetValue().strip().lower()
        if not needle:
            return
        if self._timeline is None:
            self._timeline = (
                timing_core.load_timeline(self._transcript_path)
                if self._transcript_path is not None
                else timing_core.Timeline(segments=(), source="none"))
        if self._timeline.is_empty():
            self._error(
                "This episode has no transcript timings, so a phrase cannot "
                "be found in it. Transcribe it with timestamps switched on "
                "and this will work.")
            return
        position = self._timeline.text().lower().find(needle)
        if position < 0:
            self._error(f"'{needle}' is not in this transcript.")
            return
        when = self._timeline.time_at_char(position)
        if when is None:
            self._error("There is no timing for that phrase.")
            return
        self.player.seek_to(when)
        self._announce(
            f"Moved to {core.format_time_precise(when)}. "
            "Add chapter puts a marker here.")

    def on_preview(self) -> None:
        index = self._selected()
        if index < 0:
            self._error("No chapter is selected.")
            return
        chapter = self.chapters[index]
        self.player.seek_to(chapter.start_ms)
        self._stop_at_ms = chapter.end_ms
        self.player.play()

    def hear_boundary(self) -> None:
        index = self._selected()
        if index < 0:
            self._error("No chapter is selected.")
            return
        start = self.chapters[index].start_ms
        self.player.seek_to(max(0, start - BOUNDARY_LEAD_MS))
        self._stop_at_ms = min(self.total_ms, start + BOUNDARY_TAIL_MS)
        self.player.play()

    def _check_stop(self) -> bool:
        """Stop playback if an armed preview has run past its end."""
        if self._stop_at_ms is None:
            return False
        if self.player.playhead_ms() < self._stop_at_ms:
            return False
        self._stop_at_ms = None
        self.player.pause()
        return True

    def nudge(self, direction: int, multiplier: int = 1) -> None:
        """Move the selected chapter's start by one step (or ten) either way.

        Announces the bare new time, not a sentence: this runs at key-repeat
        speed and a sentence ten times a second is unusable. The full sentence
        follows once the run goes quiet.
        """
        index = self._selected()
        if index < 0:
            self._error("No chapter is selected.")
            return
        step = max(10, int(self.nudge_ms)) * max(1, multiplier)
        try:
            chapters, applied = core.nudge_chapter_start(
                self.chapters, index, step * (1 if direction >= 0 else -1)
            )
        except core.ChapterEditError as exc:
            self._error(str(exc))
            return
        if applied == 0:
            if not self._wall_announced:
                self._wall_announced = True
                self._announce("Cannot move further.")
            return
        self._wall_announced = False
        self._apply(chapters, index, core.format_time_precise(chapters[index].start_ms))
        self._schedule_settle(index)
        if self.hear_after.GetValue():
            self.hear_boundary()

    def _schedule_settle(self, index: int) -> None:
        def settle() -> None:
            if not 0 <= index < len(self.chapters):
                return
            chapter = self.chapters[index]
            self._announce(
                f"{chapter.title} starts {core.format_time_precise(chapter.start_ms)}, "
                f"runs {core.format_time_precise(chapter.duration_ms)}"
            )

        if self._settle_timer is not None:
            self._settle_timer.Stop()
        self._settle_timer = wx.CallLater(NUDGE_SETTLE_MS, settle)

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if event.AltDown() and code in (wx.WXK_LEFT, wx.WXK_RIGHT):
            self.nudge(-1 if code == wx.WXK_LEFT else 1, 10 if event.ShiftDown() else 1)
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_edit()
            return
        event.Skip()


class EditorDialog(wx.Dialog):
    """Every tag and every chapter of one episode. Hands the edit back; never saves."""

    def __init__(
        self,
        parent: wx.Window,
        path: Path,
        *,
        announce: Callable[[str], None] | None = None,
        volume: int = 70,
        muted: bool = False,
        on_volume: Callable[[int, bool], None] | None = None,
        rates: list[float] | None = None,
    ) -> None:
        super().__init__(
            parent,
            title=f"Tags and chapters - {Path(path).name}",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        help_mod.install(self)
        from podharvest import tags as tags_mod

        self.path = Path(path)
        self._tags = tags_mod.read_tags(self.path)
        chapters = tags_mod.read_chapters(self.path)
        self.pages: dict[str, wx.Panel] = {}
        self.controls: dict[str, wx.Window] = {}
        self.totals: dict[str, wx.TextCtrl] = {}

        root = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label=f"Editing {self.path.name}")
        heading.SetFont(heading.GetFont().Scaled(1.2).Bold())
        root.Add(heading, 0, wx.ALL, 10)

        notebook = wx.Notebook(self)
        notebook.SetToolTip(
            "Six pages. Control+Tab moves to the next, Control+Shift+Tab to the "
            "previous; Tab moves between the fields of the page you are on."
        )
        set_accessible_name(notebook, "Tag and chapter pages")
        for group, label in core.GROUPS:
            page = TagPage(notebook, group)
            page.seed(self._tags)
            notebook.AddPage(page, label)
            self.pages[group] = page
            self.controls.update(page.controls)
            self.totals.update(page.totals)

        self.cover_page = CoverPage(notebook, self._tags.cover, announce=announce)
        notebook.AddPage(self.cover_page, "Cover art")
        self.pages["cover"] = self.cover_page

        total_ms = chapters[-1].end_ms if chapters else 0
        self.chapter_page = ChapterPage(
            notebook,
            chapters,
            total_ms,
            audio_path=self.path,
            transcript_path=_transcript_beside(self.path),
            announce=announce,
            volume=volume,
            muted=muted,
            on_volume=on_volume,
            rates=rates,
        )
        notebook.AddPage(self.chapter_page, "Chapters")
        self.pages["chapters"] = self.chapter_page
        root.Add(notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self, wx.ID_OK, label="Save")
        ok_btn.SetToolTip("Writes these tag and chapter edits into the episode file.")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        cancel_btn.SetToolTip("Closes without changing the file.")
        buttons.AddStretchSpacer()
        buttons.Add(ok_btn, 0, wx.RIGHT, 6)
        buttons.Add(cancel_btn, 0)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(680, 620))
        self.Fit()
        self.CentreOnParent()

    def result_tags(self) -> core.AudioTags:
        """The edited tags. The set read from the file is never mutated."""
        edited = self._tags.copy()
        for group, _label in core.GROUPS:
            self.pages[group].collect(edited)
        edited.cover = self.cover_page.cover
        return edited

    def result_chapters(self) -> list[core.Chapter]:
        """The edited chapter list."""
        return list(self.chapter_page.chapters)

    def release_audio(self) -> None:
        """Let go of the file so it can be rewritten."""
        self.chapter_page.player.shutdown()


def edit_file(
    parent: wx.Window,
    path: Path,
    *,
    announce=None,
    settings=None,
    on_settings_changed=None,
) -> bool:
    """Open *path* in the editor and save what comes back. True when saved.

    The save is the caller's, not the dialog's, so a slow write never happens
    inside a modal -- and so the dialog stays a pure editor that can be tested
    without a filesystem.

    *settings* supplies the remembered preview volume and the playback speeds
    on offer; *on_settings_changed* is called whenever the volume moves, so the
    level survives closing the window.
    """
    from podharvest import chapters as chapters_mod
    from podharvest import tags as tags_mod

    volume = int(getattr(settings, "preview_volume", 70)) if settings else 70
    muted = bool(getattr(settings, "preview_muted", False)) if settings else False
    rates = list(getattr(settings, "playback_rates", []) or []) if settings else None

    def remember(level: int, is_muted: bool) -> None:
        if settings is None:
            return
        settings.preview_volume = level
        settings.preview_muted = is_muted
        if on_settings_changed is not None:
            on_settings_changed()

    dlg = EditorDialog(
        parent, path, announce=announce, volume=volume, muted=muted,
        on_volume=remember, rates=rates,
    )
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return False
        tags = dlg.result_tags()
        chapters = dlg.result_chapters()
        dlg.release_audio()
    finally:
        dlg.Destroy()
    ok = tags_mod.write_tags(Path(path), tags)
    if chapters:
        chapters_mod.embed_chapter_objects(Path(path), chapters)
    if ok:
        LOG.info("Saved tags and chapters to %s", Path(path).name)
    return ok
