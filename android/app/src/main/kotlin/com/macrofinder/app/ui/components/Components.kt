package com.macrofinder.app.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.macrofinder.app.data.catalogue.PricePoint
import com.macrofinder.app.ui.euro
import com.macrofinder.app.ui.shortDate
import com.macrofinder.app.ui.theme.MF

/** 1dp rule in the Rule token. The rhythm does most of the separating. */
@Composable
fun Hairline(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(1.dp).background(MF.tokens.rule))
}

/**
 * A row of text buttons with the active one underlined in Signal. Used for
 * the sort control and the bottom navigation: DESIGN.md wants the function
 * visible, not behind an icon.
 */
@Composable
fun <T> TextTabs(
    options: List<T>,
    selected: T,
    label: (T) -> String,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    scrollable: Boolean = true,
    evenly: Boolean = false,
) {
    val t = MF.tokens
    val row = if (scrollable) modifier.horizontalScroll(rememberScrollState()) else modifier
    Row(row.padding(horizontal = if (evenly) 0.dp else 8.dp)) {
        options.forEach { option ->
            val active = option == selected
            Column(
                modifier = Modifier
                    .then(if (evenly) Modifier.weight(1f) else Modifier)
                    .selectable(selected = active, role = Role.Tab, onClick = { onSelect(option) })
                    .heightIn(min = 48.dp)
                    .padding(horizontal = 8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    label(option),
                    style = MF.type.labelStrong,
                    color = if (active) t.ink else t.muted,
                    maxLines = 1,
                    softWrap = false,
                    modifier = Modifier.padding(top = 12.dp, bottom = 8.dp),
                )
                Box(
                    Modifier.height(2.dp).width(if (active) 24.dp else 0.dp)
                        .background(if (active) t.signal else t.paper, RoundedCornerShape(1.dp))
                )
            }
        }
    }
}

/** A filter chip. Outlined in Rule when off, ink-filled when on. */
@Composable
fun FilterChip(text: String, selected: Boolean, onClick: () -> Unit, leadingColor: androidx.compose.ui.graphics.Color? = null) {
    val t = MF.tokens
    Row(
        modifier = Modifier
            .heightIn(min = 48.dp)
            .selectable(selected = selected, role = Role.Checkbox, onClick = onClick)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .background(if (selected) t.ink else t.card)
                .border(BorderStroke(1.dp, if (selected) t.ink else t.rule), RoundedCornerShape(8.dp))
                .padding(horizontal = 12.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (leadingColor != null) {
                Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(leadingColor))
                Spacer(Modifier.width(6.dp))
            }
            Text(text, style = MF.type.labelStrong, color = if (selected) t.paper else t.ink)
        }
    }
}

@Composable
fun ChipRow(content: @Composable () -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) { content() }
}

/** Outlined label: "1+1 gratis", "koop 2". Never a filled chip. */
@Composable
fun Badge(text: String, strong: Boolean = false) {
    val t = MF.tokens
    Text(
        text,
        style = MF.type.label,
        color = if (strong) t.ink else t.muted,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier
            .border(1.dp, if (strong) t.ink.copy(alpha = 0.55f) else t.rule, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

@Composable
fun ProductImage(url: String?, size: Dp, modifier: Modifier = Modifier, radius: Dp = 8.dp) {
    val t = MF.tokens
    Box(
        modifier.size(size).clip(RoundedCornerShape(radius)).background(if (t.dark) t.paper else t.paper),
        contentAlignment = Alignment.Center,
    ) {
        if (url != null) {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current).data(url).crossfade(false).build(),
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier.size(size).padding(size / 10),
            )
        }
    }
}

/** An instruction, not a mood (DESIGN.md 5). */
@Composable
fun EmptyState(title: String, body: String, action: String? = null, onAction: () -> Unit = {}) {
    val t = MF.tokens
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 40.dp)) {
        Text(title, style = MF.type.title, color = t.ink)
        Text(body, style = MF.type.body, color = t.muted, modifier = Modifier.padding(top = 6.dp))
        if (action != null) {
            TextAction(action, onAction, modifier = Modifier.padding(top = 12.dp))
        }
    }
}

/** A plain text button in Signal, 48dp tall. */
@Composable
fun TextAction(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, color: androidx.compose.ui.graphics.Color? = null) {
    Box(
        modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick)
            .padding(horizontal = 8.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        Text(text, style = MF.type.labelStrong.copy(fontSize = MF.type.body.fontSize),
            color = color ?: MF.tokens.signal)
    }
}

/** A solid primary button. Used sparingly: save a meal, follow. */
@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val t = MF.tokens
    Box(
        modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(10.dp)).background(t.signal)
            .clickable(onClick = onClick).padding(horizontal = 20.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = MF.type.labelStrong.copy(fontSize = MF.type.body.fontSize), color = t.onSignal)
    }
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text, style = MF.type.labelStrong, color = MF.tokens.muted,
        modifier = modifier.padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 8.dp),
    )
}

/** A flat white card on paper: 14dp radius, no shadow. */
@Composable
fun Card(modifier: Modifier = Modifier, padding: PaddingValues = PaddingValues(16.dp), content: @Composable () -> Unit) {
    Box(
        modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(MF.tokens.card).padding(padding)
    ) { content() }
}

/**
 * Weekly low price, drawn as a line. The first and last prices are written
 * next to it, so the line is never the only carrier of the information.
 */
@Composable
fun Sparkline(points: List<PricePoint>, modifier: Modifier = Modifier) {
    if (points.size < 2) return
    val t = MF.tokens
    val prices = points.map { it.price }
    val lo = prices.min()
    val hi = prices.max()
    val description = "Laagste prijs per week, van ${euro(prices.first())} op " +
        "${shortDate(points.first().week)} tot ${euro(prices.last())} nu"
    Column(modifier.semantics { contentDescription = description }) {
        Canvas(Modifier.fillMaxWidth().height(56.dp).padding(vertical = 6.dp)) {
            val span = (hi - lo).takeIf { it > 0 } ?: 1.0
            val step = size.width / (points.size - 1)
            val path = Path()
            prices.forEachIndexed { i, p ->
                val x = i * step
                val y = (size.height * (1 - (p - lo) / span)).toFloat()
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            drawPath(path, t.ink, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
            val lastY = (size.height * (1 - (prices.last() - lo) / span)).toFloat()
            drawCircle(t.signal, radius = 4.dp.toPx(), center = Offset(size.width, lastY))
        }
        Row(Modifier.fillMaxWidth()) {
            Text("${shortDate(points.first().week)} · ${euro(prices.first())}", style = MF.type.label, color = t.muted)
            Spacer(Modifier.weight(1f))
            Text("laagst ${euro(lo)} · nu ${euro(prices.last())}", style = MF.type.label, color = t.muted,
                textAlign = TextAlign.End)
        }
    }
}
