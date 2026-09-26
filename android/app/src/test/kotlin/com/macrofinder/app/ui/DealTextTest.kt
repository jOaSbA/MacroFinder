package com.macrofinder.app.ui

import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.data.catalogue.ProductDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** BRIEF section 9 on the detail screen and the list rows. Milestone 24. */
class DealTextTest {

    private fun deal(confidence: String? = "seed", protein: Double? = 8.0) = Deal(
        id = "ah:1", chain = "ah", name = "AH Magere kwark",
        proteinPer100g = protein, kcalPer100g = protein?.let { 55.0 },
        proteinPer100kcal = protein?.let { 14.5 }, eurPer100gProtein = protein?.let { 1.24 },
        eurPer1000kcal = protein?.let { 3.6 }, macroSource = protein?.let { "manual" },
        macroConfidence = confidence, discountPct = 45.0,
    )

    private fun detail(d: Deal, derived: Boolean = false) =
        ProductDetail(d, 1.79, emptyList(), derived, "Magere kwark")

    @Test
    fun `no macro is rendered without a provenance marker`() {
        for (d in listOf(deal("seed"), deal("high"), deal(null, protein = null))) {
            val strip = macroStrip(detail(d))
            val shown = (strip.top + strip.money).filter { it.value != null }
            if (shown.isNotEmpty() || strip.secondary != null) assertNotNull(strip.provenance)
            // Every estimated figure carries the mark in its own text.
            shown.filter { it.estimated }.forEach { assertTrue(it.value!!.startsWith(ESTIMATE_MARK)) }
            if (d.macrosEstimated) assertTrue(strip.secondary!!.startsWith(ESTIMATE_MARK))
        }
    }

    @Test
    fun `an estimate says what it was estimated from`() {
        val strip = macroStrip(detail(deal("seed")))
        assertTrue(strip.provenance!!.contains("magere kwark"))
        assertTrue(strip.provenance!!.contains("niet van het etiket"))
    }

    @Test
    fun `label macros say so and carry no mark`() {
        val strip = macroStrip(detail(deal("high")))
        assertEquals("Van het etiket van dit product.", strip.provenance)
        assertTrue(strip.top.all { !it.value!!.startsWith(ESTIMATE_MARK) })
    }

    @Test
    fun `unknown macros say unknown, never zero`() {
        val strip = macroStrip(detail(deal(null, protein = null)))
        assertTrue((strip.top + strip.money).all { it.value == null })
        assertTrue(strip.provenance!!.startsWith("Voedingswaarde onbekend"))
    }

    @Test
    fun `kcal worked out from kJ is marked`() {
        assertTrue(macroStrip(detail(deal("high"), derived = true)).secondary!!.contains("uit kJ"))
    }

    @Test
    fun `list metric marks estimates and names unknowns`() {
        assertEquals("≈ €1,24 per 100 g eiwit", metricText(deal("seed"), DealSort.PROTEIN_PER_EURO))
        assertEquals("€1,24 per 100 g eiwit", metricText(deal("high"), DealSort.PROTEIN_PER_EURO))
        assertEquals("eiwit onbekend", metricText(deal(null, null), DealSort.PROTEIN_PER_EURO))
        assertEquals("45% korting", metricText(deal("seed"), DealSort.DISCOUNT))
    }

    @Test
    fun `required quantity and dates read naturally`() {
        assertNull(quantityText(deal()))
        assertEquals("koop 2", quantityText(deal().copy(requiredQuantity = 2)))
        val later = deal().copy(validFrom = "2026-09-28", validTo = "2026-10-04")
        assertEquals("vanaf 28 sep", validityText(later, "2026-09-22"))
        assertEquals("t/m 4 okt", validityText(later, "2026-09-29"))
    }

    @Test
    fun `waste line only appears when it changes the answer`() {
        val kwark = deal().copy(perishable = true, requiredQuantity = 2, realisticallyConsumable = 1,
            wasteAdjustedEurPer100gProtein = 2.48)
        assertEquals("€2,48 per 100 g eiwit als je er maar 1 van de 2 op krijgt voor ze bederven",
            wasteText(kwark))
        assertNull(wasteText(kwark.copy(wasteAdjustedEurPer100gProtein = 1.24)))
    }
}
