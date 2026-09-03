"""Reporting a bug: gather the useful facts, redact the private ones, send nothing.

podHarvest's whole promise is that your listening stays on your machine, so a
bug report cannot be a thing that quietly uploads. This module builds the
report and hands it to you. **Nothing here touches the network.** You read it,
then you decide: copy it, save it, or open a pre-filled email. If you close the
window, nothing happened.

What goes in is what actually gets a bug fixed, and no more:

* the version, and what podHarvest is running on;
* whether FFmpeg is there, because half of the quiet failures are that;
* the hardware summary, because "it is slow" usually means "this machine";
* which settings differ from the defaults -- the whole settings file would be
  noise, and would carry paths nobody needs;
* the recent activity log, which is the single most useful thing in the report.

What comes out is redacted first, following the same shapes QUILL scrubs from
its diagnostic bundles (`quill/stability/redaction.py`): API keys, tokens,
anything that looks like a secret assignment, home-directory paths, and email
addresses. That is belt and braces -- keys are in the OS credential vault and
should never reach a log -- but a bug report is exactly where a stray one would
escape, and the cost of checking is nothing.
"""

from __future__ import annotations

import platform
import re
import sys
from dataclasses import fields
from pathlib import Path

from podharvest import DISPLAY_NAME, SUPPORT_EMAIL, __version__

#: Assignments whose value is a secret, whatever it looks like.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([\w.\-]*(?:key|token|secret|password|passwd|pwd|auth|bearer)[\w.\-]*)"
    r"(\s*[:=]\s*)(\S+)"
)
#: A long hex or base64-ish run: the shape of a key that was pasted bare.
_BARE_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
#: Provider key prefixes, which are recognisable and worth catching by name.
_PREFIXED_KEY = re.compile(r"\b(sk|pk|rk|hf|xai|gsk|api)[-_][A-Za-z0-9_\-]{16,}\b")
#: A home directory, which names the person using the machine.
_HOME_PATH = re.compile(
    r"(?i)\b(?:[A-Z]:\\Users\\|/home/|/Users/)[^\\/\s\"']+", re.UNICODE
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

#: How much of the log to include. Enough to see what led up to the problem,
#: little enough to paste into an email.
LOG_TAIL_LINES = 200


def redact(text: str) -> str:
    """Remove what should never leave the machine, from anywhere in *text*.

    Order matters: named assignments first, so ``api_key = abc`` is caught by
    its name rather than having to look like a key; then the shapes that give a
    secret away on their own.
    """
    if not text:
        return ""
    out = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}[removed]", text)
    out = _PREFIXED_KEY.sub("[removed]", out)
    out = _BARE_TOKEN.sub("[removed]", out)
    out = _HOME_PATH.sub(lambda m: m.group(0).rsplit("\\", 1)[0].rsplit("/", 1)[0]
                         + ("\\" if "\\" in m.group(0) else "/") + "[you]", out)
    return _EMAIL.sub("[email removed]", out)


def _changed_settings(settings) -> list[str]:
    """Only the settings that differ from the defaults.

    The whole file would be noise, and would carry the output path, which names
    a person as often as not. What matters is what somebody changed.
    """
    try:
        defaults = type(settings)()
    except Exception:  # noqa: BLE001 - a settings type that will not construct
        return []
    rows: list[str] = []
    for field in fields(settings):
        name = field.name
        if any(word in name for word in ("token", "key", "secret")):
            continue  # never reported, changed or not
        current = getattr(settings, name, None)
        if current != getattr(defaults, name, None):
            rows.append(f"  {name} = {current!r}")
    return rows


def _log_tail(log_path: Path | None, lines: int = LOG_TAIL_LINES) -> str:
    if log_path is None or not Path(log_path).is_file():
        return "(no log file was being written)"
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read the log: {exc})"
    tail = text.splitlines()[-lines:]
    return "\n".join(tail) if tail else "(the log is empty)"


def build_report(
    *,
    settings=None,
    hardware_summary: str = "",
    log_text: str = "",
    log_path: Path | None = None,
    what_happened: str = "",
) -> str:
    """The report, ready to read. Redacted. Never sent anywhere by this call."""
    from podharvest import media_health

    health = media_health.check()
    changed = _changed_settings(settings) if settings is not None else []
    body = log_text.strip() or _log_tail(log_path)

    sections = [
        f"{DISPLAY_NAME} {__version__} -- bug report",
        "",
        "What happened",
        "-------------",
        (what_happened.strip() or "(describe what you did and what you expected)"),
        "",
        "This machine",
        "------------",
        f"  podHarvest : {__version__}",
        f"  Python     : {sys.version.split()[0]}",
        f"  Platform   : {platform.platform()}",
        f"  FFmpeg     : {'found' if health.ffmpeg else 'NOT FOUND'}",
        f"  Hardware   : {hardware_summary or '(not probed)'}",
        "",
        "Settings that differ from the defaults",
        "--------------------------------------",
        ("\n".join(changed) if changed else "  (all defaults)"),
        "",
        f"Activity log (last {LOG_TAIL_LINES} lines)",
        "-" * 40,
        body,
    ]
    return redact("\n".join(sections))


def mailto_url(report: str) -> str:
    """A ``mailto:`` for the support address, with a short body.

    Deliberately short: every mail client truncates a long ``mailto`` body, and
    a report that arrives cut in half is worse than one the person pasted in
    themselves. The full text goes to the clipboard, and the body says so.
    """
    from urllib.parse import quote

    subject = quote(f"{DISPLAY_NAME} {__version__} bug report")
    body = quote(
        "The full report is on my clipboard -- paste it below this line.\n"
        "\n"
        "----------------------------------------\n"
        + report.split("Activity log")[0].strip()[:900]
    )
    return f"mailto:{SUPPORT_EMAIL}?subject={subject}&body={body}"
