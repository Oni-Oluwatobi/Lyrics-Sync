# Lyric Sync — UI Overhaul + Firebase Authentication: Delivery Report

**Date:** 2026-10-20 · **Version:** 1.0.0 · **By The Kreadive Galaxy**

This report covers the approved design overhaul (compact header + sidebar +
three-area Search workspace) and the optional Firebase Authentication feature.

---

## 1. Files created

| File | Size | Purpose |
|---|---|---|
| `lyric_sync/ui/search_screen.py` | 21.5 KB | The new Search workspace: search field + Search button, compact ranked results, live lyrics preview panel (IDLE/LIST/EMPTY/UNAVAILABLE/ERROR states, chunked rendering, responsive preview collapse) |
| `lyric_sync/ui/library_page.py` | 6.3 KB | My Library: embedded Favorites + saved/recent searches |
| `lyric_sync/ui/about_page.py` | 7.5 KB | About: version, real DB stats, tagline, privacy, credits |
| `lyric_sync/ui/account_page.py` | 10.9 KB | Account: sign-in / create account / reset password / sign-out |
| `lyric_sync/auth/__init__.py` | 0.6 KB | Auth package |
| `lyric_sync/auth/firebase_config.py` | 1.7 KB | Loads `firebase_config.json` (env override → project root → bundle → exe dir → user data) |
| `lyric_sync/auth/firebase_client.py` | 7.7 KB | urllib-only Identity Toolkit REST client (sign-in, sign-up, password reset, token refresh, account lookup) with friendly error mapping |
| `lyric_sync/auth/secure_store.py` | 4.0 KB | DPAPI-protected session store (atomic writes; tokens + email only, never the password) |
| `lyric_sync/auth/session.py` | 8.1 KB | `AuthSession` (Qt signals; all network work off the UI thread via `workers.py`) |
| `firebase_config.json` | 0.3 KB | Public web config supplied by the user (no secrets) |
| `tests/test_auth.py` | 18.9 KB | 33 tests: client contract, error mapping, DPAPI store, session transitions — all with faked transports |

## 2. Files modified

| File | Change |
|---|---|
| `lyric_sync/ui/main_window.py` (37.8 KB, rewritten) | Header (name + tagline + developer credit), sidebar (Search / My Library / Settings / About, account row, DB status dot + counts, `v1.0.0`), 7 pages, auth wiring, saved-search wiring, missing-DB → Search unavailable state; all prior orchestration preserved |
| `lyric_sync/app/theme.py` | Near-black neutral palette (`#0A0A0A`/`#0D0D0D`/`#111111`/`#171717`), `#252525` borders, `chrome` role, `HEADER_HEIGHT=52`, nav width 200, header/toggle/tagline QSS; no blue, no gradients, no glow |
| `lyric_sync/ui/components/search_box.py` | Focus glow removed; crisp border only |
| `lyric_sync/ui/components/result_row.py` | `double_activated` signal (double-click opens the song) |
| `lyric_sync/ui/settings_page.py` | Sections regrouped (Appearance / Search / Database / Application), About button → `open_about`; every existing setting preserved |
| `tools/smoke_ui.py` | New contract: `PAGE_SEARCH`, 7 pages, `search_screen` checks |
| `lyricsync.spec` | Bundles `firebase_config.json` next to the app |
| `README.md` | New screens table, layout tree, security/privacy wording, test count |
| `PROJECT_GUIDE.md` | §25/§26 rewritten, new **§26a Firebase setup + code map**, §36/§39/§42/§43/§46/§48/§49/§50 updated |

## 3. Files removed

* `lyric_sync/ui/home_page.py` — replaced by the Search workspace
* `lyric_sync/ui/results_page.py` — results + preview now live in `search_screen.py`

## 4. Untouched by design

`search_engine.py`, `lyric_sync_gospel.lsdb` (SHA-256 unchanged),
`requirements.txt` (`PySide6>=6.6.0` only), `LSDBManager`, `workers.py`,
`song_page.py`, `favorites_page.py`, `db_info_page.py`, builder toolchain.

## 5. User flows

* **Search:** type / press Enter or Search → off-thread search → compact rows
  with real labels (Strong / Good / Possible) → single click selects and drives
  the lyrics preview (matched lines highlighted) → double-click / Enter /
  "Open full song" opens the Song page. Sensitivity switcher + result count in
  the meta row; preview auto-collapses under 980 px (toggleable).
* **Library:** favorites (filter/sort/remove) + saved/recent searches; star a
  song in Song page appears immediately; recents are one click from Account…
  never, from My Library only.
* **Settings → About:** new "About Lyric Sync" button; DB reload/locate/
  validate unchanged; theme/sensitivity/live-search/history unchanged.
* **Database missing:** Search page shows the "Gospel database not installed"
  state with placement instructions; everything else stays navigable.
* **Account:** three modes (sign in / create / reset) + signed-in card with
  email and sign-out. Launch restores the saved session silently; a failed
  refresh signs out quietly with an error banner; network failure keeps the
  session.

## 6. Configuration (user-supplied)

Root `firebase_config.json` (also bundled by the spec): project
`lyrics-sync-workstation`, web `apiKey` / `appId` / `messagingSenderId` /
`measurementId`. **Public values only** — no service-account keys, no
analytics initialization. Sign-in never blocks search; without the file the
app runs exactly as before, just signed out. Console requirement documented in
`PROJECT_GUIDE.md` §26a: enable **Authentication → Email/Password**.

## 7. Test results (all run this session)

| Gate | Result |
|---|---|
| `python -m pytest tests -q` | **189 passed** (156 prior + 33 new auth) |
| `python -m pyflakes lyric_sync tools tests` | **clean** |
| `python tools/smoke_ui.py` (no DB) | **SMOKE OK**, 7 pages |
| `python tools/smoke_ui.py --database lyric_sync_gospel.lsdb` | **SMOKE OK**, 4,813 songs / 57,135 lines, results openable |
| `python main.py --self-check` | **OK** (Way Maker, 30 results, 3.7 s) |
| Prod-DB probe | **PROD_DB_UNTOUCHED** (digest `55e59d50…`) |

## 8. Not tested / limitations

* **No live Firebase call was made** — client and session are proven against
  injected transports; the console may still need Email/Password enabled
  before real sign-in works.
* **No visual/pixel test** — the UI was verified headless (offscreen smoke);
  layout should get a quick human look (preview collapse, nav highlights).
* **No packaged-build rebuild** after the spec change — `firebase_config.json`
  bundling is untested in `dist\LyricSync\LyricSync.exe`.
* DPAPI store proven on Windows only (the only supported platform).
* Password-reset delivery and email templates depend on the Firebase console;
  no custom template was configured.
* Session refresh happens on restore when the token has expired; long-running
  sessions do not schedule periodic refresh (re-auth after ~1 h idle refresh
  expiry is handled at next restore, not mid-session).
* The website button (`https://the-kreadive-galaxy.web.app/`) opens via the
  OS browser; not exercised headless.

---

## 9. Post-delivery database change (2026-10-20)

After the UI delivery, the product owner requested a one-time enrichment of
the metadata-only record *No Me Without You* (Dunsin Oyekan,
`ng_dunsin_oyekan_no_me_without_you`) with 8 supplied lyric lines
(2 stanzas × 4 lines), imported out-of-band with the write patterns of
`tools/build_gospel_db.py` / `tools/expand_ng_catalog.py`:

* `copyright_status` `METADATA_ONLY` → `USER_IMPORTED`,
  `lyrics_status` → `FULL_LYRICS`; 8 `lyrics` rows (Verse 1 / Verse 2);
  search index + FTS fragments refreshed; `build_manifest` row
  `user_import_nmwy_20261020`; `database_metadata` totals + canonical
  content digest recomputed; `VACUUM`; `validate_file(deep=True)` **all
  pass**.
* Counts: 4,813 songs · **57,143** lyric lines (was 57,135); content digest
  `55e59d50…` → **`ad62fdb1ee11b87706968f543dff0244a0ac153f6c9151d82c7c5e30af3f65d0`**;
  file bytes unchanged (36,433,920).
* Backup of the pre-import file:
  `%TEMP%\opencode\lyric_sync_gospel.backup_20261020.lsdb` (verified
  identical to the pre-import database, sha256 `498ad4e2…`).
* Verification after the import: all lyric-line queries rank the song #1
  through the real engine; `get_lyrics` returns Verse 1/Verse 2 sections;
  `pytest tests -q` **189 passed**; smoke **SMOKE OK** (status shows
  57,143 lines); self-check **OK**; prod probe **PROD_DB_AS_EXPECTED**.
  The application itself still never writes the database.

## 10. Post-delivery catalogue change #2: master-registry backfill (2026-10-20)

The product owner supplied a 275-song "Global & National Gospel Song
Database" registry. Full-lyric ingestion of the copyrighted entries was
declined (copyright policy v3); instead the legal maximum was executed:

* **Audit:** 275 registry songs → 19 already had lyrics, 67 already present
  as metadata-only, 189 missing.
* **Metadata backfill:** 189 METADATA_ONLY records added (title/artist/
  credits/provenance, **no lyric text**), 5 `build_manifest` rows
  (`registry_{ng,int,wor,gos,hym}_20261020`), 84 new artist rows.
* **Duplicate cleanup:** a variant guard then removed 4 hymn rows that
  duplicated existing PD originals (Rock of Ages, Down by the Riverside,
  Pass Me Not, Nearer My God to Thee); 3 wrongly-swept pre-existing artist
  rows were restored from the pre-import backup.
* **Result:** **4,998 songs** · 1,230 artists · 57,143 lyric lines (unchanged)
  · 2,011 METADATA_ONLY; content digest `36a705c9…`; file 36,671,488 bytes.
* **Test adjustment:** `test_sensitivity_modes_change_results` now probes
  `"blessed assurance"` instead of `"amazing grace"` — the registry growth
  pushed the latter's single POSSIBLE-tail result past the tolerant cap;
  the invariant under test (strict hides the weakest tier, tolerant
  surfaces it) is unchanged.
* Gates after the change: `pytest tests -q` **189 passed**, pyflakes clean,
  `validate_file(deep=True)` **all pass**, smoke **SMOKE OK**
  (4,998 songs · 57,143 lines), self-check **OK**, prod probe
  **PROD_DB_AS_EXPECTED**. Backup: `%TEMP%\opencode\lyric_sync_gospel.backup_pre_registry.lsdb`.

## 11. Post-delivery catalogue change #3: public-domain hymn text backfill (2026-10-21)

The product owner requested full lyrics for the 442-song wishlist (Sinach,
Nathaniel Bassey, Mercy Chinwo, Moses Bliss, Victoria Orenze, Theophilus
Sunday, Judikay, Ada Ehi, plus a tail of traditional hymns). Full-lyric
ingestion of the **copyrighted** entries was declined (copyright policy,
invariant #11): 397 of those songs stay `METADATA_ONLY` — owner-owned lyrics
can still be added through the documented `USER_IMPORTED` paste flow. The
legal portion was executed:

* **Audit:** 442 wishlist entries → 20 already had full lyrics, 360
  metadata-only (~339 copyrighted + 21 public-domain tail), 62 absent
  (58 copyrighted + 4 variants already covered by lyric-bearing rows).
* **PD text import:** full lyrics for **18 hymns / 393 lines** from
  Hymnary.org "Representative Text" pages, each source page stating
  *Copyright: Public Domain* (verified per hymn before import) — A Mighty
  Fortress, When I Survey, The Old Rugged Cross, Crown Him with Many
  Crowns, All Creatures, And Can It Be, Turn Your Eyes Upon Jesus, Praise
  to the Lord, Joyful Joyful, Swing Low Sweet Chariot, Go Tell It on the
  Mountain, 'Tis So Sweet, Standing on the Promises, Softly and Tenderly,
  Leaning on the Everlasting Arms, Guide Me O Thou Great Jehovah, Fairest
  Lord Jesus, Battle Hymn of the Republic.
* **Deliberate exclusions:** *Victory in Jesus* (Bartlett 1939 — US public
  domain not until 2035) and *We Shall Overcome* (contested rights) remain
  metadata-only; *Nearer, My God, to Thee* was already present as
  *Nearer to Thee* (35 lines); *How Great Thou Art* was left untouched —
  its existing "PUBLIC_DOMAIN" label covers the 1949 Hine translation and
  is flagged for a separate rights review (§41 of the guide).
* **Mechanics:** one transaction — lyric rows (`PUBLIC_DOMAIN`,
  language English, provenance string, folded `normalized_text`), song
  flips `METADATA_ONLY → PUBLIC_DOMAIN` / `lyrics_status =
  PUBLIC_DOMAIN_TEXT`, FTS `lyric_fragments` and
  `lyric_search_index.searchable_text` updated, `build_manifest` row
  `pd_hymn_backfill_20261021`; then `database_metadata` counts + content
  digest recomputed with the established algorithm and `VACUUM`, and the
  `provenance_policy`/`copyright_policy` text extended to record the
  Hymnary.org source and the two deliberate exclusions (policy edit is
  outside the digest input, so the content digest stayed `ffc3f3e8…`;
  only the byte-level file sha changed).
* **Result:** **4,998 songs** · 1,230 artists · **57,536 lyric lines**
  (+393) · **3,004 PUBLIC_DOMAIN** / **1,993 METADATA_ONLY** / 1
  USER_IMPORTED; content digest `ffc3f3e8abc44cc1c5afb84bc7737735ee8b09aa1322cb14061a1a54744f0cc4`;
  file sha256 `e68699f38f8936019f173be674ccdad0a70bc398d6acd0cdd62a32a4593959ef`;
  36,847,616 bytes.
* Gates after the change: `pytest tests -q` **189 passed**, pyflakes clean,
  `validate_file(deep=True)` **0 errors / 0 warnings**, smoke **SMOKE OK**
  (4,998 songs · 57,536 lines; lyric-fragment probe "what a fellowship
  what a joy divine" ranks *Leaning on the Everlasting Arms* #1 Strong),
  self-check **OK** (top Way Maker), prod probe **PROD_DB_AS_EXPECTED**
  (expected values updated for the new digest/counts). Backup:
  `%TEMP%\opencode\lyric_sync_gospel.backup_pre_pd_hymns.lsdb`.
