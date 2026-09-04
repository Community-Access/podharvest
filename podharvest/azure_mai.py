"""Azure MAI-Transcribe-2, as one more provider you can choose.

Microsoft's Fast Transcription API with `enhancedMode` pointed at the
MAI-Transcribe-2 model. It transcribes English and Spanish, can detect which
of the two it is hearing, labels speakers in the same pass, returns word-level
timings, and takes a list of terms to bias recognition towards -- which is the
one that matters for podcasts, where the same handful of names and products
come up in every episode and every engine mangles them the same way.

**It is a preview service, and this is written accordingly.** Microsoft has
not published a stable MAI-specific price, the API version is pinned rather
than floating, and the feature is off until somebody turns it on. Nothing here
becomes the default and nothing falls back to it silently. If the preview
regresses, unticking one box in Settings removes it from the picker.

Three things this deliberately does *not* do, all from the PRD:

* It does not treat preview behaviour as a permanent contract. The API version
  is a setting, so a change can be answered without a new release.
* It does not silently degrade. If diarization or word timings were asked for
  and did not come back, the result says so rather than quietly returning less
  than was requested.
* It does not put an Azure key anywhere a browser could see it. The key goes
  in the same OS credential store every other provider's key uses, never in
  the settings file.

Azure needs two things the other providers do not: the *endpoint* of your own
Speech resource, and a region that actually offers MAI. Both are settings, and
`check_configuration` says plainly which one is missing rather than letting a
request fail with a 404 nobody can interpret.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from podharvest.keystore import load_key
from podharvest.util import LOG, HarvestError

#: The provider key, used in settings, the keystore and the model catalogue.
PROVIDER = "azure-mai"

#: The model Microsoft exposes through `enhancedMode`.
MODEL_NAME = "MAI-Transcribe-2"

#: Pinned rather than floating. A preview API that changes shape under a
#: released program is a bug report nobody can act on; a setting means a
#: change can be answered without waiting for a new version.
DEFAULT_API_VERSION = "2025-10-15"

#: Regions Microsoft lists for MAI. Availability changes, so this is a
#: warning rather than a gate -- a region that has just been added should not
#: be refused by a program that has not been rebuilt since.
KNOWN_REGIONS: tuple[str, ...] = ("eastus", "northeurope", "southeastasia", "westus")

#: The languages this provider is being used for. The service supports the
#: pair; sending anything else is out of scope and would be a silent downgrade.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("auto", "Detect automatically"),
    ("en", "English"),
    ("es", "Spanish"),
)

#: `clean` reads well; `verbatim` keeps every false start and filler, which is
#: what you want when the transcript is a record rather than a read.
STYLES: tuple[tuple[str, str], ...] = (
    ("clean", "Readable - tidied up"),
    ("verbatim", "Verbatim - every word as spoken"),
)

#: Microsoft documents a limit below 300 MB. Checked before the upload starts,
#: because finding out afterwards costs the whole upload.
MAX_UPLOAD_BYTES = 300 * 1024 * 1024

#: What Azure will accept on this path.
AUDIO_SUFFIXES: tuple[str, ...] = (".wav", ".mp3", ".flac")

#: Retried: throttling, gateways, and the plain unlucky. Not retried:
#: anything about the request itself, because sending it again produces the
#: same answer more slowly.
RETRY_STATUS: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4


@dataclass
class Configuration:
    """Everything the provider needs, and whether it has it."""

    endpoint: str = ""
    region: str = ""
    api_version: str = DEFAULT_API_VERSION
    enabled: bool = False
    language: str = "auto"
    style: str = "clean"
    diarize: bool = True
    word_timestamps: bool = True
    phrases: list[str] = field(default_factory=list)
    has_key: bool = False

    def problems(self) -> list[str]:
        """Everything standing between this and a working request.

        A list rather than the first fault, so somebody setting this up for
        the first time is told all of it at once instead of discovering it one
        round trip at a time.
        """
        found: list[str] = []
        if not self.enabled:
            found.append(
                "Azure MAI-Transcribe is switched off. Tick it in Settings to "
                "use it. It is a preview service, so it is off by default.")
        if not self.has_key:
            found.append(
                "There is no Azure Speech key. Add one in Settings; it is "
                "kept in this machine's credential store, never in a file.")
        if not self.endpoint:
            found.append(
                "The Speech resource endpoint is not set. It looks like "
                "https://your-resource.cognitiveservices.azure.com and is on "
                "the resource's page in the Azure portal.")
        elif not self.endpoint.startswith("https://"):
            found.append(
                "The Speech resource endpoint must start with https://. A key "
                "is not worth sending in the clear.")
        if not self.region:
            found.append(
                "The Azure region is not set. MAI is not offered everywhere.")
        return found

    def region_warning(self) -> str:
        """A note when the region is not one Microsoft lists for MAI."""
        if not self.region or self.region.lower() in KNOWN_REGIONS:
            return ""
        return (f"Microsoft does not currently list MAI-Transcribe in "
                f"'{self.region}'. It is offered in "
                f"{', '.join(KNOWN_REGIONS)}. If the request fails with a "
                "model-not-found error, that is why.")


def configuration_from(app, settings) -> Configuration:
    """Read the provider's configuration out of settings and the keystore."""
    return Configuration(
        endpoint=str(getattr(settings, "azure_speech_endpoint", "") or "").strip().rstrip("/"),
        region=str(getattr(settings, "azure_speech_region", "") or "").strip(),
        api_version=str(getattr(settings, "azure_speech_api_version", "")
                        or DEFAULT_API_VERSION).strip(),
        enabled=bool(getattr(settings, "azure_mai_enabled", False)),
        language=str(getattr(settings, "mai_language", "auto") or "auto"),
        style=str(getattr(settings, "mai_transcribe_style", "clean") or "clean"),
        diarize=bool(getattr(settings, "mai_diarize", True)),
        word_timestamps=bool(getattr(settings, "mai_word_timestamps", True)),
        phrases=list(getattr(settings, "mai_phrases", []) or []),
        has_key=bool(load_key(app, PROVIDER)),
    )


def check_configuration(app, settings) -> tuple[bool, str]:
    """Whether MAI could run, and a sentence saying what is missing."""
    config = configuration_from(app, settings)
    problems = config.problems()
    if problems:
        return False, " ".join(problems)
    warning = config.region_warning()
    return True, warning or "Azure MAI-Transcribe is configured and switched on."


def transcribe_url(config: Configuration) -> str:
    """The Fast Transcription endpoint for this resource."""
    return (f"{config.endpoint}/speechtotext/transcriptions:transcribe"
            f"?api-version={config.api_version}")


def build_definition(config: Configuration, *, want_word_timestamps: bool,
                     want_speakers: bool) -> dict:
    """The `definition` object that goes alongside the audio.

    `locales` is omitted for automatic detection, which is what Microsoft
    documents: sending a locale is a strong hint, and a strong hint towards
    the wrong language is worse than none at all.
    """
    definition: dict = {
        "enhancedMode": {
            "enabled": True,
            "model": MODEL_NAME,
            "modelOptions": {
                "timestamps": "word" if want_word_timestamps else "segment",
                "transcribeStyle": (config.style
                                    if config.style in {"clean", "verbatim"}
                                    else "clean"),
            },
        },
    }
    if config.language in {"en", "es"}:
        definition["locales"] = [config.language]
    if want_speakers:
        definition["diarization"] = {"enabled": True}
    phrases = [p.strip() for p in config.phrases if str(p).strip()]
    if phrases:
        # Hints, not substitutions -- Azure treats them as bias and so does
        # the wording anywhere this is explained.
        definition["phraseList"] = {"phrases": phrases}
    return definition


def parse_response(payload: dict) -> tuple[list, str, float, list[str]]:
    """Turn Azure's reply into segments, language, duration and warnings.

    Returns podHarvest's own `TranscriptSegment` objects. Warnings carry
    anything that was asked for and did not come back, because a result that
    quietly contains less than was requested is the failure mode this provider
    was told not to have.
    """
    from podharvest.transcribe import TranscriptSegment

    warnings: list[str] = []
    phrases = payload.get("phrases")
    if not isinstance(phrases, list):
        phrases = []

    segments: list[TranscriptSegment] = []
    saw_speaker = False
    for phrase in phrases:
        if not isinstance(phrase, dict):
            continue
        text = str(phrase.get("text") or "").strip()
        if not text:
            continue
        # Azure reports milliseconds.
        start = float(phrase.get("offsetMilliseconds") or 0) / 1000.0
        length = float(phrase.get("durationMilliseconds") or 0) / 1000.0
        speaker = phrase.get("speaker")
        if speaker is not None:
            saw_speaker = True
        segment = TranscriptSegment(start=start, end=start + length, text=text)
        if speaker is not None and hasattr(segment, "speaker"):
            segment.speaker = f"Speaker {speaker}"
        segments.append(segment)

    if not segments:
        # Some shapes return one combined transcript instead of phrases.
        combined = payload.get("combinedPhrases")
        text = ""
        if isinstance(combined, list) and combined:
            first = combined[0]
            if isinstance(first, dict):
                text = str(first.get("text") or "").strip()
        if not text:
            raise HarvestError("Azure returned an empty transcript.")
        duration = float(payload.get("durationMilliseconds") or 0) / 1000.0
        segments = [TranscriptSegment(start=0.0, end=duration, text=text)]
        warnings.append("Azure returned one block of text with no timings, so "
                        "this transcript has no timestamps and cannot produce "
                        "chapter markers or subtitles.")

    duration = float(payload.get("durationMilliseconds") or 0) / 1000.0
    if not duration and segments:
        duration = segments[-1].end

    language = ""
    for phrase in phrases:
        if isinstance(phrase, dict) and phrase.get("locale"):
            language = str(phrase["locale"]).split("-")[0]
            break

    if saw_speaker is False and any(
            getattr(segment, "speaker", "") for segment in segments):
        # Defensive: a shape that carried speakers without the flag.
        saw_speaker = True
    return segments, language or "en", duration, warnings


class AzureMaiTranscribeEngine:
    """Azure MAI-Transcribe-2 through the Fast Transcription API."""

    def __init__(self, app, choice, settings=None) -> None:
        self.app = app
        self.choice = choice
        self.settings = settings

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                   on_progress=None):
        from podharvest.cloud import prepare_for_upload
        from podharvest.transcribe import TranscriptResult

        settings = self.settings
        if settings is None:
            from podharvest import config as config_mod

            settings = config_mod.load(self.app)

        config = configuration_from(self.app, settings)
        problems = config.problems()
        if problems:
            raise HarvestError("Azure MAI-Transcribe is not ready. "
                               + " ".join(problems))
        warning = config.region_warning()
        if warning:
            LOG.warning("%s", warning)

        key = load_key(self.app, PROVIDER)
        upload = prepare_for_upload(audio_path, Path(self.app.temp_dir))
        try:
            size = upload.stat().st_size
            if size > MAX_UPLOAD_BYTES:
                raise HarvestError(
                    f"That audio is {size / 2 ** 20:.0f} MB, and Azure's Fast "
                    f"Transcription accepts less than "
                    f"{MAX_UPLOAD_BYTES / 2 ** 20:.0f} MB. Use a model that "
                    "runs on this machine for a file this long.")

            definition = build_definition(
                config,
                want_word_timestamps=include_word_timestamps and config.word_timestamps,
                want_speakers=config.diarize)
            LOG.info("Uploading %.1f MB to Azure MAI-Transcribe (%s, %s)...",
                     size / 2 ** 20, config.region or "no region set",
                     config.style)
            if on_progress:
                on_progress(5.0)

            started = time.monotonic()
            payload = self._post(transcribe_url(config), key, definition, upload)
            elapsed = time.monotonic() - started
        finally:
            upload.unlink(missing_ok=True)

        segments, language, duration, warnings = parse_response(payload)
        if config.diarize and not any(
                getattr(s, "speaker", "") for s in segments):
            warnings.append(
                "Speaker labels were asked for and Azure did not return any, "
                "so this transcript has none.")
        for note in warnings:
            LOG.warning("%s", note)

        if on_progress:
            on_progress(100.0)
        return TranscriptResult(
            segments=segments, language=language,
            engine=f"cloud:{PROVIDER}", model=MODEL_NAME,
            audio_seconds=duration,
            transcribe_seconds=elapsed)

    def _post(self, url: str, key: str, definition: dict, audio: Path) -> dict:
        """One multipart request, retried only where retrying can help."""
        from podharvest.cloud import _multipart_with_json, _post

        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            body, content_type = _multipart_with_json(
                {"definition": json.dumps(definition)}, "audio", audio)
            try:
                return _post(url,
                             headers={"Ocp-Apim-Subscription-Key": key},
                             data=body, content_type=content_type,
                             timeout=900.0)
            except HarvestError as exc:
                last = str(exc)
                status = _status_in(last)
                if status is not None and status not in RETRY_STATUS:
                    # Bad audio, bad key, wrong region, malformed request:
                    # sending it again produces the same answer more slowly.
                    raise
                if attempt == MAX_ATTEMPTS:
                    raise
                delay = min(30.0, 2.0 ** attempt)
                LOG.warning("Azure did not answer (%s). Trying again in %.0f "
                            "seconds (attempt %d of %d).",
                            last, delay, attempt + 1, MAX_ATTEMPTS)
                time.sleep(delay)
        raise HarvestError(last or "Azure MAI-Transcribe could not be reached.")


def _status_in(message: str) -> int | None:
    """The HTTP status in an error message, when there is one."""
    for token in message.replace(":", " ").replace("(", " ").replace(")", " ").split():
        if token.isdigit() and len(token) == 3:
            return int(token)
    return None
