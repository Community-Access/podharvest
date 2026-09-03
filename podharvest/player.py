"""A small transport, because a chapter marker is judged by ear.

Nudging a boundary half a second at a time only means anything if you can hear
the result, so the Tag and Chapter Editor needs playback and podHarvest had
none. `wx.media.MediaCtrl` provides it through the platform's own media
backend: no new dependency, and it reads the containers podcasts actually
arrive in.

The panel deliberately knows nothing about chapters. It plays, it seeks, it
says where it is, and it can be told to stop at a point -- which is everything
the preview and the boundary audition need, and it keeps the chapter rules in
the shared model where both apps read them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx
import wx.media

from podharvest.a11y import set_accessible_name
from podharvest.audio_tags_core import format_time_precise
from podharvest.util import LOG

#: How often the transport re-reads the playhead, in milliseconds. Fast enough
#: that a stop-at point lands within a frame of where it was asked for, slow
#: enough to cost nothing.
TICK_MS = 100

#: How far Rewind and Forward jump. Ten seconds is the podcast convention, and
#: it is about the length of a sentence you missed.
SKIP_MS = 10_000

#: The speeds offered when nobody has said otherwise. Past 2x on purpose:
#: listening at 3x is a normal way to get through a backlog, and 0.5x is how
#: a fast speaker becomes followable. The list is a setting -- see
#: `Settings.playback_rates` -- so this is a starting point, not a ceiling.
DEFAULT_RATES: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)


def rate_label(rate: float) -> str:
    """``1.5`` -> ``1.5x``, ``2.0`` -> ``2x``. Read aloud, so no stray zero."""
    text = f"{float(rate):g}"
    return f"{text}x"


class PlayerPanel(wx.Panel):
    """Play, pause, stop, a position readout, and a stop-at point."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        announce: Callable[[str], None] | None = None,
        volume: int = 70,
        muted: bool = False,
        on_volume: Callable[[int, bool], None] | None = None,
        skip_back_ms: int = SKIP_MS,
        skip_forward_ms: int = SKIP_MS,
        rates: tuple[float, ...] | list[float] | None = None,
    ) -> None:
        super().__init__(parent)
        self._announce_fn = announce
        self._stop_at: int | None = None
        self._on_tick_cb: Callable[[], None] | None = None
        self._loaded = False
        self._volume = max(0, min(100, int(volume)))
        self._muted = bool(muted)
        # Volume before muting, so unmute restores what you had rather than
        # some default. Muting at zero would otherwise unmute to silence.
        self._pre_mute_volume = self._volume or 70
        self._on_volume_cb = on_volume
        #: Said once, not on every attempt, when the backend will not do rates.
        # Speeds this backend has already refused, so each is reported once
        # rather than on every selection.
        self._refused: set[float] = set()
        self._skip_back_ms = max(1_000, int(skip_back_ms))
        self._skip_forward_ms = max(1_000, int(skip_forward_ms))
        self._rates = list(rates) if rates else list(DEFAULT_RATES)
        if 1.0 not in self._rates:
            self._rates.append(1.0)
        self._rates.sort()

        self._media = wx.media.MediaCtrl(self)
        self._media.Hide()  # audio only; the controls below are the interface

        row = wx.BoxSizer(wx.HORIZONTAL)
        self._play_btn = wx.Button(self, label="&Play")
        self._play_btn.SetToolTip("Starts or pauses playback.")
        self._play_btn.Bind(wx.EVT_BUTTON, lambda _e: self.toggle())
        row.Add(self._play_btn, 0, wx.RIGHT, 6)

        stop_btn = wx.Button(self, label="&Stop")
        stop_btn.SetToolTip("Stops playback and forgets any armed preview.")
        stop_btn.Bind(wx.EVT_BUTTON, lambda _e: self.stop())
        row.Add(stop_btn, 0, wx.RIGHT, 6)

        self._rewind_btn = rewind_btn = wx.Button(self, label="&Rewind")
        rewind_btn.SetToolTip(
            f"Jumps back {self._skip_back_ms // 1000} seconds -- usually about "
            "the sentence you missed. Does not go past the start of the file. "
            "The amount is set in Settings."
        )
        rewind_btn.Bind(wx.EVT_BUTTON, lambda _e: self.skip_back())
        row.Add(rewind_btn, 0, wx.RIGHT, 6)

        self._forward_btn = forward_btn = wx.Button(self, label="&Forward")
        forward_btn.SetToolTip(
            f"Jumps on {self._skip_forward_ms // 1000} seconds -- long enough "
            "to clear an advert break if you set it that way. Does not go past "
            "the end of the file. The amount is set in Settings."
        )
        forward_btn.Bind(wx.EVT_BUTTON, lambda _e: self.skip_forward())
        row.Add(forward_btn, 0, wx.RIGHT, 12)

        # Label before control: screen readers pair them by creation order.
        row.Add(
            wx.StaticText(self, label="Spee&d:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            4,
        )
        self.rate_choice = wx.Choice(
            self, choices=[rate_label(r) for r in self._rates])
        self.rate_choice.SetToolTip(
            "How fast to play. Faster gets you through a backlog; slower makes "
            "a fast speaker followable, and at 0.75x it is much easier to hear "
            "exactly where a sentence starts, which is the whole job when "
            "placing a chapter marker. The speeds on offer are yours to set in "
            "Settings."
        )
        set_accessible_name(self.rate_choice, "Playback speed")
        self.rate_choice.SetSelection(self._rates.index(1.0))
        self.rate_choice.Bind(wx.EVT_CHOICE, lambda _e: self._on_rate())
        row.Add(self.rate_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        # Label before control: screen readers pair them by creation order.
        row.Add(
            wx.StaticText(self, label="Position:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.position = wx.StaticText(self, label=format_time_precise(0))
        set_accessible_name(self.position, "Playback position")
        row.Add(self.position, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        # Label before control, so a screen reader pairs them.
        row.Add(
            wx.StaticText(self, label="&Volume:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            4,
        )
        self.volume_slider = wx.Slider(
            self, value=self._volume, minValue=0, maxValue=100,
            size=wx.Size(120, -1), style=wx.SL_HORIZONTAL,
        )
        self.volume_slider.SetToolTip(
            "How loud the preview plays, from 0 to 100. Left and Right arrow "
            "move it; the level is remembered for next time."
        )
        set_accessible_name(self.volume_slider, "Preview volume")
        self.volume_slider.Bind(wx.EVT_SLIDER, lambda _e: self._on_slider())
        row.Add(self.volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.mute_btn = wx.Button(self, label="&Mute")
        self.mute_btn.SetToolTip(
            "Silences the preview without losing the volume you set; pressing "
            "it again puts that level back."
        )
        self.mute_btn.Bind(wx.EVT_BUTTON, lambda _e: self.toggle_mute())
        row.Add(self.mute_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(row, 0, wx.ALL, 6)
        self.SetSizer(root)
        self._sync_mute_label()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self._tick(), self._timer)

    # -- wiring ---------------------------------------------------------------

    def _announce(self, text: str) -> None:
        """Say something the screen reader would not otherwise say.

        Muting is exactly that: the button's label changes, but a label change
        on a control that does not have focus is silent.
        """
        if self._announce_fn is not None:
            self._announce_fn(text)

    def set_tick_handler(self, handler: Callable[[], None] | None) -> None:
        """Call *handler* on every tick -- how the editor watches its stop point."""
        self._on_tick_cb = handler

    def load(self, path: Path) -> bool:
        """Open *path*. False when the platform backend will not play it."""
        self._apply_volume()
        if not self._media.Load(str(path)):
            LOG.warning(
                "Could not open %s for playback. Editing still works; only the "
                "preview does not.",
                Path(path).name,
            )
            self._loaded = False
            return False
        self._loaded = True
        return True

    # -- volume ---------------------------------------------------------------

    def volume(self) -> int:
        """The level 0-100, as set, whether or not it is currently muted."""
        return self._volume

    def is_muted(self) -> bool:
        return self._muted

    def set_volume(self, percent: int, *, announce: bool = False) -> None:
        """Set the level and apply it. Announces only when asked to.

        MediaCtrl takes 0.0-1.0; the slider and the setting are whole percent
        because that is what a person reasons about and what reads well.
        """
        self._volume = max(0, min(100, int(percent)))
        if self._volume:
            self._pre_mute_volume = self._volume
        if self.volume_slider.GetValue() != self._volume:
            self.volume_slider.SetValue(self._volume)
        self._apply_volume()
        self._remember()
        if announce:
            self._announce(f"Volume {self._volume} percent")

    def toggle_mute(self) -> None:
        """Silence or restore the preview, and say which just happened."""
        self._muted = not self._muted
        if not self._muted and not self._volume:
            # Unmuting to silence would look like the button doing nothing.
            self._volume = self._pre_mute_volume
            self.volume_slider.SetValue(self._volume)
        self._apply_volume()
        self._sync_mute_label()
        self._remember()
        self._announce("Muted" if self._muted else f"Unmuted, volume {self._volume} percent")

    def _apply_volume(self) -> None:
        try:
            self._media.SetVolume(0.0 if self._muted else self._volume / 100.0)
        except Exception:  # noqa: BLE001 - a backend without volume still plays
            LOG.debug("This media backend does not support setting the volume.")

    def _sync_mute_label(self) -> None:
        self.mute_btn.SetLabel("Un&mute" if self._muted else "&Mute")

    def _remember(self) -> None:
        if self._on_volume_cb is not None:
            self._on_volume_cb(self._volume, self._muted)

    def _on_slider(self) -> None:
        value = self.volume_slider.GetValue()
        # Moving the slider off zero is an unmute in every way that matters.
        if self._muted and value:
            self._muted = False
            self._sync_mute_label()
        self.set_volume(value)

    def play(self) -> None:
        if not self._loaded:
            return
        self._media.Play()
        self._apply_volume()
        self._timer.Start(TICK_MS)
        self._play_btn.SetLabel("&Pause")

    def pause(self) -> None:
        self._media.Pause()
        self._timer.Stop()
        self._play_btn.SetLabel("&Play")

    def toggle(self) -> None:
        if self._media.GetState() == wx.media.MEDIASTATE_PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._media.Stop()
        self._timer.Stop()
        self._stop_at = None
        self._play_btn.SetLabel("&Play")

    def skip(self, delta_ms: int) -> None:
        """Jump *delta_ms* from where we are, clamped to the file.

        Clamped rather than refused: pressing Rewind at four seconds in should
        take you to the beginning, not do nothing.
        """
        length = self.length_ms()
        target = self.playhead_ms() + int(delta_ms)
        target = max(0, min(target, length) if length > 0 else max(0, target))
        self.seek_to(target)

    def set_skip_steps(self, back_ms: int, forward_ms: int) -> None:
        """Change the jump amounts without rebuilding the transport.

        The button tooltips name the amounts, so they are rewritten too --
        otherwise Settings would say one thing and the button another.
        """
        self._skip_back_ms = max(1_000, int(back_ms))
        self._skip_forward_ms = max(1_000, int(forward_ms))
        for button, seconds, direction in (
            (self._rewind_btn, self._skip_back_ms // 1000, "back"),
            (self._forward_btn, self._skip_forward_ms // 1000, "on"),
        ):
            button.SetToolTip(
                f"Jumps {direction} {seconds} seconds. Does not go past the "
                "end of the file. The amount is set in Settings."
            )

    def skip_back(self) -> None:
        """Jump back by the configured rewind step."""
        self.skip(-self._skip_back_ms)

    def skip_forward(self) -> None:
        """Jump on by the configured forward step."""
        self.skip(self._skip_forward_ms)

    def rate(self) -> float:
        """The current playback speed, as a multiplier."""
        selection = self.rate_choice.GetSelection()
        return self._rates[selection] if 0 <= selection < len(self._rates) else 1.0

    def rates(self) -> list[float]:
        """The speeds this transport is offering."""
        return list(self._rates)

    def set_rates(self, rates) -> None:
        """Replace the speeds on offer, keeping the current one if it survives.

        Called when the settings change, so the box does not go on offering
        speeds somebody has just removed.
        """
        current = self.rate()
        self._rates = sorted(set(list(rates) or []) | {1.0})
        self.rate_choice.Set([rate_label(r) for r in self._rates])
        self.rate_choice.SetSelection(
            self._rates.index(current) if current in self._rates
            else self._rates.index(1.0))
        self._on_rate()

    def set_rate(self, value: float) -> bool:
        """Play at *value* times normal speed. False if the backend refuses.

        Not every media backend supports rate changes, and one that silently
        ignores the request would leave the control lying about what it did --
        so the caller is told, and says so once rather than every time.
        """
        if value in self._rates:
            self.rate_choice.SetSelection(self._rates.index(value))
        try:
            return bool(self._media.SetPlaybackRate(float(value)))
        except Exception:  # noqa: BLE001 - a backend without rate control
            return False

    def _on_rate(self) -> None:
        """Apply the chosen speed, and say so if the backend would not.

        Refusal is per-speed, not all-or-nothing: a backend can be happy at 2x
        and refuse 3x. So the message names the speed that was refused, and is
        said once per speed rather than once ever -- otherwise picking a high
        speed early would silence the warning for every speed after it.
        """
        value = self.rate()
        if self.set_rate(value) or value in self._refused:
            return
        self._refused.add(value)
        LOG.info("This media backend will not play at %s; it keeps playing at "
                 "the speed it was.", rate_label(value))
        self._announce(f"This player cannot play at {rate_label(value)} on "
                       "this machine.")

    def playhead_ms(self) -> int:
        return int(self._media.Tell())

    def length_ms(self) -> int:
        return int(self._media.Length())

    def seek_to(self, ms: int) -> None:
        self._media.Seek(max(0, int(ms)))
        self._refresh_position()

    def stop_at(self, ms: int | None) -> None:
        """Stop playback once the playhead passes *ms*. None disarms it."""
        self._stop_at = ms

    def shutdown(self) -> None:
        """Release the file, so it can be rewritten while the editor is open."""
        self._timer.Stop()
        self._media.Stop()
        self._loaded = False

    # -- internals ------------------------------------------------------------

    def _refresh_position(self) -> None:
        self.position.SetLabel(format_time_precise(self.playhead_ms()))

    def _tick(self) -> None:
        self._refresh_position()
        if self._stop_at is not None and self.playhead_ms() >= self._stop_at:
            self._stop_at = None
            self.pause()
        if self._on_tick_cb is not None:
            self._on_tick_cb()
