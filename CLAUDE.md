# CLAUDE.md — bonusrank

Personal tool: track Dutch supermarket promos (AH, Jumbo, Aldi), rank by
protein-per-euro, answer "cheapest way to hit my protein target this week".

**The full brief is `docs/BRIEF.md`. Read it before non-trivial work.** This file is
the subset that must survive a context reset: engineering constraints (brief §7),
output copy rules (§9), optimiser safety rules (§5), and the endpoint state verified
on 2026-09-16.

Single user, personal use, CLI only. Not a service.

---

## 1. Engineering constraints (brief §7)

**Stack — decided, do not re-litigate.** Python 3.11+, `uv` for deps, `httpx` for
HTTP, `pydantic` for models, SQLite via stdlib `sqlite3`, `pulp` for the optimiser,
`pytest` for tests. CLI first — **no web frontend in this phase.**

**Adapters.** One module per chain in `src/bonusrank/adapters/`, implementing the
`StoreAdapter` protocol: `fetch_promotions() -> list[RawOffer]` and
`fetch_product(sku) -> RawProduct`. Adding a chain must mean **adding one file and
registering it, nothing else.** No chain-specific branching outside its own module.

**Raw before parsed.** Persist every raw JSON response to disk *before* parsing,
keyed `data/raw/{chain}/{endpoint}/{iso_date}.json`. Re-parsing history without
re-scraping is the single most valuable property of this codebase — schemas will
drift and you will want to fix a parser and replay. Never parse a response you
haven't written down first.

**Append-only prices.** Every price observation is a new row. **Never `UPDATE` a
price row.** Price history is the point of the tool.

### Politeness — non-negotiable

- **Max 2 requests/second per chain.** Exponential backoff on 429/5xx.
- **Cache responses on disk for at least 6 hours.** A re-run inside the window must
  hit disk, not the network.
- **Set a real, identifying `User-Agent`. Do NOT spoof the official mobile app.**
  This is a personal-use tool; it should be honest about being one.
- Open Food Facts is a nonprofit — cache harder there, and never bulk-sweep it.
- These are undocumented endpoints used against the operators' terms. Tolerable for
  one personal user making a few hundred requests a week. **Not** tolerable as a
  deployed service — do not add multi-user features without revisiting this.

### Testing priorities — tests BEFORE implementation

In this order; this is where the bugs will be.

1. **Unit-size parser**: `"1 kg"`, `"500 g"`, `"6 x 125 g"`, `"1,5 L"`, `"per stuk"`,
   `"ca. 300 g"`, `"400 g (uitlekgewicht 240 g)"`, `"2 x 200 ml"`.
2. **Nutrition string parser**: `"2244 kJ (538 kcal)"` to `538`; `"6.4 g"` to `6.4`;
   `"< 0,5 g"` to `0.5` **with a flag**; comma decimals throughout.
3. **Promo mechanic parser**: the full §3.2 table, plus unknown-string handling.

**Cross-check on every ingest**: stores publish their own unit price ("prijs per kilo
€6.49"). Compare it against the computed unit price. **A mismatch above 2% is a
parser bug — log it loudly.**

### Gotchas

- **Bonus weeks do not align across chains.** Never assume a weekly cycle; always
  filter on `valid_from` / `valid_to`.
- Dutch decimal commas appear in both prices and nutrition values.
- AH product ids are `wi`-prefixed strings (`wi193679`) — **do not cast to int**.
- Filter out AH statiegeld/deposit entries.
- **Always store the raw promo text alongside the parsed enum.**
- Unknown means unknown. **Never fabricate a macro value.** Unparsed mechanics go to
  `needs_review` — never silently default to "no discount" or "assume 25%".

---

## 2. Output copy rules (brief §9)

These govern every line the CLI prints.

1. Never display a macro value sourced as `estimated` **without visibly marking it.**
2. Never claim a DIY composition **"tastes the same"** — state the delta. A
   suggestion that overclaims once will make the user distrust the whole tool.
3. **Always show required quantity** next to a promo price. A 1+1 gratis on 1 kg
   kwark is excellent €/protein *and* means 2 kg of kwark in a fridge.
4. **Always show the waste-adjusted price** next to the headline price for
   perishables.
5. Prefer **"cheapest in N weeks"** over "X% off" as the headline signal.

Corollary from §3.2: `PERSONAL` offers (AH Extra's/Bonusbox, Jumbo personal) are not
available to everyone. **Tag them, let the user filter them out, and never mix them
into headline rankings silently.**

---

## 3. Optimiser safety rules (brief §5) — non-negotiable

1. **Calories are a floor, never an objective.** The cheapest way to hit a protein
   target is always a low-calorie one, so an unconstrained cost-minimising solver
   will quietly produce a starvation diet. Hard-constrain kcal from below and
   **never put kcal in the objective function with a negative coefficient.**
2. **No solution ships without a plausibility check.** If the plan has the user
   eating the same food more than the variety cap, or eating under the kcal floor,
   or eating 3 kg of anything — **reject it and re-solve. Print the rejection
   reason.**

> This tool exists to make eating *enough* cheaper, not to make eating *less*
> cheaper. Keep that distinction visible in the code and in the output copy.

---

## 4. Verified endpoint state — checked 2026-09-16

The brief's §1 endpoint table has drifted. Verified live:

### Albert Heijn — working

| Path (under `https://api.ah.nl/`) | State |
|---|---|
| `mobile-auth/v1/auth/token/anonymous` POST `{"clientId":"appie"}` | works, no account. TTL ~7 days |
| `mobile-services/bonuspage/v3/metadata` | **replaces the brief's `v1/metadata`** (v1 and v2 return HTTP 500) |
| `mobile-services/bonuspage/v2/section?application=AHWEBSHOP&date=&promotionType=&category=` | **the real promo listing lane** |
| `mobile-services/bonuspage/v2/segment?segmentId=` | SKU-level products (`v1/segment` demands a `date` param) |
| `mobile-services/discover/v1/bonus` | works, but returns only the 4-item SPOTLIGHT section — not a full listing |
| `mobile-services/product/detail/v4/fir/{webshopId}` | works **only with the `X-Application` header** (see below) |
| `mobile-services/product/search/v2?query=` | same — needs the header, not a query param |
| `mobile-services/bonuspage/v1/bonus-folder` | exists but requires an undiscovered `folder` param. Superseded — do not use |

**The AH access pattern is two-level and must stay that way:**
`v3/metadata` gives per-period `tabs[].urlMetadataList[].url` (section URLs, each
with a `count`). Those sections return **`bonusGroup`** objects — a *segment*, i.e.
one promotion such as "Alle Melkunie Breaker" — with **`products: []` empty**.
`v2/segment?segmentId=` expands a segment into actual SKUs. **Never assume a section
gives you SKUs.**

Do not hardcode section URLs — **always read them from `v3/metadata`**. They carry
the period `date` and change weekly.

`discountLabels[]` on a bonusGroup is a **typed** mechanic (`code`,
`defaultDescription`, `price`). **Prefer it over regexing the Dutch
`discountDescription` string** — that headline is sometimes `None` while the label
still carries the numbers. Store both. All 11 codes seen across 232 offers:

| Code | n | Maps to |
|---|---|---|
| `DISCOUNT_PERCENTAGE` | 77 | `PERCENT_OFF` |
| `DISCOUNT_X_FOR_Y` | 43 | `X_FOR_Y` (`2 voor 0.99`) |
| `DISCOUNT_FIXED_PRICE` | 41 | `FIXED_PRICE` |
| `DISCOUNT_X_PLUS_Y_FREE` | 30 | `X_PLUS_Y_FREE` — **1+1, 2+1, 2+2 and 5+1 all occur**, so handle X+Y generally |
| `DISCOUNT_ONE_HALF_PRICE` | 12 | `SECOND_HALF_PRICE` |
| `DISCOUNT_ACTION` | 8 | **nothing — no number anywhere. Review.** |
| `DISCOUNT_FALLBACK` | 7 | `FIXED_PRICE` — generic `ACTIE`/`BONUS` headline but a **real price** in `defaultDescription`. Not an unknown |
| `DISCOUNT_BONUS` | 6 | **nothing — review.** |
| `DISCOUNT_AMOUNT` | 5 | `AMOUNT_OFF` (`€1.50 euro korting`) |
| `DISCOUNT_WEIGHT` | 2 | `PRICE_PER_WEIGHT` (`per 100 GRAM voor €1.69`) — priced **by weight, not by pack**; needs the pack mass |
| `DISCOUNT_PERCENTAGE_PER_AMOUNT` | 1 | `BULK_TIER` (`10% korting per 2 STUKS`) |

The `Uit de Bonusfolder` SPOTLIGHT section appears in **both** tabs — **dedupe on
`segmentId`** or you will double-count.

**`X-Application: AHWEBSHOP` must be sent as a HEADER on the product lanes.**
Without it `product/detail/v4/fir` and `product/search/v2` return HTTP 500
(`Can not find application: 'null'`) even with a valid token. The bonuspage lanes
take `application` as a *query parameter* instead, and `v3/metadata` already embeds
it in the section URLs it hands out. Costly to rediscover: a 500 looks like an
outage, and the client's 5xx backoff will burn four retries per call before giving
up. `AHAdapter._auth_headers()` sends it on every request.

Anonymous auth yields **no personal offers**; `bonuspage/v1/personal` needs a member
session. Personal offers are out of reach for now — which is fine, since they must be
filtered out of headline rankings anyway.

### AH nutrition is GS1, not Dutch strings

Brief section 1.1 documents nutrition as a Dutch-keyed table of strings
(`"Eiwitten": "6.4 g"`). **That is not what the FIR endpoint returns.** It returns
GS1/GDSN structured data at `tradeItem.nutritionalInformation.nutrientHeaders[]`,
with **numeric** values keyed by GS1 nutrient code:

| Code | Meaning | | Code | Meaning |
|---|---|---|---|---|
| `ENER-` | energy — **appears twice**, once per unit (kcal, kJ) | | `FIBTG` | fibre |
| `PRO-` | protein | | `SALTEQ` | salt |
| `CHOAVL` | carbohydrate | | `FAT` | fat |
| `SUGAR-` | of which sugars | | `FASAT` | of which saturated |

`nutrientBasisQuantity` states what the values are per — usually 100 g, but **100 ml
for drinks**, which is exactly the trap brief section 2 warns about. Never assume g.

Both shapes are parsed: `parse_gs1_nutrition` for this, `parse_nutrition_block` for
the string form (still needed for Open Food Facts, other chains, older snapshots).

### Jumbo — unblocked 2026-09-17, adapter shipped

The 2026-09-16 finding was correct but stale: `mobileapi.jumbo.com` really is
dead (404 on every path). It is not what serves `jumbo.com` any more. Jumbo
rebuilt on a public Nuxt web app, and that app is **not** behind meaningful bot
protection for this purpose:

- The **full weekly listing (~140 promotions) is server-rendered**, embedded in
  a `<script id="__NUXT_DATA__">` tag on the public `/aanbiedingen` page,
  encoded in the documented `devalue` format (`parsers/devalue.py` - a ~90-line
  resolver: dict values and list elements are always integer indices into the
  same array, which is how the format de-duplicates repeated values). A plain,
  cookieless GET returns it. Akamai cookies (`bm_mi`, `bm_sv`, `akaas_as`) ride
  along on every response but never challenge a plain HTTP client here.
- A separate `/api/graphql` lane exists (persisted queries) and answers with a
  CSRF-shaped 400/401 unless the request carries `apollo-require-preflight` and
  `apollographql-client-name` headers - a standard Apollo Server safeguard, not
  bot detection, and trivially satisfied. It only surfaces a 4-item spotlight
  though (`GetHomeScreenOffers`), not the full listing, so `adapters/jumbo.py`
  does not use it.
- One promotion's own detail page (`/aanbiedingen/-/{id}`, no slug required)
  carries a `__typename: "Product"` node with a real current/promo price pair
  in cents. No nutrition was found on it or on `/producten/...` - Jumbo SKUs
  stay on the generic food_type seed until a macros source turns up.

**One promotion is not always one SKU - solved properly, not filtered around.**
Some cover a product line on the same deal ("Alle sets met 6 pakjes à 200 ml",
"M.u.v. Kuipjes à 200 gram") - AH's segment problem. Jumbo's listing never
expands these itself (`products: []` on every node, same as AH's `bonusGroup`),
but the SAME offer detail page used for a single-SKU promotion's price also
carries a `Promotion` node whose `products` field is filled in with every real
SKU the deal covers when there is more than one - found by fetching a
multi-variant promotion's own detail page directly. `expand_offer()`
(`adapters/jumbo.py`) uses that: a genuine per-SKU expansion, AH's `fetch_segment`
shape reached through the page already being fetched for pricing rather than a
separate endpoint. Re-measured after adding it: **140 promotions expanded into
1466 real, distinct, individually-priced SKUs** ("Alle Pampers" -> 28 sizes,
"Alle Dr. Oetker Ristorante pizza" -> 18 flavours - checked by hand, all
plausible). `_single_sku_subtitle`'s `alle|m.u.v.|excl.` filter is kept as a
defensive fallback for the rarer case where a detail page's `Promotion` node
carries no `products` list at all and `expand_offer` falls back to a single
product whose own listing subtitle is still the ambiguous segment-level text.

**The multipack unit-size gap is fixed, not left open.** Jumbo phrases
multipacks as `"24 blikken à 33cl"` (a count NOUN + `à`, not AH's `"6 x 125
g"`), which `parse_unit_size` did not recognise and quietly parsed as a single
330 ml can - a ~24x unit-price error. Fixed with a new, separately tested
pattern in `parsers/units.py` (`_MULTIPACK_CONTAINER_MASS/VOLUME`): Dutch
plurals are spelled out explicitly (`flessen`, `zakken`, `potten`, `dozen`, ...)
rather than built from a stem, because Dutch pluralisation doubles consonants
in ways a compact regex gets wrong in both directions. Verified against the
real data: computed unit prices for the affected beer trays dropped from
~€80/L (a false ~24x-inflated mismatch) to ~€3/L (a genuine, review-worthy few
percent), with zero regression on AH's already-verified 475/475 parse rate.

**`match_overrides.yaml` is tuned for Jumbo, not just AH.** Same category-
exclusion lever, Jumbo's own department names: `Drogisterij en gezondheid`,
`Huishouden en dieren`, `Bier en wijn`, `Frisdrank en sappen`, `Baby en kind`,
`Koffie en thee` (coffee/tea contribute no protein and are out of scope, not a
fruit-name trap like AH's soft drinks). `Koek, snoep, chocolade en chips` is
**not** excluded - unlike AH, Jumbo lumps confectionery, chips *and*
nuts/protein bars into this one category ("LiGA Proteïne Reep Pinda", "Chio
Fusion Peanuts" both live there), so it is handled the same way AH's own
`Borrel, chips, snacks` is: real food caught by `contains:`, the ~30 confirmed
junk product LINES (not bare brand names, to avoid a repeat of the "extra"
collision below) added to `never_match`.

One tuning mistake, caught by the test suite: a bare `extra` `never_match`
entry (for the Extra chewing-gum brand) also matched "AH Extra vierge
olijfolie" (AH's own premium line) and broke two existing AH matcher tests.
Fixed to specific phrases (`extra kauwgom`, `extra peppermint`, ...) - the
lesson CLAUDE.md's own guard comments already teach, re-learned the hard way:
a `never_match` entry is a phrase, not a brand name, and a generic English word
is never safe as one on its own.

Measured 2026-09-17, after `expand_offer` and the tuning above: **1466 real
SKUs, 121 matched, 303 unmatched (down from 1238), 1042 excluded as non-food**
- the review queue is now proportionate and worth reading, the same
transformation AH's own matching history describes (247 wrong matches -> 185
right ones). 262 `unit_price_mismatch` (up in absolute count only because
`expand_offer` made ~10x more SKUs checkable at all; the multipack false
positives are gone, what remains is the same genuine drained/rounding class AH's
tuna and herring already established, plus a residual around unusual pack
phrasings this milestone did not chase further).

**The base price catalogue reaches AH's own coverage.** `search_products`
(`adapters/jumbo.py`) was found by watching the network tab while typing into
Jumbo's own search box: `www.jumbo.com/producten/?searchType=keyword&
searchTerms=` is server-rendered the same way `/aanbiedingen` is (the
client-side `SearchSuggestions` GraphQL call that fires per keystroke is
autocomplete text only, never products - the real results are in this page's
own `__NUXT_DATA__`). A plain, cookieless GET returns them. `bonusrank prices
--refresh --all --chain jumbo`: **173 of 193 food types priced** - matching
AH's own 173/193 to the SKU. `bonusrank compare --chain jumbo` now produces a
verdict for all 8 archetypes, the same as AH.

One bug this surfaced, fixed at the root rather than worked around:
`_map_product` was returning `raw_unit_text=None` unconditionally, relying on
`ingest_flat`'s offer-subtitle fallback to patch it up - which does not exist
for a bare `search_products` result with no offer behind it. Every search hit
was therefore "matched but unpriceable" (no mass). Fixed by using the
product's own title as `raw_unit_text` directly in `_map_product` (it reliably
ends with a real pack size, and `parse_unit_size` already tolerates the leading
noise) - one source of truth, not a fallback chain the caller has to know about.

### Aldi NL — unblocked 2026-09-17, adapter shipped

Both 2026-09-16 findings were correct: `webservice.aldi.nl/api/v1/promotions.json`
really is a 200/zero-byte dead end, and the offers page's `__NEXT_DATA__` really
is just a Magnolia CMS navigation tree with no prices at any depth.

What works is a level below `__NEXT_DATA__`: Next.js's own **data route**,
`https://www.aldi.nl/_next/data/{buildId}/nl/aanbiedingen.html.json` - the JSON
Next.js itself fetches client-side to hydrate the page. `buildId` is never
hardcoded; it is read straight out of `__NEXT_DATA__.buildId` on a normal page
fetch first, the same reasoning CLAUDE.md already gives for AH's section URLs
(`adapters/aldi.py::_build_id`). That data route's `pageProps.apiData` is the
same JSON-string-encoded 2-element list CLAUDE.md already found
(`[["OFFER_GET", {req,res}], ["PAGE_MGNL_GET", ...]]`) - but
`OFFER_GET.res.algoliaDataMap` is what was missing before: **~210 SKUs**, each
with a structured `currentPrice` (current price, strike price, per-kg/per-litre
base price, a validity window) and a `salesUnit` size string. No cookies, no
session, no browser - confirmed with a bare `curl`.

Unlike AH's segment model, one promotion **is** one SKU here - `algoliaDataMap`
already carries per-SKU pricing directly, so `fetch_promotions` needs no
expansion step, and `fetch_product` just re-reads the same (adapter-cached) map.

**`OP=OP`** ("op is op" - while stocks last) is Aldi's own honest term for "this
is simply this week's price, no reference price is being discounted" - ~155 of
211 entries measured 2026-09-17. Mapped to `NOT_A_PROMO`, not a gap. A handful
of `"VANAF"` (tiered/variable pricing, e.g. plants) entries have no single
number to trust and are passed through unparsed for review rather than guessed.

**Category is read from the right field.** Aldi's own `mainCategoryID` is
mostly the useless literal `"offer"` - a bucket for whatever is on promotion,
not a department. `hierarchicalCategories.lvl0` is the real, AH-shaped
taxonomy ("Vlees, vis en vega", "Snoep, koek en chocolade") but is a
multi-value FACET list, not a single path - an own-brand tuna tin carries both
"Vlees, vis en vega" and "ALDI merken" side by side. `adapters/aldi.py::
_department` skips the generic cross-cutting facets (`ALDI merken`, `Speciaal
assortiment`, `Winnaarsproducten`) and uses the first genuinely departmental
one. `match_overrides.yaml` is tuned on top of that: `Huisdieren`, `Huishouden`,
alcohol and soft-drink categories excluded; `Snoep, koek en chocolade` excluded
too (pure candy here, no nuts/protein-bar overlap the way Jumbo has); `Borrelhapjes`
(party snacks) is **not** excluded - it mixes real food ("Worsten 5-pack",
"Tapas roomkaasrolletjes") with novelty items, the same shape as AH's `Borrel,
chips, snacks`. **168 of 211 SKUs carry no `hierarchicalCategories` at all** -
a real Aldi data-quality limit, not something to work around - so Aldi's
general-merchandise items (cat litter, dog chews, a face-massage tool) are
caught by name instead, the one place a category lever genuinely does not
reach.

Measured 2026-09-17, after the department fix and tuning: 210 offers, 24
matched to a food type, 29 excluded as non-food (up from 2). 26
`unit_price_mismatch` out of ~40 SKUs that even publish a `basePrice` - a
similar rate to AH's own drained/rounding residual, not a new failure mode.

One shared, real bug this surfaced: `compare_unit_price` divided by zero when a
`basePriceValue` came through as exactly `0` (a real Aldi data-quality
artefact). Fixed in `parsers/unit_price.py` as a fourth `_incomparable` case,
alongside the others already there - this could as easily have hit AH on a
future ingest and is not chain-specific.

**No base price catalogue beyond the weekly offer feed - a real limit of
Aldi's own site, not a gap left here.** Unlike AH and Jumbo, Aldi's public
website has no searchable, browsable, year-round priced catalogue: its search
box does not submit a query at all, and its `/producten/...` category pages
(confirmed by fetching several, including their own Next.js data routes) are
pure Magnolia CMS marketing text with zero prices - `algoliaConfig`/
`algoliaState` keys exist in `__NEXT_DATA__` but are `null` everywhere checked.
Aldi's entire public pricing model appears to be the rotating weekly
`aanbiedingen` feed this adapter already reads in full. `AldiAdapter`
therefore has no `search_products`, and `prices.refresh_food_type_prices`
already raises `NotImplementedError` for a chain without one (the same guard
written for Jumbo/Aldi before either had it) rather than pretending the
capability exists. This is not a capability gap to close later; `bonusrank
compare --chain aldi` already produces a verdict for every archetype Aldi's
own (smaller) catalogue can price, which is everything the site itself makes
available.

**`ingest.py` was chain-specific to AH before this milestone**, despite the
adapter protocol's promise: `ingest_ah` unpacked AH's own raw segment dicts
directly, never going through `RawProduct`. Jumbo and Aldi don't have AH's
segment indirection, so this was also the point at which a genuinely generic
path got built: `ingest_flat(conn, adapter, ...)` uses only
`fetch_promotions`/`fetch_product`, sharing the parse/cross-check/match/insert
core (`_ingest_sku`) with `ingest_ah` rather than duplicating it. `cmd_ingest`
picks a path by capability (`hasattr(adapter, "fetch_segment")`), not by chain
name - a future chain shaped like Jumbo or Aldi needs no ingest changes at all.

---

## 5. Parsers — measured behaviour (milestone 2)

`src/bonusrank/parsers/`, 165 tests, all pure functions: text in, typed value out,
no I/O. They run against persisted snapshots, so a parser fix can be replayed over
history without re-scraping.

Measured against the real AH fetch of 2026-09-16:

| Parser | Real-data result |
|---|---|
| `units.parse_unit_size` | 475/475 SKUs parsed, 0 to review |
| `unit_price.compare_unit_price` | 473/475 within 2% of AH's own stated unit price |
| `promos.parse_ah_label` | 218/232 offers priced; 14 to review (6.0%) |
| `nutrition.parse_gs1_nutrition` | protein + kcal on every SKU sampled |

**The 14 promo review cases are correct, not a gap.** They are `DISCOUNT_ACTION`
and `DISCOUNT_BONUS`, which carry no number anywhere — 8 wines with a `None`
headline and 6 non-food. Do not "fix" them by guessing a multiplier.

### A unit-price mismatch is a question, not a verdict

Both cross-check failures were the store, not the parser:

- Sun-dried tomatoes labelled `180 g` are priced per kg on **90 g** — packed in oil,
  so that is the drained weight.
- `ca. 300 g` herring is priced on **270 g** (0.90 of nominal) for variable weight.

**In that week's data not one SKU stated `uitlekgewicht` in `salesUnitSize`.** So
`unitPriceDescription` is the *only* place the drained fraction is visible, and the
canned-legume trap (section 3.1, the biggest trap in the domain model) is invisible
on the label. `UnitPriceCheck.implied_quantity_g` surfaces the mass the store's own
price implies. **Surface it; never auto-apply it** — a mismatch is genuinely
ambiguous between a parser bug and a drained fraction, and only review can tell.

### Invariants the tests pin down

- `UNKNOWN` carries a `None` multiplier and **refuses to price itself**. It is
  distinct from `NOT_A_PROMO` (multiplier 1.0, a positive finding). Collapsing the
  two would silently mis-rank every unparsed offer.
- `UnitSize.cost_basis_g` prefers drained over net mass. The cross-check
  deliberately uses **net** mass, or every tin would raise a false alarm.
- A missing macro is `None`; a real `0.0` stays `0.0`.
- kcal derived from kJ sets `kcal_is_derived` — copy rule 1 forbids showing it
  unmarked.

## 6. Storage, matching and ranking (milestones 3-6)

### Schema (`db.py`)

Brief section 6, with two things enforced by the database rather than by discipline:

- **Triggers abort any UPDATE or DELETE on `price_observations`.** A comment
  saying "append-only" would not survive a careless `INSERT OR REPLACE`.
- **`product_macros` is an addition to the section 6 tables.** Section 2 ranks a
  SKU's own FIR label figures above everything else ("prefer it always") and the
  brief's tables have nowhere to put per-SKU macros. `food_types` stays generic.

### `food_types` seed — 188 types, 590 aliases

Loaded from **every** `data/seed/food_types*.yaml` (the loader globs, so you can
drop your own file in without touching code). A duplicate key across files raises
rather than silently overwriting.

Every row is `source='manual'`, `confidence='seed'`, `source_ref=NULL`.
**No NEVO codes are cited, because no NEVO data was fetched.** That dataset
requires accepting usage conditions at rivm.nl, which is yours to do, not mine.
`seed.load_nevo()` upgrades rows in place to `source='nevo'`, `confidence='high'`
with the code in `source_ref` once you have the file in `data/external/`.

Keyed on **food type + variant**, because the variant is where the protein is:
magere vs volle kwark, tonijn in water vs in olie, linzen droog (24 g P) vs uit
blik (7 g P). Fields left out stay NULL rather than being invented.

Produce carries little protein but is seeded anyway: the kcal floor and the
variety cap (section 3) have to be satisfied with *something*, so the optimiser
needs it present and priced.

### Matcher — lanes, guards, and what each one cost to find

Lanes in priority order: SKU override, substring override, then alias matching
(exact / all-alias-words-contained / fuzzy). **Fuzzy carries its own higher bar
(0.90 vs 0.82)** — `SequenceMatcher` rates unrelated short Dutch strings at
0.82-0.84, which is how "Coca-Cola Vanilla" became `vla_vanille` at 0.824.

Every guard below was added because of a false positive **measured on the real
catalogue**. None was designed in the abstract, and the comments name the case so
nobody "simplifies" one away:

1. **Variant guard.** SKU and alias both commit to a dimension (fat / medium /
   form / prep / grain / origin) and disagree -> candidate rejected outright,
   whatever it scored. `tonijnstukken in olie` scores 0.837 against the alias
   `tonijnstukken in water` and only 0.800 against `tonijn in olie`. Variant
   *agreement* also outranks raw similarity, or the generic alias `rijst` beats
   `zilvervlies rijst`. `origin` (plantaardig vs rund) stops "Terra Plantaardige
   gehakt" being costed as beef mince.
2. **Composite-dish guard**, matched at a **word boundary inside compounds** —
   Dutch hides the dish word (`bonen|soep`, `pureer|soep`, `salad|bowl`,
   `vanille|smaak`). A free substring search is too blunt: "ijs" sits mid-word in
   **"rijst"** and would reject every bag of rice as ice cream. A short list
   (`reep`, `koek`, `drink`) stays whole-token-only, because `reep` would
   otherwise reject `kipfilet reepjes` and `drink` would reject `haverdrink`.
3. **Multi-food guard.** A name containing complete aliases for 2+ distinct food
   types is a mix, and whichever wins the macros are wrong. Nesting is collapsed
   on **content tokens** (qualifiers stripped): `olijfolie` nests inside
   `tonijnmoot in olijfolie`, so tuna-packed-in-oil stays one food. Comparing raw
   aliases instead sent every such tin to review.
4. **Category exclusion**, checked before the matcher runs. This is the single
   biggest lever on review-queue signal — the first ingest queued 2760 SKUs and
   the commonest words in that queue were *spray, wasmiddel, navulling, shampoo,
   spf50*: Etos and drogisterij, not seed gaps.

**`Borrel, chips, snacks` is deliberately NOT excluded.** It was, briefly, and it
cost 80 matches — cashewnoten, amandelen, pecannoten and pindas live there and are
among the better protein-per-euro buys in the folder. The category mixes crisps
with nuts, so the crisps are handled by name in the override file instead.

### The residual is real — use `bonusrank matches`

Containment has a false-positive tail that no threshold removes; it is a
heuristic. Measured on the final ingest, roughly **5% of matches are still
wrong** — a flavour or a minor ingredient winning over the product ("Kleintje
aioli zongedroogde tomaat", "Rijst rondjes zeezout").

The designed remedy is `data/seed/match_overrides.yaml` (`sku` / `contains` /
`never_match` / `non_rankable_categories`), **not a lower threshold**.
`bonusrank matches [--method fuzzy] [--food-type KEY]` lists what the matcher
decided, weakest first, so those rules get written from evidence. Note the
override lane runs *before* the dish guard — that is how `sinaasappelsap`
survives `sap` being a dish marker.

### Ranking (`ranking.py`)

Macro precedence is tier 1 (`product_macros`, the SKU's own label) over the
generic seed, and **which one was used is always printed**. Unit sizes are
re-parsed from `raw_unit_text` at rank time, so a parser fix improves every past
row with no re-ingest — the same replay property as the raw snapshots.

Waste adjustment (section 3.3) uses `daily_consumption_g` and
`freezer_horizon_days` from `config.yaml`. Section 5 says every such input comes
from user config; they are in `config.USER_DEFAULTS`, not scattered as constants.

### Measured on the real AH catalogue, 2026-09-17

| | before guards | after |
|---|---|---|
| matched | 247 (many wrong) | **185** |
| unmatched -> review | 2760 | **1253** |
| excluded as non-food | 55 | **1570** |
| offers with a usable protein figure | 186 | **174** |
| of those, tier-1 label macros | 68 | **115** |
| fuzzy-lane matches | 10 (half wrong) | **1** (correct) |

Fewer matches is the *point*: the 62 that went away were wrong. Review queue:
1253 `unmatched_sku`, 181 `unparsed_unit_size` (genuinely unparseable here —
"20 wasbeurten", "per paar"), 15 `unit_price_mismatch`, 14 `unparsed_promo`.

**The mismatch queue is the drained-fraction discovery lane.** Rio Mare tuna
labelled `160 g` is priced per kg on 112 g — a 0.70 drained fraction where the
seed guessed 0.75. Sun-dried tomatoes `180 g` imply 90 g, which is now in the
seed as `drained_fraction: 0.50` with that provenance in a comment. Use these to
correct `food_types.drained_fraction`; **do not auto-apply them.**

## 7. Price catalogue and the substitution engine (milestone 8)

### The base price catalogue (`prices.py`) — the thing that unblocked §4

Ranking only ever needed a price for SKUs that turned up in the bonus folder.
Pricing a DIY composition needs a price for **every** food type in the recipe,
in **every** week — and most weeks most ingredients are not on offer. So
`prices.refresh_food_type_prices` fetches a plain shelf price per food type from
`product/search/v2` and appends it as an ordinary observation with mechanic
`not_a_promo`; `prices.food_type_price` reads back the cheapest currently-valid
€/kg across that food type's SKUs, so a live bonus beats the shelf price and an
expired one does not, with no special-casing.

Measured on 2026-09-17: **173 of 193 food types priced, 20 to review.**

Three findings that cost real requests to discover:

- **Search relevance is not a match.** Hits go through the existing `Matcher`,
  guards and all — a search for `magere kwark` returns kwarktaart. There is no
  second, looser matching path, and there must not be one.
- **A hit that cannot be costed is not a hit.** AH's search puts multipacks
  first: the top result for `halfvolle melk` is a 12-pack whose `salesUnitSize`
  is `"2 stuks"`. Genuinely halfvolle melk, genuinely impossible to price per
  kilo. Taking it left four staples (melk, havermout, kipfilet, knoflook)
  unpriced while the run reported a match. `_pick` now requires a resolvable
  mass and reports these as `unparsed_unit_size`, not `unmatched_sku` — the fix
  is a `g_per_unit` in the seed, not a match override.
- **`name_nl` is often a bad search term.** `skyr met fruit` returns Coca-Cola
  multipacks; its alias `skyr aardbei` finds the product. Aliases are tried, but
  only after the canonical name fails, so the extra requests land on the gaps
  rather than on the whole sweep. This alone took matched from 150 to 173.

`max_requests` counts **requests, not food types**. A full sweep is ~190 plus
alias retries: about 95 s at 2 req/s, and free on a re-run inside the 6 h cache.

### Two lanes in one append-only table

A shelf price recorded today would supersede this week's still-valid bonus for
the same SKU under a plain "latest observation" rule, silently deleting it from
the ranking — measured as `bonusrank list` dropping from 174 rated offers to
160. `ranking._SQL` therefore takes the latest observation **per lane** (promo
or not), and `bonusrank list` filters shelf prices out by default because it
ranks *offers*; `--include-shelf-prices` opts in. Nothing is overwritten to make
this simpler — the reader disambiguates, because the writer may not.

### The engine (`archetypes.py`) — `bonusrank compare`

Ready-made SKUs are bound by **seed rules resolved at compare time**
(`ready_made.food_types` / `ready_made.contains`), never by hand-listed SKU ids,
because AH rotates webshopIds weekly. Resolved bindings are written to
`sku_archetype_map` so a rule that quietly binds the wrong SKU can be looked up.

- **`items[].grams` is per serving**, not per batch. Nothing rescales a
  composition. Ready-made is scaled *down* to `archetype.serving_g`: a 400 g pot
  for a 200 g serving is half the pot.
- **One unpriced item makes the whole composition's cost `None`, and the item is
  still listed.** Summing the rest would claim a recipe is cheaper than anyone
  can buy it for. This is the single most important rule in the module.
- **One priced side and one unknown side is not a comparison.** The verdict is
  `unknown`. Picking a winner there would always favour whichever side happened
  to have data — the engine's most damaging possible lie.
- **Pantry items** (zoetstof, kruiden, vanille) carry a
  `pantry_price_eur_per_kg` on the composition *item*, not on the food type, and
  print as `(pantry price, not promo data)`. It is a property of "a pinch of this
  in a recipe", not of the food.

`taste_delta_note` is validated non-empty by the loader (so the error names the
row, not the CHECK) and `test_compositions_seed.py` blacklists parity phrasings
in both Dutch and English. Crude, and the right crudeness for a rule that only
has to break once.

### Measured on the real AH catalogue, 2026-09-17

8 archetypes, 9 compositions. Every DIY side prices. Three archetypes have
nothing on the shelf that matches (hüttenkäse spread, overnight oats, RTD
shake) and honestly say so.

| Archetype | Verdict |
|---|---|
| Proteïne drinkyoghurt | **ready-made, by 50%** — Optimel protein, €0.60 / 25 g P |
| Proteïne reep | DIY, by 71%, +7 g P, 12 min |
| Kip-wrap lunch | DIY, by 52%, +14 g P, 8 min |
| Chocolade proteïne pudding | DIY, by 18%, −3 g P, 3 min |
| Skyr met fruit | DIY, by **9%**, +1 g P, 2 min |

Two of these correct the brief. §4.5 asked whether the engine would ever say
"just buy it" — it does, unprompted, on the first real run. And §4.4 predicts
fruit-vs-naturel skyr is "the single biggest easy win"; measured, it is the
**smallest** margin of the five, because AH's own-brand fruit skyr is €0.76 per
200 g. The markup on the flavour variant is real but small at AH. Do not
re-inflate that claim in the output copy.

## 8. Layout

```
src/bonusrank/
  http.py             polite client: 2 req/s per chain, 6h disk cache, backoff, real UA
  rawstore.py         data/raw/{chain}/{endpoint}/{iso_date}.json
  models.py           RawOffer / RawProduct (pydantic)
  config.py           settings incl. the User-Agent contact string
  adapters/base.py    StoreAdapter protocol + registry
  adapters/ah.py      Albert Heijn (promo lanes + product search)
  adapters/jumbo.py   Jumbo (Nuxt __NUXT_DATA__ + devalue)
  adapters/aldi.py    Aldi NL (Next.js data route + algoliaDataMap)
  parsers/devalue.py  generic Nuxt __NUXT_DATA__ resolver (Jumbo)
  ingest.py           ingest_ah (AH's segments) + ingest_flat (Jumbo/Aldi, generic)
  prices.py           food_type -> cheapest current EUR/kg; the base price catalogue.
                       food_type_prices (batch) is the primitive; the singular wraps it
  archetypes.py       ready-made vs DIY; the substitution engine (brief section 4)
  optimiser.py        per-meal LP: cheapest normal-shaped mix hitting an archetype's
                       protein target, bound by a meal/snack/drink macro-floor profile
  templates.py        the customiser: a template's slots, each with its candidates
                       priced and ranked for this week (milestone 12)
data/seed/archetypes.yaml       8 archetypes, 9 compositions, ready-made rules
data/seed/templates.yaml        2 meal templates, 9 slots, 32 candidates, 5 rules
data/seed/food_types_pantry.yaml  cupboard staples compositions need
docs/BRIEF.md         the full dossier — source of truth
data/raw/             persisted responses (replay source; keep)
data/external/        NEVO dataset — gitignored, has usage conditions, never commit
```

## 9. Milestones — stop after each, show output, do not build ahead

1. ~~AH adapter.~~ **Done.** 232 offers, raw persisted, replayable.
2. ~~Parsers + tests (tests first).~~ **Done.** 165 tests; unit size, unit-price
   cross-check, promo mechanics, nutrition (both shapes).
3. ~~SQLite schema + ingest.~~ **Done.** Append-only enforced by trigger.
4. ~~`food_types` seed.~~ **Done.** 111 types, all `confidence='seed'`.
5. ~~Matcher + override YAML.~~ **Done.** Four guards; see section 6.
6. ~~Ranking CLI.~~ **Done.** `bonusrank list --sort protein-per-euro`.
7. ~~Jumbo, then Aldi.~~ **Done, and brought to full parity with AH**, not just
   unblocked. Both were mis-diagnosed as blocked on 2026-09-16 - the real
   endpoints had simply moved. See section 4 for the full account: Jumbo's
   real per-SKU segment expansion (`expand_offer`), the multipack unit-size
   parser fix, `match_overrides.yaml` tuned for both catalogues (Jumbo
   121/424 matched, Aldi 24/181 - proportionate review queues, same
   transformation AH's own matching history describes), and a real
   `search_products` base-price catalogue for Jumbo (173/193 food types
   priced, matching AH's own 173/193). Aldi has no equivalent base-price
   catalogue because its own website has none to find - a confirmed structural
   fact about Aldi's site, not a gap. `bonusrank compare` produces a verdict
   for all 8 archetypes on all three chains.
8. ~~Archetypes + compositions.~~ **Done.** 8 archetypes, 9 compositions, plus the
   base price catalogue they needed. See section 7 below (a numbering
   coincidence with this milestone list, not a cross-reference).
9. ~~Per-meal optimiser.~~ **Done, scoped down from the brief's original ask.** The
   brief's own milestone 9 was a whole-day/week LP composing several meals to hit a
   daily protein target under a kcal floor and a variety cap. The user explicitly
   does not want that - they plan their own meals and days - so what shipped is
   smaller and different: `src/bonusrank/optimiser.py::optimise_meal` picks the
   cheapest gram amounts of **one archetype's own ingredients** (its seeded
   compositions' food types, plus a small hand-authored `optimise_extra_food_types`
   companion list) that hit `target_protein_g`, printed as one more line in
   `bonusrank compare` alongside the hand-authored recipes.

   The one rule this milestone exists to enforce, from the user directly: **the
   result must not be a protein-maxed mess** - a cost-minimising LP with only a
   protein floor will spend everything on the single cheapest protein source,
   because nothing in the model asks for anything else. So every archetype is
   classified by a new `meal_kind` (`meal`/`snack`/`drink` - authored judgement,
   same status as `taste_delta_note`, orthogonal to the existing `meal_slots`
   which is about *when* you'd eat it) and the solve is bound by a
   `config.USER_DEFAULTS["optimiser_profiles"]` floor set that matches what that
   kind of thing actually looks like: a `meal` gets a kcal floor AND a carb floor
   AND a fat floor; a `snack` gets a lighter kcal/carb floor and no fat floor (a
   piece of fruit is a normal snack); a `drink` gets only a low kcal floor, because
   a protein shake is *supposed* to stay protein-forward - that asymmetry is the
   whole point of classifying archetypes at all. Micros (fiber, vitamins) are
   explicitly out of scope, per the user - not constrained, not scored.

   Every floor is a lower bound; the objective only ever contains cost
   coefficients, never a kcal/protein/carb/fat one - the LP has no incentive to
   drift toward "as little as possible of everything except the cheapest protein
   source" because the model isn't scored on protein above the target either. This
   is the scoped-down analogue of the brief's original day-level safety rule 1.

   A plausibility check runs after every solve, on top of the LP's own bounds:
   if the candidate pool has 2+ priceable ingredients and the solve still puts
   ≥95% of the mass on one of them, it is rejected - **except for `drink`**, where
   an all-whey shake is exactly what the archetype is for. Measured live on
   2026-09-17: this check actually fired and caught something real -
   `chocolade_proteine_pudding` (classified `snack`) initially optimised to 154 g
   of plain havermout, because oats alone happened to be the cheapest way to hit
   20 g protein and satisfy the (lighter) snack floors - technically balanced in
   macros, but not a chocolate pudding by any stretch, and not something a person
   would actually eat as-is. The check rejects that solve honestly
   ("no plausible combination found...") rather than presenting it as an answer.
   `skyr_met_fruit`'s narrow two-ingredient pool hits the same honest rejection.
   `kip_wrap_lunch` (classified `meal`, given `olijfolie` as a fat companion) is
   rejected for a different, equally honest reason: its 30 g protein target
   cannot be reached from this pool without breaking the meal floors at all -
   `RejectedPlan`, not an exception and not a silently-loosened constraint.
   Archetypes with a wider or more balanced pool solve cleanly: `kip_wrap_lunch`'s
   sibling `overnight_oats` (a `meal`) and `proteine_drinkyoghurt`/`proteine_shake`
   (`drink`s, correctly left protein-forward and cheaper than their `meal`-shaped
   counterparts would be) all produce real, multi-ingredient, floor-satisfying
   mixes.

   `pulp` (already a decided dependency, brief §7, never previously installed)
   is now an actual `pyproject.toml` dependency. No day-level planning, no
   combining archetypes, no variety-across-meals cap - explicitly out of scope
   by the user's own instruction.

10. ~~Android app + data export.~~ **Done.** The user rejected an optimiser-driven
    UI outright: they want a browsable, filterable list of meals/snacks/drinks/
    everything-else with price, the applicable promo, and macros next to each item
    - never the app picking for them. `src/bonusrank/export.py` serializes
    `ranking.rank()` and `archetypes.compare()` (computing nothing new) to
    `docs/data/latest.json` via `bonusrank export`. `.github/workflows/
    refresh-data.yml` runs the full scrape/ingest/price/export pipeline on a
    schedule and commits the result; the Android app (`android/`, Kotlin +
    Jetpack Compose) fetches that file directly from
    `raw.githubusercontent.com` - no backend to host. See `android/README.md`
    for the app's own structure and its test split (JVM unit tests run in CI;
    Compose UI has no instrumentation tests yet, verified manually instead).

11. ~~food_types meal_kind + offer-driven tabs.~~ **Done.** The app's
    Meals/Snacks/Drinks/Other tabs were gated on the 8 curated archetypes -
    every tab but "Other" only ever showed those 8 items, no matter how much
    was actually ingested and priced. Fixed at the source: every one of the
    193 `food_types` seed rows now carries its own `meal_kind`
    (`meal`/`snack`/`drink`/`ingredient` - `db.py`, `seed.py`, tagged by hand
    per section, see `tests/test_food_types_seed.py`). **No food type is ever
    classified `meal`** - a raw chicken fillet or a bag of rice isn't a meal,
    it's a component of one, so `meal` stays exclusively an
    `archetypes.meal_kind` concept (a composed dish). `ranking.RankedOffer`
    and `export.py` carry the food type's `meal_kind` through to every offer;
    the app's SNACKS/DRINKS/OTHER tabs now filter the FULL ranked offer list
    (hundreds of matched SKUs) by it, while MEALS stays archetype-driven until
    the planned slot-based meal customiser (pasta/wrap-style: pick a carb, a
    protein, a sauce, optional greens, checked for whether the combination
    actually works, plus user-added extras and saved custom meals) is
    designed and built - that is a separate, much larger milestone, not yet
    started.

12. ~~Meal templates: slots, ranked candidates, compatibility rules.~~ **Done,
    Python side only - the app work is milestone 13 and has not started.** The
    Meals tab could only ever show 8 hand-authored archetypes, two of which are
    the only `meal_kind: meal` entries in the seed. A TEMPLATE
    (`data/seed/templates.yaml`, `templates.py`, `bonusrank templates`) is a
    shape with holes in it instead: Pasta = a pasta, a meat, a sauce, optional
    cheese and greens, each hole offering a ranked list of real candidates
    priced from this week's data. Measured 2026-09-17, the AH pasta sauce slot
    ranks pesto first and Jumbo's ranks tinned tomatoes first - the ranking is
    genuinely price-driven, which is the whole point.

    **"Slot" now means a component of a dish.** `archetypes.meal_slots` (a time
    of day) was renamed `day_parts` in this milestone for exactly that reason -
    12 call sites, done while nothing depended on the new meaning.

    Four decisions the user made, recorded so they are not re-litigated:
    compatibility is **authored in the seed**, never derived; saved meals will
    live **on-device only**; the catalogue will eventually cover **every scraped
    SKU**; and ranking is **split** - Python ranks candidates, Kotlin re-prices
    totals locally.

    The rule language is one predicate vocabulary (`{slot?, food_types?}`) with
    two kinds. A `requirement` holds when at least `min_satisfied` of its
    `requires` predicates are present - a disjunction, because the user's own
    example ("pasta pesto needs some more ingredients") means "needs cheese OR
    greens", which a single target slot cannot express. `severity`
    (`incomplete`/`wrong`/`note`) keeps "this dish is unfinished" from reading
    like "these two do not go together". Every rule carries a required, non-empty
    `note` - the only text the app will ever show about it - with the same
    authored status as `taste_delta_note`. A rule naming a food type no slot
    offers could never fire and is **rejected at load time**, not left to rot.

    Two rules carried over from `archetypes.py` because they are what keeps the
    output honest: an unpriced candidate stays in its slot with `eur=None`
    **ranked last, never dropped** (a slot that silently loses options presents a
    shorter menu than the seed says it has), and a missing macro stays `None`
    rather than becoming zero. Candidates rank by **serving cost**, not by
    €/kg - the grams differ within a slot on purpose (40 g pesto vs 200 g tinned
    tomatoes) and per-kilo would rank the small portion last for a reason that
    has nothing to do with what the meal costs.

    `prices.food_type_prices` (batch, `f.key IN (...)`) was added and
    `food_type_price` **reimplemented as a wrapper over it** - two independent
    copies of the validity-window and personal-offer filters would drift, and the
    one that drifts is the one that forgets a filter.

    11 new food types were seeded for the two templates. The first live price
    sweep queued 5 of them as `unmatched_sku`/`unparsed_unit_size`, which is the
    review lane working: 4 were fixed with `contains:` rules in
    `match_overrides.yaml` (the designed lever, never a lower threshold), and
    `rucola`'s English alias `rocket` was removed after it matched "Nestle Pirulo
    smarties rocket" - the same lesson the `extra` chewing-gum entry already
    taught. `rucola` still has no usable price and honestly shows as `?`.

    Export is `schema_version: 2`. Template bodies ship **once at top level**,
    not per chain: the slots, candidates and above all the authored rules are
    chain-independent, and three copies in one file is three chances to drift.
    Prices ship per chain under `chains.{chain}.template_prices`, and a new
    top-level `food_types` catalogue (204 entries, ~36 KB) carries macros and
    `g_per_unit` so the app can price "100 g ketchup" or "4 boiled eggs"
    locally. `eur_per_kg` ships as its own field rather than something to divide
    back out of `price_eur`, so a null rate stays null through a local recompute
    instead of becoming 0.0.

    **Not done, deliberately:** the Android customiser screen, local re-pricing,
    saved meals, arbitrary extras and full-catalogue browsing. Also deferred:
    tag-derived slot candidates (`template_slot_candidates.source` exists now so
    that lane can arrive through `_add_column_if_missing` rather than a rebuild)
    and global, template-independent rules (`template_rules.template_id` is
    already nullable for it).

13. ~~The customiser screen, local re-pricing, saved meals.~~ **Done.** The app
    can now build a meal, not only browse one: the Meals tab lists the templates,
    each slot shows its candidates cheapest-first, and the total re-costs on
    every tap. This is the first feature where the app computes rather than
    displays, so the boundary is drawn explicitly - **Python ranks, Kotlin
    re-prices, Python authors the rules, Kotlin evaluates them.** One
    implementation of "what does a kilo cost" (`prices.py`), one of "is this a
    dish" (`data/seed/templates.yaml`); the app multiplies rates and reads
    notes.

    Milestone 12 shipped food-type *macros* but no food-type *prices*, so an
    arbitrary extra had nothing to cost itself against. `export.py` now ships
    `chains.{chain}.food_type_prices` - a per-kilo rate for every food type that
    chain can price, not just slot candidates. An absent key means unknown; no
    food type is ever mapped to a zero rate.

    **Rule evaluation is three-valued** (`data/MealRules.kt`): satisfied /
    violated / **unknown**, and unknown reaches the screen as unknown rather
    than quietly passing. A meal containing a line the app cannot identify makes
    a rule about food types genuinely undecidable - that is the rule-language
    twin of `_price_composition`'s unpriced-poisons-the-total rule and of
    `_verdict` refusing to pick a winner when only one side is priced. It was
    built in from the start rather than retrofitted, so milestone 14's raw
    catalogue SKUs need a screen, not a rewrite. A rule **never blocks** a
    choice; it shows the author's note and gets out of the way.

    **Two symmetric poison rules in `data/MealMath.kt`**: one unpriced line
    nulls the euro total, one line with a missing macro nulls that macro total,
    and `unpricedLines`/`unknownMacroLines` name the culprit so the UI can say
    WHICH line spoiled it instead of showing a bare dash.

    **Saved meals store keys and quantities, never prices** - which is exactly
    what makes them re-cost as the bonus rotates, and falls out of storing keys
    rather than euros. They key on `(templateKey, slotKey, foodType)` STRINGS
    and never on a database id: `load_templates` deletes and re-inserts its
    child rows on every `bonusrank seed`, so an integer id would silently
    re-point at a different slot - no error, just wrong food. Lines are an
    ordered list with their own ids rather than a map keyed by food type,
    because `composition_items`' composite primary key makes "50 g more of the
    cheese I already picked" unrepresentable, and that constraint is right for a
    hand-authored recipe and wrong on a plate.

    Persistence is **DataStore plus the serialization plugin already present**,
    not Room: the whole persisted state is a short list of small objects, and
    Room would add KSP codegen, a schema and a migration story for a JSON
    string. `serializeMeals`/`deserializeMeals` are split out of the store so
    the round trip - the part that can silently lose a user's data - is
    testable on the JVM, since DataStore itself would need the instrumentation
    tests `android/README.md` says not to add. Unreadable stored data degrades
    to an empty list rather than crashing.

    Navigation is a `Screen` sealed interface in `UiState`, not a navigation
    library: three destinations, and a sealed class is testable in the JVM suite
    where a NavController is not.

    **Not done:** full-catalogue browsing and adding a raw unmatched SKU to a
    meal - milestone 14. Extras currently come from the seeded food-type
    catalogue, so every one of them has real macros and a real price.

Current position: **milestones 1-13 complete.** 669 Python tests, plus the
Android app's own JVM unit tests (`android/app/src/test`: filtering, JSON
decoding, rule evaluation, meal costing, saved-meal round trips).

Commands: `bonusrank seed` -> `bonusrank ingest --chain ah|jumbo|aldi [--with-macros N]`
-> `bonusrank prices --refresh --all --chain ah|jumbo` -> `bonusrank compare --chain ah|jumbo|aldi` /
`bonusrank templates --chain ah|jumbo|aldi [--template pasta]` /
`bonusrank list --chain ah|jumbo|aldi --sort protein-per-euro` / `bonusrank prices` /
`bonusrank matches` / `bonusrank review`.

**Run `bonusrank prices --refresh` before `compare`**, or most compositions
price as `?`. That is correct behaviour, not a bug.

**No web frontend in this phase** — the user has explicitly deferred it. CLI only.
