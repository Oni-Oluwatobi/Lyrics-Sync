"""Text normalisation helpers.

These mirror the catalogue conventions used by ``tools/build_gospel_db.py`` and
``tools/expand_ng_catalog.py`` so that records exported from the staging
database are compatible with the production ``.LSDB`` schema:

* ``normalized_title`` / ``normalized_artist`` use :func:`normalize`
* record ids use :func:`slug`

The scraper keeps its own copy so that neither tool depends on the other.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize(text: str | None) -> str:
    """Lowercase, drop punctuation, collapse whitespace (catalogue norm)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = text.replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def slug(text: str | None) -> str:
    """``"O Holy Night"`` -> ``o_holy_night`` (stable id fragment)."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def content_hash(*parts: str | None) -> str:
    """Stable hash over arbitrary strings (raw representation)."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8", errors="replace"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def lyrics_hash(lines: list[str]) -> str:
    """Hash of the *normalised* lyric stream — ignores case/punctuation/layout."""
    digest = hashlib.sha256()
    for line in lines:
        norm = normalize(line)
        if norm:
            digest.update(norm.encode("utf-8", errors="replace"))
            digest.update(b"\n")
    return digest.hexdigest()


def strip_numbering(title: str) -> str:
    """``"2. Jingle Bells"`` -> ``"Jingle Bells"`` (compilation list numbering)."""
    return re.sub(r"^\s*\d+\s*[.)\-–—]\s*", "", title or "").strip()


def compact_whitespace(text: str) -> str:
    return " ".join((text or "").split())
