package com.macrofinder.app.data

/**
 * Costing a composed meal on the phone. Milestone 13.
 *
 * This is the only arithmetic the app does that Python does not. It exists
 * because the user changes a quantity or adds an extra and expects the total to
 * move immediately, not after the next twice-daily refresh.
 *
 * It re-prices; it does not re-rank. The per-kilo rates it multiplies come
 * straight from the export (`food_type_prices`), which `prices.py` produced -
 * so there is still exactly one implementation of "what does a kilo of this
 * cost", and it is the tested one.
 */

/** What the app knows about food, assembled once from a decoded snapshot. */
data class MealContext(
    /** food type key -> its macros and unit mass. */
    val foodTypes: Map<String, FoodTypeEntry> = emptyMap(),
    /** food type key -> the cheapest current rate at the selected chain. */
    val prices: Map<String, FoodTypePriceEntry> = emptyMap(),
) {
    companion object {
        fun from(snapshot: ExportSnapshot, chain: String): MealContext = MealContext(
            foodTypes = snapshot.food_types.associateBy { it.key },
            prices = snapshot.chains[chain]?.food_type_prices.orEmpty(),
        )
    }
}

/**
 * Resolve a line's mass in grams, or null when it cannot be known.
 *
 * A UNITS quantity needs the food type's `g_per_unit`. Without one there is no
 * honest conversion, so the answer is null and every figure derived from it is
 * null too - never a silent fallback of one gram per unit.
 */
fun gramsOf(line: MealLine, context: MealContext): Double? = when (line.quantity.unit) {
    QuantityUnit.GRAMS -> line.quantity.amount
    QuantityUnit.UNITS -> {
        val perUnit = line.foodType?.let { context.foodTypes[it]?.g_per_unit }
        if (perUnit == null) null else line.quantity.amount * perUnit
    }
}

/** Cost and macros for one line. Any unknown input yields a null output. */
fun priceLine(line: MealLine, context: MealContext): PricedLine {
    val grams = gramsOf(line, context)
    val food = line.foodType?.let { context.foodTypes[it] }
    val rate = line.foodType?.let { context.prices[it]?.eur_per_kg }

    val eur = if (grams == null || rate == null) null else rate * grams / 1000.0
    val macros = food?.macros_per_100g

    return PricedLine(
        line = line,
        grams = grams,
        eur = eur,
        proteinG = perServing(macros?.protein_g, grams),
        kcal = perServing(macros?.kcal, grams),
        carbsG = perServing(macros?.carbs_g, grams),
        fatG = perServing(macros?.fat_g, grams),
        // An unidentified line cannot vouch for its own macros, so the absence
        // of a food type reads as "needs marking" rather than as "fine".
        macrosNeedMarking = food?.macros_need_marking ?: true,
    )
}

/**
 * Cost a whole meal.
 *
 * Both poison rules live here, and both name the line that caused them. See
 * [MealTotals] for why they are two rules and not one.
 */
fun priceMeal(lines: List<MealLine>, context: MealContext): MealTotals {
    val priced = lines.map { priceLine(it, context) }

    val unpriced = priced.filter { it.eur == null }.map { it.line.label }
    // A line is macro-unknown if ANY of the four figures is missing. Treating
    // "protein known, fat unknown" as fully known would produce a fat total
    // that quietly excludes one ingredient.
    val unknownMacros = priced
        .filter { it.proteinG == null || it.kcal == null || it.carbsG == null || it.fatG == null }
        .map { it.line.label }

    return MealTotals(
        lines = priced,
        eur = if (unpriced.isEmpty()) priced.sumOf { it.eur ?: 0.0 } else null,
        proteinG = sumOrNull(priced.map { it.proteinG }),
        kcal = sumOrNull(priced.map { it.kcal }),
        carbsG = sumOrNull(priced.map { it.carbsG }),
        fatG = sumOrNull(priced.map { it.fatG }),
        unpricedLines = unpriced.distinct(),
        unknownMacroLines = unknownMacros.distinct(),
        // Only lines that actually contributed a figure can taint the total.
        // An empty meal has nothing to mark.
        macrosNeedMarking = priced.any { it.proteinG != null && it.macrosNeedMarking },
    )
}

/**
 * Turn the user's slot picks into meal lines.
 *
 * Grams come from the candidate the export already priced, so a freshly opened
 * customiser agrees with the ranked list the user picked from.
 */
fun linesFromSelections(
    template: TemplateEntry,
    selections: Map<String, String>,
    candidates: Map<String, List<SlotCandidate>>,
): List<MealLine> = template.slots.mapNotNull { slot ->
    val foodType = selections[slot.key] ?: return@mapNotNull null
    val candidate = candidates[slot.key]?.firstOrNull { it.food_type == foodType }
    MealLine(
        id = "slot:${slot.key}",
        slotKey = slot.key,
        foodType = foodType,
        label = candidate?.name ?: foodType,
        quantity = Quantity(candidate?.grams ?: slot.default_grams, QuantityUnit.GRAMS),
    )
}

private fun perServing(per100g: Double?, grams: Double?): Double? =
    if (per100g == null || grams == null) null else per100g * grams / 100.0

/** Null if ANY element is null. The app-side twin of `archetypes._sum_or_none`. */
private fun sumOrNull(values: List<Double?>): Double? =
    if (values.any { it == null }) null else values.sumOf { it ?: 0.0 }
