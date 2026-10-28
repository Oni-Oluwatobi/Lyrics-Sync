"""The dominant search field."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from lyric_sync.ui.components.widgets import GlyphLabel


class SearchBox(QWidget):
    """Large (search screen) or compact lyric search input."""

    submitted = Signal()
    query_edited = Signal(str)
    cleared = Signal()
    focus_gained = Signal()

    def __init__(self, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.compact = compact

        self.shell = QFrame()
        self.shell.setObjectName("searchShellCompact" if compact else "searchShell")
        self.shell.setFixedHeight(40 if compact else 52)

        layout = QHBoxLayout(self.shell)
        layout.setContentsMargins(14 if compact else 18, 0, 10 if compact else 12, 0)
        layout.setSpacing(10)

        icon_size = 16 if compact else 18
        self.icon = GlyphLabel("search", size=icon_size, color="muted")
        layout.addWidget(self.icon)

        self.input = QLineEdit()
        self.input.setObjectName("searchInputCompact" if compact else "searchInput")
        self.input.setFrame(False)
        self.input.setClearButtonEnabled(False)
        self.input.setAttribute(Qt.WA_MacShowFocusRect, False)
        self.input.installEventFilter(self)
        layout.addWidget(self.input, 1)

        self.hint = QLabel("CTRL K" if not compact else "ENTER")
        self.hint.setObjectName("keyHint")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

        self.clear_button = QPushButton()
        self.clear_button.setObjectName("searchClear")
        self.clear_button.setProperty("variant", "icon")
        self.clear_button.setFixedSize(26, 26)
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self._on_clear)
        layout.addWidget(self.clear_button)
        self.clear_button.hide()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.shell)

        self.input.textChanged.connect(self._on_text_changed)
        self.input.returnPressed.connect(self.submitted)
        self._sync_clear_button()

    # ------------------------------------------------------------------ api

    def text(self) -> str:
        return self.input.text()

    def set_text(self, value: str) -> None:
        self.input.blockSignals(True)
        self.input.setText(value)
        self.input.blockSignals(False)
        self._sync_clear_button()

    def set_placeholder(self, value: str) -> None:
        self.input.setPlaceholderText(value)

    def clear(self) -> None:
        self.input.blockSignals(True)
        self.input.clear()
        self.input.blockSignals(False)
        self._sync_clear_button()

    def focus_input(self, select_all: bool = False) -> None:
        self.input.setFocus(Qt.ShortcutFocusReason)
        if select_all:
            self.input.selectAll()

    @property
    def has_focus(self) -> bool:
        return self.input.hasFocus()

    def set_search_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)

    def set_loading(self, loading: bool) -> None:
        self.shell.setProperty("loading", loading)
        self._repolish(self.shell)

    # -------------------------------------------------------------- handlers

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.input:
            if event.type() == QEvent.FocusIn:
                self.shell.setProperty("active", True)
                self._repolish(self.shell)
                self.focus_gained.emit()
            elif event.type() == QEvent.FocusOut:
                self.shell.setProperty("active", False)
                self._repolish(self.shell)
        return super().eventFilter(watched, event)

    def _on_text_changed(self, value: str) -> None:
        self._sync_clear_button()
        self.query_edited.emit(value)

    def _on_clear(self) -> None:
        self.input.clear()
        self.focus_input()
        self.cleared.emit()

    def _sync_clear_button(self) -> None:
        self.clear_button.setVisible(bool(self.input.text()))
        self.hint.setVisible(not self.input.text())

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
