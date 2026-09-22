"""The full-catalogue crawl. Milestone 15 (PLAN-V2 section 5).

The promo lanes answer "what is cheap this week". This answers "what does the
shop sell", which is what PLAN-V2 section 1 calls infrastructure rather than a
feature: the catalogue exists so any product can be priced into a meal, not so
anyone browses 43,000 SKUs.

Chain-generic on purpose, the same way `ingest_flat` is. A chain joins by
implementing four methods - `category_tree`, `category_children`,
`category_size`, `browse_category` - and needs no changes here.

Two properties this module exists to guarantee:

**Completeness under a paging ceiling that cannot be seen.** AH's search lane
returns HTTP 400, not an empty page, once `page * size` reaches 3000, and four
of its 28 top-level categories hold more than that. Walking top level and
stopping at the first error would silently drop their tails while reporting
success. So every node is measured before it is paged, and a node too big to
page through is replaced by its children. That also keeps the crawl correct as
an assortment grows past the line on its own.

**Resumption.** BRIEF section 7 caps requests at 2/second, so this is thousands
of requests spread over minutes. A run that dies halfway and starts over spends
the politeness budget twice for one result, which is the budget wasted on an
accident rather than on data. Progress is recorded per PAGE - a category is
dozens of them, and checkpointing whole categories would throw away up to a
category's worth of work on every kill.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .ingest import IngestStats, _ingest_sku
from .matcher import Matcher
from .parsers.promos import Promo, PromoKind

log = logging.getLogger(__name__)

# No defaults for a chain's page size or paging ceiling, deliberately. They
# used to exist, and a chain whose constants lived at module level instead of
# on its class silently inherited them - AH's real values equal what the
# defaults were, so nothing looked wrong until Jumbo, which needs different
# ones, got AH's 3000-offset ceiling applied to a site that has none and
# stopped after 15 of 712 pages **while reporting a complete crawl**.
#
# A wrong limit here does not fail; it truncates. So a chain that has not said
# what its limits are is refused rather than guessed at.


class CatalogueSource(Protocol):
    """What a chain must offer to be crawlable."""

    chain: str

    # How many products one request returns, and the offset past which the
    # chain refuses to page (None when it has no such limit). Both are
    # properties of the site, not preferences - see the note above.
    CATALOGUE_PAGE_SIZE: int
    CATALOGUE_MAX_OFFSET: int | None

    def category_tree(self) -> list[dict[str, Any]]: ...
    def category_children(self, taxonomy_id: Any) -> list[dict[str, Any]]: ...
    def category_size(self, taxonomy_id: Any) -> int: ...
    def browse_category(self, taxonomy_id: Any, *, page: int, size: int) -> list: ...


@dataclass
class CrawlStats:
    nodes: int = 0
    pages: int = 0
    pages_skipped: int = 0
    products: int = 0
    duplicates: int = 0
    requests: int = 0
    complete: bool = False
    ingest: IngestStats = field(default_factory=IngestStats)


def crawl(conn: sqlite3.Connection, adapter: CatalogueSource, *,
          max_requests: int | None = None) -> CrawlStats:
    """Walk `adapter`'s whole catalogue into `conn`, resuming if one is open.

    Discovery and fetching are **interleaved**, not two phases. Measuring every
    category first is the obvious shape and the wrong one: AH has 28 top-level
    categories, so a budgeted run spends its whole allowance on size probes and
    stores nothing. Interleaving means a run of any size makes progress on
    actual products, and the categories it never reached simply wait.

    `max_requests` is how a human says "do a slice of it today" without editing
    code. A run that stops on the budget leaves the crawl open, so the next one
    picks up where it left off rather than re-reading what it already has.
    """
    missing = [name for name in ("CATALOGUE_PAGE_SIZE", "CATALOGUE_MAX_OFFSET")
               if not hasattr(adapter, name)]
    if missing:
        raise TypeError(
            f"{type(adapter).__name__} does not declare {', '.join(missing)}. "
            "A crawl cannot guess these: too large a page size skips products, "
            "and too large a ceiling truncates a category silently. Declare "
            "them on the adapter CLASS - a module-level constant is invisible "
            "here."
        )
    page_size = adapter.CATALOGUE_PAGE_SIZE
    max_offset = adapter.CATALOGUE_MAX_OFFSET

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    crawl_id, done_pages, known_nodes = _open_crawl(conn, adapter.chain, now)

    stats = CrawlStats()
    matcher = Matcher.from_db(conn)
    budget = _Budget(max_requests)

    try:
        frontier = _roots(adapter, budget, known_nodes)
        while frontier:
            taxonomy_id, name = frontier.pop(0)
            key = str(taxonomy_id)

            if key in known_nodes:
                size = known_nodes[key]
                if size is None:
                    # Already known to be too big; its children are in the
                    # frontier via the same checkpoint on the next line.
                    children = _children(adapter, budget, taxonomy_id, known_nodes)
                    if children is None:
                        break
                    frontier[:0] = children
                    continue
            else:
                if not budget.take():
                    break
                size = adapter.category_size(taxonomy_id)
                if (size and max_offset is not None
                        and _page_count(size, page_size) * page_size > max_offset):
                    children = _children(adapter, budget, taxonomy_id, known_nodes)
                    if children is None:
                        break
                    if children:
                        _remember_node(conn, crawl_id, key, None, known_nodes)
                        frontier[:0] = children
                        continue
                    # Nothing to descend into. Take what the ceiling allows and
                    # say so loudly rather than reporting a complete crawl.
                    reachable = (max_offset // page_size) * page_size
                    log.warning(
                        "%s holds %d products but has no sub-categories; only the "
                        "first %d are reachable behind the paging ceiling",
                        name or taxonomy_id, size, reachable,
                    )
                    size = min(size, reachable)
                _remember_node(conn, crawl_id, key, size, known_nodes)

            if not size:
                continue
            stats.nodes += 1
            for page in range(_page_count(size, page_size)):
                # str() on both sides, always. The checkpoint column is TEXT
                # and a taxonomy id is an int, so comparing them raw makes
                # every lookup miss and a "resumed" crawl silently re-fetch the
                # whole catalogue - the exact cost this table exists to avoid.
                if (key, page) in done_pages:
                    stats.pages_skipped += 1
                    continue
                if not budget.take():
                    return _finish(conn, crawl_id, stats, budget, complete=False)

                products = adapter.browse_category(taxonomy_id, page=page, size=page_size)
                stored = _store_page(conn, products, matcher, stats, now)
                stats.pages += 1
                conn.execute(
                    "INSERT OR REPLACE INTO catalogue_crawl_pages "
                    "(crawl_id, node, page, fetched_at, products) VALUES (?,?,?,?,?)",
                    (crawl_id, key, page, now, stored),
                )
                conn.commit()
    except Exception:
        # Whatever went wrong, the pages already recorded stay recorded. The
        # next run resumes from them rather than re-fetching.
        conn.commit()
        raise

    complete = not frontier and budget.remaining
    return _finish(conn, crawl_id, stats, budget, complete=complete)


def _roots(adapter, budget, known_nodes) -> list[tuple[Any, str | None]]:
    if not budget.take():
        return []
    return [(node["id"], node.get("name")) for node in adapter.category_tree()]


def _children(adapter, budget, taxonomy_id, known_nodes):
    """The node's children, or None when the budget ran out mid-descent."""
    if not budget.take():
        return None
    return [(child["id"], child.get("name"))
            for child in adapter.category_children(taxonomy_id)]


def _remember_node(conn, crawl_id, key, size, known_nodes) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO catalogue_crawl_nodes (crawl_id, node, size) "
        "VALUES (?,?,?)", (crawl_id, key, size),
    )
    known_nodes[key] = size
    conn.commit()


def _page_count(size: int, page_size: int) -> int:
    return (size + page_size - 1) // page_size


# -- storing -------------------------------------------------------------------

def _store_page(conn, products, matcher, stats: CrawlStats, now: str) -> int:
    """Send one page through the same core `ingest` already uses.

    Nothing chain-specific and nothing catalogue-specific: the unit-size parse,
    the section-7 unit-price cross-check, category exclusion and matching are
    the tested ones, so a catalogue product and a bonus product cannot end up
    costed by two different rules.
    """
    stored = 0
    for product in products:
        if not product.sku:
            continue
        seen = conn.execute(
            "SELECT 1 FROM products WHERE chain=? AND sku=?",
            (product.chain, product.sku),
        ).fetchone()
        if seen:
            stats.duplicates += 1

        # A catalogue listing is a shelf price by definition, and NOT_A_PROMO
        # is a positive finding here rather than a parse failure: the price is
        # known and no discount applies. UNKNOWN would be the lie - it means
        # "there is a mechanic and we could not read it", and it refuses to
        # price itself. Shelf and promo also stay in separate lanes because
        # milestone 8 measured what mixing them costs: `bonusrank list`
        # silently dropping from 174 rated offers to 160.
        promo = Promo(raw_text=None, kind=PromoKind.NOT_A_PROMO,
                      effective_multiplier=1.0)
        _ingest_sku(
            conn, chain=product.chain, sku=product.sku, name=product.name,
            brand=product.brand, raw_unit_text=product.raw_unit_text,
            stated_unit_price_text=product.stated_unit_price_text,
            category=product.category, shelf_price=product.shelf_price,
            bonus_price=None, ean=product.ean, promo=promo,
            is_personal=False, valid_from=None, valid_to=None,
            matcher=matcher, stats=stats.ingest, now=now,
            queue_unmatched=False,
        )
        conn.execute(
            "UPDATE products SET subcategory=?, image_url=?, image_width=? "
            "WHERE chain=? AND sku=?",
            (product.subcategory, product.image_url, product.image_width,
             product.chain, product.sku),
        )
        if not seen:
            stats.products += 1
        stored += 1
    return stored


# -- crawl bookkeeping ---------------------------------------------------------

def _open_crawl(conn, chain: str, now: str):
    """Resume the open crawl for this chain, or start a new one.

    An unfinished crawl is resumed; a finished one is left alone and a fresh
    crawl begun. Resumption is for an interrupted run - a second deliberate
    crawl is a refresh, and must actually re-read the shop or prices freeze.
    """
    row = conn.execute(
        "SELECT id FROM catalogue_crawls WHERE chain=? AND finished_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1", (chain,),
    ).fetchone()
    if row:
        crawl_id = row[0]
        done = {
            (r["node"], r["page"])
            for r in conn.execute(
                "SELECT node, page FROM catalogue_crawl_pages WHERE crawl_id=?",
                (crawl_id,),
            )
        }
        nodes = {
            r["node"]: r["size"]
            for r in conn.execute(
                "SELECT node, size FROM catalogue_crawl_nodes WHERE crawl_id=?",
                (crawl_id,),
            )
        }
        return crawl_id, done, nodes

    cursor = conn.execute(
        "INSERT INTO catalogue_crawls (chain, started_at) VALUES (?,?)", (chain, now)
    )
    conn.commit()
    return cursor.lastrowid, set(), {}


def _finish(conn, crawl_id: int, stats: CrawlStats, budget: _Budget, *,
            complete: bool) -> CrawlStats:
    if complete:
        conn.execute("UPDATE catalogue_crawls SET finished_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"), crawl_id))
    conn.commit()
    stats.complete = complete
    stats.requests = budget.spent
    return stats


class _Budget:
    """Counts requests, and says no once the caller's ceiling is reached."""

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.spent = 0

    def take(self) -> bool:
        if not self.remaining:
            return False
        self.spent += 1
        return True

    @property
    def remaining(self) -> bool:
        return self.limit is None or self.spent < self.limit
