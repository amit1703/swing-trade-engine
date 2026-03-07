"""
wfo_cache.py — Parquet-based price cache for Walk-Forward Validation.

Downloads and stores 10 years of daily OHLCV per ticker as Parquet files.
Provides load/save helpers used by the WFO engine to avoid repeated
yfinance calls during backtesting.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from constants import (
    WFO_CACHE_DIR,
    WFO_LOOKBACK_YEARS,
    WFO_MIN_HISTORY_YEARS,
    WFO_BULK_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

# Resolve cache dir relative to this file's location (backend/)
CACHE_DIR = Path(__file__).parent / WFO_CACHE_DIR


def get_cache_path(ticker: str) -> Path:
    """Return the Parquet file path for a ticker."""
    return CACHE_DIR / f"{ticker.upper()}.parquet"


def cache_exists(ticker: str) -> bool:
    """Return True if a cached Parquet file exists for the ticker."""
    return get_cache_path(ticker).exists()


def load_ticker(ticker: str) -> Optional[pd.DataFrame]:
    """
    Load cached OHLCV data for a ticker.

    Returns None if no cache file exists.
    """
    path = get_cache_path(ticker)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning("wfo_cache: failed to read %s: %s", path, exc)
        return None


def _integrity_check(df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """
    Run integrity checks on a freshly downloaded DataFrame.

    1. Drop rows with any NaN in OHLC columns.
    2. Sort by date ascending.
    3. Reject if fewer than WFO_MIN_HISTORY_YEARS × 252 rows remain.

    Returns cleaned DataFrame, or None if it fails the minimum history check.
    """
    ohlc_cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
    df = df.dropna(subset=ohlc_cols)
    df = df.sort_index()

    min_rows = int(WFO_MIN_HISTORY_YEARS * 252)
    if len(df) < min_rows:
        logger.warning(
            "wfo_cache: %s has only %d rows (need %d for %d years) — skipping",
            ticker, len(df), min_rows, WFO_MIN_HISTORY_YEARS,
        )
        return None

    return df


def download_and_cache(
    tickers: List[str],
    job_id: str,
    progress: dict,
) -> Dict[str, bool]:
    """
    Bulk-download 10 years of OHLCV for each ticker and save as Parquet.

    SPY should already be in the tickers list (caller's responsibility).
    Updates `progress` dict in-place for polling:
        progress["tickers_completed"]
        progress["total_tickers"]
        progress["status"]  — "running" | "done" | "error"

    Returns dict of {ticker: success_bool}.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    end_dt   = datetime.utcnow()
    start_dt = end_dt - timedelta(days=int(WFO_LOOKBACK_YEARS * 365.25))
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")

    results: Dict[str, bool] = {}
    progress["total_tickers"] = len(tickers)
    progress["tickers_completed"] = 0
    progress["status"] = "running"

    # Process in batches to avoid yfinance rate limits
    batches = [
        tickers[i : i + WFO_BULK_BATCH_SIZE]
        for i in range(0, len(tickers), WFO_BULK_BATCH_SIZE)
    ]

    for batch in batches:
        batch_results = _download_batch(batch, start_str, end_str)
        for ticker, df in batch_results.items():
            cleaned = _integrity_check(df, ticker)
            if cleaned is not None:
                try:
                    cleaned.to_parquet(get_cache_path(ticker))
                    results[ticker] = True
                    logger.info("wfo_cache: saved %s (%d rows)", ticker, len(cleaned))
                except Exception as exc:
                    logger.warning("wfo_cache: save failed for %s: %s", ticker, exc)
                    results[ticker] = False
            else:
                results[ticker] = False
            progress["tickers_completed"] += 1

        # Mark tickers not returned by batch as failed
        for ticker in batch:
            if ticker not in batch_results:
                results[ticker] = False
                progress["tickers_completed"] += 1

    progress["status"] = "done"
    return results


def _download_batch(
    batch: List[str],
    start_str: str,
    end_str: str,
) -> Dict[str, pd.DataFrame]:
    """Download one batch of tickers and return {ticker: df} dict."""
    if not batch:
        return {}

    if len(batch) == 1:
        ticker = batch[0]
        try:
            df = yf.Ticker(ticker).history(
                start=start_str, end=end_str, interval="1d", auto_adjust=False
            )
            return {ticker: df} if df is not None and not df.empty else {}
        except Exception as exc:
            logger.warning("wfo_cache: single download failed for %s: %s", ticker, exc)
            return {}

    try:
        raw = yf.download(
            batch,
            start=start_str,
            end=end_str,
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            progress=False,
            threads=True,
        )
        result: Dict[str, pd.DataFrame] = {}
        top_level = raw.columns.get_level_values(0).unique().tolist()
        for ticker in batch:
            try:
                if ticker not in top_level:
                    continue
                df = raw[ticker].copy()
                df = df.dropna(how="all")
                if df.empty:
                    continue
                if df.columns.duplicated().any():
                    df = df.loc[:, ~df.columns.duplicated()]
                result[ticker] = df
            except Exception:
                pass
        return result
    except Exception as exc:
        logger.warning("wfo_cache: batch download failed: %s", exc)
        return {}
