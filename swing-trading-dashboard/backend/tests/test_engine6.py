"""Tests for Engine 6: Resistance Breakout Scanner."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine6 import scan_resistance_breakout


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_uptrend_df(n=300, base_price=100.0):
    """Minimal uptrend DataFrame: close > 50 SMA. Price trends steadily from 70 to base_price."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(70.0, base_price, n)   # steady uptrend
    high  = close * 1.01
    low   = close * 0.99
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_resistance_zone(level: float, atr: float = 1.0):
    """Create a minimal Engine 1 resistance zone dict."""
    return {
        "level": level,
        "upper": level + 0.2 * atr,
        "lower": level - 0.2 * atr,
        "type": "RESISTANCE",
        "atr": atr,
        "is_primary": True,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_returns_none_when_no_zones():
    df = make_uptrend_df()
    assert scan_resistance_breakout("TEST", df, []) is None


def test_returns_none_when_only_support_zones():
    df = make_uptrend_df()
    support_zone = {
        "level": 80.0, "upper": 80.2, "lower": 79.8,
        "type": "SUPPORT", "atr": 1.0, "is_primary": True,
    }
    assert scan_resistance_breakout("TEST", df, [support_zone]) is None


def test_detects_fresh_breakout_today():
    """Stock that crossed resistance today with volume surge should be detected."""
    n = 300
    df = make_uptrend_df(n=n, base_price=105.0)

    resistance_level = 102.0
    zone = make_resistance_zone(resistance_level, atr=1.0)
    zone_upper = zone["upper"]  # 102.2

    # Day before breakout: close just below zone_upper
    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.995
    df.iloc[-2, df.columns.get_loc("High")]  = zone_upper * 0.998

    # Breakout day (today): close above zone_upper with volume surge
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.015
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0  # 160% of 1M avg

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "Should detect today's breakout"
    assert result["setup_type"] == "RES_BREAKOUT"
    assert result["signal"] == "BRK"
    assert result["days_since_breakout"] == 0
    assert result["volume_ratio"] >= 1.5


def test_detects_breakout_3_days_ago():
    """Breakout 3 days ago is within the 3-day window and should be detected."""
    n = 300
    df = make_uptrend_df(n=n, base_price=110.0)

    zone = make_resistance_zone(107.0, atr=1.0)
    zone_upper = zone["upper"]

    # Day before breakout (4 days ago): close below zone_upper
    df.iloc[-5, df.columns.get_loc("Close")] = zone_upper * 0.99
    # Breakout 3 days ago
    df.iloc[-4, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-4, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-4, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "3-day-old breakout should be detected"
    assert result["days_since_breakout"] == 3


def test_ignores_breakout_4_days_ago():
    """Breakout older than 3 days must be ignored."""
    n = 300
    df = make_uptrend_df(n=n, base_price=110.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-6, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-5, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-5, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-5, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "4-day-old breakout must be ignored"


def test_ignores_low_volume_breakout():
    """Breakout without volume (< 100% of avg) must be ignored."""
    n = 300
    df = make_uptrend_df(n=n, base_price=105.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 800_000.0  # only 80% of avg — not enough

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Volume < 100% of avg should not qualify"


def test_detects_breakout_with_moderate_volume():
    """Breakout with 110% volume (above new 100% threshold) should be detected."""
    n = 300
    df = make_uptrend_df(n=n, base_price=103.0)  # base_price ensures lc > 50 SMA at breakout

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_100_000.0  # 110% of 1M avg

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "110% volume should qualify with new 100% threshold"
    assert result["volume_ratio"] == pytest.approx(1.1, rel=0.05)


def test_ignores_overextended_price():
    """Current close > 5% above zone.upper must be ignored even with valid breakout."""
    n = 300
    df = make_uptrend_df(n=n, base_price=115.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]  # 100.2

    # Valid breakout 3 days ago: pre-bar below zone, breakout bar just above
    df.iloc[-5, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-4, df.columns.get_loc("Close")]  = zone_upper * 1.012
    df.iloc[-4, df.columns.get_loc("High")]   = zone_upper * 1.015   # within 5%
    df.iloc[-4, df.columns.get_loc("Volume")] = 1_600_000.0

    # But current close is 8% above zone — overextended
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.08
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.09

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Overextended current price (>5% above zone) should be ignored"


def test_risk_math():
    """Entry, stop, target must follow the documented formula."""
    n = 300
    df = make_uptrend_df(n=n, base_price=105.0)

    zone = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.995
    brk_high = zone_upper * 1.015
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("High")]   = brk_high
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None

    expected_entry = round(brk_high * 1.001, 2)
    assert result["entry"] == pytest.approx(expected_entry, rel=1e-3)
    assert result["stop_loss"] < result["entry"]
    assert result["take_profit"] > result["entry"]
    # R:R = 2
    risk = result["entry"] - result["stop_loss"]
    assert result["take_profit"] == pytest.approx(result["entry"] + 2 * risk, rel=1e-3)


def test_detects_breakout_below_200sma():
    """Stage 2 filter removed — stock below 200 SMA but above 50 SMA should qualify."""
    n = 300
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # Declining price: below 200 SMA but above 50 SMA at the end
    close = np.linspace(120.0, 85.0, n)   # downtrend — 200 SMA > current price
    close[-50:] = np.linspace(85.0, 95.0, 50)  # recent recovery above 50 SMA
    high   = close * 1.01
    low    = close * 0.99
    volume = np.full(n, 1_000_000.0)
    df = pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    zone = make_resistance_zone(90.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_100_000.0

    # Confirm this df has close < 200 SMA (so old Stage 2 would have rejected it)
    sma200 = pd.Series(close).rolling(200).mean().iloc[-1]
    assert close[-1] < sma200, "Precondition: close must be below 200 SMA"

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "Should detect breakout even when below 200 SMA"
