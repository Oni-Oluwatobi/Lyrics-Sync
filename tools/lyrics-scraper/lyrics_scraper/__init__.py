"""Gospel lyrics database builder (multi-source) — development tool only.

This package is intentionally standalone: it is never imported by the Lyric Sync
application, and it never writes to the production ``lyric_sync_gospel.lsdb``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
