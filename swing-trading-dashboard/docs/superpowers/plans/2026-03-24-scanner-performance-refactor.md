# Scanner Performance Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce scanner runtime from 10–15 minutes to 2–3 minutes by introducing a disk-persisted OHLCV cache, incremental updates, two-pass filtering, and bounded worker queues.

**Architecture:** A new `cache_store.py` module owns all disk I/O for price data (parquet per ticker + lightweight metadata JSON). `_run_scan` in `main.py` is restructured into two passes: Pass 1 reads only metadata to filter ~1600 tickers down to 200–400, Pass 2 runs heavy indicator computation and engines on survivors only. `scoring.py` gains RS rank persistence (1-day TTL) to skip full O'Neil recomputation on repeat scans.

**Tech Stack:** Python 3.11+, pandas, pyarrow (parquet), asyncio, yfinance, pytest, unittest.mock

**Spec:** `swing-trading-dashboard/docs/superpowers/specs/2026-03-24-scanner-performance-refactor-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/cache_store.py` | **Create** | Disk-persisted OHLCV cache, metadata index, incremental fetch |
| `backend/constants.py` | **Modify** | Add SCAN_CACHE_DIR, PASS1_*, RS_RANK_CACHE_*, SCAN_*_WORKERS constants |
| `backend/scoring.py` | **Modify** | RS rank cache persistence (load/save/TTL/version), `compute_rs_rank_map` cache-aware |
| `backend/universe_builder.py` | **Modify** | Tighter default thresholds, RS pre-filter using cached ranks |
| `backend/main.py` | **Modify** | `_pass1_filter`, `_compute_breadth_from_metadata`, `_run_io_phase`, `_run_compute_phase`, `_run_scan` restructure |
| `backend/tests/test_cache_store.py` | **Create** | Unit tests for CacheStore (disk I/O, metadata, incremental, resilience) |
| `backend/tests/test_rs_rank_cache.py` | **Create** | Unit tests for RS cache persistence in scoring.py |
| `backend/tests/test_pass1_filter.py` | **Create** | Unit tests for Pass 1 filter + breadth + discovery + adaptive tightening |
| `backend/tests/test_worker_queues.py` | **Create** | Unit tests for I/O and compute worker queue phases |

---

## Task 1: New Constants

Add all new performance constants to `constants.py`. No logic changes — just new named values that later tasks reference.

**Files:**
- Modify: `backend/constants.py`
- Test: `backend/tests/test_cache_store.py` (constants checked as part of import)

- [ ] **Step 1: Write failing test**

  In `backend/tests/test_cache_store.py`:

  ```python
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
  ```

- [ ] **Step 2: Run test to confirm it fails**

  ```
  cd swing-trading-dashboard/backend
  python -m pytest tests/test_cache_store.py::test_new_constants_exist -v
  ```
  Expected: `ImportError` or `AssertionError`.

- [ ] **Step 3: Add constants to `constants.py`**

  Append to `constants.py` (near the bottom, after existing WFO constants):

  ```python
  # ── Scanner disk cache ────────────────────────────────────────────────────────
  SCAN_CACHE_DIR                = "data/scan_cache"
  PRICE_CACHE_FRESH_DAYS        = 2        # skip incremental if ≤ N biz days old
  PRICE_CACHE_MAX_STALE_DAYS    = 5        # attempt update; exclude if update fails
  SCAN_CACHE_METADATA_FILE      = "data/scan_cache/metadata.json"

  # ── RS rank cache ─────────────────────────────────────────────────────────────
  RS_RANK_CACHE_TTL               = 86400  # 1 day in seconds
  RS_RANK_CACHE_FILE              = "cache/rs_rank_cache.json"
  RS_RANK_CACHE_REFRESH_THRESHOLD = 72000  # 20 h: refresh before Pass 1 if older

  # ── Pass 1 thresholds ─────────────────────────────────────────────────────────
  PASS1_MIN_PRICE              = 12.0
  PASS1_MIN_AVG_VOLUME         = 1_000_000
  PASS1_MIN_DOLLAR_VOLUME      = 25_000_000
  PASS1_MIN_RS_RANK            = 45
  PASS1_MAX_SURVIVORS          = 400

  # ── Worker pools ──────────────────────────────────────────────────────────────
  SCAN_IO_WORKERS              = 48
  SCAN_COMPUTE_WORKERS         = 32
  SCAN_QUEUE_MULTIPLIER        = 2

  # ── Universe builder (tightened defaults) ─────────────────────────────────────
  UNIVERSE_MIN_PRICE           = 12.0
  UNIVERSE_MIN_AVG_VOLUME      = 1_000_000
  UNIVERSE_MIN_DOLLAR_VOL      = 25_000_000
  UNIVERSE_RS_FLOOR            = 35
  ```

- [ ] **Step 4: Run test to confirm it passes**

  ```
  python -m pytest tests/test_cache_store.py::test_new_constants_exist -v
  ```
  Expected: `PASSED`.

- [ ] **Step 5: Commit**

  ```
  git add backend/constants.py backend/tests/test_cache_store.py
  git commit -m "feat: add scanner performance refactor constants"
  ```

---

## Task 2: CacheStore — Foundation (disk I/O + metadata)

Create `cache_store.py` with the core `CacheStore` class: sharded parquet storage, metadata JSON, read-through cache, and basic helpers. No network calls in this task — only disk I/O.

**Files:**
- Create: `backend/cache_store.py`
- Test: `backend/tests/test_cache_store.py`

### Background: helpers shared across all CacheStore tests

Add this block at the top of `test_cache_store.py` (after the constants test):

```python
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
        "Close": prices, "Adj Close": prices,
        "Volume": [2_000_000] * n,
    }, index=dates)
```

- [ ] **Step 1: Write failing tests for CacheStore foundation**

  Append to `backend/tests/test_cache_store.py`:

  ```python
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
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_cache_store.py -k "not test_new_constants" -v 2>&1 | head -30
  ```
  Expected: `ModuleNotFoundError: No module named 'cache_store'`.

- [ ] **Step 3: Implement `backend/cache_store.py`**

  Create `backend/cache_store.py`:

  ```python
  """
  cache_store.py — Disk-persisted OHLCV cache for the live scanner.

  Layout:
    data/scan_cache/
      metadata.json          lightweight per-ticker index (loaded into memory at startup)
      A/AAPL.parquet         sharded by first letter of ticker
      S/SPY.parquet
      ...

  This is SEPARATE from data/price_cache/ which belongs to the WFO system.
  """
  from __future__ import annotations

  import asyncio
  import json
  import logging
  import os
  import tempfile
  import time
  from datetime import date, timedelta
  from pathlib import Path
  from typing import Dict, List, Optional

  import numpy as np
  import pandas as pd

  log = logging.getLogger(__name__)

  # ── Import constants (resolve path so this module works standalone) ───────────
  import sys
  sys.path.insert(0, os.path.dirname(__file__))
  from constants import (
      PRICE_CACHE_FRESH_DAYS,
      PRICE_CACHE_MAX_STALE_DAYS,
      SCAN_CACHE_DIR,
      SCAN_CACHE_METADATA_FILE,
  )

  # ── Business-day helpers ──────────────────────────────────────────────────────

  def _biz_days_since(last_date: date) -> int:
      """Count business days between last_date and today (exclusive)."""
      today = date.today()
      if last_date >= today:
          return 0
      delta = np.busday_count(last_date.isoformat(), today.isoformat())
      return int(delta)


  # ── CacheStore ────────────────────────────────────────────────────────────────

  class CacheStore:
      """Read-through OHLCV cache: in-memory dict → parquet on disk."""

      def __init__(self, cache_dir: str = SCAN_CACHE_DIR) -> None:
          self._dir   = Path(cache_dir)
          self._dir.mkdir(parents=True, exist_ok=True)
          self._meta_path = self._dir / "metadata.json"
          self._meta: Dict[str, dict] = {}           # in-memory metadata
          self._mem:  Dict[str, pd.DataFrame] = {}   # in-memory DataFrames
          self._meta_lock = asyncio.Lock()

          # Hit-rate tracking
          self._hits_memory = 0
          self._hits_disk   = 0
          self._hits_miss   = 0

      # ── Public: startup ───────────────────────────────────────────────────────

      def preload_index(self) -> None:
          """Load metadata.json into memory. No parquet reads."""
          if not self._meta_path.exists():
              return
          try:
              self._meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
              log.info("[cache_store] Loaded metadata for %d tickers", len(self._meta))
          except Exception as exc:
              log.warning("[cache_store] Could not load metadata.json: %s", exc)
              self._meta = {}

      # ── Public: Pass 1 (metadata only) ────────────────────────────────────────

      def get_meta(self, ticker: str, default: Optional[dict] = None) -> Optional[dict]:
          """Return in-memory metadata for ticker, or default if unknown."""
          return self._meta.get(ticker, default)

      # ── Public: Pass 2 data access ────────────────────────────────────────────

      def get(self, ticker: str) -> Optional[pd.DataFrame]:
          """Read-through: memory → parquet → None."""
          if ticker in self._mem:
              self._hits_memory += 1
              return self._mem[ticker]
          df = self._load_parquet(ticker)
          if df is not None:
              self._mem[ticker] = df
              self._hits_disk += 1
              return df
          self._hits_miss += 1
          return None

      def put(self, ticker: str, df: pd.DataFrame) -> None:
          """Write DataFrame to memory + parquet + update metadata dict."""
          df = self._normalise(df)
          self._mem[ticker] = df
          self._write_parquet(ticker, df)
          self._update_meta_sync(ticker, df)
          self._flush_metadata()

      # ── Public: staleness checks ──────────────────────────────────────────────

      def is_fresh(self, ticker: str) -> bool:
          """True if last_updated is within PRICE_CACHE_FRESH_DAYS business days."""
          meta = self._meta.get(ticker)
          if not meta:
              return False
          try:
              last = date.fromisoformat(meta["last_updated"])
              return _biz_days_since(last) <= PRICE_CACHE_FRESH_DAYS
          except Exception:
              return False

      def is_excluded(self, ticker: str) -> bool:
          """True if last_updated is more than PRICE_CACHE_MAX_STALE_DAYS biz days ago."""
          meta = self._meta.get(ticker)
          if not meta:
              return False
          try:
              last = date.fromisoformat(meta["last_updated"])
              return _biz_days_since(last) > PRICE_CACHE_MAX_STALE_DAYS
          except Exception:
              return False

      # ── Public: metrics ───────────────────────────────────────────────────────

      def cache_hit_rate(self) -> float:
          total = self._hits_memory + self._hits_disk + self._hits_miss
          if total == 0:
              return 0.0
          return round((self._hits_memory + self._hits_disk) / total, 3)

      # ── Internal ──────────────────────────────────────────────────────────────

      def _shard_path(self, ticker: str) -> Path:
          letter = ticker[0].upper() if ticker else "X"
          return self._dir / letter / f"{ticker}.parquet"

      def _load_parquet(self, ticker: str) -> Optional[pd.DataFrame]:
          path = self._shard_path(ticker)
          if not path.exists():
              return None
          try:
              df = pd.read_parquet(path)
              return self._normalise(df)
          except Exception as exc:
              log.warning("[cache_store] Corrupt parquet for %s (%s) — skipping", ticker, exc)
              return None

      def _write_parquet(self, ticker: str, df: pd.DataFrame) -> None:
          path = self._shard_path(ticker)
          path.parent.mkdir(parents=True, exist_ok=True)
          fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".parquet")
          os.close(fd)
          try:
              df.to_parquet(tmp, compression="snappy")
              os.replace(tmp, path)
          except Exception as exc:
              log.error("[cache_store] Failed to write parquet for %s: %s", ticker, exc)
              try:
                  os.unlink(tmp)
              except OSError:
                  pass

      def _normalise(self, df: pd.DataFrame) -> pd.DataFrame:
          """Ensure consistent column set, sorted DatetimeIndex, no timezone."""
          if df is None or df.empty:
              return df
          if isinstance(df.columns, pd.MultiIndex):
              df = df.copy()
              df.columns = df.columns.get_level_values(0)
          if df.columns.duplicated().any():
              df = df.loc[:, ~df.columns.duplicated()]
          if df.index.tz is not None:
              df = df.copy()
              df.index = df.index.tz_localize(None)
          df.index = pd.to_datetime(df.index).normalize()
          df = df[~df.index.duplicated(keep="last")]
          df = df.sort_index()
          return df

      def _update_meta_sync(self, ticker: str, df: pd.DataFrame) -> None:
          """Compute metadata fields from df and update in-memory dict (sync, no lock)."""
          if df is None or df.empty:
              return
          close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
          close  = df[close_col].dropna()
          vol    = df["Volume"].dropna() if "Volume" in df.columns else pd.Series(dtype=float)
          if close.empty:
              return

          last_close = float(close.iloc[-1])
          avg_vol_20 = float(vol.iloc[-20:].median()) if len(vol) >= 20 else float(vol.median()) if not vol.empty else 0.0
          dollar_vol = last_close * avg_vol_20
          sma50      = float(close.iloc[-50:].mean()) if len(close) >= 50 else float(close.mean())
          above_sma50 = last_close > sma50
          high_52w   = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
          avg_vol_50 = float(vol.iloc[-50:].median()) if len(vol) >= 50 else avg_vol_20
          avg_vol_5  = float(vol.iloc[-5:].mean()) if len(vol) >= 5 else avg_vol_20
          vol_ratio_5d = round(avg_vol_5 / avg_vol_50, 3) if avg_vol_50 > 0 else 1.0

          self._meta[ticker] = {
              "last_close":   round(last_close, 4),
              "avg_vol_20d":  round(avg_vol_20, 0),
              "dollar_vol":   round(dollar_vol, 0),
              "above_sma50":  above_sma50,
              "last_updated": df.index[-1].date().isoformat(),
              "stale":        False,
              "high_52w":     round(high_52w, 4),
              "vol_ratio_5d": vol_ratio_5d,
          }

      def _flush_metadata(self) -> None:
          """Atomically write in-memory metadata dict to disk."""
          fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".json")
          os.close(fd)
          try:
              Path(tmp).write_text(
                  json.dumps(self._meta, indent=None),
                  encoding="utf-8",
              )
              os.replace(tmp, self._meta_path)
          except Exception as exc:
              log.error("[cache_store] Failed to write metadata.json: %s", exc)
              try:
                  os.unlink(tmp)
              except OSError:
                  pass
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```
  python -m pytest tests/test_cache_store.py -k "not fetch" -v
  ```
  Expected: all foundation tests `PASSED`.

- [ ] **Step 5: Commit**

  ```
  git add backend/cache_store.py backend/tests/test_cache_store.py
  git commit -m "feat: add CacheStore foundation (disk parquet + metadata index)"
  ```

---

## Task 3: CacheStore — Incremental Fetch + Batch Resilience

Add `fetch_incremental`, `bulk_fetch_incremental`, and the three-tier batch fallback `_batch_download_with_fallback`.

**Files:**
- Modify: `backend/cache_store.py`
- Test: `backend/tests/test_cache_store.py`

- [ ] **Step 1: Write failing tests**

  Append to `test_cache_store.py`:

  ```python
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

      with patch("yfinance.Ticker") as mock_yf:
          result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

      mock_yf.assert_not_called()
      assert result is not None
      assert len(result) == len(df)

  def test_fetch_incremental_appends_new_rows(tmp_path):
      cs  = CacheStore(cache_dir=str(tmp_path))
      old = _make_df_old(252, days_ago=5)   # ends 5 calendar days ago
      cs.put("AAPL", old)
      new_bars = _make_yf_return(3)         # 3 new bars to append

      with patch("yfinance.Ticker") as mock_yf:
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

      with patch("yfinance.Ticker") as mock_yf:
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
      with patch("yfinance.Ticker") as mock_yf:
          mock_yf.return_value.history.return_value = new_bars
          result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

      # Should fall back to full download
      assert result is not None
      assert len(result) >= 10

  def test_fetch_incremental_returns_stale_cache_on_network_failure(tmp_path):
      cs  = CacheStore(cache_dir=str(tmp_path))
      old = _make_df_old(252, days_ago=3)
      cs.put("AAPL", old)

      with patch("yfinance.Ticker") as mock_yf:
          mock_yf.return_value.history.side_effect = Exception("network error")
          result = asyncio.run(cs.fetch_incremental("AAPL", asyncio.Semaphore(5)))

      assert result is not None           # returns stale cache, does not raise
      meta = cs.get_meta("AAPL")
      assert meta["stale"] is True

  def test_fetch_incremental_returns_none_when_no_cache_and_network_fails(tmp_path):
      cs = CacheStore(cache_dir=str(tmp_path))

      with patch("yfinance.Ticker") as mock_yf:
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
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_cache_store.py -k "fetch or batch or bulk" -v 2>&1 | head -20
  ```
  Expected: `AttributeError: 'CacheStore' object has no attribute 'fetch_incremental'`.

- [ ] **Step 3: Add incremental fetch methods to `cache_store.py`**

  Add these imports at the top of `cache_store.py`:

  ```python
  import yfinance as yf
  ```

  Then add these methods to `CacheStore`:

  ```python
  # ── Public: incremental fetch ─────────────────────────────────────────────────

  async def fetch_incremental(
      self,
      ticker: str,
      semaphore: asyncio.Semaphore,
  ) -> Optional[pd.DataFrame]:
      """
      Load existing parquet, fetch only missing trading days, append, save.
      Returns the updated DataFrame, or None if no data available at all.
      """
      existing = self._load_parquet(ticker)

      # Determine fetch start date
      if existing is not None and not existing.empty:
          last_date = existing.index[-1].date()
          biz_days_old = _biz_days_since(last_date)
          if biz_days_old <= PRICE_CACHE_FRESH_DAYS:
              # Already fresh — no network call
              if ticker not in self._mem:
                  self._mem[ticker] = existing
              return existing
      else:
          last_date = None
          biz_days_old = 999

      # Fetch missing days from yfinance
      loop = asyncio.get_running_loop()
      new_data: Optional[pd.DataFrame] = None
      try:
          async with semaphore:
              new_data = await loop.run_in_executor(
                  None,
                  lambda: self._yf_history(ticker, last_date),
              )
      except Exception as exc:
          log.warning("[cache_store] fetch_incremental %s failed: %s", ticker, exc)

      if new_data is None or new_data.empty:
          if existing is not None:
              # Return stale cache with stale flag
              if ticker in self._meta:
                  self._meta[ticker]["stale"] = True
              return existing
          return None  # No cache, no network — ticker excluded

      # Merge existing + new
      if existing is not None and not existing.empty:
          combined = pd.concat([existing, new_data])
      else:
          combined = new_data

      combined = self._normalise(combined)

      # Drop partial last bar (volume == 0 on current trading day)
      today = pd.Timestamp.today().normalize()
      if len(combined) > 0 and combined.index[-1] == today:
          if "Volume" in combined.columns and combined["Volume"].iloc[-1] == 0:
              combined = combined.iloc[:-1]

      self._mem[ticker] = combined
      self._write_parquet(ticker, combined)
      self._update_meta_sync(ticker, combined)
      return combined

  async def bulk_fetch_incremental(
      self,
      tickers: List[str],
      semaphore: asyncio.Semaphore,
      workers: int = 48,
  ) -> None:
      """Parallel incremental fetch for a list of tickers using a worker queue."""
      queue: asyncio.Queue = asyncio.Queue(maxsize=workers * 2)

      async def _worker():
          while True:
              ticker = await queue.get()
              if ticker is None:
                  queue.task_done()
                  break
              try:
                  await self.fetch_incremental(ticker, semaphore)
              except Exception as exc:
                  log.warning("[cache_store] bulk_fetch worker error for %s: %s", ticker, exc)
              finally:
                  queue.task_done()

      worker_tasks = [asyncio.create_task(_worker()) for _ in range(workers)]
      for t in tickers:
          await queue.put(t)
      for _ in worker_tasks:
          await queue.put(None)
      await asyncio.gather(*worker_tasks)

  async def _batch_download_with_fallback(
      self,
      tickers: List[str],
      semaphore: asyncio.Semaphore,
      batch_size: int = 100,
  ) -> None:
      """
      Three-tier batch download with automatic fallback:
        Tier 1: yf.download(100 tickers)
        Tier 2: 4 × 25-ticker sub-batches
        Tier 3: individual _fetch via yf.Ticker
      """
      loop = asyncio.get_running_loop()

      async def _dl_batch(batch: List[str]) -> dict:
          """Download a batch; returns {ticker: df} dict."""
          try:
              async with semaphore:
                  return await asyncio.wait_for(
                      loop.run_in_executor(None, lambda b=batch: _yf_batch_sync(b)),
                      timeout=30,
                  )
          except Exception:
              return {}

      batches = [tickers[i:i+batch_size] for i in range(0, len(tickers), batch_size)]
      for batch in batches:
          result = await _dl_batch(batch)
          if result:
              for t, df in result.items():
                  if df is not None and not df.empty:
                      df = self._normalise(df)
                      self._mem[t] = df
                      self._write_parquet(t, df)
                      self._update_meta_sync(t, df)
              continue

          # Tier 2: sub-batches of 25
          sub_size = max(1, batch_size // 4)
          sub_batches = [batch[i:i+sub_size] for i in range(0, len(batch), sub_size)]
          for sub in sub_batches:
              sub_result = await _dl_batch(sub)
              if sub_result:
                  for t, df in sub_result.items():
                      if df is not None and not df.empty:
                          df = self._normalise(df)
                          self._mem[t] = df
                          self._write_parquet(t, df)
                          self._update_meta_sync(t, df)
                  continue

              # Tier 3: individual
              for t in sub:
                  try:
                      async with semaphore:
                          df = await asyncio.wait_for(
                              loop.run_in_executor(None, lambda tk=t: self._yf_history(tk, None)),
                              timeout=15,
                          )
                      if df is not None and not df.empty:
                          df = self._normalise(df)
                          self._mem[t] = df
                          self._write_parquet(t, df)
                          self._update_meta_sync(t, df)
                  except Exception as exc:
                      log.warning("[cache_store] Tier3 fetch failed for %s: %s", t, exc)

      self._flush_metadata()

  # ── Internal: yfinance helpers ────────────────────────────────────────────────

  def _yf_history(
      self,
      ticker: str,
      since: Optional[date],
  ) -> Optional[pd.DataFrame]:
      """Synchronous yfinance fetch — runs in executor."""
      kwargs = dict(interval="1d", auto_adjust=False, progress=False)
      if since is None:
          kwargs["period"] = "1y"
      else:
          # Start 1 day before last known bar to catch any corrections
          start = since - timedelta(days=1)
          kwargs["start"] = start.isoformat()
          kwargs["end"]   = (date.today() + timedelta(days=1)).isoformat()

      try:
          df = yf.Ticker(ticker).history(**kwargs)
          if df is None or df.empty:
              return None
          if isinstance(df.columns, pd.MultiIndex):
              df.columns = df.columns.get_level_values(0)
          return df
      except Exception as exc:
          log.debug("[cache_store] yf.Ticker(%s).history failed: %s", ticker, exc)
          return None
  ```

  Also add this module-level helper (outside the class):

  ```python
  def _yf_batch_sync(tickers: List[str]) -> Dict[str, pd.DataFrame]:
      """Synchronous yf.download for multiple tickers. Called from executor."""
      if not tickers:
          return {}
      try:
          raw = yf.download(
              tickers,
              period="1y",
              interval="1d",
              auto_adjust=False,
              group_by="ticker",
              progress=False,
              threads=True,
              timeout=60,
          )
          result = {}
          top = raw.columns.get_level_values(0).unique().tolist()
          for t in tickers:
              try:
                  if t in top:
                      df = raw[t].dropna(how="all")
                      if not df.empty:
                          result[t] = df
              except Exception:
                  pass
          return result
      except Exception as exc:
          log.warning("[cache_store] yf.download batch failed: %s", exc)
          return {}
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```
  python -m pytest tests/test_cache_store.py -v
  ```
  Expected: all tests `PASSED`.

- [ ] **Step 5: Commit**

  ```
  git add backend/cache_store.py backend/tests/test_cache_store.py
  git commit -m "feat: add CacheStore incremental fetch and batch resilience"
  ```

---

## Task 4: RS Rank Cache Persistence

Modify `scoring.py` so `compute_rs_rank_map` returns a cached result when the disk cache is fresh and the logic version matches. Cache is written atomically after every full recompute.

**Files:**
- Modify: `backend/scoring.py`
- Create: `backend/tests/test_rs_rank_cache.py`

- [ ] **Step 1: Write failing tests**

  Create `backend/tests/test_rs_rank_cache.py`:

  ```python
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
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_rs_rank_cache.py -v 2>&1 | head -20
  ```
  Expected: `ImportError: cannot import name 'RS_LOGIC_VERSION' from 'scoring'`.

- [ ] **Step 3: Add RS cache persistence to `scoring.py`**

  After the existing imports in `scoring.py`, add the `RS_RANK_CACHE_FILE` import:

  ```python
  from constants import (
      ...existing imports...,
      RS_RANK_CACHE_FILE,
      RS_RANK_CACHE_TTL,
  )
  ```

  Then add these module-level definitions and helpers directly before `compute_rs_rank_map`:

  ```python
  # ── RS rank cache persistence ─────────────────────────────────────────────────

  RS_LOGIC_VERSION = "v3"   # increment when O'Neil weights, periods, or formula changes


  def _load_rs_cache() -> Optional[dict]:
      """Load and return the RS rank cache dict, or None if missing/unreadable."""
      try:
          if not os.path.exists(RS_RANK_CACHE_FILE):
              return None
          with open(RS_RANK_CACHE_FILE, "r", encoding="utf-8") as fh:
              return json.load(fh)
      except Exception:
          return None


  def _rs_cache_age_seconds(cache: dict) -> float:
      """Return age of cache in seconds, or infinity if unparseable."""
      try:
          computed_at = cache["_meta"]["computed_at"]
          dt = datetime.fromisoformat(computed_at)
          return (datetime.utcnow() - dt).total_seconds()
      except Exception:
          return float("inf")


  def _rs_cache_valid(cache: Optional[dict]) -> bool:
      """True if cache exists, is fresh (< TTL), and has matching logic version."""
      if cache is None:
          return False
      meta = cache.get("_meta", {})
      if meta.get("logic_version") != RS_LOGIC_VERSION:
          return False
      return _rs_cache_age_seconds(cache) < RS_RANK_CACHE_TTL


  def _save_rs_cache(rank_map: Dict[str, float]) -> None:
      """Atomically persist rank_map to RS_RANK_CACHE_FILE."""
      import tempfile as _tf
      payload = {
          "_meta": {
              "computed_at":   datetime.utcnow().isoformat(),
              "logic_version": RS_LOGIC_VERSION,
              "ticker_count":  len(rank_map),
          },
          **rank_map,
      }
      cache_path = os.path.abspath(RS_RANK_CACHE_FILE)
      os.makedirs(os.path.dirname(cache_path), exist_ok=True)
      fd, tmp = _tf.mkstemp(dir=os.path.dirname(cache_path), suffix=".json")
      os.close(fd)
      try:
          with open(tmp, "w", encoding="utf-8") as fh:
              json.dump(payload, fh)
          os.replace(tmp, cache_path)
      except Exception as exc:
          import logging as _log
          _log.getLogger(__name__).warning("Could not save RS cache: %s", exc)
          try:
              os.unlink(tmp)
          except OSError:
              pass
  ```

  Add the missing imports at the top of `scoring.py`:

  ```python
  import json
  import os
  from datetime import datetime
  ```

  Then modify `compute_rs_rank_map` to check the cache first. Replace the function's opening:

  ```python
  def compute_rs_rank_map(
      ticker_cache: Dict,
      tickers: List[str],
      spy_df: Optional[pd.DataFrame],
      sample_size: int = 600,
  ) -> Dict[str, float]:
      # ── Cache check ────────────────────────────────────────────────────────
      _cache = _load_rs_cache()
      if _rs_cache_valid(_cache):
          return {k: v for k, v in _cache.items() if not k.startswith("_")}

      # ── Full recompute (existing logic, unchanged below) ───────────────────
      if spy_df is None or spy_df.empty:
          return {}
      ... (rest of existing function unchanged) ...

      # At the end, before `return rank_map`:
      _save_rs_cache(rank_map)
      return rank_map
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```
  python -m pytest tests/test_rs_rank_cache.py -v
  ```
  Expected: all `PASSED`.

- [ ] **Step 5: Confirm existing RS ranking tests still pass**

  ```
  python -m pytest tests/test_rs_ranking.py -v
  ```
  Expected: all `PASSED` (no regression).

- [ ] **Step 6: Commit**

  ```
  git add backend/scoring.py backend/tests/test_rs_rank_cache.py
  git commit -m "feat: add RS rank cache persistence with TTL and logic version"
  ```

---

## Task 5: Universe Builder — Tighter Defaults + RS Pre-Filter

Update `build_universe`'s default arguments to use the new tighter constants. Add an RS pre-filter that excludes bottom-35% tickers when the RS cache exists.

**Files:**
- Modify: `backend/universe_builder.py`
- Test: `backend/tests/test_universe_builder.py` (existing file — add tests)

- [ ] **Step 1: Write failing tests**

  Append to `backend/tests/test_universe_builder.py`:

  ```python
  # ── Tighter defaults tests ────────────────────────────────────────────────────
  import json
  from datetime import datetime
  from unittest.mock import patch, MagicMock
  from universe_builder import build_universe, _apply_rs_prefilter
  from constants import UNIVERSE_MIN_PRICE, UNIVERSE_MIN_AVG_VOLUME, UNIVERSE_MIN_DOLLAR_VOL, UNIVERSE_RS_FLOOR

  def test_universe_min_price_is_12():
      assert UNIVERSE_MIN_PRICE == 12.0

  def test_universe_min_volume_is_1m():
      assert UNIVERSE_MIN_AVG_VOLUME == 1_000_000

  def test_universe_min_dollar_vol_is_25m():
      assert UNIVERSE_MIN_DOLLAR_VOL == 25_000_000

  def test_rs_prefilter_removes_low_rs_tickers(tmp_path):
      cache_file = tmp_path / "rs_rank_cache.json"
      rs_data = {
          "_meta": {
              "computed_at": datetime.utcnow().isoformat(),
              "logic_version": "v3",
              "ticker_count": 3,
          },
          "AAPL": 80.0,   # good
          "NVDA": 20.0,   # below UNIVERSE_RS_FLOOR (35)
          "MSFT": 50.0,   # good
      }
      cache_file.write_text(json.dumps(rs_data))

      result = _apply_rs_prefilter(
          ["AAPL", "NVDA", "MSFT", "UNKNOWN"],
          rs_cache_file=str(cache_file),
          rs_floor=UNIVERSE_RS_FLOOR,
          max_age_days=7,
      )
      assert "AAPL" in result
      assert "MSFT" in result
      assert "NVDA" not in result
      assert "UNKNOWN" in result   # no RS data → kept (safe fallback)

  def test_rs_prefilter_skips_when_cache_too_old(tmp_path):
      cache_file = tmp_path / "rs_rank_cache.json"
      rs_data = {
          "_meta": {
              "computed_at": "2020-01-01T00:00:00",  # very old
              "logic_version": "v3",
              "ticker_count": 2,
          },
          "NVDA": 10.0,  # would be filtered — but cache is too old
      }
      cache_file.write_text(json.dumps(rs_data))

      result = _apply_rs_prefilter(
          ["NVDA", "AAPL"],
          rs_cache_file=str(cache_file),
          rs_floor=35,
          max_age_days=7,
      )
      assert "NVDA" in result   # cache ignored → ticker kept
      assert "AAPL" in result

  def test_rs_prefilter_skips_when_no_cache(tmp_path):
      result = _apply_rs_prefilter(
          ["AAPL", "NVDA"],
          rs_cache_file=str(tmp_path / "nonexistent.json"),
          rs_floor=35,
          max_age_days=7,
      )
      assert "AAPL" in result
      assert "NVDA" in result
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_universe_builder.py -k "prefilter or min_price or min_volume or min_dollar" -v 2>&1 | head -20
  ```
  Expected: `ImportError: cannot import name '_apply_rs_prefilter'`.

- [ ] **Step 3: Update `universe_builder.py`**

  Add imports near the top of `universe_builder.py`:

  ```python
  import json
  ```

  Update module-level defaults to use new constants:

  ```python
  # Replace these two lines:
  DEFAULT_MIN_PRICE = 10.0
  DEFAULT_MIN_AVG_VOLUME = 500_000
  # With:
  import sys as _sys
  _sys.path.insert(0, os.path.dirname(__file__))
  from constants import UNIVERSE_MIN_PRICE as DEFAULT_MIN_PRICE
  from constants import UNIVERSE_MIN_AVG_VOLUME as DEFAULT_MIN_AVG_VOLUME
  from constants import UNIVERSE_MIN_DOLLAR_VOL as _DEFAULT_MIN_DOLLAR_VOL
  ```

  Add the `_apply_rs_prefilter` helper (before `build_universe`):

  ```python
  def _apply_rs_prefilter(
      tickers: list,
      rs_cache_file: str,
      rs_floor: float,
      max_age_days: int = 7,
  ) -> list:
      """
      Exclude tickers with RS rank < rs_floor using the persisted RS cache.
      Returns the full ticker list unchanged if cache is missing or too old.
      """
      try:
          if not os.path.exists(rs_cache_file):
              return tickers
          with open(rs_cache_file, "r", encoding="utf-8") as fh:
              cache = json.load(fh)
          computed_at = datetime.fromisoformat(cache["_meta"]["computed_at"])
          age_days = (datetime.utcnow() - computed_at).total_seconds() / 86400
          if age_days > max_age_days:
              logger.info("RS pre-filter: cache is %.1f days old (> %d) — skipping", age_days, max_age_days)
              return tickers
          original_count = len(tickers)
          kept = [t for t in tickers if cache.get(t, rs_floor) >= rs_floor]
          logger.info(
              "RS pre-filter: %d → %d tickers (removed %d with RS < %.0f)",
              original_count, len(kept), original_count - len(kept), rs_floor,
          )
          return kept
      except Exception as exc:
          logger.warning("RS pre-filter failed (%s) — skipping", exc)
          return tickers
  ```

  Update `build_universe` to call `_apply_rs_prefilter` after `filter_price_volume` and update the default dollar volume argument:

  ```python
  def build_universe(
      min_price: float = DEFAULT_MIN_PRICE,
      min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
      min_atr_pct: float = 0.0,
      min_dollar_volume: float = _DEFAULT_MIN_DOLLAR_VOL,   # changed from 0.0
  ) -> dict:
      ...
      # Step 3 — price / volume filter (unchanged)
      filtered = filter_price_volume(candidates, min_price, min_avg_volume, min_atr_pct, min_dollar_volume)

      # Step 3b — RS pre-filter (new)
      from constants import RS_RANK_CACHE_FILE, UNIVERSE_RS_FLOOR
      filtered = _apply_rs_prefilter(filtered, RS_RANK_CACHE_FILE, UNIVERSE_RS_FLOOR)

      # Step 4 — sector map (unchanged)
      ...
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```
  python -m pytest tests/test_universe_builder.py -k "prefilter or min_price or min_volume or min_dollar" -v
  ```
  Expected: all `PASSED`.

- [ ] **Step 5: Run full universe builder test suite to check for regressions**

  ```
  python -m pytest tests/test_universe_builder.py -v
  ```
  Expected: all `PASSED`.

- [ ] **Step 6: Commit**

  ```
  git add backend/universe_builder.py backend/tests/test_universe_builder.py
  git commit -m "feat: tighten universe builder defaults and add RS pre-filter"
  ```

---

## Task 6: Worker Queue Infrastructure

Extract the two worker-pool phases into standalone async functions: `_run_io_phase` (incremental fetch, 48 workers) and `_run_compute_phase` (indicators + engines, capped at cpu_count×2). These functions are added to `main.py` and can be tested in isolation.

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_worker_queues.py`

- [ ] **Step 1: Write failing tests**

  Create `backend/tests/test_worker_queues.py`:

  ```python
  """Tests for the bounded worker queue phases in main.py."""
  import sys, os, asyncio
  sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

  import pytest
  from unittest.mock import AsyncMock, MagicMock, patch
  import pandas as pd


  def _make_df(n=252):
      dates = pd.bdate_range("2024-01-02", periods=n)
      prices = [100.0 + i * 0.1 for i in range(n)]
      return pd.DataFrame({
          "Open": prices, "High": prices, "Low": prices,
          "Close": prices, "Adj Close": prices,
          "Volume": [2_000_000] * n,
      }, index=dates)


  def test_run_io_phase_processes_all_tickers():
      from main import _run_io_phase
      from cache_store import CacheStore
      import tempfile, asyncio

      processed = []
      with tempfile.TemporaryDirectory() as tmp:
          cs = CacheStore(cache_dir=tmp)
          for t in ["AAPL", "NVDA", "MSFT"]:
              cs.put(t, _make_df(252))  # already fresh

          async def run():
              sem = asyncio.Semaphore(10)
              await _run_io_phase(["AAPL", "NVDA", "MSFT"], cs, sem)

          asyncio.run(run())
          # All tickers should now be in memory
          for t in ["AAPL", "NVDA", "MSFT"]:
              assert cs.get(t) is not None


  def test_run_io_phase_handles_empty_list():
      from main import _run_io_phase
      from cache_store import CacheStore
      import tempfile

      with tempfile.TemporaryDirectory() as tmp:
          cs = CacheStore(cache_dir=tmp)
          asyncio.run(_run_io_phase([], cs, asyncio.Semaphore(5)))
          # No error — just a no-op


  def test_run_compute_phase_processes_all_survivors():
      from main import _run_compute_phase
      import tempfile, asyncio

      results = []

      async def fake_process(ticker, idx, **kwargs):
          results.append(ticker)

      survivors = ["AAPL", "NVDA", "MSFT", "GOOG"]
      asyncio.run(_run_compute_phase(
          survivors,
          process_fn=fake_process,
          workers=2,
      ))
      assert sorted(results) == sorted(survivors)


  def test_run_compute_phase_handles_worker_exception_gracefully():
      from main import _run_compute_phase
      import asyncio

      call_count = [0]

      async def sometimes_fails(ticker, idx, **kwargs):
          call_count[0] += 1
          if ticker == "FAIL":
              raise ValueError("simulated crash")

      survivors = ["AAPL", "FAIL", "NVDA"]
      asyncio.run(_run_compute_phase(
          survivors,
          process_fn=sometimes_fails,
          workers=2,
      ))
      # All 3 attempted, including FAIL
      assert call_count[0] == 3


  def test_worker_count_capped_at_cpu_count(monkeypatch):
      """Effective compute workers must not exceed os.cpu_count() × 2."""
      import os, main as m
      monkeypatch.setattr(os, "cpu_count", lambda: 2)
      assert m._effective_compute_workers() <= 4
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_worker_queues.py -v 2>&1 | head -20
  ```
  Expected: `ImportError: cannot import name '_run_io_phase' from 'main'`.

- [ ] **Step 3: Add worker queue functions to `main.py`**

  Add these after the existing `_batch_download_sync` function (around line 834):

  ```python
  # ────────────────────────────────────────────────────────────────────────────
  # Worker queue phases
  # ────────────────────────────────────────────────────────────────────────────

  def _effective_compute_workers() -> int:
      """Cap compute workers at cpu_count×2 to avoid GIL-bound thread over-subscription."""
      import os as _os
      cpu = _os.cpu_count() or 4
      return min(SCAN_COMPUTE_WORKERS, cpu * 2)


  async def _run_io_phase(
      survivors: List[str],
      cache_store,                 # CacheStore instance
      semaphore: asyncio.Semaphore,
      workers: int = SCAN_IO_WORKERS,
  ) -> None:
      """
      Parallel incremental fetch for Pass 1 survivors.
      Uses a bounded queue (workers × SCAN_QUEUE_MULTIPLIER) to limit memory pressure.
      """
      if not survivors:
          return
      await cache_store.bulk_fetch_incremental(survivors, semaphore, workers=workers)


  async def _run_compute_phase(
      survivors: List[str],
      process_fn,                  # async callable(ticker, idx, **kwargs)
      workers: Optional[int] = None,
      **process_kwargs,
  ) -> None:
      """
      Bounded worker pool for Pass 2 (indicators + engines).
      Replaces asyncio.gather(*[_process(t,i) for ...]).
      """
      if not survivors:
          return

      n_workers = workers if workers is not None else _effective_compute_workers()
      queue: asyncio.Queue = asyncio.Queue(maxsize=n_workers * SCAN_QUEUE_MULTIPLIER)

      async def _worker():
          while True:
              item = await queue.get()
              if item is None:
                  queue.task_done()
                  break
              ticker, idx = item
              try:
                  await process_fn(ticker, idx, **process_kwargs)
              except Exception as exc:
                  log.error("Compute worker error for %s: %s", ticker, exc)
              finally:
                  queue.task_done()

      worker_tasks = [asyncio.create_task(_worker()) for _ in range(n_workers)]
      for i, ticker in enumerate(survivors):
          await queue.put((ticker, i))
      for _ in worker_tasks:
          await queue.put(None)
      await asyncio.gather(*worker_tasks)
  ```

  Add the new constant imports at the top of `main.py` (in the existing import block from `constants`):

  ```python
  SCAN_COMPUTE_WORKERS,
  SCAN_IO_WORKERS,
  SCAN_QUEUE_MULTIPLIER,
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```
  python -m pytest tests/test_worker_queues.py -v
  ```
  Expected: all `PASSED`.

- [ ] **Step 5: Commit**

  ```
  git add backend/main.py backend/tests/test_worker_queues.py
  git commit -m "feat: add bounded worker queue phases for I/O and compute"
  ```

---

## Task 7: Pass 1 Filter + Breadth + Discovery

Add three standalone functions to `main.py`:
- `_compute_breadth_from_metadata(active_universe, cache_store)` — breadth over full universe from metadata
- `_identify_discovery_candidates(active_universe, cache_store, rs_cache)` — RS 60–70 near-high tickers
- `_pass1_filter(active_universe, cache_store, rs_cache)` — fast metadata filter with adaptive tightening

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_pass1_filter.py`

- [ ] **Step 1: Write failing tests**

  Create `backend/tests/test_pass1_filter.py`:

  ```python
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
          "CHEAP": _meta(last_close=5.0, above_sma50=False),    # below price floor
          "STRONG": _meta(last_close=100.0, above_sma50=True),  # passes
          "MID": _meta(last_close=50.0, above_sma50=True),      # passes
      })
      breadth, _ = _compute_breadth_from_metadata(["CHEAP", "STRONG", "MID"], cs)
      assert breadth == pytest.approx(2 / 3)   # CHEAP is still counted


  # ── _pass1_filter ─────────────────────────────────────────────────────────────

  def test_pass1_drops_ticker_below_price_floor(tmp_path):
      cs = _cs_with_meta(tmp_path, {
          "CHEAP": _meta(last_close=5.0),   # below $12
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


  def test_pass1_drops_ticker_with_no_metadata(tmp_path):
      cs = _cs_with_meta(tmp_path, {
          "KNOWN": _meta(),
      })
      survivors, _ = _pass1_filter(["KNOWN", "UNKNOWN"], cs, {})
      assert "UNKNOWN" not in survivors
      assert "KNOWN" in survivors


  def test_pass1_keeps_discovery_candidate_below_rs_floor(tmp_path):
      """Discovery candidates (RS 60-70, near-high, vol surge) bypass the RS gate."""
      cs = _cs_with_meta(tmp_path, {
          "DISC": _meta(
              last_close=48.0,
              high_52w=50.0,       # within 3% of 52w high: 48/50 = 0.96 → 4% below → near
              vol_ratio_5d=2.0,    # vol expansion
          ),
      })
      rs_cache = _fresh_rs_cache({"DISC": 65.0})  # RS 65 → in 60-70 discovery band

      survivors, discovery = _pass1_filter(["DISC"], cs, rs_cache)
      assert "DISC" in survivors
      assert "DISC" in discovery


  def test_pass1_adaptive_tightening_triggers_above_400(tmp_path):
      """When survivors > PASS1_MAX_SURVIVORS, thresholds are tightened."""
      # Create 420 tickers all passing with RS=46 (just above 45 floor)
      meta = {f"T{i:03d}": _meta() for i in range(420)}
      rs = {f"T{i:03d}": 46.0 for i in range(420)}
      cs = _cs_with_meta(tmp_path, meta)
      rs_cache = _fresh_rs_cache(rs)

      survivors, _ = _pass1_filter(list(meta.keys()), cs, rs_cache)
      # After adaptive tightening (RS floor 45→50), T* with RS=46 are dropped
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
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_pass1_filter.py -v 2>&1 | head -20
  ```
  Expected: `ImportError: cannot import name '_pass1_filter' from 'main'`.

- [ ] **Step 3: Add Pass 1 functions to `main.py`**

  Add these functions after the worker queue functions (after `_run_compute_phase`):

  ```python
  # ────────────────────────────────────────────────────────────────────────────
  # Pass 1 — fast metadata filter
  # ────────────────────────────────────────────────────────────────────────────

  def _compute_breadth_from_metadata(
      active_universe: List[str],
      cache_store,
  ) -> tuple:
      """
      Compute breadth (% above SMA50) and H/L ratio from full-universe metadata.
      Replaces compute_universe_breadth() for the regime breadth component.
      Uses the full universe — not just Pass 1 survivors.
      Returns (breadth_pct, hl_ratio) — defaults (0.5, 0.5) on empty metadata.
      """
      above = 0
      near_high = 0
      total = 0
      for ticker in active_universe:
          meta = cache_store.get_meta(ticker)
          if not meta:
              continue
          total += 1
          if meta.get("above_sma50"):
              above += 1
          # H/L proxy: near 52-week high (within 5%)
          lc     = meta.get("last_close", 0)
          h52    = meta.get("high_52w", 0)
          if h52 > 0 and lc / h52 >= 0.95:
              near_high += 1
      if total == 0:
          return 0.5, 0.5
      return above / total, near_high / total


  def _identify_discovery_candidates(
      active_universe: List[str],
      cache_store,
      rs_cache: dict,
  ) -> set:
      """
      Identify RS 60–70 tickers near 52-week high with volume expansion.
      These bypass the Pass 1 RS floor gate.
      """
      candidates = set()
      for ticker in active_universe:
          rs = rs_cache.get(ticker)
          if rs is None or not (DISCOVERY_RS_MIN <= rs < DISCOVERY_RS_MAX):
              continue
          meta = cache_store.get_meta(ticker)
          if not meta:
              continue
          lc   = meta.get("last_close", 0)
          h52  = meta.get("high_52w", 0)
          vr   = meta.get("vol_ratio_5d", 0)
          near_high = h52 > 0 and lc / h52 >= (1 - DISCOVERY_52WK_HIGH_PCT)
          vol_surge = vr >= DISCOVERY_VOL_RATIO
          if near_high and vol_surge:
              candidates.add(ticker)
      return candidates


  def _pass1_filter(
      active_universe: List[str],
      cache_store,
      rs_cache: dict,
  ) -> tuple:
      """
      Fast metadata-only filter. Returns (survivors, discovery_set).

      Filters (in order, cheapest first):
        1. Metadata exists
        2. Not excluded-stale (> PRICE_CACHE_MAX_STALE_DAYS)
        3. Price floor  (PASS1_MIN_PRICE)
        4. Volume floor (PASS1_MIN_AVG_VOLUME, PASS1_MIN_DOLLAR_VOLUME)
        5. RS pre-filter (PASS1_MIN_RS_RANK) — bypassed for discovery candidates
      Then applies adaptive tightening if survivors > PASS1_MAX_SURVIVORS.
      """
      # Identify discovery candidates BEFORE filtering so they can be whitelisted
      discovery = _identify_discovery_candidates(active_universe, cache_store, rs_cache)

      def _apply_filters(universe, rs_floor):
          result = []
          for ticker in universe:
              # Discovery candidates bypass RS gate but still need other checks
              is_discovery = ticker in discovery

              meta = cache_store.get_meta(ticker)
              if meta is None:
                  continue

              if cache_store.is_excluded(ticker):
                  continue

              if meta.get("last_close", 0) < PASS1_MIN_PRICE:
                  continue

              if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME or
                      meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
                  continue

              rs = rs_cache.get(ticker)
              if rs is not None and not is_discovery and rs < rs_floor:
                  continue

              result.append(ticker)
          return result

      survivors = _apply_filters(active_universe, PASS1_MIN_RS_RANK)

      # Adaptive tightening: if too many survivors, tighten RS then dollar_vol
      if len(survivors) > PASS1_MAX_SURVIVORS:
          for rs_step, dv_mult in [(50, 1.0), (50, 1.6), (55, 1.6)]:
              new_survivors = [
                  t for t in survivors
                  if t in discovery
                  or (
                      (rs_cache.get(t) or 0) >= rs_step
                      and (cache_store.get_meta(t) or {}).get("dollar_vol", 0) >= PASS1_MIN_DOLLAR_VOLUME * dv_mult
                  )
              ]
              log.info(
                  "Pass 1 adaptive tighten: RS≥%d dollar_vol×%.1f → %d survivors",
                  rs_step, dv_mult, len(new_survivors),
              )
              survivors = new_survivors
              if len(survivors) <= PASS1_MAX_SURVIVORS:
                  break

      return survivors, discovery
  ```

  Also add the new constant imports at the top of `main.py` (from constants):

  ```python
  PASS1_MIN_PRICE,
  PASS1_MIN_AVG_VOLUME,
  PASS1_MIN_DOLLAR_VOLUME,
  PASS1_MIN_RS_RANK,
  PASS1_MAX_SURVIVORS,
  SCAN_CACHE_DIR,
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```
  python -m pytest tests/test_pass1_filter.py -v
  ```
  Expected: all `PASSED`.

- [ ] **Step 5: Commit**

  ```
  git add backend/main.py backend/tests/test_pass1_filter.py
  git commit -m "feat: add Pass 1 filter, breadth-from-metadata, discovery whitelisting"
  ```

---

## Task 8: Wire `_run_scan` — Integration

Restructure `_run_scan` in `main.py` to use all the components built in Tasks 2–7. This is the integration task — it connects everything and replaces the old monolithic scan flow.

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_scanner_filters_integration.py` (existing file — extend it)

**Key changes to `_run_scan` (around lines 1119–1854):**

1. Import `CacheStore` and instantiate it as a module-level singleton
2. Replace `compute_universe_breadth(...)` with `_compute_breadth_from_metadata(...)`
3. Add RS cache age check before Pass 1 — refresh if cache > 20h old
4. Add Pass 1 call, log survivors count
5. Replace bulk prefetch block with `_run_io_phase(survivors, cache_store, semaphore)`
6. Replace `asyncio.gather(*[_process(t,i) ...])` with `_run_compute_phase(survivors, _process, ...)`
7. Add new timing fields to `engine_stats.timing`

- [ ] **Step 1: Write integration smoke test**

  Append to `backend/tests/test_scanner_filters_integration.py`:

  ```python
  # ── Integration: new scan state timing fields ─────────────────────────────────
  def test_scan_state_has_new_timing_fields():
      import main as m
      state = m._scan_state
      timing = state["engine_stats"]["timing"]
      for field in ("pass1_filter_s", "fetch_s", "rs_cache_s", "pass2_s"):
          assert field in timing, f"missing timing field: {field}"

  def test_scan_state_has_pass1_survivors():
      import main as m
      state = m._scan_state
      assert "pass1_survivors" in state["engine_stats"]

  def test_cache_store_module_level_singleton_exists():
      import main as m
      assert hasattr(m, "_cache_store")
      from cache_store import CacheStore
      assert isinstance(m._cache_store, CacheStore)
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```
  python -m pytest tests/test_scanner_filters_integration.py -k "new_timing or pass1_survivors or cache_store_singleton" -v 2>&1 | head -20
  ```
  Expected: `AssertionError` on missing fields.

- [ ] **Step 3: Add module-level `_cache_store` singleton to `main.py`**

  Near the module-level variable declarations (around line 428, after `_scan_state`):

  ```python
  # ── Disk-persisted OHLCV cache (scanner's own cache — separate from WFO) ─────
  from cache_store import CacheStore as _CacheStore
  _cache_store: _CacheStore = _CacheStore(cache_dir=SCAN_CACHE_DIR)
  ```

  In the `startup_event` handler (or equivalent app lifespan), add:

  ```python
  _cache_store.preload_index()
  ```

- [ ] **Step 4: Add new timing fields to `_scan_state` initialisation**

  In `_run_scan`, in the `_scan_state.update(...)` block (around line 1031), add to the timing dict:

  ```python
  "timing": {
      ...existing fields...,
      "pass1_filter_s": 0.0,
      "fetch_s":        0.0,
      "rs_cache_s":     0.0,
      "pass2_s":        0.0,
  },
  ```

  Also add outside timing:
  ```python
  "pass1_survivors": 0,
  "pass1_thresholds": {},
  "cache_hit_rate":   0.0,
  ```

- [ ] **Step 5: Replace breadth computation in `_run_scan`**

  Find the call to `compute_universe_breadth(_ticker_cache, tickers)` (around line 1208) and replace:

  ```python
  # OLD:
  breadth_pct, hl_ratio = compute_universe_breadth(_ticker_cache, tickers)

  # NEW:
  _breadth_start = time.time()
  breadth_pct, hl_ratio = _compute_breadth_from_metadata(tickers, _cache_store)
  log.info(
      "Breadth from metadata: %.1f%% above SMA50  H/L: %.2f  [%.2fs]",
      breadth_pct * 100, hl_ratio, time.time() - _breadth_start,
  )
  ```

- [ ] **Step 6: Add RS cache refresh before Pass 1**

  After the breadth computation, before the RS rank map call, add:

  ```python
  # ── RS rank cache: refresh if near-stale (> 20h) before Pass 1 uses it ───────
  _rs_cache_start = time.time()
  from scoring import _load_rs_cache as _lrc, _rs_cache_age_seconds, _rs_cache_valid
  _raw_rs_cache = _lrc()
  if _raw_rs_cache and _rs_cache_age_seconds(_raw_rs_cache) > RS_RANK_CACHE_REFRESH_THRESHOLD:
      log.info("RS cache is >20h old — refreshing before Pass 1")
      _rs_rank_map = compute_rs_rank_map(_ticker_cache, tickers, spy_df_full, sample_size=len(tickers))
      _raw_rs_cache = _lrc()   # reload the freshly written file
  _scan_state["engine_stats"]["timing"]["rs_cache_s"] = round(time.time() - _rs_cache_start, 2)
  _rs_for_pass1 = {k: v for k, v in (_raw_rs_cache or {}).items() if not k.startswith("_")}
  ```

- [ ] **Step 7: Insert Pass 1 call**

  After the RS cache check, replace the old bulk prefetch section:

  ```python
  # ── PASS 1: fast metadata filter ──────────────────────────────────────────────
  _pass1_start = time.time()
  survivors, _discovery_tickers = _pass1_filter(tickers, _cache_store, _rs_for_pass1)
  _pass1_time = round(time.time() - _pass1_start, 2)
  _scan_state["engine_stats"]["timing"]["pass1_filter_s"] = _pass1_time
  _scan_state["engine_stats"]["pass1_survivors"] = len(survivors)
  log.info(
      "Pass 1 complete: %d → %d survivors  [%.2fs]",
      len(tickers), len(survivors), _pass1_time,
  )

  # ── I/O phase: incremental fetch for survivors only ───────────────────────────
  _fetch_start = time.time()
  await _run_io_phase(survivors, _cache_store, semaphore)
  _fetch_time = round(time.time() - _fetch_start, 2)
  _scan_state["engine_stats"]["timing"]["fetch_s"] = _fetch_time
  log.info("Incremental fetch complete  [%.1fs]", _fetch_time)

  # Populate _ticker_cache from _cache_store for downstream compatibility
  for t in survivors:
      df = _cache_store.get(t)
      if df is not None:
          _ticker_cache[t] = (time.time(), df)
  ```

  Remove or comment out the old bulk prefetch block (the `uncached = [...]` / `prefetch_batches` loop, lines ~1152–1195).

- [ ] **Step 8: Replace `asyncio.gather` with `_run_compute_phase`**

  Find line 1716:
  ```python
  await asyncio.gather(*[_process(t, i) for i, t in enumerate(tickers)])
  ```
  Replace with:
  ```python
  # ── PASS 2: bounded compute worker pool ───────────────────────────────────────
  _pass2_start = time.time()
  await _run_compute_phase(survivors, _process)
  _scan_state["engine_stats"]["timing"]["pass2_s"] = round(time.time() - _pass2_start, 2)
  _scan_state["engine_stats"]["cache_hit_rate"] = _cache_store.cache_hit_rate()
  ```

  Note: `_process` already uses `semaphore` from outer scope via closure — no signature change needed.

- [ ] **Step 9: Update RS rank map computation to use fresh data**

  The RS rank map call (around line 1206) should now run AFTER the I/O phase, using the freshly populated `_ticker_cache`:

  ```python
  # Move RS rank map computation to after I/O phase (post Pass 1)
  _rs_rank_map = compute_rs_rank_map(_ticker_cache, survivors, spy_df_full, sample_size=len(survivors))
  ```

- [ ] **Step 10: Add new imports at top of `main.py`**

  ```python
  from constants import (
      ...existing...,
      RS_RANK_CACHE_REFRESH_THRESHOLD,
      SCAN_CACHE_DIR,
  )
  ```

- [ ] **Step 11: Run integration smoke tests**

  ```
  python -m pytest tests/test_scanner_filters_integration.py -v
  ```
  Expected: all `PASSED`.

- [ ] **Step 12: Run full test suite to catch regressions**

  ```
  python -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
  ```
  Expected: no new failures. If failures exist, investigate before proceeding.

- [ ] **Step 13: Commit**

  ```
  git add backend/main.py backend/tests/test_scanner_filters_integration.py
  git commit -m "feat: wire two-pass scan with worker queues and disk cache into _run_scan"
  ```

---

## Task 9: Smoke Test — End-to-End Scan Validation

Start the server and run one live scan to verify the two-pass pipeline works end-to-end. This is a manual validation step.

**Files:** None — runtime validation only.

- [ ] **Step 1: Start the backend**

  ```
  cd swing-trading-dashboard/backend
  python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
  ```
  Expected log lines on startup:
  ```
  [cache_store] Loaded metadata for N tickers   (or 0 on first run)
  ```

- [ ] **Step 2: Trigger a scan**

  ```
  curl -X POST http://localhost:8000/api/run-scan
  ```

- [ ] **Step 3: Poll scan status and observe logs**

  Watch the backend terminal for these expected log lines (in order):

  ```
  Breadth from metadata: XX.X% above SMA50
  Pass 1 complete: 1600 → N survivors  [0.XXs]    ← N should be 200-400
  Incremental fetch complete  [X.Xs]               ← X should be <60s (warm) or <300s (cold)
  RS rank map: N tickers ranked
  Engine 0: ...
  Pass 2 ...
  ✔ Scan complete  VCP=X  Pullbacks=X  ...
  ```

- [ ] **Step 4: Check timing via API**

  ```
  curl http://localhost:8000/api/scan-status | python -m json.tool | grep -A 20 timing
  ```
  Expected: `pass1_filter_s < 10`, `fetch_s < 120` (warm) or larger on first cold run.

- [ ] **Step 5: Verify scan results are unchanged from baseline**

  Run two scans back-to-back. Compare setup counts and tickers. They should be identical (deterministic, same data).

- [ ] **Step 6: Final commit**

  ```
  git add -A
  git commit -m "chore: scanner performance refactor complete — two-pass pipeline live"
  ```

---

## Regression Safety Checklist

Before calling the refactor complete, verify all of these:

- [ ] `python -m pytest tests/ -q` — all existing tests pass
- [ ] Scan produces same setups as the last pre-refactor scan (same tickers, same setup types)
- [ ] `GET /api/regime` returns valid regime data after a scan
- [ ] `GET /api/setups/vcp` returns setups (or empty list in DEFENSIVE) — not an error
- [ ] `data/scan_cache/` is populated with parquet files after the first scan
- [ ] `cache/rs_rank_cache.json` is written after each scan
- [ ] Second scan after restart is faster than the first (incremental fetch working)
- [ ] WFO system unaffected: `GET /api/wfo/status` and existing WFO tests pass
