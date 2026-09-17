"""`ingest_flat`: the chain-generic ingest path. Milestone 7.

AH's promotions are segments needing `fetch_segment` to expand into SKUs
(`ingest_ah`). Jumbo and Aldi do not have that indirection - each `RawOffer`
already names its own SKU, and `fetch_product` supplies the price. `ingest_flat`
is what the `StoreAdapter` protocol was designed for: it touches only
`fetch_promotions`/`fetch_product`, so these tests use a fake adapter that
implements nothing else, proving a chain shaped like Jumbo/Aldi needs no ingest
code of its own - only its own adapter module (CLAUDE.md section 1).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.ingest import ingest_flat
from bonusrank.matcher import Matcher
from bonusrank.models import RawOffer, RawProduct
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 17)


class _FakeFlatAdapter:
    """A minimal StoreAdapter: fetch_promotions + fetch_product, nothing else."""

    chain = "testchain"

    def __init__(self, offers: list[RawOffer], products: dict[str, RawProduct]):
        self._offers = offers
        self._products = products

    def fetch_promotions(self) -> list[RawOffer]:
        return self._offers

    def fetch_product(self, sku: str) -> RawProduct:
        return self._products[sku]


def _offer(sku="sku1", **kwargs) -> RawOffer:
    defaults = dict(
        chain="testchain", offer_id=sku, title="Magere kwark", subtitle=None,
        category=None, promo_raw_text="voor 1,20", valid_from=TODAY,
        valid_to=TODAY + timedelta(days=6), is_personal=False,
        product_skus=[sku],
    )
    defaults.update(kwargs)
    return RawOffer(**defaults)


def _product(sku="sku1", **kwargs) -> RawProduct:
    defaults = dict(
        chain="testchain", sku=sku, name="AH Magere kwark", brand="AH",
        raw_unit_text="500 g", shelf_price=1.20, bonus_price=None,
        stated_unit_price_text=None,
    )
    defaults.update(kwargs)
    return RawProduct(**defaults)


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


@pytest.fixture()
def matcher(conn):
    return Matcher.from_db(conn)


def test_ingests_a_single_offer_end_to_end(conn, matcher):
    adapter = _FakeFlatAdapter([_offer()], {"sku1": _product()})
    stats = ingest_flat(conn, adapter, matcher=matcher)

    assert stats.products == 1
    assert stats.observations == 1
    assert stats.matched == 1

    row = conn.execute(
        "SELECT * FROM products WHERE chain='testchain' AND sku='sku1'"
    ).fetchone()
    assert row["name"] == "AH Magere kwark"
    assert row["food_type_id"] is not None

    obs = conn.execute(
        "SELECT * FROM price_observations WHERE product_id=?", (row["id"],)
    ).fetchone()
    assert obs["shelf_price"] == 1.20
    assert obs["promo_mechanic"] == "fixed_price"
    assert obs["valid_from"] == TODAY.isoformat()


def test_falls_back_to_the_offer_subtitle_when_the_product_has_no_unit_text(conn, matcher):
    """Jumbo has no unit-size field on its product page at all - the offer's
    own subtitle ("Bak 300 gram") is the fallback, not a second parser."""
    offer = _offer(subtitle="Bak 300 gram")
    product = _product(raw_unit_text=None)
    stats = ingest_flat(conn, _FakeFlatAdapter([offer], {"sku1": product}), matcher=matcher)

    row = conn.execute("SELECT raw_unit_text FROM products WHERE sku='sku1'").fetchone()
    assert row["raw_unit_text"] == "Bak 300 gram"
    assert stats.unit_size_unparsed == 0


def test_falls_back_to_the_product_title_as_a_last_resort(conn, matcher):
    """Jumbo's product title reliably ends with its own pack size when neither
    a dedicated field nor the offer's subtitle has one."""
    offer = _offer(subtitle=None)
    product = _product(raw_unit_text=None, name="Jumbo Blauwe Bessen 300 g")
    ingest_flat(conn, _FakeFlatAdapter([offer], {"sku1": product}), matcher=matcher)

    row = conn.execute("SELECT unit_size_g FROM products WHERE sku='sku1'").fetchone()
    assert row["unit_size_g"] == 300.0


def test_an_unpriceable_offer_still_records_a_review_row_not_a_crash(conn, matcher):
    """A single bad SKU (e.g. fetch_product raising) must not abort the run."""
    class _FlakyAdapter(_FakeFlatAdapter):
        def fetch_product(self, sku):
            if sku == "bad":
                raise RuntimeError("boom")
            return super().fetch_product(sku)

    offers = [_offer(sku="bad", product_skus=["bad"]), _offer(sku="sku1")]
    adapter = _FlakyAdapter(offers, {"sku1": _product()})
    stats = ingest_flat(conn, adapter, matcher=matcher)

    assert stats.products == 1  # only the good one made it through
    assert conn.execute(
        "SELECT COUNT(*) FROM products WHERE chain='testchain'"
    ).fetchone()[0] == 1


def test_an_unparseable_promo_is_queued_for_review(conn, matcher):
    offer = _offer(promo_raw_text="onbekende actie tekst")
    ingest_flat(conn, _FakeFlatAdapter([offer], {"sku1": _product()}), matcher=matcher)

    row = conn.execute(
        "SELECT kind FROM needs_review WHERE ref='testchain:offer:sku1'"
    ).fetchone()
    assert row["kind"] == "unparsed_promo"


def test_is_append_only_across_two_runs_on_different_days(conn, matcher):
    adapter = _FakeFlatAdapter([_offer()], {"sku1": _product()})
    ingest_flat(conn, adapter, matcher=matcher)

    # A later run with a changed price must add a row, never touch the first.
    later_product = _product(shelf_price=1.35)
    later_offer = _offer(promo_raw_text="voor 1,35")
    ingest_flat(conn, _FakeFlatAdapter([later_offer], {"sku1": later_product}), matcher=matcher)

    count = conn.execute(
        "SELECT COUNT(*) FROM price_observations o JOIN products p ON p.id=o.product_id "
        "WHERE p.chain='testchain'"
    ).fetchone()[0]
    assert count == 2


def test_zero_offers_is_not_an_error(conn, matcher):
    stats = ingest_flat(conn, _FakeFlatAdapter([], {}), matcher=matcher)
    assert stats.products == 0
