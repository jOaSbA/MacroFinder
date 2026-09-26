"""The published app database: full builds, deltas, and the manifest.

Milestone 14 (PLAN-V2 section 5). This replaces committing a JSON snapshot back
into the repository for anything catalogue-sized. Five revisions of the current
1.07 MB `latest.json` already account for most of a 2.12 MiB object store; a
full AH plus Jumbo catalogue is roughly fifteen times that, twice a day,
forever, with no way to prune without rewriting history.

`latest.json` is deliberately left alone. It stays the promos-only
fast path the app reads on launch, and it is the reason a failed catalogue sync
degrades into a smaller app rather than a broken one.

Three decisions this module is built on:

**The artifact is a pure function of the dev database's contents.** No
timestamp, no build counter and no insertion history reaches the bytes; the
clock lives in the manifest. That is what makes a `sha256` worth publishing -
the app can tell "nothing changed" from "the catalogue moved" by comparing one
string, and the refresh job can skip re-publishing 20 MB that nobody needs.

**A build's version is its own content hash, not a timestamp.** PLAN-V2 sketches
`macrofinder-{YYYYMMDD-HHMM}.sqlite`, which would give two identical catalogues
two names and make "did this change?" undecidable without downloading both. The
filename carries the hash instead. Same idea as the plan, one fewer lie.

**Every key is a string, and product ids are `{chain}:{sku}`.** The dev
database's `products.id` is an autoincrement: rebuild from the raw snapshots,
which this project is designed to let you do, and every id shifts. A delta
keyed on those would re-point silently at a different product. This is the same
reasoning that keeps saved meals off database ids in the Android app.

Tables are `WITHOUT ROWID`, so there are no implicit integers to drift either.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, history, metrics, shelves

# Bumped whenever APP_SCHEMA changes. This is for the app to read; it is NOT
# what guards delta building - `_schema_of` compares the databases' actual
# schemas, because a version number nobody bumped is exactly the bug that
# reaches production. Milestone 15 added products.subcategory/image_width.
SCHEMA_VERSION = 3

# Enough of the hash to be unique across any plausible number of builds, short
# enough to read in a filename and a log line.
_VERSION_CHARS = 16

# See `_vacuum_into`. Any fixed value works; 1 is the value a freshly created
# database would have had after its first statement.
_PINNED_SCHEMA_COOKIE = 1

APP_SCHEMA = """
CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE food_types (
    key                       TEXT PRIMARY KEY,
    name_nl                   TEXT NOT NULL,
    meal_kind                 TEXT,
    protein_per_100g          REAL,
    kcal_per_100g             REAL,
    carbs_per_100g            REAL,
    fat_per_100g              REAL,
    g_per_unit                REAL,
    drained_fraction          REAL,
    shelf_life_days_unopened  INTEGER,
    shelf_life_days_opened    INTEGER,
    freezable                 INTEGER,
    -- BRIEF section 9 rule 1. A macro figure the app cannot describe is a
    -- macro figure the app must not render bare, and docs/AUDIT.md finding
    -- 3.3 is exactly that: the JSON export ships these numbers with no way to
    -- know they are seed estimates.
    macro_source              TEXT,
    macro_confidence          TEXT,
    -- complete / incomplete / blend, from data/seed/protein_quality.yaml
    -- (PLAN-V2 section 4.3). NULL when nobody authored one.
    protein_quality           TEXT
) WITHOUT ROWID;

-- Milestone 19. The shared shelves from data/seed/category_map.yaml, in the
-- order the app shows them. Shipped rather than hardcoded in the app so a
-- relabel doesn't need an app update.
CREATE TABLE shelves (
    key         TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    sort_order  INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE products (
    id           TEXT PRIMARY KEY,          -- '{chain}:{sku}'
    chain        TEXT NOT NULL,
    sku          TEXT NOT NULL,
    name         TEXT NOT NULL,
    brand        TEXT,
    category     TEXT,
    -- The finer shelf level. Kept apart from `category` because
    -- match_overrides.yaml excludes whole departments by the coarse one.
    subcategory  TEXT,
    -- Key into `shelves`, or NULL when the chain's category isn't mapped.
    shelf        TEXT,
    -- NULL for roughly nine SKUs in ten. The catalogue exists to make every
    -- product priceable into a meal, not only the matched ones, so an
    -- unmatched row is kept and says so.
    food_type    TEXT REFERENCES food_types(key),
    raw_unit_text TEXT,
    unit_size_g  REAL,
    unit_size_ml REAL,
    cost_basis_g REAL,
    ean          TEXT,
    -- The chain's own CDN url and the rendition width it was chosen at, from
    -- the milestone 15 catalogue crawl. Never rehosted and never proxied:
    -- PLAN-V2 section 3.3. NULL for a product only ever seen in a promo feed
    -- that carries no image.
    image_url    TEXT,
    image_width  INTEGER,
    -- Milestone 20, derived at build time so the app can sort 50k rows with
    -- an index instead of recomputing. Macros are resolved already: the SKU's
    -- own label when there is one, else the food type's seed figure, with
    -- the provenance beside them. Every one is NULL when unknown, never 0.
    mass_g               REAL,
    protein_per_100g     REAL,
    kcal_per_100g        REAL,
    carbs_per_100g       REAL,
    fat_per_100g         REAL,
    macro_source         TEXT,
    macro_confidence     TEXT,
    protein_per_100kcal  REAL,
    -- Comma-separated macro buckets (PLAN-V2 section 4.1), '' for none.
    -- `bulk` is not in here: it is relative, so meta.bulk_eur_per_1000kcal
    -- carries the cutoff and the app compares prices.eur_per_1000kcal to it.
    buckets              TEXT NOT NULL DEFAULT '',
    -- Milestone 22. Median days between promo starts (NULL under three
    -- promos) and when the last one started. The phone turns these into
    -- buy/wait against its own date, so nothing here changes daily.
    promo_cycle_days     INTEGER,
    last_promo_start     TEXT
) WITHOUT ROWID;

-- Tier 1, the SKU's own FIR label figures. BRIEF section 2 prefers these over
-- the generic food type always, and `ranking.resolve_macros` already does.
CREATE TABLE product_macros (
    product_id        TEXT PRIMARY KEY REFERENCES products(id),
    protein_per_100g  REAL,
    kcal_per_100g     REAL,
    carbs_per_100g    REAL,
    fat_per_100g      REAL,
    basis_unit        TEXT,
    kcal_is_derived   INTEGER NOT NULL DEFAULT 0,
    macro_source      TEXT,
    macro_confidence  TEXT
) WITHOUT ROWID;

-- Current prices only. The history stays in the dev database, where the
-- milestone 21/22 signals are computed - publishing every observation would
-- multiply the catalogue by the number of weeks the scraper has been running.
--
-- Two lanes per product, not one. Milestone 8 measured what happens otherwise:
-- a shelf price recorded today supersedes this week's still-valid bonus under
-- a plain 'latest observation' rule, and `bonusrank list` silently dropped
-- from 174 rated offers to 160. The reader disambiguates because the writer
-- cannot.
CREATE TABLE prices (
    product_id            TEXT NOT NULL REFERENCES products(id),
    lane                  TEXT NOT NULL CHECK (lane IN ('promo','upcoming','shelf')),
    observed_at           TEXT NOT NULL,
    shelf_price           REAL,
    bonus_price           REAL,
    promo_mechanic        TEXT,
    promo_text            TEXT,
    required_quantity     INTEGER,
    effective_unit_price  REAL,
    is_personal_offer     INTEGER NOT NULL DEFAULT 0,
    valid_from            TEXT,
    valid_to              TEXT,
    -- Milestone 20. Per lane, because a promo and a shelf price give the same
    -- product two different costs per gram of protein.
    eur_per_100g_protein  REAL,
    eur_per_1000kcal      REAL,
    -- How far below the shelf price this lane is, in percent. NULL on the
    -- shelf lane and whenever there is no shelf price to compare with.
    discount_pct          REAL,
    -- Milestone 21, BRIEF section 3.3: the cost per 100 g protein counting
    -- only what you'd get through before it goes off.
    waste_adjusted_eur_per_100g_protein  REAL,
    realistically_consumable             INTEGER,
    perishable                           INTEGER,
    -- "Cheapest in N weeks". NULL means not enough history to say.
    cheapest_in_weeks     INTEGER,
    -- Milestone 22: the shelf price went up in the 28 days before this promo.
    -- NULL when there's no earlier price to compare with.
    reference_inflated    INTEGER,
    PRIMARY KEY (product_id, lane)
) WITHOUT ROWID;

-- Weekly lowest price, for the sparkline on the detail screen. Only products
-- with known macros, and only the last 26 weeks, so this stays small. Past
-- weeks never change, which keeps deltas cheap.
CREATE TABLE price_history (
    product_id  TEXT NOT NULL REFERENCES products(id),
    week        TEXT NOT NULL,     -- the Monday, ISO date
    price       REAL NOT NULL,
    PRIMARY KEY (product_id, week)
) WITHOUT ROWID;

CREATE INDEX idx_products_chain ON products(chain);
CREATE INDEX idx_products_food_type ON products(food_type);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_shelf ON products(shelf);
CREATE INDEX idx_prices_valid ON prices(valid_from, valid_to);
CREATE INDEX idx_prices_protein ON prices(eur_per_100g_protein);
CREATE INDEX idx_products_ratio ON products(protein_per_100kcal);
"""

# name -> the columns that identify a row, for diffing and for deletions.
#
# `prices` is the reason this is a tuple rather than a column name. It is keyed
# on (product_id, lane), and a product routinely loses one lane while keeping
# the other: a SKU that was on the shelf last week and on promo this week has
# its shelf row disappear. Keyed on product_id alone, that deletion is
# invisible and the app keeps last week's shelf price forever next to this
# week's bonus.
_TABLES: dict[str, tuple[str, ...]] = {
    "meta": ("key",),
    "food_types": ("key",),
    "shelves": ("key",),
    "products": ("id",),
    "product_macros": ("product_id",),
    "prices": ("product_id", "lane"),
    "price_history": ("product_id", "week"),
}

# ASCII unit separator: it cannot occur in a chain name, an SKU or a lane, so
# the joined key is unambiguous without any escaping.
_KEY_SEP = "char(31)"


def _key_expr(table: str) -> str:
    """The single-column expression that identifies a row of `table`."""
    columns = _TABLES[table]
    if len(columns) == 1:
        return columns[0]
    return f" || {_KEY_SEP} || ".join(columns)


_DELTA_EXTRA_SCHEMA = """
CREATE TABLE delta_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
) WITHOUT ROWID;

-- A row that vanished cannot be expressed as an upsert. Without this the app
-- would keep a delisted product forever, with no way to learn otherwise short
-- of a full re-download.
CREATE TABLE deletions (
    tbl  TEXT NOT NULL,
    id   TEXT NOT NULL,
    PRIMARY KEY (tbl, id)
) WITHOUT ROWID;
"""


class SchemaMismatch(Exception):
    """Two builds of different schema versions cannot be diffed."""


def _schema_of(path: Path) -> tuple[str, ...]:
    """Every table and index definition in the file, as SQLite stored it.

    A delta is a row-level `EXCEPT`, so both sides need identical columns. The
    obvious guard is to compare the declared `schema_version`, and the obvious
    guard is wrong: a hand-maintained integer somebody forgot to bump reads as
    a match and the diff fails several frames later with "SELECTs to the left
    and right of EXCEPT do not have the same number of result columns". Which
    is how this was found. Comparing what is actually in the files cannot be
    forgotten.
    """
    db = sqlite3.connect(path)
    try:
        return tuple(sorted(
            row[0] for row in db.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
            )
        ))
    finally:
        db.close()


def _schema_version(path: Path) -> str | None:
    db = sqlite3.connect(path)
    try:
        row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError:
        return None
    finally:
        db.close()
    return row[0] if row else None


# -- building ------------------------------------------------------------------

def build_full(conn: sqlite3.Connection, out: Path, *, on: date | None = None) -> Path:
    """Write a complete app database from the dev database behind `conn`.

    `on` decides which promo counts as current and which as upcoming. The
    app still checks the dates itself, because an upcoming row becomes
    current on the phone the day it starts, whatever lane it arrived in.
    """
    on = on or date.today()
    out = Path(out)
    staging = out.with_suffix(out.suffix + ".staging")
    staging.unlink(missing_ok=True)

    db = sqlite3.connect(staging)
    try:
        db.executescript(APP_SCHEMA)
        db.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                   (str(SCHEMA_VERSION),))
        shelf_map = shelves.load()
        _copy_food_types(conn, db)
        _copy_shelves(db, shelf_map)
        _copy_products(conn, db, shelf_map)
        _copy_product_macros(conn, db)
        _copy_prices(conn, db, on)
        _derive_metrics(conn, db)
        _derive_history(conn, db)
        db.commit()
        _vacuum_into(db, out)
    finally:
        db.close()
        staging.unlink(missing_ok=True)
    return out


def _copy_food_types(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    quality = protein_quality()
    rows = src.execute(
        "SELECT key, name_nl, meal_kind, protein_per_100g, kcal_per_100g, "
        "carbs_per_100g, fat_per_100g, g_per_unit, drained_fraction, "
        "shelf_life_days_unopened, shelf_life_days_opened, freezable, "
        "source, confidence FROM food_types ORDER BY key"
    ).fetchall()
    dst.executemany(
        "INSERT INTO food_types (key, name_nl, meal_kind, protein_per_100g, "
        "kcal_per_100g, carbs_per_100g, fat_per_100g, g_per_unit, drained_fraction, "
        "shelf_life_days_unopened, shelf_life_days_opened, freezable, "
        "macro_source, macro_confidence, protein_quality) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(*r, quality.get(r[0])) for r in rows],
    )


QUALITY_PATH = config.PROJECT_ROOT / "data" / "seed" / "protein_quality.yaml"


def protein_quality() -> dict[str, str]:
    """food type key -> complete / incomplete / blend. Raises on a key listed twice."""
    import yaml

    raw = yaml.safe_load(QUALITY_PATH.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for quality, keys in raw.items():
        for key in keys or []:
            if key in out:
                raise ValueError(f"protein_quality.yaml: {key} is both {out[key]} and {quality}")
            out[key] = quality
    return out


def _copy_shelves(dst: sqlite3.Connection, shelf_map) -> None:
    dst.executemany(
        "INSERT INTO shelves (key, label, sort_order) VALUES (?,?,?)",
        [(key, label, i) for i, (key, label) in enumerate(shelf_map.shelves.items())],
    )


def _copy_products(src: sqlite3.Connection, dst: sqlite3.Connection, shelf_map) -> None:
    rows = src.execute(
        "SELECT p.chain, p.sku, p.name, p.brand, p.category, p.subcategory, "
        "       f.key AS food_type, p.raw_unit_text, p.unit_size_g, p.unit_size_ml, "
        "       p.cost_basis_g, p.ean, p.image_url, p.image_width "
        "FROM products p LEFT JOIN food_types f ON f.id = p.food_type_id "
        "ORDER BY p.chain, p.sku"
    ).fetchall()
    dst.executemany(
        "INSERT INTO products (id, chain, sku, name, brand, category, subcategory, "
        "food_type, raw_unit_text, unit_size_g, unit_size_ml, cost_basis_g, ean, "
        "image_url, image_width, shelf) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(product_id(r[0], r[1]), *r, shelf_map.shelf_for(r[0], r[4])) for r in rows],
    )


def _copy_product_macros(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    rows = src.execute(
        "SELECT p.chain, p.sku, m.protein_per_100g, m.kcal_per_100g, m.carbs_per_100g, "
        "       m.fat_per_100g, m.basis_unit, m.kcal_is_derived, m.source, m.confidence "
        "FROM product_macros m JOIN products p ON p.id = m.product_id "
        "ORDER BY p.chain, p.sku"
    ).fetchall()
    dst.executemany(
        "INSERT INTO product_macros (product_id, protein_per_100g, kcal_per_100g, "
        "carbs_per_100g, fat_per_100g, basis_unit, kcal_is_derived, macro_source, "
        "macro_confidence) VALUES (?,?,?,?,?,?,?,?,?)",
        [(product_id(r[0], r[1]), *r[2:]) for r in rows],
    )


# The same lane rule as `ranking.rank`, via `ranking.lane_filter`. Two
# implementations of "which observation counts" would drift, and the one that
# drifts is the one that forgets a lane.
_PRICES_SQL = """
SELECT p.chain, p.sku,
       CASE WHEN o.promo_mechanic = 'not_a_promo' THEN 'shelf'
            WHEN o.valid_from > :day THEN 'upcoming'
            ELSE 'promo' END AS lane,
       o.observed_at, o.shelf_price, o.bonus_price, o.promo_mechanic, o.promo_raw_text,
       o.required_quantity, o.effective_unit_price, o.is_personal_offer,
       o.valid_from, o.valid_to
FROM price_observations o
JOIN products p ON p.id = o.product_id
WHERE {lanes}
ORDER BY p.chain, p.sku, lane
"""


def _copy_prices(src: sqlite3.Connection, dst: sqlite3.Connection, on: date) -> None:
    from .ranking import lane_filter

    sql = _PRICES_SQL.format(lanes=lane_filter("shelf", "active", "upcoming"))
    rows = src.execute(sql, {"day": on.isoformat()}).fetchall()
    dst.executemany(
        "INSERT INTO prices (product_id, lane, observed_at, shelf_price, bonus_price, "
        "promo_mechanic, promo_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_from, valid_to) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(product_id(r[0], r[1]), *r[2:]) for r in rows],
    )


def _derive_metrics(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Milestone 20: resolved macros, the four metrics, and the macro buckets.

    Uses the same unit parsing and mass rules as `ranking`, so a product costs
    the same per gram of protein in the CLI and on the phone.
    """
    from .parsers.units import parse_unit_size
    from .ranking import resolve_mass

    food = {
        r["key"]: dict(r) for r in src.execute(
            "SELECT key, density_g_per_ml, g_per_unit, drained_fraction, meal_kind, "
            "freezable, protein_per_100g, kcal_per_100g, carbs_per_100g, fat_per_100g, "
            "source, confidence FROM food_types")
    }
    blank = dict.fromkeys(("density_g_per_ml", "g_per_unit", "drained_fraction"))
    label = {r[0]: r for r in dst.execute(
        "SELECT product_id, protein_per_100g, kcal_per_100g, carbs_per_100g, "
        "fat_per_100g, macro_source, macro_confidence FROM product_macros")}

    derived: dict[str, dict] = {}
    for pid, name, food_type, raw_unit in dst.execute(
            "SELECT id, name, food_type, raw_unit_text FROM products"):
        ft = food.get(food_type)
        mass = resolve_mass(parse_unit_size(raw_unit), ft or blank)
        tier1 = label.get(pid)
        if tier1 is not None and tier1[1] is not None:
            macros = tier1[1:7]
        elif ft is not None and ft["protein_per_100g"] is not None:
            macros = (ft["protein_per_100g"], ft["kcal_per_100g"], ft["carbs_per_100g"],
                      ft["fat_per_100g"], ft["source"], ft["confidence"])
        else:
            macros = (None,) * 6
        derived[pid] = {"name": name, "food_type": food_type, "ft": ft,
                        "mass": mass, "macros": macros}

    price_rows = dst.execute(
        "SELECT product_id, lane, effective_unit_price, shelf_price FROM prices").fetchall()
    price_updates = []
    current_kcal_cost: dict[str, float | None] = {}
    for pid, lane, price, shelf in price_rows:
        d = derived[pid]
        protein, kcal = d["macros"][0], d["macros"][1]
        per_protein = metrics.eur_per_100g_protein(price, d["mass"], protein)
        per_kcal = metrics.eur_per_1000kcal(price, d["mass"], kcal)
        discount = None
        if lane != "shelf" and price is not None and shelf and price < shelf:
            discount = round((1 - price / shelf) * 100.0, 1)
        price_updates.append((per_protein, per_kcal, discount, pid, lane))
        # The bulk quartile is over what a product costs now: the promo if
        # there is one, else the shelf price.
        if lane == "promo" or (lane == "shelf" and pid not in current_kcal_cost):
            current_kcal_cost[pid] = per_kcal
    dst.executemany(
        "UPDATE prices SET eur_per_100g_protein=?, eur_per_1000kcal=?, discount_pct=? "
        "WHERE product_id=? AND lane=?", price_updates)

    # "Bulk" is relative: the cheapest quarter by €/1000 kcal. Stamping it on
    # each product would rewrite hundreds of rows whenever one price moved
    # the cutoff, and every delta would carry them. So the cutoff ships once,
    # in meta, and the app compares against it.
    cutoff = metrics.bulk_cutoff(current_kcal_cost.values())
    if cutoff is not None:
        dst.execute("INSERT INTO meta (key, value) VALUES ('bulk_eur_per_1000kcal', ?)",
                    (f"{cutoff:.4f}",))
    product_updates = []
    for pid, d in derived.items():
        protein, kcal, carbs, fat, source, confidence = d["macros"]
        ft = d["ft"] or {}
        tags = metrics.buckets(
            protein=protein, kcal=kcal, mass_g=d["mass"], meal_kind=ft.get("meal_kind"),
            food_type=d["food_type"], freezable=bool(ft.get("freezable")), name=d["name"],
            eur_per_1000kcal=None, bulk_cutoff=None)
        product_updates.append((
            d["mass"], protein, kcal, carbs, fat, source, confidence,
            metrics.protein_ratio(protein, kcal), ",".join(tags), pid))
    dst.executemany(
        "UPDATE products SET mass_g=?, protein_per_100g=?, kcal_per_100g=?, "
        "carbs_per_100g=?, fat_per_100g=?, macro_source=?, macro_confidence=?, "
        "protein_per_100kcal=?, buckets=? WHERE id=?", product_updates)


def _derive_history(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Milestones 21 and 22: waste adjustment, cheapest-in-N-weeks, reference
    inflation, the promo cycle, and the weekly series for the sparkline."""
    from collections import defaultdict

    from .parsers.units import parse_unit_size
    from .ranking import _history, _waste_adjust

    settings = config.user_settings()
    dev_ids = {product_id(r[1], r[2]): r[0]
               for r in src.execute("SELECT id, chain, sku FROM products")}
    obs: dict[int, list] = defaultdict(list)
    for r in src.execute(
            "SELECT product_id, observed_at, shelf_price, effective_unit_price, "
            "promo_mechanic, valid_from FROM price_observations ORDER BY observed_at, id"):
        obs[r[0]].append(r)
    food = {r["key"]: r for r in src.execute(
        "SELECT key, shelf_life_days_opened, shelf_life_days_unopened, freezable "
        "FROM food_types")}
    products = {r[0]: r for r in dst.execute(
        "SELECT id, food_type, raw_unit_text, mass_g, protein_per_100g FROM products")}

    price_updates = []
    for pid, lane, price, required, shelf, valid_from in dst.execute(
            "SELECT product_id, lane, effective_unit_price, required_quantity, shelf_price, "
            "valid_from FROM prices WHERE lane != 'shelf'").fetchall():
        p = products[pid]
        dev = dev_ids.get(pid)
        rows = obs.get(dev, [])
        consumable = waste = perishable = None
        ft = food.get(p[1])
        if ft is not None:
            consumable, waste, perishable = _waste_adjust(
                ft, parse_unit_size(p[2]), p[3], price, required or 1, p[4], settings)
        weeks = _history(src, dev, price)["cheapest_in_weeks"] if dev else None
        inflated = None
        if valid_from:
            shelf_series = [(date.fromisoformat(r[1][:10]), r[2]) for r in rows if r[2]]
            inflated = history.reference_inflated(
                shelf_series, date.fromisoformat(valid_from), shelf)
        price_updates.append((
            waste, consumable, None if perishable is None else int(perishable), weeks,
            None if inflated is None else int(inflated), pid, lane))
    dst.executemany(
        "UPDATE prices SET waste_adjusted_eur_per_100g_protein=?, realistically_consumable=?, "
        "perishable=?, cheapest_in_weeks=?, reference_inflated=? "
        "WHERE product_id=? AND lane=?", price_updates)

    cycle_updates, series_rows = [], []
    for pid, p in products.items():
        rows = obs.get(dev_ids.get(pid), [])
        if not rows:
            continue
        starts = sorted({date.fromisoformat(r[5]) for r in rows
                         if r[4] != "not_a_promo" and r[5]})
        if starts:
            cycle_updates.append((history.cycle_days(starts), starts[-1].isoformat(), pid))
        if p[4] is not None:
            series = history.weekly_min(
                [(date.fromisoformat(r[1][:10]), r[3]) for r in rows])
            if len(series) >= 2:
                series_rows += [(pid, week, round(price, 2)) for week, price in series]
    dst.executemany(
        "UPDATE products SET promo_cycle_days=?, last_promo_start=? WHERE id=?", cycle_updates)
    dst.executemany(
        "INSERT INTO price_history (product_id, week, price) VALUES (?,?,?)", series_rows)


def product_id(chain: str, sku: str) -> str:
    """The one place the app-side product key is spelled."""
    return f"{chain}:{sku}"


# -- deltas --------------------------------------------------------------------

def build_delta(prev: Path, nxt: Path, out: Path) -> Path:
    """Write the changes that turn `prev` into `nxt`.

    Upserts come from a whole-row `EXCEPT`, which catches a new row and a
    changed row in one pass without needing to know which columns matter.
    """
    prev, nxt, out = Path(prev), Path(nxt), Path(out)

    # A delta is a row-level diff, so both sides must have the same columns.
    # When the schema moves, they do not, and the bare `EXCEPT` fails with
    # "SELECTs to the left and right of EXCEPT do not have the same number of
    # result columns" - a SQL error several frames from the actual cause.
    # Checked up front so the caller can do the only sensible thing, which is
    # publish a full build and let clients take it.
    if _schema_of(prev) != _schema_of(nxt):
        raise SchemaMismatch(
            f"schema {_schema_version(prev)} and schema {_schema_version(nxt)} "
            f"builds have different columns and cannot be diffed row by row; "
            f"publish a full build instead"
        )

    staging = out.with_suffix(out.suffix + ".staging")
    staging.unlink(missing_ok=True)

    db = sqlite3.connect(staging)
    try:
        db.executescript(APP_SCHEMA)
        db.executescript(_DELTA_EXTRA_SCHEMA)
        db.execute("ATTACH DATABASE ? AS prev", (str(prev),))
        db.execute("ATTACH DATABASE ? AS nxt", (str(nxt),))

        for table in _TABLES:
            key = _key_expr(table)
            db.execute(
                f"INSERT INTO main.{table} "
                f"SELECT * FROM nxt.{table} EXCEPT SELECT * FROM prev.{table}"
            )
            db.execute(
                "INSERT INTO main.deletions (tbl, id) "
                f"SELECT ?, {key} FROM prev.{table} "
                f"WHERE {key} NOT IN (SELECT {key} FROM nxt.{table})",
                (table,),
            )

        db.execute("INSERT INTO delta_meta (key, value) VALUES ('base_version', ?)",
                   (version_of(prev),))
        db.execute("INSERT INTO delta_meta (key, value) VALUES ('target_version', ?)",
                   (version_of(nxt),))
        db.commit()
        db.execute("DETACH DATABASE prev")
        db.execute("DETACH DATABASE nxt")
        _vacuum_into(db, out)
    finally:
        db.close()
        staging.unlink(missing_ok=True)
    return out


def apply_delta(base: Path, delta: Path, out: Path) -> Path:
    """Apply `delta` to a copy of `base` and write the result to `out`.

    The result is byte-identical to the full build the delta was cut against -
    `VACUUM INTO` normalises page layout, free lists and insertion history away,
    so "the same database" and "the same file" are the same claim here. `base`
    is never mutated.
    """
    base, delta, out = Path(base), Path(delta), Path(out)

    expected = _delta_meta(delta, "base_version")
    actual = version_of(base)
    if expected != actual:
        raise ValueError(
            f"this delta was cut from build {expected}, but the database given "
            f"is build {actual}. Applying it would produce a database that looks "
            f"correct and is quietly wrong - download the full build instead."
        )

    staging = out.with_suffix(out.suffix + ".staging")
    staging.unlink(missing_ok=True)
    shutil.copyfile(base, staging)

    db = sqlite3.connect(staging)
    try:
        db.execute("ATTACH DATABASE ? AS d", (str(delta),))
        # Deletions first: a row that was removed and a different row that was
        # added can share nothing, but doing it the other way round would let a
        # stale deletion erase a fresh upsert.
        for table in _TABLES:
            db.execute(
                f"DELETE FROM main.{table} WHERE {_key_expr(table)} IN "
                "(SELECT id FROM d.deletions WHERE tbl = ?)",
                (table,),
            )
        for table in _TABLES:
            db.execute(f"INSERT OR REPLACE INTO main.{table} SELECT * FROM d.{table}")
        db.commit()
        db.execute("DETACH DATABASE d")
        _vacuum_into(db, out)
    finally:
        db.close()
        staging.unlink(missing_ok=True)
    return out


def _delta_meta(delta: Path, key: str) -> str | None:
    db = sqlite3.connect(delta)
    try:
        row = db.execute("SELECT value FROM delta_meta WHERE key=?", (key,)).fetchone()
    finally:
        db.close()
    return row[0] if row else None


# -- identity ------------------------------------------------------------------

def version_of(path: Path) -> str:
    """A build's version: the first 16 hex characters of its own sha256.

    Content-addressed rather than clock-addressed, so two builds of an
    unchanged catalogue are the same version and the refresh job can say
    "nothing changed" instead of publishing an identical asset under a new
    name every night.
    """
    return sha256_of(path)[:_VERSION_CHARS]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _vacuum_into(db: sqlite3.Connection, out: Path) -> None:
    """The one step that makes every hash in this module mean something.

    `VACUUM INTO` writes a fresh, minimal database: no free pages, no leftover
    ordering, a reset change counter. Two databases with the same contents and
    the same schema produce the same bytes through it, whatever they went
    through to get there.

    Almost. One field survives it: the **schema cookie** at header offset 40,
    which counts schema-changing statements in the file's whole history rather
    than describing its contents. A database created by running `APP_SCHEMA`
    lands on 10; the same database copied and vacuumed again lands on 11, and
    the two files then differ in exactly one byte. Pinning the cookie before
    the vacuum is what makes "same contents" and "same bytes" the same claim,
    which is the property every hash in this module depends on.

    The cookie is a cache-invalidation counter for prepared statements within
    one connection's lifetime. Nothing reads it across processes, and the
    vacuum opens a fresh file regardless, so fixing it is safe here in a way it
    would not be on a live database.
    """
    db.execute(f"PRAGMA schema_version = {_PINNED_SCHEMA_COOKIE}")
    Path(out).unlink(missing_ok=True)
    db.execute("VACUUM INTO ?", (str(out),))


# -- the manifest --------------------------------------------------------------

# How many deltas a manifest lists. Same number as MAX_DELTA_HOPS in the
# app's SyncPlan.kt: a longer chain would never be used, a shorter one sends
# phones to the full download sooner than they need to.
MAX_PUBLISHED_DELTAS = 7


def chain_deltas(carried: list[dict], new: list[dict], *, target: str,
                 limit: int = MAX_PUBLISHED_DELTAS) -> list[dict]:
    """The deltas worth publishing: one unbroken chain ending at `target`.

    `carried` comes from the previous manifest, `new` from this build. Walks
    back from the target and stops at the first gap, so a delta that leads
    somewhere other than the current build is never published.
    """
    by_target = {d["to"]: d for d in carried}
    by_target.update({d["to"]: d for d in new})
    chain: list[dict] = []
    at = target
    while at in by_target and len(chain) < limit:
        step = by_target.pop(at)
        chain.append(step)
        at = step["from"]
    return chain[::-1]


def delta_entry(path: Path) -> dict:
    """A delta as the manifest describes it."""
    return _asset(path) | {
        "from": _delta_meta(path, "base_version"),
        "to": _delta_meta(path, "target_version"),
    }


def write_manifest(path: Path, *, full: Path, deltas: list[Path] = (),
                   delta_entries: list[dict] | None = None,
                   generated_at: date | datetime | None = None,
                   status: str = "ok") -> dict:
    """Write `manifest.json` - the only file the app fetches unconditionally.

    `status` ships from version one, reading "ok". PLAN-V2 section 7 wants a
    kill switch so the project can show a maintenance message if a chain asks
    it to stop; a kill switch added later only ever reaches the installs that
    have already updated, which is precisely the set that does not need one.
    """
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": _stamp(generated_at),
        "full": _asset(full) | {
            "version": version_of(full),
            "products": _count(full, "products"),
        },
        "deltas": (delta_entries if delta_entries is not None
                   else [delta_entry(d) for d in deltas]),
    }
    Path(path).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def halt_manifest(path: Path, *, message: str | None) -> dict:
    """Milestone 30: mark the published manifest halted, keeping its assets.

    Phones that read it stop syncing and show `message` (or their own default)
    instead of pretending the data is live. The next normal build writes "ok"
    again, so resuming is just clearing DATA_HALTED.
    """
    path = Path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = "halted"
    manifest.pop("message", None)
    if message:
        manifest["message"] = message
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _asset(path: Path) -> dict:
    path = Path(path)
    return {"file": path.name, "sha256": sha256_of(path), "bytes": path.stat().st_size}


def _count(path: Path, table: str) -> int:
    db = sqlite3.connect(path)
    try:
        return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        db.close()


def _stamp(value: date | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return datetime(value.year, value.month, value.day,
                    tzinfo=timezone.utc).isoformat(timespec="seconds")


def full_filename(path: Path) -> str:
    """`macrofinder-{version}.sqlite` - the name the release asset carries."""
    return f"macrofinder-{version_of(path)}.sqlite"


def delta_filename(prev: Path, nxt: Path) -> str:
    return f"delta-{version_of(prev)}-{version_of(nxt)}.sqlite"
