package com.macrofinder.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.components.DealRow
import com.macrofinder.app.ui.components.EmptyState
import com.macrofinder.app.ui.components.SectionLabel
import com.macrofinder.app.ui.theme.MF

/** Milestone 26: what you follow, what's on offer among it first. */
@Composable
fun FollowingScreen(vm: CatalogueViewModel, onOpen: (String) -> Unit) {
    val t = MF.tokens
    val deals by vm.followedDeals.collectAsState()
    val today = vm.today()
    val onOffer = deals.filter { it.lane != "shelf" && it.isActiveOn(today) }
    val rest = deals - onOffer.toSet()

    LazyColumn(Modifier.fillMaxSize().background(t.paper), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Text("Gevolgd", style = MF.type.display, color = t.ink,
                modifier = Modifier.padding(start = 16.dp, top = 20.dp))
            Text("Je krijgt een melding als een van deze in de aanbieding gaat.",
                style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 16.dp, top = 2.dp))
        }
        if (deals.isEmpty()) {
            item {
                EmptyState(
                    "Nog niets gevolgd",
                    "Tik op 'Volg' bij een product om het hier te zien. Gaat het in de " +
                        "aanbieding, dan hoor je het na de volgende update.",
                )
            }
        }
        if (onOffer.isNotEmpty()) {
            item { SectionLabel("Nu in de aanbieding") }
            items(onOffer, key = { "o" + it.id }) { d ->
                DealRow(d, null, DealSort.PROTEIN_PER_EURO, today, onClick = { onOpen(d.id) })
            }
        }
        if (rest.isNotEmpty()) {
            item { SectionLabel("Normale prijs") }
            items(rest, key = { "r" + it.id }) { d ->
                DealRow(d, null, DealSort.PROTEIN_PER_EURO, today, onClick = { onOpen(d.id) })
            }
        }
    }
}
