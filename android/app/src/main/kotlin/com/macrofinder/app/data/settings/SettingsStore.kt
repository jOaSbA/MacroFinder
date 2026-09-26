package com.macrofinder.app.data.settings

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.settingsStore by preferencesDataStore(name = "settings")

class SettingsStore(private val context: Context) {
    private val storesKey = stringSetPreferencesKey("stores")
    private val dietKey = stringPreferencesKey("diet")
    private val digestKey = booleanPreferencesKey("weekly_digest")
    private val digestSentKey = stringPreferencesKey("digest_sent")

    val prefs: Flow<Prefs> = context.settingsStore.data.map { p ->
        Prefs(
            stores = p[storesKey]?.filter { it in ALL_CHAINS }?.toSet()?.ifEmpty { null }
                ?: ALL_CHAINS.toSet(),
            diet = p[dietKey]?.let { runCatching { Diet.valueOf(it) }.getOrNull() } ?: Diet.ALLES,
            weeklyDigest = p[digestKey] ?: false,
        )
    }

    suspend fun current(): Prefs = prefs.first()

    /** The week the last digest went out for, so a second sync that week stays quiet. */
    suspend fun lastDigest(): String? = context.settingsStore.data.map { it[digestSentKey] }.first()

    suspend fun markDigest(week: String) {
        context.settingsStore.edit { it[digestSentKey] = week }
    }

    suspend fun save(prefs: Prefs) {
        context.settingsStore.edit {
            it[storesKey] = prefs.stores
            it[dietKey] = prefs.diet.name
            it[digestKey] = prefs.weeklyDigest
        }
    }
}
