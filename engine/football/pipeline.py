"""预测管线：赛前分析 → 多模型预测 → 快照保存；赛后复盘；历史回测；排行榜统计。

核心约束：
- 赛前预测生成后立即落快照，赛后只允许新增结果，不修改原始预测。
- 回测按时间顺序推进，模型只读取该场比赛之前的数据，避免未来数据泄漏。
- 排行榜只统计真实保存的预测与赛果，样本不足标记“样本不足”。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .datasource import DataSource, Match, MatchFeatures
from .models import (DEFAULT_WEIGHTS, MODEL_VERSION, REGISTRY, FormModel, MatchFeatures as MF,
                     ModelResult, DixonColesModel, EloModel, PoissonModel, SkellamModel,
                     fuse, update_elo)
from .radar import build_radar

MIN_SAMPLES = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc() -> str:
    return _now()


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def outcome_of(hg: int, ag: int) -> str:
    return "H" if hg > ag else ("D" if hg == ag else "A")


# ---------------- 统计指标 ----------------
def log_loss(probs: Sequence[float], y: Sequence[int]) -> float:
    eps = 1e-12
    n = 0
    s = 0.0
    for p, yi in zip(probs, y):
        if yi not in (0, 1):
            continue
        p = min(max(p, eps), 1 - eps)
        s -= math.log(p) if yi == 1 else math.log(1 - p)
        n += 1
    return s / n if n else float("nan")


def brier_multiclass(p: Sequence[float], y: Sequence[int]) -> float:
    """多分类 Brier Score，y 为 0/1 指示向量。"""
    if sum(y) != 1:
        return float("nan")
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y))


def calibration_error(probs: Sequence[float], y: Sequence[int], bins: int = 10) -> float:
    buckets: Dict[int, List[float]] = {i: [] for i in range(bins)}
    labels: Dict[int, List[int]] = {i: [] for i in range(bins)}
    for p, yi in zip(probs, y):
        if yi not in (0, 1):
            continue
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append(p)
        labels[idx].append(yi)
    total = 0.0
    n = 0
    for i in range(bins):
        if not buckets[i]:
            continue
        diff = abs(sum(buckets[i]) / len(buckets[i]) - sum(labels[i]) / len(labels[i]))
        total += diff * len(buckets[i])
        n += len(buckets[i])
    return total / n if n else float("nan")


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple:
    if n <= 0:
        return (float("nan"), float("nan"))
    phat = k / n
    denom = 1 + z ** 2 / n
    center = (phat + z ** 2 / (2 * n)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / n + z ** 2 / (4 * n ** 2)) / denom
    return (max(center - margin, 0.0), min(center + margin, 1.0))


def evaluate(predictions: Sequence[Dict[str, Any]], results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """predictions/results 按 match_id 一一对应。"""
    by_id = {r["match_id"]: r for r in results}
    rows = [(p, by_id[p["match_id"]]) for p in predictions if p["match_id"] in by_id]
    n = len(rows)
    if n == 0:
        return {"n": 0, "note": "没有可评估样本，不生成任何指标"}
    wdl_hit = 0
    score_hit = 0
    ou_hit = 0
    btts_hit = 0
    ht_hit = 0
    ll = 0.0
    brier = 0.0
    cal = []
    for p, r in rows:
        y = outcome_of(r["home_score"], r["away_score"])
        pred = p["outcome"]
        if pred == y:
            wdl_hit += 1
        if p.get("score_pick") == f"{r['home_score']}-{r['away_score']}":
            score_hit += 1
        actual_ou = "over" if r["home_score"] + r["away_score"] >= 3 else "under"
        if p.get("ou_pick") == actual_ou:
            ou_hit += 1
        actual_btts = r["home_score"] > 0 and r["away_score"] > 0
        if p.get("btts_pick") == actual_btts:
            btts_hit += 1
        if r.get("home_ht") is not None and p.get("ht_outcome"):
            if outcome_of(r["home_ht"], r["away_ht"]) == p["ht_outcome"]:
                ht_hit += 1
        probs = [p["home_win"], p["draw"], p["away_win"]]
        yvec = [1 if y == k else 0 for k in ("H", "D", "A")]
        ll += log_loss(probs, yvec)
        brier += brier_multiclass(probs, yvec)
        cal.append((p["home_win"], 1 if y == "H" else 0))
    ht_total = sum(1 for _, r in rows if r.get("home_ht") is not None)
    return {
        "n": n,
        "wdl_accuracy": wdl_hit / n,
        "wdl_ci95": wilson_interval(wdl_hit, n),
        "score_accuracy": score_hit / n,
        "ou_accuracy": ou_hit / n,
        "btts_accuracy": btts_hit / n,
        "ht_accuracy": (ht_hit / ht_total) if ht_total else None,
        "ht_n": ht_total,
        "log_loss": ll / n,
        "brier": brier / n,
        "calibration_error": calibration_error([c[0] for c in cal], [c[1] for c in cal]),
        "sufficient_sample": n >= MIN_SAMPLES,
        "min_samples": MIN_SAMPLES,
    }


# ---------------- 存储 ----------------
class Store:
    """SQLite 持久化：预测快照、赛果、复盘、回测、模型版本、任务日志。"""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        c = self.conn
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS predictions (
              match_id TEXT PRIMARY KEY, league TEXT, home TEXT, away TEXT, kickoff TEXT,
              created_at TEXT, data_cutoff TEXT, model_version TEXT, params TEXT,
              models TEXT, ensemble TEXT, score_matrix TEXT, data_quality REAL,
              snapshot_sha TEXT, report TEXT, finalized INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS results (
              match_id TEXT PRIMARY KEY, home_score INTEGER, away_score INTEGER,
              home_ht INTEGER, away_ht INTEGER, status TEXT, fetched_at TEXT, source TEXT
            );
            CREATE TABLE IF NOT EXISTS reviews (
              id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, created_at TEXT, payload TEXT
            );
            CREATE TABLE IF NOT EXISTS backtests (
              task_id TEXT PRIMARY KEY, created_at TEXT, scope TEXT, params TEXT, payload TEXT
            );
            CREATE TABLE IF NOT EXISTS model_versions (
              id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, version TEXT, params TEXT,
              created_at TEXT, is_production INTEGER DEFAULT 0, note TEXT
            );
            CREATE TABLE IF NOT EXISTS task_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, started_at TEXT, finished_at TEXT,
              ok INTEGER, detail TEXT
            );
            CREATE TABLE IF NOT EXISTS elo_ratings (team TEXT PRIMARY KEY, rating REAL, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS matches (
              match_id TEXT PRIMARY KEY, league TEXT, kickoff TEXT, status TEXT, home TEXT,
              away TEXT, home_score INTEGER, away_score INTEGER, payload TEXT, fetched_at TEXT
            );
            """
        )
        c.commit()

    def save_prediction(self, snap: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO predictions (match_id,league,home,away,kickoff,created_at,"
            "data_cutoff,model_version,params,models,ensemble,score_matrix,data_quality,"
            "snapshot_sha,report,finalized) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (snap["match_id"], snap.get("league"), snap.get("home"), snap.get("away"),
             snap.get("kickoff"), snap.get("created_at"), snap.get("data_cutoff"),
             snap.get("model_version"), json.dumps(snap.get("params", {}), ensure_ascii=False),
             json.dumps(snap.get("models", {}), ensure_ascii=False),
             json.dumps(snap.get("ensemble", {}), ensure_ascii=False),
             json.dumps(snap.get("score_matrix", {}), ensure_ascii=False),
             snap.get("data_quality"), snap.get("snapshot_sha"), snap.get("report", "")),
        )
        self.conn.commit()

    def get_prediction(self, match_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM predictions WHERE match_id=?", (match_id,)).fetchone()
        return dict(row) if row else None

    def all_predictions(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM predictions")]

    def save_result(self, match_id: str, home_score: int, away_score: int,
                    home_ht: Optional[int], away_ht: Optional[int], status: str,
                    source: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO results (match_id,home_score,away_score,home_ht,away_ht,"
            "status,fetched_at,source) VALUES (?,?,?,?,?,?,?,?)",
            (match_id, home_score, away_score, home_ht, away_ht, status, _now(), source))
        self.conn.commit()

    def save_review(self, match_id: str, payload: Dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO reviews (match_id,created_at,payload) VALUES (?,?,?)",
                          (match_id, _now(), json.dumps(payload, ensure_ascii=False)))
        self.conn.execute("UPDATE predictions SET finalized=1 WHERE match_id=?", (match_id,))
        self.conn.commit()

    def reviews(self, match_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        if match_id:
            rows = self.conn.execute("SELECT * FROM reviews WHERE match_id=? ORDER BY id DESC",
                                     (match_id,))
        else:
            rows = self.conn.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    def save_backtest(self, task_id: str, scope: Dict[str, Any], params: Dict[str, Any],
                      payload: Dict[str, Any]) -> None:
        self.conn.execute("INSERT OR REPLACE INTO backtests (task_id,created_at,scope,params,payload)"
                          " VALUES (?,?,?,?,?)",
                          (task_id, _now(), json.dumps(scope, ensure_ascii=False),
                           json.dumps(params, ensure_ascii=False),
                           json.dumps(payload, ensure_ascii=False)))
        self.conn.commit()

    def backtest(self, task_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM backtests WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d

    def log_task(self, task: str, ok: bool, detail: str, started: str) -> None:
        self.conn.execute("INSERT INTO task_logs (task,started_at,finished_at,ok,detail) "
                          "VALUES (?,?,?,?,?)", (task, started, _now(), 1 if ok else 0, detail))
        self.conn.commit()

    def upsert_elo(self, team: str, rating: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO elo_ratings (team,rating,updated_at) "
                          "VALUES (?,?,?)", (team, rating, _now()))
        self.conn.commit()

    def get_elo(self, team: str, default: float = 1500.0) -> float:
        row = self.conn.execute("SELECT rating FROM elo_ratings WHERE team=?", (team,)).fetchone()
        return float(row["rating"]) if row else default

    def cache_match(self, m: Match) -> None:
        from dataclasses import asdict as _a
        self.conn.execute("INSERT OR REPLACE INTO matches (match_id,league,kickoff,status,home,"
                          "away,home_score,away_score,payload,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (m.match_id, m.league, m.kickoff, m.status, m.home, m.away,
                           m.home_score, m.away_score,
                           json.dumps(_a(m), ensure_ascii=False, default=str), m.prov.fetched_at
                           if m.prov else _now()))
        self.conn.commit()


# ---------------- 赛前分析管线 ----------------
class Analyzer:
    def __init__(self, ds: DataSource, store: Store, weights: Optional[Dict[str, float]] = None):
        self.ds = ds
        self.store = store
        self.weights = weights or DEFAULT_WEIGHTS

    def build_features(self, m: Match, season_form: Optional[Dict[str, Any]] = None) -> MF:
        f = MF(home=m.home, away=m.away,
               elo_home=self.store.get_elo(m.home), elo_away=self.store.get_elo(m.away))
        if season_form:
            f.home_gf = season_form.get("home", {}).get("gf")
            f.home_ga = season_form.get("home", {}).get("ga")
            f.away_gf = season_form.get("away", {}).get("gf")
            f.away_ga = season_form.get("away", {}).get("ga")
            f.league_avg_home = season_form.get("league_avg_home", f.league_avg_home)
            f.league_avg_away = season_form.get("league_avg_away", f.league_avg_away)
        return f

    def analyze(self, m: Match, season_form: Optional[Dict[str, Any]] = None,
                ctx: Optional[Dict[str, Any]] = None, report: str = "") -> Dict[str, Any]:
        started = _now()
        f = self.build_features(m, season_form)
        results: List[ModelResult] = [REGISTRY[n].predict(f) for n in
                                      ("Elo", "Poisson", "DixonColes", "Skellam", "Form")]
        ens = fuse(results, self.weights)
        quality = round(sum(1 for x in (f.home_gf, f.home_ga, f.away_gf, f.away_ga)
                            if x is not None) / 4, 2)
        top = sorted(ens.score_matrix.items(), key=lambda kv: -kv[1])[:8]
        snap = {
            "match_id": m.match_id, "league": m.league, "league_name": m.league_name,
            "home": m.home, "away": m.away, "kickoff": m.kickoff,
            "created_at": started, "data_cutoff": started, "model_version": MODEL_VERSION,
            "params": {"weights": self.weights, "home_advantage": f.home_advantage},
            "models": {r.model: r.as_dict() for r in results},
            "ensemble": ens.as_dict(),
            "score_matrix": ens.score_matrix,
            "top_scores": [{"score": k, "p": v} for k, v in top],
            "outcome": ("H" if ens.home_win >= ens.away_win and ens.home_win >= ens.draw else
                        "D" if ens.draw >= ens.away_win else "A"),
            "score_pick": top[0][0] if top else None,
            "ou_pick": "over" if ens.over25 >= 0.5 else "under",
            "btts_pick": ens.btts >= 0.5,
            "ht_outcome": ("H" if ens.ht_home >= ens.ht_away and ens.ht_home >= ens.ht_draw else
                           "D" if ens.ht_draw >= ens.ht_away else "A"),
            "data_quality": quality,
            "prov": m.prov.as_dict() if m.prov else None,
            "radar": {
                "home": build_radar(f, "home", (ctx or {}).get("home"), started).as_dict(),
                "away": build_radar(f, "away", (ctx or {}).get("away"), started).as_dict(),
            },
            "degraded": ens.degraded,
            "report": report or self.default_report(m, results, ens, quality),
        }
        raw = json.dumps({k: snap[k] for k in ("match_id", "created_at", "ensemble", "params")
                          if k in snap}, ensure_ascii=False, sort_keys=True, default=str)
        snap["snapshot_sha"] = hashlib.sha256(raw.encode()).hexdigest()
        self.store.save_prediction(snap)
        self.store.cache_match(m)
        return snap

    @staticmethod
    def default_report(m: Match, results: Sequence[ModelResult], ens: ModelResult,
                       quality: float) -> str:
        lines = [
            f"【赛前分析报告】{m.home} vs {m.away}（{m.league_name or m.league}）",
            f"开赛时间：{m.kickoff or '未知'}　状态：{m.status_text or m.status}",
            f"数据完整度：{quality:.0%}" + ("（部分维度使用联赛均值估算）" if quality < 1 else ""),
            "", "一、各模型独立预测（不覆盖、不修改）",
        ]
        for r in results:
            lines.append(f"  · {r.model} v{r.version}：主胜 {r.home_win:.1%} / 平 {r.draw:.1%} "
                         f"/ 客胜 {r.away_win:.1%}；大2.5 {r.over25:.1%}；BTTS {r.btts:.1%}"
                         + (f"（降级：{r.note}）" if r.degraded else ""))
        lines += [
            "", "二、多模型融合结果",
            f"  融合权重：{ens.note}",
            f"  胜平负：主胜 {ens.home_win:.1%} / 平 {ens.draw:.1%} / 客胜 {ens.away_win:.1%}",
            f"  大2.5球 {ens.over25:.1%}；双方进球 {ens.btts:.1%}",
            f"  期望比分：主 {ens.lam_home:.2f} : 客 {ens.lam_away:.2f}",
            "  最可能比分：" + "、".join(f"{k} ({v:.1%})" for k, v in
                                     sorted(ens.score_matrix.items(), key=lambda kv: -kv[1])[:5]),
            "", "三、关键不确定因素",
            "  · 数据来源为公开接口，缺少 xG、伤停、官方首发与赔率时相关维度标记 UNKNOWN。",
            "  · 概率为模型输出，非确定结论；建议结合赛前首发公布后重新计算。",
            "", "注：本报告只解释真实数据与模型输出，不改动模型计算结果。",
        ]
        return "\n".join(lines)


# ---------------- 赛后复盘 ----------------
class Reviewer:
    def __init__(self, store: Store):
        self.store = store

    def finalize(self, match_id: str, home_score: int, away_score: int,
                 home_ht: Optional[int] = None, away_ht: Optional[int] = None,
                 source: str = "ESPN 公开比分接口") -> Optional[Dict[str, Any]]:
        snap = self.store.get_prediction(match_id)
        if not snap:
            log(f"复盘跳过：{match_id} 没有赛前快照，拒绝补造预测")
            return None
        self.store.save_result(match_id, home_score, away_score, home_ht, away_ht,
                               "post", source)
        ens = json.loads(snap["ensemble"])
        models = json.loads(snap["models"])
        y = outcome_of(home_score, away_score)
        pred = snap["outcome"] or "H"
        matrix = json.loads(snap["score_matrix"] or "{}")
        score_pick = snap["score_pick"]
        review = {
            "match_id": match_id,
            "home": snap["home"], "away": snap["away"],
            "reviewed_at": _now(),
            "prediction_created_at": snap["created_at"],
            "prediction_sha": snap["snapshot_sha"],
            "data_cutoff": snap["data_cutoff"],
            "actual": {"home_score": home_score, "away_score": away_score,
                       "home_ht": home_ht, "away_ht": away_ht, "outcome": y},
            "predicted": {"outcome": pred, "score_pick": score_pick,
                          "ou_pick": snap["ou_pick"], "btts_pick": bool(snap["btts_pick"]),
                          "ht_outcome": snap["ht_outcome"],
                          "probs": [ens["home_win"], ens["draw"], ens["away_win"]]},
            "wdl_hit": pred == y,
            "score_hit": score_pick == f"{home_score}-{away_score}",
            "ou_hit": snap["ou_pick"] == ("over" if home_score + away_score >= 3 else "under"),
            "btts_hit": bool(snap["btts_pick"]) == (home_score > 0 and away_score > 0),
            "ht_hit": (outcome_of(home_ht, away_ht) == snap["ht_outcome"])
            if home_ht is not None and snap.get("ht_outcome") else None,
            "actual_score_prob": matrix.get(f"{home_score}-{away_score}"),
            "model_probs": {k: {"H": v.get("home_win"), "D": v.get("draw"),
                                "A": v.get("away_win")} for k, v in models.items()},
            "brier": brier_multiclass([ens["home_win"], ens["draw"], ens["away_win"]],
                                      [1 if y == k else 0 for k in ("H", "D", "A")]),
            "failure_reason": self._diagnose(snap, ens, y, home_score, away_score),
            "note": "赛后只新增结果，原始预测快照保持不变（sha256 可校验）",
        }
        self.store.save_review(match_id, review)
        # Elo 赛后更新（写入新评分，旧快照不受影响）
        self.store.upsert_elo(snap["home"], update_elo(self.store.get_elo(snap["home"]),
                                                       self.store.get_elo(snap["away"]),
                                                       1 if y == "H" else (0.5 if y == "D" else 0),
                                                       home=True))
        self.store.upsert_elo(snap["away"], update_elo(self.store.get_elo(snap["away"]),
                                                       self.store.get_elo(snap["home"]),
                                                       1 if y == "A" else (0.5 if y == "D" else 0),
                                                       home=False))
        return review

    @staticmethod
    def _diagnose(snap: Dict[str, Any], ens: Dict[str, Any], y: str,
                  hg: int, ag: int) -> str:
        pred = snap["outcome"]
        if pred == y:
            return "预测方向正确"
        reasons = []
        if float(snap["data_quality"] or 0) < 1:
            reasons.append(f"数据完整度仅 {float(snap['data_quality']):.0%}，部分维度为估算值")
        probs = {"H": ens["home_win"], "D": ens["draw"], "A": ens["away_win"]}
        if max(probs.values()) < 0.45:
            reasons.append("三方概率接近，本身属于高不确定场次")
        if abs(hg - ag) >= 3:
            reasons.append("实际分差较大，属低概率事件")
        reasons.append(f"模型给出 {pred}，实际为 {y}")
        return "；".join(reasons)

    def summary(self, league: Optional[str] = None, days: Optional[int] = None) -> Dict[str, Any]:
        rows = self.store.reviews(limit=5000)
        items = [r["payload"] for r in rows]
        if league:
            items = [i for i in items if i.get("match_id") in
                     {p["match_id"] for p in self.store.all_predictions()
                      if p.get("league") == league}]
        if days:
            cutoff = time.time() - days * 86400
            items = [i for i in items if i.get("reviewed_at", "") and
                     datetime.fromisoformat(i["reviewed_at"]).timestamp() >= cutoff]
        n = len(items)
        if n == 0:
            return {"n": 0, "note": "暂无复盘样本"}
        hit = sum(1 for i in items if i.get("wdl_hit"))
        return {
            "n": n, "wdl_accuracy": hit / n,
            "wdl_ci95": wilson_interval(hit, n),
            "score_accuracy": sum(1 for i in items if i.get("score_hit")) / n,
            "ou_accuracy": sum(1 for i in items if i.get("ou_hit")) / n,
            "btts_accuracy": sum(1 for i in items if i.get("btts_hit")) / n,
            "avg_brier": sum(i.get("brier") or 0 for i in items) / n,
            "sufficient_sample": n >= MIN_SAMPLES,
            "scope": {"league": league, "days": days},
        }


# ---------------- 历史回测 ----------------
class Backtester:
    """按时间顺序回测：每场只用该场之前的数据拟合模型，杜绝未来数据泄漏。"""

    def __init__(self, store: Store, weights: Optional[Dict[str, float]] = None):
        self.store = store
        self.weights = weights or DEFAULT_WEIGHTS

    def run(self, matches: Sequence[Dict[str, Any]], task_id: str,
            scope: Optional[Dict[str, Any]] = None,
            train_ratio: float = 0.5, val_ratio: float = 0.2) -> Dict[str, Any]:
        rows = sorted([m for m in matches if m.get("home_score") is not None
                       and m.get("away_score") is not None],
                      key=lambda x: (x.get("kickoff") or "", x.get("match_id") or ""))
        n = len(rows)
        if n < 10:
            return {"task_id": task_id, "n": n, "error": "样本不足 10 场，拒绝生成回测结果"}
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)
        splits = {"train": rows[:n_train], "val": rows[n_train:n_train + n_val],
                  "test": rows[n_train + n_val:]}
        elo: Dict[str, float] = {}
        stats: Dict[str, Dict[str, float]] = {}
        preds: List[Dict[str, Any]] = []
        for m in rows:  # 时间顺序推进
            h, a = m["home"], m["away"]
            elo.setdefault(h, 1500.0)
            elo.setdefault(a, 1500.0)
            sh = stats.setdefault(h, {"gf": 0.0, "ga": 0.0, "n": 0, "hgf": 0.0, "hga": 0.0,
                                      "hn": 0, "agf": 0.0, "aga": 0.0, "an": 0})
            sa = stats.setdefault(a, {"gf": 0.0, "ga": 0.0, "n": 0, "hgf": 0.0, "hga": 0.0,
                                      "hn": 0, "agf": 0.0, "aga": 0.0, "an": 0})
            part = "test" if m in splits["test"] else ("val" if m in splits["val"] else "train")
            if part != "train" and sh["n"] > 0 and sa["n"] > 0:
                f = MF(home=h, away=a, elo_home=elo[h], elo_away=elo[a])
                f.home_gf = sh["gf"] / sh["n"]
                f.home_ga = sh["ga"] / sh["n"]
                f.away_gf = sa["gf"] / sa["n"]
                f.away_ga = sa["ga"] / sa["n"]
                f.home_rest_days = m.get("rest_home")
                f.away_rest_days = m.get("rest_away")
                rs = [REGISTRY[k].predict(f) for k in
                      ("Elo", "Poisson", "DixonColes", "Skellam", "Form")]
                ens = fuse(rs, self.weights)
                top = sorted(ens.score_matrix.items(), key=lambda kv: -kv[1])
                preds.append({
                    "match_id": m["match_id"], "league": m.get("league"), "part": part,
                    "home_win": ens.home_win, "draw": ens.draw, "away_win": ens.away_win,
                    "outcome": ("H" if ens.home_win >= max(ens.draw, ens.away_win) else
                                "D" if ens.draw >= ens.away_win else "A"),
                    "score_pick": top[0][0] if top else None,
                    "ou_pick": "over" if ens.over25 >= 0.5 else "under",
                    "btts_pick": ens.btts >= 0.5,
                    "ht_outcome": ("H" if ens.ht_home >= max(ens.ht_draw, ens.ht_away) else
                                   "D" if ens.ht_draw >= ens.ht_away else "A"),
                    "model_probs": {r.model: [r.home_win, r.draw, r.away_win] for r in rs},
                })
            # 赛后更新（只影响后续比赛）
            hg, ag = int(m["home_score"]), int(m["away_score"])
            elo[h] = update_elo(elo[h], elo[a], 1 if hg > ag else (0.5 if hg == ag else 0),
                                home=True)
            elo[a] = update_elo(elo[a], elo[h], 1 if hg < ag else (0.5 if hg == ag else 0),
                                home=False)
            for s, gf, ga in ((sh, hg, ag), (sa, ag, hg)):
                s["gf"] += gf
                s["ga"] += ga
                s["n"] += 1
        payload: Dict[str, Any] = {
            "task_id": task_id, "created_at": _now(), "model_version": MODEL_VERSION,
            "weights": self.weights,
            "scope": scope or {}, "n_total": n,
            "splits": {"train": len(splits["train"]), "val": len(splits["val"]),
                       "test": len(splits["test"])},
            "leakage_guard": "模型只使用当前比赛之前的赛果与 Elo，训练/验证/测试按时间切分",
        }
        for part in ("val", "test"):
            pp = [p for p in preds if p["part"] == part]
            rr = [{"match_id": p["match_id"], "home_score": None, "away_score": None} for p in pp]
            payload[f"{part}_metrics"] = evaluate(pp, [
                {"match_id": m["match_id"], "home_score": int(m["home_score"]),
                 "away_score": int(m["away_score"]), "home_ht": m.get("home_ht"),
                 "away_ht": m.get("away_ht")}
                for m in rows if any(p["match_id"] == m["match_id"] for p in pp)])
            # 单模型对比（胜平负方向）
            per: Dict[str, float] = {}
            for model in ("Elo", "Poisson", "DixonColes", "Skellam", "Form"):
                hit = 0
                tot = 0
                for p in pp:
                    probs = p["model_probs"].get(model)
                    if not probs:
                        continue
                    pick = "HDA"[max(range(3), key=lambda i: probs[i])]
                    actual = outcome_of(
                        int(next(m["home_score"] for m in rows if m["match_id"] == p["match_id"])),
                        int(next(m["away_score"] for m in rows if m["match_id"] == p["match_id"])))
                    hit += pick == actual
                    tot += 1
                if tot:
                    per[model] = hit / tot
            payload[f"{part}_model_compare"] = per
            payload[f"{part}_model_compare_n"] = tot if 'tot' in dir() else 0
        self.store.save_backtest(task_id, scope or {}, self.weights, payload)
        return payload


# ---------------- 排行榜 ----------------
def build_leaderboard(store: Store, scope: Optional[Dict[str, Any]] = None,
                      days: Optional[int] = None, min_samples: int = MIN_SAMPLES) -> Dict[str, Any]:
    """只统计真实保存的预测与赛果；样本不足标注“样本不足”，不参与排名。"""
    scope = scope or {}
    preds = store.all_predictions()
    rows = []
    for p in preds:
        rev = store.reviews(p["match_id"])
        if not rev:
            continue
        payload = rev[0]["payload"]
        if scope.get("league") and p.get("league") != scope["league"]:
            continue
        if days:
            cutoff = time.time() - days * 86400
            try:
                if datetime.fromisoformat(payload.get("reviewed_at", "")).timestamp() < cutoff:
                    continue
            except Exception:  # noqa
                continue
        rows.append((p, payload))
    models = ["Elo", "Poisson", "DixonColes", "Skellam", "Form", "Ensemble"]
    board: List[Dict[str, Any]] = []
    for name in models:
        ps: List[Dict[str, Any]] = []
        for p, payload in rows:
            if name == "Ensemble":
                ens = json.loads(p["ensemble"])
                probs = [ens["home_win"], ens["draw"], ens["away_win"]]
            else:
                m = (json.loads(p["models"]).get(name) or {})
                probs = [m.get("home_win"), m.get("draw"), m.get("away_win")]
                if None in probs:
                    continue
            ps.append({"match_id": p["match_id"], "home_win": probs[0], "draw": probs[1],
                       "away_win": probs[2],
                       "outcome": "HDA"[max(range(3), key=lambda i: probs[i])],
                       "score_pick": p.get("score_pick"), "ou_pick": p.get("ou_pick"),
                       "btts_pick": bool(p.get("btts_pick")), "ht_outcome": p.get("ht_outcome")})
        res = [{"match_id": r["match_id"],
                "home_score": r[1]["actual"]["home_score"],
                "away_score": r[1]["actual"]["away_score"],
                "home_ht": r[1]["actual"].get("home_ht"),
                "away_ht": r[1]["actual"].get("away_ht")} for r, _ in
               [(x, y) for x, y in rows if any(q["match_id"] == x["match_id"] for q in ps)]]
        metrics = evaluate(ps, res)
        n = metrics.get("n", 0)
        board.append({
            "model": name, "version": MODEL_VERSION, "n": n,
            "wdl_accuracy": metrics.get("wdl_accuracy") if n else None,
            "wdl_ci95": metrics.get("wdl_ci95") if n else None,
            "log_loss": metrics.get("log_loss") if n else None,
            "brier": metrics.get("brier") if n else None,
            "score_accuracy": metrics.get("score_accuracy") if n else None,
            "ou_accuracy": metrics.get("ou_accuracy") if n else None,
            "calibration_error": metrics.get("calibration_error") if n else None,
            "sufficient_sample": n >= min_samples,
            "status": "参与排名" if n >= min_samples else f"样本不足（<{min_samples}）",
            "updated_at": _now(),
        })
    ranked = sorted([b for b in board if b["sufficient_sample"]],
                    key=lambda b: (-(b["wdl_accuracy"] or 0), b["log_loss"] or 9))
    for i, b in enumerate(ranked, 1):
        b["rank"] = i
    for b in board:
        if not b["sufficient_sample"]:
            b["rank"] = None
    return {"scope": scope, "days": days, "min_samples": min_samples,
            "board": sorted(board, key=lambda b: (b["rank"] is None, b["rank"] or 99)),
            "note": "排名只基于真实赛果复盘；样本不足的模型不参与排名。不同联赛/预测类型不混排。"}
