package com.macrofinder.app.ui

import java.util.Locale

/**
 * The locale every number in this app is formatted in.
 *
 * Explicitly Dutch, never the device's. The app's copy is Dutch throughout, and
 * `"%.2f".format(x)` uses the DEVICE locale - so the same price rendered
 * "€2,54" on a Dutch phone and "€2.54" on an English one, inside otherwise
 * identical Dutch text. CLAUDE.md already records that Dutch decimal commas
 * appear in both prices and nutrition values; this is the rendering half of
 * that, and it should not depend on who is holding the phone.
 *
 * Caught by a unit test that expected "23.9 MB" and got "23,9 MB", because the
 * machine running it happened to be Dutch. On a different CI runner the same
 * code would have produced the opposite result.
 */
val AppLocale: Locale = Locale.forLanguageTag("nl-NL")

/** `"%.2f".format(x)` in the app's own locale rather than the device's. */
fun fmt(pattern: String, vararg args: Any?): String =
    String.format(AppLocale, pattern, *args)
