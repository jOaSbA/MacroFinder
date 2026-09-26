package com.macrofinder.app.data.following

import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.DealQuery
import com.macrofinder.app.data.catalogue.selectDeals
import com.macrofinder.app.data.settings.Prefs
import java.time.LocalDate
import java.time.temporal.IsoFields

/** "2026-W39": the digest goes out at most once per ISO week. */
fun digestWeek(today: LocalDate): String =
    "%d-W%02d".format(today.get(IsoFields.WEEK_BASED_YEAR), today.get(IsoFields.WEEK_OF_WEEK_BASED_YEAR))

/**
 * Milestone 33: the week's best protein deals for my stores and diet, or
 * nothing if the digest is off or already went out this week.
 *
 * The same ranking as the deal list's default sort, so the notification never
 * disagrees with the app. One product per food type, or three kwarks from
 * the same shelf would fill it.
 */
fun weeklyDigest(
    deals: List<Deal>,
    prefs: Prefs,
    today: LocalDate,
    lastSent: String?,
    size: Int = 3,
): List<Deal> {
    if (!prefs.weeklyDigest || digestWeek(today) == lastSent) return emptyList()
    return selectDeals(deals.filter(prefs::allows), DealQuery(chains = prefs.stores), today.toString())
        .map { it.deal }
        .filter { it.eurPer100gProtein != null }
        .distinctBy { it.foodType ?: it.id }
        .take(size)
}
