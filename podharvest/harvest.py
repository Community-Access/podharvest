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
from dataclasses import dataclass
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
from podharvest.util import LOG, slugify, spoken_duration, write_text


def _resolve_model(settings, hw) -> ModelChoice:
    if settings.asr_engine and settings.asr_model:
        for choice in hardware_mod.available_models(hw):
            if choice.engine == settings.asr_engine and choice.model == settings.asr_model:
                return choice
    return hardware_mod.recommend_model(hw)


@dataclass
class EpisodeProgress:
    """One episode's state, handed to `episode_callback` as a run proceeds.

    The GUI turns these into rows in its episode list; the CLI ignores them and
    reads the log instead. `percent` is progress through *this* episode, not
    the run - `progress_callback` still reports the overall figure.
    """

    index: int                  # 1-based position in the transcription queue
    total: int
    title: str
    state: str                  # waiting | transcribing | summarising | done | failed | skipped
    percent: float = 0.0
    elapsed: float = 0.0
    detail: str = ""

    #: Wording used for the episode list and the status line, so the two never
    #: drift apart.
    STATE_LABELS = {
        "waiting": "Waiting",
        "transcribing": "Transcribing",
        "summarising": "Writing summary",
        "done": "Done",
        "failed": "Failed",
        "skipped": "Skipped",
    }

    @property
    def state_label(self) -> str:
        return self.STATE_LABELS.get(self.state, self.state.title())


def _transcribe_episode(engine, ep, feed_dir: Path, *, format_opt: transcribe_mod.FormatOptions,
                        identify_speakers: bool, hf_token: str | None, settings,
                        app: AppSpace | None = None, diarization_backend: str = "pyannote",
                        enrichment_model: ModelChoice | None = None,
                        position: tuple[int, int] | None = None,
                        report: Callable[[str, float, str], None] | None = None,
                        ) -> tuple[str, float, float]:
    """Transcribe one episode's primary audio. Returns (title, audio_s, elapsed_s)."""
    def say(state: str, percent: float = 0.0, detail: str = "") -> None:
        if report:
            report(state, percent, detail)

    audio = ep.primary_audio
    if not audio or not audio.local_path:
        say("skipped", 100.0, "no audio file")
        return ep.title, 0.0, 0.0
    where = f"Episode {position[0]} of {position[1]}: " if position else ""
    LOG.info("%sstarting on '%s'. This can take a few minutes.", where, ep.title)
    t0 = time.monotonic()
    say("transcribing", 0.0)
    result = engine.transcribe(Path(audio.local_path),
                               include_word_timestamps=format_opt.include_timestamps,
                               on_progress=lambda pct: say("transcribing", pct))
    if identify_speakers:
        say("transcribing", 100.0, "identifying speakers")
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

    LOG.info("%stranscript done for '%s'. %s of audio took %s (%.1f times faster than "
             "playing it).", where, ep.title, spoken_duration(result.audio_seconds),
             spoken_duration(elapsed), result.speed_x_realtime)
    LOG.debug("Engine %s/%s wrote %s", result.engine, result.model, md_path)

    if enrichment_model is not None and app is not None:
        from podharvest.enrich import write_enrichment
        LOG.info("%swriting the summary for '%s'...", where, ep.title)
        s0 = time.monotonic()
        say("summarising", 0.0)
        # Chapters need per-segment times. A cloud model that returns plain text
        # gives one segment spanning the episode, which would produce a single
        # meaningless chapter, so ask for them only when the times are real.
        has_times = len(result.segments) > 1
        want_chapters = getattr(settings, "write_chapters", False)
        if want_chapters and not has_times:
            LOG.info("%sskipping chapter markers for '%s': this model returns text "
                     "without timestamps.", where, ep.title)
        _, chapters = write_enrichment(
            app, enrichment_model, md_path, result.text,
            full_episode=getattr(settings, "enrichment_full_episode", True),
            max_input_chars=getattr(settings, "enrichment_max_chars", 24000),
            segments=result.segments if has_times else None,
            write_chapters=want_chapters and has_times,
            total_seconds=result.audio_seconds,
            on_step=lambda n, total_steps: say(
                "summarising", 100.0 * n / max(1, total_steps),
                f"part {n} of {total_steps}" if total_steps > 1 else ""),
        )
        LOG.info("%ssummary done for '%s' (%s).", where, ep.title,
                 spoken_duration(time.monotonic() - s0))

        # Put the chapters into the audio too, so a podcast player can jump
        # between topics. Lossless - the audio stream is copied, not re-encoded.
        if chapters and getattr(settings, "chapters_into_audio", True):
            from podharvest.chapters import embed_chapters
            embed_chapters(Path(audio.local_path), chapters, result.audio_seconds,
                           title=ep.title)
    say("done", 100.0)
    return ep.title, result.audio_seconds, elapsed


def run_harvest(url: str, *, app: AppSpace, settings: config_mod.Settings | None = None,
                output_dir: str | None = None, download: bool = True, transcribe: bool = False,
                model: ModelChoice | None = None, include_timestamps: bool = True,
                identify_speakers: bool = False, limit: int | None = None,
                cancel_event: threading.Event | None = None,
                progress_callback: Callable[[float], None] | None = None,
                episode_callback: Callable[[EpisodeProgress], None] | None = None,
                hf_token: str | None = None) -> int:
    settings = settings or config_mod.load(app)
    client_kwargs = {"delay": 0.0, "retries": max(0, settings.download_retries),
                     "cache": HttpCache(app.http_cache_dir)}
    if settings.user_agent:
        client_kwargs["user_agent"] = settings.user_agent
    client = HttpClient(**client_kwargs)

    LOG.info("Reading the podcast feed: %s", url)
    feed = feed_mod.fetch_and_parse(url, client, follow_pagination=settings.follow_pagination)
    if limit:
        feed.episodes = feed.episodes[:limit]
        for i, ep in enumerate(feed.episodes):
            ep.index = i

    base = Path(output_dir or config_mod.resolved_output_dir(app, settings))
    feed_dir = base / slugify(feed.title)
    transcripts_dir = feed_dir / "transcripts"
    LOG.info("Saving '%s' (%d episodes) into %s", feed.title, len(feed.episodes), feed_dir)

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
        LOG.info("Audio files: %d saved, %d failed.", ok, failed)
    elif progress_callback:
        progress_callback(100.0 * download_pct_share)

    if transcribe and not (cancel_event and cancel_event.is_set()):
        hw = hardware_mod.probe()
        choice = model or _resolve_model(settings, hw)
        cloud_run = getattr(choice, "is_cloud", False)
        if cloud_run:
            from podharvest import cloud as cloud_mod
            provider = cloud_mod.PROVIDERS.get(choice.provider)
            LOG.info("Making transcripts with %s, running on %s's servers. Each episode's "
                     "audio is uploaded to them.", choice.model,
                     provider.label if provider else choice.provider)
        else:
            LOG.info("Making transcripts with %s, running on the %s.", choice.model,
                     "CPU" if hw.accelerator == "cpu" else hw.accelerator.upper())
        if not cloud_run and not ensure_engine_packages(app, choice.engine):
            LOG.error("Could not install packages for engine '%s'; skipping transcription.", choice.engine)
        else:
            if cloud_run and identify_speakers and choice.speakers_built_in:
                # The model labels speakers itself, so the separate diarization
                # pass would only overwrite better labels with worse ones.
                LOG.info("%s labels speakers itself, so the separate speaker "
                         "identification step is not needed.", choice.model)
                identify_speakers = False
            elif identify_speakers and not ensure_diarization_packages(app, settings.diarization_backend):
                LOG.warning("Could not install packages for diarization backend '%s'; "
                           "transcripts will not have speaker labels.", settings.diarization_backend)
                identify_speakers = False

            if cloud_run:
                from podharvest import cloud as cloud_mod
                engine = cloud_mod.build_cloud_engine(app, choice)
            else:
                compute_type = "float16" if hw.accelerator in {"cuda", "rocm"} else "int8"
                engine = transcribe_mod.build_engine(
                    app, choice, device=hw.accelerator if hw.accelerator != "metal" else "cpu",
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
            # Fraction completed of each in-flight episode, so the overall bar
            # advances smoothly through a long file instead of jumping once an
            # hour. Keyed by episode index; guarded because workers may be >1.
            partial: dict[int, float] = {}
            # When each episode's own work began, so the reported elapsed time is
            # that episode's, not the whole run's.
            started_at: dict[int, float] = {}
            counter_lock = threading.Lock()

            def overall() -> float:
                units = done + sum(partial.values())
                return 100.0 * download_pct_share + 100.0 * (1 - download_pct_share) * units / total

            def report(n: int, ep, state: str, percent: float, detail: str) -> None:
                now = time.monotonic()
                with counter_lock:
                    nonlocal done
                    started_at.setdefault(n, now)
                    if state in {"done", "failed", "skipped"}:
                        partial.pop(n, None)
                        done += 1
                    else:
                        # The summary pass is the tail of one episode's work, so
                        # it maps onto the last slice of that episode's share.
                        frac = percent / 100.0
                        partial[n] = min(1.0, 0.85 * frac if state == "transcribing"
                                         else 0.85 + 0.15 * frac)
                    pct = overall()
                    elapsed = now - started_at[n]
                if progress_callback:
                    progress_callback(pct)
                if episode_callback:
                    episode_callback(EpisodeProgress(
                        index=n, total=len(candidates), title=ep.title, state=state,
                        percent=percent, elapsed=elapsed, detail=detail))

            workers = max(1, settings.concurrent_transcriptions)
            LOG.info("%d episode(s) to transcribe.", len(candidates))
            if episode_callback:
                for n, ep in enumerate(candidates, 1):
                    episode_callback(EpisodeProgress(index=n, total=len(candidates),
                                                     title=ep.title, state="waiting"))

            def make_report(n, ep):
                return lambda state, percent, detail: report(n, ep, state, percent, detail)

            if workers == 1:
                for n, ep in enumerate(candidates, 1):
                    if cancel_event and cancel_event.is_set():
                        break
                    try:
                        _transcribe_episode(engine, ep, feed_dir, format_opt=format_opt,
                                            identify_speakers=identify_speakers, hf_token=hf_token,
                                            settings=settings, app=app,
                                            diarization_backend=settings.diarization_backend,
                                            enrichment_model=enrichment_choice,
                                            position=(n, len(candidates)),
                                            report=make_report(n, ep))
                    except Exception as exc:  # noqa: BLE001 - one bad file must not end the run
                        LOG.error("Could not transcribe '%s': %s", ep.title, exc)
                        report(n, ep, "failed", 100.0, str(exc))
            else:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="asr") as pool:
                    futures = {
                        pool.submit(_transcribe_episode, engine, ep, feed_dir, format_opt=format_opt,
                                   identify_speakers=identify_speakers, hf_token=hf_token,
                                   settings=settings, app=app,
                                   diarization_backend=settings.diarization_backend,
                                   enrichment_model=enrichment_choice,
                                   position=(n, len(candidates)),
                                   report=make_report(n, ep)): (n, ep)
                        for n, ep in enumerate(candidates, 1)
                    }
                    for future in as_completed(futures):
                        n, ep = futures[future]
                        try:
                            future.result()
                        except Exception as exc:  # noqa: BLE001
                            LOG.error("Could not transcribe '%s': %s", ep.title, exc)
                            report(n, ep, "failed", 100.0, str(exc))

    if progress_callback:
        progress_callback(100.0)
    LOG.info("All done. Everything is in %s", feed_dir)
    return 0
