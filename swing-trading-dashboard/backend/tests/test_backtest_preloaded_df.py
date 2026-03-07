"""Tests for BacktestEngine preloaded-df support (WFO integration)."""
import os
import sys
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest_engine import BacktestEngine


def _make_ticker_df(n=400, base_price=100.0):
    """Uptrending OHLCV DataFrame with enough warmup bars."""
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.linspace(80.0, base_price, n)
    return pd.DataFrame(
        {
            "Open":      close * 0.99,
            "High":      close * 1.01,
            "Low":       close * 0.98,
            "Close":     close,
            "Adj Close": close,
            "Volume":    np.full(n, 1_000_000.0),
        },
        index=dates,
    )


def _make_spy_df(n=400):
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.linspace(400.0, 480.0, n)
    return pd.DataFrame(
        {
            "Open":  close * 0.99,
            "High":  close * 1.005,
            "Low":   close * 0.995,
            "Close": close,
            "Volume": np.full(n, 50_000_000.0),
        },
        index=dates,
    )


@pytest.mark.asyncio
async def test_preloaded_df_skips_fetch():
    """When ticker_df and spy_df are provided, _fetch_data is never called."""
    ticker_df = _make_ticker_df()
    spy_df    = _make_spy_df()

    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-06-30",
        setup_types=["VCP"],
        ticker_df=ticker_df,
        spy_df=spy_df,
    )

    with patch("backtest_engine._fetch_data", new_callable=AsyncMock) as mock_fetch:
        await engine.run()

    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_none_df_still_calls_fetch():
    """When no preloaded df is given, _fetch_data is called (backward compat)."""
    engine = BacktestEngine(
        ticker="AAPL",
        start_date="2023-01-01",
        end_date="2023-03-31",
        setup_types=["VCP"],
    )

    with patch("backtest_engine._fetch_data", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (None, None)  # simulate fetch failure → empty result
        await engine.run()

    mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_preloaded_df_window_slice_respects_dates():
    """BacktestEngine replays only dates within start_date..end_date from a 400-bar df."""
    ticker_df = _make_ticker_df(n=400)
    spy_df    = _make_spy_df(n=400)

    # Window is within the df range
    start = ticker_df.index[200].strftime("%Y-%m-%d")
    end   = ticker_df.index[250].strftime("%Y-%m-%d")

    engine = BacktestEngine(
        ticker="TEST",
        start_date=start,
        end_date=end,
        setup_types=["VCP"],
        ticker_df=ticker_df,
        spy_df=spy_df,
    )

    summary = await engine.run()
    # Summary should exist (may have 0 trades, that's fine — just verifying no crash)
    assert summary is not None
    assert summary.start_date == start
    assert summary.end_date   == end
