"""
Engine 6: Resistance Breakout Scanner — Multi-Source Architecture
═════════════════════════════════════════════════════════════════
Detects institutional-quality breakouts above resistance using three
complementary resistance detection methods:

  1. DONCHIAN HIGH  — rolling N-bar high (always produces a level)
  2. PIVOT HIGHS    — structural turning points from recent price action
  3. KDE ZONES      — density-based zones from engine1 (optional supplement)

Resistance candidates are collected from all available sources, deduplicated,
and the closest level above the current price is used for breakout detection.
This eliminates the "no zones found" failure that plagued the KDE-only approach
on split-adjusted or strongly trending tickers.

Breakout Signal Logic:
  pre_close ≤ resistance  AND  brk_close > resistance × (1 + buffer)

Quality Filters (all Optuna-tunable via BacktestParams):
  ─ Volume expansion  : brk_vol ≥ vol_mult × 50-day average
  ─ ATR expansion     : bar range ≥ atr_expansion × ATR14  (0 = disabled)
  ─ Consolidation     : price was within 8% of resistance in last N bars
  ─ Trend filter      : close > 50 SMA
  ─ Overextension gate: current close ≤ resistance × 1.05

Risk Math:
  Entry      = breakout_bar_high × 1.001
  Stop Loss  = resistance − stop_atr × ATR14
  Take Profit= nearest upstream resistance, else Entry + tp_multiple × Risk

Quality Score (_raw_score for Optuna / scored-mode filtering):
  Base 5.0 + volume bonus (0–2) + breakout_pct bonus (0–2) +
  freshness bonus (0–0.5) + source quality bonus (0–0.3)
"""

import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr
from constants import (
    TARGET_RR,
    RES_STOP_ATR_FACTOR,
    RES_BREAKOUT_VOL_MULT,
    RES_DECISIVE_MIN_PCT,
    RES_DECISIVE_ATR_FACTOR,
    PIVOT_CONTAMINATION_PCT,
    PIVOT_CONTAMINATION_LOOKBACK,
)
from zone_utils import nearest_resistance_target


# ─────────────────────────────────────────────────────────────────────────────
# Temporary debug counter — logs first 20 volume gate checks to stderr/stdout.
# Set to a large number (e.g. 9999) to disable or reset to 0 at start of run.
# ─────────────────────────────────────────────────────────────────────────────
_VOL_DEBUG_COUNT: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Module-level defaults (used when params=None / legacy mode)
# ─────────────────────────────────────────────────────────────────────────────

_MAX_DAYS_LOOKBACK      = 3
_MAX_EXTEND_PCT         = 0.05    # overextension gate: price ≤ resistance × 1.05
_CONSOL_TOLERANCE       = 0.08    # consolidation window: price ≥ resistance × 0.92
_DEDUP_THRESHOLD        = 0.005   # merge resistance levels within 0.5% of each other
_PIVOT_HISTORY_BARS     = 252     # look back at most 1 year for pivot highs

_DONCHIAN_N_DEFAULT     = 63      # ~3 months
_PIVOT_STRENGTH_DEFAULT = 2
_ATR_EXP_DEFAULT        = 0.0     # disabled
_MIN_CONSOL_DEFAULT     = 3


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def scan_resistance_breakout(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
    debug: bool = False,
    params=None,
    regime_score: float = 0.5,
) -> Optional[Dict]:
    """Return the most recent qualifying resistance breakout, or None.

    Parameters
    ----------
    regime_score : float  0.0–1.0 from engine0.
        Adjusts the Donchian lookback window dynamically:
        - AGGRESSIVE (1.0) → shorter lookback (tighter, uses recent highs)
        - NEUTRAL    (0.5) → base lookback unchanged
        - DEFENSIVE  (0.0) → longer lookback (wider, more historical resistance)
        Formula: n_adjusted = base_n × (1.0 + (0.5 − regime_score) × 0.67)
        Clamped to [15, 90].
    """
    try:
        # ── Resolve tunable params (fall back to module defaults) ─────────────
        _vol_thresh  = getattr(params, "brk_vol_mult",          RES_BREAKOUT_VOL_MULT)
        _stop_atr    = getattr(params, "brk_stop_atr",          RES_STOP_ATR_FACTOR)
        _buffer      = getattr(params, "brk_min_pct",           RES_DECISIVE_MIN_PCT)
        _gap_pct     = getattr(params, "brk_gap_pct",           0.042)   # max close above resistance
        _base_n      = int(getattr(params, "brk_donchian_n",    _DONCHIAN_N_DEFAULT))
        _pivot_str   = int(getattr(params, "brk_pivot_strength",_PIVOT_STRENGTH_DEFAULT))
        _atr_exp     = getattr(params, "brk_atr_expansion",     _ATR_EXP_DEFAULT)
        _min_consol  = int(getattr(params, "brk_min_consolidation", _MIN_CONSOL_DEFAULT))

        # ── Dynamic Donchian lookback — tighter in bull, wider in bear ────────
        # regime_score=1.0: factor=0.665 → _base_n×0.665 (tighter, recent highs)
        # regime_score=0.5: factor=1.0   → _base_n unchanged
        # regime_score=0.0: factor=1.335 → _base_n×1.335 (wider, more history)
        _regime_factor = 1.0 + (0.5 - float(regime_score)) * 0.67
        _donchian_n    = max(15, min(90, int(_base_n * _regime_factor)))

        data = _prep(df)
        if data is None or len(data) < max(60, _donchian_n + 10):
            return None

        adj      = _adj_col(data)
        close_s  = data[adj]
        high_s   = data["High"]
        low_s    = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # ── Trend filter: price above 50 SMA ─────────────────────────────────
        sma50   = data["_SMA50"] if "_SMA50" in data.columns else close_s.rolling(50).mean()
        lc_val  = close_s.iloc[-1]
        lc      = float(lc_val.item() if hasattr(lc_val, "item") else lc_val)
        l50_val = sma50.iloc[-1]
        l50     = float(l50_val.item() if hasattr(l50_val, "item") else l50_val) if pd.notna(l50_val) else 0.0
        if l50 > 0 and lc < l50:
            if debug:
                print(f"Engine 6: REJECTED — Below 50 SMA ({lc:.2f} < {l50:.2f})")
            return None

        # ── Volume SMA ────────────────────────────────────────────────────────
        # Shift(1): exclude the current bar from its own average — prevents leakage.
        # vol_sma50_arr[i] = mean(Volume[i-50 : i])  (excludes bar i itself)
        vol_sma50_s = (
            data["_VOLSMA50"].shift(1)
            if "_VOLSMA50" in data.columns
            else volume_s.rolling(50, min_periods=10).mean().shift(1)
        )
        vsm50_val   = vol_sma50_s.iloc[-1]
        vol_sma50   = float(vsm50_val.item() if hasattr(vsm50_val, "item") else vsm50_val)
        if np.isnan(vol_sma50) or vol_sma50 <= 0:
            return None
        # Keep the full array so aged signals (days_back > 0) use the average
        # at the correct bar index rather than the last-bar value.
        vol_sma50_arr = vol_sma50_s.values.astype(float)

        # ── ATR ───────────────────────────────────────────────────────────────
        atr14    = data["_ATR14"] if "_ATR14" in data.columns else _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr     = float(latr_val.item() if hasattr(latr_val, "item") else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        close_arr  = close_s.values.astype(float)
        high_arr   = high_s.values.astype(float)
        low_arr    = low_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        atr_arr    = atr14.values.astype(float)
        n          = len(close_arr)

        # ── Pre-compute Donchian resistance series ────────────────────────────
        # donchian_res[i] = max(high[i-N : i])  — excludes bar i (no look-ahead)
        donchian_res = (
            pd.Series(high_arr)
            .rolling(_donchian_n)
            .max()
            .shift(1)
            .values
        )

        # ── Pre-compute pivot highs ───────────────────────────────────────────
        # Use data up to bar n-2 (all confirmed pivots, avoiding the current bar)
        pivot_levels = _find_pivot_highs(high_arr[: n - 1], _pivot_str)

        # ── Scan last _MAX_DAYS_LOOKBACK bars — collect ALL valid candidates ─────
        # All candidates that pass every filter are accumulated; the best one is
        # selected after the full scan.  This eliminates per-candidate debug spam
        # and removes artificial RES_BREAKOUT inflation from multi-level duplicates.
        _valid_candidates: List[Dict] = []

        for days_back in range(_MAX_DAYS_LOOKBACK + 1):
            brk_idx = n - 1 - days_back
            pre_idx = brk_idx - 1
            if pre_idx < _donchian_n:
                continue

            brk_close = close_arr[brk_idx]
            brk_high  = high_arr[brk_idx]
            brk_low   = low_arr[brk_idx]
            brk_vol   = volume_arr[brk_idx]
            brk_range = brk_high - brk_low
            brk_atr   = atr_arr[brk_idx] if not np.isnan(atr_arr[brk_idx]) else latr
            pre_close = close_arr[pre_idx]

            # Collect resistance candidates above pre_close
            res_candidates = _resistance_candidates(
                high_arr, pre_close,
                brk_idx, donchian_res,
                pivot_levels, zones,
            )

            if not res_candidates:
                if debug:
                    print(f"Engine 6: REJECTED day -{days_back} — No resistance above price")
                continue

            for resistance, source in res_candidates:

                # ── Zone cross ────────────────────────────────────────────────
                if not (pre_close <= resistance < brk_close):
                    if debug:
                        print(
                            f"Engine 6: REJECTED day -{days_back} [{source}@{resistance:.2f}] "
                            f"— No cross (pre={pre_close:.2f}, brk={brk_close:.2f})"
                        )
                    continue

                # ── Breakout buffer ───────────────────────────────────────────
                if brk_close < resistance * (1.0 + _buffer):
                    if debug:
                        print(
                            f"Engine 6: REJECTED day -{days_back} [{source}@{resistance:.2f}] "
                            f"— Buffer not met ({brk_close:.2f} < {resistance*(1+_buffer):.2f})"
                        )
                    continue

                # ── Overextension gate (only relevant for aged signals) ───────
                if days_back > 0 and close_arr[-1] > resistance * (1.0 + _MAX_EXTEND_PCT):
                    if debug:
                        print(f"Engine 6: REJECTED day -{days_back} [{source}] — Overextended")
                    continue

                # ── Volume filter (HARD) ──────────────────────────────────────
                # Use the 50-day average ending the bar BEFORE the breakout bar
                # (vol_sma50_arr already has shift(1) applied — no leakage).
                _vsma_at_brk = vol_sma50_arr[brk_idx] if not np.isnan(vol_sma50_arr[brk_idx]) else vol_sma50
                vol_ratio    = brk_vol / _vsma_at_brk if _vsma_at_brk > 0 else 0.0
                if vol_ratio < _vol_thresh:
                    if debug:
                        print(
                            f"Engine 6: REJECTED day -{days_back} [{source}] "
                            f"— Volume {vol_ratio:.2f}x < {_vol_thresh:.2f}x"
                        )
                    continue

                # ── ATR expansion filter (optional) ───────────────────────────
                if _atr_exp > 0 and brk_atr > 0:
                    bar_expansion = brk_range / brk_atr
                    if bar_expansion < _atr_exp:
                        if debug:
                            print(
                                f"Engine 6: REJECTED day -{days_back} [{source}] "
                                f"— ATR expansion {bar_expansion:.2f}x < {_atr_exp:.2f}x"
                            )
                        continue

                # ── Consolidation filter ──────────────────────────────────────
                # At least min_consol bars in the window before breakout must
                # have closed within _CONSOL_TOLERANCE below resistance.
                if _min_consol > 0:
                    consol_end   = brk_idx
                    consol_start = max(0, consol_end - _min_consol - 10)
                    consol_closes = close_arr[consol_start:consol_end]
                    near_res = consol_closes >= resistance * (1.0 - _CONSOL_TOLERANCE)
                    if not np.any(near_res):
                        if debug:
                            print(
                                f"Engine 6: REJECTED day -{days_back} [{source}@{resistance:.2f}] "
                                f"— No consolidation near resistance "
                                f"(max close={consol_closes.max():.2f}, "
                                f"need ≥{resistance*(1-_CONSOL_TOLERANCE):.2f})"
                            )
                        continue

                # ── Contaminated pivot check ──────────────────────────────────
                # If price previously exceeded this resistance level by more than
                # PIVOT_CONTAMINATION_PCT and then retreated, the level is a
                # failed launch-pad — reject it.
                _contam_start = max(0, brk_idx - PIVOT_CONTAMINATION_LOOKBACK)
                _contam_end   = max(0, brk_idx - 5)
                if _contam_end > _contam_start:
                    _prior_peak = float(np.max(high_arr[_contam_start:_contam_end]))
                    if _prior_peak > resistance * (1.0 + PIVOT_CONTAMINATION_PCT):
                        if debug:
                            print(
                                f"Engine 6: REJECTED day -{days_back} [{source}@{resistance:.2f}] "
                                f"— Contaminated pivot (prior peak {_prior_peak:.2f})"
                            )
                        continue

                # ── All filters passed — build candidate ──────────────────────
                breakout_pct = round((brk_close - resistance) / resistance * 100, 2)

                # Gap gate: skip if already extended too far above resistance.
                # Mirrors backtest_engine brk_gap_pct check.
                if (brk_close - resistance) / resistance > _gap_pct:
                    continue

                entry        = round(brk_high * 1.001, 2)
                stop_loss    = round(resistance - _stop_atr * latr, 2)
                risk         = entry - stop_loss
                if risk <= 0 or risk > entry * 0.15:
                    continue

                take_profit, actual_rr = nearest_resistance_target(entry, zones, risk)

                # ── Quality score ─────────────────────────────────────────────
                _score = 5.0
                # Volume bonus
                if vol_ratio >= 3.0:        _score += 2.0
                elif vol_ratio >= 2.0:      _score += 1.0
                elif vol_ratio >= 1.5:      _score += 0.5
                # Breakout strength bonus
                if breakout_pct >= 3.0:     _score += 2.0
                elif breakout_pct >= 2.0:   _score += 1.0
                elif breakout_pct >= 1.0:   _score += 0.5
                # Freshness
                if days_back == 0:          _score += 0.5
                # Source quality (Donchian = cleanest, KDE = supplemental)
                if source == "donchian":    _score += 0.3
                elif source == "pivot":     _score += 0.2

                _valid_candidates.append({
                    "ticker":              ticker,
                    "setup_type":          "RES_BREAKOUT",
                    "signal":              "BRK",
                    "entry":               entry,
                    "stop_loss":           stop_loss,
                    "take_profit":         take_profit,
                    "rr":                  actual_rr,
                    "resistance_level":    round(resistance, 2),
                    "zone_upper":          round(resistance, 2),
                    "breakout_pct":        breakout_pct,
                    "volume_ratio":        round(vol_ratio, 2),
                    "days_since_breakout": days_back,
                    "zone_source":         source,
                    "setup_date":          str(data.index[-1].date()),
                    "_raw_score":          round(_score, 1),
                    "atr":                 round(latr, 4),
                })

        if not _valid_candidates:
            if debug:
                print("Engine 6: No valid breakout found in last 3 days")
            return None

        # ── Select best candidate ─────────────────────────────────────────────
        # Primary  : highest volume_ratio  (strongest institutional confirmation)
        # Secondary: smallest breakout_pct (cleanest entry, closest to resistance)
        # Tertiary : smallest days_back    (freshest signal)
        best = max(
            _valid_candidates,
            key=lambda c: (c["volume_ratio"], -c["breakout_pct"], -c["days_since_breakout"]),
        )

        # ── Debug print: once per ticker/day, for selected candidate only ─────
        global _VOL_DEBUG_COUNT
        if _VOL_DEBUG_COUNT < 20:
            _VOL_DEBUG_COUNT += 1
            print(
                f"[E6 VOL DEBUG #{_VOL_DEBUG_COUNT}] {ticker} day-{best['days_since_breakout']} "
                f"candidates={len(_valid_candidates)} "
                f"vol_ratio={best['volume_ratio']:.3f}  threshold={_vol_thresh:.3f}  "
                f"passed=YES  trade=TRIGGERED"
            )

        return best

    except Exception as exc:
        print(f"[Engine6] {ticker}: {exc}")
        return None


def scan_res_breakout_near(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
    debug: bool = False,
    params=None,
) -> Optional[Dict]:
    """
    Watchlist: stock approaching a resistance breakout but not yet triggered.

    Conditions:
      - Trend: close > SMA50
      - Resistance identified (Donchian / pivot / KDE)
      - Close within NEAR_PCT below resistance (approaching zone)
      - Close has NOT crossed resistance yet
      - Consolidation: >= _min_consol bars within _CONSOL_TOLERANCE of resistance
      - Volume: soft signal only (no hard gate)

    Returns a WATCHLIST setup dict or None.
    """
    NEAR_PCT = 0.05   # within 5% below resistance

    try:
        _stop_atr   = getattr(params, "brk_stop_atr",           RES_STOP_ATR_FACTOR)
        _donchian_n = int(getattr(params, "brk_donchian_n",     _DONCHIAN_N_DEFAULT))
        _pivot_str  = int(getattr(params, "brk_pivot_strength", _PIVOT_STRENGTH_DEFAULT))
        _min_consol = int(getattr(params, "brk_min_consolidation", _MIN_CONSOL_DEFAULT))

        data = _prep(df)
        if data is None or len(data) < max(60, _donchian_n + 10):
            return None

        adj      = _adj_col(data)
        close_s  = data[adj]
        high_s   = data["High"]
        low_s    = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # Trend filter: close > SMA50
        sma50   = data["_SMA50"] if "_SMA50" in data.columns else close_s.rolling(50).mean()
        lc_val  = close_s.iloc[-1]
        lc      = float(lc_val.item() if hasattr(lc_val, "item") else lc_val)
        l50_val = sma50.iloc[-1]
        l50     = float(l50_val.item() if hasattr(l50_val, "item") else l50_val) if pd.notna(l50_val) else 0.0
        if l50 > 0 and lc < l50:
            return None

        vol_sma50_s = data["_VOLSMA50"] if "_VOLSMA50" in data.columns else volume_s.rolling(50).mean()
        vsm50_val   = vol_sma50_s.iloc[-1]
        vol_sma50   = float(vsm50_val.item() if hasattr(vsm50_val, "item") else vsm50_val)
        if np.isnan(vol_sma50) or vol_sma50 <= 0:
            return None

        atr14    = data["_ATR14"] if "_ATR14" in data.columns else _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr     = float(latr_val.item() if hasattr(latr_val, "item") else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        close_arr  = close_s.values.astype(float)
        high_arr   = high_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        n          = len(close_arr)

        donchian_res = (
            pd.Series(high_arr)
            .rolling(_donchian_n)
            .max()
            .shift(1)
            .values
        )
        # Watchlist uses confirmed structural pivots only (strength=5, last 6mo,
        # must have pulled back ≥3% after the pivot to prove it was real resistance).
        # Strength=2 is fine for the live scanner (volume+cross gates filter noise),
        # but without those gates every minor local high within 5% shows as a signal.
        pivot_levels = _find_confirmed_pivot_highs(high_arr[: n - 1], strength=5, lookback=126, min_pullback=0.03)

        brk_idx = n - 1
        if brk_idx < _donchian_n:
            return None

        # Watchlist: structural resistance only — confirmed pivot highs + KDE zones.
        # Donchian excluded (would flag any trending stock within 5% of recent high).
        raw_wl: List[Tuple[float, str]] = []
        for ph in pivot_levels:
            if ph > lc:
                raw_wl.append((ph, "pivot"))
        for zone in zones:
            if zone.get("type") == "RESISTANCE":
                upper = float(zone.get("upper", 0))
                if upper > lc:
                    raw_wl.append((upper, "kde"))
        raw_wl.sort(key=lambda x: x[0])
        candidates: List[Tuple[float, str]] = []
        for level, source in raw_wl:
            if not candidates or (level - candidates[-1][0]) / candidates[-1][0] > _DEDUP_THRESHOLD:
                candidates.append((level, source))

        if not candidates:
            return None

        for resistance, source in candidates:
            # Must be above current close (not yet broken)
            if resistance <= lc:
                continue

            # Proximity: close within NEAR_PCT below resistance
            distance_pct = (resistance - lc) / resistance
            if distance_pct > NEAR_PCT:
                continue

            # Consolidation: >= _min_consol bars within _CONSOL_TOLERANCE of resistance
            if _min_consol > 0:
                consol_start  = max(0, brk_idx - _min_consol - 10)
                consol_closes = close_arr[consol_start:brk_idx]
                near_res      = consol_closes >= resistance * (1.0 - _CONSOL_TOLERANCE)
                if not np.any(near_res):
                    continue

            # Volume ratio (soft signal only)
            last_vol  = volume_arr[brk_idx]
            vol_ratio = last_vol / vol_sma50 if vol_sma50 > 0 else 1.0

            entry     = round(resistance * 1.001, 2)
            stop_loss = round(resistance - _stop_atr * latr, 2)
            risk      = entry - stop_loss
            if risk <= 0 or risk > entry * 0.15:
                continue

            take_profit, actual_rr = nearest_resistance_target(entry, zones, risk)

            return {
                "ticker":           ticker,
                "setup_type":       "WATCHLIST",
                "watchlist_source": "RES_BREAKOUT",
                "entry":            entry,
                "stop_loss":        stop_loss,
                "take_profit":      take_profit,
                "rr":               actual_rr,
                "resistance_level": round(resistance, 2),
                "distance_pct":     round(distance_pct * 100, 2),
                "volume_ratio":     round(vol_ratio, 2),
                "zone_source":      source,
                "setup_date":       str(data.index[-1].date()),
                "atr":              round(latr, 4),
            }

        return None

    except Exception as exc:
        print(f"[Engine6 near] {ticker}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Resistance candidate collection
# ─────────────────────────────────────────────────────────────────────────────

def _resistance_candidates(
    high_arr: np.ndarray,
    pre_close: float,
    brk_idx: int,
    donchian_res: np.ndarray,
    pivot_levels: List[float],
    zones: List[Dict],
) -> List[Tuple[float, str]]:
    """
    Collect all resistance candidates above pre_close for the given bar.

    Sources (in priority order):
      1. Donchian high — rolling max of prior N bars (always present)
      2. Recent pivot highs — structural turning points
      3. KDE resistance zones — density-based levels (optional)

    Returns list of (level, source_name) sorted ascending (closest first),
    with near-duplicates (within 0.5%) merged.
    """
    raw: List[Tuple[float, str]] = []

    # 1. Donchian
    dc = donchian_res[brk_idx]
    if not np.isnan(dc) and dc > pre_close:
        raw.append((float(dc), "donchian"))

    # 2. Pivot highs (already filtered to above-price levels in _find_pivot_highs;
    #    re-check against pre_close since that changes per days_back)
    for ph in pivot_levels:
        if ph > pre_close:
            raw.append((ph, "pivot"))

    # 3. KDE zones
    for zone in zones:
        if zone.get("type") == "RESISTANCE":
            upper = float(zone.get("upper", 0))
            if upper > pre_close:
                raw.append((upper, "kde"))
        elif zone.get("type") == "SUPPORT":
            # Recently flipped support (price crossed above) — may still act as resistance
            upper = float(zone.get("upper", 0))
            if 0 < upper > pre_close:
                raw.append((upper, "kde"))

    if not raw:
        return []

    # Sort by level ascending (nearest resistance first)
    raw.sort(key=lambda x: x[0])

    # Deduplicate levels within _DEDUP_THRESHOLD of each other (keep first = lowest)
    deduped: List[Tuple[float, str]] = []
    for level, source in raw:
        if not deduped or (level - deduped[-1][0]) / deduped[-1][0] > _DEDUP_THRESHOLD:
            deduped.append((level, source))

    return deduped


# ─────────────────────────────────────────────────────────────────────────────
# Pivot high detection
# ─────────────────────────────────────────────────────────────────────────────

def _find_confirmed_pivot_highs(
    high_arr: np.ndarray,
    strength: int = 5,
    lookback: int = 126,
    min_pullback: float = 0.03,
) -> List[float]:
    """
    Find structural pivot highs that were confirmed as real resistance.

    Stricter than _find_pivot_highs — used by the watchlist scanner where
    the volume/cross gates that filter noise in the live scanner are absent.

    Requirements:
      - strength=5 minimum (bar must be highest of 11-bar window)
      - only considers last `lookback` bars (default 126 = ~6 months)
      - pivot must have been followed by a drop of at least `min_pullback`
        within the next 10 bars (confirms the level was actual resistance)

    Returns sorted unique list of confirmed pivot high values.
    """
    n = len(high_arr)
    start = max(0, n - lookback)
    window = high_arr[start:]
    wn = len(window)

    if wn < 2 * strength + 1:
        return []

    pivots: set = set()
    for i in range(strength, wn - strength):
        h = window[i]
        left_ok  = all(h >= window[i - s] for s in range(1, strength + 1))
        right_ok = all(h >= window[i + s] for s in range(1, strength + 1))
        if not (left_ok and right_ok):
            continue
        # Confirm real resistance: price must have dropped ≥ min_pullback after pivot
        look_end = min(wn, i + 11)
        post_low = np.min(window[i + 1:look_end]) if i + 1 < look_end else h
        if h > 0 and (h - post_low) / h >= min_pullback:
            pivots.add(round(float(h), 6))

    return sorted(pivots)


def _find_pivot_highs(
    high_arr: np.ndarray,
    strength: int,
) -> List[float]:
    """
    Find all confirmed pivot highs in high_arr.

    A pivot high at index i:
        high[i] >= max(high[i-s], high[i+s])  for s in 1..strength

    Only considers pivots with at least `strength` bars on each side.
    Uses only data already in high_arr (no look-ahead).

    Returns sorted unique list of pivot high values.
    """
    n = len(high_arr)
    if n < 2 * strength + 1:
        return []

    pivots: set = set()
    for i in range(strength, n - strength):
        h = high_arr[i]
        left_ok  = all(h >= high_arr[i - s] for s in range(1, strength + 1))
        right_ok = all(h >= high_arr[i + s] for s in range(1, strength + 1))
        if left_ok and right_ok:
            pivots.add(round(float(h), 6))

    return sorted(pivots)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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
