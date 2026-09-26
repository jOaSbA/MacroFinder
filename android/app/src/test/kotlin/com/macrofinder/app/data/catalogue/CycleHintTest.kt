package com.macrofinder.app.data.catalogue

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Same cases as `tests/test_history.py`, so the two implementations agree. */
class CycleHintTest {
    private val start = LocalDate.of(2026, 9, 21)
    private val last = start.toString()

    @Test
    fun `on promo now means buy`() =
        assertEquals(CycleHint.BUY, cycleHint(28, last, onPromo = true, today = start.plusDays(2)))

    @Test
    fun `next promo close means wait`() =
        assertEquals(CycleHint.WAIT, cycleHint(28, last, onPromo = false, today = start.plusDays(21)))

    @Test
    fun `next promo far away means buy`() =
        assertEquals(CycleHint.BUY, cycleHint(56, last, onPromo = false, today = start.plusDays(7)))

    @Test
    fun `no cycle no hint`() = assertNull(cycleHint(null, last, onPromo = false, today = start))

    @Test
    fun `more than a cycle overdue means the pattern broke`() =
        assertNull(cycleHint(14, last, onPromo = false, today = start.plusDays(40)))

    @Test
    fun `the sentence says how often and how long ago`() =
        assertEquals(
            "Elke ~4 weken in de aanbieding, laatst 3 weken geleden",
            cycleSentence(28, last, start.plusDays(21)),
        )
}
