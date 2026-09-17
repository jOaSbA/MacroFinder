"""Polite HTTP client.

Enforces the three non-negotiables from CLAUDE.md section 1:
  - at most MAX_REQUESTS_PER_SECOND per chain
  - responses cached on disk for at least CACHE_TTL_SECONDS
  - exponential backoff on 429 and 5xx

The rate limiter is keyed per chain, so adding a chain cannot slow another one down
and cannot be used to sidestep the limit by spreading requests across hosts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import config

log = logging.getLogger(__name__)


@dataclass
class _RateLimiter:
    """Minimum-interval limiter. One instance per chain."""

    min_interval: float
    _last_call: float = field(default=0.0, repr=False)

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


class CacheEntry(dict):
    """A cached response: status, headers subset, body (text), fetched_at."""


class PoliteClient:
    """A per-chain httpx wrapper. Construct one per chain, reuse it."""

    def __init__(
        self,
        chain: str,
        *,
        base_url: str = "",
        cache_ttl: int = config.CACHE_TTL_SECONDS,
        rps: float = config.MAX_REQUESTS_PER_SECOND,
    ) -> None:
        self.chain = chain
        self.cache_ttl = cache_ttl
        self._limiter = _RateLimiter(min_interval=1.0 / rps)
        self._client = httpx.Client(
            base_url=base_url,
            timeout=config.HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._cache_dir = config.CACHE_DIR / chain
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"network": 0, "cache": 0, "retries": 0}

    # -- cache ---------------------------------------------------------------

    def _cache_path(self, method: str, url: str, body: Any) -> Path:
        key = json.dumps([method, url, body], sort_keys=True, default=str)
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self._cache_dir / f"{digest}.json"

    def _read_cache(self, path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - entry.get("fetched_at", 0) > self.cache_ttl:
            return None
        return entry.get("body")

    def _write_cache(self, path: Path, url: str, status: int, body: str) -> None:
        payload = {"url": url, "status": status, "fetched_at": time.time(), "body": body}
        path.write_text(json.dumps(payload), encoding="utf-8")

    # -- request -------------------------------------------------------------

    def request_text(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> str:
        """Return the response body as text, from cache when fresh."""
        cache_path = self._cache_path(method, url, json_body)
        if use_cache:
            cached = self._read_cache(cache_path)
            if cached is not None:
                self.stats["cache"] += 1
                log.debug("cache hit %s %s", method, url)
                return cached

        last_error: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            self._limiter.wait()
            try:
                resp = self._client.request(method, url, json=json_body, headers=headers)
            except httpx.HTTPError as exc:  # transport-level: retry
                last_error = exc
                self._sleep_backoff(attempt)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                self._sleep_backoff(attempt, floor=retry_after)
                continue

            resp.raise_for_status()
            self.stats["network"] += 1
            if use_cache:
                self._write_cache(cache_path, url, resp.status_code, resp.text)
            return resp.text

        raise RuntimeError(f"giving up on {method} {url} after {config.MAX_RETRIES} attempts") from last_error

    def get_json(self, url: str, *, headers: dict[str, str] | None = None, use_cache: bool = True) -> Any:
        return json.loads(self.request_text("GET", url, headers=headers, use_cache=use_cache))

    def post_json(self, url: str, *, json_body: Any, use_cache: bool = True) -> Any:
        return json.loads(self.request_text("POST", url, json_body=json_body, use_cache=use_cache))

    def _sleep_backoff(self, attempt: int, floor: float | None = None) -> None:
        self.stats["retries"] += 1
        delay = config.BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.4)
        if floor is not None:
            delay = max(delay, floor)
        log.warning("backing off %.1fs (attempt %d)", delay, attempt + 1)
        time.sleep(delay)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None  # HTTP-date form; the exponential backoff covers it
