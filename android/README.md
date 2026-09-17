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
   `raw.githubusercontent.com/jOaSbA/MacroFinder/main/docs/data/latest.json`
   (`app/build.gradle.kts`'s `DATA_URL` build config field) - no server to
   host, no API to maintain.

`app/src/main/kotlin/com/macrofinder/app/data/ExportModels.kt` mirrors
`export.py`'s JSON shape field-for-field. If you change one, change the other.

## Tests

Per this repo's testing rule: **tests are always separate from production
code**, and everything that can run in CI does.

- `app/src/test/kotlin/` - plain JVM unit tests (JSON decoding, filtering and
  sorting logic). No Android framework classes, no emulator. These run in
  GitHub Actions on every push (`.github/workflows/ci.yml`, `gradle
  testDebugUnitTest`).
- **No Compose UI / instrumentation tests exist yet.** They need an Android
  emulator, which is slow and flaky in CI. Until that's worth the cost, UI
  changes are verified manually: build the app (`gradle assembleDebug`) and
  run it on a device or emulator yourself. Do not add `androidTest` UI tests
  and assume they run in CI - they won't, unless the workflow is updated to
  provision an emulator.

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
