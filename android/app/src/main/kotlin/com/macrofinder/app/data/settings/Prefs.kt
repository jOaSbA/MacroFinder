package com.macrofinder.app.data.settings

import com.macrofinder.app.data.catalogue.Deal

enum class Diet { ALLES, VEGETARISCH, VEGAN }

val ALL_CHAINS = listOf("ah", "jumbo", "aldi")

/**
 * Milestone 32: the stores you shop at and what you eat. Local only.
 *
 * The diet comes from the `vegetarisch`/`vegan` tags the build derives from
 * `data/seed/diet.yaml`. A product without a food type has no tag, so the
 * filter hides it: unknown is not vegetarian.
 */
data class Prefs(
    val stores: Set<String> = ALL_CHAINS.toSet(),
    val diet: Diet = Diet.ALLES,
) {
    fun allows(deal: Deal): Boolean = deal.chain in stores && when (diet) {
        Diet.ALLES -> true
        Diet.VEGETARISCH -> "vegetarisch" in deal.buckets
        Diet.VEGAN -> "vegan" in deal.buckets
    }

    /** The chains a list shows: the ones picked within my stores, or all my stores. */
    fun chainsFor(picked: Set<String>): Set<String> = (picked intersect stores).ifEmpty { stores }

    /** Turn a store on or off. The last one stays on; a list with no stores is useless. */
    fun toggleStore(chain: String): Prefs =
        if (chain in stores) (if (stores.size > 1) copy(stores = stores - chain) else this)
        else copy(stores = stores + chain)
}
