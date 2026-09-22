"""Jumbo adapter.

Endpoint state verified 2026-09-17, superseding CLAUDE.md's 2026-09-16 finding
that Jumbo was blocked. It was not bot-protection: the mobile API the brief
names (`mobileapi.jumbo.com/promotion-overview`) is simply dead (404 on every
path tried), because Jumbo has since moved onto a public web app at
`www.jumbo.com` built on Nuxt. Two things matter here:

  1. **The full weekly listing is server-rendered, not fetched by XHR.** The
     public `/aanbiedingen` page embeds it in a `<script id="__NUXT_DATA__">`
     tag, encoded with the documented `devalue` format (see
     `parsers/devalue.py`). A plain, cookieless GET of that page - no browser,
     no session - returns all ~150 weekly promotions. Akamai cookies are present
     (`bm_mi`, `bm_sv`, ...) but do not block this: they ride along on every
     response and never challenge a plain HTTP client here.
  2. **A separate GraphQL lane exists** (`/api/graphql`, persisted queries) and
     answers with a 400/401 CSRF-style rejection unless the request carries
     `apollo-require-preflight` and `apollographql-client-name` headers - a
     standard Apollo Server safeguard against form-based CSRF, not bot
     detection, and trivially satisfied. It only surfaces the four-item
     "GetHomeScreenOffers" spotlight though, not the full listing, so the
     adapter does not use it.

Some promotions cover one SKU ("Bak 300 gram"); others cover a whole product
line on the same deal ("Alle sets met 6 pakjes à 200 ml", "M.u.v. kuipjes à
200 gram") - AH's segment problem. Unlike AH, Jumbo's listing never expands
these itself: `fetch_promotions()`'s own nodes always carry `products: []`. But
the SAME offer detail page used for a single-SKU promotion's price also carries
a `Promotion` node with a real `products` list when the deal covers more than
one - discovered 2026-09-17 by fetching a multi-variant promotion's own detail
page directly. `expand_offer()` uses that: a genuine per-SKU expansion, the
same shape and cost as AH's `fetch_segment`, just reached through the page
already being fetched for pricing rather than a separate endpoint.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any
from urllib.parse import quote

from ..http import PoliteClient
from ..models import RawOffer, RawProduct
from ..parsers.devalue import extract_nuxt_data, find_all, find_by_typename, resolve, unwrap
from ..rawstore import RawStore
from .base import register

log = logging.getLogger(__name__)

BASE_URL = "https://www.jumbo.com"
OFFERS_PAGE = f"{BASE_URL}/aanbiedingen"
SEARCH_PAGE = f"{BASE_URL}/producten/"

# Milestone 15/16, verified live 2026-09-22. `/producten/` server-renders the
# whole assortment through the same `__NUXT_DATA__` lane `/aanbiedingen` uses -
# 17,063 products, `count` on the product store says so - and pages on an
# `offSet` query parameter.
CATALOGUE_PAGE = f"{BASE_URL}/producten/"

# Fixed by the site. `pageSize` is accepted and ignored: `?offSet=0&pageSize=100`
# returns 24 products, same as without it. So the assortment costs ~712 requests
# to walk, against AH's 299 for nearly three times as many products.
CATALOGUE_PAGE_SIZE = 24

# Jumbo has no paging ceiling - `?offSet=17000` answers normally where AH's own
# lane returns HTTP 400 past offset 3000. So the whole assortment is one flat
# list and the category descent `catalogue.py` needs for AH never fires here.
CATALOGUE_MAX_OFFSET = None

# Jumbo publishes one rendition per product, at 360px.
CATALOGUE_IMAGE_WIDTH = 360


@register
class JumboAdapter:
    chain = "jumbo"

    # On the CLASS: `catalogue.crawl` reads these with getattr(adapter, ...),
    # so a module-level constant never reaches it. See the same note in ah.py.
    CATALOGUE_PAGE_SIZE = CATALOGUE_PAGE_SIZE
    CATALOGUE_MAX_OFFSET = CATALOGUE_MAX_OFFSET

    def __init__(self, client: PoliteClient | None = None, store: RawStore | None = None) -> None:
        self._client = client or PoliteClient(self.chain, base_url=BASE_URL)
        self._store = store or RawStore()

    def _get_resolved(self, url: str) -> Any:
        """Fetch a page, persist its raw `__NUXT_DATA__` array, resolve it.

        The devalue ARRAY is what gets persisted, not the surrounding HTML -
        that array is the actual payload; the HTML around it is presentation.
        Persisting it as JSON keeps `data/raw/` consistent with every other
        chain (CLAUDE.md section 1: raw before parsed).
        """
        html = self._client.request_text("GET", url)
        raw_text = extract_nuxt_data(html)
        import json

        arr = json.loads(raw_text)
        self._store.save(self.chain, url, arr)
        return unwrap(resolve(arr, 0))

    # -- listing -------------------------------------------------------------

    def fetch_promotions(self) -> list[RawOffer]:
        """Every currently-listed Jumbo promotion, de-duplicated on id.

        The "Nu in de aanbieding" section repeats a highlight subset of what
        "Per gangpad" lists by category - the same double-listing shape AH's
        SPOTLIGHT section has, and dedup follows the same rule (first sighting,
        by id, wins).
        """
        root = self._get_resolved(OFFERS_PAGE)
        sections = find_all(root, "sections")
        # `sections` nests once per intermediate reactive wrapper; flatten to
        # the actual list of section dicts regardless of how deep that is.
        flat_sections: list[dict] = []
        for s in sections:
            s = unwrap(s)
            if isinstance(s, list):
                flat_sections.extend(unwrap(x) for x in s)
            elif isinstance(s, dict):
                flat_sections.append(s)

        offers: dict[str, RawOffer] = {}
        for section in flat_sections:
            for node, category in _promotions_in(section):
                offer = self._to_offer(node, category=category)
                offers.setdefault(offer.offer_id, offer)
        return list(offers.values())

    def _to_offer(self, node: dict, *, category: str | None) -> RawOffer:
        tags = unwrap(node.get("tags") or [])
        tag_text = next(
            (unwrap(t).get("text") for t in tags if unwrap(t).get("text")), None
        )
        start = unwrap(node.get("start") or {})
        end = unwrap(node.get("end") or {})
        return RawOffer(
            chain=self.chain,
            offer_id=str(node["id"]),
            title=node.get("title") or "",
            subtitle=_single_sku_subtitle(node.get("subtitle")),
            category=category,
            promo_raw_text=tag_text,
            valid_from=_as_date(start.get("iso")),
            valid_to=_as_date(end.get("iso")),
            # Jumbo's own promotion listing carries no personal/loyalty flag at
            # this level - `massOffers`/`birthdayOffers` from the GraphQL
            # spotlight lane are the personal ones, and this adapter does not
            # use that lane, so nothing here is ever personal by construction.
            is_personal=False,
            product_skus=[str(node["id"])],
            source_url=OFFERS_PAGE,
            raw_path=str(self._store.path_for(self.chain, OFFERS_PAGE)),
            raw=node,
        )

    # -- search, for the base price catalogue (prices.py) --------------------

    def search_products(self, query: str, *, size: int = 10) -> list[RawProduct]:
        """Search the whole catalogue, not just this week's promotions.

        `www.jumbo.com/producten/?searchType=keyword&searchTerms=` is server-
        rendered the same way the offers page is - discovered 2026-09-17 by
        watching the network tab while typing into the site's own search box
        and submitting it (the client-side `SearchSuggestions` GraphQL call
        fires on every keystroke but only ever returns autocomplete text, never
        products; the real results come from re-rendering this page). A plain,
        cookieless GET returns them - no session, no browser needed at runtime.

        Result cards omit `sku`/`title` for a few slots (ads or category
        tiles mixed into the results) - skipped rather than guessed at.
        """
        url = f"{SEARCH_PAGE}?searchType=keyword&searchTerms={quote(query)}"
        root = self._get_resolved(url)
        products = [
            p for p in find_by_typename(root, "Product")
            if p.get("sku") and p.get("title") and not p.get("retailSet")
        ]
        return [self._map_product(p, url) for p in products[:size]]

    # -- product level ---------------------------------------------------

    def fetch_product(self, sku: str) -> RawProduct:
        """One promotion's own detail page, single-SKU case.

        `sku` is the promotion id from `fetch_promotions`. Jumbo's page router
        resolves that id alone at `/aanbiedingen/-/{id}` with no slug needed
        (verified 2026-09-17). Required by the `StoreAdapter` protocol;
        `ingest_flat` prefers `expand_offer` when it is available, which is
        always, so this exists for direct single-SKU lookups and as the
        fallback `expand_offer` itself uses when a detail page's `Promotion`
        node carries no `products` list at all.
        """
        product = self._fetch_single_product(sku)
        url = f"{BASE_URL}/aanbiedingen/-/{sku}"
        if product is None:
            return RawProduct(chain=self.chain, sku=sku, name="", source_url=url,
                              raw_path=str(self._store.path_for(self.chain, url)))
        return self._map_product(product, url)

    def _fetch_single_product(self, offer_id: str) -> dict | None:
        url = f"{BASE_URL}/aanbiedingen/-/{offer_id}"
        root = self._get_resolved(url)
        products = find_by_typename(root, "Product")
        return next((p for p in products if not p.get("retailSet")), None)

    def expand_offer(self, offer: RawOffer) -> list[RawProduct]:
        """Every real SKU a promotion covers, priced.

        The detail page for a "one deal, several products" promotion carries a
        `Promotion` node whose own `products` field - always empty on the
        listing page - is filled in here. The same page can carry more than one
        `Promotion` node sharing the same id (a "similar deals" widget appears
        to reuse it); the one with the most products wins, never one merged
        from several, since these are alternate copies, not adjacent data.

        Falls back to the single-product page (`fetch_product`'s own lookup)
        when nothing expands - the ordinary case, most promotions are one SKU.
        """
        url = f"{BASE_URL}/aanbiedingen/-/{offer.offer_id}"
        root = self._get_resolved(url)
        promotions = find_by_typename(root, "Promotion")
        best = max(
            (unwrap(p) for p in promotions), key=lambda p: len(unwrap(p.get("products") or [])),
            default=None,
        )
        products = unwrap(best.get("products") or []) if best else []
        if not products:
            single = next((p for p in find_by_typename(root, "Product") if not p.get("retailSet")), None)
            return [self._map_product(single, url)] if single else []
        return [self._map_product(unwrap(p), url) for p in products]

    # -- catalogue (milestone 16) --------------------------------------------

    def category_tree(self) -> list[dict]:
        """One node: the whole assortment.

        AH needs a real tree because its search lane refuses offsets past 3000
        and four of its categories are bigger than that. Jumbo answers at
        offset 17,000, so there is nothing to work around - splitting the crawl
        by category here would cost the same requests and add a way to miss a
        product that sits in no tile.
        """
        return [{"id": "", "name": "hele assortiment"}]

    def category_children(self, taxonomy_id) -> list[dict]:
        return []

    def category_size(self, taxonomy_id) -> int:
        return self._product_store(CATALOGUE_PAGE)[1]

    def browse_category(self, taxonomy_id, *, page: int = 0,
                        size: int = CATALOGUE_PAGE_SIZE) -> list[RawProduct]:
        url = f"{CATALOGUE_PAGE}?offSet={page * size}"
        products, _ = self._product_store(url)
        return [self._map_product(unwrap(p), url) for p in products]

    def _product_store(self, url: str) -> tuple[list, int]:
        """The `productStore` Pinia state: this page's products and the total.

        Values arrive wrapped as `["Ref", x]` / `["Reactive", [...]]` because
        Nuxt serialises Pinia's reactivity along with the data. `unwrap`
        already handles that for the offers lane.
        """
        payload = self._get_resolved(url)
        store = ((payload or {}).get("pinia") or [None, {}])[1].get("productStore") or {}
        products = unwrap(store.get("products")) or []
        # Past the last offset the store answers `count = ["EmptyRef", "0"]`
        # rather than a number, which `unwrap` now decodes to 0. Coerced
        # defensively anyway: a page shape that changes again should give an
        # empty page rather than end the crawl 18 pages from the finish, which
        # is exactly what happened once.
        count = unwrap(store.get("count"))
        return list(products), int(count) if isinstance(count, (int, float)) else 0

    def _map_product(self, product: dict, url: str) -> RawProduct:
        """A `__typename: "Product"` node -> `RawProduct`.

        `sku` prefers the product's own internal code (e.g. "774264DS") over
        the promotion id - real and stable, unlike the shared promotion id every
        variant in an expanded segment would otherwise collide on.

        No nutrition was found on this page or `/producten/...` (unlike AH's
        FIR endpoint), and no dedicated unit-size field either. The product's
        own `title` reliably ends with its pack size ("... 6 x 200 ml",
        "Jumbo Blauwe Bessen 300 g") and `parse_unit_size` already tolerates
        the leading noise, so it is used directly here rather than left `None`
        for a caller to patch up - `search_products` results in particular have
        no promotion or offer subtitle to fall back to at all.
        """
        price = unwrap(product.get("price") or {})
        per_unit = unwrap(price.get("pricePerUnit") or {})
        sku = str(product.get("sku") or product.get("id") or "")
        title = product.get("title") or ""

        return RawProduct(
            chain=self.chain,
            sku=sku,
            name=title,
            brand=product.get("brand"),
            raw_unit_text=title or None,
            shelf_price=_cents_to_eur(price.get("price")),
            bonus_price=_cents_to_eur(price.get("promoPrice")),
            stated_unit_price_text=(
                f"per {per_unit['unit']} {per_unit['price'] / 100:.2f}"
                if per_unit.get("unit") and per_unit.get("price") is not None
                else None
            ),
            category=product.get("category"),
            # Jumbo's product node carries only the top-level department, so
            # `subcategory` stays NULL here rather than being invented from the
            # crawl's own position - which, walking a flat list, is nothing.
            image_url=product.get("image"),
            image_width=CATALOGUE_IMAGE_WIDTH if product.get("image") else None,
            url=product.get("link"),
            source_url=url,
            raw_path=str(self._store.path_for(self.chain, url)),
            raw=product,
        )


# `expand_offer` now resolves the *real* per-SKU data for a multi-variant
# promotion, so this text is no longer load-bearing for those - it only guards
# the narrower remaining case where `expand_offer` falls back to a single
# product (no `products` list found at all) but that product's own page still
# carries the segment-level "Alle sets..." subtitle as its listing subtitle.
# Left in defensively rather than removed: a subtitle like this was never a
# single SKU's own pack size, and feeding it to `parse_unit_size` produced
# unit-price cross-check "mismatches" north of 100% before expansion existed
# (measured 2026-09-17) - a category error, not a parser bug.
_MULTI_SKU_SUBTITLE = re.compile(r"\b(alle|m\.u\.v\.?|excl\.?)\b", re.I)


def _single_sku_subtitle(subtitle: str | None) -> str | None:
    if subtitle and _MULTI_SKU_SUBTITLE.search(subtitle):
        return None
    return subtitle


def _promotions_in(section: dict):
    """Yield (promotion_dict, category_title) for a section's own list and
    every one of its categories, in the shape `fetch_promotions` needs."""
    for node in unwrap(section.get("promotions") or []):
        yield unwrap(node), section.get("title")
    for category in unwrap(section.get("categories") or []):
        category = unwrap(category)
        for node in unwrap(category.get("promotions") or []):
            yield unwrap(node), category.get("title")


def _as_date(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        log.warning("jumbo: unparseable date %r", iso)
        return None


def _cents_to_eur(cents: Any) -> float | None:
    if cents is None:
        return None
    try:
        return round(float(cents) / 100.0, 2)
    except (TypeError, ValueError):
        return None
