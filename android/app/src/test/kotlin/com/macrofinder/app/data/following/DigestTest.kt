package com.macrofinder.app.data.following

import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.settings.Diet
import com.macrofinder.app.data.settings.Prefs
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Milestone 33. Pure JVM. */
class DigestTest {
    private val today = LocalDate.parse("2026-09-28")
    private val on = Prefs(weeklyDigest = true)

    private fun deal(id: String, perProtein: Double?, foodType: String? = id, vararg tags: String) = Deal(
        id = id, chain = id.substringBefore(':'), name = id, foodType = foodType, lane = "promo",
        validFrom = "2026-09-28", validTo = "2026-10-11", eurPer100gProtein = perProtein,
        proteinPer100g = perProtein?.let { 10.0 }, buckets = tags.toSet(),
    )

    private val deals = listOf(
        deal("ah:kwark", 0.9, "kwark", "vegetarisch"),
        deal("jumbo:kwark", 0.8, "kwark", "vegetarisch"),
        deal("ah:kip", 1.0, "kip"),
        deal("aldi:tofu", 1.2, "tofu", "vegetarisch", "vegan"),
        deal("ah:tin", null, null),
    )

    @Test
    fun `best protein per euro first, one per food type, unknowns left out`() {
        assertEquals(listOf("jumbo:kwark", "ah:kip", "aldi:tofu"),
            weeklyDigest(deals, on, today, lastSent = null).map { it.id })
    }

    @Test
    fun `off by default`() {
        assertTrue(weeklyDigest(deals, Prefs(), today, null).isEmpty())
    }

    @Test
    fun `once per week`() {
        assertTrue(weeklyDigest(deals, on, today, lastSent = digestWeek(today)).isEmpty())
        assertEquals(3, weeklyDigest(deals, on, today.plusDays(7), lastSent = digestWeek(today)).size)
    }

    @Test
    fun `respects my stores and diet`() {
        val veg = on.copy(stores = setOf("ah", "aldi"), diet = Diet.VEGETARISCH)
        assertEquals(listOf("ah:kwark", "aldi:tofu"), weeklyDigest(deals, veg, today, null).map { it.id })
    }

    @Test
    fun `week keys follow ISO weeks`() {
        assertEquals("2026-W40", digestWeek(today))
        assertEquals("2026-W53", digestWeek(LocalDate.parse("2026-12-31")))
    }
}
