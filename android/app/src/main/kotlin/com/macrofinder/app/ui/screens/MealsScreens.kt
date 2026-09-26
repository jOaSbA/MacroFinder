package com.macrofinder.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.cheapestPicks
import com.macrofinder.app.data.ArchetypeEntry
import com.macrofinder.app.data.MealTotals
import com.macrofinder.app.data.QuantityUnit
import com.macrofinder.app.data.RuleOutcome
import com.macrofinder.app.data.SavedMeal
import com.macrofinder.app.data.SlotCandidate
import com.macrofinder.app.data.TemplateEntry
import com.macrofinder.app.ui.ESTIMATE_MARK
import com.macrofinder.app.ui.MacroFinderViewModel
import com.macrofinder.app.ui.components.Badge
import com.macrofinder.app.ui.components.Card
import com.macrofinder.app.ui.components.ChipRow
import com.macrofinder.app.ui.components.EmptyState
import com.macrofinder.app.ui.components.FilterChip
import com.macrofinder.app.ui.components.Hairline
import com.macrofinder.app.ui.components.PrimaryButton
import com.macrofinder.app.ui.components.SectionLabel
import com.macrofinder.app.ui.components.TextAction
import com.macrofinder.app.ui.euro
import com.macrofinder.app.ui.fmt
import com.macrofinder.app.ui.theme.MF
import com.macrofinder.app.ui.theme.chainColor

/**
 * The meals tab: build a meal from a template, reopen a saved one, or see
 * where ready-made beats cooking (milestones 12, 13 and 27). Prices come from
 * latest.json at the chain picked at the top.
 */
@Composable
fun MealsScreen(
    vm: MacroFinderViewModel,
    onCustomise: (String) -> Unit,
    onSaved: () -> Unit,
) {
    val t = MF.tokens
    val state by vm.state.collectAsState()

    LazyColumn(Modifier.fillMaxSize().background(t.paper), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Text("Maaltijden", style = MF.type.display, color = t.ink,
                modifier = Modifier.padding(start = 16.dp, top = 20.dp))
            Text("Prijzen van deze week, per winkel. Kies er één:",
                style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 16.dp, top = 2.dp))
            ChipRow {
                CHAINS.forEach { (key, label) ->
                    FilterChip(label, state.chain == key, { vm.selectChain(key) }, leadingColor = chainColor(key))
                }
            }
        }
        if (state.loading) {
            item { Text("Laden…", style = MF.type.body, color = t.muted, modifier = Modifier.padding(16.dp)) }
        }
        state.error?.let { error ->
            item {
                EmptyState(
                    "Prijzen konden niet worden opgehaald",
                    "Controleer je verbinding en probeer het opnieuw. ($error)",
                    action = "Opnieuw proberen", onAction = { vm.refresh() },
                )
            }
        }
        if (state.templates.isNotEmpty()) {
            item { SectionLabel("Zelf samenstellen") }
            items(state.templates, key = { it.key }) { template ->
                TemplateCard(template, cheapestTotal(vm, template)) { onCustomise(template.key) }
            }
            item {
                Card(Modifier.padding(horizontal = 12.dp, vertical = 4.dp).clickable(onClick = onSaved)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Bewaarde maaltijden", style = MF.type.rowTitle, color = t.ink)
                            Text(
                                if (state.savedMeals.isEmpty()) "Nog niets bewaard"
                                else "${state.savedMeals.size} bewaard, elke week opnieuw doorgerekend",
                                style = MF.type.label, color = t.muted,
                            )
                        }
                        Text("›", style = MF.type.title, color = t.muted)
                    }
                }
            }
        }
        if (state.archetypes.isNotEmpty()) {
            item {
                SectionLabel("Kant-en-klaar of zelf maken")
                Text(
                    "Wat is goedkoper per gram eiwit: het pakje uit de winkel of het zelf maken? " +
                        "Met wat je inlevert aan smaak erbij.",
                    style = MF.type.label, color = t.muted,
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp),
                )
            }
            items(state.archetypes, key = { it.key }) { ArchetypeCard(it) }
        }
    }
}

/** The cheapest way to fill every required slot right now, or null if any is unpriced. */
private fun cheapestTotal(vm: MacroFinderViewModel, template: TemplateEntry): Double? {
    val prices = vm.state.value.templatePrices[template.key].orEmpty()
    val picks = cheapestPicks(template, prices) ?: return null
    return picks.entries.sumOf { (slot, food) -> prices[slot].orEmpty().first { it.food_type == food }.price_eur!! }
}

@Composable
private fun TemplateCard(template: TemplateEntry, from: Double?, onClick: () -> Unit) {
    val t = MF.tokens
    Card(Modifier.padding(horizontal = 12.dp, vertical = 4.dp).clickable(onClick = onClick)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(template.name, style = MF.type.title, color = t.ink)
                Text(template.slots.joinToString(" · ") { it.name.lowercase() },
                    style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 2.dp))
            }
            Column(horizontalAlignment = Alignment.End) {
                if (from != null) {
                    Text("vanaf", style = MF.type.label, color = t.muted)
                    Text(euro(from)!!, style = MF.type.figureSm.copy(fontSize = MF.type.title.fontSize), color = t.ink)
                }
            }
        }
    }
}

/** Milestone 27: every comparison shows its taste delta, in the author's words. */
@Composable
private fun ArchetypeCard(a: ArchetypeEntry) {
    val t = MF.tokens
    Card(Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
        Column {
            Text(a.name, style = MF.type.title, color = t.ink)
            Text(a.verdict.text, style = MF.type.body,
                color = if (a.verdict.winner == "unknown") t.muted else t.ink,
                modifier = Modifier.padding(top = 4.dp))
            Hairline(Modifier.padding(vertical = 10.dp))
            a.ready_made?.let { ready ->
                PriceLine("Kant-en-klaar", ready.name, ready.price_eur, ready.promo_text)
            } ?: PriceLine("Kant-en-klaar", "niets gevonden in deze winkel", null, null)
            a.compositions.firstOrNull()?.let { c ->
                PriceLine("Zelf maken", c.name, c.price_eur, null)
                Text(c.taste_delta_note, style = MF.type.label, color = t.muted,
                    modifier = Modifier.padding(top = 6.dp))
            }
        }
    }
}

@Composable
private fun PriceLine(label: String, name: String, price: Double?, promo: String?) {
    val t = MF.tokens
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MF.type.label, color = t.muted)
            Text(name, style = MF.type.body, color = t.ink)
        }
        if (promo != null) Box(Modifier.padding(end = 8.dp)) { Badge(promo, strong = true) }
        Text(euro(price) ?: "?", style = MF.type.figureSm, color = if (price != null) t.ink else t.muted)
    }
}

// -- the customiser -------------------------------------------------------------

@Composable
fun CustomiseScreen(vm: MacroFinderViewModel, onBack: () -> Unit, onSave: (String) -> Unit) {
    val t = MF.tokens
    val state by vm.state.collectAsState()
    val template = vm.currentTemplate()
    if (template == null) {
        LaunchedEffect(Unit) { onBack() }
        return
    }
    var name by remember { mutableStateOf("") }
    var saved by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().background(t.paper)) {
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(bottom = 16.dp)) {
            item {
                TextAction("‹ Terug", onBack, modifier = Modifier.padding(horizontal = 8.dp))
                Text(template.name, style = MF.type.display, color = t.ink,
                    modifier = Modifier.padding(start = 16.dp, bottom = 4.dp))
                Text("We beginnen met het goedkoopste. Tik om te wisselen.",
                    style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 16.dp))
            }
            template.slots.forEach { slot ->
                item(key = "label-${slot.key}") {
                    SectionLabel(if (slot.required) slot.name else "${slot.name} (optioneel)")
                }
                item(key = "slot-${slot.key}") {
                    Card(Modifier.padding(horizontal = 12.dp), padding = PaddingValues(vertical = 4.dp)) {
                        Column {
                            vm.candidatesFor(slot).forEachIndexed { i, c ->
                                if (i > 0) Hairline(Modifier.padding(start = 56.dp))
                                CandidateRow(c, state.selections[slot.key] == c.food_type) {
                                    vm.choose(slot.key,
                                        if (state.selections[slot.key] == c.food_type) null else c.food_type)
                                }
                            }
                        }
                    }
                }
            }
            item { Extras(vm) }
            item { Issues(vm) }
            item {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Box(
                        Modifier.fillMaxWidth().heightIn(min = 52.dp).clip(RoundedCornerShape(12.dp))
                            .background(t.card).border(1.dp, t.rule, RoundedCornerShape(12.dp))
                            .padding(horizontal = 14.dp),
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        if (name.isEmpty()) Text("Naam, bijv. donderdagpasta", style = MF.type.body, color = t.muted)
                        BasicTextField(name, { name = it; saved = false }, singleLine = true,
                            textStyle = MF.type.body.copy(color = t.ink), cursorBrush = SolidColor(t.signal),
                            modifier = Modifier.fillMaxWidth())
                    }
                    Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        PrimaryButton(if (saved) "Bewaard" else "Bewaar", {
                            onSave(name.ifBlank { template.name }); saved = true
                        })
                        if (saved) Text("Staat bij je bewaarde maaltijden.", style = MF.type.label,
                            color = t.muted, modifier = Modifier.padding(start = 12.dp))
                    }
                }
            }
        }
        TotalsBar(vm.currentTotals(), vm.missingSlots().map { it.name.lowercase() })
    }
}

/**
 * One candidate. A real radio button with `selectable(Role.RadioButton)`, so
 * TalkBack reports the selection instead of reading out a character.
 */
@Composable
private fun CandidateRow(c: SlotCandidate, selected: Boolean, onSelect: () -> Unit) {
    val t = MF.tokens
    Row(
        Modifier.fillMaxWidth().selectable(selected, onClick = onSelect, role = Role.RadioButton)
            .heightIn(min = 56.dp).padding(horizontal = 8.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null,
            colors = RadioButtonDefaults.colors(selectedColor = t.signal, unselectedColor = t.muted))
        Column(Modifier.weight(1f).padding(start = 8.dp)) {
            Text(c.name, style = MF.type.body, color = t.ink)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(top = 2.dp)) {
                Text(fmt("%.0f g", c.grams), style = MF.type.label, color = t.muted)
                c.promo_text?.takeUnless { it.contains("shelf price") }?.let { Badge(it, strong = true) }
                c.required_quantity?.takeIf { it > 1 }?.let { Badge("koop $it") }
            }
        }
        Text(euro(c.price_eur) ?: "geen prijs", style = MF.type.figureSm,
            color = if (c.price_eur != null) t.ink else t.muted, textAlign = TextAlign.End,
            modifier = Modifier.width(84.dp))
    }
}

/** "100 g ketchup", "4 gekookte eieren": anything from the food type list. */
@Composable
private fun Extras(vm: MacroFinderViewModel) {
    val t = MF.tokens
    val state by vm.state.collectAsState()
    var text by remember { mutableStateOf("") }
    var amount by remember { mutableStateOf("100") }
    val matches = remember(text, state.foodTypes) {
        if (text.length < 2) emptyList()
        else state.foodTypes.filter { it.name.contains(text, ignoreCase = true) }.take(5)
    }
    SectionLabel("Extra's")
    Card(Modifier.padding(horizontal = 12.dp)) {
        Column {
            state.extras.forEach { line ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${line.label} · " + when (line.quantity.unit) {
                        QuantityUnit.GRAMS -> fmt("%.0f g", line.quantity.amount)
                        QuantityUnit.UNITS -> fmt("%.0f stuks", line.quantity.amount)
                    }, style = MF.type.body, color = t.ink, modifier = Modifier.weight(1f))
                    TextAction("Weg", { vm.removeLine(line.id) }, color = t.muted)
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f).heightIn(min = 48.dp), contentAlignment = Alignment.CenterStart) {
                    if (text.isEmpty()) Text("Iets toevoegen, bijv. ketchup", style = MF.type.body, color = t.muted)
                    BasicTextField(text, { text = it }, singleLine = true,
                        textStyle = MF.type.body.copy(color = t.ink), cursorBrush = SolidColor(t.signal),
                        modifier = Modifier.fillMaxWidth())
                }
                Box(Modifier.width(64.dp).heightIn(min = 48.dp), contentAlignment = Alignment.CenterEnd) {
                    BasicTextField(amount, { amount = it.filter(Char::isDigit).take(4) }, singleLine = true,
                        textStyle = MF.type.figureSm.copy(color = t.ink, textAlign = TextAlign.End),
                        cursorBrush = SolidColor(t.signal),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                }
                Text(" g", style = MF.type.label, color = t.muted)
            }
            matches.forEach { ft ->
                Text(
                    "+ ${ft.name}", style = MF.type.body, color = t.signal,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 44.dp).clickable {
                        vm.addExtra(ft.key, amount.toDoubleOrNull() ?: 100.0, QuantityUnit.GRAMS)
                        text = ""
                    }.padding(vertical = 10.dp),
                )
            }
        }
    }
}

/** Rule notes in the author's words. Nothing here blocks anything. */
@Composable
private fun Issues(vm: MacroFinderViewModel) {
    val t = MF.tokens
    val issues = vm.currentIssues()
    if (issues.isEmpty()) return
    Column(Modifier.padding(horizontal = 12.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        issues.forEach { issue ->
            val (prefix, color) = when {
                issue.outcome == RuleOutcome.UNKNOWN -> "Niet te zeggen" to t.muted
                issue.severity == "wrong" -> "Werkt niet" to t.warn
                issue.severity == "note" -> "Goed om te weten" to t.muted
                else -> "Nog niet af" to t.warn
            }
            Card {
                Column {
                    Text(prefix, style = MF.type.labelStrong, color = color)
                    Text(issue.note, style = MF.type.body, color = t.ink, modifier = Modifier.padding(top = 2.dp))
                }
            }
        }
    }
}

/**
 * The pinned total. Unknowns are named, and seed-sourced figures carry the
 * same mark as everywhere else (BRIEF section 9 rule 1).
 */
@Composable
private fun TotalsBar(totals: MealTotals, missing: List<String>) {
    val t = MF.tokens
    Column(Modifier.fillMaxWidth().background(t.card)) {
        Hairline()
        Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text("Totaal", style = MF.type.label, color = t.muted)
                    Text(euro(totals.eur) ?: "nog onbekend", style = MF.type.figure, color = t.ink)
                }
                val mark = if (totals.macrosNeedMarking) "$ESTIMATE_MARK " else ""
                Column(horizontalAlignment = Alignment.End) {
                    Text(totals.proteinG?.let { mark + fmt("%.0f g eiwit", it) } ?: "eiwit onbekend",
                        style = MF.type.figureSm, color = if (totals.macrosNeedMarking) t.muted else t.ink)
                    Text(totals.kcal?.let { mark + fmt("%.0f kcal", it) } ?: "kcal onbekend",
                        style = MF.type.label, color = t.muted)
                }
            }
            // Carbs and fat too: the customiser is where you build a whole
            // meal, and a missing figure shows as "?" rather than hiding the row.
            if (totals.lines.isNotEmpty()) {
                val carbs = totals.carbsG?.let { fmt("%.0f g", it) } ?: "?"
                val fat = totals.fatG?.let { fmt("%.0f g", it) } ?: "?"
                Text("koolhydraten $carbs · vet $fat", style = MF.type.label, color = t.muted,
                    modifier = Modifier.padding(top = 2.dp))
            }
            val notes = listOfNotNull(
                missing.takeIf { it.isNotEmpty() }?.let { "Nog kiezen: ${it.joinToString(", ")}" },
                totals.unpricedLines.takeIf { it.isNotEmpty() }?.let { "Geen prijs voor: ${it.joinToString(", ")}" },
                totals.unknownMacroLines.takeIf { it.isNotEmpty() }
                    ?.let { "Niet alle macro's bekend voor: ${it.joinToString(", ")}" },
                if (totals.macrosNeedMarking) "$ESTIMATE_MARK geschat, niet van het etiket" else null,
            )
            notes.forEach { Text(it, style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 3.dp)) }
        }
    }
}

// -- saved meals ------------------------------------------------------------------

@Composable
fun SavedMealsScreen(vm: MacroFinderViewModel, onBack: () -> Unit, onOpen: (SavedMeal) -> Unit, onDelete: (String) -> Unit) {
    val t = MF.tokens
    val state by vm.state.collectAsState()
    LazyColumn(Modifier.fillMaxSize().background(t.paper), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            TextAction("‹ Terug", onBack, modifier = Modifier.padding(horizontal = 8.dp))
            Text("Bewaarde maaltijden", style = MF.type.display, color = t.ink,
                modifier = Modifier.padding(start = 16.dp, bottom = 8.dp))
        }
        if (state.savedMeals.isEmpty()) {
            item {
                EmptyState("Nog niets bewaard",
                    "Stel een maaltijd samen en tik op Bewaar. Hij rekent zichzelf elke week opnieuw door " +
                        "met de prijzen van dat moment.")
            }
        }
        items(state.savedMeals, key = { it.id }) { meal ->
            val totals = vm.totalsFor(meal)
            Card(Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(meal.name, style = MF.type.title, color = t.ink, modifier = Modifier.weight(1f))
                        Text(euro(totals.eur) ?: "geen prijs", style = MF.type.figureSm, color = t.ink)
                    }
                    Text(meal.lines.joinToString(" · ") { it.label }, style = MF.type.label, color = t.muted,
                        modifier = Modifier.padding(top = 2.dp))
                    Row {
                        TextAction("Openen", { onOpen(meal) })
                        Spacer(Modifier.width(8.dp))
                        TextAction("Verwijderen", { onDelete(meal.id) }, color = t.muted)
                    }
                }
            }
        }
    }
}
