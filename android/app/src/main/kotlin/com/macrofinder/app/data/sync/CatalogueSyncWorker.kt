package com.macrofinder.app.data.sync

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.macrofinder.app.BuildConfig
import java.util.concurrent.TimeUnit

/**
 * The background catalogue sync. Milestone 17.
 *
 * Unmetered network only, by constraint rather than by good intentions: a full
 * build is ~24 MB, and downloading that over somebody's mobile data because
 * they happened to open the app on a train is the kind of thing an app only
 * gets to do once.
 *
 * The manual "nu verversen" path deliberately drops that constraint, because
 * the user asking for it is the whole point - but it takes the delta path when
 * one is available, so the usual cost of asking is a few hundred kilobytes.
 */
class CatalogueSyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val syncer = CatalogueSyncer(
            store = CatalogueStore(applicationContext),
            manifestUrl = BuildConfig.MANIFEST_URL,
            assetBaseUrl = BuildConfig.ASSET_BASE_URL,
        )

        return when (val outcome = syncer.sync { setProgressAsync(it.toData()) }) {
            is SyncOutcome.UpToDate -> Result.success(
                Data.Builder().putString(KEY_STATE, "up_to_date").build()
            )
            is SyncOutcome.Installed -> Result.success(
                Data.Builder()
                    .putString(KEY_STATE, "installed")
                    .putString(KEY_VERSION, outcome.version)
                    .putLong(KEY_BYTES, outcome.bytesTransferred)
                    .putBoolean(KEY_VIA_DELTA, outcome.viaDelta)
                    .build()
            )
            // Not a retry: the publisher has asked the app to stop, and
            // retrying on a schedule is exactly what it is asking it not to do.
            is SyncOutcome.Halted -> Result.success(
                Data.Builder()
                    .putString(KEY_STATE, "halted")
                    .putString(KEY_MESSAGE, outcome.message)
                    .build()
            )
            // Retry rather than fail: the commonest cause is a connection that
            // went away mid-download, and nothing was installed, so trying
            // again later is free and correct.
            is SyncOutcome.Failed -> Result.retry()
        }
    }

    private fun SyncProgress.toData(): Data = Data.Builder()
        .putString(KEY_LABEL, label)
        .putFloat(KEY_FRACTION, fraction)
        .putLong(KEY_TOTAL_BYTES, totalBytes)
        .build()

    companion object {
        const val PERIODIC_NAME = "catalogue-sync"
        const val ONE_OFF_NAME = "catalogue-sync-now"

        const val KEY_STATE = "state"
        const val KEY_VERSION = "version"
        const val KEY_BYTES = "bytes"
        const val KEY_VIA_DELTA = "via_delta"
        const val KEY_MESSAGE = "message"
        const val KEY_LABEL = "label"
        const val KEY_FRACTION = "fraction"
        const val KEY_TOTAL_BYTES = "total_bytes"

        /**
         * Daily, not hourly. The catalogue is published weekly, so a daily
         * check finds something new one run in seven and costs one small
         * manifest fetch the other six - the whole reason a build's version is
         * its own content hash.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<CatalogueSyncWorker>(1, TimeUnit.DAYS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.UNMETERED)
                        .setRequiresStorageNotLow(true)
                        .build()
                )
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC_NAME, ExistingPeriodicWorkPolicy.KEEP, request,
            )
        }

        /** "Nu verversen". Runs on whatever connection there is. */
        fun syncNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<CatalogueSyncWorker>()
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                ONE_OFF_NAME, ExistingWorkPolicy.KEEP, request,
            )
        }
    }
}
