"""User preferences and recent searches (local JSON, atomic writes).

The ``.LSDB`` is never written to.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from lyric_sync.app.config import DEFAULT_RECENT_LIMIT

THEMES = ("system", "light", "dark")
SENSITIVITIES = ("strict", "balanced", "relaxed")


def atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON via a temp file + rename so a crash cannot corrupt the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=path.name,
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


@dataclass
class Preferences:
    """Application settings, including the recent search list."""

    theme: str = "system"
    search_history_enabled: bool = True
    live_search: bool = True
    sensitivity: str = "balanced"
    database_override: str | None = None
    recent_searches: list[str] = field(default_factory=list)
    recent_limit: int = DEFAULT_RECENT_LIMIT

    def __post_init__(self) -> None:
        self.path: Path | None = None  # type: ignore[assignment]
        if self.theme not in THEMES:
            self.theme = "system"
        if self.sensitivity not in SENSITIVITIES:
            self.sensitivity = "balanced"
        self.recent_searches = [
            str(item)[:200] for item in self.recent_searches if str(item).strip()
        ][: self.recent_limit]

    # ------------------------------------------------------------------ I/O

    @classmethod
    def load(cls, path: Path) -> "Preferences":
        preferences = cls()
        preferences.path = path  # type: ignore[assignment]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return preferences
        if not isinstance(raw, dict):
            return preferences

        def read(key: str, default):
            value = raw.get(key, default)
            return default if value is None else value

        preferences.theme = str(read("theme", preferences.theme))
        preferences.search_history_enabled = bool(
            read("search_history_enabled", preferences.search_history_enabled)
        )
        preferences.live_search = bool(read("live_search", preferences.live_search))
        preferences.sensitivity = str(read("sensitivity", preferences.sensitivity))
        override = read("database_override", None)
        preferences.database_override = str(override) if override else None
        recent = read("recent_searches", [])
        if isinstance(recent, list):
            preferences.recent_searches = [str(item) for item in recent]
        if preferences.theme not in THEMES:
            preferences.theme = "system"
        if preferences.sensitivity not in SENSITIVITIES:
            preferences.sensitivity = "balanced"
        return preferences

    def save(self) -> None:
        if self.path is None:
            return
        payload = {
            "version": 1,
            "theme": self.theme,
            "search_history_enabled": self.search_history_enabled,
            "live_search": self.live_search,
            "sensitivity": self.sensitivity,
            "database_override": self.database_override,
            "recent_searches": self.recent_searches[: self.recent_limit],
        }
        try:
            atomic_write_json(self.path, payload)
        except OSError:
            # Preferences are non-critical: never let them break the session.
            pass

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("path", None)
        return data

    # ------------------------------------------------------------- recents

    def add_recent(self, query: str) -> bool:
        """Record a query; returns ``True`` when the list changed."""
        cleaned = " ".join(str(query).split())[:200]
        if not cleaned or not self.search_history_enabled:
            return False
        if cleaned in self.recent_searches:
            self.recent_searches.remove(cleaned)
        self.recent_searches.insert(0, cleaned)
        del self.recent_searches[self.recent_limit :]
        self.save()
        return True

    def remove_recent(self, query: str) -> bool:
        if query not in self.recent_searches:
            return False
        self.recent_searches.remove(query)
        self.save()
        return True

    def clear_recent(self) -> bool:
        if not self.recent_searches:
            return False
        self.recent_searches.clear()
        self.save()
        return True
