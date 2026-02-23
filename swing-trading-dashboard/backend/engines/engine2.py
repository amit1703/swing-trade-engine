"""
Engine 2: VCP Breakout Scanner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two detection paths — both still surface as "VCP" setup type:

PATH A — DRY (Coiled Spring):
  1. Trend      : 8 EMA > 20 EMA  AND  Close > 50 SMA
  2. Contraction: Mean True Range of last 5 bars < Mean TR of prior 20 bars
  3. U-shape    : scipy curve_fit parabola over last 15 bars → a > 0
                  (U-shape accumulation, reject V-shape drops)
  4. Volume     : Dry-up phase (last 3 days avg < 50-day Vol SMA)
  5. Location   : Price is consolidating strictly just below an Engine 1
                  resistance zone (within 5% below zone level)

PATH B — BRK (Confirmed Breakout):
  1. Trend      : 8 EMA > 20 EMA  AND  Close > 50 SMA
  2. Location   : Close is STRICTLY ABOVE an Engine 1 resistance zone's
                  upper boundary, within 0.5%–3% of that upper bound
  3. Volume     : Daily Volume >= 150% of 50-day Vol SMA
  4. RS Filter  : Stock's 3-month return > SPY's 3-month return

Risk Math (both paths):
  Entry      = High of setup candle × 1.001
  Stop Loss  = min(Low, zone_lower_bound) − 0.2 × ATR
  Take Profit= Entry + 2 × Risk   (1:2 R:R)
"""

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import ema as _ema, sma as _sma, atr as _atr, true_range as _tr


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _detect_descending_trendline(
    ticker: str,
    df: pd.DataFrame,
) -> Optional[Dict]:
    """
    Detect a descending trendline from the last 120 days of High prices.

    Algorithm:
    1. Find swing highs using find_peaks on last 120 days
    2. Take the 2 most prominent peaks
    3. Fit a line through them (compute slope)
    4. Validate: negative slope, ≥2 touches within 0.8%
    5. Generate {time, value} series from peak1 to today

    Returns dict with keys: series, peak1, peak2, slope, touches
    Or None if no valid descending trendline found.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 30:
            return None

        high = data["High"].values
        dates = data.index

        # Use last 120 days for peak detection
        lookback = min(120, len(high))
        highs = high[-lookback:]
        date_slice = dates[-lookback:]

        # Find swing highs with find_peaks
        prominence_threshold = float(np.std(highs)) * 0.3
        peak_idx, props = find_peaks(highs, prominence=prominence_threshold, distance=5)

        if len(peak_idx) < 2:
            return None

        # Sort by prominence (descending), take top 2, then sort by time
        prominences = props["prominences"]
        sorted_order = np.argsort(prominences)[::-1]
        top2_raw = peak_idx[sorted_order[:2]]
        top2 = sorted(top2_raw.tolist())  # Sort by time index

        p1_idx, p2_idx = top2[0], top2[1]
        p1_price = float(highs[p1_idx])
        p2_price = float(highs[p2_idx])
        p1_date = date_slice[p1_idx]
        p2_date = date_slice[p2_idx]

        # Compute slope (price per day)
        day_diff = (p2_date - p1_date).days
        if day_diff <= 0:
            return None

        slope = (p2_price - p1_price) / day_diff

        # Validate: must be descending (negative slope)
        if slope >= 0:
            return None

        # Count touches: bars within 0.8% of trendline value
        touches = 0
        for i in range(len(highs)):
            days_from_p1 = (date_slice[i] - p1_date).days
            trendline_val = p1_price + slope * days_from_p1
            if trendline_val > 0 and abs(highs[i] - trendline_val) / trendline_val <= 0.008:
                touches += 1

        if touches < 2:
            return None

        # Generate series at actual trading dates from p1 to end of df
        series = []
        for date in data.index:
            if date < p1_date:
                continue
            days_from_p1 = (date - p1_date).days
            val = p1_price + slope * days_from_p1
            if val > 0:
                series.append({
                    "time": date.strftime("%Y-%m-%d"),
                    "value": round(float(val), 2)
                })

        if not series:
            return None

        return {
            "series": series,
            "peak1": {
                "date": p1_date.strftime("%Y-%m-%d"),
                "price": round(p1_price, 2),
            },
            "peak2": {
                "date": p2_date.strftime("%Y-%m-%d"),
                "price": round(p2_price, 2),
            },
            "slope": round(slope, 6),
            "touches": touches,
        }

    except Exception as exc:  # noqa: BLE001
        print(f"[_detect_descending_trendline] {ticker}: {exc}")
        return None


def _detect_ascending_trendline(
    ticker: str,
    df: pd.DataFrame,
) -> Optional[Dict]:
    """
    Detect an ascending trendline from the last 120 days of Low prices.

    Algorithm (mirrors descending):
    1. Find swing lows using find_peaks (inverted)
    2. Take 2 most prominent lows
    3. Fit line through them (compute slope)
    4. Validate: positive slope, ≥2 touches within 0.8%
    5. Generate {time, value} series from trough1 to today

    Returns dict with keys: series, trough1, trough2, slope, touches
    Or None if no valid ascending trendline found.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 30:
            return None

        low = data["Low"].values
        dates = data.index

        # Use last 120 days for trough detection
        lookback = min(120, len(low))
        lows = low[-lookback:]
        date_slice = dates[-lookback:]

        # Find swing lows (inverted find_peaks: negate to find minima)
        prominence_threshold = float(np.std(lows)) * 0.3
        # Negate lows to find valleys as peaks
        trough_idx, props = find_peaks(-lows, prominence=prominence_threshold, distance=5)

        if len(trough_idx) < 2:
            return None

        # Sort by prominence (descending), take top 2, then sort by time
        prominences = props["prominences"]
        sorted_order = np.argsort(prominences)[::-1]
        top2_raw = trough_idx[sorted_order[:2]]
        top2 = sorted(top2_raw.tolist())  # Sort by time index

        t1_idx, t2_idx = top2[0], top2[1]
        t1_price = float(lows[t1_idx])
        t2_price = float(lows[t2_idx])
        t1_date = date_slice[t1_idx]
        t2_date = date_slice[t2_idx]

        # Compute slope (price per day)
        day_diff = (t2_date - t1_date).days
        if day_diff <= 0:
            return None

        slope = (t2_price - t1_price) / day_diff

        # Validate: must be ascending (positive slope)
        if slope <= 0:
            return None

        # Count touches: bars within 0.8% of trendline value
        touches = 0
        for i in range(len(lows)):
            days_from_t1 = (date_slice[i] - t1_date).days
            trendline_val = t1_price + slope * days_from_t1
            if trendline_val > 0 and abs(lows[i] - trendline_val) / trendline_val <= 0.008:
                touches += 1

        if touches < 2:
            return None

        # Generate series at actual trading dates from t1 to end of df
        series = []
        for date in data.index:
            if date < t1_date:
                continue
            days_from_t1 = (date - t1_date).days
            val = t1_price + slope * days_from_t1
            if val > 0:
                series.append({
                    "time": date.strftime("%Y-%m-%d"),
                    "value": round(float(val), 2)
                })

        if not series:
            return None

        return {
            "series": series,
            "trough1": {
                "date": t1_date.strftime("%Y-%m-%d"),
                "price": round(t1_price, 2),
            },
            "trough2": {
                "date": t2_date.strftime("%Y-%m-%d"),
                "price": round(t2_price, 2),
            },
            "slope": round(slope, 6),
            "touches": touches,
        }

    except Exception as exc:  # noqa: BLE001
        print(f"[_detect_ascending_trendline] {ticker}: {exc}")
        return None


def detect_trendline(
    ticker: str,
    df: pd.DataFrame,
) -> Optional[Dict]:
    """
    Detect both descending (resistance) and ascending (support) trendlines.

    Returns unified structure with optional descending and ascending trendlines,
    or None if no trendlines found at all.

    Returns:
        {
            "descending": {...descending trendline dict...},  # or None
            "ascending": {...ascending trendline dict...}     # or None
        }
    Or None if both are None.
    """
    try:
        # Detect descending (resistance)
        descending = _detect_descending_trendline(ticker, df)

        # Detect ascending (support)
        ascending = _detect_ascending_trendline(ticker, df)

        # Return None only if both are None
        if descending is None and ascending is None:
            return None

        return {
            "descending": descending,
            "ascending": ascending,
        }

    except Exception as exc:  # noqa: BLE001
        print(f"[detect_trendline] {ticker}: {exc}")
        return None


def scan_near_breakout(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Returns a near-breakout dict if price is within 1.5% BELOW a resistance
    zone's upper boundary OR a descending trendline value.

    Does NOT require volume surge — purely proximity-based.
    Returns: {ticker, distance_pct, pattern_type, level, setup_type}
    Or None if not near any level.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 20:
            return None

        adj = _adj_col(data)
        lc_val = data[adj].iloc[-1]
        lc = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)

        PROXIMITY_PCT = 0.015   # 1.5% below level

        best_dist: Optional[float] = None
        best_level: Optional[float] = None
        best_type: Optional[str] = None

        # Check KDE resistance zones
        resistance_zones = [z for z in sr_zones if z["type"] == "RESISTANCE"]
        for z in resistance_zones:
            upper = z["upper"]
            if upper > lc:
                dist = (upper - lc) / upper
                if dist <= PROXIMITY_PCT:
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best_level = z["level"]
                        best_type = "KDE"

        # Check descending trendline (takes priority if closer)
        if trendline and trendline.get("descending") and trendline["descending"].get("series"):
            tl_today = trendline["descending"]["series"][-1]["value"]
            if tl_today > lc:
                dist = (tl_today - lc) / tl_today
                if dist <= PROXIMITY_PCT:
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best_level = tl_today
                        best_type = "TDL"

        # ── Check confirmed KDE breakout (price 0.1-3% ABOVE resistance upper) ──
        # These are stocks that just broke through a KDE resistance level.
        # scan_vcp is always called first; we only reach here if vcp returned None,
        # meaning the stock didn't pass the strict VCP trend filter. Catching these
        # confirmed breaks ensures they still surface in the WATCHLIST.
        BRK_PCT = 0.03   # up to 3% above level = "recently broke out"
        for z in resistance_zones:
            upper = z["upper"]
            if upper > 0 and lc > upper:
                pct_above = (lc - upper) / upper
                if 0.001 <= pct_above <= BRK_PCT:
                    if best_dist is None or pct_above < best_dist:
                        best_dist = pct_above
                        best_level = z["level"]
                        best_type = "KDE-BRK"

        # ── Check confirmed TDL breakout (price 0.1-3% ABOVE descending trendline) ──
        if trendline and trendline.get("descending") and trendline["descending"].get("series"):
            tl_series = trendline["descending"]["series"]
            if tl_series:
                tl_today = tl_series[-1]["value"]
                if tl_today > 0 and lc > tl_today:
                    pct_above = (lc - tl_today) / tl_today
                    if 0.001 <= pct_above <= BRK_PCT:
                        if best_dist is None or pct_above < best_dist:
                            best_dist = pct_above
                            best_level = tl_today
                            best_type = "TDL-BRK"

        if best_dist is None:
            return None

        is_confirmed_break = best_type in ("KDE-BRK", "TDL-BRK")

        return {
            "ticker":      ticker,
            "setup_type":  "WATCHLIST",
            "entry":       round(lc, 2),      # current price (placeholder)
            "stop_loss":   0.0,
            "take_profit": 0.0,
            "rr":          0.0,
            "setup_date":  str(data.index[-1].date()),
            "distance_pct": round(best_dist * 100, 2),
            "pattern_type": best_type,
            "level":        round(best_level, 2),
            "is_confirmed_break": is_confirmed_break,
        }

    except Exception as exc:
        print(f"[scan_near_breakout] {ticker}: {exc}")
        return None


def _calculate_base_depth(
    high: pd.Series,
    low: pd.Series,
    lookback: int = 30,
) -> tuple[float, bool]:
    """
    Calculate the maximum drawdown percentage of the VCP base.

    Parameters
    ----------
    high : pd.Series
        High prices (last lookback bars)
    low : pd.Series
        Low prices (last lookback bars)
    lookback : int
        Number of bars to analyze for base structure (default 30)

    Returns
    -------
    (base_depth_pct, is_valid)
        base_depth_pct: Percentage drawdown from high to low in base
        is_valid: True if depth is within professional range (10-40%)
    """
    try:
        if len(high) < lookback or len(low) < lookback:
            return 0.0, False

        recent_high = high.iloc[-lookback:].max()
        recent_low = low.iloc[-lookback:].min()

        if recent_high <= 0:
            return 0.0, False

        base_depth_pct = ((recent_high - recent_low) / recent_high) * 100

        # Professional VCP: base depth should be 10-40%
        is_valid = 10.0 <= base_depth_pct <= 40.0

        return round(base_depth_pct, 2), is_valid

    except Exception:
        return 0.0, False


def _count_contractions(
    tr_series: pd.Series,
    lookback: int = 25,
) -> tuple[int, str, bool]:
    """
    Count individual volatility contractions and identify pattern (3T, 4T, 5T, etc.).

    Parameters
    ----------
    tr_series : pd.Series
        True Range series (volatility)
    lookback : int
        Number of bars to analyze (default 25)

    Returns
    -------
    (contraction_count, pattern, is_progressive)
        contraction_count: Number of contractions detected
        pattern: "3T", "4T", "5T", etc. (or "NONE" if < 3)
        is_progressive: True if each contraction is tighter than previous
    """
    try:
        if len(tr_series) < lookback + 5:
            return 0, "NONE", False

        tr_clean = tr_series.dropna()
        if len(tr_clean) < lookback + 5:
            return 0, "NONE", False

        # Get the baseline: average TR from 20 bars ago
        baseline_tr = tr_clean.iloc[-lookback:-5].mean()

        # Count recent bars that are contractions (below baseline)
        recent_bars = tr_clean.iloc[-5:].values
        contractions = []

        for i, tr_val in enumerate(recent_bars):
            if tr_val < baseline_tr:
                contractions.append((i, tr_val))

        contraction_count = len(contractions)

        # Check if contractions are progressively tighter
        is_progressive = False
        if contraction_count >= 3:
            # Each contraction should be tighter (smaller TR) than previous
            tr_values = [v for _, v in contractions]
            is_progressive = all(tr_values[i] > tr_values[i+1] for i in range(len(tr_values)-1))

        # Map count to pattern name (3T, 4T, 5T, etc.)
        if contraction_count < 3:
            pattern = "NONE"
        else:
            pattern = f"{contraction_count}T"

        return contraction_count, pattern, is_progressive

    except Exception:
        return 0, "NONE", False


def scan_vcp(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
) -> Optional[Dict]:
    """
    Returns a setup dict if a valid VCP (Path A), Confirmed Breakout (Path B),
    Trendline Breakout (Path C), KDE Breakout (Path D), or RS Strength Breakout
    (Path E) is found, else None.

    Parameters
    ----------
    spy_3m_return : float
        SPY's 63-day (≈3 month) return, computed once per scan in main.py.
        Used for the relative-strength gate in Path B.
    rs_ratio : float
        Current RS ratio (stock/SPY).
    rs_52w_high : float
        52-week high of the RS ratio.
    rs_blue_dot : bool
        True if RS ratio is at 52-week high (institutional signal).
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj = _adj_col(data)
        close  = data[adj]
        high   = data["High"]
        low    = data["Low"]
        volume = data["Volume"]

        if close.dropna().shape[0] < 55:
            return None

        # ── Indicators ───────────────────────────────────────────────────
        ema8  = _ema(close, 8)
        ema20 = _ema(close, 20)
        sma50 = _sma(close, 50)
        sma200 = _sma(close, 200)  # Professional VCP: long-term trend filter
        atr14 = _atr(high, low, close, 14)

        # Extract scalars and use .item() for numpy types to avoid Series comparison errors
        lc   = float(close.iloc[-1].item() if hasattr(close.iloc[-1], 'item') else close.iloc[-1])
        lh   = float(high.iloc[-1].item() if hasattr(high.iloc[-1], 'item') else high.iloc[-1])
        ll   = float(low.iloc[-1].item() if hasattr(low.iloc[-1], 'item') else low.iloc[-1])
        l8   = float(ema8.iloc[-1].item() if hasattr(ema8.iloc[-1], 'item') else ema8.iloc[-1])
        l20  = float(ema20.iloc[-1].item() if hasattr(ema20.iloc[-1], 'item') else ema20.iloc[-1])
        l50  = float(sma50.iloc[-1].item() if hasattr(sma50.iloc[-1], 'item') else sma50.iloc[-1])
        l200 = float(sma200.iloc[-1].item() if hasattr(sma200.iloc[-1], 'item') else sma200.iloc[-1])
        latr = float(atr14.iloc[-1].item() if hasattr(atr14.iloc[-1], 'item') else atr14.iloc[-1])
        lvol = float(volume.iloc[-1].item() if hasattr(volume.iloc[-1], 'item') else volume.iloc[-1])

        if any(np.isnan(v) for v in [lc, lh, ll, l8, l20, l50, l200, latr]):
            return None

        # ── Shared: Baseline trend filter ────────────────────────────────
        # Requires 8 EMA > 20 EMA (short-term momentum) and price above 50 SMA.
        # NOTE: 200 SMA is NOT required here so that stocks breaking out of
        # downtrends via TDL/KDE (Paths C & D) are not gated out — they are
        # often still below the 200 SMA at the time of the initial breakout.
        # Path A (DRY coiled spring) re-applies the 200 SMA gate below.
        if not (l8 > l20 and lc > l50):
            return None
        is_above_200sma = lc > l200

        # ── Shared: Volume SMA ────────────────────────────────────────────
        vol_sma50 = volume.rolling(50).mean()
        vol_sma_val = vol_sma50.iloc[-1]
        if pd.isna(vol_sma_val):
            return None
        vol_sma_scalar = float(vol_sma_val.item() if hasattr(vol_sma_val, 'item') else vol_sma_val)
        if vol_sma_scalar <= 0:
            return None

        avg_vol        = vol_sma_scalar
        is_vol_surge   = lvol >= 1.5 * avg_vol      # ≥150 % of 50-day avg
        volume_ratio   = round(lvol / avg_vol, 2)

        # ── Shared: Stock 3-month relative strength ────────────────────────
        lb63 = min(63, len(close) - 1)
        if lb63 > 10:
            close_last = close.iloc[-1]
            close_past = close.iloc[-lb63]
            close_last_scalar = float(close_last.item() if hasattr(close_last, 'item') else close_last)
            close_past_scalar = float(close_past.item() if hasattr(close_past, 'item') else close_past)
            stock_3m_return = close_last_scalar / close_past_scalar - 1
        else:
            stock_3m_return = 0.0
        rs_vs_spy = round(stock_3m_return - spy_3m_return, 4)

        # ── FEATURE 2: Calculate base depth (professional VCP quality gate) ──
        base_depth_pct, is_valid_depth = _calculate_base_depth(high, low, lookback=30)

        # ── FEATURE 3: Count volatility contractions (3T, 4T, 5T pattern) ────
        tr = _tr(high, low, close).dropna()
        contraction_count, contraction_pattern, is_progressive = _count_contractions(tr, lookback=25)

        # ── PATH B — Confirmed Breakout ───────────────────────────────────
        # (checked first — higher conviction, takes priority)
        resistance_zones = [z for z in sr_zones if z["type"] == "RESISTANCE"]

        confirmed_breakout = False
        bk_zone: Optional[Dict] = None

        if resistance_zones and is_vol_surge and rs_vs_spy > 0:
            # Find resistance zones whose UPPER bound price has cleared
            broken = [z for z in resistance_zones if lc > z["upper"]]
            if broken:
                # Take the zone with the highest level (most recently broken)
                candidate = max(broken, key=lambda z: z["level"])
                pct_above_upper = (lc - candidate["upper"]) / candidate["upper"]
                # Price must be 0.3 % – 3 % above the zone's upper edge (reject stale breakouts)
                if 0.003 <= pct_above_upper <= 0.03:
                    confirmed_breakout = True
                    bk_zone = candidate

        if confirmed_breakout and bk_zone is not None:
            entry      = round(lh * 1.001, 2)
            stop_base  = min(ll, bk_zone["lower"])
            stop_loss  = round(stop_base - 0.2 * latr, 2)
            risk       = entry - stop_loss
            if risk <= 0 or risk > entry * 0.15:
                pass  # fall through to Path C/A check
            else:
                take_profit = round(entry + 2.0 * risk, 2)
                return {
                    "ticker":             ticker,
                    "setup_type":         "VCP",
                    "entry":              entry,
                    "stop_loss":          stop_loss,
                    "take_profit":        take_profit,
                    "rr":                 2.0,
                    "setup_date":         str(data.index[-1].date()),
                    "is_breakout":        True,
                    "is_vol_surge":       True,
                    "volume_ratio":       volume_ratio,
                    "resistance_level":   bk_zone["level"],
                    "breakout_pct":       round(
                        (lc - bk_zone["upper"]) / bk_zone["upper"] * 100, 2
                    ),
                    "rs_vs_spy":          rs_vs_spy,
                    "tr_contraction_pct": round((1 - (tr.iloc[-5:].mean() / tr.iloc[-25:-5].mean())) * 100, 1) if len(tr) >= 25 else None,
                    "is_trendline_breakout": False,
                    "is_kde_breakout":    False,
                    "is_rs_lead":         False,
                    "rs_ratio_today":     rs_ratio,
                    "rs_52w_high":        rs_52w_high,
                    "rs_blue_dot":        rs_blue_dot,
                    "trendline":          None,
                    "is_above_200sma":    is_above_200sma,
                    "base_depth_pct":     base_depth_pct,
                    "contraction_count":  contraction_count,
                    "contraction_pattern": contraction_pattern,
                    "is_progressive_tightening": is_progressive,
                }

        # ── PATH C — Trendline Breakout ────────────────────────────────────
        # Check if price broke above a descending trendline with volume
        trendline_result = detect_trendline(ticker, df)
        is_trendline_breakout = False
        trendline_data = None

        desc_tl = trendline_result.get("descending") if trendline_result else None
        if desc_tl is not None and desc_tl.get("series"):
            tl_today = desc_tl["series"][-1]["value"]
            # Breakout: close above descending trendline + vol surge ≥120% + trend filter (already checked)
            # Cap: price must be within 0-2% above the line (reject stale/extended breakouts)
            if tl_today > 0:
                pct_above_tl = (lc - tl_today) / tl_today
                if 0 < pct_above_tl <= 0.02 and lvol >= 1.2 * avg_vol:
                    is_trendline_breakout = True
                    trendline_data = trendline_result

        if is_trendline_breakout and trendline_data is not None:
            entry      = round(lh * 1.001, 2)
            stop_base  = min(ll, 0.98 * desc_tl["series"][-1]["value"])
            stop_loss  = round(stop_base - 0.2 * latr, 2)
            risk       = entry - stop_loss
            if risk > 0 and risk <= entry * 0.15:
                take_profit = round(entry + 2.0 * risk, 2)
                return {
                    "ticker":             ticker,
                    "setup_type":         "VCP",
                    "entry":              entry,
                    "stop_loss":          stop_loss,
                    "take_profit":        take_profit,
                    "rr":                 2.0,
                    "setup_date":         str(data.index[-1].date()),
                    "is_breakout":        True,
                    "is_vol_surge":       lvol >= 1.5 * avg_vol,
                    "volume_ratio":       volume_ratio,
                    "resistance_level":   None,
                    "breakout_pct":       None,
                    "rs_vs_spy":          rs_vs_spy,
                    "tr_contraction_pct": round((1 - (tr.iloc[-5:].mean() / tr.iloc[-25:-5].mean())) * 100, 1) if len(tr) >= 25 else None,
                    "is_trendline_breakout": True,
                    "is_kde_breakout":    False,
                    "is_rs_lead":         False,
                    "rs_ratio_today":     rs_ratio,
                    "rs_52w_high":        rs_52w_high,
                    "rs_blue_dot":        rs_blue_dot,
                    "trendline":          trendline_data,
                    "is_above_200sma":    is_above_200sma,
                    "base_depth_pct":     base_depth_pct,
                    "contraction_count":  contraction_count,
                    "contraction_pattern": contraction_pattern,
                    "is_progressive_tightening": is_progressive,
                }

        # ── PATH D — KDE Horizontal Breakout ─────────────────────────────────
        # Breakout above the NEAREST resistance zone above current price
        # (not highest — distant levels are irrelevant for breakout detection)

        nearest_res_above = None
        nearest_dist = float("inf")
        for z in resistance_zones:
            dist = z["level"] - lc
            # Zone must be near current price (within 5% above) to be relevant
            if -0.02 * lc <= dist <= 0.05 * lc and abs(dist) < nearest_dist:
                nearest_dist = abs(dist)
                nearest_res_above = z

        if nearest_res_above is not None:
            upper = nearest_res_above["upper"]
            pct_above_upper = (lc - upper) / upper if upper > 0 else 0.0

            # Check: 0.1% to 2.5% above resistance + volume ≥115% + RS ≥0
            is_kde_breakout = (
                0.001 <= pct_above_upper <= 0.025 and
                lvol >= 1.15 * avg_vol and
                rs_vs_spy >= 0
            )

            if is_kde_breakout:
                entry      = round(lh * 1.001, 2)
                stop_base  = min(ll, nearest_res_above["lower"])
                stop_loss  = round(stop_base - 0.2 * latr, 2)
                risk       = entry - stop_loss

                if risk > 0 and risk <= entry * 0.15:
                    take_profit = round(entry + 2.0 * risk, 2)
                    return {
                        "ticker":             ticker,
                        "setup_type":         "VCP",
                        "entry":              entry,
                        "stop_loss":          stop_loss,
                        "take_profit":        take_profit,
                        "rr":                 2.0,
                        "setup_date":         str(data.index[-1].date()),
                        "is_breakout":        True,
                        "is_vol_surge":       lvol >= 1.5 * avg_vol,
                        "volume_ratio":       volume_ratio,
                        "resistance_level":   nearest_res_above["level"],
                        "breakout_pct":       round(pct_above_upper * 100, 2),
                        "rs_vs_spy":          rs_vs_spy,
                        "tr_contraction_pct": round((1 - (tr.iloc[-5:].mean() / tr.iloc[-25:-5].mean())) * 100, 1) if len(tr) >= 25 else None,
                        "is_trendline_breakout": False,
                        "is_kde_breakout":    True,
                        "is_rs_lead":         False,
                        "rs_ratio_today":     rs_ratio,
                        "rs_52w_high":        rs_52w_high,
                        "rs_blue_dot":        rs_blue_dot,
                        "trendline":          None,
                        "is_above_200sma":    is_above_200sma,
                        "base_depth_pct":     base_depth_pct,
                        "contraction_count":  contraction_count,
                        "contraction_pattern": contraction_pattern,
                        "is_progressive_tightening": is_progressive,
                    }

        # ── PATH E — RS Strength Breakout ────────────────────────────────────
        # Institutional accumulation signal: RS Blue Dot + proximity to resistance
        # Uses nearest resistance above price (not highest distant level)

        if nearest_res_above is not None and rs_blue_dot:
            upper = nearest_res_above["upper"]
            pct_below_upper = (upper - lc) / upper if upper > 0 else 1.0

            # Check: within 3% below resistance + RS Blue Dot (no volume requirement)
            is_rs_lead = (
                pct_below_upper <= 0.03 and
                lc < upper and
                l8 > l20 and
                lc > l50
            )

            if is_rs_lead:
                entry      = round(lh * 1.001, 2)
                stop_base  = min(ll, nearest_res_above["lower"])
                stop_loss  = round(stop_base - 0.2 * latr, 2)
                risk       = entry - stop_loss

                if risk > 0 and risk <= entry * 0.15:
                    take_profit = round(entry + 2.0 * risk, 2)
                    return {
                        "ticker":             ticker,
                        "setup_type":         "VCP",
                        "entry":              entry,
                        "stop_loss":          stop_loss,
                        "take_profit":        take_profit,
                        "rr":                 2.0,
                        "setup_date":         str(data.index[-1].date()),
                        "is_breakout":        True,
                        "is_vol_surge":       False,
                        "volume_ratio":       volume_ratio,
                        "resistance_level":   nearest_res_above["level"],
                        "breakout_pct":       round(pct_below_upper * 100, 2),
                        "rs_vs_spy":          rs_vs_spy,
                        "tr_contraction_pct": round((1 - (tr.iloc[-5:].mean() / tr.iloc[-25:-5].mean())) * 100, 1) if len(tr) >= 25 else None,
                        "is_trendline_breakout": False,
                        "is_kde_breakout":    False,
                        "is_rs_lead":         True,
                        "rs_ratio_today":     rs_ratio,
                        "rs_52w_high":        rs_52w_high,
                        "rs_blue_dot":        rs_blue_dot,
                        "trendline":          None,
                        "is_above_200sma":    is_above_200sma,
                        "base_depth_pct":     base_depth_pct,
                        "contraction_count":  contraction_count,
                        "contraction_pattern": contraction_pattern,
                        "is_progressive_tightening": is_progressive,
                    }

        # ── PATH A — DRY (Coiled Spring) ──────────────────────────────────
        # Path A (coiled spring below resistance) requires the FULL trend template:
        # price must be above the 200 SMA (confirmed Stage 2 uptrend).
        if not (lc > l200):
            return None


        # ── A2. True Range contraction ────────────────────────────────────
        # (tr already computed above for contraction counting)
        if len(tr) < 26:
            return None

        last5_tr_val = tr.iloc[-5:].mean()
        prev20_tr_val = tr.iloc[-25:-5].mean()
        last5_tr  = float(last5_tr_val.item() if hasattr(last5_tr_val, 'item') else last5_tr_val)
        prev20_tr = float(prev20_tr_val.item() if hasattr(prev20_tr_val, 'item') else prev20_tr_val)
        if last5_tr >= prev20_tr:
            return None

        # ── A3. U-shape parabolic check ───────────────────────────────────
        lb      = min(15, len(close) - 5)
        recent  = close.values[-lb:].astype(float)
        if np.any(np.isnan(recent)):
            return None

        xv             = np.arange(lb, dtype=float)
        mean_p, std_p  = recent.mean(), recent.std()
        if std_p < 1e-8:
            return None

        yn   = (recent - mean_p) / std_p
        is_u = False
        try:
            popt, _ = curve_fit(_parabola, xv, yn, maxfev=2000)
            a, b, _ = popt
            vertex_x = -b / (2.0 * a) if abs(a) > 1e-8 else -1.0
            is_u = a > 0.005 and 0.0 <= vertex_x <= float(lb)
        except Exception:
            is_u = False

        if not is_u:
            return None

        # ── A4. Volume dry-up ─────────────────────────────────────────────
        last3_vol_val = volume.iloc[-3:].mean()
        last3_vol = float(last3_vol_val.item() if hasattr(last3_vol_val, 'item') else last3_vol_val)
        is_dry = last3_vol < avg_vol

        # ── A5. Engine 1 resistance proximity ────────────────────────────
        nearest_res = None
        best_dist   = float("inf")
        for z in resistance_zones:
            dist = z["level"] - lc
            # Within 5 % below resistance, price hasn't broken through
            if 0.0 <= dist <= z["level"] * 0.05 and dist < best_dist:
                best_dist   = dist
                nearest_res = z

        if nearest_res is None:
            return None

        # Volume gate: in dry-up phase below resistance OR already breaking
        at_breakout = lc >= nearest_res["lower"] and is_vol_surge
        in_dry_up   = lc <  nearest_res["lower"] and is_dry

        if not (at_breakout or in_dry_up):
            return None

        # ── Risk math ─────────────────────────────────────────────────────
        entry      = round(lh * 1.001, 2)
        stop_base  = min(ll, nearest_res["lower"])
        stop_loss  = round(stop_base - 0.2 * latr, 2)
        risk       = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None

        take_profit = round(entry + 2.0 * risk, 2)

        return {
            "ticker":             ticker,
            "setup_type":         "VCP",
            "entry":              entry,
            "stop_loss":          stop_loss,
            "take_profit":        take_profit,
            "rr":                 2.0,
            "setup_date":         str(data.index[-1].date()),
            "is_breakout":        at_breakout,
            "is_vol_surge":       is_vol_surge,
            "volume_ratio":       volume_ratio,
            "resistance_level":   nearest_res["level"],
            "breakout_pct":       None,
            "rs_vs_spy":          rs_vs_spy,
            "tr_contraction_pct": round((1 - last5_tr / prev20_tr) * 100, 1),
            "is_trendline_breakout": False,
            "is_kde_breakout":    False,
            "is_rs_lead":         False,
            "rs_ratio_today":     rs_ratio,
            "rs_52w_high":        rs_52w_high,
            "rs_blue_dot":        rs_blue_dot,
            "trendline":          None,
            "is_above_200sma":    True,
            "base_depth_pct":     base_depth_pct,
            "contraction_count":  contraction_count,
            "contraction_pattern": contraction_pattern,
            "is_progressive_tightening": is_progressive,
        }

    except Exception as exc:  # noqa: BLE001
        print(f"[Engine2] {ticker}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parabola(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    return a * x**2 + b * x + c


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
