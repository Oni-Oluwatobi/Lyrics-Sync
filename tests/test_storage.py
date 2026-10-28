"""Storage tests: preferences, recent searches and favorites."""

from __future__ import annotations

import json
from pathlib import Path

from lyric_sync.storage.favorites import FavoritesStore
from lyric_sync.storage.preferences import Preferences


def test_defaults(tmp_path: Path):
    preferences = Preferences.load(tmp_path / "missing.json")
    assert preferences.theme == "system"
    assert preferences.sensitivity == "balanced"
    assert preferences.search_history_enabled is True
    assert preferences.live_search is True
    assert preferences.recent_searches == []


def test_save_and_reload(tmp_path: Path):
    path = tmp_path / "preferences.json"
    preferences = Preferences.load(path)
    preferences.theme = "dark"
    preferences.sensitivity = "relaxed"
    preferences.live_search = False
    preferences.database_override = "C:/data/custom.lsdb"
    preferences.save()

    reloaded = Preferences.load(path)
    assert reloaded.theme == "dark"
    assert reloaded.sensitivity == "relaxed"
    assert reloaded.live_search is False
    assert reloaded.database_override == "C:/data/custom.lsdb"


def test_invalid_values_fall_back(tmp_path: Path):
    path = tmp_path / "preferences.json"
    path.write_text(
        json.dumps({"theme": "blue", "sensitivity": "wild", "recent_searches": "nope"}),
        encoding="utf-8",
    )
    preferences = Preferences.load(path)
    assert preferences.theme == "system"
    assert preferences.sensitivity == "balanced"
    assert preferences.recent_searches == []


def test_corrupt_file_uses_defaults(tmp_path: Path):
    path = tmp_path / "preferences.json"
    path.write_text("{ not json", encoding="utf-8")
    preferences = Preferences.load(path)
    assert preferences.theme == "system"


def test_recent_searches_order_and_dedupe(tmp_path: Path):
    preferences = Preferences.load(tmp_path / "preferences.json")
    preferences.add_recent("mighty god")
    preferences.add_recent("way maker")
    preferences.add_recent("mighty god")

    assert preferences.recent_searches == ["mighty god", "way maker"]


def test_recent_searches_limit(tmp_path: Path):
    preferences = Preferences.load(tmp_path / "preferences.json")
    for index in range(20):
        preferences.add_recent(f"query {index}")
    assert len(preferences.recent_searches) == preferences.recent_limit
    assert preferences.recent_searches[0] == "query 19"


def test_recent_searches_disabled(tmp_path: Path):
    preferences = Preferences.load(tmp_path / "preferences.json")
    preferences.search_history_enabled = False
    assert preferences.add_recent("mighty god") is False
    assert preferences.recent_searches == []


def test_recent_searches_remove_and_clear(tmp_path: Path):
    path = tmp_path / "preferences.json"
    preferences = Preferences.load(path)
    preferences.add_recent("one")
    preferences.add_recent("two")
    assert preferences.remove_recent("one") is True
    assert preferences.recent_searches == ["two"]
    assert preferences.remove_recent("missing") is False
    assert preferences.clear_recent() is True
    assert preferences.recent_searches == []
    assert Preferences.load(path).recent_searches == []


def test_favorites_lifecycle(tmp_path: Path):
    path = tmp_path / "favorites.json"
    favorites = FavoritesStore(path)

    assert favorites.add(10) is True
    assert favorites.add(10) is False
    assert favorites.add(3) is True
    assert favorites.contains(10)
    assert 10 in favorites
    assert len(favorites) == 2
    # most recent first
    assert favorites.song_ids == [3, 10]

    assert favorites.remove(10) is True
    assert favorites.remove(10) is False
    assert favorites.toggle(3) is False
    assert favorites.toggle(7) is True
    assert favorites.clear() is True
    assert len(favorites) == 0


def test_favorites_persist_without_lyrics(tmp_path: Path):
    path = tmp_path / "favorites.json"
    favorites = FavoritesStore(path)
    favorites.add(42)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["songs"] == [{"song_id": 42, "added_at": payload["songs"][0]["added_at"]}]
    serialized = path.read_text(encoding="utf-8")
    assert "lyric" not in serialized.lower()

    reloaded = FavoritesStore(path)
    assert reloaded.song_ids == [42]


def test_favorites_corrupt_file(tmp_path: Path):
    path = tmp_path / "favorites.json"
    path.write_text("not json at all", encoding="utf-8")
    favorites = FavoritesStore(path)
    assert len(favorites) == 0
    favorites.add(1)
    assert FavoritesStore(path).song_ids == [1]


def test_favorites_accepts_text_ids_and_ignores_invalid(tmp_path: Path):
    path = tmp_path / "favorites.json"
    path.write_text(
        json.dumps(
            {
                "songs": [
                    {"song_id": "hymn_amazing_grace_001"},
                    {"song_id": "42"},
                    {"song_id": {"bad": 1}},
                    {"song_id": None},
                    7,
                ]
            }
        ),
        encoding="utf-8",
    )
    favorites = FavoritesStore(path)
    assert favorites.song_ids == ["hymn_amazing_grace_001", 42, 7]
    assert favorites.contains("hymn_amazing_grace_001")
    assert favorites.contains("42") and favorites.contains(42)
    assert "hymn_amazing_grace_001" in favorites
