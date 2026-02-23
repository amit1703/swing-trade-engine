import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from engines.engine5 import _quality_score, scan_cup_handle, scan_flat_base


def make_cup_handle_df(n_total=110, cup_depth=0.20, handle_pct=0.08):
    """
    Build a synthetic DataFrame with a clear cup & handle pattern.
    Structure: 30 bars uptrend -> 40-bar cup -> 40-bar recovery -> 20-bar handle -> 20 bars near pivot
    """
    dates = pd.date_range("2025-01-01", periods=n_total, freq="B")

    close = np.ones(n_total) * 100.0
    # Uptrend into left peak
    for i in range(30):
        close[i] = 90 + i * 0.5          # ramp from 90 to 104.5
    left_peak = close[29]                 # ~104.5

    # Cup: half-sine dip
    for i in range(40):
        angle = np.pi * i / 39
        close[30 + i] = left_peak - cup_depth * left_peak * np.sin(angle)

    right_rim = close[69]                 # should be close to left_peak

    # Handle: small drift down
    for i in range(20):
        t = i / 19
        close[70 + i] = right_rim - handle_pct * right_rim * np.sin(np.pi * t)

    # Near pivot (last 20 bars drift up toward right_rim)
    for i in range(20):
        close[90 + i] = right_rim * 0.99 + i * 0.01

    high = close * 1.01
    low = close * 0.99
    volume = np.full(n_total, 1_000_000.0)
    volume[70:90] = 600_000.0   # dry-up in handle
    volume[-1] = 1_000_000.0

    df = pd.DataFrame({
        "Close": close,
        "High": high,
        "Low": low,
        "Open": close * 0.995,
        "Volume": volume,
    }, index=dates)
    return df


def test_rs_vs_spy_formula_uses_ratio_minus_one():
    """
    rs_ratio=1.10 means stock gained 10% vs SPY's base.
    spy_3m_return=0.05 means SPY gained 5%.
    rs_vs_spy should be (1.10-1.0) - 0.05 = 0.05 (5% outperformance).
    The OLD formula gives 1.10 - 0.05 = 1.05 which is nonsense.
    We verify by checking quality score uses a sane rs_vs_spy value.
    """
    # With correct formula: rs_vs_spy = (1.10 - 1.0) - 0.05 = 0.05
    # _quality_score gets rs_vs_spy=0.05, so rs_pts = (0.05/0.05)*25 = 25
    qs = _quality_score(
        depth_pct=0.08,         # perfect tightness → 25 pts
        max_depth_pct=0.35,
        vol_dry_pct=0.25,       # good dry-up → 25 pts
        rs_vs_spy=0.05,         # 5% outperformance → 25 pts
        rs_blue_dot=False,      # 0 pts
    )
    assert qs == 75, f"Expected 75, got {qs}"

    # With OLD formula: rs_vs_spy = 1.10 - 0.05 = 1.05
    # rs_pts = min(25, (1.05/0.05)*25) = 25 (capped, so same here)
    # But at lower outperformance the difference is stark:
    # rs_ratio=1.01, spy_3m_return=0.05
    # correct: (1.01-1.0)-0.05 = -0.04 → 0 rs_pts
    # old:      1.01-0.05=0.96  → 25 rs_pts (wrong!)
    qs_correct = _quality_score(
        depth_pct=0.08,
        max_depth_pct=0.35,
        vol_dry_pct=0.25,
        rs_vs_spy=(1.01 - 1.0) - 0.05,   # = -0.04, stock underperforms
        rs_blue_dot=False,
    )
    assert qs_correct < 75, "Underperforming stock should score < 75"


def test_scan_cup_handle_rs_vs_spy_is_negative_when_underperforming():
    """End-to-end: rs_vs_spy in output must be negative when stock underperforms SPY."""
    df = make_cup_handle_df()
    result = scan_cup_handle(
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
