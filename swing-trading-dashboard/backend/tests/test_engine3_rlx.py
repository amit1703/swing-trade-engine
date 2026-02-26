"""Tests for Engine 3 tightened relaxed pullback."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine3 import scan_relaxed_pullback


def make_pullback_df(n=200):
    """Stock in uptrend: 8 EMA > 20 EMA, close > 50 SMA. Low vol last 3 days."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(70.0, 100.0, n)
    high  = close * 1.01
    low   = close * 0.99
    volume = np.full(n, 1_000_000.0)
    volume[-3:] = 700_000.0  # low volume last 3 days
    return pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_support_zone(level: float):
    return {
        "level": level, "upper": level * 1.005,
        "lower": level * 0.995, "type": "SUPPORT",
        "is_primary": True,
    }


def test_rlx_rejects_when_no_support_zone():
    """RLX must reject when no KDE support zones are present."""
    df = make_pullback_df()
    result = scan_relaxed_pullback("TEST", df, [])
    assert result is None, "RLX must not fire without a support zone"


def test_rlx_rejects_resistance_zones_only():
    """RLX must reject when only resistance zones are present."""
    df = make_pullback_df()
    resistance_only = [
        {"level": 110.0, "upper": 110.5, "lower": 109.5,
         "type": "RESISTANCE", "is_primary": True}
    ]
    result = scan_relaxed_pullback("TEST", df, resistance_only)
    assert result is None, "RLX must not fire with only resistance zones"


def test_rlx_when_fires_cci_must_be_below_minus_30():
    """When RLX fires, cci_yesterday must be below -30."""
    df = make_pullback_df()
    support = make_support_zone(99.0)
    result = scan_relaxed_pullback("TEST", df, [support])
    if result is not None:
        assert result.get("cci_yesterday", 0) < -30, \
            "RLX should only fire when CCI[yesterday] < -30"
