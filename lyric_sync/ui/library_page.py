"""My Library: favorites plus saved searches (both fully local)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app.theme import SP_LG, SP_MD, SP_SM, SP_XL
from lyric_sync.ui.components.widgets import GlyphLabel, SectionTitle
from lyric_sync.ui.favorites_page import FavoritesPage


class RecentRow(QFrame):
    """One saved search: click to re-run, remove to forget."""

    activated = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, query: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.query = query
        self.setObjectName("recentRow")
        self.setProperty("hover", False)
        self.setCursor(Qt.PointingHandCursor)
        self.installEventFilter(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 8, 10)
        layout.setSpacing(10)

        icon = GlyphLabel("clock", size=14, color="muted")
        layout.addWidget(icon)

        label = QLabel(query)
        label.setProperty("role", "body")
        layout.addWidget(label, 1)

        remove = QPushButton("Remove")
        remove.setProperty("variant", "ghost")
        remove.setCursor(Qt.PointingHandCursor)
        remove.clicked.connect(self.remove_requested.emit)
        layout.addWidget(remove, 0, Qt.AlignVCenter)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        # Only Enter/Leave may trigger a repolish. Repolishing on every event
        # re-enters this filter (polish emits StyleChange) and overflows the
        # stack — 0xc00000fd at startup.
        if watched is self and event.type() in (QEvent.Enter, QEvent.Leave):
            hovered = event.type() == QEvent.Enter
            if self.property("hover") != hovered:
                self.setProperty("hover", hovered)
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.query)
        super().mousePressEvent(event)


class LibraryPage(QWidget):
    """Favorites and saved searches in one workspace."""

    open_song = Signal(object)
    remove_favorite = Signal(object)
    clear_favorites = Signal()
    search_requested = Signal()
    search_selected = Signal(str)
    recent_removed = Signal(str)
    clear_recents = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recents: list[str] = []
        self._recents_enabled = True
        self._rows: list[RecentRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(SP_XL, 20, SP_XL, SP_XL)
        column.setSpacing(0)
        scroll.setWidget(holder)

        heading = QLabel("My Library")
        heading.setProperty("role", "pageTitle")
        column.addWidget(heading)
        caption = QLabel("Saved on this device — favorites and recent searches.")
        caption.setProperty("role", "muted")
        column.addWidget(caption)
        column.addSpacing(SP_LG)

        # ------------------------------------------------------- favorites
        self.favorites = FavoritesPage()
        self.favorites.open_song.connect(self.open_song)
        self.favorites.remove_favorite.connect(self.remove_favorite)
        self.favorites.clear_requested.connect(self.clear_favorites)
        self.favorites.search_requested.connect(self.search_requested)
        column.addWidget(self.favorites, 1)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        column.addWidget(divider)
        column.addSpacing(SP_LG)

        # --------------------------------------------------- saved searches
        header = QHBoxLayout()
        header.setSpacing(SP_MD)
        header.addWidget(SectionTitle("Saved searches"))
        header.addStretch(1)
        self.clear_recents_button = QPushButton("Clear all")
        self.clear_recents_button.setProperty("variant", "ghost")
        self.clear_recents_button.setCursor(Qt.PointingHandCursor)
        self.clear_recents_button.clicked.connect(self.clear_recents)
        header.addWidget(self.clear_recents_button)
        column.addLayout(header)

        note = QLabel("Click a search to run it again.")
        note.setProperty("role", "caption")
        column.addWidget(note)
        column.addSpacing(SP_SM)

        self.recents_host = QWidget()
        self.recents_layout = QVBoxLayout(self.recents_host)
        self.recents_layout.setContentsMargins(0, 0, 0, 0)
        self.recents_layout.setSpacing(SP_SM)
        column.addWidget(self.recents_host)

        self.recents_empty = QLabel(
            "No saved searches yet — the queries you run will appear here."
        )
        self.recents_empty.setProperty("role", "muted")
        self.recents_empty.setWordWrap(True)
        column.addWidget(self.recents_empty)

        column.addStretch(1)

    # ------------------------------------------------------------------ api

    def set_recents(self, queries: list[str], enabled: bool = True) -> None:
        self._recents = list(queries)
        self._recents_enabled = enabled
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()

        if not enabled:
            self.recents_empty.setText(
                "Recent searches are turned off in Settings → Search."
            )
            self.recents_empty.show()
            self.clear_recents_button.setEnabled(False)
            self.clear_recents_button.hide()
            return

        for query in self._recents:
            row = RecentRow(query)
            row.activated.connect(self.search_selected)
            row.remove_requested.connect(self.recent_removed)
            self.recents_layout.addWidget(row)
            self._rows.append(row)

        self.recents_empty.setText(
            "No saved searches yet — the queries you run will appear here."
        )
        self.recents_empty.setVisible(not self._rows)
        self.clear_recents_button.setVisible(bool(self._rows))
        self.clear_recents_button.setEnabled(bool(self._rows))
