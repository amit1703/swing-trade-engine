import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_adapter_maps_initial_stop_to_stop_loss():
    """initial_stop → stop_loss for analytics.py compatibility."""
    import main as m
    trade = {
        "ticker": "AAPL", "setup_type": "VCP",
        "entry_price": 100.0, "initial_stop": 93.0,
        "exit_price": 112.0, "exit_reason": "TARGET",
        "rr_achieved": 1.71, "is_win": True,
    }
    result = m._backtest_trade_to_analytics(trade)
    assert result["stop_loss"]    == 93.0
    assert result["close_price"]  == 112.0
    assert result["status"]       == "closed"
    assert result["regime_score"] is None


def test_adapter_preserves_ticker_and_setup_type():
    import main as m
    trade = {"ticker": "MSFT", "setup_type": "PULLBACK",
             "entry_price": 200.0, "initial_stop": 190.0,
             "exit_price": 210.0}
    result = m._backtest_trade_to_analytics(trade)
    assert result["ticker"]      == "MSFT"
    assert result["setup_type"]  == "PULLBACK"
    assert result["entry_price"] == 200.0


def test_backtest_diag_status_initial_state():
    import main as m
    s = m._backtest_diag_status
    assert "status"   in s
    assert s["status"] in ("idle", "running", "completed", "failed")
    assert "done"     in s
    assert "total"    in s
    assert "last_run" in s


def test_backtest_diag_cache_path_uses_constant():
    """BACKTEST_DIAG_CACHE_PATH is derived from the BACKTEST_DIAG_CACHE_FILE constant."""
    import main as m
    from constants import BACKTEST_DIAG_CACHE_FILE
    # Path should end with the relative constant value (platform-normalised)
    normalized = BACKTEST_DIAG_CACHE_FILE.replace("/", os.sep)
    assert m.BACKTEST_DIAG_CACHE_PATH.endswith(normalized)
