package com.macrofinder.app.ui

import java.util.Locale

/**
 * Number formatting in the app's own locale, never the device's. Otherwise
 * the same price reads "€2,54" on a Dutch phone and "€2.54" on an English one,
 * inside the same Dutch sentence.
 */
val AppLocale: Locale = Locale.forLanguageTag("nl-NL")

fun fmt(pattern: String, vararg args: Any?): String =
    String.format(AppLocale, pattern, *args)

fun euro(value: Double?): String? = value?.let { fmt("€%.2f", it) }

private val MONTHS = listOf("jan", "feb", "mrt", "apr", "mei", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec")

/** "2026-09-24" -> "24 sep". Falls back to the input if it isn't a date. */
fun shortDate(iso: String?): String? {
    if (iso == null) return null
    val parts = iso.take(10).split("-")
    val month = parts.getOrNull(1)?.toIntOrNull() ?: return iso
    val day = parts.getOrNull(2)?.toIntOrNull() ?: return iso
    return "$day ${MONTHS.getOrElse(month - 1) { "?" }}"
}

/** "1.234" with a Dutch thousands separator. */
fun count(n: Int): String = fmt("%,d", n)
