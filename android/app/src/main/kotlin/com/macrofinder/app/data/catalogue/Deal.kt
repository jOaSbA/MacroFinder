package com.macrofinder.app.data.catalogue

/**
 * One priced product on one lane: this week's promo or an upcoming one.
 *
 * Read from the synced catalogue (see `src/bonusrank/appdb.py` for every
 * column), or mapped from `latest.json` while the catalogue hasn't arrived.
 * Every macro and metric is nullable, and null means unknown. Nothing here is
 * ever defaulted to zero, because zero sorts first on a "cheapest protein"
 * list.
 */
data class Deal(
    val id: String,
    val chain: String,
    val name: String,
    val brand: String? = null,
    val unitText: String? = null,
    val imageUrl: String? = null,
    val shelf: String? = null,
    val foodType: String? = null,
    val massG: Double? = null,
    val proteinPer100g: Double? = null,
    val kcalPer100g: Double? = null,
    val carbsPer100g: Double? = null,
    val fatPer100g: Double? = null,
    val macroSource: String? = null,
    val macroConfidence: String? = null,
    val proteinPer100kcal: Double? = null,
    val buckets: Set<String> = emptySet(),
    val lane: String = "promo",
    val price: Double? = null,
    val shelfPrice: Double? = null,
    val promoText: String? = null,
    val requiredQuantity: Int = 1,
    val isPersonal: Boolean = false,
    val validFrom: String? = null,
    val validTo: String? = null,
    val eurPer100gProtein: Double? = null,
    val eurPer1000kcal: Double? = null,
    val discountPct: Double? = null,
    val wasteAdjustedEurPer100gProtein: Double? = null,
    val realisticallyConsumable: Int? = null,
    val perishable: Boolean = false,
    val cheapestInWeeks: Int? = null,
    val referenceInflated: Boolean? = null,
    val promoCycleDays: Int? = null,
    val lastPromoStart: String? = null,
) {
    /**
     * BRIEF section 9 rule 1: a macro from the generic seed, or any
     * low-confidence source, never renders bare. Same test as
     * `ranking.RankedOffer.needs_macro_marking` in Python.
     */
    val macrosEstimated: Boolean
        get() = macroConfidence in setOf("seed", "low") || macroSource == "estimated"

    val hasMacros: Boolean get() = proteinPer100g != null

    /** Dates are ISO strings, so plain string comparison orders them. */
    fun isActiveOn(today: String): Boolean =
        (validFrom == null || validFrom <= today) && (validTo == null || validTo >= today)

    fun isUpcomingOn(today: String): Boolean = validFrom != null && validFrom > today
}
