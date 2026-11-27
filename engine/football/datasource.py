"""统一足球数据采集层。

数据源优先级：
1. ESPN 公开 JSON 接口（无需密钥，非官方接口，可能被限制）
2. football-data.org（免费密钥，X-Auth-Token 头，受限赛事返回 403）
3. 本地历史 CSV（football-data.co.uk 格式，用于回测）

所有返回值都附带 provenance 元信息：来源、采集时间、数据状态、可信度、是否估算。
禁止在缺失数据时补零或伪造。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/soccer"
FD_ORG = "https://api.football-data.org/v4"

# 覆盖的主要联赛：ESPN slug -> (中文名, 国家/地区)
LEAGUES: Dict[str, tuple] = {
    "eng.1": ("英超", "英格兰"),
    "esp.1": ("西甲", "西班牙"),
    "ita.1": ("意甲", "意大利"),
    "ger.1": ("德甲", "德国"),
    "fra.1": ("法甲", "法国"),
    "por.1": ("葡超", "葡萄牙"),
    "ned.1": ("荷甲", "荷兰"),
    "bel.1": ("比甲", "比利时"),
    "tur.1": ("土超", "土耳其"),
    "sco.1": ("苏超", "苏格兰"),
    "bra.1": ("巴甲", "巴西"),
    "arg.1": ("阿甲", "阿根廷"),
    "usa.1": ("美职联", "美国"),
    "mex.1": ("墨西哥甲级", "墨西哥"),
    "jpn.1": ("日职联", "日本"),
    "kor.1": ("韩K联", "韩国"),
    "chn.1": ("中超", "中国"),
    "aus.1": ("澳超", "澳大利亚"),
    "sau.1": ("沙特联", "沙特"),
    "uefa.champions": ("欧冠", "欧洲"),
    "uefa.europa": ("欧联", "欧洲"),
    "uefa.europa.conf": ("欧协联", "欧洲"),
    "conmebol.libertadores": ("解放者杯", "南美"),
    "fifa.world": ("世界杯", "国际"),
}

STALE_SECONDS = 6 * 3600


@dataclass
class Provenance:
    source: str
    fetched_at: str
    status: str = "REAL"          # REAL / ESTIMATED / UNKNOWN / STALE
    confidence: float = 1.0
    is_estimated: bool = False
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Match:
    match_id: str
    league: str
    league_name: str
    country: str
    kickoff: str
    status: str               # pre / in / post
    status_text: str
    home: str
    away: str
    home_id: str = ""
    away_id: str = ""
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_ht: Optional[int] = None
    away_ht: Optional[int] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    prov: Optional[Provenance] = None


class HttpError(RuntimeError):
    pass


def _get_json(url: str, headers: Optional[Dict[str, str]] = None,
              timeout: int = 20, retries: int = 2) -> Any:
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "python-requests/2.31")
            req.add_header("Accept", "application/json")
            for k, v in (headers or {}).items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:  # noqa
            last = exc
            if getattr(exc, "code", None) in (401, 403, 404):
                break
            time.sleep(1.5 * (attempt + 1))
    raise HttpError(f"GET {url} failed: {last}")


def utc() -> str:
    return _now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(iso: str) -> float:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return abs(datetime.now(timezone.utc).timestamp() - t.timestamp())
    except Exception:  # noqa
        return 0.0


class DataSource:
    """带备用切换的数据源管理器。"""

    def __init__(self, fd_token: Optional[str] = None, cache_dir: Optional[str] = None,
                 offline: bool = False):
        self.fd_token = fd_token or os.environ.get("FOOTBALL_DATA_TOKEN") or ""
        self.cache_dir = cache_dir
        self.offline = offline
        self.health: Dict[str, Dict[str, Any]] = {}
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    # ---------- 健康监控 ----------
    def _record(self, name: str, ok: bool, detail: str = "") -> None:
        self.health[name] = {"ok": ok, "detail": detail, "checked_at": _now()}

    def health_report(self) -> Dict[str, Any]:
        return {
            "sources": self.health,
            "offline": self.offline,
            "checked_at": _now(),
            "note": "REAL 表示真实接口取得；数据缺失一律标 UNKNOWN，不做补零。",
        }

    # ---------- ESPN ----------
    def scoreboard(self, league: str, date: Optional[str] = None) -> List[Match]:
        """date 形如 20261127（日）或 202611（月）或 2026（年）。"""
        url = f"{ESPN_SITE}/{league}/scoreboard"
        params: Dict[str, Any] = {"limit": 100}
        if date:
            params["dates"] = date
        full = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        try:
            data = _get_json(full)
        except HttpError as exc:
            self._record(f"espn:{league}", False, str(exc))
            return []
        events = data.get("events") or []
        self._record(f"espn:{league}", True, f"{len(events)} events")
        out: List[Match] = []
        for ev in events:
            m = self._parse_espn_event(ev, league)
            if m:
                out.append(m)
        return out

    def _parse_espn_event(self, ev: Dict[str, Any], league: str) -> Optional[Match]:
        try:
            comp = (ev.get("competitions") or [{}])[0]
            competitors = comp.get("competitors") or []
            if len(competitors) != 2:
                return None
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            status = ((ev.get("status") or {}).get("type") or {})
            state = status.get("state") or "pre"
            name_cn, country = LEAGUES.get(league, (ev.get("league", {}).get("name", league), ""))
            stats: Dict[str, Any] = {}
            for c in competitors:
                side = "home" if c is home else "away"
                raw = c.get("statistics") or {}
                for item in raw if isinstance(raw, list) else []:
                    key = item.get("name") or item.get("type")
                    val = item.get("displayValue") or item.get("value")
                    if key and val is not None:
                        stats[f"{side}_{key}"] = val
            return Match(
                match_id=str(ev.get("id") or ""),
                league=league,
                league_name=name_cn,
                country=country,
                kickoff=(ev.get("date") or ""),
                status=state,
                status_text=status.get("description") or "",
                home=(home.get("team") or {}).get("displayName") or "",
                away=(away.get("team") or {}).get("displayName") or "",
                home_id=str((home.get("team") or {}).get("id") or ""),
                away_id=str((away.get("team") or {}).get("id") or ""),
                home_score=self._int(home.get("score")),
                away_score=self._int(away.get("score")),
                stats=stats,
                prov=Provenance(source="ESPN 公开比分接口（非官方）", fetched_at=_now(),
                                status="REAL", confidence=0.85),
            )
        except Exception:  # noqa
            return None

    @staticmethod
    def _int(v: Any) -> Optional[int]:
        try:
            return int(v)
        except Exception:  # noqa
            return None

    def match_summary(self, league: str, match_id: str) -> Dict[str, Any]:
        url = f"{ESPN_SITE}/{league}/summary?event={match_id}"
        try:
            data = _get_json(url)
            self._record("espn:summary", True, match_id)
            return data
        except HttpError as exc:
            self._record("espn:summary", False, str(exc))
            return {}

    def standings(self, league: str, season: str) -> Dict[str, Any]:
        url = f"{ESPN_CORE}/{league}/standings?season={season}"
        try:
            data = _get_json(url)
            self._record(f"espn:standings:{league}", True, season)
            return data
        except HttpError as exc:
            self._record(f"espn:standings:{league}", False, str(exc))
            return {}

    # ---------- football-data.org（备用） ----------
    def fd_matches(self, code: str) -> List[Match]:
        if not self.fd_token:
            self._record("football-data.org", False, "未配置密钥")
            return []
        try:
            data = _get_json(f"{FD_ORG}/competitions/{code}/matches",
                             headers={"X-Auth-Token": self.fd_token})
        except HttpError as exc:
            self._record("football-data.org", False, str(exc))
            return []
        out: List[Match] = []
        for m in data.get("matches") or []:
            team = lambda k: ((m.get(k) or {}).get("name") or "")  # noqa
            score = (m.get("score") or {}).get("fullTime") or {}
            st = (m.get("status") or "")
            state = {"SCHEDULED": "pre", "TIMED": "pre", "IN_PLAY": "in",
                     "LIVE": "in", "FINISHED": "post"}.get(st, "pre")
            out.append(Match(
                match_id=f"fd{m.get('id')}", league=code,
                league_name=(m.get("competition") or {}).get("name", code),
                country=(m.get("area") or {}).get("name", ""),
                kickoff=m.get("utcDate") or "", status=state, status_text=st,
                home=team("homeTeam"), away=team("awayTeam"),
                home_score=self._int(score.get("home")), away_score=self._int(score.get("away")),
                prov=Provenance(source="football-data.org", fetched_at=_now(), status="REAL",
                                confidence=0.95),
            ))
        self._record("football-data.org", True, f"{len(out)} matches")
        return out

    # ---------- 今日赛事（多联赛聚合，失败联赛自动跳过并标注） ----------
    def today(self, date: Optional[str] = None, leagues: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        date = date or datetime.now(timezone.utc).strftime("%Y%m%d")
        matches: List[Match] = []
        failed: List[str] = []
        for slug in (leagues or LEAGUES.keys()):
            got = self.scoreboard(slug, date)
            if got:
                matches.extend(got)
            else:
                failed.append(slug)
        return {
            "date": date,
            "matches": [self._match_dict(m) for m in matches],
            "failed_leagues": failed,
            "coverage": f"{len(LEAGUES) - len(failed)}/{len(LEAGUES)} 个赛事取得数据",
            "note": "未取得数据的赛事标记为 UNKNOWN，不使用模拟数据填充。",
        }

    @staticmethod
    def _match_dict(m: Match) -> Dict[str, Any]:
        d = asdict(m)
        d["prov"] = m.prov.as_dict() if m.prov else None
        return d
