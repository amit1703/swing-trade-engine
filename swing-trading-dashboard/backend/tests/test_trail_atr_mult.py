"""Tests for V5 setup-specific ATR trailing in _manage_open_trade."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_v5_trail_constants_exist():
    """All four V5 setup-specific ATR trail constants must exist."""
    from constants import (
        VCP_TRAIL_ATR_MULT, PULLBACK_TRAIL_ATR_MULT,
        RES_BREAKOUT_TRAIL_ATR_MULT, BASE_TRAIL_ATR_MULT, TRAIL_ATR_MULT,
    )
    assert VCP_TRAIL_ATR_MULT == 2.0
    assert PULLBACK_TRAIL_ATR_MULT == 3.0
    assert RES_BREAKOUT_TRAIL_ATR_MULT == 4.25
    assert BASE_TRAIL_ATR_MULT == 4.162
    assert TRAIL_ATR_MULT == 4.162  # fallback unchanged


def test_vcp_uses_tight_trail():
    """VCP setup_type → 2.0 ATR multiplier → tighter trail than generic."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   120.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "VCP",
    }
    # close=108, ema20=100, atr14=3.0
    # VCP trail = 108 - 2.0*3.0 = 102.0; ema20=100 → new_trail=max(102,100)=102.0
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 100.0, "atr14": 3.0}
    closed, _, _ = _manage_open_trade(state, bar)
    assert not closed
    assert abs(state["trailing_stop"] - 102.0) < 0.01


def test_pullback_uses_moderate_trail():
    """PULLBACK setup_type → 3.0 ATR multiplier."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   120.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "PULLBACK",
    }
    # close=108, ema20=100, atr14=3.0
    # PULLBACK trail = 108 - 3.0*3.0 = 99.0; ema20=100 → new_trail=max(99,100)=100.0
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 100.0, "atr14": 3.0}
    closed, _, _ = _manage_open_trade(state, bar)
    assert not closed
    assert abs(state["trailing_stop"] - 100.0) < 0.01


def test_res_breakout_uses_wide_trail():
    """RES_BREAKOUT setup_type → 4.25 ATR multiplier → wider trail than VCP/PULLBACK."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   120.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "RES_BREAKOUT",
    }
    # close=108, ema20=100, atr14=2.0
    # RES_BREAKOUT trail = 108 - 4.25*2.0 = 99.5; ema20=100 → new_trail=max(99.5,100)=100.0
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 100.0, "atr14": 2.0}
    closed, _, _ = _manage_open_trade(state, bar)
    assert not closed
    assert abs(state["trailing_stop"] - 100.0) < 0.01


def test_unknown_setup_uses_fallback():
    """Unknown setup_type falls back to TRAIL_ATR_MULT (4.162)."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  90.0,
        "take_profit":   130.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "WATCHLIST",
    }
    # close=108, ema20=95, atr14=1.0
    # fallback trail = 108 - 4.162*1.0 = 103.838; ema20=95 → new_trail=103.838
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    closed, _, _ = _manage_open_trade(state, bar)
    assert not closed
    assert abs(state["trailing_stop"] - (108.0 - 4.162 * 1.0)) < 0.01


def test_trailing_stop_never_loosens():
    """Trailing stop must never move downward regardless of setup type."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop": 105.0,   # already ratcheted high
        "take_profit":   130.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "VCP",
    }
    # Bar that would compute a trail below current stop
    bar = {"date": "2024-01-02", "open": 106.0, "high": 107.0, "low": 105.5,
           "close": 106.0, "ema20": 101.0, "atr14": 3.0}
    # VCP trail = 106 - 2.0*3.0 = 100 < current 105 → stop must stay at 105
    _manage_open_trade(state, bar)
    assert state["trailing_stop"] >= 105.0


def test_stop_not_ratcheted_when_at_loss():
    """Trailing stop must not move when close <= entry_price."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   120.0,
        "entry_date":    "2024-01-01",
        "setup_type":    "VCP",
    }
    bar = {"date": "2024-01-02", "open": 99.0, "high": 100.0, "low": 98.0,
           "close": 99.0, "ema20": 101.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    assert state["trailing_stop"] == 95.0
