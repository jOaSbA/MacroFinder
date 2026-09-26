# MacroFinder Android app

Ranks this week's supermarket offers by protein or calories per euro, and lets
you search the whole catalogue, follow products and build meals. It ranks; it
never picks for you.

## Data flow

The app has no backend and never talks to a supermarket. It reads two things
from the `data-latest` GitHub release, both published by
`.github/workflows/refresh-data.yml` twice a day:

- **`latest.json`**, fetched on launch: ranked offers, meal templates and the
  ready-made vs home-made comparisons. `data/ExportModels.kt` mirrors
  `src/bonusrank/export.py` field for field; change one, change the other.
- **The catalogue**, a SQLite file synced in the background by WorkManager
  (`data/sync/`), on wifi only unless you tap "Nu verversen". The first sync is
  the full file; after that it chains small deltas from `manifest.json`.
  Nothing is installed until its sha256 matches, and an app never installs a
  catalogue whose schema it can't read (`APP_SCHEMA_VERSION` in `SyncPlan.kt`).

Until the catalogue arrives, the deal list falls back to the offers in
`latest.json`. The same sort and filter code runs on both.

## How it's put together

- `data/catalogue/`: the catalogue as the screens see it. `CatalogueReader`
  holds the SQL, `DealList` does filtering, sorting and tiers in plain Kotlin,
  `SearchIndex` builds an FTS4 index on the phone after each sync.
- `data/following/`: followed products and the "now on offer" notification.
  The decision is pure (`promoAlerts`) and tested on the JVM.
- `ui/`: `CatalogueViewModel` for deals, search, detail and following;
  `MacroFinderViewModel` for meals. `DealText` holds the rules about what text
  is shown, so the "never a bare estimate" rule has tests.
- `ui/theme/`: the tokens and type from `docs/DESIGN.md`. Archivo is bundled
  (`res/font`, OFL licence in `assets/licenses`).

Navigation is a back stack of `Route`s saved as strings, not a navigation
library. Filter and sort state live in `SavedStateHandle`.

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

Tests are always separate from production code, and all of them run in CI.

- `app/src/test/kotlin/`: JVM tests. The catalogue SQL runs here too, against
  sqlite-jdbc with the real published schema in `src/test/resources/app_schema.sql`
  (a Python test fails if that file drifts from `appdb.APP_SCHEMA`).
- `app/src/androidTest/kotlin/`: on-device tests. The sync end to end against a
  local HTTP server, and Compose UI tests for the deal list, product detail and
  meal customiser. CI runs them on an API 34 emulator; locally:

  ```bash
  cd android && gradle connectedDebugAndroidTest
  ```

- `tests/test_appdb_kotlin_parity.py` (Python side) checks that
  `CatalogueStore.kt` applies deltas to the same tables with the same keys as
  `appdb.py`, and that both agree on the schema version.

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
