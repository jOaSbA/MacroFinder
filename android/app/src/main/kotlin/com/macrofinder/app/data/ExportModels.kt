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
    /** Milestone 12. Chain-independent, so shipped once rather than per chain. */
    val templates: List<TemplateEntry> = emptyList(),
    /** Every seeded food type, so an arbitrary extra can be priced on-device. */
    val food_types: List<FoodTypeEntry> = emptyList(),
)

@Serializable
data class ChainData(
    val archetypes: List<ArchetypeEntry> = emptyList(),
    val offers: List<OfferEntry> = emptyList(),
    /** template key -> slot key -> that slot's candidates, ranked, at this chain. */
    val template_prices: Map<String, Map<String, List<SlotCandidate>>> = emptyMap(),
    /**
     * food type key -> its cheapest current rate here. Milestone 13: this is
     * what prices an arbitrary extra the user typed in, which by definition is
     * not one of some template slot's candidates. A key that is ABSENT has no
     * known price - absent is the unknown, never a zero rate.
     */
    val food_type_prices: Map<String, FoodTypePriceEntry> = emptyMap(),
)

@Serializable
data class OfferEntry(
    val sku: String,
    val name: String,
    val brand: String? = null,
    val food_type: String? = null,
    // "meal" | "snack" | "drink" | "ingredient" - which tab this belongs in.
    // Null only for an unmatched offer, which the export already excludes.
    val meal_kind: String? = null,
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
    val day_parts: List<String> = emptyList(),
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

// --- meal templates (milestone 12) ------------------------------------------
//
// A template is a shape with holes in it: a pasta, a meat, a sauce. The body
// below is authored in data/seed/templates.yaml and never computed. Prices for
// each slot's candidates arrive separately, per chain, in ChainData.

@Serializable
data class TemplateEntry(
    val key: String,
    val name: String,
    val meal_kind: String,
    val base_prep_minutes: Int? = null,
    val slots: List<TemplateSlot> = emptyList(),
    val rules: List<TemplateRule> = emptyList(),
)

@Serializable
data class TemplateSlot(
    val key: String,
    val name: String,
    val required: Boolean,
    val default_grams: Double,
    /** Food type keys. The priced, ranked versions live in `template_prices`. */
    val candidates: List<String> = emptyList(),
)

/**
 * An authored judgement about whether a combination is a real dish.
 *
 * `severity` is the difference between an unfinished dish ("incomplete") and
 * one that is actually wrong ("wrong"), with "note" for an observation that
 * blocks nothing. They must not render the same way. A rule never blocks a
 * choice - it explains, using [note], which is the only text the user sees.
 */
@Serializable
data class TemplateRule(
    val kind: String,
    val `when`: Predicate,
    val requires: List<Predicate> = emptyList(),
    val min_satisfied: Int = 1,
    val severity: String,
    val note: String,
)

/** Names a slot, a set of food types, or both. An empty predicate is invalid. */
@Serializable
data class Predicate(
    val slot: String? = null,
    val food_types: List<String> = emptyList(),
)

@Serializable
data class SlotCandidate(
    val food_type: String,
    val name: String,
    val grams: Double,
    val price_eur: Double? = null,
    /**
     * The per-kilo rate, kept as its own field rather than divided back out of
     * [price_eur]. Local re-pricing multiplies this when the user changes the
     * quantity, and a null rate must stay null through that - never 0.0.
     */
    val eur_per_kg: Double? = null,
    val protein_g: Double? = null,
    val kcal: Double? = null,
    val carbs_g: Double? = null,
    val fat_g: Double? = null,
    val eur_per_g_protein: Double? = null,
    val is_pantry: Boolean = false,
    /**
     * BRIEF section 9 rule 1: a macro figure from the seed may never be shown
     * bare. Defaults to TRUE, not false: an older snapshot that predates the
     * field carries seed estimates, so the safe reading of a missing value is
     * "assume it needs marking". Defaulting the other way would silently
     * render guesses as facts on exactly the data this exists to flag.
     */
    val macros_need_marking: Boolean = true,
    val promo_text: String? = null,
    /** Copy rule 3: a 2-for deal means two of them in the fridge. Show it. */
    val required_quantity: Int? = null,
    val is_personal_offer: Boolean = false,
    val sku: String? = null,
)

@Serializable
data class FoodTypeEntry(
    val key: String,
    val name: String,
    val meal_kind: String? = null,
    /** "4 boiled eggs" is this times four. Null where a unit makes no sense. */
    val g_per_unit: Double? = null,
    val macros_per_100g: Macros = Macros(),
    /**
     * BRIEF section 9 rule 1: a macro figure from the seed may never be shown
     * bare. Defaults to TRUE, not false: an older snapshot that predates the
     * field carries seed estimates, so the safe reading of a missing value is
     * "assume it needs marking". Defaulting the other way would silently
     * render guesses as facts on exactly the data this exists to flag.
     */
    val macros_need_marking: Boolean = true,
)

@Serializable
data class FoodTypePriceEntry(
    val eur_per_kg: Double,
    val sku: String? = null,
    val product_name: String? = null,
    val promo_text: String? = null,
    /** Copy rule 3: a 2-for deal means two of them in the fridge. Show it. */
    val required_quantity: Int = 1,
    val is_personal_offer: Boolean = false,
)
