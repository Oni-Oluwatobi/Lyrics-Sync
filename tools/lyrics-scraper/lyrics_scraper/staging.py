"""Staging database â€” the scraper's own SQLite file.

The staging database is deliberately separate from the production
``lyric_sync_gospel.lsdb``: it is the only thing the scraper ever writes, and
the production file is never opened for writing by this package.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .dedupe import DedupIndex
from .models import NormalizedSong, Warning
from .normalize import normalize, slug

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scrape_runs (
  run_id          TEXT PRIMARY KEY,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  source          TEXT NOT NULL,
  pages_requested INTEGER DEFAULT 0,
  pages_successful INTEGER DEFAULT 0,
  songs_found     INTEGER DEFAULT 0,
  songs_imported  INTEGER DEFAULT 0,
  duplicates      INTEGER DEFAULT 0,
  warnings        INTEGER DEFAULT 0,
  errors          INTEGER DEFAULT 0,
  notes           TEXT
);

CREATE TABLE IF NOT EXISTS pages (
  page_id       TEXT PRIMARY KEY,
  url           TEXT NOT NULL UNIQUE,
  final_url     TEXT,
  page_type     TEXT,
  http_status   INTEGER,
  fetched_at    TEXT,
  title         TEXT,
  raw_path      TEXT,
  bytes         INTEGER DEFAULT 0,
  from_cache    INTEGER DEFAULT 0,
  run_id        TEXT REFERENCES scrape_runs(run_id)
);

CREATE TABLE IF NOT EXISTS songs (
  song_id            TEXT PRIMARY KEY,
  run_id             TEXT REFERENCES scrape_runs(run_id),
  page_id            TEXT,
  title              TEXT NOT NULL,
  normalized_title   TEXT NOT NULL,
  artist             TEXT NOT NULL DEFAULT 'Traditional',
  normalized_artist  TEXT NOT NULL,
  author             TEXT,
  composer           TEXT,
  songwriter         TEXT,
  translator         TEXT,
  year               TEXT,
  language           TEXT,
  key_name           TEXT,
  chords             TEXT,
  album              TEXT,
  category           TEXT,
  tags               TEXT DEFAULT '[]',
  published_at       TEXT,
  modified_at        TEXT,
  source_name        TEXT NOT NULL DEFAULT 'OpenGospelLyrics',
  source_url         TEXT NOT NULL,
  article_url        TEXT NOT NULL,
  source_site        TEXT DEFAULT '',
  source_domain      TEXT DEFAULT '',
  source_adapter     TEXT DEFAULT '',
  source_meta        TEXT DEFAULT '{}',
  article_date       TEXT,
  artists            TEXT DEFAULT '[]',
  featured_artists   TEXT DEFAULT '[]',
  languages          TEXT DEFAULT '[]',
  language_confidence TEXT DEFAULT 'unknown',
  countries          TEXT DEFAULT '[]',
  region             TEXT DEFAULT '',
  taxonomy           TEXT DEFAULT '{}',
  raw_text           TEXT NOT NULL DEFAULT '',
  content_hash       TEXT NOT NULL,
  lyrics_hash        TEXT NOT NULL,
  line_count         INTEGER DEFAULT 0,
  section_count      INTEGER DEFAULT 0,
  copyright_status   TEXT NOT NULL DEFAULT 'UNKNOWN',
  review_status      TEXT NOT NULL DEFAULT 'clean',
  include_lyrics     INTEGER DEFAULT 0,
  import_status      TEXT NOT NULL DEFAULT 'staged',
  warning_count      INTEGER DEFAULT 0,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS song_sections (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id        TEXT NOT NULL REFERENCES songs(song_id) ON DELETE CASCADE,
  section_order  INTEGER NOT NULL,
  section_label  TEXT NOT NULL,
  section_type   TEXT NOT NULL,
  display_label  TEXT NOT NULL,
  line_order     INTEGER NOT NULL,
  line_text      TEXT NOT NULL,
  line_raw       TEXT NOT NULL DEFAULT '',
  line_normalized TEXT NOT NULL,
  line_repeat    INTEGER NOT NULL DEFAULT 1,
  line_repeat_unknown INTEGER NOT NULL DEFAULT 0,
  line_is_marker INTEGER NOT NULL DEFAULT 0,
  repeat_marker  INTEGER NOT NULL DEFAULT 0,
  marker         TEXT NOT NULL DEFAULT '',
  marker_target  TEXT NOT NULL DEFAULT '',
  translation    TEXT NOT NULL DEFAULT '',
  UNIQUE (song_id, section_order, line_order)
);

CREATE TABLE IF NOT EXISTS artists (
  artist_id       TEXT PRIMARY KEY,
  artist_name     TEXT NOT NULL,
  normalized_name TEXT NOT NULL UNIQUE,
  source          TEXT
);

CREATE TABLE IF NOT EXISTS song_artists (
  song_id   TEXT NOT NULL REFERENCES songs(song_id) ON DELETE CASCADE,
  artist_id TEXT NOT NULL REFERENCES artists(artist_id) ON DELETE CASCADE,
  role      TEXT NOT NULL DEFAULT 'primary',
  PRIMARY KEY (song_id, artist_id, role)
);

CREATE TABLE IF NOT EXISTS song_sources (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id       TEXT NOT NULL REFERENCES songs(song_id) ON DELETE CASCADE,
  url           TEXT NOT NULL,
  article_url   TEXT,
  page_id       TEXT,
  relation      TEXT NOT NULL DEFAULT 'primary',
  first_seen_at TEXT NOT NULL,
  UNIQUE (song_id, url, relation)
);

CREATE TABLE IF NOT EXISTS tags (
  tag_id       TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  normalized   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS song_tags (
  song_id TEXT NOT NULL REFERENCES songs(song_id) ON DELETE CASCADE,
  tag_id  TEXT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
  PRIMARY KEY (song_id, tag_id)
);

CREATE TABLE IF NOT EXISTS validation_warnings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT,
  song_id     TEXT,
  page_id     TEXT,
  code        TEXT NOT NULL,
  severity    TEXT NOT NULL DEFAULT 'warning',
  message     TEXT NOT NULL,
  song_title  TEXT,
  source_url  TEXT,
  context     TEXT,
  resolved    INTEGER DEFAULT 0,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_songs_norm_title ON songs(normalized_title);
CREATE INDEX IF NOT EXISTS idx_songs_norm_artist ON songs(normalized_artist);
CREATE INDEX IF NOT EXISTS idx_songs_source_url ON songs(source_url);
CREATE INDEX IF NOT EXISTS idx_songs_review ON songs(review_status);
CREATE INDEX IF NOT EXISTS idx_sections_song ON song_sections(song_id);
CREATE INDEX IF NOT EXISTS idx_warnings_code ON validation_warnings(code);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Stable short prefix for ``songs.song_id`` per source, so an id says which
#: site it came from instead of implying every song is from OpenGospelLyrics.
_SOURCE_PREFIX = {
    "opengospellyrics.com": "ogl",
    "africangospellyrics.com": "agl",
    "gutenberg.org": "pg",
    "zionlyrics.com": "zl",
}


#: Columns added after the first staging schema shipped; existing staging
#: databases are upgraded in place instead of being recreated.
MIGRATIONS: dict[str, dict[str, str]] = {
    "songs": {
        "source_site": "TEXT DEFAULT ''",
        "source_domain": "TEXT DEFAULT ''",
        "source_adapter": "TEXT DEFAULT ''",
        "source_meta": "TEXT DEFAULT '{}'",
        "article_date": "TEXT",
        "artists": "TEXT DEFAULT '[]'",
        "featured_artists": "TEXT DEFAULT '[]'",
        "languages": "TEXT DEFAULT '[]'",
        "language_confidence": "TEXT DEFAULT 'unknown'",
        "countries": "TEXT DEFAULT '[]'",
        "region": "TEXT DEFAULT ''",
        "taxonomy": "TEXT DEFAULT '{}'",
    },
    "song_sections": {
        "line_raw": "TEXT NOT NULL DEFAULT ''",
        "line_repeat": "INTEGER NOT NULL DEFAULT 1",
        "line_repeat_unknown": "INTEGER NOT NULL DEFAULT 0",
        "line_is_marker": "INTEGER NOT NULL DEFAULT 0",
        "repeat_marker": "INTEGER NOT NULL DEFAULT 0",
        "marker": "TEXT NOT NULL DEFAULT ''",
        "marker_target": "TEXT NOT NULL DEFAULT ''",
        "translation": "TEXT NOT NULL DEFAULT ''",
    },
}


def _ensure_columns(connection: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for name, declaration in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"
                )
    connection.commit()


def _all_tags(song: "NormalizedSong") -> list[str]:
    """Every source tag/taxonomy value worth indexing, de-duplicated."""
    values: list[str] = list(song.tags or [])
    for part in (song.category or "").split(","):
        if part.strip():
            values.append(part.strip())
    for bucket in ("themes", "countries", "languages", "artists",
                   "other_tags"):
        values.extend((song.taxonomy or {}).get(bucket, []))
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(value.strip())
    return out


class StagingDatabase:
    """Thin wrapper around the staging SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA_SQL)
        _ensure_columns(self.connection)
        self.connection.commit()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "StagingDatabase":
        return self

    def __exit__(self, *exc) -> None:
        self.connection.commit()
        self.close()

    # -- runs --------------------------------------------------------------
    def start_run(self, source: str, notes: str = "") -> str:
        run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
        suffix = 1
        while self.connection.execute(
            "SELECT 1 FROM scrape_runs WHERE run_id = ?", (run_id,)
        ).fetchone():
            suffix += 1
            run_id = f"{datetime.now(timezone.utc).strftime('run_%Y%m%d_%H%M%S')}_{suffix}"
        self.connection.execute(
            "INSERT INTO scrape_runs (run_id, started_at, source, notes) VALUES (?,?,?,?)",
            (run_id, utc_now(), source, notes),
        )
        self.connection.commit()
        return run_id

    def finish_run(self, run_id: str, **stats: int) -> None:
        assignments = ", ".join(f"{key} = ?" for key in stats)
        values = list(stats.values())
        self.connection.execute(
            "UPDATE scrape_runs SET finished_at = ?"
            + (f", {assignments}" if assignments else "")
            + " WHERE run_id = ?",
            [utc_now(), *values, run_id],
        )
        self.connection.commit()

    def update_run_field(self, run_id: str, **fields) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.connection.execute(
            f"UPDATE scrape_runs SET {assignments} WHERE run_id = ?",
            [*fields.values(), run_id],
        )
        self.connection.commit()

    # -- pages -------------------------------------------------------------
    def record_page(self, page, run_id: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO pages "
            "(page_id, url, final_url, page_type, http_status, fetched_at, title, "
            " raw_path, bytes, from_cache, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                page.page_id, page.url, page.final_url, "", page.http_status,
                page.fetched_at, "", page.raw_path, page.bytes,
                1 if page.from_cache else 0, run_id,
            ),
        )

    def update_page(self, page_id: str, page_type: str = "", title: str = "") -> None:
        self.connection.execute(
            "UPDATE pages SET page_type = COALESCE(NULLIF(?, ''), page_type), "
            "title = COALESCE(NULLIF(?, ''), title) WHERE page_id = ?",
            (page_type, title, page_id),
        )

    # -- songs -------------------------------------------------------------
    def index(self) -> DedupIndex:
        rows = self.connection.execute(
            "SELECT song_id, normalized_title, normalized_artist, source_url, "
            "content_hash, lyrics_hash FROM songs"
        ).fetchall()
        return DedupIndex.build([dict(row) for row in rows])

    def song_id_for(self, title: str, domain: str = "") -> str:
        prefix = _SOURCE_PREFIX.get(
            (domain or "").strip().lower(),
            slug(domain or "src")[:3] or "src")
        base = f"{prefix}_{slug(title)[:48]}" or f"{prefix}_untitled"
        candidate = base
        suffix = 2
        while self.connection.execute(
            "SELECT 1 FROM songs WHERE song_id = ?", (candidate,)
        ).fetchone():
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def insert_song(self, song: NormalizedSong, run_id: str, *,
                    song_id: str | None = None, review_status: str = "clean",
                    warning_count: int = 0, include_lyrics: bool = False) -> str:
        from .dedupe import draft_hashes

        norm_title, norm_artist, c_hash, l_hash = draft_hashes(song)
        song_id = song_id or self.song_id_for(song.title, song.source_domain)
        now = utc_now()
        artists = list(song.artists or ([song.artist] if song.artist else []))
        self.connection.execute(
            "INSERT INTO songs (song_id, run_id, page_id, title, "
            "normalized_title, artist, normalized_artist, author, composer, "
            "songwriter, translator, year, language, key_name, chords, album, "
            "category, tags, published_at, modified_at, source_name, "
            "source_url, article_url, source_site, source_domain, "
            "source_adapter, source_meta, article_date, artists, "
            "featured_artists, languages, language_confidence, countries, "
            "region, taxonomy, raw_text, content_hash, lyrics_hash, "
            "line_count, section_count, review_status, warning_count, "
            "copyright_status, include_lyrics, "
            "created_at, updated_at) "
            "VALUES (" + ",".join("?" * 46) + ")",
            (
                song_id, run_id, song.page_id, song.title, norm_title,
                song.artist, norm_artist, song.author, song.composer,
                song.songwriter, song.translator, song.year, song.language,
                song.key_name, song.chords, song.album, song.category,
                json.dumps(song.tags or []), song.published_at,
                song.modified_at, song.source_name, song.source_url,
                song.article_url, song.source_site, song.source_domain,
                song.source_adapter, json.dumps(song.source_metadata),
                song.article_date, json.dumps(artists),
                json.dumps(list(song.featured_artists or [])),
                json.dumps(list(song.languages or [])),
                song.language_confidence or "unknown",
                json.dumps(list(song.countries or [])), song.region or "",
                json.dumps(song.taxonomy or {}), song.raw_text,
                c_hash, l_hash, song.line_count, len(song.sections),
                review_status, warning_count,
                song.copyright_status or "UNKNOWN", 1 if include_lyrics else 0,
                now, now,
            ),
        )
        self._insert_sections(song_id, song)
        self._upsert_artist(song_id, song)
        self.add_source(song_id, song.source_url, song.article_url, song.page_id,
                        relation="primary")
        for tag in _all_tags(song):
            self._upsert_tag(song_id, tag)
        return song_id

    def add_existing_song_source(self, song_id: str, song: NormalizedSong) -> None:
        self.add_source(song_id, song.source_url, song.article_url, song.page_id,
                        relation="additional")
        self.connection.execute(
            "UPDATE songs SET updated_at = ? WHERE song_id = ?", (utc_now(), song_id)
        )

    def add_source(self, song_id: str, url: str, article_url: str,
                   page_id: str, relation: str = "primary") -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO song_sources "
            "(song_id, url, article_url, page_id, relation, first_seen_at) "
            "VALUES (?,?,?,?,?,?)",
            (song_id, url, article_url, page_id, relation, utc_now()),
        )

    def _insert_sections(self, song_id: str, song: NormalizedSong) -> None:
        rows = []
        for section_order, section in enumerate(song.sections, start=1):
            for line_order, entry in enumerate(section.entries, start=1):
                raw = entry.raw
                display = entry.text or raw
                rows.append((
                    song_id, section_order, section.label or "",
                    section.section_type,
                    section.display_label or section.label or "Verse",
                    line_order, display, raw, normalize(display),
                    entry.repeat, 1 if entry.repeat_unknown else 0,
                    1 if (not entry.text and entry.marker) else 0,
                    1 if (entry.repeat > 1 or entry.repeat_unknown
                          or entry.marker == "repeat") else 0,
                    entry.marker or "", entry.target or "",
                    entry.translation or "",
                ))
        self.connection.executemany(
            "INSERT INTO song_sections (song_id, section_order, section_label, "
            "section_type, display_label, line_order, line_text, line_raw, "
            "line_normalized, line_repeat, line_repeat_unknown, line_is_marker, "
            "repeat_marker, marker, marker_target, translation) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )

    def _upsert_artist(self, song_id: str, song: NormalizedSong) -> None:
        names = list(dict.fromkeys(
            [name for name in (song.artists or []) if name]
            + ([song.artist] if song.artist else [])
            + [name for name in (song.featured_artists or []) if name]
        ))
        if not names:
            names = ["Traditional"]
        for position, name in enumerate(names):
            role = "primary" if position == 0 else "featured"
            artist_id = self._artist_row(name, song.source_site or "")
            if artist_id:
                self.connection.execute(
                    "INSERT OR IGNORE INTO song_artists (song_id, artist_id, role) "
                    "VALUES (?,?,?)",
                    (song_id, artist_id, role),
                )

    def _artist_row(self, name: str, source: str) -> str | None:
        normalized = normalize(name)
        if not normalized:
            return None
        row = self.connection.execute(
            "SELECT artist_id FROM artists WHERE normalized_name = ?",
            (normalized,),
        ).fetchone()
        if row:
            return row["artist_id"]
        artist_id = f"src_artist_{slug(name)[:48]}" or "src_artist_unknown"
        suffix = 2
        while self.connection.execute(
            "SELECT 1 FROM artists WHERE artist_id = ?", (artist_id,)
        ).fetchone():
            artist_id = f"src_artist_{slug(name)[:48]}_{suffix}"
            suffix += 1
        self.connection.execute(
            "INSERT INTO artists (artist_id, artist_name, normalized_name, source) "
            "VALUES (?,?,?,?)",
            (artist_id, name, normalized, source or None),
        )
        return artist_id

    def _upsert_tag(self, song_id: str, tag: str) -> None:
        normalized = normalize(tag)
        if not normalized:
            return
        row = self.connection.execute(
            "SELECT tag_id FROM tags WHERE normalized = ?", (normalized,)
        ).fetchone()
        if row:
            tag_id = row["tag_id"]
        else:
            tag_id = f"tag_{slug(tag)[:48]}"
            self.connection.execute(
                "INSERT OR IGNORE INTO tags (tag_id, name, normalized) VALUES (?,?,?)",
                (tag_id, tag, normalized),
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO song_tags (song_id, tag_id) VALUES (?,?)",
            (song_id, tag_id),
        )

    # -- warnings ----------------------------------------------------------
    def add_warning(self, warning: Warning, run_id: str = "",
                    song_id: str = "", page_id: str = "") -> None:
        self.connection.execute(
            "INSERT INTO validation_warnings (run_id, song_id, page_id, code, "
            "severity, message, song_title, source_url, context, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, song_id or None, page_id or None, warning.code,
             warning.severity, warning.message, warning.song_title,
             warning.source_url, warning.context, utc_now()),
        )

    def has_warning(self, song_id: str, warning: Warning) -> bool:
        """True when this exact finding is already recorded for the song."""
        row = self.connection.execute(
            "SELECT 1 FROM validation_warnings WHERE song_id = ? AND code = ? "
            "AND message = ? AND COALESCE(context, '') = COALESCE(?, '') "
            "LIMIT 1",
            (song_id, warning.code, warning.message, warning.context),
        ).fetchone()
        return row is not None

    def link_page_warnings(self, page_id: str,
                           title_to_song: dict[str, str]) -> int:
        """Attach a page's warnings to the songs staged from that page.

        Page-level warnings are written before the songs of that page exist,
        so they carry only a title.  Matching them by title *within one page*
        keeps two songs that share a name (same title, different page) from
        claiming each other's warnings.
        """
        if not title_to_song:
            return 0
        linked = 0
        rows = self.connection.execute(
            "SELECT id, song_title FROM validation_warnings "
            "WHERE page_id = ? AND song_id IS NULL",
            (page_id,)).fetchall()
        for row in rows:
            song_id = title_to_song.get(row["song_title"] or "")
            if not song_id:
                continue
            self.connection.execute(
                "UPDATE validation_warnings SET song_id = ? WHERE id = ?",
                (song_id, row["id"]))
            linked += 1
        return linked

    def repair_warning_links(self) -> int:
        """Self-heal warnings written before they could be linked to a song.

        Matches on the page URL *and* the title, so it stays correct for
        staging databases created by older builds.
        """
        def clean(url: object) -> str:
            return str(url or "").split("#")[0].rstrip("/")

        keys: dict[tuple[str, str], str] = {}
        for row in self.connection.execute(
                "SELECT song_id, title, source_url, article_url FROM songs"):
            for url in (row["source_url"], row["article_url"]):
                keys[(clean(url), row["title"])] = row["song_id"]

        linked = 0
        for row in self.connection.execute(
                "SELECT id, song_title, source_url FROM validation_warnings "
                "WHERE song_id IS NULL").fetchall():
            song_id = keys.get((clean(row["source_url"]),
                                row["song_title"] or ""))
            if not song_id:
                continue
            self.connection.execute(
                "UPDATE validation_warnings SET song_id = ? WHERE id = ?",
                (song_id, row["id"]))
            linked += 1
        return linked

    def normalize_warning_severities(self) -> int:
        """Apply severity corrections to rows written by older builds.

        ``truncated_at_furniture`` used to be recorded as a ``warning`` even
        though stopping at a page boundary is the parsing rules working, so
        it marked perfectly good songs as needing review.
        """
        cursor = self.connection.execute(
            "UPDATE validation_warnings SET severity = 'info' "
            "WHERE code = 'truncated_at_furniture' "
            "AND severity <> 'info'")
        return max(cursor.rowcount, 0)

    def recount_warnings(self, song_id: str) -> int:
        """Set ``songs.warning_count`` to the number of rows actually shown,
        then make sure the review status agrees with them.

        A song that has findings displayed must not claim ``clean``.  The
        escalation only ever moves a song *towards* review — an approved or
        rejected decision made by a human is never silently undone.
        """
        total = self.connection.execute(
            "SELECT COUNT(*) FROM validation_warnings WHERE song_id = ?",
            (song_id,)).fetchone()[0]
        self.connection.execute(
            "UPDATE songs SET warning_count = ? WHERE song_id = ?",
            (total, song_id))
        row = self.connection.execute(
            "SELECT review_status FROM songs WHERE song_id = ?",
            (song_id,)).fetchone()
        if row and row["review_status"] in ("clean", "approved"):
            blocking = self.connection.execute(
                "SELECT COUNT(*) FROM validation_warnings WHERE song_id = ? "
                "AND severity IN ('warning', 'error')",
                (song_id,)).fetchone()[0]
            if blocking:
                self.connection.execute(
                    "UPDATE songs SET review_status = 'flagged' "
                    "WHERE song_id = ?", (song_id,))
        return total

    def prune_duplicate_warnings(self) -> int:
        """Drop rows that repeat a finding already recorded.

        The key mirrors :meth:`has_warning` (song, code, message, context)
        and deliberately ignores ``run_id`` and ``page_id``: the same finding
        surfaces once while parsing and again while validating, and re-running
        either must not stack copies.  ``source_url`` stays in the key so two
        different pages remain distinct rows.
        """
        cursor = self.connection.execute(
            "DELETE FROM validation_warnings WHERE id NOT IN ("
            "SELECT MIN(id) FROM validation_warnings GROUP BY "
            "song_id, code, severity, message, song_title, source_url, "
            "context)")
        return max(cursor.rowcount, 0)

    # -- queries -----------------------------------------------------------
    def counts(self) -> dict:
        c = self.connection
        one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "songs": one("SELECT COUNT(*) FROM songs"),
            "sections": one(
                "SELECT COUNT(*) FROM (SELECT DISTINCT song_id, section_order "
                "FROM song_sections)"
            ),
            "lyric_lines": one("SELECT COUNT(*) FROM song_sections"),
            "artists": one("SELECT COUNT(*) FROM artists"),
            "sources": one("SELECT COUNT(*) FROM song_sources"),
            "tags": one("SELECT COUNT(*) FROM tags"),
            "pages": one("SELECT COUNT(*) FROM pages"),
            "runs": one("SELECT COUNT(*) FROM scrape_runs"),
            "warnings": one("SELECT COUNT(*) FROM validation_warnings"),
            "flagged": one("SELECT COUNT(*) FROM songs WHERE review_status='flagged'"),
            "pending_review": one(
                "SELECT COUNT(*) FROM songs WHERE review_status != 'approved'"
            ),
            "approved": one(
                "SELECT COUNT(*) FROM songs WHERE review_status='approved'"
            ),
            "include_lyrics": one("SELECT COUNT(*) FROM songs WHERE include_lyrics=1"),
        }

    def commit(self) -> None:
        self.connection.commit()
