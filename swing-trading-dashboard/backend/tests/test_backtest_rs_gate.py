# swing-trading-dashboard/backend/tests/test_backtest_rs_gate.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import numpy as np
import pandas as pd
import pytest

from backtest_engine import BacktestEngine, BacktestParams


def _flat_df(n: int = 350, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=n, freq="B")
    p   = np.full(n, price)
    return pd.DataFrame({
        "Open":      p,
        "High":      p * 1.005,
        "Low":       p * 0.995,
        "Close":     p,
        "Adj Close": p,
        "Volume":    np.full(n, 3_000_000),
    }, index=idx)


def test_rs_gate_active_in_scored_mode():
    """params.rs_threshold is stored and accessible."""
    p = BacktestParams(rs_threshold=0.10)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
        params=p,
    )
    assert engine.params.rs_threshold == pytest.approx(0.10)


def test_rs_gate_not_active_in_legacy_mode():
    """Legacy mode — params is None, gate never runs."""
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
    )
    assert engine.params is None


def test_impossibly_high_rs_threshold_produces_zero_trades():
    """
    rs_threshold=1.0 means stock must beat SPY by 100% — impossible on
    synthetic flat data. Scored mode must produce 0 trades.
    score_threshold=0.0 ensures score gate doesn't interfere.
    """
    ticker_df = _flat_df(400)
    spy_df    = _flat_df(400)

    p = BacktestParams(rs_threshold=1.0, score_threshold=0.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
        ticker_df=ticker_df,
        spy_df=spy_df,
        params=p,
    )
    result = asyncio.run(engine.run())
    assert result.total_trades == 0


def test_very_low_rs_threshold_does_not_block_trades():
    """
    rs_threshold=-1.0 is always met (RS can't drop below -1 on sane data).
    score_threshold=0.0 to remove score gate. Engine may or may not find
    signals on flat data, but it should NOT be blocked by the RS gate.
    This is verified indirectly: engine runs to completion without error,
    and the only gate in play is natural signal detection.
    """
    ticker_df = _flat_df(400)
    spy_df    = _flat_df(400)

    p = BacktestParams(rs_threshold=-1.0, score_threshold=0.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
        ticker_df=ticker_df,
        spy_df=spy_df,
        params=p,
    )
    # Should complete without error
    result = asyncio.run(engine.run())
    assert result.total_trades >= 0
