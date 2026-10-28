"""Regression tests for bugs that only appear with real lyrics on the page.

Two production-only defects are pinned here:

* ``export_staging(include_lyrics=True)`` crashed with ``KeyError:
  'line_normalized'`` because the staging query omitted the column that
  ``_lyric_rows`` reads back.
* every hymn of a Gutenberg book shares one ``source_url``, so the deduplicator
  collapsed an entire 547-hymn book into a single song.
"""
from __future__ import annotations

import sqlite3

from lyrics_scraper.adapters import get_adapter
from lyrics_scraper.dedupe import INSERT, DedupIndex, apply_insert, decide
from lyrics_scraper.export import export_staging
from lyrics_scraper.gutenberg import parse_page
from lyrics_scraper.normalize import normalize
from lyrics_scraper.staging import StagingDatabase
from lyrics_scraper.validate import validate_song

from test_gutenberg import BOOK_URL, CHB_BOOK, page


def _stage_gutenberg(staging: StagingDatabase, run_id: str):
    adapter = get_adapter("gutenberg")
    result = adapter.parse(page(CHB_BOOK))
    staged = []
    for song in result.songs:
        song_id = staging.insert_song(
            song, run_id, review_status="approved",
            warning_count=len(validate_song(song)), include_lyrics=1)
        staged.append((song_id, song))
    staging.commit()
    return staged


def test_hymn_source_urls_carry_a_numbered_fragment():
    songs = parse_page(page(CHB_BOOK)).songs
    assert len(songs) >= 2
    assert [song.source_url for song in songs] == [
        f"{BOOK_URL}#hymn-{n}" for n in range(1, len(songs) + 1)
    ]


def test_a_multi_hymn_page_is_not_collapsed_by_the_deduplicator(tmp_path):
    songs = parse_page(page(CHB_BOOK)).songs
    assert len(songs) >= 2

    # replay the engine's decision loop: every hymn must be a fresh insert
    index = DedupIndex()
    for song in songs:
        decision = decide(song, index)
        assert decision.action == INSERT, (song.title, decision)
        apply_insert(index, song, f"pg_{normalize(song.title)}")
    assert len(index) == len(songs)

    with StagingDatabase(tmp_path / "staging.sqlite") as staging:
        run_id = staging.start_run("test", "command=test")
        staged = _stage_gutenberg(staging, run_id)
        assert len(staged) == len(songs)
        assert staging.counts()["songs"] == len(songs)


def test_export_with_lyrics_writes_every_line(tmp_path, prod_db_path):
    staging_path = tmp_path / "staging.sqlite"
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("test", "command=test")
        staged = _stage_gutenberg(staging, run_id)
        expected_lines = sum(len(song.all_lines) for _, song in staged)

    out_path = tmp_path / "exported.lsdb"
    summary = export_staging(staging_path, out_path, prod_path=prod_db_path,
                             include_lyrics=True, overwrite=True)

    assert summary["include_lyrics"] is True
    assert summary["songs"] == len(staged)
    assert summary["lyrics"] == expected_lines
    assert summary["metadata_only"] == 0

    connection = sqlite3.connect(out_path)
    connection.row_factory = sqlite3.Row
    songs = connection.execute(
        "SELECT id, title, artist, copyright_status, lyrics_status "
        "FROM songs ORDER BY id").fetchall()
    assert all(row["copyright_status"] == "PUBLIC_DOMAIN" for row in songs)
    assert all(row["lyrics_status"] == "PUBLIC_DOMAIN_TEXT" for row in songs)
    assert all(row["artist"] == "Traditional" for row in songs)

    first = connection.execute(
        "SELECT text, normalized_text FROM lyrics "
        "WHERE song_id = ? ORDER BY section_order, line_order LIMIT 1",
        (staged[0][0],)).fetchone()
    assert first["text"].strip()
    assert first["normalized_text"].strip()
    assert first["normalized_text"] != first["text"]

    total = connection.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0]
    assert total == expected_lines
    connection.close()


def test_export_without_the_flag_still_ships_no_lyrics(tmp_path, prod_db_path):
    staging_path = tmp_path / "staging.sqlite"
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("test", "command=test")
        _stage_gutenberg(staging, run_id)

    out_path = tmp_path / "exported.lsdb"
    summary = export_staging(staging_path, out_path, prod_path=prod_db_path,
                             include_lyrics=False, overwrite=True)
    assert summary["lyrics"] == 0
    assert summary["include_lyrics"] is False


def test_export_skips_lyrics_for_rows_left_out_of_the_include_list(
        tmp_path, prod_db_path):
    staging_path = tmp_path / "staging.sqlite"
    with StagingDatabase(staging_path) as staging:
        run_id = staging.start_run("test", "command=test")
        songs = get_adapter("gutenberg").parse(page(CHB_BOOK)).songs
        staged_lines = 0
        for index, song in enumerate(songs):
            # the guardrail is per-song: include_lyrics=1 AND approved
            included = bool(index)
            if included:
                staged_lines += len(song.all_lines)
            staging.insert_song(song, run_id, review_status="approved",
                                include_lyrics=1 if included else 0)
        staging.commit()

    out_path = tmp_path / "exported.lsdb"
    summary = export_staging(staging_path, out_path, prod_path=prod_db_path,
                             include_lyrics=True, overwrite=True)
    assert summary["songs"] == len(songs)
    assert summary["metadata_only"] == 1
    assert summary["lyrics"] == staged_lines
