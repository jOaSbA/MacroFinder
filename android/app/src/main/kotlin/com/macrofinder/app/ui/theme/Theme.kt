package com.macrofinder.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import com.macrofinder.app.data.catalogue.DealTier

/**
 * Colour tokens from docs/DESIGN.md section 2.3: paper, flat white cards,
 * near-black ink, one green signal. Cards separate from the page by value,
 * never by shadow.
 *
 * Two values differ from the spec, both to meet its own 4.5:1 floor: Muted is
 * a step darker (#6E7573 measures ~4.4:1 on Paper), and the "average" deal
 * tier is darker than #7C918A (~3:1 on white). The ratios are noted so an edit
 * can't quietly drop below them.
 */
@Immutable
data class Tokens(
    val paper: Color,
    val card: Color,
    val ink: Color,
    val muted: Color,
    val rule: Color,
    val signal: Color,
    val onSignal: Color,
    val excellent: Color,
    val good: Color,
    val average: Color,
    val warn: Color,
    val dark: Boolean,
)

val LightTokens = Tokens(
    paper = Color(0xFFF5F7F4),
    card = Color(0xFFFFFFFF),
    ink = Color(0xFF1A1D1B),      // 15.6:1 on paper
    muted = Color(0xFF5F6664),    //  5.6:1 on paper
    rule = Color(0xFFE3E7E2),
    signal = Color(0xFF00694E),   //  6.9:1 on white
    onSignal = Color.White,
    excellent = Color(0xFF00694E),
    good = Color(0xFF2E6B57),     //  6.1:1 on white
    average = Color(0xFF52615B),  //  6.3:1 on white
    warn = Color(0xFF8A4B00),     //  6.2:1 on white
    dark = false,
)

val DarkTokens = Tokens(
    paper = Color(0xFF111412),
    card = Color(0xFF1A1E1B),
    ink = Color(0xFFE8ECE9),      // 14.9:1 on card
    muted = Color(0xFF9EA6A2),    //  6.9:1 on card
    rule = Color(0xFF2B312D),
    signal = Color(0xFF63C9A0),   //  8.8:1 on card
    onSignal = Color(0xFF00291C),
    excellent = Color(0xFF63C9A0),
    good = Color(0xFF8DBBA8),
    average = Color(0xFFA9B4AF),
    warn = Color(0xFFE8B070),
    dark = true,
)

val LocalTokens = staticCompositionLocalOf { LightTokens }

/** Shorthand used across the screens: `MF.tokens.ink`. */
object MF {
    val tokens: Tokens
        @Composable get() = LocalTokens.current
    val type: AppType
        @Composable get() = LocalAppType.current
}

/** Colour for a deal's sorted-on figure. Uncertain macros always render Muted. */
@Composable
fun tierColor(tier: DealTier?, estimated: Boolean): Color {
    val t = MF.tokens
    if (estimated || tier == null) return t.muted
    return when (tier) {
        DealTier.EXCELLENT -> t.excellent
        DealTier.GOOD -> t.good
        DealTier.AVERAGE -> t.average
        DealTier.POOR -> t.muted
    }
}

/**
 * Chain identity: a thin rule down a row's leading edge, not a filled chip.
 * Three saturated chips on one screen is three colours fighting (DESIGN.md).
 */
fun chainColor(chain: String): Color = when (chain.lowercase()) {
    // Red, not AH's blue: a blue AH rule next to Aldi's blue reads as one chain.
    "ah" -> Color(0xFFE2001A)
    "jumbo" -> Color(0xFFEEB500)
    "aldi" -> Color(0xFF00549F)
    else -> Color(0xFF8A918E)
}

fun chainName(chain: String): String = when (chain.lowercase()) {
    "ah" -> "AH"
    "jumbo" -> "Jumbo"
    "aldi" -> "Aldi"
    else -> chain
}

@Composable
fun MacroFinderTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val t = if (darkTheme) DarkTokens else LightTokens
    val scheme = if (darkTheme) {
        darkColorScheme(
            primary = t.signal, onPrimary = t.onSignal, background = t.paper, onBackground = t.ink,
            surface = t.card, onSurface = t.ink, surfaceVariant = t.card, onSurfaceVariant = t.muted,
            outline = t.rule, outlineVariant = t.rule, surfaceContainerHigh = t.card,
        )
    } else {
        lightColorScheme(
            primary = t.signal, onPrimary = t.onSignal, background = t.paper, onBackground = t.ink,
            surface = t.card, onSurface = t.ink, surfaceVariant = t.card, onSurfaceVariant = t.muted,
            outline = t.rule, outlineVariant = t.rule, surfaceContainerHigh = t.card,
        )
    }
    // No dynamic colour: the app keeps its own identity on every device.
    CompositionLocalProvider(LocalTokens provides t, LocalAppType provides AppTypeScale) {
        MaterialTheme(colorScheme = scheme, typography = MaterialTypography, content = content)
    }
}
