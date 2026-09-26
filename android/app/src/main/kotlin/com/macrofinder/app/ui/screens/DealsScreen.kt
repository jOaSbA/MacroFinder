package com.macrofinder.app.ui.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.pulltorefresh.PullToRefreshContainer
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.input.nestedscroll.nestedScroll
import kotlinx.coroutines.delay
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.Role
import com.macrofinder.app.data.catalogue.Shelf
import com.macrofinder.app.data.settings.Diet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.catalogue.BUCKET_BULK
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.data.catalogue.DealWindow
import com.macrofinder.app.ui.CatalogueSyncState
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.ESTIMATE_MARK
import com.macrofinder.app.ui.components.ChipRow
import com.macrofinder.app.ui.components.DealRow
import com.macrofinder.app.ui.components.EmptyState
import com.macrofinder.app.ui.components.FilterChip
import com.macrofinder.app.ui.components.Hairline
import com.macrofinder.app.ui.components.SyncBanner
import com.macrofinder.app.ui.components.TextAction
import com.macrofinder.app.ui.components.TextTabs
import com.macrofinder.app.ui.count
import com.macrofinder.app.ui.theme.MF
import com.macrofinder.app.ui.theme.chainColor

/** PLAN-V2 section 4.1, axis B. The one axis the supermarkets don't have. */
val BUCKETS = listOf(
    "eiwitbom" to "Eiwitbom",
    "cut" to "Cut",
    BUCKET_BULK to "Bulk",
    "snel_eiwit" to "Snel eiwit",
    "ontbijt" to "Ontbijt",
    "meal_prep" to "Meal prep",
    "supplement" to "Supplement",
)

val CHAINS = listOf("ah" to "AH", "jumbo" to "Jumbo", "aldi" to "Aldi")

/**
 * The ranked list. Milestone 23: dense, one screen, the sort visible as text
 * rather than behind an icon, filters for chain, shelf, macro bucket and
 * now/upcoming.
 */
@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun DealsScreen(
    vm: CatalogueViewModel,
    sync: CatalogueSyncState,
    onRefresh: () -> Unit,
    onOpen: (String) -> Unit,
    onAbout: () -> Unit,
) {
    val t = MF.tokens
    val state by vm.state.collectAsState()
    val query by vm.query.collectAsState()
    val prefs by vm.prefs.collectAsState()
    val ranked = remember(state, query, prefs) { vm.visibleDeals() }
    val today = vm.today()
    val listState = rememberLazyListState()
    var showShelves by remember { mutableStateOf(false) }

    if (showShelves) {
        ShelfSheet(
            shelves = state.shelves,
            selected = query.shelf,
            foodOnly = query.foodOnly,
            onPick = { vm.setQuery(query.copy(shelf = it)); showShelves = false },
            onFoodOnly = { vm.setQuery(query.copy(foodOnly = it)) },
            onDismiss = { showShelves = false },
        )
    }

    // Pull to refresh starts a sync; the banner shows its progress, so the
    // spinner only has to acknowledge the pull.
    val pull = rememberPullToRefreshState()
    if (pull.isRefreshing) {
        LaunchedEffect(Unit) {
            onRefresh()
            delay(700)
            pull.endRefresh()
        }
    }

    Box(Modifier.fillMaxSize().nestedScroll(pull.nestedScrollConnection)) {
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize().background(t.paper),
        contentPadding = PaddingValues(bottom = 24.dp),
    ) {
        item {
            Row(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Aanbod", style = MF.type.display, color = t.ink)
                    Text(
                        if (query.window == DealWindow.ACTIVE) "Nu in de aanbieding, op volgorde"
                        else "Aanbiedingen die nog moeten beginnen",
                        style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 2.dp),
                    )
                }
                TextAction("Instellingen", onAbout, color = t.muted)
            }
        }
        item { Spacer(Modifier.padding(top = 8.dp)); SyncBanner(sync, state.installed, onRefresh) }

        item {
            ChipRow {
                FilterChip("Nu", query.window == DealWindow.ACTIVE,
                    { vm.setQuery(query.copy(window = DealWindow.ACTIVE)) })
                FilterChip("Binnenkort", query.window == DealWindow.UPCOMING,
                    { vm.setQuery(query.copy(window = DealWindow.UPCOMING)) })
                Spacer(Modifier.padding(horizontal = 2.dp))
                // Only my stores, and no chips at all when that's one store.
                CHAINS.filter { it.first in prefs.stores }.takeIf { it.size > 1 }.orEmpty().forEach { (key, label) ->
                    FilterChip(label, key in query.chains, {
                        val next = if (key in query.chains) query.chains - key else query.chains + key
                        vm.setQuery(query.copy(chains = next))
                    }, leadingColor = chainColor(key))
                }
            }
        }
        item {
            ChipRow {
                // Eighteen shelves don't belong in a row of chips; one chip opens
                // them in a sheet, next to the goal buckets that do.
                val shelfLabel = state.shelves.firstOrNull { it.key == query.shelf }?.label
                if (state.shelves.isNotEmpty()) {
                    FilterChip(
                        (shelfLabel ?: if (query.foodOnly) "Alleen eten" else "Alle schappen") + "  ▾",
                        shelfLabel != null || !query.foodOnly,
                        { showShelves = true },
                    )
                }
                // The diet lives in settings, but a filter you can't see is a
                // list that looks broken. Tapping it goes to settings.
                if (prefs.diet != Diet.ALLES) {
                    FilterChip(if (prefs.diet == Diet.VEGAN) "Veganistisch" else "Vegetarisch", true, onAbout)
                }
                BUCKETS.forEach { (key, label) ->
                    FilterChip(label, query.bucket == key, {
                        vm.setQuery(query.copy(bucket = if (query.bucket == key) null else key))
                    })
                }
            }
        }

        stickyHeader {
            Column(Modifier.fillMaxWidth().background(t.paper)) {
                TextTabs(
                    options = DealSort.entries,
                    selected = query.sort,
                    label = { it.label },
                    onSelect = { vm.setQuery(query.copy(sort = it)) },
                )
                Hairline()
            }
        }

        item {
            Text(
                when {
                    !state.ready -> "Laden…"
                    else -> "${count(ranked.size)} ${if (ranked.size == 1) "product" else "producten"}"
                },
                style = MF.type.label, color = t.muted,
                modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp),
            )
        }

        if (state.ready && ranked.isEmpty()) {
            item {
                EmptyState(
                    title = "Niets dat hier past",
                    body = when {
                        // A catalogue built before milestone 32 carries no diet tags.
                        prefs.diet != Diet.ALLES && state.deals.none { "vegetarisch" in it.buckets } ->
                            "Deze catalogus weet nog niet wat vegetarisch is. Dat komt met de " +
                                "volgende update; tot dan kun je het in Instellingen op Alles zetten."
                        query.window == DealWindow.UPCOMING ->
                            "Er zijn nog geen aanbiedingen voor volgende week bekend. " +
                                "AH en Jumbo zetten die meestal een dag of twee van tevoren online."
                        query.chains == setOf("aldi") ->
                            "Aldi heeft deze week niets in deze selectie. Aldi zet alleen de " +
                                "weekaanbiedingen online, zonder vaste catalogus."
                        else -> "Zet een filter uit, of kies een andere winkel."
                    },
                    action = "Filters wissen",
                    onAction = { vm.setQuery(query.copy(chains = emptySet(), shelf = null, bucket = null)) },
                )
            }
        }

        items(ranked, key = { it.deal.id + it.deal.lane }) { r ->
            DealRow(r.deal, r.tier, query.sort, today, onClick = { onOpen(r.deal.id) })
        }

        if (ranked.any { it.deal.macrosEstimated && it.deal.hasMacros }) {
            item {
                Text(
                    "$ESTIMATE_MARK geschat uit de algemene voedingswaarde van dit soort product, " +
                        "niet van het etiket. Die cijfers staan in grijs, hoe goed ze ook lijken.",
                    style = MF.type.label, color = t.muted,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 16.dp),
                )
            }
        }
    }
    if (pull.progress > 0f || pull.isRefreshing) PullToRefreshContainer(
        state = pull,
        modifier = Modifier.align(Alignment.TopCenter),
        containerColor = t.card,
        contentColor = t.signal,
    )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShelfSheet(
    shelves: List<Shelf>,
    selected: String?,
    foodOnly: Boolean,
    onPick: (String?) -> Unit,
    onFoodOnly: (Boolean) -> Unit,
    onDismiss: () -> Unit,
) {
    val t = MF.tokens
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = t.card) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            Row(
                Modifier.fillMaxWidth().toggleable(foodOnly, role = Role.Switch, onValueChange = onFoodOnly)
                    .padding(horizontal = 20.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Alleen eten", style = MF.type.rowTitle, color = t.ink)
                    Text("Geen drogisterij, huishouden of alcohol. Supplementen blijven.",
                        style = MF.type.label, color = t.muted)
                }
                Switch(checked = foodOnly, onCheckedChange = null,
                    colors = SwitchDefaults.colors(checkedTrackColor = t.signal))
            }
            Hairline(Modifier.padding(vertical = 8.dp))
            (listOf<Shelf?>(null) + shelves).forEach { shelf ->
                val active = shelf?.key == selected
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp)
                        .selectable(active, role = Role.RadioButton) { onPick(shelf?.key) }
                        .padding(horizontal = 20.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(shelf?.label ?: "Alle schappen", style = MF.type.body,
                        color = if (active) t.ink else t.muted, modifier = Modifier.weight(1f))
                    if (active) Text("✓", style = MF.type.rowTitle, color = t.signal)
                }
            }
        }
    }
}
