# Contributing to podHarvest

Thanks for considering a contribution. This project archives podcast feeds and transcribes them on-device by default, with optional opt-in cloud providers, and it is used in part by people who rely on assistive technology — which shapes a few of the guidelines below.

## Getting set up

```bash
git clone https://github.com/community-access/podharvest
cd podharvest
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev,gui]"
```

Then check it works:

```bash
python -m pytest tests/ -q
python -m podharvest info
python -m podharvest hardware
```

The core pipeline — feed parsing, conversion, rendering, downloading — depends on the standard library alone. Everything heavier (ASR engines, diarization, enrichment LLMs) is optional and is installed on demand into the portable app space the first time it is used. Please keep it that way: a new hard dependency in `podharvest/` core needs a good reason.

## Before you open a pull request

```bash
python -m pytest tests/ -q      # must pass
ruff check podharvest tests     # must be clean
```

CI runs the tests on Linux, macOS and Windows against Python 3.10–3.13. Windows matters more than usual here: the app is heavily used there, and path handling, reserved filenames, and long-path limits have all caused real bugs.

## What to work on

`docs/ACCESSIBILITY.md` has a "Known gaps" section in each part. Those are real, specific, and open. The most valuable single contribution right now is **a screen reader pass** against either the GUI or the generated HTML, reported as an issue — nobody has done one, and the documentation says so plainly.

The README roadmap lists the larger outstanding pieces.

## Guidelines

**Accessibility is a functional requirement.** If you change `podharvest/gui.py` or anything that shapes generated HTML (`render.py`, `convert.py`), consider how it reads to a screen reader, not just how it looks. Concretely:

- Never claim an accessibility behaviour in code comments or docs without verifying it. `docs/ACCESSIBILITY.md` records what has actually been checked and what has not; keep that distinction intact.
- Controls need an accessible name from an adjacent label or from `set_accessible_name()`. `wx.Window.SetName()` alone does not do this.
- Never disable the control that currently has focus without moving focus somewhere sensible first.
- Generated HTML should keep semantic structure. If a change would drop `<th>`, `scope`, `<caption>`, `<track>`, or heading levels, that is a regression.

**Do not trust feed content.** Everything from a feed is untrusted input. Escape it on the way into HTML, and be careful with anything that becomes a filename or a URL. `tests/test_convert.py` has regression tests for injection and obfuscated URL schemes — add to them rather than working around them.

**Downloads must never be silently wrong.** A truncated or duplicated download that gets recorded as complete is worse than a failure, because it is never retried. `tests/test_net_download.py` covers this; if you touch `net.stream` or `download.py`, keep those tests passing.

**Tests for behaviour, not coverage.** A test should name the thing that would break. Several tests in this repo document a specific past defect in their docstring — that is the style to follow.

**Match the surrounding code.** Type hints on public functions, docstrings that explain *why* rather than restating the signature, and comments only where the reason is not obvious from the code.

## Commit messages and PRs

Write a subject line that says what changed and why it matters. In the PR description, say what you verified and how — especially for anything touching downloads, transcription, or accessibility, where "it looked fine" is not enough.

If a change fixes a bug, a regression test is the best evidence it is fixed.

## Adding an ASR engine

The catalogue in `podharvest/hardware.py` and the dispatch in `podharvest.transcribe.build_engine` must agree. A model listed in the catalogue but not implemented in `build_engine` is offered to users in the GUI dropdown and to `podharvest benchmark`, and then fails at run time — this has happened before. If you add a `ModelChoice`, add the engine in the same PR, or do not add the `ModelChoice`.

An engine implements the `Engine` protocol: a `transcribe(audio_path, *, include_word_timestamps, on_progress=None)` returning a `TranscriptResult`. Look at `VoskEngine` for the simplest complete example.

## Reporting bugs

Include your OS, Python version, the exact command you ran, and the relevant part of `--log-file` output. For feed-parsing bugs, the feed URL is the single most useful thing you can provide.

## Code of Conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Contributions are accepted under the [MIT License](LICENSE).
