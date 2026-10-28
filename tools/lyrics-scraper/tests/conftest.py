"""Shared fixtures for the lyric scraper test-suite.

The suite is fully offline: page fixtures are stored under ``tests/fixtures``
and no test performs a network request.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROD_DB = PACKAGE_ROOT.parents[1] / "lyric_sync_gospel.lsdb"

OGl_URL = (
    "https://opengospellyrics.com/2025/11/15/a-compilation-of-top-10-classic-"
    "christmas-carols-in-english-lyrics/"
)
AGL_URL = "https://africangospellyrics.com/2026/01/27/good-god/"


def load_page(url: str, filename: str):
    from lyrics_scraper.models import RawPage

    html = (FIXTURES / filename).read_bytes().decode("utf-8", errors="replace")
    return RawPage(url=url, final_url=url, html=html, http_status=200,
                   fetched_at="2026-10-08T00:00:00Z",
                   bytes=(FIXTURES / filename).stat().st_size)


@pytest.fixture
def ogl_page():
    return load_page(OGl_URL, "ogl_christmas.html")


@pytest.fixture
def agl_page():
    return load_page(AGL_URL, "agl_good_god.html")


@pytest.fixture
def prod_db_path() -> Path:
    if not PROD_DB.exists():
        pytest.skip("production database not present")
    return PROD_DB
