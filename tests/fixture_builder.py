"""Development fixture builder.

Creates a tiny, clearly-labelled ``.LSDB`` used only by automated tests and for
manual development before the real ``lyric_sync_gospel.lsdb`` arrives.

This is NOT a Gospel catalogue. Records are synthetic or public-domain
traditional hymns, and the file records its own provenance in the ``meta``
table.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

FIXTURE_LABEL = "Lyric Sync development fixture — NOT a real Gospel catalogue"
FIXTURE_VERSION = "0.1-dev"
FIXTURE_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    region TEXT
);
CREATE TABLE songs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    artist_id INTEGER REFERENCES artists(id),
    artist TEXT,
    album TEXT,
    year INTEGER,
    country TEXT,
    category TEXT,
    songwriter TEXT,
    aliases TEXT,
    verification_status TEXT,
    copyright_status TEXT,
    lyrics_status TEXT,
    source TEXT,
    rights_notice TEXT
);
CREATE TABLE song_aliases (
    song_id INTEGER NOT NULL,
    alias TEXT NOT NULL
);
CREATE TABLE lyric_sections (
    id INTEGER PRIMARY KEY,
    song_id INTEGER NOT NULL,
    section_type TEXT NOT NULL,
    section_index INTEGER NOT NULL DEFAULT 0,
    label TEXT
);
CREATE TABLE lyric_lines (
    id INTEGER PRIMARY KEY,
    song_id INTEGER NOT NULL,
    section_id INTEGER,
    section_index INTEGER,
    section_type TEXT,
    line_index INTEGER,
    text TEXT NOT NULL
);
CREATE INDEX idx_lines_song ON lyric_lines(song_id, section_index, line_index);
CREATE INDEX idx_lines_text ON lyric_lines(text);
CREATE INDEX idx_songs_title ON songs(title);
CREATE INDEX idx_songs_artist ON songs(artist);
CREATE INDEX idx_alias_song ON song_aliases(song_id, alias);
"""

ARTISTS = [
    (1, "The Kreadive Galaxy Test Ensemble", "Nigeria", "West Africa"),
    (2, "Fixture Voices", "Ghana", "West Africa"),
    (3, "Traditional Hymn Writers", "United Kingdom", None),
    (4, "Placeholder Worship Project", "United States", "North America"),
]

# (id, title, artist_id, album, year, country, category, songwriter, aliases,
#  verification, copyright, lyrics_status, source)
SONGS = [
    (1, "The Great I Am", 1, "Signals of Praise", 2021, "Nigeria", "Worship",
     "Fixture Writer", "Great I AM, The", "VERIFIED", "USER_IMPORTED", "AVAILABLE",
     "development fixture"),
    (2, "Anchor of Peace", 2, "Harbour Songs", 2019, "Ghana", "Gospel",
     "Fixture Writer", None, "VERIFIED", "LICENSED", "AVAILABLE",
     "development fixture"),
    (3, "Faithful Still", 4, None, 2020, "United States", "Worship",
     None, "Still Faithful", "VERIFIED", "METADATA_ONLY", "UNAVAILABLE",
     "development fixture"),
    (4, "Rivers of Mercy", 2, "Harbour Songs", 2018, "Ghana", "Praise",
     "Fixture Writer", None, "UNVERIFIED", "AUTHORIZED", "AVAILABLE",
     "development fixture"),
    (5, "Amazing Grace", 3, "Hymnal Collection", 1779, "United Kingdom", "Hymn",
     "John Newton", None, "VERIFIED", "PUBLIC_DOMAIN", "AVAILABLE",
     "traditional public domain"),
    (6, "Morning Light", 1, "Signals of Praise", 2022, "Nigeria", "Devotional",
     None, None, "UNVERIFIED", "LICENSED", "AVAILABLE",
     "development fixture"),
    (7, "Psalm of Thanks", 3, "Hymnal Collection", 1769, "United Kingdom", "Psalm",
     "Traditional", None, "VERIFIED", "PUBLIC_DOMAIN", "AVAILABLE",
     "traditional public domain"),
    (8, "Every Sunrise", 4, None, 2023, "United States", "Worship",
     "Fixture Writer", None, "VERIFIED", "METADATA_ONLY", "UNAVAILABLE",
     "development fixture"),
]

SECTIONS = [
    # (id, song_id, section_type, section_index, label)
    (1, 1, "VERSE", 1, None),
    (2, 1, "CHORUS", 1, None),
    (3, 2, "VERSE", 1, None),
    (4, 2, "CHORUS", 1, None),
    (5, 4, "VERSE", 1, None),
    (6, 4, "BRIDGE", 1, None),
    (7, 5, "VERSE", 1, None),
    (8, 6, "VERSE", 1, None),
    (9, 7, "VERSE", 1, None),
]

# (song_id, section_id, section_index, section_type, line_index, text)
LINES = [
    (1, 1, 1, "VERSE", 0, "You are the mighty God, the great I AM"),
    (1, 1, 1, "VERSE", 1, "Every knee will bow before your name"),
    (1, 1, 1, "VERSE", 2, "From the rising of the sun to its end"),
    (1, 2, 1, "CHORUS", 0, "Holy, holy is the Lord of all the earth"),
    (1, 2, 1, "CHORUS", 1, "Great I AM, shining over everything"),

    (2, 3, 1, "VERSE", 0, "When the storm is loud and long"),
    (2, 3, 1, "VERSE", 1, "You hold me fast and keep me strong"),
    (2, 4, 1, "CHORUS", 0, "Anchor of peace within the wind"),
    (2, 4, 1, "CHORUS", 1, "I will trust your name again"),

    (4, 5, 1, "VERSE", 0, "There is a river, wide and free"),
    (4, 5, 1, "VERSE", 1, "Mercy flows to you and me"),
    (4, 6, 1, "BRIDGE", 0, "Carry me over the water"),
    (4, 6, 1, "BRIDGE", 1, "Nothing can sink what you have raised"),

    (5, 7, 1, "VERSE", 0, "Amazing grace how sweet the sound"),
    (5, 7, 1, "VERSE", 1, "That saved a wretch like me"),
    (5, 7, 1, "VERSE", 2, "I once was lost but now am found"),

    (6, 8, 1, "VERSE", 0, "Morning light upon the hill"),
    (6, 8, 1, "VERSE", 1, "Your mercy meets me there"),

    (7, 9, 1, "VERSE", 0, "I will give thanks to the Lord"),
    (7, 9, 1, "VERSE", 1, "With all my heart I will sing"),
]

ALIASES = [
    (1, "Great I AM, The"),
    (3, "Still Faithful"),
    (6, "Sunrise Everyday"),
]

FTS_SONGS = {
    1: "You are the mighty God, the great I AM Every knee will bow before your name "
       "From the rising of the sun to its end Holy holy is the Lord of all the earth "
       "Great I AM shining over everything",
    2: "When the storm is loud and long You hold me fast and keep me strong "
       "Anchor of peace within the wind I will trust your name again",
    4: "There is a river wide and free Mercy flows to you and me Carry me over the water "
       "Nothing can sink what you have raised",
    5: "Amazing grace how sweet the sound That saved a wretch like me "
       "I once was lost but now am found",
    6: "Morning light upon the hill Your mercy meets me there",
    7: "I will give thanks to the Lord With all my heart I will sing",
}


def build_fixture(path: Path | str) -> Path:
    """Create (or replace) the development fixture database."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    connection = sqlite3.connect(str(target))
    try:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("database_version", FIXTURE_VERSION),
                ("schema_version", str(FIXTURE_SCHEMA_VERSION)),
                ("generator", FIXTURE_LABEL),
                ("generated_by", FIXTURE_LABEL),
                ("copyright_notice", FIXTURE_LABEL),
            ],
        )
        connection.executemany(
            "INSERT INTO artists (id, name, country, region) VALUES (?, ?, ?, ?)",
            ARTISTS,
        )
        connection.executemany(
            """
            INSERT INTO songs (id, title, artist_id, artist, album, year, country,
                               category, songwriter, aliases, verification_status,
                               copyright_status, lyrics_status, source, rights_notice)
            VALUES (?, ?, ?, (SELECT name FROM artists WHERE id = ?), ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?)
            """,
            [
                (
                    song_id, title, artist_id, artist_id, album, year, country, category,
                    songwriter, aliases, verification, copyright, lyrics_status, source,
                    "Development fixture — rights information is illustrative only.",
                )
                for (
                    song_id, title, artist_id, album, year, country, category, songwriter,
                    aliases, verification, copyright, lyrics_status, source,
                ) in SONGS
            ],
        )
        connection.executemany(
            "INSERT INTO song_aliases (song_id, alias) VALUES (?, ?)", ALIASES
        )
        connection.executemany(
            """
            INSERT INTO lyric_sections (id, song_id, section_type, section_index, label)
            VALUES (?, ?, ?, ?, ?)
            """,
            SECTIONS,
        )
        connection.executemany(
            """
            INSERT INTO lyric_lines (song_id, section_id, section_index, section_type,
                                     line_index, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            LINES,
        )
        connection.execute(
            "CREATE VIRTUAL TABLE songs_fts USING fts5("
            "title, artist, lyrics, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        for song_id, lyrics in FTS_SONGS.items():
            title = next(song[1] for song in SONGS if song[0] == song_id)
            artist_id = next(song[2] for song in SONGS if song[0] == song_id)
            artist_name = next(a[1] for a in ARTISTS if a[0] == artist_id)
            connection.execute(
                "INSERT INTO songs_fts (rowid, title, artist, lyrics) VALUES (?, ?, ?, ?)",
                (song_id, title, artist_name, lyrics),
            )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    return target


if __name__ == "__main__":  # pragma: no cover - manual helper
    import sys

    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dev_fixture.lsdb")
    built = build_fixture(destination)
    print(f"Built {built}")
