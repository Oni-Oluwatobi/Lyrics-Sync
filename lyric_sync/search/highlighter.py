"""Locate and mark matched words inside snippets and lyrics."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from typing import Iterable, Sequence

from lyric_sync.models.search_result import HighlightSpan
from lyric_sync.search.query_normalizer import contraction_variants, normalize_with_map

HIGHLIGHT_CLASS = "hit"


@lru_cache(maxsize=512)
def _patterns_for(token: str) -> tuple[str, ...]:
    patterns = [token]
    variants = contraction_variants(token)
    if variants:
        patterns.append(" ".join(variants))
    return tuple(pattern for pattern in patterns if pattern)


def find_highlights(text: str, tokens: Sequence[str]) -> tuple[HighlightSpan, ...]:
    """Return sorted, merged spans of ``text`` that match any of ``tokens``."""
    if not text or not tokens:
        return ()
    return _find_highlights_cached(text, tuple(tokens))


@lru_cache(maxsize=8192)
def _find_highlights_cached(
    text: str, tokens: tuple[str, ...]
) -> tuple[HighlightSpan, ...]:
    # Cached: spans are frozen dataclasses, text and tokens are immutable.
    # The same lyric lines are re-highlighted on every search.
    normalized, index_map = normalize_with_map(text)
    if not normalized or not index_map:
        return ()

    raw: list[tuple[int, int]] = []
    for token in tokens:
        for pattern in _patterns_for(token):
            regex = re.compile(
                rf"(?<![0-9A-Za-z]){re.escape(pattern)}(?![0-9A-Za-z])"
            )
            for match in regex.finditer(normalized):
                start = match.start()
                end = match.end()
                if start >= len(index_map) or end <= 0:
                    continue
                start = index_map[start]
                end = index_map[min(end, len(index_map)) - 1] + 1
                raw.append((start, end))

    if not raw:
        return ()
    raw.sort()
    merged: list[tuple[int, int]] = []
    for start, end in raw:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(HitSpan(start, end) for start, end in merged)


HitSpan = HighlightSpan


def highlighted_html(text: str, tokens: Sequence[str], accent: str = "#FF7A1A") -> str:
    """HTML-escaped ``text`` with matched words emphasised inline.

    Qt does not apply style sheets to rich text runs, so the highlight colour is
    written directly into the markup.
    """
    spans = find_highlights(text, tokens)
    if not spans:
        return html.escape(text, quote=False)

    parts: list[str] = []
    cursor = 0
    style = f"color:{accent}; font-weight:600;"
    for span in spans:
        if span.start > cursor:
            parts.append(html.escape(text[cursor:span.start], quote=False))
        piece = html.escape(text[span.start:span.end], quote=False)
        parts.append(f'<span style="{style}">{piece}</span>')
        cursor = span.end
    if cursor < len(text):
        parts.append(html.escape(text[cursor:], quote=False))
    return "".join(parts)


def plain_highlights(text: str, tokens: Sequence[str]) -> list[tuple[int, int]]:
    """Matched ranges as plain ``(start, end)`` tuples."""
    return [(span.start, span.end) for span in find_highlights(text, tokens)]


def best_line(lines: Iterable[str], tokens: Sequence[str]) -> tuple[int, str]:
    """Pick the line that matches the query best; returns ``(index, line)``."""
    all_lines = list(lines)
    if not all_lines:
        return -1, ""
    best_index = -1
    best_count = 0
    best_len = 0
    normalized_tokens = list(tokens)
    for index, line in enumerate(all_lines):
        if not line.strip():
            continue
        count = len(find_highlights(line, normalized_tokens))
        if count > best_count or (count == best_count and count and len(line) < best_len):
            best_count = count
            best_index = index
            best_len = len(line)
    if best_index < 0:
        for index, line in enumerate(all_lines):
            if line.strip():
                return index, line
        return -1, ""
    return best_index, all_lines[best_index]
