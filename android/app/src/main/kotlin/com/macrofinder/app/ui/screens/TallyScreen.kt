package com.macrofinder.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.tally.TallyLine
import com.macrofinder.app.data.tally.TallyTotals
import com.macrofinder.app.data.tally.packCost
import com.macrofinder.app.data.tally.tallyTotals
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.ESTIMATE_MARK
import com.macrofinder.app.ui.components.Card
import com.macrofinder.app.ui.components.EmptyState
import com.macrofinder.app.ui.components.ProductImage
import com.macrofinder.app.ui.components.TextAction
import com.macrofinder.app.ui.euro
import com.macrofinder.app.ui.fmt
import com.macrofinder.app.ui.theme.MF
import com.macrofinder.app.ui.theme.chainColor
import com.macrofinder.app.ui.theme.chainName

/**
 * Milestone 38: what a planned shop costs and how much protein and energy it
 * buys. A calculator, not a list to tick off.
 */
@Composable
fun TallyScreen(vm: CatalogueViewModel, onBack: () -> Unit, onOpen: (String) -> Unit) {
    val t = MF.tokens
    val lines by vm.tallyLines.collectAsState()
    val totals = tallyTotals(lines)
    LazyColumn(Modifier.fillMaxSize().background(t.paper), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                TextAction("‹ Terug", onBack)
                Spacer(Modifier.weight(1f))
                if (lines.isNotEmpty()) TextAction("Leegmaken", vm::clearTally, color = t.muted)
            }
            Text("Teller", style = MF.type.display, color = t.ink, modifier = Modifier.padding(start = 16.dp))
            Text(
                "Wat deze boodschappen kosten en aan eiwit opleveren, met de prijzen van vandaag.",
                style = MF.type.label, color = t.muted,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 2.dp),
            )
        }
        if (lines.isEmpty()) {
            item { EmptyState("Nog niets geteld", "Tik op Tel mee bij een product om het hier op te tellen.") }
        } else {
            item { TotalsCard(totals, estimated = lines.any { it.deal?.macrosEstimated == true }) }
            items(lines, key = { it.id }) { line -> TallyRow(line, vm, onOpen) }
        }
    }
}

@Composable
private fun TotalsCard(totals: TallyTotals, estimated: Boolean) {
    val t = MF.tokens
    // BRIEF section 9 rule 1: a total built on an estimate is an estimate.
    val mark = if (estimated) "$ESTIMATE_MARK " else ""
    Card(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
        Column {
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text("Totaal", style = MF.type.label, color = t.muted)
                    Text(euro(totals.eur) ?: "onbekend", style = MF.type.figure, color = t.ink)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text(totals.proteinG?.let { mark + fmt("%.0f g eiwit", it) } ?: "eiwit onbekend",
                        style = MF.type.figureSm, color = t.ink)
                    Text(totals.kcal?.let { mark + fmt("%.0f kcal", it) } ?: "kcal onbekend",
                        style = MF.type.label, color = t.muted)
                }
            }
            totals.eurPer100gProtein?.let {
                Text("$mark${euro(it)} per 100 g eiwit", style = MF.type.body, color = t.ink,
                    modifier = Modifier.padding(top = 8.dp))
            }
            if (totals.byChain.size > 1) {
                Text(
                    totals.byChain.entries.joinToString(" · ") { (chain, eur) -> "${chainName(chain)} ${euro(eur) ?: "?"}" },
                    style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 4.dp),
                )
            }
            listOfNotNull(
                totals.unpriced.takeIf { it.isNotEmpty() }?.let { "Geen prijs voor: ${it.joinToString(", ")}" },
                totals.unknownMacros.takeIf { it.isNotEmpty() }
                    ?.let { "Eiwit of kcal onbekend voor: ${it.joinToString(", ")}" },
            ).forEach { Text(it, style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 4.dp)) }
        }
    }
}

@Composable
private fun TallyRow(line: TallyLine, vm: CatalogueViewModel, onOpen: (String) -> Unit) {
    val t = MF.tokens
    val deal = line.deal
    Card(Modifier.padding(horizontal = 12.dp, vertical = 4.dp), padding = PaddingValues(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(
                Modifier.weight(1f).clickable(enabled = deal != null) { onOpen(line.id) },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ProductImage(deal?.imageUrl, 44.dp, radius = 8.dp)
                Column(Modifier.padding(horizontal = 12.dp)) {
                    Text(deal?.name ?: "Niet meer in de catalogus", style = MF.type.body, color = t.ink,
                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                    if (deal != null) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(chainColor(deal.chain)))
                            val mark = if (deal.macrosEstimated) "$ESTIMATE_MARK " else ""
                            val protein = deal.proteinPer100g?.let { p -> deal.massG?.let { m -> p * m / 100 * line.packs } }
                            Text(
                                listOfNotNull(
                                    euro(packCost(deal, line.packs)),
                                    deal.promoText?.takeIf { deal.lane == "promo" },
                                    protein?.let { mark + fmt("%.0f g eiwit", it) },
                                ).joinToString(" · "),
                                style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 6.dp),
                            )
                        }
                    }
                }
            }
            Stepper(line.packs) { vm.setPacks(line.id, it) }
        }
    }
}

/** Minus, count, plus. Minus at one removes the line. */
@Composable
private fun Stepper(value: Int, onChange: (Int) -> Unit) {
    val t = MF.tokens
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        TextAction("−", { onChange(value - 1) }, modifier = Modifier.semantics { contentDescription = "Eén minder" })
        Text("$value", style = MF.type.figureSm, color = t.ink)
        TextAction("+", { onChange(value + 1) }, modifier = Modifier.semantics { contentDescription = "Eén meer" })
    }
}
