"""
Engine 8: High Tight Flag (HTF) Scanner
=========================================
Detects the High Tight Flag — one of the highest-conviction patterns per O'Neil.

Conditions:
  1. STRONG PRIOR MOVE  — ≥80% gain within 40 trading days (low before high)
  2. FLAG CONSOLIDATION — depth ≤ 25%, duration 5–20 bars after the runup high
  3. BREAKOUT           — today's close > flag_high (not overextended: ≤ 5% above)
  4. VOLUME             — breakout day ≥ 1.5× 20-day average

Risk math:
  Entry      = close × 1.001
  Stop Loss  = flag_low − ATR14 × ATR_STOP_MULTIPLIER
  Take Profit= Entry + TARGET_RR × risk
"""
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr
from constants import (
    TARGET_RR,
    ATR_STOP_MULTIPLIER,
    ENTRY_PRICE_MULTIPLIER,
    VOL_SURGE_MULTIPLIER,
    TR_WINDOW,
    VCP_TIGHT_RANGE_5D_PCT,
    HTF_LOOKBACK_DAYS,
    HTF_MIN_RUNUP_PCT,
    HTF_MAX_FLAG_DEPTH_PCT,
    HTF_MIN_FLAG_BARS,
    HTF_MAX_FLAG_BARS,
    HTF_MAX_EXTEND_PCT,
    HTF_MAX_RISK_PCT,
)


def scan_htf(
    ticker: str,
    df: pd.DataFrame,
    zones: Optional[List[Dict]] = None,
    debug: bool = False,
) -> Optional[Dict]:
    """Return a setup dict if a valid High Tight Flag is detected, else None.

    Note: ``zones`` is accepted for API consistency with other engines but HTF
    derives its flag boundaries directly from price action — no external zones needed.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj        = _adj_col(data)
        close_s    = data[adj]
        high_s     = data["High"]
        low_s      = data["Low"]
        volume_s   = data["Volume"]
        close_arr  = close_s.values.astype(float)
        high_arr   = high_s.values.astype(float)
        low_arr    = low_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        n          = len(close_arr)
        lc         = float(close_arr[-1])
        if lc <= 0 or np.isnan(lc):
            return None

        # ── 1. Strong Prior Move ───────────────────────────────────────────────
        lookback       = min(HTF_LOOKBACK_DAYS, n - 1)
        period_close   = close_arr[-lookback - 1:-1]   # exclude today's bar

        idx_low_rel    = int(np.argmin(period_close))
        slice_after    = period_close[idx_low_rel:]
        idx_high_rel   = idx_low_rel + int(np.argmax(slice_after))

        if idx_high_rel <= idx_low_rel:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — high does not follow low in period")
            return None

        price_low  = float(period_close[idx_low_rel])
        price_high = float(period_close[idx_high_rel])
        if price_low <= 0:
            return None

        runup = (price_high - price_low) / price_low
        if runup < HTF_MIN_RUNUP_PCT:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — runup {runup:.1%} < {HTF_MIN_RUNUP_PCT:.0%}")
            return None

        # ── 2. Flag (consolidation after runup high, before today) ────────────
        # absolute index of runup high in the full array (excluding today = -1)
        idx_high_abs = (n - 1) - lookback + idx_high_rel
        flag_bars    = (n - 1) - idx_high_abs    # bars from runup high to yesterday

        if flag_bars < HTF_MIN_FLAG_BARS:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — flag only {flag_bars} bars (min {HTF_MIN_FLAG_BARS})")
            return None
        if flag_bars > HTF_MAX_FLAG_BARS:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — flag {flag_bars} bars > max {HTF_MAX_FLAG_BARS}")
            return None

        # Flag range: from runup high through yesterday (exclude today's breakout bar)
        flag_high_arr = high_arr[idx_high_abs: n - 1]
        flag_low_arr  = low_arr[idx_high_abs: n - 1]
        if len(flag_high_arr) == 0:
            return None

        flag_high = float(flag_high_arr.max())
        flag_low  = float(flag_low_arr.min())
        if flag_high <= 0:
            return None

        flag_depth = (flag_high - flag_low) / flag_high
        if flag_depth > HTF_MAX_FLAG_DEPTH_PCT:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — flag depth {flag_depth:.1%} > {HTF_MAX_FLAG_DEPTH_PCT:.0%}")
            return None

        # ── 3. Breakout ────────────────────────────────────────────────────────
        if lc <= flag_high:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — no breakout (close {lc:.2f} ≤ flag_high {flag_high:.2f})")
            return None
        if lc > flag_high * (1 + HTF_MAX_EXTEND_PCT):
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — overextended (>{HTF_MAX_EXTEND_PCT*100:.0f}% above flag)")
            return None

        # ── 4. Volume ─────────────────────────────────────────────────────────
        vol_lookback = min(21, n - 1)
        vol_avg_20   = float(np.mean(volume_arr[-vol_lookback - 1:-1])) if vol_lookback > 0 else 0.0
        if vol_avg_20 <= 0:
            return None
        vol_ratio = float(volume_arr[-1]) / vol_avg_20
        if vol_ratio < VOL_SURGE_MULTIPLIER:
            if debug:
                print(f"Engine 8 HTF {ticker}: REJECTED — volume {vol_ratio:.1f}x < {VOL_SURGE_MULTIPLIER:.1f}x")
            return None

        # ── Risk Math ─────────────────────────────────────────────────────────
        atr14    = _atr(high_s, low_s, close_s, TR_WINDOW)
        latr_val = atr14.iloc[-1]
        latr     = float(latr_val.item() if hasattr(latr_val, "item") else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        entry      = round(lc * ENTRY_PRICE_MULTIPLIER, 2)
        stop_loss  = round(flag_low - ATR_STOP_MULTIPLIER * latr, 2)
        risk       = entry - stop_loss
        # HTF patterns have a wide flag by nature (up to 25% depth) — allow up to 35% risk
        if risk <= 0 or risk > entry * HTF_MAX_RISK_PCT:
            return None

        take_profit = round(entry + TARGET_RR * risk, 2)

        # tight_range_5d: flag's last 5 bars close range ≤ 2.5%
        last5_closes = close_arr[max(idx_high_abs, n - 6): n - 1]
        if len(last5_closes) >= 2:
            c5_range      = (last5_closes.max() - last5_closes.min()) / float(last5_closes[-1]) if last5_closes[-1] > 0 else 1.0
            tight_range_5d = c5_range <= VCP_TIGHT_RANGE_5D_PCT
        else:
            tight_range_5d = False

        return {
            "ticker":           ticker,
            "setup_type":       "HTF",
            "signal":           "BRK",
            "entry":            entry,
            "stop_loss":        stop_loss,
            "take_profit":      take_profit,
            "rr":               float(TARGET_RR),
            "runup_pct":        round(runup * 100, 2),
            "flag_bars":        int(flag_bars),
            "flag_depth_pct":   round(flag_depth * 100, 2),
            "volume_ratio":     round(vol_ratio, 2),
            "is_vol_surge":     vol_ratio >= VOL_SURGE_MULTIPLIER,
            "tight_range_5d":   tight_range_5d,
            "rs_vs_spy":        0.0,
            "rs_improving":     False,
            "rs_near_high":     False,
            "rs_acceleration":  0.0,
            "setup_date":       str(data.index[-1].date()),
            "atr":              round(latr, 4),
        }

    except Exception as exc:
        print(f"[Engine8/HTF] {ticker}: {exc}")
        return None


def _prep(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if not {"High", "Low", "Volume"}.issubset(data.columns):
        return None
    return data


def _adj_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"
