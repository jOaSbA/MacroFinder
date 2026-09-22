package com.macrofinder.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.macrofinder.app.data.ArchetypeEntry
import com.macrofinder.app.data.FoodTab
import com.macrofinder.app.data.MealTotals
import com.macrofinder.app.data.OfferEntry
import com.macrofinder.app.data.RuleOutcome
import com.macrofinder.app.data.SavedMeal
import com.macrofinder.app.data.SavedMealsStore
import com.macrofinder.app.data.SlotCandidate
import com.macrofinder.app.data.TemplateEntry
import com.macrofinder.app.ui.MacroFinderViewModel
import com.macrofinder.app.ui.Screen
import com.macrofinder.app.ui.theme.MacroFinderTheme
import com.macrofinder.app.ui.theme.chainSignal
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.TextButton
import androidx.compose.runtime.livedata.observeAsState
import androidx.work.WorkManager
import com.macrofinder.app.data.sync.CatalogueSyncWorker
import com.macrofinder.app.ui.CatalogueSyncState
import com.macrofinder.app.ui.fmt
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Milestone 17. Idempotent (ExistingPeriodicWorkPolicy.KEEP), so
        // calling it on every launch simply re-asserts the schedule rather than
        // stacking jobs.
        CatalogueSyncWorker.schedule(this)
        setContent {
            MacroFinderTheme {
                MacroFinderApp()
            }
        }
    }
}

private fun eur(value: Double?): String =
    value?.let { fmt("€%.2f", it) } ?: "?"

/**
 * One line about the catalogue sync, and a way to ask for it now.
 *
 * Shows nothing at all when there is nothing to say. A sync that found the
 * catalogue already current is not news, and a banner that is always there
 * stops being read.
 */
@Composable
private fun CatalogueSyncBanner(sync: CatalogueSyncState, onRefresh: () -> Unit) {
    if (!sync.running && sync.message == null) return

    Surface(color = MaterialTheme.colorScheme.surfaceVariant) {
        Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    sync.label ?: sync.message.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (!sync.running && !sync.halted) {
                    TextButton(onClick = onRefresh) { Text("Nu verversen") }
                }
            }
            // A determinate bar where the size is known, an indeterminate one
            // where it is not. Faking a fraction would be worse than admitting
            // the step has no measurable progress.
            if (sync.running) {
                if (sync.fraction != null) {
                    LinearProgressIndicator(
                        progress = { sync.fraction },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                    )
                } else {
                    LinearProgressIndicator(
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                    )
                }
            }
        }
    }
}

@Composable
fun MacroFinderApp(viewModel: MacroFinderViewModel = viewModel()) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val store = remember { SavedMealsStore(context) }

    LaunchedEffect(Unit) {
        store.meals.collect { viewModel.setSavedMeals(it) }
    }

    // The catalogue sync runs whether or not this screen is open, so the UI
    // observes WorkManager rather than owning the work.
    val workManager = remember { WorkManager.getInstance(context) }
    val periodic by workManager
        .getWorkInfosForUniqueWorkLiveData(CatalogueSyncWorker.PERIODIC_NAME)
        .observeAsState(emptyList())
    val oneOff by workManager
        .getWorkInfosForUniqueWorkLiveData(CatalogueSyncWorker.ONE_OFF_NAME)
        .observeAsState(emptyList())
    val sync = CatalogueSyncState.fromWorkInfo(
        // A manual refresh is what the user is waiting on, so it wins.
        oneOff.firstOrNull() ?: periodic.firstOrNull()
    )

    Scaffold(
        // The total is the number this screen exists to show, and it changes
        // on every tap. Pinning it means the feedback is never below the fold,
        // which it was when it sat at the end of a twenty-item scroll.
        bottomBar = {
            if (state.screen is Screen.Customise) TotalsBar(viewModel)
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding)) {
            CatalogueSyncBanner(
                sync = sync,
                onRefresh = { CatalogueSyncWorker.syncNow(context) },
            )
            when (state.screen) {
                is Screen.Customise -> CustomiseScreen(
                    viewModel = viewModel,
                    onSave = { name -> scope.launch { store.save(viewModel.buildSavedMeal(name)) } },
                )
                is Screen.SavedMeals -> SavedMealsScreen(
                    viewModel = viewModel,
                    onDelete = { id -> scope.launch { store.delete(id) } },
                )
                is Screen.Tabs -> BrowseScreen(viewModel)
            }
        }
    }
}

@Composable
private fun BrowseScreen(viewModel: MacroFinderViewModel) {
    val state by viewModel.state.collectAsState()

    TabRow(selectedTabIndex = state.tab.ordinal) {
        FoodTab.entries.forEach { tab ->
            Tab(
                selected = state.tab == tab,
                onClick = { viewModel.selectTab(tab) },
                text = { Text(tab.name.lowercase().replaceFirstChar { it.uppercase() }) },
            )
        }
    }

    when {
        // A bare spinner in a corner reads as a hang. Say what is happening.
        state.loading -> Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            CircularProgressIndicator()
            Text(
                "Deze week ophalen…",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 16.dp),
            )
        }
        state.error != null -> Column(modifier = Modifier.padding(24.dp)) {
            Text("Could not load this week's prices", style = MaterialTheme.typography.titleMedium)
            Text(
                state.error ?: "",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
            TextButton(onClick = { viewModel.refresh() }) { Text("Try again") }
        }
        state.tab == FoodTab.MEALS -> MealsTab(viewModel)
        else -> OfferList(viewModel.visibleOffers(), state.chain)
    }
}

/** The one saturated element in the app: a price-tag chip in the chain's own colour. */
@Composable
private fun PromoBadge(text: String, chain: String) {
    val signal = chainSignal(chain)
    Surface(
        color = signal.background,
        shape = RoundedCornerShape(4.dp),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            color = signal.content,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

@Composable
private fun MealsTab(viewModel: MacroFinderViewModel) {
    val state by viewModel.state.collectAsState()

    LazyColumn {
        item { SectionHeader("Zelf samenstellen") }
        items(state.templates) { template ->
            TemplateRow(template) { viewModel.customise(template.key) }
        }
        item {
            TextButton(
                onClick = { viewModel.showSavedMeals() },
                modifier = Modifier.padding(horizontal = 8.dp),
            ) { Text("Bewaarde maaltijden (${state.savedMeals.size})") }
        }
        item { SectionHeader("Kant-en-klaar vs. zelf maken") }
        items(viewModel.visibleArchetypes()) { archetype -> ArchetypeRow(archetype) }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 8.dp),
    )
}

@Composable
private fun TemplateRow(template: TemplateEntry, onClick: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp)
    ) {
        Text(template.name, style = MaterialTheme.typography.titleMedium)
        Text(
            template.slots.joinToString(" · ") { it.name.lowercase() },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
private fun CustomiseScreen(viewModel: MacroFinderViewModel, onSave: (String) -> Unit) {
    val state by viewModel.state.collectAsState()
    val template = viewModel.currentTemplate() ?: return
    var name by remember { mutableStateOf("") }

    LazyColumn(modifier = Modifier.fillMaxSize()) {
        item {
            TextButton(onClick = { viewModel.back() }) { Text("‹ Terug") }
            Text(
                template.name,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp),
            )
        }

        template.slots.forEach { slot ->
            item {
                SectionHeader(if (slot.required) slot.name else "${slot.name} (optioneel)")
            }
            items(viewModel.candidatesFor(slot)) { candidate ->
                CandidateRow(
                    candidate = candidate,
                    chain = state.chain,
                    selected = state.selections[slot.key] == candidate.food_type,
                    onSelect = {
                        viewModel.choose(
                            slot.key,
                            if (state.selections[slot.key] == candidate.food_type) null
                            else candidate.food_type,
                        )
                    },
                )
            }
        }

        item { IssuesBlock(viewModel) }
        item {
            Column(modifier = Modifier.padding(16.dp)) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Naam") },
                    // Empty rather than prefilled with the template name, which
                    // made every saved pasta identical in the list.
                    placeholder = { Text("bijv. donderdagpasta") },
                )
                Button(
                    onClick = { onSave(name.ifBlank { template.name }) },
                    modifier = Modifier.padding(top = 8.dp),
                ) { Text("Maaltijd bewaren") }
            }
        }
    }
}

/**
 * One candidate for one slot.
 *
 * The selection used to be a "* " prefix on the label, which meant a screen
 * reader announced "star groene pesto" and sighted users had to notice a
 * character. `selectable` with [Role.RadioButton] gives the row a real
 * selected state that TalkBack reports, and a real 48dp target.
 */
@Composable
private fun CandidateRow(
    candidate: SlotCandidate,
    chain: String,
    selected: Boolean,
    onSelect: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth()
            .selectable(selected = selected, onClick = onSelect, role = Role.RadioButton)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null)
        Column(modifier = Modifier.padding(start = 8.dp).weight(1f)) {
            Text(candidate.name, style = MaterialTheme.typography.bodyLarge)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    fmt("%.0f g", candidate.grams),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                val promo = candidate.promo_text?.takeUnless { it.contains("shelf price") }
                if (promo != null) {
                    Column(modifier = Modifier.padding(start = 8.dp)) {
                        PromoBadge(promo, chain)
                    }
                }
                val quantity = candidate.required_quantity?.takeIf { it > 1 }
                if (quantity != null) {
                    // Copy rule 3: a multi-buy means several of them in the fridge.
                    Text(
                        "koop $quantity",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                }
            }
        }
        // The price is the content of a price app, so it gets its own weight
        // and a right-aligned column the eye can run down.
        Text(
            candidate.price_eur?.let { eur(it) } ?: "geen prijs",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = if (candidate.price_eur != null) FontWeight.SemiBold else FontWeight.Normal,
            color = if (candidate.price_eur != null) MaterialTheme.colorScheme.onSurface
            else MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.End,
            modifier = Modifier.width(88.dp),
        )
    }
}

/**
 * The pinned total.
 *
 * Note the wording on unknowns. It used to read "No macro data for: sla" while
 * displaying a protein figure that included sla - two contradictory claims on
 * one screen. `sla` has protein and kcal but no carbs or fat, so the honest
 * sentence names what is missing rather than overstating it.
 *
 * The figures also carry a provenance mark. BRIEF section 9 rule 1 forbids
 * showing an estimated macro bare, and every one of these comes from the
 * generic seed - this screen was showing them unmarked, which is
 * docs/AUDIT.md finding 3.3. The offer list already marked its own with the
 * same asterisk and the same footnote wording, so the two screens now say the
 * same thing in the same way.
 */
@Composable
private fun TotalsBar(viewModel: MacroFinderViewModel) {
    val totals: MealTotals = viewModel.currentTotals()
    val missing = viewModel.missingSlots()

    Surface(color = MaterialTheme.colorScheme.surfaceVariant) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Bottom,
            ) {
                Column {
                    Text(
                        "Totaal",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        totals.eur?.let { eur(it) } ?: "nog onbekend",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    // The mark goes on the figures, never on "onbekend" -
                    // there is nothing to qualify about an unknown.
                    val mark = if (totals.macrosNeedMarking) "*" else ""
                    Text(
                        totals.proteinG?.let { fmt("%.1f g eiwit$mark", it) }
                            ?: "eiwit onbekend",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        totals.kcal?.let { fmt("%.0f kcal$mark", it) } ?: "kcal onbekend",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (missing.isNotEmpty()) {
                Text(
                    "Nog kiezen: ${missing.joinToString(", ") { it.name.lowercase() }}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            if (totals.unpricedLines.isNotEmpty()) {
                Text(
                    "Geen actuele prijs voor: ${totals.unpricedLines.joinToString(", ")}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (totals.macrosNeedMarking) {
                Text(
                    "* geschatte macro's, uit algemene voedingswaarden en niet " +
                        "van het etiket van dit product",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            if (totals.unknownMacroLines.isNotEmpty()) {
                Text(
                    "Niet alle macro's bekend voor: " +
                        totals.unknownMacroLines.joinToString(", "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** Rule warnings, in the author's words. Nothing here blocks anything. */
@Composable
private fun IssuesBlock(viewModel: MacroFinderViewModel) {
    val issues = viewModel.currentIssues()
    if (issues.isEmpty()) return

    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        issues.forEach { issue ->
            val prefix = when {
                issue.outcome == RuleOutcome.UNKNOWN -> "Niet te zeggen"
                issue.severity == "wrong" -> "Werkt niet"
                issue.severity == "note" -> "Goed om te weten"
                else -> "Nog niet af"
            }
            Text(
                "$prefix · ${issue.note}",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(vertical = 4.dp),
            )
        }
    }
}

@Composable
private fun SavedMealsScreen(viewModel: MacroFinderViewModel, onDelete: (String) -> Unit) {
    val state by viewModel.state.collectAsState()

    LazyColumn {
        item { TextButton(onClick = { viewModel.back() }) { Text("‹ Terug") } }
        if (state.savedMeals.isEmpty()) {
            item {
                Column(modifier = Modifier.padding(24.dp)) {
                    Text("Nog niets bewaard", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Stel een maaltijd samen op het tabblad Meals en bewaar hem hier. " +
                            "Elke week rekent hij zichzelf opnieuw door.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
        items(state.savedMeals) { meal -> SavedMealRow(viewModel, meal, onDelete) }
    }
}

@Composable
private fun SavedMealRow(
    viewModel: MacroFinderViewModel,
    meal: SavedMeal,
    onDelete: (String) -> Unit,
) {
    val totals = viewModel.totalsFor(meal)
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(meal.name, style = MaterialTheme.typography.titleMedium)
            Text(
                totals.eur?.let { eur(it) } ?: "geen prijs",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            meal.lines.joinToString(" · ") { it.label },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row {
            TextButton(onClick = { viewModel.openSaved(meal) }) { Text("Openen") }
            TextButton(onClick = { onDelete(meal.id) }) { Text("Verwijderen") }
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
private fun ArchetypeRow(archetype: ArchetypeEntry) {
    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text(archetype.name, style = MaterialTheme.typography.titleMedium)
        Text(
            archetype.verdict.text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        // The two prices the verdict is about. Trimming these would make the
        // screen tidier and the claim unverifiable, which is the wrong trade.
        archetype.ready_made?.let { ready ->
            Text(
                "Kant-en-klaar: ${ready.name} · ${eur(ready.price_eur)}",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        archetype.compositions.firstOrNull()?.let { composition ->
            Text(
                "Zelf maken: ${composition.name} · ${eur(composition.price_eur)}",
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                composition.taste_delta_note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
private fun OfferList(offers: List<OfferEntry>, chain: String) {
    // The asterisk on a macro figure used to appear with no legend anywhere,
    // while the SAME character meant "selected" on the customiser screen. The
    // selection is a radio button now, and the mark gets an explanation.
    val anyMarked = offers.any { it.macros_need_marking }

    LazyColumn {
        items(offers) { offer ->
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(offer.name, style = MaterialTheme.typography.bodyLarge)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        val protein = offer.macros_per_100g.protein_g
                        if (protein != null) {
                            val mark = if (offer.macros_need_marking) "*" else ""
                            Text(
                                fmt("%.1f g eiwit / 100 g$mark", protein),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        offer.price.promo_text?.let {
                            Column(modifier = Modifier.padding(start = 8.dp)) {
                                PromoBadge(it, chain)
                            }
                        }
                    }
                }
                Text(
                    offer.price.unit_price_eur?.let { eur(it) } ?: "geen prijs",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    textAlign = TextAlign.End,
                    modifier = Modifier.width(88.dp),
                )
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        }
        if (anyMarked) {
            item {
                Text(
                    "* algemene waarde uit de voedingstabel, niet het etiket van dit product",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(16.dp),
                )
            }
        }
    }
}
