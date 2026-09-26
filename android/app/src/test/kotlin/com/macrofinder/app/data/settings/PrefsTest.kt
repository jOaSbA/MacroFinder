package com.macrofinder.app.data.settings

import com.macrofinder.app.data.catalogue.Deal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Milestone 32. Pure JVM. */
class PrefsTest {
    private fun deal(chain: String, vararg tags: String) =
        Deal(id = "$chain:1", chain = chain, name = "x", buckets = tags.toSet())

    private val kwark = deal("ah", "vegetarisch")
    private val tofu = deal("ah", "vegetarisch", "vegan")
    private val kip = deal("ah")

    @Test
    fun `by default everything is allowed`() {
        assertTrue(listOf(kwark, tofu, kip, deal("aldi")).all(Prefs()::allows))
    }

    @Test
    fun `vegetarian keeps kwark and tofu and drops chicken`() {
        val p = Prefs(diet = Diet.VEGETARISCH)
        assertEquals(listOf(kwark, tofu), listOf(kwark, tofu, kip).filter(p::allows))
    }

    @Test
    fun `vegan keeps only tofu`() {
        assertEquals(listOf(tofu), listOf(kwark, tofu, kip).filter(Prefs(diet = Diet.VEGAN)::allows))
    }

    @Test
    fun `a hidden store is hidden`() {
        assertFalse(Prefs(stores = setOf("ah", "jumbo")).allows(deal("aldi")))
    }

    @Test
    fun `chains picked in a list stay within my stores`() {
        val p = Prefs(stores = setOf("ah", "jumbo"))
        assertEquals(setOf("ah", "jumbo"), p.chainsFor(emptySet()))
        assertEquals(setOf("jumbo"), p.chainsFor(setOf("jumbo", "aldi")))
        assertEquals(setOf("ah", "jumbo"), p.chainsFor(setOf("aldi")))
    }

    @Test
    fun `the last store can't be turned off`() {
        val one = Prefs(stores = setOf("ah"))
        assertEquals(one, one.toggleStore("ah"))
        assertEquals(setOf("ah", "aldi"), one.toggleStore("aldi").stores)
    }
}
