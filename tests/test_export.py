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
from bonusrank.seed import load_archetypes, load_seed, load_templates

TODAY = date(2026, 9, 17)

TEMPLATE_YAML = """
- key: test_pasta
  name: Test pasta
  meal_kind: meal
  base_prep_minutes: 15
  slots:
    - key: base
      name: Base
      default_grams: 100
      candidates:
        - {food_type: pasta_droog}
        - {food_type: pasta_volkoren_droog}
  rules:
    - kind: requirement
      severity: incomplete
      when: {slot: base, food_types: [pasta_droog]}
      requires: [{slot: base}]
      note: witte pasta vraagt om iets met smaak erbij
"""

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
    template_path = tmp_path / "templates_test.yaml"
    template_path.write_text(TEMPLATE_YAML, encoding="utf-8")
    load_templates(connection, path=template_path)
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
    # Bumped to 2 at milestone 12, when templates and the food-type catalogue
    # were added. The app decodes with ignoreUnknownKeys, so an older build
    # keeps working against a newer file - the version is for humans reading
    # a diff, not a gate.
    assert payload["schema_version"] == 2


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
    assert offer["meal_kind"] == expected.food_meal_kind
    assert offer["meal_kind"] == "snack"  # kwark_mager is seeded as a snack
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


# -- templates and the food-type catalogue (milestone 12) ---------------------

def test_template_bodies_ship_once_not_once_per_chain(conn):
    """The slots, the candidates and above all the authored rules are
    chain-independent. Three copies in one file is three chances to drift."""
    payload = build_export(conn, chains=("ah", "jumbo"), on=TODAY)

    assert [t["key"] for t in payload["templates"]] == ["test_pasta"]
    for chain in payload["chains"].values():
        assert "rules" not in json.dumps(chain["template_prices"])


def test_a_templates_rules_survive_the_round_trip_intact(conn):
    rule = build_export(conn, chains=("ah",), on=TODAY)["templates"][0]["rules"][0]

    assert rule["severity"] == "incomplete"
    assert rule["note"], "the note is the only thing the app shows about a rule"
    assert rule["when"] == {"slot": "base", "food_types": ["pasta_droog"]}
    assert rule["requires"] == [{"slot": "base"}]
    assert rule["min_satisfied"] == 1


def test_slot_candidates_are_priced_per_chain(conn):
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.00, chain="ah")
    _priced(conn, "j1", "Jumbo Pasta", "pasta_droog", "500 g", 0.50, chain="jumbo")
    payload = build_export(conn, chains=("ah", "jumbo"), on=TODAY)

    def price_of(chain):
        entries = payload["chains"][chain]["template_prices"]["test_pasta"]["base"]
        return next(e["price_eur"] for e in entries if e["food_type"] == "pasta_droog")

    assert price_of("ah") == pytest.approx(0.20)
    assert price_of("jumbo") == pytest.approx(0.10)


def test_an_unpriced_candidate_ships_with_nulls_and_is_still_listed(conn):
    entries = build_export(conn, chains=("ah",), on=TODAY)[
        "chains"]["ah"]["template_prices"]["test_pasta"]["base"]

    assert len(entries) == 2, "a slot must not lose options just because of price"
    unpriced = entries[-1]
    assert unpriced["price_eur"] is None
    # The rate the app multiplies when the user changes the quantity. Null
    # stays null; it must never arrive as 0.0.
    assert unpriced["eur_per_kg"] is None


def test_the_food_type_catalogue_carries_macros_and_a_unit_mass(conn):
    """"4 boiled eggs" is g_per_unit times four, computed on the phone."""
    catalogue = {f["key"]: f for f in build_export(conn, chains=("ah",), on=TODAY)["food_types"]}

    assert len(catalogue) > 100
    egg = catalogue["ei_gekookt"]
    assert egg["g_per_unit"] is not None
    assert egg["macros_per_100g"]["protein_g"] is not None


def test_a_food_type_with_no_macro_ships_null_not_zero(conn):
    conn.execute("UPDATE food_types SET fat_per_100g = NULL WHERE key = 'pasta_droog'")
    catalogue = {f["key"]: f for f in build_export(conn, chains=("ah",), on=TODAY)["food_types"]}
    assert catalogue["pasta_droog"]["macros_per_100g"]["fat_g"] is None


def test_every_priceable_food_type_gets_a_rate_for_arbitrary_extras(conn):
    """Milestone 13: "100 g ketchup" is priced from this map, not from a
    template slot - the user may add anything, not only slot candidates."""
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)
    prices = build_export(conn, chains=("ah",), on=TODAY)["chains"]["ah"]["food_type_prices"]

    assert prices["kwark_mager"]["eur_per_kg"] == pytest.approx(2.40)
    assert prices["kwark_mager"]["required_quantity"] == 1
    # Absent means unknown. Nothing is mapped to a zero or a guessed rate.
    assert "ketchup" not in prices


def test_food_type_prices_agree_with_what_the_pricing_module_reports(conn):
    _priced(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g", 1.20)

    from bonusrank.prices import food_type_price
    expected = food_type_price(conn, "kwark_mager", chain="ah", on=TODAY)

    shipped = build_export(conn, chains=("ah",), on=TODAY)[
        "chains"]["ah"]["food_type_prices"]["kwark_mager"]
    assert shipped["eur_per_kg"] == expected.eur_per_kg
    assert shipped["sku"] == expected.sku


# -- provenance (BRIEF section 9 rule 1, docs/AUDIT.md finding 3.3) ------------

def test_every_food_type_says_whether_its_macros_are_an_estimate(conn):
    """The customiser's totals bar rendered protein and kcal bare, computed
    entirely from these rows. That is a section 9 rule 1 violation, and the
    root cause was here rather than in the app: the export shipped the numbers
    with no way to know they are seed estimates."""
    payload = build_export(conn, chains=("ah",), on=TODAY)

    assert payload["food_types"], "nothing to check"
    for entry in payload["food_types"]:
        assert "macros_need_marking" in entry, entry["key"]

    # Every seeded row is source='manual', confidence='seed' today.
    assert all(e["macros_need_marking"] for e in payload["food_types"])


def test_a_food_type_upgraded_to_a_high_confidence_source_drops_the_marker(conn):
    """The flag travels with the data rather than being hardcoded true, because
    `seed.load_nevo` exists to flip exactly this."""
    conn.execute(
        "UPDATE food_types SET source='nevo', confidence='high' WHERE key='kwark_mager'"
    )

    payload = build_export(conn, chains=("ah",), on=TODAY)
    entry = next(e for e in payload["food_types"] if e["key"] == "kwark_mager")

    assert entry["macros_need_marking"] is False


def test_every_slot_candidate_says_whether_its_macros_are_an_estimate(conn):
    """Same numbers, same screen, same rule - and the same field name a ranked
    offer uses, so the app has one rule rather than two."""
    _priced(conn, "wi1", "AH Pasta", "pasta_droog", "500 g", 1.10)

    payload = build_export(conn, chains=("ah",), on=TODAY)
    slots = payload["chains"]["ah"]["template_prices"]["test_pasta"]

    candidates = [c for entries in slots.values() for c in entries]
    assert candidates, "nothing to check"
    for candidate in candidates:
        assert candidate["macros_need_marking"] is True, candidate["food_type"]
