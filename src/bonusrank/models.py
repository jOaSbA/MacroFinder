"""Raw, pre-normalisation models.

Deliberately dumb. These carry what a chain published, in the shape the chain
published it, plus the few fields every chain must supply for the pipeline to
function at all. No unit parsing, no promo-mechanic parsing, no macro lookup -
that is milestone 2 and later, and it happens against the persisted snapshots,
not against the network.

Two fields exist because CLAUDE.md sections 1 and 2 require them downstream:
`promo_raw_text` (always store the raw promo text alongside any parsed enum) and
`is_personal` (personal offers must never enter headline rankings silently).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawOffer(BaseModel):
    """One promotion as a chain publishes it.

    For AH this is a *segment* ("Alle Melkunie Breaker"), which may cover several
    SKUs; `product_skus` is empty until the segment is expanded. Do not assume one
    offer means one product.
    """

    model_config = ConfigDict(frozen=True)

    chain: str
    offer_id: str
    title: str

    group_id: str | None = None
    subtitle: str | None = None
    category: str | None = None

    # Raw promo text, always retained. Parsing happens in milestone 2.
    promo_raw_text: str | None = None
    # Chain-supplied typed mechanic, when there is one. AH: discountLabels[].
    promo_labels: list[dict[str, Any]] = Field(default_factory=list)

    valid_from: date | None = None
    valid_to: date | None = None

    promotion_type: str | None = None
    shop_type: str | None = None
    is_personal: bool = False
    store_only: bool = False
    is_future: bool = False

    # SKUs already inline in this payload. Empty means "not expanded yet".
    product_skus: list[str] = Field(default_factory=list)

    source_url: str | None = None
    raw_path: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


class RawProduct(BaseModel):
    """One SKU as a chain publishes it. Unit text stays unparsed on purpose."""

    model_config = ConfigDict(frozen=True)

    chain: str
    sku: str
    name: str

    brand: str | None = None
    raw_unit_text: str | None = None
    ean: str | None = None
    category: str | None = None

    shelf_price: float | None = None
    bonus_price: float | None = None
    # Chain-published unit price, e.g. "prijs per kilo 6.49". CLAUDE.md section 1
    # requires cross-checking this against the computed unit price on ingest.
    stated_unit_price_text: str | None = None

    url: str | None = None
    source_url: str | None = None
    raw_path: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)
