#!/usr/bin/env python3
"""Lyric importer for Lyric Sync: paste-in text, extracted files, or whole folders.

Lets the product owner add full lyric text that they hold rights to (e.g. text
licensed through CCLI, supplied by an artist/publisher, or otherwise cleared),
or public-domain text, with honest provenance on every row.

Three modes:

1. Paste-in (original):  --title X --artist Y --file lyrics.txt
   Plain text, parsed verbatim with optional [Section] markers.

2. File extraction:      --file song.pdf            (or .txt/.md)
   Lyrics are *extracted from the file itself* (tools/lyric_extract.py):
   PDF hymn sheets (Flate streams, WinAnsi text) and structured TXT lyric
   files ("TITLE - ARTIST" header, Source:/Published: lines, [Verse]
   markers). Title/artist are derived from the file header or filename
   (matched against known database artists); --title/--artist override.

3. Batch folder:         --batch DIR
   Every .pdf/.txt/.md under DIR is extracted and imported. Metadata comes
   from each file; existing songs with lyrics are skipped; metadata-only rows
   are upgraded in place. One backup, one recompute, one validation per run.

Copyright status is explicit: --status USER_IMPORTED (default, requires
attestation of clearance) or --status PUBLIC_DOMAIN (pre-1929 / traditional /
anonymous works). METADATA_ONLY rows never receive lyric text through this
tool's default paths.

Provenance on every imported song:
    filename + SHA-256 + file's own Source/Words-by lines + status attestation.

Examples
--------
    tools\\import_user_lyrics.py --title "My Song" --artist "Some Artist" ^
        --file my_song.txt --songwriter "Some Writer" --year 2020 ^
        --source "Licensed via CCLI #123456"

    tools\\import_user_lyrics.py --file hymns\\WhenWeAllGettoHeaven.pdf ^
        --status PUBLIC_DOMAIN --songwriter "Eliza E. Hewitt" --year 1900

    tools\\import_user_lyrics.py --batch C:\\lyrics\\songpack --dry-run

Use --dry-run to preview without writing. This is a developer tool (tools/);
the application itself never writes to the .lsdb.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsdb_write as W  # noqa: E402
import lyric_extract as X  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "lyric_sync_gospel.lsdb")

SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
SUPPORTED_EXTS = (".pdf", ".txt", ".md")

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


def parse_lyrics_text(raw: str) -> list[tuple[str, list[str]]]:
    """Return [(section_type, [lines])]."""
    sections: list[tuple[str, list[str]]] = []
    current_type = "Verse 1"
    current_lines: list[str] = []
    last_blank = False

    def flush():
        nonlocal current_lines
        if current_lines:
            sections.append((current_type, current_lines))
            current_lines = []

    for line in raw.splitlines():
        stripped = line.strip()
        m = SECTION_RE.match(stripped)
        if m:
            flush()
            current_type = m.group(1).strip()
            last_blank = False
            continue
        if stripped == "":
            if current_lines and not last_blank:
                # blank line -> close section, next header-less line begins a new verse
                flush()
                current_type = f"Verse {len(sections) + 1}"
            last_blank = True
            continue
        current_lines.append(line.rstrip())
        last_blank = False
    flush()
    return sections


def find_existing_song(con, title, artist):
    """Exact (title, artist) match; falls back to title-only when the artist
    is unknown, so file imports don't duplicate a known recording."""
    nt, na = W.normalize(title), W.normalize(artist)
    row = con.execute(
        "SELECT id, copyright_status FROM songs "
        "WHERE normalized_title=? AND normalized_artist=?", (nt, na)
    ).fetchone()
    if row:
        return row
    if na == "unknown artist":
        return con.execute(
            "SELECT id, copyright_status FROM songs "
            "WHERE normalized_title=? ORDER BY id LIMIT 1", (nt,)
        ).fetchone()
    return None


def db_known_artists(con) -> list[str]:
    rows = con.execute("SELECT DISTINCT artist FROM songs").fetchall()
    return [r[0] for r in rows if r[0] and r[0] != "Unknown Artist"]


def build_provenance(filename: str, kind: str, sha: str, origin_note,
                     status: str, extra_source) -> str:
    bits = [f"Imported from {filename} ({kind.upper()}, sha256 {sha})"]
    if origin_note:
        bits.append(origin_note)
    bits.append(ATTESTATION[status])
    if extra_source:
        bits.append(extra_source)
    return "; ".join(bits)


def song_has_lyrics(con, song_id: str) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM lyrics WHERE song_id=?", (song_id,)
    ).fetchone()[0]


def import_song(con, *, title, artist, stanzas, provenance, status,
                songwriter, year, language, subgenre, song_type, country,
                region):
    """Insert or upgrade one song + its lyric lines. Caller commits.

    Returns (action, song_id, line_count) where action is
    'create' | 'upgrade' | 'skip' (already has lyrics).
    """
    existing = find_existing_song(con, title, artist)
    if existing:
        song_id, _prev_status = existing
        n_existing = song_has_lyrics(con, song_id)
        if n_existing:
            return ("skip", song_id, n_existing)
        # metadata-only row -> upgrade in place, keeping its identity/artist
        db_artist = con.execute(
            "SELECT artist FROM songs WHERE id=?", (song_id,)
        ).fetchone()[0]
        con.execute(
            "UPDATE songs SET copyright_status=?, lyrics_status='FULL_LYRICS', "
            "source=?, songwriter=?, release_year=?, updated_at=? WHERE id=?",
            (status, provenance, songwriter or db_artist, year,
             W.now_iso(), song_id),
        )
        action = "upgrade"
    else:
        song_id = f"user_{W.slug(artist)}_{W.slug(title)[:40]}"
        base, suf = song_id, 2
        while con.execute("SELECT 1 FROM songs WHERE id=?", (song_id,)).fetchone():
            song_id = f"{base}_{suf}"; suf += 1
        con.execute(
            f"INSERT INTO songs ({', '.join(W.PROD_SONG_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in W.PROD_SONG_COLUMNS)})",
            W.song_row(
                song_id=song_id, title=title, artist=artist,
                songwriter=songwriter or artist,
                publisher="User imported",
                copyright_status=status,
                lyrics_status="FULL_LYRICS",
                source=provenance, source_url=None,
                country=country, region=region,
                language=language, subgenre=subgenre,
                song_type=song_type, album=None, release_year=year,
                aliases=[title, artist],
            ),
        )
        action = "create"

    lrows = W.lyric_rows(song_id, stanzas, language=language,
                         source=provenance, copyright_status=status)
    con.executemany(
        f"INSERT INTO lyrics ({', '.join(W.PROD_LYRIC_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in W.PROD_LYRIC_COLUMNS)})", lrows)

    # rebuild search rows from DB (picks up aliases + lyric lines)
    W.rebuild_search_rows_for_song(con, song_id)
    return (action, song_id, len(lrows))


def backup_db(db_path: str, tag: str) -> str | None:
    if not os.path.exists(db_path):
        return None
    bdir = os.path.join(os.path.dirname(db_path), "data", "backups")
    os.makedirs(bdir, exist_ok=True)
    stamp = W.now_iso().replace(":", "").replace("-", "")
    bpath = os.path.join(bdir, f"lyric_sync_gospel_pre_{tag}_{stamp}.lsdb")
    shutil.copy2(db_path, bpath)
    return bpath


def open_db(db_path: str, dry_run: bool):
    if dry_run and os.path.exists(db_path):
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    return W.open_writable(db_path)


def collect_batch_files(batch_dir: str) -> list[str]:
    out: list[str] = []
    for dirpath, _dirs, files in os.walk(batch_dir):
        for name in sorted(files):
            if name.lower().endswith(SUPPORTED_EXTS):
                out.append(os.path.join(dirpath, name))
    return out


def run_single(args, con, known_artists) -> int:
    path = args.file
    if not os.path.exists(path):
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    use_extraction = path.lower().endswith(".pdf") or not (args.title and args.artist)
    if use_extraction:
        try:
            ex = X.extract_file(path, known_artists,
                                title=args.title, artist=args.artist)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        title, artist, stanzas = ex.title, ex.artist, ex.stanzas
        provenance = build_provenance(
            os.path.basename(path), ex.kind, X.file_sha256(path),
            ex.origin_note, args.status, args.source)
        if ex.origin_note:
            print(f"Origin   : {ex.origin_note}")
    else:
        # legacy paste-in: verbatim text with optional [Section] markers
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        stanzas = parse_lyrics_text(raw)
        title, artist = args.title, args.artist
        provenance = args.source or (
            "User-imported text provided directly by the product owner "
            f"({args.status}); rights holder attests clearance."
        )

    total_lines = sum(len(lines) for _st, lines in stanzas)
    if total_lines == 0:
        print("ERROR: no lyric lines found in file.", file=sys.stderr)
        return 2

    print(f"Title    : {title}")
    print(f"Artist   : {artist}")
    print(f"Status   : {args.status}")
    print(f"Sections : {len(stanzas)}")
    print(f"Lines    : {total_lines}")
    for st, lines in stanzas:
        print(f"  [{st}] {len(lines)} lines")
    print(f"Provenance: {provenance}")

    if args.dry_run:
        print("\n(dry-run: no changes written)")
        return 0

    bpath = None if args.no_backup else backup_db(args.db, "userimport")
    if bpath:
        print(f"Backup   : {bpath}")

    # `con` is the writable connection opened by main() for non-dry runs
    # (idle connections hold no file locks, so the backup above was safe).
    try:
        action, song_id, n = import_song(
            con, title=title, artist=artist, stanzas=stanzas,
            provenance=provenance, status=args.status,
            songwriter=args.songwriter, year=args.year,
            language=args.language, subgenre=args.subgenre,
            song_type=args.song_type, country=args.country,
            region=args.region)
        if action == "skip":
            print(f"ABORT: {song_id} already has {n} lyric lines; nothing changed.")
            return 3
        stats = W.recompute_metadata(
            con, version=args.version,
            bump_note=f"{action}_import_{W.slug(title)[:24]}_{W.now_iso()[:10]} "
                      f"({args.status})")
        con.commit()
        v = W.validate(con)
        verb = "Inserted" if action == "create" else "Upgraded"
        print(f"\n{verb} {n} lyric lines into {song_id} ({action})")
        print("RECOMPUTED:", stats)
        print("VALIDATE:", v)
        return 0 if v["ok"] else 4
    finally:
        con.close()


def run_batch(args, con, known_artists) -> int:
    files = collect_batch_files(args.batch)
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"ERROR: no {'/'.join(SUPPORTED_EXTS)} files under {args.batch}",
              file=sys.stderr)
        return 2
    print(f"Batch    : {len(files)} files from {args.batch}")
    print(f"Status   : {args.status}")
    if args.dry_run:
        print("(dry-run: database opened read-only)\n")
    else:
        bpath = None if args.no_backup else backup_db(args.db, "batchimport")
        if bpath:
            print(f"Backup   : {bpath}")
        print()

    created, upgraded, skipped, failed = [], [], [], []
    seen: set[tuple[str, str]] = set()

    for i, path in enumerate(files, start=1):
        name = os.path.relpath(path, args.batch)
        try:
            ex = X.extract_file(path, known_artists)
        except (ValueError, OSError) as exc:
            print(f"[{i:3}/{len(files)}] FAIL {name}: {exc}")
            failed.append((name, str(exc)))
            continue

        key = (W.normalize(ex.title), W.normalize(ex.artist))
        if key in seen:
            print(f"[{i:3}/{len(files)}] DUP  {name}: {ex.title!r} "
                  f"({ex.artist}) already handled in this batch")
            skipped.append((name, "duplicate in batch"))
            continue
        seen.add(key)

        provenance = build_provenance(
            os.path.basename(path), ex.kind, X.file_sha256(path),
            ex.origin_note, args.status, args.source)

        print(f"[{i:3}/{len(files)}] {ex.title!r} — {ex.artist} — "
              f"{ex.line_count} lines, {len(ex.stanzas)} sections")

        if args.dry_run:
            existing = find_existing_song(con, ex.title, ex.artist)
            if existing:
                sid = existing[0]
                n = song_has_lyrics(con, sid)
                if n:
                    label = f"skip {sid} (already has {n} lines)"
                    skipped.append((name, label))
                else:
                    label = f"upgrade {sid} (metadata-only)"
                    upgraded.append((name, label))
            else:
                label = "create"
                created.append((name, label))
            print(f"         -> {label}")
            continue

        action, song_id, n = import_song(
            con, title=ex.title, artist=ex.artist, stanzas=ex.stanzas,
            provenance=provenance, status=args.status,
            songwriter=args.songwriter, year=args.year,
            language=args.language, subgenre=args.subgenre,
            song_type=args.song_type, country=args.country,
            region=args.region)
        con.commit()  # per-song commit keeps partial progress on long runs
        if action == "create":
            print(f"         -> created {song_id} ({n} lines)")
            created.append((name, song_id))
        elif action == "upgrade":
            print(f"         -> upgraded {song_id} ({n} lines)")
            upgraded.append((name, song_id))
        else:
            print(f"         -> skipped {song_id} (already has {n} lines)")
            skipped.append((name, song_id))

    print(f"\n==== Batch summary: {len(created)} created, {len(upgraded)} "
          f"upgraded, {len(skipped)} skipped, {len(failed)} failed ====")
    if failed:
        print("Failed files:")
        for name, err in failed:
            print(f"  {name}: {err}")

    if args.dry_run:
        print("\n(dry-run: no changes written)")
        return 0

    if not (created or upgraded):
        print("Nothing imported; database untouched beyond backup.")
        return 0

    stats = W.recompute_metadata(
        con, version=args.version,
        bump_note=f"batch_import_{len(created) + len(upgraded)}_songs_"
                  f"{W.now_iso()[:10]} ({args.status})")
    con.commit()
    v = W.validate(con)
    print("RECOMPUTED:", stats)
    print("VALIDATE:", v)
    return 0 if v["ok"] else 4


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Import lyrics from pasted text, extracted files, or a folder.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", help="Lyrics file: .pdf/.txt/.md (extracted) "
                                     "or plain text with --title/--artist")
    mode.add_argument("--batch", help="Folder of .pdf/.txt/.md lyric files")
    ap.add_argument("--title", default=None, help="Override derived title")
    ap.add_argument("--artist", default=None, help="Override derived artist")
    ap.add_argument("--songwriter", default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--source", default=None,
                    help="Extra provenance note appended to the attestation")
    ap.add_argument("--status", choices=("USER_IMPORTED", "PUBLIC_DOMAIN"),
                    default="USER_IMPORTED",
                    help="Copyright status of the imported text (default USER_IMPORTED)")
    ap.add_argument("--language", default="English")
    ap.add_argument("--subgenre", default="Contemporary Gospel")
    ap.add_argument("--song-type", default="Song")
    ap.add_argument("--country", default="United States")
    ap.add_argument("--region", default="North America")
    ap.add_argument("--version", default="3.3.0",
                    help="database_version recorded on recompute")
    ap.add_argument("--limit", type=int, default=None,
                    help="Batch only: process at most N files")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    con = open_db(args.db, args.dry_run)
    try:
        known_artists = db_known_artists(con)
        if args.file:
            return run_single(args, con, known_artists)
        return run_batch(args, con, known_artists)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
