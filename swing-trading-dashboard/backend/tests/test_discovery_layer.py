"""Tests for _build_discovery_tickers in main.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest


def _make_cache_entry(close_arr, vol_arr):
    """Minimal ticker_cache entry: (timestamp_float, DataFrame)."""
    n   = len(close_arr)
    idx = pd.date_range(end="2026-03-07", periods=n, freq="B")
    df  = pd.DataFrame({
        "Open":      close_arr,
        "High":      np.array(close_arr) * 1.005,
        "Low":       np.array(close_arr) * 0.995,
        "Close":     close_arr,
        "Adj Close": close_arr,
        "Volume":    vol_arr,
    }, index=idx)
    return (0.0, df)


def _near_high_prices(n=252, peak_pct=0.01):
    """Price array ending within peak_pct of its own 52wk high."""
    prices = [100.0] * n
    prices[5]  = 102.0           # 52-week high
    prices[-1] = 102.0 * (1 - peak_pct)  # within threshold
    return prices


def _expanding_vol(n=252, base=1_000_000, last5_mult=2.0):
    """Volume array where last 5 bars avg last5_mult× the 50d avg."""
    vol = [base] * n
    for i in range(-5, 0):
        vol[i] = int(base * last5_mult)
    return vol


def test_valid_discovery_candidate_included():
    """RS 65, near high, vol expanding → should be in discovery set."""
    from main import _build_discovery_tickers
    cache  = {"AAPL": _make_cache_entry(_near_high_prices(), _expanding_vol())}
    result = _build_discovery_tickers(["AAPL"], {"AAPL": 65.0}, cache)
    assert "AAPL" in result


def test_rs_above_max_excluded():
    """RS 75 >= DISCOVERY_RS_MAX (70) → not a discovery candidate."""
    from main import _build_discovery_tickers
    cache  = {"AAPL": _make_cache_entry(_near_high_prices(), _expanding_vol())}
    result = _build_discovery_tickers(["AAPL"], {"AAPL": 75.0}, cache)
    assert "AAPL" not in result


def test_rs_below_min_excluded():
    """RS 55 < DISCOVERY_RS_MIN (60) → not a discovery candidate."""
    from main import _build_discovery_tickers
    cache  = {"AAPL": _make_cache_entry(_near_high_prices(), _expanding_vol())}
    result = _build_discovery_tickers(["AAPL"], {"AAPL": 55.0}, cache)
    assert "AAPL" not in result


def test_price_not_near_52wk_high_excluded():
    """RS in range but close is 10% below 52wk high → excluded."""
    from main import _build_discovery_tickers
    prices     = [100.0] * 252
    prices[5]  = 120.0   # 52wk high = 120
    prices[-1] = 108.0   # 10% below high; fails 3% threshold
    cache  = {"MSFT": _make_cache_entry(prices, _expanding_vol())}
    result = _build_discovery_tickers(["MSFT"], {"MSFT": 65.0}, cache)
    assert "MSFT" not in result


def test_volume_not_expanding_excluded():
    """RS in range, near high, but 5d vol = 0.8× 50d avg (contracting) → excluded."""
    from main import _build_discovery_tickers
    vol    = _expanding_vol(last5_mult=0.8)  # contracting
    cache  = {"NVDA": _make_cache_entry(_near_high_prices(), vol)}
    result = _build_discovery_tickers(["NVDA"], {"NVDA": 65.0}, cache)
    assert "NVDA" not in result


def test_discovery_capped_at_max_pct():
    """Discovery set must not exceed DISCOVERY_MAX_PCT (10%) of universe size."""
    from main import _build_discovery_tickers
    n_tickers = 30
    tickers   = [f"T{i}" for i in range(n_tickers)]
    cache     = {t: _make_cache_entry(_near_high_prices(), _expanding_vol()) for t in tickers}
    rs_map    = {t: 65.0 for t in tickers}  # all qualify for RS range
    result    = _build_discovery_tickers(tickers, rs_map, cache)
    assert len(result) <= int(n_tickers * 0.10)  # cap = 3 tickers (10% of 30)
