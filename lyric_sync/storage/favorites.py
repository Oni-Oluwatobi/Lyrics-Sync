"""Favorites storage.

Only song identifiers are stored — never lyrics. Works fully offline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from lyric_sync.storage.preferences import atomic_write_json


def _coerce_id(value: object) -> int | str:
    """Numeric ids stay ``int`` (legacy files); text ids stay ``str``."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
        return text
    raise TypeError(f"unsupported song id: {value!r}")


class FavoritesStore:
    """Ordered set of favorited song ids (most recent first)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[int | str, float] = {}
        self.load()

    # ------------------------------------------------------------------ I/O

    def load(self) -> None:
        self._entries = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        songs = raw.get("songs", [])
        if not isinstance(songs, list):
            return
        for item in songs:
            if isinstance(item, dict):
                song_id = item.get("song_id")
                added = item.get("added_at", 0)
            else:
                song_id, added = item, 0
            try:
                self._entries[_coerce_id(song_id)] = float(added)
            except (TypeError, ValueError):
                continue

    def save(self) -> None:
        payload = {
            "version": 1,
            "songs": [
                {"song_id": song_id, "added_at": added}
                for song_id, added in sorted(
                    self._entries.items(), key=lambda pair: -pair[1]
                )
            ],
        }
        try:
            atomic_write_json(self.path, payload)
        except OSError:
            pass

    # ------------------------------------------------------------ operations

    @property
    def song_ids(self) -> list[int | str]:
        return sorted(self._entries, key=lambda song_id: -self._entries[song_id])

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, song_id: object) -> bool:
        try:
            return _coerce_id(song_id) in self._entries
        except (TypeError, ValueError):
            return False

    def contains(self, song_id: int | str) -> bool:
        try:
            return _coerce_id(song_id) in self._entries
        except (TypeError, ValueError):
            return False

    def add(self, song_id: int | str) -> bool:
        song_id = _coerce_id(song_id)
        if song_id in self._entries:
            return False
        self._entries[song_id] = time.time()
        self.save()
        return True

    def remove(self, song_id: int | str) -> bool:
        song_id = _coerce_id(song_id)
        if song_id not in self._entries:
            return False
        del self._entries[song_id]
        self.save()
        return True

    def toggle(self, song_id: int | str) -> bool:
        """Toggle and return the new state (``True`` when now a favorite)."""
        song_id = _coerce_id(song_id)
        if song_id in self._entries:
            del self._entries[song_id]
            self.save()
            return False
        self._entries[song_id] = time.time()
        self.save()
        return True

    def clear(self) -> bool:
        if not self._entries:
            return False
        self._entries.clear()
        self.save()
        return True
