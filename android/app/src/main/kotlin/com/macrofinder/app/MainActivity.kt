package com.macrofinder.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.macrofinder.app.data.ArchetypeEntry
import com.macrofinder.app.data.FoodTab
import com.macrofinder.app.data.MealTotals
import com.macrofinder.app.data.OfferEntry
import com.macrofinder.app.data.RuleOutcome
import com.macrofinder.app.data.SavedMeal
import com.macrofinder.app.data.SavedMealsStore
import com.macrofinder.app.data.TemplateEntry
import com.macrofinder.app.ui.MacroFinderViewModel
import com.macrofinder.app.ui.Screen
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                MacroFinderApp()
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

    // Saved meals live on the phone; the ViewModel holds no Android types, so
    // the store is collected here and handed in.
    LaunchedEffect(Unit) {
        store.meals.collect { viewModel.setSavedMeals(it) }
    }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding)) {
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
        state.loading -> CircularProgressIndicator(modifier = Modifier.padding(32.dp))
        state.error != null -> Text(
            "Could not load data: ${state.error}", modifier = Modifier.padding(16.dp)
        )
        state.tab == FoodTab.MEALS -> MealsTab(viewModel)
        else -> OfferList(viewModel.visibleOffers())
    }
}

/**
 * The Meals tab: the templates you can build, then the curated archetypes.
 *
 * Templates come first because they are the answer to "what should I cook",
 * and the archetypes are a narrower "is this worth buying ready-made".
 */
@Composable
private fun MealsTab(viewModel: MacroFinderViewModel) {
    val state by viewModel.state.collectAsState()

    LazyColumn {
        item {
            Row(modifier = Modifier.padding(16.dp)) {
                TextButton(onClick = { viewModel.showSavedMeals() }) {
                    Text("Saved meals (${state.savedMeals.size})")
                }
            }
        }
        items(state.templates) { template ->
            TemplateRow(template) { viewModel.customise(template.key) }
        }
        item { Divider() }
        items(viewModel.visibleArchetypes()) { archetype -> ArchetypeRow(archetype) }
    }
}

@Composable
private fun TemplateRow(template: TemplateEntry, onClick: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(16.dp)
    ) {
        Text(template.name, style = MaterialTheme.typography.titleMedium)
        val slots = template.slots.joinToString(", ") { it.name.lowercase() }
        Text("Build your own: $slots", style = MaterialTheme.typography.bodySmall)
    }
}

/**
 * Build a meal. Each slot lists its candidates cheapest-first, and the total
 * re-costs on every tap.
 */
@Composable
private fun CustomiseScreen(viewModel: MacroFinderViewModel, onSave: (String) -> Unit) {
    val state by viewModel.state.collectAsState()
    val template = viewModel.currentTemplate() ?: return
    var name by remember { mutableStateOf(template.name) }

    LazyColumn {
        item {
            Row(modifier = Modifier.padding(16.dp)) {
                TextButton(onClick = { viewModel.back() }) { Text("< Back") }
            }
            Text(template.name, style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(horizontal = 16.dp))
        }

        template.slots.forEach { slot ->
            item {
                val optional = if (slot.required) "" else " (optional)"
                Text("${slot.name}$optional", style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 4.dp))
            }
            items(viewModel.candidatesFor(slot)) { candidate ->
                val chosen = state.selections[slot.key] == candidate.food_type
                Row(
                    modifier = Modifier.fillMaxWidth()
                        .clickable {
                            viewModel.choose(
                                slot.key,
                                if (chosen) null else candidate.food_type,
                            )
                        }
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                ) {
                    Column {
                        Text((if (chosen) "* " else "  ") + candidate.name)
                        // An unpriced candidate says so rather than showing a
                        // zero - it is still a real option, just not a costed one.
                        val price = candidate.price_eur
                            ?.let { "€%.2f".format(it) } ?: "price unknown"
                        val quantity = candidate.required_quantity
                            ?.takeIf { it > 1 }?.let { " (buy $it)" } ?: ""
                        val promo = candidate.promo_text?.let { " - $it" } ?: ""
                        Text("${"%.0f".format(candidate.grams)} g - $price$quantity$promo",
                            style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }

        item { TotalsBlock(viewModel.currentTotals()) }
        item { IssuesBlock(viewModel) }

        item {
            Column(modifier = Modifier.padding(16.dp)) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name this meal") },
                )
                Button(onClick = { onSave(name) }, modifier = Modifier.padding(top = 8.dp)) {
                    Text("Save meal")
                }
            }
        }
    }
}

/**
 * The total, and - when it cannot be known - WHICH line made it unknown.
 *
 * A bare dash would leave the user guessing. Naming the culprit is the app-side
 * form of `PricedComposition.unpriced`.
 */
@Composable
private fun TotalsBlock(totals: MealTotals) {
    Column(modifier = Modifier.padding(16.dp)) {
        Divider()
        val cost = totals.eur?.let { "€%.2f".format(it) } ?: "unknown"
        Text("Total: $cost", style = MaterialTheme.typography.titleMedium)
        if (totals.unpricedLines.isNotEmpty()) {
            Text("No current price for: ${totals.unpricedLines.joinToString(", ")}",
                style = MaterialTheme.typography.bodySmall)
        }

        val protein = totals.proteinG?.let { "%.1f g".format(it) } ?: "unknown"
        val kcal = totals.kcal?.let { "%.0f".format(it) } ?: "unknown"
        Text("Protein: $protein - $kcal kcal")
        if (totals.unknownMacroLines.isNotEmpty()) {
            Text("No macro data for: ${totals.unknownMacroLines.joinToString(", ")}",
                style = MaterialTheme.typography.bodySmall)
        }
        totals.eurPerGProtein?.let {
            Text("€%.3f per gram of protein".format(it))
        }
    }
}

/** Rule warnings, in the author's words. Nothing here blocks anything. */
@Composable
private fun IssuesBlock(viewModel: MacroFinderViewModel) {
    val missing = viewModel.missingSlots()
    val issues = viewModel.currentIssues()

    Column(modifier = Modifier.padding(horizontal = 16.dp)) {
        if (missing.isNotEmpty()) {
            Text("Still to choose: ${missing.joinToString(", ") { it.name }}",
                style = MaterialTheme.typography.bodyMedium)
        }
        issues.forEach { issue ->
            val prefix = when {
                issue.outcome == RuleOutcome.UNKNOWN -> "Can't tell"
                issue.severity == "wrong" -> "Doesn't work"
                issue.severity == "note" -> "Worth knowing"
                else -> "Unfinished"
            }
            Text("$prefix: ${issue.note}", style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(vertical = 4.dp))
        }
    }
}

@Composable
private fun SavedMealsScreen(viewModel: MacroFinderViewModel, onDelete: (String) -> Unit) {
    val state by viewModel.state.collectAsState()

    LazyColumn {
        item {
            Row(modifier = Modifier.padding(16.dp)) {
                TextButton(onClick = { viewModel.back() }) { Text("< Back") }
            }
        }
        if (state.savedMeals.isEmpty()) {
            item {
                Text("No saved meals yet. Build one from a template on the Meals tab.",
                    modifier = Modifier.padding(16.dp))
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
    // Re-costed against the CURRENT snapshot, which is the whole reason a saved
    // meal stores keys and quantities rather than the price it had when saved.
    val totals = viewModel.totalsFor(meal)
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Text(meal.name, style = MaterialTheme.typography.titleMedium)
        Text(meal.lines.joinToString(", ") { it.label }, style = MaterialTheme.typography.bodySmall)
        Text("This week: " + (totals.eur?.let { "€%.2f".format(it) } ?: "price unknown"))
        Row {
            TextButton(onClick = { viewModel.openSaved(meal) }) { Text("Open") }
            TextButton(onClick = { onDelete(meal.id) }) { Text("Delete") }
        }
    }
}

@Composable
private fun ArchetypeRow(archetype: ArchetypeEntry) {
    Column(modifier = Modifier.padding(16.dp)) {
        Text(archetype.name, style = MaterialTheme.typography.titleMedium)
        Text(archetype.verdict.text, style = MaterialTheme.typography.bodyMedium)
        val ready = archetype.ready_made
        if (ready != null) {
            Text("Ready-made: ${ready.name} - €${"%.2f".format(ready.price_eur ?: 0.0)}"
                + (ready.promo_text?.let { " ($it)" } ?: ""))
        }
        archetype.compositions.forEach { composition ->
            val price = composition.price_eur?.let { "€%.2f".format(it) } ?: "price unknown"
            Text("DIY: ${composition.name} - $price - ${composition.taste_delta_note}")
        }
    }
}

@Composable
private fun OfferList(offers: List<OfferEntry>) {
    LazyColumn {
        items(offers) { offer ->
            Column(modifier = Modifier.padding(16.dp)) {
                Text(offer.name, style = MaterialTheme.typography.titleMedium)
                val price = offer.price.unit_price_eur?.let { "€%.2f".format(it) } ?: "price unknown"
                Text("$price" + (offer.price.promo_text?.let { " - $it" } ?: ""))
                val protein = offer.macros_per_100g.protein_g
                if (protein != null) {
                    val mark = if (offer.macros_need_marking) "*" else ""
                    Text("Protein: %.1f g / 100 g$mark".format(protein))
                }
            }
        }
    }
}
