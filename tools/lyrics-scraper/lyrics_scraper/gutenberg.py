"""Project Gutenberg hymn-book parser.

A Gutenberg "page" is an entire public-domain hymn book — plain text (``.txt``)
or the generated HTML (``-h.htm``).  One book yields one song per hymn, so a
single fetch stages 500-1300 records.

Everything here is structural.  Three print layouts are recognised by *shape*,
never by book name:

``chb``  The Christian Hymn Book — header ``{N}`` + spaces + metre, right
         aligned to column 70; two blank lines before every header; title is
         the first centred line after it.
``bh``   A Book of Hymns — header ``{N}.`` + spaces + metre + author, right
         aligned to column 72; four blank lines before every header; centred
         title below.
``otb``  The Otterbein Hymnal — header ``{N}`` + exactly five spaces + tune;
         italic ``_Title._`` line below; indented author line before the next
         header.

The HTML flavour (``<div id="cN" class="hymn">``) is recognised first because
it carries per-hymn authors the plain text of some books omits.
"""

from __future__ import annotations

import re

from .models import LyricSection, NormalizedSong, ParseResult, RawPage, Warning
from .parser import display_label

# --------------------------------------------------------------------------- #
# body bounds
# --------------------------------------------------------------------------- #

START_MARKER = re.compile(
    r"^\s*\*\*\*\s*START OF THE PROJECT GUTENBERG EBOOK\s+(.+?)\s*\*\*\*",
    flags=re.I,
)
END_MARKER = re.compile(r"^\s*\*\*\*\s*END OF THE PROJECT GUTENBERG EBOOK",
                        flags=re.I)
BACK_MATTER = re.compile(
    r"^\s*(?:INDEX OF FIRST LINES\.?|INDEX OF SUBJECTS\.?|CONTENTS\.?|"
    r"TRANSCRIBER'?S NOTES)\s*$",
    flags=re.I,
)


# --------------------------------------------------------------------------- #
# print layouts
# --------------------------------------------------------------------------- #

class Profile:
    """One print layout: how to spot a hymn header and a stanza number."""

    def __init__(self, key: str, header: re.Pattern, min_blank: int,
                 stanza: re.Pattern, fixed_width: int | None = None):
        self.key = key
        self.header = header
        self.min_blank = min_blank
        self.stanza = stanza
        self.fixed_width = fixed_width

    def is_header(self, line: str) -> int | None:
        """Hymn number when ``line`` is a header for this layout, else None."""
        if self.fixed_width is not None and len(line) != self.fixed_width:
            return None
        match = self.header.match(line)
        return int(match.group(1)) if match else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Profile({self.key!r})"


PROFILES: tuple[Profile, ...] = (
    Profile("chb", re.compile(r"^(\d{1,4}) {5,}\S"), 2,
            re.compile(r"^  (\d{1,2}) "), fixed_width=70),
    Profile("bh", re.compile(r"^(\d{1,3})\.(?:\s|$)"), 4,
            re.compile(r"^  (\d{1,2})\s+")),
    Profile("otb", re.compile(r"^(\d{1,3}) {4,6}\S"), 1,
            re.compile(r"^(\d{1,2}) ")),
)


# --------------------------------------------------------------------------- #
# furniture
# --------------------------------------------------------------------------- #

SECTION_HEADING = re.compile(r"^\s{8,}[A-Z][A-Z0-9:;,'\-. ]{3,}$")
CHORUS_MARKER = re.compile(r"^\s{6,}CHORUS\.?\s*$", flags=re.I)
PART_MARKER = re.compile(r"^\s*PART (?:FIRST|SECOND|THIRD|FOURTH)\.?\s*$", flags=re.I)
INLINE_CHORUS = re.compile(
    r"^(?:Cho\.?--|Chorus\.?--|Refrain\.?--|Ref\.?--)\s*(?P<rest>.*)$", flags=re.I)
ITALIC_TITLE = re.compile(r"^_(?P<title>.+?)_\s*(?:\((?P<ref>\d+)\)\s*)?$")
TRAILING_REF = re.compile(r"\s*\(\d{1,4}\)\s*$")
CHORUS_SENTINEL = "__CHORUS__"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _clean_title(text: str) -> str:
    """Strip print decoration from a title line, keeping its wording."""
    title = " ".join((text or "").split())
    match = ITALIC_TITLE.match(title)
    title = match.group("title").strip() if match else title.strip("_")
    title = TRAILING_REF.sub("", title).strip()
    return title.strip(" .").strip() or title.strip()


def _blank_run(lines: list[str], index: int) -> int:
    run, cursor = 0, index - 1
    while cursor >= 0 and not lines[cursor].strip():
        run += 1
        cursor -= 1
    return run


def _decode(fragment: str) -> str:
    """Flatten an HTML fragment to plain text (entities and tags gone)."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = re.sub(r"&nbsp;|&#160;", " ", text, flags=re.I)
    text = re.sub(r"&#?\w+;", " ", text)
    return " ".join(text.split())


# --------------------------------------------------------------------------- #
# body bounds and block splitting
# --------------------------------------------------------------------------- #

def _body_lines(text: str) -> tuple[list[str], str]:
    """Return ``(lines, book_title)`` restricted to the Gutenberg body."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title, start, end = "", 0, len(lines)
    for index, line in enumerate(lines):
        match = START_MARKER.match(line)
        if match:
            title, start = match.group(1).strip(), index + 1
        elif end == len(lines) and index > start and END_MARKER.match(line):
            end = index
    return lines[start:end], title


def detect_profile(lines: list[str]) -> Profile:
    """Pick the print layout by counting header candidates in the body."""
    best, best_hits = PROFILES[0], -1
    for profile in PROFILES:
        hits = sum(1 for line in lines if profile.is_header(line) is not None)
        if hits > best_hits:
            best, best_hits = profile, hits
    return best


def _split_blocks(lines: list[str], profile: Profile) -> list[tuple[int, str, list[str]]]:
    """Return ``(number, header_line, block)`` for every hymn in the body.

    Scanning starts at the header numbered 1 so a preface, table of contents
    or front index that happens to contain a matching line never enters the
    body, and stops at the first back-matter heading.
    """
    numbered_one = [index for index, line in enumerate(lines)
                    if profile.is_header(line) == 1]
    if not numbered_one:
        return []
    first = next((index for index in numbered_one
                  if _blank_run(lines, index) >= profile.min_blank), None)
    if first is None:
        first = numbered_one[0]
    stop = next(
        (index for index in range(first + 1, len(lines))
         if BACK_MATTER.match(lines[index])),
        len(lines),
    )

    starts: list[tuple[int, int, str]] = []
    for index in range(first, stop):
        number = profile.is_header(lines[index])
        if number is None:
            continue
        if starts and number == 1:
            break
        if starts and _blank_run(lines, index) < profile.min_blank:
            continue
        starts.append((number, index, lines[index]))

    out: list[tuple[int, str, list[str]]] = []
    for position, (number, index, header) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else stop
        out.append((number, header, lines[index + 1:end]))
    return out


def _header_parts(line: str, profile: Profile) -> tuple[str, str]:
    """Return ``(metre_or_tune, author)`` carried on a header line."""
    parts = [part for part in re.split(r"\s{2,}", line.strip()) if part]
    if profile.key == "bh" and len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) >= 2:
        return parts[1], ""
    return "", ""


def _index_authors(lines: list[str]) -> dict[int, str]:
    """Hymn number → author from an ``INDEX OF FIRST LINES`` appendix."""
    start = next(
        (index for index, line in enumerate(lines)
         if re.match(r"^\s*INDEX OF FIRST LINES", line, flags=re.I)),
        None,
    )
    if start is None:
        return {}
    pattern = re.compile(
        r"^\s{0,4}.+?\s{2,}_(?P<author>[^_]+)_\s+(?P<number>\d{1,4})\s*$")
    out: dict[int, str] = {}
    for line in lines[start:]:
        match = pattern.match(line.rstrip())
        if not match:
            continue
        out.setdefault(int(match.group("number")),
                       match.group("author").strip().rstrip("."))
    return out


# --------------------------------------------------------------------------- #
# one hymn body
# --------------------------------------------------------------------------- #

#: A printed credit reads as a name: a capitalised word after the first, or a
#: year.  Without this, the closing line of a short chant looks like a byline.
CREDIT_NAME = re.compile(r"\s[A-Z][A-Za-z]")
CREDIT_YEAR = re.compile(r",?\s+\d{1,4}\.?$")
CREDIT_NOT_LYRIC = {"amen", "amen.", "selah", "selah."}


def _looks_like_credit(line: str) -> bool:
    words = line.split()
    if not words or len(words) > 10:
        return False
    if line.lower() in CREDIT_NOT_LYRIC:
        return False
    if CREDIT_YEAR.search(line) or CREDIT_NAME.search(" " + line):
        return True
    return all(word[:1].isupper() for word in words if word.strip(".,;:"))


def _tail_author(block: list[str]) -> tuple[str, int]:
    """Author credit printed after the last stanza.

    Returns ``(author, block_index)`` where ``block_index`` is where the
    credit starts; every line from there on is dropped from the lyrics.  The
    credit is the last non-blank line, indented, short and name-shaped, and
    may run to two lines for translator pairs.
    """
    non_blank = [index for index, line in enumerate(block) if line.strip()]
    if len(non_blank) < 3:
        return "", len(block)
    credit: list[int] = []
    for index in reversed(non_blank[-4:]):
        line = block[index].strip()
        if (_indent(block[index]) >= 4 and len(line) <= 72
                and line.endswith(".") and _looks_like_credit(line)):
            credit.insert(0, index)
            if len(credit) == 2:
                break
            continue
        break
    if not credit:
        return "", len(block)
    return " / ".join(block[index].strip() for index in credit), credit[0]


def _hymn_body(block: list[str], title_index: int | None, end: int) -> list[str]:
    """Furniture-free lyric lines for one hymn; blanks separate stanzas."""
    body = block[:end]
    if title_index is not None:
        body = body[title_index + 1:]

    out: list[str] = []
    skipping_head = title_index is not None
    for raw in body:
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        if skipping_head:
            if _indent(line) >= 8:
                continue
            skipping_head = False
        if "|" in line and not line.strip(" |"):
            continue
        if PART_MARKER.match(line.strip()):
            continue
        # a centred CHORUS. marker introduces the next stanza, so it must be
        # tested before the general centred-heading filter swallows it
        if CHORUS_MARKER.match(line):
            if out and out[-1].strip():
                out.append("")
            out.append(CHORUS_SENTINEL)
            out.append("")
            continue
        if SECTION_HEADING.match(line) and line.strip().isupper():
            continue
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _stanzas(lines: list[str]) -> list[list[str]]:
    grouped: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                grouped.append(current)
                current = []
            continue
        if line.strip() == CHORUS_SENTINEL:
            if current:
                grouped.append(current)
                current = []
            grouped.append([CHORUS_SENTINEL])
            continue
        current.append(line)
    if current:
        grouped.append(current)
    return grouped


def _hymn_url(url: str, number: int) -> str:
    """A stable per-hymn address.

    A book is one page holding hundreds of songs.  Without a fragment every
    hymn after the first looks like "the same source URL" to the deduplicator
    and would be merged away, so each song carries the number that locates it.
    """
    return f"{url}#hymn-{number}" if url else ""


def _build_song(number: int, block: list[str], header_line: str,
                profile: Profile, *, url: str, page_id: str,
                book_title: str, index_authors: dict[int, str]
                ) -> tuple[NormalizedSong | None, list[Warning]]:
    warnings: list[Warning] = []

    # ---- title -----------------------------------------------------------
    title_index: int | None = None
    for index, line in enumerate(block[:6]):
        if not line.strip():
            continue
        stripped = line.strip()
        candidate = (ITALIC_TITLE.match(stripped) is not None
                     if profile.key == "otb" else _indent(line) >= 8)
        if candidate:
            title_index = index
        break
    title = _clean_title(block[title_index]) if title_index is not None else ""

    # ---- author ----------------------------------------------------------
    author = ""
    if profile.key == "bh":
        author = _header_parts(header_line, profile)[1]
    tail_author, tail_start = _tail_author(block)
    if not author and tail_author and profile.key == "otb":
        author = tail_author
    author = author.strip().lstrip("*").strip()
    if not author:
        author = index_authors.get(number, "")

    # ---- lyrics ----------------------------------------------------------
    end = tail_start if (profile.key == "otb" and tail_author) else len(block)
    body = _hymn_body(block, title_index, end)

    if not title:
        for line in body:
            if line.strip() and line.strip() != CHORUS_SENTINEL:
                title = _clean_title(_strip_stanza_number(line, profile)[0])
                break
    if not title:
        title = f"{book_title or 'Hymn'} #{number}"

    song = NormalizedSong(
        title=title,
        artists=[],
        source_url=_hymn_url(url, number),
        article_url=url,
        page_id=page_id,
        author=author or None,
        category="Hymnal",
        extra={"book": book_title, "hymn_number": number, "layout": profile.key},
    )
    if profile.key == "otb":
        tune, _ = _header_parts(header_line, profile)
        if tune:
            song.extra["tune"] = tune
    else:
        metre, _ = _header_parts(header_line, profile)
        if metre:
            song.extra["metre"] = metre

    # ---- stanzas ---------------------------------------------------------
    cursor, chorus_next = 0, False
    for stanza in _stanzas(body):
        if stanza == [CHORUS_SENTINEL]:
            chorus_next = True
            continue
        is_chorus = chorus_next
        chorus_next = False
        section_type = "CHORUS" if is_chorus else "VERSE"
        cursor += 1
        label = "Chorus" if is_chorus else f"Stanza {cursor}"
        section = LyricSection(
            label=label, section_type=section_type,
            display_label="Chorus" if is_chorus else display_label("VERSE", cursor, label),
        )
        stanza_number: int | None = None
        for line in stanza:
            text, parsed = _strip_stanza_number(line, profile)
            if parsed is not None:
                stanza_number = parsed
            inline = INLINE_CHORUS.match(text.strip())
            if inline:
                section.section_type = "CHORUS"
                section.display_label = "Chorus"
                text = inline.group("rest")
            section.append(text.strip(), raw=line.strip())
        if stanza_number is not None and section.section_type == "VERSE":
            section.display_label = f"Verse {stanza_number}"
        if section.entries:
            song.sections.append(section)

    if not song.sections:
        warnings.append(Warning(
            code="missing_lyrics",
            message=f"hymn {number} produced no lyric lines",
            severity="error", song_title=title, source_url=url,
        ))
        return None, warnings

    song.raw_text = "\n".join(song.clean_lines)
    return song, warnings


def _strip_stanza_number(line: str, profile: Profile) -> tuple[str, int | None]:
    match = profile.stanza.match(line)
    if not match:
        return line, None
    return line[match.end():], int(match.group(1))


# --------------------------------------------------------------------------- #
# HTML shape
# --------------------------------------------------------------------------- #

HTML_HYMN = re.compile(r'<div id="c(?P<number>\d+)" class="hymn">')
HTML_TTL = re.compile(r'<p class="ttl">(.*?)</p>', flags=re.S)
HTML_METER = re.compile(r'<p class="meter">(.*?)</p>', flags=re.S)
HTML_AUTHOR = re.compile(r'<div class="author">(.*?)</div>', flags=re.S)
HTML_VERSE = re.compile(r'<div class="verse">(.*?)</div>', flags=re.S)
HTML_PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", flags=re.S)
HTML_VN = re.compile(r'<span class="(?:vn|hst)">.*?</span>', flags=re.S)
HTML_TITLE = re.compile(r"<title>(.*?)</title>", flags=re.S | re.I)
#: Scripture reference parked to the right of a title — metadata, not title.
HTML_TAIL_REF = re.compile(r'<span class="(?:rightish|scripRef|hst)">.*?</span>',
                           flags=re.S)


def parse_html_book(text: str, *, url: str, page_id: str) -> tuple[list[NormalizedSong], str]:
    """Songs from a ``<div id="cN" class="hymn">`` Gutenberg HTML book."""
    book = ""
    match = HTML_TITLE.search(text)
    if match:
        book = _decode(match.group(1))

    matches = list(HTML_HYMN.finditer(text))
    songs: list[NormalizedSong] = []
    for position, hit in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        fragment = text[hit.start():end]
        number = int(hit.group("number"))

        title = ""
        ttl = HTML_TTL.search(fragment)
        if ttl:
            title = _clean_title(_decode(HTML_TAIL_REF.sub("", ttl.group(1))))
        meter = _decode(HTML_METER.search(fragment).group(1)) if HTML_METER.search(fragment) else ""
        author_hit = HTML_AUTHOR.search(fragment)
        author = _decode(author_hit.group(1)) if author_hit else ""

        song = NormalizedSong(
            title=title or f"Hymn {number}",
            artists=[],
            source_url=_hymn_url(url, number),
            article_url=url,
            page_id=page_id,
            author=author or None,
            category="Hymnal",
            extra={"book": book, "hymn_number": number, "layout": "html",
                   "metre": meter},
        )
        for verse in HTML_VERSE.findall(fragment):
            section = LyricSection(label="Stanza", section_type="VERSE",
                                   display_label="Verse")
            for para in HTML_PARA.findall(verse):
                line = _decode(HTML_VN.sub("", para))
                if line:
                    section.append(line, raw=line)
            if section.entries:
                song.sections.append(section)
        if not song.sections:
            continue
        for index, section in enumerate(song.sections, start=1):
            if section.section_type == "VERSE":
                section.display_label = f"Verse {index}"
                section.label = f"Stanza {index}"
        song.raw_text = "\n".join(song.clean_lines)
        songs.append(song)
    return songs, book


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def parse_page(page: RawPage, page_type: str = "") -> ParseResult:
    """Parse one Gutenberg book (plain text or generated HTML)."""
    text = page.html or ""
    url = page.final_url or page.url
    result = ParseResult(page_id=page.page_id, url=url,
                         page_type=page_type or "book")

    if 'class="hymn"' in text:
        songs, book = parse_html_book(text, url=url, page_id=page.page_id)
        result.article_title = book
        result.songs = songs
        for song in songs:
            song.article_url = url
            song.page_id = page.page_id
        if not songs:
            result.warnings.append(Warning(
                code="no_hymns_found", severity="error", source_url=url,
                message="HTML book had no div.hymn blocks with verses",
            ))
        return result

    lines, book_title = _body_lines(text)
    if not book_title:
        match = START_MARKER.search(text)
        book_title = match.group(1).strip() if match else ""
    result.article_title = book_title

    profile = detect_profile(lines)
    blocks = _split_blocks(lines, profile)
    if not blocks:
        result.warnings.append(Warning(
            code="no_hymns_found", severity="error", source_url=url,
            message="no hymn headers matched any known print layout "
                    f"(profile={profile.key})",
        ))
        return result

    index_authors = _index_authors(lines)
    for number, header, block in blocks:
        song, warnings = _build_song(
            number, block, header, profile, url=url, page_id=page.page_id,
            book_title=book_title, index_authors=index_authors)
        result.warnings.extend(warnings)
        if song is not None:
            result.songs.append(song)
    return result


__all__ = ["detect_profile", "parse_html_book", "parse_page"]
