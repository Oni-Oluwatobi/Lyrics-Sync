"""Multi-signal duplicate detection.

Signals used (in order of strength):

1. identical source URL
2. identical raw content hash
3. identical normalised (title, artist) **and** identical lyrics hash
4. identical lyrics hash with a different title
5. identical normalised title with a different artist / lyrics

Only strong signals merge a record into an existing song (by attaching an
extra source).  Ambiguous matches are inserted **and** flagged for review â€”
songs are never dropped and never auto-merged on title alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import NormalizedSong, Warning
from .normalize import content_hash, lyrics_hash, normalize

MERGE = "merge_source"          # attach source to an existing song
INSERT = "insert"               # new song, no conflict
INSERT_FLAGGED = "insert_flagged"  # new song + review warning

# Minimum number of lyric lines before two records may be merged on lyrics.
MIN_MERGE_LINES = 3


@dataclass
class DedupIndex:
    """Lookup structures over songs already present in staging."""

    by_source_url: dict[str, str] = field(default_factory=dict)
    by_content_hash: dict[str, str] = field(default_factory=dict)
    by_title_artist_lyrics: dict[tuple[str, str, str], str] = field(default_factory=dict)
    by_lyrics_hash: dict[str, list[str]] = field(default_factory=dict)
    by_title_artist: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, rows: list[dict]) -> "DedupIndex":
        index = cls()
        for row in rows:
            song_id = row["song_id"]
            source_url = row.get("source_url") or ""
            if source_url:
                index.by_source_url.setdefault(source_url, song_id)
            index.by_content_hash.setdefault(row.get("content_hash") or "", song_id)
            title = row.get("normalized_title") or ""
            artist = row.get("normalized_artist") or ""
            lhash = row.get("lyrics_hash") or ""
            if title:
                index.by_title_artist.setdefault((title, artist), []).append(song_id)
                if lhash:
                    index.by_title_artist_lyrics.setdefault((title, artist, lhash), song_id)
            if lhash:
                index.by_lyrics_hash.setdefault(lhash, []).append(song_id)
        return index

    def __len__(self) -> int:
        return len(self.by_title_artist)


@dataclass
class DedupDecision:
    action: str
    existing_song_id: str | None = None
    reason: str = ""
    warnings: list[Warning] = field(default_factory=list)


def draft_hashes(song: NormalizedSong) -> tuple[str, str, str, str]:
    """Return ``(normalized_title, normalized_artist, content_hash, lyrics_hash)``."""
    lines = song.all_lines
    return (
        normalize(song.title),
        normalize(song.artist),
        content_hash(song.raw_text, song.title),
        lyrics_hash(lines) if lines else "",
    )


def decide(song: NormalizedSong, index: DedupIndex) -> DedupDecision:
    """Classify one draft against everything already staged."""
    norm_title, norm_artist, c_hash, l_hash = draft_hashes(song)
    warnings: list[Warning] = []

    def warn(code: str, message: str, existing_id: str | None = None) -> None:
        warnings.append(Warning(
            code=code, message=message, severity="warning",
            song_title=song.title, source_url=song.source_url,
            context=existing_id or "",
        ))

    # 1. same source URL -> additional source for the stored song
    existing = index.by_source_url.get(song.source_url or "")
    if existing:
        return DedupDecision(MERGE, existing, "identical source URL", warnings)

    # 2. byte-identical raw block
    existing = index.by_content_hash.get(c_hash)
    if existing:
        return DedupDecision(MERGE, existing, "identical content hash", warnings)

    # 3. same title + artist + lyrics -> same song on another page
    key = (norm_title, norm_artist, l_hash)
    if l_hash and key in index.by_title_artist_lyrics:
        existing = index.by_title_artist_lyrics[key]
        return DedupDecision(MERGE, existing, "identical title, artist and lyrics", warnings)

    # 4. identical lyrics but a different title
    if l_hash and len(song.all_lines) >= MIN_MERGE_LINES:
        candidates = index.by_lyrics_hash.get(l_hash, [])
        if candidates:
            warn("duplicate_lyrics_title_mismatch",
                 "identical lyrics already staged under a different title "
                 f"({candidates[0]})", candidates[0])

    # 5. same title+artist but different lyrics -> ambiguous
    same_pair = index.by_title_artist.get((norm_title, norm_artist), [])
    if same_pair:
        warn("duplicate_review",
             "same title and artist already staged with different lyrics "
             f"({same_pair[0]})", same_pair[0])
        return DedupDecision(INSERT_FLAGGED, None,
                             "title/artist match, lyrics differ", warnings)

    # 6. same title, different artist -> do not merge, just note it
    if norm_title:
        for (other_title, other_artist), ids in index.by_title_artist.items():
            if other_title == norm_title and other_artist != norm_artist:
                warn("title_artist_conflict",
                     f"title also staged for another artist: {ids[0]}", ids[0])
                break

    if warnings:
        return DedupDecision(INSERT_FLAGGED, None, "conflicting signals", warnings)
    return DedupDecision(INSERT, None, "new song", warnings)


def apply_insert(index: DedupIndex, song: NormalizedSong, song_id: str) -> None:
    """Register a newly inserted song so later records dedupe against it."""
    norm_title, norm_artist, c_hash, l_hash = draft_hashes(song)
    if song.source_url:
        index.by_source_url.setdefault(song.source_url, song_id)
    if c_hash:
        index.by_content_hash.setdefault(c_hash, song_id)
    if norm_title:
        index.by_title_artist.setdefault((norm_title, norm_artist), []).append(song_id)
        if l_hash:
            index.by_title_artist_lyrics.setdefault((norm_title, norm_artist, l_hash), song_id)
    if l_hash:
        index.by_lyrics_hash.setdefault(l_hash, []).append(song_id)
