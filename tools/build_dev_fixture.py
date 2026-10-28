"""Build the development fixture database for manual testing.

    python tools/build_dev_fixture.py [output-path]

Default output: <project>/tests/fixtures/lyric_sync_dev_fixture.lsdb

Run the application against it with:

    set LYRIC_SYNC_DATABASE=tests\\fixtures\\lyric_sync_dev_fixture.lsdb
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixture_builder import build_fixture  # noqa: E402


def main(argv: list[str]) -> int:
    default = ROOT / "tests" / "fixtures" / "lyric_sync_dev_fixture.lsdb"
    target = Path(argv[0]) if argv else default
    built = build_fixture(target)
    print(f"Built development fixture: {built}")
    print("This is a clearly-labelled development fixture, not a Gospel catalogue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
