"""Favorites page: filterable, sortable card grid with inline remove."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app.theme import SP_MD, SP_SM
from lyric_sync.ui.components.widgets import CenterColumn, EmptyState, GlyphLabel


class FavoriteCard(QFrame):
    """One favorited song (metadata only — no lyrics are copied)."""

    activated = Signal(object)
    remove_requested = Signal(object)

    def __init__(self, song_id: object, title: str, subtitle: str,
                 missing: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.song_id = song_id
        self._confirming = False
        self.setObjectName("listRow")
        self.setProperty("hover", False)
        self.setCursor(Qt.PointingHandCursor if not missing else Qt.ArrowCursor)
        self.installEventFilter(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        star = GlyphLabel("star", size=16, color="yellow")
        layout.addWidget(star, 0, Qt.AlignTop)

        content = QVBoxLayout()
        content.setSpacing(4)
        title_label = QLabel(title)
        title_label.setProperty("role", "title")
        title_label.setWordWrap(True)
        content.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setProperty("role", "muted")
        content.addWidget(subtitle_label)
        layout.addLayout(content, 1)

        self.remove_button = QPushButton("Remove")
        self.remove_button.setProperty("variant", "ghost")
        self.remove_button.setCursor(Qt.PointingHandCursor)
        self.remove_button.clicked.connect(self._on_remove)
        layout.addWidget(self.remove_button, 0, Qt.AlignVCenter)

    def _on_remove(self) -> None:
        if not self._confirming:
            # Quick remove confirmation: first click arms, second confirms.
            self._confirming = True
            self.remove_button.setText("Confirm?")
            self.remove_button.setProperty("variant", "danger")
            self.remove_button.setStyleSheet("")
            self.style().unpolish(self.remove_button)
            self.style().polish(self.remove_button)
            return
        self.remove_requested.emit(self.song_id)

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
        if event.button() == Qt.LeftButton and not self._confirming:
            if self.cursor().shape() == Qt.PointingHandCursor:
                self.activated.emit(self.song_id)
        super().mousePressEvent(event)


class FavoritesPage(QWidget):
    """Songs the user marked as favorites (ids only, resolved on demand)."""

    open_song = Signal(object)
    remove_favorite = Signal(object)
    clear_requested = Signal()
    search_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[object, str, str, bool]] = []
        self._cards: list[FavoriteCard] = []
        self._columns = 2

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        container = CenterColumn(max_width=940)
        self._container = container
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        title = QLabel("Favorites")
        title.setProperty("role", "pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.clear_button = QPushButton("Clear all")
        self.clear_button.setProperty("variant", "ghost")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_requested)
        header.addWidget(self.clear_button)
        column.addLayout(header)

        subtitle = QLabel("Saved on this device — only song references are stored.")
        subtitle.setProperty("role", "muted")
        column.addWidget(subtitle)
        column.addSpacing(SP_MD)

        # ---- filter + sort bar
        controls = QHBoxLayout()
        controls.setSpacing(SP_MD)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter favorites…")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._apply_view)
        controls.addWidget(self.filter_input, 1)

        sort_label = QLabel("SORT")
        sort_label.setProperty("role", "caption")
        controls.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.setFixedWidth(170)
        self.sort_combo.addItem("Date starred", "date")
        self.sort_combo.addItem("Title A–Z", "title")
        self.sort_combo.currentIndexChanged.connect(self._apply_view)
        controls.addWidget(self.sort_combo)
        column.addLayout(controls)

        column.addSpacing(SP_MD)

        self.stack_body = QVBoxLayout()
        column.addLayout(self.stack_body, 1)

        # ---- scrolling card grid
        self.grid_host = QWidget()
        self.grid_layout = QVBoxLayout(self.grid_host)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(SP_SM)
        self.grid_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.grid_host)
        self.stack_body.addWidget(self.scroll, 1)

        self.empty_state = EmptyState(
            "No favorites yet",
            "Open a song from your search results and choose Favorite to keep it here.",
            glyph="star_outline",
            action_label="Find a song",
        )
        self.empty_state.action_requested.connect(self.search_requested)
        self.stack_body.addWidget(self.empty_state, 0, Qt.AlignCenter)

        outer.addWidget(container, 1)
        outer.addStretch(1)

        self.scroll.hide()
        self.clear_button.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._container.sync_width(self.width())
        columns = 2 if self.scroll.viewport().width() >= 640 else 1
        if columns != self._columns:
            self._columns = columns
            self._apply_view()

    # ------------------------------------------------------------------ api

    def set_items(self, entries: list[tuple[object, str, str, bool]]) -> None:
        """``entries``: ``(song_id, title, subtitle, missing)``."""
        self._entries = list(entries)
        self._apply_view()

    def _apply_view(self) -> None:
        needle = self.filter_input.text().strip().lower()
        sort_key = self.sort_combo.currentData()

        visible = [
            entry for entry in self._entries
            if not needle
            or needle in entry[1].lower()
            or needle in entry[2].lower()
        ]
        if sort_key == "title":
            visible = sorted(visible, key=lambda entry: entry[1].lower())

        # Rebuild the grid: rows of `self._columns` cards.
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SP_SM)
        in_row = 0
        for song_id, title, subtitle, missing in visible:
            card = FavoriteCard(song_id, title, subtitle, missing)
            card.activated.connect(self.open_song)
            card.remove_requested.connect(self.remove_favorite)
            stretch = 1 if self._columns > 1 else 0
            row_layout.addWidget(card, stretch)
            in_row += 1
            self._cards.append(card)
            if in_row == self._columns:
                holder = QWidget()
                holder.setLayout(row_layout)
                self.grid_layout.insertWidget(self.grid_layout.count() - 1, holder)
                row_layout = QHBoxLayout()
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(SP_SM)
                in_row = 0
        if in_row:
            row_layout.addStretch(1)
            holder = QWidget()
            holder.setLayout(row_layout)
            self.grid_layout.insertWidget(self.grid_layout.count() - 1, holder)
        self.grid_layout.addStretch(1)

        has_items = bool(self._entries)
        self.scroll.setVisible(has_items)
        self.empty_state.setVisible(not has_items)
        self.clear_button.setVisible(has_items)
