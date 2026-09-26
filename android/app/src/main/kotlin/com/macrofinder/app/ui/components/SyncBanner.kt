package com.macrofinder.app.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.macrofinder.app.ui.CatalogueSyncState
import com.macrofinder.app.ui.theme.MF

/**
 * One line about the catalogue sync. Shows nothing when there is nothing to
 * say: a banner that is always there stops being read.
 */
@Composable
fun SyncBanner(sync: CatalogueSyncState, installed: Boolean, onRefresh: () -> Unit) {
    val t = MF.tokens
    val text = when {
        sync.running -> sync.label
        sync.message != null -> sync.message
        !installed -> "Je ziet een korte lijst. De hele catalogus (±25 MB) komt binnen " +
            "zodra je op wifi bent."
        else -> null
    } ?: return

    Card(modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(text, style = MF.type.body.copy(fontSize = MF.type.label.fontSize * 1.1f),
                    color = t.muted, modifier = Modifier.weight(1f))
                if (!sync.running && !sync.halted) {
                    TextAction(if (installed) "Nu verversen" else "Nu downloaden", onRefresh,
                        modifier = Modifier.padding(start = 8.dp))
                }
            }
            if (sync.running) {
                // Determinate where the size is known. Faking a fraction would
                // be worse than admitting a step has none.
                val fraction = sync.fraction
                if (fraction != null) {
                    LinearProgressIndicator(progress = { fraction }, color = t.signal,
                        trackColor = t.rule, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                } else {
                    LinearProgressIndicator(color = t.signal, trackColor = t.rule,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                }
            }
        }
    }
}
