package com.macrofinder.app.data.following

import com.macrofinder.app.data.catalogue.Deal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Milestone 26: a followed product entering a promo raises one alert. */
class PromoAlertsTest {
    private val today = "2026-09-22"

    private fun deal(id: String, lane: String = "promo", from: String = "2026-09-21",
                     to: String = "2026-09-27", text: String = "1+1 gratis") =
        Deal(id = id, chain = "ah", name = id, lane = lane, validFrom = from,
            validTo = to, promoText = text)

    @Test
    fun `a followed product that goes on offer is announced after the sync`() {
        val out = promoAlerts(setOf("ah:1"), listOf(deal("ah:1"), deal("ah:2")), emptySet(), today)
        assertEquals(listOf("ah:1"), out.map { it.id })
    }

    @Test
    fun `the same promo is announced once, not on every sync`() {
        val kwark = deal("ah:1")
        assertTrue(promoAlerts(setOf("ah:1"), listOf(kwark), setOf(alertKey(kwark)), today).isEmpty())
    }

    @Test
    fun `next week's promo on the same product is a new alert`() {
        val thisWeek = deal("ah:1")
        val nextWeek = deal("ah:1", from = "2026-09-28", to = "2026-10-04", text = "2e halve prijs")
        val out = promoAlerts(setOf("ah:1"), listOf(nextWeek), setOf(alertKey(thisWeek)), "2026-09-28")
        assertEquals(1, out.size)
    }

    @Test
    fun `an upcoming promo waits until it starts`() {
        val later = deal("ah:1", lane = "upcoming", from = "2026-09-25")
        assertTrue(promoAlerts(setOf("ah:1"), listOf(later), emptySet(), today).isEmpty())
    }

    @Test
    fun `a shelf price is never an alert`() {
        assertTrue(promoAlerts(setOf("ah:1"), listOf(deal("ah:1", lane = "shelf")), emptySet(), today)
            .isEmpty())
    }
}
