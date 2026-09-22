# MacroFinder Android app

A browsable, filterable list of ranked meals, snacks, drinks, and everything
else, with price, the promo that makes it cheap, and macros next to each item.
This is deliberately **not** an optimiser: the app never picks for you, it
only ranks and filters what you ask to see. (The Python backend does have a
per-meal optimiser - `bonusrank compare`'s "Optimised" line - but that's a
CLI-only feature this app does not surface, on purpose.)

## Data flow

This app has no backend and no scraping code of its own:

1. The Python tool in the repo root (`src/bonusrank/`) scrapes AH/Jumbo/Aldi
   and ranks offers, exactly as it always has.
2. `bonusrank export` serializes that into `docs/data/latest.json`
   (`src/bonusrank/export.py`).
3. `.github/workflows/refresh-data.yml` runs that on a schedule and commits
   the result.
4. This app fetches that file straight from
   `raw.githubusercontent.com/jOaSbA/MacroFinder/master/docs/data/latest.json`
   (`app/build.gradle.kts`'s `DATA_URL` build config field) - no server to
   host, no API to maintain.

`app/src/main/kotlin/com/macrofinder/app/data/ExportModels.kt` mirrors
`export.py`'s JSON shape field-for-field. If you change one, change the other.

## The meal customiser (milestone 13)

The Meals tab also lets you **build** a meal instead of only picking one: choose
a pasta, a meat, a sauce, optional cheese and greens, each slot listing its real
candidates cheapest-first from this week's prices.

This is the one place the app computes rather than displays, and the split is
deliberate:

- **Python ranks.** `templates.py` prices every slot candidate and ships the
  ranked lists in the export. There is one implementation of "what does a kilo
  of this cost", and it is the tested one in `prices.py`.
- **Kotlin re-prices.** `data/MealMath.kt` multiplies the `eur_per_kg` rates
  the export already carried when you change a quantity or add an extra, so the
  total moves immediately rather than at the next refresh.
- **Kotlin evaluates the rules, Python authors them.** `data/MealRules.kt`
  reads the rules seeded in `data/seed/templates.yaml`. A rule never blocks a
  choice - it shows the author's own note and gets out of the way.

Three invariants worth not breaking:

- **Rule evaluation is three-valued**: satisfied / violated / **unknown**. A
  meal containing something the app cannot identify makes some rules genuinely
  undecidable, and unknown reaches the screen as unknown rather than passing.
- **Unknown poisons totals, in both directions.** One unpriced line makes the
  euro total null; one line with a missing macro makes that macro total null.
  Both name the offending line so the UI can say which. This is the app-side
  copy of `archetypes.py::_price_composition` and `_sum_or_none`.
- **Saved meals store keys and quantities, never prices.** That is what makes a
  saved meal re-cost itself as the weekly bonus rotates. They also key on
  strings (`templateKey`, `slotKey`, `foodType`) and never on a database id,
  because `load_templates` re-inserts its rows on every `bonusrank seed` and an
  integer id would silently re-point at a different slot.

Saved meals live on this phone only, in DataStore (`data/SavedMealsStore.kt`).
No backend, nothing committed to the repo, and they do not sync anywhere.

## Tests

Per this repo's testing rule: **tests are always separate from production
code**, and everything that can run in CI does.

- `app/src/test/kotlin/` - plain JVM unit tests (JSON decoding, filtering and
  sorting, rule evaluation, meal costing, saved-meal serialisation). No Android
  framework classes, no emulator. These run in GitHub Actions on every push
  (`.github/workflows/ci.yml`, `gradle testDebugUnitTest`).
- `SavedMealsTest` tests `serializeMeals`/`deserializeMeals` rather than
  DataStore itself. Those two are split out of `SavedMealsStore` for exactly
  that reason: the round trip is the part that can silently lose a user's
  saved meals, and it is testable where CI runs.
- `app/src/androidTest/kotlin/` - **instrumented tests, which do NOT run in
  CI.** They need an emulator, and the workflow does not provision one
  (milestone 29). CI does *compile* them, which is most of what stops them
  rotting. Run them yourself:

  ```bash
  cd android && gradle connectedDebugAndroidTest
  ```

  Milestone 17 added 15 of them, covering the catalogue sync end to end: real
  HTTP, a real SQLite file, real deltas. That is the one thing no JVM test can
  establish, because the delta application is SQL against a database rather
  than logic over objects.

  The part of the sync that *rots* is covered in CI instead, and from the
  Python side: `tests/test_appdb_kotlin_parity.py` reads `CatalogueStore.kt`
  and checks its table list and key expressions still match `appdb._TABLES`. A
  table added on one side and not the other means that table silently never
  syncs, and that is exactly the kind of drift an emulator test found weeks
  later would be too late for.

- **No Compose UI tests exist yet.** UI changes are verified manually: build
  the app (`gradle assembleDebug`) and run it on a device or emulator. Do not
  add Compose UI tests and assume they run in CI - they won't, unless the
  workflow is updated to provision an emulator.

## Getting a runnable app without installing anything

Every push builds a debug APK in CI. To get it:

1. Open the repo's **Actions** tab, click the most recent green run.
2. Download the **`macrofinder-debug-apk`** artifact (it is a zip).
3. Copy the `app-debug.apk` inside to your phone and tap it. Android will ask
   you to allow installing from this source.

That APK is **debug-only and signed with the standard debug key**. It cannot be
published to a store, and it is not a release build - it is for looking at the
app on a real device without installing the Android toolchain. Artifacts expire
after 14 days.

## Building locally

This repo does not commit a Gradle wrapper JAR (a binary file with nothing to
review in a diff). Install Gradle yourself (`brew install gradle`, or via
[sdkman](https://sdkman.io/)) matching the version in
`.github/workflows/ci.yml`, or open `android/` in Android Studio, which
manages Gradle for you automatically.

```bash
cd android
gradle testDebugUnitTest   # unit tests
gradle assembleDebug       # builds app/build/outputs/apk/debug/app-debug.apk
```
