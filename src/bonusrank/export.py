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
from .ranking import RankedOffer, rank

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
            "offers": [_offer_json(o) for o in rank(conn, chain=chain, on=today) if o.food_type],
        }

    return {
        "generated_at": generated_at,
        "schema_version": 1,
        "chains": chain_payloads,
    }


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
        "meal_slots": list(archetype.meal_slots),
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
