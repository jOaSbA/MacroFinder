"""Export a snapshot of ranked offers and archetypes for the Android app.

The app is a browsable, filterable list, not an optimiser (the user rejected the
per-meal LP UI, milestone 9, for this purpose): tabs of meals/snacks/drinks/other
foods, each showing price, which promo applies and why it's cheaper, and macros.
It has no scraping code of its own and no backend server - a scheduled GitHub
Actions job runs this export and commits the JSON, and the app fetches that file
straight off GitHub (`raw.githubusercontent.com`), so there is nothing to host.

Two views are combined into one file:

  archetypes  the 8 curated archetypes (already meal_kind-tagged meal/snack/drink),
              ready-made vs DIY vs optimised - reuses `archetypes.compare()` as-is.
  offers      every currently-valid ranked offer for a chain (`ranking.rank()`),
              for an "everything else" tab the curated archetypes don't cover.

Nothing here computes a new number. This module only serializes what `compare()`
and `rank()` already produce - the same "why is this cheap" data the CLI prints,
shaped for a phone screen instead of a terminal.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .archetypes import Comparison, PricedComposition, PricedReadyMade, compare
from .optimiser import OptimisedComposition, RejectedPlan
from .prices import FoodTypePrice, food_type_prices
from .ranking import RankedOffer, rank
from .templates import PricedCandidate, PricedTemplate, price_templates

DEFAULT_CHAINS = ("ah", "jumbo", "aldi")


def build_export(
    conn: sqlite3.Connection,
    *,
    chains: tuple[str, ...] = DEFAULT_CHAINS,
    on: date | None = None,
) -> dict[str, Any]:
    """Everything the app needs for one refresh, across every chain.

    A chain with nothing ingested yet (e.g. Jumbo/Aldi before their first
    `bonusrank ingest`) contributes an empty list rather than failing the whole
    export - one stale or unstarted chain must not block the other two.
    """
    today = on or date.today()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    chain_payloads = {}
    for chain in chains:
        chain_payloads[chain] = {
            "archetypes": [_comparison_json(c) for c in compare(conn, chain=chain, on=today)],
            # Only offers matched to a food type: the app ranks and shows
            # macros, so an unmatched SKU (usually non-food or a matcher
            # review case, CLAUDE.md section 6) is noise here, not data. This
            # also keeps the committed JSON from ballooning with rows the app
            # would never display anyway - most of a chain's weekly offers
            # never match a food type at all.
            #
            # And only offers: plain shelf prices stay out. The carried
            # database holds the whole crawled catalogue, and exporting every
            # shelf price made this file 7.7 MB on a fetch-on-launch path.
            "offers": [_offer_json(o) for o in rank(conn, chain=chain, on=today)
                       if o.food_type and o.promo_mechanic != "not_a_promo"],
            # Milestone 12: what each template's slot candidates cost at THIS
            # chain. The template bodies themselves ship once, below.
            "template_prices": {
                t.key: _template_prices_json(t)
                for t in price_templates(conn, chain=chain, on=today)
            },
            # Milestone 13: a per-kilo rate for EVERY food type this chain can
            # price, not just the ones some template slot offers. This is what
            # lets the app cost an arbitrary extra the user types in ("100 g
            # ketchup") without waiting for the next refresh. A food type with
            # no current price simply has no key here - absent means unknown,
            # exactly as `food_type_prices` returning no entry does.
            "food_type_prices": {
                key: _food_type_price_json(price)
                for key, price in food_type_prices(conn, chain=chain, on=today).items()
            },
        }

    return {
        "generated_at": generated_at,
        "schema_version": 2,
        "chains": chain_payloads,
        # Chain-independent, so shipped once. Putting the slots, the candidate
        # lists and above all the authored rules under each of three chains
        # would mean three copies of the same judgement in one file, and three
        # chances for them to drift apart.
        "templates": [_template_json(t) for t in price_templates(conn, on=today)],
        # The food-type catalogue. The app needs macros and a per-kilo rate to
        # re-price locally when the user changes a quantity or adds an extra
        # ("100 g ketchup", "4 boiled eggs" - which is what g_per_unit is for).
        "food_types": _food_types_json(conn),
    }


def _template_json(template: PricedTemplate) -> dict[str, Any]:
    """The authored body of a template: shape and rules, no prices."""
    return {
        "key": template.key,
        "name": template.name,
        "meal_kind": template.meal_kind,
        "base_prep_minutes": template.base_prep_minutes,
        "slots": [
            {
                "key": slot.key,
                "name": slot.name,
                "required": slot.required,
                "default_grams": slot.default_grams,
                "candidates": [c.food_type_key for c in slot.candidates],
            }
            for slot in template.slots
        ],
        "rules": [
            {
                "kind": rule.kind,
                "when": rule.when,
                "requires": list(rule.requires),
                "min_satisfied": rule.min_satisfied,
                "severity": rule.severity,
                "note": rule.note,
            }
            for rule in template.rules
        ],
    }


def _template_prices_json(template: PricedTemplate) -> dict[str, Any]:
    """Per-chain: each slot's candidates, ranked, with what they cost here."""
    return {
        slot.key: [_candidate_json(c) for c in slot.candidates]
        for slot in template.slots
    }


def _candidate_json(candidate: PricedCandidate) -> dict[str, Any]:
    price = candidate.price
    return {
        "food_type": candidate.food_type_key,
        "name": candidate.name_nl,
        "grams": candidate.grams,
        "price_eur": candidate.eur,
        # The primitive the app multiplies when the user changes the quantity.
        # Null stays null through that arithmetic; it never becomes 0.0.
        "eur_per_kg": candidate.eur_per_kg,
        "protein_g": candidate.protein_g,
        "kcal": candidate.kcal,
        "carbs_g": candidate.carbs_g,
        "fat_g": candidate.fat_g,
        "eur_per_g_protein": candidate.eur_per_g_protein,
        "is_pantry": candidate.is_pantry,
        # See `_food_types_json`: a slot candidate's macros come from the same
        # seeded rows and need the same marker.
        "macros_need_marking": candidate.macros_need_marking,
        # Copy rule 3 and the PERSONAL corollary apply to a ranked candidate
        # exactly as they do to a ranked offer.
        "promo_text": price.promo_raw_text if price else None,
        "required_quantity": price.required_quantity if price else None,
        "is_personal_offer": price.is_personal if price else False,
        "sku": price.sku if price else None,
    }


def _food_type_price_json(price: FoodTypePrice) -> dict[str, Any]:
    """One food type's cheapest current rate at one chain.

    `eur_per_kg` is the primitive the app multiplies by whatever quantity the
    user types. Everything else is context the user is owed before acting on
    it - copy rule 3's required quantity, and the PERSONAL corollary.
    """
    return {
        "eur_per_kg": price.eur_per_kg,
        "sku": price.sku,
        "product_name": price.product_name,
        "promo_text": price.promo_raw_text,
        "required_quantity": price.required_quantity,
        "is_personal_offer": price.is_personal,
    }


def _food_types_json(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every seeded food type, so the app can price an arbitrary extra.

    No prices here - those are per chain and live in `template_prices`, and a
    food type with no current price simply has no entry there. Absent means
    unknown, exactly as `food_type_prices` returning no key does.
    """
    rows = conn.execute(
        "SELECT key, name_nl, meal_kind, g_per_unit, protein_per_100g, "
        "kcal_per_100g, carbs_per_100g, fat_per_100g, source, confidence "
        "FROM food_types ORDER BY key"
    ).fetchall()
    return [
        {
            "key": row["key"],
            "name": row["name_nl"],
            "meal_kind": row["meal_kind"],
            # "4 boiled eggs" is this field times four. Null where a food has
            # no sensible unit (you do not buy rice by the unit).
            "g_per_unit": row["g_per_unit"],
            "macros_per_100g": {
                "protein_g": row["protein_per_100g"],
                "kcal": row["kcal_per_100g"],
                "carbs_g": row["carbs_per_100g"],
                "fat_g": row["fat_per_100g"],
            },
            # BRIEF section 9 rule 1, and docs/AUDIT.md finding 3.3. The
            # customiser's totals bar rendered these figures bare because the
            # export never said what they were: every seeded row is
            # source='manual', confidence='seed', so the answer is always yes
            # today and the app had no way to know. Same field name as a ranked
            # offer's, so the app has one rule and not two.
            "macros_need_marking": _needs_marking(row["source"], row["confidence"]),
        }
        for row in rows
    ]


def _needs_marking(source: str | None, confidence: str | None) -> bool:
    """One definition of "this figure is an estimate", shared with ranking.

    `RankedOffer.needs_macro_marking` asks the same question of a resolved
    offer. Two spellings of it would drift, and the one that drifts is the one
    that forgets a confidence level and renders a guess as a fact.
    """
    return confidence in ("seed", "low") or source == "estimated"


def write_export(conn: sqlite3.Connection, out: Path, **kwargs) -> dict[str, Any]:
    """Build the export and write it as pretty, diffable JSON.

    Sorted keys and a trailing newline: this file is committed to git by the
    refresh workflow, and a stable diff is the only way anyone will ever notice
    the export silently stopped changing.
    """
    payload = build_export(conn, **kwargs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


# -- offers (the "everything else" tab) --------------------------------------

def _offer_json(offer: RankedOffer) -> dict[str, Any]:
    return {
        "sku": offer.sku,
        "name": offer.name,
        "brand": offer.brand,
        "food_type": offer.food_type,
        # Milestone 11: which app tab this belongs in - meal/snack/drink/
        # ingredient, from the matched food type. None only when unmatched
        # (food_type is also None then; build_export already filters those
        # out, so in practice this is always set here).
        "meal_kind": offer.food_meal_kind,
        "price": {
            "unit_price_eur": offer.effective_unit_price,
            "shelf_price_eur": offer.shelf_price,
            "required_quantity": offer.required_quantity,
            "total_outlay_eur": offer.total_outlay,
            "promo_mechanic": offer.promo_mechanic,
            # The human-readable "why it's cheaper" - the store's own promo text.
            "promo_text": offer.promo_raw_text,
            "is_promo": offer.promo_mechanic not in ("not_a_promo", "unknown"),
            "cheapest_in_weeks": offer.cheapest_in_weeks,
        },
        "macros_per_100g": {
            "protein_g": offer.protein_per_100g,
            "carbs_g": offer.carbs_per_100g,
            "fat_g": offer.fat_per_100g,
            "kcal": offer.kcal_per_100g,
        },
        # Copy rule 1 (CLAUDE.md section 2): a macro figure the user cannot
        # trace to a label must be visibly marked. The app owes the same honesty
        # the CLI's `*` does - this is that marker, machine-readable.
        "macros_need_marking": offer.needs_macro_marking,
        "kcal_is_derived": offer.kcal_is_derived,
        "eur_per_100g_protein": offer.eur_per_100g_protein,
        "waste_adjusted_eur_per_100g_protein": offer.waste_adjusted_eur_per_100g_protein,
        "perishable": offer.perishable,
        "realistically_consumable_packs": offer.realistically_consumable,
        "is_personal_offer": offer.is_personal,
        "valid_from": offer.valid_from,
        "valid_to": offer.valid_to,
    }


# -- archetypes (the meal / snack / drink tabs) -------------------------------

def _comparison_json(comparison: Comparison) -> dict[str, Any]:
    archetype = comparison.archetype
    return {
        "key": archetype.key,
        "name": archetype.name,
        "meal_kind": archetype.meal_kind,
        "day_parts": list(archetype.day_parts),
        "serving_g": archetype.serving_g,
        "target_protein_g": archetype.target_protein_g,
        "ready_made": _ready_made_json(comparison.ready_made),
        "compositions": [_composition_json(c) for c in comparison.compositions],
        "optimised": _optimised_json(comparison.optimised),
        "verdict": {
            "winner": comparison.verdict.winner,
            "cheaper_pct": comparison.verdict.cheaper_pct,
            "protein_delta_g": comparison.verdict.protein_delta_g,
            "text": comparison.verdict.text,
        },
    }


def _ready_made_json(ready: PricedReadyMade | None) -> dict[str, Any] | None:
    if ready is None:
        return None
    offer = ready.offer
    return {
        "sku": offer.sku,
        "name": offer.name,
        "price_eur": ready.eur,
        "protein_g": ready.protein_g,
        "kcal": ready.kcal,
        "eur_per_g_protein": ready.eur_per_g_protein,
        "matched_by": ready.matched_by,
        "promo_text": offer.promo_raw_text,
        "required_quantity": offer.required_quantity,
        "is_personal_offer": offer.is_personal,
    }


def _composition_json(composition: PricedComposition) -> dict[str, Any]:
    return {
        "name": composition.name,
        "effort_minutes": composition.effort_minutes,
        "equipment": composition.equipment,
        "similarity_confidence": composition.similarity_confidence,
        "taste_delta_note": composition.taste_delta_note,
        "texture_delta_note": composition.texture_delta_note,
        "price_eur": composition.eur,
        "protein_g": composition.protein_g,
        "kcal": composition.kcal,
        "eur_per_g_protein": composition.eur_per_g_protein,
        "unpriced_food_types": list(composition.unpriced),
        "items": [_item_json(item) for item in composition.items],
    }


def _optimised_json(optimised: OptimisedComposition | RejectedPlan | None) -> dict[str, Any] | None:
    if optimised is None:
        return None
    if isinstance(optimised, RejectedPlan):
        return {"rejected": True, "reason": optimised.reason}
    return {
        "rejected": False,
        "price_eur": optimised.eur,
        "protein_g": optimised.protein_g,
        "carbs_g": optimised.carbs_g,
        "fat_g": optimised.fat_g,
        "kcal": optimised.kcal,
        "items": [_item_json(item) for item in optimised.items],
    }


def _item_json(item) -> dict[str, Any]:
    return {
        "food_type": item.food_type_key,
        "name": item.name_nl,
        "grams": item.grams,
        "price_eur": item.eur,
        "protein_g": item.protein_g,
        "kcal": item.kcal,
        "is_pantry": item.is_pantry,
    }
