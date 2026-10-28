"""SQL statements used by Lyric Sync.

Every statement that carries data uses placeholders. Table and column names are
*never* derived from user input — they come from ``SchemaAdapter``, which only
accepts identifiers discovered through SQLite introspection.
"""

from __future__ import annotations

# ---------------------------------------------------------------- introspection

SQLITE_MASTER = """
    SELECT name, type, sql
    FROM sqlite_master
    WHERE type IN ('table', 'view')
    ORDER BY name
"""

SQLITE_FTS_TABLES = """
    SELECT name, sql
    FROM sqlite_master
    WHERE type = 'table' AND sql IS NOT NULL
      AND (lower(sql) LIKE '%using fts5%' OR lower(sql) LIKE '%using fts4%'
           OR lower(sql) LIKE '%using fts3%')
    ORDER BY name
"""

TABLE_COLUMNS = "PRAGMA table_info({table})"

TABLE_EXISTS = "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?"

INTEGRITY_CHECK = "PRAGMA integrity_check"
QUICK_CHECK = "PRAGMA quick_check"

ROW_COUNT = "SELECT COUNT(*) FROM {table}"

# ------------------------------------------------------------------- meta

META_SELECT = "SELECT {key_col}, {value_col} FROM {meta_table}"

# ------------------------------------------------------------------- songs

SONG_COLUMNS = (
    "id",
    "title",
    "artist",
    "artist_id",
    "album",
    "year",
    "country",
    "category",
    "songwriter",
    "aliases",
    "verification_status",
    "copyright_status",
    "lyrics_status",
    "source",
    "rights_notice",
)

SONG_BY_ID = """
    SELECT {select_list}
    FROM {songs}
    WHERE {id_col} = ?
"""

SONGS_BY_IDS = """
    SELECT {select_list}
    FROM {songs}
    WHERE {id_col} IN ({placeholders})
"""

SONG_ID_TITLE_LIKE = """
    SELECT {id_col}
    FROM {songs}
    WHERE {title_col} LIKE ? ESCAPE '\\'
"""

SONG_ID_ARTIST_LIKE = """
    SELECT {id_col}
    FROM {songs}
    WHERE {artist_col} LIKE ? ESCAPE '\\'
"""

SONG_IDS_ALL = "SELECT {id_col} FROM {songs}"

# ------------------------------------------------------------------- aliases

ALIAS_COLUMNS_SQL = """
    SELECT {song_id_col}, {alias_col}
    FROM {aliases}
    WHERE {alias_col} LIKE ? ESCAPE '\\'
"""

ALIASES_FOR_SONG = """
    SELECT {alias_col}
    FROM {aliases}
    WHERE {song_id_col} = ?
"""

# ------------------------------------------------------------------- lyrics

LYRIC_LINES_FOR_SONG = """
    SELECT {select_list}
    FROM {lines}
    WHERE {song_id_col} = ?
    ORDER BY {order_list}
"""

LYRIC_LIKE = """
    SELECT DISTINCT {song_id_col}
    FROM {lines}
    WHERE {text_col} LIKE ? ESCAPE '\\'
"""

LYRIC_LINE_BY_ID = """
    SELECT {select_list}
    FROM {lines}
    WHERE {id_col} = ?
"""

LYRIC_BLOB_FOR_SONG = """
    SELECT {text_col}
    FROM {lines}
    WHERE {song_id_col} = ?
    ORDER BY {order_list}
"""

SECTIONS_FOR_SONG = """
    SELECT {select_list}
    FROM {sections}
    WHERE {song_id_col} = ?
    ORDER BY {order_list}
"""

# ------------------------------------------------------------------- artists

ARTIST_COUNT = "SELECT COUNT(*) FROM {artists}"

# ------------------------------------------------------------------- FTS

FTS_MATCH = """
    SELECT rowid AS rowid, bm25({table}) AS rank
    FROM {table}
    WHERE {table} MATCH ?
    ORDER BY rank
    LIMIT ?
"""

FTS_TABLE_ROW_COUNT = "SELECT COUNT(*) FROM {table}"
