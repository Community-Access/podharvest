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
    # -- not doing work twice ----------------------------------------------
    # Re-running podHarvest on the same feed should pick up where it left off,
    # not spend the afternoon regenerating what is already on disk. Turn these
    # off to force a fresh pass (a better ASR model, changed settings, a
    # transcript you did not like).
    reuse_transcripts: bool = True     # skip episodes already transcribed
    use_feed_transcripts: bool = True  # take the publisher's own transcript
                                        # when the feed offers one, rather than
                                        # transcribing words that already exist
    reuse_chapters: bool = True        # keep chapter markers already in the
                                        # file, or written in the show notes,
                                        # instead of asking a model for new ones
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

    # -- preview playback -------------------------------------------------
    # The Tag and Chapter Editor's transport. Remembered because judging a
    # boundary by ear means playing the same few seconds over and over, and
    # having to reset the volume every time you open an episode is the kind of
    # small tax that stops people using the feature at all.
    preview_volume: int = 70          # 0-100
    preview_muted: bool = False
    # Rewind and forward are separate on purpose. Going back is usually about
    # a sentence you missed; going forward is usually about skipping an advert
    # break, which is longer. Plenty of people want them different, and nobody
    # is served by one number pretending to suit both.
    skip_back_ms: int = 10_000        # 1000-300000
    skip_forward_ms: int = 10_000     # 1000-300000
    # Remember the playhead per file and offer it back next time. An hour-long
    # episode is not heard in one sitting.
    remember_playback_position: bool = True
    #: Move the reader's caret to keep pace with playback. Off by default
    #: and deliberately so: a caret that moves on its own takes the text out
    #: from under somebody reading at their own pace, and for a screen
    #: reader user that is not a nicety but a loss of control. Only ever
    #: turned on from Settings.
    follow_along: bool = False
    #: Spoken announcements, per kind of message, all off until asked for.
    #: An app that talks over you is a worse companion than a quiet one, so
    #: nothing here is on by default and each is chosen separately.
    announce_completions: bool = False
    announce_progress: bool = False
    announce_errors: bool = False
    #: Send the same messages to a braille display as well as speaking them.
    announce_braille: bool = False
    #: Offer, once per launch, to check favourites for new episodes. This is
    #: a question, not a schedule: nothing runs while podHarvest is closed,
    #: and nothing is downloaded by answering yes.
    ask_to_check_favourites: bool = True
    #: When the favourites were last checked, ISO 8601, so the question can
    #: stay quiet rather than being asked at every single launch.
    favourites_checked_at: str = ""
    # The speeds the player offers. Yours to change: people who listen at 3x
    # are not an edge case, and people who need 0.5x to follow a fast speaker
    # are the reason this is a list rather than a pair of buttons. 1.0 is
    # always kept, so there is always a way back to normal.
    # Local files: where a transcript for a file you already had goes, and
    # whether choosing a folder means everything under it.
    # Short tones as a run proceeds. Off by default: a sound nobody asked for
    # is an intrusion. On, it is the only thing that reports progress without
    # you reading the log, which cannot announce itself -- see cues.py.
    sound_cues: bool = False
    # The focusable status bar along the bottom. On by default: it is
    # the only place a run's state can be *read on demand*, since the
    # activity log cannot announce itself.
    show_status_bar: bool = True

    # -- Azure MAI-Transcribe (preview) ---------------------------------
    # Off until somebody turns it on, and it stays that way after an update.
    # It is a preview service: the price is not in Azure's published table and
    # the API can change, so it is never a default and never a silent
    # fallback. See podharvest/azure_mai.py and MAI-TRANSCRIBE-2-PRD.md.
    azure_mai_enabled: bool = False
    # Your own Speech resource. The key lives in the OS credential store with
    # every other provider's; only these two are safe to keep in a file.
    azure_speech_endpoint: str = ""
    azure_speech_region: str = ""
    # Pinned rather than floating, so a preview API changing shape can be
    # answered by editing a setting instead of waiting for a new version.
    azure_speech_api_version: str = "2025-10-15"
    # auto detects between the two languages the service supports; en or es
    # tells it, which is a strong hint and worth giving when you know.
    mai_language: str = "auto"
    # clean reads well; verbatim keeps the false starts, which is what a
    # record needs and a read does not.
    mai_transcribe_style: str = "clean"
    mai_diarize: bool = True
    mai_word_timestamps: bool = True
    # Names and terms to bias recognition towards. Worth setting for a show
    # with recurring guests, where every engine mangles the same few words.
    mai_phrases: list[str] = field(default_factory=list)
    # Which of Apple's stores the podcast search asks. They carry
    # different shows, so a local podcast may only appear in its own
    # country's store. Any two-letter code Apple recognises works, not
    # only the ones the search window lists.
    itunes_country: str = "us"
    search_limit: int = 25
    # Only take episodes whose titles match this. Empty means everything.
    # Applied before the episode limit, so "the 5 most recent about badgers"
    # means that rather than "any badgers among the 5 most recent".
    episode_match: str = ""
    local_transcripts_beside_file: bool = True
    local_recurse_folders: bool = True
    # Which source the main window is on. Remembered because somebody using
    # podHarvest as a tag editor should not have to switch back to Local files
    # on every launch. "find", "feed" or "local".
    source_mode: str = "feed"

    playback_rates: list[float] = field(
        default_factory=lambda: [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0])

    # The media-tools state already mentioned, so a missing FFmpeg is said
    # once rather than on every run -- and said again if it comes back and
    # goes missing a second time.
    media_health_last_notice: str = ""

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
        settings = cls(**clean)
        # A volume outside 0-100 would make the slider throw on the way up.
        # A hand-edited settings file is allowed to be wrong; the app is not
        # allowed to crash because of it.
        try:
            settings.preview_volume = max(0, min(100, int(settings.preview_volume)))
        except (TypeError, ValueError):
            settings.preview_volume = 70
        settings.preview_muted = bool(settings.preview_muted)
        for name, default in (("skip_back_ms", 10_000), ("skip_forward_ms", 10_000)):
            try:
                value = int(getattr(settings, name))
            except (TypeError, ValueError):
                value = default
            setattr(settings, name, max(1_000, min(300_000, value)))
        settings.remember_playback_position = bool(settings.remember_playback_position)
        settings.playback_rates = clean_rates(settings.playback_rates)
        # Kept in step with gui._SOURCE_MODES by the test in
        # tests/test_localfiles.py. A mode missing from this set is silently
        # rewritten to "feed" on load, so the window would open on the wrong
        # source with nothing to say why.
        if settings.source_mode not in {"find", "feed", "opml", "local"}:
            settings.source_mode = "feed"
        from podharvest.azure_mai import DEFAULT_API_VERSION, LANGUAGES, STYLES

        if settings.mai_language not in {code for code, _label in LANGUAGES}:
            settings.mai_language = "auto"
        if settings.mai_transcribe_style not in {code for code, _label in STYLES}:
            settings.mai_transcribe_style = "clean"
        if not str(settings.azure_speech_api_version or "").strip():
            settings.azure_speech_api_version = DEFAULT_API_VERSION
        settings.mai_phrases = [
            str(phrase).strip()
            for phrase in (settings.mai_phrases
                           if isinstance(settings.mai_phrases, list) else [])
            if str(phrase).strip()
        ]
        from podharvest.directory import (
            DEFAULT_LIMIT,
            MAX_LIMIT,
            clean_storefront,
        )

        settings.itunes_country = clean_storefront(settings.itunes_country)
        try:
            settings.search_limit = max(
                1, min(int(settings.search_limit), MAX_LIMIT))
        except (TypeError, ValueError):
            settings.search_limit = DEFAULT_LIMIT
        return settings


#: The slowest and fastest speeds worth offering. Below the floor speech
#: stops being speech; above the ceiling almost no media backend will comply,
#: and the ones that do are unintelligible.
MIN_RATE = 0.25
MAX_RATE = 5.0


def clean_rates(value: object) -> list[float]:
    """A usable list of playback speeds from whatever was in the settings file.

    Hand-edited settings are allowed to be wrong; the player is not allowed to
    break because of it. Values outside the sane range are dropped rather than
    clamped -- a clamped 50 silently becoming 5 is a worse surprise than it
    simply not appearing. 1.0 is always present, because a speed control with
    no way back to normal is a trap.
    """
    rates: list[float] = []
    for entry in (value if isinstance(value, (list, tuple)) else []):
        try:
            rate = round(float(entry), 2)
        except (TypeError, ValueError):
            continue
        if MIN_RATE <= rate <= MAX_RATE and rate not in rates:
            rates.append(rate)
    if 1.0 not in rates:
        rates.append(1.0)
    return sorted(rates)


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
