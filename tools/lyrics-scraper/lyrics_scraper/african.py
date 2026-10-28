"""African Gospel Lyrics page parser.

One song per post.  All rules here are structural — container boundaries,
``Label:`` lines, repetition markers, language/country taxonomy — and no song
title, artist or lyric text is ever matched literally.

Boundaries: lyric paragraphs live inside ``div.post-content``; the subscribe
box (``div.wp-block-group``), sharing bar (``div.sharedaddy``), related posts,
trending lists and the comment thread sit outside it or behind a stop label,
so none of them can reach the staging database.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime

from .detect import PERMALINK, extract_post_links
from .htmldoc import Document, Node, parse_html
from .models import (
    METADATA_LABELS,
    LyricSection,
    NormalizedSong,
    ParseResult,
    RawPage,
    Warning,
)
from .parser import detect_section, display_label, is_stop_label
from .parser import KV_LABEL  # noqa: F401  (re-exported for tests)

# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #

#: Canonical spellings for language names seen in tags and declarations.
LANGUAGES: dict[str, str] = {
    "english": "English", "yoruba": "Yoruba", "igbo": "Igbo", "hausa": "Hausa",
    "swahili": "Swahili", "zulu": "Zulu", "xhosa": "Xhosa",
    "afrikaans": "Afrikaans", "akan": "Akan", "twi": "Twi", "ewe": "Ewe",
    "lingala": "Lingala", "french": "French", "portuguese": "Portuguese",
    "spanish": "Spanish", "arabic": "Arabic", "amharic": "Amharic",
    "shona": "Shona", "sotho": "Sotho", "sesotho": "Sesotho",
    "setswana": "Setswana", "tswana": "Tswana", "swati": "SiSwati",
    "tsonga": "Tsonga", "venda": "Venda", "ndebele": "Ndebele",
    "northern sotho": "Northern Sotho", "sepedi": "Sepedi",
    "south sotho": "South Sotho", "kinyarwanda": "Kinyarwanda",
    "kirundi": "Kirundi", "luganda": "Luganda", "luo": "Dholuo",
    "kikuyu": "Kikuyu", "kiswahili": "Kiswahili", "chichewa": "Chichewa",
    "nyanja": "Nyanja", "chewa": "Chewa", "bambara": "Bambara",
    "wolof": "Wolof", "fula": "Fula", "fulani": "Fula", "dagbani": "Dagbani",
    "ga": "Ga", "dagomba": "Dagomba", "efik": "Efik", "ibibio": "Ibibio",
    "urhobo": "Urhobo", "edo": "Edo", "tiv": "Tiv", "idoma": "Idoma",
    "igala": "Igala", "kanuri": "Kanuri", "south african": "English",
    "creole": "Creole", "dutch": "Dutch", "italian": "Italian",
    "german": "German", "russian": "Russian", "chinese": "Chinese",
    "hindi": "Hindi", "swiss": "German",
}

#: Country names used to separate geography from language.
COUNTRIES: dict[str, str] = {
    "nigeria": "Nigeria", "ghana": "Ghana", "kenya": "Kenya",
    "south africa": "South Africa", "tanzania": "Tanzania",
    "uganda": "Uganda", "zimbabwe": "Zimbabwe", "rwanda": "Rwanda",
    "zambia": "Zambia", "cameroon": "Cameroon", "ethiopia": "Ethiopia",
    "liberia": "Liberia", "sierra leone": "Sierra Leone",
    "senegal": "Senegal", "ivory coast": "Ivory Coast",
    "cote divoire": "Ivory Coast", "benin": "Benin", "togo": "Togo",
    "malawi": "Malawi", "botswana": "Botswana", "namibia": "Namibia",
    "mozambique": "Mozambique", "angola": "Angola", "sudan": "Sudan",
    "south sudan": "South Sudan", "somalia": "Somalia", "egypt": "Egypt",
    "morocco": "Morocco", "algeria": "Algeria", "tunisia": "Tunisia",
    "libya": "Libya", "dr congo": "DR Congo",
    "democratic republic of the congo": "DR Congo", "congo": "Congo",
    "gabon": "Gabon", "chad": "Chad", "niger": "Niger", "mali": "Mali",
    "burkina faso": "Burkina Faso", "guinea": "Guinea",
    "guinea bissau": "Guinea-Bissau", "gambia": "Gambia",
    "mauritania": "Mauritania", "madagascar": "Madagascar",
    "mauritius": "Mauritius", "seychelles": "Seychelles",
    "eritrea": "Eritrea", "djibouti": "Djibouti",
    "central african republic": "Central African Republic",
    "lesotho": "Lesotho", "eswatini": "Eswatini", "swaziland": "Eswatini",
    "cape verde": "Cape Verde", "cabo verde": "Cape Verde",
    "sao tome": "Sao Tome and Principe", "comoros": "Comoros",
    "united states": "United States", "usa": "United States",
    "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "canada": "Canada", "brazil": "Brazil", "jamaica": "Jamaica",
    "trinidad": "Trinidad and Tobago", "barbados": "Barbados",
    "france": "France", "germany": "Germany", "spain": "Spain",
    "india": "India", "australia": "Australia", "new zealand": "New Zealand",
    "caribbean": "Caribbean", "africa": "Africa",
}

#: Classes/ids that mark the end of the song body inside the container.
STOP_CLASSES = (
    "wp-block-group", "sharedaddy", "jp-relatedposts", "sd-block",
    "newsletter", "subscribe", "jp-post-flair", "comment-respond",
    "comments", "related-posts", "entry-footer",
)

SECTION_WORDS = {
    "intro", "verse", "chorus", "refrain", "bridge", "hook", "outro",
    "repeat", "pre-chorus", "prechorus", "pre chorus", "ad-lib", "ad lib",
    "ending", "interlude", "instrumental", "post-chorus", "postchorus",
}

# Trailing repetition markers: "... You x4", "... You x?"
TRAILING_X = re.compile(r"\s*[x×]\s*(?P<n>\d{1,2}|\?)\s*$", flags=re.I)
# Trailing instruction in parentheses: "... x4 (Repeat)" / "... (Refrain)"
TRAILING_PAREN = re.compile(
    r"\s*\((?P<label>[A-Za-z][A-Za-z \-/]{1,24})\)\s*$"
)
# A whole line that is just a parenthetical instruction
SOLO_PAREN = re.compile(r"^\((?P<label>[^)]{1,30})\)$")
# A whole line that is just a repetition marker
SOLO_X = re.compile(r"^[x×]\s*(?P<n>\d{1,2}|\?)$", flags=re.I)
SOLO_REPEAT = re.compile(r"^(?:repeat|repeat again|do repeat)$", flags=re.I)
# Parenthetical gloss: "Olodumare (Creator of the universe)"
GLOSS = re.compile(r"^(?P<before>.*?)\s*\((?P<gloss>[^)]{4,})\)\s*$")
# "( Languages: English, Yoruba)"
LANG_DECL = re.compile(
    r"^\(?\s*(?:languages?|lang)\s*[:：]\s*(?P<value>.+?)\s*\)?$",
    flags=re.I,
)

BYLINE_BY = re.compile(r"^(?P<title>.+?)\s+Lyrics\s+by\s+(?P<rest>.+)$",
                       flags=re.I)
BYLINE_DASH = re.compile(r"^(?P<title>.+?)\s*(?:[–—]|\s-\s)\s*(?P<rest>.+)$")
FEATURED = re.compile(r"\s+(?:ft\.?|feat\.?|featuring)\s+", flags=re.I)
AND_SPLIT = re.compile(r"\s*(?:,|;|\s+and\s+|\s+with\s+)\s+", flags=re.I)

SITE_TITLE_SUFFIX = re.compile(r"\s*[|–—-]\s*[^|–—-]*$")

CONTENT_CLASSES = ("post-content", "entry-content", "post-body",
                   "single-content", "article-content")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _meta(doc: Document, key: str) -> str:
    key = key.lower()
    for node in doc.find_all("meta"):
        name = (node.get("property") or node.get("name") or
                node.get("itemprop") or "").lower()
        if name == key:
            return (node.get("content") or "").strip()
    return ""


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text().split())


def _norm(value: str) -> str:
    out = []
    for char in (value or "").lower():
        out.append(char if char.isalnum() or char.isspace() else " ")
    return " ".join("".join(out).split())


def _iso_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y",
                "%b %d, %Y", "%d %B %Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else ""


def detect_page_type(doc: Document, url: str) -> str:
    path = urllib.parse.urlsplit(url).path or ""
    if path.endswith(".xml") or "sitemap" in path.lower():
        return "sitemap"
    if doc.find_all(class_name="post-content") or doc.find_all(
            class_name="post-title"):
        return "single"
    if PERMALINK.match(path):
        return "single"
    if doc.find_all(class_name="post-data") or doc.find_all("h2"):
        return "listing"
    return "unknown"


# --------------------------------------------------------------------------- #
# byline / title parsing
# --------------------------------------------------------------------------- #

def parse_byline(raw_title: str) -> tuple[str, list[str], list[str]]:
    """Split ``"Song Lyrics by Artist ft. Guest"``.

    Returns ``(title, artists, featured)``; the primary artist is
    ``artists[0]``.  Never matches a specific song or artist name.
    """
    title = (raw_title or "").strip()
    title = SITE_TITLE_SUFFIX.sub("", title).strip() or title

    artists: list[str] = []
    match = BYLINE_BY.match(title)
    if match:
        title = match.group("title").strip()
        artists = _split_artists(match.group("rest"))
    else:
        match = BYLINE_DASH.match(title)
        if match and len(match.group("title").strip()) > 1:
            title = match.group("title").strip()
            artists = _split_artists(match.group("rest"))

    if not artists and re.search(r"\s+Lyrics$", title, flags=re.I):
        title = re.sub(r"\s+Lyrics$", "", title, flags=re.I).strip()

    artists = [a for a in dict.fromkeys(a.strip() for a in artists) if a]
    return title, artists, artists[1:]


def _split_artists(value: str) -> list[str]:
    parts = FEATURED.split(value or "")
    out: list[str] = []
    for part in parts:
        part = part.strip(" ,;")
        if not part:
            continue
        out.extend(piece.strip() for piece in AND_SPLIT.split(part)
                   if piece.strip())
    return out


# --------------------------------------------------------------------------- #
# taxonomy
# --------------------------------------------------------------------------- #

def _classify(term: str) -> tuple[str, str] | tuple[None, None]:
    """Return ``(kind, canonical)`` when a term is a country or language."""
    key = _norm(term)
    if key in LANGUAGES:
        return "language", LANGUAGES[key]
    if key in COUNTRIES:
        return "country", COUNTRIES[key]
    return None, None


def _taxonomy(doc: Document, wrapper: Node | None,
              artists: list[str] | None = None) -> dict:
    """Split source categories/tags into meaningful buckets."""
    buckets: dict[str, list[str]] = {
        "themes": [], "countries": [], "languages": [], "artists": [],
        "other_tags": [], "categories": [], "tags": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in buckets}

    def add(bucket: str, value: str) -> None:
        key = _norm(value)
        if not key or key in seen[bucket] or value in buckets[bucket]:
            return
        buckets[bucket].append(value)
        seen[bucket].add(key)

    # post wrapper classes: category-nigeria, tag-minister-guc
    if wrapper is not None:
        for cls in wrapper.classes:
            if cls.startswith("category-"):
                add("categories", cls[len("category-"):].replace("-", " ").title())
            elif cls.startswith("tag-"):
                add("tags", cls[len("tag-"):].replace("-", " ").title())

    # anchor taxonomy (human readable, source ordered)
    data_node = None
    for node in doc.find_all(class_name="post-data"):
        data_node = node
        break
    if data_node is not None:
        for anchor in data_node.find_all("a"):
            rel = (anchor.get("rel") or "").lower()
            href = anchor.get("href") or ""
            text = _text(anchor)
            if not text or "#comments" in href or rel == "author":
                continue
            if "category" in rel:
                add("categories", text)
            elif "tag" in rel:
                add("tags", text)

    artist_keys = {_norm(name) for name in (artists or [])}
    for value in list(buckets["categories"]) + list(buckets["tags"]):
        kind, canonical = _classify(value)
        if kind == "country":
            add("countries", canonical)
        elif kind == "language":
            add("languages", canonical)

    for value in list(buckets["categories"]):
        kind, _canonical = _classify(value)
        if not kind:
            add("themes", value)
    for value in list(buckets["tags"]):
        if _norm(value) in artist_keys:
            add("artists", value)
        elif not _classify(value)[0]:
            add("other_tags", value)
    return buckets


# --------------------------------------------------------------------------- #
# line level: repetition markers, glosses
# --------------------------------------------------------------------------- #

def parse_line(raw: str) -> dict:
    """Split one source line into display text plus its instructions.

    The raw wording is never altered — repetition markers are *recorded*,
    not expanded, and parenthetical glosses are kept in ``text``.
    """
    out = {
        "text": raw,
        "raw": raw,
        "repeat": 1,
        "repeat_unknown": False,
        "marker": "",
        "target": "",
        "translation": "",
        "original_text": "",
    }
    work = raw.strip()
    if not work:
        return out

    # whole-line markers
    match = SOLO_X.match(work)
    if match:
        return _set_marker(out, work, "repeat", token=match.group("n"))
    if SOLO_REPEAT.match(work):
        return _set_marker(out, work, "repeat")
    match = SOLO_PAREN.match(work)
    if match:
        label = match.group("label").strip()
        if label.lower() in SECTION_WORDS:
            if label.lower() == "repeat":
                return _set_marker(out, work, "repeat")
            return _set_marker(out, work, "section", target=label)

    # trailing instructions: "... You x4 (Repeat)"
    match = TRAILING_PAREN.search(work)
    paren_label = ""
    if match and match.group("label").strip().lower() in SECTION_WORDS:
        paren_label = match.group("label").strip()
        work = work[:match.start()].strip()
    match = TRAILING_X.search(work)
    if match:
        token = match.group("n")
        work = work[:match.start()].strip()
        out["repeat_unknown"] = token == "?"
        out["repeat"] = 1 if token == "?" else int(token)

    if paren_label:
        if paren_label.lower() == "repeat":
            out["marker"] = "repeat"
        else:
            out["marker"] = "section"
            out["target"] = paren_label

    out["text"] = work

    # optional gloss — recorded only, source wording untouched
    gloss = GLOSS.match(out["text"])
    if gloss and not out["marker"] and len(gloss.group("gloss").split()) >= 3:
        out["translation"] = gloss.group("gloss").strip()
        out["original_text"] = gloss.group("before").strip()
    return out


def _set_marker(out: dict, raw: str, marker: str, *, token: str = "",
                target: str = "") -> dict:
    out["raw"] = raw
    out["text"] = ""
    out["marker"] = marker
    if token:
        out["repeat_unknown"] = token == "?"
        out["repeat"] = 1 if token == "?" else int(token)
    if marker == "section":
        out["target"] = target or raw.strip("() ")
    return out


# --------------------------------------------------------------------------- #
# page parsing
# --------------------------------------------------------------------------- #

def _content_container(doc: Document) -> Node | None:
    for class_name in CONTENT_CLASSES:
        found = doc.find_all(class_name=class_name)
        if found:
            return found[0]
    articles = doc.find_all("article")
    return articles[0] if articles else None


def _wrapper(doc: Document, container: Node | None) -> Node | None:
    if container is not None:
        parent = getattr(container, "parent", None)
        while parent is not None:
            if parent.tag == "div" and (parent.get("id") or "").startswith("post-"):
                return parent
            parent = getattr(parent, "parent", None)
    for node in doc.root.iter():
        if node.tag == "div" and (node.get("id") or "").startswith("post-"):
            return node
    return None


def _is_stop_node(node: Node) -> bool:
    if node.tag in ("hr",):
        return True
    classes = [cls.lower() for cls in node.classes]
    ident = (node.get("id") or "").lower()
    for stop in STOP_CLASSES:
        if any(stop in cls for cls in classes) or stop in ident:
            return True
    return False


def _metadata_from_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip().strip("()").strip()
    match = KV_LABEL.match(stripped)
    if not match:
        return None
    label = match.group("label").strip().lower()
    if label in METADATA_LABELS:
        return METADATA_LABELS[label], match.group("value").strip()
    return None


def parse_page(page: RawPage, page_type: str = "") -> ParseResult:
    """Parse one African Gospel Lyrics page into a :class:`ParseResult`."""
    doc = parse_html(page.html, url=page.final_url or page.url)
    detected = page_type or detect_page_type(doc, page.final_url or page.url)
    result = ParseResult(
        page_id=page.page_id,
        url=page.url,
        page_type=detected,
        site_title=_meta(doc, "og:site_name"),
    )
    result.links = extract_post_links(doc, page.final_url or page.url)

    if detected == "sitemap":
        result.links = [node.text().strip() for node in doc.find_all("loc")]
        return result

    published = _meta(doc, "article:published_time") or _meta(doc, "article:created")
    modified = _meta(doc, "article:modified_time")
    result.published_at = published or None
    result.modified_at = modified or None

    # ---- title / byline -------------------------------------------------
    heading = None
    for node in doc.find_all(class_name="post-title"):
        heading = node
        break
    article_title = (_meta(doc, "og:title") or _text(heading) or doc.title)
    article_title = SITE_TITLE_SUFFIX.sub("", article_title).strip() or article_title
    result.article_title = article_title
    title, artists, featured = parse_byline(article_title)

    # ---- dates / taxonomy / languages -----------------------------------
    date_text = ""
    for node in doc.find_all(class_name="post-date"):
        date_text = _text(node)
        break
    article_date = _iso_date(published) or _iso_date(date_text)

    container = _content_container(doc)
    wrapper = _wrapper(doc, container)
    buckets = _taxonomy(doc, wrapper, artists)
    post_author = ""
    if wrapper is not None:
        for node in doc.find_all("a"):
            rel = (node.get("rel") or "").lower()
            if "author" in rel and "external" in rel:
                post_author = _text(node)
                break

    languages: list[str] = []
    confidence = "unknown"
    container_children = list(container.children) if container is not None else []
    if container is None:
        # Fall back to <body> but start after the post heading so navigation
        # lists above the article never look like lyrics.
        body = doc.body or doc.root
        container_children = list(body.children)
        passed_heading = False
        for index, node in enumerate(container_children):
            if hasattr(node, "tag") and node.tag in ("h1", "h2") and (
                    node.get("class") and "post-title" in node.get("class")):
                container_children = container_children[index + 1:]
                passed_heading = True
                break
        if not passed_heading:
            container_children = []

    # ---- song body ------------------------------------------------------
    if container is None:
        result.warnings.append(Warning(
            code="missing_content_container",
            message="no post-content container found; boundary rules applied "
                    "to <body>",
            severity="warning", source_url=page.url,
        ))

    song = NormalizedSong(
        title=title,
        artists=artists or [],
        source_url=page.final_url or page.url,
        article_url=page.url,
        page_id=page.page_id,
        article_date=article_date or None,
        published_at=published or (date_text or None),
        modified_at=modified or None,
        category=", ".join(buckets["categories"]),
        tags=list(buckets["tags"]),
        taxonomy={k: v for k, v in buckets.items() if isinstance(v, list)},
        languages=languages,
        language_confidence=confidence,
        countries=list(buckets["countries"]),
    )
    if post_author:
        song.extra["post_author"] = post_author
    song.featured_artists = list(featured)
    if artists:
        song.artist = artists[0]
    result.categories = list(buckets["categories"])
    result.tags = list(buckets["tags"])

    current: LyricSection | None = None
    raw_parts: list[str] = []
    truncated_at = ""
    node_source = container_children

    for node in node_source:
        if not hasattr(node, "tag") or not node.tag:
            continue
        if node.tag in ("script", "style", "noscript", "br", "span",
                        "iframe", "object", "embed", "form", "video",
                        "audio", "svg", "figure"):
            continue
        if node.tag == "hr":
            truncated_at = "hr separator"
            break
        if _is_stop_node(node):
            truncated_at = (node.get("id") or " ".join(node.classes)
                            or node.tag)
            break

        if node.tag in ("h2", "h3", "h4", "h5"):
            heading_text = _text(node)
            if not heading_text:
                continue
            if is_stop_label(heading_text):
                truncated_at = heading_text
                break
            found = detect_section(heading_text)
            if found:
                section_type, number, label, inline = found
                current = _start_section(song, label, section_type, number)
                if inline:
                    _append(current, inline, raw_parts)
                continue
            if node.tag in ("h2", "h3") and song.sections:
                truncated_at = heading_text
                break
            continue

        if node.tag not in ("p", "li", "blockquote", "pre"):
            continue

        for index, line in enumerate(node.text_lines()):
            if not line:
                continue
            if is_stop_label(line):
                truncated_at = line
                break

            metadata = _metadata_from_line(line)
            if metadata:
                field_name, value = metadata
                _apply_metadata(song, field_name, value)
                if field_name == "language":
                    languages = song.languages
                    confidence = "explicit"
                continue

            found = detect_section(line)
            if found:
                section_type, number, label, inline = found
                current = _start_section(song, label, section_type, number)
                if inline:
                    _append(current, inline, raw_parts)
                continue

            if current is None:
                current = _start_section(song, "", "VERSE", 0)
            _append(current, line, raw_parts)
        if truncated_at:
            break

    song.sections = [section for section in song.sections if section.entries]
    song.raw_text = "\n".join(raw_parts)

    if truncated_at and not any(w.code == "truncated_at_furniture"
                                for w in result.warnings):
        # Stopping at a boundary (footer furniture, <hr>, the next song's
        # heading) is the boundary rules working as designed, so this records
        # where parsing ended for provenance — it is not a data defect and
        # must not block review.
        result.warnings.append(Warning(
            code="truncated_at_furniture",
            message=f"song body ended at page furniture: {truncated_at!r}",
            severity="info", song_title=song.title,
            source_url=song.source_url, context=truncated_at,
        ))

    # ---- language fallback from taxonomy ---------------------------------
    if not song.languages and buckets["languages"]:
        song.languages = list(buckets["languages"])
        song.language_confidence = "inferred"
    if song.languages and not song.language:
        song.language = song.languages[0]

    if song.title and song.all_lines:
        result.songs.append(song)
    elif not song.all_lines:
        result.warnings.append(Warning(
            code="missing_lyrics",
            message="page contained no lyric lines inside the content boundary",
            severity="error", song_title=song.title, source_url=page.url,
        ))
    return result


def _start_section(song: NormalizedSong, label: str, section_type: str,
                   number: int) -> LyricSection:
    section = LyricSection(
        label=label,
        section_type=section_type,
        display_label=display_label(section_type, number, label),
    )
    song.sections.append(section)
    return section


def _append(section: LyricSection, raw: str, raw_parts: list[str]) -> None:
    raw_parts.append(raw)
    parsed = parse_line(raw)
    section.append(
        parsed["text"], raw=parsed["raw"], repeat=parsed["repeat"],
        repeat_unknown=parsed["repeat_unknown"], marker=parsed["marker"],
        target=parsed["target"], translation=parsed["translation"],
        original_text=parsed["original_text"],
    )


def _apply_metadata(song: NormalizedSong, field_name: str, value: str) -> None:
    if not value:
        return
    if field_name == "language":
        parts = [part.strip() for part in
                 re.split(r"[,/|&]|\band\b", value) if part.strip()]
        for part in parts:
            canonical = LANGUAGES.get(_norm(part), part)
            if canonical not in song.languages:
                song.languages.append(canonical)
        if song.languages:
            song.language = song.languages[0]
            song.language_confidence = "explicit"
        return
    if field_name == "artist":
        parsed = [part for part in _split_artists(value) if part]
        if parsed:
            song.artists = parsed
            song.featured_artists = parsed[1:]
        return
    if field_name == "year":
        song.year = value
        return
    if field_name == "key":
        song.key_name = value
        return
    if field_name == "chords":
        song.chords = value
        return
    if field_name == "category":
        existing = [part.strip() for part in (song.category or "").split(",")]
        for part in value.split(","):
            part = part.strip()
            if part and part not in existing:
                existing.append(part)
        song.category = ", ".join(part for part in existing if part)
        return
    current = getattr(song, field_name, None)
    if not current:
        setattr(song, field_name, value)
