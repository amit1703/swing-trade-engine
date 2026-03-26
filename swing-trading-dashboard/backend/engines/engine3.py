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
from constants import CCI_STRICT_FLOOR, CCI_RLX_FLOOR, TARGET_RR, TRENDLINE_TOUCH_TOLERANCE_PCT, ATR_STOP_MULTIPLIER, PB_ATR_STOP_MULTIPLIER, PB_MIN_TREND_BARS, SUPPORT_MAX_EXTENSION_ATR, BACKTEST_RS_THRESHOLD_DEFAULT
from zone_utils import nearest_resistance_target

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
    latr: float = 0.0,
    sma200: float = 0.0,
    ema20: float = 0.0,
    ema50: float = 0.0,
    regime: str = "",
    rs_rank: float = 0.0,
    trend_bars: int = 0,
) -> Optional[Dict]:
    """
    Find the nearest structural support for a pullback.

    Checks up to five layers in priority order:
      1. KDE SUPPORT zone   (Engine 1 horizontal density zone)
      2. Prior pivot low    (swing low where price bounced ≥3 bars)
      3. SMA200 touch       (200-day SMA acting as dynamic support)
      4. EMA50 dynamic support (Tier 2 — AGGRESSIVE + RS rank ≥ 85)
      5. EMA20 dynamic support (Tier 3 — AGGRESSIVE + RS rank ≥ 90 + trend ≥ 15 bars)

    Ascending trendlines and demand zones are intentionally excluded —
    they are subjective and produce too many false positives on choppy charts.

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

    # ── 2. Prior pivot low ────────────────────────────────────────────────────
    if len(low) >= 15:
        low_vals = low.values[-60:] if len(low) >= 60 else low.values
        for i in range(len(low_vals) - 8, 3, -1):
            candidate = float(low_vals[i])
            if candidate <= 0:
                continue
            # Shallow 3-bar pivot: candidate must be ≤ min of 3 bars before AND after.
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
            # Candidate must be within ATR-relative proximity of current bar's low.
            _prox_pct = max(0.03, 1.2 * latr / ll) if ll > 0 else 0.03
            if abs(ll - candidate) / candidate > _prox_pct:
                continue
            return {
                "level":  round(candidate, 4),
                "lower":  round(candidate * 0.99, 4),
                "upper":  round(candidate * 1.01, 4),
                "source": "CONSOLIDATION_LOW",
            }

    # ── 3. SMA200 touch ───────────────────────────────────────────────────────
    if sma200 > 0:
        _prox_pct = max(0.02, 1.0 * latr / sma200) if sma200 > 0 else 0.02
        if abs(ll - sma200) / sma200 <= _prox_pct and lc >= sma200 * 0.99:
            return {
                "level":  round(sma200, 4),
                "lower":  round(sma200 * 0.99, 4),
                "upper":  round(sma200 * 1.01, 4),
                "source": "SMA200",
            }

    # ── 4. EMA50 dynamic support (Tier 2 — conditional) ─────────────────────
    # Requires AGGRESSIVE regime + RS rank ≥ 85.
    # In a confirmed strong trend, the 50-period SMA acts as dynamic support.
    if regime == "AGGRESSIVE" and rs_rank >= 85 and ema50 > 0:
        if ll <= ema50 * 1.005 and lc >= ema50 * 0.985:
            return {"level": round(ema50, 4), "lower": round(ema50 * 0.985, 4),
                    "upper": round(ema50 * 1.005, 4), "source": "EMA50"}

    # ── 5. EMA20 dynamic support (Tier 3 — strict conditional) ───────────────
    # Requires AGGRESSIVE regime + RS rank ≥ 90 + trend ≥ 15 bars.
    # Close must fully recover to EMA20 (strict pin bar).
    if regime == "AGGRESSIVE" and rs_rank >= 90 and trend_bars >= 15 and ema20 > 0:
        if ll <= ema20 * 1.005 and lc >= ema20:
            return {"level": round(ema20, 4), "lower": round(ema20 * 0.99, 4),
                    "upper": round(ema20 * 1.005, 4), "source": "EMA20"}

    return None


def scan_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
    debug: bool = False,
    regime: str = "",
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
        # Loose floor (BACKTEST_RS_THRESHOLD_DEFAULT) allows stocks that are flat vs SPY to qualify.
        if rs_score < BACKTEST_RS_THRESHOLD_DEFAULT:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < {BACKTEST_RS_THRESHOLD_DEFAULT:.2f} — persistent underperformer)"
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

        # ── 1b. Trend duration gate ────────────────────────────────────────
        # Require EMA8>EMA20 AND Close>SMA50 for at least PB_MIN_TREND_BARS consecutive
        # bars before the signal bar — ensures pullback is into an established trend,
        # not a fresh or recovering turn.
        _e8   = ind.ema8.values[:-1]
        _e20  = ind.ema20.values[:-1]
        _c    = ind.close.values[:-1]
        _s50  = ind.sma50.values[:-1]
        _trend_mask = (_e8 > _e20) & (_c > _s50)
        _flipped = (~_trend_mask)[::-1]
        _trend_bars = int(np.argmax(_flipped)) if _flipped.any() else len(_flipped)
        if _trend_bars < PB_MIN_TREND_BARS:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - Trend too short "
                    f"({_trend_bars} bars < {PB_MIN_TREND_BARS} required)"
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

        # ── 3. Structural support (KDE / pivot low / SMA200) ─────────────
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup, latr,
            sma200=ind.l200,
            ema20=float(ind.ema20.iloc[-1]),
            ema50=float(ind.sma50.iloc[-1]),
            regime=regime,
            rs_rank=rs_score,
            trend_bars=_trend_bars,
        )
        if nearest_sup is not None and latr > 0:
            _ext_atr = (lc - nearest_sup["level"]) / latr
            if _ext_atr > SUPPORT_MAX_EXTENSION_ATR:
                nearest_sup = None   # too far from support — treat as no support found
            else:
                nearest_sup["extension_atr"] = round(_ext_atr, 2)
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

        # Stop: 1 ATR below candle low (PB_ATR_STOP_MULTIPLIER=1.0)
        # Using candle low only (not zone lower) to avoid excessively wide stops on EMA-test entries
        stop_loss = round(ll - PB_ATR_STOP_MULTIPLIER * latr, 2)

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
            "atr": round(latr, 4),
            "trend_bars":    _trend_bars,
            "extension_atr": nearest_sup.get("extension_atr", 0.0) if nearest_sup else 0.0,
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
    params=None,
    regime: str = "",
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
        if rs_score < BACKTEST_RS_THRESHOLD_DEFAULT:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < {BACKTEST_RS_THRESHOLD_DEFAULT:.2f} — persistent underperformer)"
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

        # ── 1b. Trend duration gate ────────────────────────────────────────
        _e8   = ind.ema8.values[:-1]
        _e20  = ind.ema20.values[:-1]
        _c    = ind.close.values[:-1]
        _s50  = ind.sma50.values[:-1]
        _trend_mask = (_e8 > _e20) & (_c > _s50)
        _flipped = (~_trend_mask)[::-1]
        _trend_bars = int(np.argmax(_flipped)) if _flipped.any() else len(_flipped)
        if _trend_bars < PB_MIN_TREND_BARS:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Trend too short "
                    f"({_trend_bars} bars < {PB_MIN_TREND_BARS} required)"
                )
            return None

        # ── 2. Value Zone: low penetrates EMA8/20 OR close within ATR proximity ──
        # Two ways to qualify: classic value-zone penetration (strict-style)
        # or proximity measured in ATR units — normalized for volatility.
        # 4% on a low-vol stock = many ATRs away; on a high-vol stock = barely 1 ATR.
        # ATR units give consistent meaning across different volatility regimes.
        EMA_DISTANCE_ATR = params.ema_distance if params is not None else 0.75
        penetrates   = (ll <= l8 or ll <= l20)
        atr_to_8     = abs(lc - l8)  / latr if latr > 0 else float("inf")
        atr_to_20    = abs(lc - l20) / latr if latr > 0 else float("inf")
        near_ema     = (atr_to_8 <= EMA_DISTANCE_ATR or atr_to_20 <= EMA_DISTANCE_ATR)

        if not (penetrates or near_ema):
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Not in value zone "
                    f"(Close {lc:.2f}, Low {ll:.2f}, ATR {latr:.2f}, "
                    f"EMA8 {l8:.2f} [{atr_to_8:.2f} ATR], "
                    f"EMA20 {l20:.2f} [{atr_to_20:.2f} ATR], required: penetration OR ≤{EMA_DISTANCE_ATR} ATR)"
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

        # ── Structural support (KDE zone / consolidation low / SMA200) ──
        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol, latr,
            sma200=ind.l200,
            ema20=float(ind.ema20.iloc[-1]),
            ema50=float(ind.sma50.iloc[-1]),
            regime=regime,
            rs_rank=rs_score,
            trend_bars=_trend_bars,
        )
        if nearest_sup is not None and latr > 0:
            _ext_atr = (lc - nearest_sup["level"]) / latr
            if _ext_atr > SUPPORT_MAX_EXTENSION_ATR:
                nearest_sup = None   # too far from support — treat as no support found
            else:
                nearest_sup["extension_atr"] = round(_ext_atr, 2)
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

        stop_loss = round(ll - PB_ATR_STOP_MULTIPLIER * latr, 2)
        risk = entry - stop_loss

        if risk <= 0 or risk > entry * 0.15:
            return None

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        return {
            "ticker":           ticker,
            "setup_type":       "PULLBACK",
            "entry":            entry,
            "stop_loss":        stop_loss,
            "take_profit":      take_profit,
            "rr":               actual_rr,
            "setup_date":       str(data.index[-1].date()),
            "cci_today":        round(cci_today, 2),
            "cci_yesterday":    round(cci_prev, 2),
            "support_level":    support_level,
            "support_source":   nearest_sup["source"],
            "ema8":             round(l8, 2),
            "ema20":            round(l20, 2),
            "is_relaxed":       True,
            "is_ascending_tdl": is_ascending_tdl,
            "atr":              round(latr, 4),
            "trend_bars":       _trend_bars,
            "extension_atr":    nearest_sup.get("extension_atr", 0.0) if nearest_sup else 0.0,
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
    ema8   = data["_EMA8"]    if "_EMA8"   in data.columns else _ema(close, 8)
    ema20  = data["_EMA20"]   if "_EMA20"  in data.columns else _ema(close, 20)
    sma50  = data["_SMA50"]   if "_SMA50"  in data.columns else _sma(close, 50)
    sma200 = data["_SMA200"]  if "_SMA200" in data.columns else _sma(close, 200)
    cci20  = data["_CCI20"]   if "_CCI20"  in data.columns else _cci(high, low, close, 20)
    atr14  = data["_ATR14"]   if "_ATR14"  in data.columns else _atr(high, low, close, 14)

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
    # SMA200 may be NaN on short histories — treat as 0.0 (SMA200 support layer disabled)
    _l200_raw = sma200.iloc[-1]
    l200 = _s(_l200_raw) if not (hasattr(_l200_raw, '__float__') and np.isnan(float(_l200_raw))) else 0.0

    if any(np.isnan(v) for v in [lc, lh, ll, l8, l20, l50, latr, cci_today, cci_prev]):
        return None

    return SimpleNamespace(
        data=data,
        close=close, high=high, low=low, volume=volume,
        lc=lc, lh=lh, ll=ll,
        l8=l8, l20=l20, l50=l50, l200=l200, latr=latr,
        cci_today=cci_today, cci_prev=cci_prev,
        ema8=ema8, ema20=ema20, sma50=sma50, sma200=sma200, atr14=atr14, cci20=cci20,
    )


def _find_support_below(
    lc: float,
    sr_zones: List[Dict],
    high: pd.Series,
    low: pd.Series,
    latr: float,
    max_atr: float,
) -> Optional[Dict]:
    """
    Find the nearest structural support BELOW current close within max_atr * latr.

    Three layers in priority order:
      1. KDE support zone (Engine 1 horizontal zone)
      2. Broken resistance pivot (prior confirmed high crossed above = breakout-retest)
      3. Prior consolidation low (swing low where price bounced)

    Unlike _find_structural_support (which requires the bar to already be touching
    a zone), this searches for levels the stock is approaching from above.
    Used exclusively by scan_pullback_approaching.
    """
    # 1. KDE support zones — find the closest one below current price
    for z in sorted(
        [z for z in sr_zones if z.get("type") == "SUPPORT"],
        key=lambda z: float(z.get("level", 0)),
        reverse=True,  # highest first = closest below
    ):
        level = float(z.get("level", 0))
        if level <= 0 or level >= lc:
            continue
        if latr > 0 and (lc - level) > max_atr * latr:
            continue
        return {
            "level": level,
            "lower": float(z.get("lower", level * 0.99)),
            "upper": float(z.get("upper", level * 1.01)),
            "source": "KDE",
        }

    # 2. Broken resistance pivot acting as support (breakout-retest setup).
    # Find confirmed prior highs (strength=5, last 6mo, 3% pullback confirmed)
    # that are now BELOW current price — price broke above them, now retesting.
    if len(high) >= 15:
        high_vals = high.values[-126:] if len(high) >= 126 else high.values
        hn = len(high_vals)
        strength = 5
        best_pivot: Optional[float] = None
        best_dist  = float("inf")
        for i in range(strength, hn - strength):
            h = float(high_vals[i])
            if h <= 0 or h >= lc:
                continue
            if latr > 0 and (lc - h) > max_atr * latr:
                continue
            # Structural pivot: highest of 11-bar window
            left_ok  = all(h >= float(high_vals[i - s]) for s in range(1, strength + 1))
            right_ok = all(h >= float(high_vals[i + s]) for s in range(1, strength + 1))
            if not (left_ok and right_ok):
                continue
            # Confirmed resistance: price dropped ≥3% after pivot
            look_end = min(hn, i + 11)
            post_low = min(float(high_vals[j]) for j in range(i + 1, look_end)) if i + 1 < look_end else h
            if h <= 0 or (h - post_low) / h < 0.03:
                continue
            dist = lc - h
            if dist < best_dist:
                best_dist  = dist
                best_pivot = round(h, 4)
        if best_pivot is not None:
            return {
                "level": best_pivot,
                "lower": round(best_pivot * 0.99, 4),
                "upper": round(best_pivot * 1.01, 4),
                "source": "PIVOT",
            }

    # 3. Prior consolidation lows (shallow 3-bar pivot lows below current price)
    if len(low) >= 10:
        low_vals = low.values[-60:] if len(low) >= 60 else low.values
        for i in range(len(low_vals) - 3, 3, -1):
            candidate = float(low_vals[i])
            if candidate <= 0 or candidate >= lc:
                continue
            if latr > 0 and (lc - candidate) > max_atr * latr:
                continue
            # Must be a local low (lower than 3 bars each side)
            if not (
                candidate <= min(low_vals[max(0, i - 3):i])
                and candidate <= min(low_vals[i + 1:min(len(low_vals), i + 4)])
            ):
                continue
            # Price bounced from this level at least 3 of next 5 bars
            bounced = sum(
                1 for j in range(i + 1, min(len(low_vals), i + 6))
                if float(low_vals[j]) > candidate * 1.005
            )
            if bounced < 3:
                continue
            return {
                "level": round(candidate, 4),
                "lower": round(candidate * 0.99, 4),
                "upper": round(candidate * 1.01, 4),
                "source": "CONSOLIDATION_LOW",
            }

    return None


def scan_pullback_approaching(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
    debug: bool = False,
) -> Optional[Dict]:
    """
    Watchlist: stock in uptrend pulling back toward a structural support.
    Fires before the pin bar / CCI hook — one move away from a PULLBACK setup.

    Conditions:
      - Trend: EMA8 > EMA20, close > SMA50 × 0.97 (relaxed, same as scan_relaxed_pullback)
      - CCI declining: cci_today < cci_prev  (pullback actively in progress)
      - RS not a persistent underperformer (same gate as engine 3)
      - Structural support within 2 ATR of current low
        (KDE zone / consolidation low / demand zone / ascending TDL)
      - Pin bar and CCI hook NOT required
    """
    APPROACH_ATR = 2.0   # within 2 ATR of structural support

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

        # RS gate (same as engine 3)
        if rs_score < BACKTEST_RS_THRESHOLD_DEFAULT:
            return None

        # Trend (relaxed — same as scan_relaxed_pullback)
        if not (l8 > l20 and lc > l50 * 0.97):
            return None

        # CCI must be declining — pullback is actively in progress
        if cci_today >= cci_prev:
            return None

        # Find structural support below current price (not yet reached).
        # _find_structural_support requires the bar to already BE at support,
        # so we use _find_support_below which searches for levels below current
        # close within APPROACH_ATR — the stock is heading there, not there yet.
        nearest_sup = _find_support_below(lc, sr_zones, ind.high, ind.low, latr, APPROACH_ATR)
        if nearest_sup is None:
            return None

        support_level = nearest_sup["level"]  # already guaranteed < lc

        entry     = round(lh * 1.001, 2)
        stop_loss = round(ll - PB_ATR_STOP_MULTIPLIER * latr, 2)
        risk      = entry - stop_loss
        if risk <= 0 or risk > entry * 0.15:
            return None

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        return {
            "ticker":           ticker,
            "setup_type":       "WATCHLIST",
            "watchlist_source": "PULLBACK",
            "entry":            entry,
            "stop_loss":        stop_loss,
            "take_profit":      take_profit,
            "rr":               actual_rr,
            "support_level":    support_level,
            "support_source":   nearest_sup["source"],
            "distance_pct":     round((lc - support_level) / lc * 100, 2),
            "ema8":             round(l8, 2),
            "ema20":            round(l20, 2),
            "cci_today":        round(cci_today, 2),
            "setup_date":       str(data.index[-1].date()),
            "atr":              round(latr, 4),
        }

    except Exception as exc:
        print(f"[Engine3 approaching] {ticker}: {exc}")
        return None


def scan_pullback_scored(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    params,                         # BacktestParams (duck-typed — no circular import)
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
    regime: str = "",
) -> tuple:
    """
    Score-based pullback detector for use in BacktestEngine scored mode.

    Returns (setup_dict, score) or (None, 0.0).

    Hard gates (return (None, 0.0) immediately):
    - Insufficient bars / NaN indicators
    - Trend score == 0  (no uptrend whatsoever)
    - Value zone not penetrated (low > EMA8 and low > EMA20)
    - No CCI momentum reversal (cci_prev >= params.cci_threshold OR not turning up)
    - No structural support found
    - Risk math invalid (risk <= 0 or > 15% of entry)

    Additive scoring:
    +2  : 8 EMA > 20 EMA AND close > SMA50 (strong trend)
    +1  : 8 EMA > 20 EMA AND close > SMA50*0.97 (relaxed trend)
    +2  : low penetrates EMA8 or EMA20
    +1  : close within params.ema_distance ATR of EMA8 or EMA20 (tight zone test)
    +2  : CCI_prev < -100 (deep oversold, already turning — hard gate ensures turning)
    +1  : CCI_prev < params.cci_threshold (above -100, but still below floor)
    +2  : close >= EMA20 (full pin bar — closed back above value zone)
    +1  : close >= EMA20 × 0.98 (near miss)
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

        # ── Trend duration gate ───────────────────────────────────────────────
        # Require PB_MIN_TREND_BARS consecutive bars of EMA8>EMA20 AND Close>SMA50
        # before the signal bar to exclude fresh/choppy trends.
        _e8   = ind.ema8.values[:-1]
        _e20  = ind.ema20.values[:-1]
        _c    = ind.close.values[:-1]
        _s50  = ind.sma50.values[:-1]
        _trend_mask = (_e8 > _e20) & (_c > _s50)
        _flipped = (~_trend_mask)[::-1]
        _trend_bars = int(np.argmax(_flipped)) if _flipped.any() else len(_flipped)
        if _trend_bars < PB_MIN_TREND_BARS:
            return None, 0.0

        # ── Value zone (hard gate + score) ────────────────────────────────────
        # Low must actually penetrate EMA8 or EMA20 — proximity alone is rejected.
        # Bonus point if close recovered deep into the zone (within params.ema_distance ATR).
        if not (ll <= l8 or ll <= l20):
            return None, 0.0   # hard gate: price never entered the value zone
        score += 2.0
        # Close proximity bonus: close within N ATR of EMA8 or EMA20 = tight zone test
        if latr > 0:
            atr_to_8  = abs(lc - l8)  / latr
            atr_to_20 = abs(lc - l20) / latr
            if atr_to_8 <= params.ema_distance or atr_to_20 <= params.ema_distance:
                score += 1.0

        # ── CCI momentum (hard gate + score) ─────────────────────────────────
        # CCI must be turning up from below threshold — no directionless EMA touch.
        # Floor depth is scoring only: deeply oversold = higher conviction.
        if not (cci_prev < params.cci_threshold and cci_today > cci_prev):
            return None, 0.0   # hard gate: no momentum reversal at all
        if cci_prev < -100:
            score += 2.0
        else:
            score += 1.0

        # ── Pin-bar score ──────────────────────────────────────────────────────
        # Close recovered above (or near) EMA20 — confirms rejection of value zone
        if lc >= l20:
            score += 2.0
        elif lc >= l20 * 0.98:
            score += 1.0

        # ── Structural support (hard gate + score) ────────────────────────────
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup, latr,
            sma200=ind.l200,
            ema20=float(ind.ema20.iloc[-1]),
            ema50=float(ind.sma50.iloc[-1]),
            regime=regime,
            rs_rank=rs_score,
            trend_bars=_trend_bars,
        )
        if nearest_sup is not None and latr > 0:
            _ext_atr = (lc - nearest_sup["level"]) / latr
            if _ext_atr > SUPPORT_MAX_EXTENSION_ATR:
                nearest_sup = None   # too far from support — treat as no support found
            else:
                nearest_sup["extension_atr"] = round(_ext_atr, 2)
        if nearest_sup is None:
            return None, 0.0   # hard gate: no structural support

        score += 2.0

        if nearest_sup["source"] == "ASCENDING_TDL":
            score += params.tdl_bonus

        # ── Risk math ─────────────────────────────────────────────────────────
        entry = round(lh * 1.001, 2)

        if nearest_sup["level"] >= lc:
            return None, 0.0

        stop_loss = round(ll - PB_ATR_STOP_MULTIPLIER * latr, 2)
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
            "trend_bars":       _trend_bars,
            "extension_atr":    nearest_sup.get("extension_atr", 0.0) if nearest_sup else 0.0,
        }
        return setup, score

    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("scan_pullback_scored %s: %s", ticker, exc)
        return None, 0.0
