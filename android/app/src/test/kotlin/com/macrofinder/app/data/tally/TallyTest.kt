package com.macrofinder.app.data.tally

import com.macrofinder.app.data.catalogue.Deal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Milestone 38. Pure JVM. */
class TallyTest {
    private val kwark = Deal(id = "ah:1", chain = "ah", name = "Kwark", lane = "shelf", price = 1.69,
        massG = 1000.0, proteinPer100g = 8.0, kcalPer100g = 55.0)
    private val tofu = Deal(id = "jumbo:2", chain = "jumbo", name = "Tofu", lane = "promo", price = 1.00,
        shelfPrice = 2.00, requiredQuantity = 2, massG = 200.0, proteinPer100g = 12.0, kcalPer100g = 120.0)

    @Test
    fun `totals add up line by line`() {
        val t = tallyTotals(listOf(TallyLine("ah:1", 2, kwark), TallyLine("jumbo:2", 2, tofu)))
        assertEquals(2 * 1.69 + 2 * 1.00, t.eur!!, 1e-9)
        assertEquals(2 * 80.0 + 2 * 24.0, t.proteinG!!, 1e-9)
        assertEquals(2 * 550.0 + 2 * 240.0, t.kcal!!, 1e-9)
        assertEquals(t.eur!! / t.proteinG!! * 100, t.eurPer100gProtein!!, 1e-9)
        assertEquals(mapOf("ah" to 3.38, "jumbo" to 2.00), t.byChain.mapValues { Math.round(it.value!! * 100) / 100.0 })
    }

    @Test
    fun `a multi-buy only gets its price in full groups`() {
        assertEquals(2.00, packCost(tofu, 2)!!, 1e-9)
        assertEquals(2.00 + 2.00, packCost(tofu, 3)!!, 1e-9)
        assertNull(packCost(tofu.copy(shelfPrice = null), 3))
    }

    @Test
    fun `an unknown line poisons the total and is named`() {
        val mystery = Deal(id = "ah:3", chain = "ah", name = "Mystery", price = 0.89)
        val t = tallyTotals(listOf(TallyLine("ah:1", 1, kwark), TallyLine("ah:3", 1, mystery)))
        assertEquals(2.58, t.eur!!, 1e-9)
        assertNull(t.proteinG)
        assertNull(t.eurPer100gProtein)
        assertEquals(listOf("Mystery"), t.unknownMacros)
    }

    @Test
    fun `a delisted product makes the price unknown`() {
        val t = tallyTotals(listOf(TallyLine("ah:9", 1, null)))
        assertNull(t.eur)
        assertEquals(1, t.unpriced.size)
    }

    @Test
    fun `storage round-trips and drops zero counts`() {
        assertEquals(mapOf("ah:1" to 2), decodeTally(encodeTally(mapOf("ah:1" to 2, "ah:2" to 0)) + "junk"))
    }
}
