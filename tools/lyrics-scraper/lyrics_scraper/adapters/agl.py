"""Adapter for https://africangospellyrics.com/."""

from __future__ import annotations

from ..models import ParseResult, RawPage
from .base import SourceAdapter


class AfricanGospelLyricsAdapter(SourceAdapter):
    """One-song-per-post pages on African Gospel Lyrics.

    Structure rules (``div.post-content`` boundary, ``Refrain:`` labels,
    ``x4`` / ``(Repeat)`` markers, language and country taxonomy) live in
    :mod:`lyrics_scraper.african`; this adapter only binds them to the
    source identity.
    """

    name = "africangospellyrics"
    site = "African Gospel Lyrics"
    domain = "africangospellyrics.com"
    adapter_name = "AfricanGospelLyricsAdapter"

    def _parse(self, page: RawPage, page_type: str) -> ParseResult:
        from ..african import parse_page

        return parse_page(page)
