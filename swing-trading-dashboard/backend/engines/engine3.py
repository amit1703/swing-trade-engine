"""
Engine 3: Tactical Pullback Scanner — The 8/20 Value Zone
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detects high-quality pullbacks to the 8/20 EMA value zone that
coincide with an Engine 1 support zone, confirming a pin-bar
rejection AND a CCI momentum hook.

Filter chain (all must pass):
  1. Trend        : 8 EMA > 20 EMA  AND  Close > 50 SMA
  2. Value Zone   : Daily Low penetrates 8 EMA or 20 EMA (enters value zone)
  3. Support Touch: Low touches an Engine 1 SUPPORT zone
  4. Rejection    : Daily Close ≥ 20 EMA (pin bar — closed back above)
  5. CCI Hook     : CCI[yesterday] < −50  AND  CCI[today] > CCI[yesterday]
                    (momentum turning from oversold — constant: CCI_STRICT_FLOOR)

Risk Math:
  Entry      = High of setup candle + 0.1 %
  Stop Loss  = min(Low, zone_lower) − ATR_STOP_MULTIPLIER × ATR  (currently 0.8)
  Take Profit= Entry + 2 × Risk   (1:2 R:R)
"""

import os
import sys
from types import SimpleNamespace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import ema as _ema, sma as _sma, atr as _atr, cci as _cci
from constants import CCI_STRICT_FLOOR, CCI_RLX_FLOOR, TARGET_RR, TRENDLINE_TOUCH_TOLERANCE_PCT, ATR_STOP_MULTIPLIER
from zone_utils import nearest_resistance_target

# RS gate: reject stocks that persistently underperform SPY.
# Loose floor allows flat-vs-SPY stocks to qualify. Patchable by Optuna.
RS_REJECT_THRESHOLD = -0.01219   # Optuna v4 best (trial #951); was -0.034124 (v3)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _check_ascending_trendline_touch(
    low_price: float,
    trendline_dict: Optional[Dict],
) -> tuple:
    """
    Check if low touches ascending trendline (within 0.8%).

    Args:
        low_price: Current bar's low
        trendline_dict: Ascending trendline dict from detect_trendline()

    Returns:
        (touched: bool, support_level: float)
    """
    if trendline_dict is None or "series" not in trendline_dict:
        return False, 0.0

    if not trendline_dict["series"]:
        return False, 0.0

    # Get today's value from the series
    tl_value = trendline_dict["series"][-1]["value"]

    # Check if low is within TRENDLINE_TOUCH_TOLERANCE_PCT of trendline
    if tl_value > 0:
        tolerance = tl_value * TRENDLINE_TOUCH_TOLERANCE_PCT
        if abs(low_price - tl_value) <= tolerance:
            return True, tl_value

    return False, 0.0


def _find_structural_support(
    ll: float,
    lc: float,
    sr_zones: List[Dict],
    trendline: Optional[Dict],
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    avg_vol: float,
) -> Optional[Dict]:
    """
    Find the nearest structural support for a pullback.

    Checks four layers in priority order:
      1. KDE SUPPORT zone (Engine 1 horizontal zone)
      2. Prior consolidation low (recent swing low where price bounced ≥3 bars)
      3. High-volume demand zone (reversal bar with volume ≥150% avg)
      4. Ascending trendline touch

    Returns a dict with keys: level, lower, upper, source
    Returns None if no structural support found.
    """
    ZONE_TOLERANCE = 0.025  # 2.5% zone width tolerance

    # ── 1. KDE support zone ───────────────────────────────────────────────────
    support_zones = [z for z in sr_zones if z.get("type") == "SUPPORT"]
    for z in support_zones:
        low_in_zone   = z["lower"] * (1 - ZONE_TOLERANCE) <= ll <= z["upper"] * (1 + ZONE_TOLERANCE)
        close_in_zone = z["lower"] <= lc <= z["upper"]
        if low_in_zone or close_in_zone:
            return {
                "level":  z["level"],
                "lower":  z["lower"],
                "upper":  z["upper"],
                "source": "KDE",
            }

    # ── 2. Prior consolidation low ────────────────────────────────────────────
    if len(low) >= 15:
        low_vals = low.values[-60:] if len(low) >= 60 else low.values
        for i in range(len(low_vals) - 8, 3, -1):
            candidate = float(low_vals[i])
            if candidate <= 0:
                continue
            # Shallow 3-bar pivot: candidate must be ≤ min of 3 bars before AND after.
            # Not a full 5-bar pivot definition — the 3% proximity + bounce guards compensate.
            if not (candidate <= min(low_vals[max(0, i-3):i])
                    and candidate <= min(low_vals[i+1:min(len(low_vals), i+4)])):
                continue
            # Price must have bounced: at least 3 of the next 5 bars closed above candidate
            bounced = sum(
                1 for j in range(i + 1, min(len(low_vals), i + 6))
                if float(low_vals[j]) > candidate * 1.005
            )
            if bounced < 3:
                continue
            # Candidate must be within 3% of current bar's low
            if abs(ll - candidate) / candidate > 0.03:
                continue
            return {
                "level":  round(candidate, 4),
                "lower":  round(candidate * 0.99, 4),
                "upper":  round(candidate * 1.01, 4),
                "source": "CONSOLIDATION_LOW",
            }

    # ── 3. High-volume demand zone ────────────────────────────────────────────
    if avg_vol > 0 and len(close) >= 10 and len(low) >= 10:
        lookback = min(30, len(close))
        close_vals = close.values[-lookback:]
        low_vals   = low.values[-lookback:]
        high_vals  = high.values[-lookback:]
        vol_vals   = volume.values[-lookback:] if len(volume) >= lookback else None

        if vol_vals is not None:
            for i in range(len(close_vals) - 2, 1, -1):  # skip last bar (current)
                bar_vol = float(vol_vals[i])
                if bar_vol < 1.5 * avg_vol:
                    continue
                bar_close = float(close_vals[i])
                bar_low   = float(low_vals[i])
                bar_high  = float(high_vals[i])
                bar_open  = float(close_vals[i - 1])  # approximate open with prev close
                if bar_close <= bar_open:
                    continue
                if abs(ll - bar_low) / bar_low > 0.03:
                    continue
                # Price must have held above this zone since
                held = all(
                    float(low_vals[j]) >= bar_low * 0.98
                    for j in range(i + 1, len(low_vals))
                )
                if not held:
                    continue
                return {
                    "level":  round(bar_low, 4),
                    "lower":  round(bar_low * 0.99, 4),
                    "upper":  round(bar_high, 4),
                    "source": "DEMAND_ZONE",
                }

    # ── 4. Ascending trendline ────────────────────────────────────────────────
    if trendline is not None:
        ascending_tl = trendline.get("ascending")
        if ascending_tl is not None:
            touched, tl_value = _check_ascending_trendline_touch(ll, ascending_tl)
            if touched and tl_value > 0:
                return {
                    "level":  round(tl_value, 4),
                    "lower":  round(tl_value * 0.99, 4),
                    "upper":  round(tl_value * 1.01, 4),
                    "source": "ASCENDING_TDL",
                }

    return None


def scan_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
    debug: bool = False,
) -> Optional[Dict]:
    """
    Returns a setup dict if a valid tactical pullback is found, else None.
    Checks both horizontal support zones AND ascending trendlines.
    """
    try:
        ind = _prepare_indicators(ticker, df)
        if ind is None:
            return None

        data = ind.data
        lc, lh, ll   = ind.lc, ind.lh, ind.ll
        l8, l20, l50 = ind.l8, ind.l20, ind.l50
        latr         = ind.latr
        cci_today    = ind.cci_today
        cci_prev     = ind.cci_prev

        # ── 0. RS quality gate ────────────────────────────────────────────
        # Require stock not to be a persistent underperformer vs SPY.
        # Loose floor (RS_REJECT_THRESHOLD) allows stocks that are flat vs SPY to qualify.
        if rs_score < RS_REJECT_THRESHOLD:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < {RS_REJECT_THRESHOLD:.2f} — persistent underperformer)"
                )
            return None

        # ── 1. Trend filter ───────────────────────────────────────────────
        if not (l8 > l20 and lc > l50):
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - Trend filter failed "
                    f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50 {l50:.2f})"
                )
            return None

        # ── 2. Value zone retest ──────────────────────────────────────────
        # Low must penetrate 8 EMA or 20 EMA to be "in the value zone"
        if not (ll <= l8 or ll <= l20):
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - Low {ll:.2f} not in value zone "
                    f"(EMA8 {l8:.2f}, EMA20 {l20:.2f})"
                )
            return None

        # ── 3. Structural support (KDE zone / consolidation low / demand zone / TDL) ──
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup,
        )
        if nearest_sup is None:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - No structural support "
                    f"(no KDE zone, consolidation low, demand zone, or ascending TDL near low={ll:.2f})"
                )
            return None

        is_ascending_tdl = nearest_sup["source"] == "ASCENDING_TDL"

        # ── 4. Rejection (pin bar) ────────────────────────────────────────
        # Close must be at or above 20 EMA — price closed back into the trend
        if lc < l20:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - No pin bar "
                    f"(Close {lc:.2f} < EMA20 {l20:.2f})"
                )
            return None

        # ── 5. CCI momentum hook ─────────────────────────────────────────
        # CCI must have dipped below -50 (oversold) and be turning up (hook)
        if not (cci_prev < CCI_STRICT_FLOOR and cci_today > cci_prev):
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - CCI hook failed "
                    f"(yesterday: {cci_prev:.1f}, today: {cci_today:.1f}, "
                    f"required: < {CCI_STRICT_FLOOR:.0f} then rising)"
                )
            return None

        # ── Risk math ────────────────────────────────────────────────────
        entry = round(lh * 1.001, 2)

        # Stop: min(candle low, zone bottom) − ATR_STOP_MULTIPLIER × ATR
        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)

        risk = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        return {
            "ticker": ticker,
            "setup_type": "PULLBACK",
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": actual_rr,
            "setup_date": str(data.index[-1].date()),
            "cci_today": round(cci_today, 2),
            "cci_yesterday": round(cci_prev, 2),
            "support_level": nearest_sup["level"],
            "support_source": nearest_sup["source"],
            "ema8": round(l8, 2),
            "ema20": round(l20, 2),
            "is_ascending_tdl": is_ascending_tdl,
        }

    except Exception as exc:  # noqa: BLE001
        print(f"[Engine3] {ticker}: {exc}")
        return None


def scan_relaxed_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
    debug: bool = False,
) -> Optional[Dict]:
    """
    Relaxed tactical pullback: triggers when no strict pullback found.
    Structural support broadened to 4 layers (KDE, consolidation low, demand zone, ascending TDL).

    Criteria (upgraded):
    1. Trend   : 8 EMA > 20 EMA  AND  Close > SMA50 × 0.97 (allows SMA50 test setups)
    2. Value zone: Low penetrates EMA8/EMA20  OR  Close within 4% of EMA8/EMA20
    3. CCI hook: CCI[yesterday] < CCI_RLX_FLOOR (-20) AND CCI[today] > CCI[yesterday]
    4. Volume  : Computed for scoring only — no hard gate (allows shakeout reversals)
    5. Structural support: low/close touches KDE zone / consolidation low /
       demand zone / ascending trendline via _find_structural_support() — REQUIRED.

    Flags ascending trendline touches as is_ascending_tdl for display purposes.
    """
    try:
        ind = _prepare_indicators(ticker, df)
        if ind is None:
            return None

        data   = ind.data
        volume = ind.volume
        lc, lh, ll   = ind.lc, ind.lh, ind.ll
        l8, l20, l50 = ind.l8, ind.l20, ind.l50
        latr         = ind.latr
        cci_today    = ind.cci_today
        cci_prev     = ind.cci_prev

        # ── 0. RS quality gate ────────────────────────────────────────────
        if rs_score < RS_REJECT_THRESHOLD:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < {RS_REJECT_THRESHOLD:.2f} — persistent underperformer)"
                )
            return None

        # ── 1. Trend filter (relaxed) ─────────────────────────────────────
        # Require short-term trend (8 EMA > 20 EMA) AND close within 3% of
        # SMA50 (allows SMA50 test setups where stock has pulled back to the MA).
        if not (l8 > l20 and lc > l50 * 0.97):
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Trend filter failed "
                    f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50×0.97 {l50*0.97:.2f})"
                )
            return None

        # ── 2. Value Zone: low penetrates EMA8/20 OR close within 4% ────
        # Two ways to qualify: classic value-zone penetration (strict-style)
        # or proximity (close enough to count as a test of the zone).
        penetrates = (ll <= l8 or ll <= l20)
        dist_to_8  = abs(lc - l8)  / l8  if l8  > 0 else float("inf")
        dist_to_20 = abs(lc - l20) / l20 if l20 > 0 else float("inf")
        near_ema   = (dist_to_8 <= 0.04 or dist_to_20 <= 0.04)

        if not (penetrates or near_ema):
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Not in value zone "
                    f"(Close {lc:.2f}, Low {ll:.2f}, EMA8 {l8:.2f} [{dist_to_8*100:.1f}%], "
                    f"EMA20 {l20:.2f} [{dist_to_20*100:.1f}%], required: penetration OR ≤4%)"
                )
            return None

        # ── 3. CCI Early Signal: turning from oversold ───────────────────
        # Floor raised from -30 to CCI_RLX_FLOOR (-20) to catch earlier-stage
        # pullbacks before they reach deeply oversold territory.
        cci_turning = cci_today > cci_prev and cci_prev < CCI_RLX_FLOOR
        if not cci_turning:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - CCI hook failed "
                    f"(yesterday: {cci_prev:.1f}, today: {cci_today:.1f}, "
                    f"required: < {CCI_RLX_FLOOR:.0f} and today rising)"
                )
            return None

        # ── 4. Volume: compute for scoring, no gate ───────────────────────
        # Dry-up is a quality signal (captured in scoring.py), not a hard filter.
        # This allows shakeout reversals (elevated volume finding support) to qualify.
        vol_sma50 = volume.rolling(50).mean()
        vsm_val = vol_sma50.iloc[-1]
        vsm_scalar = float(vsm_val.item() if hasattr(vsm_val, 'item') else vsm_val)
        if pd.isna(vsm_scalar) or vsm_scalar <= 0:
            return None
        avg_vol = vsm_scalar

        # ── Structural support (KDE zone / consolidation low / demand zone / TDL) ──
        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol,
        )
        if nearest_sup is None:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - No structural support "
                    f"(no KDE zone, consolidation low, demand zone, or ascending TDL near low={ll:.2f})"
                )
            return None

        is_ascending_tdl = nearest_sup["source"] == "ASCENDING_TDL"
        support_level = nearest_sup["level"]

        # ── Risk Math ─────────────────────────────────────────────────────
        entry = round(lh * 1.001, 2)

        # Validate support level is actually below current price
        if support_level >= lc:
            return None

        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
        risk = entry - stop_loss

        if risk <= 0 or risk > entry * 0.15:
            return None

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        return {
            "ticker": ticker,
            "setup_type": "PULLBACK",
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": actual_rr,
            "setup_date": str(data.index[-1].date()),
            "cci_today": round(cci_today, 2),
            "cci_yesterday": round(cci_prev, 2),
            "support_level": support_level,
            "support_source": nearest_sup["source"],
            "ema8": round(l8, 2),
            "ema20": round(l20, 2),
            "is_relaxed": True,
            "is_ascending_tdl": is_ascending_tdl,
        }

    except Exception as exc:  # noqa: BLE001
        print(f"[scan_relaxed_pullback] {ticker}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prep(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    required = {"High", "Low"}
    if not required.issubset(data.columns):
        return None
    return data


def _adj_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"


def _prepare_indicators(
    ticker: str,
    df: pd.DataFrame,
) -> Optional[SimpleNamespace]:
    """
    Shared indicator preparation used by both scan functions.

    Runs _prep(), computes EMA8/EMA20/SMA50/ATR/CCI, extracts the 9 scalar
    floats for the last bar, and guards for NaN.

    Returns a SimpleNamespace with fields:
        data       – cleaned DataFrame (output of _prep)
        close, high, low, volume – raw Series
        lc, lh, ll               – last-bar scalars
        l8, l20, l50, latr       – indicator scalars
        cci_today, cci_prev      – CCI scalars
        ema8, ema20, sma50, atr14, cci20  – full indicator Series

    Returns None if data is insufficient or any key scalar is NaN.
    """
    data = _prep(df)
    if data is None or len(data) < 60:
        return None

    adj = _adj_col(data)
    close = data[adj]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"] if "Volume" in data.columns else pd.Series(
        np.zeros(len(data)), index=data.index
    )

    if close.dropna().shape[0] < 55:
        return None

    # Use pre-computed indicator columns when available (set by BacktestEngine
    # before the replay loop) to avoid O(n) recomputation on every bar.
    ema8  = data["_EMA8"]   if "_EMA8"  in data.columns else _ema(close, 8)
    ema20 = data["_EMA20"]  if "_EMA20" in data.columns else _ema(close, 20)
    sma50 = data["_SMA50"]  if "_SMA50" in data.columns else _sma(close, 50)
    cci20 = data["_CCI20"]  if "_CCI20" in data.columns else _cci(high, low, close, 20)
    atr14 = data["_ATR14"]  if "_ATR14" in data.columns else _atr(high, low, close, 14)

    cci_clean = cci20.dropna()
    if len(cci_clean) < 2:
        return None

    def _s(v):
        return float(v.item() if hasattr(v, 'item') else v)

    lc    = _s(close.iloc[-1])
    lh    = _s(high.iloc[-1])
    ll    = _s(low.iloc[-1])
    l8    = _s(ema8.iloc[-1])
    l20   = _s(ema20.iloc[-1])
    l50   = _s(sma50.iloc[-1])
    latr  = _s(atr14.iloc[-1])
    cci_today = _s(cci20.iloc[-1])
    cci_prev  = _s(cci20.iloc[-2])

    if any(np.isnan(v) for v in [lc, lh, ll, l8, l20, l50, latr, cci_today, cci_prev]):
        return None

    return SimpleNamespace(
        data=data,
        close=close, high=high, low=low, volume=volume,
        lc=lc, lh=lh, ll=ll,
        l8=l8, l20=l20, l50=l50, latr=latr,
        cci_today=cci_today, cci_prev=cci_prev,
        ema8=ema8, ema20=ema20, sma50=sma50, atr14=atr14, cci20=cci20,
    )


def scan_pullback_scored(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    params,                         # BacktestParams (duck-typed — no circular import)
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
) -> tuple:
    """
    Score-based pullback detector for use in BacktestEngine scored mode.

    Returns (setup_dict, score) or (None, 0.0).

    Hard gates (return (None, 0.0) immediately):
    - Insufficient bars / NaN indicators
    - Trend score == 0  (no uptrend whatsoever)
    - No structural support found
    - Risk math invalid (risk <= 0 or > 15% of entry)

    Additive scoring:
    +2  : 8 EMA > 20 EMA AND close > SMA50 (strong trend)
    +1  : 8 EMA > 20 EMA AND close > SMA50*0.97 (relaxed trend)
    +2  : low penetrates EMA8 or EMA20
    +1  : close within params.ema_distance of EMA8 or EMA20
    +2  : CCI_prev < -100 (deep oversold)
    +1  : CCI_prev < params.cci_threshold AND CCI turning up
    +2  : structural support found
    +tdl_bonus : support source is ASCENDING_TDL
    """
    try:
        ind = _prepare_indicators(ticker, df)
        if ind is None:
            return None, 0.0

        lc, lh, ll   = ind.lc, ind.lh, ind.ll
        l8, l20, l50 = ind.l8, ind.l20, ind.l50
        latr         = ind.latr
        cci_today    = ind.cci_today
        cci_prev     = ind.cci_prev
        data         = ind.data

        score = 0.0

        # ── Trend score ───────────────────────────────────────────────────────
        if l8 > l20 and lc > l50:
            score += 2.0
        elif l8 > l20 and lc > l50 * 0.97:
            score += 1.0
        else:
            return None, 0.0   # hard gate: no uptrend at all

        # ── Value zone score ──────────────────────────────────────────────────
        if ll <= l8 or ll <= l20:
            score += 2.0
        else:
            dist_to_8  = abs(lc - l8)  / l8  if l8  > 0 else float("inf")
            dist_to_20 = abs(lc - l20) / l20 if l20 > 0 else float("inf")
            if dist_to_8 <= params.ema_distance or dist_to_20 <= params.ema_distance:
                score += 1.0

        # ── CCI momentum score ────────────────────────────────────────────────
        if cci_prev < -100 and cci_today > cci_prev:
            score += 2.0
        elif cci_prev < params.cci_threshold and cci_today > cci_prev:
            score += 1.0

        # ── Structural support (hard gate + score) ────────────────────────────
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup,
        )
        if nearest_sup is None:
            return None, 0.0   # hard gate: no structural support

        score += 2.0

        if nearest_sup["source"] == "ASCENDING_TDL":
            score += params.tdl_bonus

        # ── Risk math ─────────────────────────────────────────────────────────
        entry = round(lh * 1.001, 2)

        if nearest_sup["level"] >= lc:
            return None, 0.0

        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
        risk      = entry - stop_loss

        if risk <= 0 or risk > entry * 0.15:
            return None, 0.0

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        setup = {
            "ticker":           ticker,
            "setup_type":       "PULLBACK",
            "entry":            entry,
            "stop_loss":        stop_loss,
            "take_profit":      take_profit,
            "rr":               actual_rr,
            "setup_date":       str(data.index[-1].date()),
            "cci_today":        round(cci_today, 2),
            "cci_yesterday":    round(cci_prev, 2),
            "support_level":    nearest_sup["level"],
            "support_source":   nearest_sup["source"],
            "ema8":             round(l8, 2),
            "ema20":            round(l20, 2),
            "is_ascending_tdl": nearest_sup["source"] == "ASCENDING_TDL",
            "pullback_score":   score,
            "is_scored_mode":   True,
        }
        return setup, score

    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("scan_pullback_scored %s: %s", ticker, exc)
        return None, 0.0
