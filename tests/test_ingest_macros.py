"""Choosing which SKUs get a label-macro request. docs/AUDIT.md finding 5.

`product_macros` has never held a row in production: tier-1 FIR label figures
need `ingest --with-macros`, and no workflow passed it, so every macro the app
has ever shown came from the generic seed. BRIEF section 2 says to prefer the
SKU's own label "always", and `ranking.resolve_macros` already does - there was
simply never anything there to prefer.

It costs one request per SKU, so the ORDER is the whole design. After the
milestone 15 catalogue crawl there are 4,360 matched AH products and 254 of
them on a current offer; selecting "any matched product" spends the budget
almost entirely on rows no ranking prints.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.ingest import macro_candidates
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 22)


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


def _product(conn, sku, *, matched=True, promo=None, valid_to=None, chain="ah"):
    food_type_id = conn.execute(
        "SELECT id FROM food_types WHERE key='kwark_mager'"
    ).fetchone()[0] if matched else None
    conn.execute(
        "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
        "match_method, match_score, first_seen) VALUES (?,?,?,'500 g',?,'alias_exact',1.0,?)",
        (chain, sku, f"Product {sku}", food_type_id, TODAY.isoformat()),
    )
    pid = conn.execute("SELECT id FROM products WHERE chain=? AND sku=?", (chain, sku)).fetchone()[0]
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_to) VALUES (?,?,1.20,?,?,1,1.20,0,?)",
        (pid, TODAY.isoformat(), promo or "not_a_promo",
         "1+1 gratis" if promo else None,
         valid_to.isoformat() if valid_to else None),
    )
    return pid


def test_a_product_on_a_current_offer_is_fetched_before_one_that_is_not(conn):
    """The ranking prints offers. A matched product sitting on the shelf with
    no promo may never be seen at all."""
    _product(conn, "shelf_only")
    _product(conn, "on_offer", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))

    assert macro_candidates(conn, "ah", 1, on=TODAY) == ["on_offer"]


def test_an_expired_offer_does_not_count_as_a_current_one(conn):
    _product(conn, "expired", promo="x_plus_y_free", valid_to=TODAY - timedelta(days=1))
    _product(conn, "live", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))

    assert macro_candidates(conn, "ah", 1, on=TODAY) == ["live"]


def test_an_unmatched_product_is_never_a_candidate(conn):
    """Its macros would have nowhere to improve on: `resolve_macros` prefers a
    label over a food type, and an unmatched product has no food type either
    way. The request would buy a number the ranking cannot use."""
    _product(conn, "unmatched", matched=False,
             promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))

    assert macro_candidates(conn, "ah", 10, on=TODAY) == []


def test_a_product_that_already_has_label_macros_is_not_fetched_twice(conn):
    pid = _product(conn, "known", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))
    from bonusrank.ingest import LABEL_PARSER_VERSION

    conn.execute(
        "INSERT INTO product_macros (product_id, protein_per_100g, source, "
        "confidence, observed_at, parser_version) VALUES (?,10.0,'label','high',?,?)",
        (pid, TODAY.isoformat(), LABEL_PARSER_VERSION),
    )
    _product(conn, "new", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))

    assert macro_candidates(conn, "ah", 10, on=TODAY) == ["new"]


def test_the_limit_is_a_request_budget_and_is_respected(conn):
    for i in range(5):
        _product(conn, f"p{i}", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))

    assert len(macro_candidates(conn, "ah", 3, on=TODAY)) == 3


def test_another_chain_is_not_included(conn):
    """`fetch_label_macros` only knows how to read AH's FIR endpoint, and looks
    products up with `chain='ah'` hardcoded."""
    _product(conn, "jumbo_one", chain="jumbo",
             promo="x_plus_y_free", valid_to=TODAY + timedelta(days=5))

    assert macro_candidates(conn, "ah", 10, on=TODAY) == []


def test_an_offer_with_no_end_date_still_counts_as_current(conn):
    """Aldi publishes windows; some AH shelf-price rows do not. A NULL valid_to
    means "no published end", not "expired"."""
    _product(conn, "open_ended", promo="x_plus_y_free", valid_to=None)

    assert macro_candidates(conn, "ah", 10, on=TODAY) == ["open_ended"]


def test_label_macros_from_an_older_parser_are_fetched_again_after_new_ones(conn):
    """The cooked-table bug: rows parsed before the fix must be refreshed,
    or they'd stay wrong forever, since products with macros are skipped."""
    from bonusrank.ingest import LABEL_PARSER_VERSION

    old = _product(conn, "old", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=3))
    _product(conn, "none", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=3))
    current = _product(conn, "current", promo="x_plus_y_free", valid_to=TODAY + timedelta(days=3))
    conn.execute("INSERT INTO product_macros (product_id, protein_per_100g, source, confidence, "
                 "observed_at, parser_version) VALUES (?, 8.4, 'label', 'high', '2026-09-20', 1)", (old,))
    conn.execute("INSERT INTO product_macros (product_id, protein_per_100g, source, confidence, "
                 "observed_at, parser_version) VALUES (?, 24.0, 'label', 'high', '2026-09-20', ?)",
                 (current, LABEL_PARSER_VERSION))

    assert macro_candidates(conn, "ah", 10, on=TODAY) == ["none", "old"]
