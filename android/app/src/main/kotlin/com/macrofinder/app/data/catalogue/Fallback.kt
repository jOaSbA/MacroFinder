package com.macrofinder.app.data.catalogue

import com.macrofinder.app.data.ExportSnapshot
import com.macrofinder.app.data.OfferEntry

/**
 * `latest.json`'s ranked offers as [Deal]s, so the list works before the
 * catalogue has synced (first launch on mobile data, or a failed download).
 * Smaller and without images, but the same rows, the same sort and the same
 * rules about unknowns.
 */
fun fallbackDeals(snapshot: ExportSnapshot): List<Deal> =
    snapshot.chains.flatMap { (chain, data) -> data.offers.map { it.toDeal(chain) } }

fun OfferEntry.toDeal(chain: String): Deal {
    val unit = price.unit_price_eur
    val shelf = price.shelf_price_eur
    val m = macros_per_100g
    return Deal(
        id = "$chain:$sku",
        chain = chain,
        name = name,
        brand = brand,
        foodType = food_type,
        proteinPer100g = m.protein_g,
        kcalPer100g = m.kcal,
        carbsPer100g = m.carbs_g,
        fatPer100g = m.fat_g,
        macroSource = if (m.protein_g != null) (if (macros_need_marking) "manual" else "label") else null,
        macroConfidence = if (m.protein_g != null) (if (macros_need_marking) "seed" else "high") else null,
        proteinPer100kcal = if (m.protein_g != null && m.kcal != null && m.kcal > 0) m.protein_g / m.kcal * 100 else null,
        lane = if (price.is_promo) "promo" else "shelf",
        price = unit,
        shelfPrice = shelf,
        promoText = price.promo_text,
        requiredQuantity = price.required_quantity,
        isPersonal = is_personal_offer,
        validFrom = valid_from,
        validTo = valid_to,
        eurPer100gProtein = eur_per_100g_protein,
        discountPct = if (unit != null && shelf != null && shelf > unit) (1 - unit / shelf) * 100 else null,
        wasteAdjustedEurPer100gProtein = waste_adjusted_eur_per_100g_protein,
        realisticallyConsumable = realistically_consumable_packs,
        perishable = perishable,
        cheapestInWeeks = price.cheapest_in_weeks,
    )
}
