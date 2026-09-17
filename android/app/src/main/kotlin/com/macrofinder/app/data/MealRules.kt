package com.macrofinder.app.data

/**
 * Does this combination actually make a dish? Milestone 13.
 *
 * Python authors and validates the rules (`data/seed/templates.yaml`,
 * `seed.py::_validate_template`); this evaluates them, because the user
 * composes the meal here and the answer has to be instant.
 *
 * Two things this deliberately does NOT do:
 *
 * It never blocks a choice. A violated rule produces a [RuleIssue] carrying the
 * author's own note, and the user cooks whatever they like. That is the same
 * product decision that made the app a browsable list rather than an optimiser,
 * and it is also the only behaviour that survives a rule the author got
 * slightly wrong.
 *
 * It never guesses. Evaluation is THREE-valued - a rule can come out
 * [RuleOutcome.UNKNOWN], and unknown reaches the screen as unknown rather than
 * quietly passing. This is the rule-language twin of `_price_composition`'s
 * unpriced-poisons-the-total rule, and of `_verdict` refusing to pick a winner
 * when only one side is priced.
 */

enum class RuleOutcome { SATISFIED, VIOLATED, UNKNOWN }

/** A rule worth telling the user about: violated, or undecidable. */
data class RuleIssue(
    val outcome: RuleOutcome,
    /** "incomplete" | "wrong" | "note" - these must not render the same. */
    val severity: String,
    /** The author's own words. The only text the user sees about this rule. */
    val note: String,
)

/**
 * Every rule of [template] that the user should hear about, in seed order.
 *
 * A satisfied rule produces nothing - silence is the normal case, and a screen
 * that lists rules the meal already passes is a screen nobody reads.
 */
fun checkCombination(template: TemplateEntry, lines: List<MealLine>): List<RuleIssue> =
    template.rules.mapNotNull { rule ->
        val outcome = evaluate(rule, lines)
        if (outcome == RuleOutcome.SATISFIED) null
        else RuleIssue(outcome, rule.severity, rule.note)
    }

fun evaluate(rule: TemplateRule, lines: List<MealLine>): RuleOutcome {
    val trigger = matches(rule.`when`, lines)
    // The rule simply does not apply to this meal. Not a pass the user earned,
    // but indistinguishable from one as far as the screen is concerned.
    if (trigger == RuleOutcome.VIOLATED) return RuleOutcome.SATISFIED
    if (trigger == RuleOutcome.UNKNOWN) return RuleOutcome.UNKNOWN

    val results = rule.requires.map { matches(it, lines) }
    val present = results.count { it == RuleOutcome.SATISFIED }
    val undecided = results.count { it == RuleOutcome.UNKNOWN }

    return when (rule.kind) {
        // "Pesto needs cheese OR greens": at least min_satisfied of them.
        "requirement" -> when {
            present >= rule.min_satisfied -> RuleOutcome.SATISFIED
            // Enough undecided lines that the requirement COULD still be met.
            present + undecided >= rule.min_satisfied -> RuleOutcome.UNKNOWN
            else -> RuleOutcome.VIOLATED
        }
        // "Pesto and grated young cheese do not go together."
        "incompatible" -> when {
            present > 0 -> RuleOutcome.VIOLATED
            undecided > 0 -> RuleOutcome.UNKNOWN
            else -> RuleOutcome.SATISFIED
        }
        // A kind this build does not know about. Saying "fine" about a rule we
        // cannot read would be a lie; unknown is the honest answer, and the
        // author's note still reaches the user.
        else -> RuleOutcome.UNKNOWN
    }
}

/**
 * Is this predicate present in the meal?
 *
 * SATISFIED when some line definitely matches. UNKNOWN when none does, but a
 * line the app cannot identify might. VIOLATED (read as "definitely absent")
 * only when every line is identified and none matches.
 *
 * The unknown case is not hypothetical: milestone 14 lets the user add a raw
 * catalogue SKU with no food type, and a rule about sauces genuinely cannot
 * know whether that unnamed thing is one.
 */
fun matches(predicate: Predicate, lines: List<MealLine>): RuleOutcome {
    // An empty predicate matches nothing. The loader rejects one, so this is a
    // guard against a hand-edited or future-schema file, not a real case.
    if (predicate.slot == null && predicate.food_types.isEmpty()) return RuleOutcome.VIOLATED

    var undecided = false
    for (line in lines) {
        if (predicate.slot != null && line.slotKey != predicate.slot) continue

        if (predicate.food_types.isEmpty()) {
            // Slot-only predicate: "is this slot filled at all?" A line in the
            // slot answers it whether or not we can identify the food.
            return RuleOutcome.SATISFIED
        }
        val foodType = line.foodType
        if (foodType == null) {
            // Could be one of the named food types; nothing here can tell.
            undecided = true
            continue
        }
        if (foodType in predicate.food_types) return RuleOutcome.SATISFIED
    }
    return if (undecided) RuleOutcome.UNKNOWN else RuleOutcome.VIOLATED
}

/** Required slots with nothing chosen yet. Not a rule - just an unfinished form. */
fun unfilledRequiredSlots(template: TemplateEntry, lines: List<MealLine>): List<TemplateSlot> {
    val filled = lines.mapNotNull { it.slotKey }.toSet()
    return template.slots.filter { it.required && it.key !in filled }
}
