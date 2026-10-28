"""Schema introspection and tolerant mapping onto the ``.LSDB`` layout.

The real database is produced outside this application, so column names may
vary slightly. ``SchemaAdapter`` inspects the file once at open time and maps
logical fields (``title``, ``copyright_status``, ...) onto whatever columns the
file actually provides. Only identifiers discovered through SQLite introspection
are ever interpolated into SQL.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SONG_TABLE_CANDIDATES = ("songs", "song", "tracks", "track")
LYRIC_LINES_CANDIDATES = (
    "lyric_lines",
    "lyrics_lines",
    "lines",
    "song_lines",
    "song_lyrics",
    "lyrics",
    "lyrictext",
)
LYRIC_SECTIONS_CANDIDATES = ("lyric_sections", "sections", "song_sections", "parts")
ALIAS_CANDIDATES = ("song_aliases", "aliases", "titles", "song_titles", "aka")
ARTIST_CANDIDATES = ("artists", "artist", "singers")
META_CANDIDATES = (
    "meta",
    "metadata",
    "database_metadata",
    "database_info",
    "db_info",
    "info",
    "app_meta",
)

TITLE_COLUMNS = ("title", "song_title", "name", "track_title", "songname")
ARTIST_COLUMNS = ("artist", "artist_name", "singer", "performer", "artistname")


def safe_identifier(name: str) -> bool:
    """Identifiers only ever come from SQLite introspection; double-check anyway."""
    return bool(name) and bool(_IDENTIFIER.match(name))


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


@dataclass
class TableSchema:
    name: str
    columns: list[str] = field(default_factory=list)

    @property
    def lowered(self) -> dict[str, str]:
        return {column.lower(): column for column in self.columns}

    def pick(self, *candidates: str, required: bool = False) -> str | None:
        lower = self.lowered
        for candidate in candidates:
            if candidate.lower() in lower:
                return lower[candidate.lower()]
        normalized = {_normalize(key): value for key, value in lower.items()}
        for candidate in candidates:
            key = _normalize(candidate)
            if key in normalized:
                return normalized[key]
        if required:
            raise LookupError(f"none of {candidates} found in table {self.name}")
        return None


@dataclass
class FtsSchema:
    name: str
    columns: list[str]
    kind: str = "fts5"

    @property
    def has_title(self) -> bool:
        return any(_normalize(c) in {"title", "songtitle", "name"} for c in self.columns)

    @property
    def has_artist(self) -> bool:
        return any("artist" in _normalize(c) or "singer" in _normalize(c) for c in self.columns)

    @property
    def has_lyrics(self) -> bool:
        return any(
            "lyric" in _normalize(c) or _normalize(c) in {"content", "text", "body"}
            for c in self.columns
        )

    @property
    def scope(self) -> str:
        if self.has_lyrics:
            return "lyrics"
        if self.has_title:
            return "metadata"
        return "unknown"


class SchemaAdapter:
    """Maps logical fields onto the concrete schema of one ``.LSDB`` file."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.tables: dict[str, TableSchema] = {}
        self.fts_tables: list[FtsSchema] = []
        self.notes: list[str] = []
        self._introspect()

        self.songs: TableSchema | None = self._find(SONG_TABLE_CANDIDATES)
        self.lyric_lines: TableSchema | None = self._find(LYRIC_LINES_CANDIDATES)
        self.lyric_sections: TableSchema | None = self._find(LYRIC_SECTIONS_CANDIDATES)
        self.aliases: TableSchema | None = self._find(ALIAS_CANDIDATES)
        self.artists: TableSchema | None = self._find(ARTIST_CANDIDATES)
        self.meta: TableSchema | None = self._find(META_CANDIDATES)

        # A single blob of lyrics may live directly on the songs table.
        self.songs_lyric_column: str | None = None
        if self.songs is not None and self.lyric_lines is None:
            self.songs_lyric_column = self.songs.pick(
                "lyrics", "lyric", "lyrics_text", "lyric_text", "content", "text"
            )

        self.song_fields: dict[str, str | None] = {}
        self.line_fields: dict[str, str | None] = {}
        self.section_fields: dict[str, str | None] = {}
        self.alias_fields: dict[str, str | None] = {}
        self.meta_fields: dict[str, str | None] = {}
        self.artist_fields: dict[str, str | None] = {}
        self._map_fields()

    # ------------------------------------------------------------------ setup

    def _introspect(self) -> None:
        for name, sql in self.connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        ).fetchall():
            if not safe_identifier(name):
                self.notes.append(f"Skipped non-conforming relation name: {name!r}")
                continue
            try:
                rows = self.connection.execute(f'PRAGMA table_info("{name}")').fetchall()
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                self.notes.append(f"Could not read {name}: {exc}")
                continue
            self.tables[name] = TableSchema(name=name, columns=[row[1] for row in rows])

        for name, sql in self.connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL"
        ).fetchall():
            lowered = (sql or "").lower()
            if "using fts" not in lowered:
                continue
            schema = self.tables.get(name)
            if schema is None:
                continue
            kind = "fts5" if "using fts5" in lowered else "fts"
            self.fts_tables.append(FtsSchema(name=name, columns=list(schema.columns), kind=kind))

    def _find(self, candidates: tuple[str, ...]) -> TableSchema | None:
        for candidate in candidates:
            schema = self.tables.get(candidate)
            if schema is not None:
                return schema
        normalized = {_normalize(key): schema for key, schema in self.tables.items()}
        for candidate in candidates:
            schema = normalized.get(_normalize(candidate))
            if schema is not None:
                return schema
        return None

    def _map_fields(self) -> None:
        if self.songs is not None:
            s = self.songs
            try:
                title = s.pick(*TITLE_COLUMNS, required=True)
            except LookupError:
                title = None
            self.song_fields = {
                "id": s.pick("id", "song_id", "track_id", "rowid") or "rowid",
                "title": title,
                "artist": s.pick(*ARTIST_COLUMNS),
                "artist_id": s.pick("artist_id", "singer_id"),
                "album": s.pick("album", "album_title", "release"),
                "year": s.pick("year", "release_year", "released", "date"),
                "country": s.pick("country", "region", "country_region", "origin"),
                "category": s.pick("category", "genre", "type", "tag"),
                "songwriter": s.pick("songwriter", "writer", "composed_by", "author"),
                "aliases": s.pick("aliases", "aka", "also_known_as", "alt_titles"),
                "verification_status": s.pick(
                    "verification_status", "verified", "verification", "status"
                ),
                "copyright_status": s.pick(
                    "copyright_status", "rights_status", "copyright", "license", "provenance"
                ),
                "lyrics_status": s.pick("lyrics_status", "lyric_status", "has_lyrics"),
                "source": s.pick("source", "origin_source", "provider"),
                "rights_notice": s.pick(
                    "rights_notice", "license_note", "copyright_note", "notice"
                ),
                "lyrics": self.songs_lyric_column,
            }

        if self.lyric_lines is not None:
            l = self.lyric_lines
            self.line_fields = {
                "id": l.pick("id", "line_id"),
                "song_id": l.pick("song_id", "song", "track_id", required=True),
                "text": l.pick("text", "line", "lyric", "line_text", "lyric_text", "content",
                              "words", required=True),
                "line_index": l.pick("line_index", "line_number", "line_no", "number",
                                     "position", "seq", "sort_order", "idx"),
                "section_id": l.pick("section_id", "part_id"),
                "section_type": l.pick("section_type", "section", "part", "type", "block"),
                "section_index": l.pick("section_index", "part_index", "section_number"),
            }

        if self.lyric_sections is not None:
            sec = self.lyric_sections
            self.section_fields = {
                "id": sec.pick("id", "section_id"),
                "song_id": sec.pick("song_id", "song", "track_id", required=True),
                "type": sec.pick("type", "section_type", "part", "name", "heading"),
                "index": sec.pick("index", "section_index", "part_index", "number", "seq"),
                "label": sec.pick("label", "title", "heading", "name"),
            }

        if self.aliases is not None:
            a = self.aliases
            self.alias_fields = {
                "song_id": a.pick("song_id", "song", "track_id", required=True),
                "alias": a.pick("alias", "title", "name", "alt_title", "text", required=True),
            }

        if self.meta is not None:
            m = self.meta
            try:
                key_field = m.pick("key", "name", "field", "property", required=True)
                value_field = m.pick("value", "val", "data", "content", required=True)
            except LookupError:
                key_field = None
                value_field = None
            self.meta_fields = {
                "key": key_field,
                "value": value_field,
            }

        if self.artists is not None:
            ar = self.artists
            self.artist_fields = {
                "id": ar.pick("id", "artist_id"),
                "name": ar.pick("name", "artist", "title", "artist_name"),
                "country": ar.pick("country", "region"),
            }

    # ------------------------------------------------------------- accessors

    @property
    def has_songs(self) -> bool:
        return self.songs is not None and bool(self.song_fields.get("title"))

    @property
    def has_lyrics(self) -> bool:
        return self.lyric_lines is not None or bool(self.songs_lyric_column)

    @property
    def has_aliases(self) -> bool:
        return self.aliases is not None and bool(self.alias_fields.get("alias"))

    @property
    def song_id_column(self) -> str:
        return self.song_fields.get("id") or "rowid"

    def songs_select_list(self) -> str:
        """SELECT list for song rows using only existing columns."""
        parts: list[str] = []
        for logical, actual in self.song_fields.items():
            if logical == "id" or actual is None:
                continue
            parts.append(f'"{actual}" AS "f_{logical}"')
        id_col = self.song_fields.get("id") or "rowid"
        parts.insert(0, f'"{id_col}" AS "f_id"')
        return ", ".join(parts)

    def lines_select_list(self) -> str:
        parts: list[str] = []
        for logical, actual in self.line_fields.items():
            if actual is None:
                continue
            parts.append(f'"{actual}" AS "l_{logical}"')
        return ", ".join(parts) or '"rowid" AS "l_id"'

    def describe(self) -> dict[str, object]:
        return {
            "tables": {name: schema.columns for name, schema in sorted(self.tables.items())},
            "fts_tables": [
                {"name": fts.name, "columns": fts.columns, "scope": fts.scope}
                for fts in self.fts_tables
            ],
            "songs_table": self.songs.name if self.songs else None,
            "lyric_lines_table": self.lyric_lines.name if self.lyric_lines else None,
            "lyric_sections_table": self.lyric_sections.name if self.lyric_sections else None,
            "aliases_table": self.aliases.name if self.aliases else None,
            "meta_table": self.meta.name if self.meta else None,
            "field_map": {k: v for k, v in self.song_fields.items()},
            "notes": list(self.notes),
        }
