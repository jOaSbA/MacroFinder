package com.macrofinder.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.DealSort
import com.macrofinder.app.data.catalogue.DealTier
import com.macrofinder.app.ui.euro
import com.macrofinder.app.ui.metricText
import com.macrofinder.app.ui.quantityText
import com.macrofinder.app.ui.validityText
import com.macrofinder.app.ui.theme.MF
import com.macrofinder.app.ui.theme.chainColor
import com.macrofinder.app.ui.theme.chainName
import com.macrofinder.app.ui.theme.tierColor

/**
 * One deal. ~92dp, so fifty fit in two scrolls on a 6" phone.
 *
 *   chain rule | image | name, size / badges / the sorted-on figure | price
 *
 * The coloured figure bottom-left is always the metric being sorted on, so
 * changing the sort changes what sits there: one place to look.
 */
@Composable
fun DealRow(
    deal: Deal,
    tier: DealTier?,
    sort: DealSort,
    today: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val t = MF.tokens
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(t.card)
            .clickable(onClick = onClick)
            .height(IntrinsicSize.Min),
    ) {
        Box(Modifier.width(3.dp).fillMaxHeight().background(chainColor(deal.chain)))
        Row(
            Modifier.padding(start = 9.dp, end = 12.dp, top = 12.dp, bottom = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ProductImage(deal.imageUrl, 64.dp)
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(
                    deal.name, style = MF.type.rowTitle, color = t.ink,
                    maxLines = 2, overflow = TextOverflow.Ellipsis,
                )
                Text(
                    listOfNotNull(chainName(deal.chain), sizeText(deal)).joinToString(" · "),
                    style = MF.type.label, color = t.muted, maxLines = 1,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Row(
                    Modifier.padding(top = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    deal.promoText?.let { Badge(it, strong = true) }
                    quantityText(deal)?.let { Badge(it) }
                    if (deal.isUpcomingOn(today)) validityText(deal, today)?.let { Badge(it) }
                }
                Text(
                    metricText(deal, sort),
                    style = MF.type.figureSm,
                    color = tierColor(tier, deal.macrosEstimated && sort != DealSort.DISCOUNT),
                    modifier = Modifier.padding(top = 6.dp),
                    maxLines = 1,
                )
            }
            Column(horizontalAlignment = Alignment.End, modifier = Modifier.padding(start = 8.dp)) {
                Text(euro(deal.price) ?: "?", style = MF.type.figureSm.copy(fontSize = MF.type.title.fontSize),
                    color = t.ink)
                val shelf = deal.shelfPrice
                if (shelf != null && deal.price != null && shelf > deal.price + 0.005) {
                    Text(euro(shelf)!!, style = MF.type.label, color = t.muted,
                        textDecoration = TextDecoration.LineThrough)
                }
            }
        }
    }
}

private fun sizeText(deal: Deal): String? {
    val text = deal.unitText?.trim().orEmpty()
    // Jumbo's unit text is often the whole product name again; say nothing
    // rather than repeat it.
    if (text.isBlank() || text.length > 18) return null
    return text
}
