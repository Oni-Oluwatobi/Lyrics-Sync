"""Expand the production Gospel catalogue with verified Nigerian artist metadata.

Reads the researched catalogues in ``data/ng_expansion/*.json`` (metadata only —
song titles, credits, albums, release years, source URLs; NO lyric text) and
inserts them into the production database as METADATA_ONLY records, preserving
the existing schema, FTS, indexes, provenance architecture and search engine.

Usage:
    python tools/expand_ng_catalog.py            # dry run + duplicate report
    python tools/expand_ng_catalog.py --commit   # apply, validate, smoke test

Rights: modern copyrighted songs are stored METADATA_ONLY. No lyrics are
scraped, fabricated or reproduced.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_DB = ROOT / "lyric_sync_gospel.lsdb"
CATALOG_DIR = ROOT / "data" / "ng_expansion"
REPORT_DIR = CATALOG_DIR

CATALOGS = {
    "dunsin_oyekan.json": {
        "artist": "Dunsin Oyekan", "base": "dunsin oyekan",
        "publisher": "Dunsin Oyekan Ministries",
        "site": "https://dunsinoyekan.com",
        "manifest_title": "Dunsin Oyekan official catalogue (metadata)",
    },
    "lawrence_oyor.json": {
        "artist": "Lawrence Oyor", "base": "lawrence oyor",
        "publisher": "Davidic Generation",
        "site": "https://lawrenceoyor.com",
        "manifest_title": "Lawrence Oyor / Davidic Generation catalogue (metadata)",
    },
    "mercy_chinwo.json": {
        "artist": "Mercy Chinwo", "base": "mercy chinwo",
        "publisher": "EeZee Conceptz / GNT Nation",
        "site": "https://eezeeconceptz.org",
        "manifest_title": "Mercy Chinwo / GNT Nation catalogue (metadata)",
    },
    "nathaniel_bassey.json": {
        "artist": "Nathaniel Bassey", "base": "nathaniel bassey",
        "publisher": "Nathaniel Bassey Ministries",
        "site": "https://nathanielbassey.net",
        "manifest_title": "Nathaniel Bassey official discography (metadata)",
    },
    "minister_mike.json": {
        "artist": "Minister Mike", "base": "minister mike",
        "publisher": "Independent",
        "site": "https://www.instagram.com/minister__mike/",
        "manifest_title": "Minister Mike (Aregbesola Micheal Oluwadamilare) catalogue (metadata)",
    },
    "greatman_takit.json": {
        "artist": "Greatman Takit", "base": "greatman takit",
        "publisher": "Independent",
        "site": "https://greatmantakit.com",
        "manifest_title": "Greatman Takit official catalogue (metadata)",
    },
    "bidemi_olaoba.json": {
        "artist": "Bidemi Olaoba", "base": "bidemi olaoba",
        "publisher": "Independent", "site": "",
        "manifest_title": "Bidemi Olaoba catalogue (metadata)",
    },
    "festizie.json": {
        "artist": "Festizie", "base": "festizie",
        "publisher": "Independent", "site": "",
        "manifest_title": "Festizie catalogue (metadata)",
    },
    "marizu.json": {
        "artist": "Marizu", "base": "marizu",
        "publisher": "Independent", "site": "",
        "manifest_title": "Marizu catalogue (metadata)",
    },
    "midnight_crew.json": {
        "artist": "Midnight Crew", "base": "midnight crew",
        "publisher": "Independent", "site": "",
        "manifest_title": "Midnight Crew catalogue (metadata)",
    },
    "mike_abdul.json": {
        "artist": "Mike Abdul", "base": "mike abdul",
        "publisher": "Independent", "site": "",
        "manifest_title": "Mike Abdul catalogue (metadata)",
    },
    "mr_m_revelation.json": {
        "artist": "Mr M & Revelation", "base": "mr m revelation",
        "publisher": "Independent", "site": "",
        "manifest_title": "Mr M & Revelation catalogue (metadata)",
    },
    "neeja.json": {
        "artist": "Neeja", "base": "neeja",
        "publisher": "Independent", "site": "",
        "manifest_title": "Neeja catalogue (metadata)",
    },
    "sammie_okposo.json": {
        "artist": "Sammie Okposo", "base": "sammie okposo",
        "publisher": "Independent", "site": "",
        "manifest_title": "Sammie Okposo catalogue (metadata)",
    },
    "samsong.json": {
        "artist": "Samsong", "base": "samsong",
        "publisher": "Independent", "site": "",
        "manifest_title": "Samsong catalogue (metadata)",
    },
    "testimony_jaga.json": {
        "artist": "Testimony Jaga", "base": "testimony jaga",
        "publisher": "Independent", "site": "",
        "manifest_title": "Testimony Jaga catalogue (metadata)",
    },
}

# Catalogues whose entries were already imported in a previous pass (their
# guest-credit entries were inserted under the file artist and need the
# artist_credit correction during enrichment).
PASS1_FILES = {
    "dunsin_oyekan.json", "lawrence_oyor.json", "mercy_chinwo.json",
    "nathaniel_bassey.json", "minister_mike.json", "greatman_takit.json",
}

FEAT_SPLIT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with)\s+", re.IGNORECASE)
LYRIC_GUARD = re.compile(r"\S+(?:\s+\S+){15,}")  # >16 words in one field = suspicious


def _load_normalize():
    spec = importlib.util.spec_from_file_location(
        "bgdb", ROOT / "tools" / "build_gospel_db.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bgdb"] = mod
    spec.loader.exec_module(mod)
    return mod.normalize, mod.slug


normalize, slug = _load_normalize()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def artist_base(name: str) -> str:
    return normalize(FEAT_SPLIT.split(name.strip())[0])


def display_artist(primary: str, featured: list[str]) -> str:
    if featured:
        return f"{primary} feat. {', '.join(featured)}"
    return primary


def load_catalogs() -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    rejected: list[str] = []
    for filename, meta in CATALOGS.items():
        path = CATALOG_DIR / filename
        if not path.exists():
            rejected.append(f"{filename}: FILE MISSING")
            continue
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        for i, entry in enumerate(data):
            title = (entry.get("title") or "").strip()
            source_url = (entry.get("source_url") or "").strip()
            if not title:
                rejected.append(f"{filename}[{i}]: missing title")
                continue
            if not source_url:
                rejected.append(f"{filename}[{i}]: '{title}' missing source_url")
                continue
            title_field = str(entry.get("title") or "")
            album_field = str(entry.get("album") or "")
            if (LYRIC_GUARD.search(title_field)
                    or LYRIC_GUARD.search(album_field)):
                rejected.append(f"{filename}[{i}]: '{title}' rejected (text too long)")
                continue
            credit = str(entry.get("artist_credit") or "").strip()
            entry["_file"] = filename
            entry["_primary"] = credit or meta["artist"]
            entry["_base"] = artist_base(credit) if credit else meta["base"]
            entry["_file_base"] = meta["base"]
            entries.append(entry)
    return entries, rejected


def dedupe(entries: list[dict], con: sqlite3.Connection
           ) -> tuple[list[dict], list[str], list[tuple[dict, str]]]:
    existing: dict[tuple[str, str], str] = {}
    existing_ids: set[str] = set()
    existing_urls: dict[str, str] = {}
    for row in con.execute("SELECT id, normalized_title, artist, source_url FROM songs"):
        existing_ids.add(row[0])
        existing[(row[1], artist_base(row[2]))] = row[0]
        if row[3] and str(row[3]).strip():
            existing_urls.setdefault(str(row[3]).strip(), row[0])

    skips: list[str] = []
    kept: list[dict] = []
    enrich: list[tuple[dict, str]] = []
    batch_seen: dict[tuple[str, str, str], str] = {}
    batch_urls: set[str] = set()
    for entry in entries:
        ntitle = normalize(entry["title"])
        base = artist_base(display_artist(entry["_primary"], entry.get("featured") or []))
        key = (ntitle, base)
        if key in existing:
            skips.append(f"EXISTS   {entry['title']!r} by {base} -> {existing[key]}")
            enrich.append((entry, existing[key]))
            continue
        # pass-1 catalogues: guest-credit entries were imported under the file
        # artist — detect them by title + file base so they enrich, not duplicate.
        fkey = (ntitle, entry["_file_base"])
        if entry["_file"] in PASS1_FILES and fkey != key and fkey in existing:
            skips.append(f"EXISTS   {entry['title']!r} by {entry['_file_base']}"
                         f" -> {existing[fkey]} (pass-1 record)")
            enrich.append((entry, existing[fkey]))
            continue
        url = str(entry.get("source_url") or "").strip()
        if url and url in existing_urls:
            skips.append(f"EXISTS-URL {entry['title']!r} -> {existing_urls[url]}")
            enrich.append((entry, existing_urls[url]))
            continue
        if url and url in batch_urls:
            skips.append(f"IN-BATCH-URL {entry['title']!r} (same recording URL)")
            continue
        version_key = normalize(entry.get("version") or "")
        bkey = (ntitle, base, version_key)
        if bkey in batch_seen:
            skips.append(f"IN-BATCH {entry['title']!r} by {base} (dup of {batch_seen[bkey]!r})")
            continue
        batch_seen[bkey] = entry["title"]
        if url:
            batch_urls.add(url)
        kept.append(entry)

    # unique ids
    for entry in kept:
        base_id = f"ng_{slug(entry['_base'])}_{slug(entry['title'])[:60]}".strip("_")
        song_id = base_id
        suffix = 2
        while song_id in existing_ids or any(e.get("_id") == song_id for e in kept):
            song_id = f"{base_id}_{suffix}"
            suffix += 1
        entry["_id"] = song_id
    return kept, skips, enrich


def build_rows(kept: list[dict]) -> dict[str, list[tuple]]:
    songs, indexes, fts, artists = [], [], [], []
    artist_names_seen: set[str] = set()
    ts = now_iso()
    for entry in kept:
        featured = entry.get("featured") or []
        display = display_artist(entry["_primary"], featured)
        album = (entry.get("album") or "").strip() or None
        title = entry["title"]
        language = str(entry.get("language") or "").strip() or "unknown"
        songwriter = (entry.get("songwriter") or "").strip() or entry["_primary"]
        publisher = (entry.get("publisher") or "").strip() or CATALOGS[entry["_file"]]["publisher"]
        version = entry.get("version")
        note_bits = [b for b in (version and f"version: {version}" or "",) if b]
        aliases = [display, title]
        if album and normalize(album) != normalize(title):
            aliases.append(album)
        if version:
            aliases.append(f"{title} ({version})")
        aliases = list(dict.fromkeys(a for a in aliases if a))
        song_type = "Chant" if "chant" in normalize(title) else "Congregational"
        confidence = entry.get("confidence") or "high"
        verification = "VERIFIED" if confidence == "high" else "PROVISIONAL"
        source = f"{entry.get('source_name') or 'verified catalogue'} (metadata only)"
        alias_text = " ".join(normalize(a) for a in aliases)
        searchable = " ".join(x for x in (
            normalize(title), normalize(display), alias_text, normalize(album or "")
        ) if x)
        songs.append((
            entry["_id"], title, normalize(title), display, normalize(display),
            album, entry.get("release_year"), "Nigeria", "West Africa", language,
            "Gospel", "Contemporary Worship", song_type, songwriter, publisher,
            "METADATA_ONLY", "METADATA_ONLY", source, source_url_of(entry),
            json.dumps(aliases), 1, 1, verification, ts, ts,
        ))
        indexes.append((f"idx_{entry['_id']}", entry["_id"], title, display,
                        alias_text, searchable))
        fts.append((entry["_id"], title, display, alias_text,
                    normalize(album or "")))
        if normalize(display) not in artist_names_seen:
            artist_names_seen.add(normalize(display))
            artists.append((display, normalize(display)))
        _ = note_bits
    return {"songs": songs, "indexes": indexes, "fts": fts, "artists": artists}


def source_url_of(entry: dict) -> str:
    return entry["source_url"]


def common_site(filename: str, entries: list[dict]) -> str:
    """Most-used source domain for a catalogue (build_manifest url fallback)."""
    counts: dict[str, int] = {}
    for e in entries:
        if e.get("_file") != filename:
            continue
        match = re.match(r"https?://([^/]+)", str(e.get("source_url") or ""))
        if match:
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    if not counts:
        return ""
    return f"https://{max(counts.items(), key=lambda kv: kv[1])[0]}"


def apply_enrichment(con: sqlite3.Connection, enrich: list[tuple[dict, str]],
                     ts: str) -> dict[str, int]:
    """Fill empty verified fields and correct pass-1 credit attributions.

    Only rows the catalogue actually improves are touched: empty album / year /
    publisher / language / songwriter / source_url values are filled from the
    researched entry, and an explicit artist_credit (or added featured credits)
    replaces the display artist when the row belongs to the same primary artist
    or to a pass-1 file import. No other column is rewritten; lyric lines,
    rights states and provenance columns are never modified.
    """
    per_artist: dict[str, int] = {}
    for entry, song_id in enrich:
        row = con.execute(
            "SELECT artist, album, release_year, publisher, language,"
            " songwriter, source_url FROM songs WHERE id = ?",
            (song_id,),
        ).fetchone()
        if row is None:
            continue
        cur_artist, cur_album, cur_year, cur_pub, cur_lang, cur_sw, cur_url = row
        sets: list[str] = []
        vals: list = []
        desired = display_artist(entry["_primary"], entry.get("featured") or [])
        has_credit = bool(str(entry.get("artist_credit") or "").strip())
        same_primary = artist_base(cur_artist) == entry["_base"]
        pass1_origin = (entry["_file"] in PASS1_FILES
                        and artist_base(cur_artist) == entry["_file_base"])
        final_album = cur_album
        if (normalize(desired) != normalize(cur_artist)
                and (has_credit or entry.get("featured"))
                and (same_primary or pass1_origin)):
            sets += ["artist = ?", "normalized_artist = ?"]
            vals += [desired, normalize(desired)]
        if entry.get("album") and not str(cur_album or "").strip():
            sets.append("album = ?")
            vals.append(entry["album"])
            final_album = entry["album"]
        if entry.get("release_year") and not cur_year:
            sets.append("release_year = ?")
            vals.append(entry["release_year"])
        if entry.get("publisher") and not str(cur_pub or "").strip():
            sets.append("publisher = ?")
            vals.append(entry["publisher"])
        if entry.get("language") and not str(cur_lang or "").strip():
            sets.append("language = ?")
            vals.append(entry["language"])
        if entry.get("songwriter") and not str(cur_sw or "").strip():
            sets.append("songwriter = ?")
            vals.append(entry["songwriter"])
        if entry.get("source_url") and not str(cur_url or "").strip():
            sets.append("source_url = ?")
            vals.append(entry["source_url"])
        if not sets:
            continue
        sets.append("updated_at = ?")
        vals.append(ts)
        vals.append(song_id)
        con.execute(f"UPDATE songs SET {', '.join(sets)} WHERE id = ?", vals)
        if "artist = ?" in sets:
            # keep the search index in step with the corrected credits
            idx = con.execute(
                "SELECT title, aliases FROM lyric_search_index WHERE song_id = ?",
                (song_id,),
            ).fetchone()
            if idx:
                try:
                    alias_list = json.loads(idx[1]) if idx[1] else []
                except (TypeError, ValueError):
                    alias_list = []
                if desired not in alias_list:
                    alias_list.append(desired)
                alias_text = " ".join(normalize(a) for a in alias_list if a)
                searchable = " ".join(x for x in (
                    normalize(idx[0]), normalize(desired), alias_text,
                    normalize(final_album or ""),
                ) if x)
                con.execute(
                    "UPDATE lyric_search_index SET artist = ?, aliases = ?,"
                    " searchable_text = ? WHERE song_id = ?",
                    (desired, json.dumps(alias_list), searchable, song_id),
                )
                con.execute(
                    "UPDATE lyric_search_fts SET artist = ? WHERE song_id = ?",
                    (desired, song_id),
                )
        name = CATALOGS[entry["_file"]]["artist"]
        per_artist[name] = per_artist.get(name, 0) + 1
    return per_artist


def run(commit: bool) -> int:
    entries, rejected = load_catalogs()
    print(f"catalogues: {len(entries)} entries, {len(rejected)} rejected")

    con = sqlite3.connect(str(PROD_DB))
    con.row_factory = sqlite3.Row
    kept, skips, enrich = dedupe(entries, con)
    print(f"after dedupe: {len(kept)} to insert, {len(skips)} duplicates skipped,"
          f" {len(enrich)} enrichment candidates")

    dup_report = ["NG EXPANSION — DUPLICATE REPORT", f"generated {now_iso()}", ""]
    dup_report += [f"source entries: {len(entries)}  rejected: {len(rejected)}  "
                   f"duplicates skipped: {len(skips)}  to insert: {len(kept)}", ""]
    dup_report += ["-- rejected --"] + rejected + ["", "-- duplicates skipped --"] + skips
    (REPORT_DIR / "duplicate_report.txt").write_text(
        "\n".join(dup_report), encoding="utf-8")

    if not commit:
        per_artist: dict[str, int] = {}
        for e in kept:
            name = CATALOGS[e["_file"]]["artist"]
            per_artist[name] = per_artist.get(name, 0) + 1
        for name in sorted(per_artist):
            print(f"  {name}: +{per_artist[name]}")
        print(f"  enrichment candidates: {len(enrich)}"
              " (field fills / credit fixes, applied only with --commit)")
        for line in skips[:12]:
            print("  ", line)
        if len(skips) > 12:
            print(f"   ... {len(skips) - 12} more (see data/ng_expansion/duplicate_report.txt)")
        con.close()
        print("DRY RUN — no changes written. Re-run with --commit to apply.")
        return 0

    rows = build_rows(kept)
    before = {
        "songs": con.execute("SELECT COUNT(*) FROM songs").fetchone()[0],
        "artists": con.execute("SELECT COUNT(*) FROM artists").fetchone()[0],
        "lyrics": con.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0],
    }

    # artists table: add missing base artists (canonical short name)
    added_artists = 0
    existing_artist_names = {
        r[0] for r in con.execute("SELECT normalized_name FROM artists")}
    artist_inserts = []
    for filename, meta in CATALOGS.items():
        if meta["base"] not in existing_artist_names:
            artist_inserts.append((f"art_{meta['base'].replace(' ', '_')}",
                                   meta["artist"], meta["base"], "Nigeria",
                                   "West Africa", "Gospel", None, None))
            existing_artist_names.add(meta["base"])
            added_artists += 1
    # per-display artist rows (featuring variants) that do not exist yet
    for display, norm_display in rows["artists"]:
        if norm_display not in existing_artist_names:
            artist_inserts.append((f"art_{slug(display)[:60]}", display, norm_display,
                                   "Nigeria", "West Africa", "Gospel", None, None))
            existing_artist_names.add(norm_display)
            added_artists += 1

    try:
        con.execute("BEGIN")
        con.executemany(
            "INSERT INTO songs (id, title, normalized_title, artist, normalized_artist,"
            " album, release_year, country, region, language, genre, subgenre, song_type,"
            " songwriter, publisher, copyright_status, lyrics_status, source, source_url,"
            " aliases, popularity_tier, verified, verification_status, created_at,"
            " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows["songs"])
        con.executemany(
            "INSERT INTO lyric_search_index (id, song_id, title, artist, aliases,"
            " searchable_text) VALUES (?,?,?,?,?,?)", rows["indexes"])
        con.executemany(
            "INSERT INTO lyric_search_fts (song_id, title, artist, aliases,"
            " lyric_fragments) VALUES (?,?,?,?,?)", rows["fts"])
        if artist_inserts:
            con.executemany(
                "INSERT OR IGNORE INTO artists (artist_id, artist_name, normalized_name,"
                " country, region, genre, aliases, bio_snippet)"
                " VALUES (?,?,?,?,?,?,?,?)", artist_inserts)

        # enrich existing records (field fills + pass-1 credit corrections)
        enriched_counts = apply_enrichment(con, enrich, now_iso())

        # categories
        con.execute("UPDATE categories SET song_count = song_count + ?"
                    " WHERE id = 'cat_nigerian_gospel'", (len(rows["songs"]),))

        # build_manifest — one row per artist catalogue source
        manifest = []
        counts: dict[str, int] = {}
        for e in kept:
            counts[e["_file"]] = counts.get(e["_file"], 0) + 1
        totals: dict[str, int] = {}
        for e in entries:
            totals[e["_file"]] = totals.get(e["_file"], 0) + 1
        rejected_per_file: dict[str, int] = {}
        for r in rejected:
            fname = r.split("[", 1)[0].split(":", 1)[0].strip()
            rejected_per_file[fname] = rejected_per_file.get(fname, 0) + 1
        for filename, meta in CATALOGS.items():
            parsed = totals.get(filename, 0)
            accepted = counts.get(filename, 0)
            manifest.append((
                f"ng_{meta['base'].replace(' ', '_')}", meta["manifest_title"],
                meta["artist"], "2010-2026", 0,
                meta["site"] or common_site(filename, entries),
                "Metadata only — titles, credits and release data; copyrighted"
                " lyrics not reproduced.",
                now_iso(), parsed, accepted,
                max(0, parsed - accepted) + rejected_per_file.get(filename, 0)))
        con.executemany(
            "INSERT OR REPLACE INTO build_manifest (source_key, title, author,"
            " published, ebook_id, url, license, retrieved_at, songs_parsed,"
            " songs_accepted, songs_skipped) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            manifest)

        # metadata totals + version + checksum
        total_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        total_artists = con.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
        total_lyrics = con.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0]
        pd_count = con.execute(
            "SELECT COUNT(*) FROM songs WHERE copyright_status='PUBLIC_DOMAIN'"
        ).fetchone()[0]
        meta_only = con.execute(
            "SELECT COUNT(*) FROM songs WHERE copyright_status='METADATA_ONLY'"
        ).fetchone()[0]
        licensed = total_songs - pd_count - meta_only
        digest = hashlib.sha256()
        for row in con.execute(
                "SELECT id, title, artist FROM songs ORDER BY id").fetchall():
            digest.update("|".join(str(v) for v in row).encode("utf-8"))
        for row in con.execute(
                "SELECT song_id, section_order, line_order, text FROM lyrics"
                " ORDER BY song_id, section_order, line_order").fetchall():
            digest.update("|".join(str(v) for v in row).encode("utf-8"))
        content_hash = digest.hexdigest()

        provenance_policy = (
            "Every record carries its origin: songs.source/source_url name the"
            " source edition (Project Gutenberg eBook for public-domain hymns;"
            " official artist/label catalogue page for metadata-only records),"
            " lyrics.source repeats the ebook provenance per line, and the"
            " build_manifest table records license, retrieval date and yield per"
            " source. sha256_checksum is the SHA-256 of the canonical"
            " songs+lyrics dump (tools/build_gospel_db.py;"
            " tools/expand_ng_catalog.py)."
        )
        copyright_policy = (
            "The Kreadive Galaxy Strict Gospel Copyright Standard v3. Only texts"
            " published into the public domain (source editions dated 1719-1925,"
            " hosted by Project Gutenberg as public domain in the USA) are stored"
            " in full. Copyrighted modern worship songs — including the Nigerian"
            " catalogue expansion (data/ng_expansion/*.json) — remain"
            " METADATA_ONLY: titles, credits, albums and source URLs only, with"
            " no lyric text. No lyrics are generated, completed or paraphrased by"
            " any means. Sources: Project Gutenberg eBooks #13341, #46041,"
            " #16455, #20476, #59884, #59263 and the sixteen artist catalogues"
            " (see build_manifest)."
        )
        con.execute(
            "UPDATE database_metadata SET total_songs=?, total_artists=?,"
            " total_lyrics_records=?, total_licensed_records=?,"
            " total_public_domain_records=?, total_metadata_only_records=?,"
            " build_date=?, provenance_policy=?, copyright_policy=?,"
            " sha256_checksum=?, generated_by=?, database_version='3.2.0'"
            " WHERE database_name='lyric_sync_gospel.lsdb'",
            (total_songs, total_artists, total_lyrics, licensed, pd_count,
             meta_only, now_iso(), provenance_policy, copyright_policy,
             content_hash,
             "LyricSync catalogue builder (tools/build_gospel_db.py) + NG"
             " expansion (tools/expand_ng_catalog.py) — The Kreadive Galaxy"))
        con.commit()
    except Exception:
        con.rollback()
        raise
    con.execute("VACUUM")
    con.close()

    after = {
        "songs": total_songs, "artists": total_artists, "lyrics": total_lyrics,
    }
    print(f"songs {before['songs']} -> {after['songs']}"
          f"  (+{after['songs'] - before['songs']})")
    print(f"artists {before['artists']} -> {after['artists']}"
          f"  (+{added_artists})")
    print(f"lyric lines unchanged: {after['lyrics']}")
    print(f"existing records enriched: {sum(enriched_counts.values())}")

    # per-artist counts
    per_artist: dict[str, int] = {}
    for e in kept:
        name = CATALOGS[e["_file"]]["artist"]
        per_artist[name] = per_artist.get(name, 0) + 1
    print("-- per-artist inserted --")
    for name in sorted(per_artist):
        print(f"  {name}: +{per_artist[name]}")
    if enriched_counts:
        print("-- per-artist enriched --")
        for name in sorted(enriched_counts):
            print(f"  {name}: +{enriched_counts[name]} enriched")

    print("\n== validation ==")
    sys.path.insert(0, str(ROOT))
    from lyric_sync.database.database_validator import validate_file
    report = validate_file(PROD_DB, deep=True)
    print(report.to_text())
    if not report.ok:
        return 1

    print("== engine smoke ==")
    from search_engine import LyricSyncSearchEngine
    engine = LyricSyncSearchEngine(str(PROD_DB))
    checks = [
        "Dunsin Oyekan", "Lawrence Oyor", "Mercy Chinwo", "Nathaniel Bassey",
        "Minister Mike", "Greatman Takit",
        "Bidemi Olaoba", "Festizie", "Marizu", "Midnight Crew", "Mike Abdul",
        "Mr M & Revelation", "Neeja", "Sammie Okposo", "Samsong",
        "Testimony Jaga",
        "Favour", "New Wine", "Oke Mmiri", "You Are Good", "Jugular Jugular",
        "A Cry for Mercy", "amazing grace", "way maker",
    ]
    failures = []
    for q in checks:
        res = engine.search(q)
        hits = len(res.results) if hasattr(res, "results") else len(res)
        print(f"  {q!r}: {hits} hits")
        if hits == 0:
            failures.append(q)
    engine.close() if hasattr(engine, "close") else None
    if failures:
        print("SMOKE FAILURES:", failures)
        return 1

    lines = [
        "NG CATALOGUE EXPANSION — REPORT", f"generated {now_iso()}", "",
        f"source entries: {len(entries)}",
        f"rejected: {len(rejected)}",
        f"duplicates skipped: {len(skips)}",
        f"inserted: {len(kept)} (all METADATA_ONLY, 0 lyric lines added)",
        f"existing records enriched: {sum(enriched_counts.values())}",
        f"songs: {before['songs']} -> {after['songs']}",
        f"artists: {before['artists']} -> {after['artists']}",
        f"lyric lines: {after['lyrics']} (unchanged)",
        "", "-- per-artist inserted --",
    ] + [f"{k}: {v}" for k, v in sorted(per_artist.items())]
    if enriched_counts:
        lines += ["", "-- per-artist enriched --"] + [
            f"{k}: {v}" for k, v in sorted(enriched_counts.items())]
    (REPORT_DIR / "expansion_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\nCOMMIT OK — data/ng_expansion/expansion_report.txt written")
    return 0


def main(argv: list[str]) -> int:
    return run("--commit" in argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
