"""The full-catalogue crawl. Milestone 15 (PLAN-V2 section 5).

Three things this has to get right, and they are the three things the tests
here are about.

**It must not lose products to a paging limit it cannot see.** AH's search lane
returns HTTP 400 - not an empty page, an error - once `page * size` reaches
3000, and four of its 28 top-level categories are larger than that. A crawl
that walks top-level categories and stops at the first error silently drops
their tails and reports success. So the crawl measures each node first and
descends into its children when it is too big to page through.

**It must be resumable.** BRIEF section 7 caps requests at 2/second, so a
catalogue crawl is thousands of requests spread over minutes. A run that dies
halfway and starts over spends the politeness budget twice for one result.

**It must stay inside the request budget.** The cap is not advisory; it is the
thing that makes using these undocumented endpoints defensible at all.

No network anywhere here. The fake adapter below is a dictionary with a request
counter, which is also what makes the budget assertion possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bonusrank import catalogue
from bonusrank.db import connect
from bonusrank.models import RawProduct
from bonusrank.seed import load_seed

# Chosen small so a test can exceed it in one readable fixture. The real value
# is AH's own 3000.
MAX_OFFSET = 60
PAGE_SIZE = 20


class FakeCatalogue:
    """A three-level category tree with a hard paging ceiling, like AH's.

    `requests` counts every call that would have hit the network, which is what
    the politeness and resumption tests assert on.
    """

    chain = "ah"
    CATALOGUE_PAGE_SIZE = PAGE_SIZE
    CATALOGUE_MAX_OFFSET = MAX_OFFSET

    def __init__(self, tree, products, *, fail_after=None):
        self._tree = tree
        self._products = products          # taxonomy id -> list of (sku, name)
        self.requests = 0
        self._fail_after = fail_after

    def _tick(self):
        self.requests += 1
        if self._fail_after is not None and self.requests > self._fail_after:
            raise RuntimeError("network died mid-crawl")

    def category_tree(self):
        self._tick()
        return [{"id": t["id"], "name": t["name"]} for t in self._tree]

    def category_children(self, taxonomy_id):
        self._tick()
        for node in self._walk():
            if node["id"] == taxonomy_id:
                return [{"id": c["id"], "name": c["name"]}
                        for c in node.get("children", [])]
        return []

    def category_size(self, taxonomy_id):
        self._tick()
        return len(self._products.get(taxonomy_id, []))

    def browse_category(self, taxonomy_id, *, page=0, size=PAGE_SIZE):
        self._tick()
        if (self.CATALOGUE_MAX_OFFSET is not None
                and page * size >= self.CATALOGUE_MAX_OFFSET):
            raise AssertionError(
                f"the crawl asked for offset {page * size}, past the ceiling - "
                "this is the HTTP 400 that loses a category's tail"
            )
        rows = self._products.get(taxonomy_id, [])[page * size:(page + 1) * size]
        return [_product(sku, name) for sku, name in rows]

    def _walk(self, nodes=None):
        for node in nodes if nodes is not None else self._tree:
            yield node
            yield from self._walk(node.get("children", []))


def _product(sku, name):
    return RawProduct(
        chain="ah", sku=sku, name=name, brand="AH", raw_unit_text="500 g",
        category="Vlees", subcategory="Rundergehakt", shelf_price=2.50,
        image_url=f"https://static.ah.nl/dam/product/{sku}", image_width=400,
    )


def _skus(n, prefix="p"):
    return [(f"{prefix}{i}", f"Product {i}") for i in range(n)]


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


@pytest.fixture()
def small():
    """One category, comfortably inside the ceiling."""
    return FakeCatalogue(
        tree=[{"id": 1, "name": "Vlees"}],
        products={1: _skus(30)},
    )


@pytest.fixture()
def oversized():
    """A category too big to page through, whose children are not.

    This is AH's Drogisterij: 3531 products behind a 3000-offset ceiling.
    """
    return FakeCatalogue(
        tree=[{"id": 1, "name": "Drogisterij",
               "children": [{"id": 11, "name": "Shampoo"},
                            {"id": 12, "name": "Tandpasta"}]}],
        products={1: _skus(100), 11: _skus(40, "a"), 12: _skus(50, "b")},
    )


# -- completeness --------------------------------------------------------------

def test_a_crawl_stores_every_product_in_a_category(conn, small):
    stats = catalogue.crawl(conn, small)

    assert stats.products == 30
    stored = conn.execute("SELECT count(*) FROM products WHERE chain='ah'").fetchone()[0]
    assert stored == 30


def test_a_category_too_big_to_page_through_is_crawled_by_its_children(conn, oversized):
    """The bug this design exists to prevent.

    Walking node 1 directly would need offset 60, 80 - past the ceiling - and
    the fake raises rather than returning an empty page, exactly as AH returns
    400 rather than an empty page. A crawl that caught that error and moved on
    would report success having stored 60 of 100 products.
    """
    stats = catalogue.crawl(conn, oversized)

    # 40 + 50 from the two children; node 1 itself is never paged.
    assert stats.products == 90
    assert {r[0] for r in conn.execute("SELECT sku FROM products")} == {
        *(f"a{i}" for i in range(40)), *(f"b{i}" for i in range(50)),
    }


def test_a_product_in_two_categories_is_stored_once(conn):
    """Categories overlap; `products` is keyed on (chain, sku) and the crawl
    must not treat the second sighting as a new product."""
    adapter = FakeCatalogue(
        tree=[{"id": 1, "name": "Vlees"}, {"id": 2, "name": "Maaltijden"}],
        products={1: _skus(5), 2: _skus(5)},
    )

    stats = catalogue.crawl(conn, adapter)

    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 5
    assert stats.duplicates == 5


def test_every_stored_product_carries_its_image_and_category(conn, small):
    """PLAN-V2's own acceptance criterion for this milestone."""
    catalogue.crawl(conn, small)

    row = conn.execute(
        "SELECT image_url, image_width, category, subcategory FROM products LIMIT 1"
    ).fetchone()
    assert row["image_url"].startswith("https://static.ah.nl/")
    assert row["image_width"] == 400
    assert row["category"] == "Vlees"
    assert row["subcategory"] == "Rundergehakt"


def test_a_shelf_price_is_recorded_on_the_not_a_promo_lane(conn, small):
    """A catalogue price is a shelf price, and must never land in the promo
    lane - milestone 8 already measured what mixing the two costs."""
    catalogue.crawl(conn, small)

    mechanics = {r[0] for r in conn.execute("SELECT promo_mechanic FROM price_observations")}
    assert mechanics == {"not_a_promo"}


def test_a_chain_with_no_paging_ceiling_is_crawled_flat(conn):
    """Milestone 16. Jumbo answers at offset 17,000 where AH errors past 3000,
    so it declares `CATALOGUE_MAX_OFFSET = None` and walks its whole assortment
    as one list. A made-up limit would send the crawl looking for children that
    do not exist."""
    adapter = FakeCatalogue(
        tree=[{"id": "", "name": "hele assortiment"}], products={"": _skus(200)},
    )
    adapter.CATALOGUE_MAX_OFFSET = None

    stats = catalogue.crawl(conn, adapter)

    assert stats.products == 200
    assert stats.nodes == 1


# -- resumption ----------------------------------------------------------------

def test_a_killed_crawl_resumes_instead_of_starting_over(conn, oversized):
    """The politeness budget spent twice for one result is the failure here."""
    # Planning this tree costs 5 requests (the tree, node 1's size, its
    # children, and each child's size), so the kill has to land after a couple
    # of pages have actually been stored.
    dying = FakeCatalogue(oversized._tree, oversized._products, fail_after=8)
    with pytest.raises(RuntimeError):
        catalogue.crawl(conn, dying)

    before = conn.execute("SELECT count(*) FROM products").fetchone()[0]
    assert before > 0, "the fixture must die partway, not before storing anything"

    resumed = FakeCatalogue(oversized._tree, oversized._products)
    stats = catalogue.crawl(conn, resumed)

    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 90
    assert stats.pages_skipped > 0, "a resumed crawl re-fetched every page"


def test_a_finished_crawl_starts_a_fresh_one_rather_than_resuming(conn, small):
    """Resumption is for an interrupted run. A second deliberate crawl is a
    refresh and must actually re-read the catalogue, or prices freeze."""
    catalogue.crawl(conn, small)
    second = FakeCatalogue(small._tree, small._products)

    stats = catalogue.crawl(conn, second)

    assert stats.pages_skipped == 0
    assert stats.pages > 0


def test_progress_is_recorded_per_page_not_per_category(conn, oversized):
    """A category is dozens of pages. Checkpointing whole categories would
    discard up to a category's worth of work on every kill."""
    catalogue.crawl(conn, oversized)

    pages = conn.execute("SELECT count(*) FROM catalogue_crawl_pages").fetchone()[0]
    assert pages >= 5   # 40 and 50 products at 20 per page, plus the tails


# -- the adapter contract ------------------------------------------------------

def test_every_crawlable_adapter_declares_its_limits_on_the_class():
    """The bug this exists to prevent, because it was silent for a whole
    milestone.

    `catalogue.crawl` reads these with `getattr(adapter, ...)`, so a constant
    defined at MODULE level in an adapter file is invisible and the crawl
    quietly falls back to its own defaults. That went unnoticed for AH because
    AH's real values happen to equal those defaults. Jumbo, whose values differ,
    got AH's 3000-offset ceiling applied to a site that has none - and stopped
    after 15 of 712 pages while reporting a complete crawl.
    """
    from bonusrank.adapters.ah import AHAdapter
    from bonusrank.adapters.jumbo import JumboAdapter

    for adapter in (AHAdapter, JumboAdapter):
        assert "CATALOGUE_PAGE_SIZE" in dir(adapter), adapter.__name__
        assert "CATALOGUE_MAX_OFFSET" in dir(adapter), adapter.__name__

    assert AHAdapter.CATALOGUE_MAX_OFFSET == 3000
    assert JumboAdapter.CATALOGUE_MAX_OFFSET is None
    assert JumboAdapter.CATALOGUE_PAGE_SIZE == 24


def test_an_adapter_that_declares_no_limits_is_refused_rather_than_guessed_at(conn):
    """A wrong limit does not fail, it truncates. So there is no default."""
    class NewChain:
        """A new chain's adapter, written without reading catalogue.py first."""
        chain = "somewhere"

        def category_tree(self):
            raise AssertionError("must be refused before any request is made")

    adapter = NewChain()

    with pytest.raises(TypeError, match="does not declare"):
        catalogue.crawl(conn, adapter)


# -- the request budget --------------------------------------------------------

def test_the_crawl_stops_at_the_request_budget_it_was_given(conn):
    """BRIEF section 7's cap is not advisory. `max_requests` is how a human
    says "just do a slice of it today" without editing code."""
    adapter = FakeCatalogue(
        tree=[{"id": 1, "name": "Vlees"}], products={1: _skus(200)},
    )

    stats = catalogue.crawl(conn, adapter, max_requests=5)

    assert adapter.requests <= 5
    assert not stats.complete
    assert stats.products > 0


def test_an_interrupted_budget_run_resumes_where_it_stopped(conn):
    adapter = FakeCatalogue(tree=[{"id": 1, "name": "Vlees"}], products={1: _skus(59)})
    first = catalogue.crawl(conn, adapter, max_requests=4)
    assert not first.complete

    more = FakeCatalogue(adapter._tree, adapter._products)
    second = catalogue.crawl(conn, more)

    assert second.complete
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 59


def test_the_crawl_never_asks_for_an_offset_past_the_ceiling(conn, oversized):
    """Belt and braces: the fake raises on a bad offset, so this passing at all
    means no request crossed the line. Asserted explicitly because a future
    refactor could start swallowing that error."""
    catalogue.crawl(conn, oversized)  # must not raise
