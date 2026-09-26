package com.macrofinder.app.ui

import android.app.Application
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.lifecycle.SavedStateHandle
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.macrofinder.app.data.DataRepository
import com.macrofinder.app.data.SnapshotResult
import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.parseSnapshot
import com.macrofinder.app.data.sync.CatalogueStore
import com.macrofinder.app.ui.screens.CustomiseScreen
import com.macrofinder.app.ui.screens.DealsScreen
import com.macrofinder.app.ui.screens.ProductScreen
import com.macrofinder.app.ui.theme.MacroFinderTheme
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Milestone 29: the three main screens and their state transitions, driven
 * through Compose on a real device. CI runs these on an emulator.
 *
 * No network and no synced catalogue: deals go in through the latest.json
 * fallback path, meals through a fake repository.
 */
@RunWith(AndroidJUnit4::class)
class ScreensTest {

    @get:Rule val compose = createComposeRule()

    private val app = ApplicationProvider.getApplicationContext<Application>()
    private val today = java.time.LocalDate.now()

    @Before
    fun noCatalogue() = CatalogueStore(app).clear()

    private fun deal(id: String, name: String, perProtein: Double?, discount: Double?, chain: String = "ah") =
        Deal(
            id = id, chain = chain, name = name, lane = "promo", price = 1.0, shelfPrice = 2.0,
            promoText = "1+1 gratis", requiredQuantity = 2,
            validFrom = today.minusDays(1).toString(), validTo = today.plusDays(5).toString(),
            proteinPer100g = perProtein?.let { 10.0 }, eurPer100gProtein = perProtein,
            macroSource = perProtein?.let { "manual" }, macroConfidence = perProtein?.let { "seed" },
            discountPct = discount,
        )

    private fun catalogue(): CatalogueViewModel {
        val vm = CatalogueViewModel(app, SavedStateHandle())
        compose.waitUntil(5_000) { vm.state.value.ready }
        vm.setFallback(listOf(
            deal("ah:1", "Magere kwark", perProtein = 1.0, discount = 10.0),
            deal("ah:2", "Koekenpan", perProtein = null, discount = 60.0),
        ))
        return vm
    }

    @Test
    fun the_list_ranks_by_protein_and_changing_the_sort_changes_the_figure() {
        val vm = catalogue()
        compose.setContent {
            MacroFinderTheme { DealsScreen(vm, CatalogueSyncState(), {}, {}, {}) }
        }
        compose.onNodeWithText("≈ €1,00 per 100 g eiwit").assertIsDisplayed()
        compose.onNodeWithText("eiwit onbekend").assertIsDisplayed()

        compose.onNodeWithText("Korting").performClick()
        compose.onNodeWithText("60% korting").assertIsDisplayed()
    }

    @Test
    fun filtering_to_a_chain_with_nothing_shows_an_instruction_not_a_blank() {
        val vm = catalogue()
        compose.setContent {
            MacroFinderTheme { DealsScreen(vm, CatalogueSyncState(), {}, {}, {}) }
        }
        compose.onNodeWithText("Jumbo").performClick()
        compose.onNodeWithText("Niets dat hier past").assertIsDisplayed()
        compose.onNodeWithText("Filters wissen").performClick()
        compose.onNodeWithText("Magere kwark").assertIsDisplayed()
    }

    @Test
    fun the_detail_marks_estimated_macros_and_following_toggles() {
        val vm = catalogue()
        vm.openDetail("ah:1")
        compose.setContent {
            MacroFinderTheme { ProductScreen(vm, onBack = {}, onFollow = { id, _ -> vm.toggleFollow(id) }) }
        }
        compose.waitUntil(5_000) { vm.detail.value != null }
        compose.onNodeWithText("≈ Geschat", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Je betaalt €2,00 voor 2 stuks.").assertIsDisplayed()

        compose.onNodeWithText("Volg").performClick()
        compose.waitUntil(5_000) { "ah:1" in vm.followed.value }
        compose.onNodeWithText("Gevolgd ✓").assertIsDisplayed()
        vm.toggleFollow("ah:1")   // leave the device as we found it
    }

    @Test
    fun picking_a_candidate_prices_the_meal() {
        val meals = MacroFinderViewModel(FakeRepository())
        compose.waitUntil(5_000) { !meals.state.value.loading }
        meals.customise("pasta")
        compose.setContent {
            MacroFinderTheme { CustomiseScreen(meals, onBack = {}, onSave = {}) }
        }
        compose.onNodeWithText("Nog kiezen: soort pasta").assertIsDisplayed()

        compose.onNodeWithText("pasta (droog)").performClick()
        compose.onNodeWithText("€0,20").assertExists()
    }

    private class FakeRepository : DataRepository("http://unused") {
        override suspend fun fetchSnapshot() = SnapshotResult.Success(parseSnapshot(SNAPSHOT))
    }

    companion object {
        val SNAPSHOT = """
        {"generated_at":"2026-09-26T06:00:00","schema_version":2,
         "chains":{"ah":{
           "template_prices":{"pasta":{"pasta":[
             {"food_type":"pasta_droog","name":"pasta (droog)","grams":100,
              "price_eur":0.2,"eur_per_kg":2.0,"protein_g":12}]}},
           "food_type_prices":{"pasta_droog":{"eur_per_kg":2.0}}}},
         "templates":[{"key":"pasta","name":"Pasta","meal_kind":"meal",
           "slots":[{"key":"pasta","name":"Soort pasta","required":true,
                     "default_grams":100,"candidates":["pasta_droog"]}]}],
         "food_types":[{"key":"pasta_droog","name":"pasta (droog)",
           "macros_per_100g":{"protein_g":12,"kcal":350,"carbs_g":70,"fat_g":2}}]}
        """.trimIndent()
    }
}
