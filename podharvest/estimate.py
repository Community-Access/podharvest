"""How long a run will take, and what it will cost.

Every model in the catalogue carries a real-time factor: 17.2 means an hour of
audio takes about three and a half minutes. Some of those figures were measured
by `podharvest benchmark` on real audio; the rest are informed estimates. The
difference is tracked and surfaced, because "about 3 hours (estimated)" and
"about 3 hours (measured on this machine)" deserve different amounts of trust.

Local models scale with the machine. The catalogue figures are for a mid-range
CPU, so running on a GPU applies a multiplier. Cloud models do not scale with
the machine at all - they scale with the network - so no multiplier is applied
to them.
"""

from __future__ import annotations

from dataclasses import dataclass

from podharvest.hardware import Hardware, ModelChoice
from podharvest.util import spoken_duration

#: Rough speed-up over a mid-range CPU for each compute backend. Deliberately
#: conservative: an estimate that comes in early is a pleasant surprise, one
#: that comes in late feels like a broken promise.
_ACCELERATOR_MULTIPLIER = {
    "cpu": 1.0,
    "metal": 2.5,
    "rocm": 4.0,
    "cuda": 6.0,
}


@dataclass
class Estimate:
    """A prediction for one model over some amount of audio."""

    seconds: float
    speed_x: float
    measured: bool
    cost_usd: float = 0.0
    is_cloud: bool = False

    @property
    def confidence(self) -> str:
        return "measured" if self.measured else "estimated"

    def sentence(self) -> str:
        """One plain-language line, ready to be read aloud."""
        if self.seconds <= 0:
            return "Time unknown for this model."
        how = ("measured on this machine" if self.measured and not self.is_cloud
               else "measured over the network" if self.measured
               else "estimated")
        text = f"About {spoken_duration(self.seconds)} ({how})."
        if self.is_cloud and self.cost_usd > 0:
            text += f" Roughly ${self.cost_usd:.2f} in provider charges."
        return text


def estimate_for(choice: ModelChoice, audio_seconds: float,
                 hw: Hardware | None = None) -> Estimate:
    """Predict how long `choice` will take over `audio_seconds` of audio."""
    speed = choice.speed_x or 0.0
    if speed <= 0:
        return Estimate(0.0, 0.0, False, is_cloud=choice.is_cloud)

    if not choice.is_cloud and hw is not None:
        speed *= _ACCELERATOR_MULTIPLIER.get(hw.accelerator, 1.0)

    # A figure measured on a CPU no longer describes the same model on a GPU.
    measured = choice.speed_measured and (
        choice.is_cloud or hw is None or hw.accelerator == "cpu")

    cost = (audio_seconds / 60.0) * choice.cost_per_audio_minute if choice.is_cloud else 0.0
    return Estimate(seconds=audio_seconds / speed, speed_x=speed, measured=measured,
                    cost_usd=cost, is_cloud=choice.is_cloud)


def describe_model(choice: ModelChoice, audio_seconds: float = 0.0,
                   hw: Hardware | None = None) -> str:
    """A full, readable description of one model.

    This is what fills the read-only description box beside the model list, so
    it is written to be listened to from top to bottom: what it is, where it
    runs, how fast, what it costs, what it can and cannot produce.
    """
    lines = [choice.label, ""]

    where = ("Runs in the cloud, on "
             f"{_provider_label(choice.provider)}'s servers." if choice.is_cloud
             else "Runs on this machine. Nothing is uploaded.")
    lines.append(where)

    if audio_seconds > 0:
        est = estimate_for(choice, audio_seconds, hw)
        lines.append(f"Time for this feed: {est.sentence()}")
    if choice.speed_x:
        pace = "measured" if choice.speed_measured else "estimated"
        lines.append(f"Speed: about {choice.speed_x:.0f} times faster than playing the "
                     f"audio ({pace}).")

    if choice.is_cloud:
        if choice.cost_per_audio_minute:
            per_hour = choice.cost_per_audio_minute * 60
            lines.append(f"Cost: about ${choice.cost_per_audio_minute:.3f} per minute of "
                         f"audio, so roughly ${per_hour:.2f} an hour.")
        lines.append("Your audio is uploaded to the provider. Your API key pays for it.")
    else:
        if choice.size_gb:
            lines.append(f"Download: about {choice.size_gb:.1f} GB the first time, then "
                         "it is kept on disk.")
        if choice.min_ram_gb:
            lines.append(f"Needs about {choice.min_ram_gb:.1f} GB of memory.")
        if choice.requires_cuda:
            lines.append("Requires an NVIDIA graphics card.")

    lines.append("Speaker names: " + (
        "yes, worked out as part of the transcript."
        if choice.speakers_built_in else
        "only if you turn on speaker identification, which runs separately."))
    lines.append("Timestamps, chapters and subtitles: " + (
        "supported." if choice.provides_timestamps else
        "not available - this model returns plain text with no times in it."))

    if choice.notes:
        lines.extend(["", choice.notes])
    if choice.license:
        lines.append(f"Licence: {choice.license}.")
    return "\n".join(lines)


def _provider_label(provider: str) -> str:
    from podharvest.cloud import PROVIDERS
    entry = PROVIDERS.get(provider)
    return entry.label if entry else (provider or "the provider")


def feed_audio_seconds(feed) -> float:
    """Total audio in a parsed feed, for the run-level estimate.

    Falls back to a typical podcast length for episodes whose feed does not
    declare a duration, which is common enough that ignoring them would make
    the estimate wildly optimistic.
    """
    _TYPICAL_EPISODE = 45 * 60
    total = 0.0
    for ep in getattr(feed, "episodes", []):
        total += float(getattr(ep, "duration_seconds", 0) or 0) or _TYPICAL_EPISODE
    return total
