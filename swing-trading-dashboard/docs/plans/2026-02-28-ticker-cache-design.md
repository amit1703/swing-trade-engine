# Ticker Data Cache — Design Doc

**Date:** 2026-02-28

## Problem

Running the scan multiple times while the market is closed produces different tickers passing the engines each time. The algorithm is non-deterministic.

## Root Cause

`_fetch` calls yfinance live for all 700+ tickers on every scan with `CONCURRENCY_LIMIT=15`. Under rapid successive scans, yfinance rate-limits different tickers each time. After max retries those tickers are dropped silently. Different tickers dropped → different engine inputs → different results.

The engine logic itself is deterministic given identical data — the problem is entirely in the fetch layer.

## Design

### Module-level cache (`main.py`)

```python
_ticker_cache: dict[str, tuple[float, Optional[pd.DataFrame]]] = {}
```

Maps `ticker → (timestamp, df_or_None)`.

### Modified `_fetch` logic

Before any yfinance call, check the cache:

```python
entry = _ticker_cache.get(ticker)
if entry is not None:
    cached_ts, cached_df = entry
    ttl = CACHE_TTL_SUCCESS if cached_df is not None else CACHE_TTL_FAILURE
    if time.time() - cached_ts < ttl:
        return cached_df
```

On success: `_ticker_cache[ticker] = (time.time(), df)` — cached for 4 hours.
On all-retries failure: `_ticker_cache[ticker] = (time.time(), None)` — cached for 15 min.

**Negative caching** (caching `None` for failures) is the critical piece: a ticker that fails on Scan 1 also returns None on Scan 2 without hitting yfinance again, producing consistent results.

### New constants (`constants.py`)

```python
CACHE_TTL_SUCCESS = 14400   # 4 hours — market closed data doesn't change
CACHE_TTL_FAILURE = 900     # 15 min — allow retry after short window
```

### Secondary fix (`engine1.py`)

Line 107 currently uses `np.datetime64('today', 'D')` (wall clock) for KDE recency weights. Replace with the last bar in the ticker's own data:

```python
today = dates_valid.max()
```

This makes KDE weights data-driven rather than clock-driven — weights are consistent regardless of when during the day the scan runs.

## What Does NOT Change

- `_fetch` public interface — callers unchanged
- Engine logic — no changes to any engine
- DB schema — no new tables
- Scan duration for first run — identical to today
- Re-run duration — much faster (cache hit)

## Result

- Scan 1: populates cache for all ~700 tickers
- Scan 2+: reads from cache → identical DataFrames → identical engine outputs → deterministic
- After 4 hours (or 15 min for failed tickers): live re-fetch automatically
