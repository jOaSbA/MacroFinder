"""The per-meal ingredient optimiser. Milestone 9.

The brief's original milestone 9 was a whole-day/week LP: compose several meals to
hit a daily protein target under a kcal floor and a variety cap. The user does not
want that - they plan their own meals and days, and only asked for something much
smaller: given ONE archetype's usual ingredients, let `pulp` pick the gram amounts
that hit the target protein at minimum cost, instead of a seed author guessing them
by hand.

The one hard requirement this module exists to satisfy: **the result must look like
a normal meal, not a protein-maxed one.** A pure cost/protein LP with no floor on
anything else will happily spend every gram on the single cheapest protein source,
because nothing in the model asks for carbs or fat. So every archetype is classified
by `meal_kind` (authored judgement, same status as `taste_delta_note` - never
derived) and the solve is bound by a kcal/carb/fat floor profile that matches what
that kind of thing actually looks like:

  - `meal`  - a plate of food: kcal, carb AND fat floors all apply.
  - `snack` - a lighter version: a lower kcal floor, a small carb floor, no fat floor
              (a piece of fruit is a normal snack with real carbs and ~0 fat).
  - `drink` - a shake is SUPPOSED to be protein-forward. Kcal floor only, and a low
              one (just enough to rule out "100 ml of flavoured water").

Micros (fiber, vitamins, minerals) are explicitly out of scope - not constrained,
not scored. The user was explicit that they aren't needed for this to feel like a
real meal.

Every floor is a lower bound, never an objective term - the objective only ever
contains the cost coefficients. That is what stops the solver drifting toward "as
little of everything except the cheapest protein source as it can get away with";
rewarding low kcal or high protein directly is exactly the failure mode the brief's
original safety rule 1 (day-level starvation diets) warned about, just scoped down
to one meal here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import pulp

from . import config
from .archetypes import Archetype, PricedItem
from .prices import food_type_price

# Falls back for a food type with no `optimise_max_grams` of its own - the
# generic "don't let one ingredient dominate a meal" ceiling.
_DEFAULT_MAX_GRAMS = 400.0

# A solve that puts this much of the mass on one ingredient is not a meal, it's
# a serving of that one ingredient. Checked after every solve, not just relied
# on as an LP bound - the bound stops the LP going further, this check stops
# the *result* shipping if it still lands here.
_SINGLE_INGREDIENT_MASS_FRACTION = 0.95

_CANDIDATE_SQL = """
SELECT DISTINCT f.id, f.key, f.name_nl, f.protein_per_100g, f.kcal_per_100g,
       f.carbs_per_100g, f.fat_per_100g, f.optimise_max_grams
FROM composition_items i
JOIN compositions c ON c.id = i.composition_id
JOIN food_types f ON f.id = i.food_type_id
WHERE c.archetype_id = ?

UNION

SELECT DISTINCT f.id, f.key, f.name_nl, f.protein_per_100g, f.kcal_per_100g,
       f.carbs_per_100g, f.fat_per_100g, f.optimise_max_grams
FROM archetype_optimise_extras e
JOIN food_types f ON f.id = e.food_type_id
WHERE e.archetype_id = ?
"""


@dataclass(frozen=True)
class OptimisedComposition:
    """Same shape as archetypes.PricedComposition's priceable fields, so
    cmd_compare can print it identically."""

    items: tuple[PricedItem, ...]
    eur: float
    protein_g: float
    kcal: float
    carbs_g: float
    fat_g: float

    @property
    def eur_per_g_protein(self) -> float | None:
        if not self.protein_g:
            return None
        return self.eur / self.protein_g


@dataclass(frozen=True)
class RejectedPlan:
    """A terminal, explained 'no' - not a different combination to try.

    There is no second solve to fall back to once the same hand-fixed
    ingredient pool has failed a plausibility rule; the honest answer is the
    same kind of Verdict("unknown", ...) archetypes.py already gives when a
    comparison cannot be made, not a silently reshaped result.
    """

    reason: str


def _archetype_id(conn: sqlite3.Connection, archetype_key: str) -> int:
    row = conn.execute("SELECT id FROM archetypes WHERE key=?", (archetype_key,)).fetchone()
    return row["id"]


def optimise_meal(
    conn: sqlite3.Connection,
    archetype: Archetype,
    *,
    chain: str = "ah",
    on: date | None = None,
    include_personal: bool = False,
    settings: dict | None = None,
) -> OptimisedComposition | RejectedPlan | None:
    """The cheapest normal-shaped mix of this archetype's own ingredients.

    Returns None when there is nothing to optimise (fewer than two priceable
    candidates, or no target_protein_g seeded) - "not applicable", distinct
    from a RejectedPlan, which means a solve was attempted and failed a rule.
    """
    if not archetype.target_protein_g:
        return None

    settings = settings or config.user_settings()
    profile = settings["optimiser_profiles"].get(archetype.meal_kind, {})

    archetype_id = _archetype_id(conn, archetype.key)
    candidates = _priced_candidates(conn, archetype_id, chain=chain, on=on,
                                    include_personal=include_personal)
    if len(candidates) < 2:
        return None

    problem = pulp.LpProblem("meal", pulp.LpMinimize)
    grams = {
        c["key"]: pulp.LpVariable(f"grams_{c['key']}", lowBound=0,
                                  upBound=c["max_grams"])
        for c in candidates
    }

    # Objective: cost only. Never a coefficient on kcal/protein/carbs/fat -
    # that is the entire point of this module, and it is enforced by
    # construction: nothing else is ever added to this sum.
    problem += pulp.lpSum(c["eur_per_g"] * grams[c["key"]] for c in candidates)

    problem += (
        pulp.lpSum(c["protein_per_g"] * grams[c["key"]] for c in candidates)
        >= archetype.target_protein_g
    ), "protein_floor"
    if profile.get("kcal"):
        problem += (
            pulp.lpSum(c["kcal_per_g"] * grams[c["key"]] for c in candidates)
            >= profile["kcal"]
        ), "kcal_floor"
    if profile.get("carbs_g"):
        problem += (
            pulp.lpSum(c["carbs_per_g"] * grams[c["key"]] for c in candidates)
            >= profile["carbs_g"]
        ), "carbs_floor"
    if profile.get("fat_g"):
        problem += (
            pulp.lpSum(c["fat_per_g"] * grams[c["key"]] for c in candidates)
            >= profile["fat_g"]
        ), "fat_floor"

    problem.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[problem.status] != "Optimal":
        return RejectedPlan(
            "no combination of these ingredients reaches "
            f"{archetype.target_protein_g:g} g protein without breaking the "
            f"{archetype.meal_kind} kcal/carb/fat floor"
        )

    solved = {c["key"]: grams[c["key"]].value() or 0.0 for c in candidates}
    return _build_result(candidates, solved, meal_kind=archetype.meal_kind)


def _priced_candidates(conn, archetype_id, *, chain, on, include_personal) -> list[dict]:
    candidates = []
    for row in conn.execute(_CANDIDATE_SQL, (archetype_id, archetype_id)).fetchall():
        price = food_type_price(conn, row["key"], chain=chain, on=on,
                                include_personal=include_personal)
        if price is None:
            continue
        candidates.append({
            "key": row["key"],
            "name_nl": row["name_nl"],
            "eur_per_g": price.eur_per_kg / 1000.0,
            "protein_per_g": (row["protein_per_100g"] or 0.0) / 100.0,
            "kcal_per_g": (row["kcal_per_100g"] or 0.0) / 100.0,
            "carbs_per_g": (row["carbs_per_100g"] or 0.0) / 100.0,
            "fat_per_g": (row["fat_per_100g"] or 0.0) / 100.0,
            "max_grams": row["optimise_max_grams"] or _DEFAULT_MAX_GRAMS,
            "price": price,
        })
    return candidates


def _build_result(candidates, solved: dict[str, float],
                  *, meal_kind: str) -> OptimisedComposition | RejectedPlan:
    total_grams = sum(solved.values())
    if total_grams <= 0:
        return RejectedPlan("the solver found nothing to put in the meal")

    # The variety check is skipped only for `drink`: a shake that is entirely
    # whey (plus water) is completely normal, and that is the one case the
    # `drink` profile's near-absent floors are meant to allow. A `meal` or
    # `snack` degenerating to one ingredient despite having a real recipe
    # behind it (e.g. an LP substituting plain oats for an entire "chocolade
    # proteine pudding" because oats alone happens to be the cheapest way to
    # hit the protein floor) is exactly the failure this check exists to catch.
    dominant = max(solved.values()) / total_grams
    if meal_kind != "drink" and len(candidates) >= 2 and dominant >= _SINGLE_INGREDIENT_MASS_FRACTION:
        return RejectedPlan(
            "the cheapest solve is essentially one ingredient "
            f"({dominant:.0%} of the mass) - not a plausible meal"
        )

    items = []
    total_eur = total_protein = total_kcal = total_carbs = total_fat = 0.0
    for c in candidates:
        g = solved[c["key"]]
        if g <= 0:
            continue
        items.append(PricedItem(
            food_type_key=c["key"],
            name_nl=c["name_nl"],
            grams=g,
            eur=c["eur_per_g"] * g,
            protein_g=c["protein_per_g"] * g,
            kcal=c["kcal_per_g"] * g,
            is_pantry=False,
            price=c["price"],
        ))
        total_eur += c["eur_per_g"] * g
        total_protein += c["protein_per_g"] * g
        total_kcal += c["kcal_per_g"] * g
        total_carbs += c["carbs_per_g"] * g
        total_fat += c["fat_per_g"] * g

    return OptimisedComposition(
        items=tuple(items),
        eur=total_eur,
        protein_g=total_protein,
        kcal=total_kcal,
        carbs_g=total_carbs,
        fat_g=total_fat,
    )
