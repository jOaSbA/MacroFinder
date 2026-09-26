package com.macrofinder.app.data.sync

import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * Downloads and installs the published catalogue. Milestone 17.
 *
 * All the deciding happens in [planSync], which is pure and tested on the JVM.
 * What is left here is fetching bytes, checking them, and handing them to
 * [CatalogueStore] - each step small enough to read in one go.
 *
 * **Nothing is installed before its hash matches the manifest.** The manifest
 * is the only thing taken on trust, and it is small enough to re-fetch. A
 * truncated download, a proxy serving an error page as a 200, or an asset
 * replaced mid-sync all produce bytes that do not hash to what was promised,
 * and all end the same way: the existing catalogue stays, and the sync says it
 * failed.
 */
class CatalogueSyncer(
    private val store: CatalogueStore,
    private val manifestUrl: String,
    private val assetBaseUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun sync(onProgress: (SyncProgress) -> Unit = {}): SyncOutcome =
        withContext(Dispatchers.IO) {
            try {
                onProgress(SyncProgress("Bijwerken controleren", 0f))
                val manifest = json.decodeFromString<Manifest>(get(manifestUrl))

                when (val plan = planSync(manifest, store.localVersion(), store.schemaVersion())) {
                    is SyncPlan.UpToDate -> SyncOutcome.UpToDate
                    is SyncPlan.Halted -> SyncOutcome.Halted(plan.message)
                    is SyncPlan.Incompatible -> SyncOutcome.Incompatible(plan.newer)
                    is SyncPlan.ApplyDeltas -> applyAll(plan.deltas, onProgress)
                    is SyncPlan.FullDownload -> full(plan, onProgress)
                }
            } catch (e: Exception) {
                SyncOutcome.Failed(e.message ?: e.toString())
            }
        }

    private fun full(plan: SyncPlan.FullDownload, onProgress: (SyncProgress) -> Unit): SyncOutcome {
        val staged = store.stagingFile(plan.build.file)
        onProgress(SyncProgress("Catalogus downloaden", 0f, plan.build.bytes))
        val bytes = download(plan.build.file, staged, plan.build.bytes, onProgress)

        if (!verify(staged, plan.build.sha256)) {
            staged.delete()
            return SyncOutcome.Failed("de gedownloade catalogus klopt niet, opnieuw proberen")
        }
        onProgress(SyncProgress("Installeren", 1f))
        store.installFull(staged, plan.build.version)
        return SyncOutcome.Installed(plan.build.version, bytes, viaDelta = false)
    }

    private fun applyAll(
        deltas: List<Delta>,
        onProgress: (SyncProgress) -> Unit,
    ): SyncOutcome {
        var transferred = 0L
        for ((index, delta) in deltas.withIndex()) {
            val staged = store.stagingFile(delta.file)
            onProgress(
                SyncProgress(
                    "Update ${index + 1} van ${deltas.size}",
                    index.toFloat() / deltas.size,
                    delta.bytes,
                )
            )
            transferred += download(delta.file, staged, delta.bytes, onProgress)

            if (!verify(staged, delta.sha256)) {
                staged.delete()
                // Deliberately not falling through to a full download here. The
                // caller asked for a delta sync on what may be a metered or
                // slow connection; turning a failed 300 KB update into a silent
                // 24 MB one is not a decision to make on their behalf.
                return SyncOutcome.Failed("een update klopt niet, opnieuw proberen")
            }
            store.applyDelta(staged, delta.to)
            staged.delete()
        }
        return SyncOutcome.Installed(deltas.last().to, transferred, viaDelta = true)
    }

    private fun download(
        file: String,
        into: File,
        expectedBytes: Long,
        onProgress: (SyncProgress) -> Unit,
    ): Long {
        into.delete()
        val request = Request.Builder().url("$assetBaseUrl/$file").build()
        client.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "HTTP ${response.code} voor $file" }
            val body = response.body ?: error("lege response voor $file")
            body.byteStream().use { input ->
                into.outputStream().use { output ->
                    val buffer = ByteArray(1 shl 16)
                    var total = 0L
                    while (true) {
                        val read = input.read(buffer)
                        if (read <= 0) break
                        output.write(buffer, 0, read)
                        total += read
                        if (expectedBytes > 0) {
                            onProgress(
                                SyncProgress(
                                    "Downloaden",
                                    (total.toFloat() / expectedBytes).coerceIn(0f, 1f),
                                    expectedBytes,
                                )
                            )
                        }
                    }
                }
            }
        }
        return into.length()
    }

    private fun get(url: String): String {
        client.newCall(Request.Builder().url(url).build()).execute().use { response ->
            check(response.isSuccessful) { "HTTP ${response.code} voor het manifest" }
            return response.body?.string() ?: error("leeg manifest")
        }
    }

    private fun verify(file: File, expected: String): Boolean =
        expected.isNotBlank() && sha256(file).equals(expected, ignoreCase = true)

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1 shl 16)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}

data class SyncProgress(
    val label: String,
    val fraction: Float,
    val totalBytes: Long = 0,
)

sealed interface SyncOutcome {
    data object UpToDate : SyncOutcome
    data class Installed(
        val version: String,
        val bytesTransferred: Long,
        val viaDelta: Boolean,
    ) : SyncOutcome
    data class Halted(val message: String) : SyncOutcome
    data class Incompatible(val newer: Boolean) : SyncOutcome
    data class Failed(val message: String) : SyncOutcome
}
