"""Tests for RS percentile ranking and sector strength (Task 8, 10)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest
import scoring
from scoring import compute_rs_rank_map, compute_top_sectors


@pytest.fixture(autouse=True)
def _no_rs_disk_cache(tmp_path, monkeypatch):
    """Redirect RS_RANK_CACHE_FILE to a fresh temp file for every test."""
    monkeypatch.setattr(scoring, "RS_RANK_CACHE_FILE", str(tmp_path / "rs_rank_cache.json"))


def _make_cache_entry(close_vals):
    """Build a minimal _ticker_cache entry (ts, df) from a close price list."""
    dates = pd.date_range("2024-01-02", periods=len(close_vals), freq="B")
    df = pd.DataFrame({
        "Adj Close": close_vals,
        "High":      [c * 1.01 for c in close_vals],
        "Low":       [c * 0.99 for c in close_vals],
        "Close":     close_vals,
        "Volume":    [1_000_000] * len(close_vals),
    }, index=dates)
    return (0.0, df)


def _make_spy(close_vals):
    """Build a minimal SPY DataFrame."""
    dates = pd.date_range("2024-01-02", periods=len(close_vals), freq="B")
    return pd.DataFrame({
        "Adj Close": close_vals,
        "High":      [c * 1.01 for c in close_vals],
        "Low":       [c * 0.99 for c in close_vals],
        "Close":     close_vals,
        "Volume":    [50_000_000] * len(close_vals),
    }, index=dates)


# ── compute_rs_rank_map ───────────────────────────────────────────────────────

def test_rs_rank_map_ranks_in_0_to_100_range():
    """All returned ranks must be in [0, 100]."""
    n = 252
    spy = _make_spy([400.0 + i * 0.1 for i in range(n)])
    cache = {
        "A": _make_cache_entry([100.0 + i * 0.2 for i in range(n)]),  # outperforms
        "B": _make_cache_entry([100.0 + i * 0.1 for i in range(n)]),  # in-line
        "C": _make_cache_entry([100.0 + i * 0.05 for i in range(n)]), # underperforms
    }
    result = compute_rs_rank_map(cache, ["A", "B", "C"], spy)
    for ticker, rank in result.items():
        assert 0 <= rank <= 100, f"{ticker} rank={rank} out of range"


def test_rs_rank_map_outperformer_has_higher_rank():
    """Ticker with stronger returns vs SPY must have higher rank."""
    n = 252
    spy = _make_spy([400.0] * n)  # flat SPY
    cache = {
        "STRONG": _make_cache_entry([100.0 + i * 0.5 for i in range(n)]),  # +125% over year
        "WEAK":   _make_cache_entry([100.0 - i * 0.1 for i in range(n)]),  # declining
    }
    result = compute_rs_rank_map(cache, ["STRONG", "WEAK"], spy)
    assert "STRONG" in result and "WEAK" in result
    assert result["STRONG"] > result["WEAK"]


def test_rs_rank_map_empty_cache_returns_empty_dict():
    """Empty cache must return empty dict, not raise."""
    n = 252
    spy = _make_spy([400.0] * n)
    result = compute_rs_rank_map({}, [], spy)
    assert result == {}


def test_rs_rank_map_none_spy_returns_empty_dict():
    """None SPY df must return empty dict."""
    result = compute_rs_rank_map({}, [], None)
    assert result == {}


def test_rs_rank_map_insufficient_data_skipped():
    """Tickers with fewer than 63 bars are skipped gracefully."""
    n = 252
    spy = _make_spy([400.0] * n)
    cache = {
        "SHORT": _make_cache_entry([100.0] * 30),  # only 30 bars
        "LONG":  _make_cache_entry([100.0 + i * 0.2 for i in range(n)]),
    }
    result = compute_rs_rank_map(cache, ["SHORT", "LONG"], spy)
    assert "SHORT" not in result
    assert "LONG" in result


# ── compute_top_sectors ───────────────────────────────────────────────────────

def test_top_sectors_returns_at_most_top_n():
    """Returns at most top_n=5 sector names."""
    n = 252
    spy = _make_spy([400.0 + i * 0.1 for i in range(n)])
    cache = {
        f"T{i}": _make_cache_entry([100.0 + i * 0.1 * j for j in range(n)])
        for i in range(10)
    }
    tickers = list(cache.keys())
    sectors = {f"T{i}": f"Sector{i % 7}" for i in range(10)}
    result = compute_top_sectors(cache, tickers, sectors, spy, top_n=5)
    assert len(result) <= 5


def test_top_sectors_best_sector_is_first():
    """The sector with highest avg RS score must be at index 0."""
    n = 252
    spy = _make_spy([400.0] * n)  # flat SPY
    cache = {
        "TECH1": _make_cache_entry([100.0 + i * 0.5 for i in range(n)]),  # best
        "TECH2": _make_cache_entry([100.0 + i * 0.4 for i in range(n)]),  # good
        "ENRG1": _make_cache_entry([100.0 + i * 0.1 for i in range(n)]),  # weak
    }
    sectors = {"TECH1": "Technology", "TECH2": "Technology", "ENRG1": "Energy"}
    result = compute_top_sectors(cache, ["TECH1", "TECH2", "ENRG1"], sectors, spy)
    assert len(result) > 0
    assert result[0] == "Technology"


def test_top_sectors_none_spy_returns_empty():
    """None SPY must return empty list, not raise."""
    result = compute_top_sectors({}, [], {}, None)
    assert result == []
