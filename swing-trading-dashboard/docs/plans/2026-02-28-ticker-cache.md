# Ticker Data Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an in-memory TTL cache to `_fetch` so that repeated scan runs within the same session receive identical data, eliminating yfinance rate-limit-driven non-determinism.

**Architecture:** A module-level dict `_ticker_cache` maps `ticker → (timestamp, df_or_None)`. Before any yfinance call, `_fetch` checks the cache: cache hits (within TTL) return immediately. Successful fetches are stored for 4 hours; failures are stored as `None` for 15 minutes (negative cache). Scan logic is unchanged — the fix is entirely inside `_fetch`.

**Tech Stack:** Python, yfinance, pytest, `unittest.mock`

---

### Task 1: Backend — TTL cache in `constants.py` + `main.py` + tests

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py:70-71` (add two TTL constants)
- Modify: `swing-trading-dashboard/backend/main.py:56-57` (add new constants to import list)
- Modify: `swing-trading-dashboard/backend/main.py:151` (declare `_ticker_cache` dict)
- Modify: `swing-trading-dashboard/backend/main.py:191-260` (`_fetch` — add cache check + cache writes)
- Test: `swing-trading-dashboard/backend/tests/test_ticker_cache.py` (new file)

---

**Step 1: Write four failing tests in a new file `tests/test_ticker_cache.py`**

Create the file with this exact content:

```python
import asyncio
import time

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
from unittest.mock import patch, MagicMock, AsyncMock

import main as m
from main import _fetch
from constants import FETCH_MAX_RETRIES, CACHE_TTL_SUCCESS, CACHE_TTL_FAILURE


def _make_df(n=300):
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    prices = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [p - 0.5 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [2_000_000] * n,
    }, index=dates)


@pytest.fixture(autouse=True)
def clear_cache():
    m._ticker_cache.clear()
    yield
    m._ticker_cache.clear()


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_cache_hit_avoids_second_yfinance_call(mock_sleep):
    """Second _fetch for same ticker uses cache — yfinance not called again."""
    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = _make_df()
        mock_ticker.return_value = mock_instance

        df1 = asyncio.run(_fetch('AAPL'))
        df2 = asyncio.run(_fetch('AAPL'))

        assert df1 is not None
        assert df2 is df1                          # same object — cache hit
        mock_instance.history.assert_called_once() # yfinance called exactly once


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_failure_is_negatively_cached(mock_sleep):
    """Fetch failure is cached as None; second call skips yfinance entirely."""
    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = pd.DataFrame()  # empty → all retries fail
        mock_ticker.return_value = mock_instance

        result1 = asyncio.run(_fetch('FAIL'))
        result2 = asyncio.run(_fetch('FAIL'))

        assert result1 is None
        assert result2 is None
        # First call exhausts all retry attempts; second call is a negative-cache hit
        assert mock_instance.history.call_count == FETCH_MAX_RETRIES + 1


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_stale_success_entry_triggers_refetch(mock_sleep):
    """After CACHE_TTL_SUCCESS seconds, a stale cache entry triggers re-fetch."""
    df = _make_df()
    # Pre-populate cache with a timestamp older than the success TTL
    m._ticker_cache['GOOG'] = (time.time() - CACHE_TTL_SUCCESS - 1, df)

    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = _make_df()
        mock_ticker.return_value = mock_instance

        result = asyncio.run(_fetch('GOOG'))

        assert result is not None
        mock_instance.history.assert_called_once()  # re-fetched after TTL expiry


@patch('asyncio.sleep', new_callable=AsyncMock)
def test_stale_failure_entry_triggers_refetch(mock_sleep):
    """After CACHE_TTL_FAILURE seconds, a negatively-cached ticker re-fetches."""
    # Pre-populate cache with a stale None entry
    m._ticker_cache['BAD'] = (time.time() - CACHE_TTL_FAILURE - 1, None)

    with patch('main.yf.Ticker') as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = _make_df()
        mock_ticker.return_value = mock_instance

        result = asyncio.run(_fetch('BAD'))

        assert result is not None
        mock_instance.history.assert_called_once()  # re-fetched after failure TTL expiry
```

**Step 2: Run to confirm all four fail**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_ticker_cache.py -v
```

Expected: all 4 FAIL — `AttributeError: module 'main' has no attribute '_ticker_cache'` (or `ImportError: cannot import name 'CACHE_TTL_SUCCESS'`).

---

**Step 3: Add TTL constants to `constants.py`**

File: `constants.py`, after line 70 (`FETCH_BACKOFF_BASE = 1.0`). Change:

```python
FETCH_MAX_RETRIES = 3  # Maximum retry attempts for data fetches
FETCH_BACKOFF_BASE = 1.0  # Base delay for exponential backoff (seconds)
```

To:

```python
FETCH_MAX_RETRIES = 3  # Maximum retry attempts for data fetches
FETCH_BACKOFF_BASE = 1.0  # Base delay for exponential backoff (seconds)
CACHE_TTL_SUCCESS = 14400  # Seconds to cache a successful fetch (4 hours)
CACHE_TTL_FAILURE = 900    # Seconds to cache a failed fetch — retry sooner (15 min)
```

**Step 4: Add the new constants to `main.py` imports**

File: `main.py`, lines 50-61. Change:

```python
from constants import (
    CONCURRENCY_LIMIT,
    DATA_FETCH_PERIOD,
    DB_PATH,
    DAYS_3_MONTHS,
    FETCH_BACKOFF_BASE,
    FETCH_MAX_RETRIES,
    MAX_TICKERS_PER_SCAN,
    MIN_CANDLES_FOR_ANALYSIS,
    MIN_CANDLES_FOR_RS,
    TRADING_DAYS_IN_YEAR,
)
```

To:

```python
from constants import (
    CACHE_TTL_FAILURE,
    CACHE_TTL_SUCCESS,
    CONCURRENCY_LIMIT,
    DATA_FETCH_PERIOD,
    DB_PATH,
    DAYS_3_MONTHS,
    FETCH_BACKOFF_BASE,
    FETCH_MAX_RETRIES,
    MAX_TICKERS_PER_SCAN,
    MIN_CANDLES_FOR_ANALYSIS,
    MIN_CANDLES_FOR_RS,
    TRADING_DAYS_IN_YEAR,
)
```

**Step 5: Declare `_ticker_cache` in `main.py`**

File: `main.py`, line 151. Currently:

```python
_semaphore: Optional[asyncio.Semaphore] = None
```

Change to:

```python
_semaphore: Optional[asyncio.Semaphore] = None
_ticker_cache: dict = {}  # ticker → (timestamp: float, df: Optional[pd.DataFrame])
```

**Step 6: Add the cache check to `_fetch` — before the `for` loop**

File: `main.py`. The `_fetch` function starts at line 191. It has a docstring, then `for attempt in range(...)`. Insert the cache check block between the docstring and the `for` loop:

Currently:

```python
async def _fetch(ticker: str, retry_count: int = 0) -> Optional[pd.DataFrame]:
    """
    Download daily OHLCV for one ticker with retry logic and exponential backoff.

    Semaphore is acquired per-attempt (not held across retries) to prevent
    deadlock when multiple tasks retry simultaneously.
    """
    for attempt in range(retry_count, FETCH_MAX_RETRIES + 1):
```

Change to:

```python
async def _fetch(ticker: str, retry_count: int = 0) -> Optional[pd.DataFrame]:
    """
    Download daily OHLCV for one ticker with retry logic and exponential backoff.

    Semaphore is acquired per-attempt (not held across retries) to prevent
    deadlock when multiple tasks retry simultaneously.
    """
    # ── In-memory TTL cache ───────────────────────────────────────────────────
    # Successive scan runs within the same session reuse cached data, preventing
    # yfinance rate-limiting from causing different tickers to be dropped each run.
    entry = _ticker_cache.get(ticker)
    if entry is not None:
        cached_ts, cached_df = entry
        ttl = CACHE_TTL_SUCCESS if cached_df is not None else CACHE_TTL_FAILURE
        if time.time() - cached_ts < ttl:
            return cached_df

    for attempt in range(retry_count, FETCH_MAX_RETRIES + 1):
```

**Step 7: Cache the successful return in `_fetch`**

Still in `_fetch`. Find the `else:` branch that handles non-empty data (around line 230). Currently:

```python
                else:
                    # Flatten MultiIndex (newer yfinance versions)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    # Deduplicate columns (yfinance can produce duplicates)
                    if df.columns.duplicated().any():
                        df = df.loc[:, ~df.columns.duplicated()]
                    return df
```

Change to:

```python
                else:
                    # Flatten MultiIndex (newer yfinance versions)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    # Deduplicate columns (yfinance can produce duplicates)
                    if df.columns.duplicated().any():
                        df = df.loc[:, ~df.columns.duplicated()]
                    _ticker_cache[ticker] = (time.time(), df)
                    return df
```

**Step 8: Cache the two `return None` failure paths in `_fetch`**

There are three `return None` statements in `_fetch`. Add `_ticker_cache[ticker] = (time.time(), None)` before each one.

**Failure path A** — empty data after all retries. Currently:

```python
                    else:
                        log.warning(
                            "Fetch DROPPED %s: empty/None data after %d retries",
                            ticker, FETCH_MAX_RETRIES,
                        )
                        return None
```

Change to:

```python
                    else:
                        log.warning(
                            "Fetch DROPPED %s: empty/None data after %d retries",
                            ticker, FETCH_MAX_RETRIES,
                        )
                        _ticker_cache[ticker] = (time.time(), None)
                        return None
```

**Failure path B** — exception after all retries. Currently:

```python
                else:
                    log.warning(
                        "Fetch DROPPED %s: %s after %d retries",
                        ticker, type(exc).__name__, FETCH_MAX_RETRIES,
                    )
                    return None
```

Change to:

```python
                else:
                    log.warning(
                        "Fetch DROPPED %s: %s after %d retries",
                        ticker, type(exc).__name__, FETCH_MAX_RETRIES,
                    )
                    _ticker_cache[ticker] = (time.time(), None)
                    return None
```

**Failure path C** — final `return None` at the end of the function (line 260). Currently:

```python
    return None
```

Change to:

```python
    _ticker_cache[ticker] = (time.time(), None)
    return None
```

**Step 9: Run the four new tests to confirm they all pass**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_ticker_cache.py -v
```

Expected: all 4 PASS.

**Step 10: Run the full test suite to confirm nothing regresses**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: all 143 existing tests + 4 new tests = **147 tests PASS**.

**Step 11: Commit**

```bash
git add swing-trading-dashboard/backend/constants.py \
        swing-trading-dashboard/backend/main.py \
        swing-trading-dashboard/backend/tests/test_ticker_cache.py
git commit -m "feat(cache): add in-memory TTL cache to _fetch for deterministic scan results"
```

---

### Task 2: Secondary fix — pin KDE recency weights to data's own last date

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine1.py:107`

This is a one-line change. No new test needed — the existing 143 tests cover engine1 behaviour; running the full suite after is sufficient.

---

**Step 1: Change `np.datetime64('today', 'D')` to use data's own last date**

File: `engine1.py`, line 107. Currently:

```python
        today = np.datetime64('today', 'D')
        days_ago = (today - dates_valid.astype('datetime64[D]')).astype(float)
```

Change to:

```python
        today = dates_valid.max()
        days_ago = (today - dates_valid.astype('datetime64[D]')).astype(float)
```

`dates_valid.max()` is already a `numpy.datetime64` (same type as before), so all downstream arithmetic is unchanged. The KDE now weights price points relative to the ticker's own most recent bar instead of the system wall clock.

**Step 2: Run the full test suite**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: all 147 tests PASS.

**Step 3: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine1.py
git commit -m "fix(engine1): pin KDE recency weights to data's own last date, not wall clock"
```

---

## Manual Verification

After both tasks are committed:

1. Start the backend: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
2. Run Scan once — note which tickers appear in each table
3. Run Scan again immediately
4. Confirm: **same tickers in same tables both times**
5. Check backend logs — second scan should show no yfinance calls (cache hits only), completing much faster
