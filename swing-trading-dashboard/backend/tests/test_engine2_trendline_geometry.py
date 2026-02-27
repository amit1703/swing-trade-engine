"""Tests for the trendline geometry fixes (Fixes 2 & 3).

Fix 2 — No-Slice Rule (unit-tested directly on helpers):
  - Ascending : no close below the line; wick tolerance ≤ 1 %.
  - Descending: no high more than 1 % above the line.

Fix 3 — Macro Anchors (integration via detect_*):
  - Descending: anchor A = global High.max() — even if at array boundary
    where find_peaks() would miss it.
  - Ascending : anchor A = global Low.min()  — same.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine2 import (
    _detect_descending_trendline,
    _detect_ascending_trendline,
    _ascending_no_slice,
    _descending_no_slice,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(highs, lows, closes=None, n=None):
    if n is None:
        n = len(highs)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    if closes is None:
        closes = (np.array(highs) + np.array(lows)) / 2
    return pd.DataFrame(
        {
            "High":      np.array(highs,  dtype=float),
            "Low":       np.array(lows,   dtype=float),
            "Close":     np.array(closes, dtype=float),
            "Adj Close": np.array(closes, dtype=float),
            "Open":      np.array(closes, dtype=float),
            "Volume":    np.ones(n) * 1_000_000,
        },
        index=dates,
    )


# =============================================================================
# FIX 2 — No-Slice helpers (unit tests)
# =============================================================================

# ── _ascending_no_slice ───────────────────────────────────────────────────────

def test_ascending_no_slice_rejects_close_below_line():
    """A bar whose close is strictly below the ascending trendline must reject."""
    n = 60
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    lows   = np.full(n, 94.0)
    closes = np.full(n, 95.0)

    # Anchor A: bar 5 → $80
    lows[5]   = 80.0
    closes[5] = 81.0
    # Anchor B: bar 45 → $90
    lows[45]   = 90.0
    closes[45] = 91.0

    ti_date  = dates[5]
    day_diff = (dates[45] - ti_date).days   # ≈ 56 calendar days
    slope    = (90.0 - 80.0) / day_diff     # ≈ +0.179 /day

    # Force close[25] clearly below the trendline at that bar
    bar25_days = (dates[25] - ti_date).days
    tl_at_25   = 80.0 + slope * bar25_days   # ≈ 85
    closes[25] = tl_at_25 - 2.0              # 2 below trendline → violation

    result = _ascending_no_slice(lows, closes, dates, 5, 80.0, slope)
    assert result is False, \
        "Close below ascending trendline must be rejected"


def test_ascending_no_slice_rejects_wick_more_than_1pct_below():
    """A wick more than 1 % below the trendline (even with close above) must reject."""
    n = 60
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    lows   = np.full(n, 95.0)
    closes = np.full(n, 96.0)
    lows[5]   = 80.0
    closes[5] = 81.0
    lows[45]   = 90.0
    closes[45] = 91.0

    ti_date  = dates[5]
    day_diff = (dates[45] - ti_date).days
    slope    = (90.0 - 80.0) / day_diff

    bar25_days = (dates[25] - ti_date).days
    tl_at_25   = 80.0 + slope * bar25_days
    lows[25]   = tl_at_25 * 0.98     # 2 % below — exceeds 1 % wick tolerance
    closes[25] = tl_at_25 + 1.0      # close is ABOVE line (only wick violates)

    result = _ascending_no_slice(lows, closes, dates, 5, 80.0, slope)
    assert result is False, \
        "Wick > 1% below ascending trendline must be rejected"


def test_ascending_no_slice_allows_minor_wick_within_tolerance():
    """A wick 0.5 % below the line (within 1 % tolerance) must pass."""
    n = 60
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    lows   = np.full(n, 94.0)
    closes = np.full(n, 96.0)
    lows[5]   = 80.0
    closes[5] = 81.0
    lows[45]   = 90.0
    closes[45] = 91.0

    ti_date  = dates[5]
    day_diff = (dates[45] - ti_date).days
    slope    = (90.0 - 80.0) / day_diff

    bar25_days = (dates[25] - ti_date).days
    tl_at_25   = 80.0 + slope * bar25_days
    lows[25]   = tl_at_25 * 0.995    # 0.5 % below — within tolerance
    closes[25] = tl_at_25 + 2.0      # close well above line

    result = _ascending_no_slice(lows, closes, dates, 5, 80.0, slope)
    assert result is True, \
        "Minor wick within 1% tolerance must be allowed"


# ── _descending_no_slice ──────────────────────────────────────────────────────

def test_descending_no_slice_rejects_high_above_line():
    """A bar whose high exceeds the descending trendline by > 1 % must reject."""
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    highs = np.full(n, 100.0)
    highs[5]  = 120.0   # Anchor A
    highs[55] = 100.0   # Anchor B

    pi_date  = dates[5]
    day_diff = (dates[55] - pi_date).days   # ≈ 70 cal days
    slope    = (100.0 - 120.0) / day_diff   # ≈ −0.286 /day

    bar30_days = (dates[30] - pi_date).days
    tl_at_30   = 120.0 + slope * bar30_days     # ≈ 110
    highs[30]  = tl_at_30 * 1.03               # 3 % above → exceeds tolerance

    result = _descending_no_slice(highs, dates, 5, 120.0, slope)
    assert result is False, \
        "High > 1% above descending trendline must be rejected"


def test_descending_no_slice_allows_minor_wick_within_tolerance():
    """A high 0.5 % above the descending line (within 1 % tolerance) must pass.

    Use default highs = 88 so they stay below the trendline (TL drops from
    ~120 to ~90 over the window).  The 0.5%-above wick sits at bar 30 only.
    """
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    # Default highs = 88, well below the declining trendline (min TL ≈ 90 at bar 79)
    highs = np.full(n, 88.0)
    highs[5]  = 120.0
    highs[55] = 100.0

    pi_date  = dates[5]
    day_diff = (dates[55] - pi_date).days
    slope    = (100.0 - 120.0) / day_diff

    bar30_days = (dates[30] - pi_date).days
    tl_at_30   = 120.0 + slope * bar30_days
    highs[30]  = tl_at_30 * 1.005              # 0.5 % above — within tolerance

    result = _descending_no_slice(highs, dates, 5, 120.0, slope)
    assert result is True, \
        "Minor wick within 1% tolerance must be allowed"


# =============================================================================
# FIX 3 — Macro Anchors (integration)
# =============================================================================

def test_descending_macro_anchor_is_global_high():
    """
    Anchor A must always be the absolute High.max() even when it sits at the
    array boundary (index 0), where scipy find_peaks() normally misses it.

    Data (n=60, shorter window makes TL stay above price throughout):
      bar 0  → high = $150  (global max — boundary)
      bar 30 → high = $120  (secondary peak, detected by find_peaks)
      others → high = $85   (far below trendline which ranges $150→$92)

    No-slice:   highs = 85 ≤ TL_k × 1.01 at all bars k > 0 ✓
    Relevance:  lc = 84, TL today ≈ 92, 92 ≤ 84 × 1.20 = 100.8 ✓
    Expected:   peak1.price = $150
    """
    n = 60
    highs  = np.full(n, 85.0)
    lows   = np.full(n, 83.0)
    closes = np.full(n, 84.0)

    highs[0]   = 150.0
    closes[0]  = 148.0
    highs[30]  = 120.0
    closes[30] = 118.0

    df = _make_df(highs, lows, closes, n)

    result = _detect_descending_trendline("TEST", df)

    assert result is not None, \
        "Should detect a descending trendline anchored at the global max"
    assert abs(result["peak1"]["price"] - 150.0) < 1.0, \
        f"Anchor A must be global max ($150), got {result['peak1']['price']}"


def test_ascending_macro_anchor_is_global_low():
    """
    Anchor A must always be the absolute Low.min() even when it sits at the
    array boundary (index 0), where find_peaks() normally misses it.

    Data (n=60, price well above trendline throughout):
      bar 0  → low = $50  (global min — boundary)
      bar 30 → low = $80  (secondary trough)
      others → low = $114 / close = $116 (far above trendline)

    No-slice:   close ≥ TL_k at all bars k > 0 (116 >> TL which peaks at $50) ✓
    Relevance:  lc = 116, TL today ≈ 108, 108 ≥ 116 × 0.80 = 92.8 ✓
    Expected:   trough1.price = $50
    """
    n = 60
    closes = np.full(n, 116.0)
    highs  = np.full(n, 118.0)
    lows   = np.full(n, 114.0)

    lows[0]   = 50.0
    closes[0] = 51.0
    lows[30]  = 80.0
    closes[30] = 81.0

    df = _make_df(highs, lows, closes, n)

    result = _detect_ascending_trendline("TEST", df)

    assert result is not None, \
        "Should detect an ascending trendline anchored at the global min"
    assert abs(result["trough1"]["price"] - 50.0) < 1.0, \
        f"Anchor A must be global min ($50), got {result['trough1']['price']}"


def test_descending_returns_none_when_global_max_is_last_bar():
    """
    If the global high is at the very last bar, there is no room for an
    anchor B (nothing comes after the peak) → must return None.
    """
    n = 80
    # Linearly rising prices: global max at bar 79
    closes = np.linspace(80.0, 120.0, n)
    highs  = closes * 1.005
    lows   = closes * 0.995

    df = _make_df(highs, lows, closes, n)

    result = _detect_descending_trendline("TEST", df)
    assert result is None, \
        "No descending trendline possible when global max is at the last bar"


def test_ascending_returns_none_when_global_min_is_last_bar():
    """
    If the global low is at the very last bar, no ascending anchor B exists
    → must return None.
    """
    n = 80
    # Linearly falling prices: global min at bar 79
    closes = np.linspace(120.0, 80.0, n)
    highs  = closes * 1.005
    lows   = closes * 0.995

    df = _make_df(highs, lows, closes, n)

    result = _detect_ascending_trendline("TEST", df)
    assert result is None, \
        "No ascending trendline possible when global min is at the last bar"
