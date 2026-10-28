"""Adapter for https://zionlyrics.com/.

Zion Lyrics is the one modern lyrics site that publishes a documented JSON
API which robots.txt explicitly allows (``Allow: /api/v1/``), so this adapter
speaks JSON whenever it can and only falls back to HTML.

    GET /api/v1/songs?page=N     -> index page (20 records, meta.lastPage)
    GET /api/v1/songs/{slug}     -> one record with the full ``lyrics`` string
    GET /song/{slug}             -> the human page (HTML fallback)

The site rate-limits at 60 requests/minute and rejects the default Python
user agent, so the shared :class:`~lyrics_scraper.fetch.Fetcher` user agent
and throttle apply.

Copyright posture: their own ``/copyright`` page limits republication to
personal or educative use and the catalogue is user-submitted.  Songs are
therefore staged as METADATA_ONLY until an operator resolves each one.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from ..models import (
    SECTION_KEYWORDS,
    LyricSection,
    NormalizedSong,
    ParseResult,
    RawPage,
    Warning,
)
from .base import SourceAdapter

#: ``[Verse 1]``, ``[Chorus]``, ``(Bridge)`` …
BRACKET_LABEL = re.compile(r"^\s*[\[(](?P<label>[^\])]{1,40})[\])]\s*$")
FEATURED = re.compile(r"\s+(?:ft\.?|feat\.?|featuring)\s+", flags=re.I)
AND_SPLIT = re.compile(r"\s*(?:,|;|\s+and\s+)\s*", flags=re.I)
SITE_SUFFIX = re.compile(r"\s*[|–—-]\s*[^|–—-]*$")


def _label_type(label: str) -> str:
    key = re.sub(r"[\s_]+", "-", label.strip().lower())
    key = re.sub(r"-?\d+$", "", key).strip("-")
    return SECTION_KEYWORDS.get(key, "OTHER")


def _split_artists(value: str) -> tuple[list[str], list[str]]:
    parts = FEATURED.split(value or "")
    out: list[str] = []
    for part in parts:
        part = part.strip(" ,;")
        if part:
            out.extend(p.strip() for p in AND_SPLIT.split(part) if p.strip())
    return out, out[1:]


def parse_lyrics_text(text: str) -> list[LyricSection]:
    """Split a ``[Verse 1]\\nline`` payload into labelled sections."""
    sections: list[LyricSection] = []
    current: LyricSection | None = None
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        match = BRACKET_LABEL.match(line)
        if match:
            label = match.group("label").strip()
            kind = _label_type(label)
            current = LyricSection(label=label, section_type=kind,
                                   display_label=label.title() if kind == "OTHER" else label)
            sections.append(current)
            continue
        if current is None:
            current = LyricSection(label="", section_type="VERSE",
                                   display_label="Verse")
            sections.append(current)
        current.append(line, raw=line)
    return [section for section in sections if section.entries]


class ZionLyricsAdapter(SourceAdapter):
    """Zion Lyrics — JSON API with an HTML fallback."""

    name = "zionlyrics"
    site = "Zion Lyrics"
    domain = "zionlyrics.com"
    adapter_name = "ZionLyricsAdapter"
    #: ``?page=N`` index links are how the catalogue is walked.
    allow_query_links = True

    # -- detection ---------------------------------------------------------
    def matches(self, url: str) -> bool:
        return "zionlyrics.com" in (urllib.parse.urlsplit(url or "").netloc
                                    or "").lower()

    # -- parsing -----------------------------------------------------------
    def _parse(self, page: RawPage, page_type: str) -> ParseResult:
        body = (page.html or "").lstrip()
        if body.startswith("{") or body.startswith("["):
            return self._parse_json(page, body)
        return self._parse_html(page)

    # -- JSON --------------------------------------------------------------
    def _parse_json(self, page: RawPage, body: str) -> ParseResult:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            return self._failed(page, f"invalid JSON from the API: {exc}")
        data = payload.get("data")
        if isinstance(data, list):
            return self._parse_index(page, data, payload.get("meta") or {})
        if isinstance(data, dict):
            return self._parse_detail(page, data)
        return self._failed(page, "unexpected API payload shape")

    def _parse_index(self, page: RawPage, records: list, meta: dict) -> ParseResult:
        url = page.final_url or page.url
        result = ParseResult(page_id=page.page_id, url=url, page_type="api-index")
        for record in records:
            if not isinstance(record, dict):
                continue
            slug = record.get("slug") or ""
            canonical = record.get("canonicalUrl") or record.get("canonical_url")
            if slug:
                result.links.append(f"https://{self.domain}/api/v1/songs/{slug}")
            elif canonical:
                result.links.append(canonical)
        last_page = int(meta.get("lastPage") or meta.get("last_page") or 0)
        current = int(meta.get("page") or 1)
        if last_page and current < last_page:
            parts = urllib.parse.urlsplit(url)
            query = urllib.parse.parse_qs(parts.query)
            query["page"] = [str(current + 1)]
            result.links.append(urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path,
                 urllib.parse.urlencode(query, doseq=True), ""))
            )
        return result

    def _parse_detail(self, page: RawPage, record: dict) -> ParseResult:
        url = page.final_url or page.url
        result = ParseResult(page_id=page.page_id, url=url, page_type="api-song")
        song = self._song_from_record(record, url, page.page_id)
        if song is None:
            result.warnings.append(Warning(
                code="missing_lyrics", severity="error", source_url=url,
                message="API record carried no lyrics text"))
            return result
        result.songs.append(song)
        result.article_title = song.title
        return result

    # -- HTML fallback -----------------------------------------------------
    def _parse_html(self, page: RawPage) -> ParseResult:
        from ..htmldoc import parse_html

        url = page.final_url or page.url
        doc = parse_html(page.html or "", url=url)
        detected = "single" if doc.find_all(class_name="lyrics") else "listing"
        result = ParseResult(page_id=page.page_id, url=url, page_type=detected)

        for node in doc.find_all("a"):
            href = node.get("href") or ""
            if "/song/" not in href:
                continue
            absolute = urllib.parse.urljoin(url, href)
            if absolute not in result.links:
                result.links.append(absolute)

        hero = doc.find_all(class_name="song-hero")
        if not hero:
            return result
        title = ""
        for node in hero[0].find_all("h1"):
            title = " ".join(node.text().split())
            break
        artist = ""
        for node in doc.find_all(class_name="song-meta-line"):
            for anchor in node.find_all("a"):
                artist = " ".join(anchor.text().split())
                break
            break
        body_parts: list[str] = []
        for node in doc.find_all(class_name="lyrics"):
            body_parts.extend(line for line in node.text_lines() if line.strip())
        record = {
            "title": title,
            "lyrics": "\n".join(body_parts),
            "artists": [{"name": artist}] if artist else [],
            "canonicalUrl": url,
        }
        song = self._song_from_record(record, url, page.page_id)
        if song is None:
            result.warnings.append(Warning(
                code="missing_lyrics", severity="error", source_url=url,
                message="lyrics container was empty"))
            return result
        result.songs.append(song)
        result.article_title = song.title
        return result

    # -- shared ------------------------------------------------------------
    def _song_from_record(self, record: dict, url: str, page_id: str
                          ) -> NormalizedSong | None:
        title = SITE_SUFFIX.sub("", str(record.get("title") or "").strip())
        lyrics = record.get("lyrics") or record.get("lyric") or ""
        sections = parse_lyrics_text(lyrics)
        if not title or not sections:
            return None
        artists: list[str] = []
        featured: list[str] = []
        for entry in record.get("artists") or []:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
            else:
                name = str(entry).strip()
            if name:
                artists.append(name)
        if not artists and record.get("artist"):
            artists.append(str(record["artist"]).strip())
        if len(artists) == 1:
            more, more_featured = _split_artists(artists[0])
            if more:
                artists, featured = more, more_featured
        song = NormalizedSong(
            title=title,
            artists=[a for a in artists if a],
            featured_artists=[a for a in featured if a],
            source_url=record.get("canonicalUrl") or url,
            article_url=url,
            page_id=page_id,
            language=record.get("language") or None,
            modified_at=record.get("updatedAt") or record.get("updated_at"),
            sections=sections,
            extra={"verified": bool(record.get("verified")),
                   "song_id": record.get("id")},
        )
        song.raw_text = "\n".join(song.clean_lines)
        return song

    def _failed(self, page: RawPage, message: str) -> ParseResult:
        result = ParseResult(page_id=page.page_id,
                             url=page.final_url or page.url,
                             page_type="api-song")
        result.warnings.append(Warning(
            code="api_payload_error", severity="error", message=message,
            source_url=page.url))
        return result


__all__ = ["ZionLyricsAdapter", "parse_lyrics_text"]
