"""Relevance ranking for remembered-lyric queries.

The ranker combines several signals into one bounded score. Thresholds are
explicit constants — match labels are only produced where a threshold exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from lyric_sync.database.lsdb_manager import SongRecord
from lyric_sync.models.search_result import HighlightSpan, MatchLabel
from lyric_sync.search.highlighter import find_highlights
from lyric_sync.search.query_normalizer import (
    STOPWORDS,
    NormalizedQuery,
    contraction_variants,
    normalize_text,
)

# --------------------------------------------------------------------------- weights
WEIGHT_PHRASE = 0.34
WEIGHT_COVERAGE = 0.22
WEIGHT_LINE = 0.16
WEIGHT_PROXIMITY = 0.10
WEIGHT_TITLE = 0.12
WEIGHT_ARTIST = 0.04
WEIGHT_ALIAS = 0.02
WEIGHT_RETRIEVAL = 0.04

UNVERIFIED_PENALTY = 0.95
GENERIC_PENALTY = 0.85

# ---------------------------------------------------------------------- thresholds
STRONG_THRESHOLD = 0.72
GOOD_THRESHOLD = 0.50
POSSIBLE_THRESHOLD = 0.32
MIN_SCORE = 0.30
MIN_COVERAGE = 0.34

SENSITIVITY_SHIFTS = {"strict": 0.07, "balanced": 0.0, "relaxed": -0.06}
FUZZY_RATIO = {"strict": 0.86, "balanced": 0.80, "relaxed": 0.74}


@dataclass(frozen=True)
class RankedMatch:
    record: SongRecord
    score: float
    label: MatchLabel
    snippet: str
    snippet_index: int = -1
    context_before: str = ""
    context_after: str = ""
    matched_fields: tuple[str, ...] = ()
    fuzzy_terms: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()

    @property
    def highlights(self) -> tuple[HighlightSpan, ...]:
        return find_highlights(self.snippet, self.tokens)


def _words_set(text: str) -> set[str]:
    return set(text.split()) if text else set()


def _best_fuzzy_ratio(token: str, vocabulary: set[str], threshold: float) -> float:
    """Cheap fuzzy probe: filter candidates by first letter/length, then compare."""
    if not vocabulary or len(token) < 4:
        return 0.0
    first = token[0]
    length = len(token)
    best = 0.0
    for word in vocabulary:
        if not word or word[0] != first:
            continue
        if abs(len(word) - length) > 1 or len(word) < 3:
            continue
        ratio = SequenceMatcher(None, token, word).ratio()
        if ratio > best:
            best = ratio
            if best >= 0.99:
                break
    return best if best >= threshold else 0.0


def _token_hits(
    tokens: Sequence[str],
    vocabulary: set[str],
    fuzzy_threshold: float,
) -> tuple[list[float], list[str]]:
    """Per-token hit strength (1.0 exact, ~0.7 fuzzy, 0.0 miss) + fuzzy terms."""
    strengths: list[float] = []
    fuzzy_terms: list[str] = []
    for token in tokens:
        if token in vocabulary:
            strengths.append(1.0)
            continue
        variant_hit = any(
            all(part in vocabulary for part in variant.split())
            for variant in contraction_variants(token)
        )
        if variant_hit:
            strengths.append(1.0)
            continue
        ratio = _best_fuzzy_ratio(token, vocabulary, fuzzy_threshold)
        if ratio > 0:
            strengths.append(0.65 + 0.3 * (ratio - fuzzy_threshold) / (1 - fuzzy_threshold)
                             if fuzzy_threshold < 1 else 0.65)
            fuzzy_terms.append(token)
        else:
            strengths.append(0.0)
    return strengths, fuzzy_terms


def _longest_query_run(tokens: Sequence[str], words: Sequence[str]) -> int:
    """Length of the longest run of query tokens appearing in order inside ``words``."""
    if not tokens or not words:
        return 0
    best = 0
    for start_index, word in enumerate(words):
        if word != tokens[0]:
            continue
        run = 1
        cursor = start_index + 1
        for token in tokens[1:]:
            while cursor < len(words) and words[cursor] != token:
                cursor += 1
            if cursor >= len(words):
                break
            run += 1
            cursor += 1
        best = max(best, run)
        if best == len(tokens):
            break
    return best


def _proximity(words: Sequence[str], matched_tokens: Sequence[str]) -> float:
    """How close the matched query tokens sit to each other inside the lyrics."""
    if len(matched_tokens) < 2 or not words:
        return 0.0
    positions: list[int] = []
    token_index = 0
    wanted = list(matched_tokens)
    for index, word in enumerate(words):
        if token_index < len(wanted) and word == wanted[token_index]:
            positions.append(index)
            token_index += 1
    if len(positions) < 2:
        return 0.0
    span = positions[-1] - positions[0] + 1
    expected = len(positions)
    return max(0.0, min(1.0, expected / span))


def rank_record(
    query: NormalizedQuery,
    record: SongRecord,
    *,
    retrieval_sources: Sequence[str] = (),
    sensitivity: str = "balanced",
) -> RankedMatch | None:
    """Score one candidate. Returns ``None`` when the match is too weak."""
    if query.is_empty:
        return None

    shift = SENSITIVITY_SHIFTS.get(sensitivity, 0.0)
    fuzzy_threshold = FUZZY_RATIO.get(sensitivity, 0.80)

    song = record.song
    title_norm = normalize_text(song.title)
    artist_norm = normalize_text(song.display_artist)
    alias_norms = [normalize_text(alias) for alias in song.aliases]
    lines_norm = [normalize_text(line) for line in record.lines]
    lyrics_norm = " ".join(line for line in lines_norm if line)

    lyric_words = lyrics_norm.split() if lyrics_norm else []
    vocabulary: set[str] = set(lyric_words) | _words_set(title_norm) | _words_set(artist_norm)
    for alias in alias_norms:
        vocabulary |= _words_set(alias)

    if not vocabulary and not lyrics_norm:
        return None

    tokens = list(query.tokens)
    content = list(query.content)
    strengths, fuzzy_terms = _token_hits(tokens, vocabulary, fuzzy_threshold)
    content_strengths = [
        strength for token, strength in zip(tokens, strengths) if token in set(content)
    ] or strengths

    # ------------------------------------------------------------- coverage
    weights = [0.6 if token in STOPWORDS else 2.0 for token in tokens]
    total_weight = sum(weights) or 1.0
    coverage = sum(w * s for w, s in zip(weights, strengths)) / total_weight

    content_strength = (
        sum(content_strengths) / len(content_strengths) if content_strengths else 0.0
    )

    # -------------------------------------------------------------- phrases
    phrase_score = 0.0
    if query.normalized and query.normalized in lyrics_norm:
        phrase_score = 1.0
    elif query.normalized and (query.normalized in title_norm or
                               any(query.normalized in alias for alias in alias_norms)):
        phrase_score = 1.0
    else:
        run = _longest_query_run(tokens, lyric_words)
        if run >= 2:
            phrase_score = run / len(tokens)
        else:
            title_run = _longest_query_run(tokens, title_norm.split())
            phrase_score = 0.5 * (title_run / len(tokens)) if title_run else 0.0

    # ----------------------------------------------------------- line match
    line_score = 0.0
    snippet_index, snippet = -1, ""
    best_hits = -1
    for index, line in enumerate(lines_norm):
        if not line:
            continue
        line_words = set(line.split())
        hits = sum(
            1
            for token in content
            if token in line_words
            or any(all(part in line_words for part in variant.split())
                   for variant in contraction_variants(token))
        )
        ratio = hits / len(content) if content else 0.0
        if ratio > line_score or (snippet_index < 0 and hits > 0):
            line_score = max(line_score, ratio)
            snippet_index = index
            snippet = record.lines[index]
            best_hits = hits
        elif hits > best_hits and ratio == line_score:
            snippet_index = index
            snippet = record.lines[index]
            best_hits = hits

    if snippet_index < 0 and record.lines:
        snippet_index, snippet = 0, record.lines[0]

    # -------------------------------------------------------- field matches
    title_strengths, _ = _token_hits(content, _words_set(title_norm), fuzzy_threshold)
    artist_strengths, _ = _token_hits(content, _words_set(artist_norm), fuzzy_threshold)
    alias_strengths = [0.0] * len(content)
    for alias in alias_norms:
        alias_hits, _ = _token_hits(content, _words_set(alias), fuzzy_threshold)
        alias_strengths = [max(a, b) for a, b in zip(alias_strengths, alias_hits)]

    title_score = sum(title_strengths) / len(title_strengths) if title_strengths else 0.0
    artist_score = sum(artist_strengths) / len(artist_strengths) if artist_strengths else 0.0
    alias_score = sum(alias_strengths) / len(alias_strengths) if alias_strengths else 0.0

    matched_tokens = [
        token for token, strength in zip(tokens, strengths) if strength > 0
    ]
    proximity = _proximity(lyric_words, matched_tokens)

    retrieval_bonus = 0.0
    if retrieval_sources:
        if "phrase" in retrieval_sources:
            retrieval_bonus = 1.0
        elif "fts" in retrieval_sources:
            retrieval_bonus = 0.7
        elif "metadata" in retrieval_sources:
            retrieval_bonus = 0.5

    score = (
        WEIGHT_PHRASE * phrase_score
        + WEIGHT_COVERAGE * coverage
        + WEIGHT_LINE * line_score
        + WEIGHT_PROXIMITY * proximity
        + WEIGHT_TITLE * title_score
        + WEIGHT_ARTIST * artist_score
        + WEIGHT_ALIAS * alias_score
        + WEIGHT_RETRIEVAL * retrieval_bonus
    )

    # ------------------------------------------------------------- penalties
    matched_fields: list[str] = []
    if phrase_score >= 1.0 and query.normalized in lyrics_norm:
        matched_fields.append("lyrics")
    if line_score >= 1.0:
        matched_fields.append("lyric line")
    if title_score >= 1.0:
        matched_fields.append("title")
    if artist_score >= 1.0:
        matched_fields.append("artist")
    if alias_score >= 1.0:
        matched_fields.append("alias")
    if not matched_fields:
        if title_score > 0:
            matched_fields.append("title")
        elif artist_score > 0:
            matched_fields.append("artist")
        elif lyrics_norm:
            matched_fields.append("lyrics")

    # --- eligibility (hard filters) ------------------------------------
    if content_strength == 0.0 and title_score == 0.0 and artist_score == 0.0:
        return None
    if coverage < MIN_COVERAGE and phrase_score <= 0 and line_score < 0.5:
        return None
    if query.is_generic:
        # A single short word is weak evidence: demand a real hit first.
        if content_strength < 1.0 and title_score < 1.0 and line_score < 1.0:
            return None

    score = max(0.0, min(1.0, score))
    if score < MIN_SCORE + shift:
        return None

    # --- ranking penalties (affect order, not eligibility) -------------
    if song.verification_status != "VERIFIED":
        score *= UNVERIFIED_PENALTY
    if query.is_generic:
        score *= GENERIC_PENALTY
    score = max(0.0, min(1.0, score))

    label = _label_for(score, phrase_score, line_score, shift)

    context_before = ""
    context_after = ""
    if snippet_index >= 0:
        if snippet_index > 0:
            context_before = record.lines[snippet_index - 1]
        if snippet_index + 1 < len(record.lines):
            context_after = record.lines[snippet_index + 1]

    return RankedMatch(
        record=record,
        score=score,
        label=label,
        snippet=snippet or "",
        snippet_index=snippet_index,
        context_before=context_before,
        context_after=context_after,
        matched_fields=tuple(matched_fields),
        fuzzy_terms=tuple(fuzzy_terms),
        tokens=tuple(tokens),
    )


def _label_for(score: float, phrase_score: float, line_score: float, shift: float) -> MatchLabel:
    if score >= STRONG_THRESHOLD - shift and (phrase_score >= 1.0 or line_score >= 1.0):
        return MatchLabel.STRONG
    if score >= GOOD_THRESHOLD - shift:
        return MatchLabel.GOOD
    return MatchLabel.POSSIBLE
