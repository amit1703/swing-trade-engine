"""
Engine 5: Base Pattern Scanner (v2 — Volatility-Adjusted)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detects two strictly-filtered, volatility-adjusted base patterns.

PATTERN A — ATR-Adjusted Darvas Box (replaces fixed Flat Base):
  1. Stage 2 uptrend: SMA50 > SMA200 AND close > SMA50  (prior momentum REQUIRED)
  2. Box lookback: scan 20–40 trading days for the tightest valid window
  3. Dynamic tightness: box height (ceiling - floor) ≤ 3.5 × ATR14
     Eliminates slow, drifting low-ATR stocks that are NOT truly coiling
  4. Ceiling tested ≥ 2× during window (high within 0.5 × ATR of ceiling)
  5. Close in upper 25% of box (coiled near breakout)
  6. Volume dry-up: 3-day avg volume < 50-day avg volume

PATTERN B — Proportional Cup & Handle:
  1. Lookback 120 days; close > SMA200
  2. ATR-proportional depth: 15% ≤ depth ≤ (ATR_pct × 10)
     High-ATR stocks can have deeper cups; low-ATR stocks cannot
  3. Peak-to-low duration ≥ 25 trading days (no V-shapes)
  4. Current price in upper 50% of cup depth (consolidating at right height)
  5. Handle ATR < decline-phase ATR (volatility must contract in the handle)

Quality Score (0–100):
  25 pts: RS vs SPY (3-month outperformance)
  25 pts: Tightness (ATR-relative box/depth)
  25 pts: Volume dry-up (vs 50-day avg)
  25 pts: RS near 52-week high (blue dot signal)

Risk Math:
  Entry      = ceiling × 1.001  (Darvas) or handle_high × 1.001 (Cup)
  Stop Loss  = floor − 0.2 × ATR14
  Take Profit= nearest KDE resistance zone (fallback: Entry + 2 × Risk)
"""

import os
import sys
from typing import Dict, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr
from constants import TARGET_RR
from zone_utils import nearest_resistance_target


def scan_base_pattern(
    ticker: str,
    df: pd.DataFrame,
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    sr_zones: list = None,
) -> Optional[Dict]:
    """Return the highest-quality base setup found, or None."""
    ch = scan_cup_handle(ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, sr_zones)
    fb = scan_flat_base(ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, sr_zones)
    candidates = [s for s in [ch, fb] if s is not None and s.get("quality_score", 0) >= 25]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.get("quality_score", 0))


def scan_flat_base(
    ticker: str,
    df: pd.DataFrame,
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    sr_zones: list = None,
) -> Optional[Dict]:
    """ATR-Adjusted Darvas Box detector. Returns setup dict or None."""
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj = _adj_col(data)
        close_s = data[adj]
        high_s  = data["High"]
        low_s   = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # ── Stage 2: SMA50 > SMA200 AND close > SMA50 ────────────────────
        sma200 = close_s.rolling(200).mean()
        sma50  = close_s.rolling(50).mean()
        lc   = _fval(close_s.iloc[-1])
        l200 = _fval(sma200.iloc[-1])
        l50  = _fval(sma50.iloc[-1])

        if l200 <= 0 or l50 <= 0:   # SMA200 not yet available
            return None
        if lc < l50:                 # close must be above SMA50
            return None
        if l50 < l200:               # SMA50 must be above SMA200 (Stage 2)
            return None

        # ── ATR14 ─────────────────────────────────────────────────────────
        atr14 = _atr(high_s, low_s, close_s, 14)
        latr  = _fval(atr14.iloc[-1])
        if np.isnan(latr) or latr <= 0:
            return None

        # ── Volume 50-day SMA ─────────────────────────────────────────────
        vol50 = _fval(volume_s.rolling(50).mean().iloc[-1])
        if np.isnan(vol50) or vol50 <= 0:
            return None

        # Volume dry-up: 5-day avg must be below 50-day avg (consistent with Cup & Handle)
        vol5 = float(np.mean(volume_s.values[-5:]))
        if vol5 >= vol50:
            return None

        high_arr  = high_s.values.astype(float)
        low_arr   = low_s.values.astype(float)
        close_arr = close_s.values.astype(float)

        # ── Scan lookback windows 20–40, accept widest that passes all gates
        best = None
        for lb in range(40, 19, -1):
            if lb > len(close_arr):
                continue

            h_win = high_arr[-lb:]
            l_win = low_arr[-lb:]

            ceiling    = float(np.max(h_win))
            floor_val  = float(np.min(l_win))
            box_height = ceiling - floor_val

            if box_height <= 0:
                continue

            # Gate 1: dynamic tightness — box must be ≤ 3.5× ATR
            if box_height > 3.5 * latr:
                continue

            # Gate 2: ceiling tested at least twice
            touch_threshold = ceiling - 0.5 * latr
            ceiling_touches = int(np.sum(h_win >= touch_threshold))
            if ceiling_touches < 2:
                continue

            # Gate 3: close must be in upper 25% of box
            upper_quartile = floor_val + 0.75 * box_height
            if lc < upper_quartile:
                continue

            best = {
                "lookback": lb,
                "ceiling": ceiling,
                "floor": floor_val,
                "box_height": box_height,
                "atr_multiple": box_height / latr,
            }
            break

        if best is None:
            return None

        lb       = best["lookback"]
        ceiling  = best["ceiling"]
        floor_v  = best["floor"]
        box_height = best["box_height"]

        # ── Signal ────────────────────────────────────────────────────────
        last_vol  = _fval(volume_s.iloc[-1])
        vol_ratio = last_vol / vol50 if vol50 > 0 else 0.0
        dist_to_pivot = (ceiling - lc) / ceiling if ceiling > 0 else 1.0

        if lc > ceiling and vol_ratio >= 1.2:
            signal = "BRK"
        elif dist_to_pivot <= 0.010:
            signal = "DRY"
        else:
            return None

        # ── Risk math ─────────────────────────────────────────────────────
        entry     = round(ceiling * 1.001, 2)
        stop_loss = round(floor_v - 0.2 * latr, 2)
        risk = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None
        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones or [], risk)

        rs_vs_spy    = (rs_ratio - 1.0) - spy_3m_return
        vol_dry_pct  = vol5 / vol50
        tightness    = best["atr_multiple"] / 3.5   # 0 = very tight, 1 = at limit

        qs = _quality_score(
            tightness_pct=tightness,
            vol_dry_pct=vol_dry_pct,
            rs_vs_spy=rs_vs_spy,
            rs_blue_dot=rs_blue_dot,
        )

        base_start_idx = len(data) - lb

        return {
            "ticker": ticker,
            "setup_type": "BASE",
            "base_type": "FLAT_BASE",
            "signal": signal,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": actual_rr,
            "quality_score": qs,
            "base_depth_pct": round((box_height / ceiling) * 100, 1),
            "base_length_days": lb,
            "volume_dry_pct": round(vol_dry_pct * 100, 1),
            "rs_vs_spy": round(rs_vs_spy * 100, 2),
            "rs_score": round(rs_score, 4),
            "setup_date": str(data.index[-1].date()),
            "geometry": {
                "start_date": str(data.index[base_start_idx].date()),
                "end_date": str(data.index[-1].date()),
                "base_high": round(ceiling, 2),
                "base_low": round(floor_v, 2),
            },
        }

    except Exception as exc:
        print(f"[Engine5/DarvasBox] {ticker}: {exc}")
        return None


def scan_cup_handle(
    ticker: str,
    df: pd.DataFrame,
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    sr_zones: list = None,
) -> Optional[Dict]:
    """Proportional Cup & Handle with ATR-gated depth. Returns setup dict or None."""
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

        # ── Trend: close must be above SMA200 ────────────────────────────
        sma200 = close_s.rolling(200).mean()
        lc     = _fval(close_s.iloc[-1])
        l200   = _fval(sma200.iloc[-1])
        if l200 <= 0:           # SMA200 not yet computable
            return None
        if lc < l200:
            return None

        # ── ATR14 ─────────────────────────────────────────────────────────
        atr14 = _atr(high_s, low_s, close_s, 14)
        latr  = _fval(atr14.iloc[-1])
        if np.isnan(latr) or latr <= 0:
            return None
        atr_pct = latr / lc if lc > 0 else 0.0

        # ── Volume 50-day SMA ─────────────────────────────────────────────
        vol50 = _fval(volume_s.rolling(50).mean().iloc[-1])
        if np.isnan(vol50) or vol50 <= 0:
            return None

        # ── Cup detection within last 120 bars ────────────────────────────
        lookback  = min(120, len(close_s))
        close_arr = close_s.values.astype(float)
        high_arr  = high_s.values.astype(float)
        low_arr   = low_s.values.astype(float)
        vol_arr   = volume_s.values.astype(float)

        c_lb = close_arr[-lookback:]
        h_lb = high_arr[-lookback:]
        l_lb = low_arr[-lookback:]
        n    = len(c_lb)

        # Left peak: highest close in first 2/3 of window
        two_thirds = n * 2 // 3
        left_search = c_lb[:two_thirds]
        if len(left_search) < 15:
            return None
        left_peak_idx = int(np.argmax(left_search))
        left_peak     = float(left_search[left_peak_idx])

        # Cup bottom: lowest close after left peak
        after_peak = c_lb[left_peak_idx:]
        if len(after_peak) < 15:
            return None
        cup_bottom_rel = int(np.argmin(after_peak))
        cup_bottom_idx = left_peak_idx + cup_bottom_rel
        cup_bottom     = float(c_lb[cup_bottom_idx])

        # ATR-proportional depth: 15% ≤ depth ≤ (atr_pct × 10)
        depth     = (left_peak - cup_bottom) / left_peak if left_peak > 0 else 0.0
        max_depth = min(0.45, atr_pct * 10)
        if depth < 0.15 or depth > max_depth:
            return None

        # Duration: peak to low must span ≥ 25 bars (no V-shapes)
        if cup_bottom_idx - left_peak_idx < 25:
            return None

        # Right rim: highest close after cup bottom
        after_bottom = c_lb[cup_bottom_idx:]
        if len(after_bottom) < 5:
            return None
        right_rim_rel = int(np.argmax(after_bottom))
        right_rim_idx = cup_bottom_idx + right_rim_rel
        right_rim     = float(c_lb[right_rim_idx])

        # Right rim must recover at least 50% of cup depth (partial recovery ok)
        recovery = (right_rim - cup_bottom) / (left_peak - cup_bottom) if left_peak > cup_bottom else 0.0
        if recovery < 0.50:
            return None

        # ── Handle: need at least 5 bars after right rim ──────────────────
        handle_bars = n - right_rim_idx
        if handle_bars < 5:
            return None

        # Gate: current price in upper 50% of cup depth
        cup_depth_pts  = left_peak - cup_bottom
        handle_floor   = cup_bottom + 0.50 * cup_depth_pts
        if lc < handle_floor:
            return None

        # Gate: handle ATR < decline-phase ATR (volatility contraction)
        offset = len(close_arr) - lookback
        dec_start = offset + left_peak_idx
        dec_end   = offset + cup_bottom_idx
        han_start = len(close_arr) - handle_bars

        decline_tr = _mean_tr(high_arr, low_arr, close_arr, dec_start, dec_end)
        handle_tr  = _mean_tr(high_arr, low_arr, close_arr, han_start, len(close_arr))

        if decline_tr > 0 and handle_tr >= decline_tr:
            return None

        # ── Signal ────────────────────────────────────────────────────────
        handle_high_price = float(np.max(h_lb[right_rim_idx:]))
        handle_low_price  = float(np.min(l_lb[right_rim_idx:]))

        last_vol  = _fval(volume_s.iloc[-1])
        vol_ratio = last_vol / vol50 if vol50 > 0 else 0.0
        dist_to_pivot = (handle_high_price - lc) / handle_high_price if handle_high_price > 0 else 1.0

        if lc > handle_high_price and vol_ratio >= 1.2:
            signal = "BRK"
        elif dist_to_pivot <= 0.010:
            signal = "DRY"
        else:
            return None

        # ── Risk math ─────────────────────────────────────────────────────
        entry     = round(handle_high_price * 1.001, 2)
        stop_loss = round(handle_low_price - 0.2 * latr, 2)
        risk = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None
        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones or [], risk)

        # Volume dry-up quality factor (not a hard gate for Cup)
        vol5        = float(np.mean(vol_arr[-5:]))
        vol_dry_pct = vol5 / vol50 if vol50 > 0 else 1.0

        rs_vs_spy = (rs_ratio - 1.0) - spy_3m_return

        # Tightness: how close to minimum allowed depth (lower = tighter = better)
        allowed_range = max(max_depth - 0.15, 0.01)
        tightness = (depth - 0.15) / allowed_range   # 0 = min depth, 1 = max depth

        qs = _quality_score(
            tightness_pct=tightness,
            vol_dry_pct=vol_dry_pct,
            rs_vs_spy=rs_vs_spy,
            rs_blue_dot=rs_blue_dot,
        )

        left_peak_abs  = offset + left_peak_idx
        cup_bottom_abs = offset + cup_bottom_idx
        right_rim_abs  = offset + right_rim_idx
        base_length    = (len(close_arr) - 1) - left_peak_abs

        return {
            "ticker": ticker,
            "setup_type": "BASE",
            "base_type": "CUP_HANDLE",
            "signal": signal,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": actual_rr,
            "quality_score": qs,
            "base_depth_pct": round(depth * 100, 1),
            "base_length_days": max(0, base_length),
            "volume_dry_pct": round(vol_dry_pct * 100, 1),
            "rs_vs_spy": round(rs_vs_spy * 100, 2),
            "rs_score": round(rs_score, 4),
            "setup_date": str(data.index[-1].date()),
            "geometry": {
                "left_peak_date":   str(data.index[left_peak_abs].date()) if left_peak_abs < len(data) else None,
                "left_peak_price":  round(left_peak, 2),
                "cup_bottom_date":  str(data.index[cup_bottom_abs].date()) if cup_bottom_abs < len(data) else None,
                "cup_bottom_price": round(cup_bottom, 2),
                "right_rim_date":   str(data.index[right_rim_abs].date()) if right_rim_abs < len(data) else None,
                "right_rim_price":  round(right_rim, 2),
                "handle_high":      round(handle_high_price, 2),
                "handle_low":       round(handle_low_price, 2),
            },
        }

    except Exception as exc:
        print(f"[Engine5/CupHandle] {ticker}: {exc}")
        return None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _mean_tr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    start: int,
    end: int,
) -> float:
    """Mean True Range over bars [start:end]. Returns 0 if window is too small."""
    start = max(1, start)
    if end <= start + 2:
        return 0.0
    h      = high[start:end]
    l      = low[start:end]
    c_prev = close[start - 1: end - 1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - c_prev), np.abs(l - c_prev)))
    return float(np.mean(tr))


def _quality_score(
    tightness_pct: float,
    vol_dry_pct: float,
    rs_vs_spy: float,
    rs_blue_dot: bool,
) -> int:
    """Compute quality score 0–100 from four equally-weighted factors (25 pts each).

    tightness_pct: 0.0 = perfectly tight (min allowed width), 1.0 = at maximum limit.
    vol_dry_pct  : fraction of 50d avg volume (0.3 = 30% of avg = heavy dry-up).
    rs_vs_spy    : stock outperformance vs SPY (0.05 = 5% outperformance = full score).
    rs_blue_dot  : RS ratio near 52-week high.
    """
    # RS vs SPY: outperformance >= 5% = full 25 pts
    rs_pts = min(25.0, max(0.0, (rs_vs_spy / 0.05) * 25.0))

    # Tightness: 0 = max score (25), 1 = 0 pts
    tight_pts = max(0.0, (1.0 - min(1.0, tightness_pct)) * 25.0)

    # Volume dry-up: <= 30% of avg = 25 pts, scales to 0 at 1.0+
    if vol_dry_pct <= 0.3:
        vol_pts = 25.0
    elif vol_dry_pct >= 1.0:
        vol_pts = 0.0
    else:
        vol_pts = ((1.0 - vol_dry_pct) / 0.7) * 25.0

    # RS blue dot: 25 pts if True
    rs_high_pts = 25.0 if rs_blue_dot else 0.0

    return int(round(rs_pts + tight_pts + vol_pts + rs_high_pts))


def _fval(v) -> float:
    """Safe extraction of a Python float from a pandas scalar or numpy type."""
    if hasattr(v, 'item'):
        v = v.item()
    return float(v) if pd.notna(v) else 0.0


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
