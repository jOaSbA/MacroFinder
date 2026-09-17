"""Cross-check the computed unit price against the one the store publishes.

Brief section 7. This is the pipeline's only defence against a unit-size parse
that is silently wrong - the bug class the brief names as most likely, and one
that would otherwise corrupt every protein-per-euro ranking without a symptom.

Deliberate subtlety: the check compares on NET mass, while the ranking costs on
DRAINED mass (section 3.1). Feeding drained mass in here would fire a false alarm
on every tin whose label does state an uitlekgewicht.

But a mismatch is NOT automatically a parser bug. Measured against 475 real AH
SKUs on 2026-09-16, 473 agreed within 2% and both outliers were the store, not
us: sun-dried tomatoes labelled "180 g" are priced per kg on 90 g (packed in oil
- that is the drained weight), and "ca. 300 g" herring is priced on 270 g. In
this week's data NO SKU stated "uitlekgewicht" in salesUnitSize at all, so this
check is the only place a drained fraction is visible. Hence `implied_quantity_g`:
a mismatch is a question - parser bug, or the store revealing the real cost basis?
Answer it in review; never auto-apply it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from .common import normalise, parse_decimal
from .units import SizeKind, UnitSize

log = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.02


class PriceBasis(str, Enum):
    PER_KG = "per_kg"
    PER_100G = "per_100g"
    PER_LITRE = "per_litre"
    PER_100ML = "per_100ml"
    UNKNOWN = "unknown"


_NUM = r"\d+(?:[.,]\d+)?"
# Most specific first: "per 100 g" must not be read as a bare "per g".
_BASIS_PATTERNS: tuple[tuple[re.Pattern[str], PriceBasis], ...] = (
    (re.compile(rf"per\s*100\s*(?:g|gram)\b.*?({_NUM})"), PriceBasis.PER_100G),
    (re.compile(rf"per\s*100\s*ml\b.*?({_NUM})"), PriceBasis.PER_100ML),
    (re.compile(rf"per\s*(?:kg|kilo|kilogram)\b.*?({_NUM})"), PriceBasis.PER_KG),
    (re.compile(rf"per\s*(?:l|liter|litre)\b.*?({_NUM})"), PriceBasis.PER_LITRE),
)

_MASS_BASES = {PriceBasis.PER_KG: 1000.0, PriceBasis.PER_100G: 100.0}
_VOLUME_BASES = {PriceBasis.PER_LITRE: 1000.0, PriceBasis.PER_100ML: 100.0}


@dataclass(frozen=True)
class StatedUnitPrice:
    raw_text: str | None
    price: float | None = None
    basis: PriceBasis = PriceBasis.UNKNOWN
    needs_review: bool = False


@dataclass(frozen=True)
class UnitPriceCheck:
    computed: float | None
    stated: float | None
    deviation: float | None
    comparable: bool
    within_tolerance: bool | None
    reason: str = ""
    # Mass (or volume) the STORE's unit price implies, when it disagrees with the
    # label. Observed 2026-09-16: AH prices sun-dried tomatoes "180 g" per kg on
    # 90 g - the drained weight - and "ca. 300 g" herring on 270 g. So a mismatch
    # is not always a parser bug; it is often the store revealing the real cost
    # basis (brief section 3.1) that the label omits. Surfaced, never auto-applied.
    implied_quantity_g: float | None = None
    implied_quantity_ml: float | None = None

    @property
    def implied_fraction(self) -> float | None:
        """Implied mass as a fraction of the labelled net mass, e.g. 0.50."""
        if self.deviation is None or self.stated in (None, 0) or self.computed is None:
            return None
        return self.computed / self.stated


def parse_stated_unit_price(text: str | None) -> StatedUnitPrice:
    """Parse 'normale prijs per kg EUR 3.96' into a price and a basis."""
    norm = normalise(text)
    if not norm:
        return StatedUnitPrice(raw_text=text, needs_review=True)

    for pattern, basis in _BASIS_PATTERNS:
        if m := pattern.search(norm):
            price = parse_decimal(m.group(1))
            if price is not None:
                return StatedUnitPrice(raw_text=text, price=price, basis=basis)

    return StatedUnitPrice(raw_text=text, needs_review=True)


def compare_unit_price(
    stated: StatedUnitPrice,
    *,
    shelf_price: float | None,
    size: UnitSize,
    tolerance: float = DEFAULT_TOLERANCE,
    label: str = "",
) -> UnitPriceCheck:
    """Compare our computed unit price against the store's. Logs loudly on a miss."""
    if stated.price is None or stated.basis is PriceBasis.UNKNOWN:
        return _incomparable("no stated unit price")
    if stated.price == 0:
        # A free/zero stated price is a data-quality artefact, not a real basis
        # to divide by - measured on real Aldi data 2026-09-17 (a promotional
        # item whose basePriceValue came through as 0).
        return _incomparable("stated unit price is zero")
    if shelf_price is None:
        return _incomparable("no shelf price")
    if size.kind is SizeKind.UNKNOWN:
        return _incomparable("unit size did not parse")

    # Net mass on purpose - see the module docstring.
    if stated.basis in _MASS_BASES:
        if size.total_g is None:
            return _incomparable("stated per mass but size is not a mass")
        quantity = size.total_g / _MASS_BASES[stated.basis]
    elif stated.basis in _VOLUME_BASES:
        if size.total_ml is None:
            return _incomparable("stated per volume but size is not a volume")
        quantity = size.total_ml / _VOLUME_BASES[stated.basis]
    else:
        return _incomparable("unsupported basis")

    if quantity <= 0:
        return _incomparable("non-positive quantity")

    computed = shelf_price / quantity
    deviation = abs(computed - stated.price) / stated.price
    within = deviation <= tolerance

    if not within:
        log.warning(
            "UNIT PRICE MISMATCH %s: computed %.4f vs stated %.4f (%.1f%% off) "
            "size=%r shelf=%.2f implied_mass=%s g (%.0f%% of label) - either a "
            "unit-size parser bug or a drained/edible fraction the label omits",
            label or "(unlabelled)", computed, stated.price, deviation * 100,
            size.raw_text, shelf_price,
            f"{shelf_price / stated.price * _MASS_BASES[stated.basis]:.0f}"
            if stated.basis in _MASS_BASES else "n/a",
            (computed / stated.price) * 100,
        )

    implied = shelf_price / stated.price if stated.price else None
    return UnitPriceCheck(
        computed=computed, stated=stated.price, deviation=deviation,
        comparable=True, within_tolerance=within,
        implied_quantity_g=(implied * _MASS_BASES[stated.basis]
                            if implied is not None and stated.basis in _MASS_BASES else None),
        implied_quantity_ml=(implied * _VOLUME_BASES[stated.basis]
                             if implied is not None and stated.basis in _VOLUME_BASES else None),
    )


def _incomparable(reason: str) -> UnitPriceCheck:
    return UnitPriceCheck(
        computed=None, stated=None, deviation=None,
        comparable=False, within_tolerance=None, reason=reason,
    )
