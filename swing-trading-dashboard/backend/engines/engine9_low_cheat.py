"""
Engine 9: Low Cheat Entry (LCE) Scanner
==========================================
Detects early entries just below a resistance level before the official breakout.

Conditions:
  1. RESISTANCE ZONE    — KDE cluster or pivot point above current price
  2. PROXIMITY          — close within 3% below resistance
  3. RANGE CONTRACTION  — last 5-bar avg range < prior 5-bar avg range
  4. HIGHER LOW         — recent 3-bar low > prior 5-bar low (bars -8 to -3)
  5. TREND              — close > EMA20
  6. VOLUME CONTRACTION — 5-bar avg volume ≤ 80% of 20-day avg

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
from indicators import atr as _atr, ema as _ema
from constants import (
    ATR_STOP_MULTIPLIER,
    TR_WINDOW,
    EMA_LONG,
    LCE_MAX_DISTANCE_PCT,
    LCE_VOL_CONTRACTION_RATIO,
    LCE_MAX_RISK_PCT,
)


_TIGHT_RANGE_CONTRACTION = 0.7   # recent 5-bar range < 70% of prior 5-bar range → tight


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

        # ── 3. Range contraction ──────────────────────────────────────────────
        if n < 11:
            return None
        ranges_recent = high_arr[-5:] - low_arr[-5:]
        ranges_prior  = high_arr[-10:-5] - low_arr[-10:-5]
        avg_recent    = float(np.mean(ranges_recent))
        avg_prior     = float(np.mean(ranges_prior))
        if avg_prior <= 0 or avg_recent >= avg_prior:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — no range contraction ({avg_recent:.3f} >= {avg_prior:.3f})")
            return None

        # ── 4. Higher low ─────────────────────────────────────────────────────
        recent_low = float(np.min(low_arr[-3:]))
        prior_low  = float(np.min(low_arr[-8:-3]))
        if recent_low <= prior_low:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — no higher low ({recent_low:.2f} ≤ {prior_low:.2f})")
            return None

        # ── 5. Trend: close > EMA20 ───────────────────────────────────────────
        ema20_s   = _ema(close_s, EMA_LONG)
        ema20_val = ema20_s.iloc[-1]
        ema20     = float(ema20_val.item() if hasattr(ema20_val, "item") else ema20_val)
        if np.isnan(ema20) or lc < ema20:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — below EMA20 ({lc:.2f} < {ema20:.2f})")
            return None

        # ── 6. Volume contraction ─────────────────────────────────────────────
        vol_lookback = min(21, n - 1)
        vol_avg_20   = float(np.mean(volume_arr[-vol_lookback - 1:-1])) if vol_lookback > 0 else 0.0
        if vol_avg_20 <= 0:
            return None
        vol_avg_5 = float(np.mean(volume_arr[-6:-1]))
        vol_ratio = vol_avg_5 / vol_avg_20
        if vol_ratio > LCE_VOL_CONTRACTION_RATIO:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — vol ratio {vol_ratio:.2f} > {LCE_VOL_CONTRACTION_RATIO:.2f}")
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
            "signal":                     "CHEAT",
            "entry":                      entry,
            "stop_loss":                  stop_loss,
            "take_profit":                take_profit,
            "rr":                         actual_rr,
            "resistance_level":           round(resistance_level, 2),
            "distance_to_resistance_pct": round(dist * 100, 2),
            "volume_ratio":               round(vol_ratio, 2),
            "is_vol_surge":               False,
            "zone_source":                nearest.get("source", "kde"),
            "tight_range_5d":             avg_recent / avg_prior < _TIGHT_RANGE_CONTRACTION if avg_prior > 0 else False,
            "rs_vs_spy":                  0.0,
            "rs_improving":               False,
            "rs_near_high":               False,
            "rs_acceleration":            0.0,
            "setup_date":                 str(data.index[-1].date()),
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
