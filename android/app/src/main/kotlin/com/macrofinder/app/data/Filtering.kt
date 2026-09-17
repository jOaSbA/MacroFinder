package com.macrofinder.app.data

/**
 * The tabs the user asked for. MEALS is inherently different from the other
 * three: a "meal" is a composed dish (a wrap, a pasta, a pudding), never a
 * single food type on its own - no raw ingredient in the Python seed is ever
 * classified `meal_kind: meal` (see CLAUDE.md milestone 11 / `food_types`
 * seed), on purpose, the same way a raw chicken fillet isn't "a meal". So
 * MEALS is driven by [ArchetypeEntry] (curated ready-made-vs-DIY comparisons;
 * a slot-based meal customiser is planned on top of the same idea, not yet
 * built). SNACKS, DRINKS and OTHER are driven directly by the full ranked
 * `offers` list, keyed on the matched food type's own `meal_kind` - every
 * matched, priced SKU shows up in the right tab, not just a hand-picked few.
 *
 * This is deliberately NOT an optimiser: the app never picks for the user, it
 * only ranks and filters what they ask to see.
 */
enum class FoodTab { MEALS, SNACKS, DRINKS, OTHER }

/** The food_type-level meal_kind an OFFER tab (everything but MEALS) filters
 * on. Throws for MEALS, which has no such mapping - see the tab's own doc. */
private fun FoodTab.offerMealKind(): String = when (this) {
    FoodTab.SNACKS -> "snack"
    FoodTab.DRINKS -> "drink"
    FoodTab.OTHER -> "ingredient"
    FoodTab.MEALS -> error("MEALS is archetype-driven, not offer-meal_kind-driven")
}

data class FilterState(
    val maxPriceEur: Double? = null,
    val minProteinG: Double? = null,
    val hideUnpriced: Boolean = true,
    val includePersonalOffers: Boolean = false,
)

/** Archetypes for one tab, cheapest-priced route first within each. */
fun archetypesForTab(archetypes: List<ArchetypeEntry>, tab: FoodTab): List<ArchetypeEntry> {
    val kind = when (tab) {
        FoodTab.MEALS -> "meal"
        FoodTab.SNACKS -> "snack"
        FoodTab.DRINKS -> "drink"
        FoodTab.OTHER -> return emptyList()
    }
    return archetypes
        .filter { it.meal_kind == kind }
        .sortedWith(compareBy(nullsLast()) { cheapestEurPerGProtein(it) })
}

/** The cheapest €/g protein across an archetype's ready-made and DIY routes -
 * the same number `bonusrank compare`'s verdict is built from. Null when
 * nothing on either route could be priced. */
fun cheapestEurPerGProtein(archetype: ArchetypeEntry): Double? {
    val candidates = buildList {
        archetype.ready_made?.eur_per_g_protein?.let { add(it) }
        archetype.compositions.mapNotNull { it.eur_per_g_protein }.forEach { add(it) }
    }
    return candidates.minOrNull()
}

/** Every ranked offer matching `mealKind` (or all offers when null - used for
 * a global search across everything, not one specific tab), filtered and
 * sorted by €/100 g protein (unrated offers sort last, never dropped
 * silently). */
fun filterOffers(
    offers: List<OfferEntry>,
    filter: FilterState,
    mealKind: String? = null,
): List<OfferEntry> {
    return offers
        .asSequence()
        .filter { mealKind == null || it.meal_kind == mealKind }
        .filter { filter.includePersonalOffers || !it.is_personal_offer }
        .filter { !filter.hideUnpriced || it.price.unit_price_eur != null }
        .filter { filter.maxPriceEur == null || (it.price.unit_price_eur ?: Double.MAX_VALUE) <= filter.maxPriceEur }
        .filter { filter.minProteinG == null || (it.macros_per_100g.protein_g ?: 0.0) >= filter.minProteinG }
        .sortedWith(compareBy(nullsLast()) { it.eur_per_100g_protein })
        .toList()
}

/** The SNACKS/DRINKS/OTHER tabs: [filterOffers] pre-scoped to that tab's
 * food-type meal_kind. Not valid for MEALS - see [FoodTab]'s own doc. */
fun offersForTab(offers: List<OfferEntry>, tab: FoodTab, filter: FilterState): List<OfferEntry> =
    filterOffers(offers, filter, mealKind = tab.offerMealKind())
