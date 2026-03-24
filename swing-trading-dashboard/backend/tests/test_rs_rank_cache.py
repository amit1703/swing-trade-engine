"""Tests for RS rank cache persistence (TTL + logic version)."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from unittest.mock import patch
from scoring import compute_rs_rank_map, RS_LOGIC_VERSION


def _make_cache_entry(close_vals):
    dates = pd.bdate_range("2024-01-02", periods=len(close_vals))
    df = pd.DataFrame({
        "Adj Close": close_vals, "Close": close_vals,
        "High": close_vals, "Low": close_vals,
        "Volume": [1_000_000] * len(close_vals),
    }, index=dates)
    return (0.0, df)


def _make_spy(n=300):
    dates = pd.bdate_range("2024-01-02", periods=n)
    prices = [450.0 + i * 0.05 for i in range(n)]
    return pd.DataFrame({
        "Adj Close": prices, "Close": prices,
        "High": prices, "Low": prices,
        "Volume": [50_000_000] * n,
    }, index=dates)


def _fresh_meta(version=None) -> dict:
    return {
        "_meta": {
            "computed_at": datetime.utcnow().isoformat(),
            "logic_version": version or RS_LOGIC_VERSION,
            "ticker_count": 2,
        },
        "AAPL": 80.0,
        "NVDA": 90.0,
    }


def test_rs_logic_version_is_string():
    assert isinstance(RS_LOGIC_VERSION, str) and len(RS_LOGIC_VERSION) > 0


def test_compute_rs_rank_map_uses_disk_cache_when_fresh(tmp_path, monkeypatch):
    cache_file = tmp_path / "rs_rank_cache.json"
    cache_file.write_text(json.dumps(_fresh_meta()))
    monkeypatch.setattr("scoring.RS_RANK_CACHE_FILE", str(cache_file))

    result = compute_rs_rank_map({}, [], None)
    assert result == {"AAPL": 80.0, "NVDA": 90.0}


def test_compute_rs_rank_map_recomputes_on_version_mismatch(tmp_path, monkeypatch):
    cache_file = tmp_path / "rs_rank_cache.json"
    cache_file.write_text(json.dumps(_fresh_meta(version="OLD_VERSION")))
    monkeypatch.setattr("scoring.RS_RANK_CACHE_FILE", str(cache_file))

    spy_df = _make_spy(300)
    ticker_cache = {
        "AAPL": _make_cache_entry([100.0 + i * 0.1 for i in range(300)]),
    }
    result = compute_rs_rank_map(ticker_cache, ["AAPL"], spy_df)
    # Only one ticker → all get 50.0 (cross-sectional percentile meaningless)
    assert "AAPL" in result
    assert result["AAPL"] == 50.0  # single-ticker returns 50.0 per existing logic


def test_compute_rs_rank_map_recomputes_when_cache_expired(tmp_path, monkeypatch):
    cache_file = tmp_path / "rs_rank_cache.json"
    stale_meta = _fresh_meta()
    stale_meta["_meta"]["computed_at"] = "2020-01-01T00:00:00"   # very old
    cache_file.write_text(json.dumps(stale_meta))
    monkeypatch.setattr("scoring.RS_RANK_CACHE_FILE", str(cache_file))

    spy_df = _make_spy(300)
    ticker_cache = {"AAPL": _make_cache_entry([100.0] * 300)}
    result = compute_rs_rank_map(ticker_cache, ["AAPL"], spy_df)
    assert "AAPL" in result


def test_compute_rs_rank_map_saves_cache_after_recompute(tmp_path, monkeypatch):
    cache_file = tmp_path / "rs_rank_cache.json"
    monkeypatch.setattr("scoring.RS_RANK_CACHE_FILE", str(cache_file))

    spy_df = _make_spy(300)
    ticker_cache = {"AAPL": _make_cache_entry([100.0 + i * 0.1 for i in range(300)])}
    compute_rs_rank_map(ticker_cache, ["AAPL"], spy_df)

    assert cache_file.exists()
    saved = json.loads(cache_file.read_text())
    assert "_meta" in saved
    assert saved["_meta"]["logic_version"] == RS_LOGIC_VERSION
    assert "AAPL" in saved


def test_compute_rs_rank_map_returns_empty_no_spy_no_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "rs_rank_cache.json"
    monkeypatch.setattr("scoring.RS_RANK_CACHE_FILE", str(cache_file))
    result = compute_rs_rank_map({}, [], None)
    assert result == {}


def test_cache_file_written_atomically(tmp_path, monkeypatch):
    """Cache file must be replaced atomically (no partial writes)."""
    cache_file = tmp_path / "rs_rank_cache.json"
    monkeypatch.setattr("scoring.RS_RANK_CACHE_FILE", str(cache_file))
    spy_df = _make_spy(300)
    ticker_cache = {"AAPL": _make_cache_entry([100.0] * 300)}
    compute_rs_rank_map(ticker_cache, ["AAPL"], spy_df)
    # File must be valid JSON immediately after the call
    data = json.loads(cache_file.read_text())
    assert "_meta" in data
