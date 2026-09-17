"""Persist raw responses before anything parses them.

CLAUDE.md section 1: re-parsing history without re-scraping is the single most
valuable property of this codebase. Schemas will drift; you will want to fix a
parser and replay. So every response is written to

    data/raw/{chain}/{endpoint}/{iso_date}.json

before a parser is allowed to look at it. The endpoint segment is slugified from
the request path *and its discriminating query parameters* - AH serves 31 bonus
sections from one path on one date, and they must not overwrite each other.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from . import config

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _SLUG_STRIP.sub("-", value.lower()).strip("-")


_DISCRIMINATORS = ("category", "promotionType", "segmentId", "query")


def endpoint_key(url: str, *, discriminators: tuple[str, ...] = _DISCRIMINATORS) -> str:
    """Build a filesystem-safe endpoint key from a URL.

    The path always contributes. Query parameters contribute only when named in
    `discriminators`, so incidental params (an application id, a date already in
    the filename) do not fragment the store. `query` is in there for the product
    search lane: one path serves every food type we look up, and a snapshot of
    'magere kwark' must not be overwritten by 'havermout'.
    """
    parts = urlsplit(url)
    key = slugify(parts.path)
    query = dict(parse_qsl(parts.query))
    extras = [f"{slugify(name)}-{slugify(query[name])}" for name in discriminators if query.get(name)]
    if extras:
        key = f"{key}__{'__'.join(extras)}"
    return key


class RawStore:
    """Append-only-ish snapshot store. One file per chain/endpoint/day."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or config.RAW_DIR

    def path_for(self, chain: str, url: str, *, on: date | None = None) -> Path:
        stamp = (on or date.today()).isoformat()
        return self.root / chain / endpoint_key(url) / f"{stamp}.json"

    def save(self, chain: str, url: str, payload: Any, *, on: date | None = None) -> Path:
        """Write a snapshot and return its path. Overwrites same-day re-fetches."""
        path = self.path_for(chain, url, on=on)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def load(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def snapshots(self, chain: str) -> list[Path]:
        """Every stored snapshot for a chain, for replay."""
        chain_dir = self.root / chain
        return sorted(chain_dir.glob("*/*.json")) if chain_dir.exists() else []
