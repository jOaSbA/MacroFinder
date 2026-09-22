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


# -- alias ownership (docs/AUDIT.md finding 6, and the canned-legume trap) -----

def test_no_alias_is_claimed_by_two_food_types():
    """An alias with two owners is a coin toss the matcher has to make.

    `load_seed` already rejects a duplicate KEY across files, which is what
    stopped anyone noticing this: milestone 12 added `rucola`, `ijsbergsla` and
    `biefstuk` as new food types, and each collided with an alias an existing
    row already claimed - `sla` had both leaves, `runderbiefstuk_mager` had
    three spellings of steak. Whichever the matcher picked, the macros it used
    were a coincidence of iteration order.
    """
    owners: dict[str, list[str]] = {}
    for row in SEED_ROWS:
        for alias in row.get("aliases") or []:
            owners.setdefault(alias.lower(), []).append(row["key"])

    clashes = {alias: keys for alias, keys in owners.items() if len(keys) > 1}
    assert not clashes, f"aliases claimed by more than one food type: {clashes}"


def test_the_loader_rejects_an_alias_two_food_types_claim(tmp_path):
    """Pinned at the loader, not only as a data check, so a future seed file
    cannot reintroduce it by being dropped into the directory."""
    path = tmp_path / "food_types_clash.yaml"
    path.write_text(
        "- key: a_thing\n"
        "  meal_kind: ingredient\n"
        "  name_nl: a thing\n"
        "  aliases: [shared name]\n"
        "- key: another_thing\n"
        "  meal_kind: ingredient\n"
        "  name_nl: another thing\n"
        "  aliases: [shared name]\n",
        encoding="utf-8",
    )
    conn = connect(path=Path(":memory:"))

    with pytest.raises(ValueError, match="shared name"):
        load_seed(conn, path=path)


# -- the canned-legume trap (BRIEF section 3.1) -------------------------------

# A bare legume name, and the form a Dutch supermarket actually sells under it.
# Hak's whole business is tins, so "linzen" on a shelf is a tin of wet lentils
# at ~7 g protein, not a bag of dry ones at 24. Getting this backwards
# overstates protein by 3.4x and, measured on the real catalogue, put a tin of
# lentils FIRST in the whole protein-per-euro ranking.
BARE_LEGUME_NAMES = {
    "linzen": "linzen_blik",
    "bruine bonen": "bruine_bonen_blik",
    "witte bonen": "witte_bonen_blik",
    "kidneybonen": "kidneybonen_blik",
    "kikkererwten": "kikkererwten_blik",
    "doperwten": "doperwten_blik",
}


@pytest.mark.parametrize("alias,expected", sorted(BARE_LEGUME_NAMES.items()))
def test_a_bare_legume_name_belongs_to_the_tin_not_the_dry_form(alias, expected):
    owners = [row["key"] for row in SEED_ROWS
              if alias in {a.lower() for a in row.get("aliases") or []}]

    assert owners == [expected], (
        f"{alias!r} is claimed by {owners}. BRIEF section 3.1 calls this the "
        "biggest trap in the domain model: the dry and tinned forms differ by "
        "roughly 3.4x in protein, and the shelf sells the tin."
    )


def test_the_dry_form_is_still_reachable_by_an_explicit_name():
    """Moving the bare name to the tin must not orphan the dry row - AH and
    Jumbo both sell dried lentils, spelled out."""
    dry = next(row for row in SEED_ROWS if row["key"] == "linzen_droog")
    aliases = {a.lower() for a in dry["aliases"]}

    assert {"gedroogde linzen", "rode linzen", "groene linzen"} <= aliases


# -- re-seeding must remove what the seed no longer says -----------------------

def test_an_alias_removed_from_the_seed_disappears_on_the_next_load(tmp_path):
    """`load_seed` was purely additive, so every alias ever removed stayed live.

    This is what made the canned-legume fix a no-op on an existing database:
    moving the bare word `linzen` from the dry row to the tin edited the YAML
    and changed nothing, because the old alias was still sitting in
    `food_type_aliases` pointing at the dry row. Aliases are derived entirely
    from the seed files and nothing else writes them, so they are rebuilt
    wholesale - the same delete-and-reinsert `load_archetypes` already does for
    compositions and `load_templates` for slots.
    """
    conn = connect(path=Path(":memory:"))
    path = tmp_path / "food_types_x.yaml"

    path.write_text(
        "- key: a_thing\n  meal_kind: ingredient\n  name_nl: a thing\n"
        "  aliases: [old name, kept name]\n", encoding="utf-8")
    load_seed(conn, path=path)
    assert _aliases(conn, "a_thing") == {"a thing", "kept name", "old name"}

    path.write_text(
        "- key: a_thing\n  meal_kind: ingredient\n  name_nl: a thing\n"
        "  aliases: [kept name]\n", encoding="utf-8")
    load_seed(conn, path=path)

    assert _aliases(conn, "a_thing") == {"a thing", "kept name"}


def test_a_food_type_dropped_from_the_seed_becomes_unreachable(tmp_path):
    """Its row cannot be deleted - products and compositions reference it - but
    stripping its aliases makes the matcher unable to reach it, which is the
    part that decides what a product gets costed with."""
    conn = connect(path=Path(":memory:"))
    path = tmp_path / "food_types_x.yaml"

    path.write_text(
        "- key: keeper\n  meal_kind: ingredient\n  name_nl: keeper\n"
        "  aliases: [keep me]\n"
        "- key: doomed\n  meal_kind: ingredient\n  name_nl: doomed\n"
        "  aliases: [drop me]\n", encoding="utf-8")
    load_seed(conn, path=path)
    assert _aliases(conn, "doomed")

    path.write_text(
        "- key: keeper\n  meal_kind: ingredient\n  name_nl: keeper\n"
        "  aliases: [keep me]\n", encoding="utf-8")
    load_seed(conn, path=path)

    assert _aliases(conn, "doomed") == set()
    assert _aliases(conn, "keeper") == {"keeper", "keep me"}


def _aliases(conn, key: str) -> set[str]:
    return {
        row[0] for row in conn.execute(
            "SELECT a.alias FROM food_type_aliases a "
            "JOIN food_types f ON f.id = a.food_type_id WHERE f.key = ?", (key,)
        )
    }
