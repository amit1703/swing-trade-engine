"""
Engine 6: Resistance Breakout Scanner
══════════════════════════════════════
Detects stocks that have broken above a KDE resistance zone (from Engine 1)
within the last 3 trading days with institutional volume confirmation.

Criteria:
  1. Stage 2: Close > 200 SMA, Close > 50 SMA, Close >= 52w-low x 1.30, rising 200 SMA
  2. For each RESISTANCE zone: close crossed above zone.upper within last 3 days,
     was below zone.upper on the bar before the cross
  3. Breakout-day volume >= 150% of 50-day SMA
  4. Current close <= zone.upper x 1.05 (not already extended)

Risk Math:
  Entry      = breakout_bar_high x 1.001
  Stop Loss  = zone.lower - 0.2 x ATR14
  Take Profit= Entry + 2 x Risk   (1:2 R:R)
"""

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr


_VOL_SURGE_THRESHOLD = 1.50
_MAX_DAYS_LOOKBACK   = 3
_MAX_EXTEND_PCT      = 0.05


def scan_resistance_breakout(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
) -> Optional[Dict]:
    """Return most recent qualifying resistance breakout, or None."""
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj = _adj_col(data)
        close_s  = data[adj]
        high_s   = data["High"]
        low_s    = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # Stage 2 filter
        sma200 = close_s.rolling(200).mean()
        sma50  = close_s.rolling(50).mean()

        lc_val   = close_s.iloc[-1]
        lc       = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        l200_val = sma200.iloc[-1]
        l50_val  = sma50.iloc[-1]
        l200 = float(l200_val.item() if hasattr(l200_val, 'item') else l200_val) if pd.notna(l200_val) else 0.0
        l50  = float(l50_val.item()  if hasattr(l50_val,  'item') else l50_val)  if pd.notna(l50_val)  else 0.0

        if l200 > 0 and lc < l200:
            return None

        if l50 > 0 and lc < l50:
            return None

        yr_low = float(low_s.iloc[-252:].min()) if len(low_s) >= 252 else float(low_s.min())
        if yr_low > 0 and lc < yr_low * 1.30:
            return None

        if l200 > 0 and len(sma200) >= 21:
            l200_prev_val = sma200.iloc[-21]
            l200_prev = float(l200_prev_val.item() if hasattr(l200_prev_val, 'item') else l200_prev_val) if pd.notna(l200_prev_val) else 0.0
            if l200_prev > 0 and l200 <= l200_prev:
                return None

        # Volume SMA and ATR
        vol_sma50_s = volume_s.rolling(50).mean()
        vsm50_val   = vol_sma50_s.iloc[-1]
        vol_sma50   = float(vsm50_val.item() if hasattr(vsm50_val, 'item') else vsm50_val)
        if np.isnan(vol_sma50) or vol_sma50 <= 0:
            return None

        atr14    = _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr     = float(latr_val.item() if hasattr(latr_val, 'item') else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        close_arr  = close_s.values.astype(float)
        high_arr   = high_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        n          = len(close_arr)

        resistance_zones = [z for z in zones if z.get("type") == "RESISTANCE"]
        if not resistance_zones:
            return None

        best: Optional[Dict] = None
        best_days = _MAX_DAYS_LOOKBACK + 1

        for zone in resistance_zones:
            zone_upper = float(zone.get("upper", 0))
            zone_lower = float(zone.get("lower", 0))
            zone_level = float(zone.get("level", 0))
            if zone_upper <= 0:
                continue

            # Current price must not be overextended (> 5% above zone)
            if lc > zone_upper * (1 + _MAX_EXTEND_PCT):
                continue

            for days_back in range(_MAX_DAYS_LOOKBACK + 1):
                brk_idx = n - 1 - days_back
                pre_idx = brk_idx - 1
                if pre_idx < 0:
                    continue

                brk_close = close_arr[brk_idx]
                pre_close = close_arr[pre_idx]

                if not (pre_close <= zone_upper and brk_close > zone_upper):
                    continue

                brk_high_chk = high_arr[brk_idx]
                if brk_high_chk > zone_upper * (1 + _MAX_EXTEND_PCT):
                    continue

                brk_vol   = volume_arr[brk_idx]
                vol_ratio = brk_vol / vol_sma50
                if vol_ratio < _VOL_SURGE_THRESHOLD:
                    continue

                brk_high    = high_arr[brk_idx]
                entry       = round(brk_high * 1.001, 2)
                stop_loss   = round(zone_lower - 0.2 * latr, 2)
                risk        = entry - stop_loss
                if risk <= 0 or risk > entry * 0.15:
                    continue
                take_profit = round(entry + 2.0 * risk, 2)

                breakout_pct = round((brk_close - zone_upper) / zone_upper * 100, 2)

                candidate = {
                    "ticker":              ticker,
                    "setup_type":          "RES_BREAKOUT",
                    "signal":              "BRK",
                    "entry":               entry,
                    "stop_loss":           stop_loss,
                    "take_profit":         take_profit,
                    "rr":                  2.0,
                    "resistance_level":    round(zone_level, 2),
                    "zone_upper":          round(zone_upper, 2),
                    "breakout_pct":        breakout_pct,
                    "volume_ratio":        round(vol_ratio, 2),
                    "days_since_breakout": days_back,
                    "setup_date":          str(data.index[-1].date()),
                }

                if days_back < best_days:
                    best      = candidate
                    best_days = days_back
                break

        return best

    except Exception as exc:
        print(f"[Engine6/ResBreakout] {ticker}: {exc}")
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
