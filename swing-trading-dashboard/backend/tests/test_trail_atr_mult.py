"""Tests for TRAIL_ATR_MULT constant and _manage_open_trade hybrid trailing stop."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_trail_atr_mult_constant_exists():
    """TRAIL_ATR_MULT must exist in constants at its Optuna v4 optimised value."""
    from constants import TRAIL_ATR_MULT
    assert TRAIL_ATR_MULT == 4.162


def test_trail_atr_mult_imported_in_backtest_engine():
    """backtest_engine must import TRAIL_ATR_MULT."""
    import backtest_engine
    import inspect
    src = inspect.getsource(backtest_engine)
    assert "TRAIL_ATR_MULT" in src


def test_manage_open_trade_uses_atr_trail_when_tighter():
    """When atr-based trail > EMA20, trailing stop ratchets to atr trail."""
    import constants
    from backtest_engine import _manage_open_trade

    old = constants.TRAIL_ATR_MULT
    constants.TRAIL_ATR_MULT = 1.0  # tight: trail = close - 1.0 * atr14
    try:
        state = {
            "entry_price":   100.0,
            "trailing_stop":  95.0,
            "take_profit":   110.0,
            "entry_date":    "2024-01-01",
        }
        # close=105, ema20=100, atr14=2.0 → atr_trail=103.0 > ema20=100 → new_trail=103.0
        bar = {
            "date":  "2024-01-02",
            "open":  104.0, "high": 106.0, "low": 103.5,
            "close": 105.0, "ema20": 100.0, "atr14": 2.0,
        }
        closed, _, _ = _manage_open_trade(state, bar)
        assert not closed
        assert abs(state["trailing_stop"] - 103.0) < 0.01
    finally:
        constants.TRAIL_ATR_MULT = old


def test_manage_open_trade_falls_back_to_ema20_when_atr_trail_lower():
    """When EMA20 > atr trail, trailing stop ratchets to EMA20."""
    import constants
    from backtest_engine import _manage_open_trade

    old = constants.TRAIL_ATR_MULT
    constants.TRAIL_ATR_MULT = 3.0  # wide: trail = close - 3.0 * atr14
    try:
        state = {
            "entry_price":   100.0,
            "trailing_stop":  95.0,
            "take_profit":   120.0,
            "entry_date":    "2024-01-01",
        }
        # close=105, ema20=104, atr14=3.0 → atr_trail=96.0 < ema20=104 → new_trail=104.0
        bar = {
            "date":  "2024-01-02",
            "open":  104.0, "high": 106.0, "low": 103.0,
            "close": 105.0, "ema20": 104.0, "atr14": 3.0,
        }
        closed, _, _ = _manage_open_trade(state, bar)
        assert not closed
        assert abs(state["trailing_stop"] - 104.0) < 0.01
    finally:
        constants.TRAIL_ATR_MULT = old


def test_manage_open_trade_stop_not_ratcheted_when_at_loss():
    """Trailing stop must NOT ratchet when close <= entry_price."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   120.0,
        "entry_date":    "2024-01-01",
    }
    bar = {
        "date":  "2024-01-02",
        "open":  99.0, "high": 100.5, "low": 98.0,
        "close": 99.0, "ema20": 101.0, "atr14": 1.0,
    }
    _manage_open_trade(state, bar)
    assert state["trailing_stop"] == 95.0  # unchanged
