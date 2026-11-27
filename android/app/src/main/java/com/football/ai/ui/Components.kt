package com.football.ai.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun CardBox(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.clip(RoundedCornerShape(14)).background(Card).padding(14.dp), content = content)
}

@Composable
fun SectionTitle(text: String, action: String? = null, onClick: () -> Unit = {}) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = MaterialTheme.typography.titleMedium, color = Text1)
        Spacer(Modifier.weight(1f))
        if (action != null) Text(action, color = Green, modifier = Modifier.clickable(onClick = onClick))
    }
}

@Composable
fun StateView(loading: Boolean, error: String?, empty: Boolean = false,
              onRetry: () -> Unit = {}, content: @Composable () -> Unit) {
    when {
        loading -> Box(Modifier.fillMaxWidth().padding(32.dp), Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator(color = Green); Spacer(Modifier.height(10.dp))
                Text("数据加载中…", color = Text2)
            }
        }
        error != null -> Column(Modifier.fillMaxWidth().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally) {
            Text("⚠️ $error", color = Red, textAlign = TextAlign.Center)
            Spacer(Modifier.height(8.dp))
            Button(onClick = onRetry, colors = ButtonDefaults.buttonColors(containerColor = Card2)) {
                Text("重试") }
        }
        empty -> Box(Modifier.fillMaxWidth().padding(24.dp), Alignment.Center) {
            Text("暂无数据（UNKNOWN，未用模拟数据填充）", color = Text2) }
        else -> content()
    }
}

@Composable
fun Tag(text: String, color: Color = Text2) {
    Text(text, color = color, fontSize = 11.sp(), modifier = Modifier
        .clip(RoundedCornerShape(4)).background(color.copy(alpha = 0.15f)).padding(horizontal = 6.dp, vertical = 2.dp))
}

@Composable
fun ProbBar(label: String, value: Float?, color: Color) {
    Column(Modifier.padding(vertical = 3.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Text(label, color = Text1, modifier = Modifier.width(40.dp))
            LinearProgressIndicator(progress = { (value ?: 0f).coerceIn(0f, 1f) },
                modifier = Modifier.weight(1f).height(8.dp).clip(RoundedCornerShape(4)),
                color = color, trackColor = Card2)
            Text(if (value == null) "UNKNOWN" else "${"%.1f".format(value * 100)}%",
                color = if (value == null) Text2 else color, modifier = Modifier.width(64.dp),
                textAlign = TextAlign.End, fontSize = 12.sp())
        }
    }
}

@Composable
fun ScoreChip(home: String, away: String, score: Pair<Int?, Int?>?, status: String?,
              time: String?, onClick: () -> Unit, modifier: Modifier = Modifier) {
    CardBox(modifier.clickable(onClick = onClick)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(home, color = Text1, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(away, color = Text1, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                if (score?.first != null) Text("${score.first} - ${score.second}",
                    color = Green, style = MaterialTheme.typography.titleMedium)
                else Text(time ?: "--:--", color = if (status == "in") Red else Text2, fontSize = 12.sp)
                if (status == "in") Tag("直播", Red) else if (status == "post") Tag("完场") else Tag("未开赛")
            }
        }
    }
}

@Composable
fun FilterChips(options: List<Pair<String, String>>, selected: String, onChange: (String) -> Unit) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(options) { (k, v) ->
            FilterChip(selected == k, onClick = { onChange(k) }, label = { Text(v) },
                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Green,
                    selectedLabelColor = Color(0xFF04130B)))
        }
    }
}
