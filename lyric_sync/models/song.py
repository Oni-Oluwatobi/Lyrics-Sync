"""Song metadata model."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# Copyright / provenance statuses understood by the application.
PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
LICENSED = "LICENSED"
AUTHORIZED = "AUTHORIZED"
USER_IMPORTED = "USER_IMPORTED"
METADATA_ONLY = "METADATA_ONLY"

COPYRIGHT_STATUSES = (
    PUBLIC_DOMAIN,
    LICENSED,
    AUTHORIZED,
    USER_IMPORTED,
    METADATA_ONLY,
)

# Statuses whose stored lyrics may be displayed when lyrics are present.
DISPLAYABLE_COPYRIGHT = (PUBLIC_DOMAIN, LICENSED, AUTHORIZED, USER_IMPORTED)

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"

LYRICS_AVAILABLE = "AVAILABLE"
LYRICS_UNAVAILABLE = "UNAVAILABLE"

STATUS_LABELS = {
    PUBLIC_DOMAIN: "Public domain",
    LICENSED: "Licensed",
    AUTHORIZED: "Authorized",
    USER_IMPORTED: "User imported",
    METADATA_ONLY: "Metadata only",
    VERIFIED: "Verified",
    UNVERIFIED: "Unverified",
    LYRICS_AVAILABLE: "Lyrics available",
    LYRICS_UNAVAILABLE: "Lyrics unavailable",
}


def normalize_status(value: str | None, allowed: tuple[str, ...], default: str) -> str:
    if not value:
        return default
    cleaned = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    for candidate in allowed:
        if cleaned == candidate:
            return candidate
    for candidate in allowed:
        if cleaned in candidate or candidate in cleaned:
            return candidate
    return default


@dataclass(frozen=True)
class Song:
    """A single record from the ``.LSDB``."""

    id: int | str
    title: str
    artist: str = ""
    artist_id: int | str | None = None
    album: str | None = None
    year: int | None = None
    country: str | None = None
    region: str | None = None
    category: str | None = None
    songwriter: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    verification_status: str = UNVERIFIED
    copyright_status: str = METADATA_ONLY
    lyrics_status: str = LYRICS_UNAVAILABLE
    source: str | None = None
    rights_notice: str | None = None

    @property
    def display_artist(self) -> str:
        return self.artist.strip() or "Unknown artist"

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VERIFIED

    @property
    def has_stored_lyrics(self) -> bool:
        return self.lyrics_status == LYRICS_AVAILABLE

    @property
    def lyrics_displayable(self) -> bool:
        """True when stored lyrics may be shown to the user."""
        if self.copyright_status == METADATA_ONLY:
            return False
        if self.copyright_status not in DISPLAYABLE_COPYRIGHT:
            return False
        return self.has_stored_lyrics

    @property
    def copyright_label(self) -> str:
        return STATUS_LABELS.get(self.copyright_status, self.copyright_status.title())

    @property
    def verification_label(self) -> str:
        return STATUS_LABELS.get(self.verification_status, self.verification_status.title())

    @property
    def metadata_fields(self) -> list[tuple[str, str]]:
        """Ordered (label, value) pairs for the song details view."""
        rows: list[tuple[str, str]] = [("Artist", self.display_artist)]
        optional = [
            ("Album", self.album),
            ("Year", str(self.year) if self.year else None),
            ("Country", self.country),
            ("Region", self.region),
            ("Category", self.category),
            ("Songwriter", self.songwriter),
            ("Also known as", ", ".join(self.aliases) if self.aliases else None),
            ("Source", self.source),
            ("Copyright status", self.copyright_label),
            ("Verification", self.verification_label),
            ("Database ID", str(self.id)),
        ]
        rows.extend((label, value) for label, value in optional if value)
        return rows

    def with_lyrics_status(self, status: str) -> "Song":
        return replace(self, lyrics_status=status)
