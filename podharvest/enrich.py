"""Optional transcript enrichment: a local LLM pass over a finished
transcript for punctuation/casing cleanup, a summary, and chapter title
suggestions. Runs entirely on-device via `llama-cpp-python` against one of
the GGUF models in `hardware.ENRICHMENT_CHOICES` (Phi-3.5, Llama 3.2,
Nemotron-Mini, Mistral). Optional and additive - if it isn't installed or
fails, the underlying transcript is left untouched and a clear log message
explains why.

A model with an 8k context cannot read an hour-long transcript in one go, so
long episodes are summarised map-reduce style: each section is summarised on
its own, then the section notes are folded into one summary of the whole
episode. `Settings.enrichment_full_episode` turns that off in favour of a
single truncated pass, which is faster but only covers the opening stretch.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from podharvest.acquire import acquire_enrichment_model, ensure_package
from podharvest.appspace import AppSpace
from podharvest.hardware import ModelChoice
from podharvest.util import LOG, HarvestError

_SUMMARY_PROMPT = """You are an assistant that writes concise, accurate summaries of podcast transcripts for archival purposes. Given the transcript below, produce:

1. A one-paragraph summary (3-5 sentences).
2. Three to six suggested chapter titles with approximate topics covered, as a bullet list.

Do not invent facts that are not in the transcript. Keep it factual and neutral.

Transcript:
---
{transcript}
---

Summary and chapter suggestions:"""

#: Used on one slice of a long episode. The slice is explicitly framed as a
#: part rather than a whole, so the model does not describe fifteen minutes of
#: audio as though it were the entire episode.
_PART_PROMPT = """You are summarising ONE SECTION (part {n} of {total}) of a longer podcast transcript. Cover only what this section actually contains.

Write 3-5 sentences describing what happens in this section, then list the distinct topics it covers as short bullet points.

Do not invent facts. Do not speculate about what other sections contain.

Section {n} of {total}:
---
{transcript}
---

Section summary:"""

#: Chapter markers. The transcript arrives with its timestamps intact and the
#: model is asked to copy the time it sees rather than invent one - anything
#: outside the episode's length is discarded when the reply is parsed.
_CHAPTER_PROMPT = """Below is part of a podcast transcript. Every line begins with the time it was said, in [hh:mm:ss] form.

Find the points where the subject genuinely changes. For each one, write a line containing the timestamp copied exactly from the line where that subject starts, then a short descriptive title.

Rules:
- Use this format, one per line: hh:mm:ss - Title Here
- Copy timestamps from the transcript. Never invent a time.
- Aim for a chapter every few minutes. Do not mark every small remark.
- Titles should say what is discussed, in under ten words.
- Output only the list. No preamble, no commentary.

Transcript:
---
{transcript}
---

Chapters:"""

#: The reduce step: fold the per-section notes into one summary of the whole.
_COMBINE_PROMPT = """Below are notes taken from consecutive sections of a single podcast episode, in order. Using only these notes, write a summary of the episode as a whole:

1. A one-paragraph summary of the entire episode (4-6 sentences).
2. Five to ten chapter titles covering the episode from beginning to end, as a bullet list, in the order the topics appear.

Do not invent facts that are not in the notes. Keep it factual and neutral.

Section notes:
---
{notes}
---

Summary of the whole episode:"""


# Loading a multi-gigabyte GGUF off disk takes tens of seconds, so the model is
# loaded once per process and reused for every episode. The lock guards both
# the load and each generation, because transcription can run on a pool of
# worker threads and a single llama.cpp context is not thread-safe.
_LLM_LOCK = threading.Lock()
_LLM_CACHE: dict[str, object] = {}


def _load_llm(app: AppSpace, choice: ModelChoice):
    # A cloud summary model needs no download, no install and no lock - just a
    # thin object that turns a prompt into text.
    if getattr(choice, "is_cloud", False):
        from podharvest.cloud import CloudSummariser
        return CloudSummariser(app, choice)

    if not ensure_package(app, "llama-cpp-python", "llama_cpp"):
        raise HarvestError(
            "llama-cpp-python could not be installed (it requires a C++ build toolchain on some "
            "platforms). Transcript summaries are unavailable without it.")
    from llama_cpp import Llama  # type: ignore

    result = acquire_enrichment_model(app, choice)
    model_path = result.model_dir / choice.filename
    if not model_path.exists():
        raise HarvestError(f"The summary model file is missing after download: {model_path}")

    key = str(model_path)
    cached = _LLM_CACHE.get(key)
    if cached is not None:
        return cached

    LOG.info("Loading the summary model '%s'. This only happens once.", choice.model)
    llm = Llama(model_path=key, n_ctx=8192, n_threads=None, verbose=False)
    _LLM_CACHE[key] = llm
    return llm


def _generate(llm, prompt: str, *, max_tokens: int = 512) -> str:
    """Run one prompt through whichever model is in use.

    `llm` is either a llama.cpp handle or a `cloud.CloudSummariser`. The cloud
    one talks to a remote service, so it is deliberately not held under the
    local lock - that lock exists because a single llama.cpp context is not
    thread-safe, which has nothing to do with an HTTP call.
    """
    from podharvest.cloud import CloudSummariser
    if isinstance(llm, CloudSummariser):
        return llm(prompt, max_tokens=max_tokens)
    with _LLM_LOCK:
        output = llm(prompt, max_tokens=max_tokens, temperature=0.2, stop=["---"])
    text = output.get("choices", [{}])[0].get("text", "") if isinstance(output, dict) else ""
    return text.strip()


def split_transcript(text: str, chunk_chars: int) -> list[str]:
    """Split `text` into chunks of at most `chunk_chars`, breaking on blank
    lines where possible so a section rarely starts mid-sentence."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) + 2 > chunk_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
        # A single paragraph longer than the budget (unwrapped transcripts do
        # this) still has to be cut somewhere, so cut it on the character.
        while len(current) > chunk_chars:
            chunks.append(current[:chunk_chars])
            current = current[chunk_chars:]
    if current:
        chunks.append(current)
    return chunks


def timestamped_text(segments) -> str:
    """Render segments as "[hh:mm:ss] words", one per line.

    Chapter markers need to point at a time in the recording, so the model has
    to see where in the episode each piece of speech happened. Without this it
    can only guess at a running order.
    """
    lines = []
    for seg in segments:
        total = int(max(0.0, getattr(seg, "start", 0.0)))
        stamp = f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
        text = (getattr(seg, "text", "") or "").strip()
        if text:
            lines.append(f"[{stamp}] {text}")
    return "\n".join(lines)


def _parse_chapters(raw: str, max_seconds: float) -> list[tuple[int, str]]:
    """Pull "hh:mm:ss Title" lines out of a model reply.

    Models are inconsistent about how they format a list, so this accepts
    bullets, numbering, dashes and both mm:ss and hh:mm:ss, and throws away
    anything whose timestamp lands outside the episode - a made-up time is
    worse than a missing chapter.
    """
    import re
    found: list[tuple[int, str]] = []
    pattern = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*[-–—:.)\]]*\s*(.+)")
    for line in raw.splitlines():
        line = line.strip()
        # Strip bullets and list numbering, but never bare digits - the leading
        # digits of "00:03:02" are part of the timestamp, not decoration.
        line = re.sub(r"^[\s*\-–—#>•]+", "", line)
        line = re.sub(r"^\d{1,2}[.)]\s+", "", line)
        line = line.lstrip("[( \t")
        match = pattern.match(line)
        if not match:
            continue
        hours, minutes, seconds, title = match.groups()
        at = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
        title = title.strip().strip("*_[]()").strip()
        if title and 0 <= at <= max_seconds + 1:
            found.append((at, title))
    found.sort(key=lambda item: item[0])

    # Drop repeats and near-duplicates in time; a chapter every few seconds is
    # not a chapter list.
    deduped: list[tuple[int, str]] = []
    for at, title in found:
        if deduped and (at - deduped[-1][0] < 20 or title.lower() == deduped[-1][1].lower()):
            continue
        deduped.append((at, title))
    return deduped


def format_chapters(chapters: list[tuple[int, str]], total_seconds: float) -> str:
    """Render chapters as a Markdown list with a start and end time each."""
    if not chapters:
        return ""
    lines = ["## Chapters", ""]
    for index, (at, title) in enumerate(chapters):
        end = chapters[index + 1][0] if index + 1 < len(chapters) else int(total_seconds)
        lines.append(f"- **{_clock(at)} - {_clock(end)}**  {title}")
    return "\n".join(lines)


def _clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def enrich_transcript(app: AppSpace, choice: ModelChoice, transcript_text: str,
                      *, max_input_chars: int = 24000, full_episode: bool = True,
                      on_step: Callable[[int, int], None] | None = None) -> str | None:
    """Return a Markdown summary + chapter suggestions for `transcript_text`,
    or None if it could not run (never raises for a missing or optional
    dependency - callers should treat None as "skip the summary, keep going").

    With `full_episode`, the transcript is summarised in sections and the
    section notes are combined, so the result covers the whole episode.
    Otherwise only the first `max_input_chars` are summarised and the result
    says so.
    """
    try:
        with _LLM_LOCK:
            llm = _load_llm(app, choice)
    except HarvestError as exc:
        LOG.warning("Skipping the summary: %s", exc)
        return None

    text = transcript_text.strip()
    if not text:
        return None

    try:
        if not full_episode:
            covered = 100.0
            if len(text) > max_input_chars:
                covered = max_input_chars / len(text) * 100
                text = text[:max_input_chars]
            if on_step:
                on_step(1, 1)
            summary = _generate(llm, _SUMMARY_PROMPT.format(transcript=text))
            if summary and covered < 99.5:
                summary = (f"*Based on the first {covered:.0f}% of this episode. Turn on "
                           f"\"summarise the whole episode\" in settings to cover all of it.*\n\n"
                           f"{summary}")
            return summary or None

        chunks = split_transcript(text, max_input_chars)
        if len(chunks) == 1:
            if on_step:
                on_step(1, 1)
            return _generate(llm, _SUMMARY_PROMPT.format(transcript=chunks[0])) or None

        # Map: one pass per section. Total steps include the combine pass, so a
        # caller's progress reporting lines up with the work actually left.
        total_steps = len(chunks) + 1
        notes: list[str] = []
        for n, chunk in enumerate(chunks, 1):
            if on_step:
                on_step(n, total_steps)
            note = _generate(llm, _PART_PROMPT.format(n=n, total=len(chunks), transcript=chunk),
                             max_tokens=320)
            if note:
                notes.append(f"Section {n} of {len(chunks)}:\n{note}")
        if not notes:
            return None

        # Reduce. If the notes themselves overflow the context, fold them down
        # a level at a time until they fit rather than silently dropping the end.
        if on_step:
            on_step(total_steps, total_steps)
        joined = "\n\n".join(notes)
        while len(joined) > max_input_chars and len(notes) > 1:
            folded = [_generate(llm, _COMBINE_PROMPT.format(notes=group), max_tokens=320)
                      for group in split_transcript(joined, max_input_chars)]
            notes = [f for f in folded if f]
            if not notes:
                return None
            joined = "\n\n".join(notes)
        return _generate(llm, _COMBINE_PROMPT.format(notes=joined), max_tokens=768) or None
    except Exception as exc:  # noqa: BLE001 - a bad generation shouldn't break the harvest
        LOG.error("Could not write the summary: %s", exc)
        return None


def make_chapters(app: AppSpace, choice: ModelChoice, segments, total_seconds: float,
                  *, max_input_chars: int = 24000,
                  on_step: Callable[[int, int], None] | None = None
                  ) -> list[tuple[int, str]]:
    """Work out chapter markers with real start times from timestamped segments.

    Each section of the episode is read with its timestamps intact and asked for
    the points where the subject changes. Returns [(seconds, title)], empty when
    chapters could not be produced - a missing chapter list is never fatal.
    """
    stamped = timestamped_text(segments)
    if not stamped:
        return []
    try:
        with _LLM_LOCK:
            llm = _load_llm(app, choice)
    except HarvestError as exc:
        LOG.warning("Skipping chapter markers: %s", exc)
        return []

    chunks = split_transcript(stamped, max_input_chars)
    chapters: list[tuple[int, str]] = []
    try:
        for n, chunk in enumerate(chunks, 1):
            if on_step:
                on_step(n, len(chunks))
            reply = _generate(llm, _CHAPTER_PROMPT.format(transcript=chunk), max_tokens=400)
            chapters.extend(_parse_chapters(reply, total_seconds))
    except Exception as exc:  # noqa: BLE001 - chapters are a bonus, not the transcript
        LOG.error("Could not work out chapter markers: %s", exc)
        return []

    chapters.sort(key=lambda item: item[0])
    deduped: list[tuple[int, str]] = []
    for at, title in chapters:
        if deduped and at - deduped[-1][0] < 20:
            continue
        deduped.append((at, title))
    return deduped


def write_enrichment(app: AppSpace, choice: ModelChoice, transcript_path: Path,
                     transcript_text: str, *, full_episode: bool = True,
                     max_input_chars: int = 24000, segments=None,
                     write_chapters: bool = False, total_seconds: float = 0.0,
                     on_step: Callable[[int, int], None] | None = None) -> Path | None:
    """Summarise `transcript_text` and write it beside `transcript_path` as
    `<name>.summary.md`. Returns the written path, or None if it was skipped.

    With `write_chapters` and timestamped `segments`, a chapter list with start
    and end times is written above the summary.
    """
    summary = enrich_transcript(app, choice, transcript_text, max_input_chars=max_input_chars,
                                full_episode=full_episode, on_step=on_step)

    chapter_block = ""
    if write_chapters and segments:
        chapters = make_chapters(app, choice, segments, total_seconds or 0.0,
                                 max_input_chars=max_input_chars)
        chapter_block = format_chapters(chapters, total_seconds or 0.0)
        if chapters:
            LOG.info("Found %d chapter(s).", len(chapters))
        else:
            LOG.info("No chapter markers could be worked out for this episode.")

    if not summary and not chapter_block:
        return None

    body = f"# Summary ({choice.model})\n\n"
    if chapter_block:
        body += chapter_block + "\n\n"
    if summary:
        body += summary + "\n"
    out_path = transcript_path.with_suffix("").with_suffix(".summary.md")
    out_path.write_text(body, encoding="utf-8", newline="\n")
    LOG.debug("Wrote summary: %s", out_path)
    return out_path
