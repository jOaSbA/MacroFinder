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
import com.macrofinder.app.data.catalogue.AndroidSqlRunner
import com.macrofinder.app.data.catalogue.CatalogueReader
import com.macrofinder.app.data.following.FollowingStore
import com.macrofinder.app.data.following.PromoNotifier
import com.macrofinder.app.data.following.alertKey
import com.macrofinder.app.data.following.promoAlerts
import com.macrofinder.app.data.following.targetAlerts
import com.macrofinder.app.data.following.targetKey
import com.macrofinder.app.data.following.digestWeek
import com.macrofinder.app.data.following.weeklyDigest
import com.macrofinder.app.data.settings.SettingsStore
import java.time.LocalDate
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
        val store = CatalogueStore(applicationContext)
        val syncer = CatalogueSyncer(
            store = store,
            manifestUrl = BuildConfig.MANIFEST_URL,
            assetBaseUrl = BuildConfig.ASSET_BASE_URL,
        )

        return when (val outcome = syncer.sync { setProgressAsync(it.toData()) }) {
            is SyncOutcome.UpToDate -> {
                HaltState.clear(applicationContext)
                runCatching { store.ensureSearchIndex() }
                Result.success(Data.Builder().putString(KEY_STATE, "up_to_date").build())
            }
            is SyncOutcome.Installed -> {
                HaltState.clear(applicationContext)
                setProgressAsync(SyncProgress("Zoekindex bijwerken", -1f, 0).toData())
                runCatching { store.ensureSearchIndex(force = true) }
                runCatching { announceFollowedPromos(store) }
                runCatching { announceDigest(store) }
                Result.success(
                Data.Builder()
                    .putString(KEY_STATE, "installed")
                    .putString(KEY_VERSION, outcome.version)
                    .putLong(KEY_BYTES, outcome.bytesTransferred)
                    .putBoolean(KEY_VIA_DELTA, outcome.viaDelta)
                    .build()
                )
            }
            // Not a retry: the publisher has asked the app to stop, and
            // retrying on a schedule is exactly what it is asking it not to do.
            is SyncOutcome.Halted -> {
                HaltState.set(applicationContext, outcome.message)
                Result.success(
                    Data.Builder()
                        .putString(KEY_STATE, "halted")
                        .putString(KEY_MESSAGE, outcome.message)
                        .build()
                )
            }
            // Not a failure either: nothing to retry until the app or the
            // publisher changes.
            is SyncOutcome.Incompatible -> {
                runCatching { store.ensureSearchIndex() }
                Result.success(
                    Data.Builder().putString(KEY_STATE, "incompatible")
                        .putBoolean(KEY_NEWER, outcome.newer).build()
                )
            }
            // Retry rather than fail: the commonest cause is a connection that
            // went away mid-download, and nothing was installed, so trying
            // again later is free and correct.
            is SyncOutcome.Failed -> Result.retry()
        }
    }

    /** Milestone 26: tell the user when something they follow went on offer. */
    private suspend fun announceFollowedPromos(store: CatalogueStore) {
        val following = FollowingStore(applicationContext)
        val followed = following.followedNow()
        if (followed.isEmpty()) return
        val deals = store.open().use { CatalogueReader(AndroidSqlRunner(it)).dealsFor(followed) }
        val today = LocalDate.now().toString()
        val fresh = promoAlerts(followed, deals, following.notified(), today)
        if (fresh.isNotEmpty()) {
            PromoNotifier.post(applicationContext, fresh)
            following.markNotified(fresh.map(::alertKey))
        }
        // Milestone 34: price targets, checked on the same rows.
        val crossed = targetAlerts(following.targetsNow(), deals, following.notified(), today)
        if (crossed.isNotEmpty()) {
            PromoNotifier.postTargets(applicationContext, crossed)
            following.markNotified(crossed.map(::targetKey))
        }
    }

    /** Milestone 33: the weekly digest, if it's on and hasn't gone out this week. */
    private suspend fun announceDigest(store: CatalogueStore) {
        val settings = SettingsStore(applicationContext)
        val prefs = settings.current()
        if (!prefs.weeklyDigest) return
        val today = LocalDate.now()
        val deals = store.open().use { CatalogueReader(AndroidSqlRunner(it)).deals() }
        val top = weeklyDigest(deals, prefs, today, settings.lastDigest())
        if (top.isEmpty()) return
        PromoNotifier.postDigest(applicationContext, top)
        settings.markDigest(digestWeek(today))
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
        const val KEY_NEWER = "newer"
        const val KEY_LABEL = "label"
        const val KEY_FRACTION = "fraction"
        const val KEY_TOTAL_BYTES = "total_bytes"

        /**
         * Every 12 hours, the same rhythm the data is published on. A run with
         * nothing new costs one small manifest fetch, because a build's version
         * is its own content hash.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<CatalogueSyncWorker>(12, TimeUnit.HOURS)
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
