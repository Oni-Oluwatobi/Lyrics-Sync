"""Append-only developer log.

Detailed failures (tracebacks, SQL messages, import errors) are written here so
the interface can stay friendly without hiding information from developers.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from lyric_sync.app import config

LOG_FILENAME = "developer.log"


def dev_log_path() -> Path:
    return config.user_data_dir() / LOG_FILENAME


def log_event(source: str, message: str, exc: BaseException | None = None) -> Path | None:
    """Append one entry; never raises."""
    try:
        path = dev_log_path()
        stamp = datetime.now().isoformat(timespec="seconds")
        lines = [f"[{stamp}] {source}: {message}"]
        if exc is not None:
            rendered = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).rstrip()
            lines.append(rendered)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")
        return path
    except OSError:
        return None
