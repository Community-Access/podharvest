# Modules shared with QUILL

Some files exist byte-for-byte in both podHarvest and QUILL. They are not a
library and not a submodule: each repo carries its own copy, and a SHA-256
drift test in each fails the build when the two stop matching. That is
deliberate. Both apps ship standalone, neither may depend on the other, and
a silent divergence in shared logic is the failure worth engineering
against.

| File here | File in QUILL | Test that holds it |
|---|---|---|
| `podharvest/audio_tags_core.py` | `quill/core/speech/audio_tags_core.py` | `tests/test_audio_tags.py` |
| `podharvest/reuse_core.py` | `quill/core/speech/reuse_core.py` | `tests/test_reuse.py` |
| `podharvest/timing_core.py` | *(not yet adopted)* | `tests/test_timing.py` |

## The rules

- Standard library only. No wx, no third-party packages, no imports from
  `podharvest` or `quill`. A test enforces this for `timing_core`.
- Line endings are pinned with `-text` in `.gitattributes`. Without that,
  `* text=auto eol=lf` rewrites the file on checkout and the two copies
  hash differently on different machines.
- To change one: edit here, copy the file to QUILL, regenerate both
  digests, commit both repos. There is no shortcut, and the test is what
  stops there being one.

## Candidates not yet shared

These exist here and QUILL has no equivalent. They are written to be
portable; adoption is a later cycle's work.

- `podharvest/a11y.py` — `set_accessible_name` and the rule that composite
  controls keep their native accessibility, with `tests/test_a11y.py`.
  QUILL uses `SetName` in places where the same trap applies.
- `podharvest/help_audit.py` — the AST gate that fails the build when a
  focusable control ships with no help authored at its construction site.
  It follows subclasses of wx controls, so it cannot be dodged by wrapping
  one, and a companion test refuses to let a module that imports `wx` stay
  outside `SCAN_FILES`.
- `scripts/code_signing.py` — Authenticode via Azure Trusted Signing, with
  the signing library pinned and hash-verified before it is loaded.
- `installer/podharvest.iss` `[Code]` section — native `TNewCheckBox`
  instead of `[Tasks]`, because Inno's own check list never reports its
  checked state to a screen reader.
