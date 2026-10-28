"""One row in the search results list — an elevated, star-able card."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app import theme as theme_module
from lyric_sync.models.search_result import MatchLabel, SearchResult
from lyric_sync.search.highlighter import highlighted_html
from lyric_sync.ui.components.widgets import Chip, GlyphLabel, glyph_icon

_LABEL_KIND = {
    MatchLabel.STRONG: "strong",
    MatchLabel.GOOD: "good",
    MatchLabel.POSSIBLE: "possible",
}


def _hit_color() -> str:
    """Colour for matched query terms inside excerpts (yellow, per TKG)."""
    palette = theme_module.resolve_palette(
        str(theme_module.QApplication.instance().property("tkgMode") or "dark")
        if theme_module.QApplication.instance()
        else "dark"
    )
    # On the light canvas pure #FFD400 fails contrast against white, so the
    # darkened same-hue shade is used.  Dark canvas keeps the brand yellow.
    return palette.yellow if palette.mode == "dark" else "#854D0E"


def _location(song) -> str:
    parts = [part for part in (song.country, song.region) if part]
    if len(parts) == 2 and parts[1].lower() in parts[0].lower():
        parts = parts[:1]
    return "  ·  ".join(parts)


class ResultRow(QFrame):
    """Clickable, keyboard-selectable result card with a quick star toggle."""

    activated = Signal(object)
    double_activated = Signal(object)
    favorite_toggled = Signal(object, bool)

    def __init__(self, result: SearchResult, tokens: tuple[str, ...] | list[str],
                 favorite: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.song_id = result.song.id
        self.result = result
        self.tokens = tuple(tokens)
        self._favorite = favorite
        self.setObjectName("listRow")
        self.setProperty("hover", False)
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        self.installEventFilter(self)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(14)

        content = QVBoxLayout()
        content.setSpacing(6)

        # ---- line 1: title · artist ......... match badge · star
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        title = QLabel(result.song.title)
        title.setProperty("role", "title")
        title_row.addWidget(title, 0, Qt.AlignTop)

        artist = QLabel(result.song.display_artist)
        artist.setProperty("role", "muted")
        title_row.addWidget(artist, 0, Qt.AlignTop)

        title_row.addStretch(1)

        chip = Chip(result.label.value.upper(), _LABEL_KIND[result.label])
        title_row.addWidget(chip, 0, Qt.AlignTop)

        self.star_button = QPushButton()
        self.star_button.setObjectName("starButton")
        self.star_button.setFixedSize(28, 28)
        self.star_button.setCursor(Qt.PointingHandCursor)
        self.star_button.setToolTip(
            "Remove from favorites" if favorite else "Add to favorites"
        )
        self.star_button.clicked.connect(self._on_star)
        title_row.addWidget(self.star_button, 0, Qt.AlignTop)
        content.addLayout(title_row)

        # ---- line 2: metadata tags
        tags_text: list[str] = []
        song = result.song
        if song.category:
            tags_text.append(song.category)
        if song.songwriter and song.songwriter != song.artist:
            tags_text.append(song.songwriter)
        if song.year:
            tags_text.append(str(song.year))
        location = _location(song)
        if location:
            tags_text.append(location)
        tags_text.append(song.copyright_label)

        tags = QHBoxLayout()
        tags.setSpacing(6)
        for text in tags_text:
            tag = QLabel(text)
            tag.setProperty("kind", "meta")
            tags.addWidget(tag)
        tags.addStretch(1)
        content.addLayout(tags)

        # ---- line 3: excerpt snippet
        if result.snippet:
            snippet = QLabel()
            snippet.setProperty("role", "snippet")
            snippet.setWordWrap(True)
            snippet.setTextFormat(Qt.RichText)
            hit = QColor(_hit_color()).name()
            snippet.setText(
                f"“{highlighted_html(result.snippet, self.tokens, hit)}”"
            )
            content.addWidget(snippet)
        else:
            reason = "Lyrics unavailable in this database"
            if result.matched_fields:
                reason = f"Matched {', '.join(result.matched_fields)}"
            note = QLabel(reason)
            note.setProperty("role", "snippet")
            content.addWidget(note)

        outer.addLayout(content, 1)

        chevron = GlyphLabel("chevron", size=16, color="muted")
        chevron.setObjectName("rowChevron")
        outer.addWidget(chevron, 0, Qt.AlignCenter)

        self._sync_star()

    # -------------------------------------------------------------- actions

    def _on_star(self) -> None:
        self.set_favorite(not self._favorite)
        self.favorite_toggled.emit(self.song_id, self._favorite)

    def set_favorite(self, favorite: bool) -> None:
        if self._favorite == favorite:
            return
        self._favorite = favorite
        self._sync_star()

    def _sync_star(self) -> None:
        self.star_button.setIcon(
            glyph_icon(
                "star" if self._favorite else "star_outline",
                15,
                "yellow" if self._favorite else "muted",
            )
        )
        self.star_button.setIconSize(QSize(15, 15))
        self.star_button.setToolTip(
            "Remove from favorites" if self._favorite else "Add to favorites"
        )

    # -------------------------------------------------------------- selection

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self._repolish()

    def set_hover(self, hovered: bool) -> None:
        if self.property("hover") == hovered:
            return
        self.setProperty("hover", hovered)
        self._repolish()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self:
            if event.type() == QEvent.Enter:
                self.set_hover(True)
            elif event.type() == QEvent.Leave:
                self.set_hover(False)
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.song_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.double_activated.emit(self.song_id)
        super().mouseDoubleClickEvent(event)

    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
