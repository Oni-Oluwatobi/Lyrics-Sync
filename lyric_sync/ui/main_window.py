"""Main window: header, sidebar, stacked pages, keyboard flow, orchestration."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lyric_sync import APP_NAME, DEVELOPER, VERSION
from lyric_sync.app import config
from lyric_sync.app.dev_log import log_event
from lyric_sync.app.theme import HEADER_HEIGHT, NAV_RAIL_WIDTH, apply_theme
from lyric_sync.auth.session import AuthSession
from lyric_sync.database.database_validator import ValidationReport, validate_file
from lyric_sync.database.lsdb_manager import LSDBManager
from lyric_sync.models.search_result import MatchLabel, SearchResult
from lyric_sync.search.lyric_search_service import (
    DatabaseMissingError,
    EngineUnavailableError,
    LyricSearchService,
    ServiceError,
)
from lyric_sync.search.search_engine import SearchResponse
from lyric_sync.storage.favorites import FavoritesStore
from lyric_sync.storage.preferences import Preferences
from lyric_sync.ui.about_page import AboutPage
from lyric_sync.ui.account_page import AccountPage
from lyric_sync.ui.components.widgets import glyph_icon
from lyric_sync.ui.db_info_page import DatabaseInfoPage, read_provenance
from lyric_sync.ui.library_page import LibraryPage
from lyric_sync.ui.search_screen import SearchScreen
from lyric_sync.ui.settings_page import SettingsPage
from lyric_sync.ui.song_page import SongPage
from lyric_sync.ui.workers import run_task

PAGE_SEARCH = 0
PAGE_SONG = 1
PAGE_LIBRARY = 2
PAGE_SETTINGS = 3
PAGE_ABOUT = 4
PAGE_DATABASE = 5
PAGE_ACCOUNT = 6

DEBOUNCE_MS = 300
MIN_LIVE_CHARS = 2


def _close_in_background(*resources: object) -> None:
    """Close database handles without ever blocking the calling (UI) thread.

    ``service.close_async()`` detaches immediately and serialises behind any
    in-flight search; other resources (LSDBManager) close on a daemon thread.
    """
    for resource in resources:
        if resource is None:
            continue
        close_async = getattr(resource, "close_async", None)
        if close_async is not None:
            close_async()
            continue

        def closer(resource=resource) -> None:
            try:
                resource.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass

        threading.Thread(
            target=closer, name="lyric-sync-close", daemon=True
        ).start()


class MainWindow(QMainWindow):
    """Lyric Sync desktop window."""

    def __init__(self) -> None:
        super().__init__()
        self.preferences = Preferences.load(config.preferences_path())
        self.favorites = FavoritesStore(config.favorites_path())
        self.manager: LSDBManager | None = None
        self.service = LyricSearchService(sensitivity=self.preferences.sensitivity)
        self.auth = AuthSession(parent=self)
        self._request_seq = 0
        self._favorites_seq = 0
        self._active_query = ""
        self._closing = False
        self._last_results: dict[object, SearchResult] = {}
        self._last_label: dict[object, MatchLabel] = {}
        self._last_report: ValidationReport | None = None
        self._pending_load = False
        self._search_in_flight = False
        self._validation_path: Path | None = None
        self._validation_attempts = 0

        self.setWindowTitle(f"{APP_NAME} · by {DEVELOPER}")
        self.setMinimumSize(940, 620)
        self.resize(1240, 800)

        self._build_header()
        self._build_sidebar()
        self._build_body()
        self._build_shortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._run_debounced_search)

        self._sync_settings_page()
        self.search_screen.set_sensitivity(self.preferences.sensitivity)
        self.search_screen.set_favorite_lookup(self.favorites.contains)
        self.show_page(PAGE_SEARCH)
        self.library_page.set_recents(
            self.preferences.recent_searches,
            enabled=self.preferences.search_history_enabled,
        )
        self.status_dot.setProperty("state", "missing")
        self._repolish(self.status_dot)
        self.status_label.setText("Loading Gospel database…")

        self._wire_auth()
        QTimer.singleShot(0, self.reload_database)
        QTimer.singleShot(0, self.auth.restore)

    # ------------------------------------------------------------------ setup

    def _build_header(self) -> None:
        header = QFrame()
        header.setObjectName("appHeader")
        header.setFixedHeight(HEADER_HEIGHT)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)

        brand = QLabel(APP_NAME)
        brand.setProperty("role", "brand")
        layout.addWidget(brand)

        dot = QLabel("·")
        dot.setProperty("role", "tagline")
        layout.addWidget(dot)

        tagline = QLabel("Find the song. Sing the truth.")
        tagline.setProperty("role", "tagline")
        layout.addWidget(tagline)

        layout.addStretch(1)

        developer = QLabel(DEVELOPER)
        developer.setProperty("role", "tagline")
        layout.addWidget(developer)

        self.header = header

    def _build_sidebar(self) -> None:
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setFixedWidth(NAV_RAIL_WIDTH)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 16, 0, 0)
        rail_layout.setSpacing(4)

        self.nav_search = self._nav_button("search", "Search")
        self.nav_search.clicked.connect(
            lambda: self.show_page(PAGE_SEARCH, focus=True)
        )
        rail_layout.addWidget(self.nav_search)

        self.nav_library = self._nav_button("grid", "My Library")
        self.nav_library.clicked.connect(self._open_library)
        rail_layout.addWidget(self.nav_library)

        self.nav_settings = self._nav_button("gear", "Settings")
        self.nav_settings.clicked.connect(lambda: self.show_page(PAGE_SETTINGS))
        rail_layout.addWidget(self.nav_settings)

        self.nav_about = self._nav_button("info", "About")
        self.nav_about.clicked.connect(lambda: self.show_page(PAGE_ABOUT))
        rail_layout.addWidget(self.nav_about)

        rail_layout.addStretch(1)

        # ---- footer: account row + database status + version
        footer = QFrame()
        footer.setObjectName("railFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 12, 12)
        footer_layout.setSpacing(6)

        self.account_button = QPushButton("Sign in")
        self.account_button.setProperty("variant", "rail")
        self.account_button.setCheckable(True)
        self.account_button.setCursor(Qt.PointingHandCursor)
        self.account_button.setFixedHeight(36)
        self.account_button.clicked.connect(
            lambda: self.show_page(PAGE_ACCOUNT)
        )
        footer_layout.addWidget(self.account_button)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setFixedSize(8, 8)
        status_row.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        self.status_label = QLabel("Database not installed")
        self.status_label.setProperty("role", "caption")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        footer_layout.addLayout(status_row)

        version = QLabel(f"v{VERSION}")
        version.setProperty("role", "caption")
        footer_layout.addWidget(version)
        rail_layout.addWidget(footer)

        self.rail = rail

    @staticmethod
    def _nav_button(glyph: str, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "rail")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(40)
        button._glyph = glyph  # type: ignore[attr-defined]  # kept for icon resync
        button.setIcon(glyph_icon(glyph, 16, "text_muted"))
        button.setIconSize(QSize(16, 16))
        return button

    def _sync_nav(self, index: int) -> None:
        """Reflect the current page in the sidebar, icons included.

        Icon pixmaps carry their colour (Qt cannot recolour them from the
        stylesheet), so they are repainted whenever checked state changes.
        """
        self.nav_search.setChecked(index in (PAGE_SEARCH, PAGE_SONG))
        self.nav_library.setChecked(index == PAGE_LIBRARY)
        self.nav_settings.setChecked(index in (PAGE_SETTINGS, PAGE_DATABASE))
        self.nav_about.setChecked(index == PAGE_ABOUT)
        self.account_button.setChecked(index == PAGE_ACCOUNT)
        for button in (
            self.nav_search,
            self.nav_library,
            self.nav_settings,
            self.nav_about,
        ):
            color = "accent" if button.isChecked() else "text_muted"
            button.setIcon(glyph_icon(str(button._glyph), 16, color))

    def _build_body(self) -> None:
        self.pages = QStackedWidget()
        self.pages.setObjectName("appRoot")

        self.search_screen = SearchScreen()
        self.song_page = SongPage()
        self.library_page = LibraryPage()
        self.settings_page = SettingsPage()
        self.about_page = AboutPage()
        self.db_info_page = DatabaseInfoPage()
        self.account_page = AccountPage()

        for page in (
            self.search_screen,
            self.song_page,
            self.library_page,
            self.settings_page,
            self.about_page,
            self.db_info_page,
            self.account_page,
        ):
            self.pages.addWidget(page)

        central = QWidget()
        central.setObjectName("appRoot")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.rail)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.setCentralWidget(central)

        self._wire_search()
        self._wire_song()
        self._wire_library()
        self._wire_settings()
        self._wire_db_info()
        self._wire_account_page()

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Esc"), self, activated=self._handle_escape)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self._handle_back)
        QShortcut(QKeySequence("Ctrl+,"), self,
                  activated=lambda: self.show_page(PAGE_SETTINGS))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """"/" focuses search — unless the user is typing in a text field."""
        try:
            if event.type() == QEvent.KeyPress and event.text() == "/":
                if not event.modifiers():
                    focus = QApplication.focusWidget()
                    editable = focus is not None and (
                        focus.inherits("QLineEdit")
                        or focus.inherits("QTextEdit")
                        or focus.inherits("QPlainTextEdit")
                    )
                    if not editable:
                        self._focus_search()
                        return True
        except RuntimeError:
            # Nested event dispatch can observe widgets mid-destruction.
            return False
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ wiring

    def _wire_search(self) -> None:
        self.search_screen.search_submitted.connect(self._on_submit)
        self.search_screen.query_edited.connect(self._on_query_edited)
        self.search_screen.open_song.connect(self.open_song)
        self.search_screen.sensitivity_changed.connect(self._on_sensitivity_changed)
        self.search_screen.relax_requested.connect(self._rerun_active_search)
        self.search_screen.favorite_toggled.connect(self._on_favorite_toggled)

    def _wire_song(self) -> None:
        self.song_page.back_requested.connect(self._song_back)
        self.song_page.favorite_toggled.connect(self._on_favorite_toggled)

    def _wire_library(self) -> None:
        page = self.library_page
        page.open_song.connect(self.open_song)
        page.remove_favorite.connect(self._on_remove_favorite)
        page.clear_favorites.connect(self._on_clear_favorites)
        page.search_requested.connect(self.go_home)
        page.search_selected.connect(self._on_submit)
        page.recent_removed.connect(self._on_recent_removed)
        page.clear_recents.connect(self._on_clear_recents)

    def _wire_settings(self) -> None:
        page = self.settings_page
        page.theme_changed.connect(self._on_theme_changed)
        page.sensitivity_changed.connect(self._on_sensitivity_changed)
        page.live_search_toggled.connect(self._on_live_search_toggled)
        page.history_toggled.connect(self._on_history_toggled)
        page.clear_history_requested.connect(self._on_clear_recents)
        page.open_database_info.connect(self._open_database_info)
        page.validate_database.connect(self._validate_database)
        page.reload_database.connect(self.reload_database)
        page.locate_database.connect(self._locate_database)
        page.open_about.connect(lambda: self.show_page(PAGE_ABOUT))

    def _wire_db_info(self) -> None:
        self.db_info_page.back_requested.connect(lambda: self.show_page(PAGE_SETTINGS))
        self.db_info_page.refresh_requested.connect(self._load_database_info)

    def _wire_account_page(self) -> None:
        page = self.account_page
        page.sign_in_requested.connect(self.auth.sign_in)
        page.sign_up_requested.connect(self.auth.sign_up)
        page.reset_requested.connect(self.auth.send_reset)
        page.sign_out_requested.connect(self.auth.sign_out)

    def _wire_auth(self) -> None:
        self.auth.user_changed.connect(self._on_auth_user)
        self.auth.busy_changed.connect(self.account_page.set_busy)
        self.auth.error.connect(self.account_page.set_error)
        self.auth.notice.connect(self.account_page.set_info)

    def _on_auth_user(self, user) -> None:
        email = getattr(user, "email", None) if user is not None else None
        self.account_button.setText(email or "Sign in")
        self.account_button.setToolTip(
            email if email else "Optional account sign-in (Firebase)"
        )
        self.account_page.set_user(email)

    # ------------------------------------------------------------- navigation

    def show_page(self, index: int, focus: bool = True) -> None:
        self.pages.setCurrentIndex(index)
        self._sync_nav(index)
        if index == PAGE_SEARCH and focus:
            QTimer.singleShot(0, lambda: self.search_screen.focus_input())

    def go_home(self) -> None:
        self._debounce.stop()
        # Invalidate any in-flight search so its response cannot repopulate
        # the list the user just cleared.
        self._request_seq += 1
        self._search_in_flight = False
        self.search_screen.set_busy(False)
        self.search_screen.clear()
        self.song_page.clear()
        self.show_page(PAGE_SEARCH)
        self.search_screen.focus_input()

    def _open_library(self) -> None:
        self._refresh_favorites()
        self.show_page(PAGE_LIBRARY)

    def _song_back(self) -> None:
        if self.search_screen.has_results() or self._active_query:
            self.show_page(PAGE_SEARCH, focus=False)
        else:
            self.go_home()

    def _focus_search(self) -> None:
        if self.pages.currentIndex() != PAGE_SEARCH:
            self.show_page(PAGE_SEARCH, focus=False)
        self.search_screen.focus_input()

    def _handle_back(self) -> None:
        index = self.pages.currentIndex()
        if index == PAGE_SONG:
            self._song_back()
        elif index == PAGE_DATABASE:
            self.show_page(PAGE_SETTINGS)
        elif index != PAGE_SEARCH:
            self.go_home()
        elif self.search_screen.has_results() or self._active_query:
            self.go_home()

    def _handle_escape(self) -> None:
        index = self.pages.currentIndex()
        if index == PAGE_SEARCH:
            if self.search_screen.query() or self.search_screen.has_results():
                self.go_home()
        elif index == PAGE_SONG:
            self._song_back()
        elif index == PAGE_DATABASE:
            self.show_page(PAGE_SETTINGS)
        elif index != PAGE_SEARCH:
            self.go_home()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.pages.currentIndex() == PAGE_SEARCH:
            key = event.key()
            focus = QApplication.focusWidget()
            in_input = focus is self.search_screen.search_box.input
            if not in_input and key in (Qt.Key_Down, Qt.Key_PageDown):
                self.search_screen.move_selection(1)
                event.accept()
                return
            if not in_input and key in (Qt.Key_Up, Qt.Key_PageUp):
                self.search_screen.move_selection(-1)
                event.accept()
                return
            if not in_input and key in (Qt.Key_Return, Qt.Key_Enter):
                if self.search_screen.open_selected():
                    event.accept()
                    return
        super().keyPressEvent(event)

    # ----------------------------------------------------------------- search

    def _on_submit(self, query: str) -> None:
        query = " ".join((query or "").split())
        if not query:
            self.go_home()
            return
        self._debounce.stop()
        if self.preferences.search_history_enabled and self.preferences.add_recent(query):
            self._refresh_recents()
            self.settings_page.set_recent_count(len(self.preferences.recent_searches))
        self.search_screen.set_query(query)
        self.show_page(PAGE_SEARCH, focus=False)
        self._execute_search(query)

    def _on_query_edited(self, query: str) -> None:
        """Drive the debounced live search from the single search field."""
        if not self.preferences.live_search:
            return
        if len(query.strip()) < MIN_LIVE_CHARS:
            self._debounce.stop()
            if self.pages.currentIndex() == PAGE_SEARCH and not query.strip():
                self.go_home()
            return
        self._debounce.start()

    def _run_debounced_search(self) -> None:
        query = self.search_screen.query()
        if len(query.strip()) >= MIN_LIVE_CHARS:
            self._execute_search(query)

    def _rerun_active_search(self) -> None:
        query = self._active_query or self.search_screen.query()
        if len(query.strip()) >= MIN_LIVE_CHARS:
            self._execute_search(query)

    def _execute_search(self, query: str) -> None:
        self._request_seq += 1
        seq = self._request_seq
        self._active_query = query
        self._search_in_flight = True
        self.search_screen.set_query(query)
        self.search_screen.set_busy(True)
        if self.pages.currentIndex() != PAGE_SEARCH:
            self.show_page(PAGE_SEARCH, focus=False)

        def work(q: str = query, s: int = seq) -> SearchResponse | None:
            # A newer request superseded this one before the worker started:
            # skip obsolete work instead of burning CPU on it.
            if self._closing or s != self._request_seq:
                return None
            return self.service.search(q)

        def finished(response: SearchResponse | None, s: int = seq) -> None:
            if response is None:
                # Superseded before start; the newer request owns the flag.
                if s == self._request_seq:
                    self._search_in_flight = False
                return
            self._on_search_finished(s, response)

        run_task(
            work,
            on_finished=finished,
            on_error=lambda message, s=seq: self._on_search_error(s, message),
        )

    def _on_search_finished(self, seq: int, response: SearchResponse) -> None:
        self._search_in_flight = False
        if self._closing or seq != self._request_seq:
            return
        self.search_screen.set_busy(False)
        self._last_results = {result.song.id: result for result in response.results}
        self._last_label = {result.song.id: result.label for result in response.results}
        self.search_screen.show_response(response)

    def _on_search_error(self, seq: int, message: str) -> None:
        self._search_in_flight = False
        if self._closing or seq != self._request_seq:
            return
        log_event("search", message)
        self.search_screen.set_busy(False)
        self.search_screen.show_error(
            "The search could not be completed. "
            "Details were written to the development log."
        )

    # ------------------------------------------------------------- song view

    def open_song(self, song_id: object) -> None:
        if not self.service.available:
            return
        tokens = tuple(normalize_tokens(self.search_screen.query() or self._active_query))
        label = self._last_label.get(song_id)
        self.song_page.clear()
        self.show_page(PAGE_SONG)
        service = self.service

        def load() -> tuple:
            song = service.get_song(song_id)
            lyrics = service.get_lyrics(song_id) if song is not None else None
            return song, lyrics

        def done(payload) -> None:
            if self._closing:
                return
            song, lyrics = payload
            if song is None:
                self.search_screen.show_error(
                    "That song is no longer present in the loaded database."
                )
                self.show_page(PAGE_SEARCH, focus=False)
                return
            self.song_page.show_song(
                song,
                lyrics,
                query_tokens=tokens,
                match_label=label,
                favorite=self.favorites.contains(song.id),
            )

        run_task(load, on_finished=done,
                 on_error=lambda message: self._on_song_error(message))

    def _on_song_error(self, message: str) -> None:
        if self._closing:
            return
        log_event("song", message)
        self.search_screen.show_error(
            "That song could not be opened. Details were written to the "
            "development log."
        )
        self.show_page(PAGE_SEARCH, focus=False)

    # --------------------------------------------------------------- favorites

    def _refresh_favorites(self) -> None:
        """Resolve favorite titles off the UI thread.

        ``get_songs`` takes the same service lock a search holds; running it
        on the UI thread would freeze the window for the length of an
        in-flight search.
        """
        self._favorites_seq += 1
        seq = self._favorites_seq
        service = self.service
        ids = tuple(self.favorites.song_ids)

        def work() -> list[tuple[object, str, str, bool]]:
            songs = service.get_songs(ids)
            entries: list[tuple[object, str, str, bool]] = []
            for song_id in ids:
                song = songs.get(song_id)
                if song is None:
                    entries.append((song_id, "Song not in this database",
                                    str(song_id), True))
                else:
                    entries.append((song_id, song.title, song.display_artist, False))
            return entries

        def done(entries: list[tuple[object, str, str, bool]]) -> None:
            if self._closing or seq != self._favorites_seq:
                return
            self.library_page.favorites.set_items(entries)

        run_task(work, on_finished=done,
                 on_error=lambda message: log_event("favorites", message))

    def _on_favorite_toggled(self, song_id: object, state: bool) -> None:
        if state:
            self.favorites.add(song_id)
        else:
            self.favorites.remove(song_id)
        self._refresh_favorites()

    def _on_remove_favorite(self, song_id: object) -> None:
        self.favorites.remove(song_id)
        self._refresh_favorites()

    def _on_clear_favorites(self) -> None:
        self.favorites.clear()
        self._refresh_favorites()

    # --------------------------------------------------------------- recents

    def _refresh_recents(self) -> None:
        self.library_page.set_recents(
            self.preferences.recent_searches,
            enabled=self.preferences.search_history_enabled,
        )

    def _on_history_toggled(self, enabled: bool) -> None:
        self.preferences.search_history_enabled = enabled
        self.preferences.save()
        self._refresh_recents()

    def _on_clear_recents(self) -> None:
        self.preferences.clear_recent()
        self._refresh_recents()
        self.settings_page.set_recent_count(0)

    def _on_recent_removed(self, query: str) -> None:
        self.preferences.remove_recent(query)
        self._refresh_recents()
        self.settings_page.set_recent_count(len(self.preferences.recent_searches))

    # --------------------------------------------------------------- settings

    def _sync_settings_page(self) -> None:
        page = self.settings_page
        page.set_theme(self.preferences.theme)
        page.set_history_enabled(self.preferences.search_history_enabled)
        page.set_live_search(self.preferences.live_search)
        page.set_recent_count(len(self.preferences.recent_searches))
        page.set_sensitivity(self.preferences.sensitivity)

    def _on_theme_changed(self, mode: str) -> None:
        self.preferences.theme = mode
        self.preferences.save()
        apply_theme(QApplication.instance(), mode)
        self._sync_nav(self.pages.currentIndex())

    def _on_sensitivity_changed(self, value: str) -> None:
        self.preferences.sensitivity = value
        self.preferences.save()
        self.service.sensitivity = value
        self.settings_page.set_sensitivity(value)
        self.search_screen.set_sensitivity(value)

    def _on_live_search_toggled(self, enabled: bool) -> None:
        self.preferences.live_search = enabled
        self.preferences.save()

    # --------------------------------------------------------------- database

    def reload_database(self) -> None:
        if self._pending_load:
            return
        self._pending_load = True
        self.status_label.setText("Loading Gospel database…")
        override = self.preferences.database_override
        path, source = config.resolve_database_path(override)
        sensitivity = self.preferences.sensitivity

        def load() -> tuple:
            if not path.exists():
                return ("missing", path, None, None)

            service = LyricSearchService(sensitivity=sensitivity)
            try:
                service.open(path)
            except DatabaseMissingError as exc:
                return ("missing", path, exc.detail, exc.user_message)
            except ServiceError as exc:
                log_event("database", str(exc.detail))
                return (
                    "engine" if isinstance(exc, EngineUnavailableError) else "unreadable",
                    path,
                    exc.detail,
                    exc.user_message,
                )
            except Exception as exc:  # noqa: BLE001 - never crash the loader
                log_event("database", "unexpected failure opening the database", exc)
                return (
                    "unreadable",
                    path,
                    f"{exc.__class__.__name__}: {exc}",
                    "The Gospel database could not be opened",
                )

            manager: LSDBManager | None = None
            info = None
            try:
                manager = LSDBManager(path)
                manager.open()
                # validate=False: the file validation pass takes seconds on
                # cold storage and must not delay "database ready".
                info = manager.info(deep_check=False, validate=False)
            except Exception as exc:  # noqa: BLE001 - info page is optional
                log_event("database", "database info unavailable", exc)
                if manager is not None:
                    try:
                        manager.close()
                    except Exception:  # noqa: BLE001
                        pass
                manager = None

            return ("ok", (service, manager, info, None), None, None)

        def done(payload) -> None:
            kind, first, second, third = payload
            self._pending_load = False
            if self._closing:
                # Torn down mid-load: release anything the task created.
                if kind == "ok":
                    service, manager, _info, _report = first
                    _close_in_background(service, manager)
                return
            if kind == "ok":
                service, manager, info, report = first
                old_service, old_manager = self.service, self.manager
                self.service = service
                self.manager = manager
                _close_in_background(old_service, old_manager)
                self._last_report = report
                self._defer_validation(path)
                self.status_dot.setProperty("state", "ok")
                self._repolish(self.status_dot)
                if info is not None:
                    self.status_label.setText(
                        f"{info.filename}  ·  {info.song_count:,} songs  ·  "
                        f"{info.lyric_line_count:,} lyric lines"
                    )
                    self.settings_page.set_database_status(
                        True,
                        info.filename,
                        f"{info.size_label}  ·  {info.song_count:,} songs  ·  "
                        f"FTS {'available' if info.fts_available else 'not available'}",
                    )
                    self.about_page.set_stats(
                        info.song_count,
                        info.lyric_line_count,
                        info.size_label,
                        info.filename,
                        str(getattr(info, "database_version", "") or ""),
                    )
                else:
                    name = service.path.name if service.path else path.name
                    self.status_label.setText(
                        f"{name}  ·  {service.song_count:,} songs"
                    )
                    self.settings_page.set_database_status(
                        True, name, f"{service.song_count:,} songs"
                    )
                    self.about_page.set_stats(
                        service.song_count, None, "", name, ""
                    )
                self.settings_page.set_database_path(str(path))
                self.search_screen.reset_state()
                self._refresh_favorites()
            elif kind == "missing":
                self._set_database_missing(first)
            else:
                headline = str(third) or "Gospel database unavailable"
                detail = str(second) or headline
                log_event("database", f"{headline} — {detail}")
                self._set_database_failure(headline, detail)

        run_task(load, on_finished=done,
                 on_error=lambda message: self._on_load_error(message))

    def _on_load_error(self, message: str) -> None:
        self._pending_load = False
        if self._closing:
            return
        log_event("database", message)
        self.status_label.setText("Database could not be opened")
        self.settings_page.set_database_status(
            False, "", "Problem: the database could not be loaded."
        )

    def _defer_validation(self, path: Path) -> None:
        """Queue the read-only health check; never race an active search.

        On cold storage the check streams tens of megabytes; running it while
        a first search is cold-starting can push that search past 20 s.  The
        check re-tries every few seconds until no search is busy.
        """
        self._validation_path = path
        self._validation_attempts = 0
        QTimer.singleShot(3000, self._try_validation)

    def _try_validation(self) -> None:
        if self._closing or self._validation_path is None:
            return
        if self._search_in_flight or self.search_screen.busy.isVisible():
            self._validation_attempts += 1
            if self._validation_attempts < 60:  # give up after ~3 minutes
                QTimer.singleShot(3000, self._try_validation)
            return
        path, self._validation_path = self._validation_path, None
        self._schedule_background_validation(path)

    def _schedule_background_validation(self, path: Path) -> None:
        """Validate the freshly loaded database off the critical path.

        The report feeds the database-info page; users see the app ready in
        well under a second instead of waiting several seconds for checks.
        """

        def work() -> ValidationReport:
            return validate_file(path, deep=False)

        def done(report: ValidationReport) -> None:
            if self._closing:
                return
            self._last_report = report

        run_task(
            work,
            on_finished=done,
            on_error=lambda message: log_event(
                "database", f"background validation failed: {message}"
            ),
        )

    def _set_database_missing(self, path: Path) -> None:
        _close_in_background(self.service, self.manager)
        self.manager = None
        self.status_dot.setProperty("state", "missing")
        self._repolish(self.status_dot)
        self.status_label.setText("Gospel database not installed")
        expected = config.expected_database_display_path()
        self.search_screen.show_unavailable()
        self.settings_page.set_database_status(
            False, "", f"Lyric Sync is ready, but the local Gospel song database has "
                       f"not been added yet. Expected: {expected}"
        )
        self.about_page.set_stats(None, None)

    def _set_database_failure(self, headline: str, detail: str) -> None:
        _close_in_background(self.service, self.manager)
        self.manager = None
        self.status_dot.setProperty("state", "missing")
        self._repolish(self.status_dot)
        self.status_label.setText(headline)
        self.settings_page.set_database_status(False, "", f"{headline}: {detail}")
        self.search_screen.show_error(f"{headline}. {detail}")
        self.about_page.set_stats(None, None)

    def _locate_database(self) -> None:
        start_dir = str(config.project_root() / config.DATABASE_DIRNAME)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Locate Gospel database (.LSDB)",
            start_dir,
            "Lyric Sync database (*.lsdb);;SQLite database (*.sqlite *.db);;All files (*.*)",
        )
        if not selected:
            return
        self.preferences.database_override = selected
        self.preferences.save()
        self.reload_database()

    def _validate_database(self) -> None:
        path, _ = config.resolve_database_path(self.preferences.database_override)

        def work() -> ValidationReport:
            return validate_file(path, deep=True)

        def done(report: ValidationReport) -> None:
            self._last_report = report
            summary = report.summary
            self.settings_page.set_validation_result(summary, report.ok)
            if self.pages.currentIndex() == PAGE_DATABASE and self.manager is not None:
                self.db_info_page.set_info(
                    self.manager.info(deep_check=False),
                    report,
                )

        run_task(work, on_finished=done,
                 on_error=lambda message: self.settings_page.set_validation_result(
                     f"Validation failed: {message}", False
                 ))

    def _open_database_info(self) -> None:
        self.show_page(PAGE_DATABASE)
        self.db_info_page.show_loading()
        self._load_database_info()

    def _load_database_info(self) -> None:
        if self.manager is None or not self.manager.is_open:
            path, _ = config.resolve_database_path(self.preferences.database_override)
            self.db_info_page.show_missing(config.expected_database_display_path())
            return

        manager = self.manager
        report = self._last_report

        def work() -> tuple:
            info = manager.info(deep_check=False)
            digest, manifest = read_provenance(info.path)
            return info, report, digest, manifest

        def done(payload) -> None:
            info, report, digest, manifest = payload
            self.db_info_page.set_extra(digest, manifest)
            self.db_info_page.set_info(info, report)

        run_task(work, on_finished=done,
                 on_error=lambda message: self.db_info_page.show_missing(message))

    # ------------------------------------------------------------------ misc

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        # Never block window teardown on an in-flight search's lock.
        _close_in_background(self.service, self.manager)
        self.preferences.save()
        super().closeEvent(event)


def normalize_tokens(query: str) -> list[str]:
    from lyric_sync.search.query_normalizer import tokenize

    return tokenize(query)
