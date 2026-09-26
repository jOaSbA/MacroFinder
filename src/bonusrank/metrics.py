"""The four sort metrics and the macro buckets. Milestone 20.

PLAN-V2 section 4. Pure functions: numbers in, number or None out. Any
unknown input gives None, never zero, because a zero sorts first on every
"cheapest protein" list and would put the least-known product on top.
"""

from __future__ import annotations

import statistics
from functools import lru_cache
from pathlib import Path

import yaml

from . import config

BUCKETS_PATH = config.PROJECT_ROOT / "data" / "seed" / "macro_buckets.yaml"
DIET_PATH = config.PROJECT_ROOT / "data" / "seed" / "diet.yaml"

EIWITBOM_MIN_PROTEIN = 20.0          # g per 100 g
CUT_MIN_PROTEIN_PER_100KCAL = 10.0
SNEL_MIN_PROTEIN_PER_SERVING = 15.0
ONTBIJT_MIN_PROTEIN_PER_SERVING = 20.0
MEAL_PREP_MIN_PROTEIN = 15.0         # g per 100 g

# PLAN-V2 says "per serving" and the catalogue has no serving sizes. A pack
# up to this size counts as one serving; a bigger pack counts as this much.
# So a 60 g bar is a 60 g serving and a 500 g pot of skyr is a 250 g bowl.
SERVING_CAP_G = 250.0


def protein_density(protein_per_100g: float | None) -> float | None:
    return protein_per_100g


def protein_ratio(protein_per_100g: float | None, kcal_per_100g: float | None) -> float | None:
    """Grams of protein per 100 kcal. The cut metric."""
    if protein_per_100g is None or not kcal_per_100g:
        return None
    return protein_per_100g / kcal_per_100g * 100.0


def eur_per_100g_protein(price: float | None, mass_g: float | None,
                         protein_per_100g: float | None) -> float | None:
    if price is None or not mass_g or not protein_per_100g:
        return None
    return price / (protein_per_100g * mass_g / 100.0) * 100.0


def eur_per_1000kcal(price: float | None, mass_g: float | None,
                     kcal_per_100g: float | None) -> float | None:
    if price is None or not mass_g or not kcal_per_100g:
        return None
    return price / (kcal_per_100g * mass_g / 100.0) * 1000.0


def bulk_cutoff(values) -> float | None:
    """The €/1000 kcal below which a product is in the cheapest quarter."""
    known = sorted(v for v in values if v is not None)
    if len(known) < 2:
        return known[0] if known else None
    return statistics.quantiles(known, n=4, method="inclusive")[0]


@lru_cache(maxsize=1)
def _authored() -> dict:
    return yaml.safe_load(Path(BUCKETS_PATH).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def diets() -> dict[str, str]:
    """food type key -> vegan / vegetarisch / niet_vegetarisch (milestone 32)."""
    authored = yaml.safe_load(Path(DIET_PATH).read_text(encoding="utf-8"))
    return {key: diet for diet, keys in authored.items() for key in keys}


def buckets(*, protein: float | None, kcal: float | None, mass_g: float | None,
            meal_kind: str | None, food_type: str | None, freezable: bool,
            name: str, eur_per_1000kcal: float | None,
            bulk_cutoff: float | None) -> list[str]:
    """Which macro buckets a product falls in, in a fixed order.

    `supplement`, `vegetarisch` and `vegan` don't need macros: they are about
    what a product is, not what's in it.
    """
    authored = _authored()
    out: list[str] = []
    serving = min(mass_g, SERVING_CAP_G) if mass_g else None
    per_serving = protein * serving / 100.0 if (protein is not None and serving) else None

    if protein is not None and protein >= EIWITBOM_MIN_PROTEIN:
        out.append("eiwitbom")
    ratio = protein_ratio(protein, kcal)
    if ratio is not None and ratio >= CUT_MIN_PROTEIN_PER_100KCAL:
        out.append("cut")
    if (eur_per_1000kcal is not None and bulk_cutoff is not None
            and eur_per_1000kcal <= bulk_cutoff):
        out.append("bulk")
    if (meal_kind in ("snack", "drink") and per_serving is not None
            and per_serving >= SNEL_MIN_PROTEIN_PER_SERVING):
        out.append("snel_eiwit")
    if (food_type in authored["ontbijt"]["food_types"] and per_serving is not None
            and per_serving >= ONTBIJT_MIN_PROTEIN_PER_SERVING):
        out.append("ontbijt")
    if (freezable and meal_kind == "ingredient" and protein is not None
            and protein >= MEAL_PREP_MIN_PROTEIN):
        out.append("meal_prep")
    supplement = authored["supplement"]
    lowered = (name or "").lower()
    if (food_type in supplement["food_types"]
            or any(word in lowered for word in supplement["name_contains"])):
        out.append("supplement")
    # Diet rides along as two more tags, so the app filters on it without a
    # schema change. Vegan is also vegetarian. No food type, no diet.
    diet = diets().get(food_type) if food_type else None
    if diet in ("vegan", "vegetarisch"):
        out.append("vegetarisch")
    if diet == "vegan":
        out.append("vegan")
    return out
