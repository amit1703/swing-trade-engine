"""Tests for WFO engine — window generation and metrics computation."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wfo_engine import _generate_windows, _compute_wfo_metrics, _apply_portfolio_cap, WFOMetrics
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


def _make_trade_dated(ticker, entry_date, exit_date, rr=1.0):
    """Create a TradeRecord with specific dates for portfolio cap testing."""
    entry = 100.0
    stop  = 95.0   # 5% stop
    exit_p = entry + rr * (entry - stop) if rr > 0 else stop
    return TradeRecord(
        ticker=ticker, setup_type="VCP",
        signal_date=entry_date, entry_date=entry_date,
        entry_price=entry, initial_stop=stop,
        take_profit=110.0, exit_date=exit_date,
        exit_price=exit_p,
        exit_reason="TARGET" if rr > 0 else "STOP",
        holding_days=10,
    )


def test_apply_portfolio_cap_limits_concurrent_positions():
    """10 trades all starting on same day → only MAX_OPEN_POSITIONS (5) accepted."""
    trades = [
        _make_trade_dated(f"TICK{i}", "2024-01-02", "2024-01-20", rr=2.0)
        for i in range(10)
    ]
    result = _apply_portfolio_cap(trades, max_positions=5)
    assert len(result) == 5


def test_apply_portfolio_cap_allows_sequential_trades():
    """Trades that don't overlap in time are all accepted regardless of count."""
    # Each trade starts after the previous one exits
    trades = [
        _make_trade_dated("AAPL", "2024-01-02", "2024-01-10", rr=2.0),
        _make_trade_dated("MSFT", "2024-01-11", "2024-01-20", rr=2.0),
        _make_trade_dated("NVDA", "2024-01-21", "2024-01-30", rr=2.0),
        _make_trade_dated("GOOGL", "2024-01-31", "2024-02-10", rr=2.0),
        _make_trade_dated("AMZN", "2024-02-11", "2024-02-20", rr=2.0),
        _make_trade_dated("TSLA", "2024-02-21", "2024-03-01", rr=2.0),
    ]
    result = _apply_portfolio_cap(trades, max_positions=5)
    # All 6 are sequential — none overlap — all accepted
    assert len(result) == 6


def test_apply_portfolio_cap_partial_overlap():
    """When 4 are open and 2 new ones start, only 1 of the 2 is accepted (cap=5)."""
    # 4 long-running trades already open
    long_running = [
        _make_trade_dated(f"BASE{i}", "2024-01-01", "2024-02-28", rr=2.0)
        for i in range(4)
    ]
    # 2 new trades start mid-way — only 1 slot remaining
    new_trades = [
        _make_trade_dated("NEW1", "2024-01-15", "2024-01-25", rr=2.0),
        _make_trade_dated("NEW2", "2024-01-15", "2024-01-25", rr=2.0),
    ]
    result = _apply_portfolio_cap(long_running + new_trades, max_positions=5)
    assert len(result) == 5   # 4 base + 1 new


def test_apply_portfolio_cap_empty_list():
    """Empty input returns empty list without error."""
    assert _apply_portfolio_cap([], max_positions=5) == []


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


@pytest.mark.asyncio
async def test_run_wfo_passes_spy_df_to_backtest():
    """run_wfo should load SPY data and pass it to BacktestEngine (regime gate active)."""
    from wfo_engine import run_wfo
    import numpy as np
    import pandas as pd
    from unittest.mock import patch

    n = 500
    dates = pd.date_range("2015-01-01", periods=n, freq="B")

    # Downtrending SPY → defensive regime → expect 0 new-signal trades
    spy_close = np.linspace(200.0, 50.0, n)
    mock_spy_df = pd.DataFrame({
        "Close": spy_close, "Open": spy_close,
        "High": spy_close * 1.01, "Low": spy_close * 0.99,
        "Volume": np.full(n, 10_000_000), "Adj Close": spy_close,
    }, index=dates)

    # Bullish liquid ticker (would generate signals WITHOUT the regime gate)
    tick_close = np.linspace(100.0, 200.0, n)
    mock_tick_df = pd.DataFrame({
        "Close": tick_close, "Open": tick_close * 0.99,
        "High": tick_close * 1.02, "Low": tick_close * 0.98,
        "Volume": np.full(n, 5_000_000), "Adj Close": tick_close,
    }, index=dates)

    def load_either(ticker):
        return mock_spy_df if ticker == "SPY" else mock_tick_df

    with patch("wfo_engine.load_ticker", side_effect=load_either), \
         patch("wfo_engine.cache_exists", return_value=True):
        result = await run_wfo(
            tickers=["AAPL"],
            setup_types=["VCP"],
            is_months=12, oos_months=3, step_months=6,
            min_trades=1,
        )

    total_oos = sum(len(w.oos_trades) for w in result.windows)
    assert total_oos == 0, f"Expected 0 OOS trades in defensive SPY regime, got {total_oos}"
