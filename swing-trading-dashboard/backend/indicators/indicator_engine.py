"""
indicator_engine.py — Centralized Indicator Computation Layer (Task 6)
=======================================================================
Computes all technical indicators ONCE per ticker and returns a typed
TickerIndicators dataclass.  Engines receive this pre-built object
instead of recomputing identical series independently.

Pipeline:
    Download → compute_indicators() → Liquidity Filter → Earnings Filter
             → Trading Engines (receive TickerIndicators + raw df)

Indicators computed:
    • EMA8, EMA20, EMA50, EMA200    (trend / structure)
    • ATR14                          (volatility / risk sizing)
    • Volume SMA50, Dollar Volume    (liquidity gate)
    • O'Neil RS Score                (relative strength vs SPY)
    • RS Blue Dot                    (52-week RS high signal)
    • RS Ratio                       (today's RS ratio)
    • RS 52w High                    (52-week RS high value)

Usage:
    from indicators.indicator_engine import compute_indicators, TickerIndicators

    indicators = compute_indicators(df, spy_df)
    if indicators is None:
        return  # insufficient data

    if indicators.avg_volume_50d < LIQUIDITY_MIN_AVG_VOLUME:
        return  # illiquid — skip
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# Allow running from backend/ directly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import ema as _ema, sma as _sma, atr as _atr
from constants import (
    RS_BLUE_DOT_TOLERANCE_PCT,
    TRADING_DAYS_IN_YEAR,
    MIN_CANDLES_FOR_RS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Output dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TickerIndicators:
    """
    All pre-computed scalars and series for one ticker.

    Scalar fields are Python floats (never numpy types) for safe JSON
    serialisation and comparisons.  Series fields are the full pandas
    Series aligned to the original df index, available to engines that
    need them (e.g. Engine 3 CCI, Engine 1 ATR).
    """

    # ── Price scalars ──────────────────────────────────────────────────────
    close:  float      # latest adjusted close
    high:   float      # latest high
    low:    float      # latest low
    volume: float      # latest volume

    # ── Trend EMAs / SMA ──────────────────────────────────────────────────
    ema8:   float
    ema20:  float
    ema50:  float
    ema200: float      # NaN → 0.0 if SMA200 not yet computable

    # ── Volatility ────────────────────────────────────────────────────────
    atr14:  float      # latest ATR(14) value

    # ── Liquidity ─────────────────────────────────────────────────────────
    avg_volume_50d: float   # 50-day average daily volume
    dollar_volume:  float   # close × avg_volume_50d  (daily $ traded)

    # ── RS (Relative Strength vs SPY) ─────────────────────────────────────
    rs_score:    float   # O'Neil composite (weighted return diff vs SPY)
    rs_ratio:    float   # today's RS ratio (ticker_close / spy_close)
    rs_52w_high: float   # 52-week high of the RS ratio
    rs_blue_dot: bool    # RS ratio within 0.5 % of 52-week high

    # ── Data quality ──────────────────────────────────────────────────────
    candles: int         # number of valid bars

    # ── Full series (for engines that need them) ──────────────────────────
    close_series:  pd.Series = field(repr=False)
    high_series:   pd.Series = field(repr=False)
    low_series:    pd.Series = field(repr=False)
    volume_series: pd.Series = field(repr=False)
    ema8_series:   pd.Series = field(repr=False)
    ema20_series:  pd.Series = field(repr=False)
    ema50_series:  pd.Series = field(repr=False)
    ema200_series: pd.Series = field(repr=False)
    atr14_series:  pd.Series = field(repr=False)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def compute_indicators(
    df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame] = None,
) -> Optional["TickerIndicators"]:
    """
    Compute all indicators for one ticker in a single pass.

    Parameters
    ----------
    df : pd.DataFrame
        1y daily OHLCV from yfinance.  Must contain High, Low, and either
        'Adj Close' or 'Close'.
    spy_df : pd.DataFrame, optional
        SPY daily OHLCV used for RS calculations.  When None, all RS
        fields are returned as 0 / False.

    Returns
    -------
    TickerIndicators
        Fully populated dataclass, or None when data is insufficient
        (< 60 bars, or critical columns missing).
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj      = _adj_col(data)
        close_s  = data[adj]
        high_s   = data["High"]
        low_s    = data["Low"]
        volume_s = data.get("Volume", pd.Series(np.zeros(len(data)), index=data.index))
        if isinstance(volume_s, pd.DataFrame):
            volume_s = volume_s.iloc[:, 0]

        if close_s.dropna().shape[0] < 55:
            return None

        # ── Moving Averages ───────────────────────────────────────────────
        ema8_s   = _ema(close_s, 8)
        ema20_s  = _ema(close_s, 20)
        ema50_s  = _sma(close_s, 50)
        ema200_s = _sma(close_s, 200)
        atr14_s  = _atr(high_s, low_s, close_s, 14)

        # ── Last-bar scalars ──────────────────────────────────────────────
        lc    = _fval(close_s.iloc[-1])
        lh    = _fval(high_s.iloc[-1])
        ll    = _fval(low_s.iloc[-1])
        lvol  = _fval(volume_s.iloc[-1])
        l8    = _fval(ema8_s.iloc[-1])
        l20   = _fval(ema20_s.iloc[-1])
        l50   = _fval(ema50_s.iloc[-1])
        l200  = _fval(ema200_s.iloc[-1])   # 0.0 if SMA200 not yet available
        latr  = _fval(atr14_s.iloc[-1])

        if any(v != v for v in [lc, lh, ll, l8, l20, latr]):  # NaN check
            return None
        if lc <= 0 or latr <= 0:
            return None

        # ── Volume / Liquidity ────────────────────────────────────────────
        vol50_series = volume_s.rolling(50, min_periods=10).mean()
        avg_vol_50d  = _fval(vol50_series.iloc[-1])
        dollar_vol   = lc * avg_vol_50d

        # ── RS Calculations ───────────────────────────────────────────────
        rs_score    = 0.0
        rs_ratio    = 0.0
        rs_52w_high = 0.0
        rs_blue_dot = False

        if spy_df is not None and not spy_df.empty:
            try:
                rs_score    = _compute_rs_score(close_s, spy_df)
                rs_ratio, rs_52w_high, rs_blue_dot = _compute_rs_ratio(close_s, spy_df)
            except Exception:
                pass  # RS fails gracefully — engines get 0 / False

        return TickerIndicators(
            # price
            close=lc, high=lh, low=ll, volume=lvol,
            # trend
            ema8=l8, ema20=l20, ema50=l50, ema200=l200,
            # volatility
            atr14=latr,
            # liquidity
            avg_volume_50d=avg_vol_50d,
            dollar_volume=dollar_vol,
            # rs
            rs_score=rs_score,
            rs_ratio=rs_ratio,
            rs_52w_high=rs_52w_high,
            rs_blue_dot=rs_blue_dot,
            # quality
            candles=len(data),
            # series
            close_series=close_s,
            high_series=high_s,
            low_series=low_s,
            volume_series=volume_s,
            ema8_series=ema8_s,
            ema20_series=ema20_s,
            ema50_series=ema50_s,
            ema200_series=ema200_s,
            atr14_series=atr14_s,
        )

    except Exception as exc:
        # Never crash the scan — just return None for this ticker
        print(f"[indicator_engine] compute_indicators failed: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_rs_score(
    ticker_close: pd.Series,
    spy_df: pd.DataFrame,
) -> float:
    """
    O'Neil Composite RS Score.

    Formula:  (63d×40%) + (126d×20%) + (189d×20%) + (252d×20%)
    Each component = stock_period_return − spy_period_return.
    Positive = outperforming SPY.
    """
    _PERIODS = [63, 126, 189, 252]
    _WEIGHTS = [0.40, 0.20, 0.20, 0.20]

    spy_adj = _adj_col(spy_df)
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy_df = spy_df.copy()
        spy_df.columns = spy_df.columns.get_level_values(0)

    spy_close = spy_df[spy_adj].values.astype(float)
    tk_close  = ticker_close.values.astype(float)
    n_tk      = len(tk_close)

    total_w   = 0.0
    weighted  = 0.0
    for period, weight in zip(_PERIODS, _WEIGHTS):
        if n_tk <= period:
            continue
        tk_ret  = tk_close[-1] / tk_close[-period] - 1.0
        spy_ret = (spy_close[-1] / spy_close[-period] - 1.0) if len(spy_close) > period else 0.0
        weighted  += weight * (tk_ret - spy_ret)
        total_w   += weight

    return round(weighted / total_w, 4) if total_w > 0 else 0.0


def _compute_rs_ratio(
    ticker_close: pd.Series,
    spy_df: pd.DataFrame,
) -> tuple:
    """
    Returns (rs_ratio, rs_52w_high, rs_blue_dot).

    rs_ratio    = latest ticker_close / spy_close
    rs_52w_high = max RS ratio over last 252 bars
    rs_blue_dot = rs_ratio >= rs_52w_high × (1 − tolerance)
    """
    spy_adj = _adj_col(spy_df)
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy_df = spy_df.copy()
        spy_df.columns = spy_df.columns.get_level_values(0)

    spy_close = spy_df[spy_adj]
    common    = ticker_close.index.intersection(spy_close.index)

    if len(common) < MIN_CANDLES_FOR_RS:
        return 0.0, 0.0, False

    tk_aligned  = ticker_close[common]
    spy_aligned = spy_close[common]
    rs_vals     = (tk_aligned / spy_aligned).iloc[-TRADING_DAYS_IN_YEAR:]

    if rs_vals.empty:
        return 0.0, 0.0, False

    rs_today    = float(rs_vals.iloc[-1])
    rs_52w_high = float(rs_vals.max())
    rs_blue_dot = rs_today >= rs_52w_high * (1.0 - RS_BLUE_DOT_TOLERANCE_PCT)

    return round(rs_today, 4), round(rs_52w_high, 4), rs_blue_dot


def _prep(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Flatten MultiIndex, deduplicate columns, require High + Low."""
    if df is None or df.empty:
        return None
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if data.columns.duplicated().any():
        data = data.loc[:, ~data.columns.duplicated()]
    if not {"High", "Low"}.issubset(data.columns):
        return None
    return data


def _adj_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"


def _fval(v) -> float:
    """Safe float extraction from pandas/numpy scalar. Returns 0.0 on NaN."""
    if hasattr(v, "item"):
        v = v.item()
    f = float(v)
    return 0.0 if f != f else f   # NaN check: NaN != NaN
