"""全球足球智能分析 APP —— 后端 API。

前后端分离：安卓端只调用本 API；数学模型、数据抓取、复盘/回测全部在服务端完成。
API 密钥（football-data.org 等）只从环境变量读取，绝不下发给 APK。
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from football.datasource import DataSource, LEAGUES, Match  # noqa: E402
from football.pipeline import Analyzer, Backtester, Reviewer, Store, build_leaderboard  # noqa: E402
from football.radar import DIMENSIONS  # noqa: E402
from football.scheduler import EXTRA_LEAGUES, MAIN_LEAGUES, Scheduler, fetch_history  # noqa: E402

DB_PATH = os.environ.get("FOOTBALL_DB", "/data/football.db")
DATA_DIR = os.environ.get("FOOTBALL_DATA_DIR", "/data/football_app/data")

app = FastAPI(title="全球足球智能分析 API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

store = Store(DB_PATH)
ds = DataSource(api_key=os.environ.get("FOOTBALL_DATA_TOKEN"))
analyzer = Analyzer(ds, store)
reviewer = Reviewer(store)
backtester = Backtester(store)
scheduler = Scheduler(ds, store, analyzer, reviewer)

STARTED_AT = time.time()
BACKGROUND: Dict[str, str] = {}


def deserialize(m: Dict[str, Any]) -> Match:
    return Match(**{k: v for k, v in m.items() if k in Match.__dataclass_fields__})


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "version": "1.0.0", "uptime_seconds": int(time.time() - STARTED_AT),
            "db": DB_PATH, "data_source_key_configured": bool(os.environ.get("FOOTBALL_DATA_TOKEN"))}


@app.get("/api/leagues")
def leagues() -> Dict[str, Any]:
    out = []
    for slug, info in LEAGUES.items():
        out.append({"id": slug, "name": info.get("name"), "country": info.get("country"),
                    "season": info.get("season"), "source": info.get("source", "ESPN 公开接口")})
    return {"leagues": out, "note": "覆盖率以实际抓取结果为准，未获取数据的赛事标注 UNKNOWN"}


@app.get("/api/matches/today")
def matches_today(date: Optional[str] = None, leagues_q: Optional[str] = None) -> Dict[str, Any]:
    fl = [x.strip() for x in leagues_q.split(",") if x.strip()] if leagues_q else None
    try:
        return ds.today(date, fl)
    except Exception as exc:  # noqa
        raise HTTPException(502, f"数据源暂时不可用：{exc}") from exc


@app.get("/api/matches/live")
def live() -> Dict[str, Any]:
    try:
        data = ds.today(None, None)
        return {"matches": [m for m in data["matches"] if m.get("status") == "in"],
                "fetched_at": data.get("fetched_at"), "source": data.get("source")}
    except Exception as exc:  # noqa
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/match/{match_id}")
def match_detail(match_id: str) -> Dict[str, Any]:
    row = store.conn.execute("SELECT payload FROM matches WHERE match_id=?",
                             (match_id,)).fetchone()
    if not row:
        raise HTTPException(404, "找不到该比赛，请先刷新赛程")
    import json
    return json.loads(row["payload"])


@app.post("/api/analyze/{match_id}")
def analyze(match_id: str) -> Dict[str, Any]:
    row = store.conn.execute("SELECT payload FROM matches WHERE match_id=?",
                             (match_id,)).fetchone()
    if not row:
        raise HTTPException(404, "找不到该比赛，请先刷新赛程")
    import json
    m = deserialize(json.loads(row["payload"]))
    snap = analyzer.analyze(m)
    return snap


@app.get("/api/match/{match_id}/analysis")
def get_analysis(match_id: str) -> Dict[str, Any]:
    snap = store.get_prediction(match_id)
    if not snap:
        raise HTTPException(404, "该比赛尚未生成预测快照")
    import json
    return {"match_id": match_id, "created_at": snap["created_at"],
            "model_version": snap["model_version"], "params": json.loads(snap["params"]),
            "models": json.loads(snap["models"]), "ensemble": json.loads(snap["ensemble"]),
            "score_matrix": json.loads(snap["score_matrix"]),
            "data_quality": snap["data_quality"], "snapshot_sha": snap["snapshot_sha"],
            "radar": json.loads(snap["radar"]) if snap.get("radar") else None,
            "report": snap.get("report", "")}


@app.get("/api/radar/{match_id}")
def radar(match_id: str) -> Dict[str, Any]:
    a = get_analysis(match_id)
    return {"dimensions": [d["key"] for d in DIMENSIONS], "radar": a["radar"]}


@app.get("/api/review/{match_id}")
def review(match_id: str) -> Dict[str, Any]:
    rows = store.reviews(match_id)
    if not rows:
        raise HTTPException(404, "该比赛尚未完赛或还没有进行赛后复盘")
    return rows[0]["payload"]


@app.get("/api/reviews")
def reviews(league: Optional[str] = None, days: Optional[int] = None) -> Dict[str, Any]:
    return {"summary": reviewer.summary(league, days),
            "items": [r["payload"] for r in store.reviews(limit=200)]}


@app.get("/api/leaderboard")
def leaderboard(league: Optional[str] = None, days: Optional[int] = Query(None),
                prediction_type: str = "wdl") -> Dict[str, Any]:
    board = build_leaderboard(store, scope={"league": league} if league else None, days=days)
    board["prediction_type"] = prediction_type
    return board


@app.get("/api/backtest/{task_id}")
def get_backtest(task_id: str) -> Dict[str, Any]:
    row = store.backtest(task_id)
    if not row:
        raise HTTPException(404, "回测任务不存在")
    return row["payload"]


class BacktestRequest(BaseModel):
    code: str = "E0"
    season: str = "2526"
    task_id: Optional[str] = None


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest, bg: BackgroundTasks) -> Dict[str, Any]:
    task_id = req.task_id or f"bt_{req.code}_{req.season}_{uuid.uuid4().hex[:8]}"
    rows = fetch_history(req.code, req.season, cache_dir=DATA_DIR)
    if len(rows) < 10:
        raise HTTPException(400, f"历史数据不足（{len(rows)} 场），无法回测；数据不可用时会标注 UNKNOWN，不会伪造结果")
    BACKGROUND[task_id] = "running"
    bg.add_task(_backtest_worker, rows, task_id, req.code, req.season)
    return {"task_id": task_id, "sample_size": len(rows), "status": "running"}


def _backtest_worker(rows: List[Dict[str, Any]], task_id: str, code: str, season: str) -> None:
    try:
        payload = backtester.run(rows, task_id, scope={"league": code, "season": season})
        BACKGROUND[task_id] = "done"
    except Exception as exc:  # noqa
        BACKGROUND[task_id] = f"failed: {exc}"


@app.get("/api/backtest/status/{task_id}")
def backtest_status(task_id: str) -> Dict[str, Any]:
    return {"task_id": task_id, "status": BACKGROUND.get(task_id,
            "done" if store.backtest(task_id) else "unknown")}


@app.get("/api/model-lab/versions")
def model_versions() -> Dict[str, Any]:
    rows = store.conn.execute("SELECT * FROM model_versions ORDER BY id DESC").fetchall()
    return {"versions": [dict(r) for r in rows],
            "current": {"model_version": "1.0.0", "weights": analyzer.weights,
                        "status": "production"}}


class ExperimentRequest(BaseModel):
    weights: Dict[str, float] = Field(default_factory=dict)
    code: str = "E0"
    season: str = "2526"


@app.post("/api/model-lab/experiment")
def run_experiment(req: ExperimentRequest) -> Dict[str, Any]:
    weights = {**analyzer.weights, **{k: float(v) for k, v in req.weights.items()}}
    rows = fetch_history(req.code, req.season, cache_dir=DATA_DIR)
    if len(rows) < 10:
        raise HTTPException(400, "历史数据不足，无法运行实验")
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    bt = Backtester(store, weights=weights)
    payload = bt.run(rows, exp_id, scope={"league": req.code, "season": req.season,
                                          "experiment": True})
    store.conn.execute("INSERT INTO model_versions (model,version,params,created_at,note) "
                       "VALUES (?,?,?,?,?)",
                       ("Ensemble", "exp", __import__("json").dumps(weights),
                        payload["created_at"], f"实验 {exp_id}；不影响生产模型"))
    store.conn.commit()
    return {"experiment_id": exp_id, "weights": weights,
            "test_metrics": payload.get("test_metrics"),
            "note": "实验结果独立保存，不覆盖生产模型；升级需通过验证集与测试集标准"}


@app.get("/api/sources")
def sources() -> Dict[str, Any]:
    return {"report": ds.health_report(),
            "history_sources": {"main": list(MAIN_LEAGUES.keys()),
                                "extra": list(EXTRA_LEAGUES.keys())}}


@app.post("/api/admin/run-once")
def admin_run_once(date: Optional[str] = None) -> Dict[str, Any]:
    return scheduler.run_once(date)


@app.get("/api/stats")
def stats() -> Dict[str, Any]:
    def count(table: str) -> int:
        return store.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    return {"predictions": count("predictions"), "results": count("results"),
            "reviews": count("reviews"), "backtests": count("backtests"),
            "matches": count("matches")}
