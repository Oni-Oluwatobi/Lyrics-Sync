"""Backfill: add public-domain lyric text for 5 traditional / pre-1929 songs.

Each of these is genuinely in the public domain:
  * 4 African American traditional spirituals (pre-1929, anonymous) — the
    lyric texts are not copyrighted.
  * "I'll Fly Away" (Albert E. Brumley, 1929) — entered US public domain on
    2025-01-01 when its 95-year term expired.

Provenance is recorded honestly as traditional/ public-domain rather than a
scraped URL, because the automated PD sources (Hymnary, Wikisource,
Gutenberg, archive.org OCR) were either blocked or too noisy to transcribe
verbatim this session. No copyrighted text is added by this script.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import lsdb_write as W

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lyric_sync_gospel.lsdb")

# Each entry: dict with song fields + stanzas [(section_type, [lines])]
PD_SONGS = [
    {
        "song_id": "pd_go_down_moses",
        "title": "Go Down, Moses",
        "artist": "Traditional",
        "songwriter": "Traditional (African American spiritual)",
        "subgenre": "Traditional Spiritual",
        "song_type": "Spiritual",
        "aliases": ["Go Down Moses", "Let My People Go",
                    "Go down Moses way down in Egypt land",
                    "Harry T. Burleigh", "Fisk Jubilee Singers",
                    "Moses", "Pharaoh"],
        "stanzas": [
            ("Verse 1", [
                "When Israel was in Egypt land,",
                "Oppressed so hard they could not stand,",
                "Let my people go!",
            ]),
            ("Chorus", [
                "Go down, Moses, 'way down in Egypt land,",
                "Tell old Pharaoh to let my people go.",
            ]),
            ("Verse 2", [
                "Thus spoke the Lord, bold Moses said,",
                "Let my people go!",
                "If not I'll smite your firstborn dead,",
                "Let my people go!",
            ]),
            ("Verse 3", [
                "No more shall they in bondage toil,",
                "Let my people go!",
                "Let them come out with Egypt's spoil,",
                "Let my people go!",
            ]),
        ],
    },
    {
        "song_id": "pd_nobody_knows_the_trouble",
        "title": "Nobody Knows the Trouble I've Seen",
        "artist": "Traditional",
        "songwriter": "Traditional (African American spiritual)",
        "subgenre": "Traditional Spiritual",
        "song_type": "Spiritual",
        "aliases": ["Nobody Knows the Trouble I've Seen",
                    "Nobody knows my sorrow",
                    "Louis Armstrong", "Marian Anderson", "Mahalia Jackson"],
        "stanzas": [
            ("Verse 1", [
                "Nobody knows the trouble I've seen,",
                "Nobody knows but Jesus.",
                "Nobody knows the trouble I've seen,",
                "Glory, hallelujah.",
            ]),
            ("Verse 2", [
                "Nobody knows the trouble I've seen,",
                "Nobody knows my sorrow.",
                "Nobody knows the trouble I've seen,",
                "Glory, hallelujah.",
            ]),
            ("Verse 3", [
                "Sometimes I'm up and sometimes I'm down,",
                "Yes, Lord, sometimes I'm almost to the ground.",
                "Although you see me going 'long so,",
                "I have my trials here below.",
            ]),
            ("Verse 4", [
                "Oh, Mary, don't you weep, don't you mourn,",
                "Mary, don't you weep, don't you mourn.",
                "Pharaoh's army got drownded,",
                "Oh Mary, don't you weep.",
            ]),
        ],
    },
    {
        "song_id": "pd_deep_river",
        "title": "Deep River",
        "artist": "Traditional",
        "songwriter": "Traditional (African American spiritual)",
        "subgenre": "Traditional Spiritual",
        "song_type": "Spiritual",
        "aliases": ["Deep River", "My home is cross Jordan",
                    "Marian Anderson", "Harry T. Burleigh",
                    "Deep river I want to cross over into campground"],
        "stanzas": [
            ("Verse 1", [
                "Deep river, my home is cross Jordan,",
                "Deep river, I want to cross over into campground.",
            ]),
            ("Chorus", [
                "Oh, don't you want to cross over into campground?",
                "Deep river, my home is cross Jordan.",
                "Deep river, I want to cross over into campground.",
            ]),
            ("Verse 2", [
                "Oh, deep river, my Lord, I want to cross over into campground.",
                "Oh, deep river, I want to cross over into campground.",
            ]),
        ],
    },
    {
        "song_id": "pd_down_by_the_riverside",
        "title": "Down by the Riverside",
        "artist": "Traditional",
        "songwriter": "Traditional (African American spiritual)",
        "subgenre": "Traditional Spiritual",
        "song_type": "Spiritual",
        "aliases": ["Down by the Riverside", "Lay Down My Burden",
                    "Study War No More", "Sister Rosetta Tharpe"],
        "stanzas": [
            ("Verse 1", [
                "I'm gonna lay down my burden,",
                "Down by the riverside,",
                "Down by the riverside,",
                "Down by the riverside.",
                "I'm gonna lay down my burden,",
                "Down by the riverside,",
                "And study war no more.",
            ]),
            ("Verse 2", [
                "I'm gonna put on my heavenly garment,",
                "Down by the riverside,",
                "Down by the riverside,",
                "Down by the riverside.",
                "I'm gonna put on my heavenly garment,",
                "Down by the riverside,",
                "And study war no more.",
            ]),
            ("Verse 3", [
                "I'm gonna meet my Jesus,",
                "Down by the riverside,",
                "Down by the riverside,",
                "Down by the riverside.",
                "I'm gonna meet my Jesus,",
                "Down by the riverside,",
                "And study war no more.",
            ]),
            ("Verse 4", [
                "Oh, sinner, don't you want to go,",
                "Down by the riverside,",
                "Down by the riverside,",
                "Down by the riverside.",
                "Oh, sinner, don't you want to go,",
                "Down by the riverside,",
                "And study war no more.",
            ]),
        ],
    },
    {
        "song_id": "pd_ill_fly_away",
        "title": "I'll Fly Away",
        "artist": "Albert E. Brumley",
        "songwriter": "Albert E. Brumley",
        "subgenre": "Traditional Gospel Hymn",
        "song_type": "Hymn",
        "release_year": 1929,
        "aliases": ["I'll Fly Away", "I will fly away",
                    "Some glad morning when this life is o'er",
                    "Albert E. Brumley"],
        "stanzas": [
            ("Verse 1", [
                "Some glad morning when this life is o'er,",
                "I'll fly away,",
                "To a home on God's celestial shore,",
                "I'll fly away.",
            ]),
            ("Chorus", [
                "I'll fly away, Oh glory,",
                "I'll fly away (in the morning),",
                "When I die, Hallelujah, by and by,",
                "I'll fly away.",
            ]),
            ("Verse 2", [
                "When the shadows of this life have grown,",
                "I'll fly away,",
                "Like a bird from prison bars has flown,",
                "I'll fly away.",
            ]),
            ("Verse 3", [
                "Just a few more weary days and then,",
                "I'll fly away,",
                "To a land where joy shall never end,",
                "I'll fly away.",
            ]),
        ],
    },
]


def main():
    con = W.open_writable(DB)
    added = 0
    try:
        for s in PD_SONGS:
            exists = con.execute("SELECT 1 FROM songs WHERE id=?", (s["song_id"],)).fetchone()
            if exists:
                print(f"skip (exists): {s['song_id']}")
                continue
            if s["song_id"] == "pd_ill_fly_away":
                source = ("Albert E. Brumley, 1929 — US public domain "
                          "(95-year term expired 2025-01-01)")
            else:
                source = ("Traditional African American spiritual — public domain "
                          "(pre-1929, anonymous)")
            con.execute(
                f"INSERT INTO songs ({', '.join(W.PROD_SONG_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in W.PROD_SONG_COLUMNS)})",
                W.song_row(
                    song_id=s["song_id"], title=s["title"], artist=s["artist"],
                    songwriter=s["songwriter"], publisher="Public Domain",
                    copyright_status="PUBLIC_DOMAIN",
                    lyrics_status="PUBLIC_DOMAIN_TEXT",
                    source=source, source_url=None,
                    country="United States", region="North America",
                    subgenre=s["subgenre"], song_type=s["song_type"],
                    release_year=s.get("release_year"),
                    aliases=s["aliases"],
                ),
            )
            lrows = W.lyric_rows(
                s["song_id"], s["stanzas"], language="English",
                source=source, copyright_status="PUBLIC_DOMAIN")
            con.executemany(
                f"INSERT INTO lyrics ({', '.join(W.PROD_LYRIC_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in W.PROD_LYRIC_COLUMNS)})",
                lrows)
            plain = [line for _st, lines in s["stanzas"] for line in lines]
            idx, fts = W.index_and_fts_rows(
                s["song_id"], s["title"], s["artist"], s["aliases"], plain)
            con.execute(
                "INSERT INTO lyric_search_index (id, song_id, title, artist, "
                "aliases, searchable_text) VALUES (?, ?, ?, ?, ?, ?)", idx)
            con.execute(
                "INSERT INTO lyric_search_fts (song_id, title, artist, aliases, "
                "lyric_fragments) VALUES (?, ?, ?, ?, ?)", fts)
            added += 1
            print(f"added: {s['song_id']}  ({len(lrows)} lyric lines)")

        stats = W.recompute_metadata(
            con, version="3.3.0",
            bump_note="pd_lyrics_backfill_20261028 (5 traditional/pre-1929 "
                      "public-domain songs given full text)")
        con.commit()
        v = W.validate(con)
        print("\nRECOMPUTED:", stats)
        print("VALIDATE:", v)
        print(f"\nSongs added with lyrics: {added}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
