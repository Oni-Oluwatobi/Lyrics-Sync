"""Local search engine: retrieve, rank and package matching songs.

``LyricSearchEngine`` never touches the network and never loads the whole
database into memory. Retrieval is bounded; ranking runs on the small candidate
set; all database work happens on the calling (background) thread.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

from lyric_sync.database.lsdb_manager import LSDBManager
from lyric_sync.models.search_result import SearchResult
from lyric_sync.search import ranker
from lyric_sync.search.query_normalizer import (
    NormalizedQuery,
    like_pattern,
    normalize_query,
    normalize_text,
)

# Retrieval budget: keeps large databases responsive on modest hardware.
PHRASE_FTS_LIMIT = 60
OR_FTS_LIMIT = 120
LYRIC_TERM_LIMIT = 4000
METADATA_LIMIT = 300
DEFAULT_CANDIDATE_LIMIT = 250
DEFAULT_RESULT_LIMIT = 50
FUZZY_SCAN_LINE_BUDGET = 60000
FUZZY_SCAN_BATCH = 1000
FUZZY_TOKEN_MIN_LENGTH = 4
MAX_QUERY_TERMS = 8


@dataclass
class SearchResponse:
    """Everything the UI needs for one query."""

    query: NormalizedQuery
    results: list[SearchResult] = field(default_factory=list)
    elapsed_ms: float = 0.0
    candidate_count: int = 0
    truncated: bool = False
    database_available: bool = True
    note: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.results


class LyricSearchEngine:
    """Searches the local ``.LSDB`` for remembered lyrics."""

    def __init__(
        self,
        manager: LSDBManager | None = None,
        *,
        sensitivity: str = "balanced",
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        result_limit: int = DEFAULT_RESULT_LIMIT,
    ) -> None:
        self.manager = manager
        self.sensitivity = sensitivity
        self.candidate_limit = candidate_limit
        self.result_limit = result_limit

    # ------------------------------------------------------------- lifecycle

    def attach(self, manager: LSDBManager | None) -> None:
        self.manager = manager

    @property
    def available(self) -> bool:
        return self.manager is not None and self.manager.is_open

    # ------------------------------------------------------------------ search

    def search(self, raw_query: str) -> SearchResponse:
        started = time.perf_counter()
        query = normalize_query(raw_query)
        if query.is_empty:
            return SearchResponse(
                query=query,
                elapsed_ms=0.0,
                database_available=self.available,
                note=None if self.available else "database_unavailable",
            )
        if not self.available or self.manager is None:
            return SearchResponse(
                query=query,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                database_available=False,
                note="database_unavailable",
            )

        manager = self.manager
        sources = self._retrieve(manager, query)

        ordered_ids = list(sources.keys())[: self.candidate_limit]
        if not ordered_ids:
            return SearchResponse(
                query=query,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                candidate_count=0,
                database_available=True,
            )

        records = manager.get_records(ordered_ids)
        ranked: list[ranker.RankedMatch] = []
        for record in records:
            match = ranker.rank_record(
                query,
                record,
                retrieval_sources=sources.get(record.song.id, ()),
                sensitivity=self.sensitivity,
            )
            if match is not None:
                ranked.append(match)

        ranked.sort(key=lambda item: (-item.score, item.record.song.title.lower()))

        truncated = len(ranked) > self.result_limit
        top = ranked[: self.result_limit]
        results = [
            SearchResult(
                song=match.record.song,
                score=round(match.score, 4),
                label=match.label,
                snippet=match.snippet,
                highlights=match.highlights,
                context_before=match.context_before,
                context_after=match.context_after,
                matched_fields=match.matched_fields,
                fuzzy_terms=match.fuzzy_terms,
            )
            for match in top
        ]
        return SearchResponse(
            query=query,
            results=results,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(sources),
            truncated=truncated,
            database_available=True,
        )

    # ------------------------------------------------------------- retrieval

    def _retrieve(self, manager: LSDBManager, query: NormalizedQuery) -> dict[int, tuple[str, ...]]:
        """Return an ordered ``{song_id: sources}`` candidate map."""
        candidates: dict[int, set[str]] = {}
        terms = list(query.tokens)[:MAX_QUERY_TERMS]
        patterns = [like_pattern(term) for term in terms]
        phrase_pattern = like_pattern(query.normalized)
        content_terms = list(query.content)[:MAX_QUERY_TERMS]
        content_patterns = [like_pattern(term) for term in content_terms]

        def add(ids: Sequence[int], source: str, limit: int | None = None) -> None:
            added = 0
            for song_id in ids:
                bucket = candidates.setdefault(int(song_id), set())
                if source not in bucket:
                    bucket.add(source)
                added += 1
                if limit is not None and added >= limit:
                    break

        # 1. exact phrase (highest priority)
        fts_tables = list(manager.schema.fts_tables)
        if fts_tables:
            phrase_query = " ".join(terms)
            for fts in fts_tables:
                ids = self._fts_ids(manager, fts.name, f'"{phrase_query}"', PHRASE_FTS_LIMIT)
                add(self._resolve_fts_ids(manager, fts, ids), "phrase")

        add(manager.song_ids_matching_all([phrase_pattern], columns=["title"],
                                          limit=METADATA_LIMIT), "phrase")
        add(manager.song_ids_matching_all([phrase_pattern], columns=["artist"],
                                          limit=METADATA_LIMIT), "phrase")

        # 2. metadata: every term must appear in title/artist (any order)
        if patterns:
            metadata_columns = ["title"]
            if manager.schema.song_fields.get("artist"):
                metadata_columns.append("artist")
            add(
                manager.song_ids_matching_all(
                    patterns, columns=metadata_columns, limit=METADATA_LIMIT
                ),
                "metadata",
            )
            alias_column = manager.schema.song_fields.get("aliases")
            if alias_column:
                add(
                    manager.song_ids_matching_all(
                        patterns, columns=[alias_column], limit=METADATA_LIMIT
                    ),
                    "metadata",
                )

            # alias table: every term must appear somewhere in an alias
            if manager.schema.has_aliases:
                alias_hits: set[int] | None = None
                for pattern in patterns:
                    hits = set(
                        manager.song_ids_matching_alias(pattern, limit=METADATA_LIMIT)
                    )
                    alias_hits = hits if alias_hits is None else (alias_hits & hits)
                    if not alias_hits:
                        break
                if alias_hits:
                    add(sorted(alias_hits), "metadata")

        # 3. full-text index (prefix on the final term helps while typing)
        if fts_tables:
            or_query = self._or_query(terms)
            for fts in fts_tables:
                ids = self._fts_ids(manager, fts.name, or_query, OR_FTS_LIMIT)
                add(self._resolve_fts_ids(manager, fts, ids), "fts")

        # 4. lyric lines: intersect per-term matches
        lyric_hits: set[int] | None = None
        for pattern in (content_patterns or patterns):
            hits = set(manager.song_ids_matching_lyrics(pattern, limit=LYRIC_TERM_LIMIT))
            lyric_hits = hits if lyric_hits is None else (lyric_hits & hits)
            if not lyric_hits:
                break
        if lyric_hits:
            add(sorted(lyric_hits)[:LYRIC_TERM_LIMIT], "lyrics")

        # 5. fuzzy rescue for short/tolerant queries
        if len(candidates) < 3:
            add(self._fuzzy_metadata_ids(manager, query), "fuzzy")
            add(self._fuzzy_lyric_ids(manager, query), "fuzzy")

        return {song_id: tuple(sorted(sources)) for song_id, sources in candidates.items()}

    @staticmethod
    def _or_query(terms: Sequence[str]) -> str:
        if not terms:
            return ""
        parts = []
        for index, term in enumerate(terms):
            if index == len(terms) - 1 and len(term) >= 3:
                parts.append(f"{term}*")
            else:
                parts.append(term)
        return " OR ".join(parts)

    @staticmethod
    def _fts_ids(manager: LSDBManager, table: str, match_query: str, limit: int) -> list[int]:
        if not match_query:
            return []
        return [song_id for song_id, _ in manager.fts_match(table, match_query, limit)]

    @staticmethod
    def _resolve_fts_ids(manager: LSDBManager, fts, ids: Sequence[int]) -> list[int]:
        """FTS rowids are assumed to be song ids; lyric indexes may use line ids."""
        if not ids:
            return []
        existing = set(manager.get_songs(ids).keys())
        resolved = [i for i in ids if i in existing]
        unresolved = [i for i in ids if i not in existing]
        if unresolved and getattr(fts, "scope", "") == "lyrics":
            mapping = manager.line_ids_to_song_ids(unresolved)
            for line_id, song_id in mapping.items():
                if song_id not in existing:
                    resolved.append(song_id)
                    existing.add(song_id)
        return resolved

    # ------------------------------------------------------------ fuzzy rescue

    @staticmethod
    def _fuzzy_metadata_ids(manager: LSDBManager, query: NormalizedQuery) -> list[int]:
        tokens = [token for token in query.content if len(token) >= 3][:4]
        if not tokens:
            return []
        ids: list[int] = []
        try:
            rows = manager.song_titles_sample(limit=5000)
        except Exception:  # pragma: no cover - defensive
            return []
        for song_id, title, artist in rows:
            haystack = normalize_text(f"{title} {artist}").split()
            if not haystack:
                continue
            hits = sum(1 for token in tokens if _fuzzy_word_hit(token, haystack, 0.78))
            if hits and hits >= max(1, len(tokens) - 1):
                ids.append(song_id)
        return ids

    @staticmethod
    def _fuzzy_lyric_ids(manager: LSDBManager, query: NormalizedQuery) -> list[int]:
        tokens = [token for token in query.content if len(token) >= FUZZY_TOKEN_MIN_LENGTH][:3]
        if not tokens:
            return []
        total_lines = manager.count_lyric_lines_scannable()
        if total_lines <= 0 or total_lines > FUZZY_SCAN_LINE_BUDGET:
            return []
        ids: list[int] = []
        seen: set[int] = set()
        offset = 0
        while offset < total_lines and offset < FUZZY_SCAN_LINE_BUDGET:
            batch = manager.lyric_rows_batch(offset, FUZZY_SCAN_BATCH)
            if not batch:
                break
            for song_id, line in batch:
                words = normalize_text(line).split()
                if not words:
                    continue
                if any(_fuzzy_word_hit(token, words, 0.80) for token in tokens):
                    if song_id not in seen:
                        seen.add(song_id)
                        ids.append(song_id)
                        if len(ids) >= 25:
                            return ids
            offset += FUZZY_SCAN_BATCH
        return ids


def _fuzzy_word_hit(token: str, words: Sequence[str], threshold: float) -> bool:
    """True when any word in ``words`` is close enough to ``token``."""
    if token in words:
        return True
    first = token[0]
    length = len(token)
    for word in words:
        if word[0] != first or abs(len(word) - length) > 1 or len(word) < 3:
            continue
        if SequenceMatcher(None, token, word).ratio() >= threshold:
            return True
    return False
