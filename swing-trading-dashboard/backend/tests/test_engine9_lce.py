"""Tests for Engine 9: Low Cheat Entry scanner.

Run with: pytest backend/tests/test_engine9_lce.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

from engines.engine9_low_cheat import scan_lce


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_uptrend_df(n=120, end_price=98.0):
    """Uptrend DataFrame: close above EMA20 throughout."""
    dates  = pd.date_range("2024-01-01", periods=n, freq="B")
    close  = np.linspace(70.0, end_price, n)
    high   = close * 1.008
    low    = close * 0.992
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_resistance_zone(level: float):
    return {
        "level":  level,
        "upper":  level * 1.005,
        "lower":  level * 0.995,
        "type":   "RESISTANCE",
        "source": "kde",
    }


def inject_lce_conditions(df, resistance_level, vol_contraction=True):
    """
    Configure last 10 bars to satisfy LCE conditions:
    - Price below resistance but within 3%
    - Range contraction (recent < prior)
    - Higher low (recent 3-bar low > prior 5-bar low)
    - Volume contraction (last 5 avg ≤ 80% of 20d avg)
    """
    n = len(df)
    close = df["Close"].values.copy()
    high  = df["High"].values.copy()
    low   = df["Low"].values.copy()
    vol   = df["Volume"].values.copy()

    # Prior 5 bars (wider range)
    for i in range(-10, -5):
        p = resistance_level * 0.97
        close[i] = p
        high[i]  = p * 1.010   # 1% range
        low[i]   = p * 0.990
        vol[i]   = 900_000.0

    # Recent 5 bars — tighter range, higher lows, close just below resistance
    for i in range(-5, -1):
        p = resistance_level * 0.985
        close[i] = p
        high[i]  = p * 1.003   # 0.3% range (contracting)
        low[i]   = p * 0.997
        vol[i]   = 600_000.0 if vol_contraction else 1_200_000.0

    # Today's bar
    p = resistance_level * 0.982  # 1.8% below resistance
    close[-1] = p
    high[-1]  = p * 1.003
    low[-1]   = p * 0.997
    vol[-1]   = 600_000.0 if vol_contraction else 1_200_000.0

    df["Close"]  = close
    df["High"]   = high
    df["Low"]    = low
    df["Volume"] = vol


def test_valid_lce_returns_setup():
    """Valid LCE conditions return a setup dict with correct fields."""
    df = make_uptrend_df(n=120, end_price=98.0)
    resistance = 100.0
    inject_lce_conditions(df, resistance, vol_contraction=True)
    zones = [make_resistance_zone(resistance)]

    result = scan_lce("TEST", df, zones=zones)
    assert result is not None, "Expected setup dict, got None"
    assert result["setup_type"] == "LCE"
    assert result["signal"] == "CHEAT"
    assert result["entry"] > 0
    assert result["stop_loss"] < result["entry"]
    assert result["take_profit"] > result["entry"]
    assert result["rr"] >= 1.0


def test_no_zones_returns_none():
    """Without resistance zones, LCE returns None."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0)
    assert scan_lce("TEST", df, zones=[]) is None
    assert scan_lce("TEST", df, zones=None) is None


def test_price_too_far_from_resistance_returns_none():
    """Price more than 3% below resistance returns None."""
    # end_price=94.0 → last bar close = 94.0, which is 6% below resistance 100.
    # Do NOT call inject_lce_conditions — that would overwrite the last bars
    # with prices only 1.8% below resistance, defeating the test intent.
    df = make_uptrend_df(n=120, end_price=94.0)
    zones = [make_resistance_zone(100.0)]
    assert scan_lce("TEST", df, zones=zones) is None


def test_volume_expansion_rejected():
    """Volume expansion (not contraction) returns None."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_contraction=False)
    zones = [make_resistance_zone(100.0)]
    # With vol_contraction=False, vol_avg_5 = 1_200_000 > 0.8 × 900_000 = 720_000 → rejected
    result = scan_lce("TEST", df, zones=zones)
    assert result is None


def test_return_dict_has_required_fields():
    """Setup dict includes all required fields."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_contraction=True)
    zones = [make_resistance_zone(100.0)]
    result = scan_lce("TEST", df, zones=zones)
    if result is None:
        pytest.skip("Pattern not detected")
    for field in ("ticker", "setup_type", "entry", "stop_loss", "take_profit",
                  "rr", "volume_ratio", "is_vol_surge", "setup_date",
                  "resistance_level", "distance_to_resistance_pct", "zone_source"):
        assert field in result, f"Missing required field: {field}"


def test_pivot_zones_accepted():
    """Pivot-sourced zones are accepted (source-agnostic)."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_contraction=True)
    pivot_zone = {
        "level": 100.0, "upper": 100.5, "lower": 99.5,
        "type": "RESISTANCE", "source": "pivot",
    }
    result = scan_lce("TEST", df, zones=[pivot_zone])
    assert result is not None, "Expected setup with pivot zone"
    assert result["zone_source"] == "pivot"


def test_short_df_returns_none():
    """DataFrame shorter than 60 bars returns None."""
    df = make_uptrend_df(n=30)
    assert scan_lce("TEST", df, zones=[make_resistance_zone(100.0)]) is None
