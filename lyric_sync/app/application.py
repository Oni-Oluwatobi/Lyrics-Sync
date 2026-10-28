"""Application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from lyric_sync import APP_NAME, DEVELOPER, VERSION
from lyric_sync.app import config
from lyric_sync.app.theme import apply_theme
from lyric_sync.storage.preferences import Preferences


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create and configure the ``QApplication`` instance."""
    args = list(sys.argv if argv is None else argv)
    app = QApplication(args)
    app.setApplicationName(config.APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(DEVELOPER)
    app.setApplicationVersion(VERSION)
    app.setDesktopFileName("lyricsync")

    font = QFont("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)

    preferences = Preferences.load(config.preferences_path())
    apply_theme(app, preferences.theme)
    app.preferences = preferences  # type: ignore[attr-defined]
    return app


def run() -> int:
    """Launch Lyric Sync."""
    from lyric_sync.ui.main_window import MainWindow

    app = create_application()
    window = MainWindow()
    window.show()
    return app.exec()
