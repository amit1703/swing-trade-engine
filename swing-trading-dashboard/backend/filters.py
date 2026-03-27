"""
Centralized entry-gate filters shared by scanner, backtest, and WFO.

All filter functions are pure (no side effects, no network calls) so they
can be called safely inside the per-bar backtest replay loop.

Regime scoring delegates to engines/engine0.py (V2 continuous, 0.0–100.0 scale).
Identical scoring is used for both live scan and historical backtest,
eliminating train-serve skew.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

import numpy as np
import pandas as pd

from constants import (
    LIQUIDITY_MIN_AVG_VOLUME,
    LIQUIDITY_MIN_DOLLAR_VOLUME,
    EARNINGS_BLACKOUT_DAYS,
    REGIME_AGGRESSIVE_THRESHOLD,
    REGIME_SELECTIVE_THRESHOLD,
)
from engines.engine0 import compute_regime_score_series as _engine0_score_series

# Minimum bars required before regime scoring produces reliable output.
# Ensures ATR50sma warmup (14 + 50 = 64 bars); protects unit-test inputs with
# < 65 bars from returning spurious bullish signals during indicator warmup.
_REGIME_MIN_BARS = 65


def compute_regime_score_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return float regime score (0.0–100.0) per date as a pd.Series.

    Delegates to engines.engine0.compute_regime_score_series (SPY-only continuous
    7-factor scoring). Returns all-zero for inputs with fewer than _REGIME_MIN_BARS rows.
    """
    if spy_df is None or len(spy_df) < _REGIME_MIN_BARS:
        idx = spy_df.index if spy_df is not None else pd.DatetimeIndex([])
        return pd.Series(0.0, index=idx, dtype=float)
    return _engine0_score_series(spy_df)


def compute_regime_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return a boolean pd.Series (same index as spy_df) where True = bullish regime.

    Threshold: REGIME_SELECTIVE_THRESHOLD (40 on the 0.0–100.0 continuous scale).
    Returns all-False for inputs with fewer than _REGIME_MIN_BARS rows.
    """
    if spy_df is None or len(spy_df) < _REGIME_MIN_BARS:
        idx = spy_df.index if spy_df is not None else pd.DatetimeIndex([])
        return pd.Series(False, index=idx, dtype=bool)
    score = compute_regime_score_series(spy_df)
    return score >= REGIME_SELECTIVE_THRESHOLD


def compute_regime_label_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return a pd.Series of str ('AGGRESSIVE'|'SELECTIVE'|'DEFENSIVE') per date.

    Uses the same SPY-only 7-factor continuous scoring as compute_regime_series.
    Returns all-'DEFENSIVE' for inputs with fewer than _REGIME_MIN_BARS rows.
    """
    if spy_df is None or len(spy_df) < _REGIME_MIN_BARS:
        idx = spy_df.index if spy_df is not None else pd.DatetimeIndex([])
        return pd.Series("DEFENSIVE", index=idx, dtype=object)

    score = compute_regime_score_series(spy_df)
    labels = pd.Series(
        np.select(
            [score >= REGIME_AGGRESSIVE_THRESHOLD, score >= REGIME_SELECTIVE_THRESHOLD],
            ["AGGRESSIVE", "SELECTIVE"],
            default="DEFENSIVE",
        ),
        index=spy_df.index,
        dtype=object,
    )
    return labels


def passes_liquidity(
    df: pd.DataFrame,
    min_avg_volume: int = LIQUIDITY_MIN_AVG_VOLUME,
    min_dollar_volume: float = LIQUIDITY_MIN_DOLLAR_VOLUME,
) -> bool:
    """
    Return True if the most recent bar of df passes the liquidity gate:
      - 50-day median volume >= min_avg_volume  (median is robust to volume spikes
        and requires sustained liquidity, not just a few high-volume days)
      - last_close × median_volume_50d >= min_dollar_volume

    Uses the most recent min(len(df), 50) bars for the volume computation.
    Returns False on empty input (len < 2).
    """
    if df is None or len(df) < 2:
        return False

    vol = df["Volume"].iloc[-50:]
    median_vol = float(vol.median()) if len(vol) > 0 else 0.0
    if median_vol < min_avg_volume:
        return False

    last_close = float(df["Close"].iloc[-1])
    if pd.isna(last_close) or last_close <= 0:
        return False

    return bool((last_close * median_vol) >= min_dollar_volume)


def in_earnings_blackout(
    signal_date: str,
    earnings_dates: List[str],
    blackout_days: int = EARNINGS_BLACKOUT_DAYS,
) -> bool:
    """
    Return True if signal_date falls within [-1, +blackout_days] calendar days
    of any date in earnings_dates.

    Parameters
    ----------
    signal_date : str    — YYYY-MM-DD format
    earnings_dates : List[str]  — known earnings dates, YYYY-MM-DD format
    blackout_days : int  — forward days to block (default: EARNINGS_BLACKOUT_DAYS)

    Returns False (safe to trade) on empty list or any parse error.
    """
    if not earnings_dates:
        return False
    try:
        sig = datetime.strptime(signal_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False

    for ed_str in earnings_dates:
        try:
            ed = datetime.strptime(ed_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if -1 <= (ed - sig).days <= blackout_days:
            return True
    return False
