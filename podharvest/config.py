"""Persistent, richly-customizable user settings.

Stored as JSON under `AppSpace.config_file` so both the CLI and the GUI read
and write the same preferences (last feed URL, output folder, download
filters, transcription engine/model, enrichment options, network tuning,
naming templates, and more). Unknown/missing keys fall back to sensible
defaults, so the file remains forward- and backward-compatible as new
settings are added.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from podharvest.appspace import AppSpace
from podharvest.util import LOG

#: Kinds of enclosures that can individually be included/excluded on download.
DOWNLOAD_KINDS = ("audio", "video", "image", "document", "other")


@dataclass
class Settings:
    # -- feed & output -------------------------------------------------
    last_feed_url: str = ""
    output_dir: str = ""                     # "" -> AppSpace.default_output_dir
    naming_template: str = "{date}-{slug}"   # per-episode file naming; see render.episode_slug
                                             # placeholders: {date} {slug} {index} {season}
                                             #               {number} {year} {month} {day}
    episode_limit: int | None = None      # None = fetch every episode
    follow_pagination: bool = True           # follow RFC 5005 <link rel="next"> across feed pages

    # -- downloading -----------------------------------------------------
    download_enclosures: bool = True
    download_kinds: list[str] = field(default_factory=lambda: list(DOWNLOAD_KINDS))
    concurrent_downloads: int = 3
    download_retries: int = 4
    download_rate_limit_kbps: int | None = None   # None = unlimited
    max_enclosure_mb: int | None = None           # None = unlimited
    user_agent: str = ""                              # "" -> net.DEFAULT_UA
    on_duplicate_file: str = "overwrite"   # overwrite | rename | skip - when a
                                            # download's destination filename
                                            # already exists but for a *different*
                                            # source URL (e.g. re-fetching the
                                            # same episode from two feed URLs)

    # -- transcription -----------------------------------------------------
    transcribe: bool = False
    asr_engine: str = ""            # "" -> hardware.recommend_model() at runtime
    asr_model: str = ""
    include_timestamps: bool = True
    identify_speakers: bool = False
    diarization_backend: str = "pyannote"   # pyannote | sherpa-onnx | nemo-msdd
    hf_token: str = ""              # Hugging Face token for the gated pyannote models.
                                     # Falls back to $PODHARVEST_HF_TOKEN / $HF_TOKEN.
    concurrent_transcriptions: int = 1   # >1 runs multiple files through one shared model at once
    transcript_timestamp_style: str = "bracket"    # bracket [00:00:00] | paren (00:00:00) | none
    transcript_speaker_style: str = "bold"          # bold **A:** | plain A: | inline (A) | none
    transcript_paragraph_mode: bool = False          # merge same-speaker segments into paragraphs
    transcript_max_line_chars: int | None = None  # wrap plain-text transcript at this width

    # -- optional enrichment (post-transcription LLM pass) ------------------
    enrichment_enabled: bool = False
    enrichment_model: str = ""
    enrichment_full_episode: bool = True   # summarise the whole transcript in chunks.
                                            # False sends only the first
                                            # `enrichment_max_chars` and says so in
                                            # the summary file.
    enrichment_max_chars: int = 24000       # how much transcript fits in one pass;
                                            # also the chunk size when summarising
                                            # the whole episode
    write_chapters: bool = False            # chapter markers with start/end times,
                                            # written above the summary
    chapters_into_audio: bool = True        # also write them into the audio file, so a
                                            # podcast player can jump between topics.
                                            # Lossless: the audio is copied, not re-encoded.
    enrichment_provider: str = ""           # "" -> the local model; otherwise a
                                            # cloud provider name

    # -- cloud providers ---------------------------------------------------
    # API keys are NOT stored here - see podharvest.keystore. These only record
    # what the user chose, never a secret.
    cloud_enabled: bool = False             # master switch for every cloud feature
    model_filter: str = "all"               # all | local | cloud - which models the
                                            # picker offers

    # -- output formats --------------------------------------------------
    write_markdown: bool = True
    write_html: bool = True
    write_text: bool = True
    write_json: bool = True
    write_csv: bool = False
    write_srt: bool = True           # subtitle track alongside each transcript
    write_vtt: bool = False          # WebVTT track alongside each transcript

    # -- app behavior --------------------------------------------------
    log_verbosity: int = 0           # default -v level when none is given on the CLI
    log_to_file: bool = True         # keep a rolling activity log on disk
    log_dir: str = ""                # "" -> AppSpace.logs_dir
    show_finished_dialog: bool = True   # announce the end of a run with a dialog

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


def load(app: AppSpace) -> Settings:
    path = app.config_file
    if not path.exists():
        return Settings()
    try:
        return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        LOG.warning("Could not read settings (%s); using defaults.", exc)
        return Settings()


def save(app: AppSpace, settings: Settings) -> None:
    app.config_dir.mkdir(parents=True, exist_ok=True)
    try:
        app.config_file.write_text(json.dumps(settings.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        LOG.warning("Could not save settings: %s", exc)


def resolved_output_dir(app: AppSpace, settings: Settings) -> str:
    return settings.output_dir or str(app.default_output_dir)


def resolved_log_dir(app: AppSpace, settings: Settings) -> str:
    return settings.log_dir or str(app.logs_dir)


def resolved_log_file(app: AppSpace, settings: Settings) -> Path | None:
    """Where the activity log is written, or None when logging to disk is off."""
    if not settings.log_to_file:
        return None
    return Path(resolved_log_dir(app, settings)) / "podharvest.log"


def apply_overrides(settings: Settings, **overrides: Any) -> Settings:
    """Return a copy of `settings` with only the provided, non-None fields changed."""
    data = settings.to_dict()
    for key, value in overrides.items():
        if value is not None and key in data:
            data[key] = value
    return Settings.from_dict(data)
