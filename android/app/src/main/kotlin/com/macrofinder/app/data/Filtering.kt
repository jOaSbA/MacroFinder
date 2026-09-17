package com.macrofinder.app.data

/**
 * The three tabs the user asked for: meals, drinks (shakes), and "everything
 * else" - the full ranked offer list for foods that aren't one of the eight
 * curated archetypes. This is deliberately NOT an optimiser: the app never
 * picks for the user, it only ranks and filters what they ask to see.
 */
enum class FoodTab { MEALS, SNACKS, DRINKS, OTHER }

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

/** The "everything else" tab: every ranked offer, filtered and sorted by
 * €/100 g protein (unrated offers sort last, never dropped silently). */
fun filterOffers(offers: List<OfferEntry>, filter: FilterState): List<OfferEntry> {
    return offers
        .asSequence()
        .filter { filter.includePersonalOffers || !it.is_personal_offer }
        .filter { !filter.hideUnpriced || it.price.unit_price_eur != null }
        .filter { filter.maxPriceEur == null || (it.price.unit_price_eur ?: Double.MAX_VALUE) <= filter.maxPriceEur }
        .filter { filter.minProteinG == null || (it.macros_per_100g.protein_g ?: 0.0) >= filter.minProteinG }
        .sortedWith(compareBy(nullsLast()) { it.eur_per_100g_protein })
        .toList()
}
