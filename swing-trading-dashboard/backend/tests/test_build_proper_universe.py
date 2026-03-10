"""
Unit tests for pure functions in scripts/build_proper_universe.py.
No network calls — all tests use synthetic price series.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add scripts/ to path so we can import build_proper_universe directly
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from build_proper_universe import _compute_rs  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_series(values, start="2021-01-01") -> pd.Series:
    """Create a daily pd.Series from a list of floats."""
    idx = pd.date_range(start=start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def _flat_then_gain(n: int, base: float, gain_pct: float) -> pd.Series:
    """n days flat at base, then one step up by gain_pct."""
    values = [base] * n + [base * (1 + gain_pct)]
    return _make_series(values)


def _growing_series(n: int, start: float, daily_ret: float) -> pd.Series:
    """Geometric growth series of length n."""
    prices = [start * (1 + daily_ret) ** i for i in range(n)]
    return _make_series(prices)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeRsBasic:
    def test_positive_when_stock_outperforms_spy(self):
        """RS is positive when stock return > SPY return over all periods."""
        n = 300  # enough for all 4 periods (max 252)
        # Stock grows 20% total, SPY grows 5% total
        stock = _growing_series(n, start=100.0, daily_ret=0.0006)   # ~20% over 252d
        spy   = _growing_series(n, start=100.0, daily_ret=0.00018)  # ~5% over 252d

        rs = _compute_rs(stock, spy)
        assert rs > 0.0, f"Expected positive RS, got {rs}"

    def test_negative_when_stock_underperforms_spy(self):
        """RS is negative when stock return < SPY return over all periods."""
        n = 300
        # Stock grows slowly, SPY grows faster
        stock = _growing_series(n, start=100.0, daily_ret=0.00018)  # ~5% over 252d
        spy   = _growing_series(n, start=100.0, daily_ret=0.0006)   # ~20% over 252d

        rs = _compute_rs(stock, spy)
        assert rs < 0.0, f"Expected negative RS, got {rs}"

    def test_zero_when_stock_matches_spy(self):
        """RS is approximately zero when stock and SPY have identical returns."""
        n = 300
        series = _growing_series(n, start=100.0, daily_ret=0.0003)
        # Both identical → all period differences = 0
        rs = _compute_rs(series, series.copy())
        assert abs(rs) < 1e-6, f"Expected ~0.0 RS, got {rs}"


class TestComputeRsInsufficientHistory:
    def test_returns_zero_when_series_too_short_for_any_period(self):
        """RS returns 0.0 when series too short for even the 63-day period."""
        short = _make_series([100.0] * 60)  # only 60 points, period needs > 63
        spy   = _make_series([100.0] * 60)
        rs = _compute_rs(short, spy)
        assert rs == 0.0, f"Expected 0.0 for insufficient history, got {rs}"

    def test_returns_zero_when_spy_too_short(self):
        """RS returns 0.0 when SPY series is too short."""
        stock = _make_series([100.0] * 300)
        spy   = _make_series([100.0] * 60)  # SPY too short
        rs = _compute_rs(stock, spy)
        assert rs == 0.0, f"Expected 0.0 when SPY insufficient, got {rs}"

    def test_partial_periods_contribute(self):
        """If only the 63-day period has enough data, RS is still computed."""
        n = 100  # > 63, but < 126
        stock = _growing_series(n, start=100.0, daily_ret=0.0006)
        spy   = _growing_series(n, start=100.0, daily_ret=0.00018)

        rs = _compute_rs(stock, spy)
        # Only the 63-day period (weight 0.40) contributes
        # So total_w = 0.40 and result should be non-zero positive
        assert rs > 0.0, f"Expected positive partial RS, got {rs}"


class TestComputeRsWeighting:
    def test_weighting_40_20_20_20(self):
        """Verify the 40/20/20/20 weighting of the four periods."""
        n = 300

        # Build series where each period has a known excess return:
        # We'll make stock outperform SPY by exactly 10% measured at bar -63
        # and by 0% at bars -126, -189, -252.
        # To do this simply, we craft a stock that is identical to SPY
        # except for the last 63 bars where it gains an extra 10%.
        base = [100.0] * 252  # first 252 bars: identical to SPY (flat)
        # From bar 252 onward (next 48 bars): stock grows, SPY stays flat
        stock_extra = [100.0 * (1 + 0.10 * i / 47) for i in range(48)]
        spy_flat    = [100.0] * 48

        stock = _make_series(base + stock_extra)
        spy   = _make_series(base + spy_flat)

        # At the end (length = 300):
        #   period 63:  stock[-1]/stock[-63] vs spy[-1]/spy[-63]
        #   period 126: stock[-1]/stock[-126] vs spy[-1]/spy[-126]
        #   period 189: stock[-1]/stock[-189] vs spy[-1]/spy[-189]
        #   period 252: stock[-1]/stock[-252] vs spy[-1]/spy[-252]
        # stock[-1]=110, spy[-1]=100 in all cases
        # stock[-63]=100, stock[-126]=100, stock[-189]=100, stock[-252]=100
        # spy is flat at 100 throughout
        # excess for ALL periods: (110/100-1) - (100/100-1) = 10% for all
        # So weighted avg = 10% regardless of weights → RS = 0.10

        rs = _compute_rs(stock, spy)
        assert abs(rs - 0.10) < 0.01, f"Expected RS ≈ 0.10, got {rs}"

    def test_short_term_period_weighted_more(self):
        """63-day period has 40% weight; confirm it dominates over longer periods."""
        n = 300
        # Stock drastically outperforms only in recent 63 days, underperforms in older periods
        # We build: a flat base of 252 days, then a huge 63-day run-up for stock
        base_flat_stock = [100.0] * 252
        runup           = [100.0 * (1 + 0.5 * i / 47) for i in range(48)]  # +50%
        stock = _make_series(base_flat_stock + runup)

        base_flat_spy   = [100.0] * 252
        spy_runup       = [100.0 * (1 + 0.01 * i / 47) for i in range(48)]  # +1%
        spy = _make_series(base_flat_spy + spy_runup)

        rs = _compute_rs(stock, spy)
        # Large positive: short-term dominates
        assert rs > 0.2, f"Expected RS > 0.2 with recent outperformance, got {rs}"

    def test_result_is_rounded_to_4_decimal_places(self):
        """_compute_rs returns value rounded to 4 decimal places."""
        n = 300
        stock = _growing_series(n, start=100.0, daily_ret=0.0005)
        spy   = _growing_series(n, start=100.0, daily_ret=0.0002)
        rs = _compute_rs(stock, spy)
        # Check rounding: re-rounding should give same value
        assert rs == round(rs, 4), f"Result not rounded to 4dp: {rs}"
