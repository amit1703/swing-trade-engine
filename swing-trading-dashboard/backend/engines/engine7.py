"""
Engine 7: Options Catalyst Scanner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detects unusual near-term (7-45 DTE) call options activity on liquid tickers.

Signal: Smart Money aggressively buying OTM calls = potential catalyst.
Technical confirmation is intentionally relaxed (close > SMA50, not a
falling knife) because the options flow itself is the primary signal.
"""

import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from constants import (
    OPTIONS_CALL_VOL_TARGET,
    OPTIONS_DTE_MAX,
    OPTIONS_DTE_MIN,
    OPTIONS_IV_SLOPE_TARGET,
    OPTIONS_MIN_ADV,
    OPTIONS_MIN_PRICE,
    OPTIONS_MIN_SCORE,
    OPTIONS_OTM_MAX_PCT,
    OPTIONS_SKEW_MAX,
    OPTIONS_SKEW_NEUTRAL,
    OPTIONS_VOL_OI_TARGET,
)


def _days_to_expiry(expiry_str: str) -> int:
    """Return calendar days from today to expiry_str (YYYY-MM-DD)."""
    expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    return (expiry - date.today()).days


def _passes_liquidity_filter(df: pd.DataFrame) -> bool:
    """50-day avg volume > OPTIONS_MIN_ADV AND last close > OPTIONS_MIN_PRICE."""
    avg_vol = float(df["Volume"].tail(50).mean())
    close = float(df["Close"].iloc[-1])
    return bool(avg_vol >= OPTIONS_MIN_ADV and close >= OPTIONS_MIN_PRICE)


def _passes_technical_filter(df: pd.DataFrame) -> bool:
    """
    Relaxed technical confirmation — two conditions, both required:
      1. close > SMA50  (basic uptrend, not a broken chart)
      2. close > close[-10]  (not a falling knife over last 2 weeks)
    """
    if len(df) < 50:
        return False
    close = float(df["Close"].iloc[-1])
    sma50 = float(df["Close"].tail(50).mean())
    close_10d_ago = float(df["Close"].iloc[-11]) if len(df) >= 11 else float(df["Close"].iloc[0])
    return bool(close > sma50 and close > close_10d_ago)


def _fetch_options_data(ticker: str, current_close: float) -> Optional[Dict]:
    """
    Fetch near-term (OPTIONS_DTE_MIN to OPTIONS_DTE_MAX) call option chains
    from yfinance and compute aggregated metrics.

    Returns a metrics dict or None if insufficient/no options data.
    Exceptions are caught and return None (illiquid or no options listed).
    """
    try:
        t = yf.Ticker(ticker)
        all_expiries = t.options
        if not all_expiries:
            return None

        near_expiries = [
            e for e in all_expiries
            if OPTIONS_DTE_MIN <= _days_to_expiry(e) <= OPTIONS_DTE_MAX
        ]
        if not near_expiries:
            return None

        min_strike = current_close * 1.00
        max_strike = current_close * (1.0 + OPTIONS_OTM_MAX_PCT)

        calls_list: List[pd.DataFrame] = []
        put_vol_total = 0

        for expiry in near_expiries:
            chain = t.option_chain(expiry)
            calls_df = chain.calls
            puts = chain.puts

            # 0–10% OTM calls with real volume and open interest
            mask = (
                (calls_df["strike"] >= min_strike)
                & (calls_df["strike"] <= max_strike)
                & (calls_df["volume"].fillna(0) > 0)
                & (calls_df["openInterest"].fillna(0) > 0)
            )
            filtered = calls_df[mask].copy()
            filtered["expiry"] = expiry  # track which expiry each row came from
            calls_list.append(filtered)
            put_vol_total += float(puts["volume"].fillna(0).sum())

        otm_calls_list = calls_list  # alias kept for concat below

        if not otm_calls_list:
            return None

        combined = pd.concat(otm_calls_list, ignore_index=True)
        if combined.empty:
            return None

        total_call_vol = float(combined["volume"].fillna(0).sum())
        if total_call_vol == 0:
            return None

        # Vol/OI ratio (new positioning signal)
        valid = combined[combined["openInterest"] > 0].copy()
        valid["volume"] = valid["volume"].fillna(0)  # treat sparse yfinance volume as 0
        if valid.empty:
            return None
        avg_vol_oi = float((valid["volume"] / valid["openInterest"]).mean())

        # Call/Put skew
        denom = total_call_vol + put_vol_total
        call_put_ratio = total_call_vol / denom if denom > 0 else 0.5

        # IV near-term
        iv_vals = combined[combined["impliedVolatility"] > 0]["impliedVolatility"]
        iv_near = float(iv_vals.mean()) if not iv_vals.empty else 0.0

        # IV term structure (front month vs second expiry only — clean 2-point slope)
        iv_next = iv_near  # default: flat term structure
        iv_term_slope = 1.0
        if len(near_expiries) > 1:
            try:
                chain2 = t.option_chain(near_expiries[1])
                mask2 = (
                    (chain2.calls["strike"] >= min_strike)
                    & (chain2.calls["strike"] <= max_strike)
                    & (chain2.calls["impliedVolatility"].fillna(0) > 0)
                )
                next_calls = chain2.calls[mask2]
                if not next_calls.empty:
                    iv_next = float(next_calls["impliedVolatility"].mean())
                    if iv_next > 0:
                        iv_term_slope = iv_near / iv_next
            except Exception:
                pass  # keep iv_next = iv_near (flat term structure)

        # Dominant strike (highest volume) — expiry reflects that strike's actual expiry
        dominant_idx = combined["volume"].idxmax()
        dominant_strike = float(combined.loc[dominant_idx, "strike"])
        dominant_expiry = combined.loc[dominant_idx, "expiry"]  # actual expiry of dominant row
        dte = _days_to_expiry(dominant_expiry)                  # recalculate from dominant

        return {
            "total_call_volume": int(total_call_vol),
            "call_put_ratio":    round(call_put_ratio, 3),
            "avg_vol_oi_ratio":  round(avg_vol_oi, 3),
            "iv_near":           round(iv_near, 3),
            "iv_next":           round(iv_next, 3),
            "iv_term_slope":     round(iv_term_slope, 3),
            "dominant_strike":   dominant_strike,
            "dominant_expiry":   dominant_expiry,
            "dte":               dte,
        }

    except Exception:  # noqa: BLE001
        return None


def _compute_score(metrics: Dict) -> float:
    """
    Composite OPTIONS_SCORE (0–100) from four components:
      30 pts  Vol/OI ratio     — new positioning vs rolling
      25 pts  Absolute volume  — raw size of the bet
      25 pts  Call/Put skew    — directional conviction
      20 pts  IV term slope    — near-term urgency
    """
    score = 0.0
    score += min(metrics["avg_vol_oi_ratio"] / OPTIONS_VOL_OI_TARGET, 1.0) * 30
    score += min(metrics["total_call_volume"] / OPTIONS_CALL_VOL_TARGET, 1.0) * 25
    skew_component = (metrics["call_put_ratio"] - OPTIONS_SKEW_NEUTRAL) / (
        OPTIONS_SKEW_MAX - OPTIONS_SKEW_NEUTRAL
    )
    score += min(max(skew_component, 0.0), 1.0) * 25
    slope_component = (metrics["iv_term_slope"] - 1.0) / OPTIONS_IV_SLOPE_TARGET
    score += min(max(slope_component, 0.0), 1.0) * 20
    return round(score, 1)


def scan_options_catalyst(ticker: str, df: pd.DataFrame) -> Optional[Dict]:
    """
    Engine 7 entry point.

    Returns an OPTIONS_CATALYST setup dict or None.
    Runs in loop.run_in_executor() — must remain synchronous.
    """
    if not _passes_liquidity_filter(df):
        return None

    if not _passes_technical_filter(df):
        return None

    current_close = float(df["Close"].iloc[-1])

    metrics = _fetch_options_data(ticker, current_close)
    if metrics is None:
        return None

    options_score = _compute_score(metrics)
    if options_score < OPTIONS_MIN_SCORE:
        return None

    return {
        "ticker":      ticker,
        "setup_type":  "OPTIONS_CATALYST",
        "entry":       round(current_close, 2),
        "stop_loss":   round(current_close * 0.95, 2),
        "take_profit": round(current_close * 1.10, 2),
        "rr":          2.0,
        "setup_date":  date.today().isoformat(),
        "options_score": options_score,
        **metrics,
    }
