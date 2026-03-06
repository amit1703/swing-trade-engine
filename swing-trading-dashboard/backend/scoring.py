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
    SCORE_SELECTIVE_REGIME_FACTOR,
    SCORE_WEIGHT_QUALITY,
    SCORE_WEIGHT_REGIME,
    SCORE_WEIGHT_RS_QUALITY,
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
    return arr if len(arr) > 63 else None


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
        _d = setup.get("distance_pct")
        dist = float(_d if _d is not None else 1.5)
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

    # PULLBACK setups don't require a volume surge — confirmed support touch
    # (KDE zone or ascending trendline) is the quality signal.  Award a
    # baseline score so high-conviction pullbacks are not unfairly penalised.
    if st == "PULLBACK" and setup.get("support_source"):
        return max_pts * 0.3   # 6 / 20 — confirmed support contact

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


def _rs_quality_component(setup: Dict) -> float:
    """
    RS momentum quality component (0 – SCORE_WEIGHT_RS_QUALITY pts).

    Scoring contributions (additive, capped at SCORE_WEIGHT_RS_QUALITY):
      rs_vs_spy > 0.00  → +6 pts
      rs_vs_spy > 0.05  → +8 pts additional (total +14 if both)
      rs_improving      → +4 pts
      rs_near_high      → +4 pts
      rs_acceleration > 0.10 → +6 pts
      rs_acceleration > 0.05 → +4 pts (only if not above 0.10)
      tight_range_5d    → +4 pts
    """
    max_pts = float(SCORE_WEIGHT_RS_QUALITY)
    pts = 0.0

    rs_vs_spy = float(setup.get("rs_vs_spy") or 0.0)
    if rs_vs_spy > 0.0:
        pts += 6.0
    if rs_vs_spy > 0.05:
        pts += 8.0

    if setup.get("rs_improving"):
        pts += 4.0

    if setup.get("rs_near_high"):
        pts += 4.0

    rs_accel = float(setup.get("rs_acceleration") or 0.0)
    if rs_accel > 0.10:
        pts += 6.0
    elif rs_accel > 0.05:
        pts += 4.0

    if setup.get("tight_range_5d"):
        pts += 4.0

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
        reg_pts = float(SCORE_WEIGHT_REGIME) * SCORE_SELECTIVE_REGIME_FACTOR
    else:  # DEFENSIVE
        reg_pts = 0.0

    # ── 5. Sector Strength (0 or SCORE_WEIGHT_SECTOR pts) ────────────────────
    sector     = setup.get("sector", "Unknown")
    sector_pts = float(SCORE_WEIGHT_SECTOR) if sector in top_sectors else 0.0

    # ── 6. Pattern Quality (0 – SCORE_WEIGHT_QUALITY pts) ────────────────────
    qual_pts = _quality_component(setup)

    # ── 7. RS Quality Signals (0 – SCORE_WEIGHT_RS_QUALITY pts) ──────────────
    rs_qual_pts = _rs_quality_component(setup)

    raw = rs_pts + rr_pts + vol_pts + reg_pts + sector_pts + qual_pts + rs_qual_pts
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

        # In DEFENSIVE, RS gate is bypassed so some tickers may lack a rank entry.
        # For WATCHLIST items specifically, use 0 as the fallback rank so the
        # setup still gets a score and is included (proximity is the quality filter).
        # For actionable setups, still exclude if no rank (data too short for RS).
        is_watchlist = setup.get("setup_type") == "WATCHLIST"
        if rs_rank is None:
            if is_watchlist:
                rs_rank = 0.0  # will score low but still surfaces in the watchlist
            else:
                continue  # no RS rank → exclude actionable setups

        score = compute_setup_score(
            setup, rs_rank, regime_score, regime_str, top_sectors
        )
        setup["setup_score"] = score

        # WATCHLIST items bypass the score threshold — proximity to resistance is
        # already the quality filter (engine2 gates at ≤1.5% below level).
        if is_watchlist or score >= min_score:
            surviving.append(setup)

    surviving.sort(key=lambda s: s["setup_score"], reverse=True)
    return surviving
