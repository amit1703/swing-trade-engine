"""Tests for sector clustering — hot_sector injection.

Rule: after scan completes, any sector with ≥ 3 setups gets
hot_sector=True injected into each of its setup dicts.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from main import _inject_hot_sector


def _make_setup(ticker, sector):
    return {
        "ticker": ticker,
        "sector": sector,
        "setup_type": "VCP",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "rr": 2.0,
        "setup_date": "2026-02-27",
    }


# ── Threshold tests ───────────────────────────────────────────────────────────

def test_sector_not_hot_when_fewer_than_3():
    """Sector with 2 setups is NOT hot."""
    setups = [_make_setup("A", "Technology"), _make_setup("B", "Technology")]
    _inject_hot_sector(setups)
    assert all(s["hot_sector"] is False for s in setups)


def test_sector_hot_when_exactly_3():
    """Sector with exactly 3 setups IS hot (boundary condition)."""
    setups = [
        _make_setup("A", "Technology"),
        _make_setup("B", "Technology"),
        _make_setup("C", "Technology"),
    ]
    _inject_hot_sector(setups)
    assert all(s["hot_sector"] is True for s in setups)


def test_sector_hot_when_more_than_3():
    """Sector with 5 setups is hot."""
    setups = [_make_setup(str(i), "Energy") for i in range(5)]
    _inject_hot_sector(setups)
    assert all(s["hot_sector"] is True for s in setups)


# ── Mixed-sector tests ────────────────────────────────────────────────────────

def test_only_hot_sectors_flagged():
    """Sectors with 3+ are hot; sectors with <3 are not — independent."""
    setups = [
        _make_setup("A", "Technology"),
        _make_setup("B", "Technology"),
        _make_setup("C", "Technology"),   # Technology: 3 → hot ✓
        _make_setup("D", "Financials"),
        _make_setup("E", "Financials"),   # Financials: 2 → not hot
    ]
    _inject_hot_sector(setups)

    tech_setups = [s for s in setups if s["sector"] == "Technology"]
    fin_setups  = [s for s in setups if s["sector"] == "Financials"]

    assert all(s["hot_sector"] is True  for s in tech_setups)
    assert all(s["hot_sector"] is False for s in fin_setups)


def test_every_setup_receives_hot_sector_field():
    """All setups get the hot_sector field (no setup is left without it)."""
    setups = [
        _make_setup("A", "Healthcare"),
        _make_setup("B", "Energy"),
    ]
    _inject_hot_sector(setups)
    for s in setups:
        assert "hot_sector" in s, f"Setup {s['ticker']} missing hot_sector"


def test_empty_setups_list_does_not_crash():
    """Empty list must not raise."""
    _inject_hot_sector([])   # should complete without exception


def test_setups_without_sector_field_handled():
    """Setups missing 'sector' key default to 'Unknown' and don't crash."""
    s1 = {"ticker": "X", "entry": 100.0, "stop_loss": 95.0,
          "take_profit": 110.0, "rr": 2.0, "setup_date": "2026-02-27",
          "setup_type": "VCP"}
    s2 = {"ticker": "Y", "entry": 100.0, "stop_loss": 95.0,
          "take_profit": 110.0, "rr": 2.0, "setup_date": "2026-02-27",
          "setup_type": "VCP"}
    _inject_hot_sector([s1, s2])
    assert "hot_sector" in s1
    assert "hot_sector" in s2
