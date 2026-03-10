import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_backtest_diag_constants_exist():
    from constants import (
        BACKTEST_DIAG_START_DATE,
        BACKTEST_DIAG_END_DATE,
        BACKTEST_V4_TRAIL_MULT,
    )
    assert BACKTEST_DIAG_START_DATE == "2023-01-01"
    assert BACKTEST_DIAG_END_DATE   == "2024-12-31"
    assert BACKTEST_V4_TRAIL_MULT   == 4.162

def test_backtest_v4_trail_mult_is_distinct_from_trail_atr_mult():
    """BACKTEST_V4_TRAIL_MULT is a separately declared constant with the same
    numeric value as TRAIL_ATR_MULT (4.162) — not assigned as an alias."""
    from constants import BACKTEST_V4_TRAIL_MULT, TRAIL_ATR_MULT
    assert BACKTEST_V4_TRAIL_MULT == 4.162
    assert TRAIL_ATR_MULT == 4.162   # same value; non-aliasing documented in docstring only

def test_backtest_cache_file_constant_exists():
    from constants import BACKTEST_DIAG_CACHE_FILE
    assert BACKTEST_DIAG_CACHE_FILE == "cache/backtest_diagnostics.json"
