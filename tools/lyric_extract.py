"""Lyric extraction library: pull clean lyric text out of PDF hymn sheets and
TXT lyric files, ready for the USER_IMPORTED database pipeline.

Pure standard library — no PDF packages required (the build shell has no
internet). Handles the two real-world formats in this product:

* PDF hymn sheets (e.g. HymnServeAllLyrics/*.pdf): Flate/ASCII85 content
  streams, literal (WinAnsi) text strings, TJ kerning arrays, positioning
  operators. Stanza breaks are recovered from vertical spacing; binary/font
  noise is filtered by a vowel+word heuristic.
* TXT lyric files (e.g. Gospel_Batch_SongPack*/txt/*.txt): "TITLE - ARTIST"
  header, Source:/Published: lines, "===" separators, [Verse]/[Chorus]
  markers, and bare ALL-CAPS label lines ("VERSE", "CHORUS/CHOIR").

Also derives title/artist hints from filenames (CamelCase or underscored),
with optional matching against known artist names.

Developer tooling (tools/). The application itself never imports this.
Preview any file:  python tools/lyric_extract.py path/to/song.pdf --full
"""
from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# PDF internals
# ---------------------------------------------------------------------------

_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def _inflate(stream: bytes) -> bytes:
    """Best-effort decode of a PDF stream (Flate, ASCII85+Flate, or raw)."""
    for attempt in (
        lambda s: zlib.decompress(s),
        lambda s: zlib.decompress(s.strip(b"\r\n")),
        lambda s: zlib.decompress(base64.a85decode(s, adobe=True)),
        lambda s: zlib.decompress(base64.a85decode(s.strip(b"\r\n"), adobe=True)),
    ):
        try:
            return attempt(stream)
        except Exception:  # noqa: BLE001 - try the next decoding
            continue
    return stream


def _scan_events(content: bytes) -> list[tuple[str, object, object]]:
    """Walk a content stream, yielding events:

    ("STR", y, text_bytes)  — a show-text string at vertical position ``y``
    ("MOVE", y, None)       — a positioning operator moved the pen to ``y``
    ("GAP", None, None)     — a TJ kerning gap wide enough to be a word space

    ``y`` is None until the first positioning operator is seen.
    """
    events: list[tuple[str, object, object]] = []
    i, n = 0, len(content)
    array_depth = 0
    array_gap = False
    y: float | None = None
    nums: list[float] = []

    while i < n:
        b = content[i]
        if b == 0x28:  # (
            j = i + 1
            depth = 1
            buf = bytearray()
            while j < n and depth:
                c = content[j]
                if c == 0x5C:  # backslash
                    nxt = content[j + 1 : j + 2]
                    mapping = {b"n": b"\n", b"r": b"\r", b"t": b"\t",
                               b"(": b"(", b")": b")", b"\\": b"\\"}
                    if nxt in mapping:
                        buf += mapping[nxt]
                        j += 2
                    elif nxt and nxt in b"01234567":
                        k = j + 1
                        octal = b""
                        while k < n and content[k : k + 1] in b"01234567" and len(octal) < 3:
                            octal += content[k : k + 1]
                            k += 1
                        buf.append(int(octal, 8) & 0xFF)
                        j = k
                    else:
                        buf += nxt
                        j += 2
                elif c == 0x28:
                    depth += 1
                    buf.append(c)
                    j += 1
                elif c == 0x29:
                    depth -= 1
                    if depth:
                        buf.append(c)
                    j += 1
                else:
                    buf.append(c)
                    j += 1
            events.append(("STR", y, bytes(buf)))
            i = j
        elif b == 0x5B:  # [
            array_depth += 1
            array_gap = False
            i += 1
        elif b == 0x5D:  # ]
            if array_depth and array_gap:
                events.append(("GAP", None, None))
            array_depth = max(0, array_depth - 1)
            i += 1
        elif content[i : i + 2] in (b"Td", b"TD"):
            ty = nums[-1] if len(nums) >= 2 else (-12.0 if nums else 0.0)
            if y is None:
                y = 0.0
            y = y + ty
            if abs(ty) > 0.5:  # same-line repositioning is not a line break
                events.append(("MOVE", y, None))
            nums = []
            i += 2
        elif content[i : i + 2] == b"Tm":
            if len(nums) >= 6:
                new_y = nums[-1]
                if y is None or abs(new_y - y) > 0.5:
                    events.append(("MOVE", new_y, None))
                y = new_y
            nums = []
            i += 2
        elif content[i : i + 2] == b"T*":
            if y is None:
                y = 0.0
            y = y - 12.0  # nominal leading; real gaps carry the signal
            events.append(("MOVE", y, None))
            nums = []
            i += 2
        elif b in b"'\"":
            if y is None:
                y = 0.0
            y = y - 12.0
            events.append(("MOVE", y, None))
            nums = []
            i += 1
        elif b in b"-+.0123456789":
            j = i + 1
            while j < n and content[j : j + 1] in b"0123456789.eE+-":
                j += 1
            token = content[i:j]
            if re.fullmatch(rb"[-+]?[0-9]*\.?[0-9]+", token):
                value = float(token)
                if array_depth and value <= -120:  # thousandths of an em
                    array_gap = True
                else:
                    nums.append(value)
                i = j
                continue
            i += 1  # stray symbol; step over
        else:
            if b not in b" \t\r\n":
                nums = []
            i += 1
    return events


def _events_to_lines(events: list[tuple[str, object, object]]) -> list[str]:
    """Turn scan events into text lines; large vertical gaps -> blank lines."""
    # First pass: measure the most common downward step = line height.
    steps: list[float] = []
    prev_y: float | None = None
    for kind, y, _payload in events:
        if isinstance(y, (int, float)):
            if prev_y is not None:
                dy = prev_y - float(y)
                if 1 <= dy <= 200:
                    steps.append(dy)
            prev_y = float(y)
    line_h = 12.0
    if steps:
        ordered = sorted(steps)
        line_h = ordered[len(ordered) // 2] or 12.0  # median
    stanza_h = line_h * 1.55

    lines: list[str] = []
    current = ""
    last_y: float | None = None

    def flush(dy: float | None) -> None:
        nonlocal current
        if current.strip():
            lines.append(re.sub(r"[ \t]+", " ", current.strip()))
            current = ""
            if dy is not None and dy >= stanza_h:
                lines.append("")

    for kind, y, payload in events:
        if kind == "GAP":
            if current and not current.endswith(" "):
                current += " "
        elif kind == "MOVE":
            dy = None
            if last_y is not None and isinstance(y, (int, float)):
                dy = last_y - float(y)
            flush(dy)
            if isinstance(y, (int, float)):
                last_y = float(y)
        else:  # STR
            text = (payload or b"").decode("cp1252", "replace")
            if not text.strip() and not current.strip():
                # Whitespace-only string on its own line position:
                # this PDF format marks empty paragraphs this way.
                if lines and lines[-1] != "":
                    lines.append("")
            else:
                current += text
            if isinstance(y, (int, float)):
                last_y = float(y)
    flush(None)
    return lines


def pdf_to_lines(path: str | Path) -> list[str]:
    """Extract raw text lines from a PDF (best effort, order preserved)."""
    data = Path(path).read_bytes()
    lines: list[str] = []
    for match in _STREAM_RE.finditer(data):
        content = _inflate(match.group(1))
        if b"BT" not in content and b"Tj" not in content and b"TJ" not in content:
            continue
        if b"\x00" in content[:200] and b"Tj" not in content and b"TJ" not in content:
            continue  # binary (font) data, not page content
        stream_lines = _events_to_lines(_scan_events(content))
        if stream_lines:
            if lines:
                lines.append("")  # page/stream boundary ~ stanza break
            lines.extend(stream_lines)
    return lines


# ---------------------------------------------------------------------------
# Shared cleaning
# ---------------------------------------------------------------------------

_NOISE_PREFIX = re.compile(
    r"^(source|published|copyright|last updated|page|author)\b"
    r"|^(written|composed|arranged|adapted)\s+by\b"
    r"|^(words|lyrics|music|tune)\s+(by|and)\b",
    re.I,
)
_NOISE_PATTERNS = (
    re.compile(r"^[=\-_*#~]+$"),                       # === separators
    re.compile(r"^https?://\S+$"),                     # bare URLs
    re.compile(r"\.(docx?|pdf)\s*/\s*\d+\s*$", re.I),  # "file.docx / 1" headers
    re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.I),   # "Page 1 of 2"
    re.compile(r"^\d{1,3}$"),                          # bare page/hymn numbers
    re.compile(r"^[\W_]+$"),                           # symbol-only lines
    re.compile(r"^\s*(©|\(c\))", re.I),                # ©1988 BMG Songs …
    re.compile(r"\bCCLI\b", re.I),                     # CCLI#41099 registration
    re.compile(r"\bp\.?\s*o\.?\s+box\b", re.I),        # mailing addresses
)
_LABEL_LINE = re.compile(
    r"^(verse|chorus|choir|bridge|vamp|outro|intro|interlude|refrain|hook|"
    r"pre[- ]?chorus|post[- ]?chorus|ad[- ]?libs?|tag|ending)(\s*/\s*[\w &]+)?"
    r"(\s+\d+)?$",
    re.I,
)
_LEADING_VERSE_NUM = re.compile(r"^\s*\d{1,2}\s*[.)]\s+")


_TEXT_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " .,;:!?-'\"()[]{}/&%$#@*+=<>~`|\\^_"
)
_TEXT_EXTRA = set("’‘“”–—…èéêëíîïòóôöùúûüñçãáàåæœß¡¿")  # typographic/accented

def _is_lyricish(line: str) -> bool:
    """Filter font/binary junk: real words, vowels, and mostly-normal text."""
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 4:
        return False
    if not any(len(w) >= 3 for w in re.findall(r"[^\W\d_]+", line, re.UNICODE)):
        return False
    vowels = sum(1 for c in letters if c.lower() in "aeiouy")
    if vowels / len(letters) < 0.15:
        return False
    # Font binaries decode to a scatter of exotic codepoints; real lyric
    # lines are overwhelmingly ASCII plus a few typographic characters.
    normal = sum(1 for c in line if c in _TEXT_CHARS or c in _TEXT_EXTRA)
    return normal / len(line) >= 0.85


def clean_lines(lines: list[str], *, drop_labels: bool = True) -> list[str]:
    """Remove headers, separators, page furniture and junk from raw lines."""
    cleaned: list[str] = []
    for raw in lines:
        line = raw.replace("\u00a0", " ").strip()
        if not line:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")  # keep one blank = stanza break
            continue
        if any(p.search(line) for p in _NOISE_PATTERNS):
            continue
        if _NOISE_PREFIX.match(line):
            continue
        if drop_labels and _LABEL_LINE.match(line) and len(line) < 30:
            continue
        line = _LEADING_VERSE_NUM.sub("", line)
        if not _is_lyricish(line):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\s*\[([^\]\n]+)\]\s*$")


def has_section_markers(text: str) -> bool:
    return any(_SECTION_RE.match(ln) for ln in text.splitlines())


def split_stanzas(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Blank-line stanzas; repeated stanzas (>=2 lines) become Chorus."""
    stanzas: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            stanzas.append(current)
            current = []
    if current:
        stanzas.append(current)

    def key(stanza: list[str]) -> tuple[str, ...]:
        return tuple(re.sub(r"\W+", " ", ln.lower()).strip() for ln in stanza)

    counts: dict[tuple[str, ...], int] = {}
    for st in stanzas:
        k = key(st)
        counts[k] = counts.get(k, 0) + 1
    repeated = {k for k, c in counts.items() if c >= 2 and len(k) >= 2}

    labelled: list[tuple[str, list[str]]] = []
    verse_no = 0
    for st in stanzas:
        if key(st) in repeated:
            labelled.append(("Chorus", st))
        else:
            verse_no += 1
            labelled.append((f"Verse {verse_no}", st))
    return labelled


# ---------------------------------------------------------------------------
# Filename / header metadata
# ---------------------------------------------------------------------------

_SMALL_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "my", "your", "his", "her",
    "its", "and", "or", "for", "at", "by", "with", "is", "it", "that",
    "this", "from", "into", "thou", "thee", "thy", "than", "as", "but",
    "so", "up", "out", "o",
}


def titleize(words: list[str]) -> str:
    out = []
    for i, w in enumerate(words):
        low = w.lower()
        if low in _SMALL_WORDS and i not in (0, len(words) - 1):
            out.append(low)
        elif low == "i":
            out.append("I")
        elif w.isupper() and len(w) > 1:
            out.append(w.capitalize())   # ALL-CAPS input -> Title case
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def title_from_filename(path: str | Path) -> str:
    """CamelCase or underscored filename stem -> display title."""
    stem = Path(path).stem
    if "_" in stem:
        words = [w for w in stem.split("_") if w]
    else:
        words = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", stem)
    return titleize(words)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def guess_artist(path: str | Path, known_artists: list[str]) -> tuple[str, str | None]:
    """Derive (title, artist-or-None) from a filename.

    Known artist names (from the database) are matched as the longest
    contiguous token run inside the filename; "..._Unknown_Artist" keeps the
    conventional placeholder.
    """
    stem = Path(path).stem
    if "_" in stem:
        tokens = [t for t in stem.split("_") if t]
    else:
        tokens = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", stem)

    # "…_Unknown_Artist" convention
    if [t.lower() for t in tokens[-2:]] == ["unknown", "artist"]:
        tokens = tokens[:-2]
        artist: str | None = "Unknown Artist"
    else:
        artist = None

    norm_tokens = [_norm(t) for t in tokens]
    if artist is None and known_artists:
        best: tuple[int, str] | None = None
        for name in known_artists:
            name_tokens = _norm(name).split()
            if len(name_tokens) < 2:
                continue
            run = len(name_tokens)
            for start in range(len(norm_tokens) - run + 1):
                if norm_tokens[start : start + run] == name_tokens:
                    if best is None or run > best[0]:
                        best = (run, name)
        if best:
            _run, name = best
            name_tokens = _norm(name).split()
            run = len(name_tokens)
            for start in range(len(norm_tokens) - 1, -1, -1):  # rightmost
                if norm_tokens[start : start + run] == name_tokens:
                    artist = name
                    tokens = tokens[:start]
                    break

    return titleize(tokens), artist


def header_title_artist(first_lines: list[str]) -> tuple[str | None, str | None]:
    """'TITLE - ARTIST' first line convention used by the TXT song packs."""
    for line in first_lines[:3]:
        if " - " in line and not line.startswith("["):
            left, right = line.split(" - ", 1)
            if 2 <= len(left) <= 80 and 2 <= len(right) <= 60:
                return titleize(left.split()), titleize(right.split())
    return None, None


def caps_title(lines: list[str]) -> str | None:
    """A leading ALL-CAPS title line inside a PDF."""
    for line in lines[:4]:
        letters = [c for c in line if c.isalpha()]
        if 3 <= len(line.split()) <= 10 and letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
            return titleize(line.split())
    return None


# ---------------------------------------------------------------------------
# Top-level entry: one file -> ready-to-import payload
# ---------------------------------------------------------------------------


class Extracted:
    """What the importer needs: sections + provenance pieces."""

    def __init__(self, title, artist, stanzas, origin_note, kind):
        self.title = title
        self.artist = artist
        self.stanzas = stanzas  # [(section_type, [lines])]
        self.origin_note = origin_note
        self.kind = kind        # "pdf" | "txt"

    @property
    def line_count(self) -> int:
        return sum(len(lines) for _st, lines in self.stanzas)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_file(
    path: str | Path,
    known_artists: list[str] | None = None,
    *,
    title: str | None = None,
    artist: str | None = None,
) -> Extracted:
    """Extract clean sections + metadata from a .pdf/.txt/.md lyric file."""
    from import_user_lyrics import parse_lyrics_text

    path = Path(path)
    suffix = path.suffix.lower()
    known_artists = known_artists or []

    if suffix == ".pdf":
        raw_lines = pdf_to_lines(path)
        kind = "pdf"
    else:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        kind = "txt"

    # Provenance: origin lines from TXT packs (Source:/Published:) and
    # attribution lines from PDF sheets ("Words by …, tune by …").
    origin_bits = [
        ln.strip() for ln in raw_lines[:6]
        if re.match(r"^(source|published)\s*:", ln.strip(), re.I)
    ]
    origin_bits += [
        ln.strip() for ln in raw_lines
        if re.match(r"^(words|lyrics|music|tune)\s+(by|and)\b|^(written|composed|arranged)\s+by\b",
                    ln.strip(), re.I)
    ]
    origin_note = "; ".join(origin_bits) if origin_bits else None

    # Header conventions (before cleaning eats them)
    head_title, head_artist = header_title_artist(raw_lines)
    pdf_title = caps_title(clean_lines(raw_lines[:8], drop_labels=False)) if kind == "pdf" else None
    fn_title, fn_artist = guess_artist(path, known_artists)

    final_title = title or head_title or pdf_title or fn_title
    final_artist = (
        artist or head_artist
        or (fn_artist if fn_artist != "Unknown Artist" else None)
        or "Unknown Artist"
    )

    cleaned = clean_lines(raw_lines)

    # Drop the raw header line that carried "TITLE - ARTIST"
    if head_title and cleaned and _norm(cleaned[0]).startswith(_norm(head_title)):
        cleaned = cleaned[1:]
        while cleaned and not cleaned[0]:
            cleaned.pop(0)

    # Drop a leading line that just repeats the title
    if cleaned and _norm(cleaned[0]) == _norm(final_title):
        cleaned = cleaned[1:]
        while cleaned and not cleaned[0]:
            cleaned.pop(0)

    raw_text = "\n".join(cleaned)
    if has_section_markers(raw_text):
        stanzas = parse_lyrics_text(raw_text)
    else:
        stanzas = split_stanzas(cleaned)

    stanzas = [(st, lines) for st, lines in stanzas if lines]
    if not stanzas:
        raise ValueError(f"no lyric lines could be extracted from {path.name}")

    return Extracted(final_title, final_artist, stanzas, origin_note, kind)


# ---------------------------------------------------------------------------
# Preview CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Preview lyric extraction from a file.")
    ap.add_argument("file")
    ap.add_argument("--full", action="store_true", help="print every line")
    args = ap.parse_args()

    ex = extract_file(args.file)
    print(f"file    : {args.file}")
    print(f"kind    : {ex.kind}")
    print(f"title   : {ex.title}")
    print(f"artist  : {ex.artist}")
    if ex.origin_note:
        print(f"origin  : {ex.origin_note}")
    print(f"sections: {len(ex.stanzas)}   lines: {ex.line_count}")
    for st, lines in ex.stanzas:
        preview = lines[0] if lines else ""
        print(f"  [{st}] {len(lines)}  | {preview[:70]}")
        if args.full:
            for ln in lines:
                print(f"      {ln}")
