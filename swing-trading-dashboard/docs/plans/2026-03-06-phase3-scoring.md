# Phase 3 — RS Ranking, Sector Strength & Unified Scoring

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** After the bulk prefetch, compute RS percentile ranks and sector RS strength across the universe; gate all setup-producing engines on RS Rank ≥ 70; apply a 6-component unified score (0–100) to every setup and discard any with score < 70.

**Architecture:** A new module `backend/scoring.py` owns all scoring and ranking logic (zero imports from `main.py`). `main.py` calls two pre-scan helpers (`compute_rs_rank_map`, `compute_top_sectors`) right after the bulk prefetch and before per-ticker processing, storing the results in scan-scoped variables. The RS rank gate fires at the top of `_process()`. After all tickers are processed, `score_and_filter_setups()` scores, filters, and sorts `collected_setups` in-place before saving to DB. All weights and thresholds live in `constants.py`.

**Tech Stack:** Python 3.10, pandas, numpy — no new dependencies.

---

## Score Component Design

| Component | Max pts | Source field(s) |
|-----------|---------|-----------------|
| RS Rank | 30 | `rs_rank_map[ticker]` (pre-computed percentile) |
| Reward-to-Risk | 20 | `setup["rr"]` |
| Volume / Momentum | 20 | `setup["volume_ratio"]`, `is_vol_surge`; OPTIONS → `options_score`; WATCHLIST → proximity + `rs_blue_dot` |
| Regime Alignment | 15 | engine0 `regime` string |
| Sector Strength | 10 | ticker sector in computed top-5 |
| Pattern Quality | 5 | `quality_score` (BASE); else `rs_blue_dot` + `weekly_confirmed` + `atr_compressed` |
| **Total** | **100** | |

**Threshold:** score ≥ 70 to surface. In an AGGRESSIVE market (regime=15) with RS rank 80 (24 pts), R:R 2.5:1 (16.7 pts), confirmed volume surge (20 pts), top sector (10 pts) → 85.7 pts. A minimal-bar setup (rank 70, R:R 2:1, SELECTIVE) scores ~52 pts and is correctly suppressed.

---

## Task A — Add new constants

**Files:**
- Modify: `backend/constants.py`

### Step 1: Add 8 new constants after the existing `VCP_ATR_CONTRACTION_THRESHOLD` block

In `backend/constants.py`, add after line 67 (after `VCP_ATR_CONTRACTION_THRESHOLD`):

```python
# ──────────────────────────────────────────────────────────────────────────
# Phase 3 — RS Ranking & Unified Scoring (Tasks 8, 9, 10)
# ──────────────────────────────────────────────────────────────────────────

RS_RANK_MIN_PERCENTILE  = 70    # gate: skip tickers with RS rank < 70
TOP_SECTORS_N           = 5     # top N sectors by avg RS score
MIN_SETUP_SCORE         = 70    # gate: discard setups with unified score < 70

# Score component weights (must sum to 100)
SCORE_WEIGHT_RS_RANK    = 30    # RS percentile rank
SCORE_WEIGHT_RR         = 20    # Reward-to-Risk ratio
SCORE_WEIGHT_VOL        = 20    # Volume surge / momentum
SCORE_WEIGHT_REGIME     = 15    # Market regime alignment
SCORE_WEIGHT_SECTOR     = 10    # Sector in top-5 by RS
SCORE_WEIGHT_QUALITY    = 5     # Pattern quality / confirmation signals
```

### Step 2: Verify constants are importable

```bash
cd backend && python -c "
from constants import (
    RS_RANK_MIN_PERCENTILE, TOP_SECTORS_N, MIN_SETUP_SCORE,
    SCORE_WEIGHT_RS_RANK, SCORE_WEIGHT_RR, SCORE_WEIGHT_VOL,
    SCORE_WEIGHT_REGIME, SCORE_WEIGHT_SECTOR, SCORE_WEIGHT_QUALITY,
)
total = SCORE_WEIGHT_RS_RANK + SCORE_WEIGHT_RR + SCORE_WEIGHT_VOL + SCORE_WEIGHT_REGIME + SCORE_WEIGHT_SECTOR + SCORE_WEIGHT_QUALITY
print('weights sum:', total)
assert total == 100, f'Weights must sum to 100, got {total}'
print('OK')
"
```
Expected: `weights sum: 100` then `OK`

### Step 3: Commit

```bash
git add backend/constants.py
git commit -m "feat(constants): add RS ranking + unified scoring constants (Phase 3)"
```

---

## Task B — Create backend/scoring.py

**Files:**
- Create: `backend/scoring.py`
- Test: `backend/tests/test_rs_ranking.py`
- Test: `backend/tests/test_setup_scoring.py`

### Step 1: Write the failing RS ranking tests first

Create `backend/tests/test_rs_ranking.py`:

```python
"""Tests for RS percentile ranking and sector strength (Task 8, 10)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest
from scoring import compute_rs_rank_map, compute_top_sectors


def _make_cache_entry(close_vals):
    """Build a minimal _ticker_cache entry (ts, df) from a close price list."""
    dates = pd.date_range("2024-01-02", periods=len(close_vals), freq="B")
    df = pd.DataFrame({
        "Adj Close": close_vals,
        "High":      [c * 1.01 for c in close_vals],
        "Low":       [c * 0.99 for c in close_vals],
        "Close":     close_vals,
        "Volume":    [1_000_000] * len(close_vals),
    }, index=dates)
    return (0.0, df)


def _make_spy(close_vals):
    """Build a minimal SPY DataFrame."""
    dates = pd.date_range("2024-01-02", periods=len(close_vals), freq="B")
    return pd.DataFrame({
        "Adj Close": close_vals,
        "High":      [c * 1.01 for c in close_vals],
        "Low":       [c * 0.99 for c in close_vals],
        "Close":     close_vals,
        "Volume":    [50_000_000] * len(close_vals),
    }, index=dates)


# ── compute_rs_rank_map ───────────────────────────────────────────────────────

def test_rs_rank_map_ranks_in_0_to_100_range():
    """All returned ranks must be in [0, 100]."""
    n = 252
    spy = _make_spy([400.0 + i * 0.1 for i in range(n)])
    cache = {
        "A": _make_cache_entry([100.0 + i * 0.2 for i in range(n)]),  # outperforms
        "B": _make_cache_entry([100.0 + i * 0.1 for i in range(n)]),  # in-line
        "C": _make_cache_entry([100.0 + i * 0.05 for i in range(n)]), # underperforms
    }
    result = compute_rs_rank_map(cache, ["A", "B", "C"], spy)
    for ticker, rank in result.items():
        assert 0 <= rank <= 100, f"{ticker} rank={rank} out of range"


def test_rs_rank_map_outperformer_has_higher_rank():
    """Ticker with stronger returns vs SPY must have higher rank."""
    n = 252
    spy = _make_spy([400.0] * n)  # flat SPY
    cache = {
        "STRONG": _make_cache_entry([100.0 + i * 0.5 for i in range(n)]),  # +125% over year
        "WEAK":   _make_cache_entry([100.0 - i * 0.1 for i in range(n)]),  # declining
    }
    result = compute_rs_rank_map(cache, ["STRONG", "WEAK"], spy)
    assert "STRONG" in result and "WEAK" in result
    assert result["STRONG"] > result["WEAK"]


def test_rs_rank_map_empty_cache_returns_empty_dict():
    """Empty cache must return empty dict, not raise."""
    n = 252
    spy = _make_spy([400.0] * n)
    result = compute_rs_rank_map({}, [], spy)
    assert result == {}


def test_rs_rank_map_none_spy_returns_empty_dict():
    """None SPY df must return empty dict."""
    result = compute_rs_rank_map({}, [], None)
    assert result == {}


def test_rs_rank_map_insufficient_data_skipped():
    """Tickers with fewer than 63 bars are skipped gracefully."""
    n = 252
    spy = _make_spy([400.0] * n)
    cache = {
        "SHORT": _make_cache_entry([100.0] * 30),  # only 30 bars
        "LONG":  _make_cache_entry([100.0 + i * 0.2 for i in range(n)]),
    }
    result = compute_rs_rank_map(cache, ["SHORT", "LONG"], spy)
    assert "SHORT" not in result
    assert "LONG" in result


# ── compute_top_sectors ───────────────────────────────────────────────────────

def test_top_sectors_returns_at_most_top_n():
    """Returns at most top_n=5 sector names."""
    n = 252
    spy = _make_spy([400.0 + i * 0.1 for i in range(n)])
    cache = {
        f"T{i}": _make_cache_entry([100.0 + i * 0.1 * j for j in range(n)])
        for i in range(10)
    }
    tickers = list(cache.keys())
    sectors = {f"T{i}": f"Sector{i % 7}" for i in range(10)}
    result = compute_top_sectors(cache, tickers, sectors, spy, top_n=5)
    assert len(result) <= 5


def test_top_sectors_best_sector_is_first():
    """The sector with highest avg RS score must be at index 0."""
    n = 252
    spy = _make_spy([400.0] * n)  # flat SPY
    cache = {
        "TECH1": _make_cache_entry([100.0 + i * 0.5 for i in range(n)]),  # best
        "TECH2": _make_cache_entry([100.0 + i * 0.4 for i in range(n)]),  # good
        "ENRG1": _make_cache_entry([100.0 + i * 0.1 for i in range(n)]),  # weak
    }
    sectors = {"TECH1": "Technology", "TECH2": "Technology", "ENRG1": "Energy"}
    result = compute_top_sectors(cache, ["TECH1", "TECH2", "ENRG1"], sectors, spy)
    assert len(result) > 0
    assert result[0] == "Technology"


def test_top_sectors_none_spy_returns_empty():
    """None SPY must return empty list, not raise."""
    result = compute_top_sectors({}, [], {}, None)
    assert result == []
```

### Step 2: Run to confirm they fail

```bash
cd backend && python -m pytest tests/test_rs_ranking.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'scoring'` (all tests fail — correct)

### Step 3: Write the failing setup scoring tests

Create `backend/tests/test_setup_scoring.py`:

```python
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
```

### Step 4: Run to confirm these tests fail

```bash
cd backend && python -m pytest tests/test_setup_scoring.py -v 2>&1 | head -20
```
Expected: all fail with `ModuleNotFoundError: No module named 'scoring'`

### Step 5: Implement scoring.py

Create `backend/scoring.py`:

```python
"""
scoring.py — RS Ranking, Sector Strength, and Unified Setup Scoring
====================================================================
Phase 3 Tasks 8, 9, 10.

Public API
----------
compute_rs_rank_map(ticker_cache, tickers, spy_df)
    → Dict[str, float]   ticker → percentile rank 0-100

compute_top_sectors(ticker_cache, tickers, sectors, spy_df, top_n)
    → List[str]          sector names ordered best→worst, up to top_n

compute_setup_score(setup, rs_rank, regime_score, regime, top_sectors)
    → int                0-100 unified score

score_and_filter_setups(setups, rs_rank_map, regime, top_sectors, min_score)
    → List[Dict]         filtered + scored + sorted by setup_score desc
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from constants import (
    MIN_SETUP_SCORE,
    SCORE_WEIGHT_QUALITY,
    SCORE_WEIGHT_REGIME,
    SCORE_WEIGHT_RS_RANK,
    SCORE_WEIGHT_RR,
    SCORE_WEIGHT_SECTOR,
    SCORE_WEIGHT_VOL,
    TOP_SECTORS_N,
)

# ─────────────────────────────────────────────────────────────────────────────
# O'Neil RS score — fast numpy implementation
# ─────────────────────────────────────────────────────────────────────────────

_RS_PERIODS  = (63, 126, 189, 252)
_RS_WEIGHTS  = (0.40, 0.20, 0.20, 0.20)


def _rs_score_fast(close: np.ndarray, spy_close: np.ndarray) -> float:
    """
    O'Neil composite RS score (same formula as indicator_engine._compute_rs_score).

    Parameters
    ----------
    close     : 1-D float array of ticker adj-close prices (newest last)
    spy_close : 1-D float array of SPY adj-close prices (newest last)

    Returns
    -------
    float — positive = outperforming SPY
    """
    n_tk  = len(close)
    n_spy = len(spy_close)
    total_w  = 0.0
    weighted = 0.0

    for period, weight in zip(_RS_PERIODS, _RS_WEIGHTS):
        if n_tk <= period:
            continue
        tk_ret  = close[-1] / close[-period] - 1.0
        spy_ret = (spy_close[-1] / spy_close[-period] - 1.0) if n_spy > period else 0.0
        weighted += weight * (tk_ret - spy_ret)
        total_w  += weight

    return round(weighted / total_w, 6) if total_w > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Internal data prep
# ─────────────────────────────────────────────────────────────────────────────

def _extract_close(df: pd.DataFrame) -> Optional[np.ndarray]:
    """
    Pull the adjusted close from a yfinance DataFrame.
    Returns a 1-D float64 np.ndarray (NaNs dropped), or None if unusable.
    """
    if df is None or df.empty:
        return None
    data = df
    if isinstance(data.columns, pd.MultiIndex):
        data = data.copy()
        data.columns = data.columns.get_level_values(0)
    if data.columns.duplicated().any():
        data = data.loc[:, ~data.columns.duplicated()]
    col = "Adj Close" if "Adj Close" in data.columns else "Close"
    if col not in data.columns:
        return None
    arr = data[col].dropna().values.astype(float)
    return arr if len(arr) >= 63 else None


def _spy_close_array(spy_df: pd.DataFrame) -> Optional[np.ndarray]:
    """Return SPY adj-close as a float array, or None."""
    return _extract_close(spy_df)


# ─────────────────────────────────────────────────────────────────────────────
# Task 8 — RS Percentile Ranking
# ─────────────────────────────────────────────────────────────────────────────

def compute_rs_rank_map(
    ticker_cache: Dict,
    tickers: List[str],
    spy_df: Optional[pd.DataFrame],
    sample_size: int = 600,
) -> Dict[str, float]:
    """
    Compute O'Neil RS score for every ticker in the prefetch cache, then
    convert to a cross-sectional percentile rank (0–100).

    Parameters
    ----------
    ticker_cache : dict
        Module-level _ticker_cache from main.py.
        Each entry: ticker → (timestamp, df | None)
    tickers : list[str]
        Ordered ticker universe (from ACTIVE_UNIVERSE).
    spy_df : pd.DataFrame | None
        1y SPY daily data; if None, returns {}.
    sample_size : int
        Max tickers to score (first N in universe order).

    Returns
    -------
    dict  ticker → percentile rank  (0.0 – 100.0)
    """
    if spy_df is None or spy_df.empty:
        return {}

    spy_arr = _spy_close_array(spy_df)
    if spy_arr is None or len(spy_arr) < 63:
        return {}

    candidates = [
        t for t in tickers
        if t in ticker_cache and ticker_cache[t][1] is not None
    ]

    raw_scores: Dict[str, float] = {}
    for ticker in candidates[:sample_size]:
        _, df = ticker_cache[ticker]
        arr = _extract_close(df)
        if arr is None:
            continue
        try:
            raw_scores[ticker] = _rs_score_fast(arr, spy_arr)
        except Exception:
            pass

    if len(raw_scores) < 2:
        # With 0 or 1 ticker, percentile is meaningless — return as-is (all 50)
        return {t: 50.0 for t in raw_scores}

    sorted_scores = sorted(raw_scores.values())
    n = len(sorted_scores)

    rank_map: Dict[str, float] = {}
    for ticker, score in raw_scores.items():
        below = sum(1 for s in sorted_scores if s < score)
        rank_map[ticker] = round(below / n * 100, 1)

    return rank_map


# ─────────────────────────────────────────────────────────────────────────────
# Task 10 — Sector RS Strength
# ─────────────────────────────────────────────────────────────────────────────

def compute_top_sectors(
    ticker_cache: Dict,
    tickers: List[str],
    sectors: Dict[str, str],
    spy_df: Optional[pd.DataFrame],
    top_n: int = TOP_SECTORS_N,
) -> List[str]:
    """
    Compute the average O'Neil RS score for each sector across the universe,
    return the names of the top_n sectors sorted best-first.

    Parameters
    ----------
    ticker_cache : dict   module-level prefetch cache
    tickers      : list   ordered ticker universe
    sectors      : dict   ticker → sector name  (SECTORS dict from main.py)
    spy_df       : pd.DataFrame | None
    top_n        : int    how many sectors to return

    Returns
    -------
    list[str]  — sector names, best RS first, length ≤ top_n
    """
    if spy_df is None or spy_df.empty:
        return []

    spy_arr = _spy_close_array(spy_df)
    if spy_arr is None or len(spy_arr) < 63:
        return []

    sector_bucket: Dict[str, List[float]] = {}

    for ticker in tickers:
        sector = sectors.get(ticker, "Unknown")
        if sector == "Unknown":
            continue
        entry = ticker_cache.get(ticker)
        if entry is None or entry[1] is None:
            continue
        _, df = entry
        arr = _extract_close(df)
        if arr is None:
            continue
        try:
            score = _rs_score_fast(arr, spy_arr)
            sector_bucket.setdefault(sector, []).append(score)
        except Exception:
            pass

    if not sector_bucket:
        return []

    sector_avg = {
        s: sum(scores) / len(scores)
        for s, scores in sector_bucket.items()
        if scores
    }
    sorted_sectors = sorted(sector_avg.items(), key=lambda kv: kv[1], reverse=True)
    return [name for name, _ in sorted_sectors[:top_n]]


# ─────────────────────────────────────────────────────────────────────────────
# Task 9 — Unified Setup Score
# ─────────────────────────────────────────────────────────────────────────────

def _vol_component(setup: Dict) -> float:
    """
    Volume / momentum component (0 – SCORE_WEIGHT_VOL pts).

    Adapts to setup type:
    • VCP / PULLBACK / BASE / RES_BREAKOUT — uses volume_ratio / is_vol_surge
    • WATCHLIST    — uses proximity (distance_pct) + rs_blue_dot bonus
    • OPTIONS_CATALYST — uses options_score as proxy
    """
    st        = setup.get("setup_type", "")
    max_pts   = float(SCORE_WEIGHT_VOL)

    if st == "OPTIONS_CATALYST":
        opt_score = float(setup.get("options_score") or 0.0)
        return min(max_pts, opt_score / 100.0 * max_pts)

    if st == "WATCHLIST":
        # distance_pct is "% below resistance", lower = closer = better
        dist = float(setup.get("distance_pct") or 1.5)  # default 1.5% if missing
        # Closer to breakout = higher score; 0% dist → full score, 1.5% → 0 pts
        proximity_pts = max(0.0, (1.5 - dist) / 1.5) * (max_pts - 5)
        rs_dot_bonus  = 5.0 if setup.get("rs_blue_dot") else 0.0
        return min(max_pts, proximity_pts + rs_dot_bonus)

    # All other setup types: chart-based volume surge
    vol_ratio    = float(setup.get("volume_ratio") or 0.0)
    is_vol_surge = bool(setup.get("is_vol_surge", False))

    if vol_ratio >= 2.0 or is_vol_surge:
        return max_pts
    if vol_ratio >= 1.5:
        return max_pts * 0.6   # 12 / 20
    if vol_ratio >= 1.2:
        return max_pts * 0.3   # 6 / 20
    return 0.0


def _quality_component(setup: Dict) -> float:
    """
    Pattern quality component (0 – SCORE_WEIGHT_QUALITY pts).

    For BASE patterns: maps quality_score (0-100) linearly.
    For others: awards bonus pts for rs_blue_dot, weekly_confirmed, atr_compressed.
    """
    max_pts = float(SCORE_WEIGHT_QUALITY)
    qs = setup.get("quality_score")
    if qs is not None:
        return min(max_pts, float(qs) / 100.0 * max_pts)

    pts = 0.0
    if setup.get("rs_blue_dot"):
        pts += max_pts * 0.4     # ~2 pts of 5
    if setup.get("weekly_confirmed"):
        pts += max_pts * 0.4
    if setup.get("atr_compressed"):
        pts += max_pts * 0.2
    return min(max_pts, pts)


def compute_setup_score(
    setup: Dict,
    rs_rank: float,
    regime_score: int,
    regime: str,
    top_sectors: List[str],
) -> int:
    """
    Compute a 0–100 integer score for a single setup.

    Parameters
    ----------
    setup        : engine output dict (must contain setup_type, rr, sector, …)
    rs_rank      : cross-sectional percentile rank of this ticker (0–100)
    regime_score : engine0 integer score (0–100)
    regime       : "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
    top_sectors  : list of top-N sector names from compute_top_sectors()

    Returns
    -------
    int  0–100
    """
    # ── 1. RS Rank (0 – SCORE_WEIGHT_RS_RANK pts) ────────────────────────────
    rs_pts = min(float(SCORE_WEIGHT_RS_RANK), rs_rank / 100.0 * SCORE_WEIGHT_RS_RANK)

    # ── 2. Reward-to-Risk (0 – SCORE_WEIGHT_RR pts) ──────────────────────────
    rr     = float(setup.get("rr") or 0.0)
    rr_pts = min(float(SCORE_WEIGHT_RR), rr / 3.0 * SCORE_WEIGHT_RR)

    # ── 3. Volume / Momentum (0 – SCORE_WEIGHT_VOL pts) ──────────────────────
    vol_pts = _vol_component(setup)

    # ── 4. Regime Alignment (0 – SCORE_WEIGHT_REGIME pts) ────────────────────
    if regime == "AGGRESSIVE":
        reg_pts = float(SCORE_WEIGHT_REGIME)
    elif regime == "SELECTIVE":
        reg_pts = float(SCORE_WEIGHT_REGIME) * 0.53   # ~8 of 15
    else:  # DEFENSIVE
        reg_pts = 0.0

    # ── 5. Sector Strength (0 or SCORE_WEIGHT_SECTOR pts) ────────────────────
    sector     = setup.get("sector", "Unknown")
    sector_pts = float(SCORE_WEIGHT_SECTOR) if sector in top_sectors else 0.0

    # ── 6. Pattern Quality (0 – SCORE_WEIGHT_QUALITY pts) ────────────────────
    qual_pts = _quality_component(setup)

    raw = rs_pts + rr_pts + vol_pts + reg_pts + sector_pts + qual_pts
    return min(100, max(0, int(round(raw))))


def score_and_filter_setups(
    setups: List[Dict],
    rs_rank_map: Dict[str, float],
    regime: Dict,
    top_sectors: List[str],
    min_score: int = MIN_SETUP_SCORE,
) -> List[Dict]:
    """
    Score every setup, add 'setup_score' field, discard setups with:
      • ticker not in rs_rank_map   (RS rank was not computable)
      • setup_score < min_score

    Then sort survivors by setup_score descending.

    Parameters
    ----------
    setups       : raw engine output list (mutated in-place with setup_score)
    rs_rank_map  : ticker → percentile rank (from compute_rs_rank_map)
    regime       : engine0 result dict (needs keys: regime, regime_score)
    top_sectors  : list of top-N sector names
    min_score    : minimum score to keep (default MIN_SETUP_SCORE)

    Returns
    -------
    list[Dict]  filtered + sorted setups
    """
    regime_str   = regime.get("regime", "SELECTIVE")
    regime_score = int(regime.get("regime_score", 50))

    surviving: List[Dict] = []
    for setup in setups:
        ticker = setup.get("ticker", "")
        rs_rank = rs_rank_map.get(ticker)
        if rs_rank is None:
            continue   # no RS rank computed for this ticker → exclude

        score = compute_setup_score(
            setup, rs_rank, regime_score, regime_str, top_sectors
        )
        setup["setup_score"] = score

        if score >= min_score:
            surviving.append(setup)

    surviving.sort(key=lambda s: s["setup_score"], reverse=True)
    return surviving
```

### Step 6: Run all scoring tests and confirm they pass

```bash
cd backend && python -m pytest tests/test_rs_ranking.py tests/test_setup_scoring.py -v
```
Expected: All tests **PASS**.

If any test fails, read the failure message carefully and fix only the code that is wrong — do not relax assertions.

### Step 7: Commit

```bash
git add backend/scoring.py backend/tests/test_rs_ranking.py backend/tests/test_setup_scoring.py
git commit -m "feat(scoring): RS percentile ranking, sector strength, unified setup scoring (Tasks 8-10)"
```

---

## Task C — Wire scoring into main.py

**Files:**
- Modify: `backend/main.py`

### Step 1: Add imports at the top of main.py

Find the existing `from engines.engine0 import check_market_regime` import block (around line 100). Add one new import line after the `from universe_builder import ...` line:

```python
from scoring import compute_rs_rank_map, compute_top_sectors, score_and_filter_setups
```

Also add `RS_RANK_MIN_PERCENTILE` and `MIN_SETUP_SCORE` to the existing `from constants import (...)` block:

```python
    RS_RANK_MIN_PERCENTILE,
    MIN_SETUP_SCORE,
```

### Step 2: Add scan-scoped variables after the breadth computation in _run_scan()

Find this block in `_run_scan()` (around line 783):
```python
        # ── Compute universe breadth from prefetch cache ──────────────────
        breadth_pct, hl_ratio = compute_universe_breadth(_ticker_cache, tickers)
```

Directly after that block (and BEFORE the Engine 0 call), add:

```python
        # ── Task 8: RS percentile rank map (pre-computed for all tickers) ──
        rs_rank_start = time.time()
        _rs_rank_map = compute_rs_rank_map(_ticker_cache, tickers, spy_df_full)
        log.info(
            "RS rank map: %d tickers ranked  [%.1fs]",
            len(_rs_rank_map), time.time() - rs_rank_start,
        )

        # ── Task 10: Top sectors by RS strength ────────────────────────────
        _top_sectors = compute_top_sectors(
            _ticker_cache, tickers, SECTORS, spy_df_full, top_n=TOP_SECTORS_N
        )
        log.info("Top sectors by RS: %s", _top_sectors)
```

Also add `TOP_SECTORS_N` to the `from constants import (...)` block.

### Step 3: Add RS rank gate in _process()

Find this section in `_process()` (around line 926):
```python
                # ── Use pre-computed RS values from indicator engine ───────────────
                rs_ratio    = ind.rs_ratio
```

Directly before that block, insert the RS rank gate:

```python
                # ── Task 8: RS Rank gate — skip tickers below percentile threshold ──
                _ticker_rs_rank = _rs_rank_map.get(ticker)
                if _ticker_rs_rank is None or _ticker_rs_rank < RS_RANK_MIN_PERCENTILE:
                    log.debug(
                        "Skipped %s: RS rank %.1f < %.0f (threshold)",
                        ticker,
                        _ticker_rs_rank if _ticker_rs_rank is not None else 0.0,
                        RS_RANK_MIN_PERCENTILE,
                    )
                    return
```

**Note:** `_rs_rank_map` and `_top_sectors` are captured as closure variables inside `_process()` just as `spy_df_full` and `collected_setups` already are — no additional passing is required.

### Step 4: Apply scoring + filtering AFTER _inject_hot_sector, BEFORE batch_save_setups

Find this block (around line 1141):
```python
        # ── Sector Clustering — inject hot_sector flag before saving ─────────
        try:
            _inject_hot_sector(collected_setups)
        except Exception as exc:
            log.warning("Sector clustering failed: %s", exc)

        # ── Batch Save All Setups (5-10x faster than individual saves) ──────
```

Between those two blocks, add:

```python
        # ── Task 9: Unified scoring — score, filter (score < 70), and sort ──
        pre_score_count = len(collected_setups)
        try:
            collected_setups = score_and_filter_setups(
                collected_setups,
                _rs_rank_map,
                regime,
                _top_sectors,
                min_score=MIN_SETUP_SCORE,
            )
            log.info(
                "Scoring: %d → %d setups (filtered %d below score %d)  "
                "top_sectors=%s",
                pre_score_count,
                len(collected_setups),
                pre_score_count - len(collected_setups),
                MIN_SETUP_SCORE,
                _top_sectors,
            )
        except Exception as exc:
            log.warning("Setup scoring failed (keeping all setups): %s", exc)
```

The `except` clause keeps the existing setups unsorted if scoring crashes — fail-open, never lose data.

### Step 5: Update dry_run_setups to preserve setup_score

The dry_run block (around line 1161) builds a dict from collected_setups. Since collected_setups is now the scored/sorted list, no changes are needed there — setup_score is already in each dict.

### Step 6: Verify syntax

```bash
cd backend && python -c "
import py_compile
py_compile.compile('main.py', doraise=True)
print('syntax OK')
from scoring import compute_rs_rank_map, compute_top_sectors, score_and_filter_setups
print('import OK')
"
```
Expected: `syntax OK` then `import OK`

### Step 7: Run all existing tests to confirm nothing is broken

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: All previously-passing tests still pass. The two new test files pass.

### Step 8: Commit

```bash
git add backend/main.py
git commit -m "feat(main): wire RS rank gate + sector strength + unified scoring into scan pipeline"
```

---

## Task D — Smoke test the full pipeline

### Step 1: Verify syntax of all modified files

```bash
cd backend && python -c "
import py_compile
for f in ['constants.py', 'scoring.py', 'main.py']:
    py_compile.compile(f, doraise=True)
    print(f, 'OK')
"
```
Expected: 3 lines ending in `OK`

### Step 2: Test scoring.py standalone with synthetic data

```bash
cd backend && python -c "
from scoring import compute_rs_rank_map, compute_top_sectors, score_and_filter_setups
import pandas as pd, numpy as np

# Synthetic data
dates = pd.date_range('2024-01-02', periods=252, freq='B')
def make_df(vals):
    return pd.DataFrame({'Adj Close': vals, 'Close': vals,
                         'High': [v*1.01 for v in vals], 'Low': [v*0.99 for v in vals],
                         'Volume': [1e6]*252}, index=dates)

spy_df = make_df([400+i*0.1 for i in range(252)])
cache = {
    'BEST': (0, make_df([100+i*0.5 for i in range(252)])),
    'MID':  (0, make_df([100+i*0.1 for i in range(252)])),
    'WEAK': (0, make_df([100-i*0.05 for i in range(252)])),
}
sectors = {'BEST': 'Technology', 'MID': 'Technology', 'WEAK': 'Energy'}

rank_map = compute_rs_rank_map(cache, ['BEST','MID','WEAK'], spy_df)
print('RS rank map:', rank_map)
assert rank_map['BEST'] > rank_map['MID'] > rank_map['WEAK'], 'Ranking order wrong'

top_s = compute_top_sectors(cache, ['BEST','MID','WEAK'], sectors, spy_df)
print('Top sectors:', top_s)
assert top_s[0] == 'Technology', 'Technology should be top sector'

setups = [
    {'ticker':'BEST','setup_type':'VCP','sector':'Technology','entry':155,'stop_loss':148,
     'take_profit':169,'rr':2.0,'setup_date':'2026-03-06','is_vol_surge':True,
     'volume_ratio':2.1,'rs_score':0.05,'rs_blue_dot':True,'weekly_confirmed':True,
     'atr_compressed':True},
    {'ticker':'WEAK','setup_type':'VCP','sector':'Energy','entry':87,'stop_loss':84,
     'take_profit':91,'rr':1.3,'setup_date':'2026-03-06','is_vol_surge':False,
     'volume_ratio':1.0,'rs_score':-0.02,'rs_blue_dot':False,'weekly_confirmed':False,
     'atr_compressed':False},
]
regime = {'regime': 'AGGRESSIVE', 'regime_score': 80}
result = score_and_filter_setups(setups, rank_map, regime, top_s)
print('Surviving setups:', [(s['ticker'], s['setup_score']) for s in result])
print('SMOKE TEST PASSED')
"
```
Expected: ranks and scores printed, `SMOKE TEST PASSED`

### Step 3: Run the full test suite one final time

```bash
cd backend && python -m pytest tests/ -v 2>&1 | tail -20
```
Expected: All tests pass, no regressions.

### Step 4: Commit

```bash
git add -A
git commit -m "chore: Phase 3 smoke test verified — RS ranking, sector strength, unified scoring"
```

---

## Quick Reference: New Fields Added to Setup Dicts

| Field | Type | Description |
|-------|------|-------------|
| `setup_score` | int 0–100 | Unified score from scoring.py |

## New Scan-State Fields (engine_stats)

None required — logging covers observability.

## New Constants

| Constant | Default | Description |
|----------|---------|-------------|
| `RS_RANK_MIN_PERCENTILE` | 70 | Percentile gate before engine processing |
| `TOP_SECTORS_N` | 5 | Top sectors tracked for bonus |
| `MIN_SETUP_SCORE` | 70 | Minimum unified score to persist setup |
| `SCORE_WEIGHT_RS_RANK` | 30 | Component weight |
| `SCORE_WEIGHT_RR` | 20 | Component weight |
| `SCORE_WEIGHT_VOL` | 20 | Component weight |
| `SCORE_WEIGHT_REGIME` | 15 | Component weight |
| `SCORE_WEIGHT_SECTOR` | 10 | Component weight |
| `SCORE_WEIGHT_QUALITY` | 5 | Component weight |
