"""足球数学预测引擎。

五个模型各自独立计算，结果全部保留，互不覆盖：
1. 动态 Elo（含主客场修正）
2. 泊松独立进球模型
3. Dixon-Coles 低比分修正模型
4. Skellam 比分差模型
5. 近期状态 + 攻防效率模型
融合层使用固定权重加权，并做归一化与数学校验。
本模块不调用任何大模型，不产生编造概率。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Tuple

MAX_GOALS = 8
MODEL_VERSION = "1.0.0"


def _poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _skellam_pmf(d: int, l1: float, l2: float) -> float:
    """Skellam 分布概率质量函数（修正贝塞尔函数 I_{|d|}）。"""
    if l1 <= 0 or l2 <= 0:
        return 1.0 if d == 0 else 0.0
    s = 0.0
    for k in range(0, 60):
        s += _poisson(k + max(d, 0), l1) * _poisson(k + max(-d, 0), l2)
    return s


def _tau(i: int, j: int, l1: float, l2: float, rho: float) -> float:
    """Dixon-Coles 低比分修正项。"""
    if i == 0 and j == 0:
        return 1.0 - l1 * l2 * rho
    if i == 0 and j == 1:
        return 1.0 + l1 * rho
    if i == 1 and j == 0:
        return 1.0 + l2 * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


@dataclass
class MatchFeatures:
    home: str
    away: str
    elo_home: float = 1500.0
    elo_away: float = 1500.0
    home_advantage: float = 65.0
    # 近期场均进/失球
    home_gf: Optional[float] = None
    home_ga: Optional[float] = None
    away_gf: Optional[float] = None
    away_ga: Optional[float] = None
    league_avg_home: float = 1.45
    league_avg_away: float = 1.20
    home_rest_days: Optional[int] = None
    away_rest_days: Optional[int] = None
    data_quality: float = 1.0

    def ready(self) -> bool:
        return None not in (self.home_gf, self.home_ga, self.away_gf, self.away_ga)


@dataclass
class ModelResult:
    model: str
    version: str = MODEL_VERSION
    params: Dict[str, float] = field(default_factory=dict)
    home_win: float = 0.0
    draw: float = 0.0
    away_win: float = 0.0
    over25: float = 0.0
    btts: float = 0.0
    lam_home: float = 0.0
    lam_away: float = 0.0
    score_matrix: Dict[str, float] = field(default_factory=dict)
    ht_home: float = 0.0
    ht_draw: float = 0.0
    ht_away: float = 0.0
    degraded: bool = False
    note: str = ""

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _matrix_from_lambda(lh: float, la: float, rho: float = 0.0,
                        ht_share: float = 0.45) -> Tuple[Dict[str, float], Dict[str, float]]:
    raw: Dict[Tuple[int, int], float] = {}
    total = 0.0
    for i in range(0, MAX_GOALS + 1):
        for j in range(0, MAX_GOALS + 1):
            p = _poisson(i, lh) * _poisson(j, la)
            if rho:
                p *= _tau(i, j, lh, la, rho)
            if p < 0:
                p = 0.0
            raw[(i, j)] = p
            total += p
    matrix: Dict[str, float] = {}
    for (i, j), p in raw.items():
        if total > 0:
            matrix[f"{i}-{j}"] = p / total
    # 半场：以全场进球率缩放（明确标注为估算）
    ht: Dict[str, float] = {}
    lh_h, la_h = lh * ht_share, la * ht_share
    for i in range(0, 5):
        for j in range(0, 5):
            ht[f"{i}-{j}"] = _poisson(i, lh_h) * _poisson(j, la_h)
    s = sum(ht.values()) or 1.0
    ht = {k: v / s for k, v in ht.items()}
    return matrix, ht


def _outcomes(matrix: Dict[str, float]) -> Tuple[float, float, float, float, float]:
    hw = draw = aw = over = btts = 0.0
    for key, p in matrix.items():
        i, j = (int(x) for x in key.split("-"))
        if i > j:
            hw += p
        elif i == j:
            draw += p
        else:
            aw += p
        if i + j >= 3:
            over += p
        if i >= 1 and j >= 1:
            btts += p
    s = hw + draw + aw
    if s > 0:
        hw, draw, aw = hw / s, draw / s, aw / s
    return hw, draw, aw, over, btts


class EloModel:
    name = "Elo"

    @staticmethod
    def predict(f: MatchFeatures) -> ModelResult:
        rh = f.elo_home + f.home_advantage
        ra = f.elo_away
        diff = (rh - ra) / 400.0
        qh, qa = 10 ** diff, 10 ** (-diff)
        exp_h = qh / (qh + qa)
        # Elo 期望分（胜=1，平=0.5）拆成胜平负
        draw_base = 0.27
        hw = exp_h - draw_base / 2
        aw = (1 - exp_h) - draw_base / 2
        hw = max(hw, 0.01)
        aw = max(aw, 0.01)
        draw = max(1 - hw - aw, 0.01)
        s = hw + draw + aw
        hw, draw, aw = hw / s, draw / s, aw / s
        # Elo 不直接给比分，用期望进球映射（估算）
        lh = max(0.2, 1.35 * (exp_h / 0.5) ** 1.2)
        la = max(0.2, 1.25 * ((1 - exp_h) / 0.5) ** 1.2)
        matrix, ht = _matrix_from_lambda(lh, la)
        _, _, _, over, btts = _outcomes(matrix)
        return ModelResult(
            model=EloModel.name, params={"home_advantage": f.home_advantage, "K": 20.0,
                                         "draw_base": draw_base},
            home_win=hw, draw=draw, away_win=aw, over25=over, btts=btts,
            lam_home=lh, lam_away=la, score_matrix=matrix,
            ht_home=sum(v for k, v in ht.items() if int(k[0]) > int(k[2])),
            ht_draw=sum(v for k, v in ht.items() if k[0] == k[2]),
            ht_away=sum(v for k, v in ht.items() if int(k[0]) < int(k[2])),
            degraded=True, note="Elo 只输出胜平负，比分与大小球为期望进球映射的估算值",
        )


class PoissonModel:
    name = "Poisson"

    @staticmethod
    def lambdas(f: MatchFeatures) -> Tuple[float, float]:
        if not f.ready():
            return f.league_avg_home, f.league_avg_away
        lh = f.league_avg_home * (f.home_gf / f.league_avg_home) * (f.away_ga / f.league_avg_home)  # noqa
        la = f.league_avg_away * (f.away_gf / f.league_avg_away) * (f.home_ga / f.league_avg_away)  # noqa
        return max(lh, 0.05), max(la, 0.05)

    @classmethod
    def predict(cls, f: MatchFeatures) -> ModelResult:
        lh, la = cls.lambdas(f)
        matrix, ht = _matrix_from_lambda(lh, la)
        hw, draw, aw, over, btts = _outcomes(matrix)
        return ModelResult(
            model=PoissonModel.name, params={"league_avg_home": f.league_avg_home,
                                             "league_avg_away": f.league_avg_away},
            home_win=hw, draw=draw, away_win=aw, over25=over, btts=btts,
            lam_home=lh, lam_away=la, score_matrix=matrix,
            ht_home=sum(v for k, v in ht.items() if int(k[0]) > int(k[2])),
            ht_draw=sum(v for k, v in ht.items() if k[0] == k[2]),
            ht_away=sum(v for k, v in ht.items() if int(k[0]) < int(k[2])),
            degraded=not f.ready(),
            note="" if f.ready() else "缺少近期进失球数据，使用联赛均值（估算）",
        )


class DixonColesModel:
    name = "DixonColes"

    @classmethod
    def predict(cls, f: MatchFeatures, rho: float = -0.08) -> ModelResult:
        lh, la = PoissonModel.lambdas(f)
        matrix, ht = _matrix_from_lambda(lh, la, rho=rho)
        hw, draw, aw, over, btts = _outcomes(matrix)
        return ModelResult(
            model=DixonColesModel.name, params={"rho": rho,
                                               "league_avg_home": f.league_avg_home,
                                               "league_avg_away": f.league_avg_away},
            home_win=hw, draw=draw, away_win=aw, over25=over, btts=btts,
            lam_home=lh, lam_away=la, score_matrix=matrix,
            ht_home=sum(v for k, v in ht.items() if int(k[0]) > int(k[2])),
            ht_draw=sum(v for k, v in ht.items() if k[0] == k[2]),
            ht_away=sum(v for k, v in ht.items() if int(k[0]) < int(k[2])),
            degraded=not f.ready(),
            note="" if f.ready() else "缺少近期进失球数据，使用联赛均值（估算）",
        )


class SkellamModel:
    name = "Skellam"

    @classmethod
    def predict(cls, f: MatchFeatures) -> ModelResult:
        lh, la = PoissonModel.lambdas(f)
        total = lh + la
        hw = aw = 0.0
        for d in range(1, 8):
            hw += _skellam_pmf(d, lh, la)
            aw += _skellam_pmf(-d, lh, la)
        draw = _skellam_pmf(0, lh, la)
        s = hw + draw + aw
        if s > 0:
            hw, draw, aw = hw / s, draw / s, aw / s
        over = 1 - math.exp(-total) * sum(total ** k / math.factorial(k) for k in range(0, 3))
        btts = (1 - math.exp(-lh)) * (1 - math.exp(-la))
        matrix, ht = _matrix_from_lambda(lh, la)
        return ModelResult(
            model=SkellamModel.name, params={},
            home_win=hw, draw=draw, away_win=aw,
            over25=min(max(over, 0.0), 1.0), btts=min(max(btts, 0.0), 1.0),
            lam_home=lh, lam_away=la, score_matrix=matrix,
            ht_home=sum(v for k, v in ht.items() if int(k[0]) > int(k[2])),
            ht_draw=sum(v for k, v in ht.items() if k[0] == k[2]),
            ht_away=sum(v for k, v in ht.items() if int(k[0]) < int(k[2])),
            degraded=not f.ready(),
            note="Skellam 建模净胜球分布；比分矩阵借用同参数泊松展开",
        )


class FormModel:
    """近期状态 + 攻防效率 + 体能修正模型。"""
    name = "Form"

    @classmethod
    def predict(cls, f: MatchFeatures, form_weight: float = 0.35) -> ModelResult:
        base_h, base_a = PoissonModel.lambdas(f)
        rest_h = f.home_rest_days if f.home_rest_days is not None else 7
        rest_a = f.away_rest_days if f.away_rest_days is not None else 7
        fatigue_h = 1.0 if rest_h >= 5 else (0.92 if rest_h >= 3 else 0.82)
        fatigue_a = 1.0 if rest_a >= 5 else (0.92 if rest_a >= 3 else 0.82)
        lh = max(base_h * fatigue_h * (1 + form_weight * 0.15), 0.05)
        la = max(base_a * fatigue_a * (1 - form_weight * 0.05), 0.05)
        matrix, ht = _matrix_from_lambda(lh, la)
        hw, draw, aw, over, btts = _outcomes(matrix)
        return ModelResult(
            model=FormModel.name,
            params={"form_weight": form_weight, "rest_home": rest_h, "rest_away": rest_a,
                    "fatigue_home": fatigue_h, "fatigue_away": fatigue_a},
            home_win=hw, draw=draw, away_win=aw, over25=over, btts=btts,
            lam_home=lh, lam_away=la, score_matrix=matrix,
            ht_home=sum(v for k, v in ht.items() if int(k[0]) > int(k[2])),
            ht_draw=sum(v for k, v in ht.items() if k[0] == k[2]),
            ht_away=sum(v for k, v in ht.items() if int(k[0]) < int(k[2])),
            degraded=not f.ready() or f.home_rest_days is None,
            note="" if f.ready() else "缺少近期状态或休息天数，使用替代值（估算）",
        )


REGISTRY = {
    EloModel.name: EloModel,
    PoissonModel.name: PoissonModel,
    DixonColesModel.name: DixonColesModel,
    SkellamModel.name: SkellamModel,
    FormModel.name: FormModel,
}

DEFAULT_WEIGHTS = {"Elo": 0.25, "Poisson": 0.25, "DixonColes": 0.25,
                   "Skellam": 0.10, "Form": 0.15}


def check_probabilities(home: float, draw: float, away: float, tol: float = 0.02) -> bool:
    """数学校验：三项非负且和为 1。"""
    if min(home, draw, away) < 0:
        return False
    return abs(home + draw + away - 1.0) <= tol


def fuse(results: Sequence[ModelResult],
         weights: Optional[Dict[str, float]] = None) -> ModelResult:
    """多模型融合：固定权重加权，随后归一化并做校验。"""
    w = dict(weights or DEFAULT_WEIGHTS)
    usable = [r for r in results if r.model in w]
    if not usable:
        raise ValueError("没有可用的模型结果，拒绝生成融合预测")
    scale = sum(w[r.model] for r in usable) or 1.0
    hw = sum(w[r.model] * r.home_win for r in usable) / scale
    dr = sum(w[r.model] * r.draw for r in usable) / scale
    aw = sum(w[r.model] * r.away_win for r in usable) / scale
    over = sum(w[r.model] * r.over25 for r in usable) / scale
    btts = sum(w[r.model] * r.btts for r in usable) / scale
    lh = sum(w[r.model] * r.lam_home for r in usable) / scale
    la = sum(w[r.model] * r.lam_away for r in usable) / scale
    matrix: Dict[str, float] = {}
    for r in usable:
        for k, v in r.score_matrix.items():
            matrix[k] = matrix.get(k, 0.0) + w[r.model] * v
    ms = sum(matrix.values()) or 1.0
    matrix = {k: v / ms for k, v in matrix.items()}
    s = hw + dr + aw
    hw, dr, aw = hw / s, dr / s, aw / s
    if not check_probabilities(hw, dr, aw):
        raise ValueError("融合概率校验失败，拒绝输出预测")
    return ModelResult(
        model="Ensemble", version=MODEL_VERSION,
        params={"weights": {k: v / scale for k, v in w.items() if k in
                            {r.model for r in usable}}},
        home_win=hw, draw=dr, away_win=aw, over25=over, btts=btts,
        lam_home=lh, lam_away=la, score_matrix=matrix,
        ht_home=sum(v for k, v in matrix.items() if int(k[0]) > int(k[2])) * 0.45,
        ht_draw=sum(v for k, v in matrix.items() if k[0] == k[2]) * 0.45,
        ht_away=sum(v for k, v in matrix.items() if int(k[0]) < int(k[2])) * 0.45,
        degraded=any(r.degraded for r in usable),
        note="融合权重：" + ", ".join(f"{k}={v/scale:.2f}" for k, v in w.items()),
    )


def update_elo(rating: float, opponent: float, score: float, k: int = 20,
               home_advantage: float = 65.0, home: bool = True) -> float:
    """赛后 Elo 更新（score: 1 胜 0.5 平 0 负）。"""
    diff = ((rating + (home_advantage if home else 0)) - opponent) / 400.0
    exp = 1.0 / (1 + 10 ** (-diff))
    return rating + k * (score - exp)
