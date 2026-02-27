"""
Engine 5: Base Pattern Scanner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detects two classic O'Neil/Minervini base patterns on the daily timeframe.

PATTERN A — Cup & Handle (C&H):
  1. Cup     : U-shaped consolidation, 12–35% depth, 30–120 bars
  2. Right rim: recovers to within 15% of left peak
  3. Handle  : 5–25 day pullback 5–15%, volume contracting
  4. Signal  : DRY (within 1.0% of handle high) or BRK (above, vol ≥ 120%)

PATTERN B — Flat Base (FLAT):
  1. Duration: ≥ 25 trading days
  2. Depth   : ≤ 12% from high to low of range
  3. Location: Close in upper 75% of range
  4. Volume  : 10-day avg ≤ 90% of 50-day avg
  5. Signal  : DRY (within 1.0% of base high) or BRK (above, vol ≥ 120%)

Quality Score (0–100):
  25 pts: RS vs SPY (3-month outperformance)
  25 pts: Base tightness (depth)
  25 pts: Volume dry-up (vs 50-day avg)
  25 pts: RS near 52-week high (blue dot signal)

Risk Math:
  Entry      = pivot_high × 1.001
  Stop Loss  = handle_low (C&H) or base_low (FLAT) − 0.2 × ATR14
  Take Profit= Entry + 2 × Risk   (1:2 R:R)
"""

import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr


def scan_base_pattern(
    ticker: str,
    df: pd.DataFrame,
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
) -> Optional[Dict]:
    """Main entry point. Returns the highest-quality base setup found, or None."""
    ch = scan_cup_handle(ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score)
    fb = scan_flat_base(ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score)
    candidates = [s for s in [ch, fb] if s is not None and s.get("quality_score", 0) >= 25]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.get("quality_score", 0))


def scan_cup_handle(
    ticker: str,
    df: pd.DataFrame,
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
) -> Optional[Dict]:
    """Scan for a Cup & Handle pattern. Returns setup dict or None."""
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj = _adj_col(data)
        close_s = data[adj]
        high_s = data["High"]
        low_s = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # ── Trend filter: price must be above 200 SMA and 50 SMA ────────
        sma200 = close_s.rolling(200).mean()
        sma50 = close_s.rolling(50).mean()
        lc_val = close_s.iloc[-1]
        lc_raw = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        l200_val = sma200.iloc[-1]
        l50_val = sma50.iloc[-1]
        l200 = float(l200_val.item() if hasattr(l200_val, 'item') else l200_val) if pd.notna(l200_val) else 0.0
        l50 = float(l50_val.item() if hasattr(l50_val, 'item') else l50_val) if pd.notna(l50_val) else 0.0
        if l200 > 0 and lc_raw < l200:
            return None
        if l50 > 0 and lc_raw < l50:
            return None

        close = close_s.values.astype(float)
        volume = volume_s.values.astype(float)

        atr14 = _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr = float(latr_val.item() if hasattr(latr_val, 'item') else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        vol_sma_series = volume_s.rolling(50).mean()
        vol_sma_val = vol_sma_series.iloc[-1]
        vol_sma50 = float(vol_sma_val.item() if hasattr(vol_sma_val, 'item') else vol_sma_val)
        if np.isnan(vol_sma50) or vol_sma50 <= 0:
            return None

        # Use last 120 bars for cup detection
        lookback = min(120, len(close))
        close_lb = close[-lookback:]
        volume_lb = volume[-lookback:]

        cup = _find_cup(close_lb, lookback=lookback)
        if cup is None:
            return None

        if not _is_u_shaped(close_lb, cup):
            return None

        high_lb = high_s.values.astype(float)[-lookback:]
        handle = _find_handle(close_lb, high_lb, volume_lb, cup, vol_sma50)
        if handle is None:
            return None

        # Determine signal
        lc_val = close_s.iloc[-1]
        lc = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        lh_val = high_s.iloc[-1]
        lh = float(lh_val.item() if hasattr(lh_val, 'item') else lh_val)

        handle_high = handle["handle_high"]
        dist_to_pivot = (handle_high - lc) / handle_high if handle_high > 0 else 1.0
        last_vol_val = volume_s.iloc[-1]
        last_vol = float(last_vol_val.item() if hasattr(last_vol_val, 'item') else last_vol_val)
        vol_ratio = last_vol / vol_sma50 if vol_sma50 > 0 else 0.0

        if lc > handle_high and vol_ratio >= 1.2:
            signal = "BRK"
        elif dist_to_pivot <= 0.010:
            signal = "DRY"
        else:
            return None

        # Risk math
        entry = round(handle_high * 1.001, 2)
        stop_loss = round(handle["handle_low"] - 0.2 * latr, 2)
        risk = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None
        take_profit = round(entry + 2.0 * risk, 2)

        # Volume contraction: 5-day avg must be <= 85% of 50-day avg
        vol_dry_pct = float(np.mean(volume[-5:])) / vol_sma50 if vol_sma50 > 0 else 1.0
        if vol_dry_pct > 0.85:
            return None

        # RS vs SPY
        rs_vs_spy = (rs_ratio - 1.0) - spy_3m_return

        qs = _quality_score(
            depth_pct=cup["depth"],
            max_depth_pct=0.35,
            vol_dry_pct=vol_dry_pct,
            rs_vs_spy=rs_vs_spy,
            rs_blue_dot=rs_blue_dot,
        )

        offset = len(close) - lookback
        base_length = (len(close) - 1) - (offset + cup["left_peak_idx"])

        # Geometry for chart overlay (convert bar indices to dates)
        left_peak_abs = offset + cup["left_peak_idx"]
        cup_bottom_abs = offset + cup["cup_bottom_idx"]
        right_rim_abs = offset + cup["right_rim_idx"]

        return {
            "ticker": ticker,
            "setup_type": "BASE",
            "base_type": "CUP_HANDLE",
            "signal": signal,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": 2.0,
            "quality_score": qs,
            "base_depth_pct": round(cup["depth"] * 100, 1),
            "base_length_days": max(0, base_length),
            "volume_dry_pct": round(vol_dry_pct * 100, 1),
            "rs_vs_spy": round(rs_vs_spy * 100, 2),
            "rs_score":  round(rs_score, 4),
            "setup_date": str(data.index[-1].date()),
            # Geometry for chart overlay
            "geometry": {
                "left_peak_date": str(data.index[left_peak_abs].date()) if left_peak_abs < len(data) else None,
                "left_peak_price": round(cup["left_peak"], 2),
                "cup_bottom_date": str(data.index[cup_bottom_abs].date()) if cup_bottom_abs < len(data) else None,
                "cup_bottom_price": round(cup["cup_bottom"], 2),
                "right_rim_date": str(data.index[right_rim_abs].date()) if right_rim_abs < len(data) else None,
                "right_rim_price": round(cup["right_rim"], 2),
                "handle_high": round(handle["handle_high"], 2),
                "handle_low": round(handle["handle_low"], 2),
            },
        }

    except Exception as exc:
        print(f"[Engine5/CupHandle] {ticker}: {exc}")
        return None


def scan_flat_base(
    ticker: str,
    df: pd.DataFrame,
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
) -> Optional[Dict]:
    """Scan for a Flat Base pattern. Returns setup dict or None."""
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj = _adj_col(data)
        close_s = data[adj]
        high_s = data["High"]
        low_s = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # ── Trend filter: price must be above 200 SMA and 50 SMA ────────
        sma200 = close_s.rolling(200).mean()
        sma50 = close_s.rolling(50).mean()
        lc_val = close_s.iloc[-1]
        lc = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        l200_val = sma200.iloc[-1]
        l50_val = sma50.iloc[-1]
        l200 = float(l200_val.item() if hasattr(l200_val, 'item') else l200_val) if pd.notna(l200_val) else 0.0
        l50 = float(l50_val.item() if hasattr(l50_val, 'item') else l50_val) if pd.notna(l50_val) else 0.0
        if l200 > 0 and lc < l200:
            return None
        if l50 > 0 and lc < l50:
            return None

        # ── Dynamic lookback: find where the flat base starts ────────────
        # Scan backward from 60 days to find the longest window where
        # high-to-low depth stays <= 12%. Minimum 25 days.
        max_lookback = min(60, len(close_s))
        lookback = 0
        for lb in range(max_lookback, 24, -1):
            window_high = float(high_s.iloc[-lb:].max())
            window_low = float(low_s.iloc[-lb:].min())
            if window_high > 0:
                window_depth = (window_high - window_low) / window_high
                if window_depth <= 0.12:
                    lookback = lb
                    break
        if lookback < 25:
            return None

        # ── Depth: use actual High/Low for true range depth ──────────────
        base_high_price = float(high_s.iloc[-lookback:].max())
        base_low_price = float(low_s.iloc[-lookback:].min())
        if base_high_price <= 0:
            return None

        depth = (base_high_price - base_low_price) / base_high_price
        if depth > 0.12:
            return None

        # For breakout pivot, use the intraday High (consistent with geometry)
        base_high = base_high_price  # already = float(high_s.iloc[-lookback:].max())

        # Current close in upper 25% of range (near top of base)
        range_span = base_high_price - base_low_price
        if range_span > 0:
            pct_in_range = (lc - base_low_price) / range_span
            if pct_in_range < 0.75:
                return None

        # Volume contraction: 10-day avg <= 75% of 50-day avg
        vol_sma50_s = volume_s.rolling(50).mean()
        vol_sma10_s = volume_s.rolling(10).mean()
        vsm50_val = vol_sma50_s.iloc[-1]
        vsm10_val = vol_sma10_s.iloc[-1]
        vsm50 = float(vsm50_val.item() if hasattr(vsm50_val, 'item') else vsm50_val)
        vsm10 = float(vsm10_val.item() if hasattr(vsm10_val, 'item') else vsm10_val)

        if np.isnan(vsm50) or vsm50 <= 0 or np.isnan(vsm10):
            return None

        vol_ratio_10_50 = vsm10 / vsm50
        if vol_ratio_10_50 > 0.90:
            return None

        # ATR
        atr14 = _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr = float(latr_val.item() if hasattr(latr_val, 'item') else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        # Signal
        lh_val = high_s.iloc[-1]
        lh = float(lh_val.item() if hasattr(lh_val, 'item') else lh_val)
        last_vol_val = volume_s.iloc[-1]
        last_vol = float(last_vol_val.item() if hasattr(last_vol_val, 'item') else last_vol_val)
        vol_ratio = last_vol / vsm50 if vsm50 > 0 else 0.0
        dist_to_pivot = (base_high - lc) / base_high if base_high > 0 else 1.0

        if lc > base_high and vol_ratio >= 1.2:
            signal = "BRK"
        elif dist_to_pivot <= 0.010:
            signal = "DRY"
        else:
            return None

        # Risk math
        entry = round(base_high * 1.001, 2)
        stop_loss = round(base_low_price - 0.2 * latr, 2)
        risk = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None
        take_profit = round(entry + 2.0 * risk, 2)

        rs_vs_spy = (rs_ratio - 1.0) - spy_3m_return

        qs = _quality_score(
            depth_pct=depth,
            max_depth_pct=0.12,
            vol_dry_pct=vol_ratio_10_50,
            rs_vs_spy=rs_vs_spy,
            rs_blue_dot=rs_blue_dot,
        )

        # Geometry for chart overlay
        base_start_idx = len(data) - lookback

        return {
            "ticker": ticker,
            "setup_type": "BASE",
            "base_type": "FLAT_BASE",
            "signal": signal,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": 2.0,
            "quality_score": qs,
            "base_depth_pct": round(depth * 100, 1),
            "base_length_days": lookback,
            "volume_dry_pct": round(vol_ratio_10_50 * 100, 1),
            "rs_vs_spy": round(rs_vs_spy * 100, 2),
            "rs_score":  round(rs_score, 4),
            "setup_date": str(data.index[-1].date()),
            # Geometry for chart overlay (uses actual high/low for bounding box)
            "geometry": {
                "start_date": str(data.index[base_start_idx].date()),
                "end_date": str(data.index[-1].date()),
                "base_high": round(base_high_price, 2),
                "base_low": round(base_low_price, 2),
            },
        }

    except Exception as exc:
        print(f"[Engine5/FlatBase] {ticker}: {exc}")
        return None


def _find_cup(close: np.ndarray, lookback: int = 120) -> Optional[Dict]:
    """Locate cup: left peak → cup bottom → right rim."""
    n = len(close)
    data = close[-lookback:] if n >= lookback else close
    if len(data) < 30:
        return None

    # Left peak: highest close in first 2/3 of window
    two_thirds = len(data) * 2 // 3
    left_search = data[:two_thirds]
    if len(left_search) < 10:
        return None

    left_peak_idx = int(np.argmax(left_search))
    left_peak = float(left_search[left_peak_idx])

    # Cup bottom: lowest close after left peak
    after_peak = data[left_peak_idx:]
    if len(after_peak) < 5:
        return None

    cup_bottom_rel = int(np.argmin(after_peak))
    cup_bottom_idx = left_peak_idx + cup_bottom_rel
    cup_bottom = float(data[cup_bottom_idx])

    # Cup depth validation: 12–35%
    depth = (left_peak - cup_bottom) / left_peak
    if depth < 0.12 or depth > 0.35:
        return None

    # Right rim: highest close after cup bottom
    after_bottom = data[cup_bottom_idx:]
    if len(after_bottom) < 5:
        return None

    right_rim_rel = int(np.argmax(after_bottom))
    right_rim_idx = cup_bottom_idx + right_rim_rel
    right_rim = float(data[right_rim_idx])

    # Right rim must recover to within 15% of left peak
    if (left_peak - right_rim) / left_peak > 0.15:
        return None

    # Cup must span at least 20 bars
    cup_length = right_rim_idx - left_peak_idx
    if cup_length < 20:
        return None

    return {
        "left_peak_idx": left_peak_idx,
        "left_peak": left_peak,
        "cup_bottom_idx": cup_bottom_idx,
        "cup_bottom": cup_bottom,
        "right_rim_idx": right_rim_idx,
        "right_rim": right_rim,
        "depth": depth,
        "cup_length": cup_length,
    }


def _is_u_shaped(close: np.ndarray, cup: Dict) -> bool:
    """Return True if cup region fits parabola with a > 0 (U-shape)."""
    try:
        start = cup["left_peak_idx"]
        end = cup["right_rim_idx"] + 1
        segment = close[start:end].astype(float)
        if len(segment) < 6:
            return False

        x = np.arange(len(segment), dtype=float)
        y = segment

        def parabola(x, a, b, c):
            return a * x ** 2 + b * x + c

        popt, _ = curve_fit(parabola, x, y, maxfev=3000)
        return float(popt[0]) > 0
    except Exception:
        return False


def _find_handle(
    close: np.ndarray,
    high: np.ndarray,
    volume: np.ndarray,
    cup: Dict,
    vol_sma50: float,
) -> Optional[Dict]:
    """Find a valid 5–25 day handle after the cup rim."""
    rim_idx = cup["right_rim_idx"]
    right_rim = cup["right_rim"]
    cup_midpoint = (cup["left_peak"] + cup["cup_bottom"]) / 2.0

    after_rim = close[rim_idx:]
    if len(after_rim) < 6:
        return None

    # Search up to 25 days after the rim
    handle_window = after_rim[:26]
    handle_vols = volume[rim_idx: rim_idx + 26] if rim_idx + 26 <= len(volume) else volume[rim_idx:]

    # Find the lowest point in handle (skip the rim bar itself)
    search = handle_window[1:]
    if len(search) < 4:
        return None

    handle_low_rel = int(np.argmin(search))
    handle_low = float(search[handle_low_rel])
    handle_length = len(search)

    # Pullback: 3–15% from rim (strong stocks form shallow 3-5% handles)
    pullback = (right_rim - handle_low) / right_rim
    if pullback < 0.03 or pullback > 0.15:
        return None

    # Handle low must not undercut cup midpoint
    if handle_low < cup_midpoint:
        return None

    # Volume must contract in handle vs 50-day avg
    if vol_sma50 > 0 and len(handle_vols) >= 4:
        handle_avg_vol = float(np.mean(handle_vols[1:4]))
        if handle_avg_vol >= vol_sma50:
            return None

    # handle_high: max intraday High in handle window (skip rim bar at index 0)
    handle_high_window = high[rim_idx: rim_idx + 26] if rim_idx + 26 <= len(high) else high[rim_idx:]
    handle_high = float(np.max(handle_high_window[1:])) if len(handle_high_window) > 1 else float(high[rim_idx])

    return {
        "handle_high": handle_high,        # was: right_rim
        "handle_low": handle_low,
        "pullback_pct": pullback,
        "handle_length": handle_length,
    }


def _quality_score(
    depth_pct: float,
    max_depth_pct: float,
    vol_dry_pct: float,
    rs_vs_spy: float,
    rs_blue_dot: bool,
) -> int:
    """Compute quality score 0–100 from four equally-weighted factors (25 pts each)."""
    # RS vs SPY: outperformance >= 5% = full 25 pts
    rs_pts = min(25.0, max(0.0, (rs_vs_spy / 0.05) * 25.0))

    # Base tightness: depth <= 8% = 25 pts, scales to 0 at max_depth_pct
    min_depth = 0.08
    if depth_pct <= min_depth:
        tight_pts = 25.0
    elif depth_pct >= max_depth_pct:
        tight_pts = 0.0
    else:
        ratio = (depth_pct - min_depth) / (max_depth_pct - min_depth)
        tight_pts = (1.0 - ratio) * 25.0

    # Volume dry-up: vol_dry_pct <= 30% of avg = 25 pts, scales to 0 at 1.0+
    max_dry = 0.3
    if vol_dry_pct <= max_dry:
        vol_pts = 25.0
    elif vol_dry_pct >= 1.0:
        vol_pts = 0.0
    else:
        vol_pts = ((1.0 - vol_dry_pct) / (1.0 - max_dry)) * 25.0

    # RS blue dot: 25 pts if True
    rs_high_pts = 25.0 if rs_blue_dot else 0.0

    return int(round(rs_pts + tight_pts + vol_pts + rs_high_pts))


def _prep(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    required = {"High", "Low", "Volume"}
    if not required.issubset(data.columns):
        return None
    return data


def _adj_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"
