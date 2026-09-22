package com.macrofinder.app.ui

import androidx.work.WorkInfo
import com.macrofinder.app.data.sync.CatalogueSyncWorker

/**
 * What the catalogue sync is doing, in a shape a screen can render.
 *
 * Kept apart from `UiState` because the sync outlives the screen: WorkManager
 * runs it whether or not the app is open, and the UI is a window onto it rather
 * than its owner.
 *
 * [fromWorkInfo] is pure, so the mapping from WorkManager's generic states to
 * something a person can read is testable on the JVM - which matters because
 * getting it wrong shows the user a spinner that never stops.
 */
data class CatalogueSyncState(
    val running: Boolean = false,
    val label: String? = null,
    /** 0..1, or null when the step has no measurable progress. */
    val fraction: Float? = null,
    val message: String? = null,
    /** True when the publisher has asked the app to stop updating. */
    val halted: Boolean = false,
) {
    companion object {
        fun fromWorkInfo(info: WorkInfo?): CatalogueSyncState {
            if (info == null) return CatalogueSyncState()

            return when (info.state) {
                WorkInfo.State.RUNNING -> {
                    val label = info.progress.getString(CatalogueSyncWorker.KEY_LABEL)
                    val fraction = info.progress.getFloat(CatalogueSyncWorker.KEY_FRACTION, -1f)
                    CatalogueSyncState(
                        running = true,
                        label = label ?: "Bijwerken",
                        fraction = fraction.takeIf { it >= 0f },
                    )
                }

                // Enqueued but not started is usually the unmetered constraint
                // waiting for wifi. Saying so beats a silent nothing.
                WorkInfo.State.ENQUEUED -> CatalogueSyncState(
                    running = true,
                    label = "Wacht op wifi",
                )

                WorkInfo.State.SUCCEEDED -> when (
                    info.outputData.getString(CatalogueSyncWorker.KEY_STATE)
                ) {
                    "installed" -> CatalogueSyncState(
                        message = installedMessage(info),
                    )
                    "halted" -> CatalogueSyncState(
                        halted = true,
                        message = info.outputData.getString(CatalogueSyncWorker.KEY_MESSAGE),
                    )
                    // "up_to_date" says nothing, deliberately. A person who did
                    // not ask does not need to be told the catalogue was
                    // already current.
                    else -> CatalogueSyncState()
                }

                WorkInfo.State.FAILED -> CatalogueSyncState(
                    message = "Bijwerken is niet gelukt. Het probeert het later opnieuw.",
                )

                else -> CatalogueSyncState()
            }
        }

        private fun installedMessage(info: WorkInfo): String {
            val bytes = info.outputData.getLong(CatalogueSyncWorker.KEY_BYTES, 0)
            val viaDelta = info.outputData.getBoolean(CatalogueSyncWorker.KEY_VIA_DELTA, false)
            val size = when {
                bytes >= 1_000_000 -> fmt("%.1f MB", bytes / 1_000_000.0)
                else -> fmt("%d kB", bytes / 1000)
            }
            return if (viaDelta) "Catalogus bijgewerkt ($size)"
            else "Catalogus gedownload ($size)"
        }
    }
}
