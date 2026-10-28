"""OpenGospelLyrics page parser.

Detection is structural and semantic â€” headings, block order, section
vocabulary and ``Label: value`` metadata patterns.  No song title is ever
matched, so the same parser works for future compilations and single-song
pages.
"""

from __future__ import annotations

import re

from .detect import (
    collect_blocks,
    detect_page_type,
    extract_post_links,
    find_container,
    heading_text,
    song_headings,
)
from .htmldoc import Document, Node, parse_html
from .models import (
    METADATA_LABELS,
    SECTION_KEYWORDS,
    LyricSection,
    ParseResult,
    RawPage,
    NormalizedSong,
    Warning,
)
from .normalize import compact_whitespace

# Field names that stay recognisable even after the header region closed.
STRONG_LABELS = {
    "author", "authors", "author(s)", "composer", "composed by",
    "songwriter", "written by", "lyricist", "translator", "translated by",
    "year", "language", "lang", "key",
}

# "Common Chords (C Major): C, G, F"
CHORDS_LABEL = re.compile(
    r"^(?P<label>common\s+chords|chords)(?:\s*\((?P<key>[^)]+)\))?\s*:\s*(?P<value>.+)$",
    flags=re.I,
)

# "Author(s): James Lord Pierpont"
KV_LABEL = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9()/.\- ]{0,40}?)\s*:\s*(?P<value>.+)$")

# "Verse", "Verse 1", "Chorus:", "Stanza 2", "Pre-Chorus 3"
SECTION_ONLY = re.compile(
    r"^(?P<kw>[a-z][a-z\-/ ]*?)\s*(?P<num>\d+)?\s*:?\s*$", flags=re.I
)

# "Chorus: first lyric line" / "Verse 1: first lyric line"
SECTION_INLINE = re.compile(
    r"^(?P<kw>[a-z][a-z\-/ ]*?)\s*(?P<num>\d+)?\s*:\s*(?P<rest>\S.*)$", flags=re.I
)

# Paragraphs that mark the end of the song body (they are page furniture, not
# lyrics).  Reaching one truncates the current song and records a warning so
# nothing is dropped silently.
STOP_LABELS = {
    "bibliography", "references", "works cited", "sources", "further reading",
    "download pdf", "tweet", "share this", "share this post", "subscribe",
    "subscribe to get the latest posts sent to your email", "type your email",
    "post navigation", "leave a reply", "leave a comment", "comments",
    "pingback", "blog stats", "menu", "discover more from",
    "discover more from christian worship song lyrics", "related",
    "related posts", "you may also like", "read more",
    "search for lyrics or phrase", "follow us", "follow via email alerts",
    "trending lyrics", "country/language", "share the lyrics",
}

# Furniture headings/phrases that may carry a site-specific suffix
# ("Discover more from African Gospel Lyrics", "21 Comments ( +add yours? )").
STOP_PREFIXES = (
    "discover more from", "share the lyrics", "share this",
    "leave a comment", "leave a reply", "search for lyrics",
    "follow us", "follow via email", "trending lyrics", "country/language",
    "related posts", "you may also like",
    "subscribe to get the latest posts",
)
STOP_COMMENTS = re.compile(r"^\d+\s+comments?\b")

NUMBERED_PREFIX = re.compile(r"^\s*\d+\s*[.)\-â€“â€”]\s*")

CATEGORY_CLASS = re.compile(r"^(?:category|tag)-(.+)$")


# --------------------------------------------------------------------------- #
# section + metadata detection
# --------------------------------------------------------------------------- #

def _keyword_type(candidate: str) -> str | None:
    key = compact_whitespace(candidate).lower().strip()
    if key in SECTION_KEYWORDS:
        return SECTION_KEYWORDS[key]
    return None


def detect_section(text: str) -> tuple[str, int, str, str] | None:
    """Return ``(section_type, number, raw_label, inline_first_line)``.

    Matching is case-insensitive but every returned value keeps the original
    capitalisation of ``text``.
    """
    raw = compact_whitespace(text)
    if not raw or len(raw) > 60:
        return None

    match = SECTION_INLINE.match(raw)
    if match:
        section_type = _keyword_type(match.group("kw"))
        if section_type:
            number = int(match.group("num")) if match.group("num") else 0
            return section_type, number, raw, compact_whitespace(match.group("rest"))

    match = SECTION_ONLY.match(raw)
    if match:
        section_type = _keyword_type(match.group("kw"))
        if section_type:
            number = int(match.group("num")) if match.group("num") else 0
            return section_type, number, raw, ""
    return None


def is_stop_label(text: str) -> bool:
    """True when ``text`` is page furniture that ends a song body."""
    label = text.lower().strip().rstrip(":!?.â€¦ ").strip()
    if not label:
        return False
    if label in STOP_LABELS:
        return True
    if STOP_COMMENTS.match(label):
        return True
    return any(label.startswith(prefix) for prefix in STOP_PREFIXES)


def display_label(section_type: str, number: int, raw_label: str) -> str:
    """Export form, matching production values (``Verse 1``, ``Chorus``)."""
    from .models import SECTION_LABELS

    if section_type == "VERSE" and number:
        return f"Verse {number}"
    if number and section_type != "OTHER":
        return f"{SECTION_LABELS.get(section_type, 'Section')} {number}"
    base = SECTION_LABELS.get(section_type)
    if base and section_type != "OTHER":
        return base
    if section_type == "OTHER" and raw_label and ":" in raw_label:
        # inline labels such as "Repeat: first lyric line"
        head = raw_label.split(":", 1)[0].strip()
        if head:
            return head
    return raw_label or "Section"


def _split_metadata(text: str) -> tuple[str, str, str] | None:
    """Return ``(canonical_field, value, extra_key)`` for a metadata paragraph."""
    chords = CHORDS_LABEL.match(text.strip())
    if chords:
        return "chords", compact_whitespace(chords.group("value")), compact_whitespace(
            chords.group("key") or ""
        )
    match = KV_LABEL.match(text.strip())
    if not match:
        return None
    label = compact_whitespace(match.group("label")).lower().rstrip(":").strip()
    field_name = METADATA_LABELS.get(label)
    if not field_name:
        return None
    return field_name, compact_whitespace(match.group("value")), ""


def is_metadata_paragraph(text: str, in_header: bool) -> tuple[str, str, str] | None:
    """Metadata lives in the song header block, or is an unambiguous field label."""
    if not text or len(text) > 200:
        return None
    parsed = _split_metadata(text)
    if parsed is None:
        return None
    if in_header or parsed[0] in STRONG_LABELS:
        return parsed
    return None


# --------------------------------------------------------------------------- #
# page parsing
# --------------------------------------------------------------------------- #

def _meta_content(doc: Document, *keys: str) -> str | None:
    for node in doc.find_all("meta"):
        key = node.get("property") or node.get("name") or ""
        if key in keys:
            value = node.get("content")
            if value and value.strip():
                return value.strip()
    return None


def _strip_site_suffix(title: str, site: str) -> str:
    cleaned = compact_whitespace(title)
    if site and cleaned.lower().endswith(site.lower()):
        cleaned = cleaned[: -len(site)].strip(" -â€“â€”|_")
    for sep in (" - ", " | ", " â€“ ", " â€” "):
        if sep in cleaned:
            head, tail = cleaned.rsplit(sep, 1)
            if tail.lower() in ("gospel lyrics", "lyrics", "christian worship song lyrics"):
                cleaned = head
    return cleaned.strip() or title


def _article_taxonomy(container: Node | None) -> tuple[list[str], list[str]]:
    categories: list[str] = []
    tags: list[str] = []
    if container is None:
        return categories, tags
    for class_name in container.classes:
        match = CATEGORY_CLASS.match(class_name)
        if not match:
            continue
        value = match.group(1).replace("-", " ").strip()
        if not value:
            continue
        if class_name.startswith("tag-"):
            if value not in tags:
                tags.append(value)
        elif value not in categories:
            categories.append(value)
    return categories, tags


def _document_date(doc: Document) -> tuple[str | None, str | None]:
    published = None
    modified = None
    for node in doc.find_all("time"):
        value = node.get("datetime")
        if value and not published:
            published = value
    published = published or _meta_content(doc, "article:published_time")
    modified = _meta_content(doc, "article:modified_time")
    if published is None:
        text = doc.root.text()
        match = re.search(r"Published\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        if match:
            published = match.group(1)
    return published, modified


def _build_sections(items: list[tuple[str, str, int, str]]) -> list[LyricSection]:
    """``items`` is an ordered list of ``(label, type, number, line)`` groups."""
    sections: list[LyricSection] = []
    current: LyricSection | None = None
    for label, section_type, number, line in items:
        needs_new = (
            current is None
            or current.section_type != section_type
            or current.label != label
        )
        if needs_new:
            current = LyricSection(
                label=label,
                section_type=section_type,
                display_label=display_label(section_type, number, label),
            )
            sections.append(current)
        current.append(line)
    return [section for section in sections if section.lines]


def _parse_song_segment(
    blocks: list[Node],
    start: int,
    end: int,
    title: str,
    page: RawPage,
    defaults: dict,
    parse_warnings: list[Warning] | None = None,
) -> NormalizedSong:
    song = NormalizedSong(
        title=title,
        article_url=page.final_url or page.url,
        page_id=page.page_id,
        **{k: v for k, v in defaults.items() if k in NormalizedSong.__dataclass_fields__},
    )
    # Per-song canonical URL: the article URL plus a stable title fragment, so
    # two songs from one compilation never collide on the source-URL signal.
    from .normalize import slug

    base = song.article_url
    song.source_url = f"{base}#{slug(title)}" if base and title else base

    items: list[tuple[str, str, int, str]] = []
    # Songs that print no labels start as one implicit verse.
    current_label = ""
    current_type = "VERSE"
    current_number = 0
    header_open = True

    def start_section(label: str, section_type: str, number: int) -> None:
        nonlocal current_label, current_type, current_number, header_open
        current_label, current_type, current_number = label, section_type, number
        header_open = False

    raw_parts: list[str] = []
    truncated_at = ""
    for index in range(start, end):
        node = blocks[index]

        if node.tag == "hr":
            raw_parts.append("---")
            continue

        if node.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = heading_text(node)
            if not text:
                continue
            if is_stop_label(text):
                if items:
                    truncated_at = text
                    break
                continue
            raw_parts.append(text)
            found = detect_section(text)
            if found:
                section_type, number, label, inline = found
                start_section(label, section_type, number)
                if inline:
                    items.append((label, section_type, number, inline))
            continue

        if node.tag not in ("p", "blockquote", "pre", "li"):
            continue

        text = compact_whitespace(node.text())
        if not text:
            continue

        if is_stop_label(text):
            if items:
                truncated_at = text
                break
            continue

        raw_parts.append(text)

        metadata = is_metadata_paragraph(text, header_open)
        if metadata:
            _apply_metadata(song, *metadata)
            continue

        header_open = False
        found = detect_section(text)
        if found:
            section_type, number, label, inline = found
            start_section(label, section_type, number)
            if inline:
                items.append((label, section_type, number, inline))
            continue

        items.append((current_label, current_type, current_number, text))

    if truncated_at and parse_warnings is not None:
        # Hitting a boundary (the next song's heading, an <hr>) is the
        # parsing rules doing their job — record where it ended, but do not
        # treat a correct stop as a defect that blocks review.
        parse_warnings.append(Warning(
            code="truncated_at_furniture",
            message=f"song body ended at page furniture: {truncated_at!r}",
            severity="info", song_title=title,
            source_url=page.final_url or page.url, context=truncated_at,
        ))

    song.sections = _build_sections(items)
    song.raw_text = "\n".join(raw_parts)
    return song


def _apply_metadata(song: NormalizedSong, field_name: str, value: str, extra: str) -> None:
    if not value:
        return
    if field_name == "chords":
        song.chords = value
        if extra:
            song.key_name = song.key_name or extra
        return
    if field_name == "artist":
        song.artist = value
        return
    if field_name == "category":
        parts = [part.strip() for part in (song.category or "").split(",")]
        for part in value.split(","):
            part = part.strip()
            if part and part not in parts:
                parts.append(part)
        song.category = ", ".join(part for part in parts if part)
        return
    if field_name == "year":
        song.year = value
        return
    if field_name == "language":
        parts = [part.strip() for part in
                 re.split(r"[,/|&]|\band\b", value) if part.strip()]
        if parts:
            for part in parts:
                if part not in song.languages:
                    song.languages.append(part)
            song.language = song.languages[0]
            song.language_confidence = "explicit"
        return
    if field_name == "key":
        song.key_name = song.key_name or value
        return
    current = getattr(song, field_name, None)
    if not current:
        setattr(song, field_name, value)
    elif isinstance(current, str) and value.lower() not in current.lower():
        setattr(song, field_name, f"{current}; {value}")


def parse_page(page: RawPage, page_type: str = "") -> ParseResult:
    """Parse one fetched page into songs, links and warnings."""
    doc = parse_html(page.html, url=page.final_url or page.url)
    page_type = page_type or detect_page_type(doc, page.url)
    result = ParseResult(
        page_id=page.page_id,
        url=page.url,
        page_type=page_type,
        site_title=_meta_content(doc, "og:site_name") or "",
    )

    if page_type == "sitemap":
        result.links = [
            node.get("href") or node.text()
            for node in doc.find_all("loc")
        ]
        return result

    container = find_container(doc)
    if container is None:
        result.warnings.append(Warning(
            code="no_content_container",
            message="page has no recognisable content container",
            severity="error",
            source_url=page.url,
        ))
        return result

    heading_one = container.first("h1")
    result.article_title = _strip_site_suffix(
        _meta_content(doc, "og:title")
        or (heading_text(heading_one) if heading_one else "")
        or doc.title,
        result.site_title,
    )

    result.published_at, result.modified_at = _document_date(doc)
    result.categories, result.tags = _article_taxonomy(container)
    result.links = extract_post_links(doc, page.url)

    blocks = collect_blocks(container)
    headings = song_headings(blocks)

    defaults = {
        "published_at": result.published_at,
        "modified_at": result.modified_at,
        "tags": list(result.tags),
        "category": ", ".join(result.categories) if result.categories else None,
    }

    if not headings:
        song = _parse_song_segment(
            blocks, 0, len(blocks), result.article_title or doc.title,
            page, defaults, result.warnings,
        )
        if song.title:
            result.songs.append(song)
        else:
            result.warnings.append(Warning(
                code="missing_title", message="could not determine a title",
                severity="error", source_url=page.url,
            ))
        return result

    block_position = {id(node): index for index, node in enumerate(blocks)}
    for position, (_index, node, text) in enumerate(headings):
        block_index = block_position[id(node)]
        next_index = (
            block_position[id(headings[position + 1][1])]
            if position + 1 < len(headings)
            else len(blocks)
        )
        title = compact_whitespace(NUMBERED_PREFIX.sub("", text))
        if not title:
            result.warnings.append(Warning(
                code="missing_title", message="empty song heading",
                severity="warning", source_url=page.url, context=text,
            ))
            continue
        song = _parse_song_segment(blocks, block_index + 1, next_index, title,
                                   page, defaults, result.warnings)
        result.songs.append(song)

    if not result.songs:
        result.warnings.append(Warning(
            code="no_songs_detected",
            message="article contained headings but no song could be parsed",
            severity="warning", source_url=page.url,
        ))
    return result


def parse_html_text(html: str, url: str = "") -> ParseResult:
    """Convenience wrapper used by tests (no fetch required)."""
    return parse_page(RawPage(url=url, final_url=url, html=html, http_status=200))
