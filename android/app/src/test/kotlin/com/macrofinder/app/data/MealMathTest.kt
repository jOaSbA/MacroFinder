package com.macrofinder.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Local re-pricing. Pure JVM, no Android framework - this runs in CI.
 *
 * The tests that matter are the two poison rules, because they are the app-side
 * copy of `archetypes.py::_price_composition`'s single most important rule and
 * of `_sum_or_none`. Getting either wrong means the app quietly claims a meal
 * is cheaper, or higher in protein, than anyone can stand behind.
 */
class MealMathTest {

    private val context = MealContext(
        foodTypes = mapOf(
            "pasta_droog" to FoodTypeEntry(
                key = "pasta_droog", name = "pasta (droog)",
                macros_per_100g = Macros(protein_g = 12.0, kcal = 360.0, carbs_g = 72.0, fat_g = 1.5),
            ),
            "ei_gekookt" to FoodTypeEntry(
                key = "ei_gekookt", name = "gekookt ei", g_per_unit = 50.0,
                macros_per_100g = Macros(protein_g = 13.0, kcal = 143.0, carbs_g = 1.0, fat_g = 10.0),
            ),
            // Real shape from the seed: a food type with an incomplete label.
            "mystery" to FoodTypeEntry(
                key = "mystery", name = "iets", macros_per_100g = Macros(protein_g = 5.0),
            ),
            "unpriced_food" to FoodTypeEntry(
                key = "unpriced_food", name = "rucola",
                macros_per_100g = Macros(protein_g = 2.6, kcal = 25.0, carbs_g = 2.1, fat_g = 0.7),
            ),
            // Label-sourced rather than seeded: the one kind that needs no
            // marker. Rare today and the reason the flag is data rather than a
            // constant.
            "from_label" to FoodTypeEntry(
                key = "from_label", name = "kwark van het etiket",
                macros_per_100g = Macros(protein_g = 10.0, kcal = 60.0, carbs_g = 4.0, fat_g = 0.2),
                macros_need_marking = false,
            ),
        ),
        prices = mapOf(
            "pasta_droog" to FoodTypePriceEntry(eur_per_kg = 2.00),
            "ei_gekookt" to FoodTypePriceEntry(eur_per_kg = 8.00),
            "mystery" to FoodTypePriceEntry(eur_per_kg = 4.00),
            "from_label" to FoodTypePriceEntry(eur_per_kg = 3.00),
            // "unpriced_food" deliberately absent - absent IS the unknown.
        ),
    )

    private fun line(foodType: String?, amount: Double, unit: QuantityUnit = QuantityUnit.GRAMS) =
        MealLine(
            id = "line:$foodType", foodType = foodType,
            label = foodType ?: "something", quantity = Quantity(amount, unit),
        )

    // -- grams -------------------------------------------------------------

    @Test
    fun `a grams quantity is its own mass`() {
        assertEquals(100.0, gramsOf(line("pasta_droog", 100.0), context)!!, 1e-9)
    }

    @Test
    fun `four boiled eggs is four times g_per_unit`() {
        val eggs = line("ei_gekookt", 4.0, QuantityUnit.UNITS)
        assertEquals(200.0, gramsOf(eggs, context)!!, 1e-9)
    }

    @Test
    fun `units without a g_per_unit is unknown, not one gram per unit`() {
        val nonsense = line("pasta_droog", 4.0, QuantityUnit.UNITS)
        assertNull(gramsOf(nonsense, context))
    }

    // -- one line ----------------------------------------------------------

    @Test
    fun `a line costs its mass at the food type's current rate`() {
        val priced = priceLine(line("pasta_droog", 100.0), context)
        assertEquals(0.20, priced.eur!!, 1e-9)
        assertEquals(12.0, priced.proteinG!!, 1e-9)
    }

    @Test
    fun `a food type with no price entry costs nothing knowable`() {
        val priced = priceLine(line("unpriced_food", 40.0), context)
        assertNull(priced.eur)
        // Its macros are still known - the two unknowns are independent.
        assertEquals(1.04, priced.proteinG!!, 1e-9)
    }

    @Test
    fun `an unidentified line has neither price nor macros`() {
        val priced = priceLine(line(null, 100.0), context)
        assertNull(priced.eur)
        assertNull(priced.proteinG)
    }

    // -- the euro poison rule ----------------------------------------------

    @Test
    fun `one unpriced line makes the whole meal cost unknown`() {
        val totals = priceMeal(
            listOf(line("pasta_droog", 100.0), line("unpriced_food", 40.0)), context
        )
        assertNull("summing the rest would claim the meal is cheaper than it is", totals.eur)
    }

    @Test
    fun `the unpriced line is still listed and named`() {
        val totals = priceMeal(
            listOf(line("pasta_droog", 100.0), line("unpriced_food", 40.0)), context
        )
        assertEquals(2, totals.lines.size)
        assertEquals(listOf("unpriced_food"), totals.unpricedLines)
    }

    @Test
    fun `a fully priced meal costs the sum of its lines`() {
        val totals = priceMeal(
            listOf(line("pasta_droog", 100.0), line("ei_gekookt", 2.0, QuantityUnit.UNITS)),
            context,
        )
        // 100 g pasta at 2.00/kg = 0.20; 2 eggs = 100 g at 8.00/kg = 0.80.
        assertEquals(1.00, totals.eur!!, 1e-9)
        assertTrue(totals.unpricedLines.isEmpty())
    }

    // -- the macro poison rule, symmetric with the euro one ----------------

    @Test
    fun `one line with an unknown macro nulls that total only`() {
        // "mystery" has protein but no kcal, carbs or fat.
        val totals = priceMeal(listOf(line("pasta_droog", 100.0), line("mystery", 50.0)), context)

        assertEquals(14.5, totals.proteinG!!, 1e-9)  // 12.0 + 2.5, both known
        assertNull("kcal is unknown for one line, so the total is unknown", totals.kcal)
        assertNull(totals.fatG)
        // The cost is still perfectly knowable - the unknowns do not bleed.
        assertEquals(0.40, totals.eur!!, 1e-9)
    }

    @Test
    fun `an unidentified line nulls the protein total and names itself`() {
        val totals = priceMeal(listOf(line("pasta_droog", 100.0), line(null, 100.0)), context)
        assertNull(totals.proteinG)
        assertEquals(listOf("something"), totals.unknownMacroLines)
    }

    @Test
    fun `euro per gram protein is unknown when either side is`() {
        val unpriced = priceMeal(listOf(line("unpriced_food", 40.0)), context)
        val unknownMacros = priceMeal(listOf(line(null, 100.0)), context)

        assertNull(unpriced.eurPerGProtein)
        assertNull(unknownMacros.eurPerGProtein)
    }

    @Test
    fun `euro per gram protein divides when both sides are known`() {
        val totals = priceMeal(listOf(line("pasta_droog", 100.0)), context)
        assertEquals(0.20 / 12.0, totals.eurPerGProtein!!, 1e-9)
    }

    @Test
    fun `an empty meal costs nothing rather than being unknown`() {
        val totals = priceMeal(emptyList(), context)
        assertEquals(0.0, totals.eur!!, 1e-9)
        assertEquals(0.0, totals.proteinG!!, 1e-9)
    }

    // -- two lines of the same food ----------------------------------------

    @Test
    fun `the same food type may appear twice and both lines count`() {
        // composition_items' composite key forbids this on the Python side and
        // is right to; on a plate, "more of that cheese" is a normal request.
        val twice = listOf(
            line("pasta_droog", 100.0).copy(id = "a"),
            line("pasta_droog", 50.0).copy(id = "b"),
        )
        val totals = priceMeal(twice, context)
        assertEquals(2, totals.lines.size)
        assertEquals(0.30, totals.eur!!, 1e-9)
    }

    // -- building lines from slot picks ------------------------------------

    @Test
    fun `slot picks become lines with the grams the export already priced`() {
        val template = TemplateEntry(
            key = "pasta", name = "Pasta", meal_kind = "meal",
            slots = listOf(
                TemplateSlot("pasta", "Soort pasta", true, 100.0, listOf("pasta_droog")),
                TemplateSlot("sauce", "Saus", false, 150.0, listOf("pesto_groen")),
            ),
        )
        val candidates = mapOf(
            "pasta" to listOf(
                SlotCandidate(food_type = "pasta_droog", name = "pasta (droog)", grams = 125.0)
            ),
        )
        val lines = linesFromSelections(template, mapOf("pasta" to "pasta_droog"), candidates)

        assertEquals(1, lines.size)
        // 125 from the candidate, not the slot's 100 default.
        assertEquals(125.0, lines.single().quantity.amount, 1e-9)
        assertEquals("pasta", lines.single().slotKey)
    }

    @Test
    fun `an unchosen optional slot contributes no line`() {
        val template = TemplateEntry(
            key = "pasta", name = "Pasta", meal_kind = "meal",
            slots = listOf(TemplateSlot("sauce", "Saus", false, 150.0, listOf("pesto_groen"))),
        )
        assertEquals(emptyList<MealLine>(), linesFromSelections(template, emptyMap(), emptyMap()))
    }

    // -- provenance (BRIEF section 9 rule 1, docs/AUDIT.md finding 3.3) -------

    @Test
    fun `a total built from seed estimates is marked as estimated`() {
        val totals = priceMeal(listOf(line("pasta_droog", 100.0)), context)

        assertTrue(totals.macrosNeedMarking)
    }

    @Test
    fun `a total built only from label figures needs no mark`() {
        val totals = priceMeal(listOf(line("from_label", 200.0)), context)

        assertEquals(20.0, totals.proteinG!!, 0.001)
        assertTrue(!totals.macrosNeedMarking)
    }

    @Test
    fun `one estimated line taints the whole total`() {
        // A total is only as trustworthy as its least trustworthy line, exactly
        // as it is only as priced as its least priced one.
        val totals = priceMeal(
            listOf(line("from_label", 200.0), line("pasta_droog", 100.0)), context,
        )

        assertTrue(totals.macrosNeedMarking)
    }

    @Test
    fun `a line the app cannot identify is treated as needing a mark`() {
        // An unidentified line cannot vouch for its own macros. It contributes
        // no figure, so it cannot taint a total on its own...
        val unknownOnly = priceMeal(listOf(line(null, 100.0)), context)
        assertNull(unknownOnly.proteinG)

        // ...but the line itself still reads as unverified.
        assertTrue(priceLine(line(null, 100.0), context).macrosNeedMarking)
    }

    @Test
    fun `an empty meal has nothing to mark`() {
        assertTrue(!priceMeal(emptyList(), context).macrosNeedMarking)
    }
}

class CheapestPicksTest {
    private fun slot(key: String, required: Boolean) =
        TemplateSlot(key = key, name = key, required = required, default_grams = 100.0)
    private fun cand(food: String, eur: Double?) =
        SlotCandidate(food_type = food, name = food, grams = 100.0, price_eur = eur)

    private val template = TemplateEntry(
        key = "pasta", name = "Pasta", meal_kind = "meal",
        slots = listOf(slot("pasta", true), slot("sauce", true), slot("greens", false)),
    )

    @Test
    fun picks_the_cheapest_priced_candidate_for_each_required_slot() {
        val picks = cheapestPicks(template, mapOf(
            "pasta" to listOf(cand("volkoren", 0.14), cand("wit", 0.07)),
            "sauce" to listOf(cand("onbekend", null), cand("tomaat", 0.40)),
            "greens" to listOf(cand("sla", 0.10)),
        ))
        assertEquals(mapOf("pasta" to "wit", "sauce" to "tomaat"), picks)
    }

    @Test
    fun a_required_slot_with_nothing_priced_means_no_cheapest_plate() {
        val picks = cheapestPicks(template, mapOf(
            "pasta" to listOf(cand("wit", 0.07)),
            "sauce" to listOf(cand("onbekend", null)),
        ))
        assertNull(picks)
    }
}
