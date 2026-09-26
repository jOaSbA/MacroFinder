package com.macrofinder.app.data.catalogue

import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * Buy or wait, from a product's promo cycle and today's date. Milestone 22.
 *
 * Mirrors `history.cycle_hint` in Python, case for case (both test suites
 * use the same examples). It lives on the phone because it depends on the
 * date: computed at build time it would rewrite rows every day.
 */
enum class CycleHint { BUY, WAIT }

const val WAIT_WITHIN_DAYS = 14

fun cycleHint(cycleDays: Int?, lastStart: String?, onPromo: Boolean, today: LocalDate): CycleHint? {
    if (cycleDays == null || lastStart == null) return null
    if (onPromo) return CycleHint.BUY
    val start = runCatching { LocalDate.parse(lastStart) }.getOrNull() ?: return null
    val until = ChronoUnit.DAYS.between(today, start.plusDays(cycleDays.toLong()))
    return when {
        until > WAIT_WITHIN_DAYS -> CycleHint.BUY
        until > -cycleDays -> CycleHint.WAIT
        else -> null
    }
}

/** The sentence under the hint, e.g. "Elke ~4 weken in de aanbieding, laatst 3 weken geleden". */
fun cycleSentence(cycleDays: Int, lastStart: String, today: LocalDate): String {
    val weeks = Math.round(cycleDays / 7.0).coerceAtLeast(1)
    val ago = runCatching { ChronoUnit.DAYS.between(LocalDate.parse(lastStart), today) }
        .getOrNull() ?: return "Elke ~$weeks weken in de aanbieding"
    val agoText = when {
        ago < 7 -> "deze week"
        ago < 14 -> "vorige week"
        else -> "${ago / 7} weken geleden"
    }
    return "Elke ~$weeks ${if (weeks == 1L) "week" else "weken"} in de aanbieding, laatst $agoText"
}
