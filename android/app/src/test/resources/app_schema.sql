
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
    macro_confidence          TEXT
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
