"""What a kilo of a food type costs right now. Groundwork for milestone 8.

Milestones 1-6 only ever needed a price for SKUs that turned up in the bonus
folder, because ranking answers "what is a good deal this week". The
substitution engine asks something different: to price a recipe of kwark +
cacao + zoetstof it needs a price for *every* food type in it, in every week,
whether or not any of them is on offer. Most weeks, most are not.

So this module adds the missing lane in both directions:

  `refresh_food_type_prices`  fetches a regular shelf price for a food type from
                              the chain's product search and appends it as an
                              ordinary observation with mechanic `not_a_promo`.
  `food_type_price`           reads back the cheapest currently-valid price per
                              kilo across every SKU of that food type, so a live
                              bonus naturally beats the shelf price and an
                              expired one does not.

Two things are deliberately not done here. Search results go through the
existing `Matcher`, guards and all, because a search for "magere kwark" returns
kwarktaart and a second, looser matching path would undo the work of milestone
5. And a food type that nothing matches is queued for review, never given a
guessed price - the review queue is the whole reason it exists.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .matcher import MatchMethod, Matcher
from .parsers import parse_unit_size
from .parsers.promos import PromoKind
from .ranking import resolve_mass

log = logging.getLogger(__name__)

# Mechanics that mean "this is just what it costs", not a promotion.
_NOT_PROMOTIONS = {PromoKind.NOT_A_PROMO.value, PromoKind.UNKNOWN.value, None, ""}


@dataclass(frozen=True)
class FoodTypePrice:
    """The cheapest way to buy one kilo of a food type today."""

    food_type_key: str
    eur_per_kg: float
    sku: str
    product_name: str
    mass_g: float
    unit_price: float
    promo_mechanic: str | None
    promo_raw_text: str | None
    required_quantity: int
    observed_at: str
    is_personal: bool

    @property
    def is_promo(self) -> bool:
        return self.promo_mechanic not in _NOT_PROMOTIONS


@dataclass
class PriceStats:
    queried: int = 0
    matched: int = 0
    unmatched: int = 0
    observations: int = 0
    skipped_no_price: int = 0
    reviews: dict[str, int] = field(default_factory=dict)

    def review(self, kind: str) -> None:
        self.reviews[kind] = self.reviews.get(kind, 0) + 1


_PRICE_SQL = """
SELECT p.sku, p.name, p.raw_unit_text,
       f.density_g_per_ml, f.g_per_unit, f.drained_fraction,
       o.effective_unit_price, o.shelf_price, o.promo_mechanic, o.promo_raw_text,
       o.required_quantity, o.is_personal_offer, o.valid_from, o.valid_to, o.observed_at
FROM price_observations o
JOIN products p ON p.id = o.product_id
JOIN food_types f ON f.id = p.food_type_id
WHERE f.key = ? AND p.chain = ?
  AND o.id = (SELECT id FROM price_observations o2
              WHERE o2.product_id = p.id ORDER BY o2.observed_at DESC, o2.id DESC LIMIT 1)
"""


def food_type_price(
    conn: sqlite3.Connection,
    food_type_key: str,
    *,
    chain: str = "ah",
    on: date | None = None,
    include_personal: bool = False,
) -> FoodTypePrice | None:
    """Cheapest current euro-per-kilo for a food type, or None if unknown.

    None is a real answer and the caller must keep it as one: a composition with
    an unpriced item costs an unknown amount, not the sum of the rest.
    """
    today = (on or date.today()).isoformat()
    best: FoodTypePrice | None = None

    for row in conn.execute(_PRICE_SQL, (food_type_key, chain)).fetchall():
        # Bonus weeks do not align across chains; always filter on the window.
        if row["valid_from"] and row["valid_from"] > today:
            continue
        if row["valid_to"] and row["valid_to"] < today:
            continue
        if row["is_personal_offer"] and not include_personal:
            continue

        unit_price = row["effective_unit_price"]
        if unit_price is None:
            unit_price = row["shelf_price"]
        if unit_price is None:
            continue

        # Same mass the ranking divides by, via the same function.
        mass_g = resolve_mass(parse_unit_size(row["raw_unit_text"]), row)
        if not mass_g:
            continue

        candidate = FoodTypePrice(
            food_type_key=food_type_key,
            eur_per_kg=unit_price / mass_g * 1000.0,
            sku=row["sku"],
            product_name=row["name"],
            mass_g=mass_g,
            unit_price=unit_price,
            promo_mechanic=row["promo_mechanic"],
            promo_raw_text=row["promo_raw_text"],
            required_quantity=row["required_quantity"] or 1,
            observed_at=row["observed_at"],
            is_personal=bool(row["is_personal_offer"]),
        )
        if best is None or candidate.eur_per_kg < best.eur_per_kg:
            best = candidate

    return best


def refresh_food_type_prices(
    conn: sqlite3.Connection,
    adapter,
    *,
    keys: list[str] | None = None,
    max_requests: int | None = None,
    max_aliases: int = 2,
    matcher: Matcher | None = None,
    observed_at: str | None = None,
) -> PriceStats:
    """Fetch a plain shelf price for each food type from the chain's search lane.

    One request per food type, through the polite client's 6 h disk cache, so a
    same-day re-run costs nothing. `max_requests` bounds a careless run; the
    full seed is ~190 queries, which at 2 req/s is about 95 seconds. A food type
    the canonical name cannot find costs up to `max_aliases` further requests.
    """
    if not hasattr(adapter, "search_products"):
        raise NotImplementedError(
            f"{adapter.chain} has no product search lane yet; only AH does. "
            "See CLAUDE.md section 4 - Jumbo and Aldi need endpoint discovery."
        )

    matcher = matcher or Matcher.from_db(conn)
    stats = PriceStats()
    now = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")[:10]

    requests = 0
    for row in _food_types_to_price(conn, keys):
        if max_requests is not None and requests >= max_requests:
            break
        stats.queried += 1
        product, rejected, results = None, [], []

        # The canonical name is not always a good search term: "skyr met fruit"
        # returns Coca-Cola multipacks, while its alias "skyr aardbei" finds the
        # product. So aliases are tried, but only after the canonical name has
        # failed - the extra requests land on the gaps, not on the whole sweep.
        for query in _queries(conn, row, max_aliases):
            if max_requests is not None and requests >= max_requests:
                break
            try:
                results = adapter.search_products(query)
                requests += 1
            except Exception as exc:  # one bad query must not abort the sweep
                log.warning("search failed for %r: %s", query, exc)
                continue
            product, unpriceable = _pick(results, row, matcher, adapter.chain)
            # Accumulated across queries: a later query returning nothing must
            # not erase the evidence that an earlier one matched but could not
            # be costed. That distinction picks the review queue.
            rejected.extend(unpriceable)
            if product is not None:
                break

        if product is None:
            stats.unmatched += 1
            if rejected:
                # Matched, but every hit was a multipack or a "per stuk" item
                # with no resolvable mass. A different gap from a bad match, and
                # the fix is a g_per_unit in the seed, not a match override.
                stats.review("unparsed_unit_size")
                _review(conn, "unparsed_unit_size", f"food_type:{row['key']}", {
                    "query": query,
                    "matched_but_unpriceable": rejected,
                    "note": "search only returned SKUs whose unit size gives no "
                            "mass (multipacks, 'per stuk'). Add g_per_unit to the "
                            "food_types seed, or a `contains:` rule pointing at a "
                            "single-pack SKU.",
                }, now)
            else:
                stats.review("unmatched_sku")
                _review(conn, "unmatched_sku", f"food_type:{row['key']}", {
                    "queries": _queries(conn, row, max_aliases),
                    "results": [r.name for r in results][:10],
                    "note": "search returned nothing the matcher accepts - add a "
                            "`contains:` rule to match_overrides.yaml, or widen the "
                            "aliases. Never lower the threshold for this.",
                }, now)
            continue

        stats.matched += 1
        price = product.shelf_price if product.shelf_price is not None else product.bonus_price
        if price is None:
            stats.skipped_no_price += 1
            continue
        stats.observations += _store_shelf_price(
            conn, product, food_type_id=row["id"], chain=adapter.chain,
            price=price, observed_at=now,
        )

    conn.commit()
    return stats


def _queries(conn, food_type_row, max_aliases: int) -> list[str]:
    """Search terms to try, canonical name first.

    Aliases are ordered longest-first: a longer alias is more specific, and the
    specific one is what finds the product ("skyr aardbei" over "skyr").
    """
    queries = [food_type_row["name_nl"]]
    if max_aliases > 0:
        aliases = [
            r["alias"] for r in conn.execute(
                "SELECT alias FROM food_type_aliases WHERE food_type_id=?",
                (food_type_row["id"],),
            )
            if r["alias"] != food_type_row["name_nl"].lower()
        ]
        queries += sorted(aliases, key=len, reverse=True)[:max_aliases]
    return queries


def _food_types_to_price(conn, keys) -> list[sqlite3.Row]:
    sql = ("SELECT id, key, name_nl, density_g_per_ml, g_per_unit, drained_fraction "
           "FROM food_types")
    params: tuple = ()
    if keys:
        sql += f" WHERE key IN ({','.join('?' * len(keys))})"
        params = tuple(keys)
    return conn.execute(sql + " ORDER BY key", params).fetchall()


def _pick(results, food_type_row, matcher: Matcher, chain: str):
    """First search hit the matcher accepts *and* a per-kilo price can be built from.

    Search relevance is the chain's opinion; the matcher's guards are ours. A hit
    the matcher files under a different food type is a rejection, not a near
    miss: that is how "magere kwark" would otherwise become kwarktaart.

    Resolvable mass is a second, separate bar. AH's search puts multipacks near
    the top - the first hit for "halfvolle melk" is a 12-pack whose
    salesUnitSize is "2 stuks", which is genuinely halfvolle melk and genuinely
    impossible to price per kilo. Taking it would leave the food type unpriced
    while looking like a success, so those are skipped and reported separately.

    Returns (product, names_matched_but_unpriceable).
    """
    unpriceable: list[str] = []
    for product in results:
        if not product.sku or not product.name:
            continue
        match = matcher.match(product.name, brand=product.brand,
                              chain=chain, sku=product.sku)
        if match.food_type_key != food_type_row["key"]:
            continue
        if match.method is MatchMethod.EXCLUDED:
            continue
        if resolve_mass(parse_unit_size(product.raw_unit_text), food_type_row) is None:
            unpriceable.append(f"{product.name} [{product.raw_unit_text}]")
            continue
        return product, unpriceable
    return None, unpriceable


def _store_shelf_price(conn, product, *, food_type_id: int, chain: str,
                       price: float, observed_at: str) -> int:
    """Upsert the product, then append the observation. Never an UPDATE of a price."""
    size = parse_unit_size(product.raw_unit_text)
    conn.execute(
        "INSERT INTO products (chain, sku, name, brand, raw_unit_text, unit_size_g, "
        "unit_size_ml, cost_basis_g, ean, category, food_type_id, match_method, "
        "match_score, url, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(chain, sku) DO UPDATE SET name=excluded.name, brand=excluded.brand, "
        "raw_unit_text=excluded.raw_unit_text, unit_size_g=excluded.unit_size_g, "
        "unit_size_ml=excluded.unit_size_ml, cost_basis_g=excluded.cost_basis_g, "
        "category=excluded.category, food_type_id=excluded.food_type_id",
        (chain, product.sku, product.name, product.brand, product.raw_unit_text,
         size.total_g, size.total_ml, size.cost_basis_g, product.ean,
         product.category, food_type_id, "search_shelf_price", 1.0,
         product.url, observed_at),
    )
    product_id = conn.execute(
        "SELECT id FROM products WHERE chain=? AND sku=?", (chain, product.sku)
    ).fetchone()[0]

    # promo_raw_text is part of the uniqueness key, so the plain shelf price
    # carries a stable marker rather than NULL - two NULLs do not conflict in
    # SQLite, and a day's re-run would otherwise append a duplicate row.
    cursor = conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer) VALUES (?,?,?,?,?,1,?,0) "
        "ON CONFLICT (product_id, observed_at, promo_raw_text) DO NOTHING",
        (product_id, observed_at, price, PromoKind.NOT_A_PROMO.value,
         "shelf price (search)", price),
    )
    return max(cursor.rowcount, 0)


def _review(conn, kind: str, ref: str, payload: dict, now: str) -> None:
    conn.execute(
        "INSERT INTO needs_review (kind, ref, payload, first_seen) VALUES (?,?,?,?) "
        "ON CONFLICT (kind, ref) DO NOTHING",
        (kind, ref, json.dumps(payload, ensure_ascii=False), now),
    )
