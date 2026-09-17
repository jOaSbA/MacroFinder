package com.macrofinder.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.macrofinder.app.BuildConfig
import com.macrofinder.app.data.ArchetypeEntry
import com.macrofinder.app.data.DataRepository
import com.macrofinder.app.data.FilterState
import com.macrofinder.app.data.FoodTab
import com.macrofinder.app.data.OfferEntry
import com.macrofinder.app.data.SnapshotResult
import com.macrofinder.app.data.archetypesForTab
import com.macrofinder.app.data.filterOffers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class UiState(
    val loading: Boolean = true,
    val error: String? = null,
    val chain: String = "ah",
    val tab: FoodTab = FoodTab.MEALS,
    val filter: FilterState = FilterState(),
    val archetypes: List<ArchetypeEntry> = emptyList(),
    val offers: List<OfferEntry> = emptyList(),
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
                    val chainData = result.snapshot.chains[_state.value.chain]
                    _state.value = _state.value.copy(
                        loading = false,
                        archetypes = chainData?.archetypes.orEmpty(),
                        offers = chainData?.offers.orEmpty(),
                    )
                }
                is SnapshotResult.Failure -> {
                    _state.value = _state.value.copy(loading = false, error = result.message)
                }
            }
        }
    }

    fun selectTab(tab: FoodTab) {
        _state.value = _state.value.copy(tab = tab)
    }

    fun updateFilter(filter: FilterState) {
        _state.value = _state.value.copy(filter = filter)
    }

    fun visibleArchetypes(): List<ArchetypeEntry> =
        archetypesForTab(_state.value.archetypes, _state.value.tab)

    fun visibleOffers(): List<OfferEntry> =
        filterOffers(_state.value.offers, _state.value.filter)
}
