# PLAN-V3: what to build next

PLAN-V2 is done (M14-M30, M28 declined). This plan picks the next goals by
looking at what existing products already do well, and keeping only what
passes PLAN-V2's test: **does this need macros?** If it doesn't, Mandje has it
or will, and it isn't worth weeks here.

Everything in PLAN-V2 section 6 (autonomy protocol) and section 7 (no store
listing, the app never calls a chain) still applies. So does the user's rule
from milestone 9: no day or week planner.

## What the others do

Checked 2026-09-26.

| Product | What it does well | What we take |
|---|---|---|
| [Mandje](https://mijnmandje.nl/hoe-het-werkt) | 10 chains, same product at other stores sorted per kilo, price history, favourite alerts, a shopping list priced per store | "Same thing, cheaper elsewhere", but per gram of protein instead of per kilo |
| [Supermarkt Scanner](https://www.supermarktscanner.nl/) | Search a word ("protein", "eieren") and see it across 8 chains with folder offers | Nothing new; our search already does this with macros |
| [GierigGroeien](https://gieriggroeien.nl/) | Supplement prices four times a day, price per kilo of whey | Supplements are a shelf we under-serve |
| [Drogespieren](https://drogespieren.nl/overig/goedkoop-eiwitrijk-eten) | A static table of grams of protein per euro for common foods | Proof the question is real. It is a blog post; we are the live version |
| Yuka, MyFitnessPal | Scan a barcode in the shop, get a verdict and a better alternative | The in-store moment: scan, see protein per euro and a cheaper swap |
| Keepa, Pricewise | Price charts and "tell me when it drops below X" | A target alert in protein terms, not in euros |
| Folder apps (Folderz) | A weekly "new folder is out" nudge | One weekly digest of the best protein deals, opt-in |

The pattern is that every other product answers "where is this cheapest?". None
answers "what's the cheapest way to get protein this week?". That stays the
wedge.

## Goals

Ordered by value, with dependencies noted. Each one gets a branch and a PR,
CI green, merged, and a line in CLAUDE.md, as before.

### M31: cheaper alternative on the product page

From Mandje's product comparison and Yuka's "better alternative". On the detail
screen, show up to three products with the same food type that are cheaper
per 100 g protein right now, at any chain, with the saving stated ("€0,40 minder per 100 g
eiwit, bij Jumbo").

- Pure Kotlin over the synced catalogue, JVM-tested.
- Unknown protein never counts as cheaper.
- Respects the chain filter the user already set.
- Done when: opening an AH kwark shows a cheaper Jumbo kwark when one exists,
  and nothing when it's already the cheapest.

### M32: my stores and diet

Mandje asks which stores you shop at. Ours does it with macros attached.

- A settings screen (from Over): chains I shop at, and "alleen plantaardig
  eiwit" using the food types' `origin` variant.
- Hidden chains disappear from lists, alternatives and meal prices.
- DataStore, local only.
- Done when: turning off Aldi removes it everywhere, and the vegetarian switch
  leaves kwark and tofu, drops kipfilet.

### M33: weekly protein digest

The folder-app nudge, with a reason to exist. After a sync that brings a new
promo week, one notification: the top three deals by protein per euro,
for the user's own stores. Opt-in, at most once per chain week, off by
default.

- Reuses the PromoNotifier channel logic and dedupe keys.
- Done when: a sync with new promos posts one digest, and a second sync the
  same week posts nothing.

### M34: price target alerts

From Keepa, in protein terms. On a followed product, optionally set "laat het
weten onder €X per 100 g eiwit". The check runs after each sync next to the
promo alert.

- Done when: a JVM test covers crossing, not crossing, and unknown protein
  (never alerts).

### M35: EAN codes

Needed for M36 and M37, and a research task first.

- Find where each chain exposes a GTIN: AH's FIR detail has one (the label
  fetch already calls it), Jumbo's product nodes need checking, Aldi's feed
  too.
- Store it on `products`, ship it in the app DB (schema 4, parity test).
- Budget: only the label-fetch path, which is already rate limited. No new
  per-SKU sweep of the whole catalogue.
- Done when: coverage per chain is measured and written in CLAUDE.md. If a
  chain has none, say so and move on.

### M36: Open Food Facts for Jumbo and Aldi macros

Jumbo and Aldi have no label nutrition, so every Jumbo and Aldi product runs
on the generic seed. With an EAN, Open Food Facts often has the label.

- Only for matched food products on a current offer, a small budget per run,
  cached hard (BRIEF section 7: OFF is a nonprofit, never sweep it).
- Label figures from OFF are a new macro source, marked as such, ranked below
  the chain's own label and above the seed.
- Done when: the share of Jumbo deals with label macros is measured before and
  after.

### M37: barcode scan in the shop

The Yuka and MyFitnessPal moment. Scan a barcode from the Zoeken tab, land on
the product page with protein per euro and the M31 alternatives.

- Camera scanning needs a library. Prefer one that works offline and without
  Google Play services (ZXing-based) over ML Kit; note the choice in CLAUDE.md.
- Unknown barcode: say so, offer a text search.
- Done when: scanning a known EAN from the fixture opens its product in a
  device test (fed an image, not a camera).

### M38: protein tally for a shop

Not a shopping list (PLAN-V2 says no to those) and not a planner. A
calculator: add products, see total protein, kcal, euros and euros per 100 g
protein for the whole basket, per chain. It answers "how much protein does this
shop buy me?"

- Local, keys only, re-priced on every sync like saved meals.
- Done when: the tally totals match the sum of its lines in a JVM test, and an
  unknown line poisons the total the same way MealMath does.

### M39: supplements shelf

GierigGroeien shows supplements are a real category. Check what the three
chains sell as whey, protein bars and shakes, make sure they map to the right
shelf and bucket, and that protein per euro is right per scoop and per bar.

- Done when: the top of the "Supplement" bucket reads sensibly on real data,
  with any mismatches fixed in the seed.

### M40: home screen widget

The top five protein deals for the user's stores, tap to open. Glance, one new
dependency, justified in CLAUDE.md.

- Done when: it renders on the emulator and updates after a sync.

### M41: polish pass

Dark mode on every screen, 200% text again on the new screens, empty states,
TalkBack labels on the new controls, a first-run line that says what the app is
for. Screenshots in the PR.

## Order

M31, M32, M33, M34 are app-only and can go straight away. M35 blocks M36 and
M37. M38 to M41 are independent. If a goal turns out bigger than written,
split it and ship the first half, as PLAN-V2 section 6.1 says.

## Not doing

- Shopping lists shared between people, accounts, a backend.
- More chains (Lidl, Plus, Dirk): useful, but breadth is Mandje's game and each
  chain is a new adapter to keep alive. Revisit only if the author asks.
- iOS.
- A day or week planner.
