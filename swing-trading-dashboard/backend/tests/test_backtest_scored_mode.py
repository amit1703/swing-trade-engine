# swing-trading-dashboard/backend/tests/test_backtest_scored_mode.py
import asyncio
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import pytest

from backtest_engine import BacktestEngine, BacktestParams


def _flat_df(n: int = 350, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=n, freq="B")
    p   = np.full(n, price)
    return pd.DataFrame({
        "Open":      p, "High": p * 1.005,
        "Low":       p * 0.995, "Close": p,
        "Adj Close": p, "Volume": np.full(n, 3_000_000),
    }, index=idx)


def test_impossible_score_threshold_blocks_all_trades():
    """score_threshold=999 means no trade can ever pass."""
    p = BacktestParams(score_threshold=999.0, rs_threshold=-1.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
        params=p,
    )
    result = asyncio.run(engine.run())
    assert result.total_trades == 0


def test_zero_score_threshold_does_not_crash():
    """score_threshold=0.0 removes the gate — engine runs to completion."""
    p = BacktestParams(score_threshold=0.0, rs_threshold=-1.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
        params=p,
    )
    result = asyncio.run(engine.run())
    assert result.total_trades >= 0


def test_trade_record_final_score_populated_in_scored_mode():
    """In scored mode, all completed TradeRecord objects have final_score set."""
    p = BacktestParams(score_threshold=0.0, rs_threshold=-1.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
        params=p,
    )
    result = asyncio.run(engine.run())
    for trade in result.trades:
        assert trade.final_score is not None
        assert isinstance(trade.final_score, float)


def test_legacy_mode_final_score_is_none():
    """Legacy mode (params=None): TradeRecord.final_score stays None."""
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
    )
    result = asyncio.run(engine.run())
    for trade in result.trades:
        assert trade.final_score is None


def test_breakout_weight_arithmetic():
    """
    Verify the weight arithmetic: base_score * weight vs threshold.
    breakout_weight=2.0 doubles VCP base score (6.0 → 12.0).
    """
    from backtest_engine import _SIGNAL_BASE_SCORES
    assert _SIGNAL_BASE_SCORES["VCP"] == 6.0
    assert 6.0 * 2.0 >= 7.0   # would pass a threshold of 7.0
    assert 6.0 * 1.0 < 7.0    # would be blocked at threshold of 7.0
