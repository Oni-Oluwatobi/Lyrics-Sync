"""Data structures exchanged between scraper stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Section vocabulary
# --------------------------------------------------------------------------
# Order mirrors lyric_sync.models.lyric.SECTION_ORDER so exported records load
# the same way existing production rows do.
SECTION_ORDER = (
    "INTRO", "PRE_CHORUS", "VERSE", "CHORUS", "BRIDGE",
    "HOOK", "REFRAIN", "OUTRO",
)

SECTION_LABELS = {
    "INTRO": "Intro",
    "PRE_CHORUS": "Pre-Chorus",
    "VERSE": "Verse",
    "CHORUS": "Chorus",
    "BRIDGE": "Bridge",
    "HOOK": "Hook",
    "REFRAIN": "Refrain",
    "OUTRO": "Outro",
    "INTERLUDE": "Interlude",
    "SPOKEN": "Spoken",
    "OTHER": "Section",
}

# Raw heading words recognised as a section start (semantic, not title based).
SECTION_KEYWORDS: dict[str, str] = {
    "intro": "INTRO",
    "pre-chorus": "PRE_CHORUS",
    "prechorus": "PRE_CHORUS",
    "pre chorus": "PRE_CHORUS",
    "verse": "VERSE",
    "stanza": "VERSE",
    "chorus": "CHORUS",
    "refrain": "REFRAIN",
    "hook": "HOOK",
    "bridge": "BRIDGE",
    "outro": "OUTRO",
    "ending": "OUTRO",
    "interlude": "INTERLUDE",
    "instrumental": "INTERLUDE",
    "spoken": "SPOKEN",
    "narration": "SPOKEN",
    # Compact repetition labels used by African Gospel Lyrics.
    "repeat": "OTHER",
}

# Boilerplate headings that never start a song (site chrome / article furniture).
BOILERPLATE_HEADING_PATTERNS = (
    r"share this", r"like this", r"related", r"post navigation",
    r"leave a reply", r"discover more from", r"blog stats", r"^menu$",
    r"recent (songs|posts)", r"most search", r"search songs", r"comments?",
    r"pingback", r"example\b.*\bstanza\b", r"^tags?$", r"categories?",
)

# Paragraph labels treated as metadata rather than lyric lines (semantic field
# names only — never song titles).
METADATA_LABELS: dict[str, str] = {
    "author": "author",
    "authors": "author",
    "author(s)": "author",
    "writer": "author",
    "composer": "composer",
    "composed by": "composer",
    "music": "composer",
    "songwriter": "songwriter",
    "written by": "songwriter",
    "lyricist": "songwriter",
    "translator": "translator",
    "translated by": "translator",
    "year": "year",
    "published": "year",
    "release": "year",
    "language": "language",
    "languages": "language",
    "lang": "language",
    "key": "key",
    "chords": "chords",
    "common chords": "chords",
    "category": "category",
    "categories": "category",
    "album": "album",
    "artist": "artist",
    "artists": "artist",
    "singer": "artist",
    "feat": "artist",
    "featured": "artist",
}


@dataclass
class RawPage:
    """A fetched page retained exactly as downloaded."""

    url: str
    final_url: str = ""
    html: str = ""
    http_status: int = 0
    fetched_at: str = ""
    raw_path: str = ""
    bytes: int = 0
    from_cache: bool = False

    @property
    def page_id(self) -> str:
        from .normalize import content_hash

        return content_hash(self.url)[:16]


@dataclass
class LyricLine:
    """One source line, with its repetition instruction kept intact.

    ``raw`` is always the exact wording of the page.  ``text`` is the same
    line with a trailing repetition marker (``x4``) removed, so a display
    layer can render ``text`` + ``repeat`` without ever having to re-parse
    the source.
    """

    text: str                       # cleaned lyric text ("" for pure markers)
    raw: str = ""                   # exact source line — never destroyed
    repeat: int = 1                 # repetition count (1 == none)
    repeat_unknown: bool = False    # source said "x?" rather than a number
    marker: str = ""                # "" | "repeat" | "section"
    target: str = ""                # for section markers, e.g. "Refrain"
    translation: str = ""           # optional parenthetical gloss
    original_text: str = ""         # line without that gloss

    @property
    def is_marker(self) -> bool:
        return bool(self.marker)


@dataclass
class LyricSection:
    """One labelled block of lyric lines."""

    label: str = ""               # raw label as printed ("Stanza 2")
    section_type: str = "OTHER"   # normalised vocabulary (VERSE / CHORUS / ...)
    display_label: str = ""       # export form ("Verse 2")
    entries: list[LyricLine] = field(default_factory=list)

    def append(self, text: str, *, raw: str | None = None,
               repeat: int = 1, repeat_unknown: bool = False,
               marker: str = "", target: str = "",
               translation: str = "", original_text: str = "") -> LyricLine:
        entry = LyricLine(
            text=text, raw=raw if raw is not None else text, repeat=repeat,
            repeat_unknown=repeat_unknown, marker=marker, target=target,
            translation=translation, original_text=original_text,
        )
        self.entries.append(entry)
        return entry

    @property
    def lines(self) -> list[str]:
        """Raw source lines, in order (markers included, wording intact)."""
        return [entry.raw for entry in self.entries]

    @property
    def clean_lines(self) -> list[str]:
        """Display lines: repetition markers stripped, glosses kept."""
        return [entry.text or entry.raw for entry in self.entries]

    @property
    def is_empty(self) -> bool:
        return not self.entries


@dataclass
class NormalizedSong:
    """The adapter-independent staging record (one scraped song).

    Every source adapter produces exactly this shape, so validation,
    deduplication, staging and export never need to know which site a song
    came from.
    """

    title: str
    artists: list[str] = field(default_factory=list)      # primary first
    featured_artists: list[str] = field(default_factory=list)

    source_site: str = "OpenGospelLyrics"
    source_domain: str = "opengospellyrics.com"
    source_adapter: str = "OpenGospelLyricsAdapter"
    source_name: str = "OpenGospelLyrics"
    source_url: str = ""
    article_url: str = ""
    page_id: str = ""
    article_date: str | None = None

    author: str | None = None
    composer: str | None = None
    songwriter: str | None = None
    translator: str | None = None
    year: str | None = None
    languages: list[str] = field(default_factory=list)
    language_confidence: str = "unknown"   # explicit | inferred | unknown
    #: Legal posture of the text.  PUBLIC_DOMAIN / AUTHORIZED lyrics can be
    #: exported; everything else exports as metadata only.  An adapter may
    #: pre-set this (Project Gutenberg) but an operator can always override.
    copyright_status: str = "UNKNOWN"
    countries: list[str] = field(default_factory=list)
    region: str = ""
    language: str | None = None            # first language (export convenience)
    key_name: str | None = None
    chords: str | None = None
    album: str | None = None
    category: str | None = None            # free-text categories, source order
    tags: list[str] = field(default_factory=list)
    taxonomy: dict[str, list[str]] = field(default_factory=dict)

    published_at: str | None = None
    modified_at: str | None = None

    sections: list[LyricSection] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""           # pre-normalisation representation of the block

    @property
    def artist(self) -> str:
        """Primary artist — the identity used for staging and dedup."""
        if self.artists:
            return self.artists[0]
        return getattr(self, "_artist", "Traditional")

    @artist.setter
    def artist(self, value: str) -> None:
        if value:
            self.artists = [value] + [a for a in self.artists if a != value]

    @property
    def source_metadata(self) -> dict[str, Any]:
        """The source block kept verbatim in staging."""
        return {
            "site": self.source_site,
            "domain": self.source_domain,
            "url": self.source_url,
            "article_date": self.article_date or self.published_at or "",
            "adapter": self.source_adapter,
        }

    @property
    def all_lines(self) -> list[str]:
        out: list[str] = []
        for section in self.sections:
            out.extend(section.lines)
        return out

    @property
    def clean_lines(self) -> list[str]:
        out: list[str] = []
        for section in self.sections:
            out.extend(section.clean_lines)
        return out

    @property
    def line_count(self) -> int:
        return len(self.all_lines)

    @property
    def plain_text(self) -> str:
        return "\n".join(self.all_lines)


# Backwards-compatible name used by the OpenGospelLyrics parser.
SongDraft = NormalizedSong


@dataclass
class Warning:
    """A validation / dedup finding. Questionable records are flagged, never dropped."""

    code: str
    message: str
    severity: str = "warning"      # info | warning | error
    song_title: str | None = None
    source_url: str | None = None
    context: str = ""


@dataclass
class ParseResult:
    """Everything extracted from a single page."""

    page_id: str = ""
    url: str = ""
    page_type: str = "unknown"
    site_title: str = ""
    article_title: str = ""
    published_at: str | None = None
    modified_at: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    songs: list[NormalizedSong] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)

    # filled in by the source adapter that produced this result
    source_site: str = ""
    source_domain: str = ""
    adapter_name: str = ""

    def source_metadata(self) -> dict[str, Any]:
        return {
            "site": self.source_site,
            "domain": self.source_domain,
            "url": self.url,
            "article_date": self.published_at or "",
            "adapter": self.adapter_name,
        }
