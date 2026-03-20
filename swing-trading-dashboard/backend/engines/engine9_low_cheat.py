"""
Engine 9: Low Cheat Entry (LCE) Scanner
==========================================
Detects mini-breakout entries just below a resistance level.

Conditions:
  1. RESISTANCE ZONE  — KDE cluster or pivot point above current price
  2. PROXIMITY        — close within 3% below resistance
  3. HIGHER LOW       — recent 3-bar low > prior 5-bar low (bars -8 to -3)
  4. TREND            — close >= SMA50
  5. MINI-BREAKOUT    — close > prior bar's high (micro-resistance break)
  6. VOLUME EXPANSION — today's volume >= LCE_BREAKOUT_VOL_RATIO x 20-day avg

Risk math:
  Entry      = current close
  Stop Loss  = 5-bar swing low − ATR14 × ATR_STOP_MULTIPLIER
  Take Profit = resistance_upper × 1.005
"""
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr, sma as _sma
from constants import (
    ATR_STOP_MULTIPLIER,
    TR_WINDOW,
    SMA_LONG,
    LCE_MAX_DISTANCE_PCT,
    LCE_MAX_RISK_PCT,
    LCE_BREAKOUT_VOL_RATIO,
)


def scan_lce(
    ticker: str,
    df: pd.DataFrame,
    zones: Optional[List[Dict]] = None,
    debug: bool = False,
) -> Optional[Dict]:
    """Return a setup dict if a valid Low Cheat Entry is detected, else None."""
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

        lc = float(close_arr[-1])
        if lc <= 0 or np.isnan(lc):
            return None

        # ── 1. Find nearest resistance zone above current price ───────────────
        all_zones = zones or []
        above_resistance = [
            z for z in all_zones
            if z.get("type") == "RESISTANCE" and float(z.get("level", 0)) > lc
        ]
        # Also include recently-crossed SUPPORT zones just overhead
        above_resistance += [
            z for z in all_zones
            if z.get("type") == "SUPPORT"
            and float(z.get("upper", 0)) > lc
            and float(z.get("upper", 0)) <= lc * (1 + LCE_MAX_DISTANCE_PCT + 0.01)
        ]
        if not above_resistance:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — no resistance zone above {lc:.2f}")
            return None

        nearest          = min(above_resistance, key=lambda z: float(z.get("level", 9999)) - lc)
        resistance_level = float(nearest.get("level", 0))
        resistance_upper = float(nearest.get("upper", resistance_level * 1.005))
        if resistance_level <= 0:
            return None

        # ── 2. Proximity: within LCE_MAX_DISTANCE_PCT below resistance ────────
        dist = (resistance_level - lc) / resistance_level
        if dist > LCE_MAX_DISTANCE_PCT or dist <= 0:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — distance {dist:.1%} not in (0, {LCE_MAX_DISTANCE_PCT:.0%}]")
            return None

        # ── 3. Higher low ─────────────────────────────────────────────────────
        if n < 11:
            return None
        recent_low = float(np.min(low_arr[-3:]))
        prior_low  = float(np.min(low_arr[-8:-3]))
        if recent_low <= prior_low:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — no higher low ({recent_low:.2f} ≤ {prior_low:.2f})")
            return None

        # ── 4. Trend: close >= SMA50 ──────────────────────────────────────────
        sma50_s   = _sma(close_s, SMA_LONG)
        sma50_val = sma50_s.iloc[-1]
        sma50     = float(sma50_val.item() if hasattr(sma50_val, "item") else sma50_val)
        if np.isnan(sma50) or lc < sma50:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — below SMA50 ({lc:.2f} < {sma50:.2f})")
            return None

        # ── 5. Mini-breakout: close > prior bar's high ────────────────────────
        if n < 2:
            return None
        prev_bar_high = float(high_arr[-2])
        if lc <= prev_bar_high:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — close {lc:.2f} not above prior bar high {prev_bar_high:.2f}")
            return None

        # ── 6. Volume expansion: >= LCE_BREAKOUT_VOL_RATIO x 20-day avg ──────
        vol_lookback = min(21, n - 1)
        vol_avg_20   = float(np.mean(volume_arr[-vol_lookback - 1:-1])) if vol_lookback > 0 else 0.0
        if vol_avg_20 <= 0:
            return None
        lvol_today = float(volume_arr[-1])
        vol_ratio  = lvol_today / vol_avg_20
        if vol_ratio < LCE_BREAKOUT_VOL_RATIO:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — vol ratio {vol_ratio:.2f} < {LCE_BREAKOUT_VOL_RATIO:.2f} (need expansion)")
            return None

        # ── Risk Math ─────────────────────────────────────────────────────────
        atr14    = _atr(high_s, low_s, close_s, TR_WINDOW)
        latr_val = atr14.iloc[-1]
        latr     = float(latr_val.item() if hasattr(latr_val, "item") else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        swing_low   = float(np.min(low_arr[-5:]))
        entry       = round(lc, 2)
        stop_loss   = round(swing_low - ATR_STOP_MULTIPLIER * latr, 2)
        risk        = entry - stop_loss
        if risk <= 0 or risk > entry * LCE_MAX_RISK_PCT:
            return None

        take_profit = round(resistance_upper * 1.005, 2)
        actual_rr   = round((take_profit - entry) / risk, 2) if risk > 0 else 0.0
        if actual_rr < 1.0:
            return None

        return {
            "ticker":                     ticker,
            "setup_type":                 "LCE",
            "signal":                     "BRK",
            "entry":                      entry,
            "stop_loss":                  stop_loss,
            "take_profit":                take_profit,
            "rr":                         actual_rr,
            "resistance_level":           round(resistance_level, 2),
            "distance_to_resistance_pct": round(dist * 100, 2),
            "volume_ratio":               round(vol_ratio, 2),
            "is_vol_surge":               vol_ratio >= 1.5,
            "zone_source":                nearest.get("source", "kde"),
            "rs_vs_spy":                  0.0,
            "rs_improving":               False,
            "rs_near_high":               False,
            "rs_acceleration":            0.0,
            "setup_date":                 str(data.index[-1].date()),
            "atr":                        round(latr, 4),
        }

    except Exception as exc:
        print(f"[Engine9/LCE] {ticker}: {exc}")
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
