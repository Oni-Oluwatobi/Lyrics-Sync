"""Settings page: grouped cards — appearance, search, database, application."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lyric_sync import APP_NAME, DEVELOPER, VERSION
from lyric_sync.app.theme import SP_LG, SP_MD, SP_SM, SP_XL, SP_XS, SP_3XL
from lyric_sync.ui.components.widgets import (
    CenterColumn,
    Chip,
    GlyphLabel,
    SectionTitle,
    Switch,
)


class SettingsPage(QWidget):
    """Appearance, search, database and application — grouped as cards."""

    theme_changed = Signal(str)
    sensitivity_changed = Signal(str)
    live_search_toggled = Signal(bool)
    history_toggled = Signal(bool)
    clear_history_requested = Signal()
    open_database_info = Signal()
    validate_database = Signal()
    reload_database = Signal()
    locate_database = Signal()
    import_lyrics_requested = Signal()
    open_about = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addStretch(1)
        self._center = CenterColumn()
        holder_layout.addWidget(self._center)
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        self._holder = holder

        column = QVBoxLayout(self._center)
        column.setContentsMargins(0, SP_XL, 0, SP_3XL)
        column.setSpacing(0)

        heading = QLabel("Settings")
        heading.setProperty("role", "pageTitle")
        column.addWidget(heading)
        column.addSpacing(SP_XL)

        # ------------------------------------------------------- appearance
        card, layout = self._card()
        layout.addWidget(SectionTitle("Appearance"))
        layout.addSpacing(SP_MD)

        appearance_row = QHBoxLayout()
        appearance_row.setSpacing(SP_XL)
        appearance_label = self._row_label(
            "Theme", "Light, dark or follow the system setting."
        )
        appearance_row.addWidget(appearance_label, 1)

        self.segmented = QFrame()
        self.segmented.setObjectName("segmented")
        segment_layout = QHBoxLayout(self.segmented)
        segment_layout.setContentsMargins(3, 3, 3, 3)
        segment_layout.setSpacing(2)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self._theme_buttons: dict[str, QPushButton] = {}
        for key, label in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.theme_group.addButton(button)
            self._theme_buttons[key] = button
            segment_layout.addWidget(button)
        for key, button in self._theme_buttons.items():
            button.clicked.connect(lambda _=False, k=key: self._select_theme(k))
        appearance_row.addWidget(self.segmented, 0, Qt.AlignTop)
        layout.addLayout(appearance_row)
        column.addWidget(card)
        column.addSpacing(SP_LG)

        # ----------------------------------------------------------- search
        card, layout = self._card()
        layout.addWidget(SectionTitle("Search"))
        layout.addSpacing(SP_MD)

        # --- history (switch + clear)
        history_row = QHBoxLayout()
        history_row.setSpacing(SP_MD)
        history_label = self._row_label(
            "Remember recent searches", "Keep a local list of previous queries."
        )
        history_row.addWidget(history_label, 1)
        self.history_switch = Switch()
        self.history_switch.toggled.connect(self.history_toggled)
        history_row.addWidget(self.history_switch, 0, Qt.AlignTop)
        layout.addLayout(history_row)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(SP_MD)
        self.clear_history_button = QPushButton("Clear Recent Searches")
        self.clear_history_button.setProperty("variant", "secondary")
        self.clear_history_button.setCursor(Qt.PointingHandCursor)
        self.clear_history_button.clicked.connect(self.clear_history_requested)
        clear_row.addWidget(self.clear_history_button)
        self.history_count = QLabel("")
        self.history_count.setProperty("role", "caption")
        clear_row.addWidget(self.history_count)
        clear_row.addStretch(1)
        layout.addLayout(clear_row)

        layout.addSpacing(SP_MD)

        # --- live search (switch)
        live_row = QHBoxLayout()
        live_row.setSpacing(SP_MD)
        live_label = self._row_label(
            "Search while typing",
            "Run the search automatically after a short pause.",
        )
        live_row.addWidget(live_label, 1)
        self.live_search_switch = Switch()
        self.live_search_switch.toggled.connect(self.live_search_toggled)
        live_row.addWidget(self.live_search_switch, 0, Qt.AlignTop)
        layout.addLayout(live_row)

        layout.addSpacing(SP_LG)
        layout.addWidget(self._section_divider())

        # --- sensitivity radio group with threshold explanations
        layout.addSpacing(SP_MD)
        sensitivity_label = QLabel("SEARCH SENSITIVITY")
        sensitivity_label.setProperty("role", "section")
        layout.addWidget(sensitivity_label)
        layout.addSpacing(SP_SM)

        self._sensitivity_group = QButtonGroup(self)
        self._sensitivity_group.setExclusive(True)
        self._sensitivity_buttons: dict[str, QRadioButton] = {}
        for key, title, caption in (
            ("strict", "Strict  [+0.07]",
             "Only the strongest matches — fewer false positives."),
            ("balanced", "Balanced  [default]",
             "Recommended threshold for everyday searching."),
            ("relaxed", "Relaxed  [−0.06]",
             "More forgiving — widens matches when words are half-remembered."),
        ):
            radio = QRadioButton()
            radio.setCursor(Qt.PointingHandCursor)
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(2)
            title_label = QLabel(title)
            title_label.setProperty("role", "fieldTitle")
            caption_label = QLabel(caption)
            caption_label.setProperty("role", "caption")
            caption_label.setWordWrap(True)
            box_layout.addWidget(title_label)
            box_layout.addWidget(caption_label)
            row = QHBoxLayout()
            row.setSpacing(SP_MD)
            row.addWidget(radio, 0, Qt.AlignTop)
            row.addWidget(box, 1)
            holder = QWidget()
            holder.setLayout(row)
            layout.addWidget(holder)
            self._sensitivity_group.addButton(radio)
            self._sensitivity_buttons[key] = radio
            radio.clicked.connect(lambda _=False, k=key: self.sensitivity_changed.emit(k))
        column.addWidget(card)
        column.addSpacing(SP_LG)

        # --------------------------------------------------------- database
        card, layout = self._card()
        layout.addWidget(SectionTitle("Database"))
        layout.addSpacing(SP_MD)

        status_row = QHBoxLayout()
        status_row.setSpacing(SP_SM)
        status_icon = GlyphLabel("database", size=18, color="accent")
        status_row.addWidget(status_icon)
        self.database_status = QLabel("Checking…")
        self.database_status.setProperty("role", "body")
        status_row.addWidget(self.database_status, 1)
        self.database_chip = Chip("", "meta")
        status_row.addWidget(self.database_chip)
        layout.addLayout(status_row)

        self.database_detail = QLabel("")
        self.database_detail.setProperty("role", "caption")
        self.database_detail.setWordWrap(True)
        layout.addWidget(self.database_detail)
        layout.addSpacing(SP_SM)

        self.database_path_label = QLabel("—")
        self.database_path_label.setProperty("role", "caption")
        self.database_path_label.setWordWrap(True)
        layout.addWidget(self.database_path_label)

        layout.addSpacing(SP_SM)

        db_buttons = QHBoxLayout()
        db_buttons.setSpacing(SP_SM)
        for label, signal in (
            ("Database Information", self.open_database_info),
            ("Reload database", self.reload_database),
            ("Locate Database…", self.locate_database),
        ):
            button = QPushButton(label)
            button.setProperty("variant", "secondary")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(signal.emit)
            db_buttons.addWidget(button)
        db_buttons.addStretch(1)
        layout.addLayout(db_buttons)

        layout.addSpacing(SP_MD)

        validate_row = QHBoxLayout()
        validate_row.setSpacing(SP_MD)
        self.validate_button = QPushButton("Validate Database Integrity")
        self.validate_button.setProperty("variant", "primary")
        self.validate_button.setCursor(Qt.PointingHandCursor)
        self.validate_button.clicked.connect(self._on_validate_clicked)
        validate_row.addWidget(self.validate_button)
        self.validation_state = QLabel("")
        self.validation_state.setProperty("role", "caption")
        validate_row.addWidget(self.validation_state, 1)
        layout.addLayout(validate_row)

        layout.addSpacing(SP_XS)
        self.validation_result = QLabel("")
        self.validation_result.setProperty("role", "muted")
        self.validation_result.setWordWrap(True)
        self.validation_result.hide()
        layout.addWidget(self.validation_result)
        column.addWidget(card)
        column.addSpacing(SP_LG)

        # ------------------------------------------------------------ lyrics
        card, layout = self._card()
        layout.addWidget(SectionTitle("Lyrics"))
        layout.addSpacing(SP_MD)

        lyrics_body = QLabel(
            "Add your own lyric files (PDF, TXT or Markdown). Lyric Sync stores "
            "exactly what you supply, records a SHA-256 fingerprint of every "
            "file, and rebuilds search so the new songs become findable. A "
            "database backup is made before each import."
        )
        lyrics_body.setProperty("role", "caption")
        lyrics_body.setWordWrap(True)
        layout.addWidget(lyrics_body)
        layout.addSpacing(SP_MD)

        import_row = QHBoxLayout()
        import_row.setSpacing(SP_SM)
        self.import_lyrics_button = QPushButton("Import lyrics files…")
        self.import_lyrics_button.setProperty("variant", "primary")
        self.import_lyrics_button.setCursor(Qt.PointingHandCursor)
        self.import_lyrics_button.clicked.connect(self.import_lyrics_requested.emit)
        import_row.addWidget(self.import_lyrics_button)
        import_row.addStretch(1)
        layout.addLayout(import_row)

        layout.addSpacing(SP_XS)
        self.import_status = QLabel("")
        self.import_status.setProperty("role", "caption")
        self.import_status.setWordWrap(True)
        self.import_status.hide()
        layout.addWidget(self.import_status)
        column.addWidget(card)
        column.addSpacing(SP_LG)

        # ----------------------------------------------------- application
        card, layout = self._card()
        layout.addWidget(SectionTitle("Application"))
        layout.addSpacing(SP_MD)

        about_button = QPushButton("About Lyric Sync")
        about_button.setProperty("variant", "secondary")
        about_button.setCursor(Qt.PointingHandCursor)
        about_button.clicked.connect(self.open_about)
        layout.addWidget(about_button, 0, Qt.AlignLeft)
        layout.addSpacing(SP_MD)

        about_body = QLabel(
            f"{APP_NAME}  ·  Version {VERSION}  ·  By {DEVELOPER}\n"
            "Offline Gospel song identification through remembered lyrics. "
            "Account sign-in is optional; searching always runs locally."
        )
        about_body.setProperty("role", "body")
        about_body.setWordWrap(True)
        layout.addWidget(about_body)
        column.addWidget(card)

    # --------------------------------------------------------------- layout

    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        """One settings group: a surface card with its own layout."""
        card = QFrame()
        card.setObjectName("panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SP_XL, SP_LG, SP_XL, SP_LG)
        layout.setSpacing(0)
        return card, layout

    @staticmethod
    def _section_divider() -> QFrame:
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        return divider

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._center.sync_width(self.width())

    def _row_label(self, title: str, caption: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SP_XS)
        title_label = QLabel(title)
        title_label.setProperty("role", "fieldTitle")
        layout.addWidget(title_label)
        caption_label = QLabel(caption)
        caption_label.setProperty("role", "caption")
        caption_label.setWordWrap(True)
        layout.addWidget(caption_label)
        return box

    def _on_validate_clicked(self) -> None:
        self.validate_button.setEnabled(False)
        self.validate_button.setProperty("loading", True)
        self.validate_button.style().unpolish(self.validate_button)
        self.validate_button.style().polish(self.validate_button)
        self.validation_state.setText("Validating (read-only)…")
        self.validation_result.hide()
        self.validate_database.emit()

    # ------------------------------------------------------------------ api

    def set_theme(self, mode: str) -> None:
        for key, button in self._theme_buttons.items():
            button.setChecked(key == mode)

    def _select_theme(self, key: str) -> None:
        self.set_theme(key)
        self.theme_changed.emit(key)

    def set_history_enabled(self, enabled: bool) -> None:
        self.history_switch.blockSignals(True)
        self.history_switch.setChecked(enabled)
        self.history_switch.blockSignals(False)
        self.clear_history_button.setEnabled(enabled)

    def set_live_search(self, enabled: bool) -> None:
        self.live_search_switch.blockSignals(True)
        self.live_search_switch.setChecked(enabled)
        self.live_search_switch.blockSignals(False)

    def set_recent_count(self, count: int) -> None:
        if count:
            self.history_count.setText(f"{count} stored")
        else:
            self.history_count.setText("no stored searches")
        self.clear_history_button.setEnabled(count > 0)

    def set_sensitivity(self, value: str) -> None:
        radio = self._sensitivity_buttons.get(value)
        if radio is not None and not radio.isChecked():
            radio.setChecked(True)

    def set_database_status(self, available: bool, primary: str, detail: str = "") -> None:
        if available:
            self.database_status.setText(primary)
            self.database_chip.setText("LOADED")
            self.database_chip.set_kind("verified")
        else:
            self.database_status.setText("Gospel database not installed")
            self.database_chip.setText("MISSING")
            self.database_chip.set_kind("warn")
        self.database_detail.setText(detail)
        self.database_detail.setVisible(bool(detail))

    def set_database_path(self, path: str) -> None:
        self.database_path_label.setText(f"Active path: {path}")

    def set_import_status(
        self, text: str, *, ok: bool | None = None, busy: bool = False
    ) -> None:
        """Show the outcome of the last lyric import."""
        self.import_lyrics_button.setEnabled(not busy)
        self.import_lyrics_button.setProperty("loading", busy)
        self.import_lyrics_button.style().unpolish(self.import_lyrics_button)
        self.import_lyrics_button.style().polish(self.import_lyrics_button)
        self.import_status.setText(text)
        self.import_status.setVisible(bool(text))
        if ok is not None:
            self.import_status.setProperty("role", "accent" if ok else "muted")
            self.import_status.style().unpolish(self.import_status)
            self.import_status.style().polish(self.import_status)

    def set_validation_result(self, text: str, ok: bool) -> None:
        self.validate_button.setEnabled(True)
        self.validate_button.setProperty("loading", False)
        self.validate_button.style().unpolish(self.validate_button)
        self.validate_button.style().polish(self.validate_button)
        self.validation_state.setText("Health report ready" if ok else "Issues found")
        self.validation_result.setText(text)
        self.validation_result.setProperty("role", "accent" if ok else "muted")
        self.validation_result.style().unpolish(self.validation_result)
        self.validation_result.style().polish(self.validation_result)
        self.validation_result.show()
