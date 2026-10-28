"""Song detail view: sticky header, lyric reader and metadata inspector."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app.theme import SP_LG, SP_MD, SP_SM, SP_XL, SP_XS
from lyric_sync.models.lyric import SongLyrics
from lyric_sync.models.search_result import MatchLabel
from lyric_sync.models.song import METADATA_ONLY, Song
from lyric_sync.search.highlighter import highlighted_html
from lyric_sync.ui.components.widgets import (
    BackButton,
    Chip,
    Divider,
    EmptyState,
    SectionTitle,
    glyph_icon,
    icon_text_button,
)

_LABEL_KIND = {
    MatchLabel.STRONG: "strong",
    MatchLabel.GOOD: "good",
    MatchLabel.POSSIBLE: "possible",
}

_COPYRIGHT_BANNER = (
    "Lyrics for this song are protected by copyright and not distributed "
    "in the local database. Metadata and catalogue details are preserved below."
)


def _accent_color() -> str:
    from lyric_sync.app import theme as theme_module

    app = theme_module.QApplication.instance()
    mode = str(app.property("tkgMode") or "dark") if app else "dark"
    palette = theme_module.resolve_palette(mode)
    return palette.yellow if palette.mode == "dark" else "#854D0E"


class SongPage(QWidget):
    """Full detail view: 70 % lyric reader · 30 % metadata inspector."""

    back_requested = Signal()
    favorite_toggled = Signal(object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._song: Song | None = None
        self._favorite = False
        self._lyrics: SongLyrics | None = None
        self.copy_button: QPushButton | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- sticky top bar: back · title · star (never scrolls away)
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(SP_XL, SP_MD, SP_XL, SP_MD)
        holder_layout.setSpacing(SP_LG)

        self.back_button = BackButton("Results")
        self.back_button.clicked.connect(self.back_requested)
        holder_layout.addWidget(self.back_button)

        self.header_box = QVBoxLayout()
        self.header_box.setSpacing(SP_XS)
        self._title_label = QLabel("")
        self._title_label.setProperty("role", "pageTitle")
        self._title_label.setWordWrap(True)
        self.header_box.addWidget(self._title_label)
        self._artist_label = QLabel("")
        self._artist_label.setProperty("role", "byline")
        self.header_box.addWidget(self._artist_label)
        holder_layout.addLayout(self.header_box, 1)

        self.favorite_button = icon_text_button("star", "Favorite", "secondary")
        self.favorite_button.setFixedHeight(40)
        self.favorite_button.clicked.connect(self._toggle_favorite)
        holder_layout.addWidget(self.favorite_button, 0, Qt.AlignTop)

        outer.addWidget(holder)
        self._holder = holder

        # ---- split stage: reader 70 % · inspector 30 %
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        # Reader (left)
        reader = QWidget()
        reader_layout = QVBoxLayout(reader)
        reader_layout.setContentsMargins(SP_XL, 0, SP_LG, SP_XL)
        reader_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_host = QWidget()
        self._content = QWidget()
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        host_layout = QVBoxLayout(scroll_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(self._content)
        scroll.setWidget(scroll_host)
        reader_layout.addWidget(scroll)
        self._reader_scroll = scroll

        # Inspector (right)
        self.inspector = QFrame()
        self.inspector.setObjectName("inspector")
        self.inspector.setMinimumWidth(260)
        self.inspector.setMaximumWidth(380)
        self.inspector_layout = QVBoxLayout(self.inspector)
        self.inspector_layout.setContentsMargins(20, SP_LG, 20, SP_LG)
        self.inspector_layout.setSpacing(SP_MD)

        self.splitter.addWidget(reader)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        outer.addWidget(self.splitter, 1)

    # ------------------------------------------------------------------ api

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.splitter.sizes() == [0, 0]:
            self.splitter.setSizes([700, 300])
        # Keep the sticky back button inside the same horizontal envelope.
        offset = max(SP_XL, (self.width() - 1100) // 2) if self.width() > 1200 else SP_XL
        self._holder.layout().setContentsMargins(offset, SP_MD, offset, SP_MD)

    def clear(self) -> None:
        self._song = None
        self._lyrics = None
        self.copy_button = None
        self._clear_body()
        self._clear_inspector()

    def _copy_lyrics(self) -> None:
        if self._lyrics is None or self._lyrics.is_empty:
            return
        QApplication.clipboard().setText(self._lyrics.plain_text)
        if self.copy_button is not None:
            self.copy_button.setText("Copied")
            QTimer.singleShot(1600, self._restore_copy_label)

    def _restore_copy_label(self) -> None:
        if self.copy_button is not None:
            self.copy_button.setText("Copy lyrics")

    def show_song(
        self,
        song: Song,
        lyrics: SongLyrics | None,
        query_tokens: tuple[str, ...] | list[str] = (),
        match_label: MatchLabel | None = None,
        favorite: bool = False,
    ) -> None:
        self._song = song
        self._favorite = favorite
        self._clear_body()
        self._clear_inspector()

        self._title_label.setText(song.title)
        self._artist_label.setText(song.display_artist)
        self._sync_favorite_button()

        # ---- chips under the header (match quality + status)
        chips = QHBoxLayout()
        chips.setSpacing(SP_SM)
        if match_label is not None:
            chips.addWidget(Chip(match_label.value.upper(), _LABEL_KIND[match_label]))
        chips.addWidget(
            Chip(song.verification_label.upper(),
                 "verified" if song.is_verified else "meta")
        )
        chips.addStretch(1)
        self.header_box.addLayout(chips)

        # ---- copyright banner (metadata-only records)
        if song.copyright_status == METADATA_ONLY or not song.lyrics_displayable:
            banner = QFrame()
            banner.setObjectName("banner")
            banner_layout = QVBoxLayout(banner)
            banner_layout.setContentsMargins(SP_LG, SP_MD, SP_LG, SP_MD)
            banner_layout.setSpacing(SP_XS)
            banner_title = QLabel("Lyrics not distributed")
            banner_title.setProperty("role", "title")
            banner_layout.addWidget(banner_title)
            banner_text = QLabel(_COPYRIGHT_BANNER)
            banner_text.setProperty("role", "body")
            banner_text.setWordWrap(True)
            banner_layout.addWidget(banner_text)
            self.body.addWidget(banner)
            self.body.addSpacing(SP_XL)

        # ---- lyric sections
        tokens = tuple(query_tokens)
        self._lyrics = lyrics
        if song.lyrics_displayable and lyrics is not None and not lyrics.is_empty:
            header = QHBoxLayout()
            header.addWidget(SectionTitle("Lyrics"))
            header.addStretch(1)
            self.copy_button = QPushButton("Copy lyrics")
            self.copy_button.setProperty("variant", "ghost")
            self.copy_button.setCursor(Qt.PointingHandCursor)
            self.copy_button.clicked.connect(self._copy_lyrics)
            header.addWidget(self.copy_button)
            self.body.addLayout(header)
            self.body.addSpacing(SP_LG)
            self._render_lyrics(lyrics, tokens)
        elif lyrics is not None and lyrics.available and lyrics.is_empty:
            self.body.addWidget(
                EmptyState(
                    "Lyrics unavailable in this database",
                    "This record is stored as metadata only, so no lyric text "
                    "can be shown.",
                    glyph="info",
                )
            )
        else:
            self.body.addWidget(
                EmptyState(
                    "Lyrics unavailable in this database",
                    "The song can still appear in search results. "
                    "No lyric text is stored for this record.",
                    glyph="info",
                )
            )
        self.body.addStretch(1)

        # ---- inspector: metadata · copyright · provenance
        self._build_inspector(song)

    # ------------------------------------------------------------ internals

    def _clear_body(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _clear_inspector(self) -> None:
        while self.inspector_layout.count():
            item = self.inspector_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    sub = layout.takeAt(0)
                    sub_widget = sub.widget()
                    if sub_widget is not None:
                        sub_widget.deleteLater()

    def _build_inspector(self, song: Song) -> None:
        title = QLabel("DETAILS")
        title.setProperty("role", "section")
        self.inspector_layout.addWidget(title)

        # Key-value metadata table from the model (no fabricated fields).
        for label, value in song.metadata_fields:
            if label == "Artist":
                continue
            row = QVBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)
            key = QLabel(label.upper())
            key.setObjectName("metaKey")
            val = QLabel(value)
            val.setObjectName("metaValue")
            val.setWordWrap(True)
            row.addWidget(key)
            row.addWidget(val)
            holder = QWidget()
            holder.setLayout(row)
            self.inspector_layout.addWidget(holder)

        self.inspector_layout.addSpacing(SP_SM)
        self.inspector_layout.addWidget(Divider())
        self.inspector_layout.addSpacing(SP_SM)

        copyright_title = QLabel("COPYRIGHT")
        copyright_title.setProperty("role", "section")
        self.inspector_layout.addWidget(copyright_title)
        status_chip = Chip(song.copyright_label.upper(), "meta")
        if song.copyright_status == METADATA_ONLY:
            status_chip.set_kind("warn")
        self.inspector_layout.addWidget(status_chip)

        if song.rights_notice:
            rights = QLabel(song.rights_notice)
            rights.setProperty("role", "muted")
            rights.setWordWrap(True)
            self.inspector_layout.addWidget(rights)

        self.inspector_layout.addSpacing(SP_SM)
        self.inspector_layout.addWidget(Divider())
        self.inspector_layout.addSpacing(SP_SM)

        provenance_title = QLabel("PROVENANCE")
        provenance_title.setProperty("role", "section")
        self.inspector_layout.addWidget(provenance_title)
        if song.source:
            source = QLabel(song.source)
            source.setProperty("role", "muted")
            source.setWordWrap(True)
            self.inspector_layout.addWidget(source)
        db_id = QLabel(f"Database ID · {song.id}")
        db_id.setProperty("role", "caption")
        self.inspector_layout.addWidget(db_id)

        self.inspector_layout.addStretch(1)

    def _render_lyrics(self, lyrics: SongLyrics, tokens: tuple[str, ...]) -> None:
        sections = lyrics.sorted_sections()
        labelled = any(
            section.label or section.type not in ("OTHER",) for section in sections
        )
        # Count identical non-empty lines so repeats can be badged honestly
        # (derived from the stored text — never fabricated).
        line_counts = Counter(
            line.strip().lower()
            for section in sections
            for line in section.lines
            if line.strip()
        )

        for section in sections:
            if labelled:
                pill = QLabel(section.display_label.upper())
                pill.setObjectName("sectionPill")
                pill.setAlignment(Qt.AlignLeft)
                self.body.addWidget(pill)
                self.body.addSpacing(SP_MD)
            for line in section.lines:
                if not line.strip():
                    self.body.addSpacing(SP_SM)
                    continue
                rendered = QLabel()
                rendered.setProperty("role", "lyric")
                rendered.setTextFormat(Qt.RichText)
                rendered.setWordWrap(True)
                count = line_counts.get(line.strip().lower(), 1)
                if tokens:
                    text = highlighted_html(line, tokens, _accent_color())
                else:
                    text = line.replace("&", "&amp;").replace("<", "&lt;")
                if count > 1:
                    text += (
                        f' <span style="color:#6B7280; font-size:11px;">'
                        f'&times;{count}</span>'
                    )
                rendered.setText(text)
                self.body.addWidget(rendered)
                self.body.addSpacing(6)
            self.body.addSpacing(SP_LG)

    def _toggle_favorite(self) -> None:
        if self._song is None:
            return
        self._favorite = not self._favorite
        self._sync_favorite_button()
        self.favorite_toggled.emit(self._song.id, self._favorite)

    def _sync_favorite_button(self) -> None:
        active = self._favorite
        self.favorite_button.setText("In favorites" if active else "Favorite")
        self.favorite_button.setIcon(
            glyph_icon(
                "star" if active else "star_outline",
                15,
                "yellow" if active else "text_muted",
            )
        )
