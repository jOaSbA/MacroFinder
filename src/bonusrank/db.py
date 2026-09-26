"""SQLite schema and connection. Brief section 6.

Two things are enforced by the database rather than by discipline:

  1. **Price observations are append-only.** Triggers abort any UPDATE or DELETE
     on `price_observations`. The brief says never overwrite a price row; a
     comment saying so would not survive a careless `INSERT OR REPLACE`.
  2. A product can hold **both** a generic `food_type_id` and its own label
     macros. Section 2 ranks the store's own FIR data above everything else
     ("prefer it always"), and the section 6 tables have nowhere to put per-SKU
     label macros - so `product_macros` is an addition, not a substitution.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

DB_PATH = config.DATA_DIR / "bonusrank.sqlite3"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stores (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    chain         TEXT NOT NULL,
    region        TEXT,
    store_number  TEXT,
    UNIQUE (chain, store_number)
);

CREATE TABLE IF NOT EXISTS food_types (
    id                        INTEGER PRIMARY KEY,
    key                       TEXT NOT NULL UNIQUE,
    name_nl                   TEXT NOT NULL,
    name_en                   TEXT,
    state                     TEXT CHECK (state IN ('solid','liquid','countable')),
    density_g_per_ml          REAL,
    drained_fraction          REAL,
    edible_fraction           REAL,
    dry_to_cooked_factor      REAL,
    g_per_unit                REAL,
    protein_per_100g          REAL,
    kcal_per_100g             REAL,
    carbs_per_100g            REAL,
    fat_per_100g              REAL,
    fiber_per_100g            REAL,
    -- Milestone 9: the per-meal optimiser's per-ingredient quantity ceiling.
    -- NULL falls back to optimiser._DEFAULT_MAX_GRAMS - a food type only needs
    -- this set when the generic default would let it dominate a solve.
    optimise_max_grams        REAL,
    -- Milestone 11: which app tab a matched offer of this food type belongs
    -- in. Distinct from archetypes.meal_kind (which classifies a composed
    -- DISH) - this classifies the food ITSELF, so 'meal' is deliberately
    -- never used here: a raw chicken fillet or a bag of rice isn't a meal on
    -- its own, it's a component of one. Authored judgement, not derived.
    meal_kind                 TEXT CHECK (meal_kind IN ('meal','snack','drink','ingredient')),
    shelf_life_days_unopened  INTEGER,
    shelf_life_days_opened    INTEGER,
    freezable                 INTEGER,
    source                    TEXT CHECK (source IN ('label','off','nevo','manual','estimated')),
    source_ref                TEXT,
    confidence                TEXT CHECK (confidence IN ('seed','high','medium','low'))
);

-- Alternative spellings the matcher accepts for a food type.
CREATE TABLE IF NOT EXISTS food_type_aliases (
    food_type_id  INTEGER NOT NULL REFERENCES food_types(id) ON DELETE CASCADE,
    alias         TEXT NOT NULL,
    PRIMARY KEY (food_type_id, alias)
);

CREATE TABLE IF NOT EXISTS products (
    id             INTEGER PRIMARY KEY,
    chain          TEXT NOT NULL,
    sku            TEXT NOT NULL,
    name           TEXT NOT NULL,
    brand          TEXT,
    raw_unit_text  TEXT,
    unit_size_g    REAL,
    unit_size_ml   REAL,
    -- Mass money is divided by: drained beats net (section 3.1).
    cost_basis_g   REAL,
    ean            TEXT,
    category       TEXT,
    -- Milestone 15. `category` stays the top-level department, because
    -- match_overrides.yaml's non_rankable_categories matches on it and
    -- changing its meaning would silently re-include every drogisterij SKU.
    -- The finer level goes here instead.
    subcategory    TEXT,
    -- The chain's OWN CDN url, never rehosted (PLAN-V2 section 3.3). One url
    -- plus the rendition width it was picked at, so Coil can size a request
    -- without the app re-deriving it from a query string it does not own.
    image_url      TEXT,
    image_width    INTEGER,
    food_type_id   INTEGER REFERENCES food_types(id),
    match_method   TEXT,
    match_score    REAL,
    url            TEXT,
    first_seen     TEXT NOT NULL,
    UNIQUE (chain, sku)
);

-- Per-SKU label macros (tier 1). Separate from food_types, which are generic.
CREATE TABLE IF NOT EXISTS product_macros (
    product_id        INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    protein_per_100g  REAL,
    kcal_per_100g     REAL,
    carbs_per_100g    REAL,
    fat_per_100g      REAL,
    fiber_per_100g    REAL,
    salt_per_100g     REAL,
    -- 'g' or 'ml'. Drinks are declared per 100 ml (section 2).
    basis_unit        TEXT,
    kcal_is_derived   INTEGER NOT NULL DEFAULT 0,
    source            TEXT NOT NULL,
    confidence        TEXT NOT NULL,
    observed_at       TEXT NOT NULL
);

-- Milestone 15: a full-catalogue crawl is thousands of paged requests, and
-- BRIEF section 7 caps them at 2/second. A run that dies halfway must not
-- start over - it would double the request count for nothing, which is the
-- politeness budget spent on an accident.
--
-- Progress is a table rather than a file so a half-finished crawl can be
-- inspected with the same tools as everything else, and so it survives
-- whatever killed the process.
-- No UNIQUE on (chain, started_at): `id` already identifies a crawl, and two
-- crawls sharing a second-resolution timestamp is a legitimate state that the
-- constraint turned into a crash for nothing.
CREATE TABLE IF NOT EXISTS catalogue_crawls (
    id           INTEGER PRIMARY KEY,
    chain        TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
);

-- One row per category the crawl has decided about, so a resumed run does not
-- pay the measuring requests again. `size` is NULL for a node that turned out
-- to be too big to page through and was replaced by its children.
CREATE TABLE IF NOT EXISTS catalogue_crawl_nodes (
    crawl_id  INTEGER NOT NULL REFERENCES catalogue_crawls(id) ON DELETE CASCADE,
    node      TEXT NOT NULL,
    size      INTEGER,
    PRIMARY KEY (crawl_id, node)
);

-- One row per page successfully fetched AND ingested. The pair is the unit of
-- resumption: a page recorded here is never fetched again by the same crawl.
CREATE TABLE IF NOT EXISTS catalogue_crawl_pages (
    crawl_id    INTEGER NOT NULL REFERENCES catalogue_crawls(id) ON DELETE CASCADE,
    node        TEXT NOT NULL,
    page        INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    products    INTEGER NOT NULL,
    PRIMARY KEY (crawl_id, node, page)
);

CREATE TABLE IF NOT EXISTS price_observations (
    id                    INTEGER PRIMARY KEY,
    product_id            INTEGER NOT NULL REFERENCES products(id),
    store_id              INTEGER REFERENCES stores(id),
    observed_at           TEXT NOT NULL,
    shelf_price           REAL,
    bonus_price           REAL,
    promo_mechanic        TEXT,
    promo_raw_text        TEXT,
    required_quantity     INTEGER,
    effective_unit_price  REAL,
    is_personal_offer     INTEGER NOT NULL DEFAULT 0,
    valid_from            TEXT,
    valid_to              TEXT,
    raw_response_hash     TEXT,
    UNIQUE (product_id, observed_at, promo_raw_text)
);

CREATE INDEX IF NOT EXISTS idx_obs_product ON price_observations(product_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_obs_validity ON price_observations(valid_from, valid_to);

-- Price history is the point of the tool. Make overwriting impossible.
CREATE TRIGGER IF NOT EXISTS price_observations_are_append_only
BEFORE UPDATE ON price_observations
BEGIN
    SELECT RAISE(ABORT, 'price_observations is append-only (brief section 7)');
END;

CREATE TRIGGER IF NOT EXISTS price_observations_no_delete
BEFORE DELETE ON price_observations
BEGIN
    SELECT RAISE(ABORT, 'price_observations is append-only (brief section 7)');
END;

CREATE TABLE IF NOT EXISTS needs_review (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN
                    ('unmatched_sku','unparsed_promo','macro_conflict',
                     'unit_price_mismatch','unparsed_unit_size','missing_macros',
                     'unmapped_category')),
    ref          TEXT,
    payload      TEXT NOT NULL,
    first_seen   TEXT NOT NULL,
    resolved_at  TEXT,
    UNIQUE (kind, ref)
);

-- Milestone 8: the substitution engine (brief section 4).
CREATE TABLE IF NOT EXISTS archetypes (
    id                INTEGER PRIMARY KEY,
    -- `key` is what the seed and the CLI address; `name` is display text.
    key               TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL UNIQUE,
    serving_g         REAL,
    target_protein_g  REAL,
    texture           TEXT,
    temperature       TEXT,
    -- JSON list of times of day (breakfast/lunch/snack/post_workout). Bare TEXT
    -- with no stated convention is how you get two.
    --
    -- Renamed from `meal_slots` at milestone 12: "slot" is now the customiser's
    -- word for a COMPONENT of a dish (the pasta, the sauce), which is a wholly
    -- different concept and will outnumber this one. See meal_templates below.
    day_parts         TEXT,
    max_prep_minutes  INTEGER,
    -- Milestone 9: what KIND of thing this is, not when you'd eat it (that's
    -- day_parts). Drives which macro-floor profile the optimiser applies -
    -- a drink is allowed to stay protein-forward; a meal is not. Authored
    -- judgement, same status as taste_delta_note - never derived.
    meal_kind         TEXT NOT NULL DEFAULT 'meal'
                        CHECK (meal_kind IN ('meal','snack','drink'))
);

-- How a store SKU gets bound to an archetype. Rules, not SKU ids: AH rotates
-- webshopIds, so a hand-listed id rots within weeks. `compare` resolves these
-- against current products and writes the result to sku_archetype_map, which
-- keeps the binding auditable the way `bonusrank matches` audits food types.
CREATE TABLE IF NOT EXISTS archetype_ready_made_rules (
    id            INTEGER PRIMARY KEY,
    archetype_id  INTEGER NOT NULL REFERENCES archetypes(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('food_type','contains')),
    value         TEXT NOT NULL,
    UNIQUE (archetype_id, kind, value)
);

CREATE TABLE IF NOT EXISTS compositions (
    id                     INTEGER PRIMARY KEY,
    archetype_id           INTEGER NOT NULL REFERENCES archetypes(id) ON DELETE CASCADE,
    name                   TEXT NOT NULL,
    effort_minutes         INTEGER,
    equipment              TEXT,
    similarity_confidence  TEXT CHECK (similarity_confidence IN ('high','medium','low')),
    -- Required, non-empty: never claim a composition tastes the same (copy rule 2).
    taste_delta_note       TEXT NOT NULL CHECK (trim(taste_delta_note) <> ''),
    texture_delta_note     TEXT,
    UNIQUE (archetype_id, name)
);

-- Item grams are PER SERVING of the parent archetype, not per batch. The
-- engine sums them as-is; nothing rescales a composition.
CREATE TABLE IF NOT EXISTS composition_items (
    composition_id           INTEGER NOT NULL REFERENCES compositions(id) ON DELETE CASCADE,
    food_type_id             INTEGER NOT NULL REFERENCES food_types(id),
    grams                    REAL NOT NULL,
    -- Cupboard staples (zoetstof, kruiden) never appear in a promo folder, so
    -- they have no observed price. A seeded one keeps the DIY total honest;
    -- output marks it as not coming from promo data.
    pantry_price_eur_per_kg  REAL,
    PRIMARY KEY (composition_id, food_type_id)
);

CREATE TABLE IF NOT EXISTS sku_archetype_map (
    product_id    INTEGER NOT NULL REFERENCES products(id),
    archetype_id  INTEGER NOT NULL REFERENCES archetypes(id),
    PRIMARY KEY (product_id, archetype_id)
);

-- Milestone 9: hand-authored carb/fat "companion" ingredients for an
-- archetype's optimiser candidate pool, on top of whatever its own
-- compositions already use. Not automatic - see CLAUDE.md milestone 9.
CREATE TABLE IF NOT EXISTS archetype_optimise_extras (
    archetype_id  INTEGER NOT NULL REFERENCES archetypes(id) ON DELETE CASCADE,
    food_type_id  INTEGER NOT NULL REFERENCES food_types(id),
    PRIMARY KEY (archetype_id, food_type_id)
);

-- Milestone 12: the meal customiser. An archetype is a whole dish somebody
-- wrote down; a TEMPLATE is a shape with holes in it, and the holes are filled
-- from whatever is cheap this week. "Slot" here means a COMPONENT of the dish
-- (the pasta, the sauce), never a time of day - that is archetypes.day_parts.
CREATE TABLE IF NOT EXISTS meal_templates (
    id                 INTEGER PRIMARY KEY,
    key                TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL UNIQUE,
    -- Same three kinds, same meaning, as archetypes.meal_kind - so a template
    -- can reuse the optimiser's macro-floor profile rather than inventing a
    -- second floor vocabulary in YAML.
    meal_kind          TEXT NOT NULL CHECK (meal_kind IN ('meal','snack','drink')),
    base_prep_minutes  INTEGER
);

CREATE TABLE IF NOT EXISTS template_slots (
    id           INTEGER PRIMARY KEY,
    template_id  INTEGER NOT NULL REFERENCES meal_templates(id) ON DELETE CASCADE,
    key          TEXT NOT NULL,
    name         TEXT NOT NULL,
    required     INTEGER NOT NULL DEFAULT 1,
    sort_order   INTEGER NOT NULL,
    -- Every slot must state a serving size, so no candidate can ever end up
    -- without one. A candidate overrides it where the judgement differs
    -- (200 g chopped tomatoes vs 40 g pesto are the same slot).
    default_grams  REAL NOT NULL,
    UNIQUE (template_id, key)
);

-- Deliberately NOT the composite-key shape composition_items uses: the same
-- food type may legitimately appear in two slots of one template.
CREATE TABLE IF NOT EXISTS template_slot_candidates (
    slot_id                  INTEGER NOT NULL REFERENCES template_slots(id) ON DELETE CASCADE,
    food_type_id             INTEGER NOT NULL REFERENCES food_types(id),
    -- Per serving, like composition_items.grams. The loader resolves this from
    -- the candidate's own override, or the slot's default_grams when absent.
    grams                    REAL NOT NULL,
    -- Same meaning as composition_items.pantry_price_eur_per_kg, and kept here
    -- rather than on food_types for the same reason: it is a property of "a
    -- pinch of this in this recipe", not of the food.
    pantry_price_eur_per_kg  REAL,
    -- 'seed' today. Reserved for a future tag-derived lane, so that lane can
    -- arrive through _add_column_if_missing instead of a rebuild.
    source                   TEXT,
    PRIMARY KEY (slot_id, food_type_id)
);

-- Does this combination actually make a dish? Authored judgement, same status
-- as taste_delta_note - never derived from macros, never inferred.
--
-- `template_id` is nullable, reserved for a global rule applying to every
-- template ("a dry sauce needs a fat"). The loader does not emit one yet; when
-- it does, the seed must say so explicitly so it is never accidental.
CREATE TABLE IF NOT EXISTS template_rules (
    id                INTEGER PRIMARY KEY,
    template_id       INTEGER REFERENCES meal_templates(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL CHECK (kind IN ('requirement','incompatible')),
    -- JSON predicates: {"slot": key?, "food_types": [...]?}
    when_predicate    TEXT NOT NULL,
    -- JSON list of predicates. At least `min_satisfied` of them must hold.
    -- One predicate with min_satisfied 1 is the plain "slot X must be filled"
    -- case; several is "needs meat OR greens OR cheese", which is the shape
    -- the pesto rule actually needs and a single target slot cannot express.
    requires          TEXT,
    min_satisfied     INTEGER NOT NULL DEFAULT 1,
    -- 'incomplete' (unfinished dish) and 'wrong' (these do not go together)
    -- are different messages and must not render the same; 'note' is an
    -- observation that blocks nothing. NOT NULL + CHECK, so it cannot be
    -- added later by _add_column_if_missing - see its docstring.
    severity          TEXT NOT NULL CHECK (severity IN ('incomplete','wrong','note')),
    -- Why, in the author's own words. Non-empty, like taste_delta_note.
    note              TEXT NOT NULL CHECK (trim(note) <> '')
);
"""


# The milestone-8 tables grew columns after they were first created (empty) at
# milestone 3. `CREATE TABLE IF NOT EXISTS` cannot add a column, so a database
# from before that change needs these rebuilt. They hold seed data only - every
# row comes back from `bonusrank seed` - so dropping them loses nothing, and
# price_observations is never touched.
_MILESTONE_8_TABLES = (
    "composition_items", "compositions", "archetype_ready_made_rules",
    "sku_archetype_map", "archetype_optimise_extras", "archetypes",
)

# Same reasoning, its own probe. Kept separate from _MILESTONE_8_TABLES on
# purpose: conflating them would make a pre-milestone-8 database needlessly
# drop templates, and a template schema change needlessly drop archetypes.
# Each probe stays honest about which change it detects. Children first.
_MILESTONE_12_TABLES = (
    "template_rules", "template_slot_candidates", "template_slots", "meal_templates",
)


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database, creating the schema if needed."""
    target = path or DB_PATH
    if target != Path(":memory:"):
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if _needs_archetype_rebuild(conn):
        for table in _MILESTONE_8_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)
        conn.commit()
    if _needs_template_rebuild(conn):
        for table in _MILESTONE_12_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)
        conn.commit()
    _widen_review_kinds(conn)
    _add_column_if_missing(conn, "food_types", "optimise_max_grams", "REAL")
    _add_column_if_missing(conn, "food_types", "meal_kind", "TEXT")
    # Milestone 15. All nullable with no default, so no rebuild is needed.
    _add_column_if_missing(conn, "products", "subcategory", "TEXT")
    _add_column_if_missing(conn, "products", "image_url", "TEXT")
    _add_column_if_missing(conn, "products", "image_width", "INTEGER")
    conn.commit()
    return conn


def _widen_review_kinds(conn: sqlite3.Connection) -> None:
    """Rebuild needs_review when its CHECK predates a new review kind.

    SQLite can't alter a CHECK constraint. The table is copied rather than
    dropped: unlike the seed tables above, its rows are real review history.
    """
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='needs_review'").fetchone()[0]
    if "unmapped_category" in sql:
        return
    conn.execute("ALTER TABLE needs_review RENAME TO needs_review_old")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO needs_review SELECT * FROM needs_review_old")
    conn.execute("DROP TABLE needs_review_old")
    conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """`CREATE TABLE IF NOT EXISTS` cannot add a column to an existing table.

    Used only for nullable, no-default additions - a NOT NULL column still
    needs the full rebuild path `_needs_archetype_rebuild` uses.
    """
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _needs_archetype_rebuild(conn: sqlite3.Connection) -> bool:
    """True when `archetypes` predates the `key`, `meal_kind` or `day_parts` column."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(archetypes)")}
    return bool(columns) and not {"key", "meal_kind", "day_parts"} <= columns


def _needs_template_rebuild(conn: sqlite3.Connection) -> bool:
    """True when the milestone-12 template tables predate their newest columns.

    False when they do not exist yet - `CREATE TABLE IF NOT EXISTS` handles
    that case, and dropping nothing is not a rebuild. Probe the most recently
    added column of each table here when the schema grows again.
    """
    templates = {row["name"] for row in conn.execute("PRAGMA table_info(meal_templates)")}
    if not templates:
        return False
    slots = {row["name"] for row in conn.execute("PRAGMA table_info(template_slots)")}
    rules = {row["name"] for row in conn.execute("PRAGMA table_info(template_rules)")}
    return "default_grams" not in slots or "severity" not in rules


def record_review(
    conn: sqlite3.Connection, kind: str, ref: str | None, payload: str, observed_at: str
) -> None:
    """Queue something for human review. Never guessed around, never silent."""
    conn.execute(
        "INSERT INTO needs_review (kind, ref, payload, first_seen) VALUES (?,?,?,?) "
        "ON CONFLICT (kind, ref) DO NOTHING",
        (kind, ref, payload, observed_at),
    )
