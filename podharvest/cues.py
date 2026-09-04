"""Short sounds that say what just happened, for when nothing can say it.

podHarvest's activity log cannot announce itself. That is not an oversight and
it is not fixable from here: wxWidgets exposes MSAA only, has no live-region
API on any platform, and appending to a text control that does not have focus
fires an event every screen reader deliberately ignores. It is written down in
the accessibility statement as the program's most important limitation.

The consequence is that a long run is silent. An hour of transcription
finishes, or fails on the third episode of forty, and nothing says so unless
you happen to be reading the log at that moment.

A sound is not speech, but it does not need to be. Three distinguishable cues
carry the three facts that matter while a run is going:

* **one short tone** -- an episode finished,
* **a rising pair** -- the whole run finished,
* **a low tone** -- something failed.

They are pitch-distinct rather than volume-distinct so they are told apart by
ear rather than by attention, and they are deliberately brief: this is a cue,
not an alarm. Off by default, because a sound nobody asked for is an intrusion
-- the setting is `sound_cues`.

The idea, and the ascending-tone-per-download that suggested it, come from a
small script by Michael Babcock that this program grew out of.
"""

from __future__ import annotations

import threading

from podharvest.util import LOG

#: (frequency in Hz, duration in ms) for each cue. Kept well inside the range
#: laptop speakers reproduce honestly: below about 300 Hz many render a click
#: rather than a tone, and above about 2 kHz they get shrill.
TONES: dict[str, tuple[tuple[int, int], ...]] = {
    # One episode is done. Short and unobtrusive: on a forty-episode run this
    # plays forty times, so anything longer would become an irritation.
    "episode": ((880, 90),),
    # The run is over. Rising, because "finished" should sound like an ending
    # you can walk back to rather than another episode going by.
    "finished": ((660, 110), (990, 160)),
    # Something failed. Low and single, so it is not mistaken for progress.
    "failed": ((330, 180),),
    # Cancelled at your request. Falling: the opposite shape to finished.
    "cancelled": ((760, 110), (500, 160)),
}


def _play_windows(tones: tuple[tuple[int, int], ...]) -> bool:
    """Play *tones* with winsound. False when that is not available."""
    try:
        import winsound
    except ImportError:
        return False
    try:
        for frequency, duration in tones:
            winsound.Beep(frequency, duration)
    except (RuntimeError, ValueError) as exc:  # pragma: no cover - no speaker
        LOG.debug("Could not play a sound cue: %s", exc)
        return False
    return True


def _play_bell(tones: tuple[tuple[int, int], ...]) -> bool:
    """The system bell, once per tone. Everything that is not Windows.

    wx has no tone generator, so pitch is lost and only the *number* of bells
    survives -- one for an episode, two for the end of a run. Less information,
    but the difference between "something happened" and silence is most of the
    value.
    """
    try:
        import wx
    except ImportError:
        return False
    try:
        for _tone in tones:
            wx.Bell()
    except Exception as exc:  # noqa: BLE001 - a bell that will not ring is not fatal
        LOG.debug("Could not ring the bell: %s", exc)
        return False
    return True


def play(name: str, *, enabled: bool = True) -> None:
    """Play the cue called *name*, on a background thread. Never raises.

    Threaded because `winsound.Beep` blocks for the duration of the tone, and
    these are called from the UI thread as a run reports progress. A quarter of
    a second of frozen window per finished episode would be a poor trade for a
    sound, and on a forty-episode run it would be ten seconds of it.

    Unknown names are ignored rather than raising: a cue is decoration, and
    nothing should fail because a sound did.
    """
    if not enabled:
        return
    tones = TONES.get(name)
    if not tones:
        LOG.debug("No sound cue called %r.", name)
        return

    def run() -> None:
        if not _play_windows(tones):
            _play_bell(tones)

    threading.Thread(target=run, name=f"cue-{name}", daemon=True).start()


def available() -> bool:
    """Whether any way of making a sound exists on this machine.

    Used to say so in Settings rather than offering a switch that does
    nothing.
    """
    try:
        import winsound  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        import wx  # noqa: F401

        return True
    except ImportError:
        return False
