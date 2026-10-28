"""Adapter for https://www.gutenberg.org/ hymn books.

A single Gutenberg URL is an entire public-domain hymn book, so one fetch
stages hundreds of songs.  Structure rules live in
:mod:`lyrics_scraper.gutenberg`; this adapter only binds them to the source
identity and stamps every hymn as public domain — Project Gutenberg releases
these texts under its own public-domain dedication for works whose copyright
has expired.
"""

from __future__ import annotations

from ..models import ParseResult, RawPage
from .base import SourceAdapter


class GutenbergHymnBookAdapter(SourceAdapter):
    """Public-domain hymn books hosted by Project Gutenberg."""

    name = "gutenberg"
    site = "Project Gutenberg"
    domain = "gutenberg.org"
    adapter_name = "GutenbergHymnBookAdapter"
    #: Every text in these books is out of copyright worldwide.
    default_copyright_status = "PUBLIC_DOMAIN"

    def _parse(self, page: RawPage, page_type: str) -> ParseResult:
        from ..gutenberg import parse_page

        return parse_page(page, page_type)


__all__ = ["GutenbergHymnBookAdapter"]
