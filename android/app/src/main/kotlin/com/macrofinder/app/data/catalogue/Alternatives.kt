package com.macrofinder.app.data.catalogue

/** A product that gets you the same protein for less, and by how much. */
data class Alternative(val deal: Deal, val savingPer100gProtein: Double)

/**
 * The lane a product really sells at today: a running promo, else its shelf
 * price. An upcoming promo isn't a price you can pay yet, and a personal offer
 * isn't everyone's price (BRIEF section 9).
 */
fun currentLane(lanes: List<Deal>, today: String): Deal? =
    lanes.firstOrNull { it.lane == "promo" && it.isActiveOn(today) && !it.isPersonal }
        ?: lanes.firstOrNull { it.lane == "shelf" }

/**
 * Milestone 31: the same food, cheaper per 100 g protein, at any chain.
 *
 * Only the same food type counts, because "cheaper protein" across food types
 * is a different question (kwark against tuna) and the ranked list already
 * answers it. Unknown protein is never cheaper, and a product we can't price
 * per gram of protein has nothing to compare against, so it gets no list.
 * Differences under a cent are noise.
 */
fun cheaperAlternatives(
    product: Deal?,
    candidates: List<Deal>,
    today: String,
    chains: Set<String> = emptySet(),
    limit: Int = 3,
): List<Alternative> {
    val mine = product?.eurPer100gProtein ?: return emptyList()
    return candidates.filter { it.id != product.id }
        .groupBy { it.id }.values
        .mapNotNull { currentLane(it, today) }
        .filter { chains.isEmpty() || it.chain in chains }
        .mapNotNull { d ->
            val theirs = d.eurPer100gProtein ?: return@mapNotNull null
            if (mine - theirs >= 0.01) Alternative(d, mine - theirs) else null
        }
        .sortedBy { it.deal.eurPer100gProtein }
        .take(limit)
}
