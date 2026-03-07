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


def inject_lce_conditions(df, resistance_level, vol_breakout=True):
    """
    Configure last bars for mini-breakout LCE conditions:
    - Price below resistance but within 3%
    - Higher low (recent 3-bar low > prior 5-bar low at indices -8..-3)
    - Close > prior bar's high (micro-resistance break)
    - Volume >= 20-day average on breakout bar
    - Override last 20 bars with tight ranges to keep ATR small → valid R:R >= 1.0
    """
    n = len(df)
    close = df["Close"].values.copy()
    high  = df["High"].values.copy()
    low   = df["Low"].values.copy()
    vol   = df["Volume"].values.copy()

    avg_vol = 1_000_000.0  # matches make_uptrend_df baseline
    base    = resistance_level * 0.985  # consolidation level

    # Override bars -20..-9: tight consolidation near resistance (tiny ATR)
    for i in range(-20, -9):
        close[i] = base
        high[i]  = base * 1.001
        low[i]   = base * 0.999
        vol[i]   = avg_vol * 0.80

    # Bars -8..-6: deep prior lows — these set min(low_arr[-8:-3]) low enough
    for i in range(-8, -5):
        p = resistance_level * 0.975
        close[i] = p
        high[i]  = p * 1.001
        low[i]   = p * 0.999
        vol[i]   = avg_vol * 0.75

    # Bars -5..-4: still in prior group [-8:-3] but at high level;
    # also in 5-bar swing-low window [-5:] — keep close to entry for tight stop
    for i in (-5, -4):
        p = resistance_level * 0.989
        close[i] = p
        high[i]  = p * 1.001
        low[i]   = p * 0.999
        vol[i]   = avg_vol * 0.82

    # Bar -3: first bar of recent window (low_arr[-3:]) — higher low than prior min
    p3 = resistance_level * 0.990
    close[-3] = p3
    high[-3]  = p3 * 1.001
    low[-3]   = p3 * 0.999
    vol[-3]   = avg_vol * 0.85

    # Bar -2: prior bar whose high today's close must exceed
    prior_high_price = resistance_level * 0.991
    close[-2] = prior_high_price * 0.999
    high[-2]  = prior_high_price
    low[-2]   = prior_high_price * 0.999
    vol[-2]   = avg_vol * 0.85

    # Bar -1 (today): breakout — close above yesterday's high, volume at/above avg
    p = prior_high_price * 1.003   # 0.3% above prior high — within 3% of resistance
    close[-1] = p
    high[-1]  = p * 1.001
    low[-1]   = p * 0.999
    vol[-1]   = avg_vol * 1.1 if vol_breakout else avg_vol * 0.5

    df["Close"]  = close
    df["High"]   = high
    df["Low"]    = low
    df["Volume"] = vol


def test_valid_lce_returns_setup():
    """Valid LCE conditions return a setup dict with correct fields."""
    df = make_uptrend_df(n=120, end_price=98.0)
    resistance = 100.0
    inject_lce_conditions(df, resistance, vol_breakout=True)
    zones = [make_resistance_zone(resistance)]

    result = scan_lce("TEST", df, zones=zones)
    assert result is not None, "Expected setup dict, got None"
    assert result["setup_type"] == "LCE"
    assert result["signal"] == "BRK"
    assert result["entry"] > 0
    assert result["stop_loss"] < result["entry"]
    assert result["take_profit"] > result["entry"]
    assert result["rr"] >= 1.0


def test_no_zones_returns_none():
    """Without resistance zones, LCE returns None."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_breakout=True)
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


def test_volume_below_average_rejected():
    """Volume below 1x 20-day average returns None (breakout needs volume)."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_breakout=False)
    zones = [make_resistance_zone(100.0)]
    assert scan_lce("TEST", df, zones=zones) is None


def test_close_below_prior_high_rejected():
    """If today's close does not exceed prior bar's high, LCE returns None."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_breakout=True)
    # Force today's close below prior bar's high
    prior_high = float(df["High"].iloc[-2])
    df.iloc[-1, df.columns.get_loc("Close")] = prior_high * 0.995
    zones = [make_resistance_zone(100.0)]
    assert scan_lce("TEST", df, zones=zones) is None


def test_return_dict_has_required_fields():
    """Setup dict includes all required fields."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_breakout=True)
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
    inject_lce_conditions(df, 100.0, vol_breakout=True)
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
