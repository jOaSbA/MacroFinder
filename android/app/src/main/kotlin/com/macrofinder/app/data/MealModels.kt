package com.macrofinder.app.data

import kotlinx.serialization.Serializable

/**
 * A meal the user is composing or has saved. Milestone 13.
 *
 * Unlike everything in [ExportModels], this is the app's OWN data - it is not
 * mirrored from `export.py` and nothing on the Python side reads it. It never
 * leaves the phone.
 *
 * Two shapes here exist because of specific failure modes, not taste:
 *
 * A [MealLine] keys on STRINGS - `templateKey`, `slotKey`, `foodType` - and
 * never on a database id. `seed.py::load_templates` deletes and re-inserts its
 * child rows on every `bonusrank seed`, so `template_slots.id` changes from run
 * to run. A saved meal holding an integer id would silently re-point at a
 * different slot after a reseed, which is the worst kind of bug: no error, just
 * wrong food.
 *
 * Lines are an ORDERED LIST with their own ids, not a map keyed by food type.
 * `composition_items` uses `PRIMARY KEY (composition_id, food_type_id)`, which
 * makes "50 g more of the cheese I already picked" unrepresentable. That
 * constraint is right for a hand-authored recipe and wrong here.
 */
@Serializable
data class SavedMeal(
    val id: String,
    val name: String,
    /** Null for a meal built from scratch rather than from a template. */
    val templateKey: String? = null,
    val lines: List<MealLine> = emptyList(),
)

@Serializable
data class MealLine(
    /** Unique within its meal. Lets two lines share a food type. */
    val id: String,
    /**
     * Which slot of the template this fills, or null for an extra the user
     * added themselves ("100 g ketchup", "4 boiled eggs").
     */
    val slotKey: String? = null,
    /**
     * The food type, or null for something the app cannot identify. Null is
     * reserved for milestone 14's raw catalogue SKUs; it already propagates
     * correctly through pricing and rule checking, so that milestone adds a
     * screen rather than a new concept.
     */
    val foodType: String? = null,
    /** What to show. Kept on the line so a saved meal reads correctly even if
     *  the food type later disappears from the seed. */
    val label: String,
    val quantity: Quantity,
)

@Serializable
data class Quantity(val amount: Double, val unit: QuantityUnit = QuantityUnit.GRAMS)

/**
 * GRAMS is the primitive. UNITS exists because "4 boiled eggs" is how a person
 * actually thinks, and `food_types.g_per_unit` is the conversion - a food type
 * without one cannot be counted in units, and says so rather than guessing 1 g.
 */
@Serializable
enum class QuantityUnit { GRAMS, UNITS }

/** One line of a meal, costed. Any field may be null, and null means unknown. */
data class PricedLine(
    val line: MealLine,
    val grams: Double?,
    val eur: Double?,
    val proteinG: Double?,
    val kcal: Double?,
    val carbsG: Double?,
    val fatG: Double?,
)

/**
 * A whole meal, costed. Milestone 13's central rule, and the app-side twin of
 * `archetypes.py::_price_composition`:
 *
 * **One unpriced line makes `eur` null, and the line is still listed.** Summing
 * the rest would claim the meal is cheaper than anyone can buy it for.
 *
 * And its symmetric partner, which `_sum_or_none` already enforces on the
 * Python side: **one line with an unknown macro makes that macro total null.**
 * A meal containing something with no protein figure does not have a known
 * protein total, and rounding the unknown down to zero would understate it.
 *
 * [unpricedLines] and [unknownMacroLines] name the culprits, so the UI can say
 * WHICH line spoiled the total instead of showing a bare dash.
 */
data class MealTotals(
    val lines: List<PricedLine>,
    val eur: Double?,
    val proteinG: Double?,
    val kcal: Double?,
    val carbsG: Double?,
    val fatG: Double?,
    val unpricedLines: List<String> = emptyList(),
    val unknownMacroLines: List<String> = emptyList(),
) {
    val eurPerGProtein: Double?
        get() {
            val protein = proteinG
            val cost = eur
            if (cost == null || protein == null || protein <= 0.0) return null
            return cost / protein
        }
}
