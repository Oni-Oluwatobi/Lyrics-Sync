"""Project-root shim so ``python -m lyrics_scraper`` works from anywhere.

The real package lives in ``tools/lyrics-scraper/lyrics_scraper``.  Importing
this file only puts that folder at the front of ``sys.path`` (so the package
wins over this shim file); running it as a script hands control to the
package's own ``__main__``.  The full CLI, including ``ui``, behaves exactly
as it does inside ``tools/lyrics-scraper``.
"""

from __future__ import annotations

import importlib.util
import os
import runpy
import sys

_PACKAGE_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tools", "lyrics-scraper")

# Always move the package folder to the FRONT of sys.path: the root folder is
# sys.path[0] for `python -m`, and PYTHONPATH may already list the package
# folder somewhere behind it.
if sys.path[:1] != [_PACKAGE_ROOT]:
    if _PACKAGE_ROOT in sys.path:
        sys.path.remove(_PACKAGE_ROOT)
    sys.path.insert(0, _PACKAGE_ROOT)

if __name__ == "__main__":
    entry = os.path.join(_PACKAGE_ROOT, "lyrics_scraper", "__main__.py")
    spec = importlib.util.find_spec("lyrics_scraper")
    if (spec is None or not spec.submodule_search_locations
            or os.path.abspath(spec.origin) == os.path.abspath(__file__)):
        raise SystemExit(f"lyrics_scraper package not found — expected: {entry}")
    runpy.run_module("lyrics_scraper", run_name="__main__", alter_sys=True)
