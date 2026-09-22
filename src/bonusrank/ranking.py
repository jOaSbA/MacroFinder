"""Rank current offers by protein-per-euro. Brief milestone 6.

Macro precedence follows section 2: a SKU's own label figures (tier 1) beat the
generic food_type seed. Whichever is used is reported, because copy rule 1 says a
value the user cannot trace must at least be visibly marked.

Unit sizes are re-parsed from `raw_unit_text` at rank time rather than trusted
from the products table. The parsers are pure, so a parser fix improves every
past row without a re-ingest - the same replay property as the raw snapshots.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from . import config
from .parsers import parse_unit_size
from .parsers.units import SizeKind


@dataclass(frozen=True)
class RankedOffer:
    sku: str
    name: str
    brand: str | None
    raw_unit_text: str | None
    food_type: str | None
    # Milestone 11: which app tab this offer belongs in (meal/snack/drink/
    # ingredient), from the matched food type - None when unmatched, same as
    # food_type itself.
    food_meal_kind: str | None

    effective_unit_price: float | None
    shelf_price: float | None
    required_quantity: int
    promo_mechanic: str
    promo_raw_text: str | None
    total_outlay: float | None

    cost_basis_g: float | None
    protein_per_100g: float | None
    kcal_per_100g: float | None
    carbs_per_100g: float | None
    fat_per_100g: float | None
    protein_in_pack_g: float | None

    eur_per_100g_protein: float | None
    eur_per_1000kcal: float | None

    # Waste adjustment (section 3.3): the honest second number.
    waste_adjusted_eur_per_100g_protein: float | None
    realistically_consumable: int | None
    perishable: bool

    macro_source: str
    macro_confidence: str
    kcal_is_derived: bool
    is_personal: bool
    valid_from: str | None
    valid_to: str | None

    # History (section 3.4). None until there is more than one observation.
    cheapest_in_weeks: int | None
    observations: int

    @property
    def needs_macro_marking(self) -> bool:
        """True when output must visibly qualify the macro figures."""
        return self.macro_confidence in ("seed", "low") or self.macro_source == "estimated"


_SQL = """
SELECT p.id AS product_id, p.sku, p.name, p.brand, p.raw_unit_text,
       f.key AS food_type, f.protein_per_100g AS ft_protein, f.kcal_per_100g AS ft_kcal,
       f.carbs_per_100g AS ft_carbs, f.fat_per_100g AS ft_fat, f.meal_kind AS ft_meal_kind,
       f.density_g_per_ml, f.g_per_unit, f.drained_fraction,
       f.shelf_life_days_opened, f.shelf_life_days_unopened, f.freezable,
       f.source AS ft_source, f.confidence AS ft_confidence,
       m.protein_per_100g AS label_protein, m.kcal_per_100g AS label_kcal,
       m.carbs_per_100g AS label_carbs, m.fat_per_100g AS label_fat,
       m.kcal_is_derived, m.source AS label_source, m.confidence AS label_confidence,
       o.shelf_price, o.effective_unit_price, o.required_quantity, o.promo_mechanic,
       o.promo_raw_text, o.is_personal_offer, o.valid_from, o.valid_to, o.observed_at
FROM price_observations o
JOIN products p ON p.id = o.product_id
LEFT JOIN food_types f ON f.id = p.food_type_id
LEFT JOIN product_macros m ON m.product_id = p.id
WHERE p.chain = ?
  AND o.id = (SELECT id FROM price_observations o2
              WHERE o2.product_id = p.id
                AND (o2.promo_mechanic = 'not_a_promo') = (o.promo_mechanic = 'not_a_promo')
              ORDER BY o2.observed_at DESC, o2.id DESC LIMIT 1)
"""
# The latest observation is taken PER LANE - promotion or plain shelf price -
# not simply the latest row. `bonusrank prices` appends shelf prices so that DIY
# compositions can be costed when nothing is on offer, and a shelf price
# recorded today would otherwise supersede this week's still-valid bonus for the
# same SKU and quietly delete it from the ranking. Append-only storage means the
# reader has to disambiguate; nothing may be overwritten to make this simpler.


def rank(
    conn: sqlite3.Connection,
    *,
    chain: str = "ah",
    on: date | None = None,
    include_personal: bool = False,
    settings: dict | None = None,
) -> list[RankedOffer]:
    """Every currently-valid offer for a chain, richest-in-protein-per-euro first.

    Offers with no usable protein figure are returned too, with None metrics, so
    the caller can show them as unrated rather than silently dropping them.
    """
    settings = settings or config.user_settings()
    today = (on or date.today()).isoformat()

    results: list[RankedOffer] = []
    for row in conn.execute(_SQL, (chain,)).fetchall():
        # Bonus weeks do not align; always filter on the window, never a cycle.
        if row["valid_from"] and row["valid_from"] > today:
            continue
        if row["valid_to"] and row["valid_to"] < today:
            continue
        if row["is_personal_offer"] and not include_personal:
            continue
        results.append(_build(conn, row, settings))

    return results


def _build(conn: sqlite3.Connection, row: sqlite3.Row, settings: dict) -> RankedOffer:
    size = parse_unit_size(row["raw_unit_text"])
    mass_g = resolve_mass(size, row)

    protein, kcal, source, confidence = resolve_macros(row)
    carbs, fat = resolve_secondary_macros(row)

    unit_price = row["effective_unit_price"]
    required = row["required_quantity"] or 1
    total_outlay = unit_price * required if unit_price is not None else None

    protein_in_pack = protein * mass_g / 100.0 if (protein and mass_g) else None
    kcal_in_pack = kcal * mass_g / 100.0 if (kcal and mass_g) else None

    eur_per_100g_protein = (
        unit_price / protein_in_pack * 100.0
        if unit_price is not None and protein_in_pack else None
    )
    eur_per_1000kcal = (
        unit_price / kcal_in_pack * 1000.0
        if unit_price is not None and kcal_in_pack else None
    )

    consumable, waste_adjusted, perishable = _waste_adjust(
        row, size, mass_g, unit_price, required, protein, settings
    )

    return RankedOffer(
        sku=row["sku"], name=row["name"], brand=row["brand"],
        raw_unit_text=row["raw_unit_text"], food_type=row["food_type"],
        food_meal_kind=row["ft_meal_kind"],
        effective_unit_price=unit_price, shelf_price=row["shelf_price"],
        required_quantity=required, promo_mechanic=row["promo_mechanic"] or "unknown",
        promo_raw_text=row["promo_raw_text"], total_outlay=total_outlay,
        cost_basis_g=mass_g, protein_per_100g=protein, kcal_per_100g=kcal,
        carbs_per_100g=carbs, fat_per_100g=fat,
        protein_in_pack_g=protein_in_pack,
        eur_per_100g_protein=eur_per_100g_protein, eur_per_1000kcal=eur_per_1000kcal,
        waste_adjusted_eur_per_100g_protein=waste_adjusted,
        realistically_consumable=consumable, perishable=perishable,
        macro_source=source, macro_confidence=confidence,
        kcal_is_derived=bool(row["kcal_is_derived"]),
        is_personal=bool(row["is_personal_offer"]),
        valid_from=row["valid_from"], valid_to=row["valid_to"],
        **_history(conn, row["product_id"], unit_price),
    )


def resolve_macros(row) -> tuple[float | None, float | None, str, str]:
    """Protein and kcal per 100 g, plus where they came from.

    Tier 1 (the SKU's own label) beats the generic seed - brief section 2. The
    provenance travels with the numbers because copy rule 1 forbids showing a
    seed-sourced figure unmarked.
    """
    if row["label_protein"] is not None:
        return (row["label_protein"], row["label_kcal"],
                row["label_source"], row["label_confidence"])
    return (row["ft_protein"], row["ft_kcal"],
            row["ft_source"] or "none", row["ft_confidence"] or "none")


def resolve_secondary_macros(row) -> tuple[float | None, float | None]:
    """Carbs and fat per 100 g, same tier precedence as `resolve_macros`.

    Kept separate rather than folded into `resolve_macros`'s return tuple so
    existing callers of that function are untouched - this is purely additive,
    for the app export (milestone 10) which needs the fuller macro picture.
    """
    if row["label_protein"] is not None:
        return (row["label_carbs"], row["label_fat"])
    return (row["ft_carbs"], row["ft_fat"])


def resolve_mass(size, row) -> float | None:
    """Grams money should be divided by, using the food_type to fill gaps.

    Public because `prices.py` costs a food type per kilo and must divide by the
    same mass the ranking does, or a litre of milk would be priced as 1000 g in
    one place and 1030 g in the other.

    Section 3.1: cost metrics use purchased, edible, drained mass. A litre of
    milk needs the density; 'per stuk' needs g_per_unit; neither is guessable
    from the label alone, which is why food_type carries them.
    """
    if size.cost_basis_g is not None:
        mass = size.cost_basis_g
    elif size.kind is SizeKind.VOLUME and size.total_ml and row["density_g_per_ml"]:
        mass = size.total_ml * row["density_g_per_ml"]
    elif size.kind is SizeKind.COUNT and size.count and row["g_per_unit"]:
        mass = size.count * row["g_per_unit"]
    else:
        return None

    # A tin's drained fraction may come from the food_type when the label is silent
    # - which, measured on real AH data, is essentially always.
    if size.drained_g is None and row["drained_fraction"]:
        mass *= row["drained_fraction"]
    return mass


def _waste_adjust(row, size, mass_g, unit_price, required, protein, settings):
    """Brief section 3.3. A deal you throw away is not a deal."""
    shelf_life = row["shelf_life_days_opened"] or row["shelf_life_days_unopened"]
    if shelf_life is None or mass_g is None or unit_price is None or not protein:
        return None, None, False

    if row["freezable"]:
        shelf_life = max(shelf_life, int(settings["freezer_horizon_days"]))

    perishable = shelf_life <= 14
    daily = float(settings["daily_consumption_g"])
    consumable = max(1, min(required, math.floor(daily * shelf_life / mass_g)))

    # Cost of the whole promo spread only over what actually gets eaten.
    total_cost = unit_price * required
    eaten_protein_g = consumable * mass_g * protein / 100.0
    waste_adjusted = total_cost / eaten_protein_g * 100.0 if eaten_protein_g else None
    return consumable, waste_adjusted, perishable


def _history(conn: sqlite3.Connection, product_id: int, unit_price: float | None) -> dict:
    """'Cheapest in N weeks' - the headline signal the brief prefers over '% off'.

    Returns None below `MIN_HISTORY_WEEKS`. "Cheapest in 0 weeks" is not false,
    but it is not a claim either, and it was being printed beside 246 AH offers
    at once while crowding out the honest alternative this same path already
    has ("no price history yet"). See docs/AUDIT.md finding 3.2.
    """
    rows = conn.execute(
        "SELECT observed_at, effective_unit_price FROM price_observations "
        "WHERE product_id=? AND effective_unit_price IS NOT NULL ORDER BY observed_at DESC",
        (product_id,),
    ).fetchall()
    if unit_price is None or len(rows) < 2:
        return {"cheapest_in_weeks": None, "observations": len(rows)}

    today = datetime.fromisoformat(rows[0]["observed_at"]).date()
    for row in rows[1:]:
        if row["effective_unit_price"] < unit_price:
            # Back to the last time it WAS cheaper: "cheapest in 3 weeks" means
            # it has not been this cheap for three weeks, not that we have been
            # watching it for three weeks.
            since = datetime.fromisoformat(row["observed_at"]).date()
            return _weeks(today - since, len(rows))

    oldest = datetime.fromisoformat(rows[-1]["observed_at"]).date()
    return _weeks(today - oldest, len(rows))


def _weeks(span, observations: int) -> dict:
    weeks = span.days // 7
    return {
        "cheapest_in_weeks": weeks if weeks >= MIN_HISTORY_WEEKS else None,
        "observations": observations,
    }


# The shortest span "cheapest in N weeks" may be claimed over. One whole week,
# because below that the sentence carries no information - and because
# `refresh-data.yml` starts from a fresh checkout with a gitignored database, so
# in production history does not accumulate at all yet and None is the only
# honest answer this can give there (PLAN-V2 M21).
MIN_HISTORY_WEEKS = 1


SORT_KEYS = {
    "protein-per-euro": lambda o: (o.eur_per_100g_protein is None, o.eur_per_100g_protein or 0),
    "kcal-per-euro": lambda o: (o.eur_per_1000kcal is None, o.eur_per_1000kcal or 0),
    "waste-adjusted": lambda o: (
        o.waste_adjusted_eur_per_100g_protein is None,
        o.waste_adjusted_eur_per_100g_protein or 0,
    ),
    "price": lambda o: (o.effective_unit_price is None, o.effective_unit_price or 0),
}


def sort_offers(offers: list[RankedOffer], key: str = "protein-per-euro") -> list[RankedOffer]:
    return sorted(offers, key=SORT_KEYS[key])
