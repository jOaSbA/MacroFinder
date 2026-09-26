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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.catalogue.Alternative
import com.macrofinder.app.data.catalogue.CycleHint
import com.macrofinder.app.data.following.targetPresets
import com.macrofinder.app.ui.components.FilterChip
import androidx.compose.foundation.horizontalScroll
import com.macrofinder.app.data.catalogue.ProductDetail
import com.macrofinder.app.data.catalogue.cycleHint
import com.macrofinder.app.data.catalogue.cycleSentence
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.ESTIMATE_MARK
import com.macrofinder.app.ui.StripRow
import com.macrofinder.app.ui.components.Badge
import com.macrofinder.app.ui.components.Card
import com.macrofinder.app.ui.components.Hairline
import com.macrofinder.app.ui.components.ProductImage
import com.macrofinder.app.ui.components.Sparkline
import com.macrofinder.app.ui.components.TextAction
import com.macrofinder.app.ui.euro
import com.macrofinder.app.ui.historyText
import com.macrofinder.app.ui.macroStrip
import com.macrofinder.app.ui.proteinQualityNote
import com.macrofinder.app.ui.quantityText
import com.macrofinder.app.ui.theme.MF
import com.macrofinder.app.ui.theme.chainColor
import com.macrofinder.app.ui.theme.chainName
import com.macrofinder.app.ui.validityText
import com.macrofinder.app.ui.wasteText
import java.time.LocalDate
import kotlin.math.roundToInt

/**
 * One product. Milestone 24: image, macros with where they came from, the
 * four metrics, the price history, the cycle hint, required quantity and the
 * waste-adjusted price.
 */
@Composable
fun ProductScreen(
    vm: CatalogueViewModel,
    onBack: () -> Unit,
    onFollow: (String, Boolean) -> Unit,
    onOpen: (String) -> Unit = {},
) {
    val t = MF.tokens
    val detail by vm.detail.collectAsState()
    val followed by vm.followed.collectAsState()
    val targets by vm.targets.collectAsState()

    Column(Modifier.fillMaxSize().background(t.paper)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            TextAction("‹ Terug", onBack)
            Spacer(Modifier.weight(1f))
            val d = detail
            if (d != null) {
                val on = d.deal.id in followed
                TextAction(if (on) "Gevolgd ✓" else "Volg", { onFollow(d.deal.id, !on) },
                    color = if (on) t.muted else t.signal)
            }
        }
        val d = detail
        if (d == null) {
            Text("Laden…", style = MF.type.body, color = t.muted, modifier = Modifier.padding(16.dp))
            return
        }
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(horizontal = 12.dp).padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Header(d)
            PriceCard(d, vm.today())
            StripCard(d)
            val now = d.todayPer100gProtein
            if (d.deal.id in followed && now != null) {
                TargetCard(now, targets[d.deal.id], d.deal.macrosEstimated) { vm.setTarget(d.deal.id, it) }
            }
            if (d.alternatives.isNotEmpty()) AlternativesCard(d.alternatives, d.deal.macrosEstimated, onOpen)
            CycleCard(d)
            if (d.history.size >= 2) {
                Card {
                    Column {
                        Text("Laagste prijs per week", style = MF.type.labelStrong, color = t.muted)
                        Sparkline(d.history, Modifier.padding(top = 4.dp))
                    }
                }
            }
            Text(
                "Prijzen en afbeelding van ${chainName(d.deal.chain)}. MacroFinder is niet " +
                    "verbonden aan de winkel; controleer de prijs in de winkel.",
                style = MF.type.label, color = t.muted, modifier = Modifier.padding(horizontal = 4.dp, vertical = 8.dp),
            )
        }
    }
}

/**
 * Milestone 34: a price target on a followed product, in protein terms.
 * Presets rather than a number field: three taps cover what people set.
 */
@Composable
private fun TargetCard(now: Double, target: Double?, estimated: Boolean, onSet: (Double?) -> Unit) {
    val t = MF.tokens
    val mark = if (estimated) "$ESTIMATE_MARK " else ""
    val options = (targetPresets(now) + listOfNotNull(target)).distinct().sortedDescending()
    Card {
        Column {
            Text("Doelprijs", style = MF.type.labelStrong, color = t.muted)
            Text(
                target?.let { "Je krijgt een melding als 100 g eiwit $mark${euro(it)} of minder kost. Nu: $mark${euro(now)}." }
                    ?: "Krijg een melding als 100 g eiwit goedkoper wordt dan nu ($mark${euro(now)}).",
                style = MF.type.body, color = t.ink, modifier = Modifier.padding(top = 4.dp),
            )
            Row(
                Modifier.horizontalScroll(rememberScrollState()).padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                options.forEach { value ->
                    // The percentage keeps "€1,69 per 100 g eiwit" from reading as a pack price.
                    val pct = ((1 - value / now) * 100).roundToInt()
                    val label = if (pct > 0) "${euro(value)} (−$pct%)" else euro(value)!!
                    FilterChip(label, target == value, { onSet(if (target == value) null else value) })
                }
                if (target != null) FilterChip("Uit", false, { onSet(null) })
            }
        }
    }
}

/** Milestone 31: the same food for less protein money, tap to open. */
@Composable
private fun AlternativesCard(alternatives: List<Alternative>, estimated: Boolean, onOpen: (String) -> Unit) {
    val t = MF.tokens
    Card(padding = PaddingValues(vertical = 12.dp)) {
        Column {
            Text("Goedkoper voor hetzelfde eiwit", style = MF.type.labelStrong, color = t.muted,
                modifier = Modifier.padding(horizontal = 16.dp))
            alternatives.forEachIndexed { i, alt ->
                if (i > 0) Hairline(Modifier.padding(start = 72.dp))
                val deal = alt.deal
                Row(
                    Modifier.fillMaxWidth().clickable { onOpen(deal.id) }
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ProductImage(deal.imageUrl, 44.dp, radius = 8.dp)
                    Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                        Text(deal.name, style = MF.type.body, color = t.ink, maxLines = 2,
                            overflow = TextOverflow.Ellipsis)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(chainColor(deal.chain)))
                            Text(
                                listOfNotNull(chainName(deal.chain), euro(deal.price),
                                    deal.promoText?.takeIf { deal.lane == "promo" }).joinToString(" · "),
                                style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 6.dp),
                            )
                        }
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        // Estimated macros on either side make the saving an estimate too.
                        val mark = if (deal.macrosEstimated || estimated) "$ESTIMATE_MARK " else ""
                        Text("$mark${euro(alt.savingPer100gProtein)} minder", style = MF.type.labelStrong, color = t.ink)
                        Text("per 100 g eiwit", style = MF.type.label, color = t.muted)
                    }
                }
            }
        }
    }
}

@Composable
private fun Header(d: ProductDetail) {
    val t = MF.tokens
    Card {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
            ProductImage(d.deal.imageUrl, 180.dp, radius = 12.dp)
            Text(d.deal.name, style = MF.type.title, color = t.ink,
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp))
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(chainColor(d.deal.chain)))
                Text(
                    listOfNotNull(chainName(d.deal.chain), d.deal.brand, d.deal.unitText?.takeIf { it.length <= 24 },
                        d.foodTypeName).distinct().joinToString(" · "),
                    style = MF.type.label, color = t.muted, modifier = Modifier.padding(start = 6.dp),
                )
            }
        }
    }
}

@Composable
private fun PriceCard(d: ProductDetail, today: String) {
    val t = MF.tokens
    val deal = d.deal
    Card {
        Column {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(euro(deal.price) ?: "Geen prijs", style = MF.type.figure.copy(fontSize = MF.type.display.fontSize),
                    color = t.ink)
                val shelf = d.shelfLanePrice ?: deal.shelfPrice
                if (shelf != null && deal.price != null && shelf > deal.price + 0.005) {
                    Text("normaal ${euro(shelf)}", style = MF.type.label, color = t.muted,
                        textDecoration = TextDecoration.LineThrough,
                        modifier = Modifier.padding(start = 10.dp, bottom = 4.dp))
                }
            }
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                deal.promoText?.let { Badge(it, strong = true) }
                quantityText(deal)?.let { Badge(it) }
                validityText(deal, today)?.let { Badge(it) }
                if (deal.isPersonal) Badge("persoonlijk")
            }
            if (deal.requiredQuantity > 1 && deal.price != null) {
                // BRIEF section 9 rule 3: a multi-buy means several in the fridge.
                Text("Je betaalt ${euro(deal.price * deal.requiredQuantity)} voor ${deal.requiredQuantity} stuks.",
                    style = MF.type.body, color = t.ink, modifier = Modifier.padding(top = 10.dp))
            }
            if (deal.referenceInflated == true) {
                Text("De normale prijs ging kort voor deze actie omhoog. Let op de prijs zelf, " +
                    "niet het kortingspercentage.",
                    style = MF.type.body, color = t.warn, modifier = Modifier.padding(top = 10.dp))
            }
        }
    }
}

/** The macro strip: the app's one bold element (DESIGN.md 3.2). */
@Composable
private fun StripCard(d: ProductDetail) {
    val t = MF.tokens
    val strip = macroStrip(d)
    Card {
        Column {
            strip.provenance?.let {
                Text(it, style = MF.type.label, color = t.muted, modifier = Modifier.padding(bottom = 8.dp))
            }
            Hairline()
            strip.top.forEach { StripLine(it) }
            Hairline()
            strip.money.forEach { StripLine(it) }
            Hairline()
            Text(
                historyText(d.deal) ?: "Nog te weinig prijsgeschiedenis om te zeggen of dit goedkoop is",
                style = MF.type.body, color = if (d.deal.cheapestInWeeks != null) t.ink else t.muted,
                modifier = Modifier.padding(top = 10.dp),
            )
            strip.secondary?.let {
                Text(it, style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 6.dp))
            }
            proteinQualityNote(d.proteinQuality)?.let {
                Text(it, style = MF.type.label, color = t.muted, modifier = Modifier.padding(top = 8.dp))
            }
            wasteText(d.deal)?.let {
                Text(it, style = MF.type.body, color = t.warn, modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}

@Composable
private fun StripLine(row: StripRow) {
    val t = MF.tokens
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(row.label, style = MF.type.body, color = t.ink, modifier = Modifier.weight(1f))
        Text(
            row.value ?: "onbekend",
            style = if (row.value != null) MF.type.figure else MF.type.body,
            color = when {
                row.value == null -> t.muted
                row.estimated -> t.muted
                else -> t.ink
            },
        )
    }
}

@Composable
private fun CycleCard(d: ProductDetail) {
    val t = MF.tokens
    val deal = d.deal
    val today = LocalDate.now()
    val onPromo = deal.lane != "shelf" && deal.isActiveOn(today.toString())
    val hint = cycleHint(deal.promoCycleDays, deal.lastPromoStart, onPromo, today) ?: return
    Card {
        Column {
            Text(
                when (hint) {
                    CycleHint.BUY -> if (onPromo) "Kopen: nu in de aanbieding" else "Kopen als je het nodig hebt"
                    CycleHint.WAIT -> "Wachten: de volgende aanbieding komt er waarschijnlijk aan"
                },
                style = MF.type.rowTitle, color = if (hint == CycleHint.WAIT) t.warn else t.signal,
            )
            Text(cycleSentence(deal.promoCycleDays!!, deal.lastPromoStart!!, today),
                style = MF.type.body, color = t.muted, modifier = Modifier.padding(top = 4.dp))
        }
    }
}
