"""Search result model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lyric_sync.models.song import Song


class MatchLabel(str, Enum):
    """Human readable match quality. Thresholds live in ``search.ranker``."""

    STRONG = "Strong match"
    GOOD = "Good match"
    POSSIBLE = "Possible match"

    @property
    def key(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class HighlightSpan:
    """Range of characters inside ``snippet`` that matched the query."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


@dataclass(frozen=True)
class SearchResult:
    """One ranked song returned by the search engine."""

    song: Song
    score: float
    label: MatchLabel
    snippet: str = ""
    highlights: tuple[HighlightSpan, ...] = field(default_factory=tuple)
    context_before: str = ""
    context_after: str = ""
    matched_fields: tuple[str, ...] = ()
    fuzzy_terms: tuple[str, ...] = ()

    @property
    def song_id(self) -> int | str:
        return self.song.id

    @property
    def title(self) -> str:
        return self.song.title

    @property
    def artist(self) -> str:
        return self.song.display_artist

    @property
    def has_lyrics(self) -> bool:
        return self.song.lyrics_displayable
