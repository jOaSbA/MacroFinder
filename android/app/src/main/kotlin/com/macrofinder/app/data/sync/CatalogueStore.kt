package com.macrofinder.app.data.sync

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import java.io.File

/**
 * The synced catalogue on this device.
 *
 * **Raw SQLite rather than Room**, which is a deliberate departure from
 * PLAN-V2 section 3.2, so here is why. The artifact arrives fully formed from
 * `src/bonusrank/appdb.py`: it already has its schema, its indexes and its
 * data. Room's value is generating type-safe queries against a schema the app
 * owns and migrating it over time - and the app owns neither. It would need
 * entity classes mirroring `APP_SCHEMA` exactly, a `@Database(version=)` kept
 * in lockstep with `appdb.SCHEMA_VERSION`, and any drift between the two
 * becomes a crash on somebody's phone rather than a mismatch the code can
 * notice and handle. Applying a delta is `ATTACH` plus `DELETE` and
 * `INSERT OR REPLACE`, which is what `appdb.apply_delta` does in Python and
 * which Room actively gets in the way of.
 *
 * Room would also mean KSP codegen, which milestone 13 already turned down for
 * saved meals for the same reason. Reading `meta.schema_version` and deciding
 * is both smaller and more honest than declaring a version and hoping.
 *
 * The file is swapped whole on a full sync and mutated in place on a delta.
 * Nothing else writes it.
 */
class CatalogueStore(private val context: Context) {

    private val dir: File get() = File(context.filesDir, "catalogue").apply { mkdirs() }

    val databaseFile: File get() = File(dir, "catalogue.sqlite")

    /** Where a download lands before it is verified. Never read directly. */
    fun stagingFile(name: String): File = File(dir, "staging-$name")

    fun exists(): Boolean = databaseFile.exists()

    /**
     * The build currently on disk, or null when there is none or it is unusable.
     *
     * A file that exists but cannot be opened or has no version is treated as
     * absent, which makes the recovery from a half-written or corrupt download
     * the ordinary cold-install path rather than a special case.
     */
    fun localVersion(): String? {
        if (!databaseFile.exists()) return null
        return try {
            open().use { db ->
                db.rawQuery("SELECT value FROM meta WHERE key='version'", null).use { c ->
                    if (c.moveToFirst()) c.getString(0).takeIf { it.isNotBlank() } else null
                }
            }
        } catch (e: Exception) {
            null
        }
    }

    fun schemaVersion(): Int? = try {
        open().use { db ->
            db.rawQuery("SELECT value FROM meta WHERE key='schema_version'", null).use { c ->
                if (c.moveToFirst()) c.getString(0).toIntOrNull() else null
            }
        }
    } catch (e: Exception) {
        null
    }

    fun open(): SQLiteDatabase = SQLiteDatabase.openDatabase(
        databaseFile.path, null, SQLiteDatabase.OPEN_READONLY,
    )

    /**
     * Replace the catalogue with a freshly downloaded full build.
     *
     * The rename is the commit point: until it happens the old catalogue is
     * still the one on disk and still works, so a sync that dies mid-download
     * leaves a usable app rather than an empty one.
     */
    fun installFull(staged: File, version: String) {
        require(staged.exists()) { "no staged file to install" }
        databaseFile.delete()
        check(staged.renameTo(databaseFile)) { "could not move the staged build into place" }
        stampVersion(version)
    }

    /**
     * Apply one delta in place, mirroring `appdb.apply_delta` statement for
     * statement so the two cannot drift.
     *
     * Deletions run before upserts: a row removed and a different row added
     * share nothing, but the other order would let a stale deletion erase a
     * fresh upsert.
     */
    fun applyDelta(delta: File, toVersion: String) {
        SQLiteDatabase.openDatabase(
            databaseFile.path, null, SQLiteDatabase.OPEN_READWRITE,
        ).use { db ->
            db.beginTransaction()
            try {
                db.execSQL("ATTACH DATABASE ? AS d", arrayOf(delta.path))
                for (table in DELTA_TABLES) {
                    val key = keyExpression(table)
                    db.execSQL(
                        "DELETE FROM main.$table WHERE $key IN " +
                            "(SELECT id FROM d.deletions WHERE tbl = ?)",
                        arrayOf(table),
                    )
                }
                for (table in DELTA_TABLES) {
                    db.execSQL("INSERT OR REPLACE INTO main.$table SELECT * FROM d.$table")
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
                runCatching { db.execSQL("DETACH DATABASE d") }
            }
        }
        stampVersion(toVersion)
    }

    /**
     * Record which build this is, in the database's own `meta` table.
     *
     * Not in a preference file. The version has to travel with the bytes it
     * describes, or a restore, a cleared cache or a half-applied delta leaves
     * the app confidently wrong about what it is holding - and the next delta
     * would then be applied to the wrong base.
     *
     * `appdb` deliberately keeps this OUT of the published file, because a
     * version stored inside the bytes it hashes cannot be computed. It is
     * written here, on arrival, once the bytes are known good.
     *
     * Safe against a later delta: a delta's `meta` upserts are
     * `next.meta EXCEPT prev.meta` and its deletions are keys in `prev` and not
     * in `next`, and 'version' is in neither, so this row is never touched by
     * one. It is rewritten explicitly after every apply instead.
     */
    private fun stampVersion(version: String) {
        SQLiteDatabase.openDatabase(
            databaseFile.path, null, SQLiteDatabase.OPEN_READWRITE,
        ).use { db ->
            db.execSQL(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('version', ?)",
                arrayOf(version),
            )
        }
    }

    fun clear() {
        dir.listFiles()?.forEach { it.delete() }
    }

    companion object {
        /**
         * Mirrors `appdb._TABLES`, in the same order. `prices` is keyed on
         * (product_id, lane) rather than product_id alone - a SKU that moves
         * from the shelf to a promo loses its shelf row, and keyed on the
         * product alone that deletion is invisible.
         */
        val DELTA_TABLES = listOf(
            "meta", "food_types", "shelves", "products", "product_macros", "prices",
            "price_history",
        )

        private val COMPOSITE_KEYS = mapOf(
            "prices" to listOf("product_id", "lane"),
            "price_history" to listOf("product_id", "week"),
        )

        private val SINGLE_KEYS = mapOf(
            "meta" to "key",
            "food_types" to "key",
            "shelves" to "key",
            "products" to "id",
            "product_macros" to "product_id",
        )

        /** `appdb._key_expr`, in SQL that SQLite on Android parses identically. */
        fun keyExpression(table: String): String =
            COMPOSITE_KEYS[table]?.joinToString(" || char(31) || ")
                ?: SINGLE_KEYS.getValue(table)
    }
}
