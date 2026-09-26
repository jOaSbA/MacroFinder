package com.macrofinder.app.data.catalogue

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Milestone 31. Pure JVM. */
class AlternativesTest {
    private val today = "2026-09-26"

    private fun deal(id: String, perProtein: Double?, lane: String = "shelf",
                     from: String? = null, to: String? = null, personal: Boolean = false) =
        Deal(id = id, chain = id.substringBefore(':'), name = id, lane = lane,
            eurPer100gProtein = perProtein, validFrom = from, validTo = to, isPersonal = personal,
            foodType = "kwark_mager")

    private val mine = deal("ah:1", 2.00)

    @Test
    fun `cheaper products come back cheapest first with the saving`() {
        val alts = cheaperAlternatives(mine, listOf(deal("jumbo:2", 1.50), deal("aldi:3", 1.20)), today)
        assertEquals(listOf("aldi:3", "jumbo:2"), alts.map { it.deal.id })
        assertEquals(0.80, alts[0].savingPer100gProtein, 1e-9)
    }

    @Test
    fun `nothing when this product is already the cheapest`() {
        assertTrue(cheaperAlternatives(mine, listOf(deal("jumbo:2", 2.40)), today).isEmpty())
    }

    @Test
    fun `unknown protein is never cheaper, and an unpriced product has no list`() {
        assertTrue(cheaperAlternatives(mine, listOf(deal("jumbo:2", null)), today).isEmpty())
        assertTrue(cheaperAlternatives(deal("ah:1", null), listOf(deal("jumbo:2", 1.0)), today).isEmpty())
    }

    @Test
    fun `a running promo beats the shelf price, an upcoming one does not`() {
        val running = listOf(deal("jumbo:2", 2.50), deal("jumbo:2", 1.00, "promo", "2026-09-22", "2026-09-28"))
        assertEquals(1.00, cheaperAlternatives(mine, running, today).single().deal.eurPer100gProtein!!, 0.0)

        val later = listOf(deal("jumbo:2", 2.50), deal("jumbo:2", 1.00, "promo", "2026-09-29", "2026-10-05"))
        assertTrue(cheaperAlternatives(mine, later, today).isEmpty())
    }

    @Test
    fun `personal offers and hidden chains are left out`() {
        val personal = deal("jumbo:2", 1.00, "promo", "2026-09-22", "2026-09-28", personal = true)
        assertTrue(cheaperAlternatives(mine, listOf(personal), today).isEmpty())
        assertTrue(cheaperAlternatives(mine, listOf(deal("aldi:3", 1.0)), today, chains = setOf("ah", "jumbo")).isEmpty())
    }

    @Test
    fun `the product itself and sub-cent differences do not count`() {
        assertTrue(cheaperAlternatives(mine, listOf(deal("ah:1", 1.0), deal("jumbo:2", 1.995)), today).isEmpty())
    }

    @Test
    fun `at most three`() {
        val many = (1..6).map { deal("jumbo:$it", 1.0 + it / 10.0) }
        assertEquals(3, cheaperAlternatives(mine, many, today).size)
    }
}
