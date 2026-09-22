package com.macrofinder.app.data.sync

import kotlinx.serialization.Serializable

/**
 * What the sync should do next, decided from the manifest and what is on disk.
 *
 * Deliberately pure: no Android imports, no I/O, no coroutines. Everything that
 * can be decided rather than performed lives here, so the part that can be
 * wrong in an interesting way runs in CI on the JVM. What is left on the
 * Android side is downloading bytes and running SQL, which is hard to get
 * subtly wrong and easy to see fail.
 *
 * The published artifacts are described in `src/bonusrank/appdb.py`. A build's
 * version is its own content hash, which is what makes "am I up to date?" a
 * string comparison rather than a download.
 */

@Serializable
data class Manifest(
    val schema_version: Int = 0,
    /**
     * PLAN-V2 section 7's kill switch. Anything other than "ok" means the
     * project has been asked to stop publishing and the app should say so
     * rather than keep serving whatever it last downloaded as if it were live.
     */
    val status: String = "ok",
    val generated_at: String = "",
    val full: FullBuild = FullBuild(),
    val deltas: List<Delta> = emptyList(),
)

@Serializable
data class FullBuild(
    val version: String = "",
    val file: String = "",
    val sha256: String = "",
    val bytes: Long = 0,
    val products: Int = 0,
)

@Serializable
data class Delta(
    val from: String = "",
    val to: String = "",
    val file: String = "",
    val sha256: String = "",
    val bytes: Long = 0,
)

/**
 * How many deltas the app will chain before giving up and taking a full copy.
 *
 * Seven is PLAN-V2's number and it is a bandwidth decision, not a correctness
 * one: each delta costs a request and a verification, and past a handful the
 * full download is both smaller and simpler. A device that has been offline for
 * two months should not replay two months of diffs.
 */
const val MAX_DELTA_HOPS = 7

sealed interface SyncPlan {
    /** The local copy already is the published build. Costs nothing. */
    data object UpToDate : SyncPlan

    /**
     * Apply these in order. Each one's `from` is the previous one's `to`, and
     * the first one's `from` is what is on disk - checked when the plan is
     * built, so the applying code never has to wonder.
     */
    data class ApplyDeltas(val deltas: List<Delta>) : SyncPlan

    /** Take the whole thing: no local copy, no usable chain, or too far behind. */
    data class FullDownload(val build: FullBuild, val reason: String) : SyncPlan

    /** The publisher has asked the app to stop. [message] is for the user. */
    data class Halted(val message: String) : SyncPlan
}

/**
 * Decide what to do, given a manifest and the version currently on disk.
 *
 * [localVersion] is null when there is no local catalogue at all, which is the
 * cold-install case.
 */
fun planSync(manifest: Manifest, localVersion: String?): SyncPlan {
    if (manifest.status != "ok") {
        return SyncPlan.Halted(
            "De catalogus wordt op dit moment niet bijgewerkt. " +
                "Je ziet de gegevens van de laatste keer."
        )
    }

    val target = manifest.full
    if (target.version.isBlank()) {
        return SyncPlan.FullDownload(target, "the manifest names no build")
    }
    if (localVersion == target.version) return SyncPlan.UpToDate
    if (localVersion == null) {
        return SyncPlan.FullDownload(target, "no local catalogue yet")
    }

    val chain = deltaChain(manifest.deltas, from = localVersion, to = target.version)
    return when {
        chain == null ->
            SyncPlan.FullDownload(target, "no delta path from $localVersion")
        chain.size > MAX_DELTA_HOPS ->
            SyncPlan.FullDownload(
                target,
                "${chain.size} deltas behind, more than the $MAX_DELTA_HOPS-hop limit",
            )
        else -> SyncPlan.ApplyDeltas(chain)
    }
}

/**
 * Walk `from` to `to` through the available deltas, or null if it cannot be done.
 *
 * Stops at [MAX_DELTA_HOPS] + 1 rather than following a chain forever: a
 * manifest is downloaded from the network, and a cycle in it would otherwise
 * hang the sync rather than fail it. Returning the over-long chain instead of
 * null lets the caller say *why* it is falling back.
 */
internal fun deltaChain(deltas: List<Delta>, from: String, to: String): List<Delta>? {
    val byFrom = deltas.associateBy { it.from }
    val path = mutableListOf<Delta>()
    val seen = mutableSetOf(from)
    var cursor = from

    while (cursor != to) {
        val next = byFrom[cursor] ?: return null
        if (!seen.add(next.to)) return null       // a cycle; take the full build
        path += next
        cursor = next.to
        if (path.size > MAX_DELTA_HOPS) return path
    }
    return path
}
