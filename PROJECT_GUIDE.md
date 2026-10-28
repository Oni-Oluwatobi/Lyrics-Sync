# Lyric Sync — Complete Project Guide

**A single reference for everything in this repository.**

Product: **Lyric Sync** · by **The Kreadive Galaxy** · Version **1.0.0**
Database: `lyric_sync_gospel.lsdb` · v**3.2.0** · 4,998 songs · 57,536 lyric lines
Content digest: `ffc3f3e8abc44cc1c5afb84bc7737735ee8b09aa1322cb14061a1a54744f0cc4`
(post `user_import_nmwy_20261020` + master-registry metadata backfill
`registry_*_20261020` + public-domain hymn text backfill
`pd_hymn_backfill_20261021`; the pre-2026-10-20 digest was `55e59d50…`)

This document explains what the project is, how it is built, what every file
does, which rules may never be broken, and how the pieces relate to each
other. It is written to be readable by a newcomer *and* precise enough to
work from.

---

# PART ONE — WHAT THIS PROJECT IS

---

## 1. The one-line answer

Lyric Sync is an **offline Windows desktop application that finds a gospel
song from a fragment of its lyrics that you half-remember.**

You remember a line — *"the mighty God, the great I AM"* — you type it in, and
Lyric Sync searches a local SQLite songbook file on your own computer and
shows you ranked matches with the matching lines highlighted.

**No internet is used at any point.** No web requests, no cloud, no accounts,
no telemetry.

## 2. Why it exists

Gospel musicians, choristers and listeners routinely remember three or four
words of a song and nothing else — not the title, not the artist. Existing
solutions require you to already know what you are looking for, or they send
your query to a server.

Lyric Sync inverts the flow: the question is *"what song contains these
words?"* and the answer is computed entirely on your machine, from a
database file you can see, back up and replace.

## 3. The two halves of the repository

The repository contains two deliberately separate programs.

| | **The Application** | **The Database Builder** |
|---|---|---|
| Directory | `lyric_sync/` | `tools/lyrics-scraper/` |
| Purpose | Searches the songbook for the end user | Builds the songbook from websites and public-domain books |
| UI toolkit | PySide6 (Qt) | Tkinter (standard library) |
| Dependencies | `PySide6>=6.6.0` | **none** — Python standard library only |
| Ships to users? | Yes (installer) | **Never** |
| Network access | **Never** | Yes, but only from the developer's machine |
| Tests | `tests/` (189 passing) | `tools/lyrics-scraper/tests/` (88 passing) |

The two halves **never import each other**, never share a database table at
runtime, and are never packaged together. The builder is a manufacturing
tool; the application is the shop window. The only thing they have in common
is the `.lsdb` file format — and even then the application only ever *reads*
it.

Everything below follows that split.

---

# PART TWO — ARCHITECTURE

---

## 4. The big picture

```
   WEBSITES / PUBLIC-DOMAIN BOOKS
             │
             │  (builder only, developer's machine)
             ▼
   ┌──────────────────────────────────────────────┐
   │  tools/lyrics-scraper/   — THE BUILDER       │
   │                                              │
   │  fetch → detect → adapter → parse            │
   │        → normalize → validate → dedupe       │
   │        → staging.sqlite → review → export    │
   └──────────────────────────────────────────────┘
             │
             │  writes ONCE, with guardrails
             ▼
   ┌──────────────────────────────────────────────┐
   │  lyric_sync_gospel.lsdb   — THE SONGBOOK     │
   │  (read-only from here on, forever)           │
   └──────────────────────────────────────────────┘
             │
             │  (application, user's machine)
             ▼
   ┌──────────────────────────────────────────────┐
   │  lyric_sync/   — THE APPLICATION             │
   │                                              │
   │  UI ─► LyricSearchService ─► LSDBManager     │
   │                 │                  │         │
   │                 ▼                  ▼         │
   │        search_engine.py    SQLite (query_only│
   │        (frozen, by path)       = ON)         │
   └──────────────────────────────────────────────┘
             │
             ▼
        THE USER
```

## 5. The hard boundary

These are not style preferences. They are structural, and breaking any of
them breaks the product's stated promise.

1. **The application never touches the network.** There is no HTTP client
   anywhere under `lyric_sync/`. The only code in the repository that opens
   a socket is `tools/lyrics-scraper/lyrics_scraper/fetch.py`.
2. **The application never writes to the songbook.** Every connection is
   opened with `PRAGMA query_only = ON`.
3. **The builder is never imported by the application**, and
   `lyricsync.spec` never collects `tools/lyrics-scraper` into the build.
4. **The builder never imports `lyric_sync`.** It reuses no application code
   and no application table.
5. **The installer ships no scraper.** `requirements.txt` contains exactly
   one line — `PySide6>=6.6.0`.
6. **No scraper page, button or menu exists inside the application.** The
   builder has its own separate Tkinter window.

## 6. End-to-end data flow

1. A developer runs a fetch command against a URL.
2. `fetch.py` checks `robots.txt`, sleeps for any `Crawl-delay`, and downloads
   into a content-addressed cache (`output/raw/`).
3. `detect.py` decides what kind of page it is (sitemap, listing, article,
   book).
4. `adapters/` selects the right site rules from the URL host.
5. The site parser turns HTML or plain text into `NormalizedSong` objects.
6. `validate.py` scores each song `clean` / `flagged`.
7. `dedupe.py` decides insert vs. merge vs. insert-flagged.
8. Everything lands in `output/staging/staging.sqlite`.
9. A human runs `list`, `review` and `coverage` until they are satisfied.
10. `export.py` copies the production schema, empties the copy, and writes
    only approved rows — lyrics only when explicitly allowed.
11. The resulting `.lsdb` is dropped next to the application, which finds it
    and never modifies it.

---

# PART THREE — THE PRODUCTION DATABASE

---

## 7. What a `.LSDB` file is

A `.lsdb` file is an ordinary **SQLite 3 database** with a project-specific
name. Nothing about it is proprietary — `sqlite3` reads it directly.

The production file lives at the project root:

```
lyric_sync_gospel.lsdb      36,847,616 bytes (35.1 MiB)
```

There is also a `data/` directory holding an alternate location for the same
file, plus versioned backups:

```
data/backups/lyric_sync_gospel_v2.4.0_e7c5225a.lsdb
data/backups/lyric_sync_gospel_v3.0.0_407265ee.lsdb
data/backups/lyric_sync_gospel_v3.1.0_7faac476.lsdb
```

Those backups exist because the catalog was expanded in place across three
versions. The root file remains canonical.

## 8. The thirteen tables

Verified directly from the production file.

### 8.1 `songs` — 4,998 rows

The catalogue. One row per song, metadata-only unless lyrics were imported.

| Column | Type | Meaning |
|---|---|---|
| `id` | int | Primary key. This is the `song_id` used everywhere else. |
| `title` | text | Display title, as a human would type it. |
| `normalized_title` | text | Case/punctuation-stripped title used for matching. |
| `artist` | text | Primary artist display name (or `Traditional`). |
| `normalized_artist` | text | Normalised artist for matching. |
| `album` | text | Album, when known. |
| `release_year` | int | Year of release. |
| `country` | text | e.g. `Nigeria`. Never merged with `language`. |
| `region` | text | Coarser geography than `country`. |
| `language` | text | e.g. `Yoruba`, `English`. |
| `genre` | text | Primary genre. |
| `subgenre` | text | Secondary genre. |
| `song_type` | text | e.g. hymn, chorus, worship. |
| `songwriter` | text | Writer credit when distinct from the performing artist. |
| `publisher` | text | Publisher, when known. |
| `copyright_status` | text | **The export gate.** `PUBLIC_DOMAIN`, `METADATA_ONLY`, `AUTHORIZED`, `LICENSED`, `USER_IMPORTED`, `UNKNOWN`. |
| `lyrics_status` | text | `PUBLIC_DOMAIN_TEXT` when lyric text is legitimately held; empty for metadata-only rows. |
| `source` | text | Human-readable provenance, e.g. `Project Gutenberg — https://…`. |
| `source_url` | text | The canonical URL this row came from. |
| `aliases` | text | Alternate titles, JSON. Searched alongside title. |
| `popularity_tier` | text | Relative popularity bucket. |
| `verified` | int | `0` for every unreviewed row. |
| `verification_status` | text | `UNVERIFIED` until a human checks it. |
| `created_at` / `updated_at` | text | ISO-8601 timestamps. |

**Current copyright split:** 3,004 `PUBLIC_DOMAIN` · 1,993 `METADATA_ONLY` ·
1 `USER_IMPORTED` (the user-supplied Dunsin Oyekan record, see §41).

### 8.2 `lyrics` — 57,536 rows

One row per lyric line. This is the table the search engine actually reads.

| Column | Meaning |
|---|---|
| `id` | Primary key. |
| `song_id` | Foreign key into `songs.id`. |
| `section_order` | 1-based position of the section (verse/chorus). |
| `section_type` | `verse`, `chorus`, `bridge`, `intro`, `outro`, … |
| `line_order` | 1-based position of the line inside its section. |
| `text` | The line exactly as stored, for display. |
| `normalized_text` | Folded form used for matching (case, punctuation, diacritics stripped). |
| `language` | Language of this line when mixed. |
| `source` | Where this particular text came from. |
| `copyright_status` | Per-line copyright declaration. |
| `verified` | `0` until checked. |

Sections are *derived* from `section_order`/`section_type` at read time —
there is no separate `sections` table.

### 8.3 `artists` — 1,230 rows

`artist_id`, `artist_name`, `normalized_name`, `country`, `region`, `genre`,
`aliases`, `bio_snippet`. Normalised name is indexed for lookup.

### 8.4 `lyric_search_index` — 4,998 rows

A materialised, pre-joined row per song: `id`, `song_id`, `title`, `artist`,
`aliases`, `searchable_text`. This is the in-memory cache the engine loads so
it never has to issue per-query joins.

### 8.5 `lyric_search_fts` — 4,998 rows

A SQLite **FTS5** virtual table over `song_id`, `title`, `artist`, `aliases`,
`lyric_fragments`. Its five shadow tables (`…_config`, `…_content`,
`…_data`, `…_docsize`, `…_idx`) are FTS internals. When FTS is unavailable
the engine falls back to a LIKE scan; the Database Info page reports which
mode is active.

### 8.6 `build_manifest` — 29 rows

One row per catalogue import. Columns: `source_key`, `title`, `author`,
`published`, `ebook_id`, `url`, `license`, `retrieved_at`, `songs_parsed`,
`songs_accepted`, `songs_skipped`.

Real example — this is the provenance chain for the public-domain hymn books:

```
watts      "Hymns and Spiritual Songs"  Isaac Watts  1719
           https://www.gutenberg.org/ebooks/13341
           Public domain (United States) — Project Gutenberg eBook #13341
           parsed 360 · accepted 360 · skipped 0

chb        "The Christian Hymn Book"     A. Campbell and others  1870
           https://www.gutenberg.org/ebooks/46041
           parsed 1323 · accepted 1323 · skipped 0

otterbein  "The Otterbein Hymnal"        Edmund S. Lorenz (compiler)  1892
           https://www.gutenberg.org/ebooks/16455
           parsed 547 · accepted 546 · skipped 1
```

### 8.7 `database_metadata` — 1 row

The self-description of the file: `database_name`, `database_version`,
`schema_version`, `total_songs`, `total_artists`, `total_lyrics_records`,
`total_licensed_records`, `total_public_domain_records`,
`total_metadata_only_records`, `build_date`, `provenance_policy`,
`copyright_policy`, `sha256_checksum`, `generated_by`.

The `sha256_checksum` column stores a **content digest** (a digest over the
row content, not over the raw bytes) so it stays stable across vacuuming.
The current digest — `ffc3f3e8…` — is recorded in this guide and asserted by
the prod probe; the test suite separately proves the file is not modified
*by the tests themselves*.

### 8.8 `categories` — 9 rows

`id`, `name`, `description`, `song_count`. Top-level buckets for browsing.

### 8.9 The 12 indexes

```
idx_songs_title                idx_songs_normalized_title
idx_songs_artist               idx_songs_normalized_artist
idx_songs_country              idx_songs_region
idx_songs_copyright_status     idx_songs_lyrics_status
idx_lyrics_song_id             idx_lyrics_normalized_text
idx_artists_country            idx_artists_normalized_name
```

Every column the application filters or joins on is indexed. There are no
views and no triggers.

## 9. Provenance and copyright policy

Two fields govern everything:

* **`copyright_status`** — what we are legally allowed to *do* with the row.
* **`lyrics_status`** — whether we actually hold lyric text for it.

A row with `copyright_status = METADATA_ONLY` may appear in search results
(title and artist) but its lyrics are empty. This is how modern, still-copyright
songs are represented honestly: they are catalogued, they are findable, and
their text is not redistributed.

The provenance policy recorded in `database_metadata` requires that every
imported row trace back to a `build_manifest` entry with a URL, a licence
string and a retrieval timestamp.

---

# PART FOUR — THE SEARCH ENGINE

---

## 10. Why `search_engine.py` is a separate, frozen file

`search_engine.py` (474 lines, project root) is the **retrieval engine**. It
ships alongside the application and is loaded *by path* through
`lyric_sync/search/engine_loader.py` — in development from the project root,
in a frozen build from `_internal/search_engine.py`.

It is deliberately kept out of the `lyric_sync/` package because:

* it can be replaced or re-downloaded without touching application code,
* the application never edits it — the contract is that ranking behaviour is
  the engine's own,
* the packaged self-check can verify the engine is present and importable
  before the window opens.

The application may *tie-break* equal scores (exact title match first) but
otherwise preserves the engine's ordering untouched.

## 11. Module-level helpers

| Function | What it does |
|---|---|
| `normalize_text(text)` | Folds case, strips punctuation and whitespace, removes diacritics. `GRAET` → `great`. |
| `levenshtein_distance(a, b)` | Classic edit distance, used for typo tolerance. |
| `levenshtein_within(a, b, n)` | Early-exit variant — stops as soon as the distance exceeds `n`. |
| `match_token_fuzzy(token, vocabulary, threshold)` | True if a token is within the fuzzy ratio of some vocabulary word. `"amzing"` matches `"amazing"`. |

## 12. `LyricSyncSearchEngine`

```
__init__(database_path)
_verify_database()      structural check; raises if the file is not an .lsdb
get_database_info()     counts, FTS availability, schema checks
_ensure_caches()        lazy build of the in-memory index
_load_songs()           bulk read from lyric_search_index
search(query, …)        returns ranked candidates
close()
```

The engine loads `lyric_search_index` once, holds it in memory, and serves
every subsequent query from RAM. That is why searching 4,998 songs feels
instant.

## 13. Scoring

The application's ranker (`lyric_sync/search/ranker.py`) combines eight
signals. The weights sum to 1.04 because they are applied as an additive
blend, not a probability distribution:

| Weight | Constant | Value |
|---|---|---|
| Phrase match | `WEIGHT_PHRASE` | **0.34** |
| Coverage of query terms | `WEIGHT_COVERAGE` | **0.22** |
| Longest matching line | `WEIGHT_LINE` | **0.16** |
| Word proximity | `WEIGHT_PROXIMITY` | **0.10** |
| Title match | `WEIGHT_TITLE` | **0.12** |
| Artist match | `WEIGHT_ARTIST` | **0.04** |
| Alias match | `WEIGHT_ALIAS` | **0.02** |
| Retrieval score from the engine | `WEIGHT_RETRIEVAL` | **0.04** |

Two multiplicative penalties:

* `UNVERIFIED_PENALTY = 0.95` — rows not yet human-verified are nudged down.
* `GENERIC_PENALTY = 0.85` — very common titles are nudged down.

## 14. Thresholds and match labels

| Label | Constant | Minimum score |
|---|---|---|
| **Strong** | `STRONG_THRESHOLD` | **0.72** |
| **Good** | `GOOD_THRESHOLD` | **0.50** |
| **Possible** | `POSSIBLE_THRESHOLD` | **0.32** |

Gates applied before a result is shown at all:

* `MIN_SCORE = 0.30`
* `MIN_COVERAGE = 0.34` — at least a third of the query's content words must hit.

**Why labels, not percentages.** The product promise is that it never shows a
fabricated confidence figure. `Strong / Good / Possible` are honest bucket
names tied to published thresholds; `High / Medium / Low` engine confidence is
mapped onto them.

## 15. Sensitivity modes

The user picks a sensitivity in Settings; it shifts thresholds rather than
changing the algorithm.

| Mode | Score shift | Fuzzy ratio |
|---|---|---|
| `strict` | `+0.07` (harder) | `0.86` |
| `balanced` | `0.00` | `0.80` |
| `relaxed` | `-0.06` (easier) | `0.74` |

(Internal names: `SENSITIVITY_SHIFTS`, `FUZZY_RATIO`. The user-facing labels
are strict / balanced / tolerant.)

## 16. Query normalisation

`lyric_sync/search/query_normalizer.py` is what makes messy remembered input
work:

* **Diacritics stripped** — `Şinaçh` finds `Sinach`.
* **Eight apostrophe forms folded** — `' ’ ʻ ʼ ´ ʽ ῑ ′`.
* **Whitespace collapsed**, punctuation removed.
* **Stopwords** removed for content matching but kept for display.
* **Contractions expanded into variants** — `you're` ↔ `you are`,
  `he's` ↔ `he is`.
* **Unicode word tokenisation** (`[^\W_]+` with `re.UNICODE`), so Yoruba and
  other Latin-script languages with diacritics tokenize correctly.
* **`like_pattern` / `phrase_pattern`** build the SQL/FTS patterns from the
  normalised query, with all values parameterised — no string-built SQL.

## 17. Highlighting

`lyric_sync/search/highlighter.py` picks the excerpt that best demonstrates
the match — preferring the line with the densest hit cluster, falling back to
a window around the first hit — and returns inline highlight spans rather
than wrapping the whole line.

## 18. Threading

All database work happens **off the UI thread**:

* `lyric_sync/ui/workers.py` provides `Task`, `run_task()` and
  `run_in_pool()`, built on `QRunnable` / the global Qt thread pool.
* Results return through `TaskSignals` so the UI thread does the painting.
* A single lock serialises database access — SQLite connections are not
  shared across threads without synchronisation.
* Debounced live search cancels/supersedes stale queries.

---

# PART FIVE — THE APPLICATION, LAYER BY LAYER

---

## 19. Entry point

```
main.py            python main.py  →  Lyric Sync window
                   python main.py --self-check  →  headless verification
lyric_sync/main.py the actual bootstrap logic
```

`main.py` handles `--self-check`, locates the database and engine, and hands
off to `lyric_sync/app/application.py`, which creates the `QApplication`,
applies the theme and opens `MainWindow`.

## 20. `lyric_sync/app/`

| File | Size | Purpose |
|---|---|---|
| `config.py` | 5.1 KB | All constants and path discovery |
| `theme.py` | 18.4 KB | `Palette`, `resolve_palette`, `build_stylesheet`, `apply_theme` |
| `application.py` | 1.2 KB | `QApplication` bootstrap |
| `self_check.py` | 2.6 KB | Packaged-build verification |
| `dev_log.py` | 1.1 KB | `developer.log` for detailed failures |

### `config.py` constants

```
APP_NAME        = "Lyric Sync"
APP_ID          = "LyricSync"
DEVELOPER       = "The Kreadive Galaxy"
VERSION         = "1.0.0"
DATABASE_FILENAME = "lyric_sync_gospel.lsdb"
DATABASE_DIRNAME  = "data"
ENV_DATABASE    = "LYRIC_SYNC_DATABASE"
ENV_USER_DATA   = "LYRIC_SYNC_USER_DATA"
PREFERENCES_FILENAME = "preferences.json"
FAVORITES_FILENAME   = "favorites.json"
DEFAULT_RECENT_LIMIT = 12
```

### Database discovery order

`candidate_database_paths()` builds the search list; first existing file wins:

1. `LYRIC_SYNC_DATABASE` environment variable
2. The override chosen in **Settings → Locate database**
3. `.\lyric_sync_gospel.lsdb` and `.\data\lyric_sync_gospel.lsdb`
4. `<project>\lyric_sync_gospel.lsdb` and `<project>\data\…`
5. `<package>\data\lyric_sync_gospel.lsdb`
6. `<exe folder>\data\…` and `<exe folder>\lyric_sync_gospel.lsdb`
7. Packaged resources (`_internal\data\lyric_sync_gospel.lsdb`)

`search_engine.py` is resolved the same way with `LYRIC_SYNC_ENGINE`.

### Theming

`resolve_palette(mode)` handles Dark / Light / **System** (via
`system_is_dark`). The palette is **The Kreadive Galaxy brand colours:
orange, yellow, white, black — no blue anywhere.** Application title text:
**Lyric Sync · by The Kreadive Galaxy**.

## 21. `lyric_sync/models/`

| File | Purpose |
|---|---|
| `song.py` (3.9 KB) | `Song` — supports **integer and text song ids** |
| `lyric.py` (2.7 KB) | `SongLyrics`, `LyricSection`, lines |
| `search_result.py` (1.4 KB) | `SearchResult` — score, label, matched fields, highlights |

Text ids matter: the builder produces string ids like
`pg_the_conquering_pilgrim`, and the application must not assume integers.

## 22. `lyric_sync/database/`

| File | Size | Purpose |
|---|---|---|
| `lsdb_manager.py` | 34.8 KB | `LSDBManager` — all SQLite access |
| `database_validator.py` | 11.5 KB | Non-destructive validation reports |
| `schema_adapter.py` | 12.3 KB | Tolerant column/schema mapping |
| `queries.py` | 3.3 KB | Raw SQL kept in exactly one place |

### `LSDBManager` capabilities

Opening/closing, `meta()`, `info()`, `validate(deep=True)`, record fetch
(`get_song`, `get_songs`, `get_records`), lyric fetch (`get_lyrics`,
`get_lyric_lines`), four `song_ids_matching_*` pattern searches,
`song_ids_matching_all`, FTS (`fts_match`), and streaming access
(`lyric_rows_batch`, `count_lyric_lines_scannable`).

### Read-only guarantees

* `PRAGMA query_only = ON` is set immediately after open — the connection
  *physically cannot* write, regardless of what any code path attempts.
* Every SQL statement is parameterised; `queries.py` is the only place raw
  SQL text lives.
* Validation **inspects and reports**; it never repairs, never rewrites,
  never migrates.
* `_valid_song_id()` guards against hostile ids reaching a query.
* `schema_adapter.py` tolerates column drift so an older `.lsdb` still loads
  instead of crashing.

## 23. `lyric_sync/search/`

| File | Size | Purpose |
|---|---|---|
| `lyric_search_service.py` | 24.1 KB | The UI-facing service |
| `search_engine.py` | 12.4 KB | In-package retrieval (fixture schema) |
| `ranker.py` | 12.1 KB | Scoring, thresholds, match labels |
| `query_normalizer.py` | 6.4 KB | Normalisation and folding |
| `highlighter.py` | 4.1 KB | Excerpt selection + inline highlighting |
| `engine_loader.py` | 3.8 KB | Loads `search_engine.py` by path |

Note the duplication that is *intentional*: `lyric_sync/search/search_engine.py`
is an in-package retrieval used against the **development fixture** schema,
while the root `search_engine.py` is the production engine loaded by path.
The loader picks the right one for the environment.

### `LyricSearchService`

The single doorway the UI uses. Methods: `available`, `open`, `close`,
`close_async`, `search`, `search_lyrics`, `get_song`, `get_songs`,
`get_lyrics`, `database_info`.

Error types are explicit rather than bare exceptions:

```
ServiceError
├── DatabaseMissingError      no .lsdb found
├── EngineUnavailableError    search_engine.py missing/broken
└── DatabaseUnreadableError   file present but corrupt/locked
```

Each maps to a distinct, actionable message in the UI.

A module-level `_exact_title_first` provides the tie-break: when two results
score equally, an exact title match wins. This is the *only* place the app
overrides engine ordering.

## 24. `lyric_sync/storage/`

| File | Purpose |
|---|---|
| `preferences.py` (3.6 KB) | Theme, sensitivity, history settings, db override |
| `favorites.py` (4.9 KB) | Starred songs, **text-id safe** |

Both write **atomic JSON** (write to a temp file, then `os.replace`) to:

```
Windows: %APPDATA%\LyricSync\preferences.json
         %APPDATA%\LyricSync\favorites.json
Override: LYRIC_SYNC_USER_DATA=<dir>
```

Favourites are keyed by text-safe id so a song id like
`pg_a_blessing_implored` round-trips correctly.

## 25. `lyric_sync/ui/`

A compact header + sidebar shell around seven pages:

| File | Size | Purpose |
|---|---|---|
| `main_window.py` | ~35 KB | Header, sidebar, navigation, wiring, search orchestration, auth session |
| `search_screen.py` | ~14 KB | Search field + button, compact ranked results, lyrics preview panel |
| `song_page.py` | 11.2 KB | Full lyrics with section headings, favourite toggle |
| `library_page.py` | ~6 KB | Favorites (embedded `FavoritesPage`) + saved searches |
| `favorites_page.py` | 6.2 KB | Filterable, sortable favorites grid (embedded in My Library) |
| `settings_page.py` | ~12 KB | Appearance, Search, Database, Application sections |
| `about_page.py` | ~7 KB | Version, real database statistics, tagline, privacy, credits |
| `account_page.py` | ~8 KB | Optional Firebase sign-in / sign-up / reset / sign-out forms |
| `db_info_page.py` | 7.9 KB | Filename, size, counts, FTS availability, schema checks |
| `workers.py` | 3.2 KB | `QRunnable` background tasks |

`home_page.py` and `results_page.py` were removed when the approved design
made Search the single entry screen (results and preview now live together
in `search_screen.py`).

### Components

```
ui/components/search_box.py   the input (focus border, clear button)
ui/components/result_row.py   one result row: click selects, double-click opens
ui/components/widgets.py      shared buttons, labels, containers, ChipFlow
```

### What `MainWindow` actually does

It owns the header (`_build_header`: app name + tagline, developer credit),
the sidebar (`_build_sidebar`: Search / My Library / Settings / About nav,
account row, database status dot + real counts, version), navigation
(`show_page`, `_sync_nav`, `go_home`, `_focus_search`), keyboard shortcuts
(`_build_shortcuts`, `keyPressEvent`, Escape/Back handling, `/` focus),
search orchestration (`_on_submit`, `_run_debounced_search`,
`_execute_search`, `_on_search_finished`, `_on_search_error`), song opening
(`open_song`), favourites (`_refresh_favorites`, `_on_favorite_toggled`,
`_on_remove_favorite`), saved searches (`_refresh_recents`,
`_on_recent_removed`, `_on_clear_recents`), settings propagation
(`_on_theme_changed`, `_on_sensitivity_changed`, `_on_live_search_toggled`,
`_on_history_toggled`), the optional account session (`_wire_auth`,
`_on_auth_user`), and database lifecycle (`reload_database`,
`_locate_database`, `_validate_database`, `_load_database_info`,
`_schedule_background_validation`, `_set_database_missing`,
`_set_database_failure`).

Validation runs in the **background** and never blocks the window.

## 26. Screens at a glance

| Screen | What you see |
|---|---|
| **Search** | Search field + Search button, compact ranked results with **Strong / Good / Possible** labels, and a lyrics preview panel (matched lines highlighted) that follows the selection; the preview auto-collapses on narrow windows |
| **Song** | Full lyrics with section headings (Verse, Chorus…), favourite toggle |
| **My Library** | Favorites (filter, sort, remove) and saved/recent searches — all local |
| **Settings** | Appearance (theme), Search (history, live search, sensitivity), Database (status, info, reload, locate, validate), Application (version, About) |
| **About** | Version, real database statistics, tagline, privacy notes, credits |
| **Database Info** | Filename, size, song and lyric-line counts, FTS availability, schema checks |
| **Account** | Optional Firebase sign-in, account creation, password reset, sign-out |

## 26a. Optional account sign-in (Firebase Authentication)

Account sign-in is **optional** and never blocks anything else: search,
favorites, settings and About work identically signed out or offline.

### Firebase Console setup (required once per project)

1. Console → **Authentication → Get started → Sign-in method → Email/Password → Enable**.
2. **Authentication → Settings → User actions**: leave "Email/Password" enabled.
3. Project settings → **Your apps → Web app** — copy the config object into
   `firebase_config.json` at the project root (it ships with the packaged app
   via `lyricsync.spec`). Public values only: `apiKey`, `authDomain`,
   `projectId`, `storageBucket`, `messagingSenderId`, `appId`,
   `measurementId`. No service-account keys, ever.
4. Optional: **Password reset email** uses the template Firebase sends by
   default; no custom template is required.
5. `measurementId` may be present in the config; the application **never**
   initializes Google Analytics or any telemetry.

### Code map (`lyric_sync/auth/`)

| File | Purpose |
|---|---|
| `firebase_config.py` | Finds/loads `firebase_config.json` (env override → project root → bundle → exe dir → user data). Missing file ⇒ signed out, no error at launch |
| `firebase_client.py` | `FirebaseClient` — urllib-only REST client for `accounts:signInWithPassword`, `accounts:signUp`, `accounts:sendOobCode` (PASSWORD_RESET), `securetoken.googleapis.com/v1/token` refresh, `accounts:getAccountInfo`. Errors surface as `AuthError(code, friendly_message)` |
| `secure_store.py` | `SecureStore` — atomic DPAPI-protected session file (`%APPDATA%\LyricSync\account_session.bin`). Tokens + email only; **never the password** |
| `session.py` | `AuthSession(QObject)` — signals `user_changed`, `busy_changed`, `error`, `notice`; every network call runs through `lyric_sync.ui.workers.run_task` (never the UI thread) |

### Offline / privacy rules enforced in code

* Launch only reads the local session file; a token refresh happens only when
  the cached token has expired, in the background.
* A network failure during refresh **keeps** the session quietly; only a
  rejected token signs the user out.
* Search never waits on auth: no query, result, or lyric is ever sent
  anywhere. The `.LSDB` file is never uploaded.
* `tests/test_auth.py` (33 tests) covers the client, error mapping, DPAPI
  store and session transitions with **faked transports — no test touches
  the network**.

## 27. Missing-database behaviour

The application must never crash because a file is absent. When no `.lsdb`
is found it still launches and shows **"Gospel database not installed"**
plus the exact places to put the file. Each failure mode
(missing / unreadable / engine missing) has its own message.

---

# PART SIX — THE DATABASE BUILDER

---

## 28. Why the builder exists and why it is isolated

The production catalogue's history proves the need:

* **3,140 songs** came from Project Gutenberg public-domain hymn books.
* **1,345** came from Apple Music and similar as metadata-only rows.
* The rest came from 16 researched JSON catalogues.

Modern gospel lyrics sites cannot legally contribute text, so the only way
to grow the *lyric* corpus is public-domain material. The builder is
engineered around that fact: it can produce `PUBLIC_DOMAIN` rows that are
exportable with text, and it deliberately refuses to launder modern sites'
lyrics into the database.

**Isolation, restated for the builder:**

* `requirements.txt` stays `PySide6>=6.6.0` — the builder adds nothing.
* `lyricsync.spec` never collects `tools/lyrics-scraper`.
* The builder never imports `lyric_sync`.
* The production `.lsdb` is never opened for writing — `export` checks
  `--out == prod` and refuses **before** anything is deleted.

## 29. The pipeline, stage by stage

```
URL ─► fetch ─► detect ─► adapter ─► parse ─► normalize
                                                      │
        ┌─────────────────────────────────────────────┘
        ▼
   validate ─► dedupe ─► staging.sqlite ─► human review ─► export ─► .lsdb
```

### 29.1 `fetch.py` — polite, resumable HTTP

* **robots.txt** honoured per-origin; rules parsed into an allow/disallow
  list. `--ignore-robots` overrides.
* **`Crawl-delay`** read from robots and applied as the throttle.
* **`Retry-After`** honoured on 429/503, in both seconds and HTTP-date
  formats, capped at `MAX_BACKOFF = 120`.
* **Retries**: `attempts = max(retries + 1, 4)`, so transient failures get
  four real tries.
* **Status classification** —
  `RETRYABLE_STATUS` are retried; `TERMINAL_STATUS = {400, 401, 403, 404,
  410, 451}` are not (a 404 will not become a 200).
* **Content-addressed cache** in `output/raw/` keyed by a hash of the URL,
  so `--cache-only` replays the entire crawl offline.
* A browser-like User-Agent — some sites reject the default Python one.

### 29.2 `detect.py` — what kind of page is this?

Classifies the body as sitemap / listing / article / book, so the right
parser runs. Bad or unknown URLs are reported clearly rather than silently
producing zero songs.

### 29.3 `adapters/` — one module per site

| Adapter | Key | Site | Copyright default |
|---|---|---|---|
| `OpenGospelLyricsAdapter` | `opengospellyrics` | opengospellyrics.com | `UNKNOWN` |
| `AfricanGospelLyricsAdapter` | `africangospellyrics` | africangospellyrics.com | `UNKNOWN` |
| `GutenbergHymnBookAdapter` | `gutenberg` | gutenberg.org | **`PUBLIC_DOMAIN`** |
| `ZionLyricsAdapter` | `zionlyrics` | zionlyrics.com | `UNKNOWN` |

`adapter_for(url, source)` picks by host. Passing an explicit `--source`
that does not own the URL host is an **error** — site B's HTML is never
parsed with site A's rules.

`base.SourceAdapter` defines the contract:

* `parse(page) -> ParseResult`
* `default_copyright_status` — stamped onto every song it produces
* `allow_query_links` — whether listing links carrying `?` params are followed
* `allows_link(url)` — filters `BLOCKED_LINK_TOKENS` (e.g. `.xml`,
  `.pdf`, `mailto:`) so dead ends are never fetched

### 29.4 Site parsers

| File | Site |
|---|---|
| `parser.py` | OpenGospelLyrics — boundary rules exclude comments, subscribe forms, related/trending blocks, sidebars, footers and WordPress.com controls |
| `african.py` | African Gospel Lyrics |
| `gutenberg.py` | The printed hymn books (see §30) |
| `zionlyrics.py` | Zion Lyrics JSON API + HTML fallback |
| `htmldoc.py` | Shared HTML utilities (Stanford CoreNLP-style document walking, stdlib only) |

### 29.5 What parsers extract

* **Byline variants**: `Title Lyrics by Artist ft. X`, `Title – Artist`,
  WordPress `post-title` / `post-date`.
* **Taxonomy split** into `themes / countries / languages / artists /
  other_tags` — never flattened into one blob.
* **Language declaration** with `language_confidence` = `explicit` |
  `inferred` | `unknown`. Languages are *never guessed*. Countries (Nigeria)
  stay separate from languages (Yoruba).
* **Repetition markers**:
  `x4` → `repeat=4`;
  `x?` → `repeat=1` + `repeat_unknown`;
  `(Repeat)` → `marker="repeat"`;
  `(Refrain)` → `marker="section"` + `target="Refrain"`.
  Markers are **recorded, never expanded** — `line_raw` keeps the exact
  source wording.

### 29.6 `normalize.py`

`normalize()` for matching keys, `content_hash()` for byte-level identity,
`lyrics_hash()` for lyric identity, `slug()` for ids.

### 29.7 `models.py`

`NormalizedSong` (title, artists, author, category, source_url, article_url,
page_id, `copyright_status`, sections, language, country, `extra{}`),
`Warning`, `RawPage`, `ParseResult`.

### 29.8 `validate.py` — the finding catalogue

`validate_song(song)` returns a list of `Warning` objects and a status.

| Code | Default severity | Meaning |
|---|---|---|
| `missing_title` | error | Song has no title |
| `suspect_title` | warning | Title implausibly short |
| `boilerplate_title` | warning | Title looks like page furniture |
| `html_in_title` | warning | Title contains markup |
| `missing_lyrics` | error | No lyric lines extracted |
| `short_lyrics` | warning | Fewer than the minimum lines (4) |
| `excessive_lyrics` | warning | Implausibly many lines |
| `boilerplate_lines` | warning | Lines that are site furniture |
| `html_in_lyrics` | warning | Lines contain markup |
| `repeated_lines` | warning | One line dominates the song |
| `low_variety` | warning | Too little vocabulary variety |
| `editorial_note` | warning | Editorial prose leaked in |
| `editorial_label` | warning | Editorial labels leaked in |
| `empty_sections` | warning | Sections with no lines |
| `too_many_sections` | warning | Implausible section count |
| `malformed_sections` | error | Sections exist but contain no lines |
| `missing_source` | error | No source URL |
| `suspect_year` | info | Year field has no digits |

Severities are `error` / `warning` / `info`. Status derivation:

```
any error   → flagged
any warning → flagged
otherwise   → clean
```

A warning is only `clean` when there are **no** findings at all — which is
what lets the engine safely auto-approve public-domain material.

### 29.9 `dedupe.py` — the five rules

Documented precedence, strongest first:

| # | Signal | Action |
|---|---|---|
| 1 | Identical **source URL** | `merge_source` — attach as another source |
| 2 | Identical **content hash** | merge |
| 3 | Identical **title + artist + lyrics hash** | merge (cross-source) |
| 4 | Identical **lyrics**, different title | insert **flagged** (`duplicate_lyrics_title_mismatch`) |
| 5 | Same **title + artist**, different lyrics | insert **flagged** (`duplicate_review`) |

Also `title_artist_conflict` — same title, different artist — is noted but
never merges.

Two hard rules:

* **Songs are never dropped.**
* **Songs are never auto-merged on title alone.**

`MIN_MERGE_LINES = 3` — a song needs at least three lyric lines before it can
be merged on lyrics alone, so a 2-line refrain can't swallow a different song.

**Rule 1 and multi-song pages.** A Gutenberg book is one URL holding
hundreds of songs. If every hymn carried the bare book URL, rule 1 would
collapse 547 hymns into one record. That actually happened during
development. The fix is the convention that a multi-song page addresses each
song as `url#fragment` (`#hymn-12`, or `#<slug>` on OpenGospelLyrics), so
siblings never look like duplicates of each other.

`DedupIndex` keeps five lookup maps — `by_source_url`, `by_content_hash`,
`by_title_artist_lyrics`, `by_lyrics_hash`, `by_title_artist` — built from
staging and updated as each insert lands.

### 29.10 `staging.py` — the workbench

`output/staging/staging.sqlite`, ten tables:

| Table | Purpose |
|---|---|
| `scrape_runs` | One row per CLI invocation, with totals |
| `pages` | Every fetched page (hash-cached HTML lives in `output/raw`) |
| `songs` | Metadata, multi-source fields, review state |
| `song_sections` | Section/line rows including `line_raw`, repeats, markers |
| `artists` / `song_artists` | Artists with `primary` / `featured` roles |
| `song_sources` | One row per source URL — a merge keeps *both* |
| `tags` / `song_tags` | Source tags and taxonomy buckets |
| `validation_warnings` | Every validation and dedupe finding |

`MIGRATIONS` apply schema changes in place on open, so an old staging file
stays usable. The source-prefix map is `ogl → ogl`, `agl → agl`,
`gutenberg.org → pg`, `zionlyrics.com → zl` — these become the `pg_` /
`zl_` id prefixes.

Per-song fields written by `insert_song()`: `review_status`,
`warning_count`, `copyright_status`, `include_lyrics`.

### 29.11 `engine.py` — the orchestrator

`ingest(url, run_id, limit, depth, seen=)` walks the page graph, parses,
validates, dedupes, stages and counts.

Stats keys:
`pages`, `failed`, `songs`, `insert`, `flagged`, `merge`, `warnings`,
`errors`, `ready`, `skipped`, `sources`.

`ready` = songs that are approved **and** carry `include_lyrics = 1` **and**
have a public-domain/authorized copyright — i.e. exactly what an export with
`--include-lyrics` will emit.

`stage()` applies the **auto-approve rule**:

> Mark `review_status = 'approved'` and `include_lyrics = 1` **only** when
> `copyright_status == "PUBLIC_DOMAIN"` **and** validation status is
> `clean`. Everything else awaits a human.

### 29.12 `cli.py` — the commands

```
single    <url>                      one page, no link following
article   <url>                      force article detection
category  <url> --limit 25           listing page + its posts
crawl     <sitemap.xml> --depth 2    walk the graph
validate                              run validation over staging
dedupe                                show duplicate candidates
stats                                 staging totals
coverage                              per-source breakdown  ← new
review    <song_id>                  act on one song
review    --all [--source S]         act on every staged song ← new
list      [--flagged-only]           browse staged songs
export    --out <path>               write a .lsdb
ui                                    Tkinter desktop interface
```

Global flags: `--output-dir`, `--source`, `--delay`, `--timeout`,
`--cache-only`, `--ignore-robots`.
Fetch flags: `--limit`, `--depth`, **`--resume`** (skip pages and songs
already staged — use after an interrupted crawl).
Export flags: `--out`, `--version`, `--include-lyrics`, `--include-flagged`,
`--overwrite`.
Review flags: `--all`, `--source`, `--approve`, `--reject`, `--flag`,
`--no-lyrics`, `--copyright-status`.

`coverage` prints:

```
  source                  songs  appr  cln  flg   rdy    pd  warn   lines
  -----------------------------------------------------------------------
  Project Gutenberg         546   520    0   26   520   546    26   10571
  TOTAL                     546                   520               10571
```

### 29.13 `ui.py` — the builder's desktop interface

An **838-line Tkinter window**, standard library only, entirely separate
from the application's Qt UI. It runs the *same CLI* in a child process, so
every window action is reproducible from a terminal.

* **Settings** — output folder, source, delay/timeout, cache-only, ignore-robots
* **Run bar** — URL plus Single / Article / Category / Crawl, Validate,
  Dedupe, **Stop**
* **Log** tab — streamed CLI output, colour for commands/warnings/errors
* **Staged songs** tab — live table with source/review/search filters;
  selecting a row shows metadata, findings and the exact source lyric lines,
  with Approve / Reject / Flag / include-lyrics / copyright actions
* **Export** tab — path, version, include-lyrics / include-flagged / overwrite,
  same safety rules as the CLI

### 29.14 `export.py` — the guardrail

Export **copies** the production database as a schema template (read-only),
empties the copy, and writes the new rows.

Safety order:

1. Refuse `--out == prod_path` **before anything is deleted**.
2. Metadata-only by default.
3. Lyrics are written only when **all three** hold:
   * `--include-lyrics` was passed,
   * `songs.include_lyrics = 1` in staging,
   * `copyright_status ∈ {PUBLIC_DOMAIN, AUTHORIZED}`.
4. Flagged songs additionally require `--include-flagged`.

Exported songs are always `verified = 0`, `verification_status = 'UNVERIFIED'`.

Output includes a `content_digest`, a `checksum`, per-source
`build_manifest` rows, and index/FTS rebuild counts.

### 29.15 The two launchers

```
lyrics-scraper.cmd        sets PYTHONPATH, runs the package
lyrics_scraper.py         shim so `python -m lyrics_scraper` works from root
```

Both delegate to `tools/lyrics-scraper/` and never touch the application.

## 30. Project Gutenberg — the public-domain engine

This is the only source that contributes real, exportable lyric text.

### The parser (`gutenberg.py`)

Gutenberg ships two formats per book: a plain-text transcription with
`*** START OF … ***` / `*** END OF … ***` markers, and an HTML edition.
The parser handles **four shapes**:

| Profile | Header shape | Notes |
|---|---|---|
| `chb` | number + spaces + metre, right-aligned to column **70** | The Christian Hymn Book |
| `bh` | `{N}.` + metre + author, right-aligned to column **72** | A Book of Hymns |
| `otb` | `{N}` + 5 spaces + tune, with an italic `_Title._` line below | The Otterbein Hymnal |
| `html` | `<div id="cN" class="hymn">` with `p.meter`, `p.ttl`, `div.verse`, `span.vn`, `div.author` | The Christian Hymn Book HTML edition |

Block splitting prefers blank-run boundaries, falls back when the source is
irregular, and stops at back matter (`CONTENTS.`, `INDEX OF SUBJECTS`,
`INDEX OF FIRST LINES`).

Handling details that mattered:

* **Authors** come from the `INDEX OF FIRST LINES` (text) or `div.author`
  blocks (HTML). When a book has neither, the artist falls back to
  `Traditional` — never invented.
* **`CHORUS.`** is treated as a section heading *before* the generic
  section-heading rule, so refrains are labelled correctly.
* **Stanza numbers** (`  1 `, `1. `) are stripped from the lyric text but
  preserved as `section_order`.
* **Music lines** (pipe-only `| | |` figures) are dropped.
* **Title-vs-tune disambiguation** — for `otb`, the italic line is the title
  and the header token is the tune name.
* **Author cutoff** — the credit line only counts if it is indented, short,
  ends in a period, and *looks like a name* (`CREDIT_NAME` / `CREDIT_YEAR` /
  `CREDIT_NOT_LYRIC`), so a chanted line or a stray punctuation mark is not
  mistaken for an author.

### Verified parse counts

| Book | Source | Hymns found |
|---|---|---|
| The Christian Hymn Book (ebook 46041) | text | **1324 / 1324** |
| The Christian Hymn Book | HTML | **1324** |
| A Book of Hymns (ebook 33180) | text | **600 / 600** |
| The Otterbein Hymnal (ebook 16455) | text | **547 / 548** |

Otterbein's 547-of-548 is a source typo: headers 103 and 112 are missing,
113 is duplicated, 588 is printed where 538 belongs, and 539 follows 588.
The parser finds every header that actually exists. This is reported as
99.8% coverage rather than hidden.

### The adapter

`GutenbergHymnBookAdapter.default_copyright_status = "PUBLIC_DOMAIN"`.

### Verified end-to-end run

```
fetched pg16455.txt — 468,001 chars, HTTP 200
  [1] book  songs=547  gutenberg
stats: insert=546, merge=1, flagged=26, ready=520, skipped=0

groups:
  approved  include_lyrics=1  PUBLIC_DOMAIN   n=520   lines=9,984
  flagged   include_lyrics=0  PUBLIC_DOMAIN   n=26    lines=587

warning codes: duplicate_review 20 · too_many_sections 3 ·
               repeated_lines 2 · short_lyrics 1

coverage:  546 songs · 520 ready · 546 public-domain · 10,571 lines
export:    520 songs · 9,984 lyrics · 7,659,520 bytes · exit 0
```

Every exported row: `copyright_status = PUBLIC_DOMAIN`,
`lyrics_status = PUBLIC_DOMAIN_TEXT`, `artist = Traditional`.

The 26 flagged songs are held back for a human — which is the system working
as designed, not a failure.

## 31. Zion Lyrics

`zionlyrics.com` publishes a sitemap (~5,000 URLs), permissive robots rules
(`Allow: /api/v1/`) and a JSON API:

```
GET /api/v1/songs?page=N      → data[] + meta.lastPage
GET /api/v1/songs/{slug}      → one song with a `lyrics` field
```

The adapter uses the API when it can and falls back to HTML parsing. It
honours a 60 req/min budget and requires a browser User-Agent.

**Its terms limit reuse to personal/educative use**, so its rows are staged
`METADATA_ONLY` and are never exported with lyric text. The parser
`parse_lyrics_text()` splits the label-prefixed format
(`[Chorus]`, `[Verse 1]`) into proper sections.

Sources assessed and rejected: gospelrella (526 songs, thin), 
christiansonglyricz (404s), allgospellyrics (DNS failure), tunesgram (DNS
failure), hymnserve (PDF-only).

## 32. The builder's tests

88 passing tests across 8 files:

| File | Tests | Covers |
|---|---:|---|
| `test_gutenberg.py` | 24 | All three print layouts, HTML flavour, real-book parametrisation, hymn URL fragments |
| `test_zionlyrics.py` | 13 | API index/detail, HTML fallback, label parsing |
| `test_adapters.py` | 15 | Registry, source resolution, `allows_link` |
| `test_hardening.py` | 11 | Retry-After, crawl-delay, `coverage`, `review --all`, resume |
| `test_pipeline.py` | 8 | Stage → merge/flag, artist roles, marker round-trip, export safety |
| `test_cli.py` | 5 | Argument parsing and error messages |
| `test_export_lyrics.py` | 5 | **Regression: lyric rows actually written; siblings not merged** |
| `test_ui.py` | 7 | Tkinter window, CLI child process, streamed output |

**Everything is offline.** Page fixtures live in `tests/fixtures/`. No test
performs a network request. The real-book test skips itself when the
downloaded books are absent.

---

# PART SEVEN — PACKAGING & DISTRIBUTION

---

## 33. `lyricsync.spec` (PyInstaller)

Build:

```powershell
python -m PyInstaller --clean --noconfirm lyricsync.spec
```

Output: **`dist/LyricSync/LyricSync.exe`** — a folder build with **no
console window**.

### What ships

* `lyric_sync/` — all submodules collected explicitly
* `PySide6.QtCore`, `QtGui`, `QtWidgets` — only these three
* `search_engine.py` → bundle root (the loader looks beside the resources)
* `data/lyric_sync_gospel.lsdb` → `data/` (from `data/` or the project root)
* `tests/fixtures/lyric_sync_dev_fixture.lsdb` → `data/` when present, so the
  packaged app can be exercised without a production database

### What is excluded

A 31-entry `QT_EXCLUDES` list strips `QtWebEngine*`, `QtQuick*`, `QtQml`,
`Qt3D*`, `QtCharts`, `QtDataVisualization`, `QtMultimedia*`, `QtPdf*`,
`QtNetwork`, `QtSql`, `QtTest`, `QtDesigner`, `QtHelp`, `QtWebSockets` and
the rest. This keeps the build small and — importantly — **removes every Qt
module that could perform network I/O**, which reinforces invariant #1.

`console=False` means windowed builds have no stdout, hence `--self-check`
writes to a file instead.

## 34. `LyricSync.iss` (Inno Setup 6)

```powershell
ISCC.exe LyricSync.iss
# → dist\LyricSync-Setup-1.0.0.exe
```

Key properties:

* `PrivilegesRequired=lowest` — **per-user install, no UAC prompt**. Safe
  because the application is read-only at install time and keeps all
  writable state in `%APPDATA%\LyricSync`.
* `ArchitecturesAllowed=x64compatible`
* Installs to `%LOCALAPPDATA%\Programs\LyricSync`
* Source directory is `dist\LyricSync` — the PyInstaller output
* Publisher: The Kreadive Galaxy · URL: `https://the-kreadive-galaxy.web.app/`

## 35. Verification of a build

```powershell
dist\LyricSync\LyricSync.exe --self-check
type $env:APPDATA\LyricSync\self_check.txt
```

Confirms the built app can resolve the database, import the bundled engine,
and run one real search.

```powershell
python tools\smoke_ui.py --database lyric_sync_gospel.lsdb   # with database
python tools\smoke_ui.py                                      # without
```

Headless UI check for both the with-database and no-database paths.

---

# PART EIGHT — TESTING

---

## 36. The application suite: 189 passing

| File | Tests | Focus |
|---|---:|---|
| `test_database.py` | 25 | `.LSDB` open/inspect/validate, read-only guarantees, parameterised SQL, missing-database handling |
| `test_production_lsdb.py` | 58 | **Real-database integration**: title/artist/lyric-fragment/typo searches through the actual engine, section order, text-id favourites, SHA-256 proof |
| `test_auth.py` | 33 | Firebase client REST contract (faked transports), friendly error mapping, DPAPI session store, `AuthSession` transitions — **no network** |
| `test_search.py` | 23 | Search behaviour end to end |
| `test_query_normalizer.py` | 13 | Normalisation edge cases, contractions, diacritics |
| `test_storage.py` | 12 | Preferences/favourites round-trips, atomic writes |
| `test_highlighter.py` | 8 | Excerpt selection and spans |
| `test_config.py` | 7 | Path discovery, environment overrides |
| `test_service_errors.py` | 6 | Each `ServiceError` subtype |
| `test_workers.py` | 4 | Background task callback delivery |
| *(10 files total)* | **189** | All pass together: `189 passed` |

Run:

```powershell
python -m pytest tests -q
python -m pyflakes lyric_sync tools tests
```

## 37. The builder suite: 88 passing

```powershell
python -m pytest tools\lyrics-scraper\tests -q
```

## 38. The immutability proof

The most important test in the repository. It hashes the production database
before and after a run of in-test operations that would, incautious code,
modify it — and asserts the file digest is unchanged. (The suite does not
hard-code a digest; it proves *it* never writes.)

Current recorded state (after the 2026-10-20 user import + master-registry
metadata backfill and the 2026-10-21 public-domain hymn text backfill,
see §41):

```
content digest  ffc3f3e8abc44cc1c5afb84bc7737735ee8b09aa1322cb14061a1a54744f0cc4
file sha256     e68699f38f8936019f173be674ccdad0a70bc398d6acd0cdd62a32a4593959ef
songs           4998
lyrics          57536
bytes           36,847,616
```

Verified after the user import: `validate_file(deep=True)` **all pass**,
suite green, production file otherwise untouched. Re-verified after the
2026-10-21 PD-hymn backfill: deep validation 0 errors / 0 warnings, suite
189 passed, prod probe **PROD_DB_AS_EXPECTED**.

## 39. The offline rule

No test in either suite performs a network request. Builder fixtures are
HTML files checked into `tests/fixtures/`. The real-book Gutenberg test
skips itself when its source files are not present rather than downloading
them. The authentication tests in `tests/test_auth.py` inject fake
transports; the only production network path — optional Firebase sign-in —
is never exercised live.

---

# PART NINE — HISTORY & PROVENANCE

---

## 40. The catalogue expansion (v3.0.0 → v3.2.0)

Recorded in `FINAL_REPORT_3.2.0.md`.

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Songs | 3,044 | **4,813** | **+1,769** |
| Artists | 433 | **1,146** | **+713** |
| Lyric lines | 57,135 | **57,135** | **0** |
| File size | 33,972,224 B | **36,433,920 B** | +2,461,696 |
| `database_version` | 3.0.0 | **3.2.0** | — |
| Copyright split | — | **1,827 METADATA_ONLY / 2,986 PUBLIC_DOMAIN** | — |

### Method

1. **Phase A** — environment/lyric-source audit. Found no local lyric
   datasets and no lyric API → all modern songs must be metadata-only.
2. **Phase B** — catalog research via parallel research agents.
3. **Phase C** — importer tooling: `tools/expand_ng_catalog.py` extended to
   16 catalogs with artist-credit handling, URL dedup and enrichment.
4. **Phases D–E** — two commit passes (6 core artists, then 10 more).
5. **Phase F** — quality: dedup scan, credit-casing fixes, re-validation.
6. **Phase G** — tests, one package rebuild, self-check, smoke, bench.
7. **Phase H** — cleanup of temp scripts and the report.

### What was honestly not done

**10 of 60** additional artists received full catalog research (Bidemi
Olaoba, Festizie, Marizu, Midnight Crew, Mike Abdul, Mr M & Revelation,
Neeja, Sammie Okposo, Samsong, Testimony Jaga — 1,813 entries across 16 JSON
files). The research agents for the other 50 were interrupted by "finish up"
instructions; **no partial or fabricated data was written for them.** They
appear in the report's coverage appendix with only opportunistic guest-credit
additions.

That honesty is deliberate: an invented catalogue entry is worse than an
absent one.

### The ranking bug

A latent defect in the search engine buried newly-inserted songs — they
existed in the database but scored too low to surface. It was found during
the expansion and fixed with one documented change to the ranking, the only
engine change permitted by the "keep the architecture" constraint.

## 41. Known state of the catalogue

* **3,004 songs** have legitimately public-domain lyric text — including the
  18 traditional hymns given full text by the public-domain wishlist backfill
  `pd_hymn_backfill_20261021` (see below).
* **1,993 songs** are metadata-only — findable by title and artist, with no
  lyrics, because their text is still in copyright (1,826 from the NG
  expansion + **185 net added** by the master-registry metadata backfill
  `registry_*_20261020`, which covered the user-supplied 275-song registry
  and dropped 4 hymn title-variant duplicates of PD originals, less the 18
  PD hymns whose text was restored on 2026-10-21).
* **1 song** carries full lyrics under `copyright_status = USER_IMPORTED`:
  *No Me Without You* (Dunsin Oyekan,
  `ng_dunsin_oyekan_no_me_without_you`) — 8 lines supplied directly by the
  product owner on 2026-10-20 and imported out-of-band
  (`build_manifest` row `user_import_nmwy_20261020`); recorded in
  `database_metadata.copyright_policy` as the single USER_IMPORTED
  exception.
* The 2026-10-21 **public-domain hymn text backfill**
  (`build_manifest` row `pd_hymn_backfill_20261021`) added full lyrics for
  **18 wishlist hymns / 393 lines** from Hymnary.org representative texts,
  each confirmed "Copyright: Public Domain" on the source page — e.g. *The
  Old Rugged Cross*, *Crown Him with Many Crowns*, *Battle Hymn of the
  Republic*, *Swing Low, Sweet Chariot*. Songs flipped
  `METADATA_ONLY → PUBLIC_DOMAIN`; lyric rows, FTS fragments and the search
  index were updated in the same transaction, `database_metadata` content
  digest recomputed, and the file re-vacuumed (backup:
  `lyric_sync_gospel.backup_pre_pd_hymns.lsdb`). *Victory in Jesus* (1939)
  and *We Shall Overcome* were deliberately excluded (not yet / disputed
  public domain); *Nearer, My God, to Thee* was already present as
  *Nearer to Thee* with 35 lines.
* The public-domain share is dominated by the Gutenberg hymn books
  (Watts 360, Christian Hymn Book 1,323, Otterbein 546, plus others).
* Known data-quality flag (left untouched, not this change's scope): *How
  Great Thou Art* carries text labelled `PUBLIC_DOMAIN`, but the English
  words are Eric Hine's 1949 translation — a rights review is owed.

This asymmetry is the central design fact of the product: **the search works
best where the law allows it to work**, and the application is built to be
useful and honest about the difference.

---

# PART TEN — COMPLETE FILE INDEX

---

## 42. Project root

| File | Purpose |
|---|---|
| `main.py` | Application entry point (`python main.py`) + `--self-check` |
| `search_engine.py` | Production retrieval engine (474 lines), loaded **by path** |
| `lyric_sync_gospel.lsdb` | The production songbook — 36.8 MB, **never written by the application** (three sanctioned out-of-band operator changes are recorded in §41) |
| `requirements.txt` | Exactly `PySide6>=6.6.0` — one line, nothing else |
| `lyricsync.spec` | PyInstaller build definition |
| `LyricSync.iss` | Inno Setup installer definition |
| `README.md` | User-facing readme |
| `FINAL_REPORT_3.2.0.md` | Catalogue expansion report with full audit trail |
| `lyrics-scraper.cmd` | Root launcher for the builder |
| `lyrics_scraper.py` | Shim so `python -m lyrics_scraper` works from the root |
| `firebase_config.json` | Public Firebase web config for optional account sign-in (no secrets) |
| `.gitignore` | Ignores caches, build output |

## 43. `lyric_sync/` — the application

```
lyric_sync/
├── main.py                          bootstrap + CLI flags
├── __init__.py
├── app/
│   ├── config.py                    constants, path discovery (5.1 KB)
│   ├── theme.py                     palette + stylesheet, no blue (18.4 KB)
│   ├── application.py               QApplication bootstrap (1.2 KB)
│   ├── self_check.py                packaged-build verification (2.6 KB)
│   └── dev_log.py                   developer.log for failures (1.1 KB)
├── models/
│   ├── song.py                      Song, int + text ids (3.9 KB)
│   ├── lyric.py                     SongLyrics, LyricSection (2.7 KB)
│   └── search_result.py             SearchResult (1.4 KB)
├── database/
│   ├── lsdb_manager.py              all SQLite access (34.8 KB)
│   ├── database_validator.py        non-destructive reports (11.5 KB)
│   ├── schema_adapter.py            tolerant column mapping (12.3 KB)
│   └── queries.py                   raw SQL in one place (3.3 KB)
├── search/
│   ├── lyric_search_service.py      the UI's doorway (24.1 KB)
│   ├── search_engine.py             in-package retrieval, fixture schema (12.4 KB)
│   ├── ranker.py                    weights, thresholds, labels (12.1 KB)
│   ├── query_normalizer.py          folding + contraction variants (6.4 KB)
│   ├── highlighter.py               excerpts + spans (4.1 KB)
│   └── engine_loader.py             loads engine by path (3.8 KB)
├── storage/
│   ├── preferences.py               atomic JSON (3.6 KB)
│   └── favorites.py                 text-id safe favourites (4.9 KB)
├── auth/
│   ├── firebase_config.py           firebase_config.json loader
│   ├── firebase_client.py           Identity Toolkit REST client (urllib)
│   ├── secure_store.py              DPAPI-protected session token store
│   └── session.py                   AuthSession QObject (offline-safe)
└── ui/
    ├── main_window.py               header + sidebar shell, orchestration
    ├── search_screen.py             search + results + lyrics preview panel
    ├── song_page.py                 full lyrics (11.2 KB)
    ├── library_page.py              favorites + saved searches
    ├── favorites_page.py            starred grid (6.2 KB)
    ├── settings_page.py             appearance/search/db/application
    ├── about_page.py                version, stats, credits
    ├── account_page.py              Firebase sign-in / sign-up / reset
    ├── db_info_page.py              schema + counts (7.9 KB)
    ├── workers.py                   QRunnable tasks (3.2 KB)
    └── components/
        ├── search_box.py            input with focus border
        ├── result_row.py            result row (click/double-click)
        └── widgets.py               shared widgets
```

## 44. `tools/lyrics-scraper/` — the builder

```
tools/lyrics-scraper/
├── README.md                        builder-specific documentation
├── lyrics-scraper.cmd               launcher (sets PYTHONPATH)
├── lyrics_scraper/
│   ├── __main__.py                  python -m lyrics_scraper
│   ├── cli.py                       argument parsing + commands
│   ├── ui.py                        Tkinter window (838 lines)
│   ├── fetch.py                     HTTP, robots, Retry-After, cache
│   ├── detect.py                    page-type classification
│   ├── parser.py                    OpenGospelLyrics rules
│   ├── african.py                   African Gospel Lyrics rules
│   ├── gutenberg.py                 3 print layouts + HTML hymn books
│   ├── zionlyrics.py                shared Zion helpers
│   ├── htmldoc.py                   shared HTML utilities
│   ├── models.py                    NormalizedSong, Warning, RawPage
│   ├── normalize.py                 normalize, hashes, slug
│   ├── validate.py                  18 finding codes
│   ├── dedupe.py                    5 rules, DedupIndex
│   ├── staging.py                   10 tables + migrations
│   ├── engine.py                    ingest orchestration
│   ├── export.py                    .lsdb writer + guardrails
│   └── adapters/
│       ├── __init__.py              registry + adapter_for()
│       ├── base.py                  SourceAdapter contract
│       ├── ogl.py                   OpenGospelLyrics
│       ├── agl.py                   African Gospel Lyrics
│       ├── gutenberg.py             GutenbergHymnBookAdapter
│       └── zionlyrics.py            ZionLyricsAdapter
└── tests/
    ├── conftest.py                  fixtures, prod_db_path
    ├── fixtures/ogl_christmas.html  OGL fixture
    ├── fixtures/agl_good_god.html   AGL fixture
    ├── test_adapters.py             15
    ├── test_cli.py                  5
    ├── test_export_lyrics.py        5
    ├── test_gutenberg.py            24
    ├── test_hardening.py            11
    ├── test_pipeline.py             8
    ├── test_ui.py                   7
    └── test_zionlyrics.py           13
```

## 45. `tools/` (application tooling)

| File | Purpose |
|---|---|
| `build_windows.ps1` | Full package build (tests → PyInstaller → verify) |
| `build_dev_fixture.py` | Builds the development `.lsdb` fixture |
| `build_gospel_db.py` | Gospel catalogue builder |
| `expand_ng_catalog.py` | Nigerian artist catalog importer (16 catalogs) |
| `smoke_ui.py` | Headless UI smoke test |
| `bench_search.py` | Search latency benchmark |

## 46. `tests/` — application suite

```
tests/
├── conftest.py                  fixtures + dev fixture builder (0.9 KB)
├── fixture_builder.py           builds a real .lsdb for tests (9.5 KB)
├── test_auth.py                 33   ← Firebase client/session, faked transport
├── test_config.py                7
├── test_database.py             25
├── test_highlighter.py           8
├── test_production_lsdb.py      58   ← real-database integration
├── test_query_normalizer.py     13
├── test_search.py               23
├── test_service_errors.py        6
├── test_storage.py              12
└── test_workers.py               4
```

## 47. `data/`

```
data/README.txt
data/lyric_sync_gospel_next.report.json     next-version staging report
data/backups/                               versioned rollback points
data/ng_expansion/                          16 artist JSON catalogs + reports
```

---

# PART ELEVEN — INVARIANTS

---

## 48. Rules that must never break

These are the load-bearing walls. If a future change violates one, the
change is wrong regardless of how clean it looks.

### About the application

1. **Network access is optional and auth-only.** Searching, favorites,
   settings and the database never touch the network. The sole network
   client is the optional Firebase sign-in path, written with stdlib
   `urllib` — no telemetry, no update check, no font/CDN fetch, no
   analytics initialization. The Qt WebEngine/QML/multimedia modules are
   excluded from the build.
2. **The `.lsdb` is never written.** `PRAGMA query_only = ON` immediately
   after open, in every code path, forever.
3. **No schema changes, no migrations, no repairs** inside the application.
   Validation reports; it does not fix.
4. **Every SQL statement is parameterised.** No string-built queries.
5. **No fabricated confidence numbers.** Match labels are bucket names
   tied to published thresholds.
6. **The engine is never rewritten.** Ranking behaviour belongs to
   `search_engine.py`; the app may only tie-break equal scores.
7. **Database work stays off the UI thread**, serialised on one lock.
8. **Languages are never guessed.** `language_confidence` must be
   `explicit`, `inferred` or `unknown`.
9. **Brand palette:** orange, yellow, white, black. **No blue.**

### About the builder

10. **The production `.lsdb` is never opened for writing.** The export
    refusal for `--out == prod` happens **before** any unlink.
11. **Lyrics are written only with `--include-lyrics` + staging
    `include_lyrics = 1` + `copyright_status ∈ {PUBLIC_DOMAIN, AUTHORIZED}`.**
12. **Auto-approve only for `PUBLIC_DOMAIN` + `clean`.** Everything else
    waits for a human.
13. **Songs are never dropped by dedupe**, and never auto-merged on title
    alone.
14. **Multi-song pages use `url#fragment`**, so siblings never dedupe against
    each other.
15. **No crawler may exceed its politeness budget** — robots, `Crawl-delay`,
    `Retry-After` and the delay setting are all honoured.
16. **Never mix parsers across sites.** An explicit `--source` that does not
    own the URL host is an error.

### About the boundary

17. **`requirements.txt` stays `PySide6>=6.6.0`.** The builder adds no
    dependency to the shipped product.
18. **`lyricsync.spec` never collects `tools/lyrics-scraper`.**
19. **The builder never imports `lyric_sync`.**
20. **No scraper page, button or menu exists in the application.**
21. **Neither suite may perform a network request.** Auth tests always run
    against injected fake transports.

---

## 49. Verification commands

```powershell
# Application suite (expect 189 passed)
python -m pytest tests -q

# Builder suite (expect 88 passed)
python -m pytest tools\lyrics-scraper\tests -q

# Static checks (expect no output)
python -m pyflakes lyric_sync tools tests
python -m pyflakes tools\lyrics-scraper\lyrics_scraper tools\lyrics-scraper\tests lyrics_scraper.py

# Run the application
python main.py

# Builder from the root
lyrics-scraper.cmd --help
lyrics-scraper.cmd stats
lyrics-scraper.cmd coverage

# Build the songbook
lyrics-scraper.cmd single https://www.gutenberg.org/cache/epub/46041/pg46041.txt --source gutenberg
lyrics-scraper.cmd review --all --source gutenberg --approve --include-lyrics
lyrics-scraper.cmd export --out output\exports\hymns.lsdb --include-lyrics

# Package
powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
ISCC.exe LyricSync.iss
dist\LyricSync\LyricSync.exe --self-check
```

---

## 50. Closing summary

**Lyric Sync** is two programs separated by a wall.

On one side, a **PySide6 desktop application** that searches a local
SQLite songbook from a half-remembered lyric line — offline-first, read-only,
fast, with honest match labels and no fabricated confidence. Account
sign-in is optional; the songbook never leaves the machine.

On the other side, a **standard-library-only database builder** that turns
websites and two-hundred-year-old hymn books into that songbook, under strict
copyright guardrails, with a human in the review loop.

Between them sits `lyric_sync_gospel.lsdb` — 4,998 songs, 57,536 lyric lines,
1,230 artists, 29 documented imports, content digest `ffc3f3e8…` — which
neither program is allowed to write to in normal operation (the three
recorded exceptions are direct operator changes of 2026-10-20 and
2026-10-21, §41).

The wall is the design. Everything else follows from it.
