package com.football.ai

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.sp
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import com.football.ai.data.ApiRepo
import com.football.ai.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { AppTheme { MainScreen() } }
    }
}

private val tabs = listOf("home" to "首页", "leagues" to "赛事", "live" to "实时",
    "schedule" to "赛程", "leaderboard" to "排行", "me" to "我的")

@Composable
fun MainScreen() {
    val nav = rememberNavController()
    val repo = remember { ApiRepo() }
    val current by nav.currentBackStackEntryAsState()
    val route = current?.destination?.route ?: "home"
    LaunchedEffect(Unit) { repo.refresh() }
    Scaffold(bottomBar = {
        if (tabs.any { it.first == route }) NavigationBar(containerColor = Card) {
            tabs.forEach { (r, label) ->
                val selected = current?.destination?.hierarchy?.any { it.route == r } == true
                NavigationBarItem(selected, onClick = {
                    nav.navigate(r) { popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                        launchSingleTop = true; restoreState = true } },
                    icon = { Text(label, color = if (selected) Green else Text2, fontSize = 11.sp()) },
                    colors = NavigationBarItemDefaults.colors(indicatorColor = Green.copy(alpha = 0.2f))) }
        }
    }, containerColor = Bg) { pad ->
        NavHost(nav, "home", Modifier.padding(pad)) {
            tabs.forEach { (r, _) -> composable(r) {
                when (r) {
                    "home" -> HomePage(repo) { id, t -> nav.navigate("match/$id/${android.net.Uri.encode(t)}") }
                    "leagues" -> LeaguesPage(repo) { lid -> nav.navigate("schedule?league=${lid}") }
                    "live" -> LivePage(repo) { id, t -> nav.navigate("match/$id/${android.net.Uri.encode(t)}") }
                    "schedule" -> SchedulePage(repo, { id, t -> nav.navigate("match/$id/${android.net.Uri.encode(t)}") }, false)
                    "leaderboard" -> LeaderboardPage(repo)
                    else -> ProfilePage(repo)
                }
            } }
            composable("schedule?league={league}") { SchedulePage(repo, { id, t -> nav.navigate("match/$id/${android.net.Uri.encode(t)}") }, false) }
            composable("favorites") { SchedulePage(repo, { id, t -> nav.navigate("match/$id/${android.net.Uri.encode(t)}") }, true) }
            composable("reviewList") { ReviewPage(repo, null) }
            composable("match/{id}/{title}") { e ->
                val id = e.arguments!!.getString("id")!!
                val title = android.net.Uri.decode(e.arguments!!.getString("title") ?: "")
                MatchDetailPage(repo, id, title,
                    onAnalyze = { nav.navigate("analysis/$id/${android.net.Uri.encode(title)}") },
                    onReview = { nav.navigate("review/$id") },
                    onRadar = { nav.navigate("radar/$id/${android.net.Uri.encode(title)}") })
            }
            composable("analysis/{id}/{title}") { e ->
                var gen by remember { mutableStateOf(false) }
                AnalysisPage(repo, e.arguments!!.getString("id")!!, android.net.Uri.decode(e.arguments!!.getString("title")!!), gen) { gen = true }
            }
            composable("radar/{id}/{title}") { e ->
                RadarPage(repo, e.arguments!!.getString("id")!!, android.net.Uri.decode(e.arguments!!.getString("title")!!)) }
            composable("prob/{id}/{title}") { e ->
                ProbabilityPage(repo, e.arguments!!.getString("id")!!, android.net.Uri.decode(e.arguments!!.getString("title")!!)) }
            composable("report/{id}/{title}") { e ->
                ReportPage(repo, e.arguments!!.getString("id")!!, android.net.Uri.decode(e.arguments!!.getString("title")!!)) }
            composable("review/{id}") { e -> ReviewPage(repo, e.arguments!!.getString("id")) }
            composable("reviewList") -> Unit
            composable("backtest") { BacktestPage(repo) }
            composable("lab") { LabPage(repo) }
            composable("history") { HistoryPage(repo) }
            composable("favorites2") { SchedulePage(repo, { _, _ -> }, true) }
            composable("sources") { SourcesPage(repo) }
        }
    }
}
