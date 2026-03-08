"""
Centralized entry-gate filters shared by scanner, backtest, and WFO.

All filter functions are pure (no side effects, no network calls) so they
can be called safely inside the per-bar backtest replay loop.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

import pandas as pd

from constants import (
    LIQUIDITY_MIN_AVG_VOLUME,
    LIQUIDITY_MIN_DOLLAR_VOLUME,
    EARNINGS_BLACKOUT_DAYS,
    REGIME_SELECTIVE_THRESHOLD,
    REGIME_WEIGHT_EMA20,
    REGIME_WEIGHT_SMA50,
    REGIME_WEIGHT_MA_STACK,
    REGIME_WEIGHT_SLOPE,
)


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

    close  = spy_df["Close"]
    ema20  = close.ewm(span=20, adjust=False).mean()
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    slope5 = ema20 - ema20.shift(5)

    def _score(i: int) -> int:
        if pd.isna(sma200.iloc[i]):
            return 0
        s = 0
        if close.iloc[i] > ema20.iloc[i]:
            s += REGIME_WEIGHT_EMA20
        if close.iloc[i] > sma50.iloc[i]:
            s += REGIME_WEIGHT_SMA50
        if not pd.isna(sma50.iloc[i]) and sma50.iloc[i] > sma200.iloc[i]:
            s += REGIME_WEIGHT_MA_STACK
        if not pd.isna(slope5.iloc[i]):
            norm = slope5.iloc[i] / (sma50.iloc[i] * 0.01 + 1e-9)
            s += min(max(int(norm * REGIME_WEIGHT_SLOPE), 0), REGIME_WEIGHT_SLOPE)
        return s

    scores = pd.Series(
        [_score(i) for i in range(len(spy_df))],
        index=spy_df.index,
        dtype=int,
    )
    return scores >= REGIME_SELECTIVE_THRESHOLD


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

    Uses only data already in df. Safe to call inside the backtest replay loop.
    Returns False on empty or insufficient input.
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
