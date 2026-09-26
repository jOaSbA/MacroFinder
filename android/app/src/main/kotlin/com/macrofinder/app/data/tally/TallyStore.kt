package com.macrofinder.app.data.tally

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.tallyStore by preferencesDataStore(name = "tally")

/** Milestone 38: product id -> packs. Local only. */
class TallyStore(private val context: Context) {
    private val key = stringSetPreferencesKey("packs")

    val packs: Flow<Map<String, Int>> = context.tallyStore.data.map { decodeTally(it[key].orEmpty()) }

    /** Zero or less removes the product. */
    suspend fun set(id: String, packs: Int) {
        context.tallyStore.edit {
            val now = decodeTally(it[key].orEmpty())
            it[key] = encodeTally(if (packs <= 0) now - id else now + (id to packs))
        }
    }

    suspend fun clear() {
        context.tallyStore.edit { it.remove(key) }
    }
}
