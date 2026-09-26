package com.macrofinder.app.data.catalogue

/**
 * Reads the synced catalogue. The SQL lives here; running it lives behind
 * [SqlRunner], so the same queries run against Android's SQLite in the app and
 * against sqlite-jdbc in the JVM tests, on the real published schema.
 */
interface Row {
    fun string(column: String): String?
    fun double(column: String): Double?
    fun long(column: String): Long?
}

interface SqlRunner {
    fun <T> query(sql: String, args: List<Any?> = emptyList(), map: (Row) -> T): List<T>
    fun exec(sql: String, args: List<Any?> = emptyList())
    /** One statement, many rows. Much faster than [exec] in a loop on Android. */
    fun execBatch(sql: String, rows: List<List<Any?>>) = rows.forEach { exec(sql, it) }
    fun <T> transaction(block: () -> T): T
}

data class Shelf(val key: String, val label: String)

data class PricePoint(val week: String, val price: Double)

data class ProductDetail(
    val deal: Deal,
    /** The plain shelf price, when there is one, next to the promo. */
    val shelfLanePrice: Double?,
    val history: List<PricePoint>,
    val kcalIsDerived: Boolean,
    val foodTypeName: String?,
    /** complete / incomplete / blend (PLAN-V2 section 4.3), or null. */
    val proteinQuality: String? = null,
    /** Milestone 31: the same food, cheaper per 100 g protein right now. */
    val alternatives: List<Alternative> = emptyList(),
    /** What 100 g protein costs today (running promo, else shelf), for price targets. */
    val todayPer100gProtein: Double? = null,
)

class CatalogueReader(private val db: SqlRunner) {

    fun shelves(): List<Shelf> =
        db.query("SELECT key, label FROM shelves ORDER BY sort_order") {
            Shelf(it.string("key")!!, it.string("label")!!)
        }

    fun meta(key: String): String? =
        db.query("SELECT value FROM meta WHERE key = ?", listOf(key)) { it.string("value") }
            .firstOrNull()

    fun bulkCutoff(): Double? = meta("bulk_eur_per_1000kcal")?.toDoubleOrNull()

    /** Every promo and upcoming row. The window is decided later, by date. */
    fun deals(): List<Deal> = db.query("$DEAL_SELECT WHERE pr.lane != 'shelf'", emptyList(), ::deal)

    /**
     * [today] turns on the cheaper-alternatives lookup (milestone 31), limited
     * to [chains] when that isn't empty.
     */
    fun detail(productId: String, today: String? = null, chains: Set<String> = emptySet()): ProductDetail? {
        val lanes = db.query("$DEAL_SELECT WHERE p.id = ?", listOf(productId), ::deal)
        if (lanes.isEmpty()) {
            // A product with no price row at all still has a detail page.
            val bare = db.query("$PRODUCT_ONLY_SELECT WHERE p.id = ?", listOf(productId), ::deal)
            return bare.firstOrNull()?.let {
                val ft = foodType(it)
                ProductDetail(it, null, emptyList(), false, ft?.first, ft?.second)
            }
        }
        val promo = lanes.firstOrNull { it.lane == "promo" }
            ?: lanes.firstOrNull { it.lane == "upcoming" }
        val shelf = lanes.firstOrNull { it.lane == "shelf" }
        val main = promo ?: shelf ?: lanes.first()
        val history = db.query(
            "SELECT week, price FROM price_history WHERE product_id = ? ORDER BY week",
            listOf(productId),
        ) { PricePoint(it.string("week")!!, it.double("price")!!) }
        val derived = db.query(
            "SELECT kcal_is_derived FROM product_macros WHERE product_id = ?", listOf(productId),
        ) { (it.long("kcal_is_derived") ?: 0L) != 0L }.firstOrNull() ?: false
        val ft = foodType(main)
        val now = today?.let { currentLane(lanes, it) }
        val alternatives = if (today == null || main.foodType == null) emptyList() else
            cheaperAlternatives(now, sameFoodType(main.foodType, productId), today, chains)
        return ProductDetail(main, shelf?.price, history, derived, ft?.first, ft?.second, alternatives,
            now?.eurPer100gProtein)
    }

    /** Every promo and shelf row of the other products with this food type. */
    fun sameFoodType(foodType: String, excludeId: String): List<Deal> = db.query(
        "$DEAL_SELECT WHERE p.food_type = ? AND p.id != ? AND pr.lane IN ('promo', 'shelf')",
        listOf(foodType, excludeId), ::deal,
    )

    /** The food type's name and protein quality, if the product has a food type. */
    private fun foodType(deal: Deal): Pair<String?, String?>? = deal.foodType?.let { key ->
        db.query("SELECT name_nl, protein_quality FROM food_types WHERE key = ?", listOf(key)) {
            it.string("name_nl") to it.string("protein_quality")
        }.firstOrNull()
    }

    /**
     * Search results: products matching [ftsQuery] in the on-device index,
     * each with its best current price (promo if running, else shelf).
     */
    fun search(ftsQuery: String, limit: Int = 60): List<Deal> {
        if (ftsQuery.isBlank()) return emptyList()
        return db.query(
            """
            SELECT $PRODUCT_COLUMNS, $PRICE_COLUMNS
            FROM ${SearchIndex.TABLE} s
            JOIN products p ON p.id = s.id
            LEFT JOIN prices pr ON pr.product_id = p.id AND pr.lane = (
                SELECT x.lane FROM prices x WHERE x.product_id = p.id
                ORDER BY CASE x.lane WHEN 'promo' THEN 0 WHEN 'shelf' THEN 1 ELSE 2 END
                LIMIT 1)
            WHERE s.${SearchIndex.TABLE} MATCH ?
            ORDER BY p.protein_per_100g IS NULL, pr.eur_per_100g_protein IS NULL,
                     pr.eur_per_100g_protein, p.name
            LIMIT ?
            """.trimIndent(),
            listOf(ftsQuery, limit),
            ::deal,
        )
    }

    fun dealsFor(ids: Collection<String>): List<Deal> {
        if (ids.isEmpty()) return emptyList()
        val marks = ids.joinToString(",") { "?" }
        return db.query("$DEAL_SELECT WHERE p.id IN ($marks)", ids.toList(), ::deal)
    }

    companion object {
        private const val PRODUCT_COLUMNS = """
            p.id, p.chain, p.name, p.brand, p.raw_unit_text, p.image_url, p.shelf, p.food_type,
            p.mass_g, p.protein_per_100g, p.kcal_per_100g, p.carbs_per_100g, p.fat_per_100g,
            p.macro_source, p.macro_confidence, p.protein_per_100kcal, p.buckets,
            p.promo_cycle_days, p.last_promo_start"""

        private const val PRICE_COLUMNS = """
            pr.lane, pr.effective_unit_price, pr.shelf_price, pr.promo_text,
            pr.required_quantity, pr.is_personal_offer, pr.valid_from, pr.valid_to,
            pr.eur_per_100g_protein, pr.eur_per_1000kcal, pr.discount_pct,
            pr.waste_adjusted_eur_per_100g_protein, pr.realistically_consumable,
            pr.perishable, pr.cheapest_in_weeks, pr.reference_inflated"""

        val DEAL_SELECT = """
            SELECT $PRODUCT_COLUMNS, $PRICE_COLUMNS
            FROM products p JOIN prices pr ON pr.product_id = p.id""".trimIndent()

        private val PRODUCT_ONLY_SELECT = """
            SELECT $PRODUCT_COLUMNS, 'shelf' AS lane, NULL AS effective_unit_price,
                   NULL AS shelf_price, NULL AS promo_text, 1 AS required_quantity,
                   0 AS is_personal_offer, NULL AS valid_from, NULL AS valid_to,
                   NULL AS eur_per_100g_protein, NULL AS eur_per_1000kcal, NULL AS discount_pct,
                   NULL AS waste_adjusted_eur_per_100g_protein, NULL AS realistically_consumable,
                   NULL AS perishable, NULL AS cheapest_in_weeks, NULL AS reference_inflated
            FROM products p""".trimIndent()

        fun deal(r: Row) = Deal(
            id = r.string("id")!!,
            chain = r.string("chain")!!,
            name = r.string("name")!!,
            brand = r.string("brand"),
            unitText = r.string("raw_unit_text"),
            imageUrl = r.string("image_url"),
            shelf = r.string("shelf"),
            foodType = r.string("food_type"),
            massG = r.double("mass_g"),
            proteinPer100g = r.double("protein_per_100g"),
            kcalPer100g = r.double("kcal_per_100g"),
            carbsPer100g = r.double("carbs_per_100g"),
            fatPer100g = r.double("fat_per_100g"),
            macroSource = r.string("macro_source"),
            macroConfidence = r.string("macro_confidence"),
            proteinPer100kcal = r.double("protein_per_100kcal"),
            buckets = r.string("buckets").orEmpty().split(',').filter { it.isNotBlank() }.toSet(),
            lane = r.string("lane") ?: "shelf",
            price = r.double("effective_unit_price"),
            shelfPrice = r.double("shelf_price"),
            promoText = r.string("promo_text"),
            requiredQuantity = (r.long("required_quantity") ?: 1L).toInt(),
            isPersonal = (r.long("is_personal_offer") ?: 0L) != 0L,
            validFrom = r.string("valid_from"),
            validTo = r.string("valid_to"),
            eurPer100gProtein = r.double("eur_per_100g_protein"),
            eurPer1000kcal = r.double("eur_per_1000kcal"),
            discountPct = r.double("discount_pct"),
            wasteAdjustedEurPer100gProtein = r.double("waste_adjusted_eur_per_100g_protein"),
            realisticallyConsumable = r.long("realistically_consumable")?.toInt(),
            perishable = (r.long("perishable") ?: 0L) != 0L,
            cheapestInWeeks = r.long("cheapest_in_weeks")?.toInt(),
            referenceInflated = r.long("reference_inflated")?.let { it != 0L },
            promoCycleDays = r.long("promo_cycle_days")?.toInt(),
            lastPromoStart = r.string("last_promo_start"),
        )
    }
}
