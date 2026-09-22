# Audit — milestone 0 of `docs/PLAN-V2.md`

Run on **2026-09-22** against the working tree at `f9bdc7c`, with a live scrape
of all three chains on the day. Nothing was fixed during this audit; everything
below is recorded for the milestones that follow.

Environment: Python 3.11.4 in `.venv`, Gradle 8.7 + Temurin JDK 17 unpacked
outside the repo, `ANDROID_HOME` at the Studio SDK.

---

## 1. Verdicts on milestones 1-13

`verified` = ran it today and saw the claimed behaviour.
`partial` = works, but a claim in `CLAUDE.md` overstates it.
`broken` = does not do what the claim says.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | AH adapter, raw persisted, replayable | verified | `bonusrank ingest --chain ah` today: 2864 new observations, AH products 3187 -> 5051. Raw JSON under `data/raw/ah/`. |
| 2 | Parsers + tests, tests first | verified | 165 of the 669 collected tests are parser tests (`test_units`, `test_promos`, `test_nutrition*`, `test_unit_price_crosscheck`). All green. |
| 3 | SQLite schema, append-only by trigger | verified | 17 tables. `UPDATE price_observations` raises `sqlite3.IntegrityError: price_observations is append-only` — hit for real by a test fixture in an earlier session. |
| 4 | `food_types` seed | verified, count stale | 204 rows, 655 aliases, all `source='manual'`, `confidence='seed'`. `CLAUDE.md` section 6 still says "188 types, 590 aliases" and its milestone 4 line says "111 types". |
| 5 | Matcher + override YAML | **partial** | Lanes and four guards all present and working. But the guards do not cover the canned-legume trap, which is `BRIEF` section 3.1's own headline example. See 3.1 below. |
| 6 | Ranking CLI | verified | `bonusrank list --chain ah --sort protein-per-euro` prints 229 of 2671 current offers with a usable protein figure, provenance-marked. |
| 7 | Jumbo and Aldi at parity with AH | verified | Live today: Jumbo 3047 observations / 4513 valid promo rows; Aldi 238 / 66. Both adapters answered without a single error. |
| 8 | Archetypes, compositions, base price catalogue | verified | `bonusrank compare --chain ah` produces a verdict for all 8. `bonusrank prices --refresh --all --chain ah` priced 183 of 204 food types; the 21 gaps are named in the output rather than silently zeroed. |
| 9 | Per-meal optimiser | verified | `compare` prints an `Optimised` line per archetype. The plausibility check fires honestly: "no plausible combination found - the cheapest solve is essentially one ingredient (100% of the mass)". |
| 10 | Android app + data export | verified | `bonusrank export` wrote 1.14 MB: ah 478 ranked offers, jumbo 294, aldi 0. |
| 11 | `meal_kind` on every food type, offer-driven tabs | verified | All 204 seed rows carry a `meal_kind`; it reaches the export on each offer. |
| 12 | Templates, slots, ranked candidates, rules | verified | `bonusrank templates --chain ah` prints 2 templates, 9 slots, 32 candidates, 5 rules. Ranking is price-driven: AH's sauce slot leads with tomatenblokjes at EUR 0.51, pesto second. |
| 13 | Customiser screen, local re-pricing, saved meals | verified | Android JVM suite: 60 `@Test` methods across 5 files. `gradle testDebugUnitTest --rerun-tasks` -> `BUILD SUCCESSFUL`, 25 of 25 tasks executed. Screens were checked by hand on an emulator in the previous session. |

**Test gates today:** `pytest -q` -> `669 passed`. Android JVM tests -> green,
forced rerun rather than an up-to-date cache hit.

---

## 2. Sizes and counts

| Thing | Value |
|---|---|
| `docs/data/latest.json` (committed) | 1,069,466 bytes |
| Fresh export today | 1,143,952 bytes |
| `.git` on disk | 2.8 MB — 321 loose objects, 2.12 MiB |
| Commits in history | 9 |
| Commits touching `latest.json` | 5 |
| Products in the dev DB | 8,672 (ah 5,051 / jumbo 3,174 / aldi 447) |
| Matched to a food type | 860 (9.9%) |
| `product_macros` rows | **0** |
| Price observations | 10,000+, across **2 distinct dates**: 2026-09-17 and 2026-09-22 |
| `needs_review` | 2,413 unmatched / 531 unparsed unit size / 384 unit-price mismatch / 43 unparsed promo |

Three of these deserve their own line.

**`product_macros` is empty.** Tier-1 FIR label macros are ingested only when
`ingest` is given `--with-macros N`, and neither the scheduled refresh workflow
nor any run that produced the committed snapshot passes it. So every macro
figure the app has ever shown came from the generic seed, and
`macros_need_marking` is `true` on **all 478** AH offers in the export. The
tier-1 lane is built and tested but has never carried data in production.

**Price history is two data points.** `cheapest_in_weeks` is therefore `0` for
all 246 offers that have it, and greater than zero for none. See 3.2.

**Git growth confirms `PLAN-V2` section 3.1.** Five revisions of a 1.07 MB JSON
are most of a 2.12 MiB object store, so a snapshot costs roughly 350 KB packed.
At the current twice-daily cadence that is about 250 MB of history per year for
the promos-only feed alone, before any catalogue work. The plan's replacement is
warranted.

---

## 3. Bugs found

### 3.1 Canned lentils are costed as dry lentils, and they rank first

`bonusrank list --chain ah --sort protein-per-euro` today:

```
   1.     0.82*        0.58    0.74    2x  1+1 gratis         Hak Linzen
      380 g -> 380 g costed  |  24.0 g P/100g  |  food_type linzen_droog
   2.     0.91*        0.64    1.09    2x  1+1 gratis         Hak Spliterwten gedroogd
```

A 380 g Hak tin is wet lentils at roughly 7 g protein per 100 g. It is being
costed at 24.0, the dry figure, which overstates its protein by about 3.4x and
puts it at the top of the ranking. `BRIEF` section 3.1 calls this the biggest
trap in the domain model, by name.

The cause is an alias asymmetry in the seed, not a matcher failure:

```
linzen_droog       -> [..., 'linzen', ...]        24 g P
linzen_blik        -> ['linzen blik', 'linzen in blik', 'linzen uit blik']
bruine_bonen_blik  -> ['bruine bonen', ...]        6 g P
```

The bare phrase `bruine bonen` is claimed by the tin, which is right, because
Hak sells tins. The bare word `linzen` is claimed by the dry form, which is
wrong for the same reason. Four Hak and Bonduelle tins land on `linzen_droog`,
and `Chan's Gele Spliterwten` and `Hak Spliterwten` share the shape.

Affected: `linzen`, `spliterwten`. Correctly handled: `bruine bonen`,
`kikkererwten`, `witte bonen`, `kidneybonen`, `zwarte bonen`, `doperwten`.

### 3.2 "cheapest in 0 weeks" is printed and shipped

`ranking._history` returns `0` when the only prior observation falls inside the
same week, and both the CLI and the export pass that straight through. The CLI
prints "cheapest in 0 weeks" beside 246 AH offers. It is meaningless as copy and
it crowds out the honest alternative the same code path already has, "no price
history yet". This is `BRIEF` section 9 rule 5 firing on data that cannot
support it.

**Amended during M14, and it is worse than "not enough history yet".**
`data/bonusrank.sqlite3` is gitignored, and `refresh-data.yml` starts from a
fresh `actions/checkout`. Every scheduled run therefore ingests into an **empty**
database and throws it away afterwards. Price history is not merely thin in
production - it structurally cannot accumulate, and never has.
`cheapest_in_weeks` can only ever be `0` or `None` there.

Everything in `BRIEF` section 3.4 depends on history: the percentile,
reference-price inflation, cycle prediction, stock-up advice. All four are
unreachable until something persists across runs, which makes this a blocker for
**M21 and M22** rather than a copy bug. The append-only trigger has been doing
its job perfectly on a database nobody keeps.

### 3.3 Macros render without a provenance marker on two app screens

`BRIEF` section 9 rule 1: never display a macro sourced as estimated without
visibly marking it. Every macro in this project is seed-sourced (see 2), so the
rule applies to all of them.

The offer list obeys it. `MainActivity.kt:537` appends `*`, and the list carries
a footnote explaining it. Two other surfaces do not, and the root cause is that
the export gives them nothing to mark with:

- **`food_types` in the export carries no provenance field at all.** Its keys
  are `key, name, meal_kind, g_per_unit, macros_per_100g`. The customiser's
  totals bar (`MainActivity.kt:370`) renders `"32.5 g eiwit"` bare, computed
  entirely from these.
- **`template_prices` candidates carry no provenance field either.** Same
  omission, same consequence on the same screen.

This is one fix in `export.py` plus the two render sites, not three separate
fixes.

### 3.4 Aldi exports zero ranked offers

`bonusrank export` reports `aldi: 8 archetypes, 0 ranked offers`. Aldi has 66
valid promo rows today, so this is a ranking-side gap rather than an adapter
one: Aldi has no base price catalogue, which is a confirmed structural fact
about its own site (`CLAUDE.md` section 4), and few of its promo SKUs match a
food type. The app's Aldi tabs are consequently empty. Honest, but it needs a
visible empty state rather than a blank list.

---

## 4. `docs/BRIEF.md` features not implemented

`PLAN-V2` section 2 expected this list to include waste adjustment. It does not.
That one is built.

| Feature | Brief | State |
|---|---|---|
| Waste adjustment | 3.3 | **Built.** `ranking._waste_adjust`, driven by `daily_consumption_g` and `freezer_horizon_days` from `config.yaml`. All 204 food types carry a shelf life; 104 are marked freezable. Surfaced in the CLI, the export, and a `--sort waste-adjusted` key. |
| Price percentile over N weeks | 3.4 | **Partial.** "Cheapest in N weeks" exists but is a first-cheaper-observation scan, not a percentile, and there is not enough history for it to say anything (see 3.2). |
| Reference-price inflation detection | 3.4 | **Not built.** No `reference_inflated` flag anywhere. |
| Promo cycle prediction, buy/wait | 3.4 | **Not built.** No median-interval computation, no hint. |
| Stock-up advice | 3.4 | **Not built.** |
| Weekly ILP optimiser | 5 | **Not built as specified.** What exists is the deliberately scoped-down per-meal solver of milestone 9. No weekly horizon, no variety cap across meals, no `max_stores` constraint, no budget constraint, no shopping list. Both section 5 safety rules do hold in the smaller solver. |
| NEVO macros | 2, tier 3 | **Not built.** `seed.load_nevo()` exists; zero rows have `source='nevo'`. The dataset needs usage conditions accepted at rivm.nl, which is the author's to do. |
| Open Food Facts by EAN | 2, tier 2 | **Not built.** `parse_nutrition_block` can read the shape; nothing fetches it. |
| Tier-1 FIR macros in production | 2, tier 1 | **Built, never run.** See section 2. |
| Full catalogue beyond promos | — | Not built. AH and Jumbo have search-based base price catalogues; neither walks the category tree. |
| Product image URLs | — | **Not stored anywhere.** `products` has no image column and the export has no image field. `docs/DESIGN.md` makes its own start conditional on these existing. |

---

## 5. Things that are right and should not be disturbed

Recorded because the next milestones rewrite a lot of the surrounding code.

- Append-only prices enforced by trigger, not by comment.
- Unknown is `None` end to end: an unpriced candidate keeps its slot and ranks
  last, one unpriced line nulls a whole total, and both name the culprit.
- The unit-price cross-check writes a question, never a verdict. Today's queue
  still holds the drained-weight cases that taught the rule: zongedroogde
  tomaten imply 0.50 of the label, Hak haricots verts 0.53, John West tuna in
  olive oil 0.703.
- Politeness lives in code, not in prose: `MAX_REQUESTS_PER_SECOND = 2.0`,
  `CACHE_TTL_SECONDS = 6 * 60 * 60`, an honest `User-Agent`, per-chain rate
  limiting, exponential backoff.
- Rules explain and never block; every one carries an authored note.

---

## 6. Carried forward into the milestone queue

Not fixed here, per the milestone's own instruction. Each needs a home.

1. **Canned lentils (3.1)** — seed alias fix plus a test asserting that no bare
   legume alias resolves to the dry form. Belongs with **M20**, which makes
   wrong macros far more visible, or earlier if convenient.
2. **"cheapest in 0 weeks" (3.2)** — belongs in **M21**, which rebuilds this
   signal as a percentile.
3. **Missing provenance markers (3.3)** — **M24** already has an acceptance
   criterion for exactly this. The `export.py` change should land with it.
4. **Empty Aldi list (3.4)** — **M23**, as an empty state.
5. **`product_macros` never populated** — the refresh workflow needs
   `--with-macros`. Belongs with **M15**, the first milestone where per-SKU
   macros are worth the requests.
6. **Duplicate food types from milestone 12** — `rucola` and `ijsbergsla`
   collide with `sla`'s aliases, and `biefstuk` with `runderbiefstuk_mager`.
   `rucola` still shows `geen prijs` in the README screenshots. `load_seed`
   rejects duplicate keys but nothing checks alias uniqueness.
7. **Archetype verdict strings are English** (`archetypes.py::_verdict`) while
   the rest of the UI is Dutch.
8. **`CLAUDE.md` section 6 seed counts are stale** (188/590 against the actual
   204/655).
