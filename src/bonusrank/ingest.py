"""Adapter output -> SQLite. Brief milestone 3.

Every SKU goes through the same pipeline: parse the unit size, parse the promo
mechanic, cross-check our unit price against the store's, match a food_type,
then append a price observation. Nothing is ever updated in place.

Anything that cannot be determined is written to `needs_review` rather than
guessed. That is the whole reason the review queue exists, and it is why this
module has no fallback values anywhere in it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .matcher import MatchMethod, Matcher, MatchResult
from .parsers import (
    compare_unit_price,
    parse_ah_label,
    parse_promo_text,
    parse_stated_unit_price,
    parse_unit_size,
)
from .parsers.promos import PromoKind

log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    segments: int = 0
    products: int = 0
    observations: int = 0
    matched: int = 0
    unmatched: int = 0
    excluded: int = 0
    promo_unparsed: int = 0
    unit_size_unparsed: int = 0
    unit_price_mismatch: int = 0
    reviews: dict[str, int] = field(default_factory=dict)

    def review(self, kind: str) -> None:
        self.reviews[kind] = self.reviews.get(kind, 0) + 1


def ingest_ah(
    conn: sqlite3.Connection,
    adapter,
    *,
    matcher: Matcher | None = None,
    limit: int | None = None,
) -> IngestStats:
    """Fetch every AH promotion, expand it to SKUs, and record observations."""
    matcher = matcher or Matcher.from_db(conn)
    stats = IngestStats()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    offers = adapter.fetch_promotions()
    if limit:
        offers = offers[:limit]

    for offer in offers:
        promo = (
            parse_ah_label(offer.promo_labels[0], headline=offer.promo_raw_text)
            if offer.promo_labels
            else parse_promo_text(offer.promo_raw_text)
        )
        if promo.needs_review:
            stats.promo_unparsed += 1
            stats.review("unparsed_promo")
            _review(conn, "unparsed_promo", f"ah:offer:{offer.offer_id}",
                    {"title": offer.title, "raw": offer.promo_raw_text,
                     "labels": offer.promo_labels}, now)

        if not offer.group_id:
            continue
        segment = adapter.fetch_segment(offer.group_id)
        stats.segments += 1

        for product in segment.get("products") or []:
            _ingest_product(conn, product, offer, promo, matcher, stats, now)

    conn.commit()
    return stats


def _ingest_product(conn, product, offer, promo, matcher, stats, now) -> None:
    sku = str(product.get("webshopId") or "")
    if not sku:
        return
    category = offer.category or product.get("mainCategory")
    _ingest_sku(
        conn, chain="ah", sku=sku, name=product.get("title") or "",
        brand=product.get("brand"), raw_unit_text=product.get("salesUnitSize"),
        stated_unit_price_text=product.get("unitPriceDescription"),
        category=category, shelf_price=product.get("priceBeforeBonus"),
        bonus_price=product.get("currentPrice"), ean=None, promo=promo,
        is_personal=offer.is_personal, valid_from=offer.valid_from,
        valid_to=offer.valid_to, matcher=matcher, stats=stats, now=now,
    )


def _ingest_sku(
    conn, *, chain: str, sku: str, name: str, brand: str | None,
    raw_unit_text: str | None, stated_unit_price_text: str | None,
    category: str | None, shelf_price: float | None, bonus_price: float | None,
    ean: str | None, promo, is_personal: bool, valid_from, valid_to,
    matcher: Matcher, stats: IngestStats, now: str,
) -> None:
    """The chain-generic core of ingest: parse, cross-check, match, store.

    Every chain reaches this the same way once it has produced one SKU's worth
    of plain fields - AH via `_ingest_product` unpacking its segment dict,
    Jumbo/Aldi via `ingest_flat` unpacking a `RawOffer`/`RawProduct` pair. The
    logic itself (unit-size parse, the section-7 cross-check, category
    exclusion, matching, the append-only insert) does not know or care which.
    """
    size = parse_unit_size(raw_unit_text)
    if size.needs_review:
        stats.unit_size_unparsed += 1
        stats.review("unparsed_unit_size")
        _review(conn, "unparsed_unit_size", f"{chain}:{sku}",
                {"name": name, "raw": raw_unit_text}, now)

    # Brief section 7: compare against the store's own unit price on every ingest.
    check = compare_unit_price(
        parse_stated_unit_price(stated_unit_price_text),
        shelf_price=shelf_price, size=size, label=f"{name} [{sku}]",
    )
    if check.comparable and not check.within_tolerance:
        stats.unit_price_mismatch += 1
        stats.review("unit_price_mismatch")
        _review(conn, "unit_price_mismatch", f"{chain}:{sku}", {
            "name": name, "raw_unit_text": raw_unit_text,
            "computed_unit_price": round(check.computed, 4),
            "stated_unit_price": check.stated,
            "deviation_pct": round(check.deviation * 100, 1),
            "implied_mass_g": round(check.implied_quantity_g, 1) if check.implied_quantity_g else None,
            "implied_fraction_of_label": round(check.implied_fraction, 3) if check.implied_fraction else None,
            "note": "parser bug, or a drained/edible fraction the label omits - decide, do not auto-apply",
        }, now)

    # Whole categories are not rankable food. Checking the category beats
    # keyword-matching the title: the first full AH ingest put 2760 SKUs in the
    # review queue and the commonest words in it were spray, wasmiddel,
    # navulling, shampoo and spf50 - Etos and drogisterij, not seed gaps.
    if category and category in matcher.non_rankable_categories:
        match = MatchResult(None, MatchMethod.EXCLUDED, 0.0, False,
                            f"category {category!r} is not rankable food")
    else:
        match = matcher.match(name, brand=brand, chain=chain, sku=sku)

    if match.food_type_key:
        stats.matched += 1
    elif match.method is MatchMethod.EXCLUDED:
        stats.excluded += 1
    else:
        stats.unmatched += 1
        stats.review("unmatched_sku")
        _review(conn, "unmatched_sku", f"{chain}:{sku}",
                {"name": name, "brand": brand, "reason": match.reason,
                 "best_score": round(match.score, 3)}, now)

    food_type_id = None
    if match.food_type_key:
        row = conn.execute("SELECT id FROM food_types WHERE key=?", (match.food_type_key,)).fetchone()
        food_type_id = row[0] if row else None

    conn.execute(
        "INSERT INTO products (chain, sku, name, brand, raw_unit_text, unit_size_g, "
        "unit_size_ml, cost_basis_g, ean, category, food_type_id, match_method, "
        "match_score, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(chain, sku) DO UPDATE SET name=excluded.name, brand=excluded.brand, "
        "raw_unit_text=excluded.raw_unit_text, unit_size_g=excluded.unit_size_g, "
        "unit_size_ml=excluded.unit_size_ml, cost_basis_g=excluded.cost_basis_g, "
        "category=excluded.category, food_type_id=excluded.food_type_id, "
        "match_method=excluded.match_method, match_score=excluded.match_score",
        (chain, sku, name, brand, raw_unit_text, size.total_g,
         size.total_ml, size.cost_basis_g, ean, category, food_type_id,
         match.method.value, match.score, now),
    )
    product_id = conn.execute(
        "SELECT id FROM products WHERE chain=? AND sku=?", (chain, sku)
    ).fetchone()[0]
    stats.products += 1

    effective = promo.effective_unit_price(shelf_price=shelf_price, unit_size_g=size.total_g)

    # Append-only: a repeat run on the same day is a no-op, never an overwrite.
    cursor = conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, bonus_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_from, valid_to) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (product_id, observed_at, promo_raw_text) DO NOTHING",
        (product_id, now[:10], shelf_price, bonus_price, promo.kind.value,
         promo.raw_text, promo.required_quantity, effective,
         int(is_personal or promo.is_personal),
         valid_from.isoformat() if valid_from else None,
         valid_to.isoformat() if valid_to else None),
    )
    stats.observations += cursor.rowcount if cursor.rowcount > 0 else 0


def ingest_flat(
    conn: sqlite3.Connection,
    adapter,
    *,
    matcher: Matcher | None = None,
    limit: int | None = None,
) -> IngestStats:
    """Ingest a chain via the generic `StoreAdapter` protocol, no segment hacks.

    AH's `ingest_ah` unpacks its own raw segment dicts directly, never going
    through `RawProduct` - a chain-specific shortcut this path does not take.
    Two shapes of adapter are supported, both reached the same way:

      - **`expand_offer(offer) -> list[RawProduct]`**, when present, is a real
        per-SKU expansion - Jumbo's equivalent of AH's segment model, reached
        through the same offer-detail page already fetched for pricing rather
        than a separate endpoint (`adapters/jumbo.py`). Preferred whenever it
        exists, because it is strictly more capable: it is what turns "Alle
        sets met 6 pakjes à 200 ml" from one unpriceable line into 7 real,
        separately-priced SKUs.
      - Otherwise, `offer.product_skus` (already one real SKU per offer, e.g.
        Aldi) is walked with `fetch_product` per SKU - the plain protocol path.

    Either way, a chain shaped like this needs no ingest code of its own -
    only its own adapter module, per CLAUDE.md section 1.
    """
    matcher = matcher or Matcher.from_db(conn)
    stats = IngestStats()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    offers = adapter.fetch_promotions()
    if limit:
        offers = offers[:limit]

    for offer in offers:
        try:
            if hasattr(adapter, "expand_offer"):
                products = adapter.expand_offer(offer)
            else:
                products = [adapter.fetch_product(sku)
                           for sku in (offer.product_skus or [offer.offer_id])]
        except Exception as exc:  # one bad offer must not abort the whole run
            log.warning("%s: expanding offer %s failed: %s", adapter.chain, offer.offer_id, exc)
            continue

        promo = parse_promo_text(offer.promo_raw_text)
        if promo.needs_review:
            stats.promo_unparsed += 1
            stats.review("unparsed_promo")
            _review(conn, "unparsed_promo", f"{adapter.chain}:offer:{offer.offer_id}",
                    {"title": offer.title, "raw": offer.promo_raw_text}, now)

        for product in products:
            if not product.sku:
                continue
            _ingest_sku(
                conn, chain=adapter.chain, sku=product.sku,
                name=product.name or offer.title,
                brand=product.brand,
                # The pack-size text lives in different places per chain. Jumbo
                # has no dedicated field for it at all, but its own product
                # title reliably ends with one ("Jumbo Blauwe Bessen 300 g") -
                # `parse_unit_size` already tolerates leading noise, matching
                # only the trailing quantity phrase, so the full title is a
                # legitimate third source, not a second parser.
                raw_unit_text=product.raw_unit_text or offer.subtitle or product.name,
                stated_unit_price_text=product.stated_unit_price_text,
                category=product.category or offer.category,
                shelf_price=product.shelf_price, bonus_price=product.bonus_price,
                ean=product.ean, promo=promo,
                is_personal=offer.is_personal, valid_from=offer.valid_from,
                valid_to=offer.valid_to, matcher=matcher, stats=stats, now=now,
            )

    conn.commit()
    return stats


def fetch_label_macros(conn: sqlite3.Connection, adapter, skus: list[str]) -> int:
    """Fetch tier-1 label macros for specific SKUs (brief section 2: prefer always).

    Opt-in, because it costs one request per SKU and the ranking already works
    from the generic food_type figures.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    for sku in skus:
        try:
            macros = adapter.fetch_macros(sku)
        except Exception as exc:
            log.warning("macros failed for %s: %s", sku, exc)
            continue
        row = conn.execute("SELECT id FROM products WHERE chain='ah' AND sku=?", (sku,)).fetchone()
        if row is None:
            continue
        if macros.protein_per_100g is None:
            _review(conn, "missing_macros", f"ah:{sku}",
                    {"note": "FIR returned no protein figure"}, now)
            continue
        conn.execute(
            "INSERT INTO product_macros (product_id, protein_per_100g, kcal_per_100g, "
            "carbs_per_100g, fat_per_100g, fiber_per_100g, salt_per_100g, basis_unit, "
            "kcal_is_derived, source, confidence, observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(product_id) DO UPDATE SET protein_per_100g=excluded.protein_per_100g, "
            "kcal_per_100g=excluded.kcal_per_100g, basis_unit=excluded.basis_unit, "
            "kcal_is_derived=excluded.kcal_is_derived, observed_at=excluded.observed_at",
            (row[0], macros.protein_per_100g, macros.kcal_per_100g, macros.carbs_per_100g,
             macros.fat_per_100g, macros.fiber_per_100g, macros.salt_per_100g,
             macros.basis_unit, int(macros.kcal_is_derived), "label", "high", now),
        )
        written += 1
    conn.commit()
    return written


def _review(conn, kind: str, ref: str, payload: dict[str, Any], now: str) -> None:
    conn.execute(
        "INSERT INTO needs_review (kind, ref, payload, first_seen) VALUES (?,?,?,?) "
        "ON CONFLICT (kind, ref) DO NOTHING",
        (kind, ref, json.dumps(payload, ensure_ascii=False), now),
    )
