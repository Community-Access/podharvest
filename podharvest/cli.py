"""Command-line front end for podharvest.

Design goals:
- Running with no arguments shows a full usage screen (never a stack trace).
- Every subcommand also supports `-h/--help` with examples.
- If wxPython is installed and the user runs `podharvest` with no arguments
  in an interactive desktop session, we offer to launch the GUI instead of
  just printing help (use `--no-gui-prompt` or set PODHARVEST_NO_GUI=1 to
  suppress this, e.g. in CI or headless environments).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from podharvest import DISPLAY_NAME, __version__
from podharvest import appspace as appspace_mod
from podharvest import config as config_mod
from podharvest import hardware as hardware_mod
from podharvest.util import LOG, HarvestError, setup_logging

PROG = "podharvest"

EPILOG = """\
examples:
  podharvest fetch https://acbda.org/feed --transcribe
  podharvest fetch https://pinecast.com/feed/acb-diabetics-in-action -o D:\\Podcasts
  podharvest fetch https://acbda.org/feed --limit 5
  podharvest fetch --limit all          (re-uses the last feed URL, fetches everything)
  podharvest hardware
  podharvest hardware --json
  podharvest settings --show
  podharvest settings --set output_dir=D:\\Podcasts --set episode_limit=10
  podharvest gui

run "podharvest <command> --help" for command-specific options.
"""


def _limit_type(value: str) -> int | None:
    if value.strip().lower() in {"all", "none", ""}:
        return None
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--limit must be a whole number or 'all', got {value!r}") from exc
    if n < 0:
        raise argparse.ArgumentTypeError("--limit cannot be negative")
    return n


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--app-dir", metavar="PATH", help="Portable app-space root (models, cache, config, logs).")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity (-v, -vv).")
    p.add_argument("-q", "--quiet", action="store_true", help="Only show warnings and errors.")
    p.add_argument("--log-file", metavar="PATH", help="Also write detailed logs to this file.")
    p.add_argument("--no-gui-prompt", action="store_true",
                   help="Never offer to launch the GUI when run with no command "
                        "(same as setting PODHARVEST_NO_GUI=1).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Archive RSS/Atom/podcast feeds as Markdown, HTML, plain text and JSON, "
                     "download enclosures, and transcribe audio entirely on-device.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # PROG stays lowercase so "usage: podharvest fetch ..." shows the command
    # as typed, but --version is read aloud, so it gets the spoken form.
    parser.add_argument("--version", action="version",
                        version=f"{DISPLAY_NAME} {__version__}")
    _add_common(parser)

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_fetch = sub.add_parser("fetch", help="Download and convert a feed (and its enclosures).",
                              description="Fetch a feed, render every episode as Markdown/HTML/text/JSON, "
                                          "and download its enclosures into per-feed folders.")
    p_fetch.add_argument("url", nargs="?", help="Feed URL. If omitted, re-uses the last one, else prompts.")
    p_fetch.add_argument("-o", "--output", metavar="DIR", help="Destination folder (default: saved setting, then <app-dir>/feeds).")
    p_fetch.add_argument("--no-download", action="store_true", help="Convert content only; skip enclosure downloads.")
    p_fetch.add_argument("--transcribe", action="store_true", help="Transcribe downloaded audio on-device.")
    p_fetch.add_argument("--engine", metavar="ENGINE", help="ASR engine to use, e.g. faster-whisper, parakeet, parakeet-onnx.")
    p_fetch.add_argument("--model", metavar="MODEL", help="ASR model to use, e.g. small.en, parakeet-tdt-0.6b-v2.")
    p_fetch.add_argument("--limit", type=_limit_type, metavar="N|all",
                          help="Only process the first N episodes, or 'all' (default: saved setting, then all).")
    p_fetch.add_argument("--timestamps", dest="timestamps", action="store_true", default=None,
                          help="Include timestamps in transcripts (default: saved setting, then on).")
    p_fetch.add_argument("--no-timestamps", dest="timestamps", action="store_false",
                          help="Omit timestamps from transcripts.")
    p_fetch.add_argument("--speakers", dest="speakers", action="store_true", default=None,
                          help="Identify speakers via diarization (default: saved setting, then off).")
    p_fetch.add_argument("--no-speakers", dest="speakers", action="store_false",
                          help="Do not attempt speaker identification.")
    p_fetch.add_argument("--diarization-backend", choices=["pyannote", "sherpa-onnx", "nemo-msdd"],
                          help="Which speaker-identification engine to use: 'pyannote' (default, needs a HF "
                              "token), 'sherpa-onnx' (PyTorch-free, downloads ~120MB), or 'nemo-msdd' "
                              "(NVIDIA NeMo, needs the full PyTorch/NeMo stack).")
    p_fetch.add_argument("--hf-token", metavar="TOKEN",
                          help="Hugging Face access token for the gated pyannote diarization "
                              "models. Also read from $PODHARVEST_HF_TOKEN or $HF_TOKEN, or "
                              "the saved 'hf_token' setting.")
    p_fetch.add_argument("--timestamp-style", choices=["bracket", "paren", "none"],
                          help="How timestamps are written, e.g. [00:01:23] vs (00:01:23).")
    p_fetch.add_argument("--speaker-style", choices=["bold", "plain", "inline", "none"],
                          help="How speaker labels are written, e.g. **Alice:** vs Alice: vs (Alice).")
    p_fetch.add_argument("--paragraphs", dest="paragraphs", action="store_true", default=None,
                          help="Merge consecutive same-speaker lines into paragraphs instead of one line each.")
    p_fetch.add_argument("--no-paragraphs", dest="paragraphs", action="store_false",
                          help="One line per recognized speech segment (default).")
    p_fetch.add_argument("--line-width", type=int, metavar="N",
                          help="Wrap the plain-text transcript at N characters (0 = no wrapping).")
    _add_common(p_fetch)

    p_local = sub.add_parser(
        "local", help="Transcribe, summarise and chapter audio you already have.",
        description="Work on local audio files or folders: transcribe them, "
                    "write summaries, work out chapter markers and put them "
                    "into the file's tags. The same pipeline 'fetch' uses "
                    "after the download, without the feed.")
    p_local.add_argument("paths", nargs="+", metavar="PATH",
                         help="Audio files, or folders of them.")
    p_local.add_argument("--no-transcribe", action="store_true",
                         help="List what was found and stop; write nothing.")
    p_local.add_argument("--engine", metavar="ENGINE",
                         help="ASR engine to use, e.g. faster-whisper, parakeet.")
    p_local.add_argument("--model", metavar="MODEL",
                         help="ASR model to use, e.g. small.en.")
    p_local.add_argument("--beside", dest="beside", action="store_true", default=None,
                         help="Write each transcript beside its audio file (default).")
    p_local.add_argument("--no-beside", dest="beside", action="store_false",
                         help="Write transcripts into <output>/Local files instead.")
    p_local.add_argument("--no-recurse", action="store_true",
                         help="When given a folder, do not look in its subfolders.")
    p_local.add_argument("-o", "--output", metavar="DIR",
                         help="Library folder, used only with --no-beside.")
    p_local.add_argument("--timestamps", dest="timestamps", action="store_true", default=None,
                         help="Include timestamps in transcripts (default: saved setting).")
    p_local.add_argument("--no-timestamps", dest="timestamps", action="store_false",
                         help="Omit timestamps from transcripts.")
    p_local.add_argument("--speakers", dest="speakers", action="store_true", default=None,
                         help="Identify speakers via diarization.")
    p_local.add_argument("--no-speakers", dest="speakers", action="store_false",
                         help="Do not attempt speaker identification.")
    p_local.add_argument("--hf-token", metavar="TOKEN",
                         help="Hugging Face token for the gated pyannote models.")
    _add_common(p_local)

    p_hw = sub.add_parser("hardware", help="Detect hardware and recommend an on-device transcription model.",
                           description="Probe CPU/RAM/GPU and print (or emit as JSON) the recommended ASR setup.")
    p_hw.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of a summary.")
    p_hw.add_argument("--refresh", action="store_true", help="Ignore any cached hardware probe and re-detect.")
    _add_common(p_hw)

    p_gui = sub.add_parser("gui", help="Launch the wxPython desktop application.",
                            description="Launch the graphical podHarvest application (requires wxPython).")
    _add_common(p_gui)

    p_info = sub.add_parser("info", help="Show the portable app-space paths in use.",
                             description="Print where podHarvest keeps its models, cache, config and logs.")
    _add_common(p_info)

    p_bench = sub.add_parser("benchmark", help="Compare ASR models/engines on the same audio file(s).",
                              description="Transcribe the same audio file(s) with several engine:model combos "
                                          "and report timing/throughput/accuracy/failures side by side.")
    p_bench.add_argument("audio", nargs="+", help="One or more audio files to benchmark against.")
    p_bench.add_argument("--model", action="append", dest="models", metavar="ENGINE:MODEL", default=[],
                          help="engine:model to include, e.g. faster-whisper:tiny.en. Repeatable. "
                              "Defaults to every model available on this hardware.")
    p_bench.add_argument("--reference", metavar="TEXT_OR_PATH",
                          help="A reference transcript (or path to a .txt file) applied to every audio file, "
                              "used to compute Word Error Rate (WER) alongside timing.")
    p_bench.add_argument("--reference-dir", metavar="DIR",
                          help="Folder containing one <audio-filename-stem>.txt reference transcript per "
                              "audio file, for per-file WER instead of one shared reference.")
    p_bench.add_argument("--report", metavar="PATH", help="Where to write the Markdown report "
                                                          "(default: <app-dir>/logs/benchmark.md).")
    _add_common(p_bench)

    p_set = sub.add_parser("settings", help="View or change saved defaults (output folder, limits, ASR options...).",
                            description="Read or update the persisted settings.json used by both the CLI and GUI.")
    p_set.add_argument("--show", action="store_true", help="Print the current settings as JSON.")
    p_set.add_argument("--set", action="append", metavar="KEY=VALUE", default=[],
                        help="Set a setting, e.g. --set output_dir=D:\\Podcasts. Repeatable.")
    p_set.add_argument("--reset", action="store_true", help="Restore every setting to its default value.")
    _add_common(p_set)

    return parser


def _resolve_app(args: argparse.Namespace):
    app = appspace_mod.resolve(getattr(args, "app_dir", None))
    app.activate()
    verbosity = getattr(args, "verbose", 0)
    if not verbosity and not getattr(args, "quiet", False):
        # Fall back to the saved preference so `-v` does not have to be typed
        # on every invocation.
        try:
            verbosity = max(0, int(config_mod.load(app).log_verbosity))
        except (OSError, ValueError, TypeError):
            verbosity = 0
    setup_logging(
        verbosity=verbosity,
        quiet=getattr(args, "quiet", False),
        logfile=(__import__("pathlib").Path(args.log_file) if getattr(args, "log_file", None)
                 else app.logs_dir / "podharvest.log"),
    )
    return app


def _cmd_local(args: argparse.Namespace) -> int:
    """Run the pipeline over local files.

    Deliberately thin: everything of substance is in `podharvest.localfiles`,
    which the GUI calls too, so the two cannot disagree about what "process
    this file" means.
    """
    from pathlib import Path

    from podharvest.localfiles import run_local

    app = _resolve_app(args)
    settings = config_mod.load(app)

    if args.engine:
        settings.asr_engine = args.engine
    if args.model:
        settings.asr_model = args.model
    if args.timestamps is not None:
        settings.include_timestamps = args.timestamps
    if args.speakers is not None:
        settings.identify_speakers = args.speakers
    if args.beside is not None:
        settings.local_transcripts_beside_file = args.beside
    if args.no_recurse:
        settings.local_recurse_folders = False
    if args.output:
        settings.output_dir = args.output
    if args.hf_token:
        settings.hf_token = args.hf_token
    config_mod.save(app, settings)

    hf_token = (args.hf_token or settings.hf_token
                or os.environ.get("PODHARVEST_HF_TOKEN", "")
                or os.environ.get("HF_TOKEN", "")) or None

    return run_local(
        [Path(entry) for entry in args.paths],
        app=app,
        settings=settings,
        transcribe=not args.no_transcribe,
        include_timestamps=settings.include_timestamps,
        identify_speakers=settings.identify_speakers,
        hf_token=hf_token,
    )


def _cmd_hardware(args: argparse.Namespace) -> int:
    app = _resolve_app(args)
    hw = hardware_mod.probe(refresh=args.refresh)
    if args.json:
        print(json.dumps(hw.to_dict(), indent=2))
    else:
        print("\n".join(hw.summary_lines()))
        print(f"\nApp space: {app.root}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    app = _resolve_app(args)
    rows = {
        "App root": app.root,
        "Models": app.models_dir,
        "  Whisper": app.whisper_models_dir,
        "  Parakeet": app.parakeet_models_dir,
        "  Diarization": app.diarization_models_dir,
        "Isolated packages": app.python_packages_dir,
        "HTTP cache": app.http_cache_dir,
        "Config": app.config_dir,
        "Logs": app.logs_dir,
        "Default output": app.default_output_dir,
    }
    width = max(len(k) for k in rows)
    for key, value in rows.items():
        print(f"{key.ljust(width)} : {value}")
    return 0


def _cmd_gui(args: argparse.Namespace) -> int:
    _resolve_app(args)
    try:
        from podharvest.gui import run_gui
    except ImportError as exc:
        print("The desktop GUI requires wxPython. Install it with:\n"
              "    pip install wxPython\n"
              f"(import error: {exc})", file=sys.stderr)
        return 2
    return run_gui() or 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    app = _resolve_app(args)
    settings = config_mod.load(app)

    url = args.url or settings.last_feed_url
    if not url:
        try:
            url = input("Enter the RSS/Atom feed URL to harvest: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
    if not url:
        print("No feed URL provided.", file=sys.stderr)
        return 2

    output_dir = args.output or config_mod.resolved_output_dir(app, settings)
    limit = args.limit if args.limit is not None else settings.episode_limit

    settings.last_feed_url = url
    settings.output_dir = output_dir
    settings.episode_limit = limit
    settings.transcribe = args.transcribe or settings.transcribe
    if args.engine:
        settings.asr_engine = args.engine
    if args.model:
        settings.asr_model = args.model
    if args.timestamps is not None:
        settings.include_timestamps = args.timestamps
    if args.speakers is not None:
        settings.identify_speakers = args.speakers
    if args.diarization_backend:
        settings.diarization_backend = args.diarization_backend
    if args.timestamp_style:
        settings.transcript_timestamp_style = args.timestamp_style
    if args.speaker_style:
        settings.transcript_speaker_style = args.speaker_style
    if args.paragraphs is not None:
        settings.transcript_paragraph_mode = args.paragraphs
    if args.line_width is not None:
        settings.transcript_max_line_chars = args.line_width or None
    if args.hf_token:
        settings.hf_token = args.hf_token
    config_mod.save(app, settings)

    hf_token = (args.hf_token or settings.hf_token
                or os.environ.get("PODHARVEST_HF_TOKEN", "")
                or os.environ.get("HF_TOKEN", "")) or None
    if settings.identify_speakers and settings.diarization_backend == "pyannote" and not hf_token:
        LOG.warning(
            "Speaker identification uses the 'pyannote' backend, whose models are gated on "
            "Hugging Face and need an access token. Pass --hf-token, set $PODHARVEST_HF_TOKEN, "
            "or switch to the token-free backend with --diarization-backend sherpa-onnx.")

    try:
        from podharvest.harvest import run_harvest
    except ImportError as exc:
        LOG.error("Fetch pipeline is not fully wired up yet (%s).", exc)
        print(f"'{PROG} fetch' needs the feed/render/download modules, which are still being assembled "
              "in this workspace. Try 'podharvest hardware' or 'podharvest info' in the meantime.",
              file=sys.stderr)
        return 3
    return run_harvest(
        url,
        app=app,
        settings=settings,
        output_dir=output_dir,
        download=not args.no_download,
        transcribe=settings.transcribe,
        include_timestamps=settings.include_timestamps,
        identify_speakers=settings.identify_speakers,
        limit=limit,
        hf_token=hf_token,
    )


def _cmd_settings(args: argparse.Namespace) -> int:
    app = _resolve_app(args)
    settings = config_mod.Settings() if args.reset else config_mod.load(app)

    for pair in args.set:
        if "=" not in pair:
            print(f"Ignoring malformed --set value (expected KEY=VALUE): {pair!r}", file=sys.stderr)
            continue
        key, _, raw_value = pair.partition("=")
        key = key.strip()
        if key not in settings.to_dict():
            print(f"Unknown setting: {key!r}", file=sys.stderr)
            continue
        current = getattr(settings, key)
        try:
            value = _coerce_setting(current, raw_value.strip())
        except ValueError as exc:
            print(f"Could not set {key}: {exc}", file=sys.stderr)
            continue
        setattr(settings, key, value)

    if args.reset or args.set:
        config_mod.save(app, settings)
        print(f"Settings saved to {app.config_file}")

    if args.show or not (args.reset or args.set):
        print(json.dumps(settings.to_dict(), indent=2, sort_keys=True))
    return 0


def _coerce_setting(current, raw_value: str):
    if raw_value.lower() in {"none", "null", ""}:
        return None
    if isinstance(current, bool):
        return raw_value.lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int) or current is None:
        if raw_value.lower() == "all":
            return None
        return int(raw_value)
    if isinstance(current, list):
        return [v.strip() for v in raw_value.split(",") if v.strip()]
    return raw_value


def _cmd_benchmark(args: argparse.Namespace) -> int:
    app = _resolve_app(args)
    from pathlib import Path as _Path

    from podharvest import benchmark as benchmark_mod

    hw = hardware_mod.probe()
    if args.models:
        catalogue = {f"{c.engine}:{c.model}": c
                     for c in hardware_mod.available_models(hw, app, include_cloud=True)}
        choices = []
        for spec in args.models:
            if spec not in catalogue:
                print(f"Unknown or unavailable model: {spec!r}. Run 'podharvest hardware' to see options.",
                      file=sys.stderr)
                return 2
            choices.append(catalogue[spec])
    else:
        choices = hardware_mod.available_models(hw, app, include_cloud=True)

    audio_paths = [_Path(p) for p in args.audio]
    missing = [p for p in audio_paths if not p.exists()]
    if missing:
        print(f"File(s) not found: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2

    reference_dir = _Path(args.reference_dir) if args.reference_dir else None
    if reference_dir and not reference_dir.is_dir():
        print(f"--reference-dir is not a folder: {reference_dir}", file=sys.stderr)
        return 2
    reference_text = None
    if args.reference:
        ref_path = _Path(args.reference)
        reference_text = ref_path.read_text(encoding="utf-8", errors="replace") if ref_path.is_file() else args.reference
    references = benchmark_mod.load_reference_transcripts(audio_paths, reference_dir, reference_text)

    report = benchmark_mod.run_benchmark(app, audio_paths, choices, hw, references=references)
    report_path = _Path(args.report) if args.report else app.logs_dir / "benchmark.md"
    benchmark_mod.write_benchmark_report(report, hw, report_path)
    print(benchmark_mod.render_benchmark_markdown(report, hw))
    print(f"Report saved to {report_path}")
    return 0


_HANDLERS = {
    "fetch": _cmd_fetch,
    "local": _cmd_local,
    "hardware": _cmd_hardware,
    "gui": _cmd_gui,
    "info": _cmd_info,
    "settings": _cmd_settings,
    "benchmark": _cmd_benchmark,
}


def _maybe_offer_gui(args: argparse.Namespace) -> bool:
    if (getattr(args, "no_gui_prompt", False)
            or os.environ.get("PODHARVEST_NO_GUI") == "1"
            or not sys.stdin.isatty() or not sys.stdout.isatty()):
        return False
    try:
        import wx  # noqa: F401
    except ImportError:
        return False
    try:
        answer = input("No command given. Launch the podHarvest GUI? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if answer in ("", "y", "yes"):
        return _cmd_gui(args) == 0
    return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        print()
        if _maybe_offer_gui(args):
            return 0
        return 0

    handler = _HANDLERS.get(args.command)
    if handler is None:  # pragma: no cover - argparse already restricts choices
        parser.print_help()
        return 2

    try:
        return handler(args)
    except HarvestError as exc:
        LOG.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


def main_gui(argv: Sequence[str] | None = None) -> int:
    """Entry point for the windowed `podharvest-gui` script.

    Identical to `main`, except that with no arguments it launches the GUI
    directly instead of printing usage - there is no console to print to.
    """
    return main(list(argv) if argv is not None else ["gui"])


if __name__ == "__main__":
    raise SystemExit(main())
