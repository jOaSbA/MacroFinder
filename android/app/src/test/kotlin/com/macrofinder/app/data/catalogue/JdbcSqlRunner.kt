package com.macrofinder.app.data.catalogue

import java.sql.Connection
import java.sql.DriverManager
import java.sql.ResultSet

/**
 * [SqlRunner] over sqlite-jdbc, so the catalogue queries run on the JVM
 * against the real published schema (`src/test/resources/app_schema.sql`,
 * kept in step with `appdb.APP_SCHEMA` by a Python test).
 */
class JdbcSqlRunner private constructor(val connection: Connection) : SqlRunner {

    override fun <T> query(sql: String, args: List<Any?>, map: (Row) -> T): List<T> =
        connection.prepareStatement(sql).use { st ->
            args.forEachIndexed { i, a -> st.setObject(i + 1, a) }
            st.executeQuery().use { rs ->
                val row = RsRow(rs)
                buildList { while (rs.next()) add(map(row)) }
            }
        }

    override fun exec(sql: String, args: List<Any?>) {
        connection.prepareStatement(sql).use { st ->
            args.forEachIndexed { i, a -> st.setObject(i + 1, a) }
            st.execute()
        }
    }

    override fun <T> transaction(block: () -> T): T {
        val auto = connection.autoCommit
        connection.autoCommit = false
        try {
            return block().also { connection.commit() }
        } catch (e: Throwable) {
            connection.rollback(); throw e
        } finally {
            connection.autoCommit = auto
        }
    }

    private class RsRow(private val rs: ResultSet) : Row {
        override fun string(column: String): String? = rs.getString(column)
        override fun double(column: String): Double? =
            rs.getDouble(column).takeUnless { rs.wasNull() }
        override fun long(column: String): Long? =
            rs.getLong(column).takeUnless { rs.wasNull() }
    }

    companion object {
        /** A fresh in-memory database with the published schema. */
        fun withAppSchema(): JdbcSqlRunner {
            val runner = JdbcSqlRunner(DriverManager.getConnection("jdbc:sqlite::memory:"))
            val schema = JdbcSqlRunner::class.java.getResource("/app_schema.sql")!!.readText()
            schema.split(";").map { it.trim() }.filter { stmt ->
                stmt.lines().any { it.isNotBlank() && !it.trimStart().startsWith("--") }
            }.forEach { runner.exec(it) }
            return runner
        }
    }
}
