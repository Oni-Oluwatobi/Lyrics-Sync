"""Adapter for https://opengospellyrics.com/."""

from __future__ import annotations

from ..models import ParseResult, RawPage
from .base import SourceAdapter


class OpenGospelLyricsAdapter(SourceAdapter):
    """Compilations and single-song pages on OpenGospelLyrics.

    Structure rules (numbered ``<h2>`` song headings, ``Author(s):`` /
    ``Common Chords:`` metadata, ``<hr>`` separators) live in
    :mod:`lyrics_scraper.parser`; this adapter only binds them to the
    source identity.
    """

    name = "opengospellyrics"
    site = "OpenGospelLyrics"
    domain = "opengospellyrics.com"
    adapter_name = "OpenGospelLyricsAdapter"

    def _parse(self, page: RawPage, page_type: str) -> ParseResult:
        from ..parser import parse_page

        return parse_page(page, page_type)
