"""Tests for WFO engine — window generation and metrics computation."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wfo_engine import _generate_windows, _compute_wfo_metrics, WFOMetrics
from backtest_engine import TradeRecord


def _make_trade(ticker="TEST", setup_type="VCP", rr=1.0, pnl_pct=2.0):
    """Create a minimal TradeRecord with controlled rr_achieved."""
    entry  = 100.0
    stop   = 99.0   # risk = 1.0
    if rr > 0:
        exit_p = entry + rr * 1.0
    else:
        exit_p = entry + rr * 1.0  # negative rr → exit < entry

    t = TradeRecord(
        ticker=ticker,
        setup_type=setup_type,
        signal_date="2024-01-01",
        entry_date="2024-01-02",
        entry_price=entry,
        initial_stop=stop,
        take_profit=102.0,
        exit_date="2024-01-10",
        exit_price=exit_p,
        exit_reason="TARGET" if rr > 0 else "STOP",
        holding_days=8,
    )
    return t


def test_generate_windows_returns_non_empty():
    start = pd.Timestamp("2016-01-01")
    end   = pd.Timestamp("2025-12-31")
    windows = _generate_windows(start, end, is_months=24, oos_months=3, step_months=3)
    assert len(windows) > 0


def test_generate_windows_oos_non_overlapping():
    """OOS periods must not overlap between consecutive windows."""
    start = pd.Timestamp("2016-01-01")
    end   = pd.Timestamp("2025-12-31")
    windows = _generate_windows(start, end, is_months=24, oos_months=3, step_months=3)
    for i in range(len(windows) - 1):
        _, _, _, oos_end_i   = windows[i]
        _, _, oos_start_next, _ = windows[i + 1]
        assert oos_end_i <= oos_start_next, "OOS periods should not overlap"


def test_generate_windows_count_approx_24():
    """Default 24/3/3 config over 8-year range produces ~24 windows."""
    start = pd.Timestamp("2016-01-01")
    end   = pd.Timestamp("2025-12-31")
    windows = _generate_windows(start, end, is_months=24, oos_months=3, step_months=3)
    # Should be ~31 windows for a ~9.75 year span (8yr effective = 32 steps)
    assert 20 <= len(windows) <= 40


def test_compute_wfo_metrics_empty_trades():
    """Empty trade list returns zero metrics with reliable=False."""
    m = _compute_wfo_metrics([], min_trades=20)
    assert m.trades == 0
    assert m.win_rate == 0.0
    assert m.reliable is False


def test_compute_wfo_metrics_basic():
    """Basic metrics computed correctly from known trades."""
    # 2 wins (rr=2.0) + 1 loss (rr=-1.0)
    trades = [
        _make_trade(rr=2.0),
        _make_trade(rr=2.0),
        _make_trade(rr=-1.0),
    ]
    m = _compute_wfo_metrics(trades, min_trades=2)
    assert m.trades == 3
    assert abs(m.win_rate - 66.67) < 0.1
    assert abs(m.avg_r - 1.0) < 0.01          # (2 + 2 - 1) / 3
    assert abs(m.median_r - 2.0) < 0.01
    assert m.profit_factor > 1.0
    assert m.reliable is True


def test_compute_wfo_metrics_reliable_flag():
    """reliable=True only when trades >= min_trades."""
    trades = [_make_trade() for _ in range(15)]
    m_not = _compute_wfo_metrics(trades, min_trades=20)
    m_yes = _compute_wfo_metrics(trades, min_trades=10)
    assert m_not.reliable is False
    assert m_yes.reliable is True


@pytest.mark.asyncio
async def test_run_wfo_returns_wfo_result():
    """run_wfo returns a WFOResult with the correct metadata."""
    from wfo_engine import run_wfo

    # Mock cache to return a minimal df for each ticker
    n = 400
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    close = np.linspace(80.0, 100.0, n)
    mock_df = pd.DataFrame(
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

    with patch("wfo_engine.load_ticker", return_value=mock_df), \
         patch("wfo_engine.cache_exists", return_value=True):
        result = await run_wfo(
            tickers=["AAPL"],
            setup_types=["VCP"],
            is_months=12,
            oos_months=3,
            step_months=6,
            min_trades=1,
        )

    assert result is not None
    assert result.tickers == ["AAPL"]
    assert result.is_months == 12
    assert len(result.windows) > 0
