"""Benchmark representative searches through the production search path.

Usage::

    python tools\\bench_search.py            # wall-clock, 5 runs per query
    python tools\\bench_search.py --profile  # cProfile of the slowest query

Measures the full service path (UI -> LyricSearchService -> downloaded engine)
and the raw engine, so regressions in either layer are visible.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lyric_sync.search.engine_loader import load_engine_module  # noqa: E402
from lyric_sync.search.lyric_search_service import LyricSearchService  # noqa: E402

DATABASE = ROOT / "lyric_sync_gospel.lsdb"

QUERIES = [
    ("exact title", "Way Maker"),
    ("artist", "Nathaniel Bassey"),
    ("lyric fragment", "That saved a wretch like me"),
    ("typo", "amzing grace"),
    ("artist", "Sinach"),
    ("metadata-only song", "Too Faithful"),
]


def bench_service(service: LyricSearchService, runs: int) -> list[tuple[str, str, float, int]]:
    rows = []
    for kind, query in QUERIES:
        times = []
        count = 0
        for _ in range(runs):
            started = time.perf_counter()
            response = service.search(query)
            times.append((time.perf_counter() - started) * 1000)
            count = len(response.results)
        rows.append((kind, query, statistics.median(times), count))
    return rows


def bench_engine(module, runs: int) -> list[tuple[str, str, float, int]]:
    engine = module.LyricSyncSearchEngine(str(DATABASE))
    rows = []
    try:
        for kind, query in QUERIES:
            times = []
            count = 0
            for _ in range(runs):
                started = time.perf_counter()
                results = engine.search(query, limit=30)
                times.append((time.perf_counter() - started) * 1000)
                count = len(results)
            rows.append((kind, query, statistics.median(times), count))
    finally:
        engine.close()
    return rows


def profile_query(service: LyricSearchService, query: str) -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    service.search(query)
    profiler.disable()
    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative")
    stats.print_stats(18)
    print(buffer.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()

    if not DATABASE.is_file():
        print(f"database not found: {DATABASE}")
        return 1

    module = load_engine_module()
    service = LyricSearchService(sensitivity="balanced")
    service.open(DATABASE)
    try:
        service_rows = bench_service(service, args.runs)
        engine_rows = bench_engine(module, args.runs)
    finally:
        service.close()

    print(f"{'kind':<20} {'query':<32} {'service ms':>11} {'engine ms':>11} {'hits':>5}")
    for (kind, query, svc_ms, hits), (_, _, eng_ms, _) in zip(service_rows, engine_rows):
        print(f"{kind:<20} {query:<32} {svc_ms:>11.1f} {eng_ms:>11.1f} {hits:>5}")

    if args.profile:
        slowest = max(service_rows, key=lambda row: row[2])
        print(f"\ncProfile for {slowest[1]!r}")
        service = LyricSearchService(sensitivity="balanced")
        service.open(DATABASE)
        try:
            profile_query(service, slowest[1])
        finally:
            service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
