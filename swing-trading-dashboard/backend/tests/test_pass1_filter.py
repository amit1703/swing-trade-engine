"""Tests for Pass 1 filter, breadth computation, and discovery candidates."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from cache_store import CacheStore
from main import _pass1_filter, _compute_breadth_from_metadata, _identify_discovery_candidates
from constants import PASS1_MIN_PRICE, PASS1_MIN_AVG_VOLUME, PASS1_MIN_DOLLAR_VOLUME, PASS1_MIN_RS_RANK


def _meta(
    last_close=50.0,
    avg_vol_20d=2_000_000,
    dollar_vol=100_000_000,
    above_sma50=True,
    last_updated="2026-03-24",
    stale=False,
    high_52w=55.0,
    vol_ratio_5d=1.0,
) -> dict:
    return {
        "last_close": last_close,
        "avg_vol_20d": avg_vol_20d,
        "dollar_vol": dollar_vol,
        "above_sma50": above_sma50,
        "last_updated": last_updated,
        "stale": stale,
        "high_52w": high_52w,
        "vol_ratio_5d": vol_ratio_5d,
    }


def _cs_with_meta(tmp_path, tickers_meta: dict) -> CacheStore:
    """Build a CacheStore whose in-memory metadata is pre-populated."""
    cs = CacheStore(cache_dir=str(tmp_path))
    cs._meta = tickers_meta
    return cs


def _fresh_rs_cache(ranks: dict) -> dict:
    from datetime import datetime
    return {
        "_meta": {
            "computed_at": datetime.utcnow().isoformat(),
            "logic_version": "v3",
            "ticker_count": len(ranks),
        },
        **ranks,
    }


# ── _compute_breadth_from_metadata ────────────────────────────────────────────

def test_breadth_two_of_three_above_sma50(tmp_path):
    cs = _cs_with_meta(tmp_path, {
        "A": _meta(above_sma50=True),
        "B": _meta(above_sma50=True),
        "C": _meta(above_sma50=False),
    })
    breadth, _ = _compute_breadth_from_metadata(["A", "B", "C"], cs)
    assert breadth == pytest.approx(2 / 3)


def test_breadth_defaults_to_half_when_no_metadata(tmp_path):
    cs = _cs_with_meta(tmp_path, {})
    breadth, hl = _compute_breadth_from_metadata(["AAPL", "NVDA"], cs)
    assert breadth == pytest.approx(0.5)
    assert hl == pytest.approx(0.5)


def test_breadth_uses_full_universe_not_survivors(tmp_path):
    """Breadth must be computed over ALL tickers, not just those passing filters."""
    cs = _cs_with_meta(tmp_path, {
        "CHEAP": _meta(last_close=5.0, above_sma50=False),
        "STRONG": _meta(last_close=100.0, above_sma50=True),
        "MID": _meta(last_close=50.0, above_sma50=True),
    })
    breadth, _ = _compute_breadth_from_metadata(["CHEAP", "STRONG", "MID"], cs)
    assert breadth == pytest.approx(2 / 3)   # CHEAP is still counted


# ── _pass1_filter ─────────────────────────────────────────────────────────────

def test_pass1_drops_ticker_below_price_floor(tmp_path):
    cs = _cs_with_meta(tmp_path, {
        "CHEAP": _meta(last_close=5.0),
        "GOOD":  _meta(last_close=50.0),
    })
    survivors, _ = _pass1_filter(["CHEAP", "GOOD"], cs, {})
    assert "CHEAP" not in survivors
    assert "GOOD" in survivors


def test_pass1_drops_ticker_below_volume_floor(tmp_path):
    cs = _cs_with_meta(tmp_path, {
        "LOWVOL": _meta(avg_vol_20d=100_000, dollar_vol=5_000_000),
        "GOOD":   _meta(),
    })
    survivors, _ = _pass1_filter(["LOWVOL", "GOOD"], cs, {})
    assert "LOWVOL" not in survivors
    assert "GOOD" in survivors


def test_pass1_drops_ticker_below_rs_floor(tmp_path):
    cs = _cs_with_meta(tmp_path, {
        "WEAKRS": _meta(),
        "GOODRS": _meta(),
    })
    rs_cache = _fresh_rs_cache({"WEAKRS": 20.0, "GOODRS": 75.0})
    survivors, _ = _pass1_filter(["WEAKRS", "GOODRS"], cs, rs_cache)
    assert "WEAKRS" not in survivors
    assert "GOODRS" in survivors


def test_pass1_drops_excluded_stale_ticker(tmp_path):
    cs = _cs_with_meta(tmp_path, {
        "STALE": _meta(last_updated="2025-01-01"),  # very old
        "GOOD":  _meta(),
    })
    survivors, _ = _pass1_filter(["STALE", "GOOD"], cs, {})
    assert "STALE" not in survivors


def test_pass1_passes_through_ticker_with_no_metadata(tmp_path):
    """Tickers with no metadata are let through to the I/O phase (cold start / new universe additions)."""
    cs = _cs_with_meta(tmp_path, {
        "KNOWN": _meta(),
    })
    survivors, _ = _pass1_filter(["KNOWN", "UNKNOWN"], cs, {})
    assert "UNKNOWN" in survivors   # no metadata → pass through, not dropped
    assert "KNOWN" in survivors


def test_pass1_cold_start_passes_all_tickers(tmp_path):
    """When cache is completely empty (first VPS deploy), all tickers survive Pass 1."""
    cs = _cs_with_meta(tmp_path, {})
    survivors, _ = _pass1_filter(["AAPL", "NVDA", "MSFT"], cs, {})
    assert set(survivors) == {"AAPL", "NVDA", "MSFT"}


def test_pass1_keeps_discovery_candidate_below_rs_floor(tmp_path):
    """Discovery candidates (RS 60-70, near-high, vol surge) bypass the RS gate."""
    cs = _cs_with_meta(tmp_path, {
        "DISC": _meta(
            last_close=48.0,
            high_52w=50.0,       # 48/50 = 0.96 → within 5% of 52w high
            vol_ratio_5d=2.0,    # vol expansion >= 1.5
        ),
    })
    rs_cache = _fresh_rs_cache({"DISC": 65.0})  # RS 65 → in 60-70 discovery band

    survivors, discovery = _pass1_filter(["DISC"], cs, rs_cache)
    assert "DISC" in survivors
    assert "DISC" in discovery


def test_pass1_adaptive_tightening_triggers_above_400(tmp_path):
    """When survivors > PASS1_MAX_SURVIVORS, thresholds are tightened."""
    meta = {f"T{i:03d}": _meta() for i in range(420)}
    rs = {f"T{i:03d}": 46.0 for i in range(420)}
    cs = _cs_with_meta(tmp_path, meta)
    rs_cache = _fresh_rs_cache(rs)

    survivors, _ = _pass1_filter(list(meta.keys()), cs, rs_cache)
    assert len(survivors) <= 400


# ── _identify_discovery_candidates ───────────────────────────────────────────

def test_discovery_requires_rs_in_60_70_band(tmp_path):
    cs = _cs_with_meta(tmp_path, {
        "IN_BAND":  _meta(last_close=49.0, high_52w=50.0, vol_ratio_5d=2.0),
        "TOO_HIGH": _meta(last_close=49.0, high_52w=50.0, vol_ratio_5d=2.0),
        "TOO_LOW":  _meta(last_close=49.0, high_52w=50.0, vol_ratio_5d=2.0),
    })
    rs = _fresh_rs_cache({"IN_BAND": 65.0, "TOO_HIGH": 85.0, "TOO_LOW": 40.0})
    disc = _identify_discovery_candidates(["IN_BAND", "TOO_HIGH", "TOO_LOW"], cs, rs)
    assert "IN_BAND" in disc
    assert "TOO_HIGH" not in disc
    assert "TOO_LOW" not in disc
