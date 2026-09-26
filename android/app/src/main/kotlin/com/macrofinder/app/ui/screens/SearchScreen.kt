package com.macrofinder.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.components.DealRow
import com.macrofinder.app.ui.components.EmptyState
import com.macrofinder.app.ui.count
import com.macrofinder.app.ui.theme.MF

/** Milestone 25: search the whole synced catalogue, on the phone, offline. */
@Composable
fun SearchScreen(vm: CatalogueViewModel, onOpen: (String) -> Unit) {
    val t = MF.tokens
    val text by vm.searchText.collectAsState()
    val results by vm.searchResults.collectAsState()
    val state by vm.state.collectAsState()
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { if (text.isEmpty()) runCatching { focus.requestFocus() } }

    Column(Modifier.fillMaxSize().background(t.paper)) {
        Text("Zoeken", style = MF.type.display, color = t.ink,
            modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 12.dp))
        Box(
            Modifier.padding(horizontal = 12.dp).fillMaxWidth().heightIn(min = 52.dp)
                .clip(RoundedCornerShape(14.dp)).background(t.card)
                .border(1.dp, t.rule, RoundedCornerShape(14.dp)).padding(horizontal = 16.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            if (text.isEmpty()) {
                Text("kwark, kipfilet, whey…", style = MF.type.body, color = t.muted)
            }
            BasicTextField(
                value = text,
                onValueChange = vm::search,
                singleLine = true,
                textStyle = MF.type.body.copy(color = t.ink),
                cursorBrush = SolidColor(t.signal),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        }
        val scope = if (state.installed) "in ${count(state.productCount)} producten" else "in de korte lijst"
        Text(
            if (text.isBlank()) "Zoekt $scope, ook zonder internet"
            else "${results.size} gevonden $scope",
            style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 16.dp, top = 10.dp),
        )
        LazyColumn(contentPadding = PaddingValues(top = 4.dp, bottom = 24.dp)) {
            if (text.isNotBlank() && results.isEmpty()) {
                item {
                    EmptyState(
                        "Niets gevonden",
                        if (state.installed) "Probeer een korter woord, of alleen het begin ervan."
                        else "Zolang de catalogus nog niet binnen is, zoek je alleen in de aanbiedingen.",
                    )
                }
            }
            items(results, key = { it.id }) { d ->
                DealRow(d, null, DealSort.PROTEIN_PER_EURO, vm.today(), onClick = { onOpen(d.id) })
            }
        }
    }
}
