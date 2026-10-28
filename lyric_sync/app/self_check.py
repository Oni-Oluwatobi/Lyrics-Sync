"""Packaged-build self check (``--self-check``).

Run from a packaged build (``LyricSync.exe --self-check`` on Windows,
``LyricSync.app/Contents/MacOS/LyricSync --self-check`` on macOS) or from
source (``python main.py --self-check``).

Verifies that the built application can resolve the database, load the
downloaded search engine and run one real search. The outcome is written to
``self_check.txt`` in the user-data directory (windowed builds have no
console) and the exit code reports success.
"""

from __future__ import annotations

from pathlib import Path

from lyric_sync.app import config
from lyric_sync.app.dev_log import log_event
from lyric_sync.search import engine_loader
from lyric_sync.search.lyric_search_service import LyricSearchService, ServiceError


def run_self_check(destination: Path | None = None) -> int:
    lines: list[str] = []
    ok = False

    path, source = config.resolve_database_path()
    exists = path.is_file()
    lines.append(f"database: {path}")
    lines.append(f"database exists: {exists} (candidate: {source})")

    engine_file = engine_loader.find_engine_file()
    lines.append(f"engine: {engine_file}")

    if not exists:
        lines.append("error: database not found")
    elif engine_file is None:
        lines.append("error: search_engine.py not found")
    else:
        service = LyricSearchService(sensitivity="balanced")
        try:
            service.open(path)
            response = service.search("Way Maker")
            top = response.results[0].song.title if response.results else "<none>"
            lines.append(
                f"songs: {service.song_count}; results: {len(response.results)}; "
                f"top: {top}; elapsed_ms: {response.elapsed_ms:.0f}"
            )
            ok = bool(response.results)
            if not ok:
                lines.append("error: search returned no results")
        except ServiceError as exc:
            lines.append(f"error: {exc.user_message} — {exc.detail}")
            log_event("self-check", f"{exc.user_message} — {exc.detail}")
        except Exception as exc:  # noqa: BLE001 - self check must report anything
            lines.append(f"error: {exc.__class__.__name__}: {exc}")
            log_event("self-check", "unexpected failure", exc)
        finally:
            service.close()

    lines.append(f"result: {'OK' if ok else 'FAILED'}")
    target = destination or (config.user_data_dir() / "self_check.txt")
    try:
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        target = Path.cwd() / "self_check.txt"
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        print(f"self check written to {target}")
    except Exception:  # noqa: BLE001 - windowed builds may have no stdout
        pass
    return 0 if ok else 1
