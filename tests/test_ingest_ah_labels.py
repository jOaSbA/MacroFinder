"""A product's own discount label beats its segment's.

AH's online "OP=OP" segment groups ~34 unrelated products, each with its own
label (35%, 50%, 25%...). Ingest used to apply the segment's one label to all
of them, so on 2026-09-22 a €39.99 frying pan was stored as "voor 2.91" and
topped the discount ranking at 93% off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.ingest import ingest_ah
from bonusrank.models import RawOffer
from bonusrank.parsers.promos import PromoKind, parse_ah_label
from bonusrank.seed import load_seed


def _product(sku, title, before, now, label):
    return {"webshopId": sku, "title": title, "salesUnitSize": "145 g",
            "priceBeforeBonus": before, "currentPrice": now, "discountLabels": [label]}


class FakeAH:
    def fetch_promotions(self):
        return [RawOffer(
            chain="ah", offer_id="-22418", group_id="-22418", title="OP=OP",
            category="Extra online aanbiedingen", promo_raw_text="BONUS",
            promo_labels=[{"code": "DISCOUNT_FALLBACK", "defaultDescription": "voor 2.91",
                           "price": 2.91}],
            valid_from="2026-09-21", valid_to="2026-09-27")]

    def fetch_segment(self, _):
        return {"products": [
            _product(1, "BK Classic koekenpan 20cm", 39.99, 25.99,
                     {"code": "DISCOUNT_OP_IS_OP", "defaultDescription": "35% korting",
                      "percentage": 35}),
            _product(2, "John West Tonijnmoot in water", 3.59, 2.33,
                     {"code": "DISCOUNT_OP_IS_OP", "defaultDescription": "35% korting",
                      "percentage": 35}),
        ]}


@pytest.fixture()
def conn():
    c = connect(path=Path(":memory:"))
    load_seed(c)
    return c


def test_each_product_is_priced_by_its_own_label(conn):
    ingest_ah(conn, FakeAH())
    rows = {r[0]: r for r in conn.execute(
        "SELECT p.name, o.promo_raw_text, o.effective_unit_price FROM price_observations o "
        "JOIN products p ON p.id = o.product_id")}
    pan = rows["BK Classic koekenpan 20cm"]
    assert pan[1] == "35% korting"
    assert pan[2] == pytest.approx(25.99, abs=0.01)


def test_op_is_op_is_a_percentage():
    promo = parse_ah_label({"code": "DISCOUNT_OP_IS_OP", "defaultDescription": "35% korting",
                            "percentage": 35})
    assert promo.kind is PromoKind.PERCENT_OFF
    assert not promo.needs_review
