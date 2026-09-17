"""The food_types seed's own data invariants. Milestone 11.

`meal_kind` decides which tab of the app a matched offer shows up in
(meal/snack/drink/ingredient - see CLAUDE.md). It is authored, not derived,
the same convention as archetypes.meal_kind and compositions.taste_delta_note,
so this file pins the same two things those get: every row states one, and
the loader rejects a row that doesn't rather than letting a NULL slip through
to the app as an unclassified offer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bonusrank.db import connect
from bonusrank.seed import _MEAL_KINDS, load_seed, seed_files

SEED_ROWS = [
    row
    for path in seed_files()
    for row in yaml.safe_load(path.read_text(encoding="utf-8")) or []
]


def test_the_seed_is_not_empty():
    assert len(SEED_ROWS) > 100


@pytest.mark.parametrize("row", SEED_ROWS, ids=[r["key"] for r in SEED_ROWS])
def test_every_food_type_has_a_valid_meal_kind(row):
    assert row.get("meal_kind") in _MEAL_KINDS, row["key"]


def test_no_food_type_is_classified_meal():
    """A raw ingredient or single food is never 'a meal' on its own - that
    label is reserved for archetypes.meal_kind, which classifies a composed
    DISH. Giving it to individual food types here would be meaningless (a
    chicken fillet isn't a meal; a chicken-fillet-based dish is)."""
    offenders = [r["key"] for r in SEED_ROWS if r.get("meal_kind") == "meal"]
    assert offenders == []


def test_the_loader_rejects_a_missing_meal_kind(tmp_path):
    path = tmp_path / "food_types_bad.yaml"
    path.write_text(
        "- key: bad_food\n"
        "  name_nl: bad food\n"
        "  protein_per_100g: 1.0\n",
        encoding="utf-8",
    )
    conn = connect(path=Path(":memory:"))
    with pytest.raises(ValueError, match="meal_kind"):
        load_seed(conn, path=path)


def test_the_loader_rejects_an_unrecognised_meal_kind(tmp_path):
    path = tmp_path / "food_types_bad.yaml"
    path.write_text(
        "- key: bad_food\n"
        "  name_nl: bad food\n"
        "  meal_kind: dessert\n",
        encoding="utf-8",
    )
    conn = connect(path=Path(":memory:"))
    with pytest.raises(ValueError, match="meal_kind"):
        load_seed(conn, path=path)
