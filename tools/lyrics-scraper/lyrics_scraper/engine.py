"""ScraperEngine — the fetch → parse → validate → dedupe → stage pipeline.

Site knowledge lives in adapters; this engine only orchestrates:

    website → adapter → NormalizedSong → validation → dedup → staging
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .adapters import SourceAdapter, UnsupportedSource, adapter_for
from .dedupe import INSERT_FLAGGED, MERGE, apply_insert, decide
from .fetch import FetchError, Fetcher, site_origin
from .models import ParseResult, RawPage
from .staging import StagingDatabase
from .validate import severity_rank, validate_song


@dataclass
class ScraperEngine:
    """Runs one or more source adapters against live or cached pages."""

    fetcher: Fetcher
    staging: StagingDatabase
    source: str = "auto"
    _adapter_cache: dict[str, SourceAdapter] = field(default_factory=dict)

    # -- adapters ----------------------------------------------------------
    def adapter_for(self, url: str) -> SourceAdapter:
        cached = self._adapter_cache.get(url)
        if cached is None:
            cached = adapter_for(url, self.source)
            self._adapter_cache[url] = cached
        return cached

    # -- single page -------------------------------------------------------
    def fetch(self, url: str) -> RawPage:
        return self.fetcher.fetch(url)

    def parse(self, page: RawPage, *, page_type: str = "") -> tuple[
            SourceAdapter, ParseResult]:
        adapter = self.adapter_for(page.final_url or page.url)
        return adapter, adapter.parse(page, page_type=page_type)

    def stage(self, result: ParseResult, adapter: SourceAdapter, *,
              run_id: str, page: RawPage) -> dict:
        """Validate, deduplicate and write one parsed page to staging."""
        stats = {"songs": len(result.songs), "insert": 0, "flagged": 0,
                 "merge": 0, "warnings": 0, "ready": 0}
        self.staging.record_page(page, run_id)
        self.staging.update_page(page.page_id, result.page_type,
                                 result.article_title)
        # Page-level warnings cannot name a song yet: the songs of this page
        # are staged below and the rows are linked to them afterwards.
        for warning in result.warnings:
            self.staging.add_warning(warning, run_id=run_id,
                                     page_id=page.page_id)
            stats["warnings"] += 1

        index = self.staging.index()
        touched: list[str] = []
        title_to_song: dict[str, str] = {}
        for song in result.songs:
            found = validate_song(song)
            decision = decide(song, index)
            warnings = found + decision.warnings
            status = severity_rank(warnings)
            if decision.action == MERGE:
                self.staging.add_existing_song_source(
                    decision.existing_song_id, song)
                song_id = decision.existing_song_id
                stats["merge"] += 1
            else:
                # Public-domain texts (Project Gutenberg) that survive
                # validation are ready to export straight away; anything
                # questionable still waits for a human.
                ready = (song.copyright_status == "PUBLIC_DOMAIN"
                         and status == "clean")
                song_id = self.staging.insert_song(
                    song, run_id,
                    review_status="approved" if ready else status,
                    warning_count=len(warnings),
                    include_lyrics=ready,
                )
                apply_insert(index, song, song_id)
                stats["insert"] += 1
                if ready:
                    stats["ready"] += 1
                if decision.action == INSERT_FLAGGED or status == "flagged":
                    stats["flagged"] += 1
            for warning in warnings:
                if self.staging.has_warning(song_id, warning):
                    continue
                self.staging.add_warning(warning, run_id=run_id,
                                         page_id=page.page_id,
                                         song_id=song_id)
                stats["warnings"] += 1
            touched.append(song_id)
            title_to_song[song.title] = song_id

        self.staging.link_page_warnings(page.page_id, title_to_song)
        for song_id in touched:
            self.staging.recount_warnings(song_id)
        self.staging.commit()
        return stats

    # -- crawl -------------------------------------------------------------
    def ingest(self, start_url: str, *, run_id: str, limit: int = 0,
               depth: int = 1, page_type: str = "",
               seen: set[str] | None = None) -> dict:
        """Fetch, parse and stage ``start_url`` (and links when depth > 0).

        ``seen`` pre-loads URLs already handled by an earlier interrupted run,
        so re-issuing the same crawl resumes instead of starting over.
        """
        origin = site_origin(start_url)
        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        visited: set[str] = set(seen or ())
        totals = {"pages": 0, "failed": 0, "songs": 0, "insert": 0,
                  "flagged": 0, "merge": 0, "warnings": 0, "errors": 0,
                  "ready": 0, "skipped": 0}
        sources: set[str] = set()

        while queue:
            url, level = queue.popleft()
            if url in visited:
                totals["skipped"] += 1
                continue
            if limit and totals["pages"] >= limit:
                break
            try:
                adapter = self.adapter_for(url)
            except UnsupportedSource as exc:
                if url == start_url:
                    raise
                totals["failed"] += 1
                print(f"  !! {exc}")
                continue
            if site_origin(url) != origin:
                continue
            visited.add(url)
            try:
                page = self.fetcher.fetch(url)
            except FetchError as exc:
                totals["failed"] += 1
                print(f"  !! fetch failed: {exc}")
                continue

            totals["pages"] += 1
            sources.add(adapter.name)
            result = adapter.parse(page, page_type=page_type)
            self.staging.update_run_field(run_id,
                                          pages_requested=totals["pages"])
            page_stats = self.stage(result, adapter, run_id=run_id, page=page)
            for key in ("songs", "insert", "flagged", "merge", "warnings",
                        "ready"):
                totals[key] += page_stats.get(key, 0)

            if not result.songs and result.page_type in (
                    "article", "single", "single-song"):
                print(f"  -- no songs found on {url}")

            if level < depth and result.links:
                allow_xml = result.page_type == "sitemap"
                for link in result.links:
                    if site_origin(link) != origin or link in visited:
                        continue
                    if not allow_xml and not adapter.allows_link(link):
                        continue
                    queue.append((link, level + 1))

            print(f"  [{totals['pages']:>3}] {result.page_type:<9} "
                  f"songs={len(result.songs):<4} {adapter.name:<19} {url}")

        totals["sources"] = ",".join(sorted(sources))
        return totals


__all__ = ["ScraperEngine"]
