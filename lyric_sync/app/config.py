"""Application configuration, branding constants and path resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Lyric Sync"
APP_ID = "LyricSync"
DEVELOPER = "The Kreadive Galaxy"
VERSION = "1.5.2"

DATABASE_FILENAME = "lyric_sync_gospel.lsdb"
DATABASE_DIRNAME = "data"
ENV_DATABASE = "LYRIC_SYNC_DATABASE"
ENV_USER_DATA = "LYRIC_SYNC_USER_DATA"

PREFERENCES_FILENAME = "preferences.json"
FAVORITES_FILENAME = "favorites.json"

DEFAULT_RECENT_LIMIT = 12


# ---------------------------------------------------------------------------
# Runtime locations
# ---------------------------------------------------------------------------


def is_frozen() -> bool:
    """True when running from a packaged (PyInstaller) build."""
    return bool(getattr(sys, "frozen", False))


def executable_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    if sys.argv and sys.argv[0]:
        try:
            return Path(sys.argv[0]).resolve().parent
        except OSError:
            pass
    return Path.cwd()


def package_dir() -> Path:
    """The ``lyric_sync`` package directory."""
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """Source checkout root (contains ``main.py``, ``data/``, ``requirements.txt``)."""
    return package_dir().parent


def bundle_dir() -> Path | None:
    """PyInstaller extraction directory, when present."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    return Path(meipass)


def user_data_dir() -> Path:
    """Writable per-user directory for preferences, favorites and caches.

    Never touches the ``.LSDB`` database.
    """
    override = os.environ.get(ENV_USER_DATA)
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        path = base / APP_ID
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        path = base / APP_ID
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path.cwd() / f".{APP_ID}"
        path.mkdir(parents=True, exist_ok=True)
    return path


def preferences_path() -> Path:
    return user_data_dir() / PREFERENCES_FILENAME


def favorites_path() -> Path:
    return user_data_dir() / FAVORITES_FILENAME


# ---------------------------------------------------------------------------
# Database path resolution
# ---------------------------------------------------------------------------


def candidate_database_paths(override: str | os.PathLike[str] | None = None) -> list[tuple[str, Path]]:
    """Ordered candidate locations for the ``.LSDB`` file.

    The first entry that exists on disk wins. Entries are labelled so the UI can
    explain where the application looked.
    """
    name = DATABASE_FILENAME
    seen: set[Path] = set()
    candidates: list[tuple[str, Path]] = []

    def add(label: str, path: Path) -> None:
        try:
            resolved = Path(path)
        except (TypeError, ValueError):
            return
        key = resolved
        if key in seen:
            return
        seen.add(key)
        candidates.append((label, resolved))

    env = os.environ.get(ENV_DATABASE)
    if env:
        add("environment: " + ENV_DATABASE, Path(env))
    if override:
        add("configured override", Path(override))

    cwd = Path.cwd()
    add("current directory", cwd / DATABASE_DIRNAME / name)
    add("current directory (flat)", cwd / name)

    root = project_root()
    add("project data directory", root / DATABASE_DIRNAME / name)
    add("project root", root / name)
    add("package data directory", package_dir() / DATABASE_DIRNAME / name)

    exe_dir = executable_dir()
    add("application directory", exe_dir / DATABASE_DIRNAME / name)
    add("application directory (flat)", exe_dir / name)

    bundle = bundle_dir()
    if bundle is not None:
        add("packaged resources", bundle / DATABASE_DIRNAME / name)
        add("packaged resources (flat)", bundle / name)

    # Per-user writable location — the drop-in fallback for packaged builds.
    # Signed macOS .app bundles and "Program Files" installs are read-only, so
    # users cannot place the database beside the executable there.
    user = user_data_dir()
    add("user data directory", user / DATABASE_DIRNAME / name)
    add("user data directory (flat)", user / name)

    return candidates


def expected_database_display_path() -> str:
    """Human readable path shown to developers while the database is missing."""
    return f"{DATABASE_DIRNAME}/{DATABASE_FILENAME}"


def resolve_database_path(
    override: str | os.PathLike[str] | None = None,
) -> tuple[Path, str | None]:
    """Return ``(path, source_label)``.

    ``source_label`` is ``None`` when no candidate exists yet; in that case the
    returned path is the canonical development location so the UI can report it.
    """
    for label, path in candidate_database_paths(override):
        if path.is_file():
            return path, label
        if label.startswith("environment: ") or label == "configured override":
            # An explicitly chosen location must not silently fall back to
            # another copy — the interface reports it as missing instead.
            return path, label
    root = project_root()
    return root / DATABASE_DIRNAME / DATABASE_FILENAME, None
