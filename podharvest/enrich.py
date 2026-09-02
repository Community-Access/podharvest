"""Optional transcript enrichment: a local LLM pass over a finished
transcript for punctuation/casing cleanup, a summary, and chapter title
suggestions. Runs entirely on-device via `llama-cpp-python` against one of
the GGUF models in `hardware.ENRICHMENT_CHOICES` (Phi-3.5, Llama 3.2,
Nemotron-Mini, Mistral). Optional and additive - if it isn't installed or
fails, the underlying transcript is left untouched and a clear log message
explains why.
"""

from __future__ import annotations

from pathlib import Path

from podharvest.acquire import acquire_enrichment_model, ensure_package
from podharvest.appspace import AppSpace
from podharvest.hardware import ModelChoice
from podharvest.util import LOG, HarvestError

_SUMMARY_PROMPT = """You are an assistant that writes concise, accurate summaries of podcast \
transcripts for archival purposes. Given the transcript below, produce:

1. A one-paragraph summary (3-5 sentences).
2. Three to six suggested chapter titles with approximate topics covered, as a bullet list.

Do not invent facts that are not in the transcript. Keep it factual and neutral.

Transcript:
---
{transcript}
---

Summary and chapter suggestions:"""


def _load_llm(app: AppSpace, choice: ModelChoice):
    if not ensure_package(app, "llama-cpp-python", "llama_cpp"):
        raise HarvestError(
            "llama-cpp-python could not be installed (it requires a C++ build toolchain on some "
            "platforms). Transcript enrichment is unavailable without it.")
    from llama_cpp import Llama  # type: ignore

    result = acquire_enrichment_model(app, choice)
    model_path = result.model_dir / choice.filename
    if not model_path.exists():
        raise HarvestError(f"Enrichment model file not found after acquisition: {model_path}")

    LOG.info("Loading enrichment model '%s'...", choice.model)
    return Llama(model_path=str(model_path), n_ctx=8192, n_threads=None, verbose=False)


def enrich_transcript(app: AppSpace, choice: ModelChoice, transcript_text: str,
                      *, max_input_chars: int = 24000) -> str | None:
    """Return a Markdown summary + chapter suggestions for `transcript_text`,
    or None if enrichment could not run (never raises for a missing/optional
    dependency - callers should treat None as "skip enrichment, keep going").
    """
    try:
        llm = _load_llm(app, choice)
    except HarvestError as exc:
        LOG.warning("Skipping transcript enrichment: %s", exc)
        return None

    text = transcript_text.strip()
    if len(text) > max_input_chars:
        # Keep the LLM call bounded on very long episodes - a truncated
        # transcript still yields a useful summary of the first portion.
        text = text[:max_input_chars] + "\n[...transcript truncated for summarization...]"

    prompt = _SUMMARY_PROMPT.format(transcript=text)
    try:
        output = llm(prompt, max_tokens=512, temperature=0.2, stop=["---"])
    except Exception as exc:  # noqa: BLE001 - a bad generation shouldn't break the harvest
        LOG.error("Transcript enrichment generation failed: %s", exc)
        return None

    choice_text = output.get("choices", [{}])[0].get("text", "") if isinstance(output, dict) else ""
    return choice_text.strip() or None


def write_enrichment(app: AppSpace, choice: ModelChoice, transcript_path: Path,
                     transcript_text: str) -> Path | None:
    """Enrich `transcript_text` and write it alongside `transcript_path` as
    `<name>.summary.md`. Returns the written path, or None if skipped."""
    summary = enrich_transcript(app, choice, transcript_text)
    if not summary:
        return None
    out_path = transcript_path.with_suffix("").with_suffix(".summary.md")
    out_path.write_text(
        f"# Summary ({choice.model})\n\n{summary}\n", encoding="utf-8", newline="\n")
    LOG.info("Wrote enrichment summary: %s", out_path)
    return out_path
