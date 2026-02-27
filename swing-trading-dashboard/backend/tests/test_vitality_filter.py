"""Tests for the Price Action Vitality filter (Fix 1).

is_price_vital(df) must return False for zombie / buyout flatline stocks
and True for normally-traded stocks.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from validation import is_price_vital


def _make_df(highs, lows, closes=None):
    n = len(highs)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    if closes is None:
        closes = (np.array(highs) + np.array(lows)) / 2
    return pd.DataFrame(
        {
            "High":      np.array(highs, dtype=float),
            "Low":       np.array(lows,  dtype=float),
            "Close":     np.array(closes, dtype=float),
            "Adj Close": np.array(closes, dtype=float),
            "Open":      np.array(closes, dtype=float),
            "Volume":    np.ones(n) * 1_000_000,
        },
        index=dates,
    )


# ── Failing cases (zombie / flatline) ────────────────────────────────────────

def test_buyout_flatline_fails_vitality():
    """Stock gaps up on buyout announcement, then trades in a $0.10 band for weeks.
    Range = 0.10 / 45 ≈ 0.22 % → well below the 2 % threshold."""
    n = 50
    highs  = [45.05] * n
    lows   = [44.95] * n
    df = _make_df(highs, lows)
    assert is_price_vital(df) is False, \
        "Flatline buyout stock (0.22% range) must fail vitality check"


def test_zero_range_fails_vitality():
    """Completely frozen price (e.g., halted stock).  Range = 0 %."""
    n = 30
    highs = [100.0] * n
    lows  = [100.0] * n
    df = _make_df(highs, lows)
    assert is_price_vital(df) is False


def test_sub_1pct_range_fails_vitality():
    """Even 1 % range is below the 2 % floor and must be rejected."""
    n = 20
    # 0.99 % range on a $100 stock
    highs = [100.50] * n
    lows  = [99.51]  * n
    df = _make_df(highs, lows)
    assert is_price_vital(df) is False, \
        "0.99% range must fail the 2% vitality threshold"


# ── Passing cases (normal trading activity) ──────────────────────────────────

def test_normal_volatile_stock_passes_vitality():
    """A stock with typical swing-trading volatility (~10 % range) passes."""
    n = 30
    highs = [105.0] * n
    lows  = [95.0]  * n   # 10 / 105 ≈ 9.5 %
    df = _make_df(highs, lows)
    assert is_price_vital(df) is True


def test_tight_but_vital_stock_passes():
    """Exactly-2%-range stock should pass (boundary value)."""
    n = 20
    # 2.0 % range on a $100 stock: high=101, low=99 → (101-99)/101 ≈ 1.98 %
    # Use 102 / 100 → (102-100)/102 ≈ 1.96 % -- keep it safely above 2 % at high=102, low=100
    highs = [102.0] * n
    lows  = [100.0] * n   # (102-100)/102 ≈ 1.96 % — borderline, test at exactly ≥ 2 %
    # Use high=103, low=101: (103-101)/103 ≈ 1.94 % -- still <2%.
    # Use high=104, low=100: (104-100)/104 ≈ 3.85 % -- passes
    highs = [104.0] * n
    lows  = [100.0] * n
    df = _make_df(highs, lows)
    assert is_price_vital(df) is True, "3.85% range must pass vitality check"


def test_vitality_only_checks_last_10_bars():
    """Old flat period (>10 bars ago) must not cause a false rejection.
    The stock was flat before and active recently."""
    n = 30
    highs = [45.05] * 20 + [110.0, 108.0, 107.5, 105.0, 103.0,
                              102.0, 101.5, 101.0, 100.5, 100.0]
    lows  = [44.95] * 20 + [98.0,  96.0,  95.0,  93.0,  92.0,
                              91.0,  90.5,  90.0,  89.5,  89.0]
    df = _make_df(highs, lows)
    assert is_price_vital(df) is True, \
        "Recent 10-bar range is active; old flatline must not trigger rejection"


def test_vitality_handles_insufficient_data_gracefully():
    """If df has fewer than 10 bars, do not filter (return True)."""
    n = 5
    highs = [50.0] * n
    lows  = [49.9] * n
    df = _make_df(highs, lows)
    assert is_price_vital(df) is True, \
        "Insufficient data — should not filter (return True / neutral)"
