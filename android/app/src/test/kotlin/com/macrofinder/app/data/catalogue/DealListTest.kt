package com.macrofinder.app.data.catalogue

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Filtering and sorting the deal list. Milestones 18 and 23. */
class DealListTest {

    private val today = "2026-09-22"

    private fun deal(
        id: String,
        name: String = id,
        from: String? = "2026-09-20",
        to: String? = "2026-09-27",
        chain: String = "ah",
        shelf: String? = "zuivel_eieren",
        perProtein: Double? = null,
        ratio: Double? = null,
        perKcal: Double? = null,
        discount: Double? = null,
        buckets: Set<String> = emptySet(),
        price: Double? = 1.0,
        personal: Boolean = false,
        lane: String = "promo",
    ) = Deal(
        id = id, chain = chain, name = name, shelf = shelf, validFrom = from, validTo = to,
        eurPer100gProtein = perProtein, proteinPer100kcal = ratio, eurPer1000kcal = perKcal,
        discountPct = discount, buckets = buckets, price = price, isPersonal = personal, lane = lane,
    )

    private fun ids(list: List<RankedDeal>) = list.map { it.deal.id }

    // -- milestone 18 ------------------------------------------------------

    @Test
    fun `no upcoming deal can appear in the active list`() {
        val all = (1..20).map { deal("u$it", from = "2026-09-${23 + it % 5}", to = "2026-10-05") } +
            deal("now")
        val active = selectDeals(all, DealQuery(window = DealWindow.ACTIVE), today)
        assertEquals(listOf("now"), ids(active))
        assertTrue(active.all { it.deal.validFrom == null || it.deal.validFrom!! <= today })
    }

    @Test
    fun `the upcoming list holds only deals that have not started`() {
        val all = listOf(deal("now"), deal("later", from = "2026-09-24", to = "2026-09-30"))
        assertEquals(listOf("later"), ids(selectDeals(all, DealQuery(window = DealWindow.UPCOMING), today)))
    }

    @Test
    fun `an upcoming row counts as active once its date arrives`() {
        val row = deal("x", from = "2026-09-22", lane = "upcoming")
        assertEquals(listOf("x"), ids(selectDeals(listOf(row), DealQuery(), today)))
    }

    @Test
    fun `expired deals are in neither list`() {
        val old = deal("old", from = "2026-09-01", to = "2026-09-07")
        assertTrue(selectDeals(listOf(old), DealQuery(), today).isEmpty())
        assertTrue(selectDeals(listOf(old), DealQuery(window = DealWindow.UPCOMING), today).isEmpty())
    }

    @Test
    fun `a product shows once, at its cheaper price, when two lanes overlap`() {
        val a = deal("p", price = 2.0, lane = "promo")
        val b = deal("p", price = 1.5, lane = "upcoming", from = "2026-09-21")
        val out = selectDeals(listOf(a, b), DealQuery(), today)
        assertEquals(1, out.size)
        assertEquals(1.5, out.single().deal.price!!, 0.0)
    }

    // -- the sort comparators ----------------------------------------------

    @Test
    fun `protein per euro sorts cheapest first and unknowns last`() {
        val all = listOf(deal("b", perProtein = 2.0), deal("unknown"), deal("a", perProtein = 1.0))
        assertEquals(listOf("a", "b", "unknown"),
            ids(selectDeals(all, DealQuery(sort = DealSort.PROTEIN_PER_EURO), today)))
    }

    @Test
    fun `protein ratio sorts highest first and unknowns last`() {
        val all = listOf(deal("low", ratio = 5.0), deal("unknown"), deal("high", ratio = 20.0))
        assertEquals(listOf("high", "low", "unknown"),
            ids(selectDeals(all, DealQuery(sort = DealSort.PROTEIN_RATIO), today)))
    }

    @Test
    fun `kcal per euro sorts cheapest first and unknowns last`() {
        val all = listOf(deal("b", perKcal = 3.0), deal("unknown"), deal("a", perKcal = 0.5))
        assertEquals(listOf("a", "b", "unknown"),
            ids(selectDeals(all, DealQuery(sort = DealSort.KCAL_PER_EURO), today)))
    }

    @Test
    fun `discount sorts biggest first and unknowns last`() {
        val all = listOf(deal("small", discount = 10.0), deal("unknown"), deal("big", discount = 50.0))
        assertEquals(listOf("big", "small", "unknown"),
            ids(selectDeals(all, DealQuery(sort = DealSort.DISCOUNT), today)))
    }

    @Test
    fun `ties break on name so the order never jumps around`() {
        val all = listOf(deal("2", name = "Zalm", perProtein = 1.0), deal("1", name = "appel", perProtein = 1.0))
        assertEquals(listOf("1", "2"), ids(selectDeals(all, DealQuery(), today)))
    }

    // -- filters -----------------------------------------------------------

    @Test
    fun `food only drops shampoo but keeps protein powder`() {
        val all = listOf(
            deal("shampoo", shelf = "drogisterij"),
            deal("whey", shelf = "drogisterij", buckets = setOf("supplement")),
            deal("kwark"),
            deal("unmapped", shelf = null),
        )
        assertEquals(setOf("whey", "kwark", "unmapped"), ids(selectDeals(all, DealQuery(), today)).toSet())
        assertEquals(4, selectDeals(all, DealQuery(foodOnly = false), today).size)
    }

    @Test
    fun `chain, shelf and bucket filters narrow the list`() {
        val all = listOf(
            deal("a", chain = "ah", buckets = setOf("eiwitbom")),
            deal("j", chain = "jumbo", shelf = "vlees_vis"),
        )
        assertEquals(listOf("j"), ids(selectDeals(all, DealQuery(chains = setOf("jumbo")), today)))
        assertEquals(listOf("j"), ids(selectDeals(all, DealQuery(shelf = "vlees_vis"), today)))
        assertEquals(listOf("a"), ids(selectDeals(all, DealQuery(bucket = "eiwitbom"), today)))
    }

    @Test
    fun `bulk compares against the published cutoff`() {
        val all = listOf(deal("cheap", perKcal = 1.0), deal("dear", perKcal = 5.0), deal("unknown"))
        assertEquals(listOf("cheap"),
            ids(selectDeals(all, DealQuery(bucket = BUCKET_BULK), today, bulkCutoff = 2.0)))
        assertTrue(selectDeals(all, DealQuery(bucket = BUCKET_BULK), today, bulkCutoff = null).isEmpty())
    }

    @Test
    fun `personal offers stay out unless asked for`() {
        val all = listOf(deal("mine", personal = true), deal("everyone"))
        assertEquals(listOf("everyone"), ids(selectDeals(all, DealQuery(), today)))
        assertEquals(2, selectDeals(all, DealQuery(includePersonal = true), today).size)
    }

    // -- tiers ---------------------------------------------------------------

    @Test
    fun `the top tenth is excellent and unknowns get no tier`() {
        val all = (1..20).map { deal("d$it", perProtein = it.toDouble()) } + deal("unknown")
        val out = selectDeals(all, DealQuery(), today)
        assertEquals(DealTier.EXCELLENT, out[0].tier)
        assertEquals(DealTier.EXCELLENT, out[1].tier)
        assertEquals(DealTier.GOOD, out[2].tier)
        assertEquals(DealTier.POOR, out[19].tier)
        assertNull(out.last().tier)
    }
}
