"""The substitution engine. Brief section 4, milestone 8.

The engine prices two routes to the same thing - a ready-made SKU and a DIY
composition - and says which wins. The tests that matter are the ones that stop
it becoming a DIY advocate:

  * an item that cannot be priced makes the whole DIY cost unknown, and the item
    is still listed. Dropping it would silently understate DIY, which is the one
    direction this tool must not flatter (copy rule 2's spirit).
  * when ready-made is cheaper the verdict says so. Brief section 4.5: the engine
    must be willing to say "just buy it".
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank.archetypes import compare
from bonusrank.db import connect
from bonusrank.seed import load_archetypes, load_seed

TODAY = date(2026, 9, 17)
NEXT_WEEK = (TODAY + timedelta(days=7)).isoformat()
LAST_WEEK = (TODAY - timedelta(days=7)).isoformat()

ARCHETYPE_YAML = """
- key: test_pudding
  name: Test pudding
  serving_g: 200
  target_protein_g: 20
  max_prep_minutes: 5
  meal_kind: snack
  ready_made:
    food_types: [proteine_pudding]
  compositions:
    - name: kwark + cacao + zoetstof
      effort_minutes: 3
      similarity_confidence: medium
      taste_delta_note: minder zoet, zuurder
      texture_delta_note: korreliger
      items:
        - food_type: kwark_mager
          grams: 200
        - food_type: cacaopoeder
          grams: 10
        - food_type: zoetstof
          grams: 1
          pantry_price_eur_per_kg: 25.00
"""


@pytest.fixture()
def conn(tmp_path):
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    path = tmp_path / "archetypes_test.yaml"
    path.write_text(ARCHETYPE_YAML, encoding="utf-8")
    load_archetypes(connection, path=path)
    return connection


def _priced(conn, sku, name, food_type_key, raw_unit_text, price, **kwargs):
    row = conn.execute("SELECT id FROM food_types WHERE key=?", (food_type_key,)).fetchone()
    conn.execute(
        "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
        "match_method, match_score, first_seen) VALUES ('ah',?,?,?,?,'alias_exact',1.0,?)",
        (sku, name, raw_unit_text, row[0], TODAY.isoformat()),
    )
    product_id = conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()[0]
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_from, valid_to) VALUES (?,?,?,?,?,?,?,0,?,?)",
        (product_id, TODAY.isoformat(), price, kwargs.get("mechanic", "not_a_promo"),
         kwargs.get("raw_text"), kwargs.get("required", 1), price,
         kwargs.get("valid_from"), kwargs.get("valid_to")),
    )
    return product_id


def _stock_diy(conn):
    """Price every DIY item of the fixture archetype. 500 g kwark at EUR 1.20."""
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    _priced(conn, "wi2", "AH Cacaopoeder", "cacaopoeder", "250 g", 2.50)


def _only(conn, **kwargs):
    comparisons = compare(conn, on=TODAY, **kwargs)
    assert len(comparisons) == 1
    return comparisons[0]


# -- DIY pricing -----------------------------------------------------------

def test_a_fully_priced_composition_costs_the_sum_of_its_items(conn):
    _stock_diy(conn)
    composition = _only(conn).compositions[0]

    # 200 g kwark at 2.40/kg = 0.48; 10 g cacao at 10.00/kg = 0.10;
    # 1 g zoetstof at the seeded pantry 25.00/kg = 0.025.
    assert composition.eur == pytest.approx(0.605)
    assert composition.unpriced == ()


def test_an_unpriceable_item_makes_the_total_unknown_but_is_still_listed(conn):
    """Never the sum of the rest: that would understate DIY."""
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    # cacaopoeder deliberately has no observation at all.
    composition = _only(conn).compositions[0]

    assert composition.eur is None
    assert composition.eur_per_g_protein is None
    assert composition.unpriced == ("cacaopoeder",)
    assert [i.food_type_key for i in composition.items] == [
        "kwark_mager", "cacaopoeder", "zoetstof",
    ]
    assert next(i for i in composition.items if i.food_type_key == "cacaopoeder").eur is None


def test_a_pantry_item_is_costed_from_the_seed_and_flagged(conn):
    _stock_diy(conn)
    item = next(i for i in _only(conn).compositions[0].items
                if i.food_type_key == "zoetstof")

    assert item.is_pantry is True
    assert item.eur == pytest.approx(0.025)
    assert item.price is None, "a pantry price is seeded, not observed"


def test_composition_protein_sums_the_items_not_the_archetype_target(conn):
    _stock_diy(conn)
    composition = _only(conn).compositions[0]

    kwark, cacao = (conn.execute(
        "SELECT protein_per_100g FROM food_types WHERE key=?", (key,)).fetchone()[0]
        for key in ("kwark_mager", "cacaopoeder"))
    expected = kwark * 2.0 + cacao * 0.1
    assert composition.protein_g == pytest.approx(expected)


# -- ready-made pricing ----------------------------------------------------

def test_ready_made_is_scaled_to_the_archetype_serving(conn):
    """A 400 g pot priced for a 200 g serving is half the pot, not the pot."""
    _stock_diy(conn)
    _priced(conn, "wi3", "Arla Protein pudding chocolade", "proteine_pudding",
            "400 g", 2.40)
    ready = _only(conn).ready_made

    assert ready is not None
    assert ready.eur == pytest.approx(1.20)
    protein_per_100g = conn.execute(
        "SELECT protein_per_100g FROM food_types WHERE key='proteine_pudding'"
    ).fetchone()[0]
    assert ready.protein_g == pytest.approx(protein_per_100g * 2.0)


def test_the_cheapest_matching_ready_made_wins_its_side(conn):
    _stock_diy(conn)
    _priced(conn, "wi3", "Arla Protein pudding chocolade", "proteine_pudding", "200 g", 1.89)
    _priced(conn, "wi4", "Melkunie Protein pudding", "proteine_pudding", "200 g", 1.29)

    assert _only(conn).ready_made.offer.sku == "wi4"


def test_a_contains_rule_binds_a_sku_with_no_matching_food_type(conn, tmp_path):
    """Rules, not SKU ids - and a name rule must work without a food_type match."""
    path = tmp_path / "archetypes_contains.yaml"
    path.write_text(ARCHETYPE_YAML.replace(
        "    food_types: [proteine_pudding]",
        '    contains: ["protein pudding"]'), encoding="utf-8")
    conn.execute("DELETE FROM archetype_ready_made_rules")
    load_archetypes(conn, path=path)

    _stock_diy(conn)
    _priced(conn, "wi3", "Arla Protein Pudding chocolade", "proteine_pudding", "200 g", 1.89)

    assert _only(conn).ready_made.offer.sku == "wi3"


def test_resolved_ready_made_bindings_are_recorded_for_audit(conn):
    _stock_diy(conn)
    product_id = _priced(conn, "wi3", "Arla Protein pudding", "proteine_pudding",
                         "200 g", 1.89)
    _only(conn)

    row = conn.execute(
        "SELECT product_id FROM sku_archetype_map m JOIN archetypes a ON a.id=m.archetype_id "
        "WHERE a.key='test_pudding'").fetchone()
    assert row["product_id"] == product_id


# -- the verdict (section 4.5) ---------------------------------------------

def test_diy_wins_when_it_is_cheaper_per_gram_of_protein(conn):
    _stock_diy(conn)
    _priced(conn, "wi3", "Arla Protein pudding chocolade", "proteine_pudding", "200 g", 1.89)
    verdict = _only(conn).verdict

    assert verdict.winner == "diy"
    assert verdict.cheaper_pct is not None and verdict.cheaper_pct > 0
    assert verdict.extra_minutes == 3


def test_ready_made_wins_when_it_is_cheaper(conn):
    """Brief section 4.5. The engine must be willing to say 'just buy it'."""
    _stock_diy(conn)
    _priced(conn, "wi3", "Arla Protein pudding chocolade", "proteine_pudding", "200 g",
            0.45, mechanic="x_plus_y_free", raw_text="1+1 gratis", required=2,
            valid_from=LAST_WEEK, valid_to=NEXT_WEEK)
    verdict = _only(conn).verdict

    assert verdict.winner == "ready_made"
    assert "buy" in verdict.text.lower() or "koop" in verdict.text.lower()


def test_no_verdict_is_claimed_when_one_side_cannot_be_priced(conn):
    """One priced side and one unknown is not a comparison."""
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    _priced(conn, "wi3", "Arla Protein pudding", "proteine_pudding", "200 g", 1.89)
    verdict = _only(conn).verdict

    assert verdict.winner == "unknown"
    assert verdict.cheaper_pct is None


def test_no_ready_made_offer_is_not_an_error(conn):
    """Most weeks a given archetype has nothing matching on the shelf."""
    _stock_diy(conn)
    comparison = _only(conn)

    assert comparison.ready_made is None
    assert comparison.verdict.winner == "unknown"
    assert comparison.compositions[0].eur is not None


# -- filtering -------------------------------------------------------------

def test_effort_filter_drops_compositions_that_take_too_long(conn):
    _stock_diy(conn)
    assert _only(conn, max_prep_minutes=2).compositions == ()
    assert len(_only(conn, max_prep_minutes=3).compositions) == 1


def test_selecting_one_archetype_by_key(conn):
    assert [c.archetype.key for c in compare(conn, archetype_key="test_pudding",
                                             on=TODAY)] == ["test_pudding"]
    assert compare(conn, archetype_key="niet_bestaand", on=TODAY) == []
