"""The substitution engine. Brief section 4, milestone 8.

The user's actual ask: "kwark plus this milk plus some fruit tastes the same, has
more protein, and is cheaper - tell me that." This module answers the priceable
half of it and refuses to answer the other half, because section 4.3 is
explicit: similarity between a DIY composition and a store product cannot be
derived from macros. It is authored metadata, and the engine's job is to carry it
through to the output unchanged, never to compute it.

An archetype has two fulfilment routes. A **ready-made** SKU is bound by seed
rules (a food type, or a name substring) resolved against this week's offers, so
the binding survives AH rotating its webshopIds. A **composition** is a recipe of
food-type grams, priced through `prices.food_type_price` so it works in weeks
when none of its ingredients is on offer.

Three rules this module exists to keep:

  1. An item that cannot be priced makes the whole composition's cost `None`.
     The item is still listed. Summing what is left would understate DIY, which
     is the one direction this tool must not flatter.
  2. Ready-made is allowed to win, and the verdict says "just buy it" when it
     does (section 4.5). Eggs at a deep promo beat any composition.
  3. Nothing here adjusts, softens or interprets `taste_delta_note`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from . import config
from .prices import FoodTypePrice, food_type_price
from .ranking import RankedOffer, rank

if TYPE_CHECKING:
    from .optimiser import OptimisedComposition, RejectedPlan


@dataclass(frozen=True)
class Archetype:
    key: str
    name: str
    serving_g: float | None
    target_protein_g: float | None
    texture: str | None
    temperature: str | None
    meal_slots: tuple[str, ...]
    max_prep_minutes: int | None
    meal_kind: str


@dataclass(frozen=True)
class PricedItem:
    """One line of a recipe, costed."""

    food_type_key: str
    name_nl: str
    grams: float
    eur: float | None
    protein_g: float | None
    kcal: float | None
    is_pantry: bool
    # The observation that priced it. None for a pantry item, whose price is
    # seeded rather than observed - output must mark that difference.
    price: FoodTypePrice | None


@dataclass(frozen=True)
class PricedComposition:
    name: str
    effort_minutes: int | None
    equipment: str | None
    similarity_confidence: str | None
    taste_delta_note: str
    texture_delta_note: str | None
    items: tuple[PricedItem, ...]
    eur: float | None
    protein_g: float | None
    kcal: float | None
    # Food types with no current price. Non-empty means `eur` is None.
    unpriced: tuple[str, ...]

    @property
    def eur_per_g_protein(self) -> float | None:
        if self.eur is None or not self.protein_g:
            return None
        return self.eur / self.protein_g


@dataclass(frozen=True)
class PricedReadyMade:
    """A store SKU scaled down to one serving of the archetype."""

    offer: RankedOffer
    eur: float | None
    protein_g: float | None
    kcal: float | None
    matched_by: str

    @property
    def eur_per_g_protein(self) -> float | None:
        if self.eur is None or not self.protein_g:
            return None
        return self.eur / self.protein_g


@dataclass(frozen=True)
class Verdict:
    winner: str  # "diy" | "ready_made" | "unknown"
    cheaper_pct: float | None
    protein_delta_g: float | None
    extra_minutes: int | None
    text: str


@dataclass(frozen=True)
class Comparison:
    archetype: Archetype
    ready_made: PricedReadyMade | None
    compositions: tuple[PricedComposition, ...]
    verdict: Verdict
    # Milestone 9: the cheapest solver-picked mix of the archetype's own
    # ingredients. None means "not applicable" (too few priceable candidates,
    # or no target_protein_g); a RejectedPlan means a solve was attempted and
    # failed a plausibility rule - see optimiser.py.
    optimised: "OptimisedComposition | RejectedPlan | None" = None


def compare(
    conn: sqlite3.Connection,
    *,
    archetype_key: str | None = None,
    chain: str = "ah",
    on: date | None = None,
    include_personal: bool = False,
    max_prep_minutes: int | None = None,
    settings: dict | None = None,
) -> list[Comparison]:
    """Price both routes to every archetype and say which wins."""
    from .optimiser import optimise_meal  # local: optimiser imports archetypes

    settings = settings or config.user_settings()
    today = on or date.today()
    offers = rank(conn, chain=chain, on=today, include_personal=include_personal,
                  settings=settings)

    sql = "SELECT * FROM archetypes"
    params: tuple = ()
    if archetype_key:
        sql += " WHERE key = ?"
        params = (archetype_key,)
    sql += " ORDER BY key"

    results: list[Comparison] = []
    for row in conn.execute(sql, params).fetchall():
        archetype = _archetype(row)
        ready_made = _best_ready_made(conn, row["id"], archetype, offers, chain)
        compositions = tuple(
            composition
            for composition in _compositions(conn, row["id"], archetype, today,
                                             chain, include_personal)
            if max_prep_minutes is None
            or (composition.effort_minutes or 0) <= max_prep_minutes
        )
        optimised = optimise_meal(conn, archetype, chain=chain, on=today,
                                  include_personal=include_personal, settings=settings)
        results.append(Comparison(
            archetype=archetype,
            ready_made=ready_made,
            compositions=compositions,
            verdict=_verdict(ready_made, _best(compositions)),
            optimised=optimised,
        ))
    return results


def best_composition(comparison: Comparison) -> PricedComposition | None:
    """Cheapest per gram of protein among the compositions that priced."""
    return _best(comparison.compositions)


# -- the ready-made side ---------------------------------------------------

def _best_ready_made(conn, archetype_id, archetype, offers, chain) -> PricedReadyMade | None:
    """Resolve the seed rules against current offers, cheapest per g protein first.

    The binding is also written to `sku_archetype_map` so it can be audited the
    way `bonusrank matches` audits food-type matches - a rule that quietly binds
    the wrong SKU is exactly the failure mode worth being able to look up.
    """
    rules = conn.execute(
        "SELECT kind, value FROM archetype_ready_made_rules WHERE archetype_id=?",
        (archetype_id,),
    ).fetchall()
    if not rules:
        return None

    food_types = {r["value"] for r in rules if r["kind"] == "food_type"}
    substrings = [r["value"] for r in rules if r["kind"] == "contains"]

    candidates: list[PricedReadyMade] = []
    for offer in offers:
        matched_by = None
        if offer.food_type and offer.food_type.lower() in food_types:
            matched_by = f"food_type {offer.food_type}"
        else:
            name = (offer.name or "").lower()
            hit = next((s for s in substrings if s in name), None)
            if hit:
                matched_by = f"name contains {hit!r}"
        if matched_by is None:
            continue

        priced = _scale_offer(offer, archetype.serving_g, matched_by)
        if priced is not None:
            candidates.append(priced)

    if not candidates:
        return None

    # Cheapest per gram of protein; an offer with no protein figure sorts last
    # rather than being dropped, so the user still sees something is there.
    candidates.sort(key=lambda c: (
        c.eur_per_g_protein is None,
        c.eur_per_g_protein if c.eur_per_g_protein is not None else (c.eur or 0.0),
    ))
    best = candidates[0]

    product_id = conn.execute(
        "SELECT id FROM products WHERE chain=? AND sku=?",
        (chain, best.offer.sku),
    ).fetchone()
    if product_id:
        conn.execute(
            "INSERT INTO sku_archetype_map (product_id, archetype_id) VALUES (?,?) "
            "ON CONFLICT DO NOTHING",
            (product_id[0], archetype_id),
        )
        conn.commit()
    return best


def _scale_offer(offer: RankedOffer, serving_g, matched_by) -> PricedReadyMade | None:
    """One serving's worth of a pack. A 400 g pot for a 200 g serving is half of it."""
    if offer.effective_unit_price is None:
        return None
    if not serving_g or not offer.cost_basis_g:
        # No serving size or no usable mass: price the pack as-is rather than
        # inventing a scale factor, and say so by leaving protein unknown.
        return PricedReadyMade(offer, offer.effective_unit_price, None, None, matched_by)

    fraction = serving_g / offer.cost_basis_g
    return PricedReadyMade(
        offer=offer,
        eur=offer.effective_unit_price * fraction,
        protein_g=(offer.protein_per_100g * serving_g / 100.0
                   if offer.protein_per_100g is not None else None),
        kcal=(offer.kcal_per_100g * serving_g / 100.0
              if offer.kcal_per_100g is not None else None),
        matched_by=matched_by,
    )


# -- the DIY side ----------------------------------------------------------

_ITEM_SQL = """
SELECT f.key, f.name_nl, f.protein_per_100g, f.kcal_per_100g,
       i.grams, i.pantry_price_eur_per_kg
FROM composition_items i
JOIN food_types f ON f.id = i.food_type_id
WHERE i.composition_id = ?
ORDER BY i.rowid
"""


def _compositions(conn, archetype_id, archetype, today, chain, include_personal):
    rows = conn.execute(
        "SELECT * FROM compositions WHERE archetype_id=? ORDER BY id", (archetype_id,)
    ).fetchall()
    return [
        _price_composition(conn, row, today, chain, include_personal) for row in rows
    ]


def _price_composition(conn, row, today, chain, include_personal) -> PricedComposition:
    items: list[PricedItem] = []
    unpriced: list[str] = []

    for item in conn.execute(_ITEM_SQL, (row["id"],)).fetchall():
        grams = item["grams"]
        pantry = item["pantry_price_eur_per_kg"]
        if pantry is not None:
            eur, price = pantry * grams / 1000.0, None
        else:
            price = food_type_price(conn, item["key"], chain=chain, on=today,
                                    include_personal=include_personal)
            eur = price.eur_per_kg * grams / 1000.0 if price else None
            if price is None:
                unpriced.append(item["key"])

        items.append(PricedItem(
            food_type_key=item["key"],
            name_nl=item["name_nl"],
            grams=grams,
            eur=eur,
            protein_g=(item["protein_per_100g"] * grams / 100.0
                       if item["protein_per_100g"] is not None else None),
            kcal=(item["kcal_per_100g"] * grams / 100.0
                  if item["kcal_per_100g"] is not None else None),
            is_pantry=pantry is not None,
            price=price,
        ))

    # One unpriced item makes the total unknown. Summing the rest would claim a
    # recipe is cheaper than anyone can actually buy it for.
    total_eur = None if unpriced else sum(i.eur or 0.0 for i in items)

    return PricedComposition(
        name=row["name"],
        effort_minutes=row["effort_minutes"],
        equipment=row["equipment"],
        similarity_confidence=row["similarity_confidence"],
        taste_delta_note=row["taste_delta_note"],
        texture_delta_note=row["texture_delta_note"],
        items=tuple(items),
        eur=total_eur,
        protein_g=_sum_or_none(i.protein_g for i in items),
        kcal=_sum_or_none(i.kcal for i in items),
        unpriced=tuple(unpriced),
    )


def _sum_or_none(values):
    """A missing macro poisons the sum. Never fabricate one (CLAUDE.md section 1)."""
    collected = list(values)
    if any(v is None for v in collected):
        return None
    return sum(collected)


# -- the verdict (section 4.5) ---------------------------------------------

def _best(compositions) -> PricedComposition | None:
    priced = [c for c in compositions if c.eur_per_g_protein is not None]
    if priced:
        return min(priced, key=lambda c: c.eur_per_g_protein)
    return compositions[0] if compositions else None


def _verdict(ready_made: PricedReadyMade | None,
             composition: PricedComposition | None) -> Verdict:
    """Compare per-gram-of-protein cost, or say the comparison cannot be made.

    One priced side and one unknown side is not a comparison, and claiming a
    winner there would be the engine's most damaging possible lie: it would
    always favour whichever side happened to have data.
    """
    diy = composition.eur_per_g_protein if composition else None
    ready = ready_made.eur_per_g_protein if ready_made else None

    if diy is None or ready is None:
        missing = "DIY" if diy is None else "ready-made"
        return Verdict("unknown", None, None, None,
                       f"No verdict: the {missing} side could not be priced.")

    protein_delta = (composition.protein_g or 0) - (ready_made.protein_g or 0)
    minutes = composition.effort_minutes or 0

    if diy < ready:
        return Verdict(
            winner="diy",
            cheaper_pct=(ready - diy) / ready * 100.0,
            protein_delta_g=protein_delta,
            extra_minutes=minutes,
            text=(f"DIY is {(ready - diy) / ready * 100:.0f}% cheaper per gram of "
                  f"protein and {protein_delta:+.0f} g protein, costs {minutes} min."),
        )

    return Verdict(
        winner="ready_made",
        cheaper_pct=(diy - ready) / diy * 100.0,
        protein_delta_g=protein_delta,
        extra_minutes=minutes,
        text=(f"Just buy it: ready-made is {(diy - ready) / diy * 100:.0f}% cheaper "
              f"per gram of protein and saves {minutes} min."),
    )


def _archetype(row: sqlite3.Row) -> Archetype:
    return Archetype(
        key=row["key"],
        name=row["name"],
        serving_g=row["serving_g"],
        target_protein_g=row["target_protein_g"],
        texture=row["texture"],
        temperature=row["temperature"],
        meal_slots=tuple(json.loads(row["meal_slots"])) if row["meal_slots"] else (),
        max_prep_minutes=row["max_prep_minutes"],
        meal_kind=row["meal_kind"],
    )
