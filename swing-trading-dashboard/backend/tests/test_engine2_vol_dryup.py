"""Tests for VCP Path A volume dry-up gate.

Rule: in the final contraction window (last 10 bars), at least one day
must have volume < 50% of the 50-day average volume.

This eliminates setups where volume has merely "drifted down" from the
average but never had a genuine institutional dry-up day.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine2 import _has_vol_dryup


# ── Unit tests for _has_vol_dryup ────────────────────────────────────────────

def test_no_dryup_when_all_bars_above_50pct():
    """All bars at 70% of avg → no genuine dry-up day → False."""
    avg_vol = 1_000_000.0
    volume = pd.Series(np.full(50, avg_vol * 0.70))
    assert _has_vol_dryup(volume, avg_vol) is False


def test_accepts_one_bar_below_50pct():
    """One bar at 40% of avg within window → genuine dry-up → True."""
    avg_vol = 1_000_000.0
    vols = np.full(50, avg_vol * 0.70)
    vols[-5] = avg_vol * 0.40   # one day at 40% — inside 10-bar window
    volume = pd.Series(vols)
    assert _has_vol_dryup(volume, avg_vol) is True


def test_exactly_50pct_fails():
    """Volume exactly at 50% is NOT strictly less than 50% → False."""
    avg_vol = 1_000_000.0
    vols = np.full(50, avg_vol * 0.70)
    vols[-3] = avg_vol * 0.50   # exactly 50% — not < 50%
    volume = pd.Series(vols)
    assert _has_vol_dryup(volume, avg_vol) is False


def test_dryup_outside_10bar_window_ignored():
    """Dry-up day at bar -11 (outside the 10-bar window) must be ignored."""
    avg_vol = 1_000_000.0
    vols = np.full(50, avg_vol * 0.70)
    vols[-11] = avg_vol * 0.30   # 30%, but outside window
    volume = pd.Series(vols)
    assert _has_vol_dryup(volume, avg_vol) is False


def test_dryup_at_boundary_of_window():
    """Dry-up day at bar -10 (boundary of 10-bar window, iloc[-10]) → True."""
    avg_vol = 1_000_000.0
    vols = np.full(50, avg_vol * 0.70)
    vols[-10] = avg_vol * 0.30   # 30%, at the edge of the window
    volume = pd.Series(vols)
    assert _has_vol_dryup(volume, avg_vol) is True


def test_zero_avg_vol_returns_false():
    """avg_vol of zero must not divide and must return False gracefully."""
    volume = pd.Series(np.full(20, 500_000.0))
    assert _has_vol_dryup(volume, 0.0) is False
