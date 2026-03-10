import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_state(setup_type: str, trail_mult_override=None) -> dict:
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   130.0,
        "entry_date":    "2024-01-01",
        "setup_type":    setup_type,
    }
    if trail_mult_override is not None:
        state["trail_mult_override"] = trail_mult_override
    return state


def test_override_forces_single_mult_for_vcp():
    """When trail_mult_override=4.162, VCP must NOT use its V5 2.0 mult."""
    from backtest_engine import _manage_open_trade
    state = _make_state("VCP", trail_mult_override=4.162)
    # close=108, ema20=95, atr14=1.0
    # With override=4.162: atr_trail = 108 - 4.162*1.0 = 103.838; ema20=95 → new_trail=103.838
    # With VCP mult=2.0:   atr_trail = 108 - 2.0*1.0  = 106.0;   ema20=95 → new_trail=106.0
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    # Must be 103.838 (override), not 106.0 (V5 VCP)
    assert abs(state["trailing_stop"] - (108.0 - 4.162 * 1.0)) < 0.01


def test_override_forces_single_mult_for_pullback():
    """When trail_mult_override=4.162, PULLBACK must NOT use its V5 3.0 mult."""
    from backtest_engine import _manage_open_trade
    state = _make_state("PULLBACK", trail_mult_override=4.162)
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    assert abs(state["trailing_stop"] - (108.0 - 4.162 * 1.0)) < 0.01


def test_no_override_preserves_v5_vcp_mult():
    """Without override, VCP still uses its V5 tight 2.0 multiplier."""
    from backtest_engine import _manage_open_trade
    state = _make_state("VCP")   # no trail_mult_override key
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    assert abs(state["trailing_stop"] - (108.0 - 2.0 * 1.0)) < 0.01


def test_engine_stores_override_in_run():
    """BacktestEngine initialised with trail_mult_override stores it."""
    from backtest_engine import BacktestEngine
    eng = BacktestEngine("AAPL", "2023-01-01", "2023-06-01", trail_mult_override=4.162)
    assert eng.trail_mult_override == 4.162


def test_engine_default_override_is_none():
    """BacktestEngine without trail_mult_override defaults to None."""
    from backtest_engine import BacktestEngine
    eng = BacktestEngine("AAPL", "2023-01-01", "2023-06-01")
    assert eng.trail_mult_override is None
