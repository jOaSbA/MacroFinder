"""String parsers. Each is pure: text in, typed value out, no I/O, no network.

They run against the persisted snapshots, never against a live response, so a
parser fix can be replayed over history.
"""

from .nutrition import Energy, Macros, Nutrient, parse_energy, parse_gs1_nutrition, parse_nutrient, parse_nutrition_block
from .promos import Promo, PromoKind, parse_ah_label, parse_promo_text
from .unit_price import PriceBasis, StatedUnitPrice, UnitPriceCheck, compare_unit_price, parse_stated_unit_price
from .units import SizeKind, UnitSize, parse_unit_size

__all__ = [
    "Energy", "Macros", "Nutrient", "parse_energy", "parse_gs1_nutrition", "parse_nutrient", "parse_nutrition_block",
    "Promo", "PromoKind", "parse_ah_label", "parse_promo_text",
    "PriceBasis", "StatedUnitPrice", "UnitPriceCheck", "compare_unit_price", "parse_stated_unit_price",
    "SizeKind", "UnitSize", "parse_unit_size",
]
