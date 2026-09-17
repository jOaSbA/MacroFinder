package com.macrofinder.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure JVM tests, no Android framework and no emulator - this is the part of
 * the app CI can actually run (see android/README.md for the split).
 */
class FilteringTest {

    private fun offer(
        sku: String,
        priceEur: Double?,
        proteinG: Double? = 10.0,
        eurPer100gProtein: Double? = 1.0,
        personal: Boolean = false,
        mealKind: String? = "snack",
    ) = OfferEntry(
        sku = sku,
        name = "Test $sku",
        meal_kind = mealKind,
        price = PriceInfo(
            unit_price_eur = priceEur,
            required_quantity = 1,
            promo_mechanic = "not_a_promo",
            is_promo = false,
        ),
        macros_per_100g = Macros(protein_g = proteinG),
        macros_need_marking = false,
        kcal_is_derived = false,
        eur_per_100g_protein = eurPer100gProtein,
        perishable = false,
        is_personal_offer = personal,
    )

    @Test
    fun `unpriced offers are hidden by default`() {
        val offers = listOf(offer("a", 1.0), offer("b", null))
        val visible = filterOffers(offers, FilterState())
        assertEquals(listOf("a"), visible.map { it.sku })
    }

    @Test
    fun `hideUnpriced can be turned off without dropping the item`() {
        val offers = listOf(offer("a", 1.0), offer("b", null))
        val visible = filterOffers(offers, FilterState(hideUnpriced = false))
        assertEquals(setOf("a", "b"), visible.map { it.sku }.toSet())
    }

    @Test
    fun `personal offers are excluded unless explicitly included`() {
        val offers = listOf(offer("a", 1.0, personal = false), offer("b", 1.0, personal = true))
        assertEquals(listOf("a"), filterOffers(offers, FilterState()).map { it.sku })
        assertEquals(
            setOf("a", "b"),
            filterOffers(offers, FilterState(includePersonalOffers = true)).map { it.sku }.toSet(),
        )
    }

    @Test
    fun `max price filters out anything above it`() {
        val offers = listOf(offer("cheap", 1.0), offer("pricey", 5.0))
        val visible = filterOffers(offers, FilterState(maxPriceEur = 2.0))
        assertEquals(listOf("cheap"), visible.map { it.sku })
    }

    @Test
    fun `min protein filters out anything below it`() {
        val offers = listOf(offer("lean", 1.0, proteinG = 20.0), offer("weak", 1.0, proteinG = 1.0))
        val visible = filterOffers(offers, FilterState(minProteinG = 10.0))
        assertEquals(listOf("lean"), visible.map { it.sku })
    }

    @Test
    fun `offers sort cheapest per gram protein first, unrated last`() {
        val offers = listOf(
            offer("unrated", 1.0, eurPer100gProtein = null),
            offer("pricey", 1.0, eurPer100gProtein = 5.0),
            offer("cheap", 1.0, eurPer100gProtein = 1.0),
        )
        val visible = filterOffers(offers, FilterState(hideUnpriced = false))
        assertEquals(listOf("cheap", "pricey", "unrated"), visible.map { it.sku })
    }

    // -- archetypes -------------------------------------------------------

    private fun verdict() = Verdict(winner = "unknown", text = "no verdict")

    private fun archetype(key: String, kind: String, eurPerGProtein: Double?) = ArchetypeEntry(
        key = key,
        name = key,
        meal_kind = kind,
        compositions = listOfNotNull(
            eurPerGProtein?.let {
                Composition(
                    name = "test",
                    taste_delta_note = "different",
                    eur_per_g_protein = it,
                )
            },
        ),
        verdict = verdict(),
    )

    @Test
    fun `archetypesForTab only returns the matching meal_kind`() {
        val archetypes = listOf(
            archetype("pudding", "snack", 0.05),
            archetype("wrap", "meal", 0.03),
            archetype("shake", "drink", 0.01),
        )
        assertEquals(listOf("wrap"), archetypesForTab(archetypes, FoodTab.MEALS).map { it.key })
        assertEquals(listOf("shake"), archetypesForTab(archetypes, FoodTab.DRINKS).map { it.key })
        assertEquals(listOf("pudding"), archetypesForTab(archetypes, FoodTab.SNACKS).map { it.key })
    }

    @Test
    fun `the OTHER tab never returns archetypes`() {
        val archetypes = listOf(archetype("wrap", "meal", 0.03))
        assertTrue(archetypesForTab(archetypes, FoodTab.OTHER).isEmpty())
    }

    @Test
    fun `cheapestEurPerGProtein prefers the lower of ready-made and DIY`() {
        val readyMade = ReadyMade(
            sku = "r1", name = "Ready", matched_by = "food_type x",
            required_quantity = 1, is_personal_offer = false, eur_per_g_protein = 0.10,
        )
        val entry = ArchetypeEntry(
            key = "k", name = "k", meal_kind = "meal",
            ready_made = readyMade,
            compositions = listOf(
                Composition(name = "c", taste_delta_note = "d", eur_per_g_protein = 0.05),
            ),
            verdict = verdict(),
        )
        assertEquals(0.05, cheapestEurPerGProtein(entry)!!, 1e-9)
    }

    @Test
    fun `cheapestEurPerGProtein is null when nothing priced`() {
        val entry = ArchetypeEntry(key = "k", name = "k", meal_kind = "meal", verdict = verdict())
        assertEquals(null, cheapestEurPerGProtein(entry))
    }

    // -- offersForTab: every ranked offer, not just the curated archetypes --

    @Test
    fun `offersForTab only returns offers matching that tab's food meal_kind`() {
        val offers = listOf(
            offer("fruit", 1.0, mealKind = "snack"),
            offer("milk", 1.0, mealKind = "drink"),
            offer("rice", 1.0, mealKind = "ingredient"),
        )
        assertEquals(listOf("fruit"), offersForTab(offers, FoodTab.SNACKS, FilterState()).map { it.sku })
        assertEquals(listOf("milk"), offersForTab(offers, FoodTab.DRINKS, FilterState()).map { it.sku })
        assertEquals(listOf("rice"), offersForTab(offers, FoodTab.OTHER, FilterState()).map { it.sku })
    }

    @Test
    fun `offersForTab is not just the eight archetypes - it scales with the catalogue`() {
        val manySnacks = (1..50).map { offer("snack$it", 1.0, mealKind = "snack") }
        assertEquals(50, offersForTab(manySnacks, FoodTab.SNACKS, FilterState()).size)
    }

    @Test(expected = IllegalStateException::class)
    fun `offersForTab refuses MEALS - that tab is archetype-driven`() {
        offersForTab(listOf(offer("x", 1.0)), FoodTab.MEALS, FilterState())
    }
}
