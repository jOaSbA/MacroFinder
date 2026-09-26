package com.macrofinder.app.ui

import androidx.work.Data
import androidx.work.WorkInfo
import com.macrofinder.app.data.sync.CatalogueSyncWorker
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Turning WorkManager's generic states into something a person can read.
 *
 * Worth testing on its own because the failure is invisible in code review and
 * obvious to a user: get it wrong and the app shows a progress bar that never
 * finishes, or says nothing at all while a 24 MB download is running.
 *
 * Runs on the JVM. `WorkInfo` and `Data` are plain value classes, so this needs
 * no emulator.
 */
class CatalogueSyncStateTest {

    private fun workInfo(
        state: WorkInfo.State,
        output: Data = Data.EMPTY,
        progress: Data = Data.EMPTY,
    ) = WorkInfo(
        /* id = */ UUID.randomUUID(),
        /* state = */ state,
        /* tags = */ emptySet(),
        /* outputData = */ output,
        /* progress = */ progress,
        /* runAttemptCount = */ 0,
        /* generation = */ 0,
    )

    @Test
    fun `no work at all says nothing`() {
        val sync = CatalogueSyncState.fromWorkInfo(null)

        assertTrue(!sync.running)
        assertNull(sync.message)
    }

    @Test
    fun `a running sync reports its own label and fraction`() {
        val sync = CatalogueSyncState.fromWorkInfo(
            workInfo(
                WorkInfo.State.RUNNING,
                progress = Data.Builder()
                    .putString(CatalogueSyncWorker.KEY_LABEL, "Catalogus downloaden")
                    .putFloat(CatalogueSyncWorker.KEY_FRACTION, 0.25f)
                    .build(),
            )
        )

        assertTrue(sync.running)
        assertEquals("Catalogus downloaden", sync.label)
        assertEquals(0.25f, sync.fraction!!, 0.001f)
    }

    @Test
    fun `a step with no measurable progress reports no fraction rather than zero`() {
        // A bar pinned at 0% reads as stuck. Indeterminate is the honest shape
        // for "this step has no size to divide by".
        val sync = CatalogueSyncState.fromWorkInfo(workInfo(WorkInfo.State.RUNNING))

        assertTrue(sync.running)
        assertNull(sync.fraction)
    }

    @Test
    fun `a manual refresh waiting for a connection says so`() {
        val sync = CatalogueSyncState.fromWorkInfo(workInfo(WorkInfo.State.ENQUEUED), oneOff = true)

        assertTrue(sync.running)
        assertEquals("Wacht op verbinding", sync.label)
    }

    @Test
    fun `a scheduled periodic sync says nothing between runs`() {
        // The bug: periodic work is ENQUEUED between every run, so the banner
        // said "wacht op wifi" permanently, on wifi.
        val sync = CatalogueSyncState.fromWorkInfo(workInfo(WorkInfo.State.ENQUEUED), oneOff = false)

        assertTrue(!sync.running)
        assertNull(sync.label)
    }

    @Test
    fun `an up to date result says nothing at all`() {
        // Somebody who did not ask does not need telling the catalogue was
        // already current.
        val sync = CatalogueSyncState.fromWorkInfo(
            workInfo(
                WorkInfo.State.SUCCEEDED,
                output = Data.Builder()
                    .putString(CatalogueSyncWorker.KEY_STATE, "up_to_date").build(),
            )
        )

        assertTrue(!sync.running)
        assertNull(sync.message)
    }

    @Test
    fun `a delta install reports the size that was actually transferred`() {
        val sync = CatalogueSyncState.fromWorkInfo(
            workInfo(
                WorkInfo.State.SUCCEEDED,
                output = Data.Builder()
                    .putString(CatalogueSyncWorker.KEY_STATE, "installed")
                    .putLong(CatalogueSyncWorker.KEY_BYTES, 294_912)
                    .putBoolean(CatalogueSyncWorker.KEY_VIA_DELTA, true)
                    .build(),
            )
        )

        assertEquals("Catalogus bijgewerkt (294 kB)", sync.message)
    }

    @Test
    fun `a full download says downloaded rather than updated`() {
        // The distinction is the user's data allowance, so the wording carries
        // it: 24 MB is a download, 300 kB is an update.
        val sync = CatalogueSyncState.fromWorkInfo(
            workInfo(
                WorkInfo.State.SUCCEEDED,
                output = Data.Builder()
                    .putString(CatalogueSyncWorker.KEY_STATE, "installed")
                    .putLong(CatalogueSyncWorker.KEY_BYTES, 23_928_832)
                    .putBoolean(CatalogueSyncWorker.KEY_VIA_DELTA, false)
                    .build(),
            )
        )

        // A comma, not a point: the app formats in its own Dutch locale rather
        // than the device's. This test found that by failing on a Dutch
        // machine while expecting a point.
        assertEquals("Catalogus gedownload (23,9 MB)", sync.message)
    }

    @Test
    fun `a halted publisher is surfaced and hides the refresh button`() {
        val sync = CatalogueSyncState.fromWorkInfo(
            workInfo(
                WorkInfo.State.SUCCEEDED,
                output = Data.Builder()
                    .putString(CatalogueSyncWorker.KEY_STATE, "halted")
                    .putString(CatalogueSyncWorker.KEY_MESSAGE, "Even niet beschikbaar")
                    .build(),
            )
        )

        assertTrue(sync.halted)
        assertEquals("Even niet beschikbaar", sync.message)
    }

    @Test
    fun `a failure says it will try again, because it will`() {
        // The worker returns Result.retry() on failure, so this sentence is a
        // statement of fact rather than reassurance.
        val sync = CatalogueSyncState.fromWorkInfo(workInfo(WorkInfo.State.FAILED))

        assertTrue(sync.message!!.contains("later opnieuw"))
        assertTrue(!sync.running)
    }
}
