"""
Engine 6: Resistance Breakout Scanner (Minervini/O'Neil)
═════════════════════════════════════════════════════════
Detects institutional-quality breakouts above KDE resistance zones.

Three mandatory rules for a valid breakout:
  1. LAUNCHPAD   — 3 trading days before breakout: highs within 3% of resistance
                   AND daily range < 1.5 × ATR14.
  2. DECISIVE CLOSE — breakout day close > zone_upper × 1.005 (0.5% above zone)
                      AND close in top 30% of daily range.
  3. INSTITUTIONAL VOLUME — breakout day volume ≥ 150% of 50-day average.

Uptrend filter: Close > 50 SMA.
Overextension gate: current close ≤ zone_upper × 1.05.

Risk Math:
  Entry      = breakout_bar_high × 1.001
  Stop Loss  = zone.lower − 0.2 × ATR14
  Take Profit= Entry + 2 × Risk   (1:2 R:R)
"""

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr


_VOL_SURGE_THRESHOLD     = 1.50   # Rule 3: ≥ 150% of 50-day average
_MAX_DAYS_LOOKBACK       = 3      # Search window for breakout bar
_MAX_EXTEND_PCT          = 0.05   # Overextension gate (current close vs zone)
_DECISIVE_CLOSE_MIN_PCT  = 0.005  # Rule 2a: close must be > 0.5% above zone
_CLOSE_POSITION_MIN      = 0.70   # Rule 2b: close ≥ low + 70% of range (top 30%)
_LAUNCHPAD_BARS          = 3      # Rule 1: number of pre-breakout bars to check
_LAUNCHPAD_MAX_HIGH_PCT  = 1.03   # Rule 1: pre-bar high ≤ zone_upper × 1.03
_LAUNCHPAD_MAX_RANGE_ATR = 1.5    # Rule 1: pre-bar range < 1.5 × ATR14


def scan_resistance_breakout(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
    debug: bool = False,
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

        # Uptrend filter: price must be above 50 SMA
        sma50  = close_s.rolling(50).mean()

        lc_val  = close_s.iloc[-1]
        lc      = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        l50_val = sma50.iloc[-1]
        l50     = float(l50_val.item() if hasattr(l50_val, 'item') else l50_val) if pd.notna(l50_val) else 0.0

        if l50 > 0 and lc < l50:
            if debug:
                print(f"Engine 6 Breakout: REJECTED - Below 50 SMA ({lc:.2f} < {l50:.2f})")
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
        low_arr    = low_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        n          = len(close_arr)

        # Include RESISTANCE zones (price still below) AND SUPPORT zones where
        # price is within the overextension window — these are zones the price
        # recently crossed above and Engine 1 reclassified from RESISTANCE to SUPPORT.
        resistance_zones = [
            z for z in zones
            if z.get("type") == "RESISTANCE"
            or (
                z.get("type") == "SUPPORT"
                and float(z.get("upper", 0)) > 0
                and lc <= float(z.get("upper", 0)) * (1 + _MAX_EXTEND_PCT)
            )
        ]
        if not resistance_zones:
            if debug:
                print("Engine 6 Breakout: REJECTED - No KDE resistance zones found")
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
                if debug:
                    pct = (lc - zone_upper) / zone_upper
                    print(f"Engine 6 Breakout: REJECTED - Price overextended (>{pct:.1%} above zone)")
                continue

            for days_back in range(_MAX_DAYS_LOOKBACK + 1):
                brk_idx = n - 1 - days_back
                pre_idx = brk_idx - 1
                if pre_idx < 0:
                    continue

                brk_close = close_arr[brk_idx]
                pre_close = close_arr[pre_idx]

                # Basic cross: price was below zone, then closed above
                if not (pre_close <= zone_upper and brk_close > zone_upper):
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - No zone cross on day -{days_back} "
                            f"(pre {pre_close:.2f} → current {brk_close:.2f}, zone upper {zone_upper:.2f})"
                        )
                    continue

                brk_high  = high_arr[brk_idx]
                brk_low   = low_arr[brk_idx]
                brk_range = brk_high - brk_low

                # Rule 2a — Decisive close: ≥ 0.5% above zone
                if brk_close <= zone_upper * (1 + _DECISIVE_CLOSE_MIN_PCT):
                    if debug:
                        print(f"Engine 6 Breakout: REJECTED - Decisive close failed "
                              f"({brk_close:.2f} <= {zone_upper * (1 + _DECISIVE_CLOSE_MIN_PCT):.2f}, "
                              f"need >{_DECISIVE_CLOSE_MIN_PCT:.1%} above zone)")
                    continue

                # Rule 2b — Close in top 30% of day's range
                if brk_range > 0 and brk_close < brk_low + _CLOSE_POSITION_MIN * brk_range:
                    if debug:
                        pos = (brk_close - brk_low) / brk_range if brk_range > 0 else 0
                        print(f"Engine 6 Breakout: REJECTED - Close in bottom {pos:.0%} of range "
                              f"(required top 30%)")
                    continue

                # Rule 1 — Launchpad: 3 pre-breakout bars tight under resistance
                launchpad_ok = True
                _lp_fail_bar = None
                _lp_fail_range = None
                for offset in range(1, _LAUNCHPAD_BARS + 1):
                    lp_idx = brk_idx - offset
                    if lp_idx < 0:
                        launchpad_ok = False
                        _lp_fail_bar = offset
                        _lp_fail_range = float("nan")
                        break
                    lp_high  = high_arr[lp_idx]
                    lp_low   = low_arr[lp_idx]
                    lp_range = lp_high - lp_low
                    if lp_high > zone_upper * _LAUNCHPAD_MAX_HIGH_PCT:
                        launchpad_ok = False
                        _lp_fail_bar = offset
                        _lp_fail_range = lp_range
                        break
                    if latr > 0 and lp_range >= _LAUNCHPAD_MAX_RANGE_ATR * latr:
                        launchpad_ok = False
                        _lp_fail_bar = offset
                        _lp_fail_range = lp_range
                        break
                if not launchpad_ok:
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - Launchpad criteria failed "
                            f"(bar {_lp_fail_bar}: range {_lp_fail_range:.2f} >= "
                            f"{_LAUNCHPAD_MAX_RANGE_ATR}× ATR {latr:.2f})"
                        )
                    continue

                # Rule 3 — Institutional volume: ≥ 150% of 50-day average
                brk_vol   = volume_arr[brk_idx]
                vol_ratio = brk_vol / vol_sma50
                if vol_ratio < _VOL_SURGE_THRESHOLD:
                    if debug:
                        print(f"Engine 6 Breakout: REJECTED - Breakout volume {vol_ratio:.1f}x "
                              f"(required: {_VOL_SURGE_THRESHOLD:.1f}x 50d SMA)")
                    continue

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

        if best is None and debug:
            print("Engine 6 Breakout: REJECTED - No valid breakout found in last 3 days")
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
