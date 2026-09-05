"""Where the large things live, and moving them without losing them.

Models, the engines installed on demand, and the caches are the parts of
podHarvest that grow without bound -- gigabytes, on whichever drive the
user profile happens to sit on, which is often the one with least room.
This is what lets somebody put them somewhere else.

Two rules shape it.

**Settings and logs do not move.** A settings file that moves is a settings
file you can lose, and the log has to be readable when the thing you are
reporting is that the other folder is broken. Only `AppSpace.DATA_FOLDERS`
travel.

**A move copies before it deletes.** Half a gigabyte of models is not worth
risking to save a few seconds, and an interrupted `shutil.move` across
drives can leave a partial file that looks complete. Everything is copied,
verified to exist at the far end, and only then removed -- so an
interruption at any point leaves the old copy intact and podHarvest still
working from it.

Nothing here touches wx, so it can be tested without a display.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from podharvest.util import LOG

#: Headroom demanded on the destination beyond the bytes being moved.
#: A drive filled to the last byte by a model move is a drive that cannot
#: then write a transcript.
FREE_SPACE_MARGIN = 1.15


@dataclass(frozen=True)
class FolderSize:
    """One data folder and what it costs."""

    name: str
    bytes: int

    def spoken(self) -> str:
        return f"{self.name}: {human_size(self.bytes)}"


def human_size(count: int) -> str:
    """A size as it should be read aloud, not as a raw number."""
    step = float(max(0, count))
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if step < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(step)} bytes"
            return f"{step:.1f} {unit}"
        step /= 1024
    return f"{step:.1f} TB"


def folder_bytes(path: Path) -> int:
    """How large a folder is, ignoring anything unreadable.

    A permission error on one file must not stop the total being reported:
    a slightly low number is far more useful than an exception.
    """
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def measure(app) -> list[FolderSize]:
    """Each movable folder and its size, largest first."""
    sizes = [FolderSize(name, folder_bytes(app.data / name))
             for name in app.DATA_FOLDERS]
    return sorted(sizes, key=lambda s: -s.bytes)


def total_bytes(app) -> int:
    return sum(size.bytes for size in measure(app))


def free_bytes(path: Path) -> int:
    """Free space on the drive holding *path*, walking up if it is new.

    A folder the user has just typed may not exist yet, and its drive still
    has to be measurable to say whether the move can succeed.
    """
    probe = Path(path)
    while True:
        try:
            return shutil.disk_usage(str(probe)).free
        except OSError:
            if probe.parent == probe:
                return 0
            probe = probe.parent


def same_drive(one: Path, other: Path) -> bool:
    try:
        return Path(one).resolve().drive.lower() == Path(other).resolve().drive.lower()
    except (OSError, ValueError):
        return False


def check_move(app, destination: Path) -> tuple[bool, str]:
    """Whether the data can move to *destination*, and what to say either way.

    Returns (ok, sentence). The sentence is shown whichever way it goes,
    because "why not?" is the immediate question when a button is refused.
    """
    destination = Path(destination)
    source = app.data
    try:
        if destination.resolve() == source.resolve():
            return False, "That is where the data already is."
    except OSError:
        pass
    # Moving into a subfolder of the source would copy the copy.
    try:
        if source.resolve() in destination.resolve().parents:
            return False, ("That folder is inside the current one. Choose a "
                           "folder somewhere else.")
    except OSError:
        pass
    if destination.exists() and not destination.is_dir():
        return False, "That is a file, not a folder."
    needed = total_bytes(app)
    room = free_bytes(destination)
    if room < needed * FREE_SPACE_MARGIN:
        return False, (
            f"Not enough room. Moving needs about {human_size(needed)} and "
            f"that drive has {human_size(room)} free.")
    where = "the same drive" if same_drive(source, destination) else "another drive"
    return True, (
        f"Ready to move {human_size(needed)} to {where}. Nothing is deleted "
        "until every file has arrived.")


def move_data(app, destination: Path,
              on_progress: Callable[[str], None] | None = None) -> Path:
    """Move the data folders to *destination*. Returns the new data root.

    Copies everything first, checks it arrived, and only then removes the
    originals. An interruption at any point therefore leaves the old copy
    intact and podHarvest still able to run from it -- which matters more
    than the disk space a half-finished move leaves behind.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    source = app.data

    def say(text: str) -> None:
        LOG.info("%s", text)
        if on_progress is not None:
            on_progress(text)

    moved: list[Path] = []
    for name in app.DATA_FOLDERS:
        origin = source / name
        if not origin.exists():
            continue
        target = destination / name
        say(f"Copying {name} ({human_size(folder_bytes(origin))})...")
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(origin, target, dirs_exist_ok=True)
        if not target.exists():
            raise OSError(f"{name} did not arrive at {target}.")
        moved.append(origin)
        say(f"{name} copied.")

    for origin in moved:
        say(f"Removing the old {origin.name}...")
        shutil.rmtree(origin, ignore_errors=True)
    say("Done. podHarvest will use the new folder from now on.")
    return destination
