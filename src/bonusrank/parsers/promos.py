"""Promo-mechanic parser. Testing priority 3.

Brief section 3.2 requires two numbers that are different and both matter: the
**effective multiplier** and the **required quantity**. A 1+1 gratis is a great
unit price and two kilos of kwark.

The hard rule: any unparsed mechanic goes to the review queue. Never silently
default to "no discount" or "assume 25%". So `UNKNOWN` carries a None multiplier
and refuses to price itself - it cannot be mistaken for `NOT_A_PROMO`, which is a
positive finding that the price is simply the shelf price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .common import normalise, parse_decimal


class PromoKind(str, Enum):
    PERCENT_OFF = "percent_off"
    SECOND_HALF_PRICE = "second_half_price"
    SECOND_PERCENT_OFF = "second_percent_off"
    X_PLUS_Y_FREE = "x_plus_y_free"
    X_FOR_Y = "x_for_y"
    FIXED_PRICE = "fixed_price"
    BULK_TIER = "bulk_tier"
    AMOUNT_OFF = "amount_off"
    PRICE_PER_WEIGHT = "price_per_weight"
    PERSONAL = "personal"
    NOT_A_PROMO = "not_a_promo"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Promo:
    raw_text: str | None
    kind: PromoKind = PromoKind.UNKNOWN
    required_quantity: int = 1
    effective_multiplier: float | None = None
    total_promo_price: float | None = None
    percent_off: float | None = None
    amount_off: float | None = None
    price_per_100g: float | None = None
    is_personal: bool = False
    needs_review: bool = False
    source: str = "text"

    def effective_unit_price(
        self, shelf_price: float | None = None, unit_size_g: float | None = None
    ) -> float | None:
        """Price per single unit under the promo, or None if it cannot be known.

        Returning None is a feature. An unknown mechanic must not be priced, and a
        per-weight promo cannot be priced without the pack mass.
        """
        if self.kind is PromoKind.UNKNOWN:
            return None

        if self.kind is PromoKind.PRICE_PER_WEIGHT:
            if self.price_per_100g is None or unit_size_g is None:
                return None
            return self.price_per_100g * unit_size_g / 100.0

        if self.kind is PromoKind.X_FOR_Y and self.total_promo_price is not None:
            return self.total_promo_price / self.required_quantity

        if self.kind is PromoKind.FIXED_PRICE and self.total_promo_price is not None:
            return self.total_promo_price

        if self.kind is PromoKind.AMOUNT_OFF:
            if shelf_price is None or self.amount_off is None:
                return None
            return max(shelf_price - self.amount_off, 0.0)

        if self.effective_multiplier is not None and shelf_price is not None:
            return shelf_price * self.effective_multiplier

        return None

    def total_outlay(
        self, shelf_price: float | None = None, unit_size_g: float | None = None
    ) -> float | None:
        """What actually leaves the wallet: unit price x required quantity.

        Copy rule 3 exists because this number, not the unit price, is what has to
        fit in a student budget and a fridge.
        """
        unit = self.effective_unit_price(shelf_price=shelf_price, unit_size_g=unit_size_g)
        return None if unit is None else unit * self.required_quantity


_NUM = r"\d+(?:[.,]\d+)?"

# Order is significant. The bulk and "op de 2e" forms also contain "N% korting",
# so the plain percentage rule has to come last among the percentage forms.
_X_PLUS_Y = re.compile(rf"(\d+)\s*\+\s*(\d+)\s*gratis")
_NTH_HALF = re.compile(r"(\d+)e\s*halve\s*prijs")
_NTH_PERCENT = re.compile(rf"({_NUM})\s*%\s*korting\s*op\s*de\s*(\d+)e")
_BULK_VANAF = re.compile(rf"vanaf\s*(\d+)\s*stuks?\s*({_NUM})\s*%\s*korting")
_BULK_PER = re.compile(rf"({_NUM})\s*%\s*korting\s*per\s*(\d+)\s*stuks?")
_X_FOR_Y = re.compile(rf"(\d+)\s*voor\s*€?\s*({_NUM})")
_PERCENT = re.compile(rf"({_NUM})\s*%\s*korting")
_AMOUNT_OFF = re.compile(rf"€?\s*({_NUM})\s*euro\s*korting")
_PER_WEIGHT = re.compile(rf"per\s*({_NUM})\s*gram\s*voor\s*€?\s*({_NUM})")
_FIXED = re.compile(rf"(?:nu|voor)\s*€?\s*({_NUM})")

_NOT_A_PROMO = ("prijsfavoriet", "elke dag lage prijs", "altijd lage prijs")
_PERSONAL_MARKERS = ("bonusbox", "extra's voor jou", "persoonlijke bonus")


def parse_promo_text(text: str | None, *, source: str = "text") -> Promo:
    """Parse a Dutch promo string into a typed mechanic. Never raises."""
    norm = normalise(text)
    if not norm:
        return Promo(raw_text=text, kind=PromoKind.UNKNOWN, needs_review=True, source=source)

    is_personal = any(marker in norm for marker in _PERSONAL_MARKERS)

    if any(marker in norm for marker in _NOT_A_PROMO):
        return Promo(
            raw_text=text, kind=PromoKind.NOT_A_PROMO, required_quantity=1,
            effective_multiplier=1.0, source=source,
        )

    if m := _X_PLUS_Y.search(norm):
        paid, free = int(m.group(1)), int(m.group(2))
        total = paid + free
        return Promo(
            raw_text=text, kind=PromoKind.X_PLUS_Y_FREE, required_quantity=total,
            effective_multiplier=paid / total, is_personal=is_personal, source=source,
        )

    if m := _NTH_HALF.search(norm):
        n = int(m.group(1))
        return Promo(
            raw_text=text, kind=PromoKind.SECOND_HALF_PRICE, required_quantity=n,
            effective_multiplier=(n - 0.5) / n, is_personal=is_personal, source=source,
        )

    if m := _NTH_PERCENT.search(norm):
        pct, n = parse_decimal(m.group(1)) or 0.0, int(m.group(2))
        return Promo(
            raw_text=text, kind=PromoKind.SECOND_PERCENT_OFF, required_quantity=n,
            effective_multiplier=(n - pct / 100.0) / n, percent_off=pct,
            is_personal=is_personal, source=source,
        )

    for pattern, qty_group, pct_group in ((_BULK_VANAF, 1, 2), (_BULK_PER, 2, 1)):
        if m := pattern.search(norm):
            pct = parse_decimal(m.group(pct_group)) or 0.0
            return Promo(
                raw_text=text, kind=PromoKind.BULK_TIER, required_quantity=int(m.group(qty_group)),
                effective_multiplier=1.0 - pct / 100.0, percent_off=pct,
                is_personal=is_personal, source=source,
            )

    if m := _PER_WEIGHT.search(norm):
        grams, price = parse_decimal(m.group(1)), parse_decimal(m.group(2))
        if grams and price is not None:
            return Promo(
                raw_text=text, kind=PromoKind.PRICE_PER_WEIGHT,
                price_per_100g=price * 100.0 / grams, is_personal=is_personal, source=source,
            )

    if m := _AMOUNT_OFF.search(norm):
        return Promo(
            raw_text=text, kind=PromoKind.AMOUNT_OFF, amount_off=parse_decimal(m.group(1)),
            is_personal=is_personal, source=source,
        )

    if m := _X_FOR_Y.search(norm):
        return Promo(
            raw_text=text, kind=PromoKind.X_FOR_Y, required_quantity=int(m.group(1)),
            total_promo_price=parse_decimal(m.group(2)), is_personal=is_personal, source=source,
        )

    if m := _PERCENT.search(norm):
        pct = parse_decimal(m.group(1)) or 0.0
        return Promo(
            raw_text=text, kind=PromoKind.PERCENT_OFF, required_quantity=1,
            effective_multiplier=1.0 - pct / 100.0, percent_off=pct,
            is_personal=is_personal, source=source,
        )

    if m := _FIXED.search(norm):
        return Promo(
            raw_text=text, kind=PromoKind.FIXED_PRICE, required_quantity=1,
            total_promo_price=parse_decimal(m.group(1)), is_personal=is_personal, source=source,
        )

    return Promo(raw_text=text, kind=PromoKind.UNKNOWN, needs_review=True,
                 is_personal=is_personal, source=source)


# -- AH typed labels ---------------------------------------------------------
# AH ships a typed `discountLabels[].code` alongside the Dutch string, and the
# string is sometimes absent while the code is not. The code is the source of
# truth; the string supplies the numbers. Codes observed 2026-09-16.

_AH_CODE_KINDS: dict[str, PromoKind | None] = {
    "DISCOUNT_PERCENTAGE": PromoKind.PERCENT_OFF,
    "DISCOUNT_X_FOR_Y": PromoKind.X_FOR_Y,
    "DISCOUNT_FIXED_PRICE": PromoKind.FIXED_PRICE,
    "DISCOUNT_X_PLUS_Y_FREE": PromoKind.X_PLUS_Y_FREE,
    "DISCOUNT_ONE_HALF_PRICE": PromoKind.SECOND_HALF_PRICE,
    "DISCOUNT_AMOUNT": PromoKind.AMOUNT_OFF,
    "DISCOUNT_WEIGHT": PromoKind.PRICE_PER_WEIGHT,
    "DISCOUNT_PERCENTAGE_PER_AMOUNT": PromoKind.BULK_TIER,
    # Online "op = op" clearance, first seen 2026-09-22. "35% korting".
    "DISCOUNT_OP_IS_OP": PromoKind.PERCENT_OFF,
    # Generic headline ('ACTIE'/'BONUS') but a real price in defaultDescription.
    "DISCOUNT_FALLBACK": PromoKind.FIXED_PRICE,
    # Genuinely contentless - no number anywhere. These are the review cases.
    "DISCOUNT_ACTION": None,
    "DISCOUNT_BONUS": None,
}


def parse_ah_label(label: dict, *, headline: str | None = None) -> Promo:
    """Parse one AH `discountLabels[]` entry.

    `headline` is the offer's `discountDescription`, used only as a fallback when
    the label carries no description of its own.
    """
    code = (label or {}).get("code") or ""
    description = (label or {}).get("defaultDescription") or headline
    price = (label or {}).get("price")

    promo = parse_promo_text(description, source="ah_label")

    known_code = code in _AH_CODE_KINDS
    expected = _AH_CODE_KINDS.get(code)

    # The typed price is authoritative for the money-carrying kinds - it survives
    # description formats the regexes have not seen.
    if price is not None and promo.kind in (PromoKind.FIXED_PRICE, PromoKind.X_FOR_Y):
        promo = _replace(promo, total_promo_price=float(price))

    if expected is None and known_code:
        # A recognised but contentless code. Do not guess.
        return _replace(promo, kind=PromoKind.UNKNOWN, effective_multiplier=None,
                        total_promo_price=None, needs_review=True)

    if not known_code:
        # New code: keep whatever the string yielded, but flag it for review
        # rather than trusting semantics we have never seen.
        return _replace(promo, needs_review=True)

    if promo.kind is PromoKind.UNKNOWN:
        # The code says what this is but the string did not parse. Salvage only
        # what the typed price can support; otherwise review.
        if expected is PromoKind.FIXED_PRICE and price is not None:
            return Promo(raw_text=promo.raw_text, kind=PromoKind.FIXED_PRICE,
                         required_quantity=1, total_promo_price=float(price), source="ah_label")
        return _replace(promo, needs_review=True)

    return promo


def _replace(promo: Promo, **changes) -> Promo:
    from dataclasses import replace

    return replace(promo, **changes)
