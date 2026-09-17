package com.macrofinder.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * MacroFinder's colours.
 *
 * Before this existed the app called `MaterialTheme { }` with no arguments,
 * which is not a neutral choice - it ships Material 3's baseline purple
 * (#6750A4) and no dark scheme at all. A default is not a decision.
 *
 * Where these colours come from: a Dutch supermarket shelf-edge price label.
 * Near-white paper, near-black numerals, and exactly one saturated block of
 * colour marking the bonus. That is the whole visual language of the thing
 * this app is about, and it happens to be the right structure anyway - the
 * surface stays quiet so the price can be the loudest thing on screen.
 *
 * The signal colour is the CHAIN'S OWN (see [chainSignal]), which is the one
 * idea here that could not be lifted into a different product: MacroFinder
 * covers three chains, so "on promo" is red at Albert Heijn, yellow at Jumbo
 * and blue at Aldi, exactly as it is in the aisle.
 *
 * Every pair below was checked against `accessibility.md`'s 4.5:1 floor for
 * text up to 17pt; the ratios are in the comments so a future edit can't
 * quietly drop below them.
 */

// --- light: paper ---------------------------------------------------------

private val PaperSurface = Color(0xFFFBFAF7)
private val PaperCard = Color(0xFFFFFFFF)
private val InkPrimary = Color(0xFF1A1917)      // 16.4:1 on PaperSurface
private val InkMuted = Color(0xFF5C5950)        //  6.8:1 on PaperSurface
private val InkHairline = Color(0xFFE2DFD6)
private val GreenInteractive = Color(0xFF1F5C3D) //  7.6:1 on PaperSurface

// --- dark: the same label under a kitchen light at night ------------------

private val NightSurface = Color(0xFF14130F)
private val NightCard = Color(0xFF211F1A)
private val NightInk = Color(0xFFF2F0E9)        // 15.9:1 on NightSurface
private val NightInkMuted = Color(0xFFB3B0A6)   //  8.6:1 on NightSurface
private val NightHairline = Color(0xFF34322B)
private val GreenInteractiveDark = Color(0xFF7FC9A0) // 9.4:1 on NightSurface

private val LightColors = lightColorScheme(
    primary = GreenInteractive,
    onPrimary = Color.White,
    surface = PaperSurface,
    onSurface = InkPrimary,
    surfaceVariant = PaperCard,
    onSurfaceVariant = InkMuted,
    background = PaperSurface,
    onBackground = InkPrimary,
    outlineVariant = InkHairline,
)

private val DarkColors = darkColorScheme(
    primary = GreenInteractiveDark,
    onPrimary = Color(0xFF00391F),
    surface = NightSurface,
    onSurface = NightInk,
    surfaceVariant = NightCard,
    onSurfaceVariant = NightInkMuted,
    background = NightSurface,
    onBackground = NightInk,
    outlineVariant = NightHairline,
)

/**
 * The one bold element, and the only place saturated colour appears.
 *
 * [content] is not decorative: Jumbo's yellow gives 1.3:1 against white and
 * 15.6:1 against near-black, so a white-on-yellow badge would be unreadable.
 * Each chain carries the foreground its own colour actually supports.
 */
data class ChainSignal(val background: Color, val content: Color)

fun chainSignal(chain: String): ChainSignal = when (chain.lowercase()) {
    // 4.9:1 white-on-red
    "ah" -> ChainSignal(Color(0xFFE2001A), Color.White)
    // 15.6:1 black-on-yellow. White here would be 1.3:1 - unreadable.
    "jumbo" -> ChainSignal(Color(0xFFFFDD00), Color(0xFF1A1917))
    // 7.5:1 white-on-blue
    "aldi" -> ChainSignal(Color(0xFF00549F), Color.White)
    else -> ChainSignal(InkMuted, Color.White)
}

@Composable
fun MacroFinderTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    // No in-app appearance switch: the system setting is the one that counts.
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
