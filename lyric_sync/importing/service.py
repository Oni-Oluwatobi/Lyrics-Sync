"""In-app lyric import: add user-supplied PDF/TXT/MD lyric files.

This is the application-side port of ``tools/import_user_lyrics.py``. It only
ever writes text the user supplies, records sha256 provenance on every row,
backs the database up first, and rebuilds the search index for each song.

The caller must close any open reader (the search service) before importing:
SQLite allows one writer, and the app keeps its own connection open.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from lyric_sync.importing import extract as X
from lyric_sync.importing import writer as W

SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md")

ATTESTATION = {
    "USER_IMPORTED": (
        "USER_IMPORTED: product owner attests rights clearance "
        "(CCLI-licensed, supplied by artist/publisher, or otherwise cleared)"
    ),
    "PUBLIC_DOMAIN": (
        "PUBLIC_DOMAIN: product owner attests pre-1929 publication, "
        "traditional/anonymous authorship, or author death before 1956"
    ),
}

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class ImportOutcome:
    """What one import run did."""

    created: list[tuple[str, str]] = field(default_factory=list)
    upgraded: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    backup_path: str | None = None
    stats: dict = field(default_factory=dict)
    line_total: int = 0

    @property
    def imported(self) -> int:
        return len(self.created) + len(self.upgraded)

    def summary(self) -> str:
        """One-line result for the Settings page."""
        if not any((self.created, self.upgraded, self.skipped, self.failed)):
            return "No lyric files were processed."
        bits: list[str] = []
        if self.created:
            bits.append(f"{len(self.created)} new song(s)")
        if self.upgraded:
            bits.append(f"{len(self.upgraded)} upgraded")
        if self.skipped:
            bits.append(f"{len(self.skipped)} already had lyrics")
        if self.failed:
            bits.append(f"{len(self.failed)} failed")
        text = "Lyric import: " + ", ".join(bits)
        if self.line_total:
            text += f" ({self.line_total:,} lines)"
        text += "."
        if self.stats:
            text += (
                f"  Database now {self.stats['total_songs']:,} songs · "
                f"{self.stats['total_lyrics']:,} lyric lines."
            )
        return text


class LyricImportService:
    """Import lyric files into one ``.LSDB`` file."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        language: str = "English",
        subgenre: str = "Contemporary Gospel",
        country: str = "United States",
        region: str = "North America",
        song_type: str = "Song",
    ) -> None:
        self.db_path = Path(db_path)
        self.language = language
        self.subgenre = subgenre
        self.country = country
        self.region = region
        self.song_type = song_type

    # ------------------------------------------------------------------ api

    def import_files(
        self,
        paths: Sequence[str | Path],
        *,
        status: str = "USER_IMPORTED",
        progress: ProgressCallback | None = None,
    ) -> ImportOutcome:
        """Import the given files (only supported suffixes are considered)."""
        files = [
            Path(path)
            for path in paths
            if Path(path).is_file()
            and Path(path).suffix.lower() in SUPPORTED_SUFFIXES
        ]
        return self._run(files, status=status, progress=progress)

    def import_folder(
        self,
        folder: str | Path,
        *,
        status: str = "USER_IMPORTED",
        progress: ProgressCallback | None = None,
    ) -> ImportOutcome:
        """Import every supported lyric file under ``folder``."""
        root = Path(folder)
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
        return self._run(files, status=status, progress=progress)

    # ------------------------------------------------------------ internals

    def _run(
        self,
        files: list[Path],
        *,
        status: str,
        progress: ProgressCallback | None,
    ) -> ImportOutcome:
        outcome = ImportOutcome()
        if not files:
            return outcome
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        if status not in ATTESTATION:
            raise ValueError(f"unsupported import status: {status}")

        outcome.backup_path = self._backup()
        connection = W.open_writable(str(self.db_path))
        try:
            known_artists = _known_artists(connection)
            seen: set[tuple[str, str]] = set()
            total = len(files)
            for index, path in enumerate(files, start=1):
                name = path.name
                if progress is not None:
                    progress(index, total, name)
                try:
                    extracted = X.extract_file(str(path), known_artists)
                except (ValueError, OSError) as exc:
                    outcome.failed.append((name, str(exc)))
                    continue

                key = (W.normalize(extracted.title), W.normalize(extracted.artist))
                if key in seen:
                    outcome.skipped.append((name, "duplicate in this batch"))
                    continue
                seen.add(key)

                provenance = _provenance(path, extracted, status)
                try:
                    action, song_id, lines = self._import_song(
                        connection, extracted, provenance, status
                    )
                    connection.commit()
                except sqlite3.Error as exc:
                    connection.rollback()
                    outcome.failed.append(
                        (name, f"{exc.__class__.__name__}: {exc}")
                    )
                    continue

                if action == "create":
                    outcome.created.append((name, song_id))
                elif action == "upgrade":
                    outcome.upgraded.append((name, song_id))
                else:
                    outcome.skipped.append(
                        (name, f"already has {lines} lyric lines")
                    )
                if action != "skip":
                    outcome.line_total += lines

            if outcome.created or outcome.upgraded:
                outcome.stats = W.recompute_metadata(
                    connection,
                    version=None,
                    bump_note=(
                        f"in-app import {outcome.imported} song(s) "
                        f"{W.now_iso()[:10]} ({status})"
                    ),
                )
                connection.commit()
                check = W.validate(connection)
                if not check["ok"]:
                    outcome.failed.extend(
                        ("database validation", problem)
                        for problem in check["problems"]
                    )
        finally:
            connection.close()
        return outcome

    def _import_song(
        self,
        connection: sqlite3.Connection,
        extracted: X.Extracted,
        provenance: str,
        status: str,
    ) -> tuple[str, str, int]:
        title, artist, stanzas = (
            extracted.title,
            extracted.artist,
            extracted.stanzas,
        )
        existing = _find_existing(connection, title, artist)
        if existing:
            song_id = existing[0]
            count = connection.execute(
                "SELECT COUNT(*) FROM lyrics WHERE song_id=?", (song_id,)
            ).fetchone()[0]
            if count:
                return ("skip", song_id, count)
            db_artist = connection.execute(
                "SELECT artist FROM songs WHERE id=?", (song_id,)
            ).fetchone()[0]
            connection.execute(
                "UPDATE songs SET copyright_status=?, lyrics_status='FULL_LYRICS', "
                "source=?, songwriter=?, updated_at=? WHERE id=?",
                (status, provenance, db_artist, W.now_iso(), song_id),
            )
            action = "upgrade"
        else:
            song_id = f"user_{W.slug(artist)}_{W.slug(title)[:40]}"
            base, suffix = song_id, 2
            while connection.execute(
                "SELECT 1 FROM songs WHERE id=?", (song_id,)
            ).fetchone():
                song_id = f"{base}_{suffix}"
                suffix += 1
            connection.execute(
                f"INSERT INTO songs ({', '.join(W.PROD_SONG_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in W.PROD_SONG_COLUMNS)})",
                W.song_row(
                    song_id=song_id,
                    title=title,
                    artist=artist,
                    songwriter=artist,
                    publisher="User imported",
                    copyright_status=status,
                    lyrics_status="FULL_LYRICS",
                    source=provenance,
                    source_url=None,
                    country=self.country,
                    region=self.region,
                    language=self.language,
                    subgenre=self.subgenre,
                    song_type=self.song_type,
                    album=None,
                    release_year=None,
                    aliases=[title, artist],
                ),
            )
            action = "create"

        rows = W.lyric_rows(
            song_id,
            stanzas,
            language=self.language,
            source=provenance,
            copyright_status=status,
        )
        connection.executemany(
            f"INSERT INTO lyrics ({', '.join(W.PROD_LYRIC_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in W.PROD_LYRIC_COLUMNS)})",
            rows,
        )
        W.rebuild_search_rows_for_song(connection, song_id)
        return (action, song_id, len(rows))

    def _backup(self) -> str | None:
        """Copy the database beside itself (or into user data) before writing."""
        if not self.db_path.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folders = [self.db_path.parent / "data" / "backups"]
        try:  # keep the app importable without the UI stack
            from lyric_sync.app.config import user_data_dir

            folders.append(user_data_dir() / "backups")
        except Exception:  # noqa: BLE001 - optional fallback location
            pass
        for folder in folders:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / (
                    f"{self.db_path.stem}_pre_import_{stamp}{self.db_path.suffix}"
                )
                shutil.copy2(self.db_path, target)
                return str(target)
            except OSError:
                continue
        return None


def _find_existing(
    connection: sqlite3.Connection, title: str, artist: str
) -> tuple[str, str] | None:
    """Exact (title, artist) match; title-only when the artist is unknown."""
    norm_title, norm_artist = W.normalize(title), W.normalize(artist)
    row = connection.execute(
        "SELECT id, copyright_status FROM songs "
        "WHERE normalized_title=? AND normalized_artist=?",
        (norm_title, norm_artist),
    ).fetchone()
    if row:
        return row
    if norm_artist == "unknown artist":
        return connection.execute(
            "SELECT id, copyright_status FROM songs "
            "WHERE normalized_title=? ORDER BY id LIMIT 1",
            (norm_title,),
        ).fetchone()
    return None


def _known_artists(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute("SELECT DISTINCT artist FROM songs").fetchall()
    return [row[0] for row in rows if row[0] and row[0] != "Unknown Artist"]


def _provenance(path: Path, extracted: X.Extracted, status: str) -> str:
    bits = [
        f"Imported from {path.name} "
        f"({extracted.kind.upper()}, sha256 {X.file_sha256(path)})"
    ]
    if extracted.origin_note:
        bits.append(extracted.origin_note)
    bits.append(ATTESTATION[status])
    return "; ".join(bits)
