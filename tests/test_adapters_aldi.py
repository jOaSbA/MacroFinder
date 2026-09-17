"""AldiAdapter's mapping logic. Milestone 7.

Endpoint state verified 2026-09-17 (see the module docstring in
`adapters/aldi.py` and CLAUDE.md section 4). Fixture shapes below are trimmed
but real, taken from a live fetch of `algoliaDataMap`. `_build_id` and
`_fetch_offer_data` are the only network-touching parts and are not exercised
here - everything else is pure mapping.
"""

from __future__ import annotations

from datetime import date

import pytest

from bonusrank.adapters.aldi import AldiAdapter, _category_titles, _department, _from_unix, _promo_text
from bonusrank.rawstore import RawStore

# A discounted item - real shape, trimmed.
_DISCOUNTED = {
    "isAvailable": True,
    "brandName": "MY VAY",
    "name": "Vegan schnitzels",
    "shortDescription": "2 stuks, 200 g.",
    "salesUnit": "2 stuks, 200 g",
    "productSlug": "vegan-schnitzels-1200158",
    "mainCategoryID": "vega",
    "currentPrice": {
        "priceValue": 1.49,
        "strikePrice": {"strikePriceValue": 1.69},
        "basePrice": [{"basePriceValue": 7.45, "basePriceScale": "kg"}],
        "priceTagLabels": {"promoText1": "-11%"},
        "validFrom": 1789336800,
        "validUntil": 1789941599,
    },
    "productReferences": [{"type": "KVArticleNumber", "value": "2103103"}],
    "hierarchicalCategories": {"lvl0": ["Vlees, vis en vega", "ALDI merken"]},
}

# An "OP=OP" (while stocks last) item - no strike price, no reference price.
_OP_OP = {
    "isAvailable": True,
    "brandName": None,
    "name": "Aster",
    "shortDescription": "Pot",
    "mainCategoryID": "tuin",
    "currentPrice": {
        "priceValue": 1.99,
        "strikePrice": None,
        "basePrice": None,
        "priceTagLabels": {"promoText1": "OP=OP"},
        "validFrom": 1789336800,
        "validUntil": 1789941599,
    },
}

_VANAF = {
    "isAvailable": True,
    "name": "Kamerplant",
    "currentPrice": {
        "priceValue": 3.99,
        "strikePrice": None,
        "priceTagLabels": {"promoText1": "VANAF"},
    },
}


def _adapter(tmp_path):
    adapter = AldiAdapter.__new__(AldiAdapter)
    adapter._store = RawStore(root=tmp_path)
    return adapter


# -- promo text synthesis: the shared mini-language -----------------------

def test_a_strike_price_becomes_an_exact_fixed_price_phrase():
    """Lossless: the real final price, not the rounded '-11%' label."""
    assert _promo_text(_DISCOUNTED["currentPrice"]) == "voor 1,49"


def test_op_op_is_not_a_promo():
    assert _promo_text(_OP_OP["currentPrice"]) == "elke dag lage prijs"


def test_a_missing_label_with_no_strike_is_also_not_a_promo():
    assert _promo_text({"priceValue": 1.0, "strikePrice": None}) == "elke dag lage prijs"


def test_an_ambiguous_label_is_passed_through_for_review():
    """VANAF (tiered pricing) has no single number to trust - not guessed at."""
    assert _promo_text(_VANAF["currentPrice"]) == "VANAF"


# -- offer mapping ------------------------------------------------------------

def test_to_offer_maps_a_discounted_entry(tmp_path):
    offer = _adapter(tmp_path)._to_offer("1200158", _DISCOUNTED, {})
    assert offer.offer_id == "1200158"
    assert offer.title == "Vegan schnitzels"
    assert offer.subtitle == "2 stuks, 200 g."
    assert offer.promo_raw_text == "voor 1,49"
    assert offer.valid_from == _from_unix(1789336800)
    assert offer.valid_to == _from_unix(1789941599)
    assert offer.product_skus == ["1200158"]
    assert offer.is_personal is False


def test_to_offer_prefers_the_specific_hierarchical_department(tmp_path):
    """"ALDI merken" is a cross-cutting own-brand facet, not a department -
    the genuinely departmental entry in `lvl0` is what should be used."""
    offer = _adapter(tmp_path)._to_offer("1200158", _DISCOUNTED, {})
    assert offer.category == "Vlees, vis en vega"


def test_to_offer_falls_back_to_the_category_title_map_with_no_hierarchy(tmp_path):
    entry = dict(_DISCOUNTED, hierarchicalCategories=None, mainCategoryID="vega")
    offer = _adapter(tmp_path)._to_offer("1200158", entry, {"vega": "Vlees, vis en vega"})
    assert offer.category == "Vlees, vis en vega"


def test_to_offer_falls_back_to_the_raw_category_id_when_untitled(tmp_path):
    entry = dict(_DISCOUNTED, hierarchicalCategories=None, mainCategoryID="vega")
    offer = _adapter(tmp_path)._to_offer("1200158", entry, {})
    assert offer.category == "vega"


# -- department (the real, useful category) ----------------------------------

def test_department_skips_generic_facets():
    entry = {"hierarchicalCategories": {"lvl0": ["ALDI merken", "Snoep, koek en chocolade"]}}
    assert _department(entry) == "Snoep, koek en chocolade"


def test_department_is_none_when_only_generic_facets_are_present():
    entry = {"hierarchicalCategories": {"lvl0": ["ALDI merken", "Speciaal assortiment"]}}
    assert _department(entry) is None


def test_department_is_none_with_no_hierarchy_at_all():
    assert _department({}) is None
    assert _department({"hierarchicalCategories": None}) is None


# -- product mapping -----------------------------------------------------

def test_fetch_product_reads_price_and_unit_from_the_cached_map(tmp_path):
    adapter = _adapter(tmp_path)
    adapter._algolia_cache = {"1200158": _DISCOUNTED}
    product = adapter.fetch_product("1200158")

    assert product.name == "Vegan schnitzels"
    assert product.brand == "MY VAY"
    assert product.raw_unit_text == "2 stuks, 200 g"
    assert product.shelf_price == 1.69  # the strike price: what it "normally" costs
    assert product.bonus_price == 1.49  # what you actually pay this week
    assert product.stated_unit_price_text == "per kg 7.45"
    assert product.ean is None  # only KVArticleNumber seen in the real data


def test_fetch_product_with_no_strike_price_has_no_bonus_price(tmp_path):
    adapter = _adapter(tmp_path)
    adapter._algolia_cache = {"aster": _OP_OP}
    product = adapter.fetch_product("aster")
    assert product.shelf_price == 1.99
    assert product.bonus_price is None


def test_fetch_product_raises_on_an_unknown_sku(tmp_path):
    adapter = _adapter(tmp_path)
    adapter._algolia_cache = {}
    with pytest.raises(KeyError):
        adapter.fetch_product("does-not-exist")


# -- category title lookup ---------------------------------------------------

def test_category_titles_maps_product_ids_to_group_titles():
    categories = [{
        "content": [{"title": "Weekacties", "productIds": ["a", "b"]}],
    }]
    assert _category_titles(categories) == {"a": "Weekacties", "b": "Weekacties"}


def test_category_titles_first_sighting_wins():
    categories = [
        {"content": [{"title": "Deze week", "productIds": ["a"]}]},
        {"content": [{"title": "Volgende week", "productIds": ["a"]}]},
    ]
    assert _category_titles(categories) == {"a": "Deze week"}


# -- timestamps ---------------------------------------------------------

def test_from_unix_parses_a_real_timestamp():
    assert isinstance(_from_unix(1789336800), date)


def test_from_unix_handles_none_and_garbage():
    assert _from_unix(None) is None
    assert _from_unix("not a number") is None
