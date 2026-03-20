"""
Asserts that every engine return dict includes the 'atr' field.
Uses minimal synthetic DataFrames — just enough for the engine to produce a signal.
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_df(n=300, price=50.0, atr_pct=0.02, trend="up"):
    """Minimal OHLCV DataFrame with enough bars for engine warmup."""
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    if trend == "up":
        close = np.linspace(price * 0.7, price, n)
    else:
        close = np.full(n, price)
    high   = close * (1 + atr_pct)
    low    = close * (1 - atr_pct)
    open_  = close * 0.999
    vol    = np.full(n, 2_000_000.0)
    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close,
        "Adj Close": close, "Volume": vol,
    }, index=dates)
    return df


def test_engine2_vcp_has_atr():
    from engines.engine2 import scan_vcp
    df = _make_df(300)
    zones = [{"level": 52.0, "upper": 52.5, "lower": 50.0, "type": "RESISTANCE"}]
    result = scan_vcp("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_vcp must include 'atr'"
        assert result["atr"] > 0


def test_engine2_near_breakout_has_atr():
    from engines.engine2 import scan_near_breakout
    df = _make_df(300)
    zones = [{"level": 50.0, "upper": 50.2, "lower": 49.0, "type": "RESISTANCE"}]
    result = scan_near_breakout("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_near_breakout must include 'atr'"
        assert result["atr"] > 0


def test_engine3_pullback_has_atr():
    from engines.engine3 import scan_pullback
    df = _make_df(300)
    zones = [{"level": 40.0, "upper": 41.0, "lower": 39.0, "type": "SUPPORT"}]
    result = scan_pullback("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_pullback must include 'atr'"
        assert result["atr"] > 0


def test_engine3_relaxed_pullback_has_atr():
    from engines.engine3 import scan_relaxed_pullback
    df = _make_df(300)
    zones = [{"level": 40.0, "upper": 41.0, "lower": 39.0, "type": "SUPPORT"}]
    result = scan_relaxed_pullback("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_relaxed_pullback must include 'atr'"
        assert result["atr"] > 0


def test_engine5_base_has_atr():
    from engines.engine5 import scan_base_pattern
    df = _make_df(300)
    zones = []
    result = scan_base_pattern("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_base_pattern must include 'atr'"
        assert result["atr"] > 0


def test_engine6_res_breakout_has_atr():
    from engines.engine6 import scan_resistance_breakout
    df = _make_df(300)
    zones = [{"level": 48.0, "upper": 48.5, "lower": 47.0, "type": "RESISTANCE"}]
    result = scan_resistance_breakout("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_resistance_breakout must include 'atr'"
        assert result["atr"] > 0


def test_engine8_htf_has_atr():
    from engines.engine8_htf import scan_htf
    df = _make_df(300)
    zones = []
    result = scan_htf("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_htf must include 'atr'"
        assert result["atr"] > 0


def test_engine9_lce_has_atr():
    from engines.engine9_low_cheat import scan_lce
    df = _make_df(300)
    zones = [{"level": 48.0, "upper": 48.5, "lower": 47.0, "type": "RESISTANCE"}]
    result = scan_lce("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_lce must include 'atr'"
        assert result["atr"] > 0
