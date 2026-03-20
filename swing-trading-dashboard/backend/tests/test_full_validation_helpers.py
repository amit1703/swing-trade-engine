"""Tests for full system validation helpers."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_setup_meta_captures_atr_and_entry():
    """_meta_keys must include 'atr' and 'entry' so trade dicts carry them."""
    import inspect
    from backtest_engine import BacktestEngine
    src = inspect.getsource(BacktestEngine.run)
    assert '"atr"' in src or "'atr'" in src, \
        "'atr' not found in BacktestEngine.run — add it to _meta_keys"
    assert '"entry"' in src or "'entry'" in src, \
        "'entry' not found in BacktestEngine.run — add it to _meta_keys"
