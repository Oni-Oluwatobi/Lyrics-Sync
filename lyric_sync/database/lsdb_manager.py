"""``.LSDB`` access layer.

Responsibilities: locate/open the database, validate it, expose typed queries,
and provide the primitives the search engine needs. The database is always
opened read-only and is never modified by the application.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from lyric_sync.database.database_validator import (
    DatabaseError,
    DatabaseNotFoundError,
    DatabaseValidationError,
    ValidationReport,
    validate_file,
)
from lyric_sync.database.queries import (
    ALIASES_FOR_SONG,
    ALIAS_COLUMNS_SQL,
    FTS_MATCH,
    LYRIC_BLOB_FOR_SONG,
    LYRIC_LIKE,
    LYRIC_LINES_FOR_SONG,
    META_SELECT,
    ROW_COUNT,
    SONG_BY_ID,
    SONGS_BY_IDS,
    SONG_ID_ARTIST_LIKE,
    SONG_ID_TITLE_LIKE,
    SECTIONS_FOR_SONG,
)
from lyric_sync.database.schema_adapter import SchemaAdapter
from lyric_sync.models.lyric import LyricSection, SongLyrics, normalize_section_type
from lyric_sync.models.song import (
    LYRICS_AVAILABLE,
    LYRICS_UNAVAILABLE,
    METADATA_ONLY,
    UNVERIFIED,
    VERIFIED,
    Song,
    normalize_status,
)

__all__ = [
    "LSDBManager",
    "DatabaseInfo",
    "SongRecord",
    "DatabaseError",
    "DatabaseNotFoundError",
    "DatabaseValidationError",
    "ValidationReport",
]

_CHUNK = 80


@dataclass
class DatabaseInfo:
    """Everything the Database Information page displays."""

    path: str
    filename: str
    exists: bool
    size_bytes: int = 0
    version: str = ""
    schema_version: str = ""
    song_count: int = 0
    artist_count: int = 0
    lyric_line_count: int = 0
    lyric_section_count: int = 0
    alias_count: int = 0
    fts_available: bool = False
    fts_tables: list[str] = field(default_factory=list)
    fts_indexed_rows: int = 0
    integrity_status: str = "Not checked"
    integrity_detail: str = ""
    copyright_stats: dict[str, int] = field(default_factory=dict)
    verification_stats: dict[str, int] = field(default_factory=dict)
    table_count: int = 0
    songs_table: str = ""
    lyric_lines_table: str = ""
    generated_by: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def size_label(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:,.1f} {unit}" if unit != "B" else f"{int(size):,} B"
            size /= 1024
        return f"{size:,.1f} GB"


@dataclass
class SongRecord:
    """A song plus its lyric lines, ready for ranking."""

    song: Song
    lines: list[str] = field(default_factory=list)

    @property
    def lyrics_text(self) -> str:
        return "\n".join(self.lines)


class LSDBManager:
    """Read-only gateway to one ``.LSDB`` file."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self._path = Path(path)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._adapter: SchemaAdapter | None = None
        self._meta: dict[str, str] | None = None
        self._artist_names: dict[int, str] = {}

    # ------------------------------------------------------------- lifecycle

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._adapter is not None

    @property
    def schema(self) -> SchemaAdapter:
        if self._adapter is None:
            raise DatabaseValidationError("Database is not open.")
        return self._adapter

    def open(self) -> None:
        """Open and sanity-check the database (read-only)."""
        if not self._path.exists():
            raise DatabaseNotFoundError(f"Database not found: {self._path}")
        if not self._path.is_file():
            raise DatabaseNotFoundError(f"Not a file: {self._path}")

        self.close()
        connection = self.connection()
        try:
            self._adapter = SchemaAdapter(connection)
        except sqlite3.Error as exc:
            self.close()
            raise DatabaseValidationError(f"Cannot inspect schema: {exc}") from exc
        if not self._adapter.has_songs:
            self.close()
            raise DatabaseValidationError(
                "No songs table with a usable title column was found in this database."
            )

    def close(self) -> None:
        with self._lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        self._local = threading.local()
        self._adapter = None
        self._meta = None
        self._artist_names = {}

    def connection(self) -> sqlite3.Connection:
        """Per-thread read-only connection."""
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection

        uri_candidates = [
            self._path.resolve().as_uri() + "?mode=ro",
            "file:" + self._path.resolve().as_posix() + "?mode=ro",
        ]
        connection = None
        last_error: sqlite3.Error | None = None
        for uri in uri_candidates:
            try:
                connection = sqlite3.connect(uri, uri=True, timeout=10.0)
                break
            except sqlite3.Error as exc:  # pragma: no cover - platform dependent
                last_error = exc
        if connection is None:  # pragma: no cover - platform dependent
            connection = sqlite3.connect(str(self._path), timeout=10.0)
            connection.execute("PRAGMA query_only = ON")
        if last_error is not None and connection is None:  # pragma: no cover
            raise DatabaseValidationError(str(last_error))

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            connection.execute("PRAGMA trusted_schema = OFF")
        except sqlite3.Error:
            pass
        self._local.connection = connection
        with self._lock:
            self._connections.append(connection)
        return connection

    # ------------------------------------------------------------- validation

    def validate(self, deep: bool = True) -> ValidationReport:
        return validate_file(self._path, deep=deep)

    # ------------------------------------------------------------------- info

    def meta(self) -> dict[str, str]:
        if self._meta is not None:
            return self._meta
        adapter = self.schema
        values: dict[str, str] = {}
        if adapter.meta is not None:
            key_col = adapter.meta_fields.get("key")
            value_col = adapter.meta_fields.get("value")
            if key_col and value_col:
                try:
                    for row in self.connection().execute(
                        META_SELECT.format(
                            key_col=f'"{key_col}"',
                            value_col=f'"{value_col}"',
                            meta_table=f'"{adapter.meta.name}"',
                        )
                    ).fetchall():
                        if row[0] is not None:
                            values[str(row[0])] = "" if row[1] is None else str(row[1])
                except sqlite3.Error:
                    values = {}
            if not values:
                # Columnar layout: one row whose column names are the keys.
                try:
                    cursor = self.connection().execute(
                        f'SELECT * FROM "{adapter.meta.name}" LIMIT 1'
                    )
                    row = cursor.fetchone()
                    if row is not None and cursor.description:
                        for index, column in enumerate(cursor.description):
                            value = row[index]
                            if value is not None:
                                values[str(column[0])] = str(value)
                except sqlite3.Error:
                    values = {}
        self._meta = values
        return values

    def info(self, deep_check: bool = False, *, validate: bool = True) -> DatabaseInfo:
        """Describe the open database.

        ``validate=False`` skips the (potentially seconds-long) file
        validation pass so callers that only need counts — e.g. the startup
        status line — never pay for it on a critical path.
        """
        adapter = self.schema
        connection = self.connection()
        meta = self.meta()

        def count(table: str | None) -> int:
            if not table:
                return 0
            try:
                return int(connection.execute(ROW_COUNT.format(table=f'"{table}"')).fetchone()[0])
            except sqlite3.Error:
                return 0

        info = DatabaseInfo(
            path=str(self._path),
            filename=self._path.name,
            exists=self._path.exists(),
            version=meta.get("database_version") or meta.get("version") or "",
            schema_version=meta.get("schema_version") or meta.get("schema") or "",
            generated_by=meta.get("generated_by") or meta.get("generator") or "",
            song_count=count(adapter.songs.name if adapter.songs else None),
            artist_count=count(adapter.artists.name if adapter.artists else None),
            lyric_line_count=count(adapter.lyric_lines.name if adapter.lyric_lines else None),
            lyric_section_count=count(
                adapter.lyric_sections.name if adapter.lyric_sections else None
            ),
            alias_count=count(adapter.aliases.name if adapter.aliases else None),
            fts_tables=[fts.name for fts in adapter.fts_tables],
            table_count=len(adapter.tables),
            songs_table=adapter.songs.name if adapter.songs else "",
            lyric_lines_table=adapter.lyric_lines.name if adapter.lyric_lines else "",
            notes=list(adapter.notes),
        )
        info.size_bytes = self._path.stat().st_size if self._path.exists() else 0
        info.fts_available = bool(info.fts_tables)
        for name in info.fts_tables:
            info.fts_indexed_rows += count(name)

        copyright_col = adapter.song_fields.get("copyright_status")
        if copyright_col:
            info.copyright_stats = self._value_counts(
                adapter.songs.name, copyright_col  # type: ignore[union-attr]
            )
        verification_col = adapter.song_fields.get("verification_status")
        if verification_col:
            info.verification_stats = self._value_counts(
                adapter.songs.name, verification_col  # type: ignore[union-attr]
            )

        if not validate:
            info.integrity_status = "Not checked"
            info.integrity_detail = "Validation has not run yet."
            return info

        report = validate_file(self._path, deep=deep_check)
        failed = report.errors
        warned = report.warnings
        if failed:
            info.integrity_status = "Failed"
            info.integrity_detail = failed[0].detail
        elif warned:
            info.integrity_status = "Passed with warnings"
            info.integrity_detail = warned[0].detail
        else:
            info.integrity_status = "Passed"
            info.integrity_detail = "All checks passed."
        return info

    def _value_counts(self, table: str, column: str) -> dict[str, int]:
        try:
            rows = self.connection().execute(
                f'SELECT "{column}", COUNT(*) FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL GROUP BY "{column}" ORDER BY COUNT(*) DESC'
            ).fetchall()
        except sqlite3.Error:
            return {}
        return {str(row[0]): int(row[1]) for row in rows}

    # ----------------------------------------------------------------- songs

    def _select_list(self) -> str:
        return self.schema.songs_select_list()

    def _songs_where_ids(self, ids: Sequence[int | str]) -> list[Song]:
        adapter = self.schema
        if not ids or adapter.songs is None:
            return []
        select_list = self._select_list()
        id_col = adapter.song_id_column
        results: list[Song] = []
        unique = list(dict.fromkeys(i for i in ids if _valid_song_id(i) is not None))
        for start in range(0, len(unique), _CHUNK):
            chunk = unique[start:start + _CHUNK]
            placeholders = ", ".join("?" for _ in chunk)
            sql = SONGS_BY_IDS.format(
                select_list=select_list,
                songs=f'"{adapter.songs.name}"',
                id_col=f'"{id_col}"',
                placeholders=placeholders,
            )
            rows = self.connection().execute(sql, tuple(chunk)).fetchall()
            results.extend(self._row_to_song(row) for row in rows)
        missing = [i for i in unique if i not in {song.id for song in results}]
        if missing and id_col == "rowid":  # pragma: no cover - defensive
            pass
        return results

    def get_song(self, song_id: int | str) -> Song | None:
        """Look up one song by id.

        Accepts TEXT ids (production databases) and integer ids (development
        fixtures). SQLite's type affinity lets either form match, so the value
        is bound unchanged — no integer coercion. Invalid ids (``None``,
        blank strings, unsupported types) return ``None`` instead of raising.
        """
        song_id = _valid_song_id(song_id)
        if song_id is None:
            return None
        adapter = self.schema
        if adapter.songs is None:
            return None
        sql = SONG_BY_ID.format(
            select_list=self._select_list(),
            songs=f'"{adapter.songs.name}"',
            id_col=f'"{adapter.song_id_column}"',
        )
        row = self.connection().execute(sql, (song_id,)).fetchone()
        return None if row is None else self._row_to_song(row)

    def get_songs(self, ids: Iterable[int | str]) -> dict[int | str, Song]:
        return {song.id: song for song in self._songs_where_ids(list(ids))}

    def _row_to_song(self, row: sqlite3.Row) -> Song:
        data = {key: row[key] for key in row.keys() if key.startswith("f_")}
        raw_aliases = data.get("f_aliases")
        aliases: list[str] = []
        if raw_aliases:
            aliases.extend(
                part.strip()
                for part in str(raw_aliases).replace("|", ";").split(";")
                if part.strip()
            )
        song_id = data.get("f_id")
        if song_id is None:
            song_id = 0
        aliases.extend(self._aliases_for_song(song_id))

        artist = str(data.get("f_artist") or "").strip()
        artist_id = data.get("f_artist_id")
        if not artist and artist_id is not None:
            artist = self._artist_name(artist_id)

        year_raw = data.get("f_year")
        year: int | None = None
        if year_raw is not None:
            digits = "".join(ch for ch in str(year_raw) if ch.isdigit())
            if digits:
                try:
                    year = int(digits[:4])
                except ValueError:
                    year = None

        verification = normalize_status(
            data.get("f_verification_status"), (VERIFIED, UNVERIFIED), UNVERIFIED
        )
        copyright_status = normalize_status(
            data.get("f_copyright_status"), ("PUBLIC_DOMAIN", "LICENSED", "AUTHORIZED",
                                             "USER_IMPORTED", "METADATA_ONLY"),
            METADATA_ONLY,
        )
        lyrics_status_raw = data.get("f_lyrics_status")
        if lyrics_status_raw is None:
            lyrics_status = LYRICS_AVAILABLE if self.schema.has_lyrics else LYRICS_UNAVAILABLE
        else:
            lyrics_status = normalize_status(
                lyrics_status_raw, (LYRICS_AVAILABLE, LYRICS_UNAVAILABLE), LYRICS_UNAVAILABLE
            )
            if isinstance(lyrics_status_raw, (int, float)) and int(lyrics_status_raw) == 1:
                lyrics_status = LYRICS_AVAILABLE

        return Song(
            id=song_id,
            title=str(data.get("f_title") or "").strip() or "Untitled",
            artist=artist,
            artist_id=artist_id if artist_id is not None else None,
            album=_opt_str(data.get("f_album")),
            year=year,
            country=_opt_str(data.get("f_country")),
            category=_opt_str(data.get("f_category")),
            songwriter=_opt_str(data.get("f_songwriter")),
            aliases=tuple(dict.fromkeys(aliases)),
            verification_status=verification,
            copyright_status=copyright_status,
            lyrics_status=lyrics_status,
            source=_opt_str(data.get("f_source")),
            rights_notice=_opt_str(data.get("f_rights_notice")),
        )

    def _artist_name(self, artist_id: int | str) -> str:
        if artist_id in self._artist_names:
            return self._artist_names[artist_id]
        adapter = self.schema
        name = ""
        if adapter.artists is not None and adapter.artist_fields.get("name"):
            id_col = adapter.artist_fields.get("id") or "id"
            name_col = adapter.artist_fields["name"]
            try:
                row = self.connection().execute(
                    f'SELECT "{name_col}" FROM "{adapter.artists.name}" WHERE "{id_col}" = ?',
                    (artist_id,),
                ).fetchone()
            except sqlite3.Error:
                row = None
            if row is not None and row[0]:
                name = str(row[0])
        self._artist_names[artist_id] = name
        return name

    def _aliases_for_song(self, song_id: int | str) -> list[str]:
        adapter = self.schema
        if not adapter.has_aliases:
            return []
        song_id_col = adapter.alias_fields["song_id"]
        alias_col = adapter.alias_fields["alias"]
        try:
            rows = self.connection().execute(
                ALIASES_FOR_SONG.format(
                    alias_col=f'"{alias_col}"',
                    aliases=f'"{adapter.aliases.name}"',  # type: ignore[union-attr]
                    song_id_col=f'"{song_id_col}"',
                ),
                (song_id,),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [str(row[0]).strip() for row in rows if row[0]]

    # ---------------------------------------------------------------- lyrics

    def get_lyrics(self, song_id: int | str) -> SongLyrics:
        safe_id = _valid_song_id(song_id)
        if safe_id is None:
            # Malformed id: graceful "no lyrics" instead of a crash.
            return SongLyrics(song_id="", available=False)
        adapter = self.schema
        song = self.get_song(safe_id)
        notice = song.rights_notice if song else None

        if adapter.lyric_lines is not None:
            sections = self._sections_for_song(safe_id)
            if sections:
                return SongLyrics(song_id=safe_id, sections=tuple(sections),
                                  available=True, notice=notice)

        lines = self.get_lyric_lines(safe_id)
        if not lines:
            return SongLyrics(song_id=safe_id, available=False, notice=notice)
        grouped = self._group_lines_into_sections(safe_id, lines)
        return SongLyrics(song_id=safe_id, sections=tuple(grouped), available=True,
                          notice=notice)

    def get_lyric_lines(self, song_id: int) -> list[str]:
        adapter = self.schema
        if adapter.lyric_lines is None:
            if adapter.songs_lyric_column and adapter.songs is not None:
                sql = f'SELECT "{adapter.songs_lyric_column}" FROM "{adapter.songs.name}" ' \
                      f'WHERE "{adapter.song_id_column}" = ?'
                row = self.connection().execute(sql, (song_id,)).fetchone()
                if row is None or row[0] is None:
                    return []
                return [line.rstrip() for line in str(row[0]).splitlines()]
            return []

        fields = adapter.line_fields
        order = [fields["line_index"] or "rowid"]
        if fields.get("section_index"):
            order.insert(0, fields["section_index"])
        if fields.get("section_id"):
            order.insert(0, fields["section_id"])
        sql = LYRIC_BLOB_FOR_SONG.format(
            text_col=f'"{fields["text"]}"',
            lines=f'"{adapter.lyric_lines.name}"',
            song_id_col=f'"{fields["song_id"]}"',
            order_list=", ".join(f'"{col}"' for col in order),
        )
        rows = self.connection().execute(sql, (song_id,)).fetchall()
        return [str(row[0]) for row in rows if row[0] is not None]

    def _sections_for_song(self, song_id: int | str) -> list[LyricSection]:
        adapter = self.schema
        if adapter.lyric_sections is None or adapter.lyric_lines is None:
            return []
        sec = adapter.section_fields
        line = adapter.line_fields
        order = [line.get("line_index") or "rowid"]
        if line.get("section_index"):
            order.insert(0, line["section_index"])
        if line.get("section_id"):
            order.insert(0, line["section_id"])
        sql = LYRIC_LINES_FOR_SONG.format(
            select_list=adapter.lines_select_list(),
            lines=f'"{adapter.lyric_lines.name}"',
            song_id_col=f'"{line["song_id"]}"',
            order_list=", ".join(f'"{col}"' for col in order),
        )
        rows = self.connection().execute(sql, (song_id,)).fetchall()
        if not rows:
            return []

        sections_sql = SECTIONS_FOR_SONG.format(
            select_list=", ".join(
                f'"{actual}" AS "s_{logical}"'
                for logical, actual in sec.items()
                if actual
            ),
            sections=f'"{adapter.lyric_sections.name}"',
            song_id_col=f'"{sec["song_id"]}"',
            order_list=", ".join(
                f'"{sec[k]}"' for k in ("index", "id") if sec.get(k)
            ),
        )
        section_meta: dict[str, tuple[str, int, str]] = {}
        for row in self.connection().execute(sections_sql, (song_id,)).fetchall():
            data = {key: row[key] for key in row.keys()}
            key = str(data.get("s_id") if data.get("s_id") is not None else "")
            section_type = normalize_section_type(data.get("s_type") or data.get("s_label"))
            raw_index = data.get("s_index")
            try:
                index = int(raw_index) if raw_index is not None else 0
            except (TypeError, ValueError):
                index = 0
            label = str(data.get("s_label") or "") if data.get("s_label") else ""
            section_meta[key] = (section_type, index, label)

        buckets: dict[str, list[str]] = {}
        order_keys: list[str] = []
        for row in rows:
            data = {key: row[key] for key in row.keys()}
            section_id = data.get("l_section_id")
            key = "" if section_id is None else str(section_id)
            if key not in buckets:
                buckets[key] = []
                order_keys.append(key)
            text = data.get("l_text")
            if text is not None:
                buckets[key].append(str(text))

        sections: list[LyricSection] = []
        for position, key in enumerate(order_keys, start=1):
            section_type, index, label = section_meta.get(key, ("VERSE", position, ""))
            if key and key not in section_meta:
                section_type, index, label = "OTHER", 0, ""
            sections.append(
                LyricSection(
                    type=section_type,
                    index=index,
                    label=label,
                    lines=tuple(buckets[key]),
                )
            )
        return sections

    def _group_lines_into_sections(self, song_id: int | str, lines: list[str]) -> list[LyricSection]:
        """Group plain lyric lines when no sections table is available."""
        adapter = self.schema
        if adapter.lyric_lines is None:
            return [LyricSection(type="OTHER", index=0, label="", lines=tuple(lines))]

        fields = adapter.line_fields
        if not fields.get("section_type") and not fields.get("section_index"):
            return [LyricSection(type="OTHER", index=0, label="", lines=tuple(lines))]

        order = [fields.get("line_index") or "rowid"]
        select_parts = [f'"{fields["text"]}" AS "l_text"']
        for logical in ("section_type", "section_index"):
            if fields.get(logical):
                select_parts.append(f'"{fields[logical]}" AS "l_{logical}"')
                order.insert(0, fields[logical])
        sql = LYRIC_LINES_FOR_SONG.format(
            select_list=", ".join(select_parts),
            lines=f'"{adapter.lyric_lines.name}"',
            song_id_col=f'"{fields["song_id"]}"',
            order_list=", ".join(f'"{col}"' for col in order),
        )
        rows = self.connection().execute(sql, (song_id,)).fetchall()

        grouped: list[LyricSection] = []
        current_key: tuple[str, int] | None = None
        buffer: list[str] = []
        for row in rows:
            raw_type = row["l_section_type"] if "l_section_type" in row.keys() else None
            raw_index = row["l_section_index"] if "l_section_index" in row.keys() else None
            section_type = normalize_section_type(raw_type)
            try:
                index = int(raw_index) if raw_index is not None else 0
            except (TypeError, ValueError):
                index = 0
            key = (section_type, index)
            if key != current_key:
                if buffer:
                    grouped.append(
                        LyricSection(type=current_key[0], index=current_key[1],
                                     label="", lines=tuple(buffer))
                    )
                    buffer = []
                current_key = key
            if row["l_text"] is not None:
                buffer.append(str(row["l_text"]))
        if buffer and current_key is not None:
            grouped.append(
                LyricSection(type=current_key[0], index=current_key[1], label="",
                             lines=tuple(buffer))
            )
        return grouped

    # ------------------------------------------------------ search primitives

    def song_ids_matching_title(self, pattern: str, limit: int = 200) -> list[int]:
        adapter = self.schema
        if adapter.songs is None:
            return []
        column = adapter.song_fields.get("title")
        if not column:
            return []
        sql = SONG_ID_TITLE_LIKE.format(
            id_col=f'"{adapter.song_id_column}"',
            songs=f'"{adapter.songs.name}"',
            title_col=f'"{column}"',
        )
        return self._ids(sql, (pattern,), limit)

    def song_ids_matching_artist(self, pattern: str, limit: int = 200) -> list[int]:
        adapter = self.schema
        if adapter.songs is None:
            return []
        column = adapter.song_fields.get("artist")
        if not column:
            return []
        sql = SONG_ID_ARTIST_LIKE.format(
            id_col=f'"{adapter.song_id_column}"',
            songs=f'"{adapter.songs.name}"',
            artist_col=f'"{column}"',
        )
        return self._ids(sql, (pattern,), limit)

    def song_ids_matching_alias(self, pattern: str, limit: int = 200) -> list[int]:
        adapter = self.schema
        if not adapter.has_aliases:
            return []
        sql = ALIAS_COLUMNS_SQL.format(
            song_id_col=f'"{adapter.alias_fields["song_id"]}"',
            alias_col=f'"{adapter.alias_fields["alias"]}"',
            aliases=f'"{adapter.aliases.name}"',  # type: ignore[union-attr]
        )
        return self._ids(sql, (pattern,), limit)

    def song_ids_matching_lyrics(self, pattern: str, limit: int = 400) -> list[int]:
        adapter = self.schema
        if adapter.lyric_lines is None:
            return []
        fields = adapter.line_fields
        sql = LYRIC_LIKE.format(
            song_id_col=f'"{fields["song_id"]}"',
            lines=f'"{adapter.lyric_lines.name}"',
            text_col=f'"{fields["text"]}"',
        )
        return self._ids(sql, (pattern,), limit)

    def song_ids_matching_all(
        self,
        patterns: Sequence[str],
        *,
        columns: Sequence[str],
        limit: int = 400,
    ) -> list[int]:
        """Songs where *every* pattern matches inside *any* of ``columns``."""
        adapter = self.schema
        if adapter.songs is None or not patterns or not columns:
            return []
        columns = [column for column in columns if column]
        if not columns:
            return []
        clause_groups: list[str] = []
        for _pattern in patterns:
            alternatives = " OR ".join(
                f'"{column}" LIKE ? ESCAPE \'\\\'' for column in columns
            )
            clause_groups.append(f"({alternatives})")
        clauses = " AND ".join(clause_groups)
        params: list[object] = []
        for pattern in patterns:
            for _column in columns:
                params.append(pattern)
        sql = (
            f'SELECT "{adapter.song_id_column}" FROM "{adapter.songs.name}" '
            f'WHERE {clauses}'
        )
        return self._ids(sql, params, limit)

    def song_titles_sample(self, limit: int = 5000) -> list[tuple[int, str, str]]:
        """Lightweight ``(id, title, artist)`` list used by fuzzy metadata matching."""
        adapter = self.schema
        if adapter.songs is None:
            return []
        title_col = adapter.song_fields.get("title")
        artist_col = adapter.song_fields.get("artist")
        if not title_col:
            return []
        select = (
            f'"{adapter.song_id_column}", "{title_col}", "{artist_col}"'
            if artist_col
            else f'"{adapter.song_id_column}", "{title_col}", \'\''
        )
        try:
            rows = self.connection().execute(
                f'SELECT {select} FROM "{adapter.songs.name}" LIMIT ?', (limit,)
            ).fetchall()
        except sqlite3.Error:
            return []
        return [(int(row[0]), str(row[1] or ""), str(row[2] or "")) for row in rows]

    def _ids(self, sql: str, params: Sequence[object], limit: int) -> list[int]:
        try:
            rows = self.connection().execute(sql, tuple(params)).fetchall()
        except sqlite3.Error:
            return []
        ids: list[int] = []
        for row in rows:
            try:
                ids.append(int(row[0]))
            except (TypeError, ValueError):
                continue
            if len(ids) >= limit:
                break
        return ids

    def fts_match(self, table: str, match_query: str, limit: int = 200) -> list[tuple[int, float]]:
        """Run an FTS query and return ``[(song_id, rank), ...]`` (lower is better)."""
        if not match_query:
            return []
        try:
            rows = self.connection().execute(
                FTS_MATCH.format(table=f'"{table}"', table_ref=f'"{table}"'),
                (match_query, limit),
            ).fetchall()
        except sqlite3.Error:
            return []
        results: list[tuple[int, float]] = []
        for row in rows:
            try:
                results.append((int(row["rowid"]), float(row["rank"] or 0.0)))
            except (TypeError, ValueError, sqlite3.Error):
                continue
        return results

    def get_records(self, ids: Sequence[int]) -> list[SongRecord]:
        """Load songs and their lyric lines for a bounded candidate set."""
        songs = self._songs_where_ids(ids)
        records: list[SongRecord] = []
        for song in songs:
            lines = (
                self.get_lyric_lines(song.id)
                if song.has_stored_lyrics or self.schema.has_lyrics
                else []
            )
            records.append(SongRecord(song=song, lines=lines))
        return records

    def line_ids_to_song_ids(self, ids: Sequence[int]) -> dict[int, int]:
        """Map lyric line identifiers back to their song (FTS rowid fallback)."""
        adapter = self.schema
        if not ids or adapter.lyric_lines is None:
            return {}
        fields = adapter.line_fields
        id_col = fields.get("id")
        song_col = fields.get("song_id")
        if not song_col:
            return {}
        key_col = f'"{id_col}"' if id_col else "rowid"
        mapping: dict[int, int] = {}
        unique = list(dict.fromkeys(int(i) for i in ids))
        for start in range(0, len(unique), _CHUNK):
            chunk = unique[start:start + _CHUNK]
            placeholders = ", ".join("?" for _ in chunk)
            try:
                rows = self.connection().execute(
                    f'SELECT {key_col}, "{song_col}" FROM "{adapter.lyric_lines.name}" '
                    f'WHERE {key_col} IN ({placeholders})',
                    tuple(chunk),
                ).fetchall()
            except sqlite3.Error:
                return {}
            for row in rows:
                try:
                    mapping[int(row[0])] = int(row[1])
                except (TypeError, ValueError):
                    continue
        return mapping

    def lyric_rows_batch(self, offset: int, limit: int) -> list[tuple[int, str]]:
        """Bounded page of ``(song_id, line)`` rows used by the fuzzy fallback."""
        adapter = self.schema
        if adapter.lyric_lines is None:
            return []
        fields = adapter.line_fields
        order = fields.get("line_index") or "rowid"
        try:
            rows = self.connection().execute(
                f'SELECT "{fields["song_id"]}", "{fields["text"]}" '
                f'FROM "{adapter.lyric_lines.name}" '
                f'ORDER BY "{order}" LIMIT ? OFFSET ?',
                (limit, offset),
            ).fetchall()
        except sqlite3.Error:
            return []
        result: list[tuple[int, str]] = []
        for row in rows:
            if row[0] is None or row[1] is None:
                continue
            try:
                result.append((int(row[0]), str(row[1])))
            except (TypeError, ValueError):
                continue
        return result

    def count_lyric_lines_scannable(self) -> int:
        adapter = self.schema
        if adapter.lyric_lines is None:
            return 0
        try:
            return int(
                self.connection()
                .execute(ROW_COUNT.format(table=f'"{adapter.lyric_lines.name}"'))
                .fetchone()[0]
            )
        except sqlite3.Error:
            return 0


def _valid_song_id(value: object) -> int | str | None:
    """Return a bindable song id, or ``None`` when the input is unusable.

    TEXT ids (``hymn_amazing_grace_001``) and integer ids are both passed
    through unchanged: SQLite's comparison affinity matches either form, and
    coercing text ids to ``int`` is exactly what used to crash this layer.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
