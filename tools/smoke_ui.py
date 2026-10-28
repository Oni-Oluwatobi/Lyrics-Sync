"""Offscreen smoke test for the Lyric Sync desktop UI.

Run:  python tools/smoke_ui.py [--database <path>]

Verifies that the application starts, renders every page and (optionally)
performs a real search against the local database — without a display.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402


def main(argv: list[str]) -> int:
    database = None
    if "--database" in argv:
        database = argv[argv.index("--database") + 1]

    temp_home = tempfile.mkdtemp(prefix="lyricsync-smoke-")
    os.environ["LYRIC_SYNC_USER_DATA"] = temp_home
    if database:
        os.environ["LYRIC_SYNC_DATABASE"] = str(Path(database).resolve())
    else:
        # Explicit, deliberately absent location: proves the app reports a
        # missing database instead of silently finding another copy.
        os.environ["LYRIC_SYNC_DATABASE"] = str(
            Path(temp_home) / "not_installed.lsdb"
        )

    from lyric_sync.app.application import create_application
    from lyric_sync.ui.main_window import PAGE_SEARCH, PAGE_SONG, MainWindow

    app = create_application(["lyric_sync_smoke"])
    window = MainWindow()
    window.show()

    steps: list[tuple[int, object]] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            failures.append(label)

    # 1. wait (patiently, offscreen machines can be slow) for the load task
    deadline = time.time() + 10

    def wait_for_load() -> None:
        settled = window.status_label.text() != "Loading Gospel database…"
        if settled or time.time() > deadline:
            after_load()
        else:
            QTimer.singleShot(100, wait_for_load)

    def after_load() -> None:
        check(window.pages.count() == 7, "window should host seven pages")
        check(window.pages.currentIndex() == PAGE_SEARCH, "starts on the search page")
        has_db = database is not None
        check(
            window.status_label.text() != "Loading Gospel database…",
            "database status should settle",
        )
        if has_db:
            check(window.manager is not None, "database should be open")
            check("songs" in window.status_label.text(), "status shows song count")
        else:
            check(window.manager is None, "no database installed")
            check(
                window.search_screen.is_unavailable(),
                "missing-database state shown on search",
            )

        window.show_page(PAGE_SEARCH)
        check(window.pages.currentIndex() == PAGE_SEARCH, "search page reachable")
        steps.append((1, "load"))

        if has_db:
            window._execute_search("mighty god")
            search_seq = window._request_seq
            search_deadline = time.time() + 20

            def wait_for_results() -> None:
                settled = (
                    window._request_seq == search_seq
                    and not window.search_screen.busy.isVisible()
                )
                if settled or time.time() > search_deadline:
                    after_search()
                else:
                    QTimer.singleShot(100, wait_for_results)

            QTimer.singleShot(100, wait_for_results)
        else:
            QTimer.singleShot(50, finish)

    # 2. optional search + preview + song view
    def after_search() -> None:
        rows = window.search_screen._rows
        check(len(rows) > 0, "search returned at least one result")
        check(
            bool(window.search_screen.preview_text()),
            "preview panel shows the selected result",
        )
        if rows:
            window.open_song(rows[0].song_id)
            song_deadline = time.time() + 10

            def wait_for_song() -> None:
                content = window.song_page._content
                settled = (
                    window.pages.currentIndex() == PAGE_SONG
                    and content is not None
                    and content.layout() is not None
                    and content.layout().count() > 0
                )
                if settled or time.time() > song_deadline:
                    after_song()
                else:
                    QTimer.singleShot(100, wait_for_song)

            QTimer.singleShot(100, wait_for_song)
        else:
            finish()

    def after_song() -> None:
        check(window.pages.currentIndex() == PAGE_SONG, "song page shown")
        content = window.song_page._content
        check(content is not None and content.layout().count() > 0, "song page rendered")
        window.show_page(PAGE_SEARCH)
        QTimer.singleShot(50, finish)

    def finish() -> None:
        if failures:
            print("SMOKE FAILED:")
            for item in failures:
                print(f"  - {item}")
        else:
            print("SMOKE OK")
            print(f"  pages: {window.pages.count()}")
            print(f"  status: {window.status_label.text()}")
            if database:
                print(f"  results openable: {window.search_screen.has_results()}")
        window.close()
        app.exit(1 if failures else 0)

    QTimer.singleShot(100, wait_for_load)
    QTimer.singleShot(30000, lambda: (failures.append("timed out"), finish()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
