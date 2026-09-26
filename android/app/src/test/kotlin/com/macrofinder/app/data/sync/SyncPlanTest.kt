package com.macrofinder.app.data.sync

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The sync decision. Milestone 17.
 *
 * All of it runs on the JVM in CI, which is the reason the decision is separate
 * from the doing: downloading bytes and running SQL is hard to get subtly
 * wrong, but "should I take a 24 MB file or a 300 KB diff, and is the diff even
 * applicable to what I have?" is exactly the kind of thing that fails quietly
 * on somebody's phone three weeks later.
 *
 * The end-to-end half - applying real SQL to a real SQLite file - is an
 * instrumented test (`androidTest`), which needs an emulator and does not run
 * here. See `android/README.md`.
 */
class SyncPlanTest {

    private fun manifest(
        version: String = "bbb",
        deltas: List<Delta> = emptyList(),
        status: String = "ok",
        schema: Int = APP_SCHEMA_VERSION,
    ) = Manifest(
        schema_version = schema,
        status = status,
        full = FullBuild(version = version, file = "macrofinder-$version.sqlite",
                         sha256 = "deadbeef", bytes = 24_000_000, products = 52_489),
        deltas = deltas,
    )

    private fun delta(from: String, to: String, bytes: Long = 300_000) =
        Delta(from = from, to = to, file = "delta-$from-$to.sqlite",
              sha256 = "cafe", bytes = bytes)

    // -- the three ordinary outcomes ------------------------------------------

    @Test
    fun `a cold install takes the full build`() {
        val plan = planSync(manifest(), localVersion = null)

        assertTrue(plan is SyncPlan.FullDownload)
        assertEquals("no local catalogue yet", (plan as SyncPlan.FullDownload).reason)
    }

    @Test
    fun `an up to date device does nothing at all`() {
        // The whole point of versioning a build by its own content hash: an
        // unchanged catalogue costs one manifest fetch and no download.
        assertEquals(SyncPlan.UpToDate, planSync(manifest(version = "bbb"), "bbb"))
    }

    @Test
    fun `one build behind applies one delta`() {
        val plan = planSync(manifest(deltas = listOf(delta("aaa", "bbb"))), "aaa")

        assertTrue(plan is SyncPlan.ApplyDeltas)
        assertEquals(listOf("aaa" to "bbb"),
            (plan as SyncPlan.ApplyDeltas).deltas.map { it.from to it.to })
    }

    // -- the fallback ---------------------------------------------------------

    @Test
    fun `more than seven deltas behind falls back to a full download`() {
        // PLAN-V2's stated limit, and the acceptance criterion for this
        // milestone. A device that has been offline for two months should not
        // replay two months of diffs to catch up.
        val versions = (0..8).map { "v$it" }
        val deltas = versions.zipWithNext { a, b -> delta(a, b) }

        val plan = planSync(manifest(version = "v8", deltas = deltas), "v0")

        assertTrue("8 hops should fall back, not chain", plan is SyncPlan.FullDownload)
        assertTrue((plan as SyncPlan.FullDownload).reason.contains("more than the 7-hop limit"))
    }

    @Test
    fun `exactly seven deltas behind still chains`() {
        // The boundary, pinned in both directions so nobody "fixes" an
        // off-by-one by making the limit six or eight.
        val versions = (0..7).map { "v$it" }
        val deltas = versions.zipWithNext { a, b -> delta(a, b) }

        val plan = planSync(manifest(version = "v7", deltas = deltas), "v0")

        assertTrue(plan is SyncPlan.ApplyDeltas)
        assertEquals(MAX_DELTA_HOPS, (plan as SyncPlan.ApplyDeltas).deltas.size)
    }

    @Test
    fun `a version no delta starts from falls back rather than failing`() {
        // The common real case today: the publisher keeps one delta, so
        // anything older than one build behind lands here. Falling back is the
        // correct answer, not an error.
        val plan = planSync(manifest(deltas = listOf(delta("aaa", "bbb"))), "ancient")

        assertTrue(plan is SyncPlan.FullDownload)
        assertTrue((plan as SyncPlan.FullDownload).reason.contains("no delta path"))
    }

    @Test
    fun `a chain that stops short of the target falls back`() {
        // Deltas exist but do not reach the published build - a half-pruned
        // release. Applying them would leave the device on a version the
        // manifest does not describe.
        val plan = planSync(
            manifest(version = "ccc", deltas = listOf(delta("aaa", "bbb"))), "aaa",
        )

        assertTrue(plan is SyncPlan.FullDownload)
    }

    @Test
    fun `a cycle in the manifest falls back instead of hanging`() {
        // The manifest comes off the network. A loop in it must fail the sync,
        // not the app.
        val plan = planSync(
            manifest(version = "zzz",
                     deltas = listOf(delta("aaa", "bbb"), delta("bbb", "aaa"))),
            "aaa",
        )

        assertTrue(plan is SyncPlan.FullDownload)
    }

    // -- the kill switch ------------------------------------------------------

    @Test
    fun `a halted publisher stops the sync and says so in Dutch`() {
        // PLAN-V2 section 7. The app keeps showing what it already has; what it
        // must not do is keep fetching as though nothing had changed.
        val plan = planSync(manifest(status = "halted"), localVersion = "aaa")

        assertTrue(plan is SyncPlan.Halted)
        assertTrue((plan as SyncPlan.Halted).message.contains("niet bijgewerkt"))
    }

    @Test
    fun `the kill switch applies to a cold install too`() {
        assertTrue(planSync(manifest(status = "halted"), null) is SyncPlan.Halted)
    }

    // -- parsing --------------------------------------------------------------

    @Test
    fun `a real manifest decodes`() {
        // Byte-for-byte the shape `appdb.write_manifest` produces.
        val json = """
        {
          "deltas": [
            {"bytes": 294912, "file": "delta-7027cf83b7ec2859-9fe8e2c1bc23a55c.sqlite",
             "from": "7027cf83b7ec2859", "sha256": "c749", "to": "9fe8e2c1bc23a55c"}
          ],
          "full": {"bytes": 23928832, "file": "macrofinder-9fe8e2c1bc23a55c.sqlite",
                   "products": 52489, "sha256": "9fe8", "version": "9fe8e2c1bc23a55c"},
          "generated_at": "2026-09-22T13:48:41+00:00",
          "schema_version": 3,
          "status": "ok"
        }
        """.trimIndent()

        val manifest = Json { ignoreUnknownKeys = true }.decodeFromString<Manifest>(json)

        assertEquals("9fe8e2c1bc23a55c", manifest.full.version)
        assertEquals(52_489, manifest.full.products)
        assertEquals(1, manifest.deltas.size)
        assertEquals(SyncPlan.UpToDate, planSync(manifest, "9fe8e2c1bc23a55c"))
    }

    @Test
    fun `a manifest gaining a field does not break an older app`() {
        // The publisher and the app ship separately; a field added on one side
        // must not stop the other syncing at all.
        val json = """{"status":"ok","full":{"version":"bbb"},"deltas":[],"future":42}"""

        val manifest = Json { ignoreUnknownKeys = true }.decodeFromString<Manifest>(json)

        assertEquals(SyncPlan.UpToDate, planSync(manifest, "bbb"))
    }

    @Test
    fun `an empty manifest asks for a full download rather than claiming success`() {
        assertTrue(planSync(Manifest(), localVersion = "aaa") is SyncPlan.FullDownload)
    }

    // -- schema compatibility ------------------------------------------------

    @Test
    fun `a newer catalogue schema is not installed, and says the app needs updating`() {
        assertEquals(SyncPlan.Incompatible(newer = true),
            planSync(manifest(schema = APP_SCHEMA_VERSION + 1), localVersion = null))
    }

    @Test
    fun `an older published schema is left alone rather than installed over a newer app`() {
        assertEquals(SyncPlan.Incompatible(newer = false),
            planSync(manifest(schema = APP_SCHEMA_VERSION - 1), localVersion = "aaa"))
    }

    @Test
    fun `a catalogue left by an older app is replaced whole, never patched`() {
        val plan = planSync(manifest(deltas = listOf(delta("aaa", "bbb"))), localVersion = "aaa",
            localSchema = APP_SCHEMA_VERSION - 1)
        assertTrue(plan is SyncPlan.FullDownload)
    }

    @Test
    fun `a halted manifest's own message is what the user sees`() {
        val plan = planSync(
            manifest(status = "halted").copy(message = "Op verzoek van een winkel gestopt."), "aaa",
        )
        assertEquals(SyncPlan.Halted("Op verzoek van een winkel gestopt."), plan)
    }
}
