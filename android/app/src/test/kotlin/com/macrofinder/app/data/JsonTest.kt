package com.macrofinder.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Decodes a real shape of `bonusrank export`'s output (trimmed). If this ever
 * fails after a change to `src/bonusrank/export.py`, the two have drifted -
 * update [ExportModels] to match, not this fixture.
 */
class JsonTest {

    private val sample = """
    {
      "generated_at": "2026-09-17T12:00:00+00:00",
      "schema_version": 1,
      "chains": {
        "ah": {
          "offers": [
            {
              "sku": "wi123",
              "name": "AH Magere kwark",
              "brand": "AH",
              "food_type": "kwark_mager",
              "price": {
                "unit_price_eur": 1.2,
                "shelf_price_eur": 1.2,
                "required_quantity": 1,
                "total_outlay_eur": 1.2,
                "promo_mechanic": "not_a_promo",
                "promo_text": null,
                "is_promo": false,
                "cheapest_in_weeks": null
              },
              "macros_per_100g": {"protein_g": 8.0, "carbs_g": 4.0, "fat_g": 0.3, "kcal": 47.0},
              "macros_need_marking": true,
              "kcal_is_derived": false,
              "eur_per_100g_protein": 0.75,
              "waste_adjusted_eur_per_100g_protein": null,
              "perishable": true,
              "realistically_consumable_packs": 1,
              "is_personal_offer": false,
              "valid_from": null,
              "valid_to": null
            }
          ],
          "archetypes": [
            {
              "key": "test_pudding",
              "name": "Test pudding",
              "meal_kind": "snack",
              "meal_slots": ["breakfast"],
              "serving_g": 200,
              "target_protein_g": 20,
              "ready_made": null,
              "compositions": [],
              "optimised": {"rejected": true, "reason": "not enough ingredients"},
              "verdict": {"winner": "unknown", "cheaper_pct": null, "protein_delta_g": null, "text": "no verdict"}
            }
          ]
        }
      }
    }
    """.trimIndent()

    @Test
    fun `decodes a real export shape`() {
        val snapshot = parseSnapshot(sample)

        assertEquals(1, snapshot.schema_version)
        val ah = snapshot.chains.getValue("ah")
        assertEquals(1, ah.offers.size)
        assertEquals("kwark_mager", ah.offers[0].food_type)
        assertEquals(8.0, ah.offers[0].macros_per_100g.protein_g)

        val archetype = ah.archetypes[0]
        assertEquals("snack", archetype.meal_kind)
        assertNull(archetype.ready_made)
        assertEquals(true, archetype.optimised?.rejected)
        assertEquals("not enough ingredients", archetype.optimised?.reason)
    }

    @Test
    fun `an unrecognised extra field is ignored, not a crash`() {
        val withExtra = sample.replace(
            "\"schema_version\": 1,",
            "\"schema_version\": 1, \"a_future_field\": \"surprise\",",
        )
        val snapshot = parseSnapshot(withExtra)
        assertEquals(1, snapshot.schema_version)
    }

    @Test
    fun `a chain with no offers or archetypes decodes to empty lists`() {
        val minimal = """{"generated_at": "x", "schema_version": 1, "chains": {"aldi": {}}}"""
        val snapshot = parseSnapshot(minimal)
        val aldi = snapshot.chains.getValue("aldi")
        assertEquals(emptyList<OfferEntry>(), aldi.offers)
        assertEquals(emptyList<ArchetypeEntry>(), aldi.archetypes)
    }
}
