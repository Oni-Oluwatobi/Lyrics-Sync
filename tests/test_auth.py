"""Firebase Authentication: client, secure store, session — no network.

Every HTTP call is faked through the client's ``transport`` hook or a fake
client object; no test touches the network.
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from lyric_sync.auth.firebase_client import (
    AuthError,
    AuthUser,
    FirebaseClient,
    friendly_message,
)
from lyric_sync.auth.firebase_config import load_firebase_config
from lyric_sync.auth.secure_store import SecureStore

SIGNIN_PAYLOAD = {
    "localId": "user-123",
    "email": "singer@example.com",
    "idToken": "id-token-1",
    "refreshToken": "refresh-token-1",
    "expiresIn": "3600",
    "registered": True,
}


def _transport_ok(payload: dict):
    body = json.dumps(payload).encode("utf-8")

    def transport(request, timeout):
        transport.last_request = request
        transport.last_timeout = timeout
        return body

    transport.last_request = None
    return transport


def _http_error(message: str) -> HTTPError:
    body = json.dumps({"error": {"code": 400, "message": message}}).encode("utf-8")
    return HTTPError(
        "https://example.invalid/", 400, "Bad Request", {}, io.BytesIO(body)
    )


class TestFirebaseClient:
    def test_sign_in_posts_to_identity_toolkit(self):
        transport = _transport_ok(SIGNIN_PAYLOAD)
        client = FirebaseClient("test-key", transport=transport)
        user = client.sign_in("singer@example.com", "secret123")

        request = transport.last_request
        assert request.full_url.startswith(
            "https://identitytoolkit.googleapis.com/v1/"
            "accounts:signInWithPassword?key=test-key"
        )
        sent = json.loads(request.data.decode("utf-8"))
        assert sent == {
            "email": "singer@example.com",
            "password": "secret123",
            "returnSecureToken": True,
        }
        assert user.local_id == "user-123"
        assert user.email == "singer@example.com"
        assert user.id_token == "id-token-1"
        assert user.refresh_token == "refresh-token-1"
        assert user.expires_in == 3600
        assert user.registered is True

    def test_sign_up_uses_the_signup_endpoint(self):
        transport = _transport_ok(
            {**SIGNIN_PAYLOAD, "email": "new@example.com", "registered": False}
        )
        client = FirebaseClient("k", transport=transport)
        user = client.sign_up("new@example.com", "secret123")
        assert "accounts:signUp?key=k" in transport.last_request.full_url
        assert user.email == "new@example.com"
        assert user.registered is False

    def test_send_reset_uses_send_oob_code(self):
        transport = _transport_ok({})
        client = FirebaseClient("k", transport=transport)
        assert client.send_reset("singer@example.com") is None
        assert "accounts:sendOobCode?key=k" in transport.last_request.full_url
        sent = json.loads(transport.last_request.data.decode("utf-8"))
        assert sent == {
            "requestType": "PASSWORD_RESET",
            "email": "singer@example.com",
        }

    def test_refresh_uses_securetoken_endpoint(self):
        transport = _transport_ok(
            {
                "user_id": "user-123",
                "id_token": "id-token-2",
                "refresh_token": "refresh-token-2",
                "expires_in": "3600",
            }
        )
        client = FirebaseClient("k", transport=transport)
        user = client.refresh("refresh-token-1")
        assert transport.last_request.full_url.startswith(
            "https://securetoken.googleapis.com/v1/token?key=k"
        )
        sent = json.loads(transport.last_request.data.decode("utf-8"))
        assert sent["grant_type"] == "refresh_token"
        assert sent["refresh_token"] == "refresh-token-1"
        assert user.id_token == "id-token-2"
        assert user.refresh_token == "refresh-token-2"
        assert user.email == ""

    def test_get_account_returns_first_user_record(self):
        transport = _transport_ok(
            {"users": [{"localId": "u1", "email": "a@b.c", "emailVerified": True}]}
        )
        client = FirebaseClient("k", transport=transport)
        account = client.get_account("id-token-1")
        assert "accounts:getAccountInfo?key=k" in transport.last_request.full_url
        assert account["localId"] == "u1"

    def test_http_error_maps_to_friendly_message(self):
        def transport(request, timeout):
            raise _http_error("INVALID_PASSWORD")

        client = FirebaseClient("k", transport=transport)
        with pytest.raises(AuthError) as excinfo:
            client.sign_in("a@b.c", "wrong")
        assert excinfo.value.code == "INVALID_PASSWORD"
        assert "email or password" in excinfo.value.message.lower()

    def test_unknown_http_error_code_falls_back(self):
        def transport(request, timeout):
            raise _http_error("SOME_NEW_CODE")

        client = FirebaseClient("k", transport=transport)
        with pytest.raises(AuthError) as excinfo:
            client.sign_in("a@b.c", "pw")
        assert excinfo.value.code == "SOME_NEW_CODE"
        assert "please try again" in excinfo.value.message.lower()

    def test_network_error_is_reported_as_offline(self):
        def transport(request, timeout):
            raise URLError("unreachable")

        client = FirebaseClient("k", transport=transport)
        with pytest.raises(AuthError) as excinfo:
            client.sign_in("a@b.c", "pw")
        assert excinfo.value.code == "network"
        assert "offline" in excinfo.value.message.lower()

    def test_unreadable_body_is_a_protocol_error(self):
        def transport(request, timeout):
            return b"not json"

        client = FirebaseClient("k", transport=transport)
        with pytest.raises(AuthError) as excinfo:
            client.sign_in("a@b.c", "pw")
        assert excinfo.value.code == "protocol"

    def test_from_config_requires_an_api_key(self):
        assert FirebaseClient.from_config({}) is None
        assert FirebaseClient.from_config(None) is None or isinstance(
            FirebaseClient.from_config(None), FirebaseClient
        )
        client = FirebaseClient.from_config({"apiKey": "abc"})
        assert client is not None and client.api_key == "abc"


class TestFriendlyMessage:
    def test_known_codes(self):
        assert "disabled" in friendly_message("USER_DISABLED").lower()
        assert "stronger" in friendly_message("WEAK_PASSWORD").lower()

    def test_unknown_code_falls_back(self):
        assert "please try again" in friendly_message("??").lower()


class TestSecureStore:
    def test_roundtrip(self, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        store.save({"refresh_token": "rt-1", "email": "a@b.c"})
        assert store.load() == {"refresh_token": "rt-1", "email": "a@b.c"}

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert SecureStore(tmp_path / "absent.bin").load() is None

    def test_clear_removes_the_file(self, tmp_path: Path):
        path = tmp_path / "session.bin"
        store = SecureStore(path)
        store.save({"refresh_token": "rt"})
        store.clear()
        assert not path.exists()
        assert store.load() is None

    def test_corrupted_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.bin"
        path.write_bytes(b"\x00\x01\x02 not json")
        assert SecureStore(path).load() is None

    def test_plain_json_fallback_still_loads(self, tmp_path: Path):
        """A file written without DPAPI (fallback) remains readable."""
        path = tmp_path / "session.bin"
        path.write_bytes(json.dumps({"refresh_token": "rt"}).encode("utf-8"))
        assert SecureStore(path).load() == {"refresh_token": "rt"}


class TestFirebaseConfigLoader:
    def test_load_from_explicit_path(self, tmp_path: Path):
        cfg = tmp_path / "firebase_config.json"
        cfg.write_text(json.dumps({"apiKey": "abc"}), encoding="utf-8")
        assert load_firebase_config(cfg) == {"apiKey": "abc"}

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert load_firebase_config(tmp_path / "nope.json") is None

    def test_invalid_json_returns_none(self, tmp_path: Path):
        cfg = tmp_path / "firebase_config.json"
        cfg.write_text("{broken", encoding="utf-8")
        assert load_firebase_config(cfg) is None

    def test_file_without_api_key_is_ignored(self, tmp_path: Path):
        cfg = tmp_path / "firebase_config.json"
        cfg.write_text(json.dumps({"projectId": "x"}), encoding="utf-8")
        assert load_firebase_config(cfg) is None


# --------------------------------------------------------------------------
# AuthSession — Qt signals, faked client, still no network.
# --------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyric_sync.auth.session import AuthSession  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(["lyric_sync_auth_tests"])
    yield app


def _pump(app: QApplication, ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait(app: QApplication, predicate, timeout_ms: int = 10000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if predicate():
            return True
        _pump(app, 25)
    return bool(predicate())


class FakeClient:
    """Records calls; returns canned users or raises canned errors."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_with: Exception | None = None
        self.refresh_user = AuthUser("u1", "", "id-2", "refresh-2", 3600)

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def sign_in(self, email: str, password: str) -> AuthUser:
        self.calls.append(("sign_in", email, password))
        self._maybe_fail()
        return AuthUser("u1", email, "id-1", "refresh-1", 3600)

    def sign_up(self, email: str, password: str) -> AuthUser:
        self.calls.append(("sign_up", email, password))
        self._maybe_fail()
        return AuthUser("u1", email, "id-1", "refresh-1", 3600)

    def send_reset(self, email: str) -> None:
        self.calls.append(("send_reset", email))
        self._maybe_fail()

    def refresh(self, refresh_token: str) -> AuthUser:
        self.calls.append(("refresh", refresh_token))
        self._maybe_fail()
        return self.refresh_user


class TestAuthSession:
    def test_sign_in_success_updates_user_and_store(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        users: list[object] = []
        busy: list[str] = []
        session.user_changed.connect(users.append)
        session.busy_changed.connect(busy.append)

        session.sign_in("singer@example.com", "pw1234")
        assert _wait(qapp, lambda: bool(users))
        assert session.signed_in is True
        assert session.email == "singer@example.com"
        assert client.calls == [("sign_in", "singer@example.com", "pw1234")]
        assert store.load() is not None
        assert store.load()["refresh_token"] == "refresh-1"
        assert busy[0] == "Signing in…"
        assert session.busy == ""

    def test_sign_in_failure_emits_error_and_stays_signed_out(
        self, qapp, tmp_path: Path
    ):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        client.fail_with = AuthError(
            "INVALID_PASSWORD", "The email or password is incorrect."
        )
        session = AuthSession(client=client, store=store)
        errors: list[str] = []
        session.error.connect(errors.append)

        session.sign_in("singer@example.com", "wrong")
        assert _wait(qapp, lambda: bool(errors))
        assert "email or password" in errors[0].lower()
        assert session.signed_in is False
        assert store.load() is None
        assert session.busy == ""

    def test_sign_out_clears_store_and_emits_none(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        users: list[object] = []
        session.user_changed.connect(users.append)

        session.sign_in("a@b.c", "pw1234")
        assert _wait(qapp, lambda: session.signed_in)
        session.sign_out()
        assert session.signed_in is False
        assert session.email is None
        assert store.load() is None
        assert users[-1] is None

    def test_sign_up_success(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        users: list[object] = []
        session.user_changed.connect(users.append)

        session.sign_up("new@example.com", "pw1234")
        assert _wait(qapp, lambda: bool(users))
        assert client.calls == [("sign_up", "new@example.com", "pw1234")]
        assert session.email == "new@example.com"

    def test_send_reset_success_notices_the_user(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        notices: list[str] = []
        session.notice.connect(notices.append)

        session.send_reset("singer@example.com")
        assert _wait(qapp, lambda: bool(notices))
        assert "reset email sent" in notices[0].lower()
        assert client.calls == [("send_reset", "singer@example.com")]

    def test_send_reset_failure_reports_error(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        client.fail_with = AuthError("EMAIL_NOT_FOUND", "Unknown email.")
        session = AuthSession(client=client, store=store)
        errors: list[str] = []
        session.error.connect(errors.append)

        session.send_reset("missing@example.com")
        assert _wait(qapp, lambda: bool(errors))
        assert "unknown email" in errors[0].lower()

    def test_restore_adopts_stored_session_without_network(
        self, qapp, tmp_path: Path
    ):
        store = SecureStore(tmp_path / "session.bin")
        store.save(
            {
                "local_id": "u1",
                "email": "a@b.c",
                "id_token": "id-1",
                "refresh_token": "refresh-1",
                "expires_at": time.time() + 3600,
            }
        )
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        users: list[object] = []
        session.user_changed.connect(users.append)

        session.restore()  # synchronous adoption
        assert users and users[-1] is not None
        assert session.email == "a@b.c"
        assert client.calls == []  # not expired → no network

    def test_restore_refreshes_an_expired_token(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        store.save(
            {
                "local_id": "u1",
                "email": "a@b.c",
                "id_token": "old",
                "refresh_token": "refresh-1",
                "expires_at": time.time() - 10,
            }
        )
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        users: list[object] = []
        session.user_changed.connect(users.append)

        session.restore()
        assert _wait(qapp, lambda: session.user is not None and
                     session.user.id_token == "id-2")
        assert session.email == "a@b.c"  # refresh response has no email
        assert ("refresh", "refresh-1") in client.calls
        assert store.load()["id_token"] == "id-2"
        assert session.busy == ""

    def test_offline_refresh_keeps_the_session(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        store.save(
            {
                "local_id": "u1",
                "email": "a@b.c",
                "id_token": "old",
                "refresh_token": "refresh-1",
                "expires_at": time.time() - 10,
            }
        )
        client = FakeClient()
        client.fail_with = AuthError("network", "You appear to be offline.")
        session = AuthSession(client=client, store=store)
        errors: list[str] = []
        session.error.connect(errors.append)

        session.restore()
        assert _wait(qapp, lambda: session.busy == "")
        assert session.signed_in is True
        assert session.email == "a@b.c"
        assert errors == []

    def test_invalid_refresh_token_signs_out(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        store.save(
            {
                "local_id": "u1",
                "email": "a@b.c",
                "id_token": "old",
                "refresh_token": "bad",
                "expires_at": time.time() - 10,
            }
        )
        client = FakeClient()
        client.fail_with = AuthError(
            "INVALID_REFRESH_TOKEN", "Your session expired. Please sign in again."
        )
        session = AuthSession(client=client, store=store)
        errors: list[str] = []
        session.error.connect(errors.append)

        session.restore()
        assert _wait(qapp, lambda: session.signed_in is False)
        assert store.load() is None
        assert errors and "session expired" in errors[0].lower()

    def test_sign_in_without_configuration_reports_it(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        session = AuthSession(client=None, store=store)
        errors: list[str] = []
        session.error.connect(errors.append)

        from lyric_sync.auth import firebase_client as fc

        original = fc.FirebaseClient.from_config.__func__
        fc.FirebaseClient.from_config = classmethod(
            lambda cls, config=None, **kwargs: None
        )
        try:
            session.sign_in("a@b.c", "pw1234")
        finally:
            fc.FirebaseClient.from_config = classmethod(original)
        assert errors and "firebase_config.json" in errors[0]
        assert session.signed_in is False

    def test_requests_are_ignored_while_busy(self, qapp, tmp_path: Path):
        store = SecureStore(tmp_path / "session.bin")
        client = FakeClient()
        session = AuthSession(client=client, store=store)
        users: list[object] = []
        session.user_changed.connect(users.append)

        session.sign_in("a@b.c", "pw1234")
        session.sign_in("b@c.d", "pw1234")  # ignored: first still in flight
        assert _wait(qapp, lambda: bool(users))
        assert len(client.calls) == 1
        assert client.calls[0][1] == "a@b.c"
