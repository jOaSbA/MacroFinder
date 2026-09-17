package com.macrofinder.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

sealed class SnapshotResult {
    data class Success(val snapshot: ExportSnapshot) : SnapshotResult()
    data class Failure(val message: String) : SnapshotResult()
}

/**
 * Fetches the JSON snapshot the GitHub Actions refresh workflow publishes.
 * No backend of its own - `dataUrl` is a plain `raw.githubusercontent.com`
 * file, refreshed on a schedule server-side (see
 * `.github/workflows/refresh-data.yml` in the Python half of this repo).
 */
class DataRepository(
    private val dataUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
) {
    suspend fun fetchSnapshot(): SnapshotResult = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder().url(dataUrl).build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    return@withContext SnapshotResult.Failure("HTTP ${response.code}")
                }
                val body = response.body?.string()
                    ?: return@withContext SnapshotResult.Failure("empty response body")
                SnapshotResult.Success(parseSnapshot(body))
            }
        } catch (e: Exception) {
            SnapshotResult.Failure(e.message ?: e.toString())
        }
    }
}
