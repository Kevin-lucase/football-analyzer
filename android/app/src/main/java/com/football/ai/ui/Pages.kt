package com.football.ai.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.football.ai.data.ApiRepo

fun num(v: Any?, default: Float? = null): Float? = when (v) {
    is Number -> v.toFloat(); is String -> v.toFloatOrNull(); else -> default }
fun pct(v: Any?): String { val n = num(v) ?: return "UNKNOWN"; return "${"%.1f".format(n * 100)}%" }
fun str(v: Any?): String = v?.toString() ?: "UNKNOWN"

@Composable
fun HomePage(repo: ApiRepo, onMatch: (String, String) -> Unit) {
    var loading by remember { mutableStateOf(true) }; var error by remember { mutableStateOf<String?>(null) }
    var data by remember { mutableStateOf<Map<String, Any?>>(emptyMap()) }
    LaunchedEffect(Unit) { loading = true; repo.refresh()
        repo.today(null, null).onSuccess { data = it; error = null }.onFailure { error = it.message }
        loading = false }
    val matches = (data["matches"] as? List<*>)?.mapNotNull { it as? Map<String, Any?> } ?: emptyList()
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("今日全球赛事", style = MaterialTheme.typography.headlineSmall, color = Text1)
            Text("来源：${str(data["source"])}　更新：${str(data["fetched_at"]).take(19)}", color = Text2, fontSize = 11.sp()) }
        item { StateView(loading, error, matches.isEmpty(), { loading = true }) {} }
        val hot = matches.filter { str(it["status"]) == "in" }.take(6)
        if (hot.isNotEmpty()) {
            item { SectionTitle("正在进行的比赛") }
            items(hot) { m -> ScoreChip(str(m["home"]), str(m["away"]),
                num(m["home_score"])?.let { it.toInt() to num(m["away_score"])?.toInt() },
                str(m["status"]), str(m["time"]), { onMatch(str(m["id"]), str(m["home"]) + " vs " + str(m["away"])) }) }
        }
        val coming = matches.filter { str(it["status"]) != "post" }.take(30)
        if (coming.isNotEmpty()) {
            item { SectionTitle("即将开赛") }
            items(coming) { m -> ScoreChip(str(m["home"]), str(m["away"]), null, str(m["status"]),
                str(m["time"]).ifEmpty { str(m["date"]) }, { onMatch(str(m["id"]), str(m["home"]) + " vs " + str(m["away"])) }) }
        }
        if (!loading && error == null && matches.isEmpty()) item { EmptyHint() }
        item { Spacer(Modifier.height(60.dp)) }
    }
}

@Composable
fun EmptyHint() {
    CardBox { Text("今天没有可获取的比赛数据", color = Text1)
        Text("接口可能限流或暂时不可用，界面显示 UNKNOWN，不会用模拟数据填充。可到「数据源管理」查看状态，或在「个人中心」切换后端地址。", color = Text2, fontSize = 12.sp()) }
}

@Composable
fun LeaguesPage(repo: ApiRepo, onOpen: (String) -> Unit) {
    var loading by remember { mutableStateOf(true) }; var error by remember { mutableStateOf<String?>(null) }
    var groups by remember { mutableStateOf<Map<String, List<Map<String, Any?>>>>(emptyMap()) }
    LaunchedEffect(Unit) { loading = true
        repo.leagues().onSuccess { r ->
            val ls = (r["leagues"] as? List<*>)?.mapNotNull { it as? Map<String, Any?> } ?: emptyList()
            groups = ls.groupBy { str(it["country"]) } }
            .onFailure { error = it.message }; loading = false }
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Text("全球赛事中心", style = MaterialTheme.typography.headlineSmall, color = Text1) }
        item { StateView(loading, error, groups.isEmpty()) {} }
        groups.forEach { (country, ls) ->
            item { SectionTitle("$country（${ls.size}）") }
            items(ls) { l ->
                CardBox(Modifier.fillMaxWidth().clickable { onOpen(str(l["id"])) }) {
                    Row(Modifier.fillMaxWidth()) {
                        Column(Modifier.weight(1f)) {
                            Text(str(l["name"]), color = Text1)
                            Text("赛季 ${str(l["season"])}　来源 ${str(l["source"])}", color = Text2, fontSize = 11.sp()) }
                        Tag("可查询", Green)
                    }
                }
            }
        }
        item { Spacer(Modifier.height(60.dp)) }
    }
}

@Composable
fun LivePage(repo: ApiRepo, onMatch: (String, String) -> Unit) {
    var loading by remember { mutableStateOf(true) }; var error by remember { mutableStateOf<String?>(null) }
    var list by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    LaunchedEffect(Unit) { loading = true
        repo.live().onSuccess { list = (it["matches"] as? List<*>)?.mapNotNull { m -> m as? Map<String, Any?> } ?: emptyList(); error = null }
            .onFailure { error = it.message }; loading = false }
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Text("实时比分", style = MaterialTheme.typography.headlineSmall, color = Text1) }
        item { StateView(loading, error, list.isEmpty()) {} }
        items(list) { m -> ScoreChip(str(m["home"]), str(m["away"]),
            num(m["home_score"])?.let { it.toInt() to num(m["away_score"])?.toInt() }, "in", str(m["time"]),
            { onMatch(str(m["id"]), str(m["home"]) + " vs " + str(m["away"])) }) }
        item { Spacer(Modifier.height(60.dp)) }
    }
}

@Composable
fun SchedulePage(repo: ApiRepo, onMatch: (String, String) -> Unit, favOnly: Boolean) {
    var loading by remember { mutableStateOf(true) }; var error by remember { mutableStateOf<String?>(null) }
    var data by remember { mutableStateOf<Map<String, Any?>>(emptyMap()) }
    LaunchedEffect(Unit) { loading = true; repo.refresh()
        repo.today(null, null).onSuccess { data = it; error = null }.onFailure { error = it.message }
        loading = false }
    val matches = (data["matches"] as? List<*>)?.mapNotNull { it as? Map<String, Any?> } ?: emptyList()
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Text(if (favOnly) "收藏中心" else "赛程", style = MaterialTheme.typography.headlineSmall, color = Text1) }
        item { StateView(loading, error, matches.isEmpty()) {} }
        items(matches) { m -> ScoreChip(str(m["home"]), str(m["away"]),
            num(m["home_score"])?.let { it.toInt() to num(m["away_score"])?.toInt() },
            str(m["status"]), str(m["time"]), { onMatch(str(m["id"]), str(m["home"]) + " vs " + str(m["away"])) }) }
        item { Spacer(Modifier.height(60.dp)) }
    }
}

@Composable
fun MatchDetailPage(repo: ApiRepo, matchId: String, title: String,
                    onAnalyze: (String) -> Unit, onReview: (String) -> Unit, onRadar: (String) -> Unit) {
    var data by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var hasAnalysis by remember { mutableStateOf(false) }
    var hasReview by remember { mutableStateOf(false) }
    LaunchedEffect(matchId) { loading = true
        repo.match(matchId).onSuccess { data = it; error = null }.onFailure { error = it.message }
        hasAnalysis = repo.analysis(matchId).isSuccess; hasReview = repo.review(matchId).isSuccess
        loading = false }
    val m = data
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(title, style = MaterialTheme.typography.headlineSmall, color = Text1)
        StateView(loading, error, m == null) {}
        m?.let {
            CardBox {
                Text("${str(it["league_name"])}　${str(it["kickoff"])}", color = Text2, fontSize = 12.sp())
                Text("状态：${str(it["status"])}　比分：${num(it["home_score"])?.toInt() ?: "?"} - ${num(it["away_score"])?.toInt() ?: "?"}",
                    color = Text1)
                val prov = it["provenance"] as? Map<String, Any?>
                if (prov != null) {
                    Spacer(Modifier.height(6.dp))
                    Tag("${str(prov["status"])} · ${str(prov["source"])}", Green)
                    Text("采集时间：${str(prov["fetched_at"])}", color = Text2, fontSize = 10.sp())
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onAnalyze(matchId) }, modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Green)) { Text("深度分析") }
                OutlinedButton(onClick = { onRadar(matchId) }, modifier = Modifier.weight(1f)) { Text("战力雷达") }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { onAnalyze(matchId) }, modifier = Modifier.weight(1f)) {
                    Text(if (hasAnalysis) "查看概率分析" else "尚未生成预测") }
                OutlinedButton(onClick = { onReview(matchId) }, modifier = Modifier.weight(1f)) {
                    Text(if (hasReview) "赛后复盘" else "暂无复盘") }
            }
            if (hasAnalysis) Text("✅ 已有赛前预测快照，赛后不可修改", color = Green, fontSize = 12.sp())
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun AnalysisPage(repo: ApiRepo, matchId: String, title: String, generating: Boolean,
                 onGenerate: () -> Unit) {
    var data by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(generating) }
    LaunchedEffect(matchId, generating) { if (generating) return@LaunchedEffect
        loading = true
        repo.analysis(matchId).onSuccess { data = it; error = null }
            .onFailure { error = it.message }; loading = false }
    val a = data
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("深度分析 · $title", style = MaterialTheme.typography.headlineSmall, color = Text1)
        if (generating) {
            LinearProgressIndicator(Modifier.fillMaxWidth(), color = Green)
            Text("正在运行 5 个模型并保存原始预测快照…", color = Text2)
        }
        if (a == null && !generating) {
            StateView(loading, error, true) {}
            Button(onClick = onGenerate, colors = ButtonDefaults.buttonColors(containerColor = Green)) { Text("生成赛前分析与预测") }
        }
        a?.let {
            val ens = (it["ensemble"] as? Map<String, Any?>) ?: emptyMap()
            CardBox {
                SectionTitle("融合概率（模型版本 ${str(it["model_version"])}）")
                ProbBar("主胜", num(ens["home_win"]), Green)
                ProbBar("平局", num(ens["draw"]), Amber)
                ProbBar("客胜", num(ens["away_win"]), Blue)
                Spacer(Modifier.height(6.dp))
                ProbBar("大2.5", num(ens["over25"]), Green)
                ProbBar("双方进球", num(ens["btts"]), Blue)
                Text("数据完整度：${pct(it["data_quality"])}　快照：${str(it["snapshot_sha"]).take(12)}",
                    color = Text2, fontSize = 10.sp())
                Text("预测时间：${str(it["created_at"])}　数据截止：${str(it["data_cutoff"])}", color = Text2, fontSize = 10.sp())
            }
            val models = (it["models"] as? Map<String, Map<String, Any?>>) ?: emptyMap()
            CardBox {
                SectionTitle("各模型独立预测")
                models.forEach { (name, r) ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        Text(name, color = Text1, modifier = Modifier.width(90.dp), fontSize = 12.sp())
                        Text("${pct(r["home_win"])} / ${pct(r["draw"])} / ${pct(r["away_win"])}",
                            color = Text2, fontSize = 12.sp())
                    }
                }
                Text("融合权重：${str((it["params"] as? Map<*, *>)?.get("weights"))}", color = Text2, fontSize = 10.sp())
            }
            val top = (it["top_scores"] as? List<*>)?.mapNotNull { x -> x as? Map<String, Any?> } ?: emptyList()
            if (top.isNotEmpty()) CardBox {
                SectionTitle("最可能比分")
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    top.forEach { s -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(str(s["score"]), color = Green, style = MaterialTheme.typography.titleMedium)
                        Text(pct(s["p"]), color = Text2, fontSize = 11.sp()) } }
                }
            }
            Spacer(Modifier.height(60.dp))
        }
    }
}

@Composable
fun RadarPage(repo: ApiRepo, matchId: String, title: String) {
    var data by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(matchId) { loading = true
        repo.analysis(matchId).onSuccess { data = it; error = null }.onFailure { error = it.message }
        loading = false }
    val labels = listOf("整体", "近期", "主客", "进攻", "防守", "进球效率", "射门创造", "防守限制",
        "中场控制", "阵容完整", "核心球员", "替补深度", "战术适配", "体能", "历史交锋", "环境适应")
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("16维战力雷达 · $title", style = MaterialTheme.typography.headlineSmall, color = Text1)
        StateView(loading, error, data == null) {}
        data?.let { a ->
            val r = (a["radar"] as? Map<String, Any?>)
            val home = ((r?.get("home") as? Map<*, *>)?.get("dimensions") as? List<*>) ?: emptyList()
            val away = ((r?.get("away") as? Map<*, *>)?.get("dimensions") as? List<*>) ?: emptyList()
            fun vals(side: List<*>): List<Float?> = side.mapNotNull { d ->
                ((d as? Map<*, *>)?.get("score") as? Number)?.toFloat() }
            RadarChart(labels, vals(home), vals(away), "主队", "客队")
            CardBox {
                SectionTitle("维度明细（UNKNOWN 不补分）")
                home.indices.forEach { i ->
                    val h = home[i] as? Map<*, *>; val aw = away.getOrNull(i) as? Map<*, *>
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        Text(str(h?.get("name")), color = Text2, modifier = Modifier.width(72.dp), fontSize = 11.sp())
                        Text("${(h?.get("score") as? Number)?.toString() ?: "UNKNOWN"} : ${(aw?.get("score") as? Number)?.toString() ?: "UNKNOWN"}",
                            color = Text1, modifier = Modifier.weight(1f), fontSize = 11.sp())
                        Text(str(h?.get("status")), color = if (str(h?.get("status")) == "REAL") Green else Amber, fontSize = 10.sp())
                    }
                }
            }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun ProbabilityPage(repo: ApiRepo, matchId: String, title: String) {
    var data by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var ht by remember { mutableStateOf(true) }
    LaunchedEffect(matchId) { loading = true
        repo.analysis(matchId).onSuccess { data = it; error = null }.onFailure { error = it.message }
        loading = false }
    val a = data
    val ens = (a?.get("ensemble") as? Map<String, Any?>)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("概率分析 · $title", style = MaterialTheme.typography.headlineSmall, color = Text1)
        StateView(loading, error, a == null) {}
        ens?.let { e ->
            val home = num(e["home_win"]) ?: 0f; val draw = num(e["draw"]) ?: 0f; val away = num(e["away_win"]) ?: 0f
            CardBox {
                SectionTitle("半全场：${if (ht) "全场胜平负" else "半场胜平负"}")
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChips(listOf("ft" to "全场", "ht" to "半场"), if (ht) "ft" to "全场" else "ht" to "半场") { ht = it == "ht" }
                }
                Spacer(Modifier.height(6.dp))
                val (h, d, aw) = if (ht) Triple(home, draw, away) else
                    Triple(num(e["ht_home"]) ?: 0f, num(e["ht_draw"]) ?: 0f, num(e["ht_away"]) ?: 0f)
                ProbBar("主胜", h, Green); ProbBar("平", d, Amber); ProbBar("客胜", aw, Blue)
                Text("半全场组合概率 ≈ 半场×全场独立近似（估算 ESTIMATED）", color = Text2, fontSize = 10.sp())
                if (ht) {
                    val combos = listOf("H/H" to h * home, "H/D" to h * draw, "H/A" to h * away,
                        "D/H" to d * home, "D/D" to d * draw, "D/A" to d * away,
                        "A/H" to aw * home, "A/D" to aw * draw, "A/A" to aw * away)
                    Spacer(Modifier.height(6.dp)); SectionTitle("半全场九宫格")
                    combos.forEach { (k, v) -> ProbBar(k, v, if (k.startsWith("H")) Green else if (k.startsWith("D")) Amber else Blue) }
                }
            }
            val matrix = (e["score_matrix"] as? Map<String, Any?>) ?: (a!!["score_matrix"] as? Map<String, Any?>) ?: emptyMap()
            CardBox { SectionTitle("精确比分概率矩阵"); ScoreMatrix(5, matrix, Modifier.fillMaxWidth()) }
            val dist = (e["goal_dist"] as? Map<String, Any?>) ?: emptyMap()
            if (dist.isNotEmpty()) CardBox {
                SectionTitle("总进球数分布")
                dist.entries.sortedBy { it.key.toIntOrNull() ?: 99 }.forEach { (k, v) -> ProbBar("${k}球", num(v), Blue) }
            }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun ReportPage(repo: ApiRepo, matchId: String, title: String) {
    var text by remember { mutableStateOf<String?>(null) }; var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(matchId) { loading = true
        repo.analysis(matchId).onSuccess { text = str(it["report"]); error = null }.onFailure { error = it.message }
        loading = false }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Text("AI 分析报告 · $title", style = MaterialTheme.typography.headlineSmall, color = Text1)
        Spacer(Modifier.height(8.dp))
        StateView(loading, error, text == null) {
            CardBox { Text(text ?: "", color = Text1, fontSize = 13.sp()) }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun ReviewPage(repo: ApiRepo, matchId: String?) {
    var item by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var summary by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(matchId) { loading = true
        if (matchId == null) repo.reviews(null, null).onSuccess {
            summary = it["summary"] as? Map<String, Any?> }.onFailure { error = it.message }
        else repo.review(matchId).onSuccess { item = it; error = null }.onFailure { error = it.message }
        loading = false }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(if (matchId == null) "赛后复盘汇总" else "赛后复盘", style = MaterialTheme.typography.headlineSmall, color = Text1)
        StateView(loading, error, item == null && summary == null) {}
        item?.let { r ->
            val actual = (r["actual"] as? Map<String, Any?>) ?: emptyMap()
            val pred = (r["predicted"] as? Map<String, Any?>) ?: emptyMap()
            CardBox {
                SectionTitle("预测 vs 实际")
                Text("预测：${str(pred["outcome"])}　比分 ${str(pred["score_pick"])}　大球 ${pred["ou_pick"]}　BTTS ${pred["btts_pick"]}", color = Text1)
                Text("实际：${str(actual["home_score"])} - ${str(actual["away_score"])}（${str(actual["outcome"])}）", color = Green)
                Spacer(Modifier.height(4.dp))
                Tag(if (r["wdl_hit"] == true) "胜平负命中" else "未命中", if (r["wdl_hit"] == true) Green else Red)
                Tag(if (r["score_hit"] == true) "比分命中" else "比分未中", if (r["score_hit"] == true) Green else Red)
                Tag("Brier ${str(r["brier"]).take(5)}")
            }
            CardBox {
                SectionTitle("失败原因分析")
                Text(str(r["failure_reason"]), color = Text2, fontSize = 12.sp())
                Text("快照校验：${str(r["prediction_sha"]).take(12)}（赛前 ${str(r["prediction_created_at"])}）",
                    color = Text2, fontSize = 10.sp())
                Text(str(r["note"]), color = Text2, fontSize = 10.sp())
            }
        }
        summary?.let { s ->
            CardBox {
                SectionTitle("历史复盘统计")
                Text("场次：${str(s["n"])}　胜平负准确率：${pct(s["wdl_accuracy"])}", color = Text1)
                Text("比分命中：${pct(s["score_accuracy"])}　大球：${pct(s["ou_accuracy"])}　双方进球：${pct(s["btts_accuracy"])}", color = Text2, fontSize = 12.sp())
                Text("平均 Brier：${str(s["avg_brier"]).take(6)}　样本充分：${s["sufficient_sample"] == true}", color = Text2, fontSize = 11.sp())
            }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun BacktestPage(repo: ApiRepo) {
    var code by remember { mutableStateOf("E0") }
    var season by remember { mutableStateOf("2526") }
    var running by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val leagues = listOf("E0" to "英超", "SP1" to "西甲", "I1" to "意甲", "D1" to "德甲",
        "F1" to "法甲", "N1" to "荷甲", "P1" to "葡超", "JPN" to "日职", "CHN" to "中超", "BRA" to "巴甲")
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("历史回测", style = MaterialTheme.typography.headlineSmall, color = Text1)
        CardBox {
            SectionTitle("联赛与赛季")
            FilterChips(leagues, code) { code = it }
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(season, { season = it }, label = { Text("赛季（如 2526 / 2425）") },
                modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done))
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                running = true; error = null
                kotlinx.coroutines.GlobalScope.launch {
                    repo.runBacktest(code, season)
                        .onSuccess { r ->
                            val id = str(r["task_id"])
                            repeat(60) {
                                kotlinx.coroutines.delay(5000)
                                val p = repo.backtest(id).getOrNull()
                                if (p != null && p.containsKey("test_metrics")) { result = p; running = false; return@launch }
                            }
                            error = "回测超时"; running = false
                        }.onFailure { error = it.message; running = false } }
            }, colors = ButtonDefaults.buttonColors(containerColor = Green)) { Text("开始回测（时间顺序验证）") }
        }
        if (running) { LinearProgressIndicator(Modifier.fillMaxWidth(), color = Green); Text("后台回测中…", color = Text2) }
        error?.let { Text("⚠️ $it", color = Red) }
        result?.let { r ->
            val tm = (r["test_metrics"] as? Map<String, Any?>)
            val vm = (r["val_metrics"] as? Map<String, Any?>)
            CardBox {
                SectionTitle("测试集指标（n=${str(tm?.get("n"))}）")
                Text("样本切分：${str(r["splits"])}", color = Text2, fontSize = 11.sp())
                Text("胜平负准确率：${pct(tm?.get("wdl_accuracy"))}　95%CI：${str(tm?.get("wdl_ci95"))}", color = Text1)
                Text("LogLoss：${str(tm?.get("log_loss")).take(6)}　Brier：${str(tm?.get("brier")).take(6)}　校准误差：${str(tm?.get("calibration_error")).take(6)}", color = Text2, fontSize = 12.sp())
                Text("比分命中：${pct(tm?.get("score_accuracy"))}　大球：${pct(tm?.get("ou_accuracy"))}　BTTS：${pct(tm?.get("btts_accuracy"))}", color = Text2, fontSize = 12.sp())
                Text("样本充分：${tm?.get("sufficient_sample")}（<30 场不可判定优劣）", color = Amber, fontSize = 11.sp())
                Text(str(r["leakage_guard"]), color = Text2, fontSize = 10.sp())
            }
            val cmp = (r["test_model_compare"] as? Map<String, Any?>)
            if (cmp != null) CardBox {
                SectionTitle("单模型对比（验证集 / 测试集）")
                cmp.forEach { (k, v) -> Row(Modifier.fillMaxWidth()) {
                    Text(k, color = Text1, modifier = Modifier.weight(1f), fontSize = 12.sp())
                    Text(pct(v), color = Green, fontSize = 12.sp()) } }
                val vc = (vm?.get("wdl_accuracy"))
                Text("验证集准确率：${pct(vc)}", color = Text2, fontSize = 10.sp())
            }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun LabPage(repo: ApiRepo) {
    var weights by remember { mutableStateOf("""{"Elo":0.25,"Poisson":0.25,"DixonColes":0.25,"Skellam":0.1,"Form":0.15}""") }
    var code by remember { mutableStateOf("E0") }
    var season by remember { mutableStateOf("2526") }
    var result by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var versions by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var running by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { repo.versions().onSuccess { versions = it } }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("模型实验室", style = MaterialTheme.typography.headlineSmall, color = Text1)
        CardBox {
            SectionTitle("生产模型")
            Text("版本 ${str((versions?.get("current") as? Map<*, *>)?.get("model_version"))}　状态：production", color = Text1, fontSize = 12.sp())
            Text("权重 ${str((versions?.get("current") as? Map<*, *>)?.get("weights"))}", color = Text2, fontSize = 11.sp())
        }
        CardBox {
            SectionTitle("参数实验（不影响生产模型）")
            OutlinedTextField(weights, { weights = it }, label = { Text("融合权重 JSON") },
                modifier = Modifier.fillMaxWidth(), minLines = 3)
            FilterChips(listOf("E0" to "英超", "SP1" to "西甲", "I1" to "意甲", "D1" to "德甲", "F1" to "法甲"), code) { code = it }
            OutlinedTextField(season, { season = it }, label = { Text("赛季") }, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(8.dp))
            Button(onClick = {
                val w = runCatching {
                    com.google.gson.Gson().fromJson(weights, Map::class.java).mapValues { (it.value as Number).toDouble() } }.getOrNull()
                if (w == null) { error = "权重 JSON 格式错误"; return@Button }
                running = true; error = null
                kotlinx.coroutines.GlobalScope.launch {
                    repo.experiment(w, code, season)
                        .onSuccess { result = it; running = false }.onFailure { error = it.message; running = false } }
            }, colors = ButtonDefaults.buttonColors(containerColor = Green)) { Text("运行实验") }
        }
        if (running) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Green)
        error?.let { Text("⚠️ $it", color = Red) }
        result?.let { r ->
            val tm = (r["test_metrics"] as? Map<String, Any?>)
            CardBox {
                SectionTitle("实验 ${str(r["experiment_id"])} 测试集结果")
                Text("胜平负：${pct(tm?.get("wdl_accuracy"))}　LogLoss：${str(tm?.get("log_loss")).take(6)}", color = Text1)
                Text(str(r["note"]), color = Text2, fontSize = 10.sp())
                Text("升级需通过验证集+测试集标准，不会因短期表现自动替换生产模型", color = Amber, fontSize = 10.sp())
            }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun LeaderboardPage(repo: ApiRepo) {
    var league by remember { mutableStateOf<String?>(null) }
    var days by remember { mutableStateOf<Int?>(null) }
    var data by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(league, days) { loading = true
        repo.leaderboard(league, days).onSuccess { data = it; error = null }.onFailure { error = it.message }
        loading = false }
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("预测准确率排行榜", style = MaterialTheme.typography.headlineSmall, color = Text1)
        Spacer(Modifier.height(8.dp))
        FilterChips(listOf(null to "全局", "E0" to "英超", "SP1" to "西甲", "I1" to "意甲",
            "D1" to "德甲", "F1" to "法甲", "CHN" to "中超"), league ?: "") { league = it.ifEmpty { null } }
        Spacer(Modifier.height(6.dp))
        FilterChips(listOf("" to "全部时间", "7" to "7天", "30" to "30天", "90" to "90天"),
            days?.toString() ?: "") { days = it.toIntOrNull() }
        Spacer(Modifier.height(8.dp))
        StateView(loading, error, (data?.get("board") as? List<*>)?.isEmpty() != false) {
            val board = (data!!["board"] as? List<*>)?.mapNotNull { it as? Map<String, Any?> } ?: emptyList()
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(board) { b ->
                    CardBox(Modifier.fillMaxWidth()) {
                        Row(Modifier.fillMaxWidth()) {
                            Text(str(b["rank"]) ?: "-", color = Green, modifier = Modifier.width(24.dp))
                            Column(Modifier.weight(1f)) {
                                Text(str(b["model"]), color = Text1)
                                Text("测试场次 ${str(b["n"])}　${str(b["status"])}", color = Text2, fontSize = 10.sp()) }
                            Text(pct(b["wdl_accuracy"]), color = Green) }
                        Spacer(Modifier.height(4.dp))
                        Text("LogLoss ${str(b["log_loss"]).take(6)}　Brier ${str(b["brier"]).take(6)}　比分 ${pct(b["score_accuracy"])}　校准 ${str(b["calibration_error"]).take(5)}",
                            color = Text2, fontSize = 11.sp())
                    }
                }
                item { Text(str(data!!["note"]), color = Text2, fontSize = 10.sp()) }
            }
        }
    }
}

@Composable
fun HistoryPage(repo: ApiRepo) {
    var items by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(Unit) { loading = true
        repo.reviews(null, null).onSuccess { items = (it["items"] as? List<*>)?.mapNotNull { x -> x as? Map<String, Any?> } ?: emptyList(); error = null }
            .onFailure { error = it.message }; loading = false }
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Text("历史预测记录", style = MaterialTheme.typography.headlineSmall, color = Text1) }
        item { StateView(loading, error, items.isEmpty()) {} }
        items(items) { r ->
            val actual = (r["actual"] as? Map<String, Any?>) ?: emptyMap()
            CardBox(Modifier.fillMaxWidth()) {
                Text("${str(r["home"])} vs ${str(r["away"])}", color = Text1)
                Text("预测 ${str(r["prediction_created_at"])}　快照 ${str(r["prediction_sha"]).take(8)}", color = Text2, fontSize = 10.sp())
                Text("预测 ${str((r["predicted"] as? Map<*, *>)?.get("outcome"))} → 实际 ${str(actual["home_score"])}:${str(actual["away_score"])}",
                    color = if (r["wdl_hit"] == true) Green else Red, fontSize = 12.sp())
            }
        }
        item { Spacer(Modifier.height(60.dp)) }
    }
}

@Composable
fun SourcesPage(repo: ApiRepo) {
    var data by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var stats by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(Unit) { loading = true
        repo.sources().onSuccess { data = it; error = null }.onFailure { error = it.message }
        repo.stats().onSuccess { stats = it }; loading = false }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("数据源管理", style = MaterialTheme.typography.headlineSmall, color = Text1)
        StateView(loading, error, data == null) {}
        data?.let { d ->
            val report = (d["report"] as? Map<String, Any?>) ?: emptyMap()
            CardBox {
                SectionTitle("在线数据源")
                report.entries.forEach { (k, v) ->
                    Row(Modifier.fillMaxWidth()) {
                        Text(k, color = Text1, modifier = Modifier.weight(1f), fontSize = 12.sp())
                        Text(str(v), color = if (str(v).contains("ok", true)) Green else Amber, fontSize = 11.sp()) } }
                Text("数据标签：REAL 真实 / ESTIMATED 估算 / UNKNOWN 缺失 / STALE 过期", color = Text2, fontSize = 10.sp())
            }
            CardBox {
                SectionTitle("历史数据源 football-data.co.uk")
                Text("主联赛：${str((d["history_sources"] as? Map<*, *>)?.get("main"))}", color = Text2, fontSize = 11.sp())
                Text("其它联赛：${str((d["history_sources"] as? Map<*, *>)?.get("extra"))}", color = Text2, fontSize = 11.sp())
            }
        }
        stats?.let { s ->
            CardBox {
                SectionTitle("本机持久化统计")
                Text("比赛 ${str(s["matches"])}　预测快照 ${str(s["predictions"])}　赛果 ${str(s["results"])}　复盘 ${str(s["reviews"])}　回测 ${str(s["backtests"])}",
                    color = Text1, fontSize = 12.sp())
            }
        }
        Spacer(Modifier.height(60.dp))
    }
}

@Composable
fun ProfilePage(repo: ApiRepo) {
    var url by remember { mutableStateOf(Settings.DEFAULT_URL) }
    var health by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { Settings.serverUrl.first { url = it; true } }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("个人中心", style = MaterialTheme.typography.headlineSmall, color = Text1)
        CardBox {
            SectionTitle("后端服务地址")
            OutlinedTextField(url, { url = it }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { scope.launch { Settings.setServerUrl(url); repo.refresh()
                    health = repo.health().fold({ "连接正常 v${str(it["version"])}" }, { "连接失败：${it.message}" }) } },
                    colors = ButtonDefaults.buttonColors(containerColor = Green)) { Text("保存并测试") }
            }
            health?.let { Text(it, color = if (it.contains("正常")) Green else Red, fontSize = 12.sp()) }
            Text("APK 不内置任何 API 密钥，密钥只保存在后端环境变量", color = Text2, fontSize = 10.sp())
        }
        CardBox {
            SectionTitle("关于")
            Text("全球足球智能分析 v1.0.0　引擎 v1.0.0", color = Text1, fontSize = 12.sp())
            Text("模型：Elo / Poisson / Dixon-Coles / Skellam / 近期状态 + 融合。深色主题，数据缺失显示 UNKNOWN。", color = Text2, fontSize = 11.sp())
        }
        Spacer(Modifier.height(60.dp))
    }
}
