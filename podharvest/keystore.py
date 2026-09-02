"""Storage for cloud provider API keys.

Keys are secrets and never belong in `settings.json`, which is plain JSON that
gets copied around, pasted into bug reports and synced to backup folders. They
are kept out of it entirely.

Lookup order, highest priority first:

1. An environment variable - `PODHARVEST_OPENAI_KEY`, `PODHARVEST_GEMINI_KEY`,
   and so on. This is how a CI job or a shared machine supplies a key without
   writing it to disk at all, so nothing here ever overwrites one.
2. `keys.enc` in the app space's config folder. On Windows the values are
   encrypted with DPAPI, scoped to the current user account - the file is
   useless if copied to another machine or read by another user. On macOS the
   login Keychain is used instead.
3. Nothing. A missing key is not an error; it means that provider is not
   configured, and the app says so plainly rather than failing later inside an
   HTTP call.

On Linux and other platforms there is no store the standard library can reach
securely, so keys are accepted for the current session only and a warning
explains that they will not persist. That is a deliberate refusal to write
plaintext secrets to disk while implying they are protected.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from podharvest.util import LOG

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

#: Fixed, non-secret. DPAPI already scopes the blob to the current user account;
#: this adds domain separation, nothing more. Changing it would make every
#: already-stored key undecryptable.
_ENTROPY = b"podharvest-keys-v1"

#: Session-only fallback for platforms with no secure store.
_MEMORY: dict[str, str] = {}


def env_var_for(provider: str) -> str:
    """The environment variable that overrides the stored key for `provider`."""
    return f"PODHARVEST_{provider.upper().replace('-', '_')}_KEY"


# -- Windows DPAPI -----------------------------------------------------------

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    #: Never raise an interactive DPAPI prompt from a background thread.
    _UI_FORBIDDEN = 0x1


def _blob(payload: bytes):
    buf = ctypes.create_string_buffer(payload)
    return _Blob(cbData=len(payload), pbData=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _dpapi(func, data: bytes) -> bytes:
    in_blob, in_buf = _blob(data)
    ent_blob, ent_buf = _blob(_ENTROPY)
    out = _Blob()
    try:
        _ = in_buf, ent_buf          # keep the buffers alive across the call
        ok = func(ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None,
                  _UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            raise OSError(ctypes.get_last_error(), f"{func.__name__} failed")
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        if out.pbData:
            _kernel32.LocalFree(out.pbData)


def _encrypt(secret: str) -> str:
    return base64.b64encode(_dpapi(_crypt32.CryptProtectData, secret.encode("utf-8"))).decode("ascii")


def _decrypt(encoded: str) -> str:
    return _dpapi(_crypt32.CryptUnprotectData, base64.b64decode(encoded)).decode("utf-8")


# -- macOS Keychain ----------------------------------------------------------

def _keychain(args: list[str], *, input_text: str | None = None) -> str:
    import subprocess
    proc = subprocess.run(["security", *args], capture_output=True, text=True,
                          input=input_text)
    return proc.stdout.strip() if proc.returncode == 0 else ""


# -- the file ----------------------------------------------------------------

def _store_path(app) -> Path:
    return Path(app.config_dir) / "keys.enc"


def _read_store(app) -> dict[str, str]:
    path = _store_path(app)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        LOG.warning("Could not read the saved API keys (%s). Add them again in Settings.", exc)
        return {}


def _write_store(app, store: dict[str, str]) -> None:
    path = _store_path(app)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        if not _IS_WINDOWS:
            os.chmod(path, 0o600)
    except OSError as exc:
        LOG.error("Could not save the API key: %s", exc)


# -- public API --------------------------------------------------------------

def load_key(app, provider: str) -> str:
    """Return the API key for `provider`, or "" when none is configured."""
    from_env = os.environ.get(env_var_for(provider), "").strip()
    if from_env:
        return from_env
    if provider in _MEMORY:
        return _MEMORY[provider]
    if _IS_WINDOWS:
        stored = _read_store(app).get(provider, "")
        if not stored:
            return ""
        try:
            return _decrypt(stored).strip()
        except OSError:
            LOG.warning("The saved %s key could not be decrypted. That happens when the "
                        "keys file was copied from another machine or user account. "
                        "Enter the key again in Settings.", provider)
            return ""
    if _IS_MACOS:
        return _keychain(["find-generic-password", "-s", f"podharvest-{provider}", "-w"])
    return ""


def save_key(app, provider: str, key: str) -> None:
    """Store `key` for `provider`. An empty key removes it."""
    key = key.strip()
    if os.environ.get(env_var_for(provider), "").strip():
        LOG.info("%s is set from the environment variable %s, so the key you entered was "
                 "not saved. Unset that variable to manage the key here instead.",
                 provider, env_var_for(provider))
        return

    if _IS_WINDOWS:
        store = _read_store(app)
        if key:
            try:
                store[provider] = _encrypt(key)
            except OSError as exc:
                LOG.error("Windows refused to encrypt the key (%s); it was not saved.", exc)
                return
        else:
            store.pop(provider, None)
        _write_store(app, store)
        return

    if _IS_MACOS:
        service = f"podharvest-{provider}"
        if key:
            _keychain(["add-generic-password", "-U", "-s", service, "-a", "podharvest", "-w", key])
        else:
            _keychain(["delete-generic-password", "-s", service])
        return

    # Nowhere safe to write it: keep it for this session and be honest.
    if key:
        _MEMORY[provider] = key
        LOG.warning("This platform has no secure key store that podharvest can use, so the "
                    "%s key is kept for this session only. Set %s in your environment to "
                    "have it available every time.", provider, env_var_for(provider))
    else:
        _MEMORY.pop(provider, None)


def delete_key(app, provider: str) -> None:
    save_key(app, provider, "")


def configured_providers(app, providers) -> dict[str, bool]:
    """Map each provider name to whether a key is available for it."""
    return {name: bool(load_key(app, name)) for name in providers}


def redact(text: str) -> str:
    """Blank out anything key-shaped so it is safe to log.

    Belt and braces: keys should never reach a log line in the first place, but
    a provider error message can quote the request it rejected.
    """
    import re
    return re.sub(r"\b(sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}|[A-Fa-f0-9]{32}\.[A-Za-z0-9]{16,})",
                  "[key hidden]", text or "")
