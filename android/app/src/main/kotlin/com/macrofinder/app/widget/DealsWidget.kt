package com.macrofinder.app.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.macrofinder.app.MainActivity
import com.macrofinder.app.data.catalogue.AndroidSqlRunner
import com.macrofinder.app.data.catalogue.CatalogueReader
import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.data.catalogue.DealQuery
import com.macrofinder.app.data.catalogue.selectDeals
import com.macrofinder.app.data.settings.SettingsStore
import com.macrofinder.app.ui.fmt
import com.macrofinder.app.ui.theme.chainColor
import java.time.LocalDate

/**
 * Milestone 40: the five best protein deals for my stores and diet, on the
 * home screen. The same ranking as the deal list's default sort. Refreshed by
 * the sync worker after a new catalogue arrives, not on a timer.
 */
class DealsWidget : GlanceAppWidget() {

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val deals = topDeals(context)
        provideContent { Content(deals) }
    }

    private suspend fun topDeals(context: Context): List<Deal>? = runCatching {
        val store = com.macrofinder.app.data.sync.CatalogueStore(context)
        if (!store.exists()) return null
        val prefs = SettingsStore(context).current()
        val all = store.open().use { CatalogueReader(AndroidSqlRunner(it)).deals() }
        selectDeals(all.filter(prefs::allows), DealQuery(chains = prefs.stores), LocalDate.now().toString())
            .map { it.deal }
            .filter { it.eurPer100gProtein != null }
            .distinctBy { it.foodType ?: it.id }
            .take(5)
    }.getOrNull()

    @Composable
    private fun Content(deals: List<Deal>?) {
        Column(
            GlanceModifier.fillMaxSize().background(PAPER).cornerRadius(16.dp).padding(12.dp)
                .clickable(actionStartActivity<MainActivity>()),
        ) {
            Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Goedkoop eiwit", style = TextStyle(color = INK, fontSize = 15.sp, fontWeight = FontWeight.Bold),
                    modifier = GlanceModifier.defaultWeight())
                Text("per 100 g eiwit", style = TextStyle(color = MUTED, fontSize = 12.sp))
            }
            Spacer(GlanceModifier.height(6.dp))
            when {
                deals == null -> Text("Open de app om de catalogus te laden.", style = TextStyle(color = MUTED, fontSize = 13.sp))
                deals.isEmpty() -> Text("Nu niets voor jouw winkels.", style = TextStyle(color = MUTED, fontSize = 13.sp))
                else -> deals.forEach { Row(it) }
            }
        }
    }

    @Composable
    private fun Row(deal: Deal) {
        Row(GlanceModifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(GlanceModifier.size(8.dp).cornerRadius(4.dp).background(ColorProvider(chainColor(deal.chain)))) {}
            Spacer(GlanceModifier.width(8.dp))
            Text(deal.name, maxLines = 1, style = TextStyle(color = INK, fontSize = 13.sp),
                modifier = GlanceModifier.defaultWeight())
            val mark = if (deal.macrosEstimated) "≈ " else ""
            Text(mark + fmt("€%.2f", deal.eurPer100gProtein ?: 0.0),
                style = TextStyle(color = INK, fontSize = 13.sp, fontWeight = FontWeight.Bold))
        }
    }

    companion object {
        private val PAPER = ColorProvider(Color(0xFFF5F6F4))
        private val INK = ColorProvider(Color(0xFF151A17))
        private val MUTED = ColorProvider(Color(0xFF5B635E))

        /** Called by the sync worker after a new catalogue is installed. */
        suspend fun refresh(context: Context) = DealsWidget().updateAll(context)
    }
}

class DealsWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = DealsWidget()
}
