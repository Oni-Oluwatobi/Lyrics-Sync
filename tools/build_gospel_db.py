"""Build a larger public-domain Gospel catalogue (.LSDB) for Lyric Sync.

    python tools/build_gospel_db.py [--cache DIR] [--out PATH] [--fetch-only]

Pipeline
--------
1. fetch   — download authorized public-domain source texts from Project
             Gutenberg into a local cache (default: %LOCALAPPDATA%/LyricSync/
             source_cache, override with --cache or LYRIC_SYNC_SOURCE_CACHE).
2. parse   — extract songs with per-record provenance; quality gates reject
             malformed blocks; nothing is fabricated or rewritten.
3. build   — copy the production catalogue read-only, append the new songs,
             rebuild the search index, write a fresh file (default:
             data/lyric_sync_gospel_next.lsdb).

The production database (lyric_sync_gospel.lsdb) is only ever read.  Writing
over it requires an explicit --out pointing at that file plus --overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROD_DB = ROOT / "lyric_sync_gospel.lsdb"
DEFAULT_OUT = ROOT / "data" / "lyric_sync_gospel_next.lsdb"
USER_AGENT = "LyricSyncCatalogueBuilder/1.0 (The Kreadive Galaxy; offline gospel catalogue)"

# --------------------------------------------------------------------------- #
# sources — every entry is a Project Gutenberg public-domain text
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Source:
    key: str
    ebook: int
    title: str
    author: str
    published: int | None
    country: str
    region: str
    artist: str
    subgenre: str
    parser: str  # function name


SOURCES: list[Source] = [
    Source("watts", 13341, "Hymns and Spiritual Songs", "Isaac Watts", 1719,
           "United Kingdom", "Europe", "Isaac Watts", "Traditional Hymn", "watts"),
    Source("chb", 46041, "The Christian Hymn Book", "A. Campbell and others", 1870,
           "United States", "North America", "Traditional", "Traditional Hymn", "chb"),
    Source("otterbein", 16455, "The Otterbein Hymnal", "Edmund S. Lorenz (compiler)", 1892,
           "United States", "North America", "Traditional", "Traditional Hymn", "otterbein"),
    Source("chapin", 20476, "Hymns for Christian Devotion", "J. G. Adams and E. H. Chapin",
           1853, "United States", "North America", "Traditional", "Traditional Hymn", "chapin"),
    Source("folk", 59884, "Spiritual Folk-Songs of Early America",
           "George Pullen Jackson (editor)", 1925,
           "United States", "North America", "Traditional", "Traditional Hymn", "folk"),
    Source("carols", 59263, "88 Favourite Carols and Hymns for Christmas",
           "Anonymous (compiler)", None,
           "United Kingdom", "Europe", "Traditional", "Christmas Hymn", "carols"),
]

# --------------------------------------------------------------------------- #
# text helpers
# --------------------------------------------------------------------------- #

SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "nor",
    "of", "on", "or", "the", "to", "with", "yet",
}


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace (catalogue norm)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def titleize(text: str) -> str:
    """Display title: sentence -> title case, small words kept low."""
    text = re.sub(r"\s+", " ", text.strip()).rstrip(".").strip('"')
    if not text:
        return text
    punct = "'\";,:"
    words = text.split(" ")
    out: list[str] = []
    for index, word in enumerate(words):
        core_word = word.strip(punct)
        if not core_word:
            out.append(word)
            continue
        lead = word[:len(word) - len(word.lstrip(punct))]
        trail = word[len(word.rstrip(punct)):]
        low = core_word.lower()
        if core_word.isupper() and len(core_word) > 1:
            base = low
        else:
            base = core_word
        if index not in (0, len(words) - 1) and low in SMALL_WORDS:
            core = low
        elif base:
            core = base[0].upper() + base[1:]
        else:
            core = base
        out.append(lead + core + trail)
    return " ".join(out)


SCRIPTURE_LINE = re.compile(r"^([A-Z][a-z]{1,9}\.?\s*\d[\d\s\.,;:\-]*)+$")


def strip_boilerplate(text: str) -> list[str]:
    """Keep only the region between the PG start/end markers when present."""
    raw = text.splitlines()
    start = 0
    for index, line in enumerate(raw):
        if line.startswith("*** START OF THE PROJECT GUTENBERG"):
            start = index + 1
            break
    end = len(raw)
    for index in range(start, len(raw)):
        if raw[index].startswith("*** END OF THE PROJECT GUTENBERG"):
            end = index
            break
    return raw[start:end]


# --------------------------------------------------------------------------- #
# shared block assembly
# --------------------------------------------------------------------------- #


@dataclass
class SongDraft:
    source: Source
    number: str
    title: str = ""
    title_from_incipit: bool = False
    songwriter: str = ""
    aliases: list[str] = field(default_factory=list)
    stanzas: list[tuple[str, list[str]]] = field(default_factory=list)
    release_year: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def first_line(self) -> str:
        for _kind, lines in self.stanzas:
            if lines:
                return lines[0]
        return ""


def split_stanzas(block: list[str], number_re: re.Pattern[str]) -> list[list[str]]:
    """Split a lyric block on blank lines, breaking at numbered stanza starts."""
    stanzas: list[list[str]] = []
    current: list[str] = []
    for line in block:
        if not line.strip():
            if current:
                stanzas.append(current)
                current = []
            continue
        match = number_re.match(line)
        if re.match(r"^\s*Chorus\s*[\.—:]", line) and current:
            stanzas.append(current)
            current = []
        if match and current:
            stanzas.append(current)
            current = []
        if match:
            piece = re.sub(r"^\[", "", line[match.end():]).strip()
            if "[" not in piece:
                piece = re.sub(r"\]$", "", piece)
            current.append(piece)
        else:
            current.append(line.strip())
    if current:
        stanzas.append(current)
    return [s for s in stanzas if s]


def label_stanzas(stanzas: list[list[str]]) -> list[tuple[str, list[str]]]:
    labelled: list[tuple[str, list[str]]] = []
    verse = 0
    for lines in stanzas:
        first = lines[0].strip("_").strip()
        if first.lower().startswith("chorus"):
            rest = lines[1:]
            strip_m = re.match(
                r"^(chorus(?:\.|:)?\s*[—–-]\s*|chorus(?:\.|:)\s+)", first, re.I
            )
            if strip_m:
                remainder = first[strip_m.end():].strip()
                if remainder:
                    rest = [remainder] + rest
            if rest:
                labelled.append(("Chorus", rest))
        else:
            verse += 1
            labelled.append((f"Verse {verse}", lines))
    return labelled


def quality_ok(draft: SongDraft) -> tuple[bool, str]:
    lines = [line for _kind, stanza in draft.stanzas for line in stanza]
    if len(lines) < 4:
        return False, "fewer than 4 lyric lines"
    if not draft.title or len(draft.title) > 120:
        return False, "bad title length"
    if re.fullmatch(r"[\s\(\)\d]+", draft.title):
        return False, "numeric title"
    letters = sum(ch.isalpha() for ch in " ".join(lines))
    if letters < 0.3 * len(" ".join(lines)):
        return False, "too few letters"
    for line in lines:
        if len(line) > 500:
            return False, "overlong line"
        if re.fullmatch(r"\[?\d{1,4}\]?", line.strip()):
            return False, "page/footnote number line"
        if "Project Gutenberg" in line:
            return False, "boilerplate line"
    return True, ""


# --------------------------------------------------------------------------- #
# parsers
# --------------------------------------------------------------------------- #


def _cut(lines: list[str], start: int, ends: list[re.Pattern[str]]) -> int:
    for index in range(start, len(lines)):
        for pattern in ends:
            if pattern.search(lines[index]):
                return index
    return len(lines)


REF_TAIL = re.compile(
    r"[,;\s]+(?:[1-3]\s+)?[A-Z][A-Za-z]+\.?\s+\d[\d\s\.,;:\-]*(?:&c)?\.?$"
)


def strip_ref_tail(text: str) -> str:
    """Remove trailing scripture-reference segments (iteratively)."""
    while True:
        stripped = REF_TAIL.sub("", text)
        if stripped == text:
            return text
        text = stripped


def parse_watts(lines: list[str], source: Source) -> list[SongDraft]:
    marker = re.compile(r"^Hymn (\d+:\d+)\.(.*)$")
    end = _cut(lines, 0, [re.compile(r"^AN INDEX\s*$"),
                          re.compile(r"^End of the Third Book")])
    starts = [i for i in range(end) if marker.match(lines[i])]
    skip = re.compile(r"^Book \d+\.?$|^Part the (first|second|third)\.?$"
                      r"|^End of\b|^Hymns\.$")
    verse_one = re.compile(r"^1(?:\s|\[)")
    verse_any = re.compile(r"^(\d{1,2})(?:\s|\[)")
    drafts: list[SongDraft] = []
    for pos, index in enumerate(starts):
        match = marker.match(lines[index])
        assert match
        block_end = starts[pos + 1] if pos + 1 < len(starts) else end
        body = lines[index + 1: block_end]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if not body:
            continue
        draft = SongDraft(source=source, number=match.group(1))
        tail = match.group(2).strip()
        if tail and not re.match(r"^\d", tail):
            draft.notes.append(tail.rstrip("."))
        cursor = 0
        verse_start = None
        for k, line in enumerate(body):
            if verse_one.match(line) and (k == 0 or not body[k - 1].strip()):
                verse_start = k
                break
            if k >= 8:
                break
        if verse_start is not None and verse_start > 0:
            header = " ".join(
                part.strip() for part in body[:verse_start] if part.strip()
            )
            if header:
                reduced = strip_ref_tail(header)
                if reduced and reduced != header:
                    draft.aliases.append(header)
                    draft.title = titleize(reduced)
                else:
                    draft.title = titleize(header)
                cursor = verse_start
        elif verse_start is None and not verse_any.match(body[0]):
            nxt = body[1].strip() if len(body) > 1 else ""
            if nxt == "" or SCRIPTURE_LINE.match(nxt):
                draft.title = titleize(body[0])
                cursor = 1
                while cursor < len(body) and SCRIPTURE_LINE.match(body[cursor].strip()):
                    draft.aliases.append(body[cursor].strip())
                    cursor += 1
        lyric_lines: list[str] = []
        for line in body[cursor:]:
            stripped = line.strip()
            if not stripped:
                lyric_lines.append("")
                continue
            if skip.match(stripped):
                continue
            text = re.sub(r"^\[", "", stripped)
            if "[" not in text:
                text = re.sub(r"\]$", "", text)
            lyric_lines.append(text)
        while lyric_lines and not lyric_lines[-1]:
            lyric_lines.pop()
        stanzas = split_stanzas(lyric_lines, re.compile(r"^(\d{1,2})[\s\[]"))
        if normalize(draft.title) == "or thus":
            draft.title = ""
        if not draft.title and stanzas and stanzas[0]:
            draft.title = titleize(stanzas[0][0])
            draft.title_from_incipit = True
        draft.stanzas = label_stanzas(stanzas)
        if draft.stanzas:
            drafts.append(draft)
    return drafts


def parse_chb(lines: list[str], source: Source) -> list[SongDraft]:
    header = re.compile(r"^(\d{1,4}) {10,}(\S.*)$")
    end = _cut(lines, 0, [re.compile(r"^\s*CONTENTS\.\s*$"),
                          re.compile(r"^\s*INDEX OF SUBJECTS\."),
                          re.compile(r"\*\*\* END OF THE PROJECT")])
    centered = re.compile(r"^ {10,}(\S.*)$")
    section = re.compile(r"^[A-Z][A-Z\s'&,.\-]{4,}\.$")
    inline = re.compile(r"^(PART|BOOK)\b")
    starts = [i for i in range(end) if header.match(lines[i])]
    drafts: list[SongDraft] = []
    for pos, index in enumerate(starts):
        block_end = starts[pos + 1] if pos + 1 < len(starts) else end
        match = header.match(lines[index])
        assert match
        draft = SongDraft(source=source, number=match.group(1))
        cursor = index + 1
        headings: list[str] = []
        while cursor < block_end:
            line = lines[cursor]
            hit = centered.match(line)
            if hit:
                headings.append(hit.group(1).strip())
                cursor += 1
                continue
            if not line.strip():
                cursor += 1
                continue
            break
        if not headings:
            continue
        draft.title = titleize(headings[0])
        draft.aliases.extend(headings[1:])
        lyric_lines: list[str] = []
        for line in lines[cursor: block_end]:
            stripped = line.strip()
            if not stripped:
                continue
            if section.match(stripped) and not inline.match(stripped):
                continue
            if inline.match(stripped):
                continue
            lyric_lines.append(line)
        stanzas = split_stanzas(lyric_lines, re.compile(r"^ {0,3}(\d{1,2})\s+\S"))
        draft.stanzas = label_stanzas(stanzas)
        if draft.stanzas:
            drafts.append(draft)
    return drafts


def parse_otto(lines: list[str], source: Source) -> list[SongDraft]:
    header = re.compile(r"^(\d{1,4})\s{5,}(\S.*)$")
    alias_line = re.compile(r"^_(.+?)_\.?\s*(?:\((\d+)\))?\s*$")
    year_re = re.compile(r"(\d{4})")
    end = _cut(lines, 0, [re.compile(r"^INDEX OF FIRST LINES\."),
                          re.compile(r"\*\*\* END OF THE PROJECT")])
    starts = [i for i in range(end) if header.match(lines[i])]
    drafts: list[SongDraft] = []
    for pos, index in enumerate(starts):
        block_end = starts[pos + 1] if pos + 1 < len(starts) else end
        match = header.match(lines[index])
        assert match
        draft = SongDraft(source=source, number=match.group(1))
        head = match.group(2).strip()
        cursor = index + 1
        while cursor < block_end and not lines[cursor].strip():
            cursor += 1
        alias_hit = alias_line.match(lines[cursor].strip()) if cursor < block_end else None
        if alias_hit:
            draft.title = titleize(alias_hit.group(1).rstrip("."))
            cursor += 1
        while cursor < block_end and not lines[cursor].strip():
            cursor += 1
        body = lines[cursor: block_end]
        caps_line = re.compile(r"^[A-Z][A-Z\s'&,.\-]{4,}\.?$")
        attribution: str | None = None
        lyric_lines: list[str] = []
        index_cursor = 0
        while index_cursor < len(body):
            raw = body[index_cursor]
            stripped = raw.strip()
            if not stripped:
                lyric_lines.append("")
                index_cursor += 1
                continue
            if caps_line.match(stripped):
                index_cursor += 1
                continue
            if re.fullmatch(r"\(\d{1,4}\)", stripped):
                index_cursor += 1
                continue
            prev_blank = index_cursor == 0 or not body[index_cursor - 1].strip()
            next_line = body[index_cursor + 1] if index_cursor + 1 < len(body) else ""
            next_blank = not next_line.strip()
            if raw[:1] == " " and len(raw) - len(raw.lstrip()) >= 5 and prev_blank and next_blank:
                year_hit = year_re.search(stripped)
                if year_hit or (stripped.endswith(".") and len(stripped) <= 45):
                    attribution = stripped
                    index_cursor += 1
                    while index_cursor < len(body) and not body[index_cursor].strip():
                        index_cursor += 1
                    continue
            lyric_lines.append(raw)
            index_cursor += 1
        while lyric_lines and not lyric_lines[-1]:
            lyric_lines.pop()
        stanzas = split_stanzas(lyric_lines, re.compile(r"^(\d{1,2})\s"))
        if not draft.title and stanzas and stanzas[0]:
            draft.title = titleize(stanzas[0][0])
            draft.title_from_incipit = True
        if attribution:
            year_hit = year_re.search(attribution)
            name = re.split(r"[,.]?\s*\d{4}", attribution)[0]
            name = re.sub(r"[.,\s]+$", "", name).strip()
            if name:
                draft.songwriter = name
            if year_hit:
                year = int(year_hit.group(1))
                draft.release_year = year if 1000 <= year <= 2000 else None
        tune = re.sub(r"\s+[A-Za-z]\.\s*M\.$|\s+[A-Z]\.\s*[A-Z]\.\s*$", "", head)
        tune = re.sub(r"\s+\d[\d,s&].*$", "", tune).strip().rstrip(". ")
        if (tune and 3 <= len(tune) <= 30 and draft.title
                and normalize(tune) != normalize(draft.title)):
            draft.aliases.append(tune)
        draft.stanzas = label_stanzas(stanzas)
        if draft.stanzas:
            drafts.append(draft)
    return drafts


def parse_chapin(lines: list[str], source: Source) -> list[SongDraft]:
    header = re.compile(r"^(\d{1,4})\.\s{2,}(\S.*)$")
    end = _cut(lines, 0, [re.compile(r"Project Gutenberg"),
                          re.compile(r"^\*{3} END OF"),
                          re.compile(r"^Section \d")])
    starts = [i for i in range(end) if header.match(lines[i])]
    meter_word = re.compile(
        r"^(\d+\.?\s*M\.?|L\.\s*M\.?|S\.\s*M\.?|C\.\s*M\.?|P\.\s*M\.?|"
        r"\d+(?:\.\d+)*\.?\s*M\.?|\d+s(?:\s*,\s*\d+s)*\.?|[A-Za-z]\.?\s*M\.?)"
    )
    person = re.compile(r"^[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?\.?$")
    collect = re.compile(r"Coll|Chapel|Psalmody|Soc|Mission|Society|Misc|Collection", re.I)
    section = re.compile(r"^[A-Z][A-Z\s'&,.\-]{4,}\.$")
    inline = re.compile(r"^(PART|BOOK)\b")
    drafts: list[SongDraft] = []
    for pos, index in enumerate(starts):
        block_end = starts[pos + 1] if pos + 1 < len(starts) else end
        match = header.match(lines[index])
        assert match
        draft = SongDraft(source=source, number=match.group(1))
        rest = match.group(2).strip()
        parts = re.split(r"\s{2,}", rest)
        note = ""
        if len(parts) >= 2:
            tail = parts[-1].strip().rstrip(".")
            if collect.search(tail):
                note = tail
            elif person.match(parts[-1].strip()):
                if tail.lower() == "anonymous":
                    draft.songwriter = "Anonymous"
                else:
                    draft.songwriter = tail
        elif parts and parts[0] and not meter_word.match(parts[0]):
            candidate = parts[0].strip().rstrip(".")
            if person.match(parts[0].strip()) and not collect.search(candidate):
                draft.songwriter = "Anonymous" if candidate.lower() == "anonymous" else candidate
        if note:
            draft.notes.append(note)
        cursor = index + 1
        title = ""
        while cursor < block_end:
            stripped = lines[cursor].strip()
            if stripped:
                title = stripped
                cursor += 1
                break
            cursor += 1
        if not title:
            continue
        draft.title = titleize(title.strip('"'))
        while cursor < block_end and not lines[cursor].strip():
            cursor += 1
        lyric_lines: list[str] = []
        for line in lines[cursor: block_end]:
            stripped = line.strip()
            if not stripped:
                lyric_lines.append("")
                continue
            if section.match(stripped) and not inline.match(stripped):
                continue
            if inline.match(stripped):
                continue
            lyric_lines.append(line)
        stanzas = split_stanzas(lyric_lines, re.compile(r"^(\d{1,2})\s{2,}"))
        draft.stanzas = label_stanzas(stanzas)
        if draft.stanzas:
            drafts.append(draft)
    return drafts


def parse_folk(lines: list[str], source: Source) -> list[SongDraft]:
    header = re.compile(r"^ {10,}No\.\s*(\d+)\s*$")
    end = _cut(lines, 0, [
        re.compile(r"^ {10,}Bibliography\s*$"),
        re.compile(r"^ {10,}List of Abbreviations of Titles\s*$"),
        re.compile(r"^ {10,}Index of Songs by Titles\s*$"),
        re.compile(r"^ {10,}Footnotes\s*$"),
        re.compile(r"\*\*\* END OF THE PROJECT"),
    ])
    starts = [i for i in range(end) if header.match(lines[i])]
    drafts: list[SongDraft] = []
    for pos, index in enumerate(starts):
        block_end = starts[pos + 1] if pos + 1 < len(starts) else end
        match = header.match(lines[index])
        assert match
        draft = SongDraft(source=source, number=match.group(1))
        lyric_lines: list[str] = []
        for line in lines[index + 1: block_end]:
            stripped = line.strip()
            if not stripped:
                lyric_lines.append("")
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent >= 10 or indent == 0:
                continue
            if stripped in ("[Music]", "Music"):
                continue
            if stripped.startswith("[") and stripped.endswith("]") and len(stripped) < 8:
                continue
            text = stripped.strip("_")
            if text.startswith("Chorus") and len(text) < 30:
                lyric_lines.append(f"      {text}")
                continue
            lyric_lines.append(text)
        stanzas = split_stanzas(lyric_lines, re.compile(r"(?!)"))
        if stanzas and stanzas[0]:
            draft.title = titleize(stanzas[0][0])
            draft.title_from_incipit = True
        draft.stanzas = label_stanzas(stanzas)
        if draft.stanzas:
            drafts.append(draft)
    return drafts


def parse_carols(lines: list[str], source: Source) -> list[SongDraft]:
    header = re.compile(r"^ {15,}(\d{1,2})\.\s*$")
    end = _cut(lines, 0, [
        re.compile(r"\*\*\* END OF THE PROJECT"),
        re.compile(r"^ {5,}Transcriber"),
    ])
    starts = [i for i in range(end) if header.match(lines[i])]
    drafts: list[SongDraft] = []
    for pos, index in enumerate(starts):
        block_end = starts[pos + 1] if pos + 1 < len(starts) else end
        match = header.match(lines[index])
        assert match
        draft = SongDraft(source=source, number=match.group(1))
        lyric_lines: list[str] = []
        for line in lines[index + 1: block_end]:
            stripped = line.strip()
            if not stripped:
                lyric_lines.append("")
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent < 2:
                continue
            lyric_lines.append(stripped)
        stanzas = split_stanzas(lyric_lines, re.compile(r"(?!)"))
        if stanzas and stanzas[0]:
            draft.title = titleize(stanzas[0][0])
            draft.title_from_incipit = True
        draft.stanzas = label_stanzas(stanzas)
        if draft.stanzas:
            drafts.append(draft)
    return drafts


PARSERS = {
    "watts": parse_watts,
    "chb": parse_chb,
    "otterbein": parse_otto,
    "chapin": parse_chapin,
    "folk": parse_folk,
    "carols": parse_carols,
}

# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #


def default_cache_dir() -> Path:
    override = os.environ.get("LYRIC_SYNC_SOURCE_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "LyricSync" / "source_cache"


def download(url: str, timeout: int = 90, tries: int = 6) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                chunks: list[bytes] = []
                while True:
                    block = response.read(65536)
                    if not block:
                        break
                    chunks.append(block)
            return b"".join(chunks)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed: {url} ({last})")


def fetch_sources(cache: Path, keys: set[str] | None = None) -> dict[int, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    fetched: dict[int, Path] = {}
    for source in SOURCES:
        if keys and source.key not in keys:
            continue
        target = cache / f"{source.ebook}.txt"
        if target.exists() and target.stat().st_size > 10_000:
            print(f"  cached  #{source.ebook} {source.title} "
                  f"({target.stat().st_size:,} bytes)")
            fetched[source.ebook] = target
            continue
        urls = [
            f"https://www.gutenberg.org/cache/epub/{source.ebook}/pg{source.ebook}.txt",
            f"https://www.gutenberg.org/files/{source.ebook}/{source.ebook}-0.txt",
            f"https://www.gutenberg.org/files/{source.ebook}/{source.ebook}.txt",
        ]
        data = b""
        for url in urls:
            try:
                data = download(url)
                if len(data) > 10_000:
                    break
            except Exception:  # noqa: BLE001
                data = b""
        if len(data) <= 10_000:
            print(f"  FAILED  #{source.ebook} {source.title}")
            continue
        target.write_bytes(data)
        print(f"  fetched #{source.ebook} {source.title} ({len(data):,} bytes)")
        fetched[source.ebook] = target
    return fetched

# --------------------------------------------------------------------------- #
# schema (mirrors the production catalogue)
# --------------------------------------------------------------------------- #

SCHEMA_SQL = """
CREATE TABLE artists (
  artist_id TEXT PRIMARY KEY,
  artist_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  country TEXT NOT NULL,
  region TEXT NOT NULL,
  genre TEXT NOT NULL,
  aliases TEXT,
  bio_snippet TEXT
);
CREATE TABLE categories (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  song_count INTEGER DEFAULT 0
);
CREATE TABLE database_metadata (
  database_name TEXT PRIMARY KEY,
  database_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  total_songs INTEGER NOT NULL,
  total_artists INTEGER NOT NULL,
  total_lyrics_records INTEGER NOT NULL,
  total_licensed_records INTEGER NOT NULL,
  total_public_domain_records INTEGER NOT NULL,
  total_metadata_only_records INTEGER NOT NULL,
  build_date TEXT NOT NULL,
  provenance_policy TEXT NOT NULL,
  copyright_policy TEXT NOT NULL,
  sha256_checksum TEXT NOT NULL,
  generated_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE songs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  artist TEXT NOT NULL,
  normalized_artist TEXT NOT NULL,
  album TEXT,
  release_year INTEGER,
  country TEXT NOT NULL,
  region TEXT NOT NULL,
  language TEXT NOT NULL,
  genre TEXT DEFAULT 'Gospel' NOT NULL,
  subgenre TEXT NOT NULL,
  song_type TEXT NOT NULL,
  songwriter TEXT NOT NULL,
  publisher TEXT NOT NULL,
  copyright_status TEXT CHECK(copyright_status IN
    ('PUBLIC_DOMAIN', 'LICENSED', 'AUTHORIZED', 'USER_IMPORTED', 'METADATA_ONLY')) NOT NULL,
  lyrics_status TEXT CHECK(lyrics_status IN
    ('FULL_LYRICS', 'PARTIAL_AUTHORIZED', 'METADATA_ONLY', 'PUBLIC_DOMAIN_TEXT')) NOT NULL,
  source TEXT NOT NULL,
  source_url TEXT,
  aliases TEXT,
  popularity_tier INTEGER DEFAULT 1,
  verified INTEGER DEFAULT 1 NOT NULL,
  verification_status TEXT DEFAULT 'VERIFIED' NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE lyrics (
  id TEXT PRIMARY KEY,
  song_id TEXT NOT NULL,
  section_order INTEGER NOT NULL,
  section_type TEXT NOT NULL,
  line_order INTEGER NOT NULL,
  text TEXT NOT NULL,
  normalized_text TEXT NOT NULL,
  language TEXT NOT NULL,
  source TEXT NOT NULL,
  copyright_status TEXT NOT NULL,
  verified INTEGER DEFAULT 1 NOT NULL,
  FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
);
CREATE TABLE lyric_search_index (
  id TEXT PRIMARY KEY,
  song_id TEXT NOT NULL,
  title TEXT NOT NULL,
  artist TEXT NOT NULL,
  aliases TEXT,
  searchable_text TEXT NOT NULL,
  FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
);
CREATE VIRTUAL TABLE lyric_search_fts USING fts5(
  song_id UNINDEXED, title, artist, aliases, lyric_fragments,
  tokenize='porter unicode61'
);
CREATE TABLE build_manifest (
  source_key TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT NOT NULL,
  published TEXT,
  ebook_id INTEGER NOT NULL,
  url TEXT NOT NULL,
  license TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  songs_parsed INTEGER DEFAULT 0,
  songs_accepted INTEGER DEFAULT 0,
  songs_skipped INTEGER DEFAULT 0
);
CREATE INDEX idx_songs_normalized_title ON songs(normalized_title);
CREATE INDEX idx_songs_normalized_artist ON songs(normalized_artist);
CREATE INDEX idx_songs_title ON songs(title);
CREATE INDEX idx_songs_artist ON songs(artist);
CREATE INDEX idx_songs_copyright_status ON songs(copyright_status);
CREATE INDEX idx_songs_country ON songs(country);
CREATE INDEX idx_songs_region ON songs(region);
CREATE INDEX idx_songs_lyrics_status ON songs(lyrics_status);
CREATE INDEX idx_lyrics_song_id ON lyrics(song_id);
CREATE INDEX idx_lyrics_normalized_text ON lyrics(normalized_text);
CREATE INDEX idx_artists_country ON artists(country);
CREATE INDEX idx_artists_normalized_name ON artists(normalized_name);
"""

PROD_SONG_COLUMNS = (
    "id", "title", "normalized_title", "artist", "normalized_artist", "album",
    "release_year", "country", "region", "language", "genre", "subgenre",
    "song_type", "songwriter", "publisher", "copyright_status", "lyrics_status",
    "source", "source_url", "aliases", "popularity_tier", "verified",
    "verification_status", "created_at", "updated_at",
)
PROD_LYRIC_COLUMNS = (
    "id", "song_id", "section_order", "section_type", "line_order", "text",
    "normalized_text", "language", "source", "copyright_status", "verified",
)
PROD_ARTIST_COLUMNS = (
    "artist_id", "artist_name", "normalized_name", "country", "region",
    "genre", "aliases", "bio_snippet",
)

# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

KNOWN_ARTISTS: dict[str, tuple[str, str]] = {
    "isaac watts": ("United Kingdom", "Europe"),
    "john newton": ("United Kingdom", "Europe"),
    "anne steel": ("United Kingdom", "Europe"),
    "charles wesley": ("United Kingdom", "Europe"),
    "thomas kelly": ("Ireland", "Europe"),
    "walter shirley": ("United Kingdom", "Europe"),
    "bernard of clairvaux": ("France", "Europe"),
    "bowring": ("United Kingdom", "Europe"),
    "newton": ("United Kingdom", "Europe"),
    "jervis": ("United Kingdom", "Europe"),
    "butcher": ("United Kingdom", "Europe"),
    "traditional": ("International", "Global"),
}
BIO_DEFAULT = ("Unattributed public-domain hymn and folk-gospel texts collected "
               "from historic public-domain hymnals.")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def open_ro(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def copy_table(
    source: sqlite3.Connection, target: sqlite3.Connection,
    table: str, columns: tuple[str, ...],
) -> int:
    rows = source.execute(
        f"SELECT {', '.join(columns)} FROM {table}"  # noqa: S608
    ).fetchall()
    placeholders = ", ".join("?" for _ in columns)
    target.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
        [tuple(row) for row in rows],
    )
    return len(rows)


def fetch_prod_first_lines(prod: sqlite3.Connection) -> set[str]:
    keys: set[str] = set()
    rows = prod.execute(
        "SELECT song_id, text FROM lyrics WHERE song_id IN ("
        "  SELECT id FROM songs WHERE copyright_status = 'PUBLIC_DOMAIN')"
        " ORDER BY song_id, section_order, line_order"
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        if row["song_id"] in seen:
            continue
        seen.add(row["song_id"])
        keys.add(normalize(row["text"]))
    return keys


def build(out_path: Path, cache: Path, overwrite: bool, report_path: Path | None) -> int:
    if not PROD_DB.is_file():
        print(f"production database not found: {PROD_DB}")
        return 1
    if out_path.resolve() == PROD_DB.resolve() and not overwrite:
        print("refusing to overwrite the production database without --overwrite")
        return 1
    if out_path.exists() and not overwrite:
        print(f"output already exists (pass --overwrite to replace): {out_path}")
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(".building")

    print("== 1/4 fetch sources ==")
    fetched = fetch_sources(cache)
    if len(fetched) < len(SOURCES):
        print(f"warning: only {len(fetched)}/{len(SOURCES)} sources available")

    print("== 2/4 parse ==")
    drafts: list[SongDraft] = []
    manifest_rows: list[tuple] = []
    rejected: dict[str, int] = {}
    per_source: dict[str, dict[str, int]] = {}
    for source in SOURCES:
        path = fetched.get(source.ebook)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = strip_boilerplate(text)
        parser = PARSERS[source.parser]
        found = parser(lines, source)
        accepted: list[SongDraft] = []
        skipped = 0
        for draft in found:
            if '"' in draft.title:
                draft.title = draft.title.replace('"', "").strip()
            if normalize(draft.title) in ("the same", "ditto") and draft.first_line:
                draft.title = titleize(draft.first_line)
            draft.title = draft.title.rstrip(",;:").strip()
            for _kind, stanza in draft.stanzas:
                for i_line, line in enumerate(stanza):
                    stanza[i_line] = re.sub(r"\s*\[\d{1,4}\]", "", line).strip()
            ok, reason = quality_ok(draft)
            if not ok:
                skipped += 1
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            accepted.append(draft)
        per_source[source.key] = {
            "parsed": len(found), "accepted": len(accepted), "skipped": skipped,
        }
        drafts.extend(accepted)
        print(f"  {source.key:10} parsed {len(found):4}  accepted {len(accepted):4}"
              f"  skipped {skipped:3}")

    prod = open_ro(PROD_DB)
    dedupe_keys = fetch_prod_first_lines(prod)
    unique: list[SongDraft] = []
    seen: dict[str, SongDraft] = {}
    duplicates = 0
    merged = 0
    for draft in drafts:
        key = normalize(draft.first_line)
        if not key:
            duplicates += 1
            continue
        if key in dedupe_keys:
            duplicates += 1
            prior = seen.get(key)
            if prior is not None:
                if not prior.songwriter and draft.songwriter:
                    prior.songwriter = draft.songwriter
                    merged += 1
                if not prior.release_year and draft.release_year:
                    prior.release_year = draft.release_year
                extra = [a for a in draft.aliases if a not in prior.aliases]
                prior.aliases.extend(extra)
            continue
        dedupe_keys.add(key)
        seen[key] = draft
        unique.append(draft)
    print(f"  quality-rejected {sum(rejected.values())}, "
          f"duplicates dropped {duplicates}, kept {len(unique)} new songs")
    if merged:
        print(f"  backfilled songwriter on {merged} duplicates")
    if rejected:
        for reason, count in sorted(rejected.items(), key=lambda item: -item[1]):
            print(f"      - {reason}: {count}")

    print("== 3/4 write database ==")
    if temp_path.exists():
        temp_path.unlink()
    target = sqlite3.connect(temp_path)
    target.executescript(SCHEMA_SQL)
    copied_songs = copy_table(prod, target, "songs", PROD_SONG_COLUMNS)
    copied_lyrics = copy_table(prod, target, "lyrics", PROD_LYRIC_COLUMNS)
    copied_artists = copy_table(prod, target, "artists", PROD_ARTIST_COLUMNS)
    copy_table(prod, target, "categories", ("id", "name", "description", "song_count"))
    copied_index = copy_table(prod, target, "lyric_search_index",
                              ("id", "song_id", "title", "artist", "aliases",
                               "searchable_text"))
    copy_table(prod, target, "lyric_search_fts",
               ("song_id", "title", "artist", "aliases", "lyric_fragments"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing_artists = {
        row["normalized_name"]: dict(row)
        for row in prod.execute("SELECT * FROM artists").fetchall()
    }
    existing_artist_ids = {
        row["artist_id"] for row in prod.execute("SELECT artist_id FROM artists").fetchall()
    }
    artist_rows_added: dict[str, tuple[str, str, str]] = {}
    used_song_ids: set[str] = set()

    song_rows: list[tuple] = []
    lyric_rows: list[tuple] = []
    index_rows: list[tuple] = []
    fts_rows: list[tuple] = []
    for draft in unique:
        source = draft.source
        artist = draft.songwriter or source.artist
        if artist.lower() == "anonymous":
            artist = "Traditional"
        base_id = f"pg_{source.key}_{draft.number.replace(':', '_')}_{slug(draft.title)[:40]}"
        song_id = base_id
        suffix = 2
        while song_id in used_song_ids:
            song_id = f"{base_id}_{suffix}"
            suffix += 1
        used_song_ids.add(song_id)
        incipits = [stanza[0] for _kind, stanza in draft.stanzas if stanza]
        alias_list = list(dict.fromkeys(draft.aliases + incipits[:8]))
        album = (f"{source.title} ({source.published})"
                 if source.published else source.title)
        provenance = (f"{source.title} ({source.published or 'n.d.'}), "
                      f"Project Gutenberg eBook #{source.ebook}")
        songwriter = draft.songwriter or (
            source.artist if source.artist != "Traditional" else "Traditional"
        )
        song_rows.append((
            song_id, draft.title, normalize(draft.title),
            artist, normalize(artist), album, draft.release_year,
            source.country, source.region, "English", "Gospel",
            source.subgenre, "Carol" if source.key == "carols" else "Hymn",
            songwriter, "Public Domain",
            "PUBLIC_DOMAIN", "PUBLIC_DOMAIN_TEXT",
            provenance, f"https://www.gutenberg.org/ebooks/{source.ebook}",
            json.dumps(alias_list), 1, 1, "VERIFIED", now, now,
        ))
        plain_lines: list[str] = []
        for section_order, (section_type, lines) in enumerate(draft.stanzas, start=1):
            for line_order, line in enumerate(lines, start=1):
                lyric_id = f"{song_id}_s{section_order}_l{line_order}"
                lyric_rows.append((
                    lyric_id, song_id, section_order, section_type, line_order,
                    line, normalize(line), "English",
                    f"Project Gutenberg eBook #{source.ebook}",
                    "PUBLIC_DOMAIN", 1,
                ))
                plain_lines.append(line)
        alias_text = " ".join(alias_list)
        searchable = " ".join([
            normalize(draft.title), normalize(artist), alias_text,
            " ".join(plain_lines), " ".join(normalize(line) for line in plain_lines),
        ])
        index_rows.append((f"idx_{song_id}", song_id, draft.title, artist,
                           alias_text, searchable))
        fragments = " ".join(plain_lines[:12])[:1000]
        fts_rows.append((song_id, draft.title, artist, alias_text, fragments))
        if normalize(artist) not in existing_artists:
            country, region = KNOWN_ARTISTS.get(
                normalize(artist), (source.country, source.region)
            )
            artist_rows_added[normalize(artist)] = (artist, country, region)

    target.executemany(
        f"INSERT INTO songs ({', '.join(PROD_SONG_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in PROD_SONG_COLUMNS)})",
        song_rows,
    )
    target.executemany(
        f"INSERT INTO lyrics ({', '.join(PROD_LYRIC_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in PROD_LYRIC_COLUMNS)})",
        lyric_rows,
    )
    target.executemany(
        "INSERT INTO lyric_search_index (id, song_id, title, artist, aliases, "
        "searchable_text) VALUES (?, ?, ?, ?, ?, ?)",
        index_rows,
    )
    target.executemany(
        "INSERT INTO lyric_search_fts (song_id, title, artist, aliases, "
        "lyric_fragments) VALUES (?, ?, ?, ?, ?)",
        fts_rows,
    )
    for norm_name, (artist, country, region) in artist_rows_added.items():
        artist_id = f"art_{slug(artist)}"
        suffix = 1
        while artist_id in existing_artist_ids:
            suffix += 1
            artist_id = f"art_{slug(artist)}_{suffix}"
        existing_artist_ids.add(artist_id)
        existing_artists[norm_name] = {"artist_id": artist_id}
        target.execute(
            "INSERT OR IGNORE INTO artists (artist_id, artist_name, normalized_name, "
            "country, region, genre, aliases, bio_snippet) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (artist_id, artist, norm_name, country, region, "Gospel", None,
             BIO_DEFAULT if artist == "Traditional" else None),
        )

    for source in SOURCES:
        stats = per_source.get(source.key)
        if stats is None:
            continue
        manifest_rows.append((
            source.key, source.title, source.author,
            str(source.published) if source.published else "unknown",
            source.ebook, f"https://www.gutenberg.org/ebooks/{source.ebook}",
            f"Public domain (United States) — Project Gutenberg eBook #{source.ebook}",
            now, stats["parsed"], stats["accepted"], stats["skipped"],
        ))
    target.executemany(
        "INSERT INTO build_manifest (source_key, title, author, published, ebook_id, "
        "url, license, retrieved_at, songs_parsed, songs_accepted, songs_skipped) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        manifest_rows,
    )

    new_hymn_songs = sum(
        per_source.get(key, {}).get("accepted", 0)
        for key in per_source if key != "carols"
    )
    new_carol_songs = per_source.get("carols", {}).get("accepted", 0)
    target.execute("UPDATE categories SET song_count = song_count + ? WHERE id = 'cat_hymns'",
                   (new_hymn_songs,))
    target.execute(
        "UPDATE categories SET song_count = song_count + ? WHERE id = 'cat_christmas_easter'",
        (new_carol_songs,),
    )

    total_songs = target.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    total_lyrics = target.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0]
    total_artists = target.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    pd_count = target.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status = 'PUBLIC_DOMAIN'"
    ).fetchone()[0]
    meta_only = target.execute(
        "SELECT COUNT(*) FROM songs WHERE copyright_status = 'METADATA_ONLY'"
    ).fetchone()[0]
    licensed = total_songs - pd_count - meta_only

    digest = hashlib.sha256()
    for row in target.execute(
        "SELECT id, title, artist FROM songs ORDER BY id"
    ).fetchall():
        digest.update("|".join(str(value) for value in row).encode("utf-8"))
    for row in target.execute(
        "SELECT song_id, section_order, line_order, text FROM lyrics "
        "ORDER BY song_id, section_order, line_order"
    ).fetchall():
        digest.update("|".join(str(value) for value in row).encode("utf-8"))
    content_hash = digest.hexdigest()

    provenance_policy = (
        "Every record carries its origin: songs.source/source_url name the "
        "public-domain edition and Project Gutenberg eBook number, "
        "lyrics.source repeats the ebook provenance per line, and the "
        "build_manifest table records license, retrieval date and yield per "
        "source. sha256_checksum is the SHA-256 of the canonical "
        "songs+lyrics dump produced by tools/build_gospel_db.py."
    )
    copyright_policy = (
        "The Kreadive Galaxy Strict Gospel Copyright Standard v3. Only texts "
        "published into the public domain (source editions dated 1719-1925, "
        "hosted by Project Gutenberg as public domain in the USA) are stored "
        "in full. Copyrighted modern worship songs remain METADATA_ONLY. "
        "No lyrics are generated, completed or paraphrased by any means. "
        "Sources: Project Gutenberg eBooks #13341, #46041, #16455, #20476, "
        "#59884, #59263 (see build_manifest)."
    )
    target.execute(
        "INSERT INTO database_metadata (database_name, database_version, "
        "schema_version, total_songs, total_artists, total_lyrics_records, "
        "total_licensed_records, total_public_domain_records, "
        "total_metadata_only_records, build_date, provenance_policy, "
        "copyright_policy, sha256_checksum, generated_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("lyric_sync_gospel.lsdb", "3.0.0", "1",
         total_songs, total_artists, total_lyrics, licensed, pd_count, meta_only,
         now, provenance_policy, copyright_policy, content_hash,
         "LyricSync catalogue builder (tools/build_gospel_db.py) — The Kreadive Galaxy"),
    )
    target.commit()
    target.execute("VACUUM")
    target.close()
    prod.close()

    if temp_path.resolve() != out_path.resolve():
        if out_path.exists():
            out_path.unlink()
        shutil.move(str(temp_path), str(out_path))

    print("== 4/4 validate ==")
    from lyric_sync.database.database_validator import validate_file

    report = validate_file(out_path, deep=True)
    print(report.to_text())
    if not report.ok:
        print("validation failed — database not accepted")
        return 1

    print("== engine smoke test ==")
    from search_engine import LyricSyncSearchEngine

    engine = LyricSyncSearchEngine(str(out_path))
    checks = [
        "amazing grace", "when peace like a river", "that saved a wretch like me",
        "hark the herald angels sing", "great is thy faithfulness", "way maker",
        "god rest you merry gentlemen", "jesus thy feast we celebrate",
        "before jehovahs awful throne", "in thy name o lord assembling",
    ]
    smoke: dict[str, list[str]] = {}
    for query in checks:
        hits = engine.search(query, limit=3)
        titles = [hit["song"]["title"] for hit in hits]
        smoke[query] = titles
        print(f"  '{query}' -> {titles if titles else 'NO HITS'}")
    engine.close()

    size = out_path.stat().st_size
    file_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()
    summary = {
        "output": str(out_path),
        "size_bytes": size,
        "file_sha256": file_hash,
        "content_sha256": content_hash,
        "build_date": now,
        "totals": {
            "songs": total_songs,
            "artists": total_artists,
            "lyric_lines": total_lyrics,
            "public_domain": pd_count,
            "metadata_only": meta_only,
            "licensed": licensed,
            "new_songs": len(song_rows),
            "new_lyric_lines": len(lyric_rows),
            "carried_over_songs": copied_songs,
            "carried_over_lyric_lines": copied_lyrics,
            "carried_over_artists": copied_artists,
            "carried_over_index_rows": copied_index,
        },
        "per_source": per_source,
        "rejected_reasons": rejected,
        "duplicates_dropped": duplicates,
        "validation": {
            "ok": report.ok,
            "errors": [check.detail for check in report.errors],
            "warnings": [check.detail for check in report.warnings],
        },
        "smoke_searches": smoke,
    }
    destination = report_path or out_path.with_suffix(".report.json")
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nnew catalogue: {out_path}  ({size:,} bytes, "
          f"{total_songs} songs / {total_lyrics} lyric lines)")
    print(f"report: {destination}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="output .LSDB path (default: data/lyric_sync_gospel_next.lsdb)")
    parser.add_argument("--cache", type=Path, default=None,
                        help="source text cache directory")
    parser.add_argument("--fetch-only", action="store_true",
                        help="download sources and stop")
    parser.add_argument("--overwrite", action="store_true",
                        help="allow writing to an existing file (required for "
                             "the production database)")
    parser.add_argument("--report", type=Path, default=None,
                        help="build report JSON path")
    args = parser.parse_args(argv)
    cache = args.cache or default_cache_dir()
    if args.fetch_only:
        fetch_sources(cache)
        return 0
    return build(args.out, cache, args.overwrite, args.report)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
