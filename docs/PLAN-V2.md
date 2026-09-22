# MacroFinder v2 — rework plan

Supersedes nothing in `docs/BRIEF.md` (the domain research there still holds). This
document defines **what gets built next and in what order**, and the protocol for
building it without the author in the loop.

Read `CLAUDE.md` and the existing `src/bonusrank/` tree before acting on anything
here. Milestone 0 exists because this plan was written from the README, not from
the code.

---

## 1. Positioning — read this before making product decisions

There is an incumbent: **Mandje** (mijnmandje.nl). Known facts, as of this writing:

- 10 chains, **186k+ products**, full catalogue with live prices
- **1.3M+ price points** tracked, with per-product price history
- Favourites + push notification when a tracked product goes on offer
- Shopping lists, shared between users
- Price per kilo/litre computed across formats and brands
- ~14k downloads, 4.4★, launched January 2026, free, no ads, no revenue model yet
- A public review asks for "sorteren op hoogste korting" — so even sorting is thin

**Do not try to beat Mandje at breadth.** They have a backend, a catalogue and a
user base. A solo project cannot win "all the deals from all the stores, nicer."

**The wedge is the macro layer.** Mandje will not build protein-per-euro properly,
because doing it honestly requires the unglamorous work in `docs/BRIEF.md` §3 —
food-type mapping, NEVO seeding, drained weights, dry-vs-cooked, per-100-kcal
ratios. That is a lot of effort for a feature maybe 2% of a general grocery
audience wants. It is 100% of what our audience wants.

Three consequences that should settle most product arguments:

1. **When in doubt, go narrower and denser, not broader.** A lifter wants a ranked
   table they can scan in 10 seconds, not a browsing experience. Our screens should
   show *fewer* products than Mandje's, sorted better.
2. **Every feature must survive the question "does this need macros?"** If the
   answer is no, Mandje already does it or will, and we should not spend weeks
   there. Shopping lists: no. Price history: yes, but only because it feeds
   "is this cheap protein, actually?"
3. **Full catalogue is infrastructure, not a feature.** We need it so that any
   product can be priced into a meal, not so users can browse 80k SKUs. Build it
   as a lookup layer, surface it only through search and the meal customiser.

### What the current app already gets right — do not throw these away

- Chain colour as the only saturated colour (AH red, Jumbo yellow, Aldi blue)
- `koop 2` shown next to `1+1 gratis` — required quantity beside the price
- Unknowns ranked last and shown, never hidden; one unpriced line makes the
  whole total unknown
- Authored rule warnings that explain without blocking

These are better than the incumbent's. The rework is about density, taxonomy and
data scale — not about replacing this design language.

---

## 2. Milestone 0 — audit and reconcile (do this first, always)

**Do not start any other milestone until this is committed.**

1. Read `CLAUDE.md`, `docs/BRIEF.md`, `config.yaml`, and the full `src/bonusrank/`
   tree.
2. Run the pipeline end to end against live AH data. Record what actually works.
3. Produce `docs/AUDIT.md` containing:
   - A table of every milestone 1–13 claimed complete, marked
     `verified` / `partial` / `broken`, with the evidence (test name, CLI output).
   - Current size of `docs/data/latest.json`, product count, and the repo's
     `.git` directory size.
   - Which `docs/BRIEF.md` features are **not** implemented. Expect at least:
     waste adjustment (§3.3), history percentile, reference-price inflation
     detection, promo cycle prediction, the full ILP weekly optimiser (§5).
   - Any place where a macro value is displayed without a visible provenance
     marker — this violates BRIEF §9 and is a bug.
4. Do not fix anything during the audit. Record and move on.

**Acceptance:** `docs/AUDIT.md` exists, every milestone 1–13 has a verdict with
evidence, and the gap list is explicit.

---

## 3. The architecture problem that has to be solved first

### 3.1 Why the current data plane cannot hold

Today: GitHub Actions runs the CLI, writes `docs/data/latest.json`, **commits it
back to the repo**, and the Android app fetches it from `raw.githubusercontent.com`.

That is a good design for ~500 bonus items. It fails at the thing you asked for
next, for two independent reasons:

**Git bloat.** Git stores a new blob for every changed file version. A full AH +
Jumbo catalogue with images and macros is roughly 40–50k SKUs; at ~300 bytes per
product that is ~15 MB per snapshot. Committed twice a day, that is ~10 GB of git
history per year, with no way to prune without rewriting history. The repo becomes
un-clonable within months.

**Mobile fetch.** A 15 MB JSON parsed on app start is several seconds of jank and
a lot of mobile data. Users on a train will simply close it.

### 3.2 The replacement

Build the catalogue as a **SQLite file published as a GitHub Release asset**, with
the app syncing deltas into a Room database.

- Release assets do **not** enter git history. Old ones can be deleted freely.
- SQLite ships indexes, so search and category filters are instant on device.
- Room is the natural Android counterpart; no new infrastructure, no server, no
  hosting bill, no account system.

```
bonusrank build-db  ->  macrofinder-{YYYYMMDD-HHMM}.sqlite  (full, ~20 MB)
                    ->  delta-{prev}-{next}.sqlite          (changed rows only)
                    ->  manifest.json                       (versions, hashes, sizes)
                            |
                    GitHub Release "data-latest"
                            |
                    Android app: reads manifest, applies deltas, falls back to
                    full download if more than 7 deltas behind
```

Keep `docs/data/latest.json` alive as a **promos-only** feed (current bonus items,
the ~500-item case). It is small, it works, it is the fast path for the main screen,
and it means the app still shows something useful if the catalogue sync fails.

**Two data paths, different cadences:**

| Feed | Contents | Size | Refresh |
|---|---|---|---|
| `latest.json` (git) | Current + upcoming promos, ranked | < 2 MB | 2×/day |
| SQLite release asset | Full catalogue, macros, price history | ~20 MB | 1×/week full, daily delta |

### 3.3 Images

**Never rehost images.** Store the chain's own CDN URL (`static.ah.nl/...`) as a
string and let Coil load it on device with its own disk cache. Store one URL per
product plus a rendered width hint. No image bytes ever enter the repo or the
SQLite file.

If a chain's CDN blocks hotlinking, degrade to a placeholder — do not build an
image proxy, that is a hosting cost and a legal exposure for zero user value.

---

## 4. The taxonomy — the actual product differentiator

You said Mandje's categories "still need work." Correct, but the fix is not better
supermarket categories. It is a **second, orthogonal axis** they don't have.

### 4.1 Two axes, both browsable

**Axis A — shelf taxonomy.** Mirror the familiar Dutch structure so browsing feels
normal. Mandje's own 18 top-level categories are a reasonable target shape:
Groente/Aardappelen/Fruit · Vlees/Kip/Vis · Kaas/Vleeswaren/Tapas ·
Zuivel/Plantaardig/Eieren · Bakkerij/Brood · Maaltijden/Gemak · Ontbijt/Beleg ·
Pasta/Rijst/Wereldkeuken · Soepen/Sauzen/Kruiden · Snoep/Koek/Chips · Diepvries ·
Frisdrank/Sap/Water · Koffie/Thee · Bier/Wijn/Sterke Drank · Drogisterij ·
Baby/Kind · Huishouden · Huisdier.

Map each chain's native taxonomy onto this once, in a YAML file, with an
`unmapped` bucket that raises a `needs_review` row. Do not attempt fuzzy
auto-mapping of categories — there are ~18 targets and three chains, just author it.

**Axis B — macro goal.** This is ours. Computed, not authored:

| Bucket | Rule | For |
|---|---|---|
| `eiwitbom` | ≥ 20 g protein/100 g | headline protein sources |
| `cut-vriendelijk` | ≥ 10 g protein per 100 kcal | dieting, protein per calorie |
| `bulk-calorieen` | bottom quartile €/1000 kcal | eating big cheaply |
| `snel-eiwit` | ≥ 15 g protein/serving, 0 min prep | grab-and-eat |
| `ontbijt` | cold, < 5 min, ≥ 20 g protein/serving | your stated breakfast need |
| `meal-prep-basis` | freezable, bulk-cookable, ≥ 15 g/100 g | Sunday cooking |
| `supplement` | whey, casein, creatine, etc. | |

### 4.2 The four metrics that drive every sort

```
protein_density    = g protein / 100 g          "how protein-dense is this food"
protein_ratio      = g protein / 100 kcal       "the cut metric"
eur_per_100g_protein                            "the headline"
eur_per_1000kcal                                "the bulk metric"
```

`protein_ratio` is the one Mandje will never have and the one your audience
actually argues about. Make it a first-class sort, not a detail-screen number.

### 4.3 Protein quality flag

Add `protein_quality: complete | incomplete | blend` to `food_types`, authored, with
a short note. Plant sources ranking top of €/100 g protein without a completeness
marker is misleading to a lifting audience — linzen are cheap protein and an
incomplete amino acid profile, and the app should say so in one line rather than
pretend the ranking is the whole story.

This is a one-word field and a tooltip. Do not build an amino-acid database.

---

## 5. Milestones

Each is independently shippable, has machine-checkable acceptance criteria, and
assumes the previous one is merged. One branch and one PR per milestone.

### M14 — Data plane migration
Build `bonusrank build-db`. Emit full SQLite + delta + `manifest.json`. Publish to
a GitHub Release from CI. Do **not** touch the Android app yet.
**Acceptance:** a release asset exists; `sqlite3 <file> "select count(*) from products"`
returns > 0; deltas apply cleanly to produce a byte-identical DB to the full build;
`.git` size unchanged from before the milestone.

### M15 — Full catalogue ingest, AH
Walk `v1/product-shelves/categories` and pull the full AH assortment, not just
bonus items. Store image URL, EAN, shelf price, unit size, category path.
Respect the rate limits in BRIEF §7 — this is a long, slow crawl; checkpoint it
so it can resume.
**Acceptance:** > 20k AH products in the DB with a non-null image URL and category;
crawl resumes correctly after being killed mid-run; no request exceeded 2/sec.

### M16 — Full catalogue ingest, Jumbo
Same, via `categories` + `products`.
**Acceptance:** > 15k Jumbo products; same checks as M15.

### M17 — Android: Room + delta sync
App reads `manifest.json`, downloads and applies deltas, falls back to full.
Sync runs on WorkManager, on unmetered network only, with visible progress and a
manual "refresh now."
**Acceptance:** cold install syncs full DB; subsequent sync applies a delta and
transfers < 1 MB; app is usable offline afterwards; instrumented test covers the
"more than 7 deltas behind" fallback.

### M18 — Upcoming deals
AH and Jumbo publish next period's promos before they start. Ingest anything with
`valid_from` in the future into a separate `upcoming` view. Never mix upcoming and
active in the same list without a visible date badge.
**Acceptance:** upcoming promos appear with a "vanaf <date>" badge; an active-only
filter exists and defaults to on; a test asserts no upcoming item can appear in
an active-only query.

### M19 — Shelf taxonomy mapping
Author `data/seed/category_map.yaml`, three chains → the 18 shelf categories.
**Acceptance:** ≥ 95% of catalogue products mapped; the remainder in
`needs_review`; a test fails the build if the unmapped rate exceeds 10%.

### M20 — Macro buckets + the four metrics
Implement §4.1 axis B and §4.2. Metrics computed at build time, stored, indexed.
**Acceptance:** every product with known macros has all four metrics; products
with unknown macros have NULL and are excluded from macro sorts (not defaulted to
zero); a test asserts NULL-not-zero.

### M21 — Deferred BRIEF features, part 1
Waste adjustment (BRIEF §3.3) and history percentile (§3.4). These were specified
and never built.
**Acceptance:** perishable promos show both headline and waste-adjusted price;
"cheapest in N weeks" appears wherever ≥ 8 weeks of history exists.

### M22 — Deferred BRIEF features, part 2
Reference-price inflation detection and promo cycle prediction (§3.4).
**Acceptance:** a product whose shelf price rose within 28 days pre-promo is
flagged; cycle prediction emits buy/wait on products with ≥ 3 observed promos;
both have unit tests against fixture history.

### M23 — UI rework: the ranked list
Dense, scannable, one screen. Sort control exposing all four metrics plus
"hoogste korting" (the thing Mandje's reviewers are asking for). Filters: chain,
shelf category, macro bucket, active/upcoming. Keep the chain-colour chip and the
required-quantity chip.
**Acceptance:** 50 items visible within two scrolls on a 6" screen; sort and
filter state survives rotation and process death; JVM tests cover the sort
comparators.

### M24 — UI rework: product detail
Image, macros with provenance markers, all four metrics, price history sparkline,
cycle hint, protein quality note, required quantity, waste-adjusted price.
**Acceptance:** no macro rendered without a provenance marker (BRIEF §9); a test
asserts this on the view model.

### M25 — Search over the full catalogue
On-device SQLite FTS over the synced catalogue. Instant, offline.
**Acceptance:** typing "kwark" returns results in < 100 ms on a mid-range device
with the full catalogue synced; works in airplane mode.

### M26 — Favourites + local alerts
Track products; notify when one enters a promo. Purely local — the sync brings the
promo data down, the device decides whether it matters. No server, no account, no
push infrastructure.
**Acceptance:** a favourited product entering a promo raises a notification after
the next sync; a test simulates it; notifications respect system quiet hours.

### M27 — Substitution engine surfacing
The engine exists in `src/bonusrank/`; the app's meals tab only partly shows it.
Give ready-made-vs-DIY its own entry point, with the taste-delta notes visible.
**Acceptance:** every comparison shown renders a non-empty `taste_delta_note`;
a test fails if any composition in the seed lacks one.

### M28 — The weekly optimiser
The full ILP from BRIEF §5, including both safety rules. The current
implementation is a bounded per-meal optimiser, not this.
**Acceptance:** both safety rules have explicit tests — one asserting kcal never
enters the objective with a negative coefficient, one asserting a plan violating
the variety cap or kcal floor is rejected and re-solved with the reason logged.

### M29 — Compose UI tests
There is currently no automated coverage of the screens. Add it for the list,
detail and customiser.
**Acceptance:** CI runs Compose tests on an emulator; the three screens have
coverage of their state transitions.

### M30 — Distribution readiness
See §7. Only start this once M14–M29 are merged.

---

## 6. Autonomy protocol

This section exists so the agent can run unattended. Follow it literally.

### 6.1 Decide these yourself — do not ask

| Decision | Default |
|---|---|
| Library choice within the existing stack | Pick the boring one, note it in `CLAUDE.md` |
| Naming, file layout, module boundaries | Follow existing conventions in the repo |
| Whether a value is a constant or config | Config if the author might change it, else constant |
| Error copy, log messages | Write them in English; user-facing strings in Dutch |
| Test fixture data | Invent it; never hit the network in tests |
| Dutch product names in seed data | Use the chain's own spelling |
| Ambiguous acceptance criterion | Satisfy the strictest reading, note the interpretation |
| A milestone turns out bigger than expected | Split it, ship the first half, update this file |

### 6.2 Stop and ask only for these

- A chain's API has changed shape such that an adapter needs redesign, not repair.
- An acceptance criterion cannot be met without violating BRIEF §7 politeness
  limits or §9 output rules.
- A milestone requires a paid service, an account system, or a server.
- Something in this plan contradicts something in `docs/BRIEF.md`.
- Work would involve publishing the app publicly (see §7).

Everything else: decide, log the decision in `CLAUDE.md`, continue.

### 6.3 Definition of done, per milestone

1. Acceptance criteria met, demonstrably — paste the command and its output into
   the PR description.
2. `pytest -q` green. Android JVM tests green.
3. `CLAUDE.md` updated with what was built, what was decided, what was deferred.
4. No new dependency outside the stack in BRIEF §7 without a line in `CLAUDE.md`
   justifying it.
5. No TODO left in code without a corresponding line in this file.
6. Commit messages reference the milestone number.

### 6.4 Anti-patterns

- **Do not refactor beyond the milestone's scope.** A drive-by rename across 40
  files makes the diff unreviewable and the author cannot tell what changed.
- **Do not silently widen scope.** If M15 turns into "and also Aldi," stop.
- **Do not default unknown macros to zero.** NULL propagates; zero lies.
- **Do not add an account system.** Every feature here works locally.
- **Do not skip a test gate to make progress.** A red suite blocks the next
  milestone; fixing it *is* the next task.
- **Do not mock the chain APIs into passing.** If a crawl doesn't work, the
  milestone isn't done.

---

## 7. What changes when other people use this

The current politeness position in BRIEF §7 — "a single personal user making a few
hundred requests a week" — is what makes the undocumented-endpoint use defensible.
Sharing this with lifting friends changes some of that and not other parts.

**The static-snapshot architecture already solves the main problem.** One scraper
run feeds N devices. Ten users or a thousand, the chains see identical traffic.
Keep it that way: the app must **never** call a chain API directly. Everything goes
through the published snapshot. This is now an architectural rule, not a preference.

What genuinely changes:

- **Scale of use shifts the legal picture.** A personal tool is one thing; a
  distributed app redistributing a chain's catalogue, images and pricing is
  another, regardless of how polite the scraper is. Before any public listing,
  the author needs to decide that deliberately. Hotlinked product images are the
  most exposed part.
- **Attribution and accuracy matter more.** Wrong prices shown to strangers
  damage people's shopping, not just yours. The provenance markers in BRIEF §9
  stop being a nicety.
- **A kill switch becomes necessary.** The app should read a `status` field from
  `manifest.json` and be able to show a maintenance message if a chain asks the
  project to stop.

**M30 is therefore: build the kill switch, add an about screen stating data
sources and that the app is unaffiliated, and then stop.** Do not publish to Play
Store, do not create a listing, do not share a link beyond a direct APK to people
the author knows. Publishing is the author's decision to make with the full
picture, not a milestone an agent completes.

Sideloading an APK to a handful of friends is a different act from a public
listing, and only the first is in scope here.

---

## 8. Open questions for the author

Not blocking — the defaults above are fine — but worth a decision at some point:

1. **iOS?** Mandje ships both. Doing so here means abandoning Compose or adopting
   KMP. Current plan assumes Android only.
2. **How many stores does the author actually shop at weekly?** The optimiser's
   `max_stores` default is 2. If the real answer is 1, several features simplify.
3. **Is the protein quality flag wanted, or is it noise?** It is one field and one
   tooltip, but it is also an opinion about nutrition being baked into a price tool.
