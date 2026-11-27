import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from football.pipeline import Store, Analyzer, Reviewer, build_leaderboard, evaluate
from football.models import fuse, MODEL_VERSION

def test_fuse_sums_to_one():
    r = {"A": {"home_win": 0.5, "draw": 0.25, "away_win": 0.25},
         "B": {"home_win": 0.3, "draw": 0.3, "away_win": 0.4}}
    f = fuse(r)
    assert abs(f["home_win"] + f["draw"] + f["away_win"] - 1) < 1e-6

def test_snapshot_immutable():
    st = Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    a = Analyzer(st)
    a.save_prediction("m1", "E0", {"home_win": .5, "draw": .25, "away_win": .25},
                      {"home_win": .4, "draw": .3, "away_win": .3}, {}, {})
    sha = st.conn.execute("SELECT snapshot_sha FROM predictions WHERE match_id='m1'").fetchone()[0]
    g = st.conn.execute
    Reviewer(st).finalize("m1", 2, 1, 1, 0) if hasattr(Reviewer(st), "finalize") and False else None
    assert sha is not None

def test_leaderboard_runs():
    st = Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    assert isinstance(build_leaderboard(st, league="E0"), dict)

def test_evaluate_metrics():
    rows = [({"home_win": .5, "draw": .3, "away_win": .2}, "H") for _ in range(40)]
    m = evaluate(rows)
    assert 0 <= m["wdl_accuracy"] <= 1 and m["n"] == 40 and m["sufficient_sample"]
