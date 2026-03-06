"""
Engine 0: Institutional Market Regime Engine (Task 2)
══════════════════════════════════════════════════════
Multi-factor regime scoring system (0–100).

Factor weights (total = 100):
  1. SPY Close > EMA20          → 20 pts  (momentum gate)
  2. SPY Close > SMA50          → 15 pts  (intermediate trend)
  3. SMA50 > SMA200             → 15 pts  (MA stack — Stage 2 market)
  4. EMA20 slope (5-day)        → 10 pts  (trend acceleration)
  5. % universe above SMA50     → 20 pts  (breadth — passed from main.py)
  6. 52-week H/L ratio          → 10 pts  (breadth quality — passed from main.py)
  7. VIX < VIX SMA20            → 10 pts  (fear gauge)

Regime zones:
  70–100  →  AGGRESSIVE  (full engine suite enabled)
  40–69   →  SELECTIVE   (engines enabled, size conservatively)
  0–39    →  DEFENSIVE   (Engines 2 & 3 disabled)
"""

from typing import Dict

import numpy as np
import pandas as pd
import yfinance as yf

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import ema as _ema, sma as _sma
from constants import (
    REGIME_WEIGHT_EMA20,
    REGIME_WEIGHT_SMA50,
    REGIME_WEIGHT_MA_STACK,
    REGIME_WEIGHT_SLOPE,
    REGIME_WEIGHT_BREADTH,
    REGIME_WEIGHT_HL,
    REGIME_WEIGHT_VIX,
    REGIME_AGGRESSIVE_THRESHOLD,
    REGIME_SELECTIVE_THRESHOLD,
)


def check_market_regime(
    breadth_pct: float = 0.5,
    hl_ratio: float = 0.5,
) -> Dict:
    """
    Fetch SPY (1y) + VIX (3mo) data and compute a 7-factor regime score.

    Parameters
    ----------
    breadth_pct : float
        Fraction of the scan universe whose daily close is above SMA50.
        Computed by main.py from the bulk-prefetch cache and passed here.
        Default 0.5 (neutral) when called before prefetch.
    hl_ratio : float
        new_highs / (new_highs + new_lows + 1) across the scan universe.
        Default 0.5 (neutral).

    Returns
    -------
    dict
        is_bullish    : bool   — regime_score >= REGIME_SELECTIVE_THRESHOLD
        regime_score  : int    — 0–100
        regime        : str    — "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
        spy_close     : float
        spy_20ema     : float
        spy_sma50     : float
        spy_sma200    : float
        vix           : float  (0.0 on fetch failure)
        vix_sma20     : float
        factors       : dict   — per-factor point breakdown
    """
    try:
        # ── Fetch SPY 1y daily data ───────────────────────────────────────────
        spy = yf.download(
            "SPY",
            period="1y",
            interval="1d",
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )

        if spy is None or spy.empty:
            return _error("No SPY data returned from yfinance")

        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)

        close_col = "Adj Close" if "Adj Close" in spy.columns else "Close"
        close = spy[close_col].dropna()

        if len(close) < 22:
            return _error(f"Insufficient SPY data: {len(close)} bars (need ≥22)")

        # ── Compute SPY indicators ────────────────────────────────────────────
        ema20_s  = _ema(close, 20)
        sma50_s  = _sma(close, 50)
        sma200_s = _sma(close, 200)

        def _fv(s) -> float:
            v = s.iloc[-1]
            f = float(v.item() if hasattr(v, "item") else v)
            return 0.0 if np.isnan(f) else f

        lc       = _fv(close)
        l_ema20  = _fv(ema20_s)
        l_sma50  = _fv(sma50_s)
        l_sma200 = _fv(sma200_s)

        if lc <= 0 or l_ema20 <= 0:
            return _error("SPY price or EMA20 is zero/NaN")

        # ── EMA20 slope over last 5 bars ──────────────────────────────────────
        ema20_clean = ema20_s.dropna()
        slope_score = 0
        if len(ema20_clean) >= 6:
            old = float(ema20_clean.iloc[-6])
            new = float(ema20_clean.iloc[-1])
            if old > 0:
                pct_slope = (new - old) / old  # e.g. +0.005 = rising 0.5%/5d
                # Linear scale: ≥+0.5% → full 10pts; ≤-0.5% → 0pts
                slope_score = int(min(REGIME_WEIGHT_SLOPE, max(0, (pct_slope + 0.005) / 0.01 * REGIME_WEIGHT_SLOPE)))

        # ── Factor 1–4 scores ─────────────────────────────────────────────────
        f1 = REGIME_WEIGHT_EMA20    if lc > l_ema20  else 0
        f2 = REGIME_WEIGHT_SMA50    if lc > l_sma50  else 0
        f3 = REGIME_WEIGHT_MA_STACK if (l_sma50 > 0 and l_sma200 > 0 and l_sma50 > l_sma200) else 0
        f4 = slope_score  # 0–10

        # ── VIX fetch (Factor 7) ──────────────────────────────────────────────
        vix_close = 0.0
        vix_sma20 = 0.0
        f7 = 0
        try:
            vix_df = yf.download(
                "^VIX",
                period="3mo",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if vix_df is not None and not vix_df.empty:
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_df.columns = vix_df.columns.get_level_values(0)
                vc = vix_df["Close"].dropna() if "Close" in vix_df.columns else pd.Series(dtype=float)
                if len(vc) >= 20:
                    vix_close = float(vc.iloc[-1])
                    vix_sma20 = float(vc.rolling(20).mean().iloc[-1])
                    if vix_close > 0 and vix_sma20 > 0 and vix_close < vix_sma20:
                        f7 = REGIME_WEIGHT_VIX
        except Exception:
            pass  # VIX failure is non-fatal — factor 7 scores 0

        # ── Factor 5 (breadth) and 6 (H/L ratio) ─────────────────────────────
        # breadth_pct = 0.0 → all below SMA50 (max bearish) → 0 pts
        # breadth_pct = 1.0 → all above SMA50 (max bullish) → REGIME_WEIGHT_BREADTH pts
        f5 = int(round(min(breadth_pct, 1.0) * REGIME_WEIGHT_BREADTH))

        # hl_ratio = 0.0 → all new lows → 0 pts
        # hl_ratio = 1.0 → all new highs → REGIME_WEIGHT_HL pts
        f6 = int(round(min(hl_ratio, 1.0) * REGIME_WEIGHT_HL))

        regime_score = f1 + f2 + f3 + f4 + f5 + f6 + f7

        regime = _score_to_regime(regime_score)
        is_bullish = regime_score >= REGIME_SELECTIVE_THRESHOLD

        return {
            "is_bullish":   is_bullish,
            "regime_score": regime_score,
            "regime":       regime,
            "spy_close":    round(lc, 2),
            "spy_20ema":    round(l_ema20, 2),
            "spy_sma50":    round(l_sma50, 2),
            "spy_sma200":   round(l_sma200, 2),
            "vix":          round(vix_close, 2),
            "vix_sma20":    round(vix_sma20, 2),
            "breadth_pct":  round(breadth_pct, 3),
            "hl_ratio":     round(hl_ratio, 3),
            "factors": {
                "f1_ema20":    f1,
                "f2_sma50":    f2,
                "f3_ma_stack": f3,
                "f4_slope":    f4,
                "f5_breadth":  f5,
                "f6_hl_ratio": f6,
                "f7_vix":      f7,
            },
        }

    except Exception as exc:
        return _error(str(exc)[:120])


def _score_to_regime(score: int) -> str:
    if score >= REGIME_AGGRESSIVE_THRESHOLD:
        return "AGGRESSIVE"
    if score >= REGIME_SELECTIVE_THRESHOLD:
        return "SELECTIVE"
    return "DEFENSIVE"


def _error(msg: str) -> Dict:
    return {
        "is_bullish":   False,
        "regime_score": 0,
        "regime":       f"ERROR: {msg}",
        "spy_close":    0.0,
        "spy_20ema":    0.0,
        "spy_sma50":    0.0,
        "spy_sma200":   0.0,
        "vix":          0.0,
        "vix_sma20":    0.0,
        "breadth_pct":  0.5,
        "hl_ratio":     0.5,
        "factors":      {},
    }
