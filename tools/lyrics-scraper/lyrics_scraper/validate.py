"""Validation rules.

Questionable records are *flagged*, never silently discarded â€” every finding is
returned as a :class:`~lyrics_scraper.models.Warning` and persisted to the
staging database.
"""

from __future__ import annotations

import re

from .models import NormalizedSong, Warning
from .normalize import normalize

# Lines that belong to the page, not the song.
BOILERPLATE_LINE_PATTERNS = (
    r"\bsubscribe\b", r"\bdownload pdf\b", r"\bpost navigation\b",
    r"\bleave a reply\b", r"\bcancel reply\b", r"\bpingback\b",
    r"\bshare (this|on|on facebook)\b", r"\blike this:\b", r"\brelated\b",
    r"\bcopyright\s*[Â©(]", r"\bprivacy policy\b", r"\bterms (of use|and conditions)\b",
    r"\blog in to reply\b", r"\byour email address\b", r"\bsearch (this )?site\b",
    r"\badvertisement\b", r"\bsponsored\b", r"\bread more\b",
    r"\bwordpress\b", r"\bwp-admin\b", r"\ball rights reserved\b",
    r"^\s*(home|about|contact|menu|archives?)\s*$",
)

BOILERPLATE_RES = [re.compile(p, flags=re.I) for p in BOILERPLATE_LINE_PATTERNS]

HTML_LINE = re.compile(r"</?[a-z][^>]*>|&#\d+;|&[a-z]+;")

MIN_LINES = 4
MIN_CHARS = 60
MAX_LINES = 800
MAX_SECTIONS = 40


def _is_boilerplate(line: str) -> bool:
    return any(pattern.search(line) for pattern in BOILERPLATE_RES)


def validate_song(song: NormalizedSong) -> list[Warning]:
    """Return every finding for one parsed song (empty list == clean)."""
    warnings: list[Warning] = []
    lines = song.all_lines

    def add(code: str, message: str, severity: str = "warning", context: str = "") -> None:
        warnings.append(Warning(
            code=code, message=message, severity=severity,
            song_title=song.title, source_url=song.source_url, context=context,
        ))

    # --- title ------------------------------------------------------------
    title = (song.title or "").strip()
    if not title:
        add("missing_title", "song has no title", "error")
    elif len(title) < 2:
        add("suspect_title", f"title is implausibly short: {title!r}", "warning")
    elif _is_boilerplate(title):
        add("boilerplate_title", f"title looks like page furniture: {title!r}", "warning")
    elif HTML_LINE.search(title):
        add("html_in_title", f"title contains markup: {title!r}", "warning")

    # --- lyrics -----------------------------------------------------------
    joined = "\n".join(lines)
    if not lines:
        add("missing_lyrics", "no lyric lines were extracted", "error")
    else:
        if len(lines) < MIN_LINES:
            add("short_lyrics",
                f"only {len(lines)} lyric line(s) (minimum expected {MIN_LINES})",
                "warning")
        if len(joined) < MIN_CHARS:
            add("short_lyrics",
                f"lyrics are {len(joined)} characters (minimum expected {MIN_CHARS})",
                "warning")
        if len(lines) > MAX_LINES:
            add("excessive_lyrics",
                f"{len(lines)} lyric lines â€” probably whole-page text",
                "warning")

        boilerplate = [line for line in lines if _is_boilerplate(line)]
        if boilerplate:
            add("boilerplate_lines",
                f"{len(boilerplate)} non-lyric line(s) captured",
                "warning", context=" | ".join(boilerplate[:5]))

        html_lines = [line for line in lines if HTML_LINE.search(line)]
        if html_lines:
            add("html_in_lyrics",
                f"{len(html_lines)} line(s) still contain markup",
                "warning", context=" | ".join(html_lines[:3]))

        normalized = [normalize(line) for line in lines if normalize(line)]
        if normalized:
            counts: dict[str, int] = {}
            for item in normalized:
                counts[item] = counts.get(item, 0) + 1
            top_item, top_count = max(counts.items(), key=lambda kv: kv[1])
            share = top_count / len(normalized)
            if top_count >= 12 and share >= 0.4:
                add("repeated_lines",
                    f"one line occupies {share:.0%} of the song "
                    f"({top_count} repeats) â€” ad/nav loop?",
                    "warning", context=top_item)
            unique_ratio = len(set(normalized)) / max(len(normalized), 1)
            if unique_ratio < 0.25 and len(normalized) >= 8:
                add("low_variety",
                    f"only {unique_ratio:.0%} of lines are distinct",
                    "warning")

        notes = [line for line in lines
                 if len(line) > 50 and line.startswith("(") and line.endswith(")")]
        if notes:
            add("editorial_note",
                f"{len(notes)} explanatory note(s) stored as lyric lines",
                "warning", context=" | ".join(notes[:2]))
        labels = [line for line in lines
                  if re.match(r"^(example|sample|partial|note)\b", line, flags=re.I)
                  and len(line) <= 40]
        if labels:
            add("editorial_label",
                f"{len(labels)} example/label line(s) stored as lyric lines",
                "warning", context=" | ".join(labels[:3]))

    # --- sections ---------------------------------------------------------
    empty_sections = [s for s in song.sections if not s.lines]
    if empty_sections:
        add("empty_sections", f"{len(empty_sections)} section(s) have no lines", "warning")
    if len(song.sections) > MAX_SECTIONS:
        add("too_many_sections",
            f"{len(song.sections)} sections detected (expected <= {MAX_SECTIONS})",
            "warning")
    if song.sections and not lines:
        add("malformed_sections", "sections exist but contain no lines", "error")

    # --- source -----------------------------------------------------------
    if not song.source_url:
        add("missing_source", "record has no source URL", "error")

    # --- metadata ---------------------------------------------------------
    if song.year and not re.search(r"\d", song.year):
        add("suspect_year", f"year field has no digits: {song.year!r}", "info")

    return warnings


def severity_rank(warnings: list[Warning]) -> str:
    """Aggregate a song's warnings into a review status."""
    if any(w.severity == "error" for w in warnings):
        return "flagged"
    if any(w.severity == "warning" for w in warnings):
        return "flagged"
    return "clean"
