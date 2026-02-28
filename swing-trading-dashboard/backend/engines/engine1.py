"""
Engine 1: Battlefield Mapper — S/R Infrastructure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Method:
  1. Resample daily OHLCV → weekly.
  2. Collect weekly closes + weekly pivot highs/lows.
  3. Apply Kernel Density Estimation (scipy gaussian_kde) on the
     combined price-point cloud to find institutional clustering.
  4. Extract local density peaks → significant S/R price levels.
  5. Convert each peak into a ZONE:  level ± (0.2 × Daily ATR).
  6. Merge peaks that are within 1 ATR of each other (remove duplicates).
  7. Classify zones as SUPPORT (below current price) or RESISTANCE (above).
"""

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.signal import argrelextrema, find_peaks
from scipy.stats import gaussian_kde

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr
from constants import (
    PIVOT_LOOKBACK_DAYS,
    PIVOT_MIN_SEPARATION_DAYS,
    PIVOT_MIN_TOUCHES,
    PIVOT_TOUCH_MARGIN_PCT,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_sr_zones(
    ticker: str,
    df: Optional[pd.DataFrame] = None,
) -> List[Dict]:
    """
    Parameters
    ----------
    ticker : str
        Stock ticker (used for fetching if df is None).
    df : pd.DataFrame, optional
        Pre-fetched daily OHLCV with columns including 'Adj Close',
        'High', 'Low'.  If None the function downloads 2 years of data.

    Returns
    -------
    list of dicts
        Each dict: {level, upper, lower, type, atr}
        Sorted ascending by level.
    """
    try:
        data = _load(ticker, df)
        if data is None or len(data) < 60:
            return []

        adj_col = _adj_col(data)
        atr_series = _atr(data["High"], data["Low"], data[adj_col], length=14)

        if atr_series.dropna().empty:
            return []

        atr_val = atr_series.dropna().iloc[-1]
        daily_atr = float(atr_val.item() if hasattr(atr_val, 'item') else atr_val)
        if daily_atr <= 0:
            return []

        zone_half_width = 0.2 * daily_atr

        # ── Weekly resample ──────────────────────────────────────────────
        weekly = (
            data.resample("W")
            .agg({adj_col: "last", "High": "max", "Low": "min"})
            .dropna()
        )

        if len(weekly) < 10:
            return []

        # ── Pivot highs / lows (adaptive window) ─────────────────────────
        order = max(2, len(weekly) // 20)
        hi = weekly["High"].values
        lo = weekly["Low"].values
        cl = weekly[adj_col].values

        ph_idx = argrelextrema(hi, np.greater_equal, order=order)[0]
        pl_idx = argrelextrema(lo, np.less_equal, order=order)[0]

        # Collect price points with their corresponding dates for recency weighting
        price_raw = np.concatenate([cl, hi[ph_idx], lo[pl_idx]])
        dates_raw = np.concatenate([
            weekly.index.values,
            weekly.index[ph_idx].values,
            weekly.index[pl_idx].values,
        ])

        # Filter out NaN/non-positive prices
        mask = ~np.isnan(price_raw) & (price_raw > 0)
        price_points = price_raw[mask]
        dates_valid = dates_raw[mask]

        if len(price_points) < 10:
            return []

        # ── Recency-weighted KDE ──────────────────────────────────────────────
        # Compute days ago for each price point
        today = dates_valid.max().astype('datetime64[D]')
        days_ago = (today - dates_valid.astype('datetime64[D]')).astype(float)
        days_ago = np.maximum(days_ago, 0.0)

        # Recency weight: 2.0 for ≤90 days, 1.0 for ≥365 days, linear interpolation between
        weights = np.where(
            days_ago <= 90,
            2.0,
            np.where(
                days_ago >= 365,
                1.0,
                2.0 - (days_ago - 90) / 275.0
            )
        )
        weights = np.maximum(weights, 0.1)  # Ensure all weights are positive

        # Dynamic bandwidth based on coefficient of variation
        cv = float(price_points.std() / price_points.mean()) if price_points.mean() > 0 else 0.05
        n = len(price_points)
        scott_factor = n ** (-1.0 / 5.0)          # Scott's rule
        bw_scale = max(0.4, min(1.2, cv / 0.05))  # 0.4 – 1.2 multiplier

        # KDE with recency weights
        kde = gaussian_kde(price_points, bw_method=scott_factor * bw_scale, weights=weights)
        p_min = price_points.min() * 0.98
        p_max = price_points.max() * 1.02
        x = np.linspace(p_min, p_max, 600)
        density = kde(x)

        # Peak detection with find_peaks (lower prominence threshold than argrelextrema)
        prominence_threshold = np.percentile(density, 5)
        min_dist = max(4, int(len(x) * 0.008))
        peak_idx, _ = find_peaks(density, prominence=prominence_threshold, distance=min_dist)

        if len(peak_idx) == 0:
            return []

        # Get current price for proximity filtering
        cp_val = data[adj_col].iloc[-1]
        current_price = float(cp_val.item() if hasattr(cp_val, 'item') else cp_val)

        peak_prices = x[peak_idx]
        peak_densities = density[peak_idx]

        # Always include peaks within 3% of current price; also include top 70% by density
        pct_diff = np.abs(peak_prices - current_price) / current_price
        is_proximity = pct_diff <= 0.03

        threshold = np.percentile(peak_densities, 30)
        keep_mask = (peak_densities >= threshold) | is_proximity
        peak_prices = peak_prices[keep_mask]
        is_proximity_filtered = is_proximity[keep_mask]

        # ── Merge nearby peaks (within 1 ATR) ────────────────────────────
        merged: List[float] = []
        cluster: List[float] = [float(np.sort(peak_prices)[0])]
        for p in np.sort(peak_prices)[1:]:
            if p - cluster[-1] < daily_atr:
                cluster.append(p)
            else:
                merged.append(float(np.mean(cluster)))
                cluster = [p]
        merged.append(float(np.mean(cluster)))

        # ── Build zone dicts with is_primary flag ────────────────────────────
        zones: List[Dict] = []

        for i, level in enumerate(merged):
            zone_type = "RESISTANCE" if level > current_price else "SUPPORT"
            # Mark as primary if within 3% of current price
            pct_diff = abs(level - current_price) / current_price
            is_primary = pct_diff <= 0.03
            zones.append(
                {
                    "level": round(level, 2),
                    "upper": round(level + zone_half_width, 2),
                    "lower": round(level - zone_half_width, 2),
                    "type": zone_type,
                    "atr": round(daily_atr, 2),
                    "is_primary": is_primary,
                }
            )

        zones.sort(key=lambda z: z["level"])
        pivot_zones = _find_pivot_resistance(data, daily_atr, current_price)
        zones.extend(pivot_zones)
        zones.sort(key=lambda z: z["level"])
        return zones

    except Exception as exc:  # noqa: BLE001
        print(f"[Engine1] {ticker}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(ticker: str, df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is not None:
        data = df.copy()
    else:
        data = yf.download(
            ticker,
            period="2y",
            interval="1d",
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )

    if data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return data


def _adj_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"


def _find_pivot_resistance(
    df: pd.DataFrame, daily_atr: float, current_price: float
) -> List[Dict]:
    """
    Find pivot-high resistance zones from the last PIVOT_LOOKBACK_DAYS trading days.

    Uses argrelextrema on daily High prices (order=3) to find local wick maxima,
    then clusters matching pivots — within PIVOT_TOUCH_MARGIN_PCT of each other AND
    at least PIVOT_MIN_SEPARATION_DAYS bars apart — via Union-Find.  Clusters with
    >= PIVOT_MIN_TOUCHES members become zones.
    """
    lookback = df.tail(PIVOT_LOOKBACK_DAYS)
    if len(lookback) < 10:
        return []

    highs = lookback["High"].values.astype(float)
    pivot_idx_arr = argrelextrema(highs, np.greater, order=3)[0]

    if len(pivot_idx_arr) < PIVOT_MIN_TOUCHES:
        return []

    pivot_highs = highs[pivot_idx_arr]
    n = len(pivot_idx_arr)

    # ── Union-Find ──────────────────────────────────────────────────────────
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        parent[_find(a)] = _find(b)

    for i in range(n):
        for j in range(i + 1, n):
            sep = int(pivot_idx_arr[j]) - int(pivot_idx_arr[i])
            if sep < PIVOT_MIN_SEPARATION_DAYS:
                continue
            h_max = max(pivot_highs[i], pivot_highs[j])
            if h_max == 0:
                continue
            if abs(pivot_highs[i] - pivot_highs[j]) / h_max <= PIVOT_TOUCH_MARGIN_PCT:
                _union(i, j)

    # ── Group by root ───────────────────────────────────────────────────────
    clusters: dict = {}
    for i in range(n):
        root = _find(i)
        clusters.setdefault(root, []).append(i)

    zones: List[Dict] = []
    for members in clusters.values():
        if len(members) < PIVOT_MIN_TOUCHES:
            continue
        cluster_highs = [float(pivot_highs[m]) for m in members]
        level = float(np.mean(cluster_highs))
        upper = float(max(cluster_highs)) + 0.1 * daily_atr
        lower = float(min(cluster_highs)) - 0.1 * daily_atr
        zone_type = "RESISTANCE" if level > current_price else "SUPPORT"
        pct_diff = abs(level - current_price) / current_price if current_price > 0 else 1.0
        zones.append(
            {
                "level": round(level, 2),
                "upper": round(upper, 2),
                "lower": round(lower, 2),
                "type": zone_type,
                "atr": round(daily_atr, 2),
                "is_primary": pct_diff <= 0.03,
                "source": "pivot",
            }
        )

    return zones
