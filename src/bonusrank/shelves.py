"""Shelf taxonomy: each chain's departments on one shared set of shelves.

Milestone 19. The map is authored in `data/seed/category_map.yaml`; nothing
here guesses. A category the map doesn't know has no shelf, and
`record_unmapped` puts it in the review queue.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config
from .db import record_review

MAP_PATH = config.PROJECT_ROOT / "data" / "seed" / "category_map.yaml"

# Above this share of products without a shelf, the build fails. Something
# new is big enough that the app's browse view would visibly be missing it.
MAX_UNMAPPED = 0.10


class TooManyUnmapped(Exception):
    pass


@dataclass(frozen=True)
class ShelfMap:
    shelves: dict[str, str]              # key -> Dutch label, in display order
    chains: dict[str, dict[str, str]]    # chain -> {category: shelf key}

    def shelf_for(self, chain: str, category: str | None) -> str | None:
        if not category:
            return None
        return self.chains.get(chain, {}).get(category)

    def check_rate(self, counts) -> float:
        """Share of products without a shelf. Raises above MAX_UNMAPPED."""
        total = sum(n for _, _, n in counts)
        unmapped = sum(n for chain, cat, n in counts if not self.shelf_for(chain, cat))
        rate = unmapped / total if total else 0.0
        if rate > MAX_UNMAPPED:
            raise TooManyUnmapped(
                f"{rate:.1%} of products have no shelf (limit {MAX_UNMAPPED:.0%}); "
                "add the new categories to data/seed/category_map.yaml")
        return rate


def load(path: Path | None = None) -> ShelfMap:
    raw = yaml.safe_load(Path(path or MAP_PATH).read_text(encoding="utf-8"))
    shelves = dict(raw["shelves"])
    chains = {chain: dict(table or {}) for chain, table in raw["chains"].items()}
    for chain, table in chains.items():
        for category, shelf in table.items():
            if shelf not in shelves:
                raise ValueError(f"category_map.yaml: {chain} {category!r} -> "
                                 f"unknown shelf {shelf!r}")
    return ShelfMap(shelves, chains)


def category_counts(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    return [
        (r[0], r[1], r[2]) for r in conn.execute(
            "SELECT chain, coalesce(category, ''), count(*) FROM products "
            "GROUP BY 1, 2 ORDER BY 3 DESC")
    ]


def record_unmapped(conn: sqlite3.Connection, *, observed_at: str,
                    shelf_map: ShelfMap | None = None) -> list[tuple[str, str, int]]:
    """Queue every category without a shelf for review. Returns all counts."""
    shelf_map = shelf_map or load()
    counts = category_counts(conn)
    for chain, category, n in counts:
        if category and not shelf_map.shelf_for(chain, category):
            record_review(conn, "unmapped_category", f"{chain}:{category}",
                          f"{n} products", observed_at)
    return counts
