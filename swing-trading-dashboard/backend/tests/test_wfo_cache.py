"""Tests for WFO data cache layer."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import wfo_cache
from constants import WFO_MIN_HISTORY_YEARS


def _make_df(years=6, base_price=100.0):
    """Create a clean OHLCV DataFrame with enough history."""
    n = int(years * 252)
    dates = pd.date_range("2014-01-01", periods=n, freq="B")
    close = np.linspace(base_price * 0.5, base_price, n)
    return pd.DataFrame(
        {
            "Open":   close * 0.99,
            "High":   close * 1.01,
            "Low":    close * 0.98,
            "Close":  close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )


def test_get_cache_path_returns_parquet_path(tmp_path):
    """get_cache_path returns a .parquet path inside the cache dir."""
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        p = wfo_cache.get_cache_path("AAPL")
    assert str(p).endswith("AAPL.parquet")
    assert "AAPL" in str(p)


def test_cache_exists_false_for_missing(tmp_path):
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        assert wfo_cache.cache_exists("MISSING") is False


def test_cache_exists_true_after_write(tmp_path):
    df = _make_df()
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        df.to_parquet(wfo_cache.get_cache_path("AAPL"))
        assert wfo_cache.cache_exists("AAPL") is True


def test_load_ticker_returns_none_for_missing(tmp_path):
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        result = wfo_cache.load_ticker("NONEXISTENT")
    assert result is None


def test_load_ticker_roundtrip(tmp_path):
    """load_ticker reads back what was saved."""
    df = _make_df()
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        df.to_parquet(wfo_cache.get_cache_path("TEST"))
        result = wfo_cache.load_ticker("TEST")
    assert result is not None
    assert len(result) == len(df)
    assert list(result.columns) == list(df.columns)


def test_integrity_check_drops_nan_rows():
    """_integrity_check drops rows with NaN in OHLC columns."""
    df = _make_df(years=6)
    df.iloc[10, df.columns.get_loc("Close")] = float("nan")
    result = wfo_cache._integrity_check(df, "TEST")
    assert result is not None
    assert len(result) == len(df) - 1  # one row dropped


def test_integrity_check_rejects_short_history():
    """_integrity_check returns None when history < WFO_MIN_HISTORY_YEARS."""
    df = _make_df(years=WFO_MIN_HISTORY_YEARS - 1)
    result = wfo_cache._integrity_check(df, "SHORT")
    assert result is None


def test_integrity_check_sorts_ascending():
    """_integrity_check sorts the DataFrame by date ascending."""
    df = _make_df(years=6)
    df = df.iloc[::-1]  # reverse order
    result = wfo_cache._integrity_check(df, "TEST")
    assert result is not None
    assert result.index.is_monotonic_increasing
