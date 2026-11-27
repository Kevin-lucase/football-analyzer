package com.football.ai.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Bg = Color(0xFF0E1116)
val Card = Color(0xFF171C24)
val Card2 = Color(0xFF1E2530)
val Green = Color(0xFF1ED882)
val Blue = Color(0xFF4C9EFF)
val Amber = Color(0xFFF5B301)
val Red = Color(0xFFF2545B)
val Text1 = Color(0xFFE8EDF4)
val Text2 = Color(0xFF93A1B3)

private val Dark = darkColorScheme(
    primary = Green, secondary = Blue, background = Bg, surface = Card,
    surfaceVariant = Card2, onPrimary = Color(0xFF04130B), onBackground = Text1,
    onSurface = Text1, onSurfaceVariant = Text2, error = Red)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Dark,
        typography = Typography(bodyMedium = TextStyle(fontSize = 14.sp),
            titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
            headlineSmall = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.Bold)),
        content = content)
}
