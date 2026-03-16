"""
Centralized entry-gate filters shared by scanner, backtest, and WFO.

All filter functions are pure (no side effects, no network calls) so they
can be called safely inside the per-bar backtest replay loop.
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
    REGIME_WEIGHT_EMA20,
    REGIME_WEIGHT_SMA50,
    REGIME_WEIGHT_MA_STACK,
    REGIME_WEIGHT_SLOPE,
)


def _compute_spy_regime_score(spy_df: pd.DataFrame) -> pd.Series:
    """
    Compute the integer regime score series for spy_df.

    Uses SPY-only factors from engine0 (f1–f4):
      f1: SPY Close > EMA20       → REGIME_WEIGHT_EMA20  pts
      f2: SPY Close > SMA50       → REGIME_WEIGHT_SMA50  pts
      f3: SMA50 > SMA200          → REGIME_WEIGHT_MA_STACK pts
      f4: EMA20 slope (5-bar)     → 0..REGIME_WEIGHT_SLOPE pts

    Bars where SMA200 is NaN (insufficient history) are zeroed out.
    Caller is responsible for ensuring len(spy_df) >= 200.
    """
    close  = spy_df["Close"]
    ema20  = close.ewm(span=20, adjust=False).mean()
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    slope5 = ema20 - ema20.shift(5)

    # Vectorized scoring — all operations stay in NumPy speed
    score = pd.Series(0, index=spy_df.index, dtype=int)
    score += (close > ema20).astype(int) * REGIME_WEIGHT_EMA20
    score += (close > sma50).astype(int) * REGIME_WEIGHT_SMA50
    score += (sma50 > sma200).astype(int) * REGIME_WEIGHT_MA_STACK

    # f4: EMA20 slope scaled to 0..REGIME_WEIGHT_SLOPE, then clipped
    slope_norm = (slope5 / (sma50 * 0.01 + 1e-9)).fillna(0.0)
    slope_pts  = (slope_norm * REGIME_WEIGHT_SLOPE).clip(0, REGIME_WEIGHT_SLOPE).astype(int)
    score += slope_pts

    # Zero out any bars where SMA200 is NaN (insufficient history)
    score = score.where(sma200.notna(), other=0)

    return score


def compute_regime_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return a boolean pd.Series (same index as spy_df) where True = bullish regime.

    Uses SPY-only factors from engine0 (f1–f4):
      f1: SPY Close > EMA20       → REGIME_WEIGHT_EMA20  pts
      f2: SPY Close > SMA50       → REGIME_WEIGHT_SMA50  pts
      f3: SMA50 > SMA200          → REGIME_WEIGHT_MA_STACK pts
      f4: EMA20 slope (5-bar)     → 0..REGIME_WEIGHT_SLOPE pts

    Threshold: REGIME_SELECTIVE_THRESHOLD (40 pts).
    Returns all-False for inputs with < 200 bars (insufficient SMA200 history).

    Factors f5–f7 (breadth, H/L ratio, VIX) require universe-wide live data
    and are intentionally omitted for use in historical backtesting.
    """
    if spy_df is None or len(spy_df) < 200:
        if spy_df is not None:
            return pd.Series(False, index=spy_df.index, dtype=bool)
        return pd.Series(dtype=bool)

    score = _compute_spy_regime_score(spy_df)
    return score >= REGIME_SELECTIVE_THRESHOLD


# Proportionally scaled thresholds for 4/7 factor backtest regime
# Max achievable: F1(20)+F2(15)+F3(15)+F4(10) = 60 pts
# Derived from live thresholds in constants.py so both stay in sync.
_BACKTEST_REGIME_MAX        = 60
_BACKTEST_REGIME_AGGRESSIVE = round(REGIME_AGGRESSIVE_THRESHOLD / 100 * _BACKTEST_REGIME_MAX)
_BACKTEST_REGIME_SELECTIVE  = round(REGIME_SELECTIVE_THRESHOLD  / 100 * _BACKTEST_REGIME_MAX)


def compute_regime_label_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return a pd.Series of str ('AGGRESSIVE'|'SELECTIVE'|'DEFENSIVE') per date.

    Uses the same SPY-only F1-F4 scoring as compute_regime_series but returns
    regime labels using proportionally scaled thresholds for the 60-pt max:
      AGGRESSIVE : score >= 42  (equiv 70/100 of full 7-factor system)
      SELECTIVE  : score >= 24  (equiv 40/100)
      DEFENSIVE  : score <  24

    Returns all-DEFENSIVE for inputs with < 200 bars.
    """
    if spy_df is None or len(spy_df) < 200:
        if spy_df is not None:
            return pd.Series("DEFENSIVE", index=spy_df.index, dtype=object)
        return pd.Series(dtype=object)

    score = _compute_spy_regime_score(spy_df)

    labels = pd.Series(
        np.select(
            [score >= _BACKTEST_REGIME_AGGRESSIVE, score >= _BACKTEST_REGIME_SELECTIVE],
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
