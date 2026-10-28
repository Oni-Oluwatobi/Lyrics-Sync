# Lyric Sync — Gospel Catalog Expansion — Final Report
**Database:** `lyric_sync_gospel.lsdb` · **Version:** 3.2.0 · **Date:** 2026-10-05
**SHA-256 (content digest):** `55e59d50a1c284ae4b83f096d1b5ee7e54012cc076eff693ca0b00f7ac04528a`

---

## 1. Executive summary
The production Gospel database was expanded in two passes from **3,044 → 4,813 songs** (+1,769) and **433 → 1,146 artists** (+713) while keeping the existing single-database architecture and search engine. Six core expansion artists received dedicated catalog imports (pass 1), ten additional Nigerian artists received dedicated catalog imports (pass 2), and a latent ranking defect in the search engine that buried newly-inserted songs was found and fixed. All new records are metadata-only (no lyric text added, zero new FULL_LYRICS), every new row carries source provenance, deduplication skipped 696 duplicate candidates, validation passes deep checks, **156/156 tests pass**, and the package was rebuilt once with self-check/smoke/bench all green. Catalog research completed for **10 of the 60 additional artists**; the remaining 50 are reported honestly in §5.

## 2. Scope & targets
- 6 core expansion artists: **Dunsin Oyekan, Lawrence Oyor, Mercy Chinwo, Nathaniel Bassey, Greatman Takit, Minister Mike**.
- 60 additional artists specified for inspection/expansion (Sinach, Ada Ehi, Eben, Joe Praize … Eno Michael), including a 10-artist batch that received full catalog research: **Bidemi Olaoba, Festizie, Marizu, Midnight Crew, Mike Abdul, Mr M & Revelation, Neeja, Sammie Okposo, Samsong, Testimony Jaga**.
- 66 artists total audited before/after with per-artist counts (§9).

## 3. Constraints honored
- No rebuild from scratch; existing engine/architecture kept (one documented bug fix only, §15).
- Production DB never destroyed: rollbacks exist as versioned backups (§24).
- Single database only — no per-artist DBs; `data/` contains no `.lsdb` (root file remains canonical).
- No lyrics scraped, licensed ambiguously, or AI-generated: **0 lyric text rows added**; no lyric API is configured in the project.
- No temp debug code in shipped files; all QA scripts lived in `%TEMP%` and were deleted after use.

## 4. Method (phases)
1. **Phase A** — environment/lyric-source audit (found no local lyric datasets, no lyric API → all modern songs must be METADATA_ONLY).
2. **Phase B** — catalog research for additional artists via parallel research agents (interrupted twice by "finish up" → see §5).
3. **Phase C** — importer tooling: `tools/expand_ng_catalog.py` extended (16 catalogs, artist-credit handling, URL dedup, enrichment, version 3.2.0).
4. **Phase D** — pass-1 commit (6 artists, earlier in this task): 3,044 → 3,682 songs.
5. **Phase E** — pass-2 dry-run → commit (10 artists): 3,682 → 4,813 songs.
6. **Phase F** — quality: dedup scan, credit-casing fixes, re-validation.
7. **Phase G** — tests, package rebuild (once), self-check, smoke, bench, memory.
8. **Phase H** — cleanup of temp scripts + this report.

## 5. Research coverage & honesty
- **Completed:** 10 of 60 additional artists (batch 4) — 1,813 catalog entries collected across 16 JSON files (6 core + 10 batch-4), each with `source_url`, confidence, and notes.
- **Not completed:** 50 of 60 additional artists — the research agents for the other five batches were interrupted twice by "finish up" instructions; no partial/fabricated data was written for them. They appear in §9 with only opportunistic guest-credit additions (or none).
- Guest-credit additions from pass-1/pass-2 files did opportunistically add rows for many of the 50 (e.g. Moses Bliss +21, Limoblaze +16, TY Bello +7) — these come from genuine researched collab credits in the completed files, not from dedicated research.

## 6. Database totals

| Metric | Before task | After pass 1 | **Final (v3.2.0)** | Net change |
|---|---:|---:|---:|---:|
| Songs | 3,044 | 3,682 | **4,813** | **+1,769** |
| Artists | 433 | 610 | **1,146** | **+713** |
| Lyric lines | 57,135 | 57,135 | **57,135** | **0** |
| File size (bytes) | 33,972,224 | 34,897,920 | **36,433,920** | +2,461,696 |
| database_version | 3.0.0 | 3.1.0 | **3.2.0** | — |
| Copyright split | — | — | **1,827 METADATA_ONLY / 2,986 PUBLIC_DOMAIN** | — |

## 7. Pass 1 — six core expansion artists
- 652 catalog entries → **638 inserted**, 14 duplicate-skipped, 0 rejected.
- Catalog files: `dunsin_oyekan.json` (123), `nathaniel_bassey.json` (196), `greatman_takit.json` (107), `mercy_chinwo.json` (96), `lawrence_oyor.json` (93), `minister_mike.json` (37).
- Version bumped to 3.1.0; backup `lyric_sync_gospel_v3.1.0_7faac476.lsdb` taken before pass 2.

## 8. Pass 2 — ten additional artists
- 1,813 entries → **1,131 inserted**, 682 duplicate-skipped (652 existing-key + 30 URL/in-batch), **0 rejected**.
- Per-artist inserted (final minus pre-commit): Bidemi Olaoba +94, Festizie +75, Marizu +143, Midnight Crew +51, Mike Abdul +206, Mr M & Revelation +148, Neeja +24, Sammie Okposo +112, Samsong +184, Testimony Jaga +94.
- **9 rows enriched** (field fills + guest-credit corrections): Minister Mike +4, Nathaniel Bassey +5 — including two rows previously reading "Minister Mike feat. Minister Mike" → `Femi Praise feat. Minister Mike`, `Ucious Music feat. Minister Mike`.
- `build_manifest` now holds **22 import records** (6 + 16), each with parsed/accepted/skipped counts and source domain.

## 9. Per-artist coverage (66 target artists)
Columns: **Existing** = pre-task rows (v3.0.0 backup audit) · **Added** = final − existing · **Enriched** = rows corrected in pass 2 · **FULL_LYRICS** = rows with lyric text · **METADATA_ONLY** = final total. Note: collab rows credit multiple artists, so per-artist "Added" sums to more than the 1,769 unique songs added.

### Core six (dedicated catalogs)
| Artist | Existing | Added | Enriched | FULL_LYRICS | METADATA_ONLY |
|---|---:|---:|---:|---:|---:|
| Dunsin Oyekan | 3 | 125 | 0 | 0 | 128 |
| Lawrence Oyor | 1 | 97 | 0 | 0 | 98 |
| Mercy Chinwo | 3 | 99 | 0 | 0 | 102 |
| Nathaniel Bassey | 4 | 197 | 5 | 0 | 201 |
| Minister Mike | 0 | 35 | 4 | 0 | 35 |
| Greatman Takit | 0 | 113 | 0 | 0 | 113 |

### Batch-4 ten (dedicated catalogs)
| Artist | Existing | Added | Enriched | FULL_LYRICS | METADATA_ONLY |
|---|---:|---:|---:|---:|---:|
| Bidemi Olaoba | 0 | 95 | 0 | 0 | 95 |
| Mr M & Revelation | 0 | 149 | 0 | 0 | 149 |
| Testimony Jaga | 0 | 100 | 0 | 0 | 100 |
| Marizu | 0 | 143 | 0 | 0 | 143 |
| Festizie | 1 | 75 | 0 | 0 | 76 |
| Neeja | 0 | 31 | 0 | 0 | 31 |
| Mike Abdul | 0 | 216 | 0 | 0 | 216 |
| Samsong | 0 | 186 | 0 | 0 | 186 |
| Sammie Okposo | 0 | 113 | 0 | 0 | 113 |
| Midnight Crew | 0 | 51 | 0 | 0 | 51 |

### Other 50 artists (no dedicated research; guest-credit additions only)
| Artist | Existing | Added | Enriched | FULL_LYRICS | METADATA_ONLY |
|---|---:|---:|---:|---:|---:|
| Sinach | 2 | 4 | 0 | 0 | 6 |
| Ada Ehi | 1 | 5 | 0 | 0 | 6 |
| Eben | 1 | 4 | 0 | 0 | 5 |
| Joe Praize | 0 | 0 | 0 | 0 | 0 |
| Frank Edwards | 1 | 4 | 0 | 0 | 5 |
| Tim Godfrey | 0 | 5 | 0 | 0 | 5 |
| Victoria Orenze | 1 | 7 | 0 | 0 | 8 |
| Judikay | 1 | 4 | 0 | 0 | 5 |
| Moses Bliss | 2 | 21 | 0 | 0 | 23 |
| Minister GUC | 1 | 0 | 0 | 0 | 1 |
| Tope Alabi | 1 | 4 | 0 | 0 | 5 |
| Prospa Ochimana | 0 | 4 | 0 | 0 | 4 |
| Yadah | 0 | 0 | 0 | 0 | 0 |
| Sunmisola Agbebi | 0 | 6 | 0 | 0 | 6 |
| Theophilus Sunday | 1 | 8 | 0 | 0 | 9 |
| Kaestrings | 0 | 1 | 0 | 0 | 1 |
| Neon Adejo | 0 | 1 | 0 | 0 | 1 |
| Chris Morgan | 0 | 4 | 0 | 0 | 4 |
| Steve Crown | 1 | 2 | 0 | 0 | 3 |
| Peterson Okopi | 0 | 2 | 0 | 0 | 2 |
| Folabi Nuel | 0 | 4 | 0 | 0 | 4 |
| Onos Ariyo | 0 | 3 | 0 | 0 | 3 |
| Sola Allyson | 0 | 2 | 0 | 0 | 2 |
| Lara George | 0 | 0 | 0 | 0 | 0 |
| Ebuka Songs | 0 | 1 | 0 | 0 | 1 |
| Limoblaze | 0 | 16 | 0 | 0 | 16 |
| Gaise Baba | 0 | 6 | 0 | 0 | 6 |
| Prinx Emmanuel | 0 | 6 | 0 | 0 | 6 |
| CalledOut Music | 1 | 2 | 0 | 0 | 3 |
| Anendlessocean | 0 | 1 | 0 | 0 | 1 |
| Chioma Jesus | 0 | 3 | 0 | 0 | 3 |
| TY Bello | 1 | 7 | 0 | 0 | 8 |
| Nosa | 0 | 8 | 0 | 0 | 8 |
| Obiwon | 0 | 1 | 0 | 0 | 1 |
| Kunle Ajayi | 0 | 2 | 0 | 0 | 2 |
| Panam Percy Paul | 0 | 2 | 0 | 0 | 2 |
| Solomon Lange | 0 | 4 | 0 | 0 | 4 |
| Nikki Laoye | 0 | 0 | 0 | 0 | 0 |
| Tosin Martins | 0 | 1 | 0 | 0 | 1 |
| Buchi | 0 | 4 | 0 | 0 | 4 |
| Bukola Bekes | 0 | 0 | 0 | 0 | 0 |
| Glowreeyah | 0 | 0 | 0 | 0 | 0 |
| Okey Sokay | 0 | 1 | 0 | 0 | 1 |
| Ayo Vincent | 0 | 0 | 0 | 0 | 0 |
| Chinyere Udoma | 0 | 0 | 0 | 0 | 0 |
| Dunni Olanrewaju | 0 | 0 | 0 | 0 | 0 |
| Jahdiel | 0 | 0 | 0 | 0 | 0 |
| Jeremiah Gyang | 0 | 0 | 0 | 0 | 0 |
| Mairo Ese | 0 | 1 | 0 | 0 | 1 |
| Eno Michael | 0 | 1 | 0 | 0 | 1 |

## 10. Artists with zero records
**11 of 66** target artists have no songs in the database after this task: Joe Praize, Yadah, Lara George, Nikki Laoye, Bukola Bekes, Glowreeyah, Ayo Vincent, Chinyere Udoma, Dunni Olanrewaju, Jahdiel, Jeremiah Gyang. All are in the not-researched group (§5); none were fabricated.

## 11. Lyrics & rights
- **FULL_LYRICS added: 0.** No authorized lyric source exists in the project (no local datasets, no configured lyrics API, no license grants) and the target artists' songs are modern/copyrighted → every new row is `METADATA_ONLY`.
- Existing PUBLIC_DOMAIN lyrics untouched: 2,986 songs / 57,135 lines, still fully searchable (FTS phrase tests pass).
- Rights posture validated: copyright statuses present in DB = `METADATA_ONLY`, `PUBLIC_DOMAIN` only; 0 new rows with other/NULL status; 0 METADATA_ONLY songs carry lyric rows.

## 12. Data enrichment & credit corrections
- **9 enrichment updates** (pass 2): filled empty `album`/`release_year`/`version`/`songwriter` fields and corrected 4 impossible self-feature credits on Minister Mike + 5 Nathaniel Bassey rows; `lyric_search_index`/`lyric_search_fts` kept in sync.
- **14 casing corrections** (evidence-based, researched sources internally inconsistent): `solomon lange`→`Solomon Lange` (2), `neon adejo`→`Neon Adejo`, `Testimony jaga`→`Testimony Jaga`, `feat. eben`→`feat. Eben`, `Segun johnson`→`Segun Johnson`, `nina shezz`→`Nina Shezz`, `The membrane`→`The Membrane` (3), `a'dam`→`A'dam`.
- **8 source-faithful stylizations deliberately left as researched** (credits are lowercase in the cited sources): `pa song`, `Colins myles`, `Toni wenum`, `T fresh`, `Dj Penny`, `Skerz beatz`, `God of all flesh`.
- Content digest recomputed after every edit (`sha256` above).

## 13. Deduplication
- Pass 1: 14 duplicates skipped (title+artist key).
- Pass 2: 682 skipped — 652 existing-title+file-artist key matches, 30 URL-based / in-batch version-aware matches. 0 rejected for quality.
- Post-commit scan: **0 exact (normalized title, artist) duplicate pairs** across new rows.
- Total skipped duplicates across task: **696**; unique songs added: **1,769**.

## 14. Provenance
- Every one of the 1,769 new rows has non-empty `source_url`, `source`, `verification_status` (0 missing).
- `build_manifest`: 22 rows with file name, counts parsed/accepted/skipped, source domain.
- QC over all 16 catalog files before import: 1,813 entries, 0 missing `source_url`, **0 lyric-like text fields** (`lyrics`/`lyric`/`lines` keys absent).

## 15. Search engine defect & fix
- **Defect:** root `search_engine.py` capped exact/full-overlap scores at 100; sort was score-only — Python's stable sort kept DB insertion order among the resulting large 100-tie class, so newly appended songs lost every tie and were cut by `[:limit]` (30). The service-layer `_exact_title_first` tie-break (`lyric_search_service.py:480`) runs after engine truncation, so it never saw the cut songs.
- **Fix (one line, sorting only):** `results.sort(key=lambda r: (r['score'], r['exact_match']), reverse=True)` — `search_engine.py:378`, mirrored into the packaged engine. No scoring, fuzzy, synonym, or FTS behavior changed.
- Verified: `New Wine` → 10 Dunsin songs in top 30 (was 0); `You Are Good` → #1 Dunsin / #2 Nathaniel / #3 Greatman (was 0); `Oke Mmiri` → #1 Mercy Chinwo; `A Cry for Mercy` → #1 Minister Mike; `Favour` → #1 Lawrence Oyor.

## 16. Search quality verification
- 24-query engine smoke after both passes: **24/24 queries return hits**, correct artists surfaced.
- Exact-title + artist coverage asserted in tests for 12 core-catalog queries and **25 expanded-catalog queries** (spec list: Sinach, Ada Ehi, Eben, Frank Edwards, Tim Godfrey, Victoria Orenze, Judikay, Moses Bliss, Minister GUC, Tope Alabi, Sunmisola Agbebi, Theophilus Sunday, Limoblaze, Gaise Baba, Ebuka Songs, Samsong, Mike Abdul, Midnight Crew, Sammie Okposo, Testimony Jaga, Marizu, Festizie, Neeja, Bidemi Olaoba, Mr M & Revelation).
- Fuzzy/typo verified: `amzing grace` → 30 hits; `Midnight Crewe` → surfaces Midnight Crew (test).
- Lyric-phrase (existing PD) verified: `that saved a wretch like me` → `Amazing Grace / John Newton`; `way maker` → `Way Maker / Sinach`.

## 17. Database validation
Final `validate_file(deep=True)` — **ALL PASS**: file exists, size 36,433,920, valid SQLite header, read-only open, songs/artists counts (4,813 / 1,146), 57,135 lyric lines, schema version 1, FTS `lyric_search_fts` 4,813 rows, `PRAGMA integrity_check` = ok, copyright statuses ⊆ {METADATA_ONLY, PUBLIC_DOMAIN}, all lyric lines resolve to a song.

## 18. Integrity spot-checks
- U+FFFD in songs/lyrics: **0**; HTML tags in songs: **0**; empty lyric rows: **0**.
- METADATA_ONLY songs with lyric rows: **0**; new rows missing source_url/source/verification_status: **0**; new rows non-METADATA_ONLY: **0**.
- `lyric_search_index` = `lyric_search_fts` = songs = **4,813 / 4,813**.

## 19. Test suite
- `python -m pytest tests -q` → **156 passed in 209.68s** (130 prior + 12 core-catalog param + 25 expanded-catalog param + 1 fuzzy).
- `python -m pyflakes lyric_sync tests tools main.py search_engine.py` → **clean**.
- Updated expectations: `song_count == 4813`, `candidate_count == 4813`, `database_version == "3.2.0"`.

## 20. Performance
Bench (`tools/bench_search.py`) on the final 4,813-song DB — all queries hit; second run (less machine contention):

| Kind | Query | Service ms | Engine ms | Hits |
|---|---|---:|---:|---:|
| exact title | Way Maker | 164.4 | 147.9 | 30 |
| artist | Nathaniel Bassey | 69.6 | 55.0 | 30 |
| lyric fragment | That saved a wretch like me | 162.7 | 125.7 | 30 |
| typo | amzing grace | 838.6 | 104.8 | 30 |
| artist | Sinach | 249.4 | 63.8 | 6 |
| metadata-only | Too Faithful | 521.0 | 79.1 | 30 |

No algorithmic regression: engine latencies 55–148 ms typical (fuzzy/FTS paths unchanged); service overhead is candidate fetching over 30% more songs. The shared machine (multiple OpenCode/Chrome processes) caused one contended run (up to ~2.3 s); a clean re-run is shown above. 6 result pages as before.

## 21. Memory
`MEMORY OK`: process RSS 24.3 MB baseline → 104.1 MB after pass 1 → **106.2 MB** after pass 2 (+2.1 MB for +1,131 songs) — no leak.

## 22. Packaging & distribution
- `python -m PyInstaller --clean --noconfirm lyricsync.spec` → **build complete** (single rebuild at task end).
- Packaged DB `_internal\data\lyric_sync_gospel.lsdb`: **byte-identical to production** (SHA-256 hash match, 36,433,920 bytes); packaged engine contains the fix (`search_engine.py:378`).
- `--self-check`: **exit 0**, `songs: 4813; top: Way Maker; result: OK`, resolves packaged DB + engine.
- `smoke_ui.py`: **SMOKE OK** — 4,813 songs, 57,135 lyric lines, 6 pages, results openable.

## 23. Files created & modified
**Created**
- `data/ng_expansion/bidemi_olaoba.json`, `festizie.json`, `marizu.json`, `midnight_crew.json`, `mike_abdul.json`, `mr_m_revelation.json`, `neeja.json`, `sammie_okposo.json`, `samsong.json`, `testimony_jaga.json` (batch-4 catalogs, 1,161 entries).
- `data/ng_expansion/` core-6 catalogs + `duplicate_report.txt` + `expansion_report.txt` (regenerated by the importer; earlier this task).
- `data/backups/lyric_sync_gospel_v3.1.0_7faac476.lsdb` (pre-pass-2 rollback).
- `tests/test_production_lsdb.py` additions: `test_nigerian_catalog_searches_surface_target_artist`, `test_expanded_catalog_artist_searches` (25 params), `test_fuzzy_artist_search_reaches_expanded_catalog`.
- `FINAL_REPORT_3.2.0.md` (this file).

**Modified**
- `lyric_sync_gospel.lsdb` — production data (passes 1+2, enrichment, casing fixes, checksum).
- `search_engine.py` — one-line tie-break sort fix (line 378).
- `tools/expand_ng_catalog.py` — +10 catalog entries, `artist_credit` loader, URL/fkey dedup, enrichment pass, version 3.2.0, manifest & extended smoke checks.
- `tests/test_production_lsdb.py` — counts 4,813 / version 3.2.0 expectations.
- `dist/` — rebuilt package.

**Deleted (temp, outside project):** all QA/audit scripts in `%TEMP%\opencode\` (audit, QC, rank/credit/mojibake/casing/dedup/memcheck/verify scripts, self-check logs) — project tree clean of debug code.

## 24. Backups & rollback
- `data/backups/lyric_sync_gospel_v3.0.0_407265ee.lsdb` — pre-task (3,044 songs, 33,972,224 bytes).
- `data/backups/lyric_sync_gospel_v3.1.0_7faac476.lsdb` — pre-pass-2 (3,682 songs, 34,897,920 bytes).
- Rollback = stop app, copy a backup over `lyric_sync_gospel.lsdb`, redeploy the matching `dist/`.

## 25. Remaining work & manual steps
**Manual steps required now: none** — package rebuilt, validated, self-checked, and smoke-tested.

Remaining/follow-up work:
1. **Catalog research for the 50 unexpanded artists** (§5) when authorized — import via the same `tools/expand_ng_catalog.py` flow (dry-run → review → `--commit`).
2. **Lyrics for the 1,827 METADATA_ONLY songs** only if a licensed/authorized source is provided — currently 0 FULL_LYRICS by design (§11).
3. Optional: stale `data/lyric_sync_gospel_next.report.json` (references an older, deleted build) can be removed; it predates this pass.
4. Bench numbers should be re-sampled on an idle machine for publication-grade figures (§20 notes contention).
