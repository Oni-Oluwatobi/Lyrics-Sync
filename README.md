# Lyric Sync

**Offline Gospel song identification from remembered lyrics.**
By **The Kreadive Galaxy**.

You remember a line — *"the mighty God, the great I AM"* — you type it in, and
Lyric Sync searches your local `.LSDB` songbook on this computer. Searching,
favorites and settings are fully offline. An optional account sign-in
(Firebase Authentication) is available from the sidebar; it is never required
and the songbook never leaves the machine.

---

## What it does

| Screen | Purpose |
| --- | --- |
| **Search** | Search field + Search button, ranked compact results with match labels, live lyrics preview panel (matched lines highlighted; auto-collapses on narrow windows), sensitivity switcher |
| **Song** | Full lyrics with section headings (Verse, Chorus…), favorite toggle |
| **My Library** | Favorites (filter, sort, remove) plus saved/recent searches — everything local |
| **Settings** | Appearance (theme), Search (history, live search, sensitivity), Database (status, locate, reload, validate, info), Application (version, About) |
| **About** | Version, real database statistics, tagline, privacy notes, credits |
| **Database Info** | Filename, size, song and lyric-line counts, FTS availability, schema checks |
| **Account** | Optional Firebase sign-in / account creation / password reset / sign-out |

### Search behaviour

Searches run through the production engine that ships with the project
(`search_engine.py`, class `LyricSyncSearchEngine`), loaded by path — it is
never rewritten or bypassed:

* Case, punctuation, whitespace, apostrophe, Unicode and diacritic insensitive
  (`GRAET`/`great`, `MIGHTY,`/`mighty`, `are`/`re` all match)
* Contractions are folded (`you're` ↔ `you are`, `he's` ↔ `he is`)
* Partial phrases work: `"mighty god"` finds the line even inside a longer sentence
* Typo tolerance via fuzzy matching: `"amzing grace"` still finds *Amazing Grace*
* Searches titles, artists, **aliases** and full lyric text; every result
  carries a match label tied to a published threshold, never a fabricated
  confidence percentage
* Engine confidence (High/Medium/Low) maps to **Strong / Good / Possible**;
  sensitivity (strict / balanced / tolerant) chooses which tiers are shown
* Equal engine scores are tie-broken in the app (exact title match first) —
  the engine's own ranking is otherwise preserved untouched
* All database work runs **off the UI thread**, serialised on one lock, with
  `PRAGMA query_only = ON` so the connection physically cannot write

---

## Quick start (development)

```powershell
# 1. Dependencies (Python 3.11+)
python -m pip install -r requirements.txt

# 2. Tests — expect: 189 passed (includes real-database integration tests)
python -m pytest tests -q

# 3. Run — the production database next to main.py is found automatically
python main.py
```

The app picks up `lyric_sync_gospel.lsdb` from the project root (or
`data\lyric_sync_gospel.lsdb`), loads `search_engine.py` from the same place
and is immediately searchable. Without a database the app still launches and
shows **“Gospel database not installed”** plus where to put the file.

### Offline smoke test (headless UI check)

```powershell
python tools\smoke_ui.py --database lyric_sync_gospel.lsdb   # real database
python tools\smoke_ui.py                                      # no database
```

### Packaged-build self check

```powershell
dist\LyricSync\LyricSync.exe --self-check
type $env:APPDATA\LyricSync\self_check.txt
```

Confirms the built app can resolve the database, import the bundled engine
and run one real search (windowed builds have no console, so the result is
written to `self_check.txt`).

---

## Where the `.LSDB` database is found

Checked in this order — first file that exists wins:

1. `LYRIC_SYNC_DATABASE` environment variable
2. Override chosen in **Settings → Locate database**
3. `.\lyric_sync_gospel.lsdb` and `.\data\lyric_sync_gospel.lsdb` (current directory)
4. `<project>\lyric_sync_gospel.lsdb` and `<project>\data\lyric_sync_gospel.lsdb`
5. `<package>\data\lyric_sync_gospel.lsdb`
6. `<exe folder>\data\lyric_sync_gospel.lsdb` and `<exe folder>\lyric_sync_gospel.lsdb`
7. Packaged resources (`_internal\data\lyric_sync_gospel.lsdb`)

The search engine `search_engine.py` is discovered the same way:
`LYRIC_SYNC_ENGINE` override → project root → current directory → exe folder
→ packaged resources (`_internal\search_engine.py`), and is imported by path.

**The `.LSDB` file is never modified.** After opening, the service sets
`PRAGMA query_only = ON` so the connection cannot write even by mistake, SQL
is parameterised, and validation runs *without repairing*. The SHA-256 of the
production database is asserted unchanged by the test suite.

User data (preferences, favorites, recent searches, the optional account
session) lives separately in a writable per-user folder:

* Windows: `%APPDATA%\LyricSync\preferences.json`, `favorites.json`,
  `account_session.bin` (DPAPI-protected tokens — never the password)
* Override with `LYRIC_SYNC_USER_DATA=<dir>`

---

## Windows packaging

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
# or just the packaging step:
python -m PyInstaller --clean --noconfirm lyricsync.spec
```

* Output: **`dist\LyricSync\LyricSync.exe`** (folder build, no console window)
* The build bundles **both** required runtime assets:
  `\_internal\search_engine.py` (the downloaded engine) and
  `\_internal\data\lyric_sync_gospel.lsdb` (when present in the source tree)
* Verify with `dist\LyricSync\LyricSync.exe --self-check`
* Switch `-SkipTests` skips the suite; `-Fixture` also builds the dev fixture
  (the fixture is bundled as `data\lyric_sync_dev_fixture.lsdb` when present)
* Create an installer with Inno Setup / NSIS over the `dist\LyricSync` folder
  if you want a Setup.exe

Runtime requirements for the build: `requirements.txt` + `pyinstaller`.
Neither is needed on the target machine (PySide6 is bundled).

---

## Project layout

```
main.py                     entry point (python main.py) + --self-check
search_engine.py            downloaded production engine (LyricSyncSearchEngine)
lyric_sync_gospel.lsdb      production Gospel database (never modified)
firebase_config.json        public Firebase web config (optional account sign-in)
lyric_sync/
  app/      config.py        paths, branding, .LSDB discovery
            theme.py         TKG dark/light palettes + stylesheet
            application.py   QApplication bootstrap
            dev_log.py       developer.log for detailed failures
            self_check.py    packaged-build verification
  auth/     firebase_client.py  Identity Toolkit REST client (urllib only)
            firebase_config.py  runtime loader for firebase_config.json
            secure_store.py     DPAPI-protected session token store
            session.py          AuthSession (Qt signals, offline-safe)
  models/   song.py lyric.py search_result.py   (int and text song ids)
  database/ lsdb_manager.py  read-only SQLite access (info/validation only)
            database_validator.py  non-destructive validation reports
            schema_adapter.py      tolerant column/schema mapping
            queries.py              raw SQL kept in one place
  search/   engine_loader.py     loads search_engine.py by path (dev + frozen)
            lyric_search_service.py  UI service: search, songs, lyrics
            query_normalizer.py  normalisation + folding
            search_engine.py     in-package retrieval (fixture schema)
            ranker.py            scoring, thresholds, match labels
            highlighter.py       excerpt selection + inline highlighting
  storage/  preferences.py favorites.py   JSON, atomic writes, text-id favorites
  ui/       main_window.py (header + sidebar shell) + search_screen /
            library / settings / about / account / song / db_info pages
            components/   search_box, result_row, widgets
            workers.py     QRunnable background tasks (DB off the UI thread)
tests/      189 tests incl. real-database integration + auth (no network)
tools/      build_dev_fixture.py, smoke_ui.py, build_windows.ps1, bench_search.py
data/       alternate location for lyric_sync_gospel.lsdb
```

### Identity

The Kreadive Galaxy brand colours are orange / yellow / white / black — no blue
anywhere. Application text: **Lyric Sync · by The Kreadive Galaxy**.

---

## Testing

```powershell
python -m pytest tests -q          # all green
python -m pyflakes lyric_sync tools tests
```

Coverage includes: query normalisation edge cases, typo tolerance, match
label thresholds, `.LSDB` open/inspect/validate, read-only guarantees,
parameterised SQL, missing-database handling, storage round-trips,
background-task callback delivery, plus **real-database integration tests**
(`tests/test_production_lsdb.py`): title/artist/lyric-fragment/typo searches
through the downloaded engine, section order, text-id favorites and a
SHA-256 proof that the production database is untouched.

## Security & privacy

* Read-only database access, no writes, no schema changes, no repairs
* Every SQL statement is parameterised (no string-built queries)
* Searching, favorites and settings never touch the network
* The only optional network calls are Firebase Authentication
  (sign-in / sign-up / password reset) over HTTPS — the database and search
  queries are never uploaded; no analytics, no telemetry
* Favorites and history stored locally as JSON, under your control
* The account session (refresh token) is stored with Windows DPAPI — the
  password is never stored
