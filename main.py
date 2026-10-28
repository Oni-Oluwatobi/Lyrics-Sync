"""Lyric Sync entry point (run with ``python main.py``)."""

from __future__ import annotations

import sys

from lyric_sync.app.application import run

if __name__ == "__main__":
    if "--self-check" in sys.argv:
        from lyric_sync.app.self_check import run_self_check

        sys.exit(run_self_check())
    sys.exit(run())
