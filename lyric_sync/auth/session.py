"""Signed-in account state.  Every network call runs off the UI thread.

The session never blocks launch: ``restore()`` loads the locally stored
tokens synchronously (a file read) and only reaches out to the network
when the cached token has expired — and even then failures degrade to
"still signed out / stay signed in quietly" without touching search.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

from lyric_sync.app.dev_log import log_event
from lyric_sync.auth.firebase_client import AuthError, AuthUser, FirebaseClient
from lyric_sync.auth.secure_store import SecureStore
from lyric_sync.ui.workers import run_task

SESSION_FILENAME = "account_session.bin"
REFRESH_MARGIN_SECONDS = 90


class AuthSession(QObject):
    """Firebase Authentication session with optional, offline-safe behaviour."""

    user_changed = Signal(object)  # AuthUser | None
    busy_changed = Signal(str)  # "" when idle, else an operation label
    error = Signal(str)
    notice = Signal(str)

    def __init__(
        self,
        client: FirebaseClient | None = None,
        store: SecureStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if store is None:
            from lyric_sync.app import config

            store = SecureStore(config.user_data_dir() / SESSION_FILENAME)
        self._client = client
        self._store = store
        self._user: AuthUser | None = None
        self._busy = ""
        self._expires_at = 0.0

    # ------------------------------------------------------------- properties

    @property
    def user(self) -> AuthUser | None:
        return self._user

    @property
    def signed_in(self) -> bool:
        return self._user is not None

    @property
    def email(self) -> str | None:
        return self._user.email if self._user is not None else None

    @property
    def busy(self) -> str:
        return self._busy

    # ------------------------------------------------------------------ flows

    def restore(self) -> None:
        """Adopt the stored session immediately; refresh only when expired."""
        data = self._store.load()
        if not data:
            return
        refresh_token = str(data.get("refresh_token") or "")
        if not refresh_token:
            return
        self._user = AuthUser(
            local_id=str(data.get("local_id") or ""),
            email=str(data.get("email") or ""),
            id_token=str(data.get("id_token") or ""),
            refresh_token=refresh_token,
            expires_in=0,
        )
        try:
            self._expires_at = float(data.get("expires_at") or 0)
        except (TypeError, ValueError):
            self._expires_at = 0.0
        self.user_changed.emit(self._user)
        if self._expires_at and time.time() >= self._expires_at:
            self._refresh()

    def sign_in(self, email: str, password: str) -> None:
        client = self._ready_client()
        if client is None or not self._begin("Signing in…"):
            return
        self._launch(
            lambda: client.sign_in(email, password),
            self._adopt,
        )

    def sign_up(self, email: str, password: str) -> None:
        client = self._ready_client()
        if client is None or not self._begin("Creating account…"):
            return
        self._launch(
            lambda: client.sign_up(email, password),
            self._adopt,
        )

    def send_reset(self, email: str) -> None:
        client = self._ready_client()
        if client is None or not self._begin("Sending reset email…"):
            return

        def work():
            try:
                client.send_reset(email)
            except AuthError as exc:
                return exc
            return "sent"

        def done(result) -> None:
            self._end()
            if isinstance(result, AuthError):
                self.error.emit(result.message)
                return
            self.notice.emit(
                "Password reset email sent. Check your inbox for the link."
            )

        self._run(work, done)

    def sign_out(self) -> None:
        self._store.clear()
        self._user = None
        self._expires_at = 0.0
        self.user_changed.emit(None)

    def _refresh(self) -> None:
        """Silently refresh an expired token; offline keeps the session."""
        if self._user is None or not self._user.refresh_token:
            return
        client = self._client
        if client is None:
            from lyric_sync.auth.firebase_config import load_firebase_config

            data = load_firebase_config()
            if not data or not data.get("apiKey"):
                return
            client = FirebaseClient(str(data["apiKey"]))
            self._client = client
        if not self._begin("Refreshing session…"):
            return
        token = self._user.refresh_token
        previous = self._user

        def work():
            try:
                return client.refresh(token)
            except AuthError as exc:
                return exc

        def done(result) -> None:
            self._end()
            if isinstance(result, AuthError):
                if result.code == "network":
                    # Offline: keep the cached session quietly.
                    return
                self.sign_out()
                self.error.emit(result.message)
                return
            self._adopt(
                AuthUser(
                    local_id=result.local_id or previous.local_id,
                    email=previous.email,
                    id_token=result.id_token,
                    refresh_token=result.refresh_token or token,
                    expires_in=result.expires_in,
                )
            )

        self._run(work, done)

    # -------------------------------------------------------------- internals

    def _adopt(self, user: AuthUser) -> None:
        self._user = user
        if user.expires_in:
            self._expires_at = time.time() + max(30, user.expires_in - REFRESH_MARGIN_SECONDS)
        else:
            self._expires_at = 0.0
        self._store.save(
            {
                "local_id": user.local_id,
                "email": user.email,
                "id_token": user.id_token,
                "refresh_token": user.refresh_token,
                "expires_at": self._expires_at,
            }
        )
        self.user_changed.emit(user)

    def _ready_client(self) -> FirebaseClient | None:
        if self._client is None:
            self._client = FirebaseClient.from_config()
        if self._client is None:
            self.error.emit(
                "Account sign-in isn't available in this build "
                "(firebase_config.json was not found)."
            )
            return None
        return self._client

    def _begin(self, label: str) -> bool:
        if self._busy:
            return False
        self._busy = label
        self.busy_changed.emit(label)
        return True

    def _end(self) -> None:
        self._busy = ""
        self.busy_changed.emit("")

    def _launch(self, operation, on_result) -> None:
        def work():
            try:
                return operation()
            except AuthError as exc:
                return exc
            except Exception as exc:  # noqa: BLE001 - never crash the UI path
                log_event("auth", "unexpected authentication failure", exc)
                return AuthError(
                    "unexpected",
                    "Sign-in could not be completed. Please try again.",
                )

        def done(result) -> None:
            self._end()
            if isinstance(result, AuthError):
                self.error.emit(result.message)
                return
            on_result(result)

        self._run(work, done)

    def _run(self, work, done) -> None:
        run_task(work, on_finished=done,
                 on_error=lambda message: self._on_task_error(message))

    def _on_task_error(self, message: str) -> None:
        log_event("auth", message)
        self._end()
        self.error.emit("Sign-in could not be completed. Please try again.")
