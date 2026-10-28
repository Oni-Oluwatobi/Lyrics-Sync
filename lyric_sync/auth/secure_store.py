"""DPAPI-protected storage for the Firebase session file.

Only tokens and the email are stored — never the password.  On Windows the
payload is encrypted with the Data Protection API (tied to the current
user account).  If DPAPI is unavailable the JSON is written unencrypted as
a last resort (still no password), because silently losing the session is
worse than storing tokens at rest.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
from pathlib import Path

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, description: str) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        ctypes.c_wchar_p(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect(data: bytes, description: str) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class SecureStore:
    """Atomic, DPAPI-protected JSON session store."""

    def __init__(self, path: Path, description: str = "Lyric Sync account session") -> None:
        self.path = path
        self.description = description

    def save(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        try:
            blob = _protect(raw, self.description)
        except OSError:
            blob = raw
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "wb",
            dir=str(self.path.parent),
            prefix=self.path.name,
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
        except OSError:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise

    def load(self) -> dict | None:
        try:
            blob = self.path.read_bytes()
        except OSError:
            return None
        try:
            raw = _unprotect(blob, self.description)
        except OSError:
            raw = blob  # stored without DPAPI (fallback write)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass
