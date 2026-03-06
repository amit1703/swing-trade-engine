"""Tests for backtest_engine.py and database schema."""
import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import database


@pytest.mark.asyncio
async def test_backtest_results_table_exists():
    """backtest_results table is created by init_db()."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await database.init_db(db_path)
        result = await database.get_backtest_results(db_path, "AAPL")
        assert isinstance(result, list)
        assert len(result) == 0
    finally:
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_save_and_retrieve_backtest_result():
    """save_backtest_result() persists data retrievable by get_backtest_results()."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await database.init_db(db_path)
        row = {
            "run_id": "test-run-1",
            "ticker": "AAPL",
            "setup_type": "VCP",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "total_trades": 5,
            "win_count": 3,
            "loss_count": 2,
            "win_rate": 60.0,
            "avg_rr": 1.8,
            "avg_win_r": 2.5,
            "avg_loss_r": -0.8,
            "peak_equity": 12.3,
            "profit_factor": 2.2,
            "max_drawdown_pct": 5.5,
            "avg_holding_days": 12.0,
            "gross_profit": 1100.0,
            "gross_loss": -500.0,
            "net_profit_pct": 600.0,
            "trades": [{"entry": 150.0, "exit": 165.0}],
        }
        row_id = await database.save_backtest_result(db_path, row)
        assert row_id > 0
        results = await database.get_backtest_results(db_path, "AAPL")
        assert len(results) == 1
        assert results[0]["win_rate"] == 60.0
        assert results[0]["run_id"] == "test-run-1"
        assert len(results[0]["trades"]) == 1
        assert results[0]["net_profit_pct"] == 600.0
        assert results[0]["avg_win_r"] == 2.5
        assert results[0]["avg_loss_r"] == -0.8
        assert results[0]["peak_equity"] == 12.3
    finally:
        os.unlink(db_path)


def test_trade_record_fields():
    """TradeRecord has all required fields and computes derived properties correctly."""
    from backtest_engine import TradeRecord
    trade = TradeRecord(
        ticker="AAPL",
        setup_type="VCP",
        signal_date="2024-03-01",
        entry_date="2024-03-04",
        entry_price=175.0,
        initial_stop=168.0,
        take_profit=189.0,
        exit_date="2024-03-15",
        exit_price=189.0,
        exit_reason="TARGET",
        holding_days=11,
    )
    assert abs(trade.rr_achieved - 2.0) < 0.01
    assert abs(trade.pnl_pct - (189.0 - 175.0) / 175.0 * 100) < 0.01
    assert trade.is_win is True


def test_trade_record_loss():
    """TradeRecord.is_win is False when exit_price <= entry_price."""
    from backtest_engine import TradeRecord
    trade = TradeRecord(
        ticker="AAPL",
        setup_type="VCP",
        signal_date="2024-03-01",
        entry_date="2024-03-04",
        entry_price=175.0,
        initial_stop=168.0,
        take_profit=189.0,
        exit_date="2024-03-06",
        exit_price=168.0,
        exit_reason="STOP",
        holding_days=2,
    )
    assert abs(trade.rr_achieved - (-1.0)) < 0.01
    assert trade.is_win is False


def _make_trade(entry, exit_price, stop, days=10, setup="VCP"):
    """Helper: create a TradeRecord from basic price levels."""
    from backtest_engine import TradeRecord
    return TradeRecord(
        ticker="TEST", setup_type=setup,
        signal_date="2024-01-01", entry_date="2024-01-02",
        entry_price=entry, initial_stop=stop,
        take_profit=entry + 2 * (entry - stop),
        exit_date="2024-01-12", exit_price=exit_price,
        exit_reason="TARGET" if exit_price > entry else "STOP",
        holding_days=days,
    )


def test_compute_metrics_win_rate():
    """win_rate = wins / total * 100."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # win
        _make_trade(100, 110, 95),  # win
        _make_trade(100, 95, 95),   # loss
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert abs(summary.win_rate - 66.67) < 0.05
    assert isinstance(summary.net_profit_pct, float)


def test_compute_metrics_profit_factor():
    """profit_factor = gross_profit / abs(gross_loss)."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # +10 pnl_pct
        _make_trade(100, 95, 95),   # -5 pnl_pct
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert abs(summary.profit_factor - 2.0) < 0.05
    # avg_rr = mean of ALL trades: win rr=2.0, loss rr=-1.0 → avg = 0.5
    assert abs(summary.avg_rr - 0.5) < 0.01
    # net_profit_pct = 10 + (-5) = 5.0
    assert abs(summary.net_profit_pct - 5.0) < 0.1


def test_compute_metrics_no_trades():
    """Zero trades returns zero metrics without crashing."""
    from backtest_engine import compute_metrics
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", [])
    assert summary.total_trades == 0
    assert summary.win_rate == 0.0
    assert summary.profit_factor == 0.0
    assert summary.net_profit_pct == 0.0
    assert summary.avg_win_r == 0.0
    assert summary.avg_loss_r == 0.0
    assert summary.peak_equity == 0.0


def test_compute_metrics_max_drawdown():
    """max_drawdown_pct is peak-to-trough of cumulative pnl."""
    from backtest_engine import compute_metrics
    # +10%, -15%, +5% → cumulative: 10, -5, 0 → peak 10, trough -5 = drawdown 15%
    trades = [
        _make_trade(100, 110, 95, days=5),   # +10%
        _make_trade(100, 85, 95, days=5),    # -15%
        _make_trade(100, 105, 95, days=5),   # +5%
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert abs(summary.max_drawdown_pct - 15.0) < 0.5


def test_manage_trade_stop_hit():
    """Trade closes at stop when low <= trailing_stop."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 102.0, "high": 104.0, "low": 94.0, "close": 96.0, "ema20": 101.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 110.0, "entry_date": "2024-03-04"}
    closed, exit_price, exit_reason = _manage_open_trade(state, bar)
    assert closed is True
    assert exit_reason == "STOP"
    assert abs(exit_price - 95.0) < 0.01


def test_manage_trade_target_hit():
    """Trade closes at take_profit when high >= take_profit."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 108.0, "high": 112.0, "low": 107.0, "close": 111.0, "ema20": 102.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 110.0, "entry_date": "2024-03-04"}
    closed, exit_price, exit_reason = _manage_open_trade(state, bar)
    assert closed is True
    assert exit_reason == "TARGET"
    assert abs(exit_price - 110.0) < 0.01


def test_manage_trade_trailing_stop_ratchets():
    """trailing_stop increases to ema20 when close > entry and ema20 > trailing_stop."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 105.0, "high": 108.0, "low": 104.0, "close": 106.0, "ema20": 103.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 115.0, "entry_date": "2024-03-04"}
    closed, exit_price, exit_reason = _manage_open_trade(state, bar)
    assert closed is False
    assert abs(state["trailing_stop"] - 103.0) < 0.01


def test_manage_trade_trailing_stop_does_not_drop():
    """trailing_stop never decreases even if ema20 dips below it."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 105.0, "high": 108.0, "low": 104.0, "close": 106.0, "ema20": 93.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 115.0, "entry_date": "2024-03-04"}
    closed, _, _ = _manage_open_trade(state, bar)
    assert closed is False
    assert abs(state["trailing_stop"] - 95.0) < 0.01


def test_detect_signals_returns_none_for_short_slice():
    """
    _detect_signals must return None when df_slice has fewer than MIN_BARS_FOR_SIGNAL bars.
    This verifies the lookahead-prevention guard works correctly.
    """
    from backtest_engine import _detect_signals, MIN_BARS_FOR_SIGNAL
    import pandas as pd
    import numpy as np

    # 30 bars — below the 60-bar minimum
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    price = 100.0 + np.random.randn(30).cumsum()
    df = pd.DataFrame({
        "Open": price * 0.99,
        "High": price * 1.01,
        "Low":  price * 0.98,
        "Close": price,
        "Adj Close": price,
        "Volume": np.ones(30) * 1_000_000,
    }, index=dates)

    result = _detect_signals("AAPL", df, df, ["VCP"])
    assert result is None


def test_backtest_engine_zero_signals():
    """BacktestEngine produces 0-trade summary when no signals fire."""
    import asyncio
    import unittest.mock as mock
    from backtest_engine import BacktestEngine

    with mock.patch("backtest_engine._detect_signals", return_value=None), \
         mock.patch("backtest_engine._fetch_data") as mock_fetch:
        import numpy as np
        import pandas as pd

        # 400 bars of flat price history
        dates = pd.date_range("2023-01-01", periods=400, freq="B")
        price = np.full(400, 100.0)
        df = pd.DataFrame({
            "Open": price, "High": price * 1.01,
            "Low": price * 0.99, "Close": price,
            "Adj Close": price, "Volume": np.ones(400) * 1_000_000,
        }, index=dates)

        mock_fetch.return_value = (df, df)

        engine = BacktestEngine("AAPL", "2024-01-01", "2024-12-31", ["VCP"])
        summary = asyncio.run(engine.run())

    assert summary.total_trades == 0
    assert summary.win_rate == 0.0


def test_avg_rr_is_all_trades():
    """avg_rr = mean R across ALL trades including losses."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # win: rr = (110-100)/(100-95) = +2.0
        _make_trade(100, 95, 95),   # loss: rr = (95-100)/(100-95) = -1.0
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    # avg_rr = mean(2.0, -1.0) = 0.5
    assert abs(summary.avg_rr - 0.5) < 0.01
    # avg_win_r = 2.0 (wins only)
    assert abs(summary.avg_win_r - 2.0) < 0.01
    # avg_loss_r = -1.0 (losses only)
    assert abs(summary.avg_loss_r - (-1.0)) < 0.01


def test_peak_equity_compound():
    """peak_equity tracks the peak of the compound equity curve."""
    from backtest_engine import compute_metrics
    # +10%, -5%: equity 1.0 → 1.10 → 1.045; peak=1.10 so peak_equity=10.0%
    trades = [
        _make_trade(100, 110, 95, days=5),  # +10%
        _make_trade(100, 95, 95, days=5),   # -5%
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert abs(summary.peak_equity - 10.0) < 0.5


def test_net_profit_pct():
    """net_profit_pct = gross_profit + gross_loss (wins + losses)."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # pnl_pct = +10%
        _make_trade(100, 95, 95),   # pnl_pct = -5%
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert abs(summary.net_profit_pct - 5.0) < 0.1
