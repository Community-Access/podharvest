"""Ties the feed parser, renderer, downloader and transcriber together.

This is what `podharvest fetch` and the GUI's "Start" button call. It never
does I/O itself beyond orchestration - all the real work lives in
`podharvest.feed`, `podharvest.render`, `podharvest.download`, and
`podharvest.transcribe`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from podharvest import config as config_mod
from podharvest import download as download_mod
from podharvest import feed as feed_mod
from podharvest import hardware as hardware_mod
from podharvest import render as render_mod
from podharvest import transcribe as transcribe_mod
from podharvest.acquire import ensure_diarization_packages, ensure_engine_packages
from podharvest.appspace import AppSpace
from podharvest.hardware import ModelChoice
from podharvest.net import HttpCache, HttpClient
from podharvest.util import LOG, slugify, write_text


def _resolve_model(settings, hw) -> ModelChoice:
    if settings.asr_engine and settings.asr_model:
        for choice in hardware_mod.available_models(hw):
            if choice.engine == settings.asr_engine and choice.model == settings.asr_model:
                return choice
    return hardware_mod.recommend_model(hw)


def _transcribe_episode(engine, ep, feed_dir: Path, *, format_opt: transcribe_mod.FormatOptions,
                        identify_speakers: bool, hf_token: str | None, settings,
                        app: AppSpace | None = None, diarization_backend: str = "pyannote",
                        enrichment_model: ModelChoice | None = None,
                        ) -> tuple[str, float, float]:
    """Transcribe one episode's primary audio. Returns (title, audio_s, elapsed_s)."""
    audio = ep.primary_audio
    if not audio or not audio.local_path:
        return ep.title, 0.0, 0.0
    t0 = time.monotonic()
    result = engine.transcribe(Path(audio.local_path), include_word_timestamps=format_opt.include_timestamps)
    if identify_speakers:
        turns = transcribe_mod.diarize(Path(audio.local_path), app=app, backend=diarization_backend,
                                       hf_token=hf_token)
        transcribe_mod.apply_speakers(result, turns)
    elapsed = time.monotonic() - t0

    out_dir = feed_dir / "transcripts"
    slug = render_mod.episode_slug(ep, settings)
    # The Markdown and plain-text transcripts are always written - they are the
    # transcript itself. The subtitle tracks are optional side-cars, so they
    # follow the write_srt / write_vtt settings.
    md_path = out_dir / f"{slug}.md"
    write_text(md_path, transcribe_mod.format_markdown(result, format_opt))
    write_text(out_dir / f"{slug}.txt", transcribe_mod.format_text(result, format_opt))
    if getattr(settings, "write_srt", True):
        write_text(out_dir / f"{slug}.srt", transcribe_mod.format_srt(result, format_opt))
    if getattr(settings, "write_vtt", False):
        write_text(out_dir / f"{slug}.vtt", transcribe_mod.format_vtt(result, format_opt))

    if enrichment_model is not None and app is not None:
        from podharvest.enrich import write_enrichment
        write_enrichment(app, enrichment_model, md_path, result.text)

    LOG.info("Transcribed '%s': %s audio in %.1fs (%.2fx real-time) with %s/%s.",
             ep.title, result.audio_seconds, elapsed, result.speed_x_realtime, result.engine, result.model)
    return ep.title, result.audio_seconds, elapsed


def run_harvest(url: str, *, app: AppSpace, settings: config_mod.Settings | None = None,
                output_dir: str | None = None, download: bool = True, transcribe: bool = False,
                model: ModelChoice | None = None, include_timestamps: bool = True,
                identify_speakers: bool = False, limit: int | None = None,
                cancel_event: threading.Event | None = None,
                progress_callback: Callable[[float], None] | None = None,
                hf_token: str | None = None) -> int:
    settings = settings or config_mod.load(app)
    client_kwargs = {"delay": 0.0, "retries": max(0, settings.download_retries),
                     "cache": HttpCache(app.http_cache_dir)}
    if settings.user_agent:
        client_kwargs["user_agent"] = settings.user_agent
    client = HttpClient(**client_kwargs)

    LOG.info("Fetching feed: %s", url)
    feed = feed_mod.fetch_and_parse(url, client, follow_pagination=settings.follow_pagination)
    if limit:
        feed.episodes = feed.episodes[:limit]
        for i, ep in enumerate(feed.episodes):
            ep.index = i

    base = Path(output_dir or config_mod.resolved_output_dir(app, settings))
    feed_dir = base / slugify(feed.title)
    transcripts_dir = feed_dir / "transcripts"
    LOG.info("Writing '%s' (%d episode(s)) to %s", feed.title, len(feed.episodes), feed_dir)

    # Create the full folder layout up front (markdown/html/text/json/audio/
    # video/images/documents/other/transcripts) so the structure is visible
    # immediately, even before any downloads or transcription have produced
    # files in some of them.
    for name in ("markdown", "html", "text", "json"):
        (feed_dir / name).mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("audio", "video", "image", "document", "other"):
        download_mod.kind_dir(feed_dir, kind).mkdir(parents=True, exist_ok=True)

    for ep in feed.episodes:
        render_mod.write_episode_outputs(ep, feed, feed_dir, settings)
    render_mod.write_feed_outputs(feed, feed_dir, settings)

    download_pct_share = 0.6 if transcribe else 1.0

    def scaled_download(pct: float) -> None:
        if progress_callback:
            progress_callback(pct * download_pct_share)

    if download and settings.download_enclosures:
        ok, failed = download_mod.download_all(
            feed, feed_dir, settings, client=client, cancel_event=cancel_event,
            progress_callback=scaled_download)
        LOG.info("Enclosure downloads: %d ok, %d failed.", ok, failed)
    elif progress_callback:
        progress_callback(100.0 * download_pct_share)

    if transcribe and not (cancel_event and cancel_event.is_set()):
        hw = hardware_mod.probe()
        choice = model or _resolve_model(settings, hw)
        LOG.info("Transcribing with %s:%s on %s.", choice.engine, choice.model, hw.accelerator)
        if not ensure_engine_packages(app, choice.engine):
            LOG.error("Could not install packages for engine '%s'; skipping transcription.", choice.engine)
        else:
            if identify_speakers and not ensure_diarization_packages(app, settings.diarization_backend):
                LOG.warning("Could not install packages for diarization backend '%s'; "
                           "transcripts will not have speaker labels.", settings.diarization_backend)
                identify_speakers = False
            compute_type = "float16" if hw.accelerator in {"cuda", "rocm"} else "int8"
            engine = transcribe_mod.build_engine(app, choice, device=hw.accelerator if hw.accelerator != "metal" else "cpu",
                                                 compute_type=compute_type)
            format_opt = transcribe_mod.FormatOptions(
                include_timestamps=include_timestamps,
                timestamp_style=settings.transcript_timestamp_style,
                include_speakers=identify_speakers,
                speaker_style=settings.transcript_speaker_style,
                paragraph_mode=settings.transcript_paragraph_mode,
                max_line_chars=settings.transcript_max_line_chars,
            )
            enrichment_choice = None
            if settings.enrichment_enabled:
                enrichment_choice = next(
                    (c for c in hardware_mod.available_enrichment_models(hw) if c.model == settings.enrichment_model),
                    None) or hardware_mod.recommend_enrichment_model(hw)
                if enrichment_choice is None:
                    LOG.warning("Enrichment was requested but no enrichment model fits this machine's RAM; skipping.")
            candidates = [ep for ep in feed.episodes
                         if ep.primary_audio and ep.primary_audio.local_path
                         and ep.primary_audio.status == "ok"]
            total = len(candidates) or 1
            done = 0

            def bump():
                nonlocal done
                done += 1
                if progress_callback:
                    progress_callback(100.0 * download_pct_share + (100.0 * (1 - download_pct_share) * done / total))

            workers = max(1, settings.concurrent_transcriptions)
            if workers == 1:
                for ep in candidates:
                    if cancel_event and cancel_event.is_set():
                        break
                    _transcribe_episode(engine, ep, feed_dir, format_opt=format_opt,
                                        identify_speakers=identify_speakers, hf_token=hf_token,
                                        settings=settings, app=app,
                                        diarization_backend=settings.diarization_backend,
                                        enrichment_model=enrichment_choice)
                    bump()
            else:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="asr") as pool:
                    futures = {
                        pool.submit(_transcribe_episode, engine, ep, feed_dir, format_opt=format_opt,
                                   identify_speakers=identify_speakers, hf_token=hf_token,
                                   settings=settings, app=app,
                                   diarization_backend=settings.diarization_backend,
                                   enrichment_model=enrichment_choice): ep
                        for ep in candidates
                    }
                    for future in as_completed(futures):
                        ep = futures[future]
                        try:
                            future.result()
                        except Exception as exc:  # noqa: BLE001
                            LOG.error("Transcription failed for '%s': %s", ep.title, exc)
                        bump()

    if progress_callback:
        progress_callback(100.0)
    LOG.info("Done: %s", feed_dir)
    return 0
