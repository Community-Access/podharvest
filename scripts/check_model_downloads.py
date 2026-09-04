"""Download every model in the catalogue and check it verifies.

Not a unit test. This talks to Hugging Face and Alphacephei, takes tens of
gigabytes and the better part of an hour, and is meant to be run by hand
before a release -- because the interesting failures in model acquisition are
exactly the ones a mocked test cannot see. The bug that prompted it (a
perfectly good download rejected as "missing or truncated .gitignore") passed
every unit test in the suite.

There are seven distinct routes through `acquire`, and a model is only
interesting here insofar as it exercises one:

* a whole Hugging Face repo snapshot     -- faster-whisper, moonshine, parakeet, canary
* a single named file in a repo          -- llama-cpp GGUF files
* a zip archive over plain HTTPS         -- vosk
* the onnx triple-file layout            -- parakeet-onnx
* and the three verification branches those land in.

Run it with a roomy app space::

    PODHARVEST_HOME=S:/podharvest-modeltest python scripts/check_model_downloads.py
    ... --only vosk,moonshine        one or more engines
    ... --max-gb 2                   skip anything bigger
    ... --keep                       leave the files behind

Every model is checked three ways: it downloads, `verify_model` accepts what
arrived, and `is_downloaded` says yes on a *second* look -- which is the one
that failed before, because the first check used a fresh file list and the
second read the manifest.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field

from podharvest import acquire
from podharvest import appspace as appspace_mod
from podharvest import hardware as hardware_mod
from podharvest.util import setup_logging


@dataclass
class Outcome:
    """What happened to one model."""

    engine: str
    model: str
    size_gb: float
    downloaded: bool = False
    verified: bool = False
    reread: bool = False
    seconds: float = 0.0
    bytes_on_disk: int = 0
    note: str = ""
    skipped: str = ""
    percents: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.downloaded and self.verified and self.reread

    def line(self) -> str:
        if self.skipped:
            return f"SKIP  {self.engine:14} {self.model:32} {self.skipped}"
        mark = "OK  " if self.ok else "FAIL"
        size = f"{self.bytes_on_disk / (1024 ** 3):5.2f}GB"
        detail = "" if self.ok else f"  <- {self.note}"
        progress = f" {len(self.percents):3d} progress reports" if self.percents else ""
        return (f"{mark}  {self.engine:14} {self.model:32} {size} "
                f"{self.seconds:6.1f}s{progress}{detail}")


def every_model() -> list:
    """The whole catalogue, ASR and enrichment, biggest last."""
    models = []
    for group in ("WHISPER_CHOICES", "PARAKEET_CHOICES", "PARAKEET_ONNX_CHOICES",
                  "CANARY_CHOICES", "VOSK_CHOICES", "MOONSHINE_CHOICES",
                  "ENRICHMENT_CHOICES"):
        models.extend(getattr(hardware_mod, group))
    # Smallest first: an early failure should be quick, and a slow success
    # should not delay the news that something small is broken.
    return sorted(models, key=lambda m: m.size_gb)


def check(app, choice, *, keep: bool) -> Outcome:
    """Download one model, verify it, then verify it again from the manifest."""
    result = Outcome(engine=choice.engine, model=choice.model,
                     size_gb=choice.size_gb)
    # Ask where it goes rather than working it out again here. Duplicating
    # that logic is what made this harness report a healthy 2 GB download as
    # "model directory does not exist" -- it was looking in the wrong folder.
    model_dir = acquire._model_dir(app, choice)
    if model_dir.exists() and not keep:
        shutil.rmtree(model_dir, ignore_errors=True)

    def on_progress(percent: float, _detail: str) -> None:
        whole = int(percent)
        if not result.percents or result.percents[-1] != whole:
            result.percents.append(whole)

    started = time.monotonic()
    try:
        if choice.kind == "enrichment" or choice.engine == "llama-cpp":
            acquired = acquire.acquire_enrichment_model(app, choice)
        else:
            acquired = acquire.acquire_asr_model(
                app, choice, on_progress=on_progress)
        # The result knows where it put things; trust it over any guess.
        model_dir = acquired.model_dir
        result.downloaded = True
    except Exception as exc:  # noqa: BLE001 - the whole point is to report it
        result.note = f"{type(exc).__name__}: {exc}"
        result.seconds = time.monotonic() - started
        return result
    result.seconds = time.monotonic() - started

    # 1. Does what arrived pass verification?
    ok, reason = acquire.verify_model(model_dir, choice)
    result.verified = ok
    if not ok:
        result.note = f"verify_model said: {reason}"

    # 2. And does a *fresh* look agree? This is the one that used to fail: the
    #    download checked a list it had just built, and everything afterwards
    #    read the manifest instead.
    result.reread = acquire.is_downloaded(app, choice)
    if result.verified and not result.reread:
        result.note = "verified on download but is_downloaded() says no"

    try:
        result.bytes_on_disk = sum(
            p.stat().st_size for p in model_dir.rglob("*") if p.is_file())
    except OSError:
        pass

    if not keep:
        shutil.rmtree(model_dir, ignore_errors=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="",
                        help="Comma-separated engines to check.")
    parser.add_argument("--max-gb", type=float, default=0.0,
                        help="Skip models bigger than this (0 = no limit).")
    parser.add_argument("--keep", action="store_true",
                        help="Leave the downloads in place.")
    args = parser.parse_args(argv)

    setup_logging(verbosity=1)
    app = appspace_mod.resolve()
    print(f"App space: {app.root}")
    print(f"Models:    {app.models_dir}")
    print()

    wanted = {e.strip() for e in args.only.split(",") if e.strip()}
    outcomes: list[Outcome] = []
    for choice in every_model():
        if wanted and choice.engine not in wanted:
            continue
        if args.max_gb and choice.size_gb > args.max_gb:
            outcomes.append(Outcome(
                engine=choice.engine, model=choice.model, size_gb=choice.size_gb,
                skipped=f"bigger than {args.max_gb} GB"))
            continue
        print(f"--- {choice.engine} / {choice.model} ({choice.size_gb} GB)",
              flush=True)
        try:
            outcome = check(app, choice, keep=args.keep)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            outcome = Outcome(engine=choice.engine, model=choice.model,
                              size_gb=choice.size_gb,
                              note=f"harness error: {exc}")
            traceback.print_exc()
        outcomes.append(outcome)
        print(outcome.line(), flush=True)
        print(flush=True)

    print("=" * 78)
    for outcome in outcomes:
        print(outcome.line())
    checked = [o for o in outcomes if not o.skipped]
    good = [o for o in checked if o.ok]
    print("=" * 78)
    print(f"{len(good)} of {len(checked)} checked models downloaded and verified.")
    return 0 if len(good) == len(checked) else 1


if __name__ == "__main__":
    sys.exit(main())
