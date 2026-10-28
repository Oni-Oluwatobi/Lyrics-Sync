"""Minimal HTML document tree built on :mod:`html.parser`.

Only stdlib is used so the scraper adds **no** dependency to the Lyric Sync
application or to ``requirements.txt``.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Iterator

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# Elements whose stray end tag must not close an outer ancestor.
LOOSE_END_TAGS = {"p", "li", "dt", "dd", "option", "tr", "td", "th"}


class Node:
    """One element (or the document root)."""

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None,
                 parent: "Node | None" = None) -> None:
        self.tag = tag
        self.attrs: dict[str, str] = attrs or {}
        self.children: list[Node] = []
        self.parent = parent

    # -- attribute helpers -------------------------------------------------
    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def has_class(self, name: str) -> bool:
        return name in self.classes

    # -- traversal ---------------------------------------------------------
    def iter(self, include_self: bool = False) -> Iterator["Node"]:
        if include_self:
            yield self
        for child in self.children:
            if isinstance(child, str):
                continue
            yield child
            yield from child.iter()

    def find_all(
        self,
        tag: str | None = None,
        class_name: str | None = None,
        predicate=None,
    ) -> list["Node"]:
        out: list[Node] = []
        for node in self.iter():
            if tag is not None and node.tag != tag:
                continue
            if class_name is not None and not node.has_class(class_name):
                continue
            if predicate is not None and not predicate(node):
                continue
            out.append(node)
        return out

    def first(self, tag: str | None = None, class_name: str | None = None,
              predicate=None) -> "Node | None":
        found = self.find_all(tag, class_name, predicate)
        return found[0] if found else None

    # -- content -----------------------------------------------------------
    def text(self, separator: str = " ", strip: bool = True) -> str:
        parts: list[str] = []

        def walk(node: "Node") -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif child.tag in ("script", "style", "noscript"):
                    continue
                elif child.tag == "br":
                    parts.append("\n")
                else:
                    walk(child)

        walk(self)
        joined = "".join(parts) if separator == "\n" else separator.join(parts)
        joined = joined.replace("\r", "")
        return joined.strip() if strip else joined

    def text_lines(self) -> list[str]:
        """Text split into display lines (``<br>`` becomes a line break)."""
        text = self.text(separator="\n", strip=False)
        return [line.strip() for line in text.replace("\r", "").split("\n")
                if line.strip()]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Node {self.tag} {self.attrs} children={len(self.children)}>"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("[document]")
        self._stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        node = Node(tag, dict(attrs), parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        node = Node(tag, dict(attrs), parent=self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return
        # Stray end tag: ignore unless it is a "loose" container we can close.
        if tag in LOOSE_END_TAGS:
            for index in range(len(self._stack) - 1, 0, -1):
                if self._stack[index].tag == tag:
                    del self._stack[index:]
                    return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


class Document:
    """Parsed page."""

    def __init__(self, root: Node, url: str = "") -> None:
        self.root = root
        self.url = url

    def find_all(self, tag: str | None = None, class_name: str | None = None,
                 predicate=None) -> list[Node]:
        return self.root.find_all(tag, class_name, predicate)

    @property
    def title(self) -> str:
        node = self.root.first("title")
        return node.text() if node else ""

    @property
    def body(self) -> Node | None:
        return self.root.first("body")

    @property
    def article(self) -> Node | None:
        return self.root.first("article")

    @property
    def main(self) -> Node | None:
        return self.root.first("main")


def parse_html(text: str, url: str = "") -> Document:
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return Document(builder.root, url=url)
