package com.macrofinder.app.data

import kotlinx.serialization.Serializable

/**
 * Mirrors `src/bonusrank/export.py`'s JSON shape exactly (field for field), on
 * the Python side of this repo. Keep the two in sync by hand - there is no
 * shared schema file, just this comment pointing at the source of truth.
 *
 * Field names are snake_case here on purpose, matching the JSON directly
 * (decoded with [MacroFinderJson], which is configured to expect that), so a
 * diff between this file and export.py's dict keys is a literal text diff.
 */
@Serializable
data class ExportSnapshot(
    val generated_at: String,
    val schema_version: Int,
    val chains: Map<String, ChainData>,
)

@Serializable
data class ChainData(
    val archetypes: List<ArchetypeEntry> = emptyList(),
    val offers: List<OfferEntry> = emptyList(),
)

@Serializable
data class OfferEntry(
    val sku: String,
    val name: String,
    val brand: String? = null,
    val food_type: String? = null,
    val price: PriceInfo,
    val macros_per_100g: Macros,
    val macros_need_marking: Boolean,
    val kcal_is_derived: Boolean,
    val eur_per_100g_protein: Double? = null,
    val waste_adjusted_eur_per_100g_protein: Double? = null,
    val perishable: Boolean,
    val realistically_consumable_packs: Int? = null,
    val is_personal_offer: Boolean,
    val valid_from: String? = null,
    val valid_to: String? = null,
)

@Serializable
data class PriceInfo(
    val unit_price_eur: Double? = null,
    val shelf_price_eur: Double? = null,
    val required_quantity: Int,
    val total_outlay_eur: Double? = null,
    val promo_mechanic: String,
    // The human-readable "why it's cheaper" line from the store itself.
    val promo_text: String? = null,
    val is_promo: Boolean,
    val cheapest_in_weeks: Int? = null,
)

@Serializable
data class Macros(
    val protein_g: Double? = null,
    val carbs_g: Double? = null,
    val fat_g: Double? = null,
    val kcal: Double? = null,
)

@Serializable
data class ArchetypeEntry(
    val key: String,
    val name: String,
    // "meal" | "snack" | "drink" - see CLAUDE.md milestone 9 in the Python repo.
    val meal_kind: String,
    val meal_slots: List<String> = emptyList(),
    val serving_g: Double? = null,
    val target_protein_g: Double? = null,
    val ready_made: ReadyMade? = null,
    val compositions: List<Composition> = emptyList(),
    val optimised: OptimisedPlan? = null,
    val verdict: Verdict,
)

@Serializable
data class ReadyMade(
    val sku: String,
    val name: String,
    val price_eur: Double? = null,
    val protein_g: Double? = null,
    val kcal: Double? = null,
    val eur_per_g_protein: Double? = null,
    val matched_by: String,
    val promo_text: String? = null,
    val required_quantity: Int,
    val is_personal_offer: Boolean,
)

@Serializable
data class Composition(
    val name: String,
    val effort_minutes: Int? = null,
    val equipment: String? = null,
    val similarity_confidence: String? = null,
    val taste_delta_note: String,
    val texture_delta_note: String? = null,
    val price_eur: Double? = null,
    val protein_g: Double? = null,
    val kcal: Double? = null,
    val eur_per_g_protein: Double? = null,
    val unpriced_food_types: List<String> = emptyList(),
    val items: List<Item> = emptyList(),
)

@Serializable
data class Item(
    val food_type: String,
    val name: String,
    val grams: Double,
    val price_eur: Double? = null,
    val protein_g: Double? = null,
    val kcal: Double? = null,
    val is_pantry: Boolean,
)

/** Either a solved mix, or an honest, explained rejection - never both null. */
@Serializable
data class OptimisedPlan(
    val rejected: Boolean,
    val reason: String? = null,
    val price_eur: Double? = null,
    val protein_g: Double? = null,
    val carbs_g: Double? = null,
    val fat_g: Double? = null,
    val kcal: Double? = null,
    val items: List<Item> = emptyList(),
)

@Serializable
data class Verdict(
    val winner: String,
    val cheaper_pct: Double? = null,
    val protein_delta_g: Double? = null,
    val text: String,
)
