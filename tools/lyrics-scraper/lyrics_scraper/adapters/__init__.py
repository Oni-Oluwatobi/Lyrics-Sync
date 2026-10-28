"""Adapter registry.

``--source auto`` maps a hostname to its adapter; an explicit ``--source``
key selects one directly.  Unknown hosts fail with a clear message listing
the supported sources.
"""

from __future__ import annotations

import urllib.parse

from .agl import AfricanGospelLyricsAdapter
from .base import SourceAdapter, UnsupportedSource
from .gutenberg import GutenbergHymnBookAdapter
from .ogl import OpenGospelLyricsAdapter
from .zionlyrics import ZionLyricsAdapter

ADAPTERS: tuple[SourceAdapter, ...] = (
    OpenGospelLyricsAdapter(),
    AfricanGospelLyricsAdapter(),
    ZionLyricsAdapter(),
    GutenbergHymnBookAdapter(),
)

_BY_NAME = {adapter.name: adapter for adapter in ADAPTERS}


def available_sources() -> list[str]:
    return [adapter.name for adapter in ADAPTERS]


def get_adapter(name: str) -> SourceAdapter:
    adapter = _BY_NAME.get((name or "").strip().lower())
    if adapter is None:
        raise UnsupportedSource(
            f"unknown source {name!r} — available: "
            + ", ".join(available_sources())
        )
    return adapter


def _looks_like_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def detect_adapter(url: str) -> SourceAdapter:
    if not _looks_like_url(url):
        raise UnsupportedSource(
            f"not an http(s) URL: {url!r} — expected "
            f"https://host/page (a stray character before the scheme would "
            f"cause this)"
        )
    for adapter in ADAPTERS:
        if adapter.matches(url):
            return adapter
    host = urllib.parse.urlsplit(url).netloc or url
    raise UnsupportedSource(
        f"unsupported source: {host} — this builder supports: "
        + ", ".join(f"{a.name} ({a.domain})" for a in ADAPTERS)
    )


def adapter_for(url: str, source: str = "auto") -> SourceAdapter:
    """Resolve an adapter for ``url`` honouring ``--source``.

    An explicit ``--source`` that does not own ``url``'s host is an error:
    silently parsing site B's HTML with site A's rules would corrupt staging.
    """
    source = (source or "auto").strip().lower()
    if not _looks_like_url(url):
        raise UnsupportedSource(
            f"not an http(s) URL: {url!r} — expected "
            f"https://host/page (a stray character before the scheme would "
            f"cause this)"
        )
    if source in ("auto", "", "detect"):
        return detect_adapter(url)
    adapter = get_adapter(source)
    if not adapter.matches(url):
        host = urllib.parse.urlsplit(url).netloc or url
        raise UnsupportedSource(
            f"source {source!r} does not match {host} — pick the source that "
            f"owns this URL or use --source auto. Supported sources: "
            + ", ".join(f"{a.name} ({a.domain})" for a in ADAPTERS)
        )
    return adapter


__all__ = [
    "ADAPTERS", "AfricanGospelLyricsAdapter", "OpenGospelLyricsAdapter",
    "SourceAdapter", "UnsupportedSource", "adapter_for", "available_sources",
    "detect_adapter", "get_adapter",
]
