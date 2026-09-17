"""The shipped archetype seed, checked as data. Brief section 4.3, copy rule 2.

`compositions.taste_delta_note` being NOT NULL stops a composition existing
without a note. It does not stop the note being wrong, and the one way it can be
wrong that matters is claiming parity. So this file tests the seed content, not
the code: a parity claim in a YAML file is a bug, and it should fail here rather
than in front of the user.

The blacklist is crude. That is the right crudeness for a rule that only has to
be broken once to make the whole tool untrustworthy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bonusrank.db import connect
from bonusrank.seed import archetype_files, load_archetypes, load_seed

# Phrasings that assert the DIY version tastes the same. Dutch and English,
# because the seed notes are Dutch and the brief is English.
PARITY_CLAIMS = (
    "tastes the same", "taste the same", "same taste", "indistinguishable",
    "identical", "just like the real", "no difference",
    "smaakt hetzelfde", "hetzelfde als", "identiek", "net zo lekker",
    "niet van echt te onderscheiden", "geen verschil", "precies hetzelfde",
)

SEED_ROWS = [
    row
    for path in archetype_files()
    for row in yaml.safe_load(path.read_text(encoding="utf-8")) or []
]
COMPOSITIONS = [
    (archetype["key"], composition)
    for archetype in SEED_ROWS
    for composition in archetype.get("compositions") or []
]


@pytest.fixture(scope="module")
def seeded():
    conn = connect(path=Path(":memory:"))
    load_seed(conn)
    load_archetypes(conn)
    return conn


def test_the_seed_is_not_empty():
    """Brief section 4.4 names eight archetypes worth shipping."""
    assert len(SEED_ROWS) >= 8
    assert COMPOSITIONS


@pytest.mark.parametrize("key,composition", COMPOSITIONS,
                         ids=[f"{k}:{c['name']}" for k, c in COMPOSITIONS])
def test_every_composition_states_a_taste_delta(key, composition):
    note = composition.get("taste_delta_note")
    assert isinstance(note, str) and note.strip(), f"{key}: taste_delta_note is required"


@pytest.mark.parametrize("key,composition", COMPOSITIONS,
                         ids=[f"{k}:{c['name']}" for k, c in COMPOSITIONS])
def test_no_composition_claims_it_tastes_the_same(key, composition):
    """Copy rule 2. Emit what differs; never claim parity."""
    notes = " ".join(
        str(composition.get(field) or "")
        for field in ("taste_delta_note", "texture_delta_note", "name")
    ).lower()
    offending = [claim for claim in PARITY_CLAIMS if claim in notes]
    assert not offending, f"{key} claims parity: {offending}"


@pytest.mark.parametrize("key,composition", COMPOSITIONS,
                         ids=[f"{k}:{c['name']}" for k, c in COMPOSITIONS])
def test_similarity_confidence_is_one_of_the_three_allowed_values(key, composition):
    assert composition.get("similarity_confidence") in ("high", "medium", "low"), key


@pytest.mark.parametrize("key,composition", COMPOSITIONS,
                         ids=[f"{k}:{c['name']}" for k, c in COMPOSITIONS])
def test_every_composition_has_items_with_positive_grams(key, composition):
    items = composition.get("items") or []
    assert items, f"{key}: a composition with no items cannot be priced"
    for item in items:
        assert item.get("grams", 0) > 0, f"{key}: {item.get('food_type')} has no grams"


def test_every_referenced_food_type_exists_in_the_seed(seeded):
    """A typo in a recipe should fail here, not silently unprice a composition."""
    known = {row["key"] for row in seeded.execute("SELECT key FROM food_types")}
    referenced = {
        item["food_type"]
        for _, composition in COMPOSITIONS
        for item in composition["items"]
    }
    assert referenced <= known, f"unknown food types: {sorted(referenced - known)}"


def test_every_archetype_has_a_valid_meal_kind():
    """Milestone 9: drives which macro-floor profile the optimiser applies."""
    for archetype in SEED_ROWS:
        assert archetype.get("meal_kind") in ("meal", "snack", "drink"), archetype["key"]


def test_optimise_extra_food_types_reference_real_food_types(seeded):
    known = {row["key"] for row in seeded.execute("SELECT key FROM food_types")}
    for archetype in SEED_ROWS:
        for key in archetype.get("optimise_extra_food_types") or []:
            assert key in known, f"{archetype['key']}: optimise_extra_food_types {key!r}"


def test_archetype_keys_are_unique():
    keys = [row["key"] for row in SEED_ROWS]
    assert len(keys) == len(set(keys))


def test_ready_made_rules_reference_real_food_types(seeded):
    known = {row["key"] for row in seeded.execute("SELECT key FROM food_types")}
    for archetype in SEED_ROWS:
        for key in (archetype.get("ready_made") or {}).get("food_types") or []:
            assert key in known, f"{archetype['key']}: ready_made food_type {key!r}"


# -- the loader's own guards -----------------------------------------------

def test_the_loader_rejects_an_empty_taste_delta_note(tmp_path):
    """Enforced at the loader, so the failure names the row rather than the CHECK."""
    path = tmp_path / "archetypes_bad.yaml"
    path.write_text(
        "- key: bad\n"
        "  name: Bad\n"
        "  meal_kind: meal\n"
        "  compositions:\n"
        "    - name: something\n"
        "      taste_delta_note: '   '\n"
        "      items:\n"
        "        - food_type: kwark_mager\n"
        "          grams: 100\n",
        encoding="utf-8",
    )
    conn = connect(path=Path(":memory:"))
    load_seed(conn)
    with pytest.raises(ValueError, match="taste_delta_note"):
        load_archetypes(conn, path=path)


def test_the_loader_rejects_an_unknown_food_type(tmp_path):
    path = tmp_path / "archetypes_unknown.yaml"
    path.write_text(
        "- key: bad\n"
        "  name: Bad\n"
        "  meal_kind: meal\n"
        "  compositions:\n"
        "    - name: something\n"
        "      similarity_confidence: medium\n"
        "      taste_delta_note: minder zoet\n"
        "      items:\n"
        "        - food_type: nonsense_key\n"
        "          grams: 100\n",
        encoding="utf-8",
    )
    conn = connect(path=Path(":memory:"))
    load_seed(conn)
    with pytest.raises(ValueError, match="nonsense_key"):
        load_archetypes(conn, path=path)


def test_the_loader_rejects_a_duplicate_archetype_key(tmp_path):
    path = tmp_path / "archetypes_dupe.yaml"
    row = ("- key: dupe\n"
           "  name: Dupe {n}\n"
           "  meal_kind: meal\n"
           "  compositions:\n"
           "    - name: something {n}\n"
           "      similarity_confidence: medium\n"
           "      taste_delta_note: minder zoet\n"
           "      items:\n"
           "        - food_type: kwark_mager\n"
           "          grams: 100\n")
    path.write_text(row.format(n=1) + row.format(n=2), encoding="utf-8")
    conn = connect(path=Path(":memory:"))
    load_seed(conn)
    with pytest.raises(ValueError, match="dupe"):
        load_archetypes(conn, path=path)


def test_reloading_the_seed_is_idempotent(seeded):
    """`bonusrank seed` is run repeatedly; it must not multiply compositions."""
    before = seeded.execute("SELECT COUNT(*) FROM composition_items").fetchone()[0]
    load_archetypes(seeded)
    after = seeded.execute("SELECT COUNT(*) FROM composition_items").fetchone()[0]
    assert before == after
