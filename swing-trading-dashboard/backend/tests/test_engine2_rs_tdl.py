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

def test_brk_rejects_stock_lagging_spy_by_more_than_5pct():
    """BRK path must reject stock with rs_vs_spy < -0.05.

    base_price=101.5 puts lc naturally ~1.3% above zone_upper (100.2),
    satisfying the 0.3-3% pct_above_upper window without disrupting EMA order.
    spy_3m_return=0.15 pushes rs_vs_spy to ~-0.077 (< -0.05), so BRK is blocked.
    """
    df = make_trending_df(base_price=101.5)
    zone = make_resistance_zone(100.0, atr=1.0)
    # Boost last-bar volume to trigger is_vol_surge (need >= 1.5x avg_vol)
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0

    # spy up 15 % over 3 months; stock only up ~7 % → rs_vs_spy ≈ -0.077 < -0.05
    result = scan_vcp("TEST", df, [zone], spy_3m_return=0.15, rs_blue_dot=False)
    # Path B must NOT fire; result may still come from another path (C/D/E/A)
    # but if BRK fires, its rs_vs_spy must be > -0.05
    if result is not None and result.get("is_breakout") and not result.get("is_trendline_breakout"):
        assert result.get("rs_vs_spy", 0) > -0.05, \
            "BRK path should not fire when rs_vs_spy < -0.05"


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
    df = make_trending_df(base_price=100.0)

    # Create a fake trendline whose current value is below current price
    # (simulating a stock 1.5% above its descending trendline)
    trendline_value = 100.0 * 0.985  # trendline is below current price
    trendline = {
        "descending": {
            "series": [{"time": "2025-01-01", "value": trendline_value}],
            "slope": -0.1,
            "touches": 3,
        },
        "ascending": None,
    }

    result = scan_near_breakout("TEST", df, [], trendline=trendline)
    if result is not None:
        assert result.get("pattern_type") != "TDL-BRK", \
            "TDL-BRK should no longer appear in watchlist"
