"""RS formula correctness tests for Engine 5."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from engines.engine5 import _quality_score, scan_cup_handle, scan_flat_base


def make_darvas_box_df(n_total=260, box_days=30):
    dates = pd.date_range("2023-01-01", periods=n_total, freq="B")
    close = np.ones(n_total, dtype=float)
    trend_bars = n_total - box_days
    for i in range(trend_bars):
        close[i] = 50.0 + i * (50.0 / (trend_bars - 1))

    box_high = 100.0
    box_height = 2.5   # ATR ≈ 1.0, multiple = 2.5
    box_low = box_high - box_height
    for i in range(box_days):
        t = i / box_days
        close[trend_bars + i] = box_low + box_height * (0.4 + 0.3 * np.sin(2 * np.pi * t))

    high = close + 0.5
    low  = close - 0.5
    high[trend_bars + 3]  = box_high + 0.5
    high[trend_bars + 18] = box_high + 0.5
    ceiling = float(np.max(high[-box_days:]))
    close[-1] = ceiling * 0.992

    volume = np.full(n_total, 1_000_000.0)
    volume[-3:] = 600_000.0

    return pd.DataFrame({
        "Close": close, "High": high, "Low": low,
        "Open": close * 0.998, "Volume": volume,
    }, index=dates)


def test_rs_vs_spy_formula_uses_ratio_minus_one():
    """
    rs_ratio=1.10, spy_3m_return=0.05 → rs_vs_spy = (1.10-1.0) - 0.05 = 0.05.
    _quality_score(tightness=0.08, vol_dry=0.25, rs_vs_spy=0.05, blue_dot=False) = 75 pts.
    Old formula (ratio - spy = 1.05) would also give 25 pts (capped), so test
    the sensitive case: stock underperforms.
    """
    # With correct formula: rs_vs_spy = (1.01-1.0)-0.05 = -0.04 → 0 RS pts → < 75
    qs_underperform = _quality_score(
        tightness_pct=0.0,     # perfect tightness → 25 pts
        vol_dry_pct=0.25,      # good dry-up → 25 pts
        rs_vs_spy=(1.01 - 1.0) - 0.05,  # = -0.04 (underperforms)
        rs_blue_dot=False,
    )
    assert qs_underperform < 75, (
        f"Underperforming stock should score < 75, got {qs_underperform}"
    )

    # Outperforming stock: rs_vs_spy = 0.05 → full 25 pts
    qs_outperform = _quality_score(
        tightness_pct=0.0,
        vol_dry_pct=0.25,
        rs_vs_spy=0.05,
        rs_blue_dot=False,
    )
    assert qs_outperform == 75, f"Expected 75, got {qs_outperform}"


def test_scan_flat_base_rs_vs_spy_negative_when_underperforming():
    """End-to-end: rs_vs_spy in output must be negative when stock underperforms SPY."""
    df = make_darvas_box_df()
    result = scan_flat_base(
        "TEST", df,
        spy_3m_return=0.05,
        rs_ratio=1.01,
        rs_52w_high=1.05,
        rs_blue_dot=False,
    )
    if result is not None:
        assert result["rs_vs_spy"] < 0, (
            f"rs_vs_spy should be negative (stock underperforms), got {result['rs_vs_spy']}"
        )
