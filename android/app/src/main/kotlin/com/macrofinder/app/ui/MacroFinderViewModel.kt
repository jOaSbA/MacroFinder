package com.macrofinder.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.macrofinder.app.BuildConfig
import com.macrofinder.app.data.ArchetypeEntry
import com.macrofinder.app.data.DataRepository
import com.macrofinder.app.data.FilterState
import com.macrofinder.app.data.FoodTab
import com.macrofinder.app.data.FoodTypeEntry
import com.macrofinder.app.data.MealContext
import com.macrofinder.app.data.MealLine
import com.macrofinder.app.data.MealTotals
import com.macrofinder.app.data.OfferEntry
import com.macrofinder.app.data.Quantity
import com.macrofinder.app.data.QuantityUnit
import com.macrofinder.app.data.RuleIssue
import com.macrofinder.app.data.SavedMeal
import com.macrofinder.app.data.SlotCandidate
import com.macrofinder.app.data.SnapshotResult
import com.macrofinder.app.data.TemplateEntry
import com.macrofinder.app.data.TemplateSlot
import com.macrofinder.app.data.archetypesForTab
import com.macrofinder.app.data.checkCombination
import com.macrofinder.app.data.linesFromSelections
import com.macrofinder.app.data.offersForTab
import com.macrofinder.app.data.priceMeal
import com.macrofinder.app.data.unfilledRequiredSlots
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Which screen is showing. A sealed class in state rather than a navigation
 * library: the app has three destinations, and this one is testable on the JVM
 * where a NavController is not.
 */
sealed interface Screen {
    data object Tabs : Screen
    data class Customise(val templateKey: String) : Screen
    data object SavedMeals : Screen
}

data class UiState(
    val loading: Boolean = true,
    val error: String? = null,
    val chain: String = "ah",
    val tab: FoodTab = FoodTab.MEALS,
    val screen: Screen = Screen.Tabs,
    val filter: FilterState = FilterState(),
    val archetypes: List<ArchetypeEntry> = emptyList(),
    val offers: List<OfferEntry> = emptyList(),
    val templates: List<TemplateEntry> = emptyList(),
    val foodTypes: List<FoodTypeEntry> = emptyList(),
    /** template key -> slot key -> ranked candidates, for the selected chain. */
    val templatePrices: Map<String, Map<String, List<SlotCandidate>>> = emptyMap(),
    /** Prices and macros for local re-costing. Rebuilt on every refresh. */
    val mealContext: MealContext = MealContext(),
    /** slot key -> chosen food type, for the template currently being built. */
    val selections: Map<String, String> = emptyMap(),
    /** Lines the user added that are not slot picks ("100 g ketchup"). */
    val extras: List<MealLine> = emptyList(),
    val savedMeals: List<SavedMeal> = emptyList(),
)

class MacroFinderViewModel(
    private val repository: DataRepository = DataRepository(BuildConfig.DATA_URL),
) : ViewModel() {

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            when (val result = repository.fetchSnapshot()) {
                is SnapshotResult.Success -> {
                    val snapshot = result.snapshot
                    val chain = _state.value.chain
                    val chainData = snapshot.chains[chain]
                    _state.value = _state.value.copy(
                        loading = false,
                        archetypes = chainData?.archetypes.orEmpty(),
                        offers = chainData?.offers.orEmpty(),
                        templates = snapshot.templates,
                        foodTypes = snapshot.food_types,
                        templatePrices = chainData?.template_prices.orEmpty(),
                        // Rebuilding this is what re-prices every saved meal:
                        // the meals themselves hold no euros, only keys.
                        mealContext = MealContext.from(snapshot, chain),
                    )
                }
                is SnapshotResult.Failure -> {
                    _state.value = _state.value.copy(loading = false, error = result.message)
                }
            }
        }
    }

    // -- navigation --------------------------------------------------------

    fun selectTab(tab: FoodTab) {
        _state.value = _state.value.copy(tab = tab, screen = Screen.Tabs)
    }

    /** Open the customiser on a template, starting from an empty plate. */
    fun customise(templateKey: String) {
        _state.value = _state.value.copy(
            screen = Screen.Customise(templateKey), selections = emptyMap(), extras = emptyList(),
        )
    }

    fun showSavedMeals() {
        _state.value = _state.value.copy(screen = Screen.SavedMeals)
    }

    fun back() {
        _state.value = _state.value.copy(screen = Screen.Tabs)
    }

    fun updateFilter(filter: FilterState) {
        _state.value = _state.value.copy(filter = filter)
    }

    // -- composing a meal --------------------------------------------------

    /** Pick a candidate for a slot, or pass null to clear an optional slot. */
    fun choose(slotKey: String, foodType: String?) {
        val selections = _state.value.selections.toMutableMap()
        if (foodType == null) selections.remove(slotKey) else selections[slotKey] = foodType
        _state.value = _state.value.copy(selections = selections)
    }

    /**
     * Add an extra. Each gets its own id, so "50 g more of the cheese I already
     * picked" is a second line rather than an overwrite of the first.
     */
    fun addExtra(foodType: String, amount: Double, unit: QuantityUnit) {
        val label = _state.value.foodTypes.firstOrNull { it.key == foodType }?.name ?: foodType
        val extra = MealLine(
            id = "extra:${foodType}:${System.nanoTime()}",
            slotKey = null,
            foodType = foodType,
            label = label,
            quantity = Quantity(amount, unit),
        )
        _state.value = _state.value.copy(extras = _state.value.extras + extra)
    }

    fun removeLine(id: String) {
        _state.value = _state.value.copy(extras = _state.value.extras.filterNot { it.id == id })
    }

    /** The current plate: slot picks in template order, then the extras. */
    fun currentLines(): List<MealLine> {
        val template = currentTemplate() ?: return _state.value.extras
        val candidates = _state.value.templatePrices[template.key].orEmpty()
        return linesFromSelections(template, _state.value.selections, candidates) +
            _state.value.extras
    }

    fun currentTemplate(): TemplateEntry? {
        val screen = _state.value.screen
        if (screen !is Screen.Customise) return null
        return _state.value.templates.firstOrNull { it.key == screen.templateKey }
    }

    fun candidatesFor(slot: TemplateSlot): List<SlotCandidate> {
        val template = currentTemplate() ?: return emptyList()
        return _state.value.templatePrices[template.key]?.get(slot.key).orEmpty()
    }

    /** What this plate costs right now, with unknowns named rather than hidden. */
    fun currentTotals(): MealTotals = priceMeal(currentLines(), _state.value.mealContext)

    /** Rules the user should hear about. Empty when the combination is fine. */
    fun currentIssues(): List<RuleIssue> {
        val template = currentTemplate() ?: return emptyList()
        return checkCombination(template, currentLines())
    }

    fun missingSlots(): List<TemplateSlot> {
        val template = currentTemplate() ?: return emptyList()
        return unfilledRequiredSlots(template, currentLines())
    }

    // -- saved meals -------------------------------------------------------

    /**
     * Build a saved meal from the current plate. Keys and quantities only -
     * never a price, so the meal re-costs itself against next week's bonus.
     */
    fun buildSavedMeal(name: String, id: String = "meal:${System.nanoTime()}"): SavedMeal =
        SavedMeal(
            id = id,
            name = name,
            templateKey = (_state.value.screen as? Screen.Customise)?.templateKey,
            lines = currentLines(),
        )

    fun setSavedMeals(meals: List<SavedMeal>) {
        _state.value = _state.value.copy(savedMeals = meals)
    }

    /** Re-cost a saved meal against the CURRENT snapshot, not what it cost when saved. */
    fun totalsFor(meal: SavedMeal): MealTotals = priceMeal(meal.lines, _state.value.mealContext)

    /** Reopen a saved meal in the customiser, with its picks restored. */
    fun openSaved(meal: SavedMeal) {
        val templateKey = meal.templateKey
        _state.value = _state.value.copy(
            screen = if (templateKey != null) Screen.Customise(templateKey) else Screen.Tabs,
            selections = meal.lines
                .filter { it.slotKey != null && it.foodType != null }
                .associate { it.slotKey!! to it.foodType!! },
            extras = meal.lines.filter { it.slotKey == null },
        )
    }

    // -- the browse tabs ---------------------------------------------------

    /** MEALS only - the curated archetypes. Empty on the other three tabs. */
    fun visibleArchetypes(): List<ArchetypeEntry> =
        archetypesForTab(_state.value.archetypes, _state.value.tab)

    /** SNACKS/DRINKS/OTHER - the full ranked offer list for that tab's kind. */
    fun visibleOffers(): List<OfferEntry> {
        val tab = _state.value.tab
        if (tab == FoodTab.MEALS) return emptyList()
        return offersForTab(_state.value.offers, tab, _state.value.filter)
    }
}
