"""
TDD tests for engine1._find_pivot_resistance()

Naming conventions used by _spike_at():
  - A "spike" is a local maximum: highs[idx] is set to spike_val,
    and the ±3 neighbours are depressed so argrelextrema(order=3) detects it.
"""

import numpy as np
import pandas as pd
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engines.engine1 import _find_pivot_resistance


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_df(n: int = 150, highs=None, current_close: float = 95.0) -> pd.DataFrame:
    """Build a minimal daily OHLCV DataFrame with controlled High values."""
    if highs is None:
        highs = np.ones(n) * 100.0
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = np.ones(n) * current_close
    return pd.DataFrame(
        {
            "Open":      closes - 1.0,
            "High":      highs.copy(),
            "Low":       closes - 2.0,
            "Close":     closes,
            "Adj Close": closes,
            "Volume":    [1_000_000] * n,
        },
        index=dates,
    )


def _spike_at(highs: np.ndarray, idx: int, spike_val: float, order: int = 3) -> np.ndarray:
    """
    Return a copy of `highs` with a clear local maximum at `idx`.
    Sets highs[idx] = spike_val and depresses ±order neighbours to spike_val - 1.
    """
    h = highs.copy()
    h[idx] = spike_val
    for off in range(1, order + 1):
        if idx - off >= 0:
            h[idx - off] = min(h[idx - off], spike_val - 1.0)
        if idx + off < len(h):
            h[idx + off] = min(h[idx + off], spike_val - 1.0)
    return h


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_no_zone_when_fewer_than_two_pivots():
    """Only one pivot high in the lookback window → no cluster → empty list."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 70, 106.0)
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert zones == []


def test_two_matching_pivots_form_one_zone():
    """Two pivots within 1.5% and ≥7 bars apart → exactly one pivot zone."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 105.5)  # 0.48% diff, 40 bars apart
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert len(zones) == 1
    assert zones[0]["source"] == "pivot"


def test_pivots_too_close_in_bars_not_paired():
    """Pivots separated by fewer than PIVOT_MIN_SEPARATION_DAYS bars → no zone."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 60, 105.0)
    highs = _spike_at(highs, 64, 105.2)  # only 4 bars apart — below threshold
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert zones == []


def test_pivots_too_far_apart_in_price_not_paired():
    """Two pivots > 1.5% apart in price → do not cluster → no zone."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 107.0)  # 1.9% diff — above PIVOT_TOUCH_MARGIN_PCT
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert zones == []


def test_zone_above_current_price_is_resistance():
    """Cluster level > current_price → zone type is 'RESISTANCE'."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 105.3)
    df = _make_df(highs=highs, current_close=95.0)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert len(zones) == 1
    assert zones[0]["type"] == "RESISTANCE"


def test_zone_below_current_price_is_not_returned():
    """Pivot resistance only emits overhead zones — clusters below current price are dropped."""
    # Background at 90, spikes at 95 (above background, below current_price=100)
    highs = np.ones(150) * 90.0
    highs = _spike_at(highs, 40, 95.0)
    highs = _spike_at(highs, 80, 95.3)
    df = _make_df(highs=highs, current_close=100.0)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=100.0)
    assert zones == []


def test_zone_bounds_use_atr_padding():
    """upper = level + 0.1*ATR  ;  lower = level - 0.1*ATR  (tight band around mean level)."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 104.5)
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert len(zones) == 1
    level = (105.0 + 104.5) / 2  # mean of cluster highs = 104.75
    assert zones[0]["upper"] == pytest.approx(level + 0.1 * 2.0, abs=0.01)
    assert zones[0]["lower"] == pytest.approx(level - 0.1 * 2.0, abs=0.01)


def test_source_field_is_always_pivot():
    """Every zone returned by _find_pivot_resistance has source == 'pivot'."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 105.3)
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert all(z["source"] == "pivot" for z in zones)
