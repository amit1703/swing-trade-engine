import asyncio
import time

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
from unittest.mock import patch, MagicMock, AsyncMock

import main as m
from main import _fetch
from constants import FETCH_MAX_RETRIES, CACHE_TTL_SUCCESS, CACHE_TTL_FAILURE


def _make_df(n=300):
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    prices = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [p - 0.5 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [2_000_000] * n,
    }, index=dates)


@pytest.fixture(autouse=True)
def clear_cache():
    m._ticker_cache.clear()
    # _semaphore is normally initialized by the FastAPI lifespan; set it for tests
    original_semaphore = m._semaphore
    m._semaphore = asyncio.Semaphore(1)
    yield
    m._ticker_cache.clear()
    m._semaphore = original_semaphore


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_cache_hit_avoids_second_yfinance_call(mock_sleep):
    """Second _fetch for same ticker uses cache — yfinance not called again."""
    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = _make_df()
        mock_ticker.return_value = mock_instance

        df1 = asyncio.run(_fetch('AAPL'))
        df2 = asyncio.run(_fetch('AAPL'))

        assert df1 is not None
        assert df2 is df1                          # same object — cache hit
        mock_instance.history.assert_called_once() # yfinance called exactly once


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_failure_is_negatively_cached(mock_sleep):
    """Fetch failure is cached as None; second call skips yfinance entirely."""
    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = pd.DataFrame()  # empty → all retries fail
        mock_ticker.return_value = mock_instance

        result1 = asyncio.run(_fetch('FAIL'))
        result2 = asyncio.run(_fetch('FAIL'))

        assert result1 is None
        assert result2 is None
        # First call exhausts all retry attempts; second call is a negative-cache hit
        expected_attempts = FETCH_MAX_RETRIES + 1  # initial attempt + FETCH_MAX_RETRIES retries
        assert mock_instance.history.call_count == expected_attempts


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_stale_success_entry_triggers_refetch(mock_sleep):
    """After CACHE_TTL_SUCCESS seconds, a stale cache entry triggers re-fetch."""
    df = _make_df()
    # Pre-populate cache with a timestamp older than the success TTL
    m._ticker_cache['GOOG'] = (time.time() - CACHE_TTL_SUCCESS - 1, df)

    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = _make_df()
        mock_ticker.return_value = mock_instance

        result = asyncio.run(_fetch('GOOG'))

        assert result is not None
        mock_instance.history.assert_called_once()  # re-fetched after TTL expiry


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_stale_failure_entry_triggers_refetch(mock_sleep):
    """After CACHE_TTL_FAILURE seconds, a negatively-cached ticker re-fetches."""
    # Pre-populate cache with a stale None entry
    m._ticker_cache['BAD'] = (time.time() - CACHE_TTL_FAILURE - 1, None)

    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = _make_df()
        mock_ticker.return_value = mock_instance

        result = asyncio.run(_fetch('BAD'))

        assert result is not None
        mock_instance.history.assert_called_once()  # re-fetched after failure TTL expiry
