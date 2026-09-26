package com.macrofinder.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.macrofinder.app.R

/**
 * One family, Archivo (docs/DESIGN.md 2.4), bundled rather than downloaded so
 * it works on phones without Play Services. OFL licence in assets/licenses.
 *
 * Every numeric style turns on tabular figures. Without "tnum", €2,54 and
 * €11,90 in adjacent rows have different digit widths and the price column
 * wobbles.
 */
@OptIn(ExperimentalTextApi::class)
private fun archivo(weight: Int) = Font(
    R.font.archivo,
    weight = FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight)),
)

val Archivo = FontFamily(archivo(400), archivo(500), archivo(600), archivo(700))

private const val TNUM = "tnum"

@Immutable
data class AppType(
    val display: TextStyle,
    val title: TextStyle,
    val rowTitle: TextStyle,
    val body: TextStyle,
    val figure: TextStyle,
    val figureSm: TextStyle,
    val label: TextStyle,
    val labelStrong: TextStyle,
)

val AppTypeScale = AppType(
    display = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(600), fontSize = 28.sp,
        letterSpacing = (-0.5).sp, lineHeight = 32.sp),
    title = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(600), fontSize = 19.sp,
        lineHeight = 24.sp),
    rowTitle = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(600), fontSize = 15.sp,
        lineHeight = 19.sp),
    body = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(400), fontSize = 15.sp,
        lineHeight = 1.45.em),
    figure = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(600), fontSize = 22.sp,
        lineHeight = 26.sp, fontFeatureSettings = TNUM),
    figureSm = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(500), fontSize = 14.sp,
        lineHeight = 18.sp, fontFeatureSettings = TNUM),
    label = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(500), fontSize = 12.sp,
        lineHeight = 16.sp, fontFeatureSettings = TNUM),
    labelStrong = TextStyle(fontFamily = Archivo, fontWeight = FontWeight(600), fontSize = 13.sp,
        lineHeight = 16.sp, fontFeatureSettings = TNUM),
)

val LocalAppType = staticCompositionLocalOf { AppTypeScale }

/** Material's own slots, mapped onto the same family so stock widgets match. */
val MaterialTypography = Typography(
    headlineSmall = AppTypeScale.display.copy(fontSize = 24.sp),
    titleLarge = AppTypeScale.title,
    titleMedium = AppTypeScale.rowTitle,
    titleSmall = AppTypeScale.labelStrong,
    bodyLarge = AppTypeScale.body,
    bodyMedium = AppTypeScale.body.copy(fontSize = 14.sp),
    bodySmall = AppTypeScale.label.copy(fontSize = 13.sp),
    labelLarge = AppTypeScale.labelStrong.copy(fontSize = 14.sp),
    labelMedium = AppTypeScale.label,
    labelSmall = AppTypeScale.label.copy(fontSize = 11.sp),
)
