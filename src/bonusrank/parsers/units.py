"""Unit-size parser. Testing priority 1 - the main source of bugs.

The important output is not `total_g`, it is `cost_basis_g`. Brief section 3.1:
cost metrics use purchased, edible, *drained* mass, because you pay for brine you
pour away. A 400 g tin of chickpeas draining to 240 g looks ~40% better on
protein-per-euro than it is if you cost it on net weight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .common import normalise, parse_decimal


class SizeKind(str, Enum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"
    UNKNOWN = "unknown"


_MASS_UNITS = {"kg": 1000.0, "kilo": 1000.0, "kilogram": 1000.0, "g": 1.0, "gr": 1.0, "gram": 1.0}
_VOLUME_UNITS = {"l": 1000.0, "ltr": 1000.0, "liter": 1000.0, "litre": 1000.0, "ml": 1.0, "cl": 10.0, "dl": 100.0}

_NUM = r"\d+(?:[.,]\d+)?"
_MASS_WORDS = "kilogram|kilo|kg|gram|gr|g"
_VOLUME_WORDS = "liter|litre|ltr|ml|cl|dl|l"
_COUNT_WORDS = "stuks|stuk|eieren|st"

# "N container à/van value unit" - a Dutch multipack phrasing with a count NOUN
# instead of AH's "N x value unit". Found on Jumbo 2026-09-17: "24 blikken à
# 33cl" was falling through to the SINGLE-unit pattern (matching only "33 cl"),
# silently dropping the "24" and producing a unit price ~24x too high.
#
# Spelled out rather than built from a stem + suffix pattern: Dutch pluralises
# with consonant doubling (fles -> flessen, zak -> zakken, pot -> potten,
# doos -> dozen) that a compact regex gets wrong in both directions. Longest
# form first in each family so the alternation does not stop early on a prefix.
_CONTAINER_WORDS = (
    r"blikken|blikjes|blikje|blik|"
    r"flessen|flesjes|flesje|fles|"
    r"rollen|rol|"
    r"zakken|zakjes|zakje|zak|"
    r"potten|potjes|potje|pot|"
    r"pakken|pakjes|pakje|pak|"
    r"dozen|doosjes|doosje|doos"
)

# Order matters: the drained weight is stripped before the net size is read.
_DRAINED = re.compile(rf"uitlekgewicht\s*:?\s*({_NUM})\s*({_MASS_WORDS})\b")
_APPROX = re.compile(r"(?:^|\s)(ca\.?|circa|\+/-|ong\.?|ongeveer)(?:\s|$)|\+/-")
_MULTIPACK_MASS = re.compile(rf"(\d+)\s*x\s*({_NUM})\s*({_MASS_WORDS})\b")
_MULTIPACK_VOLUME = re.compile(rf"(\d+)\s*x\s*({_NUM})\s*({_VOLUME_WORDS})\b")
_MULTIPACK_CONTAINER_MASS = re.compile(
    rf"(\d+)\s*(?:{_CONTAINER_WORDS})\s*(?:à|van)\s*({_NUM})\s*({_MASS_WORDS})\b"
)
_MULTIPACK_CONTAINER_VOLUME = re.compile(
    rf"(\d+)\s*(?:{_CONTAINER_WORDS})\s*(?:à|van)\s*({_NUM})\s*({_VOLUME_WORDS})\b"
)
_SINGLE_MASS = re.compile(rf"({_NUM})\s*({_MASS_WORDS})\b")
_SINGLE_VOLUME = re.compile(rf"({_NUM})\s*({_VOLUME_WORDS})\b")
_COUNT = re.compile(rf"(?:(\d+)\s*)?\b({_COUNT_WORDS})\b")


@dataclass(frozen=True)
class UnitSize:
    raw_text: str | None
    kind: SizeKind = SizeKind.UNKNOWN
    count: int | None = None
    unit_size_g: float | None = None
    unit_size_ml: float | None = None
    total_g: float | None = None
    total_ml: float | None = None
    drained_g: float | None = None
    is_approximate: bool = False
    needs_review: bool = False

    @property
    def cost_basis_g(self) -> float | None:
        """The mass to divide money by. Drained beats net, always (section 3.1)."""
        return self.drained_g if self.drained_g is not None else self.total_g

    @property
    def needs_food_type_mass(self) -> bool:
        """True when grams cannot be known from the label alone.

        Countables need `food_type.g_per_unit`; volumes need `density_g_per_ml`.
        Callers must resolve this before computing protein-per-euro.
        """
        return self.total_g is None and self.kind in (SizeKind.COUNT, SizeKind.VOLUME)


def parse_unit_size(text: str | None) -> UnitSize:
    """Parse a Dutch shelf unit string. Never raises; never invents a mass."""
    norm = normalise(text)
    if not norm:
        return UnitSize(raw_text=text, kind=SizeKind.UNKNOWN, needs_review=True)

    is_approx = bool(_APPROX.search(norm))

    drained_g = None
    drained_match = _DRAINED.search(norm)
    if drained_match:
        value = parse_decimal(drained_match.group(1))
        if value is not None:
            drained_g = value * _MASS_UNITS[drained_match.group(2)]
        # Remove it so "400 g (uitlekgewicht 240 g)" reads its net size, not 240.
        norm = norm[: drained_match.start()] + " " + norm[drained_match.end() :]
        norm = normalise(norm.replace("(", " ").replace(")", " "))

    parsed = (
        _try_multipack(norm, _MULTIPACK_MASS, _MASS_UNITS, SizeKind.MASS)
        or _try_multipack(norm, _MULTIPACK_VOLUME, _VOLUME_UNITS, SizeKind.VOLUME)
        or _try_multipack(norm, _MULTIPACK_CONTAINER_MASS, _MASS_UNITS, SizeKind.MASS)
        or _try_multipack(norm, _MULTIPACK_CONTAINER_VOLUME, _VOLUME_UNITS, SizeKind.VOLUME)
        or _try_single(norm, _SINGLE_MASS, _MASS_UNITS, SizeKind.MASS)
        or _try_single(norm, _SINGLE_VOLUME, _VOLUME_UNITS, SizeKind.VOLUME)
        or _try_count(norm)
    )

    if parsed is None:
        # Unknown, but a drained weight alone is still usable.
        return UnitSize(
            raw_text=text,
            kind=SizeKind.MASS if drained_g is not None else SizeKind.UNKNOWN,
            drained_g=drained_g,
            is_approximate=is_approx,
            needs_review=drained_g is None,
        )

    kind, count, per_unit = parsed
    if kind is SizeKind.MASS:
        return UnitSize(
            raw_text=text, kind=kind, count=count, unit_size_g=per_unit,
            total_g=per_unit * count if per_unit is not None else None,
            drained_g=drained_g, is_approximate=is_approx,
        )
    if kind is SizeKind.VOLUME:
        return UnitSize(
            raw_text=text, kind=kind, count=count, unit_size_ml=per_unit,
            total_ml=per_unit * count if per_unit is not None else None,
            drained_g=drained_g, is_approximate=is_approx,
        )
    return UnitSize(
        raw_text=text, kind=SizeKind.COUNT, count=count,
        drained_g=drained_g, is_approximate=is_approx,
    )


def _try_multipack(norm, pattern, units, kind):
    m = pattern.search(norm)
    if not m:
        return None
    value = parse_decimal(m.group(2))
    if value is None:
        return None
    return kind, int(m.group(1)), value * units[m.group(3)]


def _try_single(norm, pattern, units, kind):
    m = pattern.search(norm)
    if not m:
        return None
    value = parse_decimal(m.group(1))
    if value is None:
        return None
    return kind, 1, value * units[m.group(2)]


def _try_count(norm):
    m = _COUNT.search(norm)
    if not m:
        return None
    return SizeKind.COUNT, int(m.group(1)) if m.group(1) else 1, None
