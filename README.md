# MacroFinder

Tracks Dutch supermarket promotions (Albert Heijn, Jumbo, Aldi) and ranks food by
protein-per-euro. Two parts:

- **`bonusrank`** (`src/bonusrank/`) - a Python CLI that scrapes the three chains,
  parses prices and macros, matches products to food types, and ranks what's on
  offer. It also crawls the full assortment: 52,489 products at last count.
- **MacroFinder** (`android/`) - a Kotlin/Jetpack Compose Android app that shows
  that data as a browsable, filterable list: tabs for meals, snacks, drinks, and
  everything else, each item showing its price, which promo applies and why it's
  cheaper, and its macros. It does not pick meals for you - you filter and choose.

## The app

Real screenshots, running on an emulator against live Albert Heijn data.

| Meals | Build your own |
|---|---|
| ![The Meals tab: templates to build from, then ready-made-vs-DIY comparisons](docs/images/meals-tab.png) | ![The Pasta customiser: each slot's candidates ranked cheapest-first, with a live total pinned to the bottom](docs/images/customiser.png) |

| Combination rules | Dark mode |
|---|---|
| ![Picking pesto alone triggers an authored warning that the dish is unfinished](docs/images/rule-warning.png) | ![The same screen in dark mode](docs/images/dark-mode.png) |

Three things those screens are doing on purpose:

- **The red chip is the only saturated colour in the app**, and it is the chain's
  own: red at Albert Heijn, yellow at Jumbo, blue at Aldi, exactly as on the shelf.
  `koop 2` next to a `1+1 gratis` is there because that deal means two jars in your
  fridge, not one cheap one.
- **Unknowns are shown, never hidden.** `rucola - geen prijs` stays in the list,
  ranked last. One unpriced line makes the whole total unknown rather than quietly
  summing the rest.
- **Rules explain, they never block.** *"Pesto alleen op pasta is droog en eenzijdig
  vet"* is a sentence a person wrote in `data/seed/templates.yaml`. You can still
  cook it.

Every macro figure carries a marker saying whether it came from the product's own
label or from a generic table. Most are still generic, and the app says so rather
than presenting an estimate as a fact.

## How data gets from one to the other

There is no backend server and no API. Two scheduled GitHub Actions jobs publish
two feeds, on different cadences, because they change at different speeds.

| Feed | Contents | Size | How | Refresh |
|---|---|---|---|---|
| `latest.json` | current promos, ranked | ~900 KB | GitHub **Release** asset | twice a day |
| `macrofinder-*.sqlite` | the full catalogue | ~24 MB | GitHub **Release** asset | weekly |

Both live on the `data-latest` release, so the bots never commit. The app fetches
`latest.json` on launch. It is small, and it is what keeps a failed catalogue sync from meaning a broken app.

The catalogue is a release asset rather than a committed file because git cannot
prune. A 24 MB snapshot committed twice a day is roughly 10 GB of history a year
that can never be removed without rewriting it, and the repo becomes un-clonable
within months. Release assets can be deleted freely.

Each catalogue build also emits a delta against the previous one. The deltas are
verified on every build: applying one to the previous database has to reproduce
the next one **byte for byte**, or it is not published. In steady state a delta is
about 1.8% of a full download.

```
bonusrank scrape/rank --export--> latest.json ------------------------------> app
bonusrank catalogue/build-db ---> macrofinder-{hash}.sqlite + delta + manifest.json
                                     |
                                 GitHub Release "data-latest"
```

**The app does not read the catalogue yet.** The data plane is built and running;
wiring the app to sync it into a local Room database is the next milestone. Until
then the app shows what `latest.json` carries.

That cadence is a deliberate choice, not a default: these are undocumented,
unofficial endpoints. The full catalogue crawl is about 1,000 requests, capped at
2 per second per chain, and it runs once a week. One scraper run feeds every
device, and the app never calls a chain directly - that is an architectural rule,
not a preference, and it is what keeps the request volume flat no matter how many
people use the app.

## Repo layout

```
src/bonusrank/       the CLI: adapters, parsers, matcher, ranking, pricing,
                      archetypes/compositions, the per-meal optimiser, the
                      full-catalogue crawl, the published app database, export
tests/                Python tests (pytest) - kept separate from src/, see below
data/seed/            hand-authored reference data (food macros, meal archetypes)
docs/BRIEF.md         the original project brief and domain research
docs/PLAN-V2.md       what gets built next, and in what order
docs/AUDIT.md         what actually works, measured against a live run
docs/DESIGN.md        the visual direction for the UI rework
docs/images/          app screenshots used in this README
android/              the Android app (Kotlin + Jetpack Compose)
.github/workflows/    CI (tests), the data refresh, and the catalogue build
CLAUDE.md             detailed engineering log for the Python backend
```

## Running the backend yourself

```bash
pip install -e ".[dev]"
bonusrank seed
bonusrank ingest --chain ah --with-macros 300
bonusrank prices --refresh --all --chain ah
bonusrank compare --chain ah
bonusrank export --out dist/latest.json
```

The full catalogue crawl is separate, because it is long and only worth running
weekly. It checkpoints per page and resumes, so killing it costs nothing:

```bash
bonusrank catalogue --chain ah          # ~300 requests, or use --max-requests N
bonusrank catalogue --chain jumbo       # ~712 requests
bonusrank build-db --out-dir dist/data  # the SQLite build, delta and manifest
```

## Tests

Tests live entirely under `tests/` (Python) and `android/app/src/test/` (Kotlin),
never mixed into the implementation files.

- **Python (`pytest`)**: 749 tests, running fully in GitHub Actions on every push
  and PR (`.github/workflows/ci.yml`). No live network access is needed - the test
  suite uses fixtures and an in-memory database.
- **Android (`android/app/src/test/`)**: 65 plain JVM unit tests (JSON decoding,
  filtering and sorting, rule evaluation, meal costing, saved-meal round trips).
  Also run in CI, no emulator needed. There are currently no Compose UI /
  instrumentation tests, since those need an emulator; UI changes are verified
  manually. See `android/README.md` for the full story.

Run everything locally:

```bash
pytest -q                                  # Python
cd android && gradle testDebugUnitTest     # Android (needs a local Gradle install)
```

## Status

Milestones 1-16 are complete. See `CLAUDE.md` for the full engineering history
(endpoint discovery, parser edge cases, matcher tuning, the optimiser's safety
rules) and `docs/AUDIT.md` for a verified account of what works, measured against
a live run rather than claimed.

Working today: three chain adapters, a tested parser and matcher, a ranking CLI, a
ready-made-vs-DIY substitution engine with a bounded per-meal optimiser, the full
catalogue crawl with product images, a byte-deterministic SQLite data plane with
verified deltas, and the app itself - browsable ranked lists plus a slot-based
meal customiser with on-device re-pricing and saved meals.

Not done yet, in rough order: the app syncing the catalogue into a local database,
upcoming-week promos, a shelf-category taxonomy, macro goal buckets, and the
deferred brief features around price history. `docs/PLAN-V2.md` has the list.

Two known limits worth stating plainly:

- **Price history does not accumulate.** Each CI run starts from a fresh checkout
  with a gitignored database, so "cheapest in N weeks" has nothing to compute
  from and correctly says so. Everything in the brief that depends on history is
  blocked on fixing that.
- **Aldi has no browsable catalogue.** Its own site does not publish one, so Aldi
  is limited to its weekly offer feed. That is a fact about the site, not a gap
  here.

This is a personal tool, built against undocumented endpoints and not affiliated
with any of the three chains.
