# Lyrics Database Builder

A standalone, standard-library-only tool that scrapes gospel lyrics sites
into a **staging database**, validates and de-duplicates the records, and
exports them into Lyric Sync's `.lsdb` format.

```
WEBSITES → BUILDER → STAGING → VALIDATION → DEDUPE → REVIEW → EXPORT → LYRIC SYNC DB
```

## Isolation guarantees

* Never imported by the Lyric Sync application; `lyrics_sync` is not a
  dependency here and this package is never collected into the installer
  (`lyricsync.spec`).
* The production database `lyric_sync_gospel.lsdb` is **never opened for
  writing**. Export copies it (read-only) as the schema template, empties the
  copy, and refuses any `--out` path equal to the production file — that
  refusal happens before anything is deleted.
* No page, button or network call in Lyric Sync performs scraping.

## Sources

| `--source` key        | Site                     | Adapter                      | Copyright default |
| --------------------- | ------------------------ | ---------------------------- | ----------------- |
| `opengospellyrics`    | opengospellyrics.com     | `OpenGospelLyricsAdapter`    | `UNKNOWN`         |
| `africangospellyrics` | africangospellyrics.com  | `AfricanGospelLyricsAdapter` | `UNKNOWN`         |
| `gutenberg`           | gutenberg.org            | `GutenbergHymnBookAdapter`   | `PUBLIC_DOMAIN`   |
| `zionlyrics`          | zionlyrics.com           | `ZionLyricsAdapter`          | `UNKNOWN`         |

`--source auto` (default) picks the adapter from the URL host. Passing an
explicit `--source` that does not own the URL host is an error, so site B's
HTML is never parsed with site A's rules.

### Project Gutenberg

Gutenberg hymn books are the only source that ships **actual public-domain
lyrics**, so they are the one source whose rows are exportable with text.
A single book URL yields hundreds of songs, and each one is given a stable
`{url}#hymn-{n}` fragment so the deduplicator does not collapse the whole
book into a single record.

Three print layouts are detected automatically (`chb`, `bh`, `otb`), plus
the `<div class="hymn">` HTML flavour used by some books. Authors are taken
from the book's `INDEX OF FIRST LINES` (plain text) or its `div.author`
blocks (HTML); when a book has neither the artist falls back to
`Traditional`.

```bat
lyrics-scraper.cmd single https://www.gutenberg.org/cache/epub/46041/pg46041.txt --source gutenberg
lyrics-scraper.cmd coverage
lyrics-scraper.cmd review --all --source gutenberg --approve --include-lyrics
lyrics-scraper.cmd export --out output\exports\hymns.lsdb --include-lyrics
```

### Zion Lyrics

`zionlyrics.com` publishes a sitemap and a JSON API
(`/api/v1/songs?page=N`, `/api/v1/songs/{slug}`). The adapter uses the API
when it can and falls back to HTML parsing. Its terms limit reuse to
personal/educative use, so its rows are staged `METADATA_ONLY` and are never
exported with lyrics.

## Commands

Run them from `tools\lyrics-scraper\` **or from the project root** — a root
`lyrics-scraper.cmd` (sets `PYTHONPATH`) and a root `lyrics_scraper.py` shim
(make `python -m lyrics_scraper` work anywhere) both delegate to this package
and never touch Lyric Sync:

```bat
lyrics-scraper.cmd ui                                :: desktop interface (Tkinter)
lyrics-scraper.cmd single   <url>                    :: one page, no link following
lyrics-scraper.cmd article  <url>                    :: force article detection
lyrics-scraper.cmd category <url> --limit 25         :: listing page + its posts
lyrics-scraper.cmd crawl    <sitemap.xml> --depth 2
lyrics-scraper.cmd stats | validate | dedupe | list [--flagged-only]
lyrics-scraper.cmd coverage                          :: staging broken down by source
lyrics-scraper.cmd review <song_id> --approve --include-lyrics
lyrics-scraper.cmd review --all --source gutenberg --approve
lyrics-scraper.cmd export --out output\exports\new.lsdb [--include-lyrics]
```

Global flags: `--output-dir` (default `output/`), `--source`, `--delay`,
`--timeout`, `--cache-only`, `--ignore-robots`.

`--cache-only` replays `output/raw/*.html` without touching the network.
Every fetch command also takes `--resume`, which re-runs the same URL and
skips pages and songs already in staging — use it after an interrupted crawl.

`coverage` prints a per-source table
(`songs | approved | clean | flagged | ready | public-domain | warnings |
lyrics`) plus a TOTAL row, so you can see how much of a source is still
awaiting review.

`review --all` (optionally narrowed with `--source`) applies the same
`--approve` / `--reject` / `--flag` / `--include-lyrics` / `--copyright`
actions to every staged song in one pass.

## Desktop interface (`ui`)

`lyrics-scraper.cmd ui` (or `python -m lyrics_scraper ui`) opens a Tkinter
window — standard library only, part of the standalone builder, never
imported by Lyric Sync or its installer. It runs **the same CLI** in a child
process, so every window action is reproducible from a terminal:

* **Settings** — output folder, `--source`, delay/timeout, cache-only,
  ignore-robots (all applied to the next command).
* **Run bar** — URL plus Single / Article / Category (limit) / Crawl (depth),
  Validate, Dedupe and **Stop** (terminates the child process).
* **Log** tab — streamed CLI output with colour for commands, warnings and
  errors, plus "open output folder".
* **Staged songs** tab — live table (title, artist, source, date, sections,
  lines, review, warnings) with source/review/search filters; selecting a row
  shows metadata, findings and the exact source lyric lines, with
  Approve / Reject / Flag / include-lyrics / copyright actions.
* **Export** tab — output path, version, include-lyrics / include-flagged /
  overwrite, with the same safety rules as the CLI.

Status bar shows staging counts (`songs | sections | lines | artists | …`).
The window auto-refreshes after every command.

## What each adapter owns

Site knowledge lives entirely in `lyrics_scraper/adapters/*.py` plus one
parser per site (`parser.py` for OpenGospelLyrics, `african.py` for African
Gospel Lyrics, `gutenberg.py` for the printed hymn books, `zionlyrics.py`
for Zion Lyrics):

* page-type detection and the **main content container** (comments,
  subscribe forms, related/trending blocks, sidebars, footers and
  WordPress.com controls are excluded by boundary rules),
* byline parsing — `Title Lyrics by Artist ft. X`, `Title – Artist`, and
  WordPress `post-title`/`post-date` conventions,
* taxonomy splitting into `themes / countries / languages / artists /
  other_tags` (never flattened),
* language declaration with `language_confidence`:
  `explicit` | `inferred` | `unknown` — languages are never guessed,
  and `countries` (e.g. Nigeria) are kept separate from languages (e.g. Yoruba),
* repetition markers: `x4` → `repeat=4`, `x?` → `repeat=1` +
  `repeat_unknown`, `(Repeat)` → `marker="repeat"`, `(Refrain)` →
  `marker="section"` + `target="Refrain"`. Markers are **recorded, never
  expanded**, and `raw` keeps the exact source wording (glosses stay in
  `raw`, with `translation` as an optional side channel).

Every song carries a permanent source record:
`{site, domain, url, article_date, adapter}` (`songs.source_site`,
`source_domain`, `source_adapter`, `source_meta`, `song_sources` rows).

## Staging database (`output/staging/staging.sqlite`)

| Table                | Purpose                                            |
| -------------------- | -------------------------------------------------- |
| `scrape_runs`        | one row per CLI run                                |
| `pages`              | fetched pages (hash-cached HTML in `output/raw`)   |
| `songs`              | metadata, multi-source fields, review state        |
| `song_sections`      | section/line rows incl. `line_raw`, repeats, markers |
| `artists` / `song_artists` | artists with `primary` / `featured` roles    |
| `song_sources`       | one row per source URL (merge keeps both)          |
| `tags` / `song_tags` | source tags and taxonomy buckets                   |
| `validation_warnings`| every validation / dedupe finding                  |

Schema changes are applied in place by `MIGRATIONS` on open.

## Dedupe rules

1. identical source URL → attach as another source (`merge_source`)
   (multi-song pages address each song as `url#fragment`, so this rule
   never swallows a sibling song)
2. identical content hash → merge
3. identical title + artist + lyrics → merge (cross-source)
4. identical lyrics, different title → insert **flagged**
5. same title + artist, different lyrics → insert **flagged**
   (`duplicate_review`) — never auto-merged and never dropped

## Review and copyright

A song is exported with lyrics only when it is `review_status = 'approved'`
**and** `include_lyrics = 1` **and** `copyright_status` is
`PUBLIC_DOMAIN` or `AUTHORIZED`. Everything else stays metadata-only.

The engine auto-approves a song (setting `include_lyrics = 1`) only when its
`copyright_status` is `PUBLIC_DOMAIN` **and** validation reports `clean`.
Every other song is left for a human, which is why a Gutenberg book lands as
roughly 95% ready and the modern lyrics sites land at 0%.

## Export rules

* Default export is **metadata only** (0 lyric rows). Lyrics are written
  only with `--include-lyrics` **and** `songs.include_lyrics = 1` **and**
  `copyright_status ∈ {PUBLIC_DOMAIN, AUTHORIZED}`; flagged songs additionally
  need `--include-flagged`.
* Exported songs are `verified = 0`, `verification_status = 'UNVERIFIED'`.
* `language` comes from the first declared language (falling back to the
  site language field, then `English`), `country` from the first declared
  country, `source`/`source_url` from the song's own origin, and one
  `build_manifest` row is written per source site.

## Tests

```bat
python -m pytest tools\lyrics-scraper\tests -q
```

Offline only: page fixtures live in `tests/fixtures/`. The suite covers
adapter detection, every site parser (boundaries, languages/countries,
markers, the three Gutenberg print layouts and its HTML flavour), staging
round-trips, cross-source merge/flag behaviour, resume/Retry-After/
Crawl-delay, the `coverage` and `review --all` commands, and export safety
(both "lyric rows are actually written" and "production is byte-identical
afterwards").

## Adding a source

1. Create `lyrics_scraper/adapters/mysite.py` subclassing `SourceAdapter`
   (`name`, `site`, `domain`, `adapter_name`, `_parse()`).
2. Write `lyrics_scraper/mysite.py` for the site's HTML rules and return a
   `ParseResult` of `NormalizedSong` records.
3. Register the adapter in `lyrics_scraper/adapters/__init__.py` (`ADAPTERS`).
4. Drop a page fixture into `tests/fixtures/` and add parse + boundary tests.
