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
            "profit_factor": 2.2,
            "max_drawdown_pct": 5.5,
            "avg_holding_days": 12.0,
            "gross_profit": 1100.0,
            "gross_loss": -500.0,
            "trades": [{"entry": 150.0, "exit": 165.0}],
        }
        row_id = await database.save_backtest_result(db_path, row)
        assert row_id > 0
        results = await database.get_backtest_results(db_path, "AAPL")
        assert len(results) == 1
        assert results[0]["win_rate"] == 60.0
        assert results[0]["run_id"] == "test-run-1"
        assert len(results[0]["trades"]) == 1
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


def test_compute_metrics_profit_factor():
    """profit_factor = gross_profit / abs(gross_loss)."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # +10 pnl_pct
        _make_trade(100, 95, 95),   # -5 pnl_pct
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert abs(summary.profit_factor - 2.0) < 0.05


def test_compute_metrics_no_trades():
    """Zero trades returns zero metrics without crashing."""
    from backtest_engine import compute_metrics
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", [])
    assert summary.total_trades == 0
    assert summary.win_rate == 0.0
    assert summary.profit_factor == 0.0


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
