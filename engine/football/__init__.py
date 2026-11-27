"""全球足球智能分析引擎。"""
from .datasource import DataSource, Match, MatchFeatures, Provenance, LEAGUES
from .models import (MODEL_VERSION, DEFAULT_WEIGHTS, REGISTRY, ModelResult, fuse,
                     update_elo, check_probabilities)
from .pipeline import (Analyzer, Backtester, Reviewer, Store, build_leaderboard, evaluate,
                       log, utc, wilson_interval)
from .radar import DIMENSIONS, RadarDimension, build_radar

__version__ = "1.0.0"
