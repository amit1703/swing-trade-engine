"""Tests for Engine 2 RS threshold and TDL routing changes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine2 import scan_vcp, scan_near_breakout


def make_trending_df(n=300, base_price=100.0):
    """Uptrending stock: 8 EMA > 20 EMA, close > 50 SMA, close > 200 SMA."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(60.0, base_price, n)
    high  = close * 1.005
    low   = close * 0.995
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_resistance_zone(level: float, atr: float = 1.0):
    return {
        "level": level, "upper": level + 0.2 * atr,
        "lower": level - 0.2 * atr, "type": "RESISTANCE",
        "atr": atr, "is_primary": True,
    }


# ── RS threshold tests ─────────────────────────────────────────────────────────

def test_brk_rs_threshold_contrast():
    """Path B fires for both strong and weak RS stocks (RS gate removed).

    After removing the rs_score > 0 hard gate from Path B, both setups
    should fire when volume and resistance conditions are met, regardless
    of relative strength vs SPY.
    """
    df_weak = make_trending_df(base_price=101.5)
    df_strong = make_trending_df(base_price=101.5)
    zone = make_resistance_zone(100.0, atr=1.0)

    # Both have volume surge
    df_weak.iloc[-1, df_weak.columns.get_loc("Volume")] = 1_600_000.0
    df_strong.iloc[-1, df_strong.columns.get_loc("Volume")] = 1_600_000.0

    # With spy_3m=0.15: stock ~+6% over 63 days, rs_vs_spy ≈ -0.09
    # RS gate removed — Path B should now fire for both
    result_weak = scan_vcp("TEST", df_weak, [zone], spy_3m_return=0.15, rs_blue_dot=False)

    # With spy_3m=0.02: stock ~+6% over 63 days, rs_vs_spy ≈ +0.04 — Path B should fire
    result_strong = scan_vcp("TEST", df_strong, [zone], spy_3m_return=0.02, rs_blue_dot=False)

    assert result_strong is not None, "BRK should fire when rs_vs_spy > -0.05"
    # RS gate removed: weak RS stocks can also fire Path B now
    assert result_weak is not None, "BRK should fire even with weak RS (gate removed)"


def test_brk_accepts_stock_lagging_spy_by_less_than_5pct():
    """BRK path must accept stock with rs_vs_spy between -0.05 and 0.

    base_price=101.5 gives lc ~1.3% above zone_upper (100.2) with healthy EMA order.
    spy_3m_return=0.02 keeps rs_vs_spy positive (~+0.07), well above the -0.05 floor.
    """
    df = make_trending_df(base_price=101.5)
    zone = make_resistance_zone(100.0, atr=1.0)
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0

    # spy up only 2 %; stock up ~7 % → rs_vs_spy ≈ +0.07 > -0.05, BRK should fire
    result = scan_vcp("TEST", df, [zone], spy_3m_return=0.02, rs_blue_dot=False)
    assert result is not None, "Should detect BRK with rs_vs_spy > -0.05"


# ── TDL-BRK routing test ──────────────────────────────────────────────────────

def test_near_breakout_does_not_return_tdl_brk():
    """scan_near_breakout must NOT produce TDL-BRK pattern_type anymore."""
    df = make_trending_df(base_price=100.0)  # lc ≈ 100

    # Put a KDE resistance zone 0.5% above current price → will produce a KDE proximity result
    zone_level = 100.0 * 1.005
    zone = {"level": zone_level, "upper": zone_level * 1.002, "lower": zone_level * 0.998,
            "type": "RESISTANCE", "is_primary": True}

    # Trendline BELOW current price (lc=100 > tl_today=99):
    # Old code would have flagged TDL-BRK when lc > tl_today within 0.1-3% above trendline.
    # New code has removed TDL-BRK; only KDE/KDE-BRK/TDL proximity types remain.
    trendline_value = 99.0  # 1% below lc → old code would flag TDL-BRK
    trendline = {
        "descending": {
            "series": [{"time": "2025-01-01", "value": trendline_value}],
            "slope": -0.1,
            "touches": 3,
        },
        "ascending": None,
    }

    result = scan_near_breakout("TEST", df, [zone], trendline=trendline)
    # The KDE zone is 0.5% above lc, which is within PROXIMITY_PCT=1.5% → should fire
    assert result is not None, "Should find KDE proximity result with zone 0.5% above price"
    # Must NOT be TDL-BRK (that code path has been removed)
    assert result.get("pattern_type") != "TDL-BRK", \
        "TDL-BRK should no longer appear after removal"
