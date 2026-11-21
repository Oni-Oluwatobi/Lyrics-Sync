"""Application-level search service over the downloaded ``.LSDB`` engine.

Architecture::

    UI  ->  LyricSearchService  ->  search_engine.LyricSyncSearchEngine  ->  lyric_sync_gospel.lsdb

The UI only ever sees :class:`~lyric_sync.models.search_result.SearchResult`,
:class:`~lyric_sync.models.song.Song` and
:class:`~lyric_sync.models.lyric.SongLyrics` — never SQL or ``sqlite3``.

All database work is serialised on one lock, runs on the calling (worker)
thread and is strictly read-only.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Sequence

from lyric_sync.app.dev_log import log_event
from lyric_sync.models.lyric import LyricSection, SongLyrics, normalize_section_type
from lyric_sync.models.search_result import HighlightSpan, MatchLabel, SearchResult
from lyric_sync.models.song import (
    COPYRIGHT_STATUSES,
    LYRICS_AVAILABLE,
    LYRICS_UNAVAILABLE,
    METADATA_ONLY,
    UNVERIFIED,
    VERIFIED,
    Song,
    normalize_status,
)
from lyric_sync.search.engine_loader import (
    SearchEngineUnavailable,
    load_engine_module,
)
from lyric_sync.search.highlighter import find_highlights
from lyric_sync.search.query_normalizer import NormalizedQuery, normalize_query
from lyric_sync.search.search_engine import SearchResponse

CONFIDENCE_LABELS = {
    "High": MatchLabel.STRONG,
    "Medium": MatchLabel.GOOD,
    "Low": MatchLabel.POSSIBLE,
}

# Settings -> which engine confidence tiers are shown and how many are asked for.
SENSITIVITY_LIMITS = {"strict": 20, "balanced": 30, "tolerant": 50}
SENSITIVITY_TIERS = {
    "strict": frozenset({"High", "Medium"}),
    "balanced": frozenset({"High", "Medium", "Low"}),
    "tolerant": frozenset({"High", "Medium", "Low"}),
}

LYRICS_STATUS_AVAILABLE = frozenset(
    {
        "AVAILABLE",
        "LYRICS_AVAILABLE",
        "FULL_LYRICS",
        "PARTIAL_AUTHORIZED",
        "PUBLIC_DOMAIN_TEXT",
    }
)

_ID_CHUNK = 400


class ServiceError(RuntimeError):
    """Base class for errors safe to show in the interface."""

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.user_message = message
        self.detail = detail or message


class DatabaseMissingError(ServiceError):
    pass


class EngineUnavailableError(ServiceError):
    pass


class DatabaseUnreadableError(ServiceError):
    pass


class LyricSearchService:
    """Read-only search façade used by the window."""

    def __init__(self, *, sensitivity: str = "balanced", result_limit: int | None = None) -> None:
        self.sensitivity = sensitivity if sensitivity in SENSITIVITY_LIMITS else "balanced"
        self.result_limit = result_limit
        self._engine = None
        self._path: Path | None = None
        self._tables: frozenset[str] = frozenset()
        self._song_count = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------- lifecycle

    @property
    def available(self) -> bool:
        return self._engine is not None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def song_count(self) -> int:
        return self._song_count

    def open(self, path: Path | str) -> None:
        """Open ``path`` with the downloaded engine. Raises :class:`ServiceError`."""
        target = Path(path)
        if not target.is_file():
            raise DatabaseMissingError(
                "Gospel database not installed",
                detail=f"Expected file: {target}",
            )

        try:
            module = load_engine_module()
        except SearchEngineUnavailable as exc:
            raise EngineUnavailableError(exc.user_message, detail=str(exc)) from exc

        engine_cls = getattr(module, "LyricSyncSearchEngine")
        self.close()
        try:
            engine = engine_cls(str(target))
        except FileNotFoundError as exc:
            raise DatabaseMissingError(
                "Gospel database not installed", detail=str(exc)
            ) from exc
        except ValueError as exc:
            raise DatabaseUnreadableError(
                "The Gospel database could not be read",
                detail=str(exc),
            ) from exc
        except sqlite3.Error as exc:
            raise DatabaseUnreadableError(
                "The Gospel database could not be opened",
                detail=f"{exc.__class__.__name__}: {exc}",
            ) from exc

        try:
            engine.conn.execute("PRAGMA query_only = ON")
            tables = {
                str(row[0])
                for row in engine.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            song_count = int(
                engine.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            )
        except sqlite3.Error as exc:
            engine.close()
            raise DatabaseUnreadableError(
                "The Gospel database structure could not be read",
                detail=f"{exc.__class__.__name__}: {exc}",
            ) from exc

        self._engine = engine
        self._path = target
        self._tables = frozenset(tables)
        self._song_count = song_count

    def close(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
            if engine is not None:
                try:
                    engine.close()
                except Exception:  # noqa: BLE001 - closing must never raise
                    pass
        self._path = None
        self._tables = frozenset()
        self._song_count = 0

    def close_async(self) -> None:
        """Detach immediately and close the connection on a daemon thread.

        The UI thread never waits for the service lock (which an in-flight
        search may hold); the background closer serialises behind it safely.
        In-flight calls keep their own local engine reference, so they finish
        without error.
        """
        engine, self._engine = self._engine, None
        self._path = None
        self._tables = frozenset()
        self._song_count = 0
        if engine is None:
            return
        lock = self._lock

        def closer() -> None:
            with lock:
                try:
                    engine.close()
                except Exception:  # noqa: BLE001 - closing must never raise
                    pass

        threading.Thread(
            target=closer, name="lyric-sync-db-close", daemon=True
        ).start()

    # ---------------------------------------------------------------- search

    def search(
        self,
        raw_query: str,
        limit: int | None = None,
        region_filter: str | None = None,
    ) -> SearchResponse:
        return self.search_lyrics(raw_query, limit=limit, region_filter=region_filter)

    def search_lyrics(
        self,
        query: str,
        limit: int | None = None,
        region_filter: str | None = None,
    ) -> SearchResponse:
        """Search titles, artists, aliases and remembered lyrics."""
        normalized = normalize_query(query)
        if normalized.is_empty:
            return SearchResponse(
                query=normalized,
                database_available=self.available,
                note=None if self.available else "database_unavailable",
            )
        engine = self._engine
        if engine is None:
            return SearchResponse(
                query=normalized,
                database_available=False,
                note="database_unavailable",
            )

        started = time.perf_counter()
        tiers = SENSITIVITY_TIERS[self.sensitivity]
        wanted = limit or self.result_limit or SENSITIVITY_LIMITS[self.sensitivity]
        wanted = max(1, int(wanted))

        try:
            with self._lock:
                raw_results = engine.search(
                    query, limit=wanted, region_filter=region_filter
                )
        except Exception as exc:  # noqa: BLE001 - surfaced through the UI
            detail = f"{exc.__class__.__name__}: {exc}"
            log_event("search", f"query {query!r} failed: {detail}", exc)
            raise ServiceError("The search could not be completed", detail=detail) from exc

        results: list[SearchResult] = []
        for item in raw_results:
            result = self._to_result(item, normalized, tiers)
            if result is not None:
                results.append(result)
        results = _exact_title_first(results, normalized)

        elapsed = (time.perf_counter() - started) * 1000
        return SearchResponse(
            query=normalized,
            results=results,
            elapsed_ms=elapsed,
            candidate_count=self._song_count,
            truncated=len(raw_results) >= wanted,
            database_available=True,
        )

    def _to_result(
        self,
        item: dict,
        normalized: NormalizedQuery,
        tiers: frozenset[str],
    ) -> SearchResult | None:
        confidence = str(item.get("confidence") or "")
        if confidence not in tiers:
            return None
        song_data = item.get("song") or {}
        song = _song_from_row(song_data)
        if song is None:
            return None

        tokens = list(normalized.tokens)
        matched_tokens = tuple(str(token) for token in (item.get("matched_tokens") or ()))
        lyric_lines = [
            str(entry.get("text"))
            for entry in (item.get("lyrics") or [])
            if isinstance(entry, dict) and entry.get("text")
        ]

        snippet, snippet_field = _best_snippet(song, lyric_lines, tokens)
        engine_snippet = str(item.get("matched_snippet") or "").strip()
        if not snippet and _usable_engine_snippet(engine_snippet, normalized, song):
            snippet = engine_snippet
        fields = _matched_fields(normalized, song, snippet_field, matched_tokens)
        score = float(item.get("score") or 0) / 100.0

        return SearchResult(
            song=song,
            score=max(0.0, min(1.0, score)),
            label=CONFIDENCE_LABELS.get(confidence, MatchLabel.POSSIBLE),
            snippet=snippet,
            highlights=_highlights(snippet, tokens),
            matched_fields=fields,
            fuzzy_terms=_fuzzy_terms(matched_tokens, song, lyric_lines),
        )

    # ------------------------------------------------------------- song data

    def get_song(self, song_id: int | str) -> Song | None:
        found = self.get_songs([song_id])
        return found.get(_plain_id(song_id))

    def get_songs(self, ids: Iterable[int | str]) -> dict[int | str, Song]:
        wanted = list(dict.fromkeys(ids))
        engine = self._engine
        if not wanted or engine is None:
            return {}
        songs: dict[int | str, Song] = {}
        with self._lock:
            connection = engine.conn
            for start in range(0, len(wanted), _ID_CHUNK):
                chunk = wanted[start:start + _ID_CHUNK]
                placeholders = ", ".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT * FROM songs WHERE id IN ({placeholders})", tuple(chunk)
                ).fetchall()
                for row in rows:
                    song = _song_from_row(dict(row))
                    if song is not None:
                        songs[song.id] = song
            if "song_aliases" in self._tables:
                for song_id, song in list(songs.items()):
                    extra = connection.execute(
                        "SELECT alias FROM song_aliases WHERE song_id = ?",
                        (song_id,),
                    ).fetchall()
                    aliases = tuple(
                        dict.fromkeys(
                            song.aliases
                            + tuple(str(row[0]).strip() for row in extra if row[0])
                        )
                    )
                    if aliases != song.aliases:
                        songs[song_id] = _with_aliases(song, aliases)
        return songs

    def get_lyrics(self, song_id: int | str) -> SongLyrics:
        safe_id = _safe_id(song_id)
        engine = self._engine
        if engine is None:
            return SongLyrics(song_id=safe_id, available=False)
        with self._lock:
            if "lyric_lines" in self._tables:
                sections = self._legacy_sections(safe_id, engine.conn)
            elif "lyrics" in self._tables:
                sections = self._sections_from_lyrics(safe_id, engine.conn)
            else:
                sections = []
        return SongLyrics(
            song_id=safe_id,
            sections=tuple(sections),
            available=True,
        )

    def _sections_from_lyrics(
        self, song_id: int | str, connection: sqlite3.Connection
    ) -> list[LyricSection]:
        rows = connection.execute(
            "SELECT section_order, section_type, line_order, text FROM lyrics "
            "WHERE song_id = ? ORDER BY section_order, line_order",
            (song_id,),
        ).fetchall()

        buckets: list[list[object]] = []
        for section_order, section_type, _line_order, text in rows:
            if text is None:
                continue
            raw_type = str(section_type or "").strip()
            if not buckets or buckets[-1][3] != (section_order, section_type):
                try:
                    order = int(section_order)
                except (TypeError, ValueError):
                    order = len(buckets) + 1
                buckets.append([order, raw_type, [str(text)], (section_order, section_type)])
            else:
                buckets[-1][2].append(str(text))

        return [
            LyricSection(
                type=normalize_section_type(str(raw_type)),
                index=_trailing_index(str(raw_type)),
                label=str(raw_type),
                lines=tuple(lines),
                order=int(order),
            )
            for order, raw_type, lines, _key in buckets
        ]

    def _legacy_sections(
        self, song_id: int | str, connection: sqlite3.Connection
    ) -> list[LyricSection]:
        meta_rows = connection.execute(
            "SELECT id, section_type, section_index, label FROM lyric_sections "
            "WHERE song_id = ? ORDER BY section_index, id",
            (song_id,),
        ).fetchall()
        line_rows = connection.execute(
            "SELECT section_id, section_type, line_index, text FROM lyric_lines "
            "WHERE song_id = ? ORDER BY section_index, line_index",
            (song_id,),
        ).fetchall()

        meta: dict[object, tuple[str, int, str]] = {}
        order_keys: list[object] = []
        for section_id, section_type, section_index, label in meta_rows:
            raw_type = str(section_type or "").strip()
            meta[section_id] = (
                normalize_section_type(raw_type or str(label or "")),
                _as_int(section_index),
                str(label or ""),
            )
            order_keys.append(section_id)

        buckets: dict[object, list[str]] = {}
        line_order: list[object] = []
        for section_id, section_type, _line_index, text in line_rows:
            if text is None:
                continue
            if section_id not in buckets:
                buckets[section_id] = []
                if section_id not in line_order:
                    line_order.append(section_id)
            buckets[section_id].append(str(text))
            if section_id not in meta:
                raw_type = str(section_type or "").strip()
                meta[section_id] = (normalize_section_type(raw_type), 0, raw_type)

        sections: list[LyricSection] = []
        for position, key in enumerate(line_order, start=1):
            section_type, index, label = meta.get(key, ("VERSE", position, ""))
            sections.append(
                LyricSection(
                    type=section_type,
                    index=index,
                    label=label,
                    lines=tuple(buckets.get(key, ())),
                    order=position,
                )
            )
        return sections

    def database_info(self) -> dict:
        engine = self._engine
        if engine is None:
            return {}
        with self._lock:
            try:
                info = engine.get_database_info()
            except Exception:  # noqa: BLE001 - metadata is optional
                return {}
        return dict(info) if isinstance(info, dict) else {}


# --------------------------------------------------------------------------- #
# row -> model helpers
# --------------------------------------------------------------------------- #


def _exact_title_first(
    results: list[SearchResult], normalized: NormalizedQuery
) -> list[SearchResult]:
    """Within equal engine scores, put exact title matches first.

    The downloaded engine scores many songs identically at the top (e.g.
    "Way Maker" and "Nothing but the Blood of Jesus" both score 100 for that
    query). Only ties are reordered — engine ranking is otherwise preserved.
    """
    from lyric_sync.search.query_normalizer import normalize_text

    wanted = normalize_text(normalized.raw)
    if not wanted or len(results) < 2:
        return results

    ordered: list[SearchResult] = []
    start = 0
    while start < len(results):
        end = start
        while (
            end + 1 < len(results)
            and results[end + 1].score == results[start].score
        ):
            end += 1
        group = results[start:end + 1]
        if len(group) > 1:
            exact = [
                result
                for result in group
                if normalize_text(result.song.title) == wanted
                or any(normalize_text(alias) == wanted for alias in result.song.aliases)
            ]
            exact_ids = {id(result) for result in exact}
            rest = [result for result in group if id(result) not in exact_ids]
            # Among equally-scored non-exact hits, put songs whose lyrics can
            # actually be shown first. Metadata-only rows are identification
            # only; without this they tie with readable songs and crowd the
            # top of results with "Lyrics not distributed" dead ends.
            if any(result.has_lyrics for result in rest):
                rest = [result for result in rest if result.has_lyrics] + [
                    result for result in rest if not result.has_lyrics
                ]
            group = exact + rest
        ordered.extend(group)
        start = end + 1
    return ordered


def _plain_id(value: object) -> object:
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        try:
            return int(value.strip())
        except ValueError:
            return value
    return value


def _safe_id(value: int | str) -> int | str:
    """Return a usable song id for model objects (never None/blank-typed)."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    return ""


def _get(data: dict, *names: str, default=None):
    for name in names:
        value = data.get(name)
        if value is not None:
            return value
    return default


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _parse_aliases(raw) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        items = [str(item) for item in raw]
    else:
        text = str(raw).strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            items = [str(item) for item in parsed]
        elif isinstance(parsed, str):
            items = [parsed]
        elif "|" in text:
            items = text.split("|")
        else:
            items = [text]
    return tuple(item.strip() for item in items if item and item.strip())


def _song_from_row(data: dict) -> Song | None:
    if not data:
        return None
    song_id = _get(data, "id", "song_id")
    title = _get(data, "title")
    if song_id is None or title is None:
        return None

    lyrics_raw = str(_get(data, "lyrics_status", default="") or "").strip().upper()
    lyrics_status = (
        LYRICS_AVAILABLE if lyrics_raw in LYRICS_STATUS_AVAILABLE else LYRICS_UNAVAILABLE
    )

    return Song(
        id=song_id,
        title=str(title),
        artist=str(_get(data, "artist", "artist_name", default="") or ""),
        artist_id=_get(data, "artist_id"),
        album=_as_str(_get(data, "album")),
        year=_as_int(_get(data, "release_year", "year")),
        country=_as_str(_get(data, "country")),
        region=_as_str(_get(data, "region")),
        category=_as_str(_get(data, "category", "subgenre")),
        songwriter=_as_str(_get(data, "songwriter")),
        aliases=_parse_aliases(_get(data, "aliases")),
        verification_status=normalize_status(
            _get(data, "verification_status"), (VERIFIED, UNVERIFIED), UNVERIFIED
        ),
        copyright_status=normalize_status(
            _get(data, "copyright_status"), COPYRIGHT_STATUSES, METADATA_ONLY
        ),
        lyrics_status=lyrics_status,
        source=_as_str(_get(data, "source")),
        rights_notice=_as_str(_get(data, "rights_notice", "publisher")),
    )


def _as_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _with_aliases(song: Song, aliases: tuple[str, ...]) -> Song:
    from dataclasses import replace

    return replace(song, aliases=aliases)


def _trailing_index(raw_type: str) -> int:
    match = re.search(r"(\d+)\s*$", raw_type)
    return int(match.group(1)) if match else 0


# --------------------------------------------------------------------------- #
# snippets, highlights, fields
# --------------------------------------------------------------------------- #


def _highlight_count(text: str, tokens: Sequence[str]) -> int:
    if not text or not tokens:
        return 0
    return len(find_highlights(text, tokens))


def _best_snippet(
    song: Song, lyric_lines: Sequence[str], tokens: Sequence[str]
) -> tuple[str, str]:
    best_text = ""
    best_count = 0
    field = ""
    for text in lyric_lines:
        count = _highlight_count(text, tokens)
        if count > best_count:
            best_text, best_count, field = text, count, "lyrics"
    for alias in song.aliases:
        count = _highlight_count(alias, tokens)
        if count > best_count:
            best_text, best_count, field = alias, count, "aliases"
    return best_text, field


def _usable_engine_snippet(
    snippet: str, normalized: NormalizedQuery, song: Song
) -> bool:
    if not snippet:
        return False
    lowered = snippet.lower()
    if lowered.startswith("matched:"):
        return False
    if lowered in {normalized.raw.strip().lower(), normalized.normalized.lower()}:
        return False
    if lowered == song.title.strip().lower():
        return False
    return True


def _highlights(snippet: str, tokens: Sequence[str]) -> tuple[HighlightSpan, ...]:
    return find_highlights(snippet, tokens) if snippet else ()


def _words(text: str) -> set[str]:
    from lyric_sync.search.query_normalizer import normalize_text

    return set(normalize_text(text or "").split())


def _matched_fields(
    normalized: NormalizedQuery,
    song: Song,
    snippet_field: str,
    matched_tokens: Sequence[str],
) -> tuple[str, ...]:
    content = list(normalized.content) or list(normalized.tokens)
    fields: list[str] = []
    if content and set(content) <= _words(song.title):
        fields.append("title")
    if content and set(content) <= _words(song.display_artist):
        fields.append("artist")
    if snippet_field and snippet_field not in fields:
        fields.append(snippet_field)
    if not fields:
        fields.append("lyrics" if matched_tokens else "database")
    return tuple(dict.fromkeys(fields))


def _fuzzy_terms(
    matched_tokens: Sequence[str], song: Song, lyric_lines: Sequence[str]
) -> tuple[str, ...]:
    if not matched_tokens:
        return ()
    haystack = " ".join(
        [song.title, song.display_artist, *song.aliases, *lyric_lines]
    )
    words = _words(haystack)
    return tuple(
        token
        for token in matched_tokens
        if token not in words and not any(
            word.startswith(token) or token.startswith(word)
            for word in words
            if len(word) >= 3 and len(token) >= 3
        )
    )
