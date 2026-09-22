"""Albert Heijn adapter.

Endpoint state verified 2026-09-16; see CLAUDE.md section 4 for the drift against
the brief. The two things that matter here:

  1. The listing lane is two-level. `bonuspage/v3/metadata` hands out section URLs;
     each section returns `bonusGroup` objects (a *segment*, one promotion covering
     possibly several SKUs) with `products` EMPTY. Expanding a segment into SKUs is
     a separate call, `bonuspage/v2/segment?segmentId=`, and is not part of
     milestone 1.
  2. Section URLs are never hardcoded. They come from metadata, they carry the
     period date, and they change weekly.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable
from urllib.parse import quote

from ..http import PoliteClient
from ..models import RawOffer, RawProduct
from ..rawstore import RawStore
from .base import register

log = logging.getLogger(__name__)

API_ROOT = "https://api.ah.nl"
MOBILE_SERVICES = f"{API_ROOT}/mobile-services"
AUTH_URL = f"{API_ROOT}/mobile-auth/v1/auth/token/anonymous"
METADATA_URL = f"{MOBILE_SERVICES}/bonuspage/v3/metadata"
SEGMENT_URL = f"{MOBILE_SERVICES}/bonuspage/v2/segment"
PRODUCT_DETAIL_URL = f"{MOBILE_SERVICES}/product/detail/v4/fir"
PRODUCT_SEARCH_URL = f"{MOBILE_SERVICES}/product/search/v2"

# Milestone 15, verified live 2026-09-22. Note the version sits BEFORE the path
# here, unlike every other lane in this file - `mobile-services/v1/product-
# shelves/...`, not `mobile-services/product-shelves/v1/...`. Both of the
# obvious spellings return 404, which costs an afternoon to find out.
CATEGORIES_URL = f"{MOBILE_SERVICES}/v1/product-shelves/categories"

# The same search lane the food-type price sweep uses, filtered by taxonomy and
# with an empty query. 28 top-level categories, 43,038 products, measured
# 2026-09-22.
#
# Two limits found by probing, neither documented:
#
#   * `size=200` returns 203 items. The three extras are sponsored/injected
#     cards and carry the same shape, so they are kept and deduped on sku
#     rather than trimmed - dropping the tail of a page by count would throw
#     away real products.
#   * **`page * size >= 3000` returns HTTP 400.** Not an empty page - a hard
#     error. Four top-level categories are larger than that (Drogisterij 3531,
#     Soepen/sauzen 3358, Bier/wijn 3075, Koek/snoep 2856 is close), so a
#     top-level-only crawl silently loses their tails. `catalogue.py` descends
#     into sub-categories whenever a node is too big to page through, which
#     also keeps the crawl correct as the assortment grows.
CATALOGUE_PAGE_SIZE = 200
CATALOGUE_MAX_OFFSET = 3000

# The rendition to store. A 64dp list thumbnail is ~200px at 3x and the detail
# screen wants more, so 400 is the one size that serves both without a second
# request. Falls back to the largest available when a product has no 400.
PREFERRED_IMAGE_WIDTH = 400

# Required as a HEADER on the product lanes. Without it product/detail/v4/fir and
# product/search/v2 return HTTP 500 ("Can not find application: 'null'") even with
# a valid token - verified 2026-09-16. The bonuspage lanes take it as a query
# parameter instead; metadata already embeds that in the section URLs it hands out.
AH_APPLICATION = "AHWEBSHOP"

# Anonymous auth only ever yields universal offers; a member session would be
# needed for AH Extra's / Bonusbox. Kept as a set so the flag has one owner.
_PERSONAL_PROMOTION_TYPES = {"PERSONAL", "BONUSBOX", "EXTRAS"}


@register
class AHAdapter:
    chain = "ah"

    # Declared on the CLASS, not just at module level. `catalogue.crawl` reads
    # them with getattr(adapter, ...), so a module-level constant is invisible
    # to it and the crawl silently falls back to its own defaults. That went
    # unnoticed here because AH's real values happen to equal those defaults;
    # it was Jumbo, which needs different ones, that exposed it.
    CATALOGUE_PAGE_SIZE = CATALOGUE_PAGE_SIZE
    CATALOGUE_MAX_OFFSET = CATALOGUE_MAX_OFFSET

    def __init__(self, client: PoliteClient | None = None, store: RawStore | None = None) -> None:
        self._client = client or PoliteClient(self.chain, base_url=API_ROOT)
        self._store = store or RawStore()
        self._token: str | None = None

    # -- auth ----------------------------------------------------------------

    @property
    def token(self) -> str:
        if self._token is None:
            payload = self._client.post_json(AUTH_URL, json_body={"clientId": "appie"})
            self._token = payload["access_token"]
            log.debug("anonymous token acquired, expires_in=%s", payload.get("expires_in"))
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Application": AH_APPLICATION}

    def _get(self, url: str) -> Any:
        """Fetch, persist the raw payload, then return it. Never the other way round."""
        payload = self._client.get_json(url, headers=self._auth_headers())
        self._store.save(self.chain, url, payload)
        return payload

    # -- listing -------------------------------------------------------------

    def fetch_metadata(self) -> dict[str, Any]:
        return self._get(METADATA_URL)

    def section_urls(self, metadata: dict[str, Any]) -> list[str]:
        """Every section URL across every period and tab, de-duplicated.

        The SPOTLIGHT section is listed under both the 'Uitgelicht' and 'Alle Bonus'
        tabs, so this de-duplicates while preserving order.
        """
        seen: dict[str, None] = {}
        for period in metadata.get("periods", []):
            for tab in period.get("tabs", []):
                for entry in tab.get("urlMetadataList", []):
                    url = entry.get("url")
                    if url:
                        seen.setdefault(f"{MOBILE_SERVICES}/{url.lstrip('/')}", None)
        return list(seen)

    def fetch_promotions(self) -> list[RawOffer]:
        """Every currently-listed AH promotion, de-duplicated on offer id."""
        metadata = self.fetch_metadata()
        urls = self.section_urls(metadata)
        log.info("ah: %d sections to fetch", len(urls))

        offers: dict[str, RawOffer] = {}
        for url in urls:
            payload = self._get(url)
            raw_path = str(self._store.path_for(self.chain, url))
            for offer in self._parse_section(payload, source_url=url, raw_path=raw_path):
                # Same segment appears in several sections; first sighting wins.
                offers.setdefault(offer.offer_id, offer)
        return list(offers.values())

    def _parse_section(self, payload: dict[str, Any], *, source_url: str, raw_path: str) -> Iterable[RawOffer]:
        for item in payload.get("bonusGroupOrProducts") or []:
            # The key name is a union: a section entry is either a bonus group
            # (a segment) or a bare product. Only bonusGroup seen in the wild so far.
            node = item.get("bonusGroup") or item.get("product")
            if not node:
                log.warning("ah: unrecognised section entry keys=%s", sorted(item))
                continue
            yield self._to_offer(node, source_url=source_url, raw_path=raw_path)

    def _to_offer(self, node: dict[str, Any], *, source_url: str, raw_path: str) -> RawOffer:
        validity = node.get("validityPeriod") or {}
        promotion_type = node.get("promotionType")
        offer_id = str(node.get("offerId") or node.get("segmentId") or node.get("id"))

        return RawOffer(
            chain=self.chain,
            offer_id=offer_id,
            group_id=str(node["segmentId"]) if node.get("segmentId") is not None else None,
            title=node.get("segmentDescription") or node.get("title") or "",
            subtitle=node.get("subtitle"),
            category=node.get("category"),
            promo_raw_text=node.get("discountDescription"),
            promo_labels=node.get("discountLabels") or [],
            valid_from=_as_date(validity.get("start") or node.get("bonusStartDate")),
            valid_to=_as_date(validity.get("end") or node.get("bonusEndDate")),
            promotion_type=promotion_type,
            shop_type=node.get("shopType"),
            is_personal=(promotion_type or "").upper() in _PERSONAL_PROMOTION_TYPES,
            store_only=bool(node.get("storeOnlyPromotion")),
            is_future=bool(node.get("future")),
            product_skus=[str(p["webshopId"]) for p in node.get("products") or [] if p.get("webshopId")],
            source_url=source_url,
            raw_path=raw_path,
            raw=node,
        )

    # -- SKU level -----------------------------------------------------------
    # Required by the StoreAdapter protocol. Not exercised by milestone 1.

    def fetch_segment(self, segment_id: str) -> dict[str, Any]:
        """Expand a segment into its SKUs. Milestone 3 (ingest) uses this."""
        return self._get(f"{SEGMENT_URL}?segmentId={segment_id}")

    def fetch_product(self, sku: str) -> RawProduct:
        """One SKU with its FIR (EU 1169/2011) nutrition declaration.

        `sku` is the AH webshopId. Note the brief's gotcha: AH product ids appear
        elsewhere as `wi`-prefixed strings - do not cast them to int.
        """
        url = f"{PRODUCT_DETAIL_URL}/{sku}"
        payload = self._get(url)
        card = payload.get("productCard") or payload
        trade_item = payload.get("tradeItem") or {}
        return RawProduct(
            chain=self.chain,
            sku=str(sku),
            name=card.get("title") or card.get("description") or "",
            brand=card.get("brand"),
            raw_unit_text=card.get("salesUnitSize") or card.get("unitSize"),
            ean=trade_item.get("gtin") or card.get("gtin") or card.get("ean"),
            category=card.get("mainCategory"),
            shelf_price=_as_float(card.get("priceBeforeBonus") or card.get("price")),
            bonus_price=_as_float(card.get("currentPrice")) if card.get("isBonus") else None,
            stated_unit_price_text=card.get("unitPriceDescription"),
            url=card.get("link") or card.get("url"),
            source_url=url,
            raw_path=str(self._store.path_for(self.chain, url)),
            raw=payload,
        )

    def search_products(self, query: str, *, size: int = 10) -> list[RawProduct]:
        """Search the catalogue by name, for prices outside the bonus folder.

        The ranking only ever needed prices for SKUs that appeared in a promo.
        Pricing a DIY composition needs a price for every food type in it, in
        every week - so this is the lane that gives a food type a price when it
        is not on offer.

        Takes `query` as a query parameter but `X-Application` as a HEADER;
        `_auth_headers` already sends it. Without that header this returns HTTP
        500 and looks exactly like an outage (CLAUDE.md section 4).
        """
        url = f"{PRODUCT_SEARCH_URL}?query={quote(query)}&size={size}"
        payload = self._get(url)
        cards = payload.get("products") or payload.get("cards") or []
        return [self._to_product(card, source_url=url) for card in cards if card]

    # -- catalogue (milestone 15) --------------------------------------------

    def category_tree(self) -> list[dict[str, Any]]:
        """The top-level shelf categories, each with its own children.

        Three levels deep in practice. Only as much of it as the crawl needs is
        walked: `catalogue.py` asks for children when a node turns out to be
        too big to page through, and not otherwise.
        """
        return list(self._get(CATEGORIES_URL) or [])

    def category_children(self, taxonomy_id: int | str) -> list[dict[str, Any]]:
        payload = self._get(f"{CATEGORIES_URL}/{taxonomy_id}/sub-categories")
        return list((payload or {}).get("children") or [])

    def category_size(self, taxonomy_id: int | str) -> int:
        """How many products a category holds, including its whole subtree."""
        payload = self._get(f"{PRODUCT_SEARCH_URL}?query=&taxonomyId={taxonomy_id}&size=1")
        return int(((payload or {}).get("page") or {}).get("totalElements") or 0)

    def browse_category(self, taxonomy_id: int | str, *, page: int = 0,
                        size: int = CATALOGUE_PAGE_SIZE) -> list[RawProduct]:
        """One page of a category, as full products rather than offers.

        Same endpoint as `search_products`, with an empty query and a taxonomy
        filter - so the cross-check, unit parsing and matching downstream see
        exactly the shape they already handle.
        """
        url = (f"{PRODUCT_SEARCH_URL}?query=&taxonomyId={taxonomy_id}"
               f"&size={size}&page={page}")
        payload = self._get(url)
        cards = (payload or {}).get("products") or []
        return [self._to_product(card, source_url=url) for card in cards if card]

    def _to_product(self, card: dict[str, Any], *, source_url: str) -> RawProduct:
        """Map a search-result card. Detail responses nest one; search lists them."""
        price = card.get("price") or {}
        # Search cards carry price either flat or under a `price` object,
        # depending on the lane. Neither shape is documented; accept both.
        shelf = _as_float(
            card.get("priceBeforeBonus")
            or price.get("was")
            or price.get("now")
            or card.get("currentPrice")
        )
        bonus = _as_float(price.get("now") or card.get("currentPrice")) if (
            card.get("isBonus") or price.get("was")
        ) else None
        return RawProduct(
            chain=self.chain,
            sku=str(card.get("webshopId") or card.get("id") or ""),
            name=card.get("title") or card.get("description") or "",
            brand=card.get("brand"),
            raw_unit_text=card.get("salesUnitSize") or card.get("unitSize"),
            ean=card.get("gtin") or card.get("ean"),
            category=card.get("mainCategory"),
            subcategory=card.get("subCategory"),
            **_image(card.get("images")),
            shelf_price=shelf,
            bonus_price=bonus,
            stated_unit_price_text=card.get("unitPriceDescription"),
            url=card.get("link") or card.get("url"),
            source_url=source_url,
            raw_path=str(self._store.path_for(self.chain, source_url)),
            raw=card,
        )

    def fetch_macros(self, sku: str):
        """Label macros for one SKU, straight from the GS1 nutrition block."""
        from ..parsers import parse_gs1_nutrition

        payload = self._get(f"{PRODUCT_DETAIL_URL}/{sku}")
        return parse_gs1_nutrition((payload.get("tradeItem") or {}).get("nutritionalInformation"))


def _image(images: Any) -> dict[str, Any]:
    """Pick one rendition from AH's own list, and say how wide it is.

    PLAN-V2 section 3.3: store the chain's url, never the bytes and never a
    proxy. Storing the width alongside means the app never has to parse a
    `rendition=400x400_WEBP` query string it does not own to find out what it
    is about to download.
    """
    candidates = [i for i in (images or []) if i.get("url") and i.get("width")]
    if not candidates:
        return {"image_url": None, "image_width": None}
    exact = [i for i in candidates if i["width"] == PREFERRED_IMAGE_WIDTH]
    chosen = exact[0] if exact else max(candidates, key=lambda i: i["width"])
    return {"image_url": chosen["url"], "image_width": int(chosen["width"])}


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        log.warning("ah: unparseable date %r", value)
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # Dutch decimal commas turn up in price strings (CLAUDE.md section 1).
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None
