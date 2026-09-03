"""What podHarvest quietly cannot do when FFmpeg is missing.

Taken from QUILL Cast (`quill/core/podcasts/media_health.py`), whose argument
applies here word for word.

A missing playback engine announces itself: the thing does not play. Every one
of podHarvest's FFmpeg features fails **by producing a plausible result**. The
episode downloads, and simply does not gain chapter markers. The transcript
comes out, and the duration in it is zero. A cloud transcription is skipped for
being oversized, when re-encoding it to Opus would have fitted it in one
request. A person cannot tell any of those from working correctly, so nobody
reports them, so they stay broken.

So podHarvest says it once, in one plain sentence, and stays silent on a
healthy install. The shape is Cast's: one boolean, everything else derived, so
a caller cannot build a report whose words disagree with its own state; a
`summary` that is **empty when healthy**, because a startup that reports "all
is well" every time trains people to talk over the one startup that had
something to say; and a `readout` that is never empty, because somebody who
asked a question is owed an answer even when the answer is good news.

The capability list is podHarvest's own -- it needs FFmpeg for different things
than Cast does -- and every line of it names something a person would notice
missing, not a function name.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What stops working, in the words of what a person would miss. Ordered by how
#: likely you are to hit it.
FFMPEG_CAPABILITIES: tuple[str, ...] = (
    "writing chapter markers into an episode that is not an MP3",
    "reading how long an episode is",
    "shrinking a long episode so a cloud transcriber will accept it",
    "splitting an oversized episode at its natural pauses",
)


@dataclass(frozen=True, slots=True)
class MediaHealth:
    """Whether FFmpeg is here, and what its absence costs."""

    ffmpeg: bool

    @property
    def healthy(self) -> bool:
        return self.ffmpeg

    @property
    def lost_capabilities(self) -> tuple[str, ...]:
        return () if self.ffmpeg else FFMPEG_CAPABILITIES

    def signature(self) -> str:
        """A stable key for "this exact state has already been mentioned".

        Remembered against this rather than a bare told-them-once flag, so a
        machine that is repaired and later breaks again is told again, and a
        machine in the same state is not told on every run forever.
        """
        return f"ffmpeg={int(self.ffmpeg)}"

    def summary(self) -> str:
        """What is missing and what it costs. Empty when healthy."""
        if self.healthy:
            return ""
        return (
            "FFmpeg is not installed. Podcasts still download and transcribe "
            "normally, but these do nothing until it is there: "
            + _join(FFMPEG_CAPABILITIES)
            + "."
        )

    def repair_hint(self) -> str:
        """What can be done about it, or "" when healthy.

        Names the two routes that actually work rather than sending anybody to
        a download page: podHarvest fetches its own tools, and a system install
        it can find on PATH is equally good.
        """
        if self.healthy:
            return ""
        return (
            "podHarvest can fetch it for you the first time it needs it, or "
            "install FFmpeg yourself and make sure it is on your PATH."
        )

    def notice(self) -> str:
        """The summary and the repair hint as one spoken paragraph."""
        if self.healthy:
            return ""
        return f"{self.summary()} {self.repair_hint()}"

    def readout(self) -> str:
        """The answer to *asking*, which unlike the notice is never empty.

        Somebody who opened a menu item asked a question and is owed an answer;
        silence there reads as a broken menu item rather than as good news.
        """
        if self.healthy:
            return (
                "FFmpeg is installed. Chapter markers, episode durations, and "
                "cloud-transcription shrinking are all available."
            )
        return self.notice()


def _join(items: tuple[str, ...]) -> str:
    """``a, b and c`` -- a list as it is read aloud, not as it is punctuated."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def check() -> MediaHealth:
    """Look for FFmpeg now. Cheap enough to call at startup."""
    from podharvest.hardware import find_ffmpeg

    try:
        return MediaHealth(ffmpeg=bool(find_ffmpeg()))
    except Exception:  # noqa: BLE001 - a probe that fails is a missing tool
        return MediaHealth(ffmpeg=False)
