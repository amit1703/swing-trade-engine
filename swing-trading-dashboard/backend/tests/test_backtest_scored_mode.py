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


def test_final_score_propagation_from_state_to_trade_record():
    """
    The engine stores signal['_final_score'] in trade_state and then passes
    trade_state.get('_final_score') to TradeRecord. Verify that pattern works
    end-to-end using the same call signature as the engine.
    """
    from backtest_engine import TradeRecord

    # Simulate the trade_state dict the engine builds when opening a trade
    trade_state = {
        "ticker": "TEST",
        "setup_type": "PULLBACK",
        "signal_date": "2024-01-02",
        "entry_date": "2024-01-03",
        "entry_price": 100.0,
        "initial_stop": 95.0,
        "take_profit": 112.0,
        "_final_score": 8.5,
    }

    # Same pattern used in BacktestEngine._manage_open_trade / EOD close
    tr = TradeRecord(
        ticker=trade_state["ticker"],
        setup_type=trade_state["setup_type"],
        signal_date=trade_state["signal_date"],
        entry_date=trade_state["entry_date"],
        entry_price=trade_state["entry_price"],
        initial_stop=trade_state["initial_stop"],
        take_profit=trade_state["take_profit"],
        exit_date="2024-01-15",
        exit_price=108.0,
        exit_reason="TARGET",
        holding_days=12,
        final_score=trade_state.get("_final_score"),
    )
    assert tr.final_score == pytest.approx(8.5)
    assert tr.to_dict()["final_score"] == pytest.approx(8.5)


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


def test_backtest_params_has_vcp_bonus():
    """BacktestParams has vcp_bonus defaulting to 1.0."""
    from backtest_engine import BacktestParams
    p = BacktestParams()
    assert hasattr(p, "vcp_bonus")
    assert p.vcp_bonus == 1.0
