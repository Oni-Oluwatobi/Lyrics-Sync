"""Package entry point (``python -m lyric_sync.main``)."""

from __future__ import annotations

import sys

from lyric_sync.app.application import run

if __name__ == "__main__":
    sys.exit(run())
