"""Open Food Facts label macros, by barcode. Milestone 36.

Jumbo and Aldi publish no nutrition we can read, so every Jumbo product ran on
the generic seed. With a barcode (milestone 35), Open Food Facts often has the
label, typed in by volunteers. That makes it a label source, not an estimate,
but a second-hand one: it ranks below the chain's own label and above the seed,
and the app says where it came from.

Open Food Facts is a nonprofit (BRIEF section 7): a small budget per run, only
matched food products, current offers first, one request per second, and every
lookup remembered in `off_lookups` so a product OFF doesn't know isn't asked
about again for two months. Data is ODbL; the app's Over screen credits it.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
FIELDS = "product_name,nutriments"
RETRY_AFTER_DAYS = 60
CACHE_TTL_SECONDS = 30 * 24 * 3600
KJ_PER_KCAL = 4.184


@dataclass(frozen=True)
class OffMacros:
    protein_per_100g: float
    kcal_per_100g: float | None
    carbs_per_100g: float | None
    fat_per_100g: float | None
    fiber_per_100g: float | None
    salt_per_100g: float | None
    kcal_is_derived: bool


def _num(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def parse_off(payload: dict) -> OffMacros | None:
    """Label figures per 100 g, or None when missing or implausible.

    Volunteer data has typos, so two checks: no figure over 100 g (or 900
    kcal), and the energy has to roughly match 4P + 4C + 9F when all three
    are there. A row that fails is skipped, not repaired.
    """
    if not payload or payload.get("status") != 1:
        return None
    n = (payload.get("product") or {}).get("nutriments") or {}
    protein = _num(n.get("proteins_100g"))
    if protein is None:
        return None
    carbs, fat = _num(n.get("carbohydrates_100g")), _num(n.get("fat_100g"))
    kcal, derived = _num(n.get("energy-kcal_100g")), False
    if kcal is None and _num(n.get("energy-kj_100g")) is not None:
        kcal, derived = round(_num(n.get("energy-kj_100g")) / KJ_PER_KCAL, 1), True

    if any(v is not None and not 0 <= v <= 100 for v in (protein, carbs, fat)):
        return None
    if kcal is not None and not 0 <= kcal <= 900:
        return None
    if kcal is not None and carbs is not None and fat is not None:
        expected = 4 * protein + 4 * carbs + 9 * fat
        if abs(expected - kcal) > max(40.0, 0.3 * kcal):
            return None
    return OffMacros(protein, kcal, carbs, fat, _num(n.get("fiber_100g")),
                     _num(n.get("salt_100g")), derived)


def disagrees_with_seed(protein: float, seed_protein: float | None) -> bool:
    """A figure far from the food type's usual value suggests the barcode
    points at a different product (Jumbo's come from image names). Small
    numbers are left alone: 0.5 against 0.0 g for an oil is not a mismatch."""
    if seed_protein is None or abs(protein - seed_protein) <= 3.0:
        return False
    low, high = sorted((protein, seed_protein))
    return low == 0 or high / low > 2.5


_CANDIDATES_SQL = """
SELECT p.id, p.ean, f.protein_per_100g AS seed_protein,
       MAX(CASE WHEN o.promo_mechanic NOT IN ('not_a_promo','unknown')
                 AND (o.valid_to IS NULL OR o.valid_to >= :today) THEN 1 ELSE 0 END) AS on_promo
FROM products p
JOIN food_types f ON f.id = p.food_type_id
LEFT JOIN price_observations o ON o.product_id = p.id
WHERE p.chain IN ('jumbo', 'aldi')
  AND p.ean IS NOT NULL
  AND p.id NOT IN (SELECT product_id FROM product_macros)
  AND p.ean NOT IN (SELECT ean FROM off_lookups WHERE looked_up_at >= :retry_after)
GROUP BY p.id
ORDER BY on_promo DESC, p.id
LIMIT :limit
"""


def fetch_off_macros(conn: sqlite3.Connection, client, limit: int, *, on: date | None = None) -> dict[str, int]:
    """Look up to `limit` barcodes and store what passes as label macros."""
    today = on or date.today()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stats = {"written": 0, "missing": 0, "rejected": 0}
    rows = conn.execute(_CANDIDATES_SQL, {
        "today": today.isoformat(),
        "retry_after": (today - timedelta(days=RETRY_AFTER_DAYS)).isoformat(),
        "limit": limit,
    }).fetchall()
    for row in rows:
        try:
            payload = client.get_json(OFF_URL.format(ean=row["ean"]) + f"?fields={FIELDS}")
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code != 404:
                log.warning("OFF lookup failed for %s: %s", row["ean"], exc)
                continue
            payload = None
        except httpx.HTTPError as exc:
            log.warning("OFF lookup failed for %s: %s", row["ean"], exc)
            continue

        macros = parse_off(payload) if payload else None
        if macros is None:
            # Known product without a protein figure is as good as unknown;
            # only figures that fail the checks count as rejected.
            nutriments = ((payload or {}).get("product") or {}).get("nutriments") or {}
            outcome = "rejected" if _num(nutriments.get("proteins_100g")) is not None else "missing"
        elif disagrees_with_seed(macros.protein_per_100g, row["seed_protein"]):
            log.info("OFF protein %.1f g for %s is far from the seed's %.1f; skipped",
                     macros.protein_per_100g, row["ean"], row["seed_protein"])
            outcome = "rejected"
        else:
            conn.execute(
                "INSERT INTO product_macros (product_id, protein_per_100g, kcal_per_100g, "
                "carbs_per_100g, fat_per_100g, fiber_per_100g, salt_per_100g, basis_unit, "
                "kcal_is_derived, source, confidence, observed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], macros.protein_per_100g, macros.kcal_per_100g, macros.carbs_per_100g,
                 macros.fat_per_100g, macros.fiber_per_100g, macros.salt_per_100g, None,
                 int(macros.kcal_is_derived), "off", "medium", now),
            )
            outcome = "written"
        stats[outcome] += 1
        conn.execute(
            "INSERT INTO off_lookups (ean, looked_up_at, outcome) VALUES (?,?,?) "
            "ON CONFLICT(ean) DO UPDATE SET looked_up_at=excluded.looked_up_at, outcome=excluded.outcome",
            (row["ean"], today.isoformat(), outcome),
        )
    conn.commit()
    return stats
