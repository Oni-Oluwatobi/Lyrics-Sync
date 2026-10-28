"""Validation of ``.LSDB`` files.

Validation never repairs or rewrites anything — it only reports. A failed
validation is surfaced to the user/developer instead of triggering destructive
action.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from lyric_sync.database.schema_adapter import SchemaAdapter
from lyric_sync.models.song import COPYRIGHT_STATUSES

SQLITE_HEADER = b"SQLite format 3\x00"

SUPPORTED_SCHEMA_MIN = 1
SUPPORTED_SCHEMA_MAX = 1

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


class DatabaseError(Exception):
    """Base class for database problems."""


class DatabaseNotFoundError(DatabaseError):
    """The expected ``.LSDB`` file does not exist."""


class DatabaseValidationError(DatabaseError):
    """The file exists but cannot be used."""


@dataclass
class Check:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == PASS


@dataclass
class ValidationReport:
    path: str
    ok: bool = False
    checks: list[Check] = field(default_factory=list)
    elapsed_ms: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [check for check in self.checks if check.status == WARN]

    @property
    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "Database passed all checks."
        if self.ok:
            return f"Database usable — {len(self.warnings)} warning(s)."
        first = self.errors[0].detail if self.errors else "Unknown problem."
        return f"Database problem: {first}"

    def to_text(self) -> str:
        lines = [f"Lyric Sync database validation — {self.path}", ""]
        for check in self.checks:
            lines.append(f"[{check.status}] {check.name}: {check.detail}")
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            lines.extend(f"  - {note}" for note in self.notes)
        lines.append("")
        lines.append(self.summary)
        return "\n".join(lines)


def _header_ok(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(16) == SQLITE_HEADER
    except OSError:
        return False


def validate_file(path: Path | str, deep: bool = True) -> ValidationReport:
    """Run every available check against one ``.LSDB`` file."""
    started = time.perf_counter()
    file_path = Path(path)
    report = ValidationReport(path=str(file_path))

    def add(name: str, status: str, detail: str) -> None:
        report.checks.append(Check(name, status, detail))

    if not file_path.exists():
        add("File exists", FAIL, f"Not found: {file_path}")
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report

    size = file_path.stat().st_size
    add("File exists", PASS, str(file_path))
    if size == 0:
        add("File size", FAIL, "File is empty.")
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report
    add("File size", PASS, f"{size:,} bytes")

    if not _header_ok(file_path):
        add("SQLite header", FAIL, "File is not a SQLite database.")
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report
    add("SQLite header", PASS, "Valid SQLite 3 file")

    connection: sqlite3.Connection | None = None
    try:
        uri = file_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error:
        try:
            connection = sqlite3.connect(f"file:{file_path.resolve().as_posix()}?mode=ro", uri=True,
                                         timeout=5.0)
        except sqlite3.Error as exc:
            add("Open database", FAIL, f"Cannot open read-only: {exc}")
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report

    try:
        connection.execute("PRAGMA query_only = ON")
        add("Open database", PASS, "Opened read-only")

        try:
            adapter = SchemaAdapter(connection)
        except sqlite3.Error as exc:
            add("Schema inspection", FAIL, f"Cannot inspect schema: {exc}")
            return report

        report.notes.extend(adapter.notes)

        if adapter.has_songs:
            add("Songs table", PASS, f"Mapped onto '{adapter.songs.name}'")
        else:
            add("Songs table", FAIL, "No usable songs table with a title column was found.")
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report

        # -- counts -------------------------------------------------------
        songs_table = adapter.songs.name
        song_count = _count(connection, songs_table)
        add("Song count", PASS if song_count else WARN,
            f"{song_count:,} song(s)" if song_count else "The database contains no songs.")

        if adapter.artists is not None:
            add("Artists table", PASS, f"{_count(connection, adapter.artists.name):,} artist(s)")
        else:
            add("Artists table", WARN, "No artists table — artist names are read from songs.")

        if adapter.lyric_lines is not None:
            line_count = _count(connection, adapter.lyric_lines.name)
            add("Lyric lines", PASS, f"{line_count:,} line(s)")
        elif adapter.songs_lyric_column:
            add("Lyric lines", WARN,
                "Lyrics stored as a single column on the songs table — no section labels.")
        else:
            add("Lyric lines", WARN, "No lyrics table found — metadata-only database.")

        # -- schema version ------------------------------------------------
        version = _meta_value(connection, adapter, "schema_version")
        if version is None:
            add("Schema version", WARN, "No schema_version entry in the metadata table.")
        else:
            try:
                number = int(str(version).strip())
            except ValueError:
                number = -1
            if SUPPORTED_SCHEMA_MIN <= number <= SUPPORTED_SCHEMA_MAX:
                add("Schema version", PASS, str(number))
            else:
                add("Schema version", WARN,
                    f"Version {version} is outside the supported range "
                    f"{SUPPORTED_SCHEMA_MIN}..{SUPPORTED_SCHEMA_MAX}.")

        # -- FTS -------------------------------------------------------------
        if adapter.fts_tables:
            details = []
            for fts in adapter.fts_tables:
                try:
                    rows = _count(connection, fts.name)
                except sqlite3.Error as exc:
                    add(f"Full-text index ({fts.name})", FAIL, f"Unreadable: {exc}")
                    continue
                details.append(f"{fts.name} [{fts.scope}] {rows:,} rows")
            if details:
                add("Full-text index", PASS, "; ".join(details))
        else:
            add("Full-text index", WARN,
                "No FTS5 index — search falls back to a slower SQL scan.")

        # -- integrity --------------------------------------------------------
        if deep:
            try:
                rows = connection.execute("PRAGMA integrity_check").fetchall()
                result = rows[0][0] if rows else "unknown"
            except sqlite3.Error as exc:
                add("Integrity check", FAIL, f"Could not run: {exc}")
            else:
                if str(result).lower() == "ok":
                    add("Integrity check", PASS, "ok")
                else:
                    add("Integrity check", FAIL, str(result))
        else:
            try:
                rows = connection.execute("PRAGMA quick_check").fetchall()
                result = rows[0][0] if rows else "unknown"
            except sqlite3.Error as exc:
                add("Integrity check", FAIL, f"Could not run: {exc}")
            else:
                add("Integrity check", PASS if str(result).lower() == "ok" else "WARN",
                    str(result))

        # -- provenance values ------------------------------------------------
        copyright_col = adapter.song_fields.get("copyright_status")
        if copyright_col:
            values = {
                str(row[0]).upper()
                for row in connection.execute(
                    f'SELECT DISTINCT "{copyright_col}" FROM "{songs_table}" '
                    f'WHERE "{copyright_col}" IS NOT NULL'
                ).fetchall()
            }
            unknown = sorted(v for v in values if v and v not in COPYRIGHT_STATUSES)
            if unknown:
                add("Copyright statuses", WARN, "Unrecognised values: " + ", ".join(unknown))
            else:
                add("Copyright statuses", PASS,
                    ", ".join(sorted(values)) if values else "none recorded")
        else:
            add("Copyright statuses", WARN, "No copyright column mapped.")

        # -- orphan lyrics ------------------------------------------------------
        if adapter.lyric_lines is not None:
            song_id_col = adapter.song_id_column
            line_song_col = adapter.line_fields.get("song_id")
            if line_song_col:
                try:
                    orphan = connection.execute(
                        f'SELECT COUNT(*) FROM "{adapter.lyric_lines.name}" l '
                        f'LEFT JOIN "{songs_table}" s '
                        f'ON l."{line_song_col}" = s."{song_id_col}" '
                        f'WHERE s."{song_id_col}" IS NULL'
                    ).fetchone()[0]
                except sqlite3.Error as exc:
                    add("Lyric integrity", WARN, f"Could not check: {exc}")
                else:
                    add(
                        "Lyric integrity",
                        WARN if orphan else PASS,
                        f"{orphan:,} lyric line(s) without a matching song" if orphan
                        else "All lyric lines resolve to a song.",
                    )

        report.ok = not report.errors
    except sqlite3.Error as exc:
        add("Database read", FAIL, f"{exc}")
        report.ok = False
    finally:
        if connection is not None:
            connection.close()
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)

    return report


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _meta_value(
    connection: sqlite3.Connection, adapter: SchemaAdapter, key: str
) -> str | None:
    if adapter.meta is None:
        return None
    key_col = adapter.meta_fields.get("key")
    value_col = adapter.meta_fields.get("value")
    if key_col and value_col:
        try:
            row = connection.execute(
                f'SELECT "{value_col}" FROM "{adapter.meta.name}" WHERE "{key_col}" = ?',
                (key,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None and row[0] is not None:
            return row[0]
    # Columnar layout: one row whose column names are the metadata keys.
    try:
        cursor = connection.execute(f'SELECT * FROM "{adapter.meta.name}" LIMIT 1')
        row = cursor.fetchone()
    except sqlite3.Error:
        return None
    if row is None or not cursor.description:
        return None
    columns = [column[0] for column in cursor.description]
    if key in columns:
        value = row[columns.index(key)]
        return None if value is None else value
    return None
