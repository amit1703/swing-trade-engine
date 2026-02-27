"""Tests for calculate_rs_score — O'Neil composite RS formula.

Formula:
  rs_score = (63d × 40%) + (126d × 20%) + (189d × 20%) + (252d × 20%)

Each component = stock_period_return − spy_period_return.
Positive = stock outperforming SPY on a weighted basis.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine4 import calculate_rs_score


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(n, default=100.0, overrides=None):
    """
    Build a DataFrame with `n` bars, all Close = `default`.
    `overrides` maps {lookback_period: price} → sets prices[n - period] = price.
    Only the last-bar price and the lookback prices matter for the formula.
    """
    prices = np.full(n, default, dtype=float)
    if overrides:
        for period, price in overrides.items():
            prices[-period] = price
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": prices}, index=dates)


# ── Weight & formula contract ─────────────────────────────────────────────────

def test_weights_sum_to_one_for_full_outperformance():
    """
    Stock doubles at every lookback, SPY flat → rs_score ≈ 1.0
    (100% outperformance × total weight 1.0).
    """
    # close[-1] = 100, all lookback bars = 50  →  all period returns = 100%
    df_stock = _make_df(300, default=50.0, overrides={1: 100.0})
    df_spy   = _make_df(300, default=100.0)  # SPY flat, 0% all periods

    score = calculate_rs_score(df_stock, df_spy)
    assert abs(score - 1.0) < 0.01, f"Expected ≈ 1.0, got {score}"


def test_63d_component_has_40pct_weight():
    """
    Only 63-day period has outperformance (+100%); all others = flat.
    Score should be exactly 0.40 × 1.0 = 0.40.
    """
    # close[-63] = 50, last = 100 → 100% return on 63d
    # All other lookback bars = 100 (same as last bar) → 0% on 126/189/252d
    df_stock = _make_df(300, default=100.0, overrides={63: 50.0})
    df_spy   = _make_df(300, default=100.0)

    score = calculate_rs_score(df_stock, df_spy)
    assert abs(score - 0.40) < 0.01, f"Expected ≈ 0.40, got {score}"


def test_exact_formula_calculation():
    """
    Verify exact numbers for mixed outperformance across all four periods.

    Stock returns: 63d=10%, 126d=18%, 189d=25%, 252d=30%
    SPY  returns: 63d= 5%, 126d=10%, 189d=15%, 252d=20%

    Expected:
      (10%-5%) × 0.40 = 0.020
      (18%-10%) × 0.20 = 0.016
      (25%-15%) × 0.20 = 0.020
      (30%-20%) × 0.20 = 0.020
      Total             = 0.076
    """
    df_stock = _make_df(300, default=100.0, overrides={
        63:  100.0 / 1.10,   # 63d return  = 10%
        126: 100.0 / 1.18,   # 126d return = 18%
        189: 100.0 / 1.25,   # 189d return = 25%
        252: 100.0 / 1.30,   # 252d return = 30%
    })
    df_spy = _make_df(300, default=100.0, overrides={
        63:  100.0 / 1.05,   # 63d return  =  5%
        126: 100.0 / 1.10,   # 126d return = 10%
        189: 100.0 / 1.15,   # 189d return = 15%
        252: 100.0 / 1.20,   # 252d return = 20%
    })

    score = calculate_rs_score(df_stock, df_spy)
    assert abs(score - 0.076) < 0.002, f"Expected ≈ 0.076, got {score}"


# ── Sign direction ────────────────────────────────────────────────────────────

def test_positive_score_when_stock_outperforms():
    """Stock returns 40%, SPY flat → score > 0."""
    df_stock = _make_df(300, default=60.0, overrides={1: 100.0})
    df_spy   = _make_df(300, default=100.0)
    assert calculate_rs_score(df_stock, df_spy) > 0


def test_negative_score_when_stock_underperforms():
    """Stock flat, SPY up 20% on all periods → score < 0."""
    df_stock = _make_df(300, default=100.0)
    df_spy   = _make_df(300, default=100.0 / 1.20, overrides={1: 100.0})
    assert calculate_rs_score(df_stock, df_spy) < 0


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_no_spy_df_uses_raw_stock_returns():
    """
    spy_df=None → spy_ret=0 for all periods.
    Stock +50% on 63d, flat on 126/189/252d → score = 0.40 × 0.50 = 0.20.
    """
    df_stock = _make_df(300, default=100.0, overrides={63: 100.0 / 1.50})
    score = calculate_rs_score(df_stock, None)
    assert abs(score - 0.20) < 0.01, f"Expected ≈ 0.20, got {score}"


def test_insufficient_data_returns_zero():
    """Fewer than 64 bars of data → can't compute any period → 0.0."""
    df_stock = _make_df(50, default=100.0)
    df_spy   = _make_df(50, default=100.0)
    assert calculate_rs_score(df_stock, df_spy) == 0.0


def test_partial_history_uses_available_periods():
    """
    80 bars: only the 63-day period qualifies (126/189/252 skipped).
    Stock +100% on 63d, spy flat → score = 0.40.
    """
    df_stock = _make_df(80, default=50.0, overrides={1: 100.0})
    df_spy   = _make_df(80, default=100.0)
    score = calculate_rs_score(df_stock, df_spy)
    assert abs(score - 0.40) < 0.01, f"Expected ≈ 0.40 (partial), got {score}"
