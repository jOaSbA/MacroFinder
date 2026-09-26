package com.macrofinder.app.data.sync

import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Applying a real delta to a real SQLite file.
 *
 * **This does not run in CI.** It needs an emulator, and per `android/README.md`
 * this project does not provision one in GitHub Actions yet (that is milestone
 * 29). Run it yourself:
 *
 * ```
 * cd android && gradle connectedDebugAndroidTest
 * ```
 *
 * The part of this that rots - the table list and the key expressions staying
 * in step with `appdb._TABLES` - is covered in CI instead, from the Python
 * side, by `tests/test_appdb_kotlin_parity.py`. What is covered here is the SQL
 * actually doing what it says on a real database, which no amount of reading
 * source text can establish.
 *
 * The fixtures are built here rather than committed as binaries, because a
 * `.sqlite` file in git is a blob nobody can review in a diff - the same reason
 * this repo does not commit a Gradle wrapper jar.
 */
@RunWith(AndroidJUnit4::class)
class CatalogueStoreTest {

    private lateinit var store: CatalogueStore
    private lateinit var scratch: File

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        store = CatalogueStore(context)
        store.clear()
        scratch = File(context.cacheDir, "sync-test").apply { deleteRecursively(); mkdirs() }
    }

    // -- fixtures --------------------------------------------------------------

    /** The subset of `appdb.APP_SCHEMA` these tests touch. */
    private fun schema(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
        db.execSQL(
            "CREATE TABLE food_types (key TEXT PRIMARY KEY, name_nl TEXT NOT NULL, " +
                "protein_per_100g REAL) WITHOUT ROWID"
        )
        db.execSQL(
            "CREATE TABLE shelves (key TEXT PRIMARY KEY, label TEXT NOT NULL, " +
                "sort_order INTEGER NOT NULL) WITHOUT ROWID"
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
        db.execSQL(
            "CREATE TABLE price_history (product_id TEXT NOT NULL, week TEXT NOT NULL, " +
                "price REAL NOT NULL, PRIMARY KEY (product_id, week)) WITHOUT ROWID"
        )
    }

    private fun buildBase(): File {
        val file = File(scratch, "base.sqlite")
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            schema(db)
            db.execSQL("INSERT INTO meta VALUES ('schema_version','3')")
            db.execSQL("INSERT INTO products VALUES ('ah:1','ah','1','Kwark')")
            db.execSQL("INSERT INTO products VALUES ('ah:2','ah','2','Kipfilet')")
            db.execSQL("INSERT INTO products VALUES ('ah:3','ah','3','Seizoensartikel')")
            db.execSQL("INSERT INTO prices VALUES ('ah:1','shelf',1.20)")
            db.execSQL("INSERT INTO prices VALUES ('ah:2','shelf',3.99)")
            db.execSQL("INSERT INTO prices VALUES ('ah:3','shelf',0.99)")
        }
        return file
    }

    /**
     * A delta covering all three things that can happen between builds: a row
     * changes, a row appears, and a row disappears - including the lane case,
     * where `ah:2` moves off the shelf and onto a promo.
     */
    private fun buildDelta(): File {
        val file = File(scratch, "delta.sqlite")
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            schema(db)
            db.execSQL(
                "CREATE TABLE deletions (tbl TEXT NOT NULL, id TEXT NOT NULL, " +
                    "PRIMARY KEY (tbl, id)) WITHOUT ROWID"
            )
            db.execSQL("INSERT INTO products VALUES ('ah:4','ah','4','Skyr')")
            db.execSQL("INSERT INTO products VALUES ('ah:1','ah','1','Kwark magere')")
            db.execSQL("INSERT INTO prices VALUES ('ah:2','promo',2.99)")
            db.execSQL("INSERT INTO prices VALUES ('ah:4','shelf',1.79)")
            db.execSQL("INSERT INTO deletions VALUES ('products','ah:3')")
            // The composite key, spelled exactly as `appdb._key_expr` spells it.
            db.execSQL("INSERT INTO deletions VALUES ('prices','ah:3' || char(31) || 'shelf')")
            db.execSQL("INSERT INTO deletions VALUES ('prices','ah:2' || char(31) || 'shelf')")
        }
        return file
    }

    private fun install(): Unit = store.installFull(buildBase(), "v1")

    private fun <T> query(sql: String, read: (android.database.Cursor) -> T): List<T> =
        store.open().use { db ->
            db.rawQuery(sql, null).use { c ->
                buildList { while (c.moveToNext()) add(read(c)) }
            }
        }

    // -- installing ------------------------------------------------------------

    @Test
    fun a_full_build_installs_and_reports_its_version() {
        install()

        assertEquals("v1", store.localVersion())
        assertEquals(3, store.schemaVersion())
        assertEquals(3, query("SELECT count(*) FROM products") { it.getInt(0) }.single())
    }

    @Test
    fun no_local_catalogue_reports_no_version_rather_than_throwing() {
        assertNull(store.localVersion())
    }

    @Test
    fun an_unreadable_file_reads_as_absent_so_recovery_is_the_cold_install_path() {
        install()
        store.databaseFile.writeText("this is not a database")

        assertNull(store.localVersion())
    }

    // -- applying a delta ------------------------------------------------------

    @Test
    fun a_delta_adds_changes_and_removes_the_right_rows() {
        install()

        store.applyDelta(buildDelta(), "v2")

        val names = query("SELECT id, name FROM products ORDER BY id") {
            it.getString(0) to it.getString(1)
        }
        assertEquals(
            listOf("ah:1" to "Kwark magere", "ah:2" to "Kipfilet", "ah:4" to "Skyr"),
            names,
        )
    }

    @Test
    fun losing_one_price_lane_removes_only_that_lane() {
        // The case that made `deletions` need a composite key. `ah:2` was on
        // the shelf and is on promo now; keyed on product_id alone the shelf
        // row survives and the app shows two disagreeing prices.
        install()

        store.applyDelta(buildDelta(), "v2")

        val lanes = query("SELECT product_id, lane FROM prices ORDER BY product_id, lane") {
            it.getString(0) to it.getString(1)
        }
        assertEquals(
            listOf("ah:2" to "promo", "ah:1" to "shelf", "ah:4" to "shelf").sortedBy { it.first },
            lanes,
        )
    }

    @Test
    fun applying_a_delta_advances_the_recorded_version() {
        install()

        store.applyDelta(buildDelta(), "v2")

        assertEquals("v2", store.localVersion())
    }

    @Test
    fun a_delta_that_fails_partway_leaves_the_catalogue_as_it_was() {
        // The whole apply runs in one transaction. A half-applied delta would
        // leave a device on a version the manifest describes but whose rows do
        // not match it, and the next delta would then be applied to that.
        install()
        val broken = File(scratch, "broken.sqlite")
        SQLiteDatabase.openOrCreateDatabase(broken, null).use { db ->
            schema(db)
            db.execSQL(
                "CREATE TABLE deletions (tbl TEXT NOT NULL, id TEXT NOT NULL, " +
                    "PRIMARY KEY (tbl, id)) WITHOUT ROWID"
            )
            db.execSQL("INSERT INTO products VALUES ('ah:9','ah','9','Nieuw')")
            db.execSQL("DROP TABLE prices")   // makes the apply fail midway
        }

        runCatching { store.applyDelta(broken, "v2") }

        assertEquals("v1", store.localVersion())
        assertEquals(3, query("SELECT count(*) FROM products") { it.getInt(0) }.single())
    }

    @Test
    fun the_app_is_usable_offline_once_a_catalogue_is_installed() {
        // Nothing here touches the network: the point is that everything the
        // app reads comes off local disk once a sync has happened.
        install()

        val protein = query("SELECT count(*) FROM products WHERE chain='ah'") { it.getInt(0) }
        assertEquals(listOf(3), protein)
    }
}
