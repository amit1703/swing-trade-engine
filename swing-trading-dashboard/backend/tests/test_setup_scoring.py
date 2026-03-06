"""Tests for unified setup scoring (Task 9)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from scoring import compute_setup_score, score_and_filter_setups


def _vcp(ticker="AAPL", rr=2.5, vol_ratio=2.2, rs_blue_dot=True,
         weekly_confirmed=True, atr_compressed=True):
    return {
        "ticker": ticker, "setup_type": "VCP", "sector": "Technology",
        "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
        "rr": rr, "setup_date": "2026-03-06",
        "is_vol_surge": vol_ratio >= 1.5,
        "volume_ratio": vol_ratio,
        "rs_score": 0.05,
        "rs_blue_dot": rs_blue_dot,
        "weekly_confirmed": weekly_confirmed,
        "atr_compressed": atr_compressed,
    }


def _pullback(ticker="MSFT", rr=2.0):
    return {
        "ticker": ticker, "setup_type": "PULLBACK", "sector": "Technology",
        "entry": 200.0, "stop_loss": 190.0, "take_profit": 220.0,
        "rr": rr, "setup_date": "2026-03-06",
        "support_source": "KDE",
    }


def _watchlist(ticker="NVDA", distance_pct=0.8):
    return {
        "ticker": ticker, "setup_type": "WATCHLIST", "sector": "Technology",
        "entry": 150.0, "stop_loss": 0.0, "take_profit": 0.0,
        "rr": 0.0, "setup_date": "2026-03-06",
        "distance_pct": distance_pct,
        "rs_blue_dot": True,
    }


def _options(ticker="SPY", options_score=80):
    return {
        "ticker": ticker, "setup_type": "OPTIONS_CATALYST", "sector": "Financials",
        "entry": 500.0, "stop_loss": 475.0, "take_profit": 550.0,
        "rr": 2.0, "setup_date": "2026-03-06",
        "options_score": options_score,
    }


# ── Score range ───────────────────────────────────────────────────────────────

def test_score_always_in_0_to_100():
    """Score must never exceed 100 or go below 0 for any input."""
    top_sectors = ["Technology"]
    for rr in [0.0, 1.0, 2.0, 5.0, 99.0]:
        for rs_rank in [0, 50, 100]:
            setup = _vcp(rr=rr, vol_ratio=3.0)
            s = compute_setup_score(setup, rs_rank, 75, "AGGRESSIVE", top_sectors)
            assert 0 <= s <= 100, f"score={s} out of range (rr={rr}, rs_rank={rs_rank})"


# ── High-conviction setup passes threshold ────────────────────────────────────

def test_high_conviction_vcp_passes_70():
    """RS rank 85, vol 2x, rr 2.5, AGGRESSIVE, top sector → score >= 70."""
    setup = _vcp(rr=2.5, vol_ratio=2.2, rs_blue_dot=True, weekly_confirmed=True)
    score = compute_setup_score(setup, rs_rank=85, regime_score=80,
                                regime="AGGRESSIVE", top_sectors=["Technology"])
    assert score >= 70, f"Expected >= 70, got {score}"


def test_high_conviction_pullback_passes_70():
    """Good pullback with rs_rank 90, rr 2.5, AGGRESSIVE → score >= 70."""
    setup = _pullback(rr=2.5)
    score = compute_setup_score(setup, rs_rank=90, regime_score=80,
                                regime="AGGRESSIVE", top_sectors=["Technology"])
    assert score >= 70, f"Expected >= 70, got {score}"


# ── Low-quality setups fail ───────────────────────────────────────────────────

def test_low_rs_rank_setup_fails_70():
    """RS rank 60 (below gate) with average params → score < 70."""
    setup = _vcp(rr=2.0, vol_ratio=1.5)
    score = compute_setup_score(setup, rs_rank=60, regime_score=50,
                                regime="SELECTIVE", top_sectors=[])
    assert score < 70, f"Expected < 70, got {score}"


def test_no_vol_surge_reduces_score():
    """Same setup but with vol_ratio=1.0 should score lower than vol_ratio=2.0."""
    base = _vcp(rr=2.0)
    s_high = compute_setup_score(
        {**base, "volume_ratio": 2.0, "is_vol_surge": True},
        rs_rank=80, regime_score=70, regime="AGGRESSIVE", top_sectors=[]
    )
    s_low = compute_setup_score(
        {**base, "volume_ratio": 1.0, "is_vol_surge": False},
        rs_rank=80, regime_score=70, regime="AGGRESSIVE", top_sectors=[]
    )
    assert s_high > s_low


# ── Regime alignment component ────────────────────────────────────────────────

def test_aggressive_regime_scores_higher_than_selective():
    """AGGRESSIVE adds more points than SELECTIVE, all else equal."""
    setup = _vcp(rr=2.0, vol_ratio=2.0)
    s_agg = compute_setup_score(setup, 80, 80, "AGGRESSIVE", [])
    s_sel = compute_setup_score(setup, 80, 50, "SELECTIVE",  [])
    assert s_agg > s_sel


def test_defensive_regime_scores_lowest():
    """DEFENSIVE must score less than SELECTIVE."""
    setup = _vcp(rr=2.0, vol_ratio=2.0)
    s_sel = compute_setup_score(setup, 80, 50, "SELECTIVE",  [])
    s_def = compute_setup_score(setup, 80, 20, "DEFENSIVE",  [])
    assert s_sel > s_def


# ── Sector bonus ──────────────────────────────────────────────────────────────

def test_top_sector_adds_bonus():
    """Ticker in top_sectors should score higher than ticker not in top_sectors."""
    setup = _vcp(rr=2.0, vol_ratio=2.0)
    s_in  = compute_setup_score(setup, 80, 70, "SELECTIVE", ["Technology"])
    s_out = compute_setup_score(setup, 80, 70, "SELECTIVE", ["Energy"])
    assert s_in > s_out


# ── OPTIONS / WATCHLIST specialisation ────────────────────────────────────────

def test_watchlist_scoring_does_not_crash():
    """WATCHLIST setup (rr=0, no vol_ratio) must not raise."""
    setup = _watchlist(distance_pct=0.5)
    s = compute_setup_score(setup, rs_rank=75, regime_score=70,
                            regime="SELECTIVE", top_sectors=["Technology"])
    assert 0 <= s <= 100


def test_options_catalyst_uses_options_score():
    """HIGH options_score should give more vol-component points than low."""
    s_high = compute_setup_score(_options(options_score=90), 80, 70, "SELECTIVE", [])
    s_low  = compute_setup_score(_options(options_score=50), 80, 70, "SELECTIVE", [])
    assert s_high > s_low


# ── score_and_filter_setups ───────────────────────────────────────────────────

def test_filter_removes_below_threshold():
    """Setups with score < MIN_SETUP_SCORE must be removed."""
    setups = [
        _vcp("AAPL", rr=3.0, vol_ratio=2.5),  # should pass with rs_rank=90, AGGRESSIVE
        _vcp("JUNK", rr=0.5, vol_ratio=0.8),  # very weak — should fail
    ]
    rs_rank_map = {"AAPL": 90.0, "JUNK": 71.0}
    regime = {"regime": "AGGRESSIVE", "regime_score": 80}
    top_sectors = ["Technology"]
    result = score_and_filter_setups(setups, rs_rank_map, regime, top_sectors)
    tickers = [s["ticker"] for s in result]
    assert "AAPL" in tickers, "High-conviction setup must survive filter"
    assert "JUNK" not in tickers, "Weak setup must be filtered out"


def test_results_sorted_by_score_descending():
    """Results must be sorted by setup_score descending."""
    setups = [
        _vcp("LOW",  rr=1.5, vol_ratio=1.5),
        _vcp("HIGH", rr=3.0, vol_ratio=2.5),
        _vcp("MID",  rr=2.0, vol_ratio=2.0),
    ]
    rs_rank_map = {"HIGH": 90.0, "MID": 80.0, "LOW": 72.0}
    regime = {"regime": "AGGRESSIVE", "regime_score": 80}
    top_sectors = ["Technology"]
    result = score_and_filter_setups(setups, rs_rank_map, regime, top_sectors)
    scores = [s["setup_score"] for s in result]
    assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"


def test_setup_score_field_written_to_each_setup():
    """Every returned setup must have an integer 'setup_score' key."""
    setups = [_vcp("AAPL", rr=3.0, vol_ratio=2.5)]
    rs_rank_map = {"AAPL": 90.0}
    regime = {"regime": "AGGRESSIVE", "regime_score": 80}
    result = score_and_filter_setups(setups, rs_rank_map, regime, ["Technology"])
    for s in result:
        assert "setup_score" in s, "setup_score field missing"
        assert isinstance(s["setup_score"], int)


def test_ticker_not_in_rs_rank_map_is_excluded():
    """Setup whose ticker has no RS rank entry must be excluded."""
    setups = [_vcp("MISSING", rr=3.0, vol_ratio=2.5)]
    result = score_and_filter_setups(
        setups, {}, {"regime": "AGGRESSIVE", "regime_score": 80}, []
    )
    assert result == [], "Ticker with no RS rank must be excluded"
