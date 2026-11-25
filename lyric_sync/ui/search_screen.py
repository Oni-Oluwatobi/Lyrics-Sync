"""Search screen: search field, compact results list, lyrics preview panel.

The workspace of the app.  Top row is the search field + Search button;
below it the results list shares the row with a lyrics preview panel that
updates as the selection moves (single click selects, double click or
Enter opens the full song).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app.theme import SP_MD, SP_SM, SP_XL, SP_XS
from lyric_sync.models.search_result import SearchResult
from lyric_sync.search.highlighter import highlighted_html
from lyric_sync.search.search_engine import SearchResponse
from lyric_sync.ui.components.result_row import ResultRow, _hit_color
from lyric_sync.ui.components.search_box import SearchBox
from lyric_sync.ui.components.widgets import BusyBar, Chip, EmptyState

# Auto-collapse threshold for the preview panel (workspace width in px).
PREVIEW_BREAKPOINT = 980
PREVIEW_WIDTH = 340


def split_by_lyrics(results, show_without_lyrics: bool):
    """Return (visible, hidden_count) for the lyrics-first default.

    Songs stored as metadata-only can be identified but have no lyric text to
    read; hiding them by default keeps results focused on songs you can sing
    along with. The Settings switch restores the full catalogue.
    """
    if show_without_lyrics:
        return list(results), 0
    visible = [result for result in results if result.has_lyrics]
    return visible, len(results) - len(visible)


class SearchScreen(QWidget):
    """The Search workspace: query field, ranked results, lyrics preview."""

    search_submitted = Signal(str)
    query_edited = Signal(str)
    open_song = Signal(object)
    sensitivity_changed = Signal(str)
    relax_requested = Signal()
    favorite_toggled = Signal(object, bool)

    STATE_IDLE = 0
    STATE_LIST = 1
    STATE_EMPTY = 2
    STATE_UNAVAILABLE = 3
    STATE_ERROR = 4

    # Rows are created in small slices so one response never stalls the UI
    # thread (a 50-row rebuild measured ~450 ms in one block on low-end gear;
    # 4-row slices keep the longest block well under 100 ms).
    RENDER_CHUNK = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[ResultRow] = []
        self._current = -1
        self._is_favorite = None  # set by the window: callable[[object], bool]
        self._render_queue: list = []
        self._render_tokens: list[str] = []
        self._tokens: list[str] = []
        self._state = self.STATE_IDLE
        self.show_without_lyrics = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_chunk)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SP_XL, 20, SP_XL, SP_MD)
        outer.setSpacing(SP_SM)

        # ------------------------------------------------- search field row
        search_row = QHBoxLayout()
        search_row.setSpacing(SP_SM)

        self.search_box = SearchBox()
        self.search_box.set_placeholder("Enter lyrics you remember…")
        self.search_box.query_edited.connect(self.query_edited)
        self.search_box.submitted.connect(
            lambda: self.search_submitted.emit(self.search_box.text())
        )
        search_row.addWidget(self.search_box, 1)

        self.search_button = QPushButton("Search")
        self.search_button.setProperty("variant", "primary")
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.setFixedHeight(52)
        self.search_button.clicked.connect(
            lambda: self.search_submitted.emit(self.search_box.text())
        )
        search_row.addWidget(self.search_button, 0, Qt.AlignVCenter)
        outer.addLayout(search_row)

        # ----------------------------------------------- summary / controls
        meta_row = QHBoxLayout()
        meta_row.setSpacing(SP_MD)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "heading")
        meta_row.addWidget(self.summary_label, 1)

        self.count_chip = Chip("", "meta")
        meta_row.addWidget(self.count_chip)

        sensitivity_label = QLabel("SENSITIVITY")
        sensitivity_label.setProperty("role", "caption")
        meta_row.addWidget(sensitivity_label, 0, Qt.AlignVCenter)

        self.segmented = QFrame()
        self.segmented.setObjectName("segmented")
        segment_layout = QHBoxLayout(self.segmented)
        segment_layout.setContentsMargins(3, 3, 3, 3)
        segment_layout.setSpacing(2)
        self._sensitivity_group = QButtonGroup(self)
        self._sensitivity_group.setExclusive(True)
        self._sensitivity_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("strict", "Strict"),
            ("balanced", "Balanced"),
            ("relaxed", "Relaxed"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(
                {
                    "strict": "Only the strongest matches (+0.07 threshold)",
                    "balanced": "Recommended balance (default)",
                    "relaxed": "More forgiving matches (−0.06 threshold)",
                }[key]
            )
            self._sensitivity_group.addButton(button)
            self._sensitivity_buttons[key] = button
            segment_layout.addWidget(button)
        for key, button in self._sensitivity_buttons.items():
            button.clicked.connect(
                lambda _=False, k=key: self.sensitivity_changed.emit(k)
            )
        meta_row.addWidget(self.segmented, 0, Qt.AlignVCenter)

        self.preview_toggle = QPushButton("Preview")
        self.preview_toggle.setProperty("variant", "toggle")
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.setChecked(True)
        self.preview_toggle.setCursor(Qt.PointingHandCursor)
        self.preview_toggle.setToolTip("Show or hide the lyrics preview panel")
        self.preview_toggle.toggled.connect(self._apply_preview_visibility)
        meta_row.addWidget(self.preview_toggle, 0, Qt.AlignVCenter)
        outer.addLayout(meta_row)

        self.busy = BusyBar()
        outer.addWidget(self.busy)
        outer.addSpacing(SP_XS)

        # --------------------------------------- results pane | preview pane
        body = QHBoxLayout()
        body.setSpacing(0)

        self.stack = QFrame()
        self.stack.setObjectName("panelFlat")
        stack_layout = QVBoxLayout(self.stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        self.list_view = QWidget()
        self.list_view.setObjectName("appRoot")
        self.list_layout = QVBoxLayout(self.list_view)
        self.list_layout.setContentsMargins(SP_XS, SP_XS, SP_XS, SP_XS)
        self.list_layout.setSpacing(SP_SM)
        self.list_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.StrongFocus)
        self.scroll.setWidget(self.list_view)
        self.scroll.hide()
        stack_layout.addWidget(self.scroll)

        self.idle_state = EmptyState(
            "Search the songbook",
            "Enter a line you remember — even a few words are enough. "
            "Everything searches locally on this computer.",
            glyph="search",
        )
        stack_layout.addWidget(self._centered(self.idle_state))

        self.empty_state = EmptyState(
            "No matching lyrics found in local songbook",
            "Nothing in the offline database matched this query closely enough.",
            glyph="search",
        )
        self.empty_state.add_suggestion(
            "Check for typos, or try fewer words from the line you remember."
        )
        self.empty_state.add_suggestion(
            "Switch sensitivity to Relaxed mode to widen the match threshold."
        )
        self.empty_state.add_suggestion(
            "Some modern songs are stored as metadata only (copyright) — "
            "their lyrics are not distributed."
        )
        relax_button = self.empty_state.add_action("Switch to Relaxed")
        relax_button.clicked.connect(self._on_relax_clicked)
        stack_layout.addWidget(self._centered(self.empty_state))

        self.unavailable_state = EmptyState(
            "Gospel database not installed",
            "Lyric Sync is ready, but the local Gospel song database has not been "
            "added yet. Expected: data/lyric_sync_gospel.lsdb",
            glyph="database",
        )
        stack_layout.addWidget(self._centered(self.unavailable_state))

        self.error_state = EmptyState(
            "Search could not be completed",
            "",
            glyph="info",
        )
        stack_layout.addWidget(self._centered(self.error_state))

        body.addWidget(self.stack, 1)

        # --------------------------------------------------- lyrics preview
        self.preview_panel = QFrame()
        self.preview_panel.setObjectName("inspector")
        self.preview_panel.setFixedWidth(PREVIEW_WIDTH)
        preview = QVBoxLayout(self.preview_panel)
        preview.setContentsMargins(18, 16, 18, 16)
        preview.setSpacing(10)

        preview_header = QHBoxLayout()
        preview_caption = QLabel("PREVIEW")
        preview_caption.setProperty("role", "caption")
        preview_header.addWidget(preview_caption)
        preview_header.addStretch(1)
        preview.addLayout(preview_header)

        self.preview_empty = EmptyState(
            "No preview yet",
            "Select a result to preview its matched lyrics here.",
            glyph="search",
        )
        preview.addWidget(self.preview_empty, 1)

        self.preview_body = QWidget()
        body_layout = QVBoxLayout(self.preview_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        self.preview_title = QLabel("")
        self.preview_title.setProperty("role", "title")
        self.preview_title.setWordWrap(True)
        body_layout.addWidget(self.preview_title)

        self.preview_artist = QLabel("")
        self.preview_artist.setProperty("role", "muted")
        self.preview_artist.setWordWrap(True)
        body_layout.addWidget(self.preview_artist)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(SP_SM)
        self.preview_chip = Chip("", "meta")
        badge_row.addWidget(self.preview_chip)
        badge_row.addStretch(1)
        body_layout.addLayout(badge_row)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        body_layout.addWidget(divider)

        excerpt_caption = QLabel("MATCHED LYRICS")
        excerpt_caption.setProperty("role", "caption")
        body_layout.addWidget(excerpt_caption)

        self.preview_before = QLabel("")
        self.preview_before.setProperty("role", "snippet")
        self.preview_before.setWordWrap(True)
        self.preview_before.setTextFormat(Qt.RichText)
        body_layout.addWidget(self.preview_before)

        self.preview_hit = QLabel("")
        self.preview_hit.setProperty("role", "lyric")
        self.preview_hit.setWordWrap(True)
        self.preview_hit.setTextFormat(Qt.RichText)
        body_layout.addWidget(self.preview_hit)

        self.preview_after = QLabel("")
        self.preview_after.setProperty("role", "snippet")
        self.preview_after.setWordWrap(True)
        self.preview_after.setTextFormat(Qt.RichText)
        body_layout.addWidget(self.preview_after)

        body_layout.addStretch(1)

        self.preview_open = QPushButton("Open full song")
        self.preview_open.setProperty("variant", "primary")
        self.preview_open.setCursor(Qt.PointingHandCursor)
        self.preview_open.clicked.connect(self._on_preview_open)
        self.preview_open.hide()
        body_layout.addWidget(self.preview_open, 0, Qt.AlignBottom)

        self.preview_selected: object | None = None
        preview.addWidget(self.preview_body, 1)
        self.preview_body.hide()

        body.addWidget(self.preview_panel, 0)
        outer.addLayout(body, 1)

        self._footer = QLabel("")
        self._footer.setProperty("role", "caption")
        outer.addWidget(self._footer)

        self.show_state(self.STATE_IDLE)
        self.set_sensitivity("balanced")

    # ------------------------------------------------------------------ api

    @staticmethod
    def _centered(state: QWidget) -> QWidget:
        """Center an EmptyState inside its stack page."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(state, 0, Qt.AlignCenter)
        row.addStretch(1)
        return holder

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Small workspace: collapse the preview automatically.  The user can
        # re-enable it from the Preview toggle at any width.
        if self.width() < PREVIEW_BREAKPOINT and self.preview_toggle.isChecked():
            self.preview_toggle.setChecked(False)

    def set_query(self, query: str) -> None:
        self.search_box.set_text(query)

    def query(self) -> str:
        return self.search_box.text()

    def focus_input(self, select_all: bool = False) -> None:
        self.search_box.focus_input(select_all=select_all)

    focus_search = focus_input

    def set_favorite_lookup(self, lookup) -> None:
        """``lookup(song_id) -> bool`` decides each row's initial star."""
        self._is_favorite = lookup

    def set_sensitivity(self, value: str) -> None:
        button = self._sensitivity_buttons.get(value)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_show_without_lyrics(self, enabled: bool) -> None:
        """Lyrics-first default: hide metadata-only catalogue rows."""
        self.show_without_lyrics = bool(enabled)

    @property
    def state(self) -> int:
        return self._state

    def is_unavailable(self) -> bool:
        return self._state == self.STATE_UNAVAILABLE

    def preview_text(self) -> str:
        """Title currently shown in the preview panel (smoke checks use this)."""
        return self.preview_title.text()

    def show_state(self, state: int) -> None:
        self._state = state
        self.scroll.setVisible(state == self.STATE_LIST)
        self.idle_state.parentWidget().setVisible(state == self.STATE_IDLE)
        self.empty_state.parentWidget().setVisible(state == self.STATE_EMPTY)
        self.unavailable_state.parentWidget().setVisible(
            state == self.STATE_UNAVAILABLE
        )
        self.error_state.parentWidget().setVisible(state == self.STATE_ERROR)

    def set_busy(self, busy: bool) -> None:
        self.busy.setVisible(busy)
        self.search_box.set_loading(busy)
        self.search_button.setProperty("loading", busy)
        self.search_button.setEnabled(not busy)
        self.search_button.style().unpolish(self.search_button)
        self.search_button.style().polish(self.search_button)
        if busy:
            self.summary_label.setText("Searching…")

    def show_unavailable(self) -> None:
        self._clear_rows()
        self._clear_preview()
        self.summary_label.setText("Search")
        self.count_chip.setText("")
        self.show_state(self.STATE_UNAVAILABLE)
        self._footer.setText("")

    def show_error(self, message: str) -> None:
        self._clear_rows()
        self._clear_preview()
        self.error_state.set_message(
            "Search could not be completed",
            message or "An unexpected problem occurred while searching.",
        )
        self.show_state(self.STATE_ERROR)
        self._footer.setText("")

    def show_response(self, response: SearchResponse) -> None:
        self._clear_rows()
        self._clear_preview()
        query_text = response.query.display or response.query.raw
        if not response.database_available:
            self.show_unavailable()
            return

        results, hidden = split_by_lyrics(
            response.results, self.show_without_lyrics
        )
        total = len(results)
        self.summary_label.setText(f"Results for “{query_text}”")
        chip_text = f"{total} SONG" + ("S FOUND" if total != 1 else " FOUND")
        if hidden:
            chip_text += f" · {hidden} HIDDEN"
        self.count_chip.setText(chip_text)

        if not results:
            self.show_state(self.STATE_EMPTY)
            if hidden:
                self._footer.setText(
                    f"{hidden} match(es) are catalogue metadata only (no lyric "
                    f"text). Turn on “Show songs without lyrics” in Settings to "
                    f"see them."
                )
            else:
                self._footer.setText("")
            return

        tokens = list(response.query.tokens)
        self._tokens = tokens
        self._render_queue = list(results)
        self._render_tokens = tokens
        self._render_chunk()  # first slice immediately; the rest chunked
        self.show_state(self.STATE_LIST)
        footer = (
            f"{response.candidate_count} candidates examined in "
            f"{response.elapsed_ms:.0f} ms"
        )
        if hidden:
            footer += f"  ·  {hidden} metadata-only hiding"
        if response.truncated:
            footer += "  ·  showing the strongest matches only"
        self._footer.setText(footer)

    def reset_state(self) -> None:
        """Return to the idle prompt after the database becomes available."""
        if self._rows:
            self.show_state(self.STATE_LIST)
        else:
            self.summary_label.setText("")
            self.count_chip.setText("")
            self.show_state(self.STATE_IDLE)

    def _on_relax_clicked(self) -> None:
        self.set_sensitivity("relaxed")
        self.sensitivity_changed.emit("relaxed")
        self.relax_requested.emit()

    def _render_chunk(self) -> None:
        """Create at most RENDER_CHUNK rows, then yield back to the event loop."""
        self._render_timer.stop()
        tokens = self._render_tokens
        for _ in range(self.RENDER_CHUNK):
            if not self._render_queue:
                break
            result = self._render_queue.pop(0)
            favorite = (
                bool(self._is_favorite(result.song.id))
                if self._is_favorite is not None
                else False
            )
            row = ResultRow(result, tokens, favorite=favorite)
            row.activated.connect(lambda _id, r=row: self._select_row_widget(r))
            row.double_activated.connect(self.open_song)
            row.favorite_toggled.connect(self.favorite_toggled)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)
        if self._render_queue:
            self._render_timer.start(0)
        if self._rows and self._current < 0:
            self.select_row(0)

    def clear(self) -> None:
        self._clear_rows()
        self._clear_preview()
        self.summary_label.setText("")
        self.count_chip.setText("")
        self.search_box.clear()
        self.show_state(self.STATE_IDLE)
        self._footer.setText("")

    def has_results(self) -> bool:
        return bool(self._rows)

    # ---------------------------------------------------------- navigation

    def select_row(self, row: int) -> None:
        if not self._rows:
            return
        row = max(0, min(len(self._rows) - 1, row))
        self._current = row
        for index, widget in enumerate(self._rows):
            widget.set_selected(index == row)
        target = self._rows[row]
        self.scroll.ensureWidgetVisible(target, 0, 48)
        self._show_preview(target.result)

    def _select_row_widget(self, row: ResultRow) -> None:
        try:
            index = self._rows.index(row)
        except ValueError:
            return
        self.select_row(index)

    def move_selection(self, delta: int) -> None:
        if not self._rows:
            return
        self.select_row(0 if self._current < 0 else self._current + delta)

    def open_selected(self) -> bool:
        if 0 <= self._current < len(self._rows):
            self.open_song.emit(self._rows[self._current].song_id)
            return True
        return False

    # ------------------------------------------------------------ preview

    def _apply_preview_visibility(self) -> None:
        self.preview_panel.setVisible(self.preview_toggle.isChecked())

    def _on_preview_open(self) -> None:
        if self.preview_selected is not None:
            self.open_song.emit(self.preview_selected)

    def _clear_preview(self) -> None:
        self.preview_selected = None
        self.preview_title.setText("")
        self.preview_artist.setText("")
        self.preview_chip.setText("")
        self.preview_before.setText("")
        self.preview_hit.setText("")
        self.preview_after.setText("")
        self.preview_open.hide()
        self.preview_body.hide()
        self.preview_empty.show()

    def _show_preview(self, result: SearchResult) -> None:
        self.preview_selected = result.song.id
        self.preview_title.setText(result.song.title)
        self.preview_artist.setText(result.song.display_artist)
        self.preview_chip.setText(result.label.value.upper())
        kind = {
            "Strong match": "strong",
            "Good match": "good",
            "Possible match": "possible",
        }.get(result.label.value, "meta")
        self.preview_chip.set_kind(kind)

        hit_color = _hit_color()
        if result.snippet:
            self.preview_before.setText(f"…{result.context_before}")
            self.preview_before.setVisible(bool(result.context_before))
            self.preview_hit.setText(
                f"“{highlighted_html(result.snippet, self._tokens, hit_color)}”"
            )
            self.preview_after.setText(f"{result.context_after}…")
            self.preview_after.setVisible(bool(result.context_after))
        else:
            self.preview_before.hide()
            self.preview_after.hide()
            if result.matched_fields:
                note = f"Matched {', '.join(result.matched_fields)}"
            else:
                note = "Lyrics unavailable in this database"
            self.preview_hit.setText(note)

        self.preview_empty.hide()
        self.preview_body.show()
        self.preview_open.show()

    # ---------------------------------------------------------- internals

    def _clear_rows(self) -> None:
        self._render_timer.stop()
        self._render_queue = []
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        self._current = -1
