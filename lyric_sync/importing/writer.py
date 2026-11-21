"""Shared write helpers for the Kreadive Galaxy catalogue backfill.

Originally developer-side tooling (lives in tools/, beside build_gospel_db.py);
vendored into the application package so the in-app lyric import can write to
the production .lsdb exactly the way the canonical builder does: same
normalize(), same column orders, same searchable_text/FTS composition, same
content-digest algorithm.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

# --- exact copy of build_gospel_db.normalize (catalogue norm) ---
def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize(text)).strip("_")


PROD_SONG_COLUMNS = [
    "id", "title", "normalized_title", "artist", "normalized_artist", "album",
    "release_year", "country", "region", "language", "genre", "subgenre",
    "song_type", "songwriter", "publisher", "copyright_status", "lyrics_status",
    "source", "source_url", "aliases", "popularity_tier", "verified",
    "verification_status", "created_at", "updated_at",
]

PROD_LYRIC_COLUMNS = [
    "id", "song_id", "section_order", "section_type", "line_order", "text",
    "normalized_text", "language", "source", "copyright_status", "verified",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_writable(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA busy_timeout=60000")
    return con


def song_row(
    *, song_id, title, artist, songwriter, publisher, copyright_status,
    lyrics_status, source, country, region, language="English",
    genre="Gospel", subgenre, song_type, source_url=None, album=None,
    release_year=None, aliases=None, popularity_tier=1, verified=1,
    verification_status="VERIFIED", created_at=None, updated_at=None,
) -> tuple:
    now = created_at or now_iso()
    alias_json = json.dumps(aliases or [], ensure_ascii=False)
    return (
        song_id, title, normalize(title), artist, normalize(artist), album,
        release_year, country, region, language, genre, subgenre, song_type,
        songwriter, publisher, copyright_status, lyrics_status, source,
        source_url, alias_json, popularity_tier, verified, verification_status,
        now, updated_at or now,
    )


def lyric_rows(song_id, stanzas, *, language, source, copyright_status,
               section_type_fallback="Verse") -> list[tuple]:
    """stanzas: list of (section_type, [lines]). Returns PROD_LYRIC_COLUMNS tuples."""
    rows = []
    for section_order, (section_type, lines) in enumerate(stanzas, start=1):
        st = section_type or f"{section_type_fallback} {section_order}"
        for line_order, line in enumerate(lines, start=1):
            rows.append((
                f"{song_id}_s{section_order}_l{line_order}", song_id,
                section_order, st, line_order, line, normalize(line),
                language, source, copyright_status, 1,
            ))
    return rows


def index_and_fts_rows(song_id, title, artist, alias_list, plain_lines):
    """Return (index_row, fts_row) matching build_gospel_db composition."""
    alias_text = " ".join(alias_list)
    searchable = " ".join([
        normalize(title), normalize(artist), alias_text,
        " ".join(plain_lines),
        " ".join(normalize(line) for line in plain_lines),
    ])
    index_row = (f"idx_{song_id}", song_id, title, artist, alias_text, searchable)
    fragments = " ".join(plain_lines[:12])[:1000]
    fts_row = (song_id, title, artist, alias_text, fragments)
    return index_row, fts_row


def rebuild_search_rows_for_song(con, song_id):
    """Rebuild lyric_search_index + lyric_search_fts for one song from its
    songs + lyrics rows. Safe for metadata-only songs (no lyrics)."""
    s = con.execute(
        "SELECT title, artist, aliases FROM songs WHERE id=?", (song_id,)
    ).fetchone()
    if s is None:
        return False
    title, artist, aliases_json = s
    try:
        alias_list = json.loads(aliases_json) if aliases_json else []
    except Exception:
        alias_list = []
    plain = [
        r[0] for r in con.execute(
            "SELECT text FROM lyrics WHERE song_id=? "
            "ORDER BY section_order, line_order", (song_id,)
        ).fetchall()
    ]
    index_row, fts_row = index_and_fts_rows(song_id, title, artist, alias_list, plain)
    con.execute("DELETE FROM lyric_search_index WHERE song_id=?", (song_id,))
    con.execute("DELETE FROM lyric_search_fts WHERE song_id=?", (song_id,))
    con.execute(
        "INSERT INTO lyric_search_index (id, song_id, title, artist, aliases, "
        "searchable_text) VALUES (?, ?, ?, ?, ?, ?)", index_row)
    con.execute(
        "INSERT INTO lyric_search_fts (song_id, title, artist, aliases, "
        "lyric_fragments) VALUES (?, ?, ?, ?, ?)", fts_row)
    return True


def recompute_metadata(con, *, version=None, bump_note=None):
    """Recompute counts + content digest and write them into the single
    database_metadata row. Mirrors build_gospel_db.build()."""
    total_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    total_lyrics = con.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0]
    total_artists = con.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    pd_count = con.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status='PUBLIC_DOMAIN'"
    ).fetchone()[0]
    meta_only = con.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status='METADATA_ONLY'"
    ).fetchone()[0]
    licensed = total_songs - pd_count - meta_only

    digest = hashlib.sha256()
    for row in con.execute(
        "SELECT id, title, artist FROM songs ORDER BY id"
    ).fetchall():
        digest.update("|".join(str(v) for v in row).encode("utf-8"))
    # Sort in Python: SQLite's ORDER BY on 60k+ lyric rows costs ~20 s on the
    # production database (no covering index), while the equivalent Python
    # sort is instant and yields the identical canonical order.
    lyric_rows = con.execute(
        "SELECT song_id, section_order, line_order, text FROM lyrics"
    ).fetchall()
    lyric_rows.sort(key=lambda row: (str(row[0]), row[1], row[2]))
    for row in lyric_rows:
        digest.update("|".join(str(v) for v in row).encode("utf-8"))
    content_hash = digest.hexdigest()

    row = con.execute(
        "SELECT database_version, generated_by FROM database_metadata "
        "WHERE database_name='lyric_sync_gospel.lsdb'"
    ).fetchone()
    gen_by = (row[1] if row else "") or ""
    if bump_note:
        gen_by = (gen_by + " | " + bump_note).strip(" |")
    new_version = version or (row[0] if row else "3.2.0")

    con.execute(
        "UPDATE database_metadata SET total_songs=?, total_artists=?, "
        "total_lyrics_records=?, total_licensed_records=?, "
        "total_public_domain_records=?, total_metadata_only_records=?, "
        "build_date=?, sha256_checksum=?, database_version=?, generated_by=? "
        "WHERE database_name='lyric_sync_gospel.lsdb'",
        (total_songs, total_artists, total_lyrics, licensed, pd_count,
         meta_only, now_iso(), content_hash, new_version, gen_by),
    )
    return {
        "total_songs": total_songs, "total_lyrics": total_lyrics,
        "total_artists": total_artists, "public_domain": pd_count,
        "metadata_only": meta_only, "licensed": licensed,
        "content_digest": content_hash,
    }


def validate(con) -> dict:
    """Non-destructive sanity checks mirroring the app's expectations.

    Uses set comparisons rather than correlated ``NOT EXISTS`` subqueries:
    ``lyric_search_index.song_id`` has no index, so the subquery form scans the
    whole table once per song and can hang for minutes.
    """
    problems = []
    song_ids = {row[0] for row in con.execute("SELECT id FROM songs")}
    lyric_song_ids = {
        row[0] for row in con.execute("SELECT DISTINCT song_id FROM lyrics")
    }
    orphan_ids = lyric_song_ids - song_ids
    if orphan_ids:
        problems.append(f"{len(orphan_ids)} orphan lyric song ids")

    index_ids = {
        row[0] for row in con.execute("SELECT song_id FROM lyric_search_index")
    }
    missing_idx = song_ids - index_ids
    if missing_idx:
        problems.append(f"{len(missing_idx)} songs missing search index")

    fts_ids = {
        row[0] for row in con.execute("SELECT song_id FROM lyric_search_fts")
    }
    missing_fts = song_ids - fts_ids
    if missing_fts:
        problems.append(f"{len(missing_fts)} songs missing FTS row")
    # CHECK constraints are enforced by SQLite on write; do a quick distinct scan
    bad_cs = con.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status NOT IN "
        "('PUBLIC_DOMAIN','LICENSED','AUTHORIZED','USER_IMPORTED','METADATA_ONLY')"
    ).fetchone()[0]
    if bad_cs:
        problems.append(f"{bad_cs} songs with invalid copyright_status")
    bad_ls = con.execute(
        "SELECT COUNT(*) FROM songs WHERE lyrics_status NOT IN "
        "('FULL_LYRICS','PARTIAL_AUTHORIZED','METADATA_ONLY','PUBLIC_DOMAIN_TEXT')"
    ).fetchone()[0]
    if bad_ls:
        problems.append(f"{bad_ls} songs with invalid lyrics_status")
    return {"ok": not problems, "problems": problems}
