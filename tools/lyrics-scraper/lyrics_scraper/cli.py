"""Command line interface.

Usage::

    python -m lyrics_scraper single  https://opengospellyrics.com/...
    python -m lyrics_scraper crawl   https://opengospellyrics.com/sitemap.xml
    python -m lyrics_scraper validate
    python -m lyrics_scraper dedupe
    python -m lyrics_scraper export --out output/exports/opengospellyrics.lsdb
    python -m lyrics_scraper stats
    python -m lyrics_scraper review <song_id> --approve --include-lyrics

The only file this package ever writes is the staging database (plus the raw
cache and an export file the operator names explicitly).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import UnsupportedSource, available_sources
from .dedupe import MERGE, decide
from .engine import ScraperEngine
from .fetch import FetchError, Fetcher
from .staging import StagingDatabase
from .validate import severity_rank, validate_song

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PACKAGE_ROOT / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lyrics_scraper",
        description="Gospel lyrics database builder (staging only) — "
                    "sources: " + ", ".join(available_sources()),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT),
                        help="raw cache, staging database and exports root")
    parser.add_argument("--source", default="auto",
                        choices=["auto", *available_sources()],
                        help="source adapter; auto detects from the domain")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds between HTTP requests")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--cache-only", action="store_true",
                        help="never hit the network; use output/raw only")
    parser.add_argument("--ignore-robots", action="store_true")

    sub = parser.add_subparsers(
        dest="command",
        help="command to run (default: ui — the desktop interface)")

    for name, help_text in (
        ("single", "parse one URL (any page type)"),
        ("article", "parse one URL, forcing article detection"),
        ("category", "parse a category listing and ingest each post"),
        ("crawl", "start from a sitemap/section page and follow links"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("url")
        command.add_argument("--limit", type=int, default=0,
                             help="maximum pages to fetch (0 = no limit)")
        command.add_argument("--depth", type=int, default=1,
                             help="link follow depth for category/crawl")
        command.add_argument("--resume", action="store_true",
                             help="skip URLs this staging database has already "
                                  "fetched, so an interrupted crawl continues")

    sub.add_parser("validate", help="re-run validation over staged songs")
    sub.add_parser("dedupe", help="re-run duplicate detection over staging")

    command = sub.add_parser("export", help="write a production-format .lsdb")
    command.add_argument("--out", required=True)
    command.add_argument("--version", default="1.0.0")
    command.add_argument("--include-lyrics", action="store_true",
                         help="export lyrics only for songs explicitly "
                              "resolved in staging (include_lyrics=1)")
    command.add_argument("--include-flagged", action="store_true")
    command.add_argument("--overwrite", action="store_true")

    sub.add_parser("stats", help="staging statistics")
    sub.add_parser("coverage", help="per-source yield: staged, flagged, "
                                    "lyrics-ready, public domain")

    command = sub.add_parser("review", help="update a song's review state")
    command.add_argument("song_id", nargs="?", default="",
                         help="staged song id (omit with --all)")
    command.add_argument("--all", action="store_true",
                         help="apply to every staged song (narrow it with "
                              "--source)")
    command.add_argument("--approve", action="store_true")
    command.add_argument("--reject", action="store_true")
    command.add_argument("--flag", action="store_true")
    command.add_argument("--include-lyrics", action="store_true")
    command.add_argument("--no-lyrics", action="store_true")
    command.add_argument("--copyright-status",
                         choices=["PUBLIC_DOMAIN", "AUTHORIZED", "LICENSED",
                                  "USER_IMPORTED", "METADATA_ONLY", "UNKNOWN"])

    command = sub.add_parser("list", help="list staged songs")
    command.add_argument("--flagged-only", action="store_true")
    command.add_argument("--limit", type=int, default=50)

    sub.add_parser("ui", help="launch the desktop interface (Tkinter)")
    return parser


def _paths(args) -> tuple[Path, Path, Path]:
    root = Path(args.output_dir)
    return root / "raw", root / "staging" / "staging.sqlite", root / "exports"


def _fetcher(args) -> Fetcher:
    raw_dir, _staging, _exports = _paths(args)
    return Fetcher(
        cache_dir=raw_dir,
        delay=args.delay,
        timeout=args.timeout,
        ignore_robots=args.ignore_robots,
        cache_only=args.cache_only,
    )


def command_stats(staging: StagingDatabase) -> None:
    for key, value in staging.counts().items():
        print(f"  {key:<16}: {value}")


def command_validate(staging: StagingDatabase, run_id: str) -> None:
    # self-heal databases written by older builds: link orphan page warnings
    # to their song, correct severities that were too harsh, and drop
    # byte-for-byte repeat rows
    corrected = staging.normalize_warning_severities()
    repaired = staging.repair_warning_links()
    pruned = staging.prune_duplicate_warnings()
    rows = staging.connection.execute(
        "SELECT song_id, title, source_url FROM songs"
    ).fetchall()
    flagged = 0
    added = 0
    for row in rows:
        song = _load_song_draft(staging, row["song_id"])
        if song is None:
            continue
        found = validate_song(song)
        if found:
            flagged += 1
            status = severity_rank(found)
            staging.connection.execute(
                "UPDATE songs SET review_status = CASE WHEN ? = 'flagged' "
                "THEN 'flagged' ELSE review_status END WHERE song_id = ?",
                (status, row["song_id"]),
            )
            for warning in found:
                if staging.has_warning(row["song_id"], warning):
                    continue
                staging.add_warning(warning, run_id=run_id,
                                    song_id=row["song_id"])
                added += 1
        staging.recount_warnings(row["song_id"])
    staging.commit()
    print(f"  re-validated {len(rows)} song(s); {flagged} flagged; "
          f"{added} new warning row(s); corrected {corrected}, "
          f"linked {repaired}, pruned {pruned} duplicate(s)")


def command_dedupe(staging: StagingDatabase) -> None:
    index = staging.index()
    rows = staging.connection.execute(
        "SELECT song_id FROM songs ORDER BY created_at"
    ).fetchall()
    merged = 0
    for row in rows:
        song = _load_song_draft(staging, row["song_id"])
        if song is None:
            continue
        decision = decide(song, index)
        if decision.action == MERGE and decision.existing_song_id != row["song_id"]:
            staging.add_existing_song_source(decision.existing_song_id, song)
            staging.connection.execute(
                "DELETE FROM song_sections WHERE song_id = ?",
                (row["song_id"],),
            )
            staging.connection.execute(
                "DELETE FROM songs WHERE song_id = ?", (row["song_id"],)
            )
            merged += 1
        elif decision.warnings:
            staging.connection.execute(
                "UPDATE songs SET review_status = 'flagged' WHERE song_id = ?",
                (row["song_id"],),
            )
            for warning in decision.warnings:
                if staging.has_warning(row["song_id"], warning):
                    continue
                staging.add_warning(warning, song_id=row["song_id"])
            staging.recount_warnings(row["song_id"])
    staging.commit()
    print(f"  scanned {len(rows)} song(s); {merged} duplicate row(s) merged")


def _load_song_draft(staging: StagingDatabase, song_id: str):
    """Rebuild a staged song (sections, markers, metadata) for re-validation."""
    from .models import LyricSection, NormalizedSong

    row = staging.connection.execute(
        "SELECT * FROM songs WHERE song_id = ?", (song_id,)
    ).fetchone()
    if row is None:
        return None

    def as_list(value) -> list:
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []

    lines = staging.connection.execute(
        "SELECT section_order, section_label, section_type, display_label, "
        "line_order, line_text, line_raw, line_repeat, line_repeat_unknown, "
        "line_is_marker, marker, marker_target, translation "
        "FROM song_sections WHERE song_id = ? "
        "ORDER BY section_order, line_order",
        (song_id,),
    ).fetchall()

    sections: dict[int, LyricSection] = {}
    for line in lines:
        order = line["section_order"]
        section = sections.get(order)
        if section is None:
            section = LyricSection(
                label=line["section_label"],
                section_type=line["section_type"],
                display_label=line["display_label"],
            )
            sections[order] = section
        section.append(
            "" if line["line_is_marker"] else line["line_text"],
            raw=line["line_raw"] or line["line_text"],
            repeat=line["line_repeat"] or 1,
            repeat_unknown=bool(line["line_repeat_unknown"]),
            marker=line["marker"] or "",
            target=line["marker_target"] or "",
            translation=line["translation"] or "",
        )

    artists = as_list(row["artists"]) or [row["artist"]]
    return NormalizedSong(
        title=row["title"],
        artists=artists,
        featured_artists=as_list(row["featured_artists"]),
        source_site=row["source_site"] or "",
        source_domain=row["source_domain"] or "",
        source_adapter=row["source_adapter"] or "",
        source_name=row["source_name"] or "",
        source_url=row["source_url"],
        article_url=row["article_url"],
        page_id=row["page_id"] or "",
        article_date=row["article_date"],
        author=row["author"], year=row["year"],
        languages=as_list(row["languages"]),
        language_confidence=row["language_confidence"] or "unknown",
        countries=as_list(row["countries"]),
        language=row["language"],
        copyright_status=row["copyright_status"] or "UNKNOWN",
        key_name=row["key_name"], chords=row["chords"],
        category=row["category"], tags=as_list(row["tags"]),
        taxonomy={},
        raw_text=row["raw_text"],
        sections=[sections[order] for order in sorted(sections)],
    )


def command_review(staging: StagingDatabase, args) -> None:
    rows = _review_targets(staging, args)
    if not rows:
        raise SystemExit("no songs matched — nothing to update")
    for song_id in rows:
        _apply_review(staging, song_id, args)
    staging.commit()
    print(f"  updated {len(rows)} song(s)")


def _review_targets(staging: StagingDatabase, args) -> list[str]:
    """Song ids a review command should touch (one, or a whole source)."""
    if not getattr(args, "all", False):
        row = staging.connection.execute(
            "SELECT song_id FROM songs WHERE song_id = ?", (args.song_id,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"song not found: {args.song_id}")
        return [row["song_id"]]
    query = "SELECT song_id FROM songs"
    params: tuple = ()
    source = (getattr(args, "source", "") or "").strip().lower()
    if source and source not in ("auto", "detect"):
        from .adapters import get_adapter

        adapter = get_adapter(source)
        query += (" WHERE source_domain = ? OR source_site = ? "
                  "OR source_adapter = ?")
        params = (adapter.domain, adapter.site, adapter.adapter_name)
    query += " ORDER BY song_id"
    return [row["song_id"] for row in
            staging.connection.execute(query, params)]


def _apply_review(staging: StagingDatabase, song_id: str, args) -> None:
    if args.approve:
        staging.connection.execute(
            "UPDATE songs SET review_status = 'approved' WHERE song_id = ?",
            (song_id,))
    elif args.reject:
        staging.connection.execute(
            "UPDATE songs SET review_status = 'rejected' WHERE song_id = ?",
            (song_id,))
    elif args.flag:
        staging.connection.execute(
            "UPDATE songs SET review_status = 'flagged' WHERE song_id = ?",
            (song_id,))
    if args.include_lyrics:
        staging.connection.execute(
            "UPDATE songs SET include_lyrics = 1 WHERE song_id = ?",
            (song_id,))
    elif args.no_lyrics:
        staging.connection.execute(
            "UPDATE songs SET include_lyrics = 0 WHERE song_id = ?",
            (song_id,))
    if args.copyright_status:
        staging.connection.execute(
            "UPDATE songs SET copyright_status = ? WHERE song_id = ?",
            (args.copyright_status, song_id))


def command_coverage(staging: StagingDatabase) -> None:
    """Yield per source, so an operator can see what a crawl actually got."""
    rows = staging.connection.execute(
        "SELECT COALESCE(NULLIF(source_site, ''), source_domain) AS source, "
        "COUNT(*) AS songs, "
        "SUM(review_status = 'approved') AS approved, "
        "SUM(review_status = 'clean') AS clean, "
        "SUM(review_status = 'flagged') AS flagged, "
        "SUM(review_status = 'rejected') AS rejected, "
        "SUM(include_lyrics) AS lyrics_ready, "
        "SUM(copyright_status = 'PUBLIC_DOMAIN') AS public_domain, "
        "SUM(copyright_status = 'METADATA_ONLY') AS meta_only, "
        "SUM(warning_count > 0) AS with_warnings, "
        "COALESCE(SUM(line_count), 0) AS lines "
        "FROM songs GROUP BY source ORDER BY songs DESC"
    ).fetchall()
    if not rows:
        print("  staging is empty — run a fetch first")
        return
    header = (f"  {'source':<22} {'songs':>6} {'appr':>5} {'cln':>4} "
              f"{'flg':>4} {'rdy':>5} {'pd':>5} {'warn':>5} {'lines':>7}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        print(f"  {row['source'][:22]:<22} {row['songs']:>6} "
              f"{row['approved'] or 0:>5} {row['clean'] or 0:>4} "
              f"{row['flagged'] or 0:>4} {row['lyrics_ready'] or 0:>5} "
              f"{row['public_domain'] or 0:>5} {row['with_warnings'] or 0:>5} "
              f"{row['lines'] or 0:>7}")
    totals = staging.connection.execute(
        "SELECT COUNT(*) AS songs, SUM(include_lyrics) AS ready, "
        "SUM(line_count) AS lines FROM songs").fetchone()
    print(f"  {'TOTAL':<22} {totals['songs']:>6} "
          f"{'':>5} {'':>4} {'':>4} {totals['ready'] or 0:>5} "
          f"{'':>5} {'':>5} {totals['lines'] or 0:>7}")


def command_list(staging: StagingDatabase, args) -> None:
    query = ("SELECT song_id, title, artist, review_status, include_lyrics, "
             "copyright_status, line_count FROM songs")
    if args.flagged_only:
        query += " WHERE review_status = 'flagged'"
    query += " ORDER BY song_id LIMIT ?"
    for row in staging.connection.execute(query, (args.limit,)):
        print(f"  {row['song_id']:<46} {row['review_status']:<8} "
              f"lyrics={row['include_lyrics']} {row['copyright_status']:<14} "
              f"lines={row['line_count']:<4} {row['title'][:40]}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _raw, staging_path, exports_dir = _paths(args)

    if not args.command:
        # Bare `python -m lyrics_scraper` opens the desktop interface.
        print("No command given — launching the desktop interface "
              "(use --help for the CLI).", flush=True)
        args.command = "ui"

    if args.command == "ui":
        try:
            from .ui import launch
        except ImportError as exc:
            raise SystemExit(
                f"GUI unavailable ({exc}) — use the command line instead: "
                "lyrics-scraper --help")
        return launch(
            output_dir=args.output_dir, source=args.source,
            delay=args.delay, timeout=args.timeout,
            cache_only=args.cache_only, ignore_robots=args.ignore_robots)

    if args.command in ("validate", "dedupe", "stats", "review", "list",
                        "coverage"):
        if not staging_path.exists():
            raise SystemExit(f"staging database not found: {staging_path}")
        with StagingDatabase(staging_path) as staging:
            if args.command == "stats":
                command_stats(staging)
            elif args.command == "coverage":
                command_coverage(staging)
            elif args.command == "validate":
                command_validate(staging, staging.start_run("validate"))
            elif args.command == "dedupe":
                command_dedupe(staging)
            elif args.command == "review":
                command_review(staging, args)
            elif args.command == "list":
                command_list(staging, args)
        return 0

    if args.command == "export":
        from .export import ExportError, export_staging

        prod_path = PACKAGE_ROOT.parent.parent / "lyric_sync_gospel.lsdb"
        exports_dir.mkdir(parents=True, exist_ok=True)
        try:
            summary = export_staging(
                staging_path,
                args.out,
                prod_path=prod_path,
                version=args.version,
                include_lyrics=args.include_lyrics,
                include_flagged=args.include_flagged,
                overwrite=args.overwrite,
            )
        except ExportError as exc:
            raise SystemExit(f"export refused: {exc}")
        for key, value in summary.items():
            print(f"  {key:<18}: {value}")
        return 0

    # fetch / parse commands — resolve the source FIRST so an unsupported URL
    # fails before staging is created or a run row is written
    from .adapters import adapter_for as resolve_adapter

    try:
        resolve_adapter(args.url, args.source)
    except UnsupportedSource as exc:
        raise SystemExit(str(exc))

    fetcher = _fetcher(args)
    page_type = "article" if args.command == "article" else ""
    depth = 0 if args.command in ("single", "article") else args.depth
    with StagingDatabase(staging_path) as staging:
        engine = ScraperEngine(fetcher=fetcher, staging=staging,
                               source=args.source)
        run_id = staging.start_run(
            args.url, f"command={args.command} source={args.source}")
        already: set[str] = set()
        if getattr(args, "resume", False):
            already = {row["url"] for row in staging.connection.execute(
                "SELECT DISTINCT url FROM pages")}
        try:
            stats = engine.ingest(args.url, run_id=run_id,
                                  limit=args.limit, depth=depth,
                                  page_type=page_type, seen=already)
        except UnsupportedSource as exc:
            raise SystemExit(f"{exc}")
        except FetchError as exc:
            raise SystemExit(f"fetch failed: {exc}")
        staging.finish_run(
            run_id, pages_requested=stats["pages"],
            pages_successful=stats["pages"], songs_found=stats["songs"],
            songs_imported=stats["insert"] + stats["flagged"],
            duplicates=stats["merge"], warnings=stats["warnings"],
            errors=stats["failed"],
        )
    print(f"\n  pages={stats['pages']} skipped={stats.get('skipped', 0)} "
          f"songs={stats['songs']} staged={stats['insert']} "
          f"merged={stats['merge']} flagged={stats['flagged']} "
          f"ready={stats.get('ready', 0)} warnings={stats['warnings']} "
          f"failed={stats['failed']}")
    print(f"  source adapter(s): {stats.get('sources') or args.source}")
    print(f"  staging: {staging_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
