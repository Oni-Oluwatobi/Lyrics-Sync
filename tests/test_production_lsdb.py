"""Integration tests against the real production database.

These tests open the shipped ``lyric_sync_gospel.lsdb`` through
:class:`LyricSearchService` — the exact path the interface uses — and prove
that the downloaded ``search_engine.py`` is the one running. The database is
never modified: a SHA-256 checksum taken before the tests is asserted after
they all finish.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from lyric_sync.search import engine_loader
from lyric_sync.search.lyric_search_service import (
    DatabaseMissingError,
    DatabaseUnreadableError,
    LyricSearchService,
    ServiceError,
)
from lyric_sync.models.search_result import MatchLabel
from lyric_sync.storage.favorites import FavoritesStore

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = ROOT / "lyric_sync_gospel.lsdb"

pytestmark = pytest.mark.skipif(
    not PRODUCTION_DB.is_file(),
    reason="production database lyric_sync_gospel.lsdb not present",
)

AMAZING_GRACE = "hymn_amazing_grace_001"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module", autouse=True)
def database_untouched():
    """Read-only proof: the file hash must not change during the module."""
    before = sha256(PRODUCTION_DB)
    yield
    assert sha256(PRODUCTION_DB) == before, "production database was modified"


@pytest.fixture()
def service():
    instance = LyricSearchService(sensitivity="balanced")
    instance.open(PRODUCTION_DB)
    try:
        yield instance
    finally:
        instance.close()


def titles(response) -> list[str]:
    return [result.song.title for result in response.results]


# --------------------------------------------------------------------------- #
# database loading
# --------------------------------------------------------------------------- #


def test_service_opens_production_database(service: LyricSearchService) -> None:
    assert service.available
    assert service.path == PRODUCTION_DB
    assert service.song_count == 4998
    assert service.get_song(AMAZING_GRACE) is not None


def test_engine_is_the_downloaded_search_engine_module(
    service: LyricSearchService,
) -> None:
    loaded = engine_loader.loaded_from()
    assert loaded is not None
    assert loaded.resolve() == (ROOT / "search_engine.py").resolve()
    assert type(service._engine).__name__ == "LyricSyncSearchEngine"


def test_database_info_reports_manifest(service: LyricSearchService) -> None:
    info = service.database_info()
    assert isinstance(info, dict)
    assert info.get("database_version") == "3.2.0"
    assert info.get("database_name") == "lyric_sync_gospel.lsdb"


def test_missing_file_raises_database_missing(tmp_path: Path) -> None:
    service = LyricSearchService()
    with pytest.raises(DatabaseMissingError):
        service.open(tmp_path / "absent.lsdb")
    service.close()


def test_non_database_file_is_rejected(tmp_path: Path) -> None:
    bogus = tmp_path / "fake.lsdb"
    bogus.write_bytes(b"this is definitely not a sqlite database")
    service = LyricSearchService()
    with pytest.raises((DatabaseUnreadableError, ServiceError)):
        service.open(bogus)
    service.close()


def test_connection_is_read_only(service: LyricSearchService) -> None:
    with pytest.raises(sqlite3.OperationalError):
        service._engine.conn.execute("UPDATE songs SET title = 'changed'")


# --------------------------------------------------------------------------- #
# search behaviour (real engine, real data)
# --------------------------------------------------------------------------- #


def test_search_way_maker(service: LyricSearchService) -> None:
    response = service.search("Way Maker")
    assert response.results
    assert response.results[0].song.title == "Way Maker"
    assert response.results[0].label is MatchLabel.STRONG
    assert response.candidate_count == 4998
    assert response.elapsed_ms > 0


def test_search_great_is_thy_faithfulness(service: LyricSearchService) -> None:
    response = service.search("Great is thy faithfulness")
    assert response.results
    assert response.results[0].song.title == "Great Is Thy Faithfulness"


def test_search_by_artist_nathaniel_bassey(service: LyricSearchService) -> None:
    response = service.search("Nathaniel Bassey")
    assert response.results
    assert any("Nathaniel" in result.song.display_artist for result in response.results)


def test_search_by_artist_sinach(service: LyricSearchService) -> None:
    response = service.search("Sinach")
    assert response.results
    assert any("Sinach" in result.song.display_artist for result in response.results)


@pytest.mark.parametrize(
    ("query", "artist_fragment"),
    [
        ("Dunsin Oyekan", "Dunsin Oyekan"),
        ("Lawrence Oyor", "Lawrence Oyor"),
        ("Mercy Chinwo", "Mercy Chinwo"),
        ("Nathaniel Bassey", "Nathaniel Bassey"),
        ("Minister Mike", "Minister Mike"),
        ("Greatman Takit", "Greatman Takit"),
        ("Favour", "Lawrence Oyor"),
        ("New Wine", "Dunsin Oyekan"),
        ("Oke Mmiri", "Mercy Chinwo"),
        ("You Are Good", "Greatman Takit"),
        ("Jugular Jugular", "Greatman Takit"),
        ("A Cry for Mercy", "Minister Mike"),
    ],
)
def test_nigerian_catalog_searches_surface_target_artist(
    service: LyricSearchService, query: str, artist_fragment: str
) -> None:
    """Every expanded-catalog query must reach its artist within the returned page."""
    response = service.search(query)
    assert response.results, f"no results for {query!r}"
    assert any(
        artist_fragment in result.song.display_artist for result in response.results
    ), f"{artist_fragment!r} missing from results for {query!r}"


@pytest.mark.parametrize(
    ("query", "artist_fragment"),
    [
        ("Sinach", "Sinach"),
        ("Ada Ehi", "Ada Ehi"),
        ("Eben", "Eben"),
        ("Frank Edwards", "Frank Edwards"),
        ("Tim Godfrey", "Tim Godfrey"),
        ("Victoria Orenze", "Victoria Orenze"),
        ("Judikay", "Judikay"),
        ("Moses Bliss", "Moses Bliss"),
        ("Minister GUC", "Minister GUC"),
        ("Tope Alabi", "Tope Alabi"),
        ("Sunmisola Agbebi", "Sunmisola"),
        ("Theophilus Sunday", "Theophilus Sunday"),
        ("Limoblaze", "Limoblaze"),
        ("Gaise Baba", "Gaise"),
        ("Ebuka Songs", "Ebuka"),
        ("Samsong", "Samsong"),
        ("Mike Abdul", "Mike Abdul"),
        ("Midnight Crew", "Midnight Crew"),
        ("Sammie Okposo", "Sammie Okposo"),
        ("Testimony Jaga", "Testimony Jaga"),
        ("Marizu", "Marizu"),
        ("Festizie", "Festizie"),
        ("Neeja", "Neeja"),
        ("Bidemi Olaoba", "Bidemi Olaoba"),
        ("Mr M & Revelation", "Mr M"),
    ],
)
def test_expanded_catalog_artist_searches(
    service: LyricSearchService, query: str, artist_fragment: str
) -> None:
    """Spec search-quality list: artist queries must reach their artist."""
    response = service.search(query)
    assert response.results, f"no results for {query!r}"
    assert any(
        artist_fragment in result.song.display_artist for result in response.results
    ), f"{artist_fragment!r} missing from results for {query!r}"


def test_fuzzy_artist_search_reaches_expanded_catalog(
    service: LyricSearchService,
) -> None:
    """A typo'd artist query must still surface the expanded-catalog artist."""
    response = service.search("Midnight Crewe")
    assert response.results
    assert any(
        "Midnight Crew" in result.song.display_artist for result in response.results
    )


def test_typo_query_still_finds_amazing_grace(service: LyricSearchService) -> None:
    response = service.search("amzing grace")
    assert response.results
    assert any(title.startswith("Amazing") for title in titles(response))


def test_remembered_lyric_fragment(service: LyricSearchService) -> None:
    response = service.search("That saved a wretch like me")
    assert response.results
    assert response.results[0].song.title == "Amazing Grace"
    assert any(field == "lyrics" for field in response.results[0].matched_fields)


def test_metadata_only_song_has_no_lyrics(service: LyricSearchService) -> None:
    response = service.search("Way Maker")
    way_maker = next(
        result.song for result in response.results if result.song.title == "Way Maker"
    )
    assert way_maker.lyrics_displayable is False
    lyrics = service.get_lyrics(way_maker.id)
    assert lyrics.is_empty


def test_strict_sensitivity_hides_weak_matches(service: LyricSearchService) -> None:
    service.sensitivity = "strict"
    response = service.search("peace like a river")
    assert all(
        result.label in (MatchLabel.STRONG, MatchLabel.GOOD)
        for result in response.results
    )


# --------------------------------------------------------------------------- #
# song details
# --------------------------------------------------------------------------- #


def test_sections_follow_database_order(service: LyricSearchService) -> None:
    lyrics = service.get_lyrics(AMAZING_GRACE)
    assert not lyrics.is_empty
    ordered_sections = lyrics.sorted_sections()
    orders = [section.order for section in ordered_sections]
    assert orders == sorted(orders)
    assert len(orders) == len(set(orders))
    assert [section.label for section in ordered_sections] == [
        "Verse 1",
        "Verse 2",
        "Verse 3",
        "Verse 4",
    ]
    assert "Amazing grace" in lyrics.plain_text


def test_get_songs_keeps_text_ids(service: LyricSearchService) -> None:
    songs = service.get_songs([AMAZING_GRACE, "does_not_exist"])
    assert list(songs) == [AMAZING_GRACE]
    assert songs[AMAZING_GRACE].title == "Amazing Grace"


def test_favorites_resolve_against_real_database(
    service: LyricSearchService, tmp_path: Path
) -> None:
    store = FavoritesStore(tmp_path / "favorites.json")
    store.add(AMAZING_GRACE)
    assert store.contains(AMAZING_GRACE)
    resolved = service.get_songs(store.song_ids)
    assert resolved[AMAZING_GRACE].title == "Amazing Grace"


# --------------------------------------------------------------------------- #
# text-id safety in the database layer (regression: int() crashes)
# --------------------------------------------------------------------------- #


def test_manager_reads_text_ids_on_production_database() -> None:
    from lyric_sync.database.lsdb_manager import LSDBManager

    manager = LSDBManager(PRODUCTION_DB)
    manager.open()
    try:
        song = manager.get_song(AMAZING_GRACE)
        assert song is not None
        assert song.id == AMAZING_GRACE  # text id preserved, not coerced
        assert song.title == "Amazing Grace"

        missing = manager.get_song("hymn_not_a_real_song_999")
        assert missing is None

        invalid = manager.get_song(None)  # type: ignore[arg-type]
        assert invalid is None

        mixed = manager.get_songs([AMAZING_GRACE, "missing_song", None])
        assert list(mixed) == [AMAZING_GRACE]

        lyrics = manager.get_lyrics(AMAZING_GRACE)
        assert lyrics.available is True
        assert not lyrics.is_empty

        malformed = manager.get_lyrics(None)  # type: ignore[arg-type]
        assert malformed.available is False
        assert malformed.is_empty
    finally:
        manager.close()


# --------------------------------------------------------------------------- #
# tie-break and sensitivity regressions
# --------------------------------------------------------------------------- #


def test_exact_title_tie_break_is_preserved(service: LyricSearchService) -> None:
    """'Way Maker' ties with another song at the same engine score."""
    response = service.search("Way Maker")
    top = response.results[0]
    assert top.song.title == "Way Maker"
    tied = [
        result
        for result in response.results[1:]
        if result.score == top.score and result.song.title != "Way Maker"
    ]
    assert tied, "expected an equal-score competitor for the tie-break"
    assert 0.0 < top.score <= 1.0


def test_sensitivity_modes_change_results(service: LyricSearchService) -> None:
    # "blessed assurance" has a stable weak-match tail on the catalogue:
    # strict shows only the handful of strong hits, balanced/tolerant surface
    # the POSSIBLE tier (the earlier probe query "amazing grace" lost its
    # single POSSIBLE tail result when the registry backfill grew the
    # catalogue past the tolerant cap).
    service.sensitivity = "strict"
    strict = service.search("blessed assurance")
    service.sensitivity = "balanced"
    balanced = service.search("blessed assurance")
    service.sensitivity = "tolerant"
    tolerant = service.search("blessed assurance")

    strict_ids = {result.song.id for result in strict.results}
    tolerant_ids = {result.song.id for result in tolerant.results}

    # strict hides the weakest tier entirely...
    assert strict.results
    assert MatchLabel.POSSIBLE not in {r.label for r in strict.results}
    # ...tolerant surfaces it and never returns fewer songs...
    assert MatchLabel.POSSIBLE in {r.label for r in tolerant.results}
    assert len(tolerant.results) >= len(strict.results)
    # ...and every strict hit is also a tolerant hit (same engine ranking).
    assert strict_ids <= tolerant_ids
    # balanced sits between the two
    assert len(strict.results) <= len(balanced.results) <= len(tolerant.results)
