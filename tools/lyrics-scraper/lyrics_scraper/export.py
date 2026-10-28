"""Export staging data into Lyric Sync's production ``.lsdb`` format.

The exporter **copies** the production database file (read-only), empties it
and refills it with staged songs, so the schema, indexes and FTS structure are
guaranteed to match the application.  The production file itself is never
opened for writing and the exporter refuses to target it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .normalize import normalize, slug

PROD_SONG_COLUMNS = [
    "id", "title", "normalized_title", "artist", "normalized_artist", "album",
    "release_year", "country", "region", "language", "genre", "subgenre",
    "song_type", "songwriter", "publisher", "copyright_status",
    "lyrics_status", "source", "source_url", "aliases", "popularity_tier",
    "verified", "verification_status", "created_at", "updated_at",
]

PROD_LYRIC_COLUMNS = [
    "id", "song_id", "section_order", "section_type", "line_order", "text",
    "normalized_text", "language", "source", "copyright_status", "verified",
]

CLEAR_ORDER = [
    "lyrics", "lyric_search_index", "lyric_search_fts", "songs", "artists",
    "build_manifest", "categories", "database_metadata",
]

SOURCE_NAME = "OpenGospelLyrics"
SOURCE_KEY = "opengospellyrics"
SOURCE_URL = "https://opengospellyrics.com/"
GENERATED_BY = (
    "Lyric Sync database builder (tools/lyrics-scraper/lyrics_scraper/export.py)"
    " — The Kreadive Galaxy"
)


class ExportError(RuntimeError):
    """Raised when an export cannot proceed safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _list(value) -> list[str]:
    """Read a JSON list column from staging (safe on bad data)."""
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str) and item]


def _first(value) -> str:
    items = _list(value)
    return items[0] if items else ""


def _source_key(song: dict) -> str:
    domain = song.get("source_domain") or ""
    if not domain:
        return SOURCE_KEY
    return domain.split(".")[0]


def _source_home(song: dict) -> str:
    domain = song.get("source_domain") or ""
    return f"https://{domain}/" if domain else SOURCE_URL


def _release_year(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(ch if ch.isdigit() else " " for ch in value).split()
    for token in digits:
        if len(token) == 4:
            return int(token)
    return None


def _aliases(song: dict, sections: list[dict]) -> list[str]:
    """Parenthetical alternate titles plus the first line of each section."""
    out: list[str] = []
    title = song["title"] or ""
    if "(" in title and title.endswith(")"):
        out.append(title[title.find("(") + 1:-1].strip())
    seen_sections: set[int] = set()
    for row in sections:
        order = row["section_order"]
        if order in seen_sections or row["line_order"] != 1:
            continue
        seen_sections.add(order)
        out.append(row["line_text"])
        if len(out) >= 8:
            break
    return [item for item in dict.fromkeys(out) if item]


def create_target(prod_path: Path, out_path: Path) -> sqlite3.Connection:
    """Copy the production file and empty it.  Production is only read."""
    if not prod_path.exists():
        raise ExportError(f"production database not found: {prod_path}")
    if out_path.resolve() == prod_path.resolve():
        raise ExportError(
            "refusing to write the production database — choose a new --out path"
        )
    if out_path.exists():
        raise ExportError(
            f"output already exists (use --overwrite to replace): {out_path}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(prod_path, out_path)

    connection = sqlite3.connect(out_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    for table in CLEAR_ORDER:
        connection.execute(f"DELETE FROM {table}")
    connection.commit()
    return connection


def _stage_rows(staging: sqlite3.Connection, *, include_flagged: bool) -> list[dict]:
    where = "" if include_flagged else "WHERE review_status != 'flagged'"
    songs = staging.execute(
        f"SELECT * FROM songs {where} ORDER BY created_at, song_id"
    ).fetchall()
    out = []
    for song in songs:
        sections = staging.execute(
            "SELECT section_order, section_label, section_type, display_label, "
            "line_order, line_text, line_normalized "
            "FROM song_sections WHERE song_id = ? "
            "ORDER BY section_order, line_order",
            (song["song_id"],),
        ).fetchall()
        out.append({"song": dict(song), "sections": [dict(r) for r in sections]})
    return out


def _song_row(song: dict, sections: list[dict], *, with_lyrics: bool,
              now: str) -> tuple:
    artist = song["artist"] or "Traditional"
    site = song["source_site"] or SOURCE_NAME
    language = _first(song["languages"]) or song["language"] or "English"
    country = _first(song["countries"]) or ""
    year = _release_year(song["year"]) or _release_year(song["article_date"])
    author = song["author"] or song["songwriter"] or artist
    category = (song["category"] or "").lower()
    is_carol = "carol" in category
    aliases = _aliases(song, sections)
    if with_lyrics:
        copyright_status = song["copyright_status"]
        if copyright_status == "PUBLIC_DOMAIN":
            lyrics_status = "PUBLIC_DOMAIN_TEXT"
        else:
            lyrics_status = "FULL_LYRICS"
    else:
        copyright_status = "METADATA_ONLY"
        lyrics_status = "METADATA_ONLY"
    plain_lines = [row["line_text"] for row in sections] if with_lyrics else []
    alias_text = " ".join(aliases)
    searchable = " ".join([
        normalize(song["title"] or ""),
        normalize(artist),
        alias_text,
        " ".join(plain_lines),
        " ".join(normalize(line) for line in plain_lines),
    ]).strip()
    song["_alias_text"] = alias_text
    song["_searchable"] = searchable
    song["_plain_lines"] = plain_lines
    song["_language"] = language
    return (
        song["song_id"], song["title"], song["normalized_title"], artist,
        song["normalized_artist"], song["album"] or None,
        year, country, "",
        language, "Gospel",
        "Traditional Carol" if is_carol else "Traditional Hymn",
        "Carol" if is_carol else "Hymn",
        author, "Public Domain" if with_lyrics else "Unknown",
        copyright_status, lyrics_status,
        f"{site} — {song['article_url']}" if song["article_url"] else site,
        song["source_url"], json.dumps(aliases), 1, 0, "UNVERIFIED", now, now,
    )


def _lyric_rows(song: dict, sections: list[dict], language: str) -> list[tuple]:
    rows = []
    source = song["source_url"] or song["source_site"] or SOURCE_NAME
    for row in sections:
        lyric_id = (f"{song['song_id']}_s{row['section_order']}"
                    f"_l{row['line_order']}")
        rows.append((
            lyric_id, song["song_id"], row["section_order"],
            row["display_label"] or row["section_label"] or "Verse",
            row["line_order"], row["line_text"], row["line_normalized"],
            language, source,
            song["copyright_status"], 0,
        ))
    return rows


def content_digest(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in connection.execute(
        "SELECT id, title, artist FROM songs ORDER BY id"
    ).fetchall():
        digest.update("|".join(str(value) for value in row).encode("utf-8"))
    for row in connection.execute(
        "SELECT song_id, section_order, line_order, text FROM lyrics "
        "ORDER BY song_id, section_order, line_order"
    ).fetchall():
        digest.update("|".join(str(value) for value in row).encode("utf-8"))
    return digest.hexdigest()


def write_metadata(connection: sqlite3.Connection, *, database_name: str,
                   version: str, article_titles: list[str],
                   exported: int, skipped: int, fetched: int,
                   sources: list[tuple[str, str, str]]) -> None:
    """Write database_metadata plus one build_manifest row per source site."""
    total_songs = connection.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    total_lyrics = connection.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0]
    total_artists = connection.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    pd_count = connection.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status = 'PUBLIC_DOMAIN'"
    ).fetchone()[0]
    meta_only = connection.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status = 'METADATA_ONLY'"
    ).fetchone()[0]
    licensed = total_songs - pd_count - meta_only
    digest = content_digest(connection)

    names = ", ".join(dict.fromkeys(name for _key, name, _url in sources))
    provenance_policy = (
        "Every record carries its origin: songs.source/source_url name the "
        f"source page ({names}) the text came from, the per-song source URL "
        "keeps a stable fragment for compilation entries, and the "
        "build_manifest table records retrieval time and yield per source. "
        "sha256_checksum is the SHA-256 of the canonical songs+lyrics dump."
    )
    copyright_policy = (
        "Scraped records are exported as METADATA_ONLY (title, artist, "
        "credits, sections) unless an operator explicitly resolved copyright "
        "in staging and ran the export with --include-lyrics. No lyrics are "
        "generated, completed or paraphrased."
    )
    connection.execute(
        "INSERT INTO database_metadata (database_name, database_version, "
        "schema_version, total_songs, total_artists, total_lyrics_records, "
        "total_licensed_records, total_public_domain_records, "
        "total_metadata_only_records, build_date, provenance_policy, "
        "copyright_policy, sha256_checksum, generated_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (database_name, version, "1", total_songs, total_artists, total_lyrics,
         licensed, pd_count, meta_only, utc_now(), provenance_policy,
         copyright_policy, digest, GENERATED_BY),
    )
    titles = "; ".join(dict.fromkeys(t for t in article_titles if t))[:500]
    for key, name, home in sources:
        connection.execute(
            "INSERT INTO build_manifest (source_key, title, author, published, "
            "ebook_id, url, license, retrieved_at, songs_parsed, songs_accepted, "
            "songs_skipped) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, titles or name, name, "", 0, home,
             "Third-party lyrics site — exported for operator review; each "
             "song retains its own source URL.",
             utc_now(), fetched, exported, skipped),
        )


def export_staging(
    staging_path: Path | str,
    out_path: Path | str,
    *,
    prod_path: Path | str,
    version: str = "1.0.0",
    include_lyrics: bool = False,
    include_flagged: bool = False,
    overwrite: bool = False,
) -> dict:
    """Create a new ``.lsdb`` containing the staged songs."""
    staging_path = Path(staging_path)
    out_path = Path(out_path)
    prod_path = Path(prod_path)

    if not staging_path.exists():
        raise ExportError(f"staging database not found: {staging_path}")
    # Refuse to touch the production file BEFORE anything is deleted.
    if out_path.resolve() == prod_path.resolve():
        raise ExportError(
            "refusing to write the production database — choose a new --out path"
        )
    if out_path.exists() and overwrite:
        out_path.unlink()

    staging = sqlite3.connect(staging_path)
    staging.row_factory = sqlite3.Row
    try:
        rows = _stage_rows(staging, include_flagged=include_flagged)
        page_rows = [dict(r) for r in staging.execute(
            "SELECT page_id, title FROM pages"
        ).fetchall()]
    finally:
        staging.close()

    target = create_target(prod_path, out_path)
    target.execute("PRAGMA foreign_keys = ON")

    now = utc_now()
    song_rows: list[tuple] = []
    lyric_rows: list[tuple] = []
    index_rows: list[tuple] = []
    fts_rows: list[tuple] = []
    artist_map: dict[str, tuple] = {}

    for entry in rows:
        song = entry["song"]
        sections = entry["sections"]
        allow_lyrics = (
            include_lyrics
            and bool(song["include_lyrics"])
            and song["copyright_status"] in ("PUBLIC_DOMAIN", "AUTHORIZED")
        )
        row = _song_row(song, sections, with_lyrics=allow_lyrics, now=now)
        song_rows.append(row)

        if allow_lyrics:
            lyric_rows.extend(
                _lyric_rows(song, sections, song["_language"]))

        alias_text = song["_alias_text"]
        index_rows.append((
            f"idx_{song['song_id']}", song["song_id"], song["title"],
            song["artist"] or "Traditional", alias_text, song["_searchable"],
        ))
        fragments = " ".join(song["_plain_lines"][:12])[:1000]
        fts_rows.append((
            song["song_id"], song["title"], song["artist"] or "Traditional",
            alias_text, fragments,
        ))

        for name in dict.fromkeys(
                _list(song["artists"]) + _list(song["featured_artists"])
                + [song["artist"] or "Traditional"]):
            artist_map.setdefault(normalize(name), (
                f"art_{slug(name)[:60]}" or "art_unknown",
                name, "", "",
            ))

    if song_rows:
        target.executemany(
            f"INSERT INTO songs ({', '.join(PROD_SONG_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in PROD_SONG_COLUMNS)})",
            song_rows,
        )
    if lyric_rows:
        target.executemany(
            f"INSERT INTO lyrics ({', '.join(PROD_LYRIC_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in PROD_LYRIC_COLUMNS)})",
            lyric_rows,
        )
    if index_rows:
        target.executemany(
            "INSERT INTO lyric_search_index (id, song_id, title, artist, "
            "aliases, searchable_text) VALUES (?, ?, ?, ?, ?, ?)",
            index_rows,
        )
    if fts_rows:
        target.executemany(
            "INSERT INTO lyric_search_fts (song_id, title, artist, aliases, "
            "lyric_fragments) VALUES (?, ?, ?, ?, ?)",
            fts_rows,
        )
    existing_artists = {
        row["artist_id"]
        for row in target.execute("SELECT artist_id FROM artists").fetchall()
    }
    artist_rows = []
    for key, (artist_id, name, country, region) in sorted(artist_map.items()):
        candidate = artist_id
        suffix = 1
        while candidate in existing_artists:
            suffix += 1
            candidate = f"{artist_id}_{suffix}"
        existing_artists.add(candidate)
        artist_rows.append((candidate, name, key, country, region, "Gospel",
                            "[]", ""))
    if artist_rows:
        target.executemany(
            "INSERT INTO artists (artist_id, artist_name, normalized_name, "
            "country, region, genre, aliases, bio_snippet) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            artist_rows,
        )

    source_sites: dict[str, tuple[str, str, str]] = {}
    for entry in rows:
        song = entry["song"]
        key = _source_key(song)
        source_sites.setdefault(
            key, (key, song["source_site"] or SOURCE_NAME,
                  _source_home(song)))
    if not source_sites:
        source_sites[SOURCE_KEY] = (SOURCE_KEY, SOURCE_NAME, SOURCE_URL)

    write_metadata(
        target, database_name=out_path.name, version=version,
        article_titles=[row["title"] for row in page_rows if row["title"]],
        exported=len(song_rows), skipped=0,
        fetched=len(page_rows) or len({row["song"]["page_id"] for row in rows}),
        sources=sorted(source_sites.values()),
    )
    target.commit()
    target.execute("VACUUM")
    target.close()

    digest = ""
    verify = sqlite3.connect(out_path)
    verify.row_factory = sqlite3.Row
    digest = verify.execute(
        "SELECT sha256_checksum FROM database_metadata"
    ).fetchone()[0]
    counts = {
        "songs": verify.execute("SELECT COUNT(*) FROM songs").fetchone()[0],
        "lyrics": verify.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0],
        "artists": verify.execute("SELECT COUNT(*) FROM artists").fetchone()[0],
        "index": verify.execute(
            "SELECT COUNT(*) FROM lyric_search_index").fetchone()[0],
        "fts": verify.execute(
            "SELECT COUNT(*) FROM lyric_search_fts").fetchone()[0],
        "metadata_only": verify.execute(
            "SELECT COUNT(*) FROM songs WHERE copyright_status='METADATA_ONLY'"
        ).fetchone()[0],
    }
    verify.close()

    return {
        "output": str(out_path),
        "size_bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        "checksum": digest,
        "include_lyrics": bool(include_lyrics),
        **counts,
    }
