"""The meal-template seed and its loader. Milestone 12.

Two jobs. First, the shipped templates in data/seed/templates.yaml must be
internally consistent - a rule naming a slot that does not exist, or a food type
no slot offers, is a rule that can never fire, and nothing at runtime would ever
tell you. Second, every rejection the loader promises must actually happen, with
the offending row named: `_validate_template` exists so a bad seed fails with a
sentence you can act on rather than a bare CHECK violation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from bonusrank.db import connect
from bonusrank.seed import load_seed, load_templates, template_files

SEEDED = [
    row
    for path in template_files()
    for row in yaml.safe_load(path.read_text(encoding="utf-8")) or []
]


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


def _load(conn, tmp_path, yaml_text, name="templates_test.yaml"):
    path = tmp_path / name
    path.write_text(yaml_text, encoding="utf-8")
    return load_templates(conn, path=path)


VALID = """
- key: t
  name: T
  meal_kind: meal
  slots:
    - key: base
      name: Base
      default_grams: 100
      candidates:
        - {food_type: pasta_droog}
    - key: sauce
      name: Saus
      required: false
      default_grams: 50
      candidates:
        - {food_type: olijfolie}
  rules:
    - kind: requirement
      severity: incomplete
      when: {slot: sauce, food_types: [olijfolie]}
      requires: [{slot: base}]
      note: olie alleen is geen maaltijd
"""


# -- the shipped seed ------------------------------------------------------

def test_templates_are_actually_seeded():
    assert SEEDED, "data/seed/templates.yaml is the whole point of milestone 12"


@pytest.mark.parametrize("row", SEEDED, ids=[r["key"] for r in SEEDED])
def test_every_rule_names_a_slot_the_template_has(row):
    slot_keys = {slot["key"] for slot in row["slots"]}
    for rule in row.get("rules") or []:
        for predicate in [rule["when"], *(rule.get("requires") or [])]:
            slot = predicate.get("slot")
            assert slot is None or slot in slot_keys, (
                f"{row['key']}: rule names slot {slot!r}, slots are {sorted(slot_keys)}"
            )


@pytest.mark.parametrize("row", SEEDED, ids=[r["key"] for r in SEEDED])
def test_every_rule_only_names_food_types_some_slot_offers(row):
    """A rule about a food type nothing offers can never fire, and nothing at
    runtime would say so."""
    offered = {
        candidate["food_type"]
        for slot in row["slots"]
        for candidate in slot["candidates"]
    }
    for rule in row.get("rules") or []:
        for predicate in [rule["when"], *(rule.get("requires") or [])]:
            for food_type in predicate.get("food_types") or []:
                assert food_type in offered, f"{row['key']}: {food_type} is in no slot"


@pytest.mark.parametrize("row", SEEDED, ids=[r["key"] for r in SEEDED])
def test_every_rule_has_a_real_note(row):
    """The note is the ONLY thing the app shows about a rule."""
    for rule in row.get("rules") or []:
        assert rule.get("note", "").strip(), f"{row['key']}: a rule with no note"


@pytest.mark.parametrize("row", SEEDED, ids=[r["key"] for r in SEEDED])
def test_every_slot_states_a_serving_size(row):
    for slot in row["slots"]:
        assert slot.get("default_grams", 0) > 0, f"{row['key']}/{slot['key']}"


def test_the_shipped_seed_loads_against_the_real_food_types(conn):
    counts = load_templates(conn)
    assert counts["templates"] == len(SEEDED)
    assert counts["candidates"] > counts["slots"], "a slot with one option is not a choice"


# -- what the loader writes ------------------------------------------------

def test_a_candidate_without_grams_inherits_the_slots_default(conn, tmp_path):
    _load(conn, tmp_path, VALID)
    grams = conn.execute(
        "SELECT c.grams FROM template_slot_candidates c "
        "JOIN template_slots s ON s.id = c.slot_id WHERE s.key = 'base'"
    ).fetchone()[0]
    assert grams == 100


def test_predicates_round_trip_as_json(conn, tmp_path):
    _load(conn, tmp_path, VALID)
    row = conn.execute("SELECT when_predicate, requires FROM template_rules").fetchone()
    assert json.loads(row["when_predicate"]) == {
        "slot": "sauce", "food_types": ["olijfolie"],
    }
    assert json.loads(row["requires"]) == [{"slot": "base"}]


def test_reloading_replaces_slots_rather_than_accumulating(conn, tmp_path):
    """An edited template drops candidates; an upsert would keep the removed
    ones, which is why load_archetypes deletes wholesale too."""
    _load(conn, tmp_path, VALID)
    trimmed = VALID.replace("        - {food_type: olijfolie}\n", "        - {food_type: pasta_volkoren_droog}\n")
    _load(conn, tmp_path, trimmed.replace("food_types: [olijfolie]", "food_types: [pasta_volkoren_droog]"))

    keys = {
        r[0] for r in conn.execute(
            "SELECT f.key FROM template_slot_candidates c "
            "JOIN food_types f ON f.id = c.food_type_id"
        )
    }
    assert "olijfolie" not in keys
    assert conn.execute("SELECT COUNT(*) FROM template_rules").fetchone()[0] == 1


# -- what the loader refuses ----------------------------------------------

@pytest.mark.parametrize(
    "old, new, needle",
    [
        ("meal_kind: meal", "meal_kind: soep", "meal_kind"),
        ("severity: incomplete", "severity: bad", "severity"),
        ("note: olie alleen is geen maaltijd", "note: '   '", "note"),
        ("when: {slot: sauce, food_types: [olijfolie]}", "when: {slot: nosuch}", "nosuch"),
        ("requires: [{slot: base}]",
         "requires: [{slot: base}]\n      min_satisfied: 4", "min_satisfied"),
        ("- {food_type: pasta_droog}", "- {food_type: nosuchfood}", "nosuchfood"),
        ("default_grams: 100", "default_grams: 0", "default_grams"),
    ],
    ids=["bad meal_kind", "bad severity", "empty note", "unknown slot in rule",
         "unreachable min_satisfied", "unknown food_type", "zero default_grams"],
)
def test_the_loader_names_what_to_fix(conn, tmp_path, old, new, needle):
    mutated = VALID.replace(old, new)
    assert mutated != VALID, "the mutation did not apply - fix the test, not the loader"
    with pytest.raises(ValueError) as caught:
        _load(conn, tmp_path, mutated)
    assert needle in str(caught.value), str(caught.value)


def test_a_template_with_no_slots_is_rejected(conn, tmp_path):
    with pytest.raises(ValueError, match="slots"):
        _load(conn, tmp_path, "- {key: t, name: T, meal_kind: meal}\n")


def test_a_slot_with_no_candidates_is_rejected(conn, tmp_path):
    with pytest.raises(ValueError, match="candidates"):
        _load(conn, tmp_path, """
- key: t
  name: T
  meal_kind: meal
  slots:
    - {key: base, name: Base, default_grams: 100, candidates: []}
""")


def test_the_same_food_type_twice_in_one_slot_is_rejected(conn, tmp_path):
    with pytest.raises(ValueError, match="twice"):
        _load(conn, tmp_path, """
- key: t
  name: T
  meal_kind: meal
  slots:
    - key: base
      name: Base
      default_grams: 100
      candidates:
        - {food_type: pasta_droog}
        - {food_type: pasta_droog, grams: 50}
""")


def test_the_same_food_type_in_two_slots_is_allowed(conn, tmp_path):
    """Deliberately not composition_items' constraint: a food type may play two
    roles in one template."""
    counts = _load(conn, tmp_path, """
- key: t
  name: T
  meal_kind: meal
  slots:
    - key: base
      name: Base
      default_grams: 100
      candidates: [{food_type: pasta_droog}]
    - key: extra
      name: Extra
      default_grams: 30
      candidates: [{food_type: pasta_droog}]
""")
    assert counts["candidates"] == 2


def test_a_rule_naming_a_food_type_no_slot_offers_is_rejected(conn, tmp_path):
    with pytest.raises(ValueError, match="could never fire"):
        _load(conn, tmp_path, VALID.replace(
            "food_types: [olijfolie]", "food_types: [kwark_mager]"
        ))


def test_a_duplicate_template_key_is_rejected(conn, tmp_path):
    """Matching load_seed and load_archetypes: a second definition of the same
    key must fail loudly rather than silently overwrite the first."""
    with pytest.raises(ValueError, match="duplicate template key"):
        _load(conn, tmp_path, VALID + VALID)


def test_template_files_globs_so_you_can_drop_your_own_file_in(tmp_path):
    (tmp_path / "templates.yaml").write_text("[]", encoding="utf-8")
    (tmp_path / "templates_mine.yaml").write_text("[]", encoding="utf-8")
    (tmp_path / "archetypes.yaml").write_text("[]", encoding="utf-8")
    assert [p.name for p in template_files(tmp_path)] == [
        "templates.yaml", "templates_mine.yaml",
    ]
