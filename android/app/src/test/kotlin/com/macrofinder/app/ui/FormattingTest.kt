package com.macrofinder.app.ui

import java.util.Locale
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/**
 * Numbers are formatted in the app's locale, never the device's.
 *
 * This exists because the opposite was true and nothing noticed until a unit
 * test failed on a Dutch machine while expecting a point. On an English phone
 * the app rendered "€2.54" inside otherwise entirely Dutch copy; on a Dutch one
 * it rendered "€2,54". Both from the same line of code.
 *
 * The tests below change the JVM default locale on purpose, which is the only
 * way to prove the formatting does not depend on it.
 */
class FormattingTest {

    private lateinit var original: Locale

    @Before
    fun setUp() {
        original = Locale.getDefault()
    }

    @After
    fun tearDown() {
        Locale.setDefault(original)
    }

    @Test
    fun `a decimal keeps its Dutch comma on an English device`() {
        Locale.setDefault(Locale.US)

        assertEquals("€2,54", fmt("€%.2f", 2.54))
    }

    @Test
    fun `a decimal keeps its Dutch comma on a Dutch device`() {
        Locale.setDefault(Locale.forLanguageTag("nl-NL"))

        assertEquals("€2,54", fmt("€%.2f", 2.54))
    }

    @Test
    fun `a locale with its own digits does not leak them in`() {
        // Arabic-Indic digits would render the price unreadable to the person
        // this app is for, and `String.format` will happily produce them.
        Locale.setDefault(Locale.forLanguageTag("ar-EG"))

        assertEquals("23,9 MB", fmt("%.1f MB", 23.9))
    }

    @Test
    fun `an integer is unaffected, which is the point of testing it`() {
        Locale.setDefault(Locale.US)

        assertEquals("294 kB", fmt("%d kB", 294))
    }
}
