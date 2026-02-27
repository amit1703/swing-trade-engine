"""
Engine 4: RS Line Analysis
==========================
Detects institutional accumulation through Relative Strength (RS) Line tracking.
RS Line = Ticker Close / SPY Close (daily ratio over 252 trading days).
Blue Dot = 52-week high in the RS Line.
"""

import os
import sys
from typing import Optional, List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from constants import TRADING_DAYS_IN_YEAR, RS_BLUE_DOT_TOLERANCE_PCT


def calculate_rs_line(
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame,
) -> Optional[List[float]]:
    """
    Calculate Relative Strength Line: ticker_close / spy_close for each day.

    Parameters
    ----------
    ticker_df : pd.DataFrame
        Ticker OHLCV data with 'Close' or 'Adj Close' column
    spy_df : pd.DataFrame
        SPY OHLCV data with 'Close' or 'Adj Close' column

    Returns
    -------
    List[float]
        RS ratios aligned with ticker_df dates, or None if calculation fails
    """
    try:
        if ticker_df is None or ticker_df.empty or spy_df is None or spy_df.empty:
            return None

        # Flatten MultiIndex if needed
        if isinstance(ticker_df.columns, pd.MultiIndex):
            ticker_df.columns = ticker_df.columns.get_level_values(0)
        if isinstance(spy_df.columns, pd.MultiIndex):
            spy_df.columns = spy_df.columns.get_level_values(0)

        # Use Adj Close if available, else Close
        ticker_close_col = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"
        spy_close_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"

        ticker_close = ticker_df[ticker_close_col]
        spy_close = spy_df[spy_close_col]

        if ticker_close.empty or spy_close.empty:
            return None

        # Align dates: use intersection of both series
        common_dates = ticker_close.index.intersection(spy_close.index)
        if len(common_dates) < TRADING_DAYS_IN_YEAR:
            return None  # Need at least 252 trading days

        ticker_aligned = ticker_close[common_dates]
        spy_aligned = spy_close[common_dates]

        # Calculate RS ratios
        rs_line = (ticker_aligned / spy_aligned).values.tolist()

        # Return only last 252 days
        return rs_line[-TRADING_DAYS_IN_YEAR:] if len(rs_line) >= TRADING_DAYS_IN_YEAR else None

    except Exception as exc:
        print(f"[calculate_rs_line] Error: {exc}")
        return None


def detect_rs_blue_dot(rs_line: List[float]) -> bool:
    """
    Detect if current RS ratio is at or near 52-week high.

    Blue Dot = RS_today >= max(RS_history over last 252 days)
    Signals institutional accumulation.

    Parameters
    ----------
    rs_line : List[float]
        RS ratios (last 252 days), e.g., [0.95, 0.96, 0.97, ...]

    Returns
    -------
    bool
        True if current ratio is at 52-week high, False otherwise
    """
    try:
        if rs_line is None or len(rs_line) < TRADING_DAYS_IN_YEAR:
            return False

        rs_today = float(rs_line[-1])
        rs_52w_high = float(np.max(rs_line))

        # Blue Dot if within 0.5% of 52-week high (tolerance for rounding)
        return rs_today >= rs_52w_high * (1 - RS_BLUE_DOT_TOLERANCE_PCT)

    except Exception as exc:
        print(f"[detect_rs_blue_dot] Error: {exc}")
        return False


def calculate_rs_score(
    ticker_df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame],
) -> float:
    """
    O'Neil Composite RS Score.

    Formula:
        rs_score = (63d × 40%) + (126d × 20%) + (189d × 20%) + (252d × 20%)

    Each component = stock_period_return − spy_period_return.
    Positive = stock outperforming SPY on a weighted basis.

    Uses the 'Close' column (or 'Adj Close' if available) from each DataFrame.
    If spy_df is None, spy_return is treated as 0 for all periods.
    If fewer than 64 bars are available, returns 0.0.
    Periods that require more bars than available are skipped; the weight is
    then redistributed among qualifying periods.

    Returns
    -------
    float
        Weighted relative return score (e.g. 0.076 means 7.6% outperformance).
    """
    _PERIODS  = [63, 126, 189, 252]
    _WEIGHTS  = [0.40, 0.20, 0.20, 0.20]

    try:
        if ticker_df is None or ticker_df.empty:
            return 0.0

        # Flatten MultiIndex columns if needed
        if isinstance(ticker_df.columns, pd.MultiIndex):
            ticker_df = ticker_df.copy()
            ticker_df.columns = ticker_df.columns.get_level_values(0)

        tk_col = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"
        ticker_close = ticker_df[tk_col].values.astype(float)

        if spy_df is not None and not spy_df.empty:
            if isinstance(spy_df.columns, pd.MultiIndex):
                spy_df = spy_df.copy()
                spy_df.columns = spy_df.columns.get_level_values(0)
            spy_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
            spy_close = spy_df[spy_col].values.astype(float)
        else:
            spy_close = None

        n = len(ticker_close)

        total_weight  = 0.0
        weighted_diff = 0.0

        for period, weight in zip(_PERIODS, _WEIGHTS):
            if n <= period:          # need at least period+1 bars
                continue

            tk_ret = ticker_close[-1] / ticker_close[-period] - 1.0

            if spy_close is not None and len(spy_close) > period:
                spy_ret = spy_close[-1] / spy_close[-period] - 1.0
            else:
                spy_ret = 0.0

            weighted_diff += weight * (tk_ret - spy_ret)
            total_weight  += weight

        if total_weight == 0.0:
            return 0.0

        return weighted_diff

    except Exception as exc:
        print(f"[calculate_rs_score] Error: {exc}")
        return 0.0


def get_rs_stats(rs_line: List[float]) -> dict:
    """
    Get current RS statistics for logging/debugging.

    Returns
    -------
    dict
        {'rs_today': float, 'rs_52w_high': float, 'rs_trend': str}
    """
    try:
        if rs_line is None or len(rs_line) < 2:
            return {"rs_today": None, "rs_52w_high": None, "rs_trend": "UNKNOWN"}

        rs_today = float(rs_line[-1])
        rs_prev = float(rs_line[-2])
        rs_52w_high = float(np.max(rs_line))

        # Simple trend: up if today > yesterday, down if lower
        if rs_today > rs_prev:
            trend = "UP"
        elif rs_today < rs_prev:
            trend = "DOWN"
        else:
            trend = "FLAT"

        return {
            "rs_today": round(rs_today, 4),
            "rs_52w_high": round(rs_52w_high, 4),
            "rs_trend": trend,
        }

    except Exception as exc:
        print(f"[get_rs_stats] Error: {exc}")
        return {"rs_today": None, "rs_52w_high": None, "rs_trend": "UNKNOWN"}
