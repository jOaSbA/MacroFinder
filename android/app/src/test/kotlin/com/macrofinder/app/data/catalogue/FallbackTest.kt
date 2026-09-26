package com.macrofinder.app.data.catalogue

import com.macrofinder.app.data.parseSnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** latest.json's offers as deals, before the catalogue arrives. */
class FallbackTest {
    private val json = """
    {"generated_at":"x","schema_version":2,"chains":{"ah":{"offers":[
      {"sku":"1","name":"Kwark","price":{"unit_price_eur":1.0,"shelf_price_eur":2.0,
        "required_quantity":2,"promo_mechanic":"x_plus_y_free","promo_text":"1+1 gratis",
        "is_promo":true},"macros_per_100g":{"protein_g":8.0,"kcal":55.0},
        "macros_need_marking":true,"kcal_is_derived":false,"eur_per_100g_protein":1.25,
        "perishable":true,"is_personal_offer":false},
      {"sku":"2","name":"Macaroni","price":{"unit_price_eur":0.72,"required_quantity":1,
        "promo_mechanic":"not_a_promo","is_promo":false},"macros_per_100g":{},
        "macros_need_marking":true,"kcal_is_derived":false,"perishable":false,
        "is_personal_offer":false}]}}}
    """.trimIndent()

    @Test
    fun `only offers become deals, not shelf prices`() {
        val deals = fallbackDeals(parseSnapshot(json))
        assertEquals(listOf("ah:1"), deals.map { it.id })
    }

    @Test
    fun `the mapping keeps discount, marking and the unknowns unknown`() {
        val d = fallbackDeals(parseSnapshot(json)).single()
        assertEquals(50.0, d.discountPct!!, 0.001)
        assertEquals(true, d.macrosEstimated)
        assertEquals(2, d.requiredQuantity)
        assertNull(d.eurPer1000kcal)
    }
}
