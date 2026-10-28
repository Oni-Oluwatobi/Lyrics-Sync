"""Firebase Identity Toolkit REST client — stdlib only.

Uses Google's public web API endpoints with the web API key from
``firebase_config.json``.  No SDK, no service accounts, no analytics.
All exceptions surface as :class:`AuthError` with a user-friendly message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

IDENTITY_BASE = "https://identitytoolkit.googleapis.com/v1"
SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
DEFAULT_TIMEOUT = 12.0

NETWORK_MESSAGE = (
    "You appear to be offline. Sign-in is optional — searching and "
    "everything else keep working without it."
)

FRIENDLY_ERRORS = {
    "EMAIL_EXISTS": "An account with this email already exists.",
    "EMAIL_NOT_FOUND": "The email or password is incorrect.",
    "INVALID_PASSWORD": "The email or password is incorrect.",
    "INVALID_LOGIN_CREDENTIALS": "The email or password is incorrect.",
    "USER_DISABLED": "This account has been disabled.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": (
        "Too many attempts. Please wait a moment and try again."
    ),
    "OPERATION_NOT_ALLOWED": (
        "Email/password sign-in is not enabled for this project. "
        "Enable it in the Firebase console (Authentication → Sign-in method)."
    ),
    "WEAK_PASSWORD": "Please choose a stronger password (at least 6 characters).",
    "INVALID_EMAIL": "Enter a valid email address.",
    "MISSING_PASSWORD": "Enter your password.",
    "MISSING_EMAIL": "Enter your email address.",
    "INVALID_REFRESH_TOKEN": "Your session expired. Please sign in again.",
    "USER_NOT_FOUND": "Your session expired. Please sign in again.",
    "TOKEN_EXPIRED": "Your session expired. Please sign in again.",
}


class AuthError(Exception):
    """Authentication failure with a stable ``code`` and friendly message."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or message


@dataclass(frozen=True)
class AuthUser:
    """Signed-in account state from Firebase Authentication."""

    local_id: str
    email: str
    id_token: str
    refresh_token: str
    expires_in: int
    registered: bool = True


def friendly_message(code: str) -> str:
    return FRIENDLY_ERRORS.get(
        code, "Sign-in could not be completed. Please try again."
    )


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


class FirebaseClient:
    """Thin REST wrapper around the Firebase Identity Toolkit endpoints."""

    def __init__(
        self,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Callable[[Request, float], bytes] | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport or _default_transport

    @classmethod
    def from_config(
        cls, config: dict | None = None, **kwargs
    ) -> "FirebaseClient | None":
        """Build a client from ``firebase_config.json``; ``None`` if missing."""
        data = config
        if data is None:
            from lyric_sync.auth.firebase_config import load_firebase_config

            data = load_firebase_config()
        key = (data or {}).get("apiKey")
        if not key:
            return None
        return cls(str(key), **kwargs)

    # ----------------------------------------------------------------- HTTP

    def _post_json(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            raw = self._transport(request, self.timeout)
        except HTTPError as exc:
            raise _error_from_http(exc) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise AuthError("network", NETWORK_MESSAGE, detail=str(exc)) from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuthError(
                "protocol",
                "The sign-in service returned an unreadable response.",
                detail=str(exc),
            ) from exc
        if not isinstance(data, dict):
            raise AuthError(
                "protocol",
                "The sign-in service returned an unexpected response.",
            )
        return data

    def _endpoint(self, path: str) -> str:
        return f"{IDENTITY_BASE}/{path}?key={self.api_key}"

    # ------------------------------------------------------------ operations

    def sign_in(self, email: str, password: str) -> AuthUser:
        data = self._post_json(
            self._endpoint("accounts:signInWithPassword"),
            {"email": email, "password": password, "returnSecureToken": True},
        )
        return _user_from_payload(data, registered=True)

    def sign_up(self, email: str, password: str) -> AuthUser:
        data = self._post_json(
            self._endpoint("accounts:signUp"),
            {"email": email, "password": password, "returnSecureToken": True},
        )
        return _user_from_payload(
            data, registered=bool(data.get("registered", True))
        )

    def send_reset(self, email: str) -> None:
        self._post_json(
            self._endpoint("accounts:sendOobCode"),
            {"requestType": "PASSWORD_RESET", "email": email},
        )

    def refresh(self, refresh_token: str) -> AuthUser:
        data = self._post_json(
            f"{SECURE_TOKEN_URL}?key={self.api_key}",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        try:
            expires_in = int(data.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        return AuthUser(
            local_id=str(data.get("user_id", "")),
            email="",
            id_token=str(data.get("id_token", "")),
            refresh_token=str(data.get("refresh_token", "") or refresh_token),
            expires_in=expires_in,
        )

    def get_account(self, id_token: str) -> dict:
        """``accounts:getAccountInfo`` — returns the first user record."""
        data = self._post_json(
            self._endpoint("accounts:getAccountInfo"),
            {"idToken": id_token},
        )
        users = data.get("users")
        if isinstance(users, list) and users and isinstance(users[0], dict):
            return users[0]
        return {}


def _error_from_http(exc: HTTPError) -> AuthError:
    message = ""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error", {})
        if isinstance(error, dict):
            message = str(error.get("message", ""))
    except (ValueError, AttributeError, OSError):
        message = ""
    code = message.split(" ")[0] if message else f"http_{exc.code}"
    return AuthError(code, friendly_message(code), detail=message or str(exc))


def _user_from_payload(data: dict, registered: bool) -> AuthUser:
    try:
        expires_in = int(data.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600
    return AuthUser(
        local_id=str(data.get("localId", "")),
        email=str(data.get("email", "")),
        id_token=str(data.get("idToken", "")),
        refresh_token=str(data.get("refreshToken", "")),
        expires_in=expires_in,
        registered=registered,
    )
