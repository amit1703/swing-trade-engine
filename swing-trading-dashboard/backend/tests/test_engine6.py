"""Tests for Engine 6: Resistance Breakout Scanner (Minervini/O'Neil overhaul).

Three mandatory rules for a valid breakout:
  1. LAUNCHPAD   — 3 trading days before breakout: highs within 3% of resistance
                   AND daily range < 1.5 × ATR14.
  2. DECISIVE CLOSE — breakout day close > zone_upper × 1.005 (0.5% above zone)
                      AND close in top 30% of daily range.
  3. INSTITUTIONAL VOLUME — breakout day volume ≥ 150% of 50-day average.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine6 import scan_resistance_breakout


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def make_resistance_zone(level: float, atr: float = 1.0):
    return {
        "level":  level,
        "upper":  level + 0.2 * atr,
        "lower":  level - 0.2 * atr,
        "type":   "RESISTANCE",
        "atr":    atr,
        "is_primary": True,
    }


def setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6):
    """
    Configure a valid Minervini-style breakout in-place.

    Applies:
      • Launchpad: bars -3, -2, -1 before breakout are tight under resistance.
      • Breakout bar: close 1.2% above zone, top 30% of range, institutional volume.

    Returns the breakout bar's high (for risk-math assertions).
    """
    n       = len(df)
    brk_idx = n - 1 - days_ago

    # ── Launchpad bars (brk_idx-3, brk_idx-2, brk_idx-1) ────────────────
    # High just below resistance; tight range (ATR for make_uptrend_df ≈ 2.0,
    # so range=0.8 is safely below the 1.5×ATR ≈ 3.0 threshold).
    for offset in range(1, 4):
        idx = brk_idx - offset
        if 0 <= idx < n:
            pre_high  = zone_upper * 0.995
            pre_range = 0.8
            df.iloc[idx, df.columns.get_loc("High")]  = pre_high
            df.iloc[idx, df.columns.get_loc("Low")]   = pre_high - pre_range
            df.iloc[idx, df.columns.get_loc("Close")] = pre_high - pre_range * 0.5

    # ── Breakout bar ──────────────────────────────────────────────────────
    brk_high  = zone_upper * 1.015
    brk_low   = zone_upper * 0.998   # small lower wick
    brk_close = zone_upper * 1.012   # 1.2 % above zone — decisive close ✓
    # Verify top-30%: (close-low)/(high-low) = (1.012-0.998)/(1.015-0.998) = 0.014/0.017 ≈ 0.82 > 0.70 ✓

    df.iloc[brk_idx, df.columns.get_loc("Close")]  = brk_close
    df.iloc[brk_idx, df.columns.get_loc("High")]   = brk_high
    df.iloc[brk_idx, df.columns.get_loc("Low")]    = brk_low
    df.iloc[brk_idx, df.columns.get_loc("Volume")] = 1_000_000.0 * vol_mult

    return brk_high


# =============================================================================
# Basic structural tests (unchanged behavior)
# =============================================================================

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


def test_ignores_breakout_4_days_ago():
    """Breakout older than 3 days must be ignored (3-day window unchanged)."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=110.0)
    zone       = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=4)

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "4-day-old breakout must be ignored"


def test_ignores_overextended_price():
    """Current close > 5% above zone.upper → ignored (overextension gate)."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=115.0)
    zone       = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    # Valid breakout 3 days ago
    setup_full_breakout(df, zone_upper, days_ago=3)

    # But today's close is 8 % above zone — overextended
    df.iloc[-1, df.columns.get_loc("Close")] = zone_upper * 1.08
    df.iloc[-1, df.columns.get_loc("High")]  = zone_upper * 1.09

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Overextended current price should be ignored"


# =============================================================================
# Rule 3: Institutional Volume (≥ 150 % of 50-day average)
# =============================================================================

def test_institutional_volume_threshold_is_150_pct():
    """Breakout day volume must be ≥ 150% of 50-day average."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)   # 160 % → should pass
    result_pass = scan_resistance_breakout("TEST", df, [zone])

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.4)   # 140 % → should fail
    result_fail = scan_resistance_breakout("TEST", df, [zone])

    assert result_pass is not None, "160% volume should qualify (≥150%)"
    assert result_fail is None,     "140% volume must not qualify (<150%)"


def test_ignores_low_volume_breakout():
    """Breakout with only 80 % volume (< 150 % threshold) must be ignored."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=0.8)   # 80 %

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "80% volume must not qualify"


# =============================================================================
# Rule 2: Decisive Close
# =============================================================================

def test_ignores_breakout_close_below_half_pct_threshold():
    """Close only 0.3 % above zone_upper (< 0.5 % minimum) must be rejected."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    # Override breakout bar: close only 0.3% above zone
    brk_close = zone_upper * 1.003   # < 1.005 threshold
    brk_high  = zone_upper * 1.010
    brk_low   = zone_upper * 0.998
    df.iloc[-1, df.columns.get_loc("Close")] = brk_close
    df.iloc[-1, df.columns.get_loc("High")]  = brk_high
    df.iloc[-1, df.columns.get_loc("Low")]   = brk_low

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Close < 0.5% above zone must be rejected"


def test_ignores_breakout_with_weak_close_position():
    """Close in bottom 30 % of the day's range (wick that closed poorly) is rejected."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    # Override: very wide upper wick (6%), low just above zone → close at 15% of range
    # brk_low must be above zone so that close at 15% of range still clears 0.5% threshold
    brk_high  = zone_upper * 1.060   # wide upper wick
    brk_low   = zone_upper * 1.002   # wick starts just above zone
    # Close at bottom 15% of range → weak rejection candle
    daily_range = brk_high - brk_low
    brk_close   = brk_low + 0.15 * daily_range      # 15 % = NOT in top 30 %
    assert brk_close > zone_upper * 1.005, "Precondition: close still above 0.5% threshold"

    df.iloc[-1, df.columns.get_loc("Close")] = brk_close
    df.iloc[-1, df.columns.get_loc("High")]  = brk_high
    df.iloc[-1, df.columns.get_loc("Low")]   = brk_low

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Close in bottom 30% of range must be rejected"


# =============================================================================
# Rule 1: Launchpad Contraction
# =============================================================================

def test_ignores_breakout_when_pre_bars_above_resistance():
    """Pre-breakout bars with highs > 3% above resistance fail the launchpad."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    # Override launchpad: bar -2 has high 5% above resistance (too extended)
    brk_idx = n - 1
    df.iloc[brk_idx - 2, df.columns.get_loc("High")] = zone_upper * 1.05

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Pre-bar high > 3% above resistance must fail launchpad"


def test_ignores_breakout_when_pre_bars_have_wide_range():
    """Pre-breakout bars with range > 1.5 × ATR fail the launchpad."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    # Override launchpad bar -2: give it a very wide range (ATR ≈ 2, 1.5×ATR ≈ 3; use 10)
    brk_idx  = n - 1
    pre_high = zone_upper * 0.995
    df.iloc[brk_idx - 2, df.columns.get_loc("High")] = pre_high
    df.iloc[brk_idx - 2, df.columns.get_loc("Low")]  = pre_high - 10.0   # 10 >> 1.5×ATR

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Pre-bar range > 1.5×ATR must fail launchpad"


# =============================================================================
# Valid breakout detection (all three rules satisfied)
# =============================================================================

def test_detects_fresh_breakout_today():
    """Valid Minervini breakout today is detected (all 3 rules satisfied)."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None,          "Should detect today's valid breakout"
    assert result["setup_type"] == "RES_BREAKOUT"
    assert result["signal"]     == "BRK"
    assert result["days_since_breakout"] == 0
    assert result["volume_ratio"] >= 1.5


def test_detects_breakout_3_days_ago():
    """Valid breakout 3 days ago (within the 3-day window) is detected."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=110.0)
    zone       = make_resistance_zone(107.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=3, vol_mult=1.6)

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None,                  "3-day-old breakout should be detected"
    assert result["days_since_breakout"] == 3


def test_risk_math():
    """Entry, stop, and target follow the documented formula."""
    n  = 300
    df = make_uptrend_df(n=n, base_price=105.0)
    zone       = make_resistance_zone(102.0, atr=1.0)
    zone_upper = zone["upper"]

    brk_high = setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None

    expected_entry = round(brk_high * 1.001, 2)
    assert result["entry"]       == pytest.approx(expected_entry, rel=1e-3)
    assert result["stop_loss"]   <  result["entry"]
    assert result["take_profit"] >  result["entry"]

    risk = result["entry"] - result["stop_loss"]
    assert result["take_profit"] == pytest.approx(result["entry"] + 2 * risk, rel=1e-3)


def test_detects_breakout_below_200sma():
    """Stage-2 filter removed — breakout below 200 SMA but above 50 SMA qualifies."""
    n = 300
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(120.0, 85.0, n)
    close[-50:] = np.linspace(85.0, 95.0, 50)   # recovery above 50 SMA
    high   = close * 1.01
    low    = close * 0.99
    volume = np.full(n, 1_000_000.0)
    df = pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    zone       = make_resistance_zone(90.0, atr=1.0)
    zone_upper = zone["upper"]

    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    sma200 = pd.Series(close).rolling(200).mean().iloc[-1]
    assert close[-1] < sma200, "Precondition: close must be below 200 SMA"

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "Should detect breakout even when below 200 SMA"
