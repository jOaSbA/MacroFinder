package com.macrofinder.app.data.catalogue

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase

/** [SqlRunner] over Android's own SQLite. The JVM tests use sqlite-jdbc instead. */
class AndroidSqlRunner(private val db: SQLiteDatabase) : SqlRunner {

    override fun <T> query(sql: String, args: List<Any?>, map: (Row) -> T): List<T> =
        db.rawQuery(sql, args.map { it?.toString() }.toTypedArray()).use { cursor ->
            val row = CursorRow(cursor)
            buildList { while (cursor.moveToNext()) add(map(row)) }
        }

    override fun exec(sql: String, args: List<Any?>) {
        if (args.isEmpty()) db.execSQL(sql) else db.execSQL(sql, args.toTypedArray())
    }

    override fun execBatch(sql: String, rows: List<List<Any?>>) {
        val statement = db.compileStatement(sql)
        try {
            for (row in rows) {
                statement.clearBindings()
                row.forEachIndexed { i, v ->
                    when (v) {
                        null -> statement.bindNull(i + 1)
                        is Long -> statement.bindLong(i + 1, v)
                        is Int -> statement.bindLong(i + 1, v.toLong())
                        is Double -> statement.bindDouble(i + 1, v)
                        else -> statement.bindString(i + 1, v.toString())
                    }
                }
                statement.executeInsert()
            }
        } finally {
            statement.close()
        }
    }

    override fun <T> transaction(block: () -> T): T {
        db.beginTransaction()
        try {
            val result = block()
            db.setTransactionSuccessful()
            return result
        } finally {
            db.endTransaction()
        }
    }

    private class CursorRow(private val c: Cursor) : Row {
        private fun index(column: String) = c.getColumnIndexOrThrow(column)
        override fun string(column: String): String? =
            index(column).let { if (c.isNull(it)) null else c.getString(it) }
        override fun double(column: String): Double? =
            index(column).let { if (c.isNull(it)) null else c.getDouble(it) }
        override fun long(column: String): Long? =
            index(column).let { if (c.isNull(it)) null else c.getLong(it) }
    }
}
