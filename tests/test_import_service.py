"""Tests for the in-app lyric import (lyric_sync.importing).

The importer writes the production schema, so these tests clone that schema
(DDL only — no rows) into a tiny temporary database instead of copying the
42 MB production file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lyric_sync.importing import LyricImportService

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = ROOT / "lyric_sync_gospel.lsdb"

pytestmark = pytest.mark.skipif(
    not PRODUCTION_DB.is_file(),
    reason="production database lyric_sync_gospel.lsdb not present",
)

LYRIC_FILE = """TEST IMPORT SONG - Test Import Artist
Source: unit test fixture
Published: 2026-11-21
==================================================

[Verse 1]
This is a fixture lyric line
Another fixture lyric line

[Chorus]
Sing the fixture chorus now
"""


def _schema_db(tmp_path: Path) -> Path:
    """Create an empty database with the production schema (no rows)."""
    source = sqlite3.connect(f"file:{PRODUCTION_DB}?mode=ro", uri=True)
    try:
        rows = source.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
    finally:
        source.close()

    tables: list[str] = []
    indexes: list[str] = []
    for kind, name, sql in rows:
        if kind == "table" and not name.startswith(("sqlite_", "lyric_search_fts_")):
            tables.append(sql)
        elif kind == "index" and not name.startswith("sqlite_autoindex"):
            indexes.append(sql)

    target = tmp_path / "schema.lsdb"
    connection = sqlite3.connect(target)
    try:
        for statement in tables:
            connection.execute(statement)
        for statement in indexes:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO database_metadata ("
            "database_name, database_version, schema_version, total_songs, "
            "total_artists, total_lyrics_records, total_licensed_records, "
            "total_public_domain_records, total_metadata_only_records, "
            "build_date, provenance_policy, copyright_policy, sha256_checksum, "
            "generated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "lyric_sync_gospel.lsdb", "3.4.0", "1", 0, 0, 0, 0, 0, 0,
                "2026-11-21T00:00:00Z", "test", "test", "", "test",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return target


def _query(db: Path, sql: str, params: tuple = ()):
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def test_import_creates_song_and_lyrics(tmp_path: Path) -> None:
    db = _schema_db(tmp_path)
    lyric_file = tmp_path / "test_import_song.txt"
    lyric_file.write_text(LYRIC_FILE, encoding="utf-8")

    outcome = LyricImportService(db).import_files([lyric_file])

    assert outcome.failed == []
    assert len(outcome.created) == 1
    assert outcome.upgraded == []
    assert outcome.line_total >= 3
    assert outcome.backup_path and Path(outcome.backup_path).is_file()
    assert outcome.stats["total_songs"] == 1

    rows = _query(
        db,
        "SELECT id, title, artist, copyright_status, source FROM songs "
        "WHERE normalized_title = ?",
        ("test import song",),
    )
    assert len(rows) == 1
    song_id, title, artist, copyright_status, source = rows[0]
    assert title.lower() == "test import song"
    assert artist.lower() == "test import artist"
    assert copyright_status == "USER_IMPORTED"
    assert "sha256" in source

    line_count = _query(
        db, "SELECT COUNT(*) FROM lyrics WHERE song_id = ?", (song_id,)
    )[0][0]
    assert line_count >= 3

    # search rows were rebuilt: one index row, one FTS row, findable by lyric
    assert _query(
        db, "SELECT COUNT(*) FROM lyric_search_index WHERE song_id = ?", (song_id,)
    )[0][0] == 1
    assert _query(
        db, "SELECT COUNT(*) FROM lyric_search_fts WHERE song_id = ?", (song_id,)
    )[0][0] == 1
    assert _query(
        db,
        "SELECT COUNT(*) FROM lyric_search_fts WHERE lyric_search_fts MATCH ?",
        ("fixture",),
    )[0][0] >= 1


def test_second_import_is_skipped(tmp_path: Path) -> None:
    db = _schema_db(tmp_path)
    lyric_file = tmp_path / "test_import_song.txt"
    lyric_file.write_text(LYRIC_FILE, encoding="utf-8")

    first = LyricImportService(db).import_files([lyric_file])
    assert len(first.created) == 1

    second = LyricImportService(db).import_files([lyric_file])
    assert second.created == []
    assert second.upgraded == []
    assert len(second.skipped) == 1
    assert second.stats == {}


def test_empty_lyric_file_fails_without_writing(tmp_path: Path) -> None:
    db = _schema_db(tmp_path)
    empty = tmp_path / "empty.txt"
    empty.write_text("EMPTY SONG - Nobody\nSource: none\n", encoding="utf-8")

    outcome = LyricImportService(db).import_files([empty])

    assert outcome.created == []
    assert outcome.upgraded == []
    assert len(outcome.failed) == 1
    assert _query(db, "SELECT COUNT(*) FROM songs")[0][0] == 0
    assert _query(db, "SELECT COUNT(*) FROM lyrics")[0][0] == 0


def test_unsupported_files_are_ignored(tmp_path: Path) -> None:
    image = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\n")

    outcome = LyricImportService(tmp_path / "absent.lsdb").import_files([image])

    assert outcome.created == outcome.upgraded == outcome.failed == []
    assert not (tmp_path / "absent.lsdb").exists()
