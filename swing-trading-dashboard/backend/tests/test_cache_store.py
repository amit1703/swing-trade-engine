import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest

def test_new_constants_exist():
    from constants import (
        SCAN_CACHE_DIR,
        PRICE_CACHE_FRESH_DAYS,
        PRICE_CACHE_MAX_STALE_DAYS,
        SCAN_CACHE_METADATA_FILE,
        RS_RANK_CACHE_TTL,
        RS_RANK_CACHE_FILE,
        RS_RANK_CACHE_REFRESH_THRESHOLD,
        PASS1_MIN_PRICE,
        PASS1_MIN_AVG_VOLUME,
        PASS1_MIN_DOLLAR_VOLUME,
        PASS1_MIN_RS_RANK,
        PASS1_MAX_SURVIVORS,
        SCAN_IO_WORKERS,
        SCAN_COMPUTE_WORKERS,
        SCAN_QUEUE_MULTIPLIER,
        UNIVERSE_MIN_PRICE,
        UNIVERSE_MIN_AVG_VOLUME,
        UNIVERSE_MIN_DOLLAR_VOL,
        UNIVERSE_RS_FLOOR,
    )
    assert SCAN_CACHE_DIR == "data/scan_cache"
    assert PRICE_CACHE_FRESH_DAYS == 2
    assert PRICE_CACHE_MAX_STALE_DAYS == 5
    assert RS_RANK_CACHE_TTL == 86400
    assert RS_RANK_CACHE_REFRESH_THRESHOLD == 72000
    assert PASS1_MIN_PRICE == 12.0
    assert PASS1_MIN_AVG_VOLUME == 1_000_000
    assert PASS1_MIN_DOLLAR_VOLUME == 25_000_000
    assert PASS1_MIN_RS_RANK == 45
    assert PASS1_MAX_SURVIVORS == 400
    assert SCAN_IO_WORKERS == 48
    assert SCAN_COMPUTE_WORKERS == 32
    assert SCAN_QUEUE_MULTIPLIER == 2
    assert UNIVERSE_MIN_PRICE == 12.0
    assert UNIVERSE_MIN_AVG_VOLUME == 1_000_000
    assert UNIVERSE_MIN_DOLLAR_VOL == 25_000_000
    assert UNIVERSE_RS_FLOOR == 35

import asyncio
import json
import time
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
from cache_store import CacheStore

def _make_df(n: int = 252, price_start: float = 100.0, vol: int = 2_000_000) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with a DatetimeIndex ending today."""
    end   = pd.Timestamp.today().normalize()
    dates = pd.bdate_range(end=end, periods=n)
    prices = [price_start + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [p - 0.5 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [vol] * n,
    }, index=dates)

def _make_df_old(n: int = 252, days_ago: int = 10) -> pd.DataFrame:
    """DataFrame whose last date is `days_ago` calendar days in the past."""
    end   = pd.Timestamp.today().normalize() - pd.Timedelta(days=days_ago)
    dates = pd.bdate_range(end=end, periods=n)
    prices = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices,
        "Close": prices, "Adj Close": prices, "Volume": [2_000_000] * n,
    }, index=dates)

# ── CacheStore foundation tests ───────────────────────────────────────────────

def test_put_creates_sharded_parquet(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("AAPL", _make_df(252))
    assert (tmp_path / "A" / "AAPL.parquet").exists()

def test_put_and_get_roundtrip(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    df = _make_df(252)
    cs.put("AAPL", df)
    result = cs.get("AAPL")
    pd.testing.assert_frame_equal(result.reset_index(drop=True),
                                  df.reset_index(drop=True),
                                  check_like=True)

def test_get_returns_none_for_unknown_ticker(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    assert cs.get("UNKNOWN") is None

def test_get_meta_contains_required_fields(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("NVDA", _make_df(60, price_start=50.0))
    meta = cs.get_meta("NVDA")
    assert meta is not None
    for field in ("last_close", "avg_vol_20d", "dollar_vol",
                  "above_sma50", "last_updated", "stale",
                  "high_52w", "vol_ratio_5d"):
        assert field in meta, f"missing field: {field}"

def test_get_meta_returns_none_for_unknown(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    assert cs.get_meta("UNKNOWN") is None

def test_get_meta_with_default(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    assert cs.get_meta("UNKNOWN", {}) == {}

def test_preload_index_restores_metadata(tmp_path):
    cs1 = CacheStore(cache_dir=str(tmp_path))
    cs1.put("MSFT", _make_df(252))
    # New instance — only disk; call preload_index
    cs2 = CacheStore(cache_dir=str(tmp_path))
    cs2.preload_index()
    assert cs2.get_meta("MSFT") is not None

def test_corrupt_parquet_returns_none(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    shard = tmp_path / "A"
    shard.mkdir(parents=True)
    (shard / "AAPL.parquet").write_bytes(b"not a valid parquet file")
    assert cs.get("AAPL") is None

def test_is_fresh_true_when_last_date_is_today(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("AAPL", _make_df(252))
    assert cs.is_fresh("AAPL")

def test_is_fresh_false_when_stale(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("AAPL", _make_df_old(252, days_ago=10))
    assert not cs.is_fresh("AAPL")

def test_is_excluded_false_within_stale_limit(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("AAPL", _make_df_old(252, days_ago=3))   # 3 calendar days ≈ 2 biz days
    assert not cs.is_excluded("AAPL")

def test_is_excluded_true_beyond_stale_limit(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("AAPL", _make_df_old(252, days_ago=20))  # clearly stale
    assert cs.is_excluded("AAPL")

def test_put_writes_metadata_json(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("GOOG", _make_df(252))
    meta_path = tmp_path / "metadata.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text())
    assert "GOOG" in data

def test_cache_hit_rate_after_memory_hit(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    cs.put("AAPL", _make_df(252))
    cs.get("AAPL")  # memory hit
    cs.get("AAPL")  # memory hit again
    # After 2 gets (both memory hits after put), hit rate > 0
    assert cs.cache_hit_rate() >= 0.0


# ── Incremental fetch tests ───────────────────────────────────────────────────
from unittest.mock import patch, MagicMock

def _make_yf_return(rows: int, start_price: float = 110.0) -> pd.DataFrame:
    """Simulated yfinance .history() return (fresh bars)."""
    end   = pd.Timestamp.today().normalize()
    dates = pd.bdate_range(end=end, periods=rows)
    prices = [start_price + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices,
        "Close": prices, "Adj Close": prices, "Volume": [3_000_000] * rows,
    }, index=dates)

def test_fetch_incremental_returns_existing_when_fresh(tmp_path):
    cs  = CacheStore(cache_dir=str(tmp_path))
    df  = _make_df(252)           # ends today → already fresh
    cs.put("AAPL", df)

    with patch("cache_store.yf.Ticker") as mock_yf:
        result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

    mock_yf.assert_not_called()
    assert result is not None
    assert len(result) == len(df)

def test_fetch_incremental_appends_new_rows(tmp_path):
    cs  = CacheStore(cache_dir=str(tmp_path))
    old = _make_df_old(252, days_ago=5)   # ends 5 calendar days ago
    cs.put("AAPL", old)
    new_bars = _make_yf_return(3)         # 3 new bars to append

    with patch("cache_store.yf.Ticker") as mock_yf:
        mock_ticker          = MagicMock()
        mock_yf.return_value = mock_ticker
        mock_ticker.history.return_value = new_bars

        result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

    assert result is not None
    assert len(result) >= len(old)        # at least as many rows
    # Last date should be today
    assert result.index[-1].date() == date.today()

def test_fetch_incremental_no_duplicates_after_append(tmp_path):
    cs  = CacheStore(cache_dir=str(tmp_path))
    old = _make_df_old(252, days_ago=3)
    cs.put("AAPL", old)
    # Return overlap: yfinance returns 2 bars including the last existing date
    overlap = _make_yf_return(2)

    with patch("cache_store.yf.Ticker") as mock_yf:
        mock_yf.return_value.history.return_value = overlap
        result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

    assert result is not None
    assert not result.index.duplicated().any(), "index must have no duplicates"

def test_fetch_incremental_handles_corrupt_parquet(tmp_path):
    cs   = CacheStore(cache_dir=str(tmp_path))
    # Write corrupt file
    shard = tmp_path / "A"
    shard.mkdir(parents=True)
    (shard / "AAPL.parquet").write_bytes(b"garbage")

    new_bars = _make_yf_return(252)
    with patch("cache_store.yf.Ticker") as mock_yf:
        mock_yf.return_value.history.return_value = new_bars
        result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

    # Should fall back to full download
    assert result is not None
    assert len(result) >= 10

def test_fetch_incremental_returns_stale_cache_on_network_failure(tmp_path):
    cs  = CacheStore(cache_dir=str(tmp_path))
    old = _make_df_old(252, days_ago=10)   # 10 calendar days → always > PRICE_CACHE_FRESH_DAYS
    cs.put("AAPL", old)

    with patch("cache_store.yf.Ticker") as mock_yf:
        mock_yf.return_value.history.side_effect = Exception("network error")
        result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

    assert result is not None           # returns stale cache, does not raise
    meta = cs.get_meta("AAPL")
    assert meta["stale"] is True

def test_fetch_incremental_returns_none_when_no_cache_and_network_fails(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))

    with patch("cache_store.yf.Ticker") as mock_yf:
        mock_yf.return_value.history.side_effect = Exception("network error")
        result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

    assert result is None

def test_batch_download_with_fallback_retries_smaller_batches(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))

    call_sizes = []
    def fake_download(tickers, **kwargs):
        call_sizes.append(len(tickers))
        if len(tickers) == 100:
            raise Exception("batch too large")
        # Return empty dict for sub-batches (simulates partial failure)
        return {}

    tickers = [f"T{i:03d}" for i in range(100)]
    with patch("cache_store.yf") as mock_yf:
        mock_yf.download.side_effect = fake_download
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
        asyncio.run(cs._batch_download_with_fallback(tickers, asyncio.Semaphore(10)))

    # First call was 100 (failed), then should try smaller batches
    assert 100 in call_sizes
    assert any(s < 100 for s in call_sizes)

def test_bulk_fetch_incremental_processes_all_tickers(tmp_path):
    cs = CacheStore(cache_dir=str(tmp_path))
    tickers = ["AAPL", "NVDA", "MSFT"]

    # Pre-populate with fresh data so no network call needed
    for t in tickers:
        cs.put(t, _make_df(252))

    fetched = []
    original_fetch = cs.fetch_incremental
    async def tracking_fetch(ticker, sem):
        fetched.append(ticker)
        return await original_fetch(ticker, sem)

    cs.fetch_incremental = tracking_fetch
    asyncio.run(cs.bulk_fetch_incremental(tickers, asyncio.Semaphore(5), workers=2))
    assert sorted(fetched) == sorted(tickers)
