package com.macrofinder.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Rule evaluation. Pure JVM, no Android framework - this runs in CI.
 *
 * The two tests that matter most are the ones named after the user's own
 * examples, and the ones that pin down three-valued evaluation: a rule that
 * cannot be decided must come out UNKNOWN and reach the screen as such, never
 * quietly pass.
 */
class MealRulesTest {

    private fun slotLine(slot: String, foodType: String?) = MealLine(
        id = "slot:$slot", slotKey = slot, foodType = foodType,
        label = foodType ?: "something", quantity = Quantity(100.0),
    )

    private fun extra(foodType: String?) = MealLine(
        id = "extra:${foodType ?: "?"}", slotKey = null, foodType = foodType,
        label = foodType ?: "something", quantity = Quantity(50.0),
    )

    /** The user's own pesto rule: needs cheese OR greens, not one named slot. */
    private val pestoNeedsBody = TemplateRule(
        kind = "requirement",
        `when` = Predicate(slot = "sauce", food_types = listOf("pesto_groen")),
        requires = listOf(Predicate(slot = "cheese"), Predicate(slot = "greens")),
        min_satisfied = 1,
        severity = "incomplete",
        note = "Pesto alleen op pasta is droog.",
    )

    private val tomatoNeedsMeat = TemplateRule(
        kind = "requirement",
        `when` = Predicate(slot = "sauce", food_types = listOf("pastasaus_tomaat")),
        requires = listOf(Predicate(slot = "meat")),
        min_satisfied = 1,
        severity = "incomplete",
        note = "Tomatensaus met vlees is af zoals het is.",
    )

    private val pestoNotWithYoungCheese = TemplateRule(
        kind = "incompatible",
        `when` = Predicate(slot = "sauce", food_types = listOf("pesto_groen")),
        requires = listOf(Predicate(slot = "cheese", food_types = listOf("kaas_geraspt_30"))),
        severity = "wrong",
        note = "Pesto zit al vol kaas en olie.",
    )

    private val template = TemplateEntry(
        key = "pasta", name = "Pasta", meal_kind = "meal",
        slots = listOf(
            TemplateSlot("pasta", "Soort pasta", true, 100.0, listOf("pasta_droog")),
            TemplateSlot("sauce", "Saus", true, 150.0, listOf("pesto_groen", "pastasaus_tomaat")),
            TemplateSlot("meat", "Vlees", true, 110.0, listOf("kipfilet_rauw")),
            TemplateSlot("cheese", "Kaas", false, 25.0, listOf("kaas_geraspt_30")),
            TemplateSlot("greens", "Groente", false, 80.0, listOf("rucola")),
        ),
        rules = listOf(pestoNeedsBody, tomatoNeedsMeat, pestoNotWithYoungCheese),
    )

    // -- the user's two stated examples ------------------------------------

    @Test
    fun `pesto on its own is flagged as unfinished`() {
        val lines = listOf(slotLine("pasta", "pasta_droog"), slotLine("sauce", "pesto_groen"))
        assertEquals(RuleOutcome.VIOLATED, evaluate(pestoNeedsBody, lines))
    }

    @Test
    fun `pesto with greens is satisfied - cheese is not the only way`() {
        val lines = listOf(
            slotLine("pasta", "pasta_droog"),
            slotLine("sauce", "pesto_groen"),
            slotLine("greens", "rucola"),
        )
        assertEquals(RuleOutcome.SATISFIED, evaluate(pestoNeedsBody, lines))
    }

    @Test
    fun `tomato sauce with meat needs nothing more`() {
        val lines = listOf(
            slotLine("pasta", "pasta_droog"),
            slotLine("sauce", "pastasaus_tomaat"),
            slotLine("meat", "kipfilet_rauw"),
        )
        assertEquals(RuleOutcome.SATISFIED, evaluate(tomatoNeedsMeat, lines))
        assertTrue(checkCombination(template, lines).isEmpty())
    }

    @Test
    fun `tomato sauce without meat is flagged`() {
        val lines = listOf(slotLine("pasta", "pasta_droog"), slotLine("sauce", "pastasaus_tomaat"))
        assertEquals(RuleOutcome.VIOLATED, evaluate(tomatoNeedsMeat, lines))
    }

    // -- the rule must not misfire -----------------------------------------

    @Test
    fun `a rule whose trigger is absent does not fire at all`() {
        val lines = listOf(slotLine("sauce", "pastasaus_tomaat"), slotLine("meat", "kipfilet_rauw"))
        assertEquals(RuleOutcome.SATISFIED, evaluate(pestoNeedsBody, lines))
    }

    @Test
    fun `an incompatible pair fires only when both sides are present`() {
        val pestoOnly = listOf(slotLine("sauce", "pesto_groen"))
        val pestoAndCheese = pestoOnly + slotLine("cheese", "kaas_geraspt_30")

        assertEquals(RuleOutcome.SATISFIED, evaluate(pestoNotWithYoungCheese, pestoOnly))
        assertEquals(RuleOutcome.VIOLATED, evaluate(pestoNotWithYoungCheese, pestoAndCheese))
    }

    @Test
    fun `min_satisfied of two needs both, not either`() {
        val needsBoth = pestoNeedsBody.copy(min_satisfied = 2)
        val one = listOf(slotLine("sauce", "pesto_groen"), slotLine("cheese", "kaas_geraspt_30"))
        val both = one + slotLine("greens", "rucola")

        assertEquals(RuleOutcome.VIOLATED, evaluate(needsBoth, one))
        assertEquals(RuleOutcome.SATISFIED, evaluate(needsBoth, both))
    }

    // -- three-valued: unknown must never pass as fine ---------------------

    @Test
    fun `an unidentified line makes a food_types rule undecidable, not satisfied`() {
        // Milestone 14 lets the user add a raw catalogue SKU with no food type.
        // A rule about pesto genuinely cannot know what that thing is.
        val lines = listOf(slotLine("sauce", null))
        assertEquals(RuleOutcome.UNKNOWN, evaluate(pestoNeedsBody, lines))
    }

    @Test
    fun `an unidentified extra can leave a requirement undecided`() {
        val lines = listOf(slotLine("sauce", "pesto_groen"), extra(null))
        // The unnamed extra might be a cheese; nothing here can say it is not.
        val cheeseByFoodType = pestoNeedsBody.copy(
            requires = listOf(Predicate(food_types = listOf("kaas_geraspt_30"))),
        )
        assertEquals(RuleOutcome.UNKNOWN, evaluate(cheeseByFoodType, lines))
    }

    @Test
    fun `a slot-only predicate is decidable even when the food is unidentified`() {
        // "Is the cheese slot filled?" does not depend on knowing what the
        // cheese is, so this stays a definite yes.
        val lines = listOf(slotLine("sauce", "pesto_groen"), slotLine("cheese", null))
        assertEquals(RuleOutcome.SATISFIED, evaluate(pestoNeedsBody, lines))
    }

    @Test
    fun `an unknown rule kind is reported as unknown, never as fine`() {
        val alien = pestoNeedsBody.copy(kind = "some_future_kind")
        val lines = listOf(slotLine("sauce", "pesto_groen"))
        assertEquals(RuleOutcome.UNKNOWN, evaluate(alien, lines))
    }

    @Test
    fun `an unknown outcome still reaches the user with the authored note`() {
        val lines = listOf(slotLine("sauce", null))
        val issue = checkCombination(template, lines).first()
        assertEquals(RuleOutcome.UNKNOWN, issue.outcome)
        assertEquals("Pesto alleen op pasta is droog.", issue.note)
    }

    // -- what reaches the screen -------------------------------------------

    @Test
    fun `satisfied rules produce no issues - silence is the normal case`() {
        val lines = listOf(
            slotLine("pasta", "pasta_droog"),
            slotLine("sauce", "pesto_groen"),
            slotLine("greens", "rucola"),
        )
        assertEquals(emptyList<RuleIssue>(), checkCombination(template, lines))
    }

    @Test
    fun `severity is carried through so wrong and unfinished do not read alike`() {
        val lines = listOf(slotLine("sauce", "pesto_groen"), slotLine("cheese", "kaas_geraspt_30"))
        val severities = checkCombination(template, lines).map { it.severity }
        assertEquals(listOf("wrong"), severities)
    }

    @Test
    fun `unfilled required slots are reported separately from rule issues`() {
        val lines = listOf(slotLine("pasta", "pasta_droog"))
        val missing = unfilledRequiredSlots(template, lines).map { it.key }
        assertEquals(listOf("sauce", "meat"), missing)
    }
}
