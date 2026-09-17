package com.macrofinder.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.macrofinder.app.data.ArchetypeEntry
import com.macrofinder.app.data.FoodTab
import com.macrofinder.app.data.OfferEntry
import com.macrofinder.app.ui.MacroFinderViewModel

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

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding)) {
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
                state.error != null -> Text("Could not load data: ${state.error}",
                    modifier = Modifier.padding(16.dp))
                state.tab == FoodTab.MEALS -> ArchetypeList(viewModel.visibleArchetypes())
                else -> OfferList(viewModel.visibleOffers())
            }
        }
    }
}

@Composable
private fun ArchetypeList(archetypes: List<ArchetypeEntry>) {
    LazyColumn {
        items(archetypes) { archetype ->
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
