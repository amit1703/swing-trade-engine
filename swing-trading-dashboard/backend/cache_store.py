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
import yfinance as yf

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

    # ── Public: incremental fetch ─────────────────────────────────────────────

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
        self._flush_metadata()

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


# ── Module-level helpers ──────────────────────────────────────────────────────

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
