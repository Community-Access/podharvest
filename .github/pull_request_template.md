## What this changes

<!-- What changed, and why it matters. -->

## How it was verified

<!-- Say what you actually ran. "Tests pass" is fine for a small change; anything
     touching downloads, transcription, or accessibility needs more than that. -->

- [ ] `python -m pytest tests/ -q` passes
- [ ] `ruff check podharvest tests` is clean

## Checklist

- [ ] A regression test covers the bug, if this fixes one
- [ ] `CHANGELOG.md` updated for a user-visible change
- [ ] If this touches the GUI or generated HTML: considered how it reads to a screen reader,
      and did not add an accessibility claim to the docs that has not been verified
- [ ] If this adds a `ModelChoice`: the matching engine is implemented in `build_engine`
