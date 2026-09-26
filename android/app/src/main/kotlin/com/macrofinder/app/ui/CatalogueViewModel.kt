package com.macrofinder.app.ui

import android.app.Application
import android.database.sqlite.SQLiteDatabase
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.macrofinder.app.data.catalogue.AndroidSqlRunner
import com.macrofinder.app.data.catalogue.CatalogueReader
import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.DealQuery
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.data.catalogue.DealWindow
import com.macrofinder.app.data.catalogue.ProductDetail
import com.macrofinder.app.data.catalogue.RankedDeal
import com.macrofinder.app.data.catalogue.SearchIndex
import com.macrofinder.app.data.catalogue.Shelf
import com.macrofinder.app.data.catalogue.selectDeals
import com.macrofinder.app.data.following.FollowingStore
import com.macrofinder.app.data.sync.CatalogueStore
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class CatalogueState(
    val ready: Boolean = false,
    /** True once a synced catalogue is on disk. Until then deals come from latest.json. */
    val installed: Boolean = false,
    val version: String? = null,
    val deals: List<Deal> = emptyList(),
    val shelves: List<Shelf> = emptyList(),
    val bulkCutoff: Double? = null,
    val productCount: Int = 0,
    val searchReady: Boolean = false,
)

/**
 * The synced catalogue, as the screens see it. Milestones 23 to 26.
 *
 * Deals are loaded once per sync and then filtered and sorted in memory
 * (`selectDeals`), which is why a tap on a sort is instant. The query lives
 * in [SavedStateHandle], so rotation and process death keep it.
 */
class CatalogueViewModel(
    app: Application,
    private val saved: SavedStateHandle,
) : AndroidViewModel(app) {

    private val store = CatalogueStore(app)
    private val following = FollowingStore(app)
    private var db: SQLiteDatabase? = null

    private val _state = MutableStateFlow(CatalogueState())
    val state: StateFlow<CatalogueState> = _state.asStateFlow()

    private var fallback: List<Deal> = emptyList()

    private val _query = MutableStateFlow(restoreQuery())
    val query: StateFlow<DealQuery> = _query.asStateFlow()

    val followed: StateFlow<Set<String>> =
        following.followed.stateIn(viewModelScope, SharingStarted.Eagerly, emptySet())

    private val _searchText = MutableStateFlow(saved.get<String>("search") ?: "")
    val searchText: StateFlow<String> = _searchText.asStateFlow()
    private val _searchResults = MutableStateFlow<List<Deal>>(emptyList())
    val searchResults: StateFlow<List<Deal>> = _searchResults.asStateFlow()
    private var searchJob: Job? = null

    private val _detail = MutableStateFlow<ProductDetail?>(null)
    val detail: StateFlow<ProductDetail?> = _detail.asStateFlow()

    private val _followedDeals = MutableStateFlow<List<Deal>>(emptyList())
    val followedDeals: StateFlow<List<Deal>> = _followedDeals.asStateFlow()

    init {
        reload()
        viewModelScope.launch { followed.collect { refreshFollowed(it) } }
    }

    fun today(): String = LocalDate.now().toString()

    // -- loading -------------------------------------------------------------

    /** Re-read the catalogue if the version on disk changed. Cheap otherwise. */
    private var loadJob: Job? = null

    fun reload(force: Boolean = false) {
        val previous = loadJob
        loadJob = viewModelScope.launch {
            previous?.join()
            // The index build holds a write lock; reading the version during it
            // can fail with SQLITE_BUSY and look like "no catalogue".
            indexJob?.join()
            val next = withContext(Dispatchers.IO) { load(force) } ?: return@launch
            // The fallback may have arrived while this load ran; don't let a
            // stale empty list overwrite it.
            _state.value = if (next.installed) next else next.copy(deals = fallback)
            if (next.installed && !next.searchReady) buildIndex()
            refreshFollowed(followed.value)
            if (_searchText.value.isNotBlank()) search(_searchText.value)
        }
    }

    private fun load(force: Boolean): CatalogueState? {
        val version = store.localVersion()
        if (!force && _state.value.ready && version == _state.value.version) return null
        if (version == null) {
            // A file that is there but can't be read right now (locked, mid
            // install) never downgrades a catalogue that already loaded.
            if (store.exists() && _state.value.installed) return null
            return CatalogueState(ready = true, installed = false, deals = fallback)
        }
        db?.close()
        val handle = runCatching { store.open() }.getOrNull()
            ?: return CatalogueState(ready = true, installed = false, deals = fallback)
        db = handle
        val runner = AndroidSqlRunner(handle)
        val reader = CatalogueReader(runner)
        return runCatching {
            CatalogueState(
                ready = true,
                installed = true,
                version = version,
                deals = reader.deals(),
                shelves = reader.shelves(),
                bulkCutoff = reader.bulkCutoff(),
                productCount = runner.query("SELECT count(*) AS n FROM products") {
                    (it.long("n") ?: 0L).toInt()
                }.first(),
                searchReady = SearchIndex.exists(runner),
            )
        }.getOrElse { e ->
            Log.w("MacroFinder", "catalogue unreadable, using the short list", e)
            CatalogueState(ready = true, installed = false, deals = fallback)
        }
    }

    private var indexJob: Job? = null

    /**
     * Normally the sync worker builds the search index. If it hasn't yet
     * (first launch after an app update, say), build it here, after the list
     * is already on screen, rather than leave a search box that finds nothing.
     */
    private fun buildIndex() {
        indexJob = viewModelScope.launch {
            withContext(Dispatchers.IO) { runCatching { store.ensureSearchIndex() } }
            _state.value = _state.value.copy(searchReady = true)
        }
    }

    /** latest.json's offers, shown until the catalogue has arrived. */
    fun setFallback(deals: List<Deal>) {
        fallback = deals
        if (!_state.value.installed) _state.value = _state.value.copy(ready = true, deals = deals)
    }

    private fun reader(): CatalogueReader? = db?.let { CatalogueReader(AndroidSqlRunner(it)) }

    // -- the list --------------------------------------------------------------

    fun visibleDeals(): List<RankedDeal> {
        val s = _state.value
        return selectDeals(s.deals, _query.value, today(), s.bulkCutoff)
    }

    fun setQuery(q: DealQuery) {
        _query.value = q
        saved["window"] = q.window.name
        saved["chains"] = q.chains.joinToString(",")
        saved["shelf"] = q.shelf
        saved["bucket"] = q.bucket
        saved["foodOnly"] = q.foodOnly
        saved["personal"] = q.includePersonal
        saved["sort"] = q.sort.name
    }

    private fun restoreQuery(): DealQuery = DealQuery(
        window = saved.get<String>("window")?.let { runCatching { DealWindow.valueOf(it) }.getOrNull() }
            ?: DealWindow.ACTIVE,
        chains = saved.get<String>("chains")?.split(',')?.filter { it.isNotBlank() }?.toSet().orEmpty(),
        shelf = saved.get<String>("shelf"),
        bucket = saved.get<String>("bucket"),
        foodOnly = saved.get<Boolean>("foodOnly") ?: true,
        includePersonal = saved.get<Boolean>("personal") ?: false,
        sort = saved.get<String>("sort")?.let { runCatching { DealSort.valueOf(it) }.getOrNull() }
            ?: DealSort.PROTEIN_PER_EURO,
    )

    // -- search ----------------------------------------------------------------

    fun search(text: String) {
        _searchText.value = text
        saved["search"] = text
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(120)
            loadJob?.join()
            indexJob?.join()
            val fts = SearchIndex.query(text)
            _searchResults.value = if (fts == null) emptyList() else withContext(Dispatchers.IO) {
                reader()?.let { r -> runCatching { r.search(fts) }.getOrDefault(emptyList()) }
                    ?: searchFallback(text)
            }
        }
    }

    /** Before the catalogue arrives, search the fallback list by name. */
    private fun searchFallback(text: String): List<Deal> {
        val words = SearchIndex.fold(text).split(' ').filter { it.isNotBlank() }
        return fallback.filter { d -> words.all { SearchIndex.fold(d.name).contains(it) } }.take(60)
    }

    // -- detail ----------------------------------------------------------------

    fun openDetail(id: String) {
        _detail.value = null
        viewModelScope.launch {
            // A tap during the first load must wait for the catalogue, not
            // fall back to the thinner latest.json row.
            loadJob?.join()
            _detail.value = withContext(Dispatchers.IO) {
                reader()?.let { runCatching { it.detail(id) }.getOrNull() }
                    ?: (fallback + _searchResults.value).firstOrNull { it.id == id }
                        ?.let { ProductDetail(it, null, emptyList(), false, null) }
            }
        }
    }

    // -- following -------------------------------------------------------------

    fun toggleFollow(id: String) {
        viewModelScope.launch { following.toggle(id) }
    }

    private suspend fun refreshFollowed(ids: Set<String>) {
        _followedDeals.value = withContext(Dispatchers.IO) {
            val r = reader()
            val today = today()
            if (r == null) {
                fallback.filter { it.id in ids }
            } else {
                // One row per product: its running promo if any, else the shelf price.
                val rows = runCatching { r.dealsFor(ids) }.getOrDefault(emptyList())
                rows.groupBy { it.id }.values.map { lanes ->
                    lanes.firstOrNull { it.lane != "shelf" && it.isActiveOn(today) }
                        ?: lanes.firstOrNull { it.lane == "shelf" }
                        ?: lanes.first()
                }
            }
        }.sortedWith(compareBy({ it.lane == "shelf" }, { it.name.lowercase() }))
    }

    override fun onCleared() {
        db?.close()
    }
}
