# swing-trading-dashboard/backend/tests/test_backtest_diagnostics_print.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from analytics import print_backtest_diagnostics


def _trade(setup_type="VCP", is_win=True, rr=1.5, final_score=6.0):
    return {
        "ticker":      "AAPL",
        "setup_type":  setup_type,
        "entry_price": 150.0,
        "exit_price":  150.0 + (rr * 5.0 if is_win else -5.0),
        "exit_reason": "TARGET" if is_win else "STOP",
        "rr_achieved": rr if is_win else -1.0,
        "pnl_pct":     rr * 3.33 if is_win else -3.33,
        "is_win":      is_win,
        "final_score": final_score,
    }


def test_returns_string():
    result = print_backtest_diagnostics([_trade()])
    assert isinstance(result, str)


def test_contains_total_trade_count():
    trades = [_trade(), _trade(is_win=False)]
    result = print_backtest_diagnostics(trades)
    assert "2" in result


def test_contains_setup_type_breakdown():
    trades = [_trade("VCP"), _trade("PULLBACK", is_win=False)]
    result = print_backtest_diagnostics(trades)
    assert "VCP" in result
    assert "PULLBACK" in result


def test_score_section_present_when_final_score_set():
    trades = [_trade(final_score=7.5), _trade(final_score=4.0)]
    result = print_backtest_diagnostics(trades)
    assert "score" in result.lower()


def test_score_section_omitted_when_no_final_score():
    """Legacy mode: all final_score=None → score section not shown."""
    trades = [_trade(final_score=None), _trade(final_score=None)]
    result = print_backtest_diagnostics(trades)
    assert "avg final score" not in result.lower()


def test_empty_trades_does_not_crash():
    result = print_backtest_diagnostics([])
    assert isinstance(result, str)
    assert "0" in result or "No trades" in result
