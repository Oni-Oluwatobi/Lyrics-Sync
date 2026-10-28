"""Account page: optional Firebase Authentication (sign in / sign up / reset).

Everything on this page is optional — search, favorites and settings never
require a network connection or an account.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app.theme import SP_LG, SP_MD, SP_SM, SP_XL
from lyric_sync.ui.components.widgets import CenterColumn


class AccountPage(QWidget):
    """Sign-in workspace driven by signals; the session object does the work."""

    sign_in_requested = Signal(str, str)  # email, password
    sign_up_requested = Signal(str, str)  # email, password
    reset_requested = Signal(str)  # email
    sign_out_requested = Signal()

    MODE_SIGN_IN = "signin"
    MODE_SIGN_UP = "signup"
    MODE_RESET = "reset"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = self.MODE_SIGN_IN

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        container = CenterColumn(max_width=560)
        self._container = container
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 20, 0, SP_XL)
        column.setSpacing(0)

        heading = QLabel("Account")
        heading.setProperty("role", "pageTitle")
        column.addWidget(heading)
        subtitle = QLabel(
            "Sign-in is optional — searching, favorites and settings work "
            "without an account."
        )
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        column.addWidget(subtitle)
        column.addSpacing(SP_LG)

        # ------------------------------------------------------ sign-in form
        self.auth_panel = QFrame()
        self.auth_panel.setObjectName("panel")
        form = QVBoxLayout(self.auth_panel)
        form.setContentsMargins(SP_XL, SP_LG, SP_XL, SP_LG)
        form.setSpacing(0)

        self.segmented = QFrame()
        self.segmented.setObjectName("segmented")
        segment_layout = QHBoxLayout(self.segmented)
        segment_layout.setContentsMargins(3, 3, 3, 3)
        segment_layout.setSpacing(2)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[str, QPushButton] = {}
        for key, label in (
            (self.MODE_SIGN_IN, "Sign in"),
            (self.MODE_SIGN_UP, "Create account"),
            (self.MODE_RESET, "Reset password"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self._mode_group.addButton(button)
            self._mode_buttons[key] = button
            segment_layout.addWidget(button)
        self._mode_buttons[self.MODE_SIGN_IN].setChecked(True)
        for key, button in self._mode_buttons.items():
            button.clicked.connect(lambda _=False, k=key: self._set_mode(k))
        form.addWidget(self.segmented)
        form.addSpacing(SP_LG)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Email")
        self.email_input.setClearButtonEnabled(True)
        form.addWidget(self.email_input)
        form.addSpacing(SP_MD)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        form.addWidget(self.password_input)
        form.addSpacing(SP_MD)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("Confirm password")
        self.confirm_input.setEchoMode(QLineEdit.Password)
        self.confirm_input.hide()
        form.addWidget(self.confirm_input)
        form.addSpacing(SP_MD)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        form.addWidget(self.error_label)
        self.info_label = QLabel("")
        self.info_label.setProperty("role", "accent")
        self.info_label.setWordWrap(True)
        self.info_label.hide()
        form.addWidget(self.info_label)
        form.addSpacing(SP_SM)

        self.submit_button = QPushButton("Sign in")
        self.submit_button.setProperty("variant", "primary")
        self.submit_button.setCursor(Qt.PointingHandCursor)
        self.submit_button.clicked.connect(self._on_submit)
        form.addWidget(self.submit_button, 0, Qt.AlignRight)

        self.busy_label = QLabel("")
        self.busy_label.setProperty("role", "caption")
        self.busy_label.setAlignment(Qt.AlignRight)
        self.busy_label.hide()
        form.addWidget(self.busy_label, 0, Qt.AlignRight)

        self.email_input.returnPressed.connect(self._on_submit)
        self.password_input.returnPressed.connect(self._on_submit)
        self.confirm_input.returnPressed.connect(self._on_submit)

        column.addWidget(self.auth_panel)
        column.addSpacing(SP_MD)

        note = QLabel(
            "Accounts are handled by Firebase Authentication over HTTPS. "
            "Your song database and search queries never leave this computer."
        )
        note.setProperty("role", "caption")
        note.setWordWrap(True)
        column.addWidget(note)
        column.addSpacing(SP_LG)

        # ------------------------------------------------------ signed-in card
        self.user_panel = QFrame()
        self.user_panel.setObjectName("panel")
        user_layout = QVBoxLayout(self.user_panel)
        user_layout.setContentsMargins(SP_XL, SP_LG, SP_XL, SP_LG)
        user_layout.setSpacing(0)

        self.user_email = QLabel("")
        self.user_email.setProperty("role", "title")
        self.user_email.setWordWrap(True)
        user_layout.addWidget(self.user_email)
        user_layout.addSpacing(SP_SM)

        signed_caption = QLabel("Signed in with Firebase Authentication.")
        signed_caption.setProperty("role", "caption")
        user_layout.addWidget(signed_caption)
        user_layout.addSpacing(SP_MD)

        self.sign_out_button = QPushButton("Sign out")
        self.sign_out_button.setProperty("variant", "danger")
        self.sign_out_button.setCursor(Qt.PointingHandCursor)
        self.sign_out_button.clicked.connect(self.sign_out_requested)
        user_layout.addWidget(self.sign_out_button, 0, Qt.AlignLeft)

        self.user_error = QLabel("")
        self.user_error.setWordWrap(True)
        self.user_error.hide()
        user_layout.addWidget(self.user_error)

        self.user_panel.hide()
        column.addWidget(self.user_panel)

        column.addStretch(1)

    # --------------------------------------------------------------- layout

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._container.sync_width(self.width())

    # ------------------------------------------------------------------ api

    def set_user(self, email: str | None) -> None:
        if email:
            self.user_email.setText(email)
            self.user_panel.show()
            self.auth_panel.hide()
        else:
            self.user_panel.hide()
            self.auth_panel.show()

    def set_busy(self, operation: str | None) -> None:
        busy = bool(operation)
        self.auth_panel.setEnabled(not busy)
        self.submit_button.setProperty("loading", busy)
        self.submit_button.style().unpolish(self.submit_button)
        self.submit_button.style().polish(self.submit_button)
        if busy:
            self.busy_label.setText(operation or "Working…")
            self.busy_label.show()
        else:
            self.busy_label.hide()
        self.user_panel.setEnabled(True)
        self.sign_out_button.setEnabled(not busy)

    def set_error(self, message: str) -> None:
        self.user_error.setText(message)
        self.user_error.setVisible(bool(message))
        if not message:
            self.error_label.hide()
            return
        # Errors belong to the form unless the user is signed in.
        if self.auth_panel.isVisible():
            self.error_label.setText(message)
            self.error_label.setProperty("state", "error")
            self.error_label.style().unpolish(self.error_label)
            self.error_label.style().polish(self.error_label)
            self.error_label.show()
            self.info_label.hide()

    def set_info(self, message: str) -> None:
        self.info_label.setText(message)
        self.info_label.setVisible(bool(message))
        if message:
            self.error_label.hide()

    # ------------------------------------------------------------ form logic

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        button = self._mode_buttons.get(mode)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        signup = mode == self.MODE_SIGN_UP
        reset = mode == self.MODE_RESET
        self.password_input.setVisible(not reset)
        self.confirm_input.setVisible(signup)
        if signup:
            self.submit_button.setText("Create account")
        elif reset:
            self.submit_button.setText("Send reset email")
        else:
            self.submit_button.setText("Sign in")
        self.set_error("")
        self.set_info("")

    def _on_submit(self) -> None:
        email = self.email_input.text().strip()
        password = self.password_input.text()
        confirm = self.confirm_input.text()

        if self._mode == self.MODE_SIGN_UP:
            error = self._validate_signup(email, password, confirm)
        elif self._mode == self.MODE_RESET:
            error = self._validate_email(email)
        else:
            error = self._validate_credentials(email, password)
        if error:
            self.set_error(error)
            return
        self.set_error("")
        self.set_info("")
        if self._mode == self.MODE_SIGN_UP:
            self.sign_up_requested.emit(email, password)
        elif self._mode == self.MODE_RESET:
            self.reset_requested.emit(email)
        else:
            self.sign_in_requested.emit(email, password)

    @staticmethod
    def _validate_email(email: str) -> str:
        if not email or "@" not in email or email.startswith("@"):
            return "Enter a valid email address."
        return ""

    @classmethod
    def _validate_credentials(cls, email: str, password: str) -> str:
        base = cls._validate_email(email)
        if base:
            return base
        if not password:
            return "Enter your password."
        return ""

    @classmethod
    def _validate_signup(cls, email: str, password: str, confirm: str) -> str:
        base = cls._validate_credentials(email, password)
        if base:
            return base
        if len(password) < 6:
            return "Password must be at least 6 characters."
        if password != confirm:
            return "The passwords do not match."
        return ""
