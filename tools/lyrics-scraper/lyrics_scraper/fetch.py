"""Fetching with caching, rate limiting and robots.txt compliance.

Stdlib only (``urllib``), so the scraper never adds a dependency to the main
``requirements.txt``.  Every response is written to ``output/raw/`` before it
is parsed, so raw material is always available for reprocessing.

Politeness rules, in the order they apply:

1. at least ``delay`` seconds between requests to a host
2. whatever ``Crawl-delay`` the site's robots.txt asks for (larger wins)
3. ``Retry-After`` from a 429/503 response — a backoff the site itself chose
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .models import RawPage
from .normalize import content_hash

USER_AGENT = "Mozilla/5.0 (compatible; LyricSyncDatabaseBuilder/1.0)"
DEFAULT_TIMEOUT = 30.0
DEFAULT_DELAY = 1.0
DEFAULT_RETRIES = 2

#: Temporary conditions worth waiting out; everything else is a hard failure.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
#: Never worth retrying — the URL or the client is wrong, not busy.
TERMINAL_STATUS = frozenset({400, 401, 403, 404, 410, 451})
MAX_BACKOFF = 120.0

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
}


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved after every retry."""


def retry_after_seconds(headers) -> float:
    """Seconds a server asked us to wait, capped at :data:`MAX_BACKOFF`."""
    if headers is None:
        return 0.0
    try:
        value = (headers.get("Retry-After") or "").strip()
    except AttributeError:
        return 0.0
    if not value:
        return 0.0
    if value.isdigit():
        return min(float(value), MAX_BACKOFF)
    try:
        when = parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return 0.0
    return min(max(when - time.time(), 0.0), MAX_BACKOFF)


@dataclass
class Fetcher:
    """Cached, throttled HTTP client."""

    cache_dir: Path
    delay: float = DEFAULT_DELAY
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    ignore_robots: bool = False
    cache_only: bool = False
    _last_request: float = 0.0
    _robots: dict[str, list[str]] = field(default_factory=dict)
    _robots_fetched: set[str] = field(default_factory=set)
    _crawl_delay: dict[str, float] = field(default_factory=dict)
    fetched: int = 0
    from_cache: int = 0
    backed_off: int = 0

    # -- cache -------------------------------------------------------------
    def cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{content_hash(url)[:16]}.html"

    def meta_path(self, url: str) -> Path:
        return self.cache_dir / f"{content_hash(url)[:16]}.meta.json"

    def read_cache(self, url: str) -> RawPage | None:
        path = self.cache_path(url)
        if not path.exists():
            return None
        meta = {}
        meta_path = self.meta_path(url)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        html = path.read_text(encoding="utf-8", errors="replace")
        return RawPage(
            url=url,
            final_url=meta.get("final_url") or url,
            html=html,
            http_status=int(meta.get("http_status") or 200),
            fetched_at=meta.get("fetched_at") or "",
            raw_path=str(path),
            bytes=len(html.encode("utf-8")),
            from_cache=True,
        )

    def write_cache(self, url: str, html: str, *, final_url: str,
                    http_status: int) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_path(url)
        path.write_text(html, encoding="utf-8")
        meta = {
            "url": url,
            "final_url": final_url,
            "http_status": http_status,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bytes": len(html.encode("utf-8")),
        }
        self.meta_path(url).write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    # -- robots ------------------------------------------------------------
    def robots_allowed(self, url: str) -> bool:
        if self.ignore_robots:
            return True
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots_fetched:
            self._robots_fetched.add(origin)
            self._robots[origin] = []
            robots_path = self.cache_dir / f"robots_{content_hash(origin)[:16]}.txt"
            body = ""
            if robots_path.exists():
                try:
                    body = robots_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    body = ""
            else:
                try:
                    body, _, _ = self._load(origin + "/robots.txt", throttle=False)
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    robots_path.write_text(body, encoding="utf-8")
                except FetchError:
                    body = ""
            rules: list[str] = []
            applies = False
            for line in body.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                field_name, _, value = line.partition(":")
                field_name = field_name.strip().lower()
                value = value.strip()
                if field_name == "user-agent":
                    applies = value in ("*", USER_AGENT)
                elif applies and field_name == "crawl-delay":
                    try:
                        self._crawl_delay[origin] = float(value)
                    except ValueError:
                        pass
                elif applies and field_name in ("disallow", "allow"):
                    if value:
                        rules.append(f"{field_name} {value}")
            self._robots[origin] = rules
        path = parts.path or "/"
        for rule in self._robots[origin]:
            kind, _, pattern = rule.partition(" ")
            target = path if path.startswith(pattern) else ""
            if kind == "disallow" and target:
                return False
            if kind == "allow" and target:
                return True
        return True

    # -- network -----------------------------------------------------------
    def _throttle(self, url: str = "") -> None:
        """Sleep long enough to honour the configured delay and Crawl-delay."""
        delay = self.delay
        if url:
            origin = site_origin(url)
            self.robots_allowed(url)          # populates _crawl_delay
            delay = max(delay, self._crawl_delay.get(origin, 0.0))
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request = time.monotonic()

    def _load(self, url: str, throttle: bool = True) -> tuple[str, str, int]:
        """Download ``url`` once, returning ``(html, final_url, status)``.

        429/503 and friends wait out ``Retry-After`` (site-chosen backoff)
        before trying again; 403/404 fail immediately because repeating them
        only wastes the operator's time and the site's patience.
        """
        last_error: Exception | None = None
        attempts = max(self.retries + 1, 4)
        for attempt in range(attempts):
            if throttle:
                self._throttle(url)
            request = urllib.request.Request(url, headers=_HEADERS)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read()
                    charset = response.headers.get_content_charset() or "utf-8"
                    return (
                        data.decode(charset, errors="replace"),
                        response.geturl() or url,
                        int(getattr(response, "status", 200) or 200),
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in TERMINAL_STATUS:
                    break
                wait = retry_after_seconds(getattr(exc, "headers", None))
                if attempt + 1 < attempts:
                    self.backed_off += 1
                    time.sleep(wait if wait > 0
                               else min(MAX_BACKOFF, 2.0 * (attempt + 1)))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(min(MAX_BACKOFF, 1.5 * (attempt + 1)))
        raise FetchError(f"failed to fetch {url}: {last_error}")

    def fetch(self, url: str) -> RawPage:
        """Return a page from cache when possible, otherwise download it."""
        cached = self.read_cache(url)
        if cached is not None:
            self.from_cache += 1
            return cached
        if self.cache_only:
            raise FetchError(f"not cached (cache-only mode): {url}")
        if not self.robots_allowed(url):
            raise FetchError(f"disallowed by robots.txt: {url}")

        html, final_url, status = self._load(url)
        path = self.write_cache(url, html, final_url=final_url, http_status=status)
        self.fetched += 1
        return RawPage(
            url=url,
            final_url=final_url,
            html=html,
            http_status=status,
            fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            raw_path=str(path),
            bytes=len(html.encode("utf-8")),
            from_cache=False,
        )


def site_origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
