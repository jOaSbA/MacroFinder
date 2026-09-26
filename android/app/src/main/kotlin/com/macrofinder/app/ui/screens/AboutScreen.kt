package com.macrofinder.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.macrofinder.app.BuildConfig
import com.macrofinder.app.ui.CatalogueSyncState
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.components.Card
import com.macrofinder.app.ui.components.TextAction
import com.macrofinder.app.ui.count
import com.macrofinder.app.ui.theme.MF

/**
 * Milestone 30 / PLAN-V2 section 7: where the data comes from, that the app
 * isn't affiliated with any chain, and what happens if the publisher stops.
 */
@Composable
fun AboutScreen(vm: CatalogueViewModel, sync: CatalogueSyncState, generatedAt: String?, onBack: () -> Unit) {
    val t = MF.tokens
    val state by vm.state.collectAsState()
    Column(Modifier.fillMaxSize().background(t.paper)) {
        TextAction("‹ Terug", onBack, modifier = Modifier.padding(horizontal = 8.dp))
        Column(
            Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 12.dp).padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("Over MacroFinder", style = MF.type.display, color = t.ink, modifier = Modifier.padding(4.dp))
            if (sync.halted) {
                Card {
                    Text(sync.message ?: "De gegevens worden op dit moment niet bijgewerkt.",
                        style = MF.type.body, color = t.warn)
                }
            }
            Card {
                Column {
                    Text("Wat het doet", style = MF.type.rowTitle, color = t.ink)
                    Text(
                        "MacroFinder zet de aanbiedingen van AH, Jumbo en Aldi op volgorde van wat je " +
                            "aan eiwit (of calorieën) krijgt per euro. Het kiest niets voor je; het rangschikt.",
                        style = MF.type.body, color = t.muted, modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
            Card {
                Column {
                    Text("Waar de cijfers vandaan komen", style = MF.type.rowTitle, color = t.ink)
                    Text(
                        "Prijzen, aanbiedingen en productfoto's komen van de openbare websites van de " +
                            "winkels. Een macro van het etiket heeft geen teken; een cijfer met ≈ is " +
                            "geschat uit de algemene voedingswaarde van dat soort product. Onbekend blijft " +
                            "onbekend en telt nergens als nul.",
                        style = MF.type.body, color = t.muted, modifier = Modifier.padding(top = 4.dp),
                    )
                    Text(
                        "MacroFinder is niet verbonden aan Albert Heijn, Jumbo of Aldi. Controleer de " +
                            "prijs in de winkel.",
                        style = MF.type.body, color = t.ink, modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
            Card {
                Column {
                    Text("Gegevens op dit toestel", style = MF.type.rowTitle, color = t.ink)
                    val lines = listOfNotNull(
                        if (state.installed) "Catalogus: ${count(state.productCount)} producten " +
                            "(versie ${state.version?.take(8)})" else "Catalogus: nog niet gedownload",
                        generatedAt?.let { "Aanbiedingen bijgewerkt: ${it.take(16).replace('T', ' ')}" },
                        "App-versie ${BuildConfig.VERSION_NAME}",
                    )
                    lines.forEach {
                        Text(it, style = MF.type.body, color = t.muted, modifier = Modifier.padding(top = 4.dp))
                    }
                }
            }
            Card {
                Column {
                    Text("Open source", style = MF.type.rowTitle, color = t.ink)
                    Text(
                        "Code en gegevens: github.com/jOaSbA/MacroFinder. Lettertype Archivo, " +
                            "SIL Open Font License 1.1.",
                        style = MF.type.body, color = t.muted, modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}
