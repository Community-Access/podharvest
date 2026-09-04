"""Finding out whether a newer podHarvest exists -- only when asked.

podHarvest has no way to tell you a new release exists, and an app you
installed once and liked deserves better than "check the website sometime".
The answer here is deliberately minimal: a Help-menu item that, when you
choose it, asks GitHub's public releases API what the newest version is and
tells you how yours compares.

**Nothing checks automatically.** No startup ping, no timer, no nagging.
Choosing the menu item is the consent, every time; the request carries no
account, no identifier and nothing about your library -- it is the same
anonymous request a web browser makes opening the releases page. That is the
line the egress rules draw, and this module stays behind it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from podharvest import __version__
from podharvest.net import HttpClient
from podharvest.util import LOG, HarvestError

#: The public releases API for this project. HTTPS only, no authentication.
LATEST_URL = ("https://api.github.com/repos/"
              "Community-Access/podharvest/releases/latest")

#: Where a person goes to actually get the new version.
RELEASES_PAGE = "https://github.com/Community-Access/podharvest/releases"


class UpdateError(HarvestError):
    """The releases API could not be read."""


@dataclass
class UpdateReport:
    """What the check found, ready to be said aloud."""

    current: str
    latest: str
    url: str

    @property
    def standing(self) -> str:
        """"newer", "same" or "older" -- how *latest* compares to current."""
        return compare(self.current, self.latest)

    def describe(self) -> str:
        if self.standing == "newer":
            return (f"Version {self.latest} is available. "
                    f"You have {self.current}.")
        if self.standing == "older":
            return (f"You have {self.current}, which is newer than the "
                    f"latest release ({self.latest}). Nothing to do.")
        return f"You have {self.current}, which is the latest release."


def _numbers(version: str) -> tuple[int, ...]:
    """The comparable part of a version: its dotted numbers.

    "v1.2.0" and "1.2" and "1.2.0-beta" all reduce to their digits; anything
    after the numbers is ignored rather than guessed about. Missing parts
    count as zero, so 1.2 == 1.2.0.
    """
    cleaned = str(version or "").strip().lstrip("vV")
    found = re.match(r"(\d+(?:\.\d+)*)", cleaned)
    if not found:
        return ()
    parts = tuple(int(piece) for piece in found.group(1).split("."))
    while parts and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def compare(current: str, latest: str) -> str:
    """How *latest* stands relative to *current*: newer, same or older.

    An unparseable version on either side is reported as "same", because
    "you should upgrade" is not a claim to make on garbage input.
    """
    ours, theirs = _numbers(current), _numbers(latest)
    if not ours or not theirs:
        return "same"
    if theirs > ours:
        return "newer"
    if theirs < ours:
        return "older"
    return "same"


def parse_release(body: bytes | str) -> tuple[str, str]:
    """The version tag and page address from a releases-API response."""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise UpdateError(f"The releases API sent something that is not "
                          f"JSON ({exc}).") from exc
    if not isinstance(data, dict):
        raise UpdateError("The releases API sent an unexpected shape.")
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        raise UpdateError("The releases API response has no version tag.")
    url = str(data.get("html_url") or RELEASES_PAGE)
    return tag, url


def check(client: HttpClient | None = None, *,
          current: str = __version__) -> UpdateReport:
    """Ask GitHub for the newest release and compare it with *current*.

    One anonymous HTTPS GET, made because the user chose the menu item.
    Raises `UpdateError` when the answer cannot be had, so the window can
    say "could not check" instead of pretending everything is current.
    """
    client = client or HttpClient()
    try:
        response = client.get(LATEST_URL)
    except Exception as exc:  # noqa: BLE001 - network errors come in many shapes
        raise UpdateError(f"Could not reach the releases page ({exc}). "
                          "Check your internet connection.") from exc
    if response.status != 200:
        raise UpdateError(f"The releases API answered with status "
                          f"{response.status}.")
    tag, url = parse_release(response.body)
    report = UpdateReport(current=current, latest=tag.lstrip("vV"), url=url)
    LOG.info("Update check: %s", report.describe())
    return report
