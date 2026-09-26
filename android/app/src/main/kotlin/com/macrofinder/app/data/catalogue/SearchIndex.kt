package com.macrofinder.app.data.catalogue

import java.text.Normalizer

/**
 * Full-text search over the synced catalogue. Milestone 25.
 *
 * FTS4, not FTS5: Android's own SQLite has shipped FTS4 for years, while FTS5
 * depends on the device. Built on the phone after each sync rather than
 * shipped in the published file, so deltas stay plain row diffs and the index
 * never has to be diffed at all.
 *
 * Text is folded before it goes in and before a query runs ("Proteïne" and
 * "proteine" are the same word to someone typing on a phone), so the default
 * tokenizer is enough.
 */
object SearchIndex {
    const val TABLE = "search_index"

    fun rebuild(db: SqlRunner) {
        db.transaction {
            db.exec("DROP TABLE IF EXISTS $TABLE")
            db.exec("CREATE VIRTUAL TABLE $TABLE USING fts4(id, body, notindexed=id)")
            val rows = db.query(
                "SELECT p.id, p.name, p.brand, f.name_nl FROM products p " +
                    "LEFT JOIN food_types f ON f.key = p.food_type"
            ) { r ->
                r.string("id")!! to listOfNotNull(
                    r.string("name"), r.string("brand"), r.string("name_nl"),
                ).joinToString(" ")
            }
            for ((id, text) in rows) {
                db.exec("INSERT INTO $TABLE (id, body) VALUES (?, ?)", listOf(id, fold(text)))
            }
        }
    }

    fun exists(db: SqlRunner): Boolean =
        db.query("SELECT name FROM sqlite_master WHERE name = ?", listOf(TABLE)) { it.string("name") }
            .isNotEmpty()

    /** Lowercase, accents stripped, anything that isn't a letter or digit made a space. */
    fun fold(text: String): String =
        Normalizer.normalize(text.lowercase(), Normalizer.Form.NFD)
            .replace(Regex("\\p{M}+"), "")
            .replace(Regex("[^a-z0-9]+"), " ")
            .trim()

    /**
     * What the user typed, as an FTS query: every word must match, and the
     * last one as a prefix so results appear while typing. Null when there is
     * nothing left to search for.
     */
    fun query(input: String): String? {
        val words = fold(input).split(' ').filter { it.isNotBlank() }
        if (words.isEmpty()) return null
        return words.joinToString(" ") { "$it*" }
    }
}
