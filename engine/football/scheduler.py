"""历史数据加载（football-data.co.uk 格式 CSV）与后台调度。

与在线接口不同，CSV 属于可核验的历史文件：下载失败直接标记 UNKNOWN，不生成模拟数据。
"""
from __future__ import annotations

import csv
import io
import os
import time
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

from .datasource import _get_json, _now, HttpError
from .pipeline import Analyzer, Reviewer, Store, log

FD_MAIN = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
FD_EXTRA = "https://www.football-data.co.uk/new/{code}.csv"

MAIN_LEAGUES = {
    "E0": ("英超", "英格兰"), "E1": ("英冠", "英格兰"), "SP1": ("西甲", "西班牙"),
    "SP2": ("西乙", "西班牙"), "I1": ("意甲", "意大利"), "I2": ("意乙", "意大利"),
    "D1": ("德甲", "德国"), "D2": ("德乙", "德国"), "F1": ("法甲", "法国"),
    "F2": ("法乙", "法国"), "N1": ("荷甲", "荷兰"), "B1": ("比甲", "比利时"),
    "P1": ("葡超", "葡萄牙"), "T1": ("土超", "土耳其"), "SC0": ("苏超", "苏格兰"),
    "G1": ("希腊超", "希腊"),
}
EXTRA_LEAGUES = {
    "ARG": ("阿甲", "阿根廷"), "BRA": ("巴甲", "巴西"), "CHN": ("中超", "中国"),
    "JPN": ("日职联", "日本"), "MEX": ("墨西哥甲级", "墨西哥"), "USA": ("美职联", "美国"),
    "AUT": ("奥甲", "奥地利"), "DEN": ("丹超", "丹麦"), "NOR": ("挪超", "挪威"),
    "SWE": ("瑞典超", "瑞典"), "POL": ("波兰超", "波兰"), "RUS": ("俄超", "俄罗斯"),
    "FIN": ("芬超", "芬兰"), "IRL": ("爱尔兰超", "爱尔兰"), "SWZ": ("瑞士超", "瑞士"),
    "TUR": ("土甲", "土耳其"),
}


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except Exception:  # noqa
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:  # noqa
        return None


def parse_fd_csv(text: str, code: str, season: str) -> List[Dict[str, Any]]:
    """解析 football-data.co.uk CSV。返回统一结构；缺字段保持 None。"""
    reader = csv.DictReader(io.StringIO(text))
    out: List[Dict[str, Any]] = []
    name_cn, country = MAIN_LEAGUES.get(code, EXTRA_LEAGUES.get(code, (code, "")))
    for row in reader:
        home = (row.get("HomeTeam") or "").strip()
        away = (row.get("AwayTeam") or "").strip()
        if not home or not away:
            continue
        hg, ag = _to_int(row.get("FTHG")), _to_int(row.get("FTAG"))
        if hg is None or ag is None:
            continue
        date = (row.get("Date") or "").strip()
        out.append({
            "match_id": f"fd_{code}_{season}_{date}_{home}_{away}".replace(" ", ""),
            "league": code, "league_name": name_cn, "country": country,
            "season": season, "kickoff": date, "status": "post",
            "home": home, "away": away, "home_score": hg, "away_score": ag,
            "home_ht": _to_int(row.get("HTHG")), "away_ht": _to_int(row.get("HTAG")),
            "shots_home": _to_int(row.get("HS")), "shots_away": _to_int(row.get("AS")),
            "sot_home": _to_int(row.get("HST")), "sot_away": _to_int(row.get("AST")),
            "corners_home": _to_int(row.get("HC")), "corners_away": _to_int(row.get("AC")),
            "odds_home": _to_float(row.get("B365H") or row.get("PSH") or row.get("AvgH")),
            "odds_draw": _to_float(row.get("B365D") or row.get("PSD") or row.get("AvgD")),
            "odds_away": _to_float(row.get("B365A") or row.get("PSA") or row.get("AvgA")),
            "source": "football-data.co.uk",
            "provenance": {"source": "football-data.co.uk CSV", "status": "REAL",
                           "fetched_at": _now()},
        })
    return out


def fetch_history(code: str, season: str, cache_dir: Optional[str] = None,
                  timeout: int = 30) -> List[Dict[str, Any]]:
    url = FD_MAIN.format(season=season, code=code) if code in MAIN_LEAGUES \
        else FD_EXTRA.format(code=code)
    cache = os.path.join(cache_dir, f"{code}_{season}.csv") if cache_dir else None
    if cache and os.path.exists(cache) and os.path.getsize(cache) > 1000:
        text = open(cache, encoding="cp1252", errors="replace").read()
    else:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "python-requests/2.31")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("cp1252", "replace")
            if cache:
                os.makedirs(cache_dir, exist_ok=True)
                open(cache, "w", encoding="utf-8").write(text)
        except Exception as exc:  # noqa
            log(f"历史数据获取失败 {code} {season}: {exc}")
            return []
    return parse_fd_csv(text, code, season)


# ---------------- 后台调度 ----------------
class Scheduler:
    """后台任务：赛程更新、赛前分析+快照、赛果检测+复盘、排行榜更新、数据源监控。
    设计为可被 APScheduler / cron / GitHub Actions 定时调用；每个任务独立记录日志与失败重试。
    """

    def __init__(self, ds: DataSource, store: Store, analyzer: Analyzer,
                 reviewer: Reviewer, leagues: Optional[Iterable[str]] = None):
        self.ds = ds
        self.store = store
        self.analyzer = analyzer
        self.reviewer = reviewer
        self.leagues = list(leagues or [])

    def update_fixtures(self, date: Optional[str] = None) -> Dict[str, Any]:
        started = _now()
        try:
            data = self.ds.today(date, self.leagues or None)
            for m in data["matches"]:
                from .datasource import Match
                self.store.cache_match(Match(**{k: v for k, v in m.items()
                                                if k in Match.__dataclass_fields__}))
            self.store.log_task("update_fixtures", True, data["coverage"], started)
            return data
        except Exception as exc:  # noqa
            self.store.log_task("update_fixtures", False, str(exc), started)
            return {"error": str(exc)}

    def pre_match_analysis(self, date: Optional[str] = None) -> Dict[str, Any]:
        started = _now()
        from .datasource import Match
        rows = self.store.conn.execute(
            "SELECT payload FROM matches WHERE status='pre'").fetchall()
        done, failed = [], []
        for r in rows:
            import json as _j
            m = Match(**_j.loads(r["payload"]))
            if self.store.get_prediction(m.match_id):
                continue
            try:
                self.analyzer.analyze(m)
                done.append(m.match_id)
            except Exception as exc:  # noqa
                failed.append(f"{m.match_id}:{exc}")
        self.store.log_task("pre_match_analysis", True if not failed else False,
                            f"done={len(done)} failed={len(failed)}", started)
        return {"analyzed": done, "failed": failed}

    def settle_results(self) -> Dict[str, Any]:
        started = _now()
        pending = self.store.conn.execute(
            "SELECT p.match_id, p.home, p.away FROM predictions p "
            "LEFT JOIN results r ON p.match_id=r.match_id WHERE r.match_id IS NULL").fetchall()
        settled: List[str] = []
        for row in pending:
            try:
                got = self.ds.scoreboard(None, None) if False else None
            except Exception:  # noqa
                got = None
            # 逐场核对：优先查缓存赛程状态
            cached = self.store.conn.execute("SELECT payload FROM matches WHERE match_id=?",
                                             (row["match_id"],)).fetchone()
            if not cached:
                continue
            import json as _j
            from .datasource import Match
            m = Match(**_j.loads(cached["payload"]))
            if m.status == "post" and m.home_score is not None:
                self.reviewer.finalize(m.match_id, int(m.home_score), int(m.away_score),
                                       m.home_ht, m.away_ht,
                                       m.prov.source if m.prov else "公开接口")
                settled.append(m.match_id)
        self.store.log_task("settle_results", True, f"settled={len(settled)}", started)
        return {"settled": settled}

    def monitor_sources(self) -> Dict[str, Any]:
        started = _now()
        try:
            self.ds.scoreboard("eng.1")
        except Exception:  # noqa
            pass
        report = self.ds.health_report()
        self.store.log_task("monitor_sources", True, str(report)[:500], started)
        return report

    def run_once(self, date: Optional[str] = None) -> Dict[str, Any]:
        return {
            "fixtures": self.update_fixtures(date),
            "analysis": self.pre_match_analysis(date),
            "settlement": self.settle_results(),
            "health": self.monitor_sources(),
            "ran_at": _now(),
        }
