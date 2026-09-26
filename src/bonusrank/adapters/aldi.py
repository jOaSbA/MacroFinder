"""Aldi NL adapter.

Endpoint state verified 2026-09-17, superseding CLAUDE.md's 2026-09-16 finding.
Both things the brief and CLAUDE.md tried are confirmed dead: the documented
`webservice.aldi.nl/api/v1/promotions.json` returns 200 with a zero-byte body,
and `__NEXT_DATA__` on the offers page is genuinely just a Magnolia CMS
navigation tree with no prices at any depth, as CLAUDE.md found.

What actually works is the page's own Next.js **data route** - the JSON Next.js
itself fetches client-side to hydrate the page, one level below `__NEXT_DATA__`,
at `/_next/data/{buildId}/nl/aanbiedingen.html.json`. `buildId` is not guessed:
it is read straight out of `__NEXT_DATA__.buildId` on a normal page fetch, the
same way AH's section URLs are read from `v3/metadata` rather than hardcoded -
it changes on every Aldi deploy.

That data route's `pageProps.apiData` is a JSON-encoded 2-element list (the
shape CLAUDE.md already found: `[["OFFER_GET", {req, res}], ["PAGE_MGNL_GET",
...]]`). `OFFER_GET.res.algoliaDataMap` is what was missing before: 200+ SKUs
keyed by product id, each with a structured `currentPrice` (current, strike,
and per-kilo/per-litre base price, plus a validity window) - the exact pricing
CLAUDE.md said was unreachable. No cookies, no session, no browser needed.

**`OP=OP`** ("while stocks last") is Aldi's own honest term for "this is simply
this week's price, no reference price is being discounted" - the large majority
of entries (~155 of 211 measured 2026-09-17). Mapped to `NOT_A_PROMO`, not
treated as a gap.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from ..http import PoliteClient
from ..models import RawOffer, RawProduct
from ..rawstore import RawStore
from .base import register

log = logging.getLogger(__name__)

BASE_URL = "https://www.aldi.nl"
OFFERS_PAGE = f"{BASE_URL}/aanbiedingen.html"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


@register
class AldiAdapter:
    chain = "aldi"

    def __init__(self, client: PoliteClient | None = None, store: RawStore | None = None) -> None:
        self._client = client or PoliteClient(self.chain, base_url=BASE_URL)
        self._store = store or RawStore()
        self._algolia_cache: dict[str, dict] | None = None

    # -- discovery -------------------------------------------------------

    def _build_id(self) -> str:
        """Read the current deploy's build id off a plain page fetch.

        Never hardcoded or cached across process runs - it changes on every
        Aldi deploy, the same reasoning CLAUDE.md gives for AH's section URLs.
        """
        html = self._client.request_text("GET", OFFERS_PAGE)
        match = _NEXT_DATA_RE.search(html)
        if not match:
            raise ValueError("aldi: no __NEXT_DATA__ on the offers page - page shape changed")
        return json.loads(match.group(1))["buildId"]

    def _fetch_offer_data(self) -> dict[str, Any]:
        """The `OFFER_GET` half of `apiData`: `algoliaDataMap` + `categories`.

        Persisted before parsing, per CLAUDE.md section 1. Cached on `self` for
        the lifetime of the adapter so `fetch_promotions` and N calls to
        `fetch_product` share one fetch - the underlying HTTP call is also
        6h-disk-cached, but this avoids re-parsing the 400KB JSON N+1 times.
        """
        if self._algolia_cache is not None:
            return self._algolia_cache

        build_id = self._build_id()
        url = f"{BASE_URL}/_next/data/{build_id}/nl/aanbiedingen.html.json"
        payload = self._client.get_json(url)
        self._store.save(self.chain, url, payload)

        api_data = json.loads(payload["pageProps"]["apiData"])
        offer_get = next(
            (entry[1] for entry in api_data if isinstance(entry, list) and entry[0] == "OFFER_GET"),
            None,
        )
        if offer_get is None:
            raise ValueError("aldi: apiData has no OFFER_GET entry - page shape changed")

        self._algolia_cache = offer_get["res"]["algoliaDataMap"]
        self._categories = offer_get["res"].get("categories") or []
        return self._algolia_cache

    # -- listing -----------------------------------------------------------

    def fetch_promotions(self) -> list[RawOffer]:
        """Every currently-listed SKU. One promotion per SKU - no expansion step.

        Unlike AH's segment model, `algoliaDataMap` already gives per-SKU
        pricing directly, so `product_skus` is filled immediately and
        `fetch_product` only ever re-reads this same (cached) map.
        """
        algolia = self._fetch_offer_data()
        category_by_id = _category_titles(self._categories)

        offers = []
        for object_id, entry in algolia.items():
            if entry.get("isAvailable") is False:
                continue
            offers.append(self._to_offer(object_id, entry, category_by_id))
        return offers

    def _to_offer(self, object_id: str, entry: dict, category_by_id: dict[str, str]) -> RawOffer:
        current = entry.get("currentPrice") or {}
        valid_from = _from_unix(current.get("validFrom"))
        valid_to = _from_unix(current.get("validUntil"))
        return RawOffer(
            chain=self.chain,
            offer_id=object_id,
            title=entry.get("name") or "",
            subtitle=entry.get("shortDescription"),
            category=_department(entry)
            or category_by_id.get(entry.get("mainCategoryID"), entry.get("mainCategoryID")),
            promo_raw_text=_promo_text(current),
            valid_from=valid_from,
            valid_to=valid_to,
            is_personal=False,  # Aldi's public offer feed carries no loyalty tier
            product_skus=[object_id],
            source_url=OFFERS_PAGE,
            raw_path=str(self._store.path_for(self.chain, OFFERS_PAGE)),
            raw=entry,
        )

    # -- product level -------------------------------------------------------

    def fetch_product(self, sku: str) -> RawProduct:
        """Re-reads the same (cached) `algoliaDataMap` entry `fetch_promotions` used.

        No separate per-product endpoint was found; none is needed - the
        listing already carries full pricing and unit-size text per SKU.
        """
        algolia = self._fetch_offer_data()
        entry = algolia.get(sku)
        if entry is None:
            raise KeyError(f"aldi: sku {sku!r} not in the current offer feed")

        current = entry.get("currentPrice") or {}
        base = (current.get("basePrice") or [{}])[0]
        return RawProduct(
            chain=self.chain,
            sku=sku,
            name=entry.get("name") or "",
            brand=entry.get("brandName"),
            raw_unit_text=entry.get("salesUnit") or entry.get("shortDescription"),
            # `productReferences[].type` is only ever "KVArticleNumber" across
            # the 211 SKUs measured 2026-09-17 - no EAN type seen, so none is
            # guessed at. `KVArticleNumber` is Aldi's own internal number, not
            # a GTIN; ean stays unset rather than mislabelling it.
            ean=None,
            category=_department(entry) or entry.get("mainCategoryID"),
            shelf_price=current.get("strikePrice", {}).get("strikePriceValue")
            if current.get("strikePrice") else current.get("priceValue"),
            bonus_price=current.get("priceValue") if current.get("strikePrice") else None,
            # "per kg 7.45" - matches parsers.unit_price's "per (kg|...) NUMBER"
            # pattern, which expects the basis word before the number.
            stated_unit_price_text=(
                f"per {base['basePriceScale']} {base['basePriceValue']}"
                if base.get("basePriceValue") is not None else None
            ),
            image_url=_image(entry),
            image_width=IMAGE_WIDTH if _image(entry) else None,
            url=f"{BASE_URL}/aanbiedingen/{entry.get('productSlug')}.html"
            if entry.get("productSlug") else None,
            source_url=OFFERS_PAGE,
            raw_path=str(self._store.path_for(self.chain, OFFERS_PAGE)),
            raw=entry,
        )


# `mainCategoryID` is often the useless literal "offer" - a bucket for
# whatever is on promotion this week, not a department. `hierarchicalCategories
# .lvl0` is the real, AH-shaped taxonomy ("Vlees, vis en vega", "Snoep, koek en
# chocolade"), but it is a multi-value FACET list, not a single path - an
# own-brand tuna tin carries both "Vlees, vis en vega" and "ALDI merken" side by
# side. These generic, cross-cutting facets are skipped so the first genuinely
# departmental one is what gets used for both display and category exclusion.
_GENERIC_FACETS = {"ALDI merken", "Speciaal assortiment", "Winnaarsproducten"}


def _department(entry: dict) -> str | None:
    lvl0 = (entry.get("hierarchicalCategories") or {}).get("lvl0") or []
    return next((c for c in lvl0 if c not in _GENERIC_FACETS), None)


def _category_titles(categories: list[dict]) -> dict[str, str]:
    """`mainCategoryID` -> a human title, from the week's category groupings.

    Best-effort: falls back to the raw id in `_to_offer` when a category id
    from `algoliaDataMap` was not one of this week's listed groupings.
    """
    titles: dict[str, str] = {}
    for week in categories:
        for group in week.get("content") or []:
            for pid in group.get("productIds") or []:
                titles.setdefault(pid, group.get("title"))
    return titles


def _promo_text(current: dict) -> str | None:
    """Synthesise the Dutch phrase `parse_promo_text` already understands.

    Aldi expresses a discount structurally (`priceValue` vs `strikePrice`), not
    as a Dutch sentence like AH's `discountDescription` - so this adapter
    translates the structured fact into that shared mini-language rather than
    inventing a second, Aldi-only promo parser. `OP=OP` ("op is op", while
    stocks last) has no reference price at all and is genuinely
    `NOT_A_PROMO`-shaped: this week's price simply is this week's price.
    """
    strike = current.get("strikePrice")
    price = current.get("priceValue")
    if strike and price is not None:
        # Exact and lossless: the final price, not the rounded "-11%" label.
        return f"voor {price:.2f}".replace(".", ",")

    label = ((current.get("priceTagLabels") or {}).get("promoText1") or "").strip()
    if not label or label.upper() in ("OP=OP",):
        return "elke dag lage prijs"  # -> NOT_A_PROMO, matches the AH sentinel

    # "VANAF" (tiered/variable pricing, e.g. plants) has no single number to
    # trust - left as the raw label so it queues for review, not guessed at.
    return label


def _from_unix(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value)).date()
    except (TypeError, ValueError, OSError):
        log.warning("aldi: unparseable timestamp %r", value)
        return None


# Scene7 serves any size from the same url. 400px matches the AH rendition:
# a 64dp thumbnail at 3x and the detail screen, one request.
IMAGE_WIDTH = 400


def _image(entry: dict) -> str | None:
    """The primary product shot from `assets`, sized for the app."""
    for asset in entry.get("assets") or []:
        if asset.get("type") == "primary" and asset.get("url"):
            return f"{asset['url']}?wid={IMAGE_WIDTH}&hei={IMAGE_WIDTH}"
    return None
