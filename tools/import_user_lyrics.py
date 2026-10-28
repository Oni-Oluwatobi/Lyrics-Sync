#!/usr/bin/env python3
"""Paste-in USER_IMPORTED lyric importer for Lyric Sync (item 3).

Lets the product owner add full lyric text that they hold rights to (e.g. text
licensed through CCLI, supplied by an artist/publisher, or otherwise cleared).
The row enters under copyright_status=USER_IMPORTED / lyrics_status=FULL_LYRICS
with provenance, mirroring the existing record user_import_nmwy_20261020.

This is a developer tool (lives in tools/, beside build_gospel_db.py). The
application itself never writes to the .lsdb.

Lyrics file format (plain text):
    * Optional section header lines wrapped in brackets start a new section,
      e.g.  [Chorus]   [Verse 2]   [Bridge]
    * A blank line with no header also starts a new section.
    * Every other non-empty line is one lyric line, stored verbatim.

Example
-------
    tools\\import_user_lyrics.py ^
        --title "My Song" --artist "Some Artist" ^
        --file my_song.txt --songwriter "Some Writer" --year 2020 ^
        --source "Licensed via CCLI #123456, imported 2026-10-28"

Use --dry-run to preview parsing without writing.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsdb_write as W  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "lyric_sync_gospel.lsdb")

SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


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
        if not current_lines and last_blank:
            # starting fresh after a blank
            pass
        current_lines.append(line.rstrip())
        last_blank = False
    flush()
    return sections


def find_existing_song(con, title, artist):
    nt, na = W.normalize(title), W.normalize(artist)
    row = con.execute(
        "SELECT id, copyright_status FROM songs "
        "WHERE normalized_title=? AND normalized_artist=?", (nt, na)
    ).fetchone()
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import USER_IMPORTED lyrics.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", required=True)
    ap.add_argument("--file", required=True, help="Path to plain-text lyrics file")
    ap.add_argument("--songwriter", default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--source", default=None, help="Provenance note (rights basis)")
    ap.add_argument("--language", default="English")
    ap.add_argument("--subgenre", default="Contemporary Gospel")
    ap.add_argument("--song-type", default="Song")
    ap.add_argument("--country", default="United States")
    ap.add_argument("--region", default="North America")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    with open(args.file, encoding="utf-8") as fh:
        raw = fh.read()
    stanzas = parse_lyrics_text(raw)
    total_lines = sum(len(lines) for _st, lines in stanzas)
    if total_lines == 0:
        print("ERROR: no lyric lines found in file.", file=sys.stderr)
        return 2

    provenance = args.source or (
        "User-imported text provided directly by the product owner "
        "(USER_IMPORTED); rights holder attests clearance."
    )

    print(f"Title    : {args.title}")
    print(f"Artist   : {args.artist}")
    print(f"Sections : {len(stanzas)}")
    print(f"Lines    : {total_lines}")
    for st, lines in stanzas:
        print(f"  [{st}] {len(lines)} lines")
    print(f"Provenance: {provenance}")

    if args.dry_run:
        print("\n(dry-run: no changes written)")
        return 0

    # Backup unless disabled
    if not args.no_backup and os.path.exists(args.db):
        bdir = os.path.join(os.path.dirname(args.db), "data", "backups")
        os.makedirs(bdir, exist_ok=True)
        stamp = W.now_iso().replace(":", "").replace("-", "")
        bpath = os.path.join(bdir, f"lyric_sync_gospel_pre_userimport_{stamp}.lsdb")
        shutil.copy2(args.db, bpath)
        print(f"Backup   : {bpath}")

    con = W.open_writable(args.db)
    try:
        existing = find_existing_song(con, args.title, args.artist)
        if existing:
            song_id, status = existing
            has_lyrics = con.execute(
                "SELECT COUNT(*) FROM lyrics WHERE song_id=?", (song_id,)
            ).fetchone()[0]
            if has_lyrics:
                print(f"ABORT: {song_id} already has {has_lyrics} lyric lines.")
                return 3
            # upgrade metadata-only row to hold text
            con.execute(
                "UPDATE songs SET copyright_status='USER_IMPORTED', "
                "lyrics_status='FULL_LYRICS', source=?, songwriter=?, "
                "release_year=?, updated_at=? WHERE id=?",
                (provenance, args.songwriter or args.artist, args.year,
                 W.now_iso(), song_id),
            )
            print(f"Upgraded existing song: {song_id} (was {status})")
        else:
            song_id = f"user_{W.slug(args.artist)}_{W.slug(args.title)[:40]}"
            base, suf = song_id, 2
            while con.execute("SELECT 1 FROM songs WHERE id=?", (song_id,)).fetchone():
                song_id = f"{base}_{suf}"; suf += 1
            con.execute(
                f"INSERT INTO songs ({', '.join(W.PROD_SONG_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in W.PROD_SONG_COLUMNS)})",
                W.song_row(
                    song_id=song_id, title=args.title, artist=args.artist,
                    songwriter=args.songwriter or args.artist,
                    publisher="User imported",
                    copyright_status="USER_IMPORTED",
                    lyrics_status="FULL_LYRICS",
                    source=provenance, source_url=None,
                    country=args.country, region=args.region,
                    language=args.language, subgenre=args.subgenre,
                    song_type=args.song_type, album=None, release_year=args.year,
                    aliases=[args.title, args.artist],
                ),
            )
            print(f"Created new song: {song_id}")

        lrows = W.lyric_rows(song_id, stanzas, language=args.language,
                             source=provenance, copyright_status="USER_IMPORTED")
        con.executemany(
            f"INSERT INTO lyrics ({', '.join(W.PROD_LYRIC_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in W.PROD_LYRIC_COLUMNS)})", lrows)

        # rebuild search rows from DB (picks up aliases + lyric lines)
        W.rebuild_search_rows_for_song(con, song_id)

        stats = W.recompute_metadata(
            con, version="3.3.0",
            bump_note=f"user_import_{W.slug(args.title)[:24]}_20261028 (USER_IMPORTED)")
        con.commit()
        v = W.validate(con)
        print(f"\nInserted {len(lrows)} lyric lines into {song_id}")
        print("RECOMPUTED:", stats)
        print("VALIDATE:", v)
        return 0 if v["ok"] else 4
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
