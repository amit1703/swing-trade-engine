"""Tests for RES_BREAKOUT signal detection in the backtest engine."""
import sys
import os
import types
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest_engine import _detect_signals


def make_uptrend_df(n=300, base_price=100.0):
    """Uptrend DataFrame: close > 50 SMA throughout."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close  = np.linspace(70.0, base_price, n)
    high   = close * 1.01
    low    = close * 0.99
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6):
    """Configure a valid Minervini-style breakout in df (modifies in place)."""
    n       = len(df)
    brk_idx = n - 1 - days_ago

    for offset in range(1, 4):
        lp_idx = brk_idx - offset
        if lp_idx >= 0:
            df.iloc[lp_idx, df.columns.get_loc("High")]   = zone_upper * 1.005
            df.iloc[lp_idx, df.columns.get_loc("Low")]    = zone_upper * 0.990
            df.iloc[lp_idx, df.columns.get_loc("Close")]  = zone_upper * 0.995

    brk_close  = zone_upper * 1.012
    brk_high   = brk_close  * 1.003
    brk_low    = brk_close  * 0.990
    avg_vol    = float(df["Volume"].iloc[max(0, brk_idx - 50):brk_idx].mean())
    brk_vol    = avg_vol * vol_mult

    df.iloc[brk_idx, df.columns.get_loc("Close")]  = brk_close
    df.iloc[brk_idx, df.columns.get_loc("High")]   = brk_high
    df.iloc[brk_idx, df.columns.get_loc("Low")]    = brk_low
    df.iloc[brk_idx, df.columns.get_loc("Volume")] = brk_vol
    return brk_high


def make_spy_df(n=300):
    dates  = pd.date_range("2024-01-01", periods=n, freq="B")
    close  = np.linspace(400.0, 500.0, n)
    return pd.DataFrame(
        {"Close": close, "High": close*1.01, "Low": close*0.99,
         "Open": close, "Volume": np.full(n, 50_000_000.0)},
        index=dates,
    )


def make_dummy_indicators():
    ns = types.SimpleNamespace()
    ns.rs_ratio    = 1.05
    ns.rs_52w_high = 1.10
    ns.rs_blue_dot = False
    ns.rs_score    = 0.05
    return ns


def make_resistance_zone(level, atr=1.0, source="kde"):
    return {
        "level":      level,
        "upper":      level + 0.2 * atr,
        "lower":      level - 0.2 * atr,
        "type":       "RESISTANCE",
        "atr":        atr,
        "is_primary": True,
        "source":     source,
    }


def test_detect_signals_res_breakout_fires_when_all_rules_pass():
    """_detect_signals returns a setup dict when all Minervini rules pass."""
    zone_level = 100.0
    zone_upper = zone_level + 0.2
    df  = make_uptrend_df(n=300, base_price=99.0)
    spy = make_spy_df(n=300)
    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)
    zones = [make_resistance_zone(zone_level, atr=1.0)]

    with patch("indicators.indicator_engine.compute_indicators", return_value=make_dummy_indicators()), \
         patch("engines.engine1.calculate_sr_zones", return_value=zones):
        result = _detect_signals("TEST", df, spy, ["RES_BREAKOUT"])

    assert result is not None, "Expected a setup dict, got None"
    assert result["setup_type"] == "RES_BREAKOUT"
    assert result["signal"] == "BRK"
    assert result["entry"] > 0
    assert result["stop_loss"] < result["entry"]


def test_detect_signals_res_breakout_none_on_low_volume():
    """_detect_signals returns None when breakout volume is below threshold."""
    zone_level = 100.0
    zone_upper = zone_level + 0.2
    df  = make_uptrend_df(n=300, base_price=99.0)
    spy = make_spy_df(n=300)
    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.0)  # only 100% = fails 150% rule
    zones = [make_resistance_zone(zone_level, atr=1.0)]

    with patch("indicators.indicator_engine.compute_indicators", return_value=make_dummy_indicators()), \
         patch("engines.engine1.calculate_sr_zones", return_value=zones):
        result = _detect_signals("TEST", df, spy, ["RES_BREAKOUT"])

    assert result is None, "Expected None when volume is insufficient"


def test_detect_signals_res_breakout_uses_pivot_zones():
    """_detect_signals accepts pivot-sourced zones for RES_BREAKOUT."""
    zone_level = 100.0
    zone_upper = zone_level + 0.2
    df  = make_uptrend_df(n=300, base_price=99.0)
    spy = make_spy_df(n=300)
    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)
    pivot_zone = make_resistance_zone(zone_level, atr=1.0, source="pivot")

    with patch("indicators.indicator_engine.compute_indicators", return_value=make_dummy_indicators()), \
         patch("engines.engine1.calculate_sr_zones", return_value=[pivot_zone]):
        result = _detect_signals("TEST", df, spy, ["RES_BREAKOUT"])

    assert result is not None, "Pivot-zone breakout should fire"
    assert result["setup_type"] == "RES_BREAKOUT"
