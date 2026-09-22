"""AH's catalogue lane. Milestone 15.

Only the milestone-15 additions are covered here: picking one image rendition,
and mapping a browse card's catalogue fields. The promo lanes have their own
coverage through the ingest and parser suites.

No network. `_image` is a pure function, and the card shapes below are trimmed
copies of real responses fetched on 2026-09-22.
"""

from __future__ import annotations

from bonusrank.adapters.ah import PREFERRED_IMAGE_WIDTH, AHAdapter, _image
from bonusrank.rawstore import RawStore

# The rendition list AH actually returns, with the urls shortened.
REAL_IMAGES = [
    {"width": 800, "height": 800, "url": "https://static.ah.nl/x?rendition=800x800_WEBP"},
    {"width": 400, "height": 400, "url": "https://static.ah.nl/x?rendition=400x400_WEBP"},
    {"width": 200, "height": 200, "url": "https://static.ah.nl/x?rendition=200x200_WEBP"},
    {"width": 48, "height": 48, "url": "https://static.ah.nl/x?rendition=48x48_GIF"},
    {"width": 80, "height": 80, "url": "https://static.ah.nl/x?rendition=80x80_JPG"},
]


def test_the_preferred_width_is_chosen_when_it_exists():
    """400 is the one size that serves a 64dp list thumbnail at 3x and a detail
    screen without a second request."""
    assert _image(REAL_IMAGES) == {
        "image_url": "https://static.ah.nl/x?rendition=400x400_WEBP",
        "image_width": PREFERRED_IMAGE_WIDTH,
    }


def test_the_largest_available_is_used_when_the_preferred_width_is_missing():
    """Downscaling on the device beats upscaling, so the fallback goes up."""
    assert _image([REAL_IMAGES[0], REAL_IMAGES[2]])["image_width"] == 800


def test_no_images_gives_null_rather_than_an_invented_url():
    """The app shows its own placeholder. The data does not pretend."""
    assert _image(None) == {"image_url": None, "image_width": None}
    assert _image([]) == {"image_url": None, "image_width": None}


def test_a_rendition_missing_its_width_is_skipped_not_guessed():
    """A url with no width would force the app to parse the query string to
    find out what it is about to download - which is exactly what storing the
    width alongside exists to avoid."""
    assert _image([{"url": "https://static.ah.nl/x"}]) == {
        "image_url": None, "image_width": None,
    }


def test_a_browse_card_maps_its_catalogue_fields(tmp_path):
    """`mainCategory` stays in `category` because match_overrides.yaml excludes
    whole departments by it; the finer level goes to `subcategory`."""
    card = {
        "webshopId": 4004,
        "title": "AH Rundergehakt",
        "brand": "AH",
        "salesUnitSize": "500 g",
        "mainCategory": "Vlees",
        "subCategory": "Rundergehakt",
        "priceBeforeBonus": 5.49,
        "unitPriceDescription": "prijs per kilo 10.98",
        "images": REAL_IMAGES,
    }

    # A real adapter, but pointed at a temp raw store: `_to_product` records
    # where the response was persisted, and nothing here goes near the network.
    adapter = AHAdapter(store=RawStore(root=tmp_path))
    product = adapter._to_product(card, source_url="https://example.invalid")

    assert product.sku == "4004"
    assert product.category == "Vlees"
    assert product.subcategory == "Rundergehakt"
    assert product.image_width == 400
    assert product.shelf_price == 5.49
    assert product.stated_unit_price_text == "prijs per kilo 10.98"
