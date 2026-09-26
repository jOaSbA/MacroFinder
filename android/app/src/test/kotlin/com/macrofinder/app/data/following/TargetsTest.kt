package com.macrofinder.app.data.following

import com.macrofinder.app.data.catalogue.Deal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Milestone 34. Pure JVM. */
class TargetsTest {
    private val today = "2026-09-26"

    private fun deal(id: String, perProtein: Double?, lane: String = "shelf") = Deal(
        id = id, chain = "ah", name = id, lane = lane, eurPer100gProtein = perProtein,
        validFrom = if (lane == "promo") "2026-09-22" else null,
        validTo = if (lane == "promo") "2026-09-28" else null,
    )

    @Test
    fun `alerts when today's price crosses the target`() {
        val alerts = targetAlerts(mapOf("ah:1" to 2.0), listOf(deal("ah:1", 1.8)), emptySet(), today)
        assertEquals(listOf("ah:1"), alerts.map { it.id })
    }

    @Test
    fun `quiet when above the target`() {
        assertTrue(targetAlerts(mapOf("ah:1" to 2.0), listOf(deal("ah:1", 2.1)), emptySet(), today).isEmpty())
    }

    @Test
    fun `unknown protein never alerts`() {
        assertTrue(targetAlerts(mapOf("ah:1" to 2.0), listOf(deal("ah:1", null)), emptySet(), today).isEmpty())
    }

    @Test
    fun `a running promo counts, and the same price alerts once`() {
        val lanes = listOf(deal("ah:1", 2.5), deal("ah:1", 1.5, "promo"))
        val first = targetAlerts(mapOf("ah:1" to 2.0), lanes, emptySet(), today)
        assertEquals(1.5, first.single().eurPer100gProtein!!, 0.0)
        assertTrue(targetAlerts(mapOf("ah:1" to 2.0), lanes, setOf(targetKey(first.single())), today).isEmpty())
    }

    @Test
    fun `products without a target are ignored`() {
        assertTrue(targetAlerts(emptyMap(), listOf(deal("ah:1", 0.1)), emptySet(), today).isEmpty())
    }

    @Test
    fun `presets are 10, 20 and 30 percent under`() {
        assertEquals(listOf(1.8, 1.6, 1.4), targetPresets(2.0))
    }

    @Test
    fun `targets round-trip, and junk is skipped`() {
        val targets = mapOf("jumbo:394270CUP" to 1.75, "ah:1" to 2.0)
        assertEquals(targets, decodeTargets(encodeTargets(targets) + "garbage"))
    }
}
