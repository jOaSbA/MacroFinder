package com.macrofinder.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer

/**
 * Saved meals, on this phone only. Milestone 13.
 *
 * DataStore rather than Room: the entire persisted state is a short list of
 * small objects, and the project already has kotlinx.serialization and
 * [MacroFinderJson]. Room would mean a KSP code-generation step, a database
 * schema and a migration story for something a JSON string handles.
 *
 * **Prices are never stored.** A saved meal holds template, slot, food type and
 * quantity - keys and numbers the user chose - and is re-costed against the
 * current snapshot every time it is opened. That is what makes a saved meal
 * follow the weekly bonus around, and it falls out of storing keys rather than
 * euros. Storing a price would freeze last week's deal into the meal forever.
 *
 * Serialisation failures are swallowed into an empty list rather than crashing:
 * a saved meal is a convenience, and a file written by an older build must
 * never make the app unusable. [serializeMeals] and [deserializeMeals] are
 * separated out so the round trip is testable on the JVM - DataStore itself
 * needs an instrumentation test, which `android/README.md` is explicit about
 * not adding.
 */
private val Context.savedMealsDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "saved_meals"
)

private val SAVED_MEALS = stringPreferencesKey("saved_meals_json")

private val MEALS = ListSerializer(SavedMeal.serializer())

fun serializeMeals(meals: List<SavedMeal>): String =
    MacroFinderJson.encodeToString(MEALS, meals)

fun deserializeMeals(json: String?): List<SavedMeal> {
    if (json.isNullOrBlank()) return emptyList()
    return try {
        MacroFinderJson.decodeFromString(MEALS, json)
    } catch (e: Exception) {
        emptyList()
    }
}

class SavedMealsStore(private val context: Context) {

    val meals: Flow<List<SavedMeal>> =
        context.savedMealsDataStore.data.map { deserializeMeals(it[SAVED_MEALS]) }

    suspend fun save(meal: SavedMeal) {
        context.savedMealsDataStore.edit { preferences ->
            val current = deserializeMeals(preferences[SAVED_MEALS])
            // Replace by id rather than appending, so re-saving an opened meal
            // edits it instead of leaving a near-duplicate behind.
            val updated = current.filterNot { it.id == meal.id } + meal
            preferences[SAVED_MEALS] = serializeMeals(updated)
        }
    }

    suspend fun delete(id: String) {
        context.savedMealsDataStore.edit { preferences ->
            val remaining = deserializeMeals(preferences[SAVED_MEALS]).filterNot { it.id == id }
            preferences[SAVED_MEALS] = serializeMeals(remaining)
        }
    }
}
