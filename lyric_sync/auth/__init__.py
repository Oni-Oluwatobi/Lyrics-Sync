"""Optional Firebase Authentication for Lyric Sync.

Sign-in is never required: search, favorites and settings stay fully
offline.  The network code uses only the Python standard library
(``urllib``) against Google's Identity Toolkit REST API — no SDK, no
analytics, no telemetry.
"""

from lyric_sync.auth.firebase_client import AuthError, AuthUser, FirebaseClient
from lyric_sync.auth.secure_store import SecureStore
from lyric_sync.auth.session import AuthSession

__all__ = [
    "AuthError",
    "AuthSession",
    "AuthUser",
    "FirebaseClient",
    "SecureStore",
]
