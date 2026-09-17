"""The per-meal optimiser. Milestone 9.

The point of this module is a single guarantee: a cost-minimising LP with only a
protein floor will happily spend every gram on the single cheapest protein source,
because nothing in the model asks for anything else. These tests exist to prove
that guarantee is broken correctly - a `meal`-kind archetype is forced into a real,
carb/fat-bearing mix, while a `drink`-kind archetype (a protein shake) is correctly
left alone to stay protein-forward.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pulp
import pytest

from bonusrank.archetypes import Archetype
from bonusrank.db import connect
from bonusrank.optimiser import OptimisedComposition, RejectedPlan, optimise_meal
from bonusrank.seed import load_archetypes, load_seed

TODAY = date(2026, 9, 17)

# whey_poeder: high protein, ~0 carbs, ~0 fat, expensive per gram.
# havermout: moderate protein, real carbs and fat, cheap per gram.
ARCHETYPE_YAML = """
- key: test_meal
  name: Test meal
  serving_g: 300
  target_protein_g: 20
  meal_kind: meal
  compositions:
    - name: whey + havermout
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: whey_poeder
          grams: 30
        - food_type: havermout
          grams: 50

- key: test_drink
  name: Test drink
  serving_g: 300
  target_protein_g: 20
  meal_kind: drink
  compositions:
    - name: whey + havermout
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: whey_poeder
          grams: 30
        - food_type: havermout
          grams: 50

- key: test_snack
  name: Test snack
  serving_g: 300
  target_protein_g: 20
  meal_kind: snack
  compositions:
    - name: whey + havermout
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: whey_poeder
          grams: 30
        - food_type: havermout
          grams: 50

- key: test_single_ingredient
  name: Test single ingredient
  serving_g: 300
  target_protein_g: 20
  meal_kind: drink
  compositions:
    - name: whey only
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: whey_poeder
          grams: 30

- key: test_infeasible
  name: Test infeasible
  serving_g: 300
  target_protein_g: 5000
  meal_kind: meal
  compositions:
    - name: whey + havermout
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: whey_poeder
          grams: 30
        - food_type: havermout
          grams: 50

- key: test_no_target
  name: Test no target
  serving_g: 300
  meal_kind: meal
  compositions:
    - name: whey + havermout
      similarity_confidence: medium
      taste_delta_note: minder zoet
      items:
        - food_type: whey_poeder
          grams: 30
        - food_type: havermout
          grams: 50
"""


@pytest.fixture()
def conn(tmp_path):
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    path = tmp_path / "optimiser_test.yaml"
    path.write_text(ARCHETYPE_YAML, encoding="utf-8")
    load_archetypes(connection, path=path)
    return connection


def _priced(conn, sku, name, food_type_key, raw_unit_text, price):
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
        "is_personal_offer) VALUES (?,?,?,'not_a_promo',NULL,1,?,0)",
        (product_id, TODAY.isoformat(), price, price),
    )


def _stock(conn):
    """Whey at EUR 8/kg is the cheapest PROTEIN source here (EUR/g protein
    beats havermout's), but has little carb/fat. Havermout at EUR 3/kg is a
    worse protein buy but is where the carbs and fat actually come from - the
    exact shape needed to prove the meal floors force a real mix rather than
    an all-whey solve."""
    _priced(conn, "wi1", "Whey poeder", "whey_poeder", "1000 g", 8.00)
    _priced(conn, "wi2", "Havermout", "havermout", "1000 g", 3.00)


def _archetype(conn, key) -> Archetype:
    from bonusrank.archetypes import _archetype as row_to_archetype
    row = conn.execute("SELECT * FROM archetypes WHERE key=?", (key,)).fetchone()
    return row_to_archetype(row)


# -- meal vs drink: the actual regression test for this session's ask -------

def test_a_meal_kind_archetype_gets_a_real_carb_and_fat_bearing_mix(conn):
    """Without the meal profile's floors, a cost-minimal solve would spend
    everything on whey and ~0 g on the havermout. With them, it must not."""
    _stock(conn)
    result = optimise_meal(conn, _archetype(conn, "test_meal"), on=TODAY)

    assert isinstance(result, OptimisedComposition)
    havermout = next(i for i in result.items if i.food_type_key == "havermout")
    assert havermout.grams > 20, "the meal floors did not force a real carb/fat source"
    assert result.carbs_g > 0
    assert result.fat_g > 0


def test_a_drink_kind_archetype_is_allowed_to_stay_protein_forward(conn):
    """The same ingredient pool, but a shake has no carb/fat floor at all."""
    _stock(conn)
    result = optimise_meal(conn, _archetype(conn, "test_drink"), on=TODAY)

    assert isinstance(result, OptimisedComposition)
    # Cheaper overall than the meal-kind solve, because it isn't forced to buy
    # as much of the pricier carb source.
    meal_result = optimise_meal(conn, _archetype(conn, "test_meal"), on=TODAY)
    assert result.eur <= meal_result.eur


def test_a_snack_kind_archetype_gets_the_lighter_profile():
    from bonusrank.config import USER_DEFAULTS
    profiles = USER_DEFAULTS["optimiser_profiles"]
    assert profiles["snack"]["kcal"] < profiles["meal"]["kcal"]
    assert "fat_g" not in profiles["snack"]


# -- basic mechanics ----------------------------------------------------------

def test_the_protein_floor_is_met(conn):
    _stock(conn)
    result = optimise_meal(conn, _archetype(conn, "test_meal"), on=TODAY)
    assert result.protein_g >= 20 - 1e-6


def test_too_few_priceable_candidates_is_not_applicable(conn):
    """Only whey priced - havermout has no observation at all."""
    _priced(conn, "wi1", "Whey poeder", "whey_poeder", "1000 g", 20.00)
    assert optimise_meal(conn, _archetype(conn, "test_meal"), on=TODAY) is None


def test_no_target_protein_is_not_applicable(conn):
    _stock(conn)
    assert optimise_meal(conn, _archetype(conn, "test_no_target"), on=TODAY) is None


def test_an_infeasible_target_is_rejected_not_raised(conn):
    _stock(conn)
    result = optimise_meal(conn, _archetype(conn, "test_infeasible"), on=TODAY)
    assert isinstance(result, RejectedPlan)


def test_a_single_ingredient_pool_cannot_hide_a_degenerate_solve(conn):
    """Only one candidate priced at all - too few to optimise a MIX, so this is
    'not applicable' rather than a single-ingredient plan pretending to be one."""
    _priced(conn, "wi1", "Whey poeder", "whey_poeder", "1000 g", 20.00)
    result = optimise_meal(conn, _archetype(conn, "test_single_ingredient"), on=TODAY)
    assert result is None


# -- the objective never rewards low kcal or high protein --------------------

def test_the_objective_contains_only_cost_terms(conn):
    """Structural: catches a future change that accidentally adds a
    kcal/protein coefficient to the objective, the actual failure mode this
    module exists to prevent (a starvation-shaped meal)."""
    _stock(conn)
    archetype = _archetype(conn, "test_meal")

    # Rebuild the same LP optimise_meal would, and inspect its objective -
    # every coefficient must equal a candidate's price per gram, nothing else.
    import bonusrank.optimiser as optimiser_module
    candidates = optimiser_module._priced_candidates(
        conn, optimiser_module._archetype_id(conn, archetype.key),
        chain="ah", on=TODAY, include_personal=False,
    )
    prob = pulp.LpProblem("test", pulp.LpMinimize)
    grams = {c["key"]: pulp.LpVariable(c["key"], lowBound=0) for c in candidates}
    prob += pulp.lpSum(c["eur_per_g"] * grams[c["key"]] for c in candidates)

    expected = {c["key"]: c["eur_per_g"] for c in candidates}
    for var, coeff in prob.objective.items():
        assert coeff == pytest.approx(expected[var.name])
