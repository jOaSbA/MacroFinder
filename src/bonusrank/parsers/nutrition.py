"""Nutrition parser. Testing priority 2.

Two input shapes, both real:

  `parse_nutrition_block` - a Dutch-keyed table of strings with units attached
  and energy as a dual kJ/kcal string ("Eiwitten": "6.4 g"). This is what the
  brief section 1.1 documents, and what Open Food Facts and older snapshots use.

  `parse_gs1_nutrition` - GS1/GDSN structured data with numeric values keyed by
  GS1 nutrient code (PRO-, ENER-, CHOAVL...). This is what AH's FIR endpoint
  actually returns as of 2026-09-16, contrary to the brief.

Three rules are enforced structurally rather than by convention: a missing value
is None and never 0.0 (unknown means unknown, and a real 0.0 stays 0.0); a
"< 0,5 g" ceiling keeps a flag so output can mark it; and kcal derived from kJ is
marked derived, because copy rule 1 forbids showing a derived value unmarked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import normalise, parse_decimal

KJ_PER_KCAL = 4.184

_NUM = r"\d+(?:[.,]\d+)*"
_UPPER_BOUND = re.compile(r"^\s*(?:<|minder dan|kleiner dan)\s*")
_VALUE = re.compile(rf"({_NUM})\s*(mg|g|kcal|kj|mcg|µg)?\b")
_KJ = re.compile(rf"({_NUM})\s*kj\b")
_KCAL = re.compile(rf"({_NUM})\s*kcal\b")


@dataclass(frozen=True)
class Nutrient:
    raw_text: str | None
    value: float | None = None
    unit: str | None = None
    is_upper_bound: bool = False
    needs_review: bool = False

    @property
    def value_g(self) -> float | None:
        """The value expressed in grams, when that conversion is defined."""
        if self.value is None:
            return None
        if self.unit == "g":
            return self.value
        if self.unit == "mg":
            return self.value / 1000.0
        if self.unit in ("mcg", "µg"):
            return self.value / 1_000_000.0
        return None


@dataclass(frozen=True)
class Energy:
    raw_text: str | None
    kj: float | None = None
    kcal: float | None = None
    kcal_is_derived: bool = False
    needs_review: bool = False


@dataclass(frozen=True)
class Macros:
    """Per 100 g (or per 100 ml - the food's name says which, brief section 2)."""

    kcal_per_100g: float | None = None
    kcal_is_derived: bool = False
    protein_per_100g: float | None = None
    carbs_per_100g: float | None = None
    sugars_per_100g: float | None = None
    fat_per_100g: float | None = None
    saturated_per_100g: float | None = None
    fiber_per_100g: float | None = None
    salt_per_100g: float | None = None
    # What the values are per. Usually 100 g, but drinks are often per 100 ml and
    # treating ml as g silently would misprice them by their density (section 2).
    basis_quantity: float | None = None
    basis_unit: str | None = None
    nutrients: dict[str, Nutrient] = field(default_factory=dict)
    unmapped_keys: list[str] = field(default_factory=list)
    needs_review: bool = False


def parse_nutrient(text: str | None) -> Nutrient:
    """Parse one Dutch nutrition value such as '6.4 g' or '< 0,5 g'."""
    norm = normalise(text)
    if not norm:
        return Nutrient(raw_text=text, needs_review=True)

    is_upper_bound = bool(_UPPER_BOUND.search(norm))
    stripped = _UPPER_BOUND.sub("", norm)

    m = _VALUE.search(stripped)
    if not m:
        return Nutrient(raw_text=text, is_upper_bound=is_upper_bound, needs_review=True)

    value = parse_decimal(m.group(1))
    if value is None:
        return Nutrient(raw_text=text, is_upper_bound=is_upper_bound, needs_review=True)

    return Nutrient(raw_text=text, value=value, unit=m.group(2), is_upper_bound=is_upper_bound)


def parse_energy(text: str | None) -> Energy:
    """Parse '2244 kJ (538 kcal)'. Falls back to deriving kcal from kJ, flagged."""
    norm = normalise(text)
    if not norm:
        return Energy(raw_text=text, needs_review=True)

    kj_match, kcal_match = _KJ.search(norm), _KCAL.search(norm)
    kj = parse_decimal(kj_match.group(1)) if kj_match else None
    kcal = parse_decimal(kcal_match.group(1)) if kcal_match else None

    if kcal is None and kj is not None:
        # Arithmetic, not a guess - but it must stay visibly marked (copy rule 1).
        return Energy(raw_text=text, kj=kj, kcal=round(kj / KJ_PER_KCAL, 1), kcal_is_derived=True)

    if kj is None and kcal is None:
        return Energy(raw_text=text, needs_review=True)

    return Energy(raw_text=text, kj=kj, kcal=kcal)


# AH's Dutch nutrition keys, as observed on product/detail/v4/fir.
_KEY_MAP = {
    "energie": "energy",
    "eiwitten": "protein",
    "eiwit": "protein",
    "koolhydraten": "carbs",
    "waarvan suikers": "sugars",
    "vet": "fat",
    "waarvan verzadigd": "saturated",
    "waarvan verzadigde vetzuren": "saturated",
    "voedingsvezel": "fiber",
    "vezels": "fiber",
    "zout": "salt",
}


def parse_nutrition_block(block: dict[str, str]) -> Macros:
    """Parse a whole AH-style Dutch nutrition table into typed macros."""
    values: dict[str, float | None] = {}
    nutrients: dict[str, Nutrient] = {}
    unmapped: list[str] = []
    kcal = None
    kcal_derived = False

    for key, raw in (block or {}).items():
        slug = _KEY_MAP.get(normalise(key))
        if slug is None:
            unmapped.append(key)
            continue
        if slug == "energy":
            energy = parse_energy(raw)
            kcal, kcal_derived = energy.kcal, energy.kcal_is_derived
            continue
        nutrient = parse_nutrient(raw)
        nutrients[slug] = nutrient
        values[slug] = nutrient.value

    return Macros(
        kcal_per_100g=kcal,
        kcal_is_derived=kcal_derived,
        protein_per_100g=values.get("protein"),
        carbs_per_100g=values.get("carbs"),
        sugars_per_100g=values.get("sugars"),
        fat_per_100g=values.get("fat"),
        saturated_per_100g=values.get("saturated"),
        fiber_per_100g=values.get("fiber"),
        salt_per_100g=values.get("salt"),
        nutrients=nutrients,
        unmapped_keys=unmapped,
        # Protein and energy are the two this tool cannot function without.
        needs_review=values.get("protein") is None or kcal is None,
    )


# -- GS1 / GDSN structured nutrition ----------------------------------------
# What AH's product/detail/v4/fir actually returns, verified 2026-09-16. Values
# are numbers, not strings, and nutrients are keyed by GS1 code rather than by
# Dutch label. The brief's section 1.1 describes an older string-keyed shape;
# both are supported because Open Food Facts and other chains still use strings.

_GS1_CODES = {
    "PRO-": "protein",
    "CHOAVL": "carbs",
    "SUGAR-": "sugars",
    "FAT": "fat",
    "FASAT": "saturated",
    "FIBTG": "fiber",
    "SALTEQ": "salt",
}


def parse_gs1_nutrition(nutritional_information: dict | None) -> Macros:
    """Parse `tradeItem.nutritionalInformation` into per-100 macros."""
    headers = (nutritional_information or {}).get("nutrientHeaders") or []
    if not headers:
        return Macros(needs_review=True)

    header = headers[0]
    basis = header.get("nutrientBasisQuantity") or {}
    basis_value = basis.get("value")
    basis_unit = ((basis.get("measurementUnitCode") or {}).get("value") or "").lower() or None
    # Normalise everything to per-100 of whatever the basis unit is.
    scale = 100.0 / basis_value if basis_value else 1.0

    values: dict[str, float] = {}
    nutrients: dict[str, Nutrient] = {}
    unmapped: list[str] = []
    kcal = kj = None

    for detail in header.get("nutrientDetail") or []:
        code = ((detail.get("nutrientTypeCode") or {}).get("value") or "").strip()
        quantities = detail.get("quantityContained") or []
        if not quantities:
            continue

        if code == "ENER-":
            # ENER- appears once per unit; pick by unit, never convert blindly.
            for q in quantities:
                unit = ((q.get("measurementUnitCode") or {}).get("value") or "").lower()
                value = q.get("value")
                if value is None:
                    continue
                if unit == "kcal":
                    kcal = value * scale
                elif unit == "kj":
                    kj = value * scale
            continue

        slug = _GS1_CODES.get(code)
        if slug is None:
            unmapped.append(code)
            continue

        q = quantities[0]
        value = q.get("value")
        if value is None:
            continue
        unit = ((q.get("measurementUnitCode") or {}).get("value") or "").lower()
        grams = value * scale
        if unit == "mg":
            grams /= 1000.0
        elif unit in ("mcg", "µg", "μg"):
            grams /= 1_000_000.0
        values[slug] = grams
        nutrients[slug] = Nutrient(
            raw_text=None, value=grams, unit="g",
            is_upper_bound=(detail.get("measurementPrecisionCode") or {}).get("value") == "LESS_THAN",
        )

    kcal_derived = False
    if kcal is None and kj is not None:
        kcal, kcal_derived = round(kj / KJ_PER_KCAL, 1), True

    return Macros(
        kcal_per_100g=kcal,
        kcal_is_derived=kcal_derived,
        protein_per_100g=values.get("protein"),
        carbs_per_100g=values.get("carbs"),
        sugars_per_100g=values.get("sugars"),
        fat_per_100g=values.get("fat"),
        saturated_per_100g=values.get("saturated"),
        fiber_per_100g=values.get("fiber"),
        salt_per_100g=values.get("salt"),
        basis_quantity=100.0 if basis_value else None,
        basis_unit=basis_unit,
        nutrients=nutrients,
        unmapped_keys=unmapped,
        needs_review=values.get("protein") is None or kcal is None,
    )
