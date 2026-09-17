"""JumboAdapter's mapping logic. Milestone 7.

Endpoint state verified 2026-09-17 (see the module docstring in
`adapters/jumbo.py` and CLAUDE.md section 4). These tests exercise the pure
mapping functions against realistic fixture shapes captured from the live page,
not the network calls themselves - `_get_resolved` is the only part that
touches HTTP, and it is a thin, untestable-without-a-server wrapper around
`PoliteClient` + `devalue.resolve`, already covered by `test_devalue.py`.
"""

from __future__ import annotations

from datetime import date

import pytest

from bonusrank.adapters.jumbo import JumboAdapter, _as_date, _cents_to_eur, _promotions_in, _single_sku_subtitle
from bonusrank.rawstore import RawStore

# A trimmed but real-shaped promotion node, as it appears inside a category.
_PROMOTION = {
    "id": "3021745",
    "title": "Blauwe bessen",
    "subtitle": "Bak 300 gram",
    "start": {"iso": "2026-09-16T00:01:00+02:00"},
    "end": {"iso": "2026-09-22T23:59:59+02:00"},
    "tags": [{"text": "voor 3,49"}],
}

_MULTI_VARIANT_PROMOTION = {
    "id": "3020225",
    "title": "Campina Langlekker Halfvolle Melk Multipack Mini's",
    "subtitle": "Alle sets met 6 pakjes à 200 ml",
    "start": {"iso": "2026-09-16T00:01:00+02:00"},
    "end": {"iso": "2026-09-22T23:59:59+02:00"},
    "tags": [{"text": "25% korting"}],
}


def _adapter(tmp_path):
    # No real HTTP client needed for the pure mapping methods under test, but
    # `_to_offer` does compute a raw_path via the (harmless, local) RawStore.
    adapter = JumboAdapter.__new__(JumboAdapter)
    adapter._store = RawStore(root=tmp_path)
    return adapter


# -- the ambiguous-subtitle guard --------------------------------------------

@pytest.mark.parametrize("subtitle", [
    "Alle sets met 6 pakjes à 200 ml",
    "M.u.v. Kuipjes à 200 gram",
    "Per verpakking<br />M.u.v. Kuipjes à 200 gram",  # the exact real-data case
    "Excl. losse flessen",
])
def test_a_multi_sku_subtitle_is_discarded(subtitle):
    """A promotion covering a product line, not one SKU's own pack size.

    Measured 2026-09-17: feeding this to the unit-size parser as if it were one
    SKU produced unit-price cross-check "mismatches" north of 100%, which is a
    category error, not a parser bug or a genuine store discrepancy.
    """
    assert _single_sku_subtitle(subtitle) is None


@pytest.mark.parametrize("subtitle", [
    "Bak 300 gram",
    "Net 750 gram",
    "Schaal 350 gram",
    None,
])
def test_a_genuine_single_sku_subtitle_passes_through(subtitle):
    assert _single_sku_subtitle(subtitle) == subtitle


# -- offer mapping ------------------------------------------------------------

def test_to_offer_maps_the_promotion_shape(tmp_path):
    offer = _adapter(tmp_path)._to_offer(dict(_PROMOTION, image="x"), category="Aardappelen, groente en fruit")
    assert offer.offer_id == "3021745"
    assert offer.title == "Blauwe bessen"
    assert offer.subtitle == "Bak 300 gram"
    assert offer.category == "Aardappelen, groente en fruit"
    assert offer.promo_raw_text == "voor 3,49"
    assert offer.valid_from == date(2026, 9, 16)
    assert offer.valid_to == date(2026, 9, 22)
    assert offer.product_skus == ["3021745"]
    assert offer.is_personal is False


def test_to_offer_discards_a_multi_variant_subtitle(tmp_path):
    offer = _adapter(tmp_path)._to_offer(_MULTI_VARIANT_PROMOTION, category="Zuivel")
    assert offer.subtitle is None


def test_to_offer_picks_the_first_tag_with_text(tmp_path):
    node = dict(_PROMOTION, tags=[{"text": None}, {"text": "1+1 gratis"}])
    offer = _adapter(tmp_path)._to_offer(node, category=None)
    assert offer.promo_raw_text == "1+1 gratis"


def test_to_offer_with_no_tags_has_no_promo_text(tmp_path):
    node = dict(_PROMOTION, tags=[])
    offer = _adapter(tmp_path)._to_offer(node, category=None)
    assert offer.promo_raw_text is None


# -- promotions_in: flattening a section's own list + its categories --------

def test_promotions_in_yields_section_level_promotions_with_the_section_title():
    section = {"title": "Nu in de aanbieding", "promotions": [_PROMOTION], "categories": []}
    result = list(_promotions_in(section))
    assert result == [(_PROMOTION, "Nu in de aanbieding")]


def test_promotions_in_yields_category_level_promotions_with_the_category_title():
    section = {
        "title": "Per gangpad",
        "promotions": [],
        "categories": [{"title": "Zuivel", "promotions": [_PROMOTION]}],
    }
    result = list(_promotions_in(section))
    assert result == [(_PROMOTION, "Zuivel")]


def test_promotions_in_combines_both_levels():
    spotlight = dict(_PROMOTION, id="1")
    categorised = dict(_PROMOTION, id="2")
    section = {
        "title": "Nu in de aanbieding",
        "promotions": [spotlight],
        "categories": [{"title": "Zuivel", "promotions": [categorised]}],
    }
    ids = {node["id"] for node, _ in _promotions_in(section)}
    assert ids == {"1", "2"}


# -- small helpers ------------------------------------------------------------

def test_as_date_parses_the_iso_prefix():
    assert _as_date("2026-09-22T23:59:59+02:00") == date(2026, 9, 22)


def test_as_date_handles_none_and_garbage():
    assert _as_date(None) is None
    assert _as_date("not a date") is None


def test_cents_to_eur():
    assert _cents_to_eur(349) == 3.49
    assert _cents_to_eur(None) is None
    assert _cents_to_eur("not a number") is None


# -- expand_offer: real per-SKU expansion for multi-variant promotions -------
# Discovered 2026-09-17: a multi-variant promotion's own OFFER DETAIL page (the
# same page fetched for a single-SKU promotion's price) carries a `Promotion`
# node whose `products` field - always empty on the listing page - is filled
# in with every real SKU the deal covers.

_VARIANT_PRODUCT = {
    "__typename": "Product", "id": "138601PAK", "sku": "138601PAK",
    "brand": "Optimel", "category": "Zuivel",
    "title": "Optimel Langlekker Drinkyoghurt Aardbei Framboos 0% Vet 6 x 200 ml",
    "price": {"__typename": "Price", "price": 299, "promoPrice": 249,
              "pricePerUnit": {"__typename": "PricePerUnit", "price": 208, "unit": "l"}},
    "link": "/producten/optimel-6x200ml",
}


def _root_with_promotion(products, *, extra_promotions=()):
    return {"state": {"$spromotion-detail-data": {
        "__typename": "Promotion", "id": "3020225", "products": products,
    }}, "extra": list(extra_promotions)}


def _patched_adapter(tmp_path, monkeypatch, resolved_root):
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(adapter, "_get_resolved", lambda url: resolved_root)
    return adapter


def test_expand_offer_maps_every_variant(tmp_path, monkeypatch):
    root = _root_with_promotion([_VARIANT_PRODUCT, dict(_VARIANT_PRODUCT, sku="61470PAK", id="61470PAK")])
    adapter = _patched_adapter(tmp_path, monkeypatch, root)

    products = adapter.expand_offer(_offer_obj())
    assert [p.sku for p in products] == ["138601PAK", "61470PAK"]
    assert products[0].shelf_price == 2.99
    assert products[0].bonus_price == 2.49
    assert products[0].stated_unit_price_text == "per l 2.08"


def test_expand_offer_prefers_the_sku_field_over_the_shared_promotion_id(tmp_path, monkeypatch):
    root = _root_with_promotion([_VARIANT_PRODUCT])
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    products = adapter.expand_offer(_offer_obj())
    assert products[0].sku == "138601PAK"
    assert products[0].sku != "3020225"  # the shared promotion/offer id


def test_expand_offer_falls_back_to_a_single_product_when_products_is_empty(tmp_path, monkeypatch):
    root = {
        "state": {"$spromotion-detail-data": {"__typename": "Promotion", "id": "3021745", "products": []}},
        "single": {"__typename": "Product", "id": "774264DS", "sku": "774264DS",
                  "title": "Jumbo Blauwe Bessen 300 g",
                  "price": {"price": 429, "promoPrice": 349}},
    }
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    products = adapter.expand_offer(_offer_obj(offer_id="3021745"))
    assert len(products) == 1
    assert products[0].sku == "774264DS"


def test_expand_offer_picks_the_promotion_node_with_the_most_products(tmp_path, monkeypatch):
    """The same page can repeat a Promotion node with the same id but fewer
    products (a "similar deals" widget) - the fuller one wins, not a merge."""
    root = {
        "a": {"__typename": "Promotion", "id": "3020225", "products": [_VARIANT_PRODUCT]},
        "b": {"__typename": "Promotion", "id": "3020225",
              "products": [_VARIANT_PRODUCT, dict(_VARIANT_PRODUCT, sku="61470PAK")]},
    }
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    products = adapter.expand_offer(_offer_obj())
    assert len(products) == 2


def test_expand_offer_returns_nothing_when_no_product_exists_at_all(tmp_path, monkeypatch):
    root = {"a": {"__typename": "Promotion", "id": "x", "products": []}}
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    assert adapter.expand_offer(_offer_obj()) == []


def _offer_obj(offer_id="3020225"):
    from bonusrank.models import RawOffer
    return RawOffer(chain="jumbo", offer_id=offer_id, title="x", product_skus=[offer_id])


# -- search_products: the base price catalogue (prices.py) -------------------

def test_search_products_maps_every_result(tmp_path, monkeypatch):
    root = {"a": _VARIANT_PRODUCT, "b": dict(_VARIANT_PRODUCT, sku="61470PAK", id="61470PAK")}
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    results = adapter.search_products("optimel")
    assert [r.sku for r in results] == ["138601PAK", "61470PAK"]


def test_search_products_skips_cards_with_no_sku_or_title(tmp_path, monkeypatch):
    """Ad/category tiles mixed into real search results, observed 2026-09-17."""
    blank = {"__typename": "Product", "id": None, "sku": None, "title": None}
    root = {"a": _VARIANT_PRODUCT, "b": blank}
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    results = adapter.search_products("optimel")
    assert len(results) == 1


def test_search_products_respects_size(tmp_path, monkeypatch):
    root = {str(i): dict(_VARIANT_PRODUCT, sku=f"sku{i}", id=f"sku{i}") for i in range(5)}
    adapter = _patched_adapter(tmp_path, monkeypatch, root)
    assert len(adapter.search_products("optimel", size=2)) == 2
