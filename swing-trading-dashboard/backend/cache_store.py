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
