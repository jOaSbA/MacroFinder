"""Meal templates: the customiser's shapes, priced against this week's data.

`archetypes.py` answers "is this specific dish cheaper ready-made or homemade?"
Both sides of that question are hand-authored down to the gram. A TEMPLATE asks
something looser and more useful week to week: here is the shape of a pasta -
a pasta, a meat, a sauce, optionally cheese and greens - so which of the things
that can fill each hole is cheapest right now?

Nothing here decides for the user. It ranks the options in each slot and hands
the list over; picking is the user's job, and the compatibility rules only ever
warn, never block. That is the same product decision that made the app a
browsable list rather than an optimiser.

Two rules carried over deliberately from `archetypes.py`, because they are the
ones that keep the output honest:

  * An unpriced candidate stays in its slot with `eur=None`, ranked last. It is
    never dropped - a slot that silently loses options is a slot that lies
    about what you could cook.
  * A missing macro stays None and propagates. Nothing is filled in with a
    zero to make arithmetic easier.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from .prices import FoodTypePrice, food_type_prices

_TEMPLATE_SQL = "SELECT * FROM meal_templates ORDER BY key"

_SLOT_SQL = """
SELECT id, key, name, required, default_grams
FROM template_slots WHERE template_id = ? ORDER BY sort_order
"""

_CANDIDATE_SQL = """
SELECT f.key, f.name_nl, f.protein_per_100g, f.kcal_per_100g,
       f.carbs_per_100g, f.fat_per_100g, f.source, f.confidence,
       c.grams, c.pantry_price_eur_per_kg
FROM template_slot_candidates c
JOIN food_types f ON f.id = c.food_type_id
WHERE c.slot_id = ?
"""

_RULE_SQL = """
SELECT kind, when_predicate, requires, min_satisfied, severity, note
FROM template_rules WHERE template_id = ? OR template_id IS NULL ORDER BY id
"""


@dataclass(frozen=True)
class PricedCandidate:
    """One thing that could fill one slot, costed for one serving."""

    food_type_key: str
    name_nl: str
    grams: float
    # Euro for `grams` of it. None means no current price - the candidate is
    # still shown, because "we don't know" is different from "not an option".
    eur: float | None
    # The per-kilo rate, kept as its own field rather than left to be divided
    # back out of `eur`. The app re-prices locally when the user changes the
    # quantity, and a null rate must stay null through that, never become 0.0.
    eur_per_kg: float | None
    protein_g: float | None
    kcal: float | None
    carbs_g: float | None
    fat_g: float | None
    is_pantry: bool
    # BRIEF section 9 rule 1: a macro figure from the seed may never be shown
    # bare. Every seeded row is source='manual', confidence='seed', so this is
    # true for every candidate today - but it travels with the data rather than
    # being assumed, because the tier-1 label lane exists and will flip some of
    # them. docs/AUDIT.md finding 3.3 is what happens without it: the
    # customiser rendered these totals with no marker at all.
    macros_need_marking: bool
    # The observation behind the price, carrying the promo mechanic, the
    # required quantity and the personal-offer flag. Copy rule 3 applies to a
    # ranked candidate exactly as it does to a ranked offer: a candidate that
    # is cheapest because of a 1+1 means two of them in the fridge.
    price: FoodTypePrice | None

    @property
    def eur_per_g_protein(self) -> float | None:
        if self.eur is None or not self.protein_g:
            return None
        return self.eur / self.protein_g


@dataclass(frozen=True)
class PricedSlot:
    key: str
    name: str
    required: bool
    default_grams: float
    #: Cheapest serving first; candidates with no price last.
    candidates: tuple[PricedCandidate, ...]


@dataclass(frozen=True)
class TemplateRule:
    """An authored judgement about whether a combination is a real dish.

    `when` and each entry of `requires` is a predicate: a mapping that may
    carry `slot` (a slot key) and/or `food_types` (a list of keys). A
    `requirement` holds when at least `min_satisfied` of `requires` are
    present; an `incompatible` fires when `when` and any of `requires` are
    both present.
    """

    kind: str
    when: dict
    requires: tuple[dict, ...]
    min_satisfied: int
    severity: str
    note: str


@dataclass(frozen=True)
class PricedTemplate:
    key: str
    name: str
    meal_kind: str
    base_prep_minutes: int | None
    slots: tuple[PricedSlot, ...]
    rules: tuple[TemplateRule, ...]


def price_templates(
    conn: sqlite3.Connection,
    *,
    chain: str = "ah",
    on: date | None = None,
    include_personal: bool = False,
) -> tuple[PricedTemplate, ...]:
    """Every template, with each slot's candidates priced and ranked."""
    templates = conn.execute(_TEMPLATE_SQL).fetchall()
    if not templates:
        return ()

    # One query for every candidate in every template, rather than one per
    # candidate. `food_type_prices` is the primitive precisely for this.
    keys = [
        row["key"]
        for row in conn.execute(
            "SELECT DISTINCT f.key FROM template_slot_candidates c "
            "JOIN food_types f ON f.id = c.food_type_id"
        )
    ]
    prices = food_type_prices(
        conn, keys, chain=chain, on=on, include_personal=include_personal
    )

    return tuple(_template(conn, row, prices) for row in templates)


def _template(
    conn: sqlite3.Connection, row: sqlite3.Row, prices: dict[str, FoodTypePrice]
) -> PricedTemplate:
    slots = tuple(
        _slot(conn, slot_row, prices)
        for slot_row in conn.execute(_SLOT_SQL, (row["id"],)).fetchall()
    )
    rules = tuple(
        TemplateRule(
            kind=rule["kind"],
            when=json.loads(rule["when_predicate"]),
            requires=tuple(json.loads(rule["requires"]) if rule["requires"] else ()),
            min_satisfied=rule["min_satisfied"],
            severity=rule["severity"],
            note=" ".join(rule["note"].split()),
        )
        for rule in conn.execute(_RULE_SQL, (row["id"],)).fetchall()
    )
    return PricedTemplate(
        key=row["key"],
        name=row["name"],
        meal_kind=row["meal_kind"],
        base_prep_minutes=row["base_prep_minutes"],
        slots=slots,
        rules=rules,
    )


def _slot(
    conn: sqlite3.Connection, row: sqlite3.Row, prices: dict[str, FoodTypePrice]
) -> PricedSlot:
    candidates = [
        _candidate(candidate_row, prices)
        for candidate_row in conn.execute(_CANDIDATE_SQL, (row["id"],)).fetchall()
    ]
    # Cheapest serving first. Serving cost rather than euro-per-kilo, because
    # the grams differ within a slot on purpose - 40 g of pesto against 200 g
    # of chopped tomatoes - and per-kilo would rank the small portion last for
    # a reason that has nothing to do with what the meal costs. Unpriced
    # candidates sort last, the same way unrated offers do in `ranking`.
    candidates.sort(key=lambda c: (c.eur is None, c.eur if c.eur is not None else 0.0))
    return PricedSlot(
        key=row["key"],
        name=row["name"],
        required=bool(row["required"]),
        default_grams=row["default_grams"],
        candidates=tuple(candidates),
    )


def _candidate(row: sqlite3.Row, prices: dict[str, FoodTypePrice]) -> PricedCandidate:
    grams = row["grams"]
    pantry = row["pantry_price_eur_per_kg"]
    price = None if pantry is not None else prices.get(row["key"])

    eur_per_kg = pantry if pantry is not None else (price.eur_per_kg if price else None)
    eur = None if eur_per_kg is None else eur_per_kg * grams / 1000.0

    return PricedCandidate(
        food_type_key=row["key"],
        name_nl=row["name_nl"],
        grams=grams,
        eur=eur,
        eur_per_kg=eur_per_kg,
        protein_g=_per_serving(row["protein_per_100g"], grams),
        kcal=_per_serving(row["kcal_per_100g"], grams),
        carbs_g=_per_serving(row["carbs_per_100g"], grams),
        fat_g=_per_serving(row["fat_per_100g"], grams),
        is_pantry=pantry is not None,
        macros_need_marking=row["confidence"] in ("seed", "low")
        or row["source"] == "estimated",
        price=price,
    )


def _per_serving(per_100g: float | None, grams: float) -> float | None:
    """None in, None out. A missing macro is unknown, never zero."""
    return None if per_100g is None else per_100g * grams / 100.0
