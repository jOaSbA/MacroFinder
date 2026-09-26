package com.macrofinder.app.data.following

import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.currentLane
import kotlin.math.roundToInt

/**
 * Milestone 34: "tell me when this drops under X per 100 g protein", the
 * Keepa idea in protein terms. Pure, so the crossing cases are JVM tests.
 */

/** Keyed on the product and the price, so a further drop under target alerts again. Starts with the id, like [alertKey]. */
fun targetKey(deal: Deal): String =
    "${deal.id}|target|${deal.eurPer100gProtein?.let { (it * 100).roundToInt() }}"

/** Preset targets offered on the product page: 10, 20 and 30 percent under today's figure. */
fun targetPresets(current: Double): List<Double> =
    listOf(0.9, 0.8, 0.7).map { (current * it * 100).roundToInt() / 100.0 }

/**
 * Followed products whose price today is at or under their target and that
 * haven't been announced at this price. Unknown protein never crosses.
 */
fun targetAlerts(
    targets: Map<String, Double>,
    deals: List<Deal>,
    alreadyNotified: Set<String>,
    today: String,
): List<Deal> = deals.groupBy { it.id }
    .filterKeys { it in targets }
    .mapNotNull { (id, lanes) ->
        val now = currentLane(lanes, today) ?: return@mapNotNull null
        val value = now.eurPer100gProtein ?: return@mapNotNull null
        if (value <= targets.getValue(id) && targetKey(now) !in alreadyNotified) now else null
    }
    .sortedBy { it.name }

/** Stored as "id|value" strings, because DataStore preferences have no map type. */
fun encodeTargets(targets: Map<String, Double>): Set<String> =
    targets.map { (id, v) -> "$id|$v" }.toSet()

fun decodeTargets(raw: Set<String>): Map<String, Double> = raw.mapNotNull { entry ->
    val id = entry.substringBeforeLast('|', "")
    val value = entry.substringAfterLast('|').toDoubleOrNull()
    if (id.isEmpty() || value == null) null else id to value
}.toMap()
