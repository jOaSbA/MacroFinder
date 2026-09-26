package com.macrofinder.app.ui

import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.data.catalogue.ProductDetail

/**
 * The words and numbers the screens show, kept out of the composables so the
 * rules about them (never a bare estimated macro, unknown says unknown) are
 * JVM-tested.
 */

/** Prefix on any figure that comes from the generic seed rather than the label. */
const val ESTIMATE_MARK = "≈"

/** The sorted-on figure for a list row. DESIGN.md: always in the same slot. */
fun metricText(deal: Deal, sort: DealSort): String {
    val mark = if (deal.macrosEstimated) "$ESTIMATE_MARK " else ""
    return when (sort) {
        DealSort.PROTEIN_PER_EURO -> deal.eurPer100gProtein
            ?.let { "$mark${euro(it)} per 100 g eiwit" } ?: "eiwit onbekend"
        DealSort.PROTEIN_RATIO -> deal.proteinPer100kcal
            ?.let { mark + fmt("%.1f g eiwit per 100 kcal", it) } ?: "kcal onbekend"
        DealSort.KCAL_PER_EURO -> deal.eurPer1000kcal
            ?.let { "$mark${euro(it)} per 1000 kcal" } ?: "kcal onbekend"
        // A discount is a price fact, not a macro, so it never carries the mark.
        DealSort.DISCOUNT -> deal.discountPct?.let { fmt("%.0f%% korting", it) } ?: "korting onbekend"
    }
}

data class StripRow(val label: String, val value: String?, val estimated: Boolean)

data class MacroStripModel(
    val top: List<StripRow>,
    val money: List<StripRow>,
    val secondary: String?,
    /** Where the macros come from. Never null when any macro row has a value. */
    val provenance: String?,
)

/**
 * The macro strip on the detail screen (DESIGN.md 3.2), BRIEF section 9 rule
 * 1: no macro figure without saying where it came from.
 */
fun macroStrip(detail: ProductDetail): MacroStripModel {
    val d = detail.deal
    val est = d.macrosEstimated
    val mark = if (est) "$ESTIMATE_MARK " else ""
    fun v(x: Double?, f: (Double) -> String) = x?.let { mark + f(it) }

    val top = listOf(
        StripRow("Eiwit per 100 g", v(d.proteinPer100g) { fmt("%.1f g", it) }, est),
        StripRow("Eiwit per 100 kcal", v(d.proteinPer100kcal) { fmt("%.1f g", it) }, est),
    )
    val money = listOf(
        StripRow("Per 100 g eiwit", v(d.eurPer100gProtein) { euro(it)!! }, est),
        StripRow("Per 1000 kcal", v(d.eurPer1000kcal) { euro(it)!! }, est),
    )
    val secondary = listOfNotNull(
        d.kcalPer100g?.let { fmt("%.0f kcal", it) + if (detail.kcalIsDerived) " (uit kJ)" else "" },
        d.carbsPer100g?.let { fmt("%.1f g koolh.", it) },
        d.fatPer100g?.let { fmt("%.1f g vet", it) },
    ).takeIf { it.isNotEmpty() }?.joinToString(" · ", prefix = "${mark}per 100 g: ")

    val anyValue = (top + money).any { it.value != null } || secondary != null
    val provenance = when {
        !anyValue && !d.hasMacros -> "Voedingswaarde onbekend. We rekenen hier niets mee."
        est -> "$ESTIMATE_MARK Geschat uit de algemene waarde voor " +
            (detail.foodTypeName?.lowercase() ?: "dit soort product") + ", niet van het etiket."
        else -> "Van het etiket van dit product."
    }
    return MacroStripModel(top, money, secondary, provenance)
}

/** "koop 2" beside a multi-buy: BRIEF section 9 rule 3. */
fun quantityText(deal: Deal): String? =
    deal.requiredQuantity.takeIf { it > 1 }?.let { "koop $it" }

fun validityText(deal: Deal, today: String): String? = when {
    deal.isUpcomingOn(today) -> shortDate(deal.validFrom)?.let { "vanaf $it" }
    deal.lane != "shelf" -> shortDate(deal.validTo)?.let { "t/m $it" }
    else -> null
}

/** BRIEF section 9 rule 5: "cheapest in N weeks" beats "% off" as the headline. */
fun historyText(deal: Deal): String? = deal.cheapestInWeeks?.let { weeks ->
    if (weeks == 1) "Goedkoopste in 1 week" else "Goedkoopste in $weeks weken"
}

/** BRIEF section 9 rule 4: the honest second number for perishables. */
fun wasteText(deal: Deal): String? {
    val waste = deal.wasteAdjustedEurPer100gProtein ?: return null
    val headline = deal.eurPer100gProtein ?: return null
    if (!deal.perishable || waste <= headline * 1.01) return null
    val eaten = deal.realisticallyConsumable ?: return null
    return "${euro(waste)} per 100 g eiwit als je er maar $eaten van de " +
        "${deal.requiredQuantity} op krijgt voor ze bederven"
}

/**
 * PLAN-V2 section 4.3, one line. Complete protein says nothing: the flag is
 * there to qualify a cheap plant source, not to decorate every chicken fillet.
 */
fun proteinQualityNote(quality: String?): String? = when (quality) {
    "incomplete" -> "Onvolledig eiwit: mist genoeg van een of meer essentiële aminozuren. " +
        "Combineer peulvruchten met granen, of eet het naast zuivel, ei of soja."
    "blend" -> "Mengsel van eiwitbronnen; hoe volledig het is hangt af van het recept."
    else -> null
}
