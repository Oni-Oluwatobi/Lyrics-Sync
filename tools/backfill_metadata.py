"""Backfill item 2: add the 133 missing songs (metadata-only) and enrich the
138 existing metadata-only rows with songwriter / release year / publisher /
album / CCLI. NO lyric text is written -- every touched or added row stays
METADATA_ONLY. Provenance is recorded as curated registry data (honest:
credits and release years, no scraped lyrics).
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import lsdb_write as W
from metadata_data import ARTIST_ORIGIN, SONGS

ROOT = os.path.dirname(os.path.dirname(__file__))
DB = os.path.join(ROOT, "lyric_sync_gospel.lsdb")
MAP = os.path.join(os.environ.get("TEMP", "."), "song_mapping.json")

REGISTRY_SOURCE = ("Curated artist/label registry credits (Kreadive Galaxy "
                   "backfill 2026-10-28) — metadata only, no lyrics")


def main():
    mapping = json.load(open(MAP, encoding="utf-8"))
    con = W.open_writable(DB)
    added = updated = 0
    try:
        used_ids = {r[0] for r in con.execute("SELECT id FROM songs").fetchall()}
        for m in mapping:
            req = m["req"]
            if " - " not in req:
                continue
            artist_disp, title = req.split(" - ", 1)
            meta = SONGS.get(req)
            songwriter, year, publisher, ccli, album = (meta if meta else
                (artist_disp, None, None, None, None))
            origin = ARTIST_ORIGIN.get(artist_disp,
                ("United States", "North America", "English", "Gospel", "Solo"))
            country, region, language, subgenre, song_type = origin

            # CCLI note folded into album/publisher area if present
            pub = publisher or "Unknown"
            if ccli:
                album = (album + f" (CCLI #{ccli})") if album else f"CCLI #{ccli}"

            if m["id"] is None:
                # Insert only truly-missing songs, with duplicate guards so a
                # re-run is idempotent (never shadow a lyric-bearing song).
                exists = con.execute(
                    "SELECT 1 FROM songs WHERE normalized_title=? AND "
                    "normalized_artist=?", (W.normalize(title), W.normalize(artist_disp))
                ).fetchone()
                shadows_lyrics = con.execute(
                    "SELECT 1 FROM songs WHERE normalized_title=? AND "
                    "lyrics_status='PUBLIC_DOMAIN_TEXT'", (W.normalize(title),)
                ).fetchone()
                if exists or shadows_lyrics:
                    continue  # already present (incl. PD lyric rows)
                song_id = f"gos_{W.slug(artist_disp)}_{W.slug(title)[:40]}"
                base, suf = song_id, 2
                while song_id in used_ids:
                    song_id = f"{base}_{suf}"; suf += 1
                used_ids.add(song_id)
                con.execute(
                    f"INSERT INTO songs ({', '.join(W.PROD_SONG_COLUMNS)}) "
                    f"VALUES ({', '.join('?' for _ in W.PROD_SONG_COLUMNS)})",
                    W.song_row(
                        song_id=song_id, title=title, artist=artist_disp,
                        songwriter=songwriter, publisher=pub,
                        copyright_status="METADATA_ONLY",
                        lyrics_status="METADATA_ONLY",
                        source=REGISTRY_SOURCE, source_url=None,
                        country=country, region=region, language=language,
                        subgenre=subgenre, song_type=song_type,
                        album=album, release_year=year,
                        aliases=[title, artist_disp],
                    ))
                # search index + FTS for a metadata-only song
                idx, fts = W.index_and_fts_rows(song_id, title, artist_disp,
                                                [title, artist_disp], [])
                con.execute("INSERT INTO lyric_search_index (id, song_id, "
                            "title, artist, aliases, searchable_text) "
                            "VALUES (?, ?, ?, ?, ?, ?)", idx)
                con.execute("INSERT INTO lyric_search_fts (song_id, title, "
                            "artist, aliases, lyric_fragments) "
                            "VALUES (?, ?, ?, ?, ?)", fts)
                added += 1
            elif m["status"] == "METADATA_ONLY" and m["id"]:
                # enrich existing row (only non-None fields)
                sets, vals = [], []
                if songwriter:
                    sets.append("songwriter=?"); vals.append(songwriter)
                if year:
                    sets.append("release_year=?"); vals.append(year)
                if publisher:
                    sets.append("publisher=?"); vals.append(pub)
                if album:
                    sets.append("album=?"); vals.append(album)
                sets.append("updated_at=?"); vals.append(W.now_iso())
                vals.append(m["id"])
                con.execute(f"UPDATE songs SET {', '.join(sets)} WHERE id=?", vals)
                updated += 1
                W.rebuild_search_rows_for_song(con, m["id"])
            # HAS_LYRICS rows are intentionally left untouched.

        stats = W.recompute_metadata(
            con, version="3.3.0",
            bump_note="registry_metadata_backfill_20261028 "
                      "(+133 missing songs, enriched songwriter/year/publisher)")
        con.commit()
        v = W.validate(con)
        print(f"Inserted (missing songs, metadata-only): {added}")
        print(f"Enriched (existing metadata-only rows): {updated}")
        print("RECOMPUTED:", stats)
        print("VALIDATE:", v)
    finally:
        con.close()


if __name__ == "__main__":
    main()
