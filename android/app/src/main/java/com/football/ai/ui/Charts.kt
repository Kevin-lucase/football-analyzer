package com.football.ai.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 雷达图：score 为 null 的维度保留 0 并标记 UNKNOWN，不把缺失当 0 分解读。 */
@Composable
fun RadarChart(labels: List<String>, home: List<Float?>, away: List<Float?>,
               homeName: String, awayName: String, modifier: Modifier = Modifier) {
    val n = labels.size
    Canvas(modifier.size(300.dp)) {
        val cx = size.width / 2; val cy = size.height / 2 + 10f
        val r = minOf(size.width, size.height) / 2 - 44f
        fun pt(i: Int, frac: Float): Offset {
            val a = -Math.PI / 2 + 2 * Math.PI * i / n
            return Offset((cx + r * frac * kotlin.math.cos(a)).toFloat(),
                          (cy + r * frac * kotlin.math.sin(a)).toFloat())
        }
        for (ring in 1..4) {
            val p = Path()
            for (i in 0 until n) { val q = pt(i, ring / 4f); if (i == 0) p.moveTo(q.x, q.y) else p.lineTo(q.x, q.y) }
            p.close()
            drawPath(p, Card2, style = Stroke(1f))
        }
        for (i in 0 until n) drawLine(Card2, Offset(cx, cy), pt(i, 1f), 1f)
        fun poly(values: List<Float?>, color: Color) {
            val p = Path()
            for (i in 0 until n) {
                val v = (values[i] ?: 0f).coerceIn(0f, 100f) / 100f
                val q = pt(i, v.coerceAtLeast(0.02f)); if (i == 0) p.moveTo(q.x, q.y) else p.lineTo(q.x, q.y)
            }
            p.close(); drawPath(p, color.copy(alpha = 0.25f)); drawPath(p, color, style = Stroke(2f))
            for (i in 0 until n) if (values[i] != null) drawCircle(color, 3f, pt(i, (values[i]!! / 100f).coerceAtLeast(0.02f)))
        }
        poly(home, Green); poly(away, Blue)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp).background(Green)); Spacer(Modifier.width(4.dp)); Text(homeName, color = Text1) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp).background(Blue)); Spacer(Modifier.width(4.dp)); Text(awayName, color = Text1) }
    }
}

/** 精确比分概率矩阵（热力格）。 */
@Composable
fun ScoreMatrix(maxGoals: Int, matrix: Map<String, Any?>, modifier: Modifier = Modifier) {
    val keys = (0..maxGoals).flatMap { h -> (0..maxGoals).map { a -> "$h-$a" } }
    val vals = keys.associateWith { k -> (matrix[k] as? Number)?.toFloat() }
    val maxV = vals.values.maxOfOrNull { it ?: 0f } ?: 0f
    Column(modifier) {
        for (h in 0..maxGoals) {
            Row(Modifier.fillMaxWidth()) {
                for (a in 0..maxGoals) {
                    val v = vals["$h-$a"]
                    val t = if (maxV > 0 && v != null) v / maxV else 0f
                    Box(Modifier.weight(1f).aspectRatio(1.3f).padding(2.dp)
                        .clip(RoundedCornerShape(6)).background(Green.copy(alpha = 0.05f + 0.75f * t)),
                        Alignment.Center) {
                        Text(if (v == null) "-" else "${"%.0f".format(v * 100)}",
                            color = if (t > 0.5) Color(0xFF04130B) else Text2, fontSize = 10.sp())
                    }
                }
            }
        }
        Text("行=主队进球，列=客队进球；单位为概率%(四舍五入)，缺失格为 -", color = Text2, fontSize = 10.sp())
    }
}
