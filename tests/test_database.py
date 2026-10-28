"""Database layer tests: open, validate, query, fail-safes."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from lyric_sync.database.database_validator import (
    DatabaseNotFoundError,
    DatabaseValidationError,
    validate_file,
)
from lyric_sync.database.lsdb_manager import LSDBManager
from lyric_sync.models.song import METADATA_ONLY, PUBLIC_DOMAIN
from lyric_sync.search.search_engine import LyricSearchEngine


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------- missing


def test_open_missing_database_raises(missing_db: Path):
    manager = LSDBManager(missing_db)
    with pytest.raises(DatabaseNotFoundError):
        manager.open()


def test_validate_missing_database_reports_failure(missing_db: Path):
    report = validate_file(missing_db, deep=False)
    assert report.ok is False
    assert report.errors[0].name == "File exists"


def test_engine_without_open_manager_is_unavailable(missing_db: Path):
    engine = LyricSearchEngine(LSDBManager(missing_db))
    response = engine.search("mighty god")
    assert response.database_available is False
    assert response.results == []


# ----------------------------------------------------------------------- valid


def test_open_and_counts(manager: LSDBManager):
    info = manager.info(deep_check=False)
    assert info.song_count == 8
    assert info.artist_count == 4
    assert info.lyric_line_count == 20
    assert info.fts_available is True
    assert "songs_fts" in info.fts_tables
    assert info.version
    assert info.schema_version == "1"
    assert info.size_bytes > 0
    assert info.copyright_stats.get(PUBLIC_DOMAIN, 0) >= 1
    assert info.verification_stats


def test_song_metadata(manager: LSDBManager):
    song = manager.get_song(1)
    assert song is not None
    assert song.title == "The Great I Am"
    assert song.artist == "The Kreadive Galaxy Test Ensemble"
    assert song.album == "Signals of Praise"
    assert song.year == 2021
    assert song.category == "Worship"
    assert song.verification_status == "VERIFIED"
    assert "Great I AM, The" in song.aliases


def test_unknown_song_returns_none(manager: LSDBManager):
    assert manager.get_song(99999) is None


def test_lyrics_sections_are_ordered(manager: LSDBManager):
    lyrics = manager.get_lyrics(1)
    assert lyrics.available is True
    labels = [section.display_label for section in lyrics.sorted_sections()]
    assert labels[0].startswith("Verse")
    assert any(label.startswith("Chorus") for label in labels)
    assert "You are the mighty God, the great I AM" in lyrics.plain_lines


def test_metadata_only_song_has_no_lyrics(manager: LSDBManager):
    lyrics = manager.get_lyrics(3)
    assert lyrics.available is False
    assert lyrics.is_empty
    assert manager.get_song(3).copyright_status == METADATA_ONLY


def test_fts_match_returns_song_ids(manager: LSDBManager):
    hits = manager.fts_match("songs_fts", "mighty", 10)
    assert hits and hits[0][0] == 1


def test_validation_passes_on_fixture(fixture_db: Path):
    report = validate_file(fixture_db, deep=True)
    assert report.ok is True
    assert report.errors == []
    assert "Songs table" in report.to_text()


# -------------------------------------------------------------------- failures


def test_invalid_file_is_rejected(tmp_path: Path):
    bogus = tmp_path / "bogus.lsdb"
    bogus.write_bytes(b"This is not a database at all")
    report = validate_file(bogus, deep=True)
    assert report.ok is False
    assert any(check.name == "SQLite header" for check in report.errors)

    with pytest.raises(DatabaseValidationError):
        LSDBManager(bogus).open()


def test_schema_mismatch_is_reported(tmp_path: Path):
    target = tmp_path / "schema_mismatch.lsdb"
    connection = sqlite3.connect(str(target))
    connection.execute("CREATE TABLE songs (id INTEGER PRIMARY KEY, artist TEXT)")
    connection.commit()
    connection.close()

    report = validate_file(target, deep=False)
    assert report.ok is False

    with pytest.raises(DatabaseValidationError):
        LSDBManager(target).open()


def test_missing_songs_table_is_reported(tmp_path: Path):
    target = tmp_path / "no_songs.lsdb"
    connection = sqlite3.connect(str(target))
    connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(DatabaseValidationError):
        LSDBManager(target).open()


def test_database_without_fts_still_searches(tmp_path: Path):
    target = tmp_path / "no_fts.lsdb"
    connection = sqlite3.connect(str(target))
    connection.execute(
        "CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT, artist TEXT,"
        " copyright_status TEXT, verification_status TEXT, lyrics_status TEXT)"
    )
    connection.execute(
        "CREATE TABLE lyric_lines (id INTEGER PRIMARY KEY, song_id INTEGER,"
        " line_index INTEGER, text TEXT)"
    )
    connection.executemany(
        "INSERT INTO songs (id, title, artist, copyright_status, verification_status,"
        " lyrics_status) VALUES (?, ?, ?, 'PUBLIC_DOMAIN', 'VERIFIED', 'AVAILABLE')",
        [(1, "Rivers of Mercy", "Fixture Voices")],
    )
    connection.execute(
        "INSERT INTO lyric_lines (song_id, line_index, text) VALUES (1, 0,"
        " 'There is a river, wide and free')"
    )
    connection.commit()
    connection.close()

    report = validate_file(target, deep=False)
    assert report.ok is True
    assert any(
        check.name == "Full-text index" and check.status == "WARN"
        for check in report.checks
    )

    manager = LSDBManager(target)
    manager.open()
    try:
        engine = LyricSearchEngine(manager)
        response = engine.search("river of mercy")
        assert response.results
        assert response.results[0].song.id == 1
    finally:
        manager.close()


def test_corrupted_file_fails_integrity_check(fixture_db: Path, tmp_path: Path):
    damaged = tmp_path / "damaged.lsdb"
    data = bytearray(fixture_db.read_bytes())
    # Overwrite part of the first table b-tree page.
    for offset in range(4096, 4200):
        data[offset] = 0xFF
    damaged.write_bytes(bytes(data))

    report = validate_file(damaged, deep=True)
    assert report.ok is False


def test_search_never_modifies_the_database(fixture_db: Path, manager: LSDBManager):
    before = _sha256(fixture_db)
    engine = LyricSearchEngine(manager)
    for query in ("mighty god", "amazing grace", "you are the mighty god"):
        engine.search(query)
    assert _sha256(fixture_db) == before


def test_database_is_read_only(manager: LSDBManager):
    with pytest.raises(sqlite3.Error):
        manager.connection().execute(
            "INSERT INTO songs (id, title) VALUES (999, 'hacked')"
        )


def test_parameters_are_bound_not_interpolated(manager: LSDBManager):
    # Hostile input must never become SQL.
    assert manager.get_song(-1) is None
    assert manager.get_song(1) is not None
    rows = manager.song_ids_matching_title("%")
    assert isinstance(rows, list)


# ------------------------------------------------------------------ song ids


def test_get_song_keeps_existing_integer_ids(manager: LSDBManager):
    song = manager.get_song(1)
    assert song is not None
    assert song.id == 1


def test_get_song_accepts_digit_string_id(manager: LSDBManager):
    # SQLite type affinity matches '1' against the integer column; no crash.
    song = manager.get_song("1")
    assert song is not None
    assert song.id == 1


def test_get_song_missing_text_id_returns_none(manager: LSDBManager):
    assert manager.get_song("song_does_not_exist") is None
    assert manager.get_song("999999") is None


def test_get_song_rejects_malformed_ids(manager: LSDBManager):
    for bad in (None, "", "   ", 1.5, True, object()):
        assert manager.get_song(bad) is None  # type: ignore[arg-type]


def test_get_songs_handles_mixed_and_invalid_ids(manager: LSDBManager):
    songs = manager.get_songs([1, "2", "missing", None, ""])
    assert 1 in songs
    assert 2 in songs
    assert len(songs) == 2


def test_get_lyrics_with_text_id_returns_lyrics(manager: LSDBManager):
    lyrics = manager.get_lyrics("1")
    assert lyrics.available is True
    assert not lyrics.is_empty


def test_get_lyrics_malformed_id_is_graceful(manager: LSDBManager):
    lyrics = manager.get_lyrics(None)  # type: ignore[arg-type]
    assert lyrics.available is False
    assert lyrics.is_empty
