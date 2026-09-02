"""Side-by-side ASR model benchmarking: run several engine/model combos
against the same audio and report timing, throughput, accuracy (Word Error
Rate against an optional reference transcript), and a text preview for
manual quality comparison. Results are written to both the standard log
and a standalone Markdown report so comparisons are easy to revisit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from podharvest.accuracy import word_error_rate
from podharvest.appspace import AppSpace
from podharvest.hardware import Hardware, ModelChoice
from podharvest.transcribe import build_engine
from podharvest.util import LOG, HarvestError, human_duration, write_text


@dataclass
class BenchmarkRow:
    engine: str
    model: str
    audio_file: str
    audio_seconds: float = 0.0
    load_seconds: float = 0.0
    transcribe_seconds: float = 0.0
    speed_x_realtime: float = 0.0
    preview: str = ""
    wer: float | None = None
    accuracy: float | None = None
    error: str | None = None


@dataclass
class BenchmarkReport:
    rows: list[BenchmarkRow] = field(default_factory=list)

    def totals_by_model(self) -> dict[str, dict[str, float]]:
        totals: dict[str, dict[str, float]] = {}
        for row in self.rows:
            key = f"{row.engine}:{row.model}"
            t = totals.setdefault(key, {"audio": 0.0, "elapsed": 0.0, "failed": 0,
                                        "wer_sum": 0.0, "wer_n": 0})
            if row.error:
                t["failed"] += 1
                continue
            t["audio"] += row.audio_seconds
            t["elapsed"] += row.transcribe_seconds
            if row.wer is not None:
                t["wer_sum"] += row.wer
                t["wer_n"] += 1
        return totals


def load_reference_transcripts(audio_paths: list[Path], reference_dir: Path | None,
                               reference_text: str | None) -> dict[str, str]:
    """Map each audio file's name to a reference transcript.

    - `reference_text` applies the same reference to every audio file (useful
      when benchmarking clips of the same source recording).
    - `reference_dir` looks for `<audio-stem>.txt` next to each audio file's
      name inside that folder, so different files can have different
      references.
    """
    refs: dict[str, str] = {}
    for audio_path in audio_paths:
        name = Path(audio_path).name
        if reference_dir:
            candidate = reference_dir / f"{Path(audio_path).stem}.txt"
            if candidate.exists():
                refs[name] = candidate.read_text(encoding="utf-8", errors="replace")
                continue
        if reference_text:
            refs[name] = reference_text
    return refs


def run_benchmark(app: AppSpace, audio_paths: list[Path], choices: list[ModelChoice],
                  hw: Hardware, *, include_word_timestamps: bool = False,
                  references: dict[str, str] | None = None) -> BenchmarkReport:
    references = references or {}
    report = BenchmarkReport()
    for choice in choices:
        LOG.info("=== Benchmarking %s:%s ===", choice.engine, choice.model)
        try:
            device = hw.accelerator if hw.accelerator != "metal" else "cpu"
            compute_type = "float16" if hw.accelerator in {"cuda", "rocm"} else "int8"
            t0 = time.monotonic()
            engine = build_engine(app, choice, device=device, compute_type=compute_type)
            if hasattr(engine, "_load"):
                engine._load()
            load_s = time.monotonic() - t0
        except HarvestError as exc:
            LOG.warning("Skipping %s:%s - %s", choice.engine, choice.model, exc)
            report.rows.append(BenchmarkRow(choice.engine, choice.model, "(all files)", error=str(exc)))
            continue

        for audio_path in audio_paths:
            file_name = Path(audio_path).name
            try:
                result = engine.transcribe(audio_path, include_word_timestamps=include_word_timestamps)
                row = BenchmarkRow(
                    engine=choice.engine, model=choice.model, audio_file=file_name,
                    audio_seconds=result.audio_seconds, load_seconds=load_s,
                    transcribe_seconds=result.transcribe_seconds, speed_x_realtime=result.speed_x_realtime,
                    preview=result.text[:120].replace("\n", " "),
                )
                reference = references.get(file_name)
                if reference:
                    wer_result = word_error_rate(reference, result.text)
                    row.wer, row.accuracy = wer_result.wer, wer_result.accuracy
                    LOG.info("  %s: %.1fs audio -> %.1fs (%.2fx real-time), WER %.1f%% (accuracy %.1f%%)",
                             file_name, row.audio_seconds, row.transcribe_seconds, row.speed_x_realtime,
                             row.wer * 100, row.accuracy * 100)
                else:
                    LOG.info("  %s: %.1fs audio -> %.1fs (%.2fx real-time)",
                             file_name, row.audio_seconds, row.transcribe_seconds, row.speed_x_realtime)
            except Exception as exc:  # noqa: BLE001 - one failed file shouldn't sink the benchmark
                LOG.error("  %s failed: %s", file_name, exc)
                row = BenchmarkRow(choice.engine, choice.model, file_name, error=str(exc))
            report.rows.append(row)
    return report


def render_benchmark_markdown(report: BenchmarkReport, hw: Hardware) -> str:
    has_wer = any(row.wer is not None for row in report.rows)
    lines = ["# ASR model benchmark", "",
             f"Hardware: {hw.cpu_name} | {hw.ram_gb} GB RAM | "
             f"accelerator: {hw.accelerator}"
             + (f" ({hw.best_gpu.name})" if hw.best_gpu else ""), ""]
    if not has_wer:
        lines += ["*No reference transcript was supplied, so only timing/throughput are shown. "
                 "Pass `--reference`/`--reference-dir` to also measure Word Error Rate (WER).*", ""]

    summary_header = "| Engine:Model | Audio processed | Time taken | Speed | Avg WER | Avg accuracy | Failures |" \
        if has_wer else "| Engine:Model | Audio processed | Time taken | Speed | Failures |"
    summary_sep = "|---|---|---|---|---|---|---|" if has_wer else "|---|---|---|---|---|"
    lines += ["## Summary (total audio processed vs. total time taken)", "", summary_header, summary_sep]
    for key, t in report.totals_by_model().items():
        speed = round(t["audio"] / t["elapsed"], 2) if t["elapsed"] else 0.0
        if has_wer:
            avg_wer = t["wer_sum"] / t["wer_n"] if t["wer_n"] else None
            wer_cell = f"{avg_wer * 100:.1f}%" if avg_wer is not None else "-"
            acc_cell = f"{(1 - avg_wer) * 100:.1f}%" if avg_wer is not None else "-"
            lines.append(f"| {key} | {human_duration(int(t['audio']))} | {t['elapsed']:.1f}s | "
                         f"{speed}x real-time | {wer_cell} | {acc_cell} | {int(t['failed'])} |")
        else:
            lines.append(f"| {key} | {human_duration(int(t['audio']))} | {t['elapsed']:.1f}s | "
                         f"{speed}x real-time | {int(t['failed'])} |")

    detail_header = "| Engine:Model | File | Audio | Elapsed | Speed | WER | Notes |" \
        if has_wer else "| Engine:Model | File | Audio | Elapsed | Speed | Notes |"
    detail_sep = "|---|---|---|---|---|---|---|" if has_wer else "|---|---|---|---|---|---|"
    lines += ["", "## Per-file detail", "", detail_header, detail_sep]
    for row in report.rows:
        if row.error:
            filler = "| - | - | - | - |" if has_wer else "| - | - | - |"
            lines.append(f"| {row.engine}:{row.model} | {row.audio_file} {filler} FAILED: {row.error} |")
        elif has_wer:
            wer_cell = f"{row.wer * 100:.1f}%" if row.wer is not None else "-"
            lines.append(f"| {row.engine}:{row.model} | {row.audio_file} | "
                         f"{human_duration(int(row.audio_seconds))} | {row.transcribe_seconds:.1f}s | "
                         f"{row.speed_x_realtime}x | {wer_cell} | \"{row.preview}...\" |")
        else:
            lines.append(f"| {row.engine}:{row.model} | {row.audio_file} | "
                         f"{human_duration(int(row.audio_seconds))} | {row.transcribe_seconds:.1f}s | "
                         f"{row.speed_x_realtime}x | \"{row.preview}...\" |")
    return "\n".join(lines).strip() + "\n"


def write_benchmark_report(report: BenchmarkReport, hw: Hardware, path: Path) -> Path:
    return write_text(path, render_benchmark_markdown(report, hw))
