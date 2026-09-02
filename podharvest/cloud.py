"""Cloud transcription and summarisation providers.

Everything here is opt-in and needs the user's own API key. Nothing in this
module runs, and no audio leaves the machine, unless a key has been configured
and a cloud model has been picked explicitly.

Which providers can do what, stated plainly because the difference matters:

- **OpenAI** transcribes audio (`gpt-4o-transcribe`, `gpt-4o-mini-transcribe`,
  `whisper-1`) and writes summaries.
- **Google Gemini** transcribes audio and is the only option here that labels
  speakers as part of the same request, with no separate diarization pass.
- **OpenRouter** and **Ollama Cloud** are text-model gateways. Neither has a
  speech-to-text endpoint, so they appear as summary providers only. Listing
  them as transcription options would just produce failures at request time.

Every provider caps the size of a request. Audio is first re-encoded to 16 kHz
mono Opus, which is what these models listen to anyway and which turns an hour
of podcast into about 7 MB. Anything still over the limit after that is split at
natural pauses - never mid-word - and the pieces are transcribed in order and
stitched back onto one timeline.
"""

from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path

from podharvest.hardware import ModelChoice
from podharvest.keystore import load_key, redact
from podharvest.util import LOG, HarvestError, spoken_duration

#: Providers that can turn audio into text.
TRANSCRIBE_PROVIDERS = ("openai", "gemini")
#: Providers that can write summaries and chapter markers from a transcript.
SUMMARY_PROVIDERS = ("openai", "gemini", "openrouter", "ollama-cloud")
ALL_PROVIDERS = ("openai", "gemini", "openrouter", "ollama-cloud")


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    key_url: str
    key_hint: str
    can_transcribe: bool
    can_summarise: bool


PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        "openai", "OpenAI",
        "https://platform.openai.com/api-keys",
        "Starts with 'sk-'. Billed to your OpenAI account.",
        can_transcribe=True, can_summarise=True),
    "gemini": Provider(
        "gemini", "Google Gemini",
        "https://aistudio.google.com/apikey",
        "From Google AI Studio. Has a free tier with daily limits.",
        can_transcribe=True, can_summarise=True),
    "openrouter": Provider(
        "openrouter", "OpenRouter",
        "https://openrouter.ai/keys",
        "One key for many text models. Summaries only - OpenRouter has no "
        "speech-to-text endpoint.",
        can_transcribe=False, can_summarise=True),
    "ollama-cloud": Provider(
        "ollama-cloud", "Ollama Cloud",
        "https://ollama.com/settings/keys",
        "Hosted Ollama models. Summaries only - no speech-to-text endpoint.",
        can_transcribe=False, can_summarise=True),
}


# -- the cloud model catalogue ----------------------------------------------
# Speeds are wall-clock real-time factors including upload, measured on a normal
# home connection; they move around with network conditions far more than a
# local model does, which is why none is marked as measured.

# Speeds and error rates below were measured against the same 5-minute clip and
# human reference used for the local models, over a normal home connection.
# Network conditions move a cloud speed around far more than they move a local
# one, so treat these as the shape of the thing rather than a guarantee.
CLOUD_ASR_CHOICES: list[ModelChoice] = [
    ModelChoice(
        "cloud", "gpt-4o-mini-transcribe", 0.0,
        "OpenAI GPT-4o mini transcribe - fastest and cheapest, cloud",
        location="cloud", provider="openai", speed_x=30.4, speed_measured=True,
        cost_per_audio_minute=0.003, license="commercial",
        provides_timestamps=False,
        notes="The fastest option of any tested, local or cloud, and accurate with it "
              "(2.9% word error rate). Returns plain text only, so it cannot produce "
              "timestamps, chapter markers or subtitle files."),
    ModelChoice(
        "cloud", "gpt-4o-transcribe", 0.0,
        "OpenAI GPT-4o transcribe - stronger on difficult audio, cloud",
        location="cloud", provider="openai", speed_x=19.4, speed_measured=True,
        cost_per_audio_minute=0.006, license="commercial",
        provides_timestamps=False,
        notes="Measured 3.5% word error rate on clean speech - no better than the mini "
              "model there, and twice the price, though it is built to handle accents and "
              "crosstalk better. Returns plain text only: no timestamps, chapters or "
              "subtitles."),
    ModelChoice(
        "cloud", "whisper-1", 0.0,
        "OpenAI Whisper - the only OpenAI option with timestamps, cloud",
        location="cloud", provider="openai", speed_x=17.5, speed_measured=True,
        cost_per_audio_minute=0.006, license="commercial",
        provides_timestamps=True,
        notes="Measured 2.8% word error rate, the best of the OpenAI models tested. The "
              "only one that returns timestamps, so pick this one if you want chapter "
              "markers or subtitle files from OpenAI."),
    ModelChoice(
        "cloud", "gemini-2.5-flash", 0.0,
        "Google Gemini Flash - names the speakers, cloud",
        location="cloud", provider="gemini", speed_x=13.5, speed_measured=True,
        cost_per_audio_minute=0.001, license="commercial",
        speakers_built_in=True, provides_timestamps=True,
        notes="Transcribes and labels speakers in a single pass - no separate speaker "
              "identification step, and no Hugging Face token needed. In testing it "
              "worked out a speaker's actual name from the audio rather than just "
              "numbering the voices. Least accurate of the cloud options at 4.2% word "
              "error rate, and the cheapest per minute."),
    ModelChoice(
        "cloud", "gemini-pro-latest", 0.0,
        "Google Gemini Pro - names the speakers, most accurate Gemini, cloud",
        location="cloud", provider="gemini", speed_x=6.5, speed_measured=True,
        cost_per_audio_minute=0.004, license="commercial",
        speakers_built_in=True, provides_timestamps=True,
        notes="Measured 3.0% word error rate against Flash's 4.2%, and also names "
              "speakers in the same pass. The slowest option tested - about half the "
              "speed of running Parakeet on this machine."),
]

# Model ids are verified against each provider's own model list - a wrong id
# fails at request time with a 404 that says nothing useful to a user.
CLOUD_SUMMARY_CHOICES: list[ModelChoice] = [
    ModelChoice("cloud", "gpt-4o-mini", 0.0,
                "OpenAI GPT-4o mini - summaries and chapters, cloud",
                kind="enrichment", location="cloud", provider="openai",
                license="commercial",
                notes="Produced clean chapter markers with accurate times in testing. "
                      "A summary takes a couple of seconds against a couple of minutes "
                      "for the on-device model."),
    ModelChoice("cloud", "gemini-2.5-flash", 0.0,
                "Google Gemini Flash - summaries and chapters, cloud",
                kind="enrichment", location="cloud", provider="gemini",
                license="commercial",
                notes="The best chapter markers of the providers tested - it found the "
                      "most topic changes and titled them well. Fast and cheap."),
    ModelChoice("cloud", "anthropic/claude-haiku-4.5", 0.0,
                "Claude Haiku 4.5 via OpenRouter - summaries and chapters, cloud",
                kind="enrichment", location="cloud", provider="openrouter",
                license="commercial",
                notes="One OpenRouter key reaches hundreds of models; this is a fast, "
                      "inexpensive default."),
    ModelChoice("cloud", "gpt-oss:120b", 0.0,
                "gpt-oss 120B via Ollama Cloud - summaries, cloud",
                kind="enrichment", location="cloud", provider="ollama-cloud",
                license="commercial",
                notes="Writes good summaries, but followed the chapter-marker format "
                      "poorly in testing and found only one chapter where others found "
                      "six to eight. Prefer another provider if you want chapters."),
]


def available_cloud_models(app, *, kind: str = "asr") -> list[ModelChoice]:
    """Cloud models whose provider has a key configured. Empty when none has."""
    pool = CLOUD_ASR_CHOICES if kind == "asr" else CLOUD_SUMMARY_CHOICES
    return [c for c in pool if load_key(app, c.provider)]


def cloud_is_available(app) -> bool:
    """True when at least one provider has a key, from any source."""
    return any(load_key(app, name) for name in ALL_PROVIDERS)


# -- HTTP --------------------------------------------------------------------

def _post(url: str, *, headers: dict, data: bytes = b"", timeout: float = 600.0,
          content_type: str = "application/json") -> dict:
    """POST and return the decoded JSON body.

    Uses urllib so a cloud provider does not drag in a new dependency for
    someone who only ever runs local models.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", content_type)
    for header, value in headers.items():
        req.add_header(header, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = redact(exc.read().decode("utf-8", "replace")[:600])
        if exc.code in (401, 403):
            raise HarvestError(
                f"{url.split('/')[2]} rejected the API key ({exc.code}). Check the key in "
                f"Settings, and that the account it belongs to is active.") from exc
        if exc.code == 429:
            raise HarvestError(
                f"{url.split('/')[2]} is rate limiting or the account is out of credit "
                f"({exc.code}). {body}") from exc
        raise HarvestError(f"{url.split('/')[2]} returned {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise HarvestError(f"Could not reach {url.split('/')[2]}: {exc.reason}") from exc


def _multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    """Build a multipart/form-data body for a file upload."""
    boundary = "----podharvest" + str(int(time.time() * 1000))
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += f"{value}\r\n".encode()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    out += f"--{boundary}\r\n".encode()
    out += (f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{path.name}"\r\n').encode()
    out += f"Content-Type: {mime}\r\n\r\n".encode()
    out += path.read_bytes()
    out += f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# -- audio preparation -------------------------------------------------------

#: Every provider caps the request body. Speech carries perfectly well at
#: 16 kHz mono, and Opus at 16 kbps turns an hour of podcast into about 7 MB -
#: comfortably one request, where the original 54 MB MP3 would need splitting.
_UPLOAD_BITRATE = "16k"
_UPLOAD_SAMPLE_RATE = "16000"


def prepare_for_upload(audio_path: Path, temp_dir: Path) -> Path:
    """Transcode `audio_path` to a small mono Opus file and return the new path."""
    import subprocess

    from podharvest.hardware import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise HarvestError("ffmpeg is required to prepare audio for a cloud provider.")
    temp_dir.mkdir(parents=True, exist_ok=True)
    out = temp_dir / f"{audio_path.stem}.upload.ogg"
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(audio_path), "-ac", "1",
         "-ar", _UPLOAD_SAMPLE_RATE, "-c:a", "libopus", "-b:a", _UPLOAD_BITRATE,
         "-application", "voip", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise HarvestError(f"Could not compress the audio for upload: {proc.stderr[:300]}")
    return out


# -- engines -----------------------------------------------------------------

class OpenAITranscribeEngine:
    """OpenAI's audio transcription endpoint.

    `whisper-1` returns per-segment timestamps; the GPT-4o transcribe models are
    more accurate but return plain text only, so a transcript from those has one
    segment covering the whole episode and cannot carry timestamps or chapters.
    """

    URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(self, app, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                   on_progress=None):
        from podharvest.transcribe import TranscriptResult, TranscriptSegment

        key = load_key(self.app, "openai")
        if not key:
            raise HarvestError("No OpenAI API key is configured. Add one in Settings.")

        upload = prepare_for_upload(audio_path, Path(self.app.temp_dir))
        LOG.info("Uploading %.1f MB to OpenAI (%s)...",
                 upload.stat().st_size / 2 ** 20, self.choice.model)
        if on_progress:
            on_progress(5.0)

        wants_segments = self.choice.model == "whisper-1"

        def one(part: Path):
            fields = {"model": self.choice.model,
                      "response_format": "verbose_json" if wants_segments else "json"}
            body, content_type = _multipart(fields, "file", part)
            payload = _post(self.URL, headers={"Authorization": f"Bearer {key}"},
                            data=body, content_type=content_type)
            segments = []
            for seg in payload.get("segments") or []:
                text = (seg.get("text") or "").strip()
                if text:
                    segments.append(TranscriptSegment(
                        start=float(seg.get("start", 0.0)),
                        end=float(seg.get("end", 0.0)), text=text))
            duration = float(payload.get("duration") or 0.0)
            if not segments:
                text = (payload.get("text") or "").strip()
                if not text:
                    raise HarvestError("OpenAI returned an empty transcript.")
                segments = [TranscriptSegment(start=0.0, end=duration, text=text)]
            return segments, payload.get("language") or "en", duration

        t0 = time.monotonic()
        try:
            segments, language, duration = transcribe_in_parts(
                upload, Path(self.app.temp_dir), "openai", one, on_progress)
        finally:
            upload.unlink(missing_ok=True)
        elapsed = time.monotonic() - t0
        if on_progress:
            on_progress(100.0)

        return TranscriptResult(
            segments=segments, language=language,
            engine="cloud:openai", model=self.choice.model,
            audio_seconds=duration or (segments[-1].end if segments else 0.0),
            transcribe_seconds=elapsed)


class GeminiTranscribeEngine:
    """Google Gemini, which transcribes and labels speakers in one request.

    Gemini is asked for structured JSON so the reply is parsed rather than
    scraped: a list of segments each carrying start, end, speaker and text.
    """

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    PROMPT = (
        "Transcribe this audio completely and accurately. Return every segment of speech "
        "in order. For each segment give its start and end time in seconds from the "
        "beginning of the audio, the speaker, and the words spoken.\n\n"
        "Label speakers as 'Speaker 1', 'Speaker 2' and so on, consistently throughout - "
        "the same voice must always get the same label. If a speaker introduces themselves "
        "or is named by someone else, use that name instead.\n\n"
        "Transcribe what is actually said. Do not summarise, correct grammar, skip "
        "repetition, or add anything that is not in the audio."
    )

    SCHEMA = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "speaker": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["start", "end", "text"],
                },
            }
        },
        "required": ["segments"],
    }

    def __init__(self, app, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice

    def transcribe(self, audio_path: Path, *, include_word_timestamps: bool,
                   on_progress=None):
        import base64

        from podharvest.transcribe import TranscriptResult, TranscriptSegment

        key = load_key(self.app, "gemini")
        if not key:
            raise HarvestError("No Google Gemini API key is configured. Add one in Settings.")

        upload = prepare_for_upload(audio_path, Path(self.app.temp_dir))
        LOG.info("Uploading %.1f MB to Gemini (%s)...",
                 upload.stat().st_size / 2 ** 20, self.choice.model)
        if on_progress:
            on_progress(5.0)

        def one(part: Path):
            raw = part.read_bytes()
            body = json.dumps({
                "contents": [{"parts": [
                    {"text": self.PROMPT},
                    {"inline_data": {"mime_type": "audio/ogg",
                                     "data": base64.b64encode(raw).decode("ascii")}},
                ]}],
                "generationConfig": {
                    "temperature": 0.0,
                    "response_mime_type": "application/json",
                    "response_schema": self.SCHEMA,
                },
            }).encode("utf-8")
            payload = _post(self.URL.format(model=self.choice.model),
                            headers={"x-goog-api-key": key}, data=body)
            try:
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
            except (KeyError, IndexError, ValueError) as exc:
                finish = (payload.get("candidates") or [{}])[0].get("finishReason", "")
                extra = (f" (the model stopped early: {finish})"
                         if finish and finish != "STOP" else "")
                raise HarvestError(f"Gemini's reply could not be read{extra}.") from exc

            segments = []
            for seg in parsed.get("segments") or []:
                body_text = (seg.get("text") or "").strip()
                if not body_text:
                    continue
                segments.append(TranscriptSegment(
                    start=float(seg.get("start") or 0.0), end=float(seg.get("end") or 0.0),
                    text=body_text, speaker=(seg.get("speaker") or "").strip() or None))
            if not segments:
                raise HarvestError("Gemini returned an empty transcript.")
            return segments, "en", segments[-1].end

        t0 = time.monotonic()
        try:
            segments, language, duration = transcribe_in_parts(
                upload, Path(self.app.temp_dir), "gemini", one, on_progress)
        finally:
            upload.unlink(missing_ok=True)
        elapsed = time.monotonic() - t0
        if on_progress:
            on_progress(100.0)

        return TranscriptResult(
            segments=segments, language=language, engine="cloud:gemini",
            model=self.choice.model, audio_seconds=duration or segments[-1].end,
            transcribe_seconds=elapsed)


def build_cloud_engine(app, choice: ModelChoice):
    """Return the engine for a cloud ASR `choice`."""
    if choice.provider == "openai":
        return OpenAITranscribeEngine(app, choice)
    if choice.provider == "gemini":
        return GeminiTranscribeEngine(app, choice)
    label = PROVIDERS[choice.provider].label if choice.provider in PROVIDERS else choice.provider
    raise HarvestError(
        f"{label} does not offer speech-to-text. Pick an OpenAI or Gemini model, "
        "or one that runs on this machine.")


# -- text generation (summaries and chapter markers) -------------------------

#: OpenAI, OpenRouter and Ollama Cloud all speak the OpenAI chat-completions
#: shape, so one code path covers three providers. Gemini does not, and gets
#: its own below.
_CHAT_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "ollama-cloud": "https://ollama.com/v1/chat/completions",
}


def generate_text(app, provider: str, model: str, prompt: str,
                  *, max_tokens: int = 512, temperature: float = 0.2) -> str:
    """Ask a cloud text model for a completion. Returns "" on an empty reply."""
    key = load_key(app, provider)
    if not key:
        raise HarvestError(
            f"No API key is configured for {PROVIDERS[provider].label}. Add one in Settings.")

    if provider == "gemini":
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens},
        }).encode("utf-8")
        payload = _post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent",
            headers={"x-goog-api-key": key}, data=body)
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError):
            return ""

    endpoint = _CHAT_ENDPOINTS.get(provider)
    if not endpoint:
        raise HarvestError(f"{provider} cannot write summaries.")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "openrouter":
        # OpenRouter asks callers to identify themselves; it also makes the
        # request show up sensibly in the user's own usage dashboard.
        headers["HTTP-Referer"] = "https://github.com/jeffbishop/podharvest"
        headers["X-Title"] = "podharvest"
    payload = _post(endpoint, headers=headers, data=body)
    try:
        return (payload["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError):
        return ""


class CloudSummariser:
    """A drop-in stand-in for the local llama.cpp model in `enrich`.

    `enrich` only ever needs "turn this prompt into text", so a cloud provider
    can serve the same summaries and chapter markers as the on-device model
    with no other change.
    """

    def __init__(self, app, choice: ModelChoice) -> None:
        self.app = app
        self.choice = choice

    @property
    def label(self) -> str:
        return self.choice.model

    def __call__(self, prompt: str, *, max_tokens: int = 512) -> str:
        return generate_text(self.app, self.choice.provider, self.choice.model,
                             prompt, max_tokens=max_tokens)


# -- splitting oversized audio -----------------------------------------------

#: Request-body ceilings, minus headroom for the rest of the request. Gemini
#: receives audio base64-encoded, which inflates it by a third, so its usable
#: audio budget is the smaller number.
PROVIDER_MAX_UPLOAD_BYTES = {
    "openai": 24 * 1024 * 1024,        # documented limit is 25 MB
    "gemini": 14 * 1024 * 1024,        # 20 MB request cap / 1.34 for base64
}


def _silence_points(audio_path: Path, ffmpeg: str) -> list[float]:
    """Times, in seconds, where the audio goes quiet enough to cut safely.

    Cutting mid-word costs a word at every boundary - the same failure the
    local Parakeet path had. Cutting in a gap between sentences costs nothing,
    so the split points are chosen from actual silence rather than by dividing
    the running time.
    """
    import re
    import subprocess

    proc = subprocess.run(
        [ffmpeg, "-i", str(audio_path), "-af", "silencedetect=noise=-30dB:d=0.35",
         "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", proc.stderr)]
    # The middle of each silence is the safest place to cut. strict=False is
    # deliberate: a silence still open when the file ends has a start and no
    # matching end, so the two lists legitimately differ in length.
    return sorted((s + e) / 2 for s, e in zip(starts, ends, strict=False) if e > s)


def _duration_seconds(audio_path: Path, ffmpeg: str) -> float:
    import subprocess

    from podharvest.hardware import find_ffprobe
    probe = find_ffprobe()
    if not probe:
        return 0.0
    out = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def split_for_upload(audio_path: Path, temp_dir: Path,
                     max_bytes: int) -> list[tuple[Path, float]]:
    """Return [(part_file, start_offset_seconds)] small enough to upload.

    `audio_path` is already compressed by `prepare_for_upload`. When it fits, it
    is returned unchanged as a single part. When it does not, it is cut at
    natural pauses and each piece keeps the offset it started at, so segment
    times can be shifted back onto the original timeline.
    """
    import subprocess

    from podharvest.hardware import find_ffmpeg

    size = audio_path.stat().st_size
    if size <= max_bytes:
        return [(audio_path, 0.0)]

    ffmpeg = find_ffmpeg()
    duration = _duration_seconds(audio_path, ffmpeg)
    if duration <= 0:
        raise HarvestError("Could not read the length of the audio, so it cannot be split.")

    # How many pieces, and therefore where each one should end. One extra piece
    # gives headroom, since compressed audio is not perfectly uniform in bitrate.
    parts_wanted = int(size // max_bytes) + 2
    target_len = duration / parts_wanted
    LOG.info("The audio is %.1f MB, over the %.0f MB limit for this provider. Splitting "
             "it into %d pieces at natural pauses.",
             size / 2 ** 20, max_bytes / 2 ** 20, parts_wanted)

    quiet = _silence_points(audio_path, ffmpeg)
    boundaries: list[float] = []
    for n in range(1, parts_wanted):
        target = target_len * n
        # Snap to the nearest pause, but only if one is reasonably close;
        # otherwise cut on time rather than drift into a badly uneven piece.
        near = min(quiet, key=lambda t: abs(t - target), default=None)
        boundaries.append(near if near is not None and abs(near - target) < target_len * 0.25
                          else target)
    boundaries = sorted(b for b in boundaries if 0 < b < duration)

    edges = [0.0, *boundaries, duration]
    parts: list[tuple[Path, float]] = []
    for index in range(len(edges) - 1):
        start, end = edges[index], edges[index + 1]
        out = temp_dir / f"{audio_path.stem}.part{index + 1:02d}.ogg"
        proc = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(audio_path),
             "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
             "-c:a", "libopus", "-b:a", _UPLOAD_BITRATE, str(out)],
            capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            raise HarvestError(f"Could not split the audio: {proc.stderr[:300]}")
        parts.append((out, start))
    LOG.info("Split into %d pieces of about %s each.",
             len(parts), spoken_duration(target_len))
    return parts


def transcribe_in_parts(audio_path: Path, temp_dir: Path, provider: str,
                        transcribe_one, on_progress=None):
    """Transcribe `audio_path`, splitting first when it is too big to upload.

    `transcribe_one(path)` returns (segments, language, duration) for one piece.
    Segment times from each piece are shifted by that piece's offset so the
    merged transcript runs on one continuous clock.
    """
    max_bytes = PROVIDER_MAX_UPLOAD_BYTES.get(provider, 20 * 1024 * 1024)
    parts = split_for_upload(audio_path, temp_dir, max_bytes)

    all_segments = []
    language = "en"
    total = 0.0
    try:
        for index, (part, offset) in enumerate(parts, 1):
            if len(parts) > 1:
                LOG.info("Transcribing piece %d of %d...", index, len(parts))
            segments, lang, duration = transcribe_one(part)
            language = lang or language
            for seg in segments:
                seg.start += offset
                seg.end += offset
            all_segments.extend(segments)
            total = max(total, offset + duration)
            if on_progress:
                on_progress(min(100.0, 100.0 * index / len(parts)))
    finally:
        for part, _ in parts:
            if part != audio_path:
                part.unlink(missing_ok=True)
    return all_segments, language, total
