plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.macrofinder.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.macrofinder.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        // Milestone 17. These tests need an emulator and do NOT run in CI; see
        // android/README.md and the class comment on CatalogueStoreTest.
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Both feeds live on the `data-latest` release, not in git. The tag is
        // a moving pointer at "the current data", so these URLs never change.
        // latest.json used to be committed twice a day by a bot, which buried
        // the real history under snapshot commits.
        buildConfigField(
            "String", "DATA_URL",
            "\"https://github.com/jOaSbA/MacroFinder/releases/download/data-latest/latest.json\"",
        )
        buildConfigField(
            "String", "MANIFEST_URL",
            "\"https://github.com/jOaSbA/MacroFinder/releases/download/data-latest/manifest.json\"",
        )
        buildConfigField(
            "String", "ASSET_BASE_URL",
            "\"https://github.com/jOaSbA/MacroFinder/releases/download/data-latest\"",
        )
    }

    // The Kotlin source lives under kotlin/ rather than java/, including for
    // the instrumented tests.
    sourceSets {
        getByName("androidTest").kotlin.srcDir("src/androidTest/kotlin")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.4")
    implementation("androidx.activity:activity-compose:1.9.1")

    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.material3:material3")

    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Product images straight from the chain's own CDN, with an on-device
    // disk cache. PLAN-V2 section 3.3 names Coil; nothing is rehosted.
    implementation("io.coil-kt:coil-compose:2.7.0")

    // Saved meals, on-device only (milestone 13). DataStore rather than Room:
    // the persisted state is a short list of small objects, and a JSON string
    // through the serialization plugin already here beats adding KSP codegen
    // and a database schema. See data/SavedMealsStore.kt.
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // Milestone 17: the background catalogue sync. WorkManager rather than a
    // coroutine on app start, because the constraint that matters - unmetered
    // network only - is one the system enforces and the app cannot. A 24 MB
    // download over somebody's mobile data is the kind of thing an app only
    // gets to do once.
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    // WorkManager reports progress as LiveData; this is the Compose bridge.
    implementation("androidx.compose.runtime:runtime-livedata")

    // Unit tests (JVM, no emulator - see android/README.md). Compose UI itself
    // is intentionally left untested here; see that README for why.
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
    // WorkInfo and Data are plain value classes, so the sync-state mapping is
    // JVM-testable without an emulator.
    testImplementation("androidx.work:work-runtime-ktx:2.9.1")
    // Runs the catalogue SQL on the JVM against the real published schema,
    // so the queries are tested in CI rather than only on an emulator.
    testImplementation("org.xerial:sqlite-jdbc:3.46.1.0")

    // Instrumented tests (emulator, NOT run in CI). Milestone 17 uses these for
    // the one thing reading source text cannot establish: that the delta SQL
    // does what it says on a real SQLite database. Run with
    // `gradle connectedDebugAndroidTest`.
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:core-ktx:1.6.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    // A local HTTP server, so the end-to-end sync test drives real downloads
    // without reaching the network. Already an okhttp project.
    androidTestImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
}
