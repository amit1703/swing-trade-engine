import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_meta_keys_include_support_level():
    """support_level must be captured from signal into _setup_meta."""
    from backtest_engine import _BACKTEST_META_KEYS
    assert "support_level" in _BACKTEST_META_KEYS

def test_meta_keys_include_geometry():
    """geometry must be captured for BASE base_high lookup."""
    from backtest_engine import _BACKTEST_META_KEYS
    assert "geometry" in _BACKTEST_META_KEYS
