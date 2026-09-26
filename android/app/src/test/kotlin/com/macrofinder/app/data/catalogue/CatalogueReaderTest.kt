package com.macrofinder.app.data.catalogue

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * The catalogue queries, run for real against the published schema.
 * Milestones 23 to 25.
 */
class CatalogueReaderTest {

    private lateinit var db: JdbcSqlRunner
    private lateinit var reader: CatalogueReader

    @Before
    fun setUp() {
        db = JdbcSqlRunner.withAppSchema()
        reader = CatalogueReader(db)
        db.exec("INSERT INTO meta VALUES ('bulk_eur_per_1000kcal', '2.5000')")
        db.exec("INSERT INTO shelves VALUES ('zuivel_eieren','Zuivel, plantaardig, eieren',3)")
        db.exec("INSERT INTO shelves VALUES ('groente_fruit','Groente, aardappelen, fruit',0)")
        db.exec("INSERT INTO food_types (key, name_nl, protein_quality) VALUES ('kwark_mager','Magere kwark','complete')")
        product("ah:1", "AH Magere kwark", foodType = "kwark_mager", protein = 8.0, kcal = 55.0)
        product("jumbo:2", "Jumbo Proteïne pudding", protein = 10.0, kcal = 80.0)
        product("ah:3", "Mystery tin")
        price("ah:1", "promo", 0.99, perProtein = 1.24, from = "2026-09-20", to = "2026-09-27")
        price("ah:1", "shelf", 1.79)
        price("jumbo:2", "upcoming", 1.49, from = "2026-09-24", to = "2026-09-30")
        price("ah:3", "shelf", 0.89)
        db.exec("INSERT INTO price_history VALUES ('ah:1','2026-09-07',1.79)")
        db.exec("INSERT INTO price_history VALUES ('ah:1','2026-09-14',0.99)")
    }

    private fun product(id: String, name: String, foodType: String? = null,
                        protein: Double? = null, kcal: Double? = null) {
        val (chain, sku) = id.split(":")
        db.exec(
            "INSERT INTO products (id, chain, sku, name, food_type, protein_per_100g, " +
                "kcal_per_100g, macro_source, macro_confidence, buckets) VALUES (?,?,?,?,?,?,?,?,?,?)",
            listOf(id, chain, sku, name, foodType, protein, kcal,
                protein?.let { "manual" }, protein?.let { "seed" }, ""),
        )
    }

    private fun price(id: String, lane: String, p: Double, perProtein: Double? = null,
                      from: String? = null, to: String? = null) {
        db.exec(
            "INSERT INTO prices (product_id, lane, observed_at, shelf_price, effective_unit_price, " +
                "required_quantity, is_personal_offer, valid_from, valid_to, eur_per_100g_protein) " +
                "VALUES (?,?,?,?,?,1,0,?,?,?)",
            listOf(id, lane, "2026-09-22", 1.79, p, from, to, perProtein),
        )
    }

    @Test
    fun `deals are every promo and upcoming row, never a shelf price`() {
        val deals = reader.deals()
        assertEquals(setOf("ah:1" to "promo", "jumbo:2" to "upcoming"),
            deals.map { it.id to it.lane }.toSet())
    }

    @Test
    fun `detail lists the same food cheaper elsewhere`() {
        product("jumbo:9", "Jumbo Magere kwark", foodType = "kwark_mager", protein = 8.0, kcal = 55.0)
        price("jumbo:9", "shelf", 0.89, perProtein = 1.11)
        product("aldi:8", "Aldi Magere kwark", foodType = "kwark_mager", protein = 8.0, kcal = 55.0)
        price("aldi:8", "shelf", 1.29, perProtein = 1.61)

        val alts = reader.detail("ah:1", today = "2026-09-24")!!.alternatives
        assertEquals(listOf("jumbo:9"), alts.map { it.deal.id })
        assertEquals(0.13, alts.single().savingPer100gProtein, 1e-9)
        // Without a date there's no "now" to compare against.
        assertTrue(reader.detail("ah:1")!!.alternatives.isEmpty())
    }

    @Test
    fun `unknown macros come back null, not zero`() {
        val tin = reader.detail("ah:3")!!.deal
        assertNull(tin.proteinPer100g)
        assertNull(tin.eurPer100gProtein)
        assertTrue(!tin.hasMacros)
    }

    @Test
    fun `detail picks the promo and keeps the shelf price beside it`() {
        val detail = reader.detail("ah:1")!!
        assertEquals("promo", detail.deal.lane)
        assertEquals(1.79, detail.shelfLanePrice!!, 0.0)
        assertEquals(listOf("2026-09-07", "2026-09-14"), detail.history.map { it.week })
        assertEquals("Magere kwark", detail.foodTypeName)
        assertEquals("complete", detail.proteinQuality)
        assertTrue(detail.deal.macrosEstimated)
    }

    @Test
    fun `shelves come in display order and the bulk cutoff is read from meta`() {
        assertEquals(listOf("groente_fruit", "zuivel_eieren"), reader.shelves().map { it.key })
        assertEquals(2.5, reader.bulkCutoff()!!, 0.0)
    }

    @Test
    fun `search finds products by folded prefix, accents or not`() {
        SearchIndex.rebuild(db)
        assertTrue(SearchIndex.exists(db))
        assertEquals(listOf("jumbo:2"), reader.search(SearchIndex.query("protei")!!).map { it.id })
        assertEquals(listOf("ah:1"), reader.search(SearchIndex.query("magere kw")!!).map { it.id })
        // Found through its food type's name even though the product name differs.
        assertEquals(listOf("ah:1"), reader.search(SearchIndex.query("Magere kwark")!!).map { it.id })
    }

    @Test
    fun `search shows a product with no price at all rather than hiding it`() {
        db.exec("INSERT INTO products (id, chain, sku, name, buckets) VALUES ('ah:9','ah','9','Kwarktaart','')")
        SearchIndex.rebuild(db)
        val hits = reader.search(SearchIndex.query("kwark")!!).map { it.id }
        assertTrue("ah:9" in hits)
        // Known protein cost sorts first.
        assertEquals("ah:1", hits.first())
    }

    @Test
    fun `search prefers the promo lane when one is running`() {
        SearchIndex.rebuild(db)
        val kwark = reader.search(SearchIndex.query("kwark")!!).first { it.id == "ah:1" }
        assertEquals("promo", kwark.lane)
        assertEquals(0.99, kwark.price!!, 0.0)
    }

    @Test
    fun `deals for a set of ids, for the following screen`() {
        assertEquals(setOf("ah:1"), reader.dealsFor(listOf("ah:1")).map { it.id }.toSet())
        assertTrue(reader.dealsFor(emptyList()).isEmpty())
    }

    @Test
    fun `a missing product has no detail`() = assertNull(reader.detail("nope:0"))

    @Test
    fun `folding strips accents and punctuation`() {
        assertEquals("proteine pudding 200 g", SearchIndex.fold("Proteïne-pudding (200 g)"))
        assertEquals("kwark* mag*", SearchIndex.query("  Kwark, mag "))
        assertNull(SearchIndex.query(" ,. "))
        assertNotNull(SearchIndex.query("a"))
    }
}
