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
  4. RS Filter  : Stock's 3-month return > SPY's 3-month return − 5% (rs_vs_spy > −0.05)

Risk Math (both paths):
  Entry      = High of setup candle × 1.001
  Stop Loss  = min(Low, zone_lower_bound) − ATR_STOP_MULTIPLIER × ATR  (currently 0.8)
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
from constants import (
    TARGET_RR, ATR_STOP_MULTIPLIER, VCP_ATR_CONTRACTION_THRESHOLD,
    VCP_TIGHT_RANGE_5D_PCT, VCP_MIN_CONTRACTIONS_STRICT, VCP_MIN_CONTRACTIONS_RELAXED,
)
from zone_utils import nearest_resistance_target

# ── Per-process trendline / curve-fit caches ──────────────────────────────
# Key: (ticker, last_bar_date_str, lookback_len)  →  result dict or None
# Eliminates redundant scipy find_peaks / curve_fit calls across WFO windows
# that share overlapping bars (same ticker + date = identical lookback data).
_TDL_DESC_CACHE:  Dict[tuple, Optional[Dict]] = {}
_TDL_ASC_CACHE:   Dict[tuple, Optional[Dict]] = {}
# Key: (ticker, last_bar_date_str, lb) → bool (is_u)
_CURVE_FIT_CACHE: Dict[tuple, bool] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _descending_no_slice(
    highs: np.ndarray,
    date_slice,
    anchor_idx: int,
    anchor_price: float,
    slope: float,
) -> bool:
    """
    Validate a descending trendline does NOT pierce through price action.

    Rule: between the anchor bar and the end of the data, no bar's High may
    exceed the trendline value by more than 1 %.  A descending resistance
    line must CONTAIN price above it — not slice through candles.

    Returns True  (line is valid)
    Returns False (line slices through price action — reject it)
    """
    anchor_date = date_slice[anchor_idx]
    for k in range(len(highs)):
        if date_slice[k] <= anchor_date:
            continue
        days_k = (date_slice[k] - anchor_date).days
        tl_val = anchor_price + slope * days_k
        if tl_val <= 0:
            continue
        if highs[k] > tl_val * 1.01:   # high > line + 1 % → slice
            return False
    return True


def _ascending_no_slice(
    lows: np.ndarray,
    closes: np.ndarray,
    date_slice,
    anchor_idx: int,
    anchor_price: float,
    slope: float,
) -> bool:
    """
    Validate an ascending trendline does NOT pierce through price action.

    Rules (both must hold for every bar after the anchor):
      1. Close must NOT be below the trendline (a close below = support broken).
      2. Low  must NOT be more than 1 % below the trendline (wick tolerance).

    Returns True  (line is valid)
    Returns False (line slices through price action — reject it)
    """
    anchor_date = date_slice[anchor_idx]
    for k in range(len(lows)):
        if date_slice[k] <= anchor_date:
            continue
        days_k = (date_slice[k] - anchor_date).days
        tl_val = anchor_price + slope * days_k
        if tl_val <= 0:
            continue
        if closes[k] < tl_val:            # close below line → reject
            return False
        if lows[k] < tl_val * 0.99:       # wick > 1 % below → reject
            return False
    return True


def _detect_descending_trendline(
    ticker: str,
    df: pd.DataFrame,
) -> Optional[Dict]:
    """
    Detect a descending trendline from the last 120 days of High prices.

    Algorithm (three-rule rewrite):
    1. MACRO ANCHOR  — Anchor A is ALWAYS the global High.max() of the
       lookback window (even if at the array boundary where find_peaks misses it).
       This ensures we capture the overarching structural trendline, not just
       local micro-patterns.
    2. NO-SLICE RULE — Between anchor A and today, no bar's High may exceed
       the trendline by more than 1 %.  Lines that pierce through candles are
       rejected.
    3. RELEVANCE     — Trendline value today must be ≤ 120 % of current close.
       Filters stale lines from peaks far above current price.

    Anchor B is selected from find_peaks candidates that appear AFTER anchor A,
    scored by touch count.  Best (most touches) is chosen.

    Returns dict with keys: series, peak1, peak2, slope, touches
    Or None if no valid descending trendline found.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 30:
            return None

        high = data["High"].values
        adj  = _adj_col(data)
        dates = data.index

        lookback = min(120, len(high))
        _cache_key = (ticker, str(data.index[-1].date()), lookback)
        if _cache_key in _TDL_DESC_CACHE:
            return _TDL_DESC_CACHE[_cache_key]
        highs      = high[-lookback:]
        date_slice = dates[-lookback:]
        adj_close  = data[adj].values[-lookback:]

        # ── Fix 3: Macro anchor — always start from the global maximum ────
        global_max_idx = int(np.argmax(highs))
        p1_price       = float(highs[global_max_idx])
        p1_date        = date_slice[global_max_idx]

        # ── Find anchor B candidates with find_peaks ────────────────────
        prominence_threshold = float(np.std(highs)) * 0.3
        peak_idx, _ = find_peaks(highs, prominence=prominence_threshold, distance=5)

        best_pair    = None
        best_touches = 0

        for j in range(len(peak_idx)):
            pj_idx = int(peak_idx[j])
            if pj_idx <= global_max_idx:
                continue            # B must come after A

            pj_price = float(highs[pj_idx])
            pj_date  = date_slice[pj_idx]

            day_diff = (pj_date - p1_date).days
            if day_diff <= 0:
                continue

            slope = (pj_price - p1_price) / day_diff
            if slope >= 0:          # Must be descending
                continue

            # ── Fix 2: No-slice rule ──────────────────────────────────────
            if not _descending_no_slice(highs, date_slice, global_max_idx, p1_price, slope):
                continue

            # Score by touch count (bars within 1 % of trendline)
            touches = 0
            for k in range(len(highs)):
                days_k = (date_slice[k] - p1_date).days
                tl_val = p1_price + slope * days_k
                if tl_val > 0 and abs(highs[k] - tl_val) / tl_val <= 0.010:
                    touches += 1

            if touches > best_touches or (
                touches == best_touches and best_pair is not None
                and pj_idx > best_pair[0]
            ):
                best_touches = touches
                best_pair    = (pj_idx, pj_price, pj_date, slope)

        if best_pair is None or best_touches < 2:
            _TDL_DESC_CACHE[_cache_key] = None
            return None

        p2_idx, p2_price, p2_date, slope = best_pair

        # Generate series from anchor A to end of df
        series = []
        for date in data.index:
            if date < p1_date:
                continue
            days_from_p1 = (date - p1_date).days
            val = p1_price + slope * days_from_p1
            if val > 0:
                series.append({
                    "time":  date.strftime("%Y-%m-%d"),
                    "value": round(float(val), 2),
                })

        if not series:
            _TDL_DESC_CACHE[_cache_key] = None
            return None

        # ── Relevance filter ─────────────────────────────────────────────
        lc_val  = data[adj].iloc[-1]
        lc      = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        tl_today = series[-1]["value"]
        if lc > 0 and tl_today > lc * 1.20:
            _TDL_DESC_CACHE[_cache_key] = None
            return None

        _res = {
            "series": series,
            "peak1":  {"date": p1_date.strftime("%Y-%m-%d"), "price": round(p1_price, 2)},
            "peak2":  {"date": p2_date.strftime("%Y-%m-%d"), "price": round(p2_price, 2)},
            "slope":  round(slope, 6),
            "touches": best_touches,
        }
        _TDL_DESC_CACHE[_cache_key] = _res
        return _res

    except Exception as exc:  # noqa: BLE001
        print(f"[_detect_descending_trendline] {ticker}: {exc}")
        return None


def _detect_ascending_trendline(
    ticker: str,
    df: pd.DataFrame,
) -> Optional[Dict]:
    """
    Detect an ascending trendline from the last 120 days of Low prices.

    Algorithm (three-rule rewrite):
    1. MACRO ANCHOR  — Anchor A is ALWAYS the global Low.min() of the
       lookback window (even at the array boundary).
    2. NO-SLICE RULE — Between anchor A and today:
         • No close may fall below the trendline.
         • No low may drop more than 1 % below the trendline (wick tolerance).
    3. RELEVANCE     — Trendline value today must be ≥ 80 % of current close.

    Anchor B is selected from find_peaks (inverted) candidates after anchor A,
    scored by touch count.

    Returns dict with keys: series, trough1, trough2, slope, touches
    Or None if no valid ascending trendline found.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 30:
            return None

        low   = data["Low"].values
        adj   = _adj_col(data)
        dates = data.index

        lookback   = min(120, len(low))
        lows       = low[-lookback:]
        date_slice = dates[-lookback:]
        closes     = data[adj].values[-lookback:]

        _cache_key = (ticker, str(data.index[-1].date()), lookback)
        if _cache_key in _TDL_ASC_CACHE:
            return _TDL_ASC_CACHE[_cache_key]

        # ── Fix 3: Macro anchor — always start from the global minimum ───
        global_min_idx = int(np.argmin(lows))
        t1_price       = float(lows[global_min_idx])
        t1_date        = date_slice[global_min_idx]

        # ── Find anchor B candidates with find_peaks (inverted) ─────────
        prominence_threshold = float(np.std(lows)) * 0.3
        trough_idx, _ = find_peaks(-lows, prominence=prominence_threshold, distance=5)

        best_pair    = None
        best_touches = 0

        for j in range(len(trough_idx)):
            tj_idx = int(trough_idx[j])
            if tj_idx <= global_min_idx:
                continue            # B must come after A

            tj_price = float(lows[tj_idx])
            tj_date  = date_slice[tj_idx]

            day_diff = (tj_date - t1_date).days
            if day_diff <= 0:
                continue

            slope = (tj_price - t1_price) / day_diff
            if slope <= 0:          # Must be ascending (higher lows)
                continue

            # ── Fix 2: No-slice rule ──────────────────────────────────────
            if not _ascending_no_slice(lows, closes, date_slice, global_min_idx, t1_price, slope):
                continue

            # Score by touch count (bars within 1 % of trendline)
            touches = 0
            for k in range(len(lows)):
                days_k = (date_slice[k] - t1_date).days
                tl_val = t1_price + slope * days_k
                if tl_val > 0 and abs(lows[k] - tl_val) / tl_val <= 0.010:
                    touches += 1

            if touches > best_touches or (
                touches == best_touches and best_pair is not None
                and tj_idx > best_pair[0]
            ):
                best_touches = touches
                best_pair    = (tj_idx, tj_price, tj_date, slope)

        if best_pair is None or best_touches < 2:
            _TDL_ASC_CACHE[_cache_key] = None
            return None

        t2_idx, t2_price, t2_date, slope = best_pair

        # Generate series from anchor A to end of df
        series = []
        for date in data.index:
            if date < t1_date:
                continue
            days_from_t1 = (date - t1_date).days
            val = t1_price + slope * days_from_t1
            if val > 0:
                series.append({
                    "time":  date.strftime("%Y-%m-%d"),
                    "value": round(float(val), 2),
                })

        if not series:
            _TDL_ASC_CACHE[_cache_key] = None
            return None

        # ── Relevance filter ─────────────────────────────────────────────
        lc_val  = data[adj].iloc[-1]
        lc      = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        tl_today = series[-1]["value"]
        if lc > 0 and tl_today < lc * 0.80:
            _TDL_ASC_CACHE[_cache_key] = None
            return None

        _res = {
            "series":  series,
            "trough1": {"date": t1_date.strftime("%Y-%m-%d"), "price": round(t1_price, 2)},
            "trough2": {"date": t2_date.strftime("%Y-%m-%d"), "price": round(t2_price, 2)},
            "slope":   round(slope, 6),
            "touches": best_touches,
        }
        _TDL_ASC_CACHE[_cache_key] = _res
        return _res

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
        BRK_PCT = 0.01   # up to 1% above level = "recently broke out"
        for z in resistance_zones:
            upper = z["upper"]
            if upper > 0 and lc > upper:
                pct_above = (lc - upper) / upper
                if 0.001 <= pct_above <= BRK_PCT:
                    if best_dist is None or pct_above < best_dist:
                        best_dist = pct_above
                        best_level = z["level"]
                        best_type = "KDE-BRK"

        if best_dist is None:
            return None

        is_confirmed_break = best_type in ("KDE-BRK",)

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


def _weekly_confirmed(df: pd.DataFrame) -> bool:
    """
    Task 12: Multi-timeframe confirmation.

    Resamples daily OHLCV to weekly (week-ending Friday) and checks:
      • Weekly EMA8 > Weekly EMA20
      • Weekly Close > Weekly EMA20  (price above short-term weekly trend)

    Returns True when both conditions hold on the most recent complete week.
    Returns False on any data error (fail open — do not block setups).
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 40:
            return False

        adj  = _adj_col(data)
        wkly = data.resample("W-FRI").agg({
            adj:    "last",
            "High": "max",
            "Low":  "min",
        }).dropna()

        if len(wkly) < 22:
            return False

        wc      = wkly[adj]
        w_ema8  = _ema(wc, 8)
        w_ema20 = _ema(wc, 20)

        if w_ema8.dropna().empty or w_ema20.dropna().empty:
            return False

        we8  = float(w_ema8.iloc[-1])
        we20 = float(w_ema20.iloc[-1])
        wlc  = float(wc.iloc[-1])

        if any(np.isnan(v) for v in [we8, we20, wlc]):
            return False

        return we8 > we20 and wlc > we20

    except Exception:
        return False  # fail open


def _has_vol_dryup(
    volume: pd.Series,
    avg_vol: float,
    window: int = 10,
    threshold: float = 0.5,
) -> bool:
    """
    Return True if at least one bar in the last `window` bars has
    volume strictly less than `threshold` × avg_vol.

    Implements the Minervini/O'Neil "institutional dry-up" gate:
    genuine volume evaporation must include at least one day of real
    indifference (< 50 % of the 50-day average), not just a mild
    drift below the average.
    """
    if avg_vol <= 0 or len(volume) < window:
        return False
    return bool((volume.iloc[-window:] < threshold * avg_vol).any())


def scan_vcp(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    rs_improving: bool = False,
    rs_near_high: bool = False,
    rs_acceleration: float = 0.0,
    debug: bool = False,
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
    rs_improving : bool
        True if the RS line slope over the last 10 bars is positive.
        Passed through to all return dicts as a quality signal.
    rs_near_high : bool
        True if current RS ratio is within 10% of its 52-week high.
        Passed through to all return dicts as a quality signal.
    rs_acceleration : float
        Rate of change of the RS line over 10 bars, normalised by prior value.
        Positive = accelerating outperformance. Passed through to all return dicts.
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

        # ── Indicators (use pre-computed columns from BacktestEngine when available) ──
        ema8   = data["_EMA8"]   if "_EMA8"   in data.columns else _ema(close, 8)
        ema20  = data["_EMA20"]  if "_EMA20"  in data.columns else _ema(close, 20)
        sma50  = data["_SMA50"]  if "_SMA50"  in data.columns else _sma(close, 50)
        sma200 = data["_SMA200"] if "_SMA200" in data.columns else _sma(close, 200)
        atr14  = data["_ATR14"]  if "_ATR14"  in data.columns else _atr(high, low, close, 14)

        # Extract scalars and use .item() for numpy types to avoid Series comparison errors
        lc   = float(close.iloc[-1].item() if hasattr(close.iloc[-1], 'item') else close.iloc[-1])

        # ── Tight Price Action: 5-day close range / last close ────────────────
        _closes_5    = data[_adj_col(data)].iloc[-5:].values if len(data) >= 5 else data[_adj_col(data)].values
        _c5_range    = (float(_closes_5.max()) - float(_closes_5.min())) / float(lc) if lc > 0 else 1.0
        tight_range_5d = _c5_range <= VCP_TIGHT_RANGE_5D_PCT

        lh   = float(high.iloc[-1].item() if hasattr(high.iloc[-1], 'item') else high.iloc[-1])
        ll   = float(low.iloc[-1].item() if hasattr(low.iloc[-1], 'item') else low.iloc[-1])
        l8   = float(ema8.iloc[-1].item() if hasattr(ema8.iloc[-1], 'item') else ema8.iloc[-1])
        l20  = float(ema20.iloc[-1].item() if hasattr(ema20.iloc[-1], 'item') else ema20.iloc[-1])
        l50  = float(sma50.iloc[-1].item() if hasattr(sma50.iloc[-1], 'item') else sma50.iloc[-1])
        l200 = float(sma200.iloc[-1].item() if hasattr(sma200.iloc[-1], 'item') else sma200.iloc[-1])
        latr = float(atr14.iloc[-1].item() if hasattr(atr14.iloc[-1], 'item') else atr14.iloc[-1])
        lvol = float(volume.iloc[-1].item() if hasattr(volume.iloc[-1], 'item') else volume.iloc[-1])

        if any(np.isnan(v) for v in [lc, lh, ll, l8, l20, l50, latr]):
            return None

        # ── Shared: Baseline trend filter ────────────────────────────────
        # Requires 8 EMA > 20 EMA (short-term momentum) and price above 50 SMA.
        # NOTE: 200 SMA is NOT required here so that stocks breaking out of
        # downtrends via TDL/KDE (Paths C & D) are not gated out — they are
        # often still below the 200 SMA at the time of the initial breakout.
        # Path A (DRY coiled spring) re-applies the 200 SMA gate below.
        if not (l8 > l20 and lc > l50):
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - Trend filter failed "
                    f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50 {l50:.2f})"
                )
            return None
        is_above_200sma = (not np.isnan(l200)) and lc > l200

        # ── Shared: Volume SMA ────────────────────────────────────────────
        vol_sma50   = data["_VOLSMA50"] if "_VOLSMA50" in data.columns else volume.rolling(50).mean()
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

        if resistance_zones and is_vol_surge:
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

        if confirmed_breakout and bk_zone is not None and contraction_count >= VCP_MIN_CONTRACTIONS_RELAXED:
            entry      = round(lh * 1.001, 2)
            stop_base  = min(ll, bk_zone["lower"])
            stop_loss  = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
            risk       = entry - stop_loss
            if risk <= 0 or risk > entry * 0.15:
                if debug:
                    print(
                        f"Engine 2 VCP: REJECTED - Path B risk math invalid "
                        f"(risk={risk:.2f}, entry={entry:.2f}, "
                        f"max_allowed={entry * 0.15:.2f})"
                    )
            else:
                take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)
                return {
                    "ticker":             ticker,
                    "setup_type":         "VCP",
                    "entry":              entry,
                    "stop_loss":          stop_loss,
                    "take_profit":        take_profit,
                    "rr": actual_rr,
                    "setup_date":         str(data.index[-1].date()),
                    "is_breakout":        True,
                    "is_vol_surge":       True,
                    "volume_ratio":       volume_ratio,
                    "resistance_level":   bk_zone["level"],
                    "breakout_pct":       round(
                        (lc - bk_zone["upper"]) / bk_zone["upper"] * 100, 2
                    ),
                    "rs_vs_spy":          rs_vs_spy,
                    "rs_score":           round(rs_score, 4),
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
                    "weekly_confirmed":    _weekly_confirmed(df),
                    "atr_compressed":      False,
                    "is_minervini_dryup":  _has_vol_dryup(volume, avg_vol),
                    "rs_improving":        rs_improving,
                    "rs_near_high":        rs_near_high,
                    "rs_acceleration":     rs_acceleration,
                    "tight_range_5d":      tight_range_5d,
                }

        # ── Path B debug: no vol surge or no cleared resistance zone ─────────
        if debug and not confirmed_breakout:
            if not resistance_zones:
                print(
                    f"Engine 2 VCP: REJECTED - Breakout volume {volume_ratio:.1f}x "
                    f"(required: ≥1.5x 50d SMA) — no resistance zones available"
                )
            elif not is_vol_surge:
                print(
                    f"Engine 2 VCP: REJECTED - Breakout volume {volume_ratio:.1f}x "
                    f"(required: ≥1.5x 50d SMA)"
                )

        # ── PATH C — Trendline Breakout ────────────────────────────────────
        # Check if price broke above a descending trendline with volume
        trendline_result = detect_trendline(ticker, df)
        is_trendline_breakout = False
        trendline_data = None

        desc_tl = trendline_result.get("descending") if trendline_result else None
        if desc_tl is not None and desc_tl.get("series"):
            tl_today = desc_tl["series"][-1]["value"]
            # Breakout: close above descending trendline + vol surge ≥100% + trend filter (already checked)
            # Cap: price must be within 0-3% above the line (reject stale/extended breakouts)
            if tl_today > 0:
                pct_above_tl = (lc - tl_today) / tl_today
                if 0 < pct_above_tl <= 0.03 and lvol >= 1.0 * avg_vol:
                    is_trendline_breakout = True
                    trendline_data = trendline_result

        if is_trendline_breakout and trendline_data is not None and contraction_count >= VCP_MIN_CONTRACTIONS_RELAXED:
            entry      = round(lh * 1.001, 2)
            stop_base  = min(ll, 0.98 * desc_tl["series"][-1]["value"])
            stop_loss  = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
            risk       = entry - stop_loss
            if risk > 0 and risk <= entry * 0.15:
                take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)
                return {
                    "ticker":             ticker,
                    "setup_type":         "VCP",
                    "entry":              entry,
                    "stop_loss":          stop_loss,
                    "take_profit":        take_profit,
                    "rr": actual_rr,
                    "setup_date":         str(data.index[-1].date()),
                    "is_breakout":        True,
                    "is_vol_surge":       lvol >= 1.5 * avg_vol,
                    "volume_ratio":       volume_ratio,
                    "resistance_level":   None,
                    "breakout_pct":       None,
                    "rs_vs_spy":          rs_vs_spy,
                    "rs_score":           round(rs_score, 4),
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
                    "weekly_confirmed":    _weekly_confirmed(df),
                    "atr_compressed":      False,
                    "is_minervini_dryup":  _has_vol_dryup(volume, avg_vol),
                    "rs_improving":        rs_improving,
                    "rs_near_high":        rs_near_high,
                    "rs_acceleration":     rs_acceleration,
                    "tight_range_5d":      tight_range_5d,
                }

        # ── Path C debug: no valid descending trendline detected ─────────────
        if debug and not is_trendline_breakout:
            if trendline_result is None or trendline_result.get("descending") is None:
                print(
                    f"Engine 2 VCP: REJECTED - No valid descending trendline detected"
                )

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
                lvol >= 1.15 * avg_vol
            )

            if is_kde_breakout and contraction_count >= VCP_MIN_CONTRACTIONS_RELAXED:
                entry      = round(lh * 1.001, 2)
                stop_base  = min(ll, nearest_res_above["lower"])
                stop_loss  = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
                risk       = entry - stop_loss

                if risk > 0 and risk <= entry * 0.15:
                    take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)
                    return {
                        "ticker":             ticker,
                        "setup_type":         "VCP",
                        "entry":              entry,
                        "stop_loss":          stop_loss,
                        "take_profit":        take_profit,
                        "rr": actual_rr,
                        "setup_date":         str(data.index[-1].date()),
                        "is_breakout":        True,
                        "is_vol_surge":       lvol >= 1.5 * avg_vol,
                        "volume_ratio":       volume_ratio,
                        "resistance_level":   nearest_res_above["level"],
                        "breakout_pct":       round(pct_above_upper * 100, 2),
                        "rs_vs_spy":          rs_vs_spy,
                        "rs_score":           round(rs_score, 4),
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
                        "weekly_confirmed":    _weekly_confirmed(df),
                        "atr_compressed":      False,
                        "is_minervini_dryup":  _has_vol_dryup(volume, avg_vol),
                        "rs_improving":        rs_improving,
                        "rs_near_high":        rs_near_high,
                        "rs_acceleration":     rs_acceleration,
                        "tight_range_5d":      tight_range_5d,
                    }

        # ── Path D debug: no KDE breakout ────────────────────────────────────
        if debug and nearest_res_above is None:
            print(
                f"Engine 2 VCP: REJECTED - Not within 5% of any resistance zone "
                f"(Close {lc:.2f}, no nearby zone)"
            )

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
                stop_loss  = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
                risk       = entry - stop_loss

                if risk > 0 and risk <= entry * 0.15:
                    take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)
                    return {
                        "ticker":             ticker,
                        "setup_type":         "VCP",
                        "entry":              entry,
                        "stop_loss":          stop_loss,
                        "take_profit":        take_profit,
                        "rr": actual_rr,
                        "setup_date":         str(data.index[-1].date()),
                        "is_breakout":        True,
                        "is_vol_surge":       False,
                        "volume_ratio":       volume_ratio,
                        "resistance_level":   nearest_res_above["level"],
                        "breakout_pct":       round(pct_below_upper * 100, 2),
                        "rs_vs_spy":          rs_vs_spy,
                        "rs_score":           round(rs_score, 4),
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
                        "weekly_confirmed":    _weekly_confirmed(df),
                        "atr_compressed":      False,
                        "is_minervini_dryup":  _has_vol_dryup(volume, avg_vol),
                        "rs_improving":        rs_improving,
                        "rs_near_high":        rs_near_high,
                        "rs_acceleration":     rs_acceleration,
                        "tight_range_5d":      tight_range_5d,
                    }

        # ── PATH A — DRY (Coiled Spring) ──────────────────────────────────
        # Path A (coiled spring below resistance) requires the FULL trend template:
        # price must be above the 200 SMA (confirmed Stage 2 uptrend).
        if not (lc > l200):
            if debug:
                l200_str = f"{l200:.2f}" if not np.isnan(l200) else "N/A (insufficient data)"
                print(
                    f"Engine 2 VCP: REJECTED - Trend filter failed "
                    f"(Close {lc:.2f} below SMA200 {l200_str} — Path A requires Stage 2)"
                )
            return None

        # ── A2. True Range contraction ────────────────────────────────────
        # (tr already computed above for contraction counting)
        if len(tr) < 26:
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - No volume dry-up "
                    f"(insufficient TR data: {len(tr)} bars, need 26)"
                )
            return None

        last5_tr_val = tr.iloc[-5:].mean()
        prev20_tr_val = tr.iloc[-25:-5].mean()
        last5_tr  = float(last5_tr_val.item() if hasattr(last5_tr_val, 'item') else last5_tr_val)
        prev20_tr = float(prev20_tr_val.item() if hasattr(prev20_tr_val, 'item') else prev20_tr_val)
        if last5_tr >= prev20_tr:
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - No volume dry-up "
                    f"(TR not contracting: last5={last5_tr:.4f} >= prev20={prev20_tr:.4f})"
                )
            return None

        # A2b. ATR contraction confirmation (Task 13)
        # latr (already extracted and NaN-checked above) is today's ATR value.
        atr20_clean = atr14.dropna()
        atr_compressed = False
        if len(atr20_clean) >= 20:
            atr20_avg = float(atr20_clean.iloc[-20:].mean())
            atr_compressed = latr < atr20_avg * VCP_ATR_CONTRACTION_THRESHOLD
            if not atr_compressed:
                if debug:
                    print(
                        f"Engine 2 VCP: REJECTED - ATR not compressed "
                        f"(ATR={latr:.4f}, ATR20avg={atr20_avg:.4f}, "
                        f"threshold={atr20_avg * VCP_ATR_CONTRACTION_THRESHOLD:.4f})"
                    )
                return None
        # Note: atr20_clean always has ≥46 values when len(data)≥60, so the else
        # branch is unreachable in production — atr_compressed is always set above.

        # Progressive contraction structure gate (Path A requires >=3 progressive contractions)
        if not (contraction_count >= VCP_MIN_CONTRACTIONS_STRICT and is_progressive):
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - Path A requires {VCP_MIN_CONTRACTIONS_STRICT} "
                    f"progressive contractions "
                    f"(got {contraction_count}, is_progressive={is_progressive})"
                )
            return None

        # ── A3. U-shape parabolic check ───────────────────────────────────
        lb      = min(15, len(close) - 5)
        recent  = close.values[-lb:].astype(float)
        if np.any(np.isnan(recent)):
            return None

        _cf_key = (ticker, str(data.index[-1].date()), lb)
        if _cf_key in _CURVE_FIT_CACHE:
            is_u = _CURVE_FIT_CACHE[_cf_key]
        else:
            xv             = np.arange(lb, dtype=float)
            mean_p, std_p  = recent.mean(), recent.std()
            is_u = False
            if std_p >= 1e-8:
                yn = (recent - mean_p) / std_p
                try:
                    popt, _ = curve_fit(_parabola, xv, yn, maxfev=2000)
                    a, b, _ = popt
                    vertex_x = -b / (2.0 * a) if abs(a) > 1e-8 else -1.0
                    is_u = a > 0.005 and 0.0 <= vertex_x <= float(lb)
                except Exception:
                    is_u = False
            _CURVE_FIT_CACHE[_cf_key] = is_u

        if not is_u:
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - No volume dry-up "
                    f"(U-shape parabola check failed — no coiled base detected)"
                )
            return None

        # ── A4. Volume dry-up ─────────────────────────────────────────────
        # Two-part gate:
        #   (a) 3-day average below the 50-day average (quiet overall)
        #   (b) At least one day in the last 10 bars had genuine evaporation
        #       (< 50 % of the 50-day average) — eliminates mild drift-down
        last3_vol_val = volume.iloc[-3:].mean()
        last3_vol = float(last3_vol_val.item() if hasattr(last3_vol_val, 'item') else last3_vol_val)
        # Task 14: Minervini strict dry-up — any bar in last 10 < 50% avg vol
        is_minervini_dryup = _has_vol_dryup(volume, avg_vol)
        is_dry = last3_vol < avg_vol and is_minervini_dryup

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
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - Not within 5% of any resistance zone "
                    f"(Path A: no KDE zone within 5% above Close {lc:.2f})"
                )
            return None

        # Volume gate: in dry-up phase below resistance OR already breaking
        at_breakout = lc >= nearest_res["lower"] and is_vol_surge
        in_dry_up   = lc <  nearest_res["lower"] and is_dry

        if not (at_breakout or in_dry_up):
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - No volume dry-up "
                    f"(last3_vol={last3_vol:.0f} vs avg_vol={avg_vol:.0f}, "
                    f"is_dry={is_dry}, is_vol_surge={is_vol_surge})"
                )
            return None

        # ── Risk math ─────────────────────────────────────────────────────
        entry      = round(lh * 1.001, 2)
        stop_base  = min(ll, nearest_res["lower"])
        stop_loss  = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
        risk       = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        return {
            "ticker":             ticker,
            "setup_type":         "VCP",
            "entry":              entry,
            "stop_loss":          stop_loss,
            "take_profit":        take_profit,
            "rr": actual_rr,
            "setup_date":         str(data.index[-1].date()),
            "is_breakout":        at_breakout,
            "is_vol_surge":       is_vol_surge,
            "volume_ratio":       volume_ratio,
            "resistance_level":   nearest_res["level"],
            "breakout_pct":       None,
            "rs_vs_spy":          rs_vs_spy,
            "rs_score":           round(rs_score, 4),
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
            "weekly_confirmed":    _weekly_confirmed(df),
            "atr_compressed":      atr_compressed,
            "is_minervini_dryup":  is_minervini_dryup,
            "rs_improving":        rs_improving,
            "rs_near_high":        rs_near_high,
            "rs_acceleration":     rs_acceleration,
            "tight_range_5d":      tight_range_5d,
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
