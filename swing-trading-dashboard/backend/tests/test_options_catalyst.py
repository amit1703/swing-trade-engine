"""
TDD tests for Engine 7 — Options Catalyst scanner.

Tests cover the three helper functions independently, then validate the
top-level scan_options_catalyst() with mocked options data.
"""

import numpy as np
import pandas as pd
import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engines.engine7 import (
    _passes_liquidity_filter,
    _passes_technical_filter,
    _compute_score,
    scan_options_catalyst,
)
from constants import OPTIONS_MIN_SCORE


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def _make_flat_df(n: int = 200, avg_vol: int = 2_000_000, price: float = 50.0) -> pd.DataFrame:
    """Flat prices at `price` for `n` bars — good for liquidity filter tests."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [price - 0.2] * n,
        "High":      [price + 0.5] * n,
        "Low":       [price - 0.5] * n,
        "Close":     [price] * n,
        "Adj Close": [price] * n,
        "Volume":    [avg_vol] * n,
    }, index=dates)


def _make_trending_df(
    n: int = 200, avg_vol: int = 2_000_000, start: float = 50.0, step: float = 0.1
) -> pd.DataFrame:
    """Linearly trending prices — for technical filter and integration tests."""
    prices = [start + i * step for i in range(n)]
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [p - 0.5 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [avg_vol] * n,
    }, index=dates)


def _make_downtrending_df(
    n: int = 200, avg_vol: int = 2_000_000, start: float = 100.0, step: float = 0.1
) -> pd.DataFrame:
    """Linearly declining prices — for technical filter failure tests."""
    prices = [max(start - i * step, 0.01) for i in range(n)]
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [max(p - 0.5, 0.01) for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [avg_vol] * n,
    }, index=dates)


# ── _passes_liquidity_filter ──────────────────────────────────────────────────

def test_liquidity_passes_high_volume_and_price():
    df = _make_flat_df(avg_vol=2_000_000, price=50.0)
    assert _passes_liquidity_filter(df) is True


def test_liquidity_fails_low_volume():
    df = _make_flat_df(avg_vol=500_000, price=50.0)
    assert _passes_liquidity_filter(df) is False


def test_liquidity_fails_low_price():
    df = _make_flat_df(avg_vol=2_000_000, price=8.0)
    assert _passes_liquidity_filter(df) is False


# ── _passes_technical_filter ──────────────────────────────────────────────────

def test_technical_passes_uptrending_stock():
    # start=50, step=0.1, n=200 → last close ≈ 69.9, SMA50 ≈ 67.5 → close > SMA50 ✓
    # close[-1]=69.9 > close[-11]=68.9 ✓
    df = _make_trending_df(n=200, start=50.0, step=0.1)
    assert _passes_technical_filter(df) is True


def test_technical_fails_downtrending_stock():
    # start=100, step=0.1, n=200 → last close ≈ 80.1, SMA50 ≈ 82.6 → close < SMA50 ✗
    df = _make_downtrending_df(n=200, start=100.0, step=0.1)
    assert _passes_technical_filter(df) is False


# ── _compute_score ────────────────────────────────────────────────────────────

def test_compute_score_max_inputs_returns_100():
    metrics = {
        "avg_vol_oi_ratio":  2.0,   # capped → 30 pts
        "total_call_volume": 5000,  # capped → 25 pts
        "call_put_ratio":    0.95,  # capped → 25 pts
        "iv_term_slope":     1.40,  # capped → 20 pts
    }
    assert _compute_score(metrics) == pytest.approx(100.0, abs=0.1)


def test_compute_score_neutral_inputs_returns_zero():
    metrics = {
        "avg_vol_oi_ratio":  0.0,
        "total_call_volume": 0,
        "call_put_ratio":    0.5,   # neutral → 0 pts
        "iv_term_slope":     1.0,   # flat → 0 pts
    }
    assert _compute_score(metrics) == pytest.approx(0.0, abs=0.1)


def test_compute_score_partial_inputs_below_threshold():
    # vol/oi=1.0 (30pts) + call_vol=2000 (25pts) = 55pts < OPTIONS_MIN_SCORE=60
    metrics = {
        "avg_vol_oi_ratio":  1.0,
        "total_call_volume": 2000,
        "call_put_ratio":    0.5,   # neutral → 0 pts
        "iv_term_slope":     1.0,   # flat → 0 pts
    }
    assert _compute_score(metrics) < OPTIONS_MIN_SCORE


# ── scan_options_catalyst integration ────────────────────────────────────────

def test_scan_returns_none_for_illiquid_ticker():
    df = _make_flat_df(avg_vol=100_000, price=50.0)
    # No yfinance call should be made — pre-filter rejects immediately
    result = scan_options_catalyst("ILLIQ", df)
    assert result is None


def test_scan_returns_setup_when_all_conditions_met():
    # Trending stock: avg_vol=5M, price 50→70 over 200 bars → passes both filters
    df = _make_trending_df(n=200, avg_vol=5_000_000, start=50.0, step=0.1)

    high_score_metrics = {
        "total_call_volume": 5000,
        "call_put_ratio":    0.90,
        "avg_vol_oi_ratio":  1.5,
        "iv_near":           0.50,
        "iv_next":           0.38,
        "iv_term_slope":     1.32,
        "dominant_strike":   72.0,
        "dominant_expiry":   "2026-03-21",
        "dte":               21,
    }
    # Score: 30 + 25 + 25 + min(0.32/0.30, 1)*20 = 100 → well above threshold

    with patch("engines.engine7._fetch_options_data", return_value=high_score_metrics):
        result = scan_options_catalyst("STRONG", df)

    assert result is not None
    assert result["setup_type"] == "OPTIONS_CATALYST"
    assert result["ticker"] == "STRONG"
    assert result["options_score"] >= OPTIONS_MIN_SCORE
    assert result["take_profit"] > result["entry"] > result["stop_loss"]
    assert result["rr"] == 2.0
