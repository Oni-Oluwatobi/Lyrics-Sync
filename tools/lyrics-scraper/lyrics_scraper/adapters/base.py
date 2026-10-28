"""Source adapter contract.

Every lyrics website gets its own adapter.  An adapter owns all site-specific
behaviour (page detection, container/boundary rules, byline and taxonomy
conventions) and hands back the shared :class:`ParseResult` of
:class:`~lyrics_scraper.models.NormalizedSong` records.

    ScraperEngine
    ├── OpenGospelLyricsAdapter
    └── AfricanGospelLyricsAdapter
"""

from __future__ import annotations

import urllib.parse
from abc import ABC, abstractmethod

from ..models import ParseResult, RawPage


class UnsupportedSource(RuntimeError):
    """Raised when no adapter recognises a URL."""


class SourceAdapter(ABC):
    """One website, one adapter."""

    #: short CLI key, e.g. ``opengospellyrics``
    name: str = ""
    #: human readable site name stored in staging
    site: str = ""
    #: hostname used for ``--source auto`` detection
    domain: str = ""
    #: class name recorded next to every song
    adapter_name: str = ""
    #: legal posture every song from this source inherits when it is known
    #: up front (Project Gutenberg dedicates its texts to the public domain).
    #: Never invented for sites that merely *host* third-party lyrics.
    default_copyright_status: str = ""
    #: query strings normally create duplicate crawl paths; a source that
    #: paginates with ``?page=N`` opts in.
    allow_query_links: bool = False

    #: link tokens that would take the crawler into site chrome or a download
    BLOCKED_LINK_TOKENS: tuple[str, ...] = (
        "/wp-admin", "/wp-login", "#", "mailto:", ".pdf", ".zip", ".exe",
        ".xml",  # a sitemap is followed only when the page itself was one
    )

    # -- detection ---------------------------------------------------------
    def matches(self, url: str) -> bool:
        host = (urllib.parse.urlsplit(url).netloc or "").lower()
        host = host[4:] if host.startswith("www.") else host
        return bool(self.domain) and host == self.domain

    # -- crawling ----------------------------------------------------------
    def allows_link(self, url: str) -> bool:
        """Whether the engine should follow ``url`` when expanding a page."""
        if any(token in url for token in self.BLOCKED_LINK_TOKENS):
            return False
        if not self.allow_query_links and "?" in url:
            return False
        return True

    # -- parsing -----------------------------------------------------------
    @abstractmethod
    def _parse(self, page: RawPage, page_type: str) -> ParseResult:
        """Site-specific parsing; implemented by each adapter."""

    def parse(self, page: RawPage, *, page_type: str = "") -> ParseResult:
        """Parse a page and stamp every song with this source's identity."""
        result = self._parse(page, page_type)
        result.source_site = self.site
        result.source_domain = self.domain
        result.adapter_name = self.adapter_name
        for song in result.songs:
            song.source_site = self.site
            song.source_domain = self.domain
            song.source_adapter = self.adapter_name
            song.source_name = self.site
            if self.default_copyright_status and song.copyright_status in ("", "UNKNOWN"):
                song.copyright_status = self.default_copyright_status
            if not song.article_date:
                song.article_date = result.published_at
        return result

    # -- helpers -----------------------------------------------------------
    def describe(self) -> str:
        return f"{self.adapter_name} ({self.domain})"
