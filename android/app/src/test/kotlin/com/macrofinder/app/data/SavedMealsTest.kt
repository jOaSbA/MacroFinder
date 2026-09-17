package com.macrofinder.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Saved meals: the serialised form, tested without DataStore.
 *
 * DataStore itself needs an instrumentation test and an emulator, which
 * `android/README.md` is explicit about not adding. [serializeMeals] and
 * [deserializeMeals] are split out of the store for exactly this reason - the
 * round trip is the part that can silently lose a user's data, and it is
 * testable here where CI runs.
 */
class SavedMealsTest {

    private val meal = SavedMeal(
        id = "meal:1",
        name = "Donderdagpasta",
        templateKey = "pasta",
        lines = listOf(
            MealLine(
                id = "slot:pasta", slotKey = "pasta", foodType = "pasta_droog",
                label = "pasta (droog)", quantity = Quantity(100.0),
            ),
            MealLine(
                id = "extra:ei", slotKey = null, foodType = "ei_gekookt",
                label = "gekookt ei", quantity = Quantity(4.0, QuantityUnit.UNITS),
            ),
        ),
    )

    @Test
    fun `a saved meal survives a round trip intact`() {
        assertEquals(listOf(meal), deserializeMeals(serializeMeals(listOf(meal))))
    }

    @Test
    fun `a saved meal stores no prices at all`() {
        // This is what makes a saved meal follow the weekly bonus around: it
        // holds keys and quantities, and is re-costed on every open. A stored
        // euro figure would freeze last week's deal into it forever.
        val json = serializeMeals(listOf(meal))
        assertTrue(json, !json.contains("eur"))
        assertTrue(json, !json.contains("price"))
    }

    @Test
    fun `a saved meal keys on strings, never on a seed id`() {
        // seed.py::load_templates deletes and re-inserts its child rows on
        // every run, so template_slots.id changes. An integer here would
        // silently re-point at a different slot after a reseed.
        val json = serializeMeals(listOf(meal))
        assertTrue(json.contains("\"slotKey\":\"pasta\""))
        assertTrue(json.contains("\"foodType\":\"pasta_droog\""))
    }

    @Test
    fun `two lines of the same food type both survive`() {
        val doubled = meal.copy(
            lines = meal.lines + meal.lines[0].copy(id = "extra:more-pasta"),
        )
        val restored = deserializeMeals(serializeMeals(listOf(doubled))).single()
        assertEquals(3, restored.lines.size)
        assertEquals(setOf("slot:pasta", "extra:ei", "extra:more-pasta"),
            restored.lines.map { it.id }.toSet())
    }

    @Test
    fun `nothing stored yet reads as an empty list, not a crash`() {
        assertEquals(emptyList<SavedMeal>(), deserializeMeals(null))
        assertEquals(emptyList<SavedMeal>(), deserializeMeals(""))
    }

    @Test
    fun `unreadable stored data degrades to empty rather than crashing the app`() {
        // A file written by an older build must never make the app unusable.
        assertEquals(emptyList<SavedMeal>(), deserializeMeals("{not json at all"))
    }

    @Test
    fun `a line with no food type round trips as unidentified`() {
        // Milestone 14's raw catalogue SKUs land here. The concept already
        // persists correctly, so that milestone adds a screen, not a schema.
        val unnamed = meal.copy(
            lines = listOf(
                MealLine(id = "x", foodType = null, label = "iets uit de winkel",
                    quantity = Quantity(100.0)),
            ),
        )
        val restored = deserializeMeals(serializeMeals(listOf(unnamed))).single()
        assertNull(restored.lines.single().foodType)
        assertEquals("iets uit de winkel", restored.lines.single().label)
    }

    @Test
    fun `a saved meal re-costs against whatever snapshot is current`() {
        val cheap = MealContext(
            foodTypes = mapOf("pasta_droog" to FoodTypeEntry("pasta_droog", "pasta")),
            prices = mapOf("pasta_droog" to FoodTypePriceEntry(eur_per_kg = 1.00)),
        )
        val dear = cheap.copy(
            prices = mapOf("pasta_droog" to FoodTypePriceEntry(eur_per_kg = 3.00)),
        )
        val lines = listOf(meal.lines[0])

        assertEquals(0.10, priceMeal(lines, cheap).eur!!, 1e-9)
        assertEquals(0.30, priceMeal(lines, dear).eur!!, 1e-9)
    }
}
