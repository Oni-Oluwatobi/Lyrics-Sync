"""Lyric content models."""

from __future__ import annotations

from dataclasses import dataclass, field

SECTION_ORDER = (
    "INTRO",
    "PRE_CHORUS",
    "VERSE",
    "CHORUS",
    "BRIDGE",
    "HOOK",
    "REFRAIN",
    "OUTRO",
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

# Order used when the database does not supply explicit ordering.
_SECTION_RANK = {name: index for index, name in enumerate(SECTION_ORDER)}


def normalize_section_type(raw: str | None) -> str:
    if not raw:
        return "OTHER"
    cleaned = str(raw).strip().upper().replace(" ", "_").replace("-", "_")
    if cleaned in SECTION_LABELS:
        return cleaned
    for name in SECTION_LABELS:
        if name in cleaned:
            return name
    if cleaned.isdigit():
        return "VERSE"
    return "OTHER"


@dataclass(frozen=True)
class LyricSection:
    """One labelled block of lyrics (verse, chorus, ...)."""

    type: str
    index: int = 0
    label: str = ""
    lines: tuple[str, ...] = field(default_factory=tuple)
    order: int = 0

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        base = SECTION_LABELS.get(self.type, self.type.title())
        if self.type in ("VERSE", "BRIDGE", "PRE_CHORUS") and self.index:
            return f"{base} {self.index}"
        return base

    @property
    def sort_key(self) -> tuple[int, int]:
        # Sections that carry a database order keep it: Verse 1, Chorus, Verse 2
        # is how the songbook prints them, not Verse 1, Verse 2, Chorus.
        if self.order:
            return (self.order, self.index)
        return (_SECTION_RANK.get(self.type, len(SECTION_ORDER)), self.index)


@dataclass(frozen=True)
class SongLyrics:
    """Lyrics for one song, exactly as stored in the database."""

    song_id: int | str
    sections: tuple[LyricSection, ...] = field(default_factory=tuple)
    available: bool = False
    notice: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any(section.lines for section in self.sections)

    def sorted_sections(self) -> list[LyricSection]:
        return sorted(self.sections, key=lambda section: section.sort_key)

    @property
    def plain_lines(self) -> list[str]:
        lines: list[str] = []
        for section in self.sorted_sections():
            lines.extend(section.lines)
        return lines

    @property
    def plain_text(self) -> str:
        return "\n".join(self.plain_lines)
