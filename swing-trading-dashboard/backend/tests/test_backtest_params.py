# swing-trading-dashboard/backend/tests/test_backtest_params.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from backtest_engine import BacktestParams, BacktestEngine, TradeRecord


def test_backtest_params_defaults():
    p = BacktestParams()
    assert p.rs_threshold    == pytest.approx(-0.01219, abs=1e-5)
    assert p.cci_threshold   == pytest.approx(-20.0)
    assert p.ema_distance    == pytest.approx(0.04)
    assert p.score_threshold == pytest.approx(5.0)
    assert p.breakout_weight == pytest.approx(1.0)
    assert p.pullback_weight == pytest.approx(1.0)
    assert p.tdl_bonus       == pytest.approx(1.0)


def test_backtest_params_custom():
    p = BacktestParams(rs_threshold=0.05, score_threshold=7.0)
    assert p.rs_threshold    == pytest.approx(0.05)
    assert p.score_threshold == pytest.approx(7.0)
    assert p.breakout_weight == pytest.approx(1.0)


def test_backtest_engine_accepts_params():
    p = BacktestEngine(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
        params=BacktestParams(),
    )
    assert p.params is not None


def test_backtest_engine_none_params_by_default():
    engine = BacktestEngine(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    assert engine.params is None


def test_trade_record_final_score_defaults_none():
    tr = TradeRecord(
        ticker="AAPL", setup_type="VCP",
        signal_date="2024-01-02", entry_date="2024-01-03",
        entry_price=150.0, initial_stop=145.0, take_profit=160.0,
        exit_date="2024-01-10", exit_price=158.0,
        exit_reason="TARGET", holding_days=7,
    )
    assert tr.final_score is None


def test_trade_record_final_score_set():
    tr = TradeRecord(
        ticker="AAPL", setup_type="VCP",
        signal_date="2024-01-02", entry_date="2024-01-03",
        entry_price=150.0, initial_stop=145.0, take_profit=160.0,
        exit_date="2024-01-10", exit_price=158.0,
        exit_reason="TARGET", holding_days=7,
        final_score=7.5,
    )
    assert tr.final_score == pytest.approx(7.5)
    assert tr.to_dict()["final_score"] == pytest.approx(7.5)
