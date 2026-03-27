"""
Engine 0: Continuous Market Regime Engine (V2 — 7-Factor SPY-Only)
═══════════════════════════════════════════════════════════════════
All 7 factors are computable from SPY OHLCV alone.
Identical logic for live scanner and historical backtest — eliminates
train-serve skew.

Factor design (weights sum to 100; Optuna-injectable via RegimeWeights):
  F1 Close/EMA20  (10 pts): σ((close − EMA20) / ATR14 × k)
  F2 Close/SMA50  (10 pts): σ((close − SMA50) / ATR14 × k)
  F3 SMA50 Slope  (20 pts): σ(SMA50_5bar_pct × k)          ← heavy: momentum
  F4 Close/SMA200 (25 pts): σ((close − SMA200) / ATR14 × k) ← heaviest: long trend
  F5 EMA20/SMA50  (10 pts): σ((EMA20 − SMA50) / ATR14 × k) ← stack alignment
  F6 ATR Regime   (10 pts): 1 − σ((ATR-ratio − 1) × k)     ← inverted: low vol
  F7 EMA8/EMA20   (15 pts): σ((EMA8 − EMA20) / ATR14 × k)  ← short momentum

CCI multiplier (applied to raw sum):
  CCI > 150 → linear penalty down to 0.35 at CCI 250+
  CCI < −150 and turning up → 1.10 boost (oversold reversal)

Output: float 0.0–1.0 per bar (was 0–100 in V1 4-factor version).

Regime zones (0.0–1.0 scale):
  0.70–1.0  → AGGRESSIVE  (full engine suite)
  0.40–0.69 → SELECTIVE   (all engines, conservative sizing)
  0.00–0.39 → DEFENSIVE   (Engines 2 & 3 disabled)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
import yfinance as yf

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from constants import (
    REGIME_AGGRESSIVE_THRESHOLD,
    REGIME_SELECTIVE_THRESHOLD,
    REGIME_W_CLOSE_EMA20,
    REGIME_W_CLOSE_SMA50,
    REGIME_W_SMA50_SLOPE,
    REGIME_W_CLOSE_SMA200,
    REGIME_W_EMA20_SMA50,
    REGIME_W_ATR_REGIME,
    REGIME_W_EMA8_EMA20,
    REGIME_K_CLOSE_EMA20,
    REGIME_K_CLOSE_SMA50,
    REGIME_K_SMA50_SLOPE,
    REGIME_K_CLOSE_SMA200,
    REGIME_K_EMA20_SMA50,
    REGIME_K_ATR_REGIME,
    REGIME_K_EMA8_EMA20,
    REGIME_CCI_OB_START,
    REGIME_CCI_OB_MAX,
    REGIME_CCI_MIN_MULT,
    REGIME_CCI_OS_LEVEL,
    REGIME_CCI_BOOST,
)


@dataclass
class RegimeWeights:
    """
    All tunable regime parameters — injectable by Optuna or WFO sweep.

    Weights need not sum to exactly 100; the scoring formula normalises by
    the actual sum so any positive values produce a valid 0.0–1.0 output.
    """
    # Component weights
    w_close_ema20:  float = REGIME_W_CLOSE_EMA20
    w_close_sma50:  float = REGIME_W_CLOSE_SMA50
    w_sma50_slope:  float = REGIME_W_SMA50_SLOPE
    w_close_sma200: float = REGIME_W_CLOSE_SMA200
    w_ema20_sma50:  float = REGIME_W_EMA20_SMA50
    w_atr:          float = REGIME_W_ATR_REGIME
    w_ema8_ema20:   float = REGIME_W_EMA8_EMA20
    # Sigmoid steepness params
    k_close_ema20:  float = REGIME_K_CLOSE_EMA20
    k_close_sma50:  float = REGIME_K_CLOSE_SMA50
    k_sma50_slope:  float = REGIME_K_SMA50_SLOPE
    k_close_sma200: float = REGIME_K_CLOSE_SMA200
    k_ema20_sma50:  float = REGIME_K_EMA20_SMA50
    k_atr:          float = REGIME_K_ATR_REGIME
    k_ema8_ema20:   float = REGIME_K_EMA8_EMA20
    # CCI multiplier params
    cci_ob_start:   float = REGIME_CCI_OB_START
    cci_ob_max:     float = REGIME_CCI_OB_MAX
    cci_min_mult:   float = REGIME_CCI_MIN_MULT
    cci_os_level:   float = REGIME_CCI_OS_LEVEL
    cci_boost:      float = REGIME_CCI_BOOST


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sigmoid_series(x: pd.Series, k: float) -> pd.Series:
    """Vectorised logistic sigmoid σ(x · k) → (0, 1)."""
    return 1.0 / (1.0 + np.exp(-x * k))


def _cci_multiplier_series(
    close: pd.Series,
    high: Optional[pd.Series],
    low: Optional[pd.Series],
    weights: RegimeWeights,
    period: int = 20,
) -> pd.Series:
    """
    CCI-based score multiplier aligned to *close* index.

    Uses Typical Price (H+L+C)/3 when H/L are available, else falls back to Close.
    Returns a float Series clamped to [cci_min_mult, cci_boost].
    """
    tp = (high + low + close) / 3.0 if (high is not None and low is not None) else close
    tp_sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    denom = (0.015 * mad).replace(0.0, np.nan)
    cci = ((tp - tp_sma) / denom).fillna(0.0)

    mult = pd.Series(1.0, index=close.index, dtype=float)

    # Overbought penalty: linear 1.0 → cci_min_mult over [ob_start, ob_max]
    ob_range = max(weights.cci_ob_max - weights.cci_ob_start, 1e-9)
    ob_mask  = cci > weights.cci_ob_start
    penalty  = ((cci - weights.cci_ob_start) / ob_range).clip(0.0, 1.0)
    penalty_mult = 1.0 - penalty * (1.0 - weights.cci_min_mult)
    mult = mult.where(~ob_mask, other=penalty_mult)

    # Oversold boost: CCI < os_level AND turning up (CCI[t] > CCI[t-1])
    os_mask = (cci < weights.cci_os_level) & (cci > cci.shift(1))
    mult = mult.where(~os_mask, other=weights.cci_boost)

    return mult.clip(weights.cci_min_mult, weights.cci_boost)


def _extract_ohlc(spy_df: pd.DataFrame):
    """
    Extract (close, high, low) Series from spy_df, handling MultiIndex columns.
    Returns (close, high_or_None, low_or_None).
    """
    df = spy_df
    if isinstance(df.columns, pd.MultiIndex):
        lvl1 = df.columns.get_level_values(1)
        if "SPY" in lvl1:
            df = df.xs("SPY", axis=1, level=1, drop_level=True)
        else:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)

    close = None
    for col in ("Close", "Adj Close"):
        if col in df.columns:
            c = df[col]
            close = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
            break
    if close is None:
        close = df.iloc[:, 0]

    def _get(col):
        if col not in df.columns:
            return None
        s = df[col]
        return s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s

    return close, _get("High"), _get("Low")


# ── Public API ────────────────────────────────────────────────────────────────

def compute_regime_score_series(
    spy_df: pd.DataFrame,
    weights: Optional[RegimeWeights] = None,
) -> pd.Series:
    """
    Vectorised continuous regime scoring. Returns float Series 0.0–100.0,
    same index as *spy_df*.

    Parameters
    ----------
    spy_df  : pd.DataFrame — SPY daily OHLCV (High/Low used when present).
              Falls back to Close-only ATR approximation if High/Low absent.
    weights : RegimeWeights — override defaults for Optuna/WFO sweeps.

    Notes
    -----
    SMA200 warmup requires ~200 bars. Bars before that produce lower F4 scores.
    Caller guards (filters.py _REGIME_MIN_BARS=65) protect against early-series
    noise. SMA200 fills in gracefully as data accumulates — no hard cutoff here.
    """
    if weights is None:
        weights = RegimeWeights()

    if spy_df is None or len(spy_df) < 20:
        idx = spy_df.index if spy_df is not None else pd.DatetimeIndex([])
        return pd.Series(0.0, index=idx, dtype=float)

    close, high, low = _extract_ohlc(spy_df)

    # ── Indicators ────────────────────────────────────────────────────────────
    ema8   = close.ewm(span=8,   adjust=False).mean()
    ema20  = close.ewm(span=20,  adjust=False).mean()
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    if high is not None and low is not None:
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
    else:
        # Close-only fallback: approximate TR via consecutive-bar abs difference
        tr = close.diff().abs()

    atr14    = tr.rolling(14).mean()
    atr50sma = atr14.rolling(50).mean()
    safe_atr = atr14.replace(0.0, np.nan)

    # ── F1: Close vs EMA20 ────────────────────────────────────────────────────
    f1 = _sigmoid_series((close - ema20) / safe_atr.fillna(1.0), weights.k_close_ema20) * weights.w_close_ema20

    # ── F2: Close vs SMA50 ────────────────────────────────────────────────────
    d_sma50 = ((close - sma50) / safe_atr).fillna(0.0)
    f2 = _sigmoid_series(d_sma50, weights.k_close_sma50) * weights.w_close_sma50

    # ── F3: SMA50 5-bar slope ─────────────────────────────────────────────────
    sma50_shift5 = sma50.shift(5).replace(0.0, np.nan)
    sma50_slope  = ((sma50 - sma50_shift5) / sma50_shift5).fillna(0.0)
    f3 = _sigmoid_series(sma50_slope, weights.k_sma50_slope) * weights.w_sma50_slope

    # ── F4: Close vs SMA200 (heaviest weight) ─────────────────────────────────
    # SMA200 is NaN for first 199 bars; fill with 0.0 so σ(0)=0.5 (neutral)
    d_sma200 = ((close - sma200) / safe_atr).fillna(0.0)
    f4 = _sigmoid_series(d_sma200, weights.k_close_sma200) * weights.w_close_sma200

    # ── F5: EMA20 vs SMA50 (stack alignment) ─────────────────────────────────
    d_ema20_sma50 = ((ema20 - sma50) / safe_atr).fillna(0.0)
    f5 = _sigmoid_series(d_ema20_sma50, weights.k_ema20_sma50) * weights.w_ema20_sma50

    # ── F6: ATR Regime — inverted, low vol = stable ───────────────────────────
    safe_atr50 = atr50sma.replace(0.0, np.nan)
    atr_ratio  = (atr14 / safe_atr50 - 1.0).fillna(0.0)
    f6 = (1.0 - _sigmoid_series(atr_ratio, weights.k_atr)) * weights.w_atr

    # ── F7: EMA8 vs EMA20 (short-term momentum) ───────────────────────────────
    d_ema8_ema20 = ((ema8 - ema20) / safe_atr).fillna(0.0)
    f7 = _sigmoid_series(d_ema8_ema20, weights.k_ema8_ema20) * weights.w_ema8_ema20

    # ── Weighted sum → 0.0–1.0 then scaled to 0.0–100.0 ─────────────────────
    w_sum = (weights.w_close_ema20 + weights.w_close_sma50 + weights.w_sma50_slope
             + weights.w_close_sma200 + weights.w_ema20_sma50
             + weights.w_atr + weights.w_ema8_ema20)
    raw = (f1 + f2 + f3 + f4 + f5 + f6 + f7) / w_sum

    # ── CCI multiplier ────────────────────────────────────────────────────────
    cci_mult = _cci_multiplier_series(close, high, low, weights)
    cci_mult = cci_mult.reindex(raw.index).fillna(1.0)

    score = (raw * cci_mult).clip(0.0, 1.0) * 100.0
    return score.reindex(spy_df.index).fillna(0.0)


def compute_volatility_scalar_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return ATR14 / close as a fraction-of-price series (same index as spy_df).

    Typical range: 0.01–0.06 (1%–6% of price per ATR unit).
    Used by callers to scale position sizing or risk parameters dynamically.
    Returns 0.02 (neutral default) where data is insufficient.
    """
    if spy_df is None or len(spy_df) < 15:
        idx = spy_df.index if spy_df is not None else pd.DatetimeIndex([])
        return pd.Series(0.02, index=idx, dtype=float)

    close, high, low = _extract_ohlc(spy_df)

    if high is not None and low is not None:
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
    else:
        tr = close.diff().abs()

    atr14     = tr.rolling(14).mean()
    safe_close = close.replace(0.0, np.nan)
    scalar    = (atr14 / safe_close).fillna(0.02).clip(0.005, 0.15)
    return scalar.reindex(spy_df.index).fillna(0.02)


def check_market_regime(
    breadth_pct: float = 0.5,
    hl_ratio: float = 0.5,
) -> Dict:
    """
    Fetch SPY 1y data and compute the continuous regime score for the live scanner.

    breadth_pct / hl_ratio are retained in the signature for backward compatibility
    but are no longer used in scoring — SPY-only model eliminates train-serve skew.

    Returns
    -------
    dict
        is_bullish         : bool    — regime_score >= REGIME_SELECTIVE_THRESHOLD
        regime_score       : float   — 0.0–1.0
        regime             : str     — "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
        volatility_scalar  : float   — ATR14/close at last bar (fraction of price)
        spy_close          : float
        spy_20ema          : float
        spy_sma50          : float
        spy_sma200         : float
        vix                : float   — always 0.0 (removed from scoring)
        vix_sma20          : float   — always 0.0
        factors            : dict    — per-component contribution at last bar
    """
    try:
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

        if len(spy) < 22:
            return _error(f"Insufficient SPY data: {len(spy)} bars (need ≥22)")

        scores = compute_regime_score_series(spy)
        if scores.empty:
            return _error("compute_regime_score_series returned empty")

        regime_score = float(scores.iloc[-1])
        regime       = _score_to_regime(regime_score)
        is_bullish   = regime_score >= REGIME_SELECTIVE_THRESHOLD

        # Volatility scalar at last bar
        vol_scalars = compute_volatility_scalar_series(spy)
        volatility_scalar = float(vol_scalars.iloc[-1]) if not vol_scalars.empty else 0.02

        # ── Scalar indicators for the response dict ───────────────────────────
        close, high, low = _extract_ohlc(spy)
        close = close.dropna()

        def _last(s: pd.Series) -> float:
            s2 = s.dropna()
            if s2.empty:
                return 0.0
            v = s2.iloc[-1]
            f = float(v.item() if hasattr(v, "item") else v)
            return 0.0 if np.isnan(f) else f

        ema8_s   = close.ewm(span=8,   adjust=False).mean()
        ema20_s  = close.ewm(span=20,  adjust=False).mean()
        sma50_s  = close.rolling(50).mean()
        sma200_s = close.rolling(200).mean()

        if high is not None and low is not None:
            h = high if isinstance(high, pd.Series) else high.iloc[:, 0]
            l = low  if isinstance(low,  pd.Series) else low.iloc[:,  0]
            tr14 = pd.concat([h - l, (h - close.shift(1)).abs(), (l - close.shift(1)).abs()], axis=1).max(axis=1)
        else:
            tr14 = close.diff().abs()
        atr14_s    = tr14.rolling(14).mean()
        atr50sma_s = atr14_s.rolling(50).mean()

        w = RegimeWeights()
        safe_atr_s   = atr14_s.replace(0.0, np.nan)
        safe_atr50_s = atr50sma_s.replace(0.0, np.nan)

        f1_s = _sigmoid_series((close - ema20_s) / safe_atr_s, w.k_close_ema20) * w.w_close_ema20
        f2_s = _sigmoid_series((close - sma50_s) / safe_atr_s, w.k_close_sma50) * w.w_close_sma50
        sma50_shift5 = sma50_s.shift(5).replace(0.0, np.nan)
        slope5 = ((sma50_s - sma50_shift5) / sma50_shift5).fillna(0.0)
        f3_s  = _sigmoid_series(slope5, w.k_sma50_slope) * w.w_sma50_slope
        sma200_s2 = sma200_s.ffill()  # forward-fill for display
        f4_s  = _sigmoid_series((close - sma200_s2) / safe_atr_s, w.k_close_sma200) * w.w_close_sma200
        f5_s  = _sigmoid_series((ema20_s - sma50_s) / safe_atr_s, w.k_ema20_sma50) * w.w_ema20_sma50
        atr_r = (atr14_s / safe_atr50_s - 1.0).fillna(0.0)
        f6_s  = (1.0 - _sigmoid_series(atr_r, w.k_atr)) * w.w_atr
        f7_s  = _sigmoid_series((ema8_s - ema20_s) / safe_atr_s, w.k_ema8_ema20) * w.w_ema8_ema20

        return {
            "is_bullish":        is_bullish,
            "regime_score":      round(regime_score, 3),
            "regime":            regime,
            "volatility_scalar": round(volatility_scalar, 4),
            "spy_close":         round(_last(close), 2),
            "spy_20ema":         round(_last(ema20_s), 2),
            "spy_sma50":         round(_last(sma50_s), 2),
            "spy_sma200":        round(_last(sma200_s), 2),
            "vix":               0.0,
            "vix_sma20":         0.0,
            "breadth_pct":       round(breadth_pct, 3),
            "hl_ratio":          round(hl_ratio, 3),
            "factors": {
                "f1_close_ema20":  round(_last(f1_s), 3),
                "f2_close_sma50":  round(_last(f2_s), 3),
                "f3_sma50_slope":  round(_last(f3_s), 3),
                "f4_close_sma200": round(_last(f4_s), 3),
                "f5_ema20_sma50":  round(_last(f5_s), 3),
                "f6_atr":          round(_last(f6_s), 3),
                "f7_ema8_ema20":   round(_last(f7_s), 3),
            },
        }

    except Exception as exc:
        return _error(str(exc)[:120])


def _score_to_regime(score: float) -> str:
    if score >= REGIME_AGGRESSIVE_THRESHOLD:
        return "AGGRESSIVE"
    if score >= REGIME_SELECTIVE_THRESHOLD:
        return "SELECTIVE"
    return "DEFENSIVE"


def _error(msg: str) -> Dict:
    return {
        "is_bullish":        False,
        "regime_score":      0.0,
        "regime":            f"ERROR: {msg}",
        "volatility_scalar": 0.02,
        "spy_close":         0.0,
        "spy_20ema":         0.0,
        "spy_sma50":         0.0,
        "spy_sma200":        0.0,
        "vix":               0.0,
        "vix_sma20":         0.0,
        "breadth_pct":       0.5,
        "hl_ratio":          0.5,
        "factors":           {},
    }
