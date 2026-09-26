package com.macrofinder.app.data.tally

import com.macrofinder.app.data.catalogue.Deal

/**
 * Milestone 38: a protein tally for a shop. Not a shopping list and not a
 * planner: add products, see what the basket costs and how much protein and
 * energy it buys. Stored as product ids and pack counts, never prices, so it
 * re-prices on every sync like saved meals.
 */
data class TallyLine(val id: String, val packs: Int, val deal: Deal?)

data class TallyTotals(
    val eur: Double?,
    val proteinG: Double?,
    val kcal: Double?,
    /** Euros per 100 g protein for the whole basket. */
    val eurPer100gProtein: Double?,
    val byChain: Map<String, Double?>,
    /** Lines that make [eur] unknown, by name. */
    val unpriced: List<String>,
    /** Lines that make [proteinG] or [kcal] unknown, by name. */
    val unknownMacros: List<String>,
)

/**
 * What [packs] of a product cost today. A multi-buy ("1+1 gratis", koop 2)
 * only gets its promo price in full groups; the rest pay the shelf price, and
 * without one the cost is unknown rather than a guess.
 */
fun packCost(deal: Deal, packs: Int): Double? {
    val price = deal.price ?: return null
    val group = deal.requiredQuantity.coerceAtLeast(1)
    if (deal.lane != "promo" || group == 1) return price * packs
    val rest = packs % group
    val restCost = if (rest == 0) 0.0 else (deal.shelfPrice ?: return null) * rest
    return (packs - rest) * price + restCost
}

private fun perPack(per100: Double?, deal: Deal): Double? {
    val mass = deal.massG ?: return null
    return per100?.let { it * mass / 100.0 }
}

/** The same poison rule as MealMath: one unknown line makes that total unknown, and is named. */
fun tallyTotals(lines: List<TallyLine>): TallyTotals {
    val costs = lines.map { l -> l.deal?.let { packCost(it, l.packs) } }
    val protein = lines.map { l -> l.deal?.let { perPack(it.proteinPer100g, it) }?.times(l.packs) }
    val kcal = lines.map { l -> l.deal?.let { perPack(it.kcalPer100g, it) }?.times(l.packs) }
    fun name(l: TallyLine) = l.deal?.name ?: "een product dat niet meer in de catalogus staat"

    val eur = if (costs.any { it == null }) null else costs.sumOf { it!! }
    val proteinG = if (protein.any { it == null }) null else protein.sumOf { it!! }
    val kcalSum = if (kcal.any { it == null }) null else kcal.sumOf { it!! }
    val byChain = lines.indices.groupBy { lines[it].deal?.chain ?: "?" }
        .mapValues { (_, idx) -> if (idx.any { costs[it] == null }) null else idx.sumOf { costs[it]!! } }
    return TallyTotals(
        eur = eur,
        proteinG = proteinG,
        kcal = kcalSum,
        eurPer100gProtein = if (eur != null && proteinG != null && proteinG > 0) eur / proteinG * 100 else null,
        byChain = byChain,
        unpriced = lines.filterIndexed { i, _ -> costs[i] == null }.map(::name),
        unknownMacros = lines.filterIndexed { i, _ -> protein[i] == null || kcal[i] == null }.map(::name),
    )
}

fun encodeTally(packs: Map<String, Int>): Set<String> = packs.filterValues { it > 0 }.map { (id, n) -> "$id|$n" }.toSet()

fun decodeTally(raw: Set<String>): Map<String, Int> = raw.mapNotNull { e ->
    val id = e.substringBeforeLast('|', "")
    val n = e.substringAfterLast('|').toIntOrNull()
    if (id.isEmpty() || n == null || n <= 0) null else id to n
}.toMap()
