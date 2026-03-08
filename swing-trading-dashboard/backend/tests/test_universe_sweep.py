"""
Tests for universe_sweep.py helpers.

Run from backend/:
    pytest tests/test_universe_sweep.py -v
"""

from __future__ import annotations

import json
import sys
import os

# Ensure backend/ and scripts/ are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1. _load_best_params — missing file raises FileNotFoundError
# ---------------------------------------------------------------------------

def test_load_best_params_missing_raises(tmp_path):
    """FileNotFoundError raised when the params file does not exist."""
    from universe_sweep import _load_best_params

    missing = tmp_path / "nonexistent_best_parameters.json"
    with pytest.raises(FileNotFoundError, match="Best parameters not found"):
        _load_best_params(missing)


# ---------------------------------------------------------------------------
# 2. _load_best_params — returns the 'parameters' sub-dict
# ---------------------------------------------------------------------------

def test_load_best_params_returns_parameters(tmp_path):
    """_load_best_params should return the 'parameters' dict from JSON."""
    from universe_sweep import _load_best_params

    params = {
        "ATR_MULTIPLIER": 1.4,
        "VCP_TIGHTNESS_RANGE": 0.05,
        "BREAKOUT_BUFFER_ATR": 0.4,
        "BREAKOUT_VOL_MULT": 1.1,
        "TARGET_RR": 2.5,
        "TRAIL_ATR_MULT": 2.2,
        "REGIME_BULL_THRESHOLD": 35,
        "ENGINE3_RS_THRESHOLD": -0.05,
    }
    payload = {
        "generated_at": "2026-03-09T00:00:00Z",
        "best_score": 0.1,
        "parameters": params,
    }
    f = tmp_path / "best_parameters.json"
    f.write_text(json.dumps(payload))

    result = _load_best_params(f)
    assert result == params


# ---------------------------------------------------------------------------
# 3. _load_rs_ranked_tickers — missing file raises FileNotFoundError
# ---------------------------------------------------------------------------

def test_load_rs_ranked_tickers_missing_raises():
    """FileNotFoundError raised when rs_ranked_tickers.json does not exist."""
    import universe_sweep as us

    original = us._RS_RANKED_FILE
    try:
        us._RS_RANKED_FILE = Path("/nonexistent_path/rs_ranked_tickers.json")
        with pytest.raises(FileNotFoundError, match="RS ranked tickers not found"):
            us._load_rs_ranked_tickers()
    finally:
        us._RS_RANKED_FILE = original


# ---------------------------------------------------------------------------
# 4. _load_rs_ranked_tickers — filters to cached tickers only
# ---------------------------------------------------------------------------

def test_load_rs_ranked_tickers_filters_uncached(tmp_path, monkeypatch):
    """Only tickers for which cache_exists returns True are included."""
    import universe_sweep as us

    ranked = [
        {"ticker": "AAPL", "rs_score": 1.0},
        {"ticker": "UNCACHED", "rs_score": 0.9},
        {"ticker": "MSFT", "rs_score": 0.8},
    ]
    rs_file = tmp_path / "rs_ranked_tickers.json"
    rs_file.write_text(json.dumps({"generated_at": "x", "ranked": ranked}))

    cached = {"AAPL", "MSFT"}

    monkeypatch.setattr(us, "_RS_RANKED_FILE", rs_file)
    monkeypatch.setattr(us, "cache_exists", lambda ticker: ticker in cached)

    result = us._load_rs_ranked_tickers()
    assert result == ["AAPL", "MSFT"]
    assert "UNCACHED" not in result


# ---------------------------------------------------------------------------
# 5. _load_rs_ranked_tickers — respects top_n
# ---------------------------------------------------------------------------

def test_load_rs_ranked_tickers_respects_top_n(tmp_path, monkeypatch):
    """Returns only first N tickers when N < total cached."""
    import universe_sweep as us

    ranked = [
        {"ticker": "A", "rs_score": 1.0},
        {"ticker": "B", "rs_score": 0.9},
        {"ticker": "C", "rs_score": 0.8},
        {"ticker": "D", "rs_score": 0.7},
    ]
    rs_file = tmp_path / "rs_ranked_tickers.json"
    rs_file.write_text(json.dumps({"generated_at": "x", "ranked": ranked}))

    monkeypatch.setattr(us, "_RS_RANKED_FILE", rs_file)
    monkeypatch.setattr(us, "cache_exists", lambda ticker: True)

    result = us._load_rs_ranked_tickers(top_n=2)
    assert result == ["A", "B"]


# ---------------------------------------------------------------------------
# 6. _build_universe — size 35 returns REPRESENTATIVE_TICKERS
# ---------------------------------------------------------------------------

def test_build_universe_u1_uses_representative(monkeypatch):
    """_build_universe(35) returns REPRESENTATIVE_TICKERS without RS filtering."""
    import universe_sweep as us

    fake_rep = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(us, "REPRESENTATIVE_TICKERS", fake_rep)

    result = us._build_universe(35)
    assert result == fake_rep


# ---------------------------------------------------------------------------
# 7. _build_universe — size > 35 calls _load_rs_ranked_tickers
# ---------------------------------------------------------------------------

def test_build_universe_large_calls_rs_ranked(monkeypatch):
    """_build_universe(80) returns 80-item list from _load_rs_ranked_tickers."""
    import universe_sweep as us

    fake_tickers = [f"T{i}" for i in range(80)]

    monkeypatch.setattr(us, "_load_rs_ranked_tickers", lambda top_n=None: fake_tickers[:top_n] if top_n else fake_tickers)

    result = us._build_universe(80)
    assert len(result) == 80
    assert result == fake_tickers
