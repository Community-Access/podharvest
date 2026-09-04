"""Authenticode code signing for podharvest's Windows builds.

Signing goes through **Azure Trusted Signing**: there is no PFX and no private
key on this machine. ``signtool.exe`` loads a Microsoft-supplied signing
library (``Azure.CodeSigning.Dlib.dll``), which submits a digest to the
account's ``codesigning.azure.net`` endpoint and receives a short-lived
certificate in return. Authentication is the ambient Azure credential -- an
``az login`` session on a workstation, a workload identity in CI.

The account and certificate profile live in ``installer/signing-metadata.json``
so a build has no secrets to carry. Nothing in that file is sensitive: it names
an endpoint and a profile, and access is decided by the Azure credential.

Why any of this matters here: Windows SmartScreen warns on unsigned installers,
and that warning is at its least helpful when read aloud. podharvest's audience
is screen reader users, so a public release is signed.

The approach and most of the hard-won details are shared with QUILL's
``scripts/code_signing.py``; this is the smaller version podharvest needs.

Design rules:

* **Opt-in.** Nothing signs unless asked. A contributor's build never needs a
  credential, and produces a byte-for-byte ordinary binary.
* **Fail loudly when asked to sign.** A signing step that quietly does nothing
  is worse than no signing: the release looks finished and every user still
  meets SmartScreen. Requested signing that cannot proceed is an error.
* **No shell.** ``signtool`` is invoked with an argv list. Passing ``/fd``-style
  switches through a shell (Git Bash especially) mangles them into paths and
  produces the misleading "No file digest algorithm specified".

Run it::

    python scripts/code_signing.py doctor              # is this machine ready?
    python scripts/code_signing.py sign a.exe b.dll    # sign named files
    python scripts/code_signing.py sign-tree dist\\podharvest
    python scripts/code_signing.py verify a.exe
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

#: Which signing account and certificate profile to use. Overridable with
#: PODHARVEST_SIGN_METADATA for a different profile or a CI-supplied one.
DEFAULT_METADATA = _ROOT / "installer" / "signing-metadata.json"

#: Microsoft's timestamp authority for Trusted Signing. Timestamping is not
#: optional in practice: a Trusted Signing certificate lives for a few days, so
#: an untimestamped signature is invalid almost immediately.
DEFAULT_TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"

#: The signing library, pinned by version and verified by hash. It is loaded
#: into signtool and speaks to the signing service on our behalf, so it gets
#: the same treatment as any other build input: exactly this build, or fail.
CLIENT_VERSION = "1.0.95"
CLIENT_URL = (
    "https://api.nuget.org/v3-flatcontainer/microsoft.trusted.signing.client/"
    f"{CLIENT_VERSION}/microsoft.trusted.signing.client.{CLIENT_VERSION}.nupkg"
)
CLIENT_SHA256 = "3bfcf1e0a3cb42af1692f0a8ed45c15de070c2de86f28a59b2795d904d8a920f"

#: What a tree-sign covers. Authenticode applies to PE images; podharvest's
#: bundle ships CPython extension modules as .pyd, and a bundle where only the
#: launcher is signed still loads unsigned code beside it.
DEFAULT_PATTERNS = ("*.exe", "*.dll", "*.pyd")


class SigningError(RuntimeError):
    """A signing or verification step could not be completed."""


@dataclass(frozen=True)
class SigningConfig:
    """Everything one signtool invocation needs, resolved once per build."""

    signtool: Path
    dlib: Path
    metadata: Path
    timestamp_url: str = DEFAULT_TIMESTAMP_URL


# -- finding the tools --------------------------------------------------------


def metadata_path() -> Path:
    override = os.environ.get("PODHARVEST_SIGN_METADATA", "").strip()
    return Path(override) if override else DEFAULT_METADATA


def deps_root() -> Path:
    """Where the signing library is staged. Build output, never shipped."""
    return _ROOT / "build" / "deps" / "trusted-signing"


def _version_key(name: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in name.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def find_signtool() -> Path | None:
    """Locate signtool.exe, preferring the newest Windows SDK installed.

    The SDK layout is ``Windows Kits\\10\\bin\\<version>\\x64\\signtool.exe``,
    and several versions sit side by side, so there is no fixed path to use.
    """
    roots: list[Path] = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        value = os.environ.get(var, "").strip()
        if value:
            roots.append(Path(value) / "Windows Kits" / "10" / "bin")
    best: tuple[tuple[int, ...], Path] | None = None
    for kits_bin in roots:
        if not kits_bin.is_dir():
            continue
        for version_dir in kits_bin.iterdir():
            candidate = version_dir / "x64" / "signtool.exe"
            if candidate.is_file():
                key = _version_key(version_dir.name)
                if best is None or key > best[0]:
                    best = (key, candidate)
    if best is not None:
        return best[1]
    found = shutil.which("signtool") or shutil.which("signtool.exe")
    return Path(found) if found else None


def _dlib_path() -> Path:
    return deps_root() / CLIENT_VERSION / "bin" / "x64" / "Azure.CodeSigning.Dlib.dll"


def ensure_dlib(*, force: bool = False) -> Path:
    """Stage the signing library, downloading and verifying it if needed."""
    dlib = _dlib_path()
    if dlib.is_file() and not force:
        return dlib
    cache = deps_root()
    nupkg = cache / f"microsoft.trusted.signing.client.{CLIENT_VERSION}.nupkg"
    _download_verified(CLIENT_URL, nupkg, sha256=CLIENT_SHA256)
    extract_root = cache / CLIENT_VERSION
    if extract_root.exists():
        shutil.rmtree(extract_root)
    with zipfile.ZipFile(nupkg) as archive:
        # Only the bin/ tree is wanted; the package also carries docs, a
        # nuspec, and libraries for architectures this build never loads.
        for member in archive.namelist():
            normalized = member.replace("\\", "/")
            if normalized.startswith("bin/") and not normalized.endswith("/"):
                archive.extract(member, extract_root)
    if not dlib.is_file():
        raise SigningError(
            f"Azure.CodeSigning.Dlib.dll was not in {nupkg} after extraction."
        )
    return dlib


def _download_verified(url: str, dest: Path, *, sha256: str) -> None:
    """Fetch *url* to *dest*, refusing anything whose hash does not match."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, tmp.open("wb") as handle:  # noqa: S310
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            hasher.update(block)
            handle.write(block)
    actual = hasher.hexdigest()
    if actual != sha256:
        tmp.unlink(missing_ok=True)
        raise SigningError(
            f"SHA-256 mismatch for {url}\n  expected {sha256}\n  got      {actual}"
        )
    tmp.replace(dest)


def azure_credential_available() -> bool:
    """Best-effort check for an Azure login, to sharpen error messages.

    Never authoritative -- CI can hold a workload identity the CLI cannot see --
    so it only ever adds a hint, and never blocks a signing attempt.
    """
    az = shutil.which("az")
    if not az:
        return False
    try:
        result = subprocess.run(
            [az, "account", "show", "--output", "none"],
            capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def resolve_config(*, timestamp_url: str = DEFAULT_TIMESTAMP_URL) -> SigningConfig:
    """Everything needed to sign, or an error saying exactly what is missing."""
    signtool = find_signtool()
    if signtool is None:
        raise SigningError(
            "signtool.exe not found. Install the Windows 10/11 SDK's Signing "
            "Tools, or put signtool.exe on PATH.")
    meta = metadata_path()
    if not meta.is_file():
        raise SigningError(
            f"Signing metadata not found at {meta}. It names the Trusted "
            "Signing endpoint, account and certificate profile.")
    return SigningConfig(
        signtool=signtool, dlib=ensure_dlib(), metadata=meta,
        timestamp_url=timestamp_url)


# -- signing and verifying ----------------------------------------------------


def collect_files(root: Path,
                  patterns: Sequence[str] = DEFAULT_PATTERNS) -> list[Path]:
    """Every file under *root* matching *patterns*, sorted and deduplicated."""
    found: set[Path] = set()
    for pattern in patterns:
        found.update(p for p in Path(root).rglob(pattern) if p.is_file())
    return sorted(found)


def sign_files(files: Iterable[Path], config: SigningConfig,
               *, batch: int = 50) -> list[Path]:
    """Sign each file, in batches. Raises rather than partially succeeding.

    signtool takes many files per call, and each still costs one round trip to
    the signing service inside the library; batching only saves process
    startup, but it also keeps the command line from growing without bound.
    """
    resolved = [Path(f) for f in files]
    missing = [f for f in resolved if not f.is_file()]
    if missing:
        raise SigningError(
            "Cannot sign files that are not there: "
            + ", ".join(str(m) for m in missing))
    if not resolved:
        return []
    for start in range(0, len(resolved), batch):
        chunk = resolved[start:start + batch]
        command = [
            str(config.signtool), "sign",
            "/fd", "SHA256",
            "/tr", config.timestamp_url,
            "/td", "SHA256",
            "/dlib", str(config.dlib),
            "/dmdf", str(config.metadata),
            *(str(f) for f in chunk),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            hint = ""
            if not azure_credential_available():
                hint = "\nNo Azure credential found -- run `az login`."
            raise SigningError(
                f"signtool sign failed (exit {result.returncode})."
                f"{hint}\n{_tail(result.stdout)}\n{_tail(result.stderr)}")
    return resolved


def verify_files(files: Iterable[Path]) -> list[tuple[Path, bool]]:
    """Check each file's embedded signature the way Windows itself would.

    ``/pa`` selects the Default Authentication Policy -- the policy SmartScreen
    and the elevation prompt apply -- rather than the driver-signing policy.
    """
    signtool = find_signtool()
    if signtool is None:
        raise SigningError("signtool.exe not found; cannot verify.")
    results: list[tuple[Path, bool]] = []
    for raw in files:
        path = Path(raw)
        outcome = subprocess.run(
            [str(signtool), "verify", "/pa", str(path)],
            capture_output=True, text=True, check=False)
        results.append((path, outcome.returncode == 0))
    return results


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


# -- command line -------------------------------------------------------------


def _cmd_doctor(_args) -> int:
    signtool = find_signtool()
    meta = metadata_path()
    dlib = _dlib_path()
    print("Authenticode signing, via Azure Trusted Signing:")
    print(f"  signtool.exe  : {signtool or 'NOT FOUND -- install the Windows SDK'}")
    print(f"  metadata      : {meta} {'OK' if meta.is_file() else 'MISSING'}")
    print(f"  signing dlib  : {dlib if dlib.is_file() else 'not staged yet (staged on first sign)'}")
    print(f"  Azure login   : {'present' if azure_credential_available() else 'not found -- run az login'}")
    ready = bool(signtool) and meta.is_file()
    print("Ready to sign." if ready else "Not ready: see the items above.")
    return 0 if ready else 1


def _cmd_sign(args) -> int:
    config = resolve_config()
    signed = sign_files([Path(p) for p in args.paths], config)
    print(f"Signed {len(signed)} file(s).")
    return 0


def _cmd_sign_tree(args) -> int:
    config = resolve_config()
    patterns = tuple(args.pattern) if args.pattern else DEFAULT_PATTERNS
    files = collect_files(Path(args.root), patterns)
    if not files:
        raise SigningError(f"Nothing matching {', '.join(patterns)} under {args.root}.")
    signed = sign_files(files, config)
    print(f"Signed {len(signed)} file(s) under {args.root}.")
    return 0


def _cmd_verify(args) -> int:
    results = verify_files(Path(p) for p in args.paths)
    for path, good in results:
        print(f"{'valid  ' if good else 'INVALID'}: {path}")
    return 0 if all(good for _path, good in results) else 1


def _cmd_verify_tree(args) -> int:
    files = collect_files(Path(args.root), tuple(args.pattern) if args.pattern
                          else DEFAULT_PATTERNS)
    results = verify_files(files)
    bad = [path for path, good in results if not good]
    print(f"Checked {len(results)} file(s); {len(bad)} unsigned or invalid.")
    for path in bad[:20]:
        print(f"  INVALID: {path}")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/code_signing.py",
        description="Authenticode signing through Azure Trusted Signing.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Report whether this machine can sign.")

    p_sign = sub.add_parser("sign", help="Sign the named files.")
    p_sign.add_argument("paths", nargs="+")

    p_tree = sub.add_parser("sign-tree", help="Sign every binary under a folder.")
    p_tree.add_argument("root")
    p_tree.add_argument("--pattern", action="append",
                        help="Glob to sign; repeatable. Default *.exe, *.dll, *.pyd.")

    p_verify = sub.add_parser("verify", help="Verify the named files' signatures.")
    p_verify.add_argument("paths", nargs="+")

    p_vtree = sub.add_parser("verify-tree", help="Verify every binary under a folder.")
    p_vtree.add_argument("root")
    p_vtree.add_argument("--pattern", action="append")

    args = parser.parse_args(argv)
    handlers = {
        "doctor": _cmd_doctor, "sign": _cmd_sign, "sign-tree": _cmd_sign_tree,
        "verify": _cmd_verify, "verify-tree": _cmd_verify_tree,
    }
    try:
        return handlers[args.command](args)
    except SigningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
