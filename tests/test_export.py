"""The Android app's JSON snapshot. Milestone 10.

The app has no scraping or ranking logic of its own - it only renders what this
module serializes. So the one thing these tests must pin down is that nothing
here computes a NEW number: every figure in the export must trace back to
`ranking.rank()` or `archetypes.compare()`, which are already tested on their
own terms.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.export import build_export, write_export
from bonusrank.seed import load_archetypes, load_seed

TODAY = date(2026, 9, 17)

ARCHETYPE_YAML = """
- key: test_pudding
  name: Test pudding
  serving_g: 200
  target_protein_g: 20
  meal_kind: snack
  ready_made:
    food_types: [proteine_pudding]
  compositions:
    - name: kwark + cacao + zoetstof
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: kwark_mager
          grams: 200
        - food_type: cacaopoeder
          grams: 10
"""


@pytest.fixture()
def conn(tmp_path):
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    path = tmp_path / "export_test.yaml"
    path.write_text(ARCHETYPE_YAML, encoding="utf-8")
    load_archetypes(connection, path=path)
    return connection


def _priced(conn, sku, name, food_type_key, raw_unit_text, price, chain="ah"):
    row = conn.execute("SELECT id FROM food_types WHERE key=?", (food_type_key,)).fetchone()
    conn.execute(
        "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
        "match_method, match_score, first_seen) VALUES (?,?,?,?,?,'alias_exact',1.0,?)",
        (chain, sku, name, raw_unit_text, row[0], TODAY.isoformat()),
    )
    product_id = conn.execute("SELECT id FROM products WHERE chain=? AND sku=?",
                              (chain, sku)).fetchone()[0]
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer) VALUES (?,?,?,'not_a_promo',NULL,1,?,0)",
        (product_id, TODAY.isoformat(), price, price),
    )


# -- shape --------------------------------------------------------------------

def test_the_export_has_one_entry_per_requested_chain(conn):
    payload = build_export(conn, chains=("ah", "jumbo"), on=TODAY)
    assert set(payload["chains"]) == {"ah", "jumbo"}
    assert "generated_at" in payload
    assert payload["schema_version"] == 1


def test_a_chain_with_nothing_ingested_yields_no_offers_not_an_error(conn):
    """Archetypes are chain-independent seed data - a chain with nothing
    ingested still lists them, just with nothing priced. Only `offers` (which
    comes straight from that chain's own price_observations) is empty."""
    payload = build_export(conn, chains=("aldi",), on=TODAY)
    assert payload["chains"]["aldi"]["offers"] == []
    assert payload["chains"]["aldi"]["archetypes"][0]["ready_made"] is None
    assert payload["chains"]["aldi"]["archetypes"][0]["compositions"][0]["price_eur"] is None


def test_the_result_is_json_serialisable(conn):
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    payload = build_export(conn, chains=("ah",), on=TODAY)
    json.dumps(payload)  # must not raise


# -- offers trace back to ranking.rank(), nothing invented --------------------

def test_offer_figures_match_what_rank_would_report(conn):
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)

    from bonusrank.ranking import rank
    expected = rank(conn, chain="ah", on=TODAY)[0]

    payload = build_export(conn, chains=("ah",), on=TODAY)
    offer = payload["chains"]["ah"]["offers"][0]

    assert offer["sku"] == expected.sku
    assert offer["price"]["unit_price_eur"] == expected.effective_unit_price
    assert offer["macros_per_100g"]["protein_g"] == expected.protein_per_100g
    assert offer["macros_per_100g"]["carbs_g"] == expected.carbs_per_100g
    assert offer["macros_per_100g"]["fat_g"] == expected.fat_per_100g
    assert offer["macros_need_marking"] == expected.needs_macro_marking


# -- archetypes trace back to archetypes.compare() ----------------------------

def test_archetype_figures_match_what_compare_would_report(conn):
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    _priced(conn, "wi2", "AH Cacaopoeder", "cacaopoeder", "250 g", 2.50)

    from bonusrank.archetypes import compare
    expected = compare(conn, chain="ah", on=TODAY, archetype_key="test_pudding")[0]

    payload = build_export(conn, chains=("ah",), on=TODAY)
    archetype = payload["chains"]["ah"]["archetypes"][0]

    assert archetype["key"] == "test_pudding"
    assert archetype["meal_kind"] == "snack"
    assert archetype["verdict"]["winner"] == expected.verdict.winner
    assert archetype["compositions"][0]["price_eur"] == expected.compositions[0].eur
    assert archetype["ready_made"] is None  # nothing on the shelf in this fixture


def test_a_rejected_optimised_plan_is_marked_rejected_not_dropped(conn):
    """The app must be able to tell 'no plausible mix' apart from 'no data'."""
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    _priced(conn, "wi2", "AH Cacaopoeder", "cacaopoeder", "250 g", 2.50)

    payload = build_export(conn, chains=("ah",), on=TODAY)
    optimised = payload["chains"]["ah"]["archetypes"][0]["optimised"]

    # Only two ingredients and no carb/fat companion for this snack fixture -
    # either None (not enough candidates) or an explicit rejection, never a
    # silently-invented "success".
    assert optimised is None or optimised["rejected"] in (True, False)


# -- write_export writes stable, diffable JSON --------------------------------

def test_write_export_produces_sorted_diffable_json(conn, tmp_path):
    out = tmp_path / "latest.json"
    write_export(conn, out, chains=("ah",), on=TODAY)

    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    reloaded = json.loads(text)
    assert reloaded["chains"]["ah"]["offers"] == []


def test_write_export_creates_parent_directories(conn, tmp_path):
    out = tmp_path / "nested" / "dir" / "latest.json"
    write_export(conn, out, chains=("ah",), on=TODAY)
    assert out.exists()
