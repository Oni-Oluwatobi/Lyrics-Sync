"""Page-type detection and structural (not title-specific) song heuristics."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .htmldoc import Document, Node
from .models import BOILERPLATE_HEADING_PATTERNS

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Numbered compilation entries: "1. Silent Night", "2) Jingle Bells", "3 - Away"
NUMBERED_HEADING = re.compile(r"^\s*\d+\s*[.)\-–—]\s*\S")

# WordPress permalinks look like /2025/11/15/slug/
PERMALINK = re.compile(r"^/\d{4}/\d{2}/\d{2}/[^/]+/?$")

BOILERPLATE_RES = [re.compile(p, flags=re.I) for p in BOILERPLATE_HEADING_PATTERNS]

# Candidate containers, most specific first.
CONTAINER_SCORES = (
    ("article", 100),
    ("div", 60),
    ("section", 50),
    ("main", 40),
    ("body", 10),
)


def is_boilerplate_heading(text: str) -> bool:
    """True for site chrome / article furniture that never starts a song."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return True
    if cleaned.endswith(":") and len(cleaned) < 40:
        return True
    return any(pattern.search(cleaned) for pattern in BOILERPLATE_RES)


def is_numbered_heading(text: str) -> bool:
    return bool(NUMBERED_HEADING.match(text or ""))


def heading_text(node: Node) -> str:
    return " ".join(node.text().split())


def find_container(doc: Document) -> Node | None:
    """Best-effort main content container for a WordPress page."""
    article = doc.article
    if article is not None:
        return article
    # WordPress classic themes: div.entry-content
    for node in doc.find_all("div"):
        classes = node.classes
        if "entry-content" in classes or "post-content" in classes:
            return node
    return doc.main or doc.body


def collect_blocks(container: Node) -> list[Node]:
    """Headings, paragraphs and separators in document order."""
    wanted = HEADING_TAGS | {"p", "hr", "blockquote", "pre", "li", "hgroup"}
    return [node for node in container.iter() if node.tag in wanted]


def song_headings(blocks: list[Node]) -> list[tuple[int, Node, str]]:
    """Return ``(block_index, node, text)`` for headings that open a song.

    Two structural tiers:

    1. Numbered headings inside the container — strong compilation signal.
    2. If a page has none, any non-boilerplate ``h2``/``h3`` is used.

    Titles are never matched, so new compilations work unchanged.
    """
    candidates: list[tuple[int, Node, str]] = []
    for index, node in enumerate(blocks):
        if node.tag not in ("h2", "h3"):
            continue
        text = heading_text(node)
        if not text or is_boilerplate_heading(text):
            continue
        if is_numbered_heading(text):
            candidates.append((index, node, text))
    if candidates:
        return candidates

    fallback: list[tuple[int, Node, str]] = []
    for index, node in enumerate(blocks):
        if node.tag != "h2":
            continue
        text = heading_text(node)
        if not text or is_boilerplate_heading(text):
            continue
        fallback.append((index, node, text))
    return fallback


def detect_page_type(doc: Document, url: str) -> str:
    """Classify a page: sitemap / category / tag / archive / article / single."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path.endswith(".xml") or doc.root.first("urlset") is not None:
        return "sitemap"
    if "/category/" in path:
        return "category"
    if "/tag/" in path:
        return "tag"
    if re.search(r"/page/\d+/?$", path) or path.count("/") >= 4:
        return "archive"

    container = find_container(doc)
    if container is None:
        return "unknown"

    blocks = collect_blocks(container)
    headings = song_headings(blocks)
    has_date = bool(doc.find_all("time")) or bool(
        doc.find_all(predicate=lambda n: n.has_class("entry-date")
                     or n.has_class("post-date"))
    )
    if headings:
        return "article"
    if has_date or doc.article is not None:
        return "single"
    return "unknown"


def extract_post_links(doc: Document, base_url: str) -> list[str]:
    """Internal permalink links discovered on archive/category/listing pages."""
    from urllib.parse import urljoin

    seen: list[str] = []
    found: set[str] = set()
    for node in doc.find_all("a"):
        href = node.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc and parsed.netloc != urlparse(base_url).netloc:
            continue
        if PERMALINK.match(parsed.path or "") and absolute not in found:
            found.add(absolute)
            seen.append(absolute)
    return seen
