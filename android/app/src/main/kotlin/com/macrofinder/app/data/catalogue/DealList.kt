package com.macrofinder.app.data.catalogue

/**
 * Filtering and sorting the deal list. Milestones 18 and 23.
 *
 * Pure, so the whole thing runs in the JVM tests. The deals are loaded into
 * memory once per sync (a few thousand rows) and everything the user taps
 * re-runs here, which is why changing the sort is instant.
 */

enum class DealWindow { ACTIVE, UPCOMING }

/** The four metrics from PLAN-V2 section 4.2, plus discount. */
enum class DealSort(val label: String) {
    PROTEIN_PER_EURO("Eiwit per euro"),
    PROTEIN_RATIO("Per 100 kcal"),
    KCAL_PER_EURO("Kcal per euro"),
    DISCOUNT("Korting"),
}

/** Shelves that are never food. Supplements are rescued by their bucket. */
val NON_FOOD_SHELVES = setOf("drogisterij", "huishouden", "huisdier", "baby", "alcohol")

const val BUCKET_BULK = "bulk"

data class DealQuery(
    val window: DealWindow = DealWindow.ACTIVE,
    /** Empty means every chain. */
    val chains: Set<String> = emptySet(),
    val shelf: String? = null,
    val bucket: String? = null,
    val foodOnly: Boolean = true,
    val includePersonal: Boolean = false,
    val sort: DealSort = DealSort.PROTEIN_PER_EURO,
)

/** How good a deal's sorted-on figure is, relative to the rest of the list. */
enum class DealTier { EXCELLENT, GOOD, AVERAGE, POOR }

data class RankedDeal(val deal: Deal, val tier: DealTier?)

fun selectDeals(
    all: List<Deal>,
    query: DealQuery,
    today: String,
    bulkCutoff: Double? = null,
): List<RankedDeal> {
    val inWindow = all.filter {
        when (query.window) {
            DealWindow.ACTIVE -> it.isActiveOn(today)
            DealWindow.UPCOMING -> it.isUpcomingOn(today)
        }
    }
    val filtered = onePerProduct(inWindow).filter { deal ->
        (query.chains.isEmpty() || deal.chain in query.chains) &&
            (query.shelf == null || deal.shelf == query.shelf) &&
            (query.includePersonal || !deal.isPersonal) &&
            (!query.foodOnly || isFood(deal)) &&
            (query.bucket == null || inBucket(deal, query.bucket, bulkCutoff))
    }
    val sorted = filtered.sortedWith(comparatorFor(query.sort))
    return withTiers(sorted, query.sort)
}

fun isFood(deal: Deal): Boolean =
    deal.shelf !in NON_FOOD_SHELVES || "supplement" in deal.buckets

fun inBucket(deal: Deal, bucket: String, bulkCutoff: Double?): Boolean =
    if (bucket == BUCKET_BULK) {
        // Relative, so the cutoff ships once in meta rather than on each row.
        bulkCutoff != null && deal.eurPer1000kcal != null && deal.eurPer1000kcal <= bulkCutoff
    } else {
        bucket in deal.buckets
    }

/**
 * A product can show up twice in one window: a promo and an "upcoming" one
 * that has since started. Keep the cheaper.
 */
private fun onePerProduct(deals: List<Deal>): List<Deal> =
    deals.groupBy { it.id }.values.map { rows ->
        rows.minWithOrNull(compareBy(nullsLast()) { it.price }) ?: rows.first()
    }

/** The value a sort orders on, oriented so smaller is better. */
fun sortValue(deal: Deal, sort: DealSort): Double? = when (sort) {
    DealSort.PROTEIN_PER_EURO -> deal.eurPer100gProtein
    DealSort.PROTEIN_RATIO -> deal.proteinPer100kcal?.let { -it }
    DealSort.KCAL_PER_EURO -> deal.eurPer1000kcal
    DealSort.DISCOUNT -> deal.discountPct?.let { -it }
}

/** Unknowns go last, never dropped. Ties break on name so the order is stable. */
fun comparatorFor(sort: DealSort): Comparator<Deal> =
    compareBy<Deal, Double?>(nullsLast()) { sortValue(it, sort) }
        .thenBy { it.name.lowercase() }
        .thenBy { it.id }

/**
 * Top 10% excellent, next 20% good, next 30% average, rest poor, among the
 * deals that have the figure at all. DESIGN.md colours by these.
 */
private fun withTiers(sorted: List<Deal>, sort: DealSort): List<RankedDeal> {
    val known = sorted.count { sortValue(it, sort) != null }
    var rank = 0
    return sorted.map { deal ->
        if (sortValue(deal, sort) == null) {
            RankedDeal(deal, null)
        } else {
            val share = rank++.toDouble() / known
            RankedDeal(deal, when {
                share < 0.10 -> DealTier.EXCELLENT
                share < 0.30 -> DealTier.GOOD
                share < 0.60 -> DealTier.AVERAGE
                else -> DealTier.POOR
            })
        }
    }
}
