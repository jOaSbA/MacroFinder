# Bonusrank — project brief & research dossier

A personal tool that tracks Dutch supermarket promotions (AH, Jumbo, Aldi) and answers
one question every week: **what is the cheapest way for me to hit my protein target?**

This document exists so the coding agent does **not** need to do discovery research.
Everything below was verified externally. Where something is uncertain it is marked
`VERIFY`. Read this fully before writing code.

---

## 0. Context about the user

- Student, lives at home, cooks **one meal a day for himself** (usually dinner).
- Breakfast must be high protein, cold, and fast (<5 min).
- Wants "quick supplements to the diet" — grab-and-eat protein, no prep.
- Budget-constrained. Shops at Albert Heijn, Jumbo, Aldi. Lidl is **out of scope**.
- Realistically visits **1–2 stores per week**, not four.

---

## 1. Data sources — verified endpoints

### 1.1 Albert Heijn

**Base:** `https://api.ah.nl/` (also `https://ms.ah.nl`)

**Auth — anonymous token, no account needed:**
```
POST https://api.ah.nl/mobile-auth/v1/auth/token/anonymous
Body: {"clientId": "appie"}
```
Returns a bearer token. Refresh via `mobile-auth/v1/auth/token/refresh`.

**Endpoints under `mobile-services/`:**

| Path | Purpose |
|---|---|
| `bonuspage/v1/metadata` | Bonus period structure & segment ids |
| `bonuspage/v1/bonus-folder` | The bonus folder — main promo listing |
| `bonuspage/v1/segment` | Products within a bonus segment |
| `bonuspage/v1/personal` | Personal offers — **flag these, not universal** |
| `discover/v1/bonus` | Alternative bonus discovery lane |
| `product/search/v2` | Product search |
| `product/search/v1/gtin/{barcode}` | Lookup by EAN |
| `product/detail/v4/fir/{webShopId}` | **Product detail incl. nutrition.** `fir` = EU Food Information Regulation (1169/2011), which mandates the nutrition declaration |
| `v1/product-shelves/categories` | Category tree |
| `v1/product-shelves/categories/{id}/sub-categories` | Subcategories |

**Nutrition field names** — AH returns a Dutch-keyed structure. Observed keys:

```
"Energie":            "2244 kJ (538 kcal)"   <- must parse kcal out of the parens
"Eiwitten":           "6.4 g"
"Koolhydraten":       "54 g"
"Waarvan suikers":    "2.7 g"
"Vet":                "32 g"
"Waarvan verzadigd":  "3.9 g"
"Voedingsvezel":      "4.8 g"
"Zout":               "1.2 g"
```

Values are **strings with units**, not numbers. Energy is dual kJ/kcal in one string.
Write a dedicated parser with tests. Also seen on product records:
`discount_type` (e.g. `"2 voor 2.00"`), `discount_period` (e.g. `"vanaf maandag"`),
`is_discounted`, `price_current`, `price_previous`, `unit_size`, `brand`, `category`.

Product ids look like `wi193679`. Web URL form:
`https://www.ah.nl/producten/product/{id}/{slug}`

Reference implementation worth reading (do not vendor it, just read):
`AppiePy` on PyPI — shows the parsed shape of an AH product.

### 1.2 Jumbo

**Base:** `https://mobileapi.jumbo.com/` (versioned in path on some deployments —
`VERIFY` whether a `/v17/` style prefix is currently required)

| Path | Purpose |
|---|---|
| `promotion-overview` | **Primary promo feed** |
| `promotion-tabs` | Promo tab structure |
| `promotion-tabs/{id}/{runtimeId}` | Promos within a tab/runtime window |
| `promotion/{id}` | Single promotion detail |
| `products` | Product list |
| `products/{id}` | Product detail |
| `products/{id}/alternatives` | **Useful for the substitution engine** |
| `search` | Search |
| `categories` | Category tree |
| `stores` | Store locator — needed, promos have store scope |

Jumbo's `runtimeId` concept encodes the promo validity window. Capture it.

### 1.3 Aldi NL

**Base:** `https://webservice.aldi.nl/api/v1/`

| Path | Purpose |
|---|---|
| `products.json` | Category tree |
| `products/{category}/{subcategory}.json` | Products in a category |
| `articles/products/{path}/{articleId}.json` | Article detail |
| `promotions.json` | **Promotions list** |
| `promotions/{promotionId}{region}.json` | Promotion detail, region-scoped |
| `flyer.json` | Weekly folder |
| `articlesearch/{query}.json` | Search |

`VERIFY`: Aldi NL has been migrating to a Next.js frontend. If `webservice.aldi.nl`
returns 404/410, fall back to fetching the offers page and parsing the embedded
`__NEXT_DATA__` JSON blob — no browser automation needed either way. Try the
webservice API first; it is cleaner.

Note Aldi promos are **region-scoped**. Determine the user's region once, store it
in config.

### 1.4 Out of scope

Lidl has no public product API and the community consensus is that there is no
usable product data endpoint. Do not attempt it. Picnic, Plus and Coop endpoints
exist (see `Repsay/supermarket-mobile-api-connector` → `endpoints.md`) if the user
ever wants them; do not build them now.

---

## 2. Nutrition data sources

Three tiers, in priority order. Each macro row records **which tier it came from**.

### Tier 1 — the store's own FIR data
AH `product/detail/v4/fir/{webShopId}` gives label nutrition for that exact SKU.
This is the most accurate source because it is the actual product. Prefer it always.

### Tier 2 — Open Food Facts (by EAN)
Free, keyless, no auth:
```
GET https://world.openfoodfacts.org/api/v2/product/{barcode}
    ?fields=product_name,brands,quantity,nutriments,nutrition_grades
```
Response `nutriments` contains `proteins_100g`, `energy-kcal_100g`,
`carbohydrates_100g`, `fat_100g`, `fiber_100g`, `salt_100g` as **numbers**.
Coverage for Dutch huismerk products is patchy — expect misses, handle `status: 0`.
Be polite: OFF is a nonprofit. Cache aggressively, rate-limit hard, set a real
`User-Agent` identifying the app and a contact.

### Tier 3 — NEVO (RIVM), the Dutch national food composition database
- Current version: **NEVO-online 2025/9.0**, ~2328 foods, ~130 nutrients.
- Free download as a dataset after accepting the usage conditions at rivm.nl.
- Composition is expressed **per 100 g edible portion** (e.g. meat without bone).
  A handful of items are **per 100 ml** — this is stated in the food's name.
- Contains **generic**, not brand-specific, foods.

NEVO is the right authority for `food_types` (generic "magere kwark", "kipfilet
rauw", "linzen gedroogd"). It is the seed source. Cite the NEVO code in the
`source` column so numbers are traceable.

**Do not commit the NEVO dataset to the repo** — it has usage conditions attached.
Keep it in `data/external/` and gitignore it; ship a loader script instead.

---

## 3. The hard parts of the domain model

These are where the project will actually break. Read carefully.

### 3.1 Mass, volume, and the four different "weights"

A product's printed weight is usually **not** the mass you should divide protein by.
Every `food_type` carries:

| Field | Meaning | Example |
|---|---|---|
| `state` | `solid` / `liquid` / `countable` | |
| `density_g_per_ml` | For liquids, to convert ml → g | melk 1.03, yoghurt 1.03, olie 0.92 |
| `drained_fraction` | uitlekgewicht ÷ netto gewicht | kikkererwten blik ≈ 0.60, tonijn blik ≈ 0.75 |
| `edible_fraction` | after removing bone/shell/peel | ei in schaal ≈ 0.88, kip met bot ≈ 0.70 |
| `dry_to_cooked_factor` | mass multiplier when cooked | rijst ≈ 2.5, pasta ≈ 2.2, linzen ≈ 2.4, havermout ≈ 3.0 |
| `g_per_unit` | for countables | ei M ≈ 58 g bruto, wrap ≈ 62 g |

**Two rules that must not be conflated:**

1. **Cost metrics use purchased, edible, drained mass.**
   Cooking adds water. Water is free and contains no protein. €/g protein for dry
   rice uses the *dry* weight. Canned chickpeas use the *drained* weight, because
   you pay for brine you pour away.
2. **Portion sizes in recipes use as-served mass.**
   "80 g dry pasta" and "176 g cooked pasta" are the same thing; the UI must be
   explicit about which it means.

Canned legumes are the single biggest trap. A 400 g tin of kikkererwten with a
240 g drained weight will show ~40% better protein-per-euro than reality if you
use net weight.

### 3.2 Promotion mechanics

Dutch promo strings are a small, closed vocabulary. Parse into a typed enum with
both an **effective multiplier** and a **required quantity** — these are different
and both matter.

| Enum | Dutch string examples | Effective | Min qty |
|---|---|---|---|
| `PERCENT_OFF` | `25% korting`, `Alles 35% korting` | 0.75 | 1 |
| `SECOND_HALF_PRICE` | `2e halve prijs` | 0.75 | 2 |
| `ONE_PLUS_ONE_FREE` | `1+1 gratis` | 0.50 | 2 |
| `TWO_PLUS_ONE_FREE` | `2+1 gratis` | 0.667 | 3 |
| `X_FOR_Y` | `2 voor 3.00`, `3 voor 5.00` | computed | X |
| `FIXED_PRICE` | `nu 1.99` (was 2.99) | computed | 1 |
| `SECOND_PERCENT_OFF` | `50% korting op de 2e` | computed | 2 |
| `BULK_TIER` | `vanaf 3 stuks 30% korting` | computed | 3 |
| `PERSONAL` | AH Extra's / Bonusbox, Jumbo personal | computed | varies |
| `NOT_A_PROMO` | `Prijsfavoriet`, `Elke dag lage prijs` | 1.0 | 1 |

Hard requirements:
- `PERSONAL` offers are **not available to everyone**. Tag them and let the user
  filter them out. Never mix them into headline rankings silently.
- Any unparsed mechanic goes to a review queue. **Never** silently default to
  "no discount" or "assume 25%".
- Report both `effective_unit_price` and `required_quantity` in every output. A
  1+1 gratis on 1 kg kwark is excellent €/protein *and* means 2 kg of kwark in a
  fridge, which is the next problem.

### 3.3 Waste adjustment

A deal you throw away is not a deal. Each `food_type` needs
`shelf_life_days_unopened`, `shelf_life_days_opened`, and `freezable: bool`.

```
realistically_consumable = min(required_qty,
                               floor(daily_consumption_g * effective_shelf_life
                                     / unit_size_g))
waste_adjusted_price = total_promo_cost / (realistically_consumable * unit_size_g)
```

Freezable items (kipfilet, brood, wraps) get shelf life extended to the freezer
horizon. Kwark does not freeze well — mark it.

Surface both numbers. "€0.019/g protein, but only €0.031/g if you can't eat 2 kg
of kwark in 10 days" is the honest answer.

### 3.4 Is it actually a deal? (price history)

Store every observation; never overwrite. Then:

- **Percentile**: where does this bonus price sit against the last N weeks of
  observed prices for this SKU? "Cheapest in 14 weeks" beats "25% korting".
- **Reference-price inflation**: if `shelf_price` rose within 28 days before a
  promo started, flag `reference_inflated` and rank on absolute price, not % off.
- **Cycle prediction**: per SKU, record promo start dates, take the median
  interval, predict the next one. Output a `buy` / `wait` hint:
  *"Goes on bonus every ~4 weeks, last promo 3 weeks ago — wait."*
- **Stock-up advice**: non-perishable + at historic low → suggest buying N weeks'
  supply, bounded by the required quantity and by storage sanity.

---

## 4. The substitution engine (the interesting feature)

The user's actual ask: *"kwark plus this milk plus some fruit tastes the same, has
more protein, and is cheaper — tell me that."*

### 4.1 Model it around archetypes, not products

An **archetype** is a thing you want, independent of who sells it.

```yaml
archetype: chocolate_protein_pudding
  serving_g: 200
  target_protein_g: 20
  texture: creamy_spoonable
  temperature: cold
  sweetness: medium
  meal_slots: [breakfast, snack]
  max_prep_minutes: 5
```

Two ways to satisfy an archetype:

1. **`ReadyMade`** — a SKU that *is* this thing (Arla Protein pudding, etc.)
2. **`Composition`** — a recipe of `food_type` quantities that approximates it

The engine prices both from current promo data and compares.

### 4.2 Output shape

```
Chocolate protein pudding — 200 g serving

  Ready-made   Arla Protein pudding chocolade   €1.89   20 g P   €0.095/g P   0 min
  DIY          250 g magere kwark (AH, 1+1)
               + 8 g cacaopoeder
               + zoetstof                        €0.72   27 g P   €0.027/g P   3 min

  → DIY is 62% cheaper and +7 g protein, costs 3 minutes.
    Taste delta: less sweet, tangier. Add 5 g honing to close the gap (+15 kcal).
```

### 4.3 Be honest about taste — do not compute it

Similarity between a DIY composition and a store product **cannot be derived** from
macros. It must be authored metadata on the `Composition`:

- `similarity_confidence: high | medium | low`
- `taste_delta_note: "less sweet, tangier"` — a required, non-empty string
- `texture_delta_note`
- `flavour_tags` / `texture_tags` for filtering

**Never emit "tastes the same."** Emit what differs. A suggestion that overclaims
once will make the user distrust the whole tool.

### 4.4 Seed compositions worth shipping

High-value DIY-beats-store-bought cases in the Dutch market:

| Archetype | Ready-made | DIY composition |
|---|---|---|
| Chocolade proteïne pudding | Arla/Melkunie protein pudding | magere kwark + cacao + zoetstof |
| Proteïne drinkyoghurt | Arla Protein drink | magere kwark + halfvolle melk + vanille |
| Proteïne reep | Barebells / Quest | havermout + whey + pindakaas, no-bake |
| Proteïne shake | kant-en-klare shake | whey + melk, or kwark + melk |
| Skyr met fruit | Skyr fruitvariant | naturel skyr + diepvriesfruit (much cheaper per g) |
| Hüttenkäse spread | kruidenkwark/dip | hüttenkäse + kruiden + knoflook |
| Kip-wrap lunch | kant-en-klare wrap | wrap + kipfilet + hüttenkäse + sla |
| Overnight oats | kant-en-klare pot | havermout + kwark + melk + fruit |

Flavour-variant products (fruit skyr vs naturel skyr) are almost always the single
biggest easy win — the fruit portion is tiny and the markup is large.

### 4.5 Reverse direction too

Also detect when **ready-made wins**: eggs at a deep promo can beat any composition,
and canned tuna often beats fresh. The engine must be willing to say "just buy it."

---

## 5. The weekly optimiser

**Inputs** (all from user config, none hardcoded):
daily protein target, daily kcal **floor**, weekly budget, meals cooked per day,
store whitelist, max stores per week, dislikes/allergies, max prep minutes per
meal slot.

**Output**: shopping list + which promos to use + what to eat, per meal slot.

Formulate as an integer linear program (`pulp` is fine at this scale). Constraints:

- weekly protein ≥ target × 7
- weekly kcal ≥ floor × 7
- **variety cap**: max N servings of any one `food_type` per week (default 7)
- promo `required_quantity` is integer — you cannot buy half of a 1+1
- perishability: quantity bought ≤ realistically consumable (§3.3)
- stores used ≤ max_stores
- respect per-meal-slot prep time limits

Objective: minimise total cost.

### Two non-negotiable safety rules for the optimiser

1. **Calories are a floor, never an objective.** The cheapest way to hit a protein
   target is always a low-calorie one, so an unconstrained cost-minimising solver
   will quietly produce a starvation diet. Hard-constrain kcal from below and never
   put kcal in the objective function with a negative coefficient.
2. **No solution ships without a plausibility check.** If the plan has the user
   eating the same food more than the variety cap, or eating under the kcal floor,
   or eating 3 kg of anything, reject it and re-solve. Print the rejection reason.

This tool exists to make eating enough cheaper, not to make eating less cheaper.
Keep that distinction visible in the code and in the output copy.

---

## 6. Data model

```
stores            id, name, chain, region, store_number

products          id, store, sku, name, brand, raw_unit_text, unit_size_g,
                  unit_size_ml, ean, food_type_id (nullable), url, first_seen

price_observations  id, product_id, observed_at, shelf_price, bonus_price,
                    promo_mechanic (enum), promo_raw_text, required_quantity,
                    effective_unit_price, is_personal_offer, valid_from, valid_to,
                    store_id, raw_response_hash

food_types        id, name_nl, name_en, state, density_g_per_ml, drained_fraction,
                  edible_fraction, dry_to_cooked_factor, g_per_unit,
                  protein_per_100g, kcal_per_100g, carbs_per_100g, fat_per_100g,
                  fiber_per_100g, shelf_life_days_unopened, shelf_life_days_opened,
                  freezable, source (enum), source_ref, confidence

archetypes        id, name, serving_g, target_protein_g, texture, temperature,
                  meal_slots, max_prep_minutes

compositions      id, archetype_id, name, effort_minutes, equipment,
                  similarity_confidence, taste_delta_note, texture_delta_note

composition_items composition_id, food_type_id, grams

sku_archetype_map product_id, archetype_id   -- ready-made fulfilments

needs_review      id, kind (unmatched_sku | unparsed_promo | macro_conflict),
                  payload, first_seen, resolved_at
```

`source` enum: `label` (store FIR data) > `off` (Open Food Facts) > `nevo` >
`manual` > `estimated`.

**Macro conflict rule:** if two sources disagree by more than 20% on protein,
write a `macro_conflict` row and use the higher-priority source, but mark
`confidence: low` so the UI can show it.

---

## 7. Engineering constraints

- Python 3.11+, `uv` for dependency management.
- `httpx` for HTTP, `pydantic` for models, SQLite via stdlib `sqlite3`.
- `pulp` for the optimiser. `pytest` for tests.
- CLI first. **No web frontend in this phase.**
- One adapter module per chain implementing a shared `StoreAdapter` protocol:
  `fetch_promotions() -> list[RawOffer]` and `fetch_product(sku) -> RawProduct`.
  Adding a chain must mean adding one file and registering it, nothing else.
- **Persist raw JSON responses to disk before parsing**, keyed by
  `{chain}/{endpoint}/{iso_date}.json`. Re-parsing history without re-scraping is
  the single most valuable property of this codebase — schemas will drift and you
  will want to fix a parser and replay.
- Append-only price observations. Never UPDATE a price row.

### Politeness — non-negotiable

- Max 2 requests/second per chain. Exponential backoff on 429/5xx.
- Cache responses on disk for 6 hours minimum.
- Set a real, identifying `User-Agent`. **Do not spoof the official mobile app's
  User-Agent.** This is a personal-use tool; it should be honest about being one.
- Open Food Facts is a nonprofit — cache harder there, and never bulk-sweep it.
- These are undocumented endpoints being used against the operators' terms. That
  is a tolerable position for a single personal user making a few hundred requests
  a week. It stops being tolerable if this is ever deployed as a public service,
  so do not add multi-user features without revisiting this.

### Testing priorities

Write tests **before** the implementation for these three, in this order — they are
where the bugs will be:

1. Unit-size parser: `"1 kg"`, `"500 g"`, `"6 x 125 g"`, `"1,5 L"`, `"per stuk"`,
   `"ca. 300 g"`, `"400 g (uitlekgewicht 240 g)"`, `"2 x 200 ml"`.
2. Nutrition string parser: `"2244 kJ (538 kcal)"` → `538`; `"6.4 g"` → `6.4`;
   `"< 0,5 g"` → `0.5` with a flag; comma decimals throughout.
3. Promo mechanic parser: the full table in §3.2, plus unknown-string handling.

**Cross-check**: stores publish their own unit price ("prijs per kilo €6.49").
Compare it against your computed unit price on every ingest. A mismatch above 2%
is a parser bug — log it loudly.

### Other gotchas

- Bonus weeks **do not align** across chains. Never assume a weekly cycle; always
  filter on `valid_from` / `valid_to`.
- Dutch decimal commas appear in both prices and nutrition values.
- AH product ids are `wi`-prefixed strings, not integers. Do not cast.
- Some AH "products" are statiegeld/deposit entries. Filter them out.
- Store the raw promo text alongside the parsed enum, always.

---

## 8. Milestones

Stop after each and show output. Do not build ahead.

1. **AH adapter only.** Anonymous auth, fetch bonus folder, print raw offer count
   and 5 sample offers. Persist raw JSON. Nothing else.
2. **Parsers + tests.** Unit size, nutrition strings, promo mechanics. Tests first.
   Show the test output and the parse results on real fetched data.
3. **SQLite schema + ingest.** Show a row count and one fully populated record,
   including a promo with `required_quantity > 1`.
4. **`food_types` seed.** ~120 Dutch staples, NEVO-sourced where possible, with
   every field in §3.1 populated. Leave gaps rather than guessing; anything
   uncertain gets `confidence: low` and a `needs_review` row.
5. **Matcher.** SKU name → `food_type`, fuzzy with a manual override YAML.
   Unmatched → `needs_review`, never guessed.
6. **Ranking CLI.** `bonusrank list --sort protein-per-euro --store ah`
   Shows €/100 g protein, €/1000 kcal, required quantity, waste-adjusted price,
   and a history percentile once data exists.
7. **Jumbo adapter**, then **Aldi adapter**.
8. **Archetypes + compositions.** Seed the table in §4.4. `bonusrank compare`.
9. **Optimiser.** `bonusrank plan --week` with the §5 constraints and both safety
   rules enforced and tested.

---

## 9. Output copy rules

- Never display a macro value sourced as `estimated` without visibly marking it.
- Never claim a DIY composition "tastes the same" — state the delta.
- Always show required quantity next to a promo price.
- Always show the waste-adjusted price next to the headline price for perishables.
- Prefer "cheapest in N weeks" over "X% off" as the headline signal.
