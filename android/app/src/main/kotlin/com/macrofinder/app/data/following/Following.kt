package com.macrofinder.app.data.following

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.macrofinder.app.data.catalogue.Deal
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/**
 * Followed products and local promo alerts. Milestone 26.
 *
 * Purely on the phone. The sync brings the promo data down and the phone
 * decides whether a followed product just went on offer. No server, no
 * account, no push.
 */

/** One alert per promo, not per sync: keyed on the product and the promo's own window. */
fun alertKey(deal: Deal): String = "${deal.id}|${deal.validFrom}|${deal.promoText}"

/**
 * Followed products that are on offer today and haven't been announced yet.
 * Pure, so the "a followed product enters a promo" case is a JVM test.
 */
fun promoAlerts(
    followed: Set<String>,
    deals: List<Deal>,
    alreadyNotified: Set<String>,
    today: String,
): List<Deal> =
    deals.filter { it.id in followed && it.lane != "shelf" && it.isActiveOn(today) }
        .filter { alertKey(it) !in alreadyNotified }
        .distinctBy { it.id }
        .sortedBy { it.name }

private val Context.followingStore by preferencesDataStore(name = "following")

class FollowingStore(private val context: Context) {
    private val followedKey = stringSetPreferencesKey("followed")
    private val notifiedKey = stringSetPreferencesKey("notified")

    val followed: Flow<Set<String>> =
        context.followingStore.data.map { it[followedKey].orEmpty() }

    suspend fun toggle(productId: String) {
        context.followingStore.edit { prefs ->
            val now = prefs[followedKey].orEmpty()
            prefs[followedKey] = if (productId in now) now - productId else now + productId
        }
    }

    suspend fun followedNow(): Set<String> = followed.first()

    suspend fun notified(): Set<String> =
        context.followingStore.data.map { it[notifiedKey].orEmpty() }.first()

    /** Remember what was announced. Old keys for unfollowed products are dropped. */
    suspend fun markNotified(keys: Collection<String>) {
        context.followingStore.edit { prefs ->
            val followed = prefs[followedKey].orEmpty()
            val kept = prefs[notifiedKey].orEmpty().filter { it.substringBefore('|') in followed }
            prefs[notifiedKey] = (kept + keys).toSet()
        }
    }
}
