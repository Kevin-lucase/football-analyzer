"""16 维战力雷达。

每个维度都标注数据来源、评分口径、数据完整度；缺数据的维度一律返回
score=None / status=UNKNOWN，绝不自动补成 0 分或虚假分数。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .models import MatchFeatures, PoissonModel

DIMENSIONS: List[str] = [
    "整体实力", "近期状态", "主客场表现", "进攻能力", "防守能力", "进球效率",
    "射门创造能力", "防守限制能力", "中场控制能力", "阵容完整度", "核心球员能力",
    "替补阵容深度", "战术适配程度", "体能和休息情况", "历史交锋表现", "比赛环境适应能力",
]

_UNKNOWN = "UNKNOWN"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _scale(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return _clamp01((x - lo) / (hi - lo))


@dataclass
class DimScore:
    name: str
    score: Optional[float]
    status: str
    source: str
    formula: str
    completeness: float
    scored_at: str
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TeamRadar:
    team: str
    side: str
    dimensions: List[DimScore] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"team": self.team, "side": self.side,
                "dimensions": [d.as_dict() for d in self.dimensions],
                "known_count": sum(1 for d in self.dimensions if d.score is not None)}


def _mk(name: str, score: Optional[float], source: str, formula: str,
        completeness: float, scored_at: str, note: str = "") -> DimScore:
    return DimScore(name=name, score=None if score is None else round(score * 100, 1),
                    status=_UNKNOWN if score is None else "OK", source=source,
                    formula=formula, completeness=completeness, scored_at=scored_at,
                    note=note)


def build_radar(f: MatchFeatures, side: str, ctx: Optional[Dict[str, Any]] = None,
                scored_at: str = "") -> TeamRadar:
    """side: 'home' / 'away'。ctx 可含射门、控球、伤停、休息、交锋等可选数据。"""
    ctx = ctx or {}
    team = f.home if side == "home" else f.away
    gf = f.home_gf if side == "home" else f.away_gf
    ga = f.home_ga if side == "home" else f.away_ga
    elo = f.elo_home if side == "home" else f.away_away if False else (f.elo_home if side == "home" else f.elo_away)  # noqa
    rest = f.home_rest_days if side == "home" else f.away_rest_days
    lh, la = PoissonModel.lambdas(f)
    lam = lh if side == "home" else la

    dims: List[DimScore] = []
    # 1 整体实力：Elo 归一
    dims.append(_mk(DIMENSIONS[0], _scale(elo, 1200, 1900), "动态 Elo 模型",
                    "(Elo-1200)/(1900-1200)", 1.0, scored_at))
    # 2 近期状态
    form = ctx.get("form_points_ratio")
    dims.append(_mk(DIMENSIONS[1], None if form is None else _clamp01(form),
                    "近期10场积分", "近10场积分/(10*3)", 0.9 if form is not None else 0.0,
                    scored_at, "" if form is not None else "缺少近10场战绩"))
    # 3 主客场表现
    ha = ctx.get("home_away_ratio")
    if ha is None and gf is not None and ga is not None:
        ha = _clamp01(0.5 + (gf - ga) * 0.08 + (0.06 if side == "home" else 0))
    dims.append(_mk(DIMENSIONS[2], None if ha is None else _clamp01(ha),
                    "主客场进失球", "0.5+(主客净胜球)*0.08+主场加成",
                    0.8 if ha is not None else 0.0, scored_at))
    # 4 进攻能力
    dims.append(_mk(DIMENSIONS[3], _scale(lam, 0.4, 2.8), "泊松期望进球 λ",
                    "(λ-0.4)/(2.8-0.4)", 1.0 if gf is not None else 0.4, scored_at,
                    "" if gf is not None else "λ 由联赛均值估算"))
    # 5 防守能力
    opp = la if side == "home" else lh
    dims.append(_mk(DIMENSIONS[4], _scale(1 / max(opp, 0.1), 0.4, 3.0), "对手期望进球",
                    "(1/对手λ 归一)", 1.0 if ga is not None else 0.4, scored_at))
    # 6 进球效率
    conv = ctx.get("conversion")
    dims.append(_mk(DIMENSIONS[5], None if conv is None else _scale(conv, 0.05, 0.20),
                    "射门转化率", "进球/射门", 0.8 if conv is not None else 0.0, scored_at,
                    "" if conv is not None else "缺少射门数据"))
    # 7 射门创造能力
    sot = ctx.get("shots_on_target")
    dims.append(_mk(DIMENSIONS[6], None if sot is None else _scale(sot, 1.0, 7.0),
                    "场均射正", "射正数归一", 0.8 if sot is not None else 0.0, scored_at,
                    "" if sot is not None else "缺少射正数据"))
    # 8 防守限制能力
    ga_sot = ctx.get("shots_on_target_against")
    dims.append(_mk(DIMENSIONS[7], None if ga_sot is None else _scale(1 / max(ga_sot, 0.3), 0.15, 1.0),
                    "被射正数", "1/被射正 归一", 0.8 if ga_sot is not None else 0.0, scored_at,
                    "" if ga_sot is not None else "缺少被射正数据"))
    # 9 中场控制能力
    poss = ctx.get("possession")
    dims.append(_mk(DIMENSIONS[8], None if poss is None else _scale(poss, 35.0, 65.0),
                    "控球率", "(控球率-35)/(65-35)", 0.7 if poss is not None else 0.0,
                    scored_at, "" if poss is not None else "缺少控球数据"))
    # 10 阵容完整度
    avail = ctx.get("squad_availability")
    dims.append(_mk(DIMENSIONS[9], None if avail is None else _clamp01(avail),
                    "伤停名单", "可用主力数/主力总数", 0.7 if avail is not None else 0.0,
                    scored_at, "" if avail is not None else "缺少伤停数据"))
    # 11 核心球员能力
    key = ctx.get("key_player_rating")
    dims.append(_mk(DIMENSIONS[10], None if key is None else _scale(key, 5.5, 8.5),
                    "球员评分", "核心球员评分归一", 0.6 if key is not None else 0.0,
                    scored_at, "" if key is not None else "缺少球员评分数据"))
    # 12 替补阵容深度
    bench = ctx.get("bench_quality")
    dims.append(_mk(DIMENSIONS[11], None if bench is None else _scale(bench, 0.3, 0.9),
                    "替补贡献占比", "替补进球+助攻占比", 0.5 if bench is not None else 0.0,
                    scored_at, "" if bench is not None else "缺少替补数据"))
    # 13 战术适配程度
    tactic = ctx.get("tactic_fit")
    dims.append(_mk(DIMENSIONS[12], None if tactic is None else _clamp01(tactic),
                    "教练战术适配", "定性评分（人工/估算）", 0.3 if tactic is not None else 0.0,
                    scored_at, "" if tactic is not None else "缺少战术数据"))
    # 14 体能和休息情况
    dims.append(_mk(DIMENSIONS[13], None if rest is None else _scale(rest, 2, 8),
                    "赛程休息天数", "(休息天数-2)/(8-2)", 0.7 if rest is not None else 0.0,
                    scored_at, "" if rest is not None else "缺少赛程数据"))
    # 15 历史交锋表现
    h2h = ctx.get("h2h_win_ratio")
    dims.append(_mk(DIMENSIONS[14], None if h2h is None else _clamp01(h2h),
                    "历史交锋近6场", "胜场数/场次", 0.7 if h2h is not None else 0.0,
                    scored_at, "" if h2h is not None else "缺少交锋数据"))
    # 16 比赛环境适应能力
    env = ctx.get("env_adapt")
    dims.append(_mk(DIMENSIONS[15], None if env is None else _clamp01(env),
                    "天气/场地/客场适应", "综合定性评分", 0.3 if env is not None else 0.0,
                    scored_at, "" if env is not None else "缺少天气与场地数据"))
    return TeamRadar(team=team, side=side, dimensions=dims)
