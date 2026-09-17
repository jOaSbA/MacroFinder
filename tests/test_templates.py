"""Meal templates: slot pricing and candidate ranking. Milestone 12.

The tests that matter here are the ones that stop a slot from lying about what
you could cook:

  * an unpriced candidate stays in its slot, ranked last, with eur None. A slot
    that quietly drops options presents a shorter menu than the seed says it
    has, and nothing in the output would reveal it.
  * candidates rank by SERVING cost, not by euro-per-kilo. The grams differ
    within a slot on purpose, so per-kilo would rank 40 g of pesto behind 200 g
    of chopped tomatoes for a reason that has nothing to do with the meal.
  * a missing macro stays None rather than becoming zero.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.seed import load_seed, load_templates
from bonusrank.templates import price_templates

TODAY = date(2026, 9, 17)

TEMPLATE_YAML = """
- key: test_pasta
  name: Test pasta
  meal_kind: meal
  base_prep_minutes: 15
  slots:
    - key: pasta
      name: Soort pasta
      required: true
      default_grams: 100
      candidates:
        - {food_type: pasta_droog}
        - {food_type: pasta_volkoren_droog}
    - key: sauce
      name: Saus
      required: false
      default_grams: 150
      candidates:
        - {food_type: tomatenblokjes_blik, grams: 200}
        - {food_type: olijfolie, grams: 10}
  rules:
    - kind: requirement
      severity: incomplete
      when: {slot: sauce, food_types: [olijfolie]}
      requires:
        - {slot: pasta}
      min_satisfied: 1
      note: olie alleen is geen saus
"""


@pytest.fixture()
def conn(tmp_path):
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    path = tmp_path / "templates_test.yaml"
    path.write_text(TEMPLATE_YAML, encoding="utf-8")
    load_templates(connection, path=path)
    return connection


def _priced(conn, sku, name, food_type_key, raw_unit_text, price, valid_to=None):
    row = conn.execute("SELECT id FROM food_types WHERE key=?", (food_type_key,)).fetchone()
    conn.execute(
        "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
        "match_method, match_score, first_seen) VALUES ('ah',?,?,?,?,'alias_exact',1.0,?)",
        (sku, name, raw_unit_text, row[0], TODAY.isoformat()),
    )
    product_id = conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()[0]
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, required_quantity, effective_unit_price, is_personal_offer, "
        "valid_to) VALUES (?,?,?,'not_a_promo',1,?,0,?)",
        (product_id, TODAY.isoformat(), price, price, valid_to),
    )
    return product_id


def _only(conn):
    templates = price_templates(conn, on=TODAY)
    assert len(templates) == 1
    return templates[0]


def _slot(template, key):
    return next(s for s in template.slots if s.key == key)


# -- pricing ---------------------------------------------------------------

def test_a_candidate_costs_its_own_grams_at_the_cheapest_current_rate(conn):
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00)
    candidate = _slot(_only(conn), "pasta").candidates[0]

    # 500 g for EUR 1.00 is 2.00/kg; the slot's default serving is 100 g.
    assert candidate.eur_per_kg == pytest.approx(2.00)
    assert candidate.eur == pytest.approx(0.20)


def test_the_per_kilo_rate_ships_alongside_the_serving_price(conn):
    """The app re-prices locally when the user changes grams, and dividing the
    rate back out of a None serving price is not possible."""
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00)
    template = _only(conn)
    priced = _slot(template, "pasta").candidates[0]
    unpriced = _slot(template, "pasta").candidates[-1]

    assert priced.eur_per_kg is not None
    assert unpriced.eur is None and unpriced.eur_per_kg is None


def test_a_cheaper_observation_of_the_same_food_type_wins(conn):
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00)
    _priced(conn, "wi2", "Brand Pasta", "pasta_droog", "500 g", 0.60)
    assert _slot(_only(conn), "pasta").candidates[0].eur == pytest.approx(0.12)


# -- ranking ---------------------------------------------------------------

def test_candidates_rank_by_serving_cost_not_by_euro_per_kilo(conn):
    """Olive oil is far dearer per kilo than tinned tomatoes, but the slot uses
    10 g of it against 200 g of them - so it is the cheaper way to fill the
    slot, and must rank first."""
    _priced(conn, "wi1", "AH Tomatenblokjes", "tomatenblokjes_blik", "400 g", 1.00)
    _priced(conn, "wi2", "AH Olijfolie", "olijfolie", "500 ml", 5.00)
    sauce = _slot(_only(conn), "sauce")

    # tomatoes: 2.50/kg x 200 g = 0.50. oil: 10.00/kg x 10 g = 0.10.
    assert [c.food_type_key for c in sauce.candidates] == [
        "olijfolie", "tomatenblokjes_blik",
    ]


def test_an_unpriced_candidate_is_kept_and_ranked_last(conn):
    _priced(conn, "wi1", "AH Volkoren pasta", "pasta_volkoren_droog", "500 g", 2.00)
    candidates = _slot(_only(conn), "pasta").candidates

    assert [c.food_type_key for c in candidates] == [
        "pasta_volkoren_droog", "pasta_droog",
    ]
    assert candidates[-1].eur is None, "an unpriced candidate must not be dropped"


def test_a_slot_with_no_prices_at_all_still_lists_every_candidate(conn):
    candidates = _slot(_only(conn), "pasta").candidates
    assert len(candidates) == 2
    assert all(c.eur is None for c in candidates)


# -- macros ----------------------------------------------------------------

def test_macros_are_scaled_to_the_serving(conn):
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00)
    candidate = _slot(_only(conn), "pasta").candidates[0]
    # The seed carries 12 g protein per 100 g; the serving is 100 g.
    assert candidate.protein_g == pytest.approx(12.0)
    assert candidate.grams == 100


def test_a_missing_macro_stays_none_and_never_becomes_zero(conn):
    conn.execute("UPDATE food_types SET fat_per_100g = NULL WHERE key = 'pasta_droog'")
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00)
    candidate = _slot(_only(conn), "pasta").candidates[0]

    assert candidate.fat_g is None
    assert candidate.protein_g is not None


def test_eur_per_g_protein_is_none_when_either_side_is_unknown(conn):
    candidate = _slot(_only(conn), "pasta").candidates[0]
    assert candidate.eur_per_g_protein is None


# -- shape -----------------------------------------------------------------

def test_slot_order_and_optionality_come_from_the_seed(conn):
    template = _only(conn)
    assert [s.key for s in template.slots] == ["pasta", "sauce"]
    assert _slot(template, "pasta").required is True
    assert _slot(template, "sauce").required is False


def test_a_candidate_may_override_the_slots_default_grams(conn):
    sauce = _slot(_only(conn), "sauce")
    grams = {c.food_type_key: c.grams for c in sauce.candidates}
    assert sauce.default_grams == 150
    assert grams == {"tomatenblokjes_blik": 200, "olijfolie": 10}


def test_rules_come_through_with_their_note_and_severity(conn):
    rule = _only(conn).rules[0]
    assert rule.kind == "requirement"
    assert rule.severity == "incomplete"
    assert rule.note == "olie alleen is geen saus"
    assert rule.when == {"slot": "sauce", "food_types": ["olijfolie"]}
    assert rule.requires == ({"slot": "pasta"},)
    assert rule.min_satisfied == 1


def test_no_templates_seeded_is_an_empty_tuple_not_an_error(tmp_path):
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    assert price_templates(connection, on=TODAY) == ()


# -- promo context ---------------------------------------------------------

def test_the_observation_behind_the_price_is_carried_on_the_candidate(conn):
    """Copy rule 3: a candidate that is cheapest because of a multi-buy means
    several of them in the fridge, so the observation must reach the caller."""
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00)
    candidate = _slot(_only(conn), "pasta").candidates[0]

    assert candidate.price is not None
    assert candidate.price.sku == "wi1"
    assert candidate.price.required_quantity == 1


def test_an_expired_offer_does_not_price_a_candidate(conn):
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00,
            valid_to=(TODAY - timedelta(days=1)).isoformat())
    assert all(c.eur is None for c in _slot(_only(conn), "pasta").candidates)
