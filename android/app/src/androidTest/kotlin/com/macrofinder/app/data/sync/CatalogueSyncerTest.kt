package com.macrofinder.app.data.sync

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The sync, end to end, against a real HTTP server and a real SQLite file.
 *
 * **Does not run in CI** - it needs an emulator (milestone 29). Run it with
 * `gradle connectedDebugAndroidTest`. See `CatalogueStoreTest` for why the part
 * that rots is covered from the Python side instead.
 *
 * This is where PLAN-V2's "instrumented test covers the more-than-7-deltas-
 * behind fallback" criterion is met. The decision itself is pure and covered on
 * the JVM in `SyncPlanTest`; what this adds is that the decision is actually
 * the one the syncer acts on, over real HTTP, ending with real bytes on disk.
 */
@RunWith(AndroidJUnit4::class)
class CatalogueSyncerTest {

    private lateinit var server: MockWebServer
    private lateinit var store: CatalogueStore
    private lateinit var scratch: File

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        store = CatalogueStore(context)
        store.clear()
        scratch = File(context.cacheDir, "syncer-test").apply { deleteRecursively(); mkdirs() }
        server = MockWebServer().also { it.start() }
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    // -- fixtures --------------------------------------------------------------

    /**
     * Every table `CatalogueStore.DELTA_TABLES` walks, because a real published
     * artifact always has all of them and `applyDelta` rightly does not tolerate
     * a missing one - a delta short of a table is a broken delta, not a small one.
     */
    private fun schema(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
        db.execSQL(
            "CREATE TABLE food_types (key TEXT PRIMARY KEY, name_nl TEXT NOT NULL) WITHOUT ROWID"
        )
        db.execSQL(
            "CREATE TABLE products (id TEXT PRIMARY KEY, chain TEXT NOT NULL, " +
                "sku TEXT NOT NULL, name TEXT NOT NULL) WITHOUT ROWID"
        )
        db.execSQL(
            "CREATE TABLE product_macros (product_id TEXT PRIMARY KEY, " +
                "protein_per_100g REAL) WITHOUT ROWID"
        )
        db.execSQL(
            "CREATE TABLE prices (product_id TEXT NOT NULL, lane TEXT NOT NULL, " +
                "shelf_price REAL, PRIMARY KEY (product_id, lane)) WITHOUT ROWID"
        )
    }

    private fun buildDatabase(name: String, products: Int): File {
        val file = File(scratch, name)
        file.delete()
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            schema(db)
            db.execSQL("INSERT INTO meta VALUES ('schema_version','2')")
            repeat(products) {
                db.execSQL("INSERT INTO products VALUES ('ah:$it','ah','$it','Product $it')")
            }
        }
        return file
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1 shl 16)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun enqueueFile(file: File) {
        val buffer = Buffer().write(file.readBytes())
        server.enqueue(MockResponse().setResponseCode(200).setBody(buffer))
    }

    private fun enqueueJson(json: String) {
        server.enqueue(MockResponse().setResponseCode(200).setBody(json))
    }

    private fun syncer() = CatalogueSyncer(
        store = store,
        manifestUrl = server.url("/manifest.json").toString(),
        assetBaseUrl = server.url("").toString().trimEnd('/'),
    )

    // -- the acceptance criteria ----------------------------------------------

    @Test
    fun a_cold_install_downloads_and_installs_the_full_build() = runTest {
        val full = buildDatabase("full.sqlite", products = 40)
        enqueueJson(
            """{"status":"ok","schema_version":2,
                "full":{"version":"v1","file":"full.sqlite",
                        "sha256":"${sha256(full)}","bytes":${full.length()},"products":40},
                "deltas":[]}"""
        )
        enqueueFile(full)

        val outcome = syncer().sync()

        assertTrue("got $outcome", outcome is SyncOutcome.Installed)
        assertEquals("v1", (outcome as SyncOutcome.Installed).version)
        assertEquals(false, outcome.viaDelta)
        assertEquals("v1", store.localVersion())
    }

    @Test
    fun a_second_sync_with_nothing_new_transfers_no_database_at_all() = runTest {
        installBase("v1", products = 40)
        enqueueJson(
            """{"status":"ok","full":{"version":"v1","file":"full.sqlite","sha256":"x"},
                "deltas":[]}"""
        )

        val outcome = syncer().sync()

        assertEquals(SyncOutcome.UpToDate, outcome)
        // One request: the manifest. The catalogue itself was never asked for.
        assertEquals(1, server.requestCount)
    }

    @Test
    fun more_than_seven_deltas_behind_takes_the_full_build_instead() = runTest {
        // PLAN-V2's acceptance criterion for this milestone, end to end.
        installBase("v0", products = 40)
        val full = buildDatabase("full.sqlite", products = 60)

        val hops = (0..8).map { "v$it" }.zipWithNext { a, b ->
            """{"from":"$a","to":"$b","file":"d-$a-$b.sqlite","sha256":"y","bytes":100}"""
        }
        enqueueJson(
            """{"status":"ok",
                "full":{"version":"v8","file":"full.sqlite",
                        "sha256":"${sha256(full)}","bytes":${full.length()},"products":60},
                "deltas":[${hops.joinToString(",")}]}"""
        )
        enqueueFile(full)

        val outcome = syncer().sync()

        assertTrue("got $outcome", outcome is SyncOutcome.Installed)
        assertEquals(false, (outcome as SyncOutcome.Installed).viaDelta)
        assertEquals("v8", store.localVersion())
        // The manifest and exactly one asset: the full build. No delta was
        // fetched, which is the whole point of the limit.
        assertEquals(2, server.requestCount)
    }

    @Test
    fun a_subsequent_sync_applies_a_delta_and_transfers_well_under_a_megabyte() = runTest {
        // PLAN-V2's other acceptance criterion for this milestone. Measured on
        // the real catalogue a steady-state delta is 295 KB against a 24 MB
        // full build - 1.8%. The fixture here is tiny; what is asserted is that
        // the delta path is taken and that what crosses the wire is the delta.
        installBase("v1", products = 40)
        val delta = buildDelta("delta.sqlite")

        enqueueJson(
            """{"status":"ok",
                "full":{"version":"v2","file":"full.sqlite","sha256":"z","bytes":99999999},
                "deltas":[{"from":"v1","to":"v2","file":"delta.sqlite",
                           "sha256":"${sha256(delta)}","bytes":${delta.length()}}]}"""
        )
        enqueueFile(delta)

        val outcome = syncer().sync()

        assertTrue("got $outcome", outcome is SyncOutcome.Installed)
        val installed = outcome as SyncOutcome.Installed
        assertEquals(true, installed.viaDelta)
        assertEquals("v2", store.localVersion())
        assertTrue(
            "transferred ${installed.bytesTransferred} bytes",
            installed.bytesTransferred < 1_000_000,
        )

        // The row the delta added is really there, and the one it removed is gone.
        store.open().use { db ->
            db.rawQuery("SELECT name FROM products WHERE id='ah:99'", null).use { c ->
                assertTrue("the new product was not applied", c.moveToFirst())
            }
            db.rawQuery("SELECT 1 FROM products WHERE id='ah:0'", null).use { c ->
                assertTrue("the deleted product survived", !c.moveToFirst())
            }
        }
    }

    private fun buildDelta(name: String): File {
        val file = File(scratch, name)
        file.delete()
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            schema(db)
            db.execSQL(
                "CREATE TABLE deletions (tbl TEXT NOT NULL, id TEXT NOT NULL, " +
                    "PRIMARY KEY (tbl, id)) WITHOUT ROWID"
            )
            db.execSQL("INSERT INTO products VALUES ('ah:99','ah','99','Nieuw product')")
            db.execSQL("INSERT INTO deletions VALUES ('products','ah:0')")
        }
        return file
    }

    // -- honesty about bad bytes ----------------------------------------------

    @Test
    fun a_download_whose_hash_is_wrong_is_not_installed() = runTest {
        installBase("v1", products = 40)
        val full = buildDatabase("full.sqlite", products = 60)
        enqueueJson(
            """{"status":"ok",
                "full":{"version":"v2","file":"full.sqlite",
                        "sha256":"0000000000000000","bytes":${full.length()}},
                "deltas":[]}"""
        )
        enqueueFile(full)

        val outcome = syncer().sync()

        assertTrue("got $outcome", outcome is SyncOutcome.Failed)
        // The catalogue that was already there still is, and still works.
        assertEquals("v1", store.localVersion())
    }

    @Test
    fun a_halted_publisher_stops_before_downloading_anything() = runTest {
        installBase("v1", products = 40)
        enqueueJson(
            """{"status":"halted","full":{"version":"v9","file":"full.sqlite"},"deltas":[]}"""
        )

        val outcome = syncer().sync()

        assertTrue(outcome is SyncOutcome.Halted)
        assertEquals(1, server.requestCount)
        assertEquals("v1", store.localVersion())
    }

    @Test
    fun a_server_error_fails_the_sync_without_touching_the_catalogue() = runTest {
        installBase("v1", products = 40)
        server.enqueue(MockResponse().setResponseCode(503))

        val outcome = syncer().sync()

        assertTrue(outcome is SyncOutcome.Failed)
        assertEquals("v1", store.localVersion())
    }

    private fun installBase(version: String, products: Int) {
        store.installFull(buildDatabase("base-$version.sqlite", products), version)
    }
}
