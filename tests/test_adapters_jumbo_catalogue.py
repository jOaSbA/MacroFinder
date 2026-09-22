"""Jumbo's catalogue lane. Milestone 16.

Only the milestone-16 additions: the flat crawl shape, and mapping a product
node's catalogue fields. The offers lane and the devalue resolver have their own
coverage in `test_adapters_jumbo.py` and `test_devalue.py`.

No network. The node below is a trimmed copy of a real one fetched 2026-09-22.
"""

from __future__ import annotations

from bonusrank.adapters.jumbo import CATALOGUE_IMAGE_WIDTH, JumboAdapter
from bonusrank.rawstore import RawStore

PRODUCT_NODE = {
    "id": "532148ZK",
    "sku": "532148ZK",
    "brand": "Dole",
    "category": "Aardappelen, groente en fruit",
    "subtitle": None,
    "title": "Jumbo Dole Bananen 5 Stuks",
    "image": "https://www.jumbo.com/dam-images/fit-in/360x360/Products/x.png",
    "link": "/producten/jumbo-dole-bananen-5-stuks-532148ZK",
    "price": {
        "price": 169,
        "promoPrice": None,
        "pricePerUnit": {"price": 34, "unit": "pieces"},
    },
}


def _adapter(tmp_path) -> JumboAdapter:
    return JumboAdapter(store=RawStore(root=tmp_path))


def test_the_whole_assortment_is_one_node():
    """AH needs a category tree because its lane refuses offsets past 3000 and
    four of its categories are bigger than that. Jumbo answers at offset
    17,000, so splitting the crawl by category would cost the same requests and
    add a way to miss a product that sits in no tile."""
    tree = JumboAdapter.category_tree(None)

    assert len(tree) == 1
    assert tree[0]["id"] == ""
    assert JumboAdapter.category_children(None, "") == []


def test_jumbo_declares_no_paging_ceiling():
    """`None` and not a large number. A made-up limit would make the crawl
    descend into children that do not exist."""
    # Asserted on the CLASS, which is where `catalogue.crawl` looks. Asserting
    # the module-level constant is what let this ship broken once already.
    assert JumboAdapter.CATALOGUE_MAX_OFFSET is None


def test_the_page_size_is_the_one_the_site_actually_uses():
    """`pageSize` is accepted and ignored - `?offSet=0&pageSize=100` returns 24
    products, same as without it. Asking for more would silently skip 76 of
    every 100 products, because the crawl advances by what it asked for."""
    assert JumboAdapter.CATALOGUE_PAGE_SIZE == 24


def test_a_product_node_maps_its_catalogue_fields(tmp_path):
    product = _adapter(tmp_path)._map_product(PRODUCT_NODE, "https://example.invalid")

    assert product.sku == "532148ZK"
    assert product.name == "Jumbo Dole Bananen 5 Stuks"
    assert product.category == "Aardappelen, groente en fruit"
    assert product.shelf_price == 1.69
    assert product.image_url.endswith("/x.png")
    assert product.image_width == CATALOGUE_IMAGE_WIDTH


def test_the_title_carries_the_pack_size_because_nothing_else_does(tmp_path):
    """Jumbo has no unit-size field. The title reliably ends with the pack size
    and `parse_unit_size` tolerates the leading noise, so it is used directly
    rather than left None for a caller to patch up."""
    product = _adapter(tmp_path)._map_product(PRODUCT_NODE, "https://example.invalid")

    assert product.raw_unit_text == "Jumbo Dole Bananen 5 Stuks"


def test_the_stated_unit_price_survives_for_the_cross_check(tmp_path):
    """BRIEF section 7 compares the chain's own unit price against the computed
    one on every ingest. Jumbo publishes it in cents under `pricePerUnit`."""
    product = _adapter(tmp_path)._map_product(PRODUCT_NODE, "https://example.invalid")

    assert product.stated_unit_price_text == "per pieces 0.34"


def test_a_product_with_no_image_gets_a_null_width_not_a_default(tmp_path):
    """The width describes an image that exists. Stamping 360 on a missing one
    would tell the app to size a request for nothing."""
    node = dict(PRODUCT_NODE, image=None)

    product = _adapter(tmp_path)._map_product(node, "https://example.invalid")

    assert product.image_url is None
    assert product.image_width is None
