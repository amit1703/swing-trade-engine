# Walk-Forward Validation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a walk-forward optimization (WFO) system that validates strategy robustness across rolling IS/OOS windows with Parquet data caching, API endpoints, and a new tab in BacktestPanel.

**Architecture:** Four layers — Data Cache (wfo_cache.py + Parquet files) → WFO Engine (wfo_engine.py) → API (6 new endpoints in main.py + wfo_results DB table) → Frontend (Walk-Forward tab in BacktestPanel.jsx). BacktestEngine gains optional preloaded-df params to skip yfinance fetching.

**Tech Stack:** Python 3.11, FastAPI, pandas, numpy, pyarrow (new), aiosqlite, React 18, plain SVG for charts.

**Design reference:** `docs/plans/2026-03-07-walk-forward-validation-design.md`

---

### Task 1: Data Cache Layer

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/constants.py`
- Create: `backend/wfo_cache.py`
- Create: `backend/tests/test_wfo_cache.py`
- Create: `backend/data/price_cache/.gitkeep`
- Modify: `.gitignore` (ignore parquet files)

**Context for implementer:**

The WFO engine needs 10 years of OHLCV history per ticker, cached as Parquet. The cache lives at `backend/data/price_cache/{ticker}.parquet`. SPY is always cached (needed for RS calculations). Bulk download uses `yf.download(..., group_by="ticker", threads=True)` to avoid per-ticker rate limits.

New constants needed:
- `WFO_CACHE_DIR = "data/price_cache"` — relative to backend/
- `WFO_LOOKBACK_YEARS = 10` — how far back to download
- `WFO_MIN_HISTORY_YEARS = 5` — minimum usable history to save
- `WFO_BULK_BATCH_SIZE = 100` — tickers per yf.download call

Integrity check (applied before saving each ticker):
1. Drop rows with any NaN in Open/High/Low/Close columns
2. Sort index ascending by date
3. Reject and warn if fewer than `WFO_MIN_HISTORY_YEARS × 252` rows remain after cleaning

The `download_and_cache` function accepts a mutable `progress` dict that the caller can poll:
```python
progress = {"status": "running", "tickers_completed": 0, "total_tickers": 120}
```

---

**Step 1: Write failing tests**

Create `backend/tests/test_wfo_cache.py`:

```python
"""Tests for WFO data cache layer."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import wfo_cache


def _make_df(years=6, base_price=100.0):
    """Create a clean OHLCV DataFrame with enough history."""
    n = int(years * 252)
    dates = pd.date_range("2014-01-01", periods=n, freq="B")
    close = np.linspace(base_price * 0.5, base_price, n)
    return pd.DataFrame(
        {
            "Open":   close * 0.99,
            "High":   close * 1.01,
            "Low":    close * 0.98,
            "Close":  close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )


def test_get_cache_path_returns_parquet_path(tmp_path):
    """get_cache_path returns a .parquet path inside the cache dir."""
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        p = wfo_cache.get_cache_path("AAPL")
    assert str(p).endswith("AAPL.parquet")
    assert "AAPL" in str(p)


def test_cache_exists_false_for_missing(tmp_path):
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        assert wfo_cache.cache_exists("MISSING") is False


def test_cache_exists_true_after_write(tmp_path):
    df = _make_df()
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        df.to_parquet(wfo_cache.get_cache_path("AAPL"))
        assert wfo_cache.cache_exists("AAPL") is True


def test_load_ticker_returns_none_for_missing(tmp_path):
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        result = wfo_cache.load_ticker("NONEXISTENT")
    assert result is None


def test_load_ticker_roundtrip(tmp_path):
    """load_ticker reads back what was saved."""
    df = _make_df()
    with patch.object(wfo_cache, "CACHE_DIR", tmp_path):
        df.to_parquet(wfo_cache.get_cache_path("TEST"))
        result = wfo_cache.load_ticker("TEST")
    assert result is not None
    assert len(result) == len(df)
    assert list(result.columns) == list(df.columns)


def test_integrity_check_drops_nan_rows():
    """_integrity_check drops rows with NaN in OHLC columns."""
    df = _make_df(years=6)
    df.iloc[10, df.columns.get_loc("Close")] = float("nan")
    result = wfo_cache._integrity_check(df, "TEST")
    assert result is not None
    assert len(result) == len(df) - 1  # one row dropped


def test_integrity_check_rejects_short_history():
    """_integrity_check returns None when history < WFO_MIN_HISTORY_YEARS."""
    df = _make_df(years=2)  # only 2 years, below 5-year minimum
    result = wfo_cache._integrity_check(df, "SHORT")
    assert result is None


def test_integrity_check_sorts_ascending():
    """_integrity_check sorts the DataFrame by date ascending."""
    df = _make_df(years=6)
    df = df.iloc[::-1]  # reverse order
    result = wfo_cache._integrity_check(df, "TEST")
    assert result is not None
    assert result.index.is_monotonic_increasing
```

**Step 2: Run tests to confirm they fail**

```bash
cd backend
python -m pytest tests/test_wfo_cache.py -v
```

Expected: `ImportError` — `wfo_cache` module does not exist yet.

**Step 3: Add pyarrow to requirements.txt**

Add after the last line:
```
pyarrow>=14.0.0
```

**Step 4: Add WFO constants to constants.py**

Add a new section after the `# Bulk Download (Task 5)` section:

```python
# ──────────────────────────────────────────────────────────────────────────────
# Walk-Forward Validation (WFO)
# ──────────────────────────────────────────────────────────────────────────────

WFO_CACHE_DIR         = "data/price_cache"   # relative to backend/
WFO_LOOKBACK_YEARS    = 10                   # years of history to download
WFO_MIN_HISTORY_YEARS = 5                    # minimum usable years before rejecting
WFO_BULK_BATCH_SIZE   = 100                  # tickers per yf.download() call
```

**Step 5: Create `backend/wfo_cache.py`**

```python
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
```

**Step 6: Create cache directory placeholder**

```bash
mkdir -p backend/data/price_cache
touch backend/data/price_cache/.gitkeep
```

**Step 7: Add to .gitignore**

Open `.gitignore` in the project root and add:
```
# WFO price cache (large Parquet files)
swing-trading-dashboard/backend/data/price_cache/*.parquet
```

**Step 8: Run tests to confirm they pass**

```bash
cd backend
pip install pyarrow
python -m pytest tests/test_wfo_cache.py -v
```

Expected: `8 passed`

**Step 9: Run full suite**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: all tests pass (275 + 8 new = 283)

**Step 10: Commit**

```bash
git add backend/requirements.txt backend/constants.py backend/wfo_cache.py \
        backend/tests/test_wfo_cache.py backend/data/price_cache/.gitkeep .gitignore
git commit -m "feat(wfo): add Parquet price cache layer with bulk download"
```

---

### Task 2: BacktestEngine Preloaded-DF Support

**Files:**
- Modify: `backend/backtest_engine.py` (lines 463–510)
- Create: `backend/tests/test_backtest_preloaded_df.py`

**Context for implementer:**

Currently `BacktestEngine.__init__` takes `ticker, start_date, end_date, setup_types, run_id`. The `run()` method calls `_fetch_data(self.ticker, self.start_date)` to get OHLCV data.

The WFO engine will call BacktestEngine hundreds of times with pre-downloaded DataFrames from the Parquet cache. We need to add two optional params: `ticker_df` and `spy_df`. When both are provided, `run()` skips the `_fetch_data` call entirely.

The existing date-window logic (`replay_dates = all_dates[(all_dates >= start) & (all_dates <= end)]`) already handles slicing the preloaded 10-year df to the IS/OOS window. No other changes needed.

**Step 1: Write failing tests**

Create `backend/tests/test_backtest_preloaded_df.py`:

```python
"""Tests for BacktestEngine preloaded-df support (WFO integration)."""
import os
import sys
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest_engine import BacktestEngine


def _make_ticker_df(n=400, base_price=100.0):
    """Uptrending OHLCV DataFrame with enough warmup bars."""
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.linspace(80.0, base_price, n)
    return pd.DataFrame(
        {
            "Open":      close * 0.99,
            "High":      close * 1.01,
            "Low":       close * 0.98,
            "Close":     close,
            "Adj Close": close,
            "Volume":    np.full(n, 1_000_000.0),
        },
        index=dates,
    )


def _make_spy_df(n=400):
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.linspace(400.0, 480.0, n)
    return pd.DataFrame(
        {
            "Open":  close * 0.99,
            "High":  close * 1.005,
            "Low":   close * 0.995,
            "Close": close,
            "Volume": np.full(n, 50_000_000.0),
        },
        index=dates,
    )


@pytest.mark.asyncio
async def test_preloaded_df_skips_fetch():
    """When ticker_df and spy_df are provided, _fetch_data is never called."""
    ticker_df = _make_ticker_df()
    spy_df    = _make_spy_df()

    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-06-30",
        setup_types=["VCP"],
        ticker_df=ticker_df,
        spy_df=spy_df,
    )

    with patch("backtest_engine._fetch_data", new_callable=AsyncMock) as mock_fetch:
        await engine.run()

    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_none_df_still_calls_fetch():
    """When no preloaded df is given, _fetch_data is called (backward compat)."""
    mock_df = _make_ticker_df()

    engine = BacktestEngine(
        ticker="AAPL",
        start_date="2023-01-01",
        end_date="2023-03-31",
        setup_types=["VCP"],
    )

    with patch("backtest_engine._fetch_data", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (None, None)  # simulate fetch failure → empty result
        await engine.run()

    mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_preloaded_df_window_slice_respects_dates():
    """BacktestEngine replays only dates within start_date..end_date from a 400-bar df."""
    ticker_df = _make_ticker_df(n=400)
    spy_df    = _make_spy_df(n=400)

    # Window is within the df range
    start = ticker_df.index[200].strftime("%Y-%m-%d")
    end   = ticker_df.index[250].strftime("%Y-%m-%d")

    engine = BacktestEngine(
        ticker="TEST",
        start_date=start,
        end_date=end,
        setup_types=["VCP"],
        ticker_df=ticker_df,
        spy_df=spy_df,
    )

    summary = await engine.run()
    # Summary should exist (may have 0 trades, that's fine — just verifying no crash)
    assert summary is not None
    assert summary.start_date == start
    assert summary.end_date   == end
```

**Step 2: Run tests to confirm they fail**

```bash
cd backend
python -m pytest tests/test_backtest_preloaded_df.py -v
```

Expected: `FAILED` — `BacktestEngine.__init__` does not accept `ticker_df` or `spy_df` yet.

**Step 3: Modify `BacktestEngine.__init__`**

Find lines 463–475 in `backend/backtest_engine.py`:
```python
    def __init__(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        setup_types: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ):
        self.ticker      = ticker.upper()
        self.start_date  = start_date
        self.end_date    = end_date
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
        self.run_id      = run_id or str(uuid.uuid4())
```

Change to:
```python
    def __init__(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        setup_types: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        ticker_df: Optional[pd.DataFrame] = None,
        spy_df: Optional[pd.DataFrame] = None,
    ):
        self.ticker      = ticker.upper()
        self.start_date  = start_date
        self.end_date    = end_date
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
        self.run_id      = run_id or str(uuid.uuid4())
        self.ticker_df   = ticker_df
        self.spy_df      = spy_df
```

**Step 4: Modify `BacktestEngine.run()` to skip fetch when preloaded**

Find lines 485–506 in `backend/backtest_engine.py`:
```python
        # ── 1. Fetch data ─────────────────────────────────────────────────
        ticker_df, spy_df = await _fetch_data(self.ticker, self.start_date)
        if ticker_df is None or spy_df is None:
            logger.warning("Backtest: data fetch failed for %s", self.ticker)
            return compute_metrics(
                self.ticker, "+".join(self.setup_types),
                self.start_date, self.end_date, [], run_id,
            )
```

Change to:
```python
        # ── 1. Fetch data (or use preloaded df for WFO) ───────────────────
        if self.ticker_df is not None and self.spy_df is not None:
            ticker_df = self.ticker_df
            spy_df    = self.spy_df
        else:
            ticker_df, spy_df = await _fetch_data(self.ticker, self.start_date)
            if ticker_df is None or spy_df is None:
                logger.warning("Backtest: data fetch failed for %s", self.ticker)
                return compute_metrics(
                    self.ticker, "+".join(self.setup_types),
                    self.start_date, self.end_date, [], run_id,
                )
```

**Step 5: Run tests to confirm they pass**

```bash
cd backend
python -m pytest tests/test_backtest_preloaded_df.py -v
```

Expected: `3 passed`

**Step 6: Run full suite**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: all tests pass (283 + 3 = 286)

**Step 7: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_preloaded_df.py
git commit -m "feat(backtest): add optional preloaded ticker_df/spy_df to skip yfinance fetch"
```

---

### Task 3: WFO Engine

**Files:**
- Create: `backend/wfo_engine.py`
- Create: `backend/tests/test_wfo_engine.py`

**Context for implementer:**

The WFO engine orchestrates rolling IS/OOS window backtests. Key concepts:

- **Window generation:** Given a date range, IS/OOS/step lengths in months, produce a list of `(is_start, is_end, oos_start, oos_end)` tuples. Use `pd.DateOffset(months=n)` for month arithmetic.
- **Per-window execution:** For each window, for each ticker, run BacktestEngine twice (IS period, OOS period) with preloaded DFs from the cache. Collect all trades across tickers for IS and OOS separately.
- **Metrics computation:** `_compute_wfo_metrics()` takes a list of `TradeRecord` objects and returns a `WFOMetrics` dataclass.
- **Per-setup breakdown:** After collecting all trades for a window, filter by `setup_type` and compute metrics for each.
- **Stability score:** `OOS_expectancy / IS_expectancy` (0.0 if IS expectancy ≤ 0).
- **Progress tracking:** `progress` dict updated with `windows_completed` and `total_windows` for the API status endpoint.

**WFOMetrics fields** (per window, per IS/OOS period, aggregate + per-setup):
- `trades` (int), `win_rate` (float %), `avg_r` (float), `median_r` (float), `expectancy` (float), `profit_factor` (float), `net_profit_pct` (float), `reliable` (bool: trades >= min_trades)

**Expectancy formula** (matches design doc):
`expectancy = (win_rate_frac × avg_win_r) − (loss_rate_frac × avg_loss_r_abs)`

Where `avg_loss_r_abs` is the magnitude of average loss R.

---

**Step 1: Write failing tests**

Create `backend/tests/test_wfo_engine.py`:

```python
"""Tests for WFO engine — window generation and metrics computation."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wfo_engine import _generate_windows, _compute_wfo_metrics, WFOMetrics
from backtest_engine import TradeRecord


def _make_trade(ticker="TEST", setup_type="VCP", rr=1.0, pnl_pct=2.0):
    """Create a minimal TradeRecord with controlled rr_achieved."""
    # Reverse-engineer entry/stop/exit so __post_init__ gives us desired rr
    entry  = 100.0
    stop   = 99.0   # risk = 1.0
    if rr > 0:
        exit_p = entry + rr * 1.0
    else:
        exit_p = entry + rr * 1.0  # negative rr → exit < entry

    t = TradeRecord(
        ticker=ticker,
        setup_type=setup_type,
        signal_date="2024-01-01",
        entry_date="2024-01-02",
        entry_price=entry,
        initial_stop=stop,
        take_profit=102.0,
        exit_date="2024-01-10",
        exit_price=exit_p,
        exit_reason="TARGET" if rr > 0 else "STOP",
        holding_days=8,
    )
    return t


def test_generate_windows_returns_non_empty():
    start = pd.Timestamp("2016-01-01")
    end   = pd.Timestamp("2025-12-31")
    windows = _generate_windows(start, end, is_months=24, oos_months=3, step_months=3)
    assert len(windows) > 0


def test_generate_windows_oos_non_overlapping():
    """OOS periods must not overlap between consecutive windows."""
    start = pd.Timestamp("2016-01-01")
    end   = pd.Timestamp("2025-12-31")
    windows = _generate_windows(start, end, is_months=24, oos_months=3, step_months=3)
    for i in range(len(windows) - 1):
        _, _, _, oos_end_i   = windows[i]
        _, _, oos_start_next, _ = windows[i + 1]
        assert oos_end_i <= oos_start_next, "OOS periods should not overlap"


def test_generate_windows_count_approx_24():
    """Default 24/3/3 config over 8-year range produces ~24 windows."""
    start = pd.Timestamp("2016-01-01")
    end   = pd.Timestamp("2025-12-31")
    windows = _generate_windows(start, end, is_months=24, oos_months=3, step_months=3)
    # Should be ~31 windows for a ~9.75 year span (8yr effective = 32 steps)
    assert 20 <= len(windows) <= 40


def test_compute_wfo_metrics_empty_trades():
    """Empty trade list returns zero metrics with reliable=False."""
    m = _compute_wfo_metrics([], min_trades=20)
    assert m.trades == 0
    assert m.win_rate == 0.0
    assert m.reliable is False


def test_compute_wfo_metrics_basic():
    """Basic metrics computed correctly from known trades."""
    # 2 wins (rr=2.0) + 1 loss (rr=-1.0)
    trades = [
        _make_trade(rr=2.0),
        _make_trade(rr=2.0),
        _make_trade(rr=-1.0),
    ]
    m = _compute_wfo_metrics(trades, min_trades=2)
    assert m.trades == 3
    assert abs(m.win_rate - 66.67) < 0.1
    assert abs(m.avg_r - 1.0) < 0.01          # (2 + 2 - 1) / 3
    assert abs(m.median_r - 2.0) < 0.01
    assert m.profit_factor > 1.0
    assert m.reliable is True


def test_compute_wfo_metrics_reliable_flag():
    """reliable=True only when trades >= min_trades."""
    trades = [_make_trade() for _ in range(15)]
    m_not = _compute_wfo_metrics(trades, min_trades=20)
    m_yes = _compute_wfo_metrics(trades, min_trades=10)
    assert m_not.reliable is False
    assert m_yes.reliable is True


@pytest.mark.asyncio
async def test_run_wfo_returns_wfo_result():
    """run_wfo returns a WFOResult with the correct metadata."""
    from wfo_engine import run_wfo

    # Mock cache to return a minimal df for each ticker
    n = 400
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    close = np.linspace(80.0, 100.0, n)
    mock_df = pd.DataFrame(
        {
            "Open":      close * 0.99,
            "High":      close * 1.01,
            "Low":       close * 0.98,
            "Close":     close,
            "Adj Close": close,
            "Volume":    np.full(n, 1_000_000.0),
        },
        index=dates,
    )

    with patch("wfo_engine.load_ticker", return_value=mock_df), \
         patch("wfo_engine.cache_exists", return_value=True):
        result = await run_wfo(
            tickers=["AAPL"],
            setup_types=["VCP"],
            is_months=12,
            oos_months=3,
            step_months=6,
            min_trades=1,
        )

    assert result is not None
    assert result.tickers == ["AAPL"]
    assert result.is_months == 12
    assert len(result.windows) > 0
```

**Step 2: Run tests to confirm they fail**

```bash
cd backend
python -m pytest tests/test_wfo_engine.py -v
```

Expected: `ImportError` — `wfo_engine` module does not exist yet.

**Step 3: Create `backend/wfo_engine.py`**

```python
"""
wfo_engine.py — Walk-Forward Optimization engine.

Rolls IS/OOS windows over cached price data, runs BacktestEngine for each
window/ticker combination, and aggregates trade-level metrics.

Entry point: run_wfo(tickers, setup_types, is_months, oos_months, ...)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from backtest_engine import BacktestEngine, TradeRecord
from wfo_cache import load_ticker, cache_exists

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WFOMetrics:
    """Aggregate metrics for one IS or OOS period."""
    trades:         int
    win_rate:       float   # %
    avg_r:          float   # mean R-multiple
    median_r:       float   # median R-multiple
    expectancy:     float   # (wr × avg_win_r) − (lr × avg_loss_r_abs)
    profit_factor:  float   # gross_profit / abs(gross_loss); inf if no losses
    net_profit_pct: float   # sum of pnl_pct across all trades
    reliable:       bool    # True when trades >= min_trades

    def to_dict(self) -> dict:
        return {
            "trades":         self.trades,
            "win_rate":       round(self.win_rate, 2),
            "avg_r":          round(self.avg_r, 3),
            "median_r":       round(self.median_r, 3),
            "expectancy":     round(self.expectancy, 3),
            "profit_factor":  round(self.profit_factor, 3),
            "net_profit_pct": round(self.net_profit_pct, 2),
            "reliable":       self.reliable,
        }


@dataclass
class WFOWindowResult:
    """Results for one rolling window."""
    window_num:     int
    is_start:       str
    is_end:         str
    oos_start:      str
    oos_end:        str
    is_metrics:     WFOMetrics
    oos_metrics:    WFOMetrics
    stability_score: float               # OOS_expectancy / IS_expectancy
    per_setup:      Dict[str, dict]      # {setup_type: {"is": dict, "oos": dict}}
    is_trades:      List[dict]           # raw trade records (IS)
    oos_trades:     List[dict]           # raw trade records (OOS)

    def to_dict(self) -> dict:
        return {
            "window_num":      self.window_num,
            "is_start":        self.is_start,
            "is_end":          self.is_end,
            "oos_start":       self.oos_start,
            "oos_end":         self.oos_end,
            "is_metrics":      self.is_metrics.to_dict(),
            "oos_metrics":     self.oos_metrics.to_dict(),
            "stability_score": round(self.stability_score, 3),
            "per_setup":       self.per_setup,
            "is_trades":       self.is_trades,
            "oos_trades":      self.oos_trades,
        }


@dataclass
class WFOResult:
    """Full walk-forward result for one run."""
    run_id:      str
    tickers:     List[str]
    setup_types: List[str]
    is_months:   int
    oos_months:  int
    step_months: int
    min_trades:  int
    created_at:  str
    windows:     List[WFOWindowResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id":      self.run_id,
            "tickers":     self.tickers,
            "setup_types": self.setup_types,
            "is_months":   self.is_months,
            "oos_months":  self.oos_months,
            "step_months": self.step_months,
            "min_trades":  self.min_trades,
            "created_at":  self.created_at,
            "windows":     [w.to_dict() for w in self.windows],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Window generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_windows(
    start: pd.Timestamp,
    end:   pd.Timestamp,
    is_months:   int,
    oos_months:  int,
    step_months: int,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """
    Generate rolling (is_start, is_end, oos_start, oos_end) window tuples.

    IS and OOS windows are non-overlapping. Steps forward by step_months each
    iteration. Stops when oos_end would exceed the available data end date.
    """
    windows = []
    is_start = start
    while True:
        is_end    = is_start + pd.DateOffset(months=is_months)
        oos_start = is_end
        oos_end   = oos_start + pd.DateOffset(months=oos_months)
        if oos_end > end:
            break
        windows.append((is_start, is_end, oos_start, oos_end))
        is_start = is_start + pd.DateOffset(months=step_months)
    return windows


# ─────────────────────────────────────────────────────────────────────────────
# Metrics computation
# ─────────────────────────────────────────────────────────────────────────────

def _compute_wfo_metrics(trades: List[TradeRecord], min_trades: int) -> WFOMetrics:
    """
    Compute WFO-specific aggregate metrics from a list of TradeRecord objects.

    Expectancy = (win_rate_frac × avg_win_r) − (loss_rate_frac × avg_loss_r_abs)
    where avg_loss_r_abs is the magnitude of average loss R.
    """
    n = len(trades)
    if n == 0:
        return WFOMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False)

    wins   = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    win_rate     = len(wins) / n * 100
    loss_rate    = len(losses) / n

    all_r    = [t.rr_achieved for t in trades]
    avg_r    = float(np.mean(all_r))
    median_r = float(np.median(all_r))

    avg_win_r     = float(np.mean([t.rr_achieved for t in wins]))   if wins   else 0.0
    avg_loss_r_abs = float(np.mean([abs(t.rr_achieved) for t in losses])) if losses else 0.0

    win_rate_frac  = len(wins)   / n
    loss_rate_frac = len(losses) / n
    expectancy = (win_rate_frac * avg_win_r) - (loss_rate_frac * avg_loss_r_abs)

    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss   = abs(sum(t.pnl_pct for t in losses))
    profit_factor  = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_profit_pct = sum(t.pnl_pct for t in trades)

    return WFOMetrics(
        trades=n,
        win_rate=win_rate,
        avg_r=avg_r,
        median_r=median_r,
        expectancy=expectancy,
        profit_factor=profit_factor,
        net_profit_pct=net_profit_pct,
        reliable=n >= min_trades,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_wfo(
    tickers:     List[str],
    setup_types: List[str],
    is_months:   int  = 24,
    oos_months:  int  = 3,
    step_months: int  = 3,
    min_trades:  int  = 20,
    run_id:      Optional[str]  = None,
    progress:    Optional[dict] = None,
) -> WFOResult:
    """
    Run walk-forward optimization across rolling IS/OOS windows.

    Parameters
    ----------
    tickers     : list of ticker symbols (must be cached — see wfo_cache.py)
    setup_types : list of setup type strings (VCP, PULLBACK, etc.)
    is_months   : in-sample window length in months
    oos_months  : out-of-sample window length in months
    step_months : step size between windows in months
    min_trades  : minimum trades for a window to be marked reliable
    run_id      : optional run identifier (auto-generated if None)
    progress    : optional mutable dict for status polling:
                    {"windows_completed": 0, "total_windows": N}

    Returns
    -------
    WFOResult with all windows populated.
    """
    run_id = run_id or str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    # ── Load all cached DataFrames upfront ────────────────────────────────────
    loaded_dfs: Dict[str, pd.DataFrame] = {}
    spy_df: Optional[pd.DataFrame] = None

    for ticker in tickers:
        if not cache_exists(ticker):
            logger.warning("wfo: no cache for %s — skipping", ticker)
            continue
        df = load_ticker(ticker)
        if df is None:
            continue
        if ticker == "SPY":
            spy_df = df
        loaded_dfs[ticker] = df

    if spy_df is None and "SPY" in loaded_dfs:
        spy_df = loaded_dfs["SPY"]

    if spy_df is None:
        logger.warning("wfo: SPY cache missing — RS signals will be degraded")
        # Create a dummy spy_df from the first available ticker to avoid crashes
        if loaded_dfs:
            first = next(iter(loaded_dfs.values()))
            spy_df = first.copy()
        else:
            return WFOResult(
                run_id=run_id, tickers=tickers, setup_types=setup_types,
                is_months=is_months, oos_months=oos_months, step_months=step_months,
                min_trades=min_trades, created_at=created_at, windows=[],
            )

    # ── Determine date range from available data ───────────────────────────────
    all_start_dates = [df.index.min() for df in loaded_dfs.values()]
    all_end_dates   = [df.index.max() for df in loaded_dfs.values()]

    data_start = max(all_start_dates)   # latest start = earliest common date
    data_end   = min(all_end_dates)     # earliest end = latest common date

    windows = _generate_windows(data_start, data_end, is_months, oos_months, step_months)

    if progress is not None:
        progress["total_windows"]     = len(windows)
        progress["windows_completed"] = 0

    logger.info("wfo [%s]: %d tickers, %d windows", run_id, len(loaded_dfs), len(windows))

    # ── Per-window loop ────────────────────────────────────────────────────────
    result_windows: List[WFOWindowResult] = []

    for window_num, (is_start, is_end, oos_start, oos_end) in enumerate(windows, 1):
        is_start_str  = is_start.strftime("%Y-%m-%d")
        is_end_str    = is_end.strftime("%Y-%m-%d")
        oos_start_str = oos_start.strftime("%Y-%m-%d")
        oos_end_str   = oos_end.strftime("%Y-%m-%d")

        is_trades_all:  List[TradeRecord] = []
        oos_trades_all: List[TradeRecord] = []

        for ticker, ticker_df in loaded_dfs.items():
            if ticker == "SPY":
                continue  # Don't backtest SPY itself

            # IS period
            is_engine = BacktestEngine(
                ticker=ticker,
                start_date=is_start_str,
                end_date=is_end_str,
                setup_types=setup_types,
                ticker_df=ticker_df,
                spy_df=spy_df,
            )
            is_summary = await is_engine.run()
            is_trades_all.extend(is_summary.trades)

            # OOS period
            oos_engine = BacktestEngine(
                ticker=ticker,
                start_date=oos_start_str,
                end_date=oos_end_str,
                setup_types=setup_types,
                ticker_df=ticker_df,
                spy_df=spy_df,
            )
            oos_summary = await oos_engine.run()
            oos_trades_all.extend(oos_summary.trades)

        # ── Compute aggregate metrics ──────────────────────────────────────
        is_metrics  = _compute_wfo_metrics(is_trades_all,  min_trades)
        oos_metrics = _compute_wfo_metrics(oos_trades_all, min_trades)

        is_exp  = is_metrics.expectancy
        oos_exp = oos_metrics.expectancy
        stability_score = round(oos_exp / is_exp, 3) if is_exp > 0 else 0.0

        # ── Per-setup breakdown ────────────────────────────────────────────
        per_setup: Dict[str, dict] = {}
        for stype in setup_types:
            is_st  = [t for t in is_trades_all  if t.setup_type == stype]
            oos_st = [t for t in oos_trades_all if t.setup_type == stype]
            per_setup[stype] = {
                "is":  _compute_wfo_metrics(is_st,  min_trades).to_dict(),
                "oos": _compute_wfo_metrics(oos_st, min_trades).to_dict(),
            }

        result_windows.append(WFOWindowResult(
            window_num=window_num,
            is_start=is_start_str,
            is_end=is_end_str,
            oos_start=oos_start_str,
            oos_end=oos_end_str,
            is_metrics=is_metrics,
            oos_metrics=oos_metrics,
            stability_score=stability_score,
            per_setup=per_setup,
            is_trades=[t.to_dict() for t in is_trades_all],
            oos_trades=[t.to_dict() for t in oos_trades_all],
        ))

        if progress is not None:
            progress["windows_completed"] = window_num

        logger.info(
            "wfo [%s] window %d/%d: IS %d trades, OOS %d trades, stability=%.2f",
            run_id, window_num, len(windows),
            len(is_trades_all), len(oos_trades_all), stability_score,
        )

    return WFOResult(
        run_id=run_id,
        tickers=tickers,
        setup_types=setup_types,
        is_months=is_months,
        oos_months=oos_months,
        step_months=step_months,
        min_trades=min_trades,
        created_at=created_at,
        windows=result_windows,
    )
```

**Step 4: Run tests to confirm they pass**

```bash
cd backend
python -m pytest tests/test_wfo_engine.py -v
```

Expected: `7 passed`

**Step 5: Run full suite**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: all tests pass (286 + 7 = 293)

**Step 6: Commit**

```bash
git add backend/wfo_engine.py backend/tests/test_wfo_engine.py
git commit -m "feat(wfo): add WFO engine with rolling IS/OOS windows and metrics"
```

---

### Task 4: API Endpoints + DB Table

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/main.py`

**Context for implementer:**

Add `wfo_results` table to database.py and wire up 6 new API endpoints in main.py. No unit tests for the API layer — covered by running the full suite.

The `wfo_results` table stores a JSON blob per run (same pattern as `backtest_results`). In-memory dicts track download job progress and WFO run progress (same pattern as `_scan_state`).

**Download job flow:**
1. `POST /api/wfo/download` → validates body, ensures SPY in list, creates job_id, starts background thread (not async task — yf.download is synchronous), returns `{job_id}`
2. `GET /api/wfo/download-status/{job_id}` → polls `_wfo_download_jobs[job_id]`

**WFO run flow:**
1. `POST /api/wfo/run` → creates run_id, saves initial row to DB, starts background async task, returns `{run_id}`
2. `GET /api/wfo/status/{run_id}` → reads from DB + in-memory progress dict
3. `GET /api/wfo/results/{run_id}` → reads result_json from DB
4. `GET /api/wfo/export/{run_id}` → builds CSV from all trades across all windows, returns file download

---

**Step 1: Add `wfo_results` table to `database.py`**

Add the following SQL constant after `_CREATE_BACKTEST_RESULTS`:

```python
_CREATE_WFO_RESULTS = """
CREATE TABLE IF NOT EXISTS wfo_results (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT    NOT NULL UNIQUE,
    status            TEXT    NOT NULL DEFAULT 'running',
    progress_pct      INTEGER NOT NULL DEFAULT 0,
    windows_completed INTEGER NOT NULL DEFAULT 0,
    total_windows     INTEGER NOT NULL DEFAULT 0,
    result_json       TEXT,
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_WFO_INDEX = "CREATE INDEX IF NOT EXISTS idx_wfo_run_id ON wfo_results(run_id);"
```

Update `init_db()` to execute both:

```python
async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_SCAN_RUNS)
        await db.execute(_CREATE_MARKET_REGIME)
        await db.execute(_CREATE_SCAN_SETUPS)
        await db.execute(_CREATE_SR_ZONES)
        await db.execute(_CREATE_TRADES)
        await db.execute(_CREATE_BACKTEST_RESULTS)
        await db.execute(_BACKTEST_INDEX)
        await db.execute(_CREATE_WFO_RESULTS)      # ← new
        await db.execute(_WFO_INDEX)               # ← new
        for idx_sql in _INDEXES:
            await db.execute(idx_sql)
        await db.commit()
```

Add these four DB helper functions after the existing backtest helpers:

```python
async def create_wfo_run(db_path: str, run_id: str) -> None:
    """Insert initial wfo_results row with status='running'."""
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        await db.execute(
            "INSERT OR IGNORE INTO wfo_results (run_id, status) VALUES (?, ?)",
            (run_id, "running"),
        )
        await db.commit()


async def update_wfo_progress(
    db_path: str,
    run_id: str,
    progress_pct: int,
    windows_completed: int,
    total_windows: int,
) -> None:
    """Update progress columns on an existing wfo_results row."""
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        await db.execute(
            """
            UPDATE wfo_results
               SET progress_pct=?, windows_completed=?, total_windows=?
             WHERE run_id=?
            """,
            (progress_pct, windows_completed, total_windows, run_id),
        )
        await db.commit()


async def save_wfo_result(db_path: str, run_id: str, result_json: str) -> None:
    """Save completed WFO result JSON and mark status='done'."""
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        await db.execute(
            """
            UPDATE wfo_results
               SET status='done', progress_pct=100, result_json=?
             WHERE run_id=?
            """,
            (result_json, run_id),
        )
        await db.commit()


async def get_wfo_run(db_path: str, run_id: str) -> Optional[Dict]:
    """Fetch one wfo_results row. Returns None if not found."""
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM wfo_results WHERE run_id=?", (run_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
```

**Step 2: Add imports and state dicts to `main.py`**

At the top of `main.py`, add imports alongside existing imports:

```python
import json
import threading
```

(Check if `json` and `threading` are already imported — add only what's missing.)

Also add:
```python
from wfo_cache import download_and_cache, cache_exists as wfo_cache_exists
from wfo_engine import run_wfo
from database import (
    create_wfo_run, update_wfo_progress,
    save_wfo_result, get_wfo_run,
)
```

Add in-memory state dicts near the other `_scan_state` dict (around line 174):

```python
# WFO in-memory state
_wfo_download_jobs: Dict[str, Dict] = {}   # job_id → progress dict
_wfo_runs:          Dict[str, Dict] = {}   # run_id → progress dict
```

**Step 3: Add Pydantic models and 6 API endpoints**

Add these Pydantic models near the other `BacktestRequest` model:

```python
class WFODownloadRequest(BaseModel):
    tickers: List[str]

class WFORunRequest(BaseModel):
    tickers:     List[str]
    setup_types: List[str] = Field(
        default_factory=lambda: ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
    )
    is_months:   int = 24
    oos_months:  int = 3
    step_months: int = 3
    min_trades:  int = 20
```

Add the 6 endpoints (place them after the existing backtest endpoints):

```python
# ─────────────────────────────────────────────────────────────────────────────
# WFO Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/wfo/download")
async def wfo_download(req: WFODownloadRequest, background_tasks: BackgroundTasks):
    """
    Start a background download of 10-year OHLCV data for the requested tickers.
    SPY is added automatically. Returns {job_id} for polling.
    """
    tickers = [t.upper() for t in req.tickers]
    if "SPY" not in tickers:
        tickers = ["SPY"] + tickers

    job_id = str(uuid.uuid4())
    progress = {
        "status":            "running",
        "tickers_completed": 0,
        "total_tickers":     len(tickers),
    }
    _wfo_download_jobs[job_id] = progress

    def _run_download():
        try:
            download_and_cache(tickers, job_id, progress)
        except Exception as exc:
            progress["status"] = "error"
            log.exception("WFO download job %s failed: %s", job_id, exc)

    background_tasks.add_task(_run_download)
    return {"job_id": job_id, "total_tickers": len(tickers)}


@app.get("/api/wfo/download-status/{job_id}")
async def wfo_download_status(job_id: str):
    """Poll download job progress."""
    job = _wfo_download_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/wfo/run")
async def wfo_run(req: WFORunRequest, background_tasks: BackgroundTasks):
    """
    Start a walk-forward validation run in the background.
    Returns {run_id} for polling.
    """
    run_id = str(uuid.uuid4())
    progress = {"windows_completed": 0, "total_windows": 0}
    _wfo_runs[run_id] = progress

    await create_wfo_run(DB_PATH, run_id)

    async def _do_wfo():
        try:
            result = await run_wfo(
                tickers=req.tickers,
                setup_types=req.setup_types,
                is_months=req.is_months,
                oos_months=req.oos_months,
                step_months=req.step_months,
                min_trades=req.min_trades,
                run_id=run_id,
                progress=progress,
            )
            total = progress["total_windows"]
            for w in range(total):
                pct = int((w + 1) / total * 100) if total > 0 else 100
                await update_wfo_progress(
                    DB_PATH, run_id, pct,
                    progress["windows_completed"], total,
                )
            await save_wfo_result(DB_PATH, run_id, json.dumps(result.to_dict()))
            log.info("WFO run %s complete: %d windows", run_id, len(result.windows))
        except Exception as exc:
            log.exception("WFO run %s failed: %s", run_id, exc)

    background_tasks.add_task(_do_wfo)
    return {"run_id": run_id, "status": "started"}


@app.get("/api/wfo/status/{run_id}")
async def wfo_status(run_id: str):
    """Poll WFO run progress."""
    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    mem = _wfo_runs.get(run_id, {})
    return {
        "status":            row["status"],
        "progress_pct":      row["progress_pct"],
        "windows_completed": mem.get("windows_completed", row["windows_completed"]),
        "total_windows":     mem.get("total_windows",     row["total_windows"]),
    }


@app.get("/api/wfo/results/{run_id}")
async def wfo_results(run_id: str):
    """Return the full WFO result JSON."""
    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] != "done" or not row["result_json"]:
        return {"status": row["status"], "result": None}
    return {"status": "done", "result": json.loads(row["result_json"])}


@app.get("/api/wfo/export/{run_id}")
async def wfo_export(run_id: str):
    """Export full trade-level CSV for a completed WFO run."""
    from fastapi.responses import StreamingResponse
    import csv
    import io

    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] != "done" or not row["result_json"]:
        raise HTTPException(status_code=400, detail="Run not complete")

    result = json.loads(row["result_json"])

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "window_num", "period", "is_start", "is_end", "oos_start", "oos_end",
        "ticker", "setup_type", "signal_date", "entry_date", "entry_price",
        "initial_stop", "take_profit", "exit_date", "exit_price",
        "exit_reason", "holding_days", "rr_achieved", "pnl_pct", "is_win",
    ])

    for win in result["windows"]:
        base = [
            win["window_num"], "", win["is_start"], win["is_end"],
            win["oos_start"], win["oos_end"],
        ]
        for trade in win["is_trades"]:
            writer.writerow(base[:1] + ["IS"] + base[2:] + [
                trade["ticker"], trade["setup_type"], trade["signal_date"],
                trade["entry_date"], trade["entry_price"], trade["initial_stop"],
                trade["take_profit"], trade["exit_date"], trade["exit_price"],
                trade["exit_reason"], trade["holding_days"],
                trade["rr_achieved"], trade["pnl_pct"], trade["is_win"],
            ])
        for trade in win["oos_trades"]:
            writer.writerow(base[:1] + ["OOS"] + base[2:] + [
                trade["ticker"], trade["setup_type"], trade["signal_date"],
                trade["entry_date"], trade["entry_price"], trade["initial_stop"],
                trade["take_profit"], trade["exit_date"], trade["exit_price"],
                trade["exit_reason"], trade["holding_days"],
                trade["rr_achieved"], trade["pnl_pct"], trade["is_win"],
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wfo_{run_id}.csv"},
    )
```

**Step 4: Run full suite**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: all tests pass (293 passing)

**Step 5: Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "feat(wfo): add API endpoints, DB table, and CSV export"
```

---

### Task 5: Frontend Walk-Forward Tab

**Files:**
- Modify: `frontend/src/components/BacktestPanel.jsx`
- Modify: `frontend/src/api.js`

**Context for implementer:**

`BacktestPanel.jsx` currently has NO tabs — it's a single-view component. This task wraps the existing content in a "Replay" tab and adds a full "Walk-Forward" tab.

**Tab navigation:** Simple state variable `activeTab` (`"replay"` | `"wfo"`). Style matches existing dark dashboard aesthetic.

**Walk-Forward tab layout:**
1. Controls panel (ticker input, setup checkboxes, IS/OOS/Step fields, min trades, Download Cache button, Run Walk-Forward button, progress bar)
2. Results area with 3 view buttons: "Windows Table" (default), "IS/OOS Chart", "Heatmap"
3. Windows Table: one row per window; expandable row for per-setup breakdown
4. IS/OOS Chart: plain SVG bar chart — IS win rate (blue) vs OOS win rate (orange) per window
5. Heatmap: plain SVG grid — X=windows, Y=setup types, cell=OOS expectancy, color scale green→red

**Stability score coloring:**
- `stability >= 0.6` → normal text
- `stability < 0.6` → red text (overfitting warning)

**Unreliable windows** (trades < min_trades): row opacity 0.5, italicized.

**Polling:** After `POST /api/wfo/run`, poll `GET /api/wfo/status/{run_id}` every 3 seconds until status is `"done"`, then fetch results. Display progress bar using `progress_pct`.

---

**Step 1: Add WFO API functions to `api.js`**

Append to `frontend/src/api.js`:

```javascript
// ─── Walk-Forward Validation ─────────────────────────────────────────────────

export async function wfoDownload(tickers) {
  const res = await fetch('/api/wfo/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickers }),
  })
  return res.json()
}

export async function wfoDownloadStatus(jobId) {
  const res = await fetch(`/api/wfo/download-status/${jobId}`)
  return res.json()
}

export async function wfoRun(params) {
  const res = await fetch('/api/wfo/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return res.json()
}

export async function wfoStatus(runId) {
  const res = await fetch(`/api/wfo/status/${runId}`)
  return res.json()
}

export async function wfoResults(runId) {
  const res = await fetch(`/api/wfo/results/${runId}`)
  return res.json()
}

export function wfoExportUrl(runId) {
  return `/api/wfo/export/${runId}`
}
```

**Step 2: Replace `BacktestPanel.jsx` with tabbed version**

The implementer should read the current file first, then add:
1. `import { wfoDownload, wfoDownloadStatus, wfoRun, wfoStatus, wfoResults, wfoExportUrl } from '../api.js'`
2. `const [activeTab, setActiveTab] = useState('replay')` at the top of the component
3. Wrap existing JSX return in a tab container structure
4. Add the Walk-Forward tab JSX (see below)

Here is the complete Walk-Forward tab JSX to add (paste as a new `{activeTab === 'wfo' && (...)}` block):

```jsx
{activeTab === 'wfo' && (
  <WalkForwardTab />
)}
```

And the `WalkForwardTab` component (define above `BacktestPanel` in the same file):

```jsx
const WFO_SETUP_OPTIONS = ['VCP', 'PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE']

function WalkForwardTab() {
  const [tickerInput,   setTickerInput  ] = useState('')
  const [setupTypes,    setSetupTypes   ] = useState([...WFO_SETUP_OPTIONS])
  const [isMonths,      setIsMonths     ] = useState(24)
  const [oosMonths,     setOosMonths    ] = useState(3)
  const [stepMonths,    setStepMonths   ] = useState(3)
  const [minTrades,     setMinTrades    ] = useState(20)
  const [downloading,   setDownloading  ] = useState(false)
  const [dlStatus,      setDlStatus     ] = useState('')
  const [running,       setRunning      ] = useState(false)
  const [progressPct,   setProgressPct  ] = useState(0)
  const [status,        setStatus       ] = useState('')
  const [result,        setResult       ] = useState(null)   // WFOResult
  const [runId,         setRunId        ] = useState(null)
  const [viewMode,      setViewMode     ] = useState('table') // 'table'|'chart'|'heatmap'
  const [expanded,      setExpanded     ] = useState({})     // {window_num: bool}

  const parsedTickers = () =>
    tickerInput.split(',').map(t => t.trim().toUpperCase()).filter(Boolean)

  const toggleSetup = (s) => setSetupTypes(prev =>
    prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
  )

  // ── Download cache ──────────────────────────────────────────────────────────
  const handleDownload = async () => {
    const tickers = parsedTickers()
    if (tickers.length === 0) return
    setDownloading(true)
    setDlStatus('Starting download…')
    try {
      const { job_id, total_tickers } = await wfoDownload(tickers)
      setDlStatus(`Downloading ${total_tickers} tickers…`)
      const interval = setInterval(async () => {
        const st = await wfoDownloadStatus(job_id)
        setDlStatus(`Downloaded ${st.tickers_completed}/${st.total_tickers}`)
        if (st.status !== 'running') {
          clearInterval(interval)
          setDlStatus(`Download ${st.status === 'done' ? 'complete' : 'failed'} (${st.tickers_completed}/${st.total_tickers})`)
          setDownloading(false)
        }
      }, 2000)
    } catch {
      setDlStatus('Download error')
      setDownloading(false)
    }
  }

  // ── Run WFO ─────────────────────────────────────────────────────────────────
  const handleRun = async () => {
    const tickers = parsedTickers()
    if (tickers.length === 0 || setupTypes.length === 0) return
    setRunning(true)
    setProgressPct(0)
    setResult(null)
    setStatus('Starting walk-forward run…')
    try {
      const { run_id } = await wfoRun({
        tickers, setup_types: setupTypes,
        is_months: isMonths, oos_months: oosMonths,
        step_months: stepMonths, min_trades: minTrades,
      })
      setRunId(run_id)
      const interval = setInterval(async () => {
        const st = await wfoStatus(run_id)
        setProgressPct(st.progress_pct || 0)
        setStatus(`Window ${st.windows_completed}/${st.total_windows} (${st.progress_pct || 0}%)`)
        if (st.status === 'done') {
          clearInterval(interval)
          const res = await wfoResults(run_id)
          setResult(res.result)
          setStatus(`Complete — ${res.result?.windows?.length || 0} windows`)
          setRunning(false)
        } else if (st.status === 'error') {
          clearInterval(interval)
          setStatus('Run failed — check server logs')
          setRunning(false)
        }
      }, 3000)
    } catch {
      setStatus('Error starting run')
      setRunning(false)
    }
  }

  const inputStyle = {
    background: '#1a1a2e', color: '#e0e0e0', border: '1px solid #333',
    borderRadius: 4, padding: '4px 8px', fontSize: 13,
  }
  const btnStyle = (color='#2563eb', disabled=false) => ({
    background: disabled ? '#333' : color, color: '#fff', border: 'none',
    borderRadius: 4, padding: '6px 14px', cursor: disabled ? 'not-allowed' : 'pointer',
    fontSize: 13, opacity: disabled ? 0.6 : 1,
  })

  return (
    <div style={{ padding: 16, color: '#e0e0e0', fontFamily: 'monospace' }}>
      {/* Controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>TICKERS</div>
          <input
            style={{ ...inputStyle, width: 280 }}
            placeholder="AAPL, NVDA, MSFT, …"
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value)}
          />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>IS MONTHS</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={isMonths} onChange={e => setIsMonths(+e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>OOS MONTHS</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={oosMonths} onChange={e => setOosMonths(+e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>STEP MONTHS</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={stepMonths} onChange={e => setStepMonths(+e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>MIN TRADES</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={minTrades} onChange={e => setMinTrades(+e.target.value)} />
        </div>
      </div>

      {/* Setup type checkboxes */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        {WFO_SETUP_OPTIONS.map(s => (
          <label key={s} style={{ fontSize: 12, cursor: 'pointer' }}>
            <input type="checkbox" checked={setupTypes.includes(s)}
              onChange={() => toggleSetup(s)} style={{ marginRight: 4 }} />
            {s}
          </label>
        ))}
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'center' }}>
        <button style={btnStyle('#444', downloading)} onClick={handleDownload} disabled={downloading}>
          {downloading ? 'Downloading…' : 'Download Cache'}
        </button>
        <button style={btnStyle('#2563eb', running)} onClick={handleRun} disabled={running}>
          {running ? 'Running…' : 'Run Walk-Forward'}
        </button>
        {result && runId && (
          <a href={wfoExportUrl(runId)} download style={{ ...btnStyle('#166534'), textDecoration: 'none' }}>
            Export CSV
          </a>
        )}
      </div>

      {/* Status */}
      {dlStatus && <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{dlStatus}</div>}
      {status    && <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{status}</div>}

      {/* Progress bar */}
      {running && (
        <div style={{ background: '#1a1a2e', borderRadius: 4, height: 8, marginBottom: 12 }}>
          <div style={{ background: '#2563eb', width: `${progressPct}%`, height: '100%', borderRadius: 4, transition: 'width 0.3s' }} />
        </div>
      )}

      {/* View toggle */}
      {result && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          {[['table','Windows Table'],['chart','IS/OOS Chart'],['heatmap','Heatmap']].map(([v,label]) => (
            <button key={v} onClick={() => setViewMode(v)}
              style={btnStyle(viewMode === v ? '#2563eb' : '#333')}>
              {label}
            </button>
          ))}
        </div>
      )}

      {/* View: Windows Table */}
      {result && viewMode === 'table' && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#1a1a2e', color: '#888' }}>
                {['#','IS Period','OOS Period','IS WR%','OOS WR%','IS Avg R','OOS Avg R',
                  'IS Expect','OOS Expect','Stability','IS Trades','OOS Trades','✓'].map(h => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #333' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.windows.map(w => {
                const isRel    = w.is_metrics.reliable && w.oos_metrics.reliable
                const stabBad  = w.stability_score < 0.6
                const rowStyle = { opacity: isRel ? 1 : 0.5, fontStyle: isRel ? 'normal' : 'italic' }
                return [
                  <tr key={w.window_num} style={rowStyle}
                    onClick={() => setExpanded(prev => ({ ...prev, [w.window_num]: !prev[w.window_num] }))}
                    onMouseEnter={e => e.currentTarget.style.background='#1a2040'}
                    onMouseLeave={e => e.currentTarget.style.background=''}
                    style={{ ...rowStyle, cursor: 'pointer' }}>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.window_num}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: '#888' }}>{w.is_start.slice(0,7)}→{w.is_end.slice(0,7)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: '#888' }}>{w.oos_start.slice(0,7)}→{w.oos_end.slice(0,7)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.win_rate.toFixed(1)}%</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.win_rate.toFixed(1)}%</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.avg_r.toFixed(2)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.avg_r.toFixed(2)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.expectancy.toFixed(3)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.expectancy.toFixed(3)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: stabBad ? '#ef4444' : '#4ade80', fontWeight: stabBad ? 700 : 400 }}>
                      {w.stability_score.toFixed(2)}
                    </td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.trades}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.trades}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: isRel ? '#4ade80' : '#f59e0b' }}>{isRel ? '✓' : '!'}</td>
                  </tr>,
                  expanded[w.window_num] && (
                    <tr key={`${w.window_num}-detail`}>
                      <td colSpan={13} style={{ padding: '8px 16px', background: '#111', borderBottom: '1px solid #333' }}>
                        <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ color: '#888' }}>
                              <th style={{ textAlign: 'left', padding: '3px 6px' }}>Setup</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>IS Trades</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>OOS Trades</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>IS WR%</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>OOS WR%</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>IS Expect</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>OOS Expect</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(w.per_setup).map(([stype, d]) => (
                              <tr key={stype}>
                                <td style={{ padding: '3px 6px', color: '#60a5fa' }}>{stype}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.is.trades}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.oos.trades}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.is.win_rate.toFixed(1)}%</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.oos.win_rate.toFixed(1)}%</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.is.expectancy.toFixed(3)}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.oos.expectancy.toFixed(3)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )
                ]
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* View: IS/OOS Bar Chart */}
      {result && viewMode === 'chart' && (
        <WFOBarChart windows={result.windows} />
      )}

      {/* View: Heatmap */}
      {result && viewMode === 'heatmap' && (
        <WFOHeatmap windows={result.windows} setupTypes={result.setup_types} />
      )}
    </div>
  )
}


function WFOBarChart({ windows }) {
  const W = 28, GAP = 4, H = 160, PAD = { top: 10, bottom: 30, left: 40, right: 10 }
  const totalW = windows.length * (W * 2 + GAP + 6) + PAD.left + PAD.right

  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>IS Win Rate (blue) vs OOS Win Rate (orange) per window</div>
      <svg width={totalW} height={H + PAD.top + PAD.bottom} style={{ fontFamily: 'monospace' }}>
        {/* Y axis */}
        {[0, 25, 50, 75, 100].map(pct => {
          const y = PAD.top + H - (pct / 100) * H
          return (
            <g key={pct}>
              <line x1={PAD.left - 4} x2={totalW - PAD.right} y1={y} y2={y}
                stroke="#333" strokeWidth={pct === 0 ? 1 : 0.5} />
              <text x={PAD.left - 8} y={y + 4} textAnchor="end" fill="#888" fontSize={9}>{pct}%</text>
            </g>
          )
        })}
        {windows.map((w, i) => {
          const x0 = PAD.left + i * (W * 2 + GAP + 6)
          const isH  = (w.is_metrics.win_rate / 100) * H
          const oosH = (w.oos_metrics.win_rate / 100) * H
          return (
            <g key={w.window_num}>
              {/* IS bar */}
              <rect x={x0} y={PAD.top + H - isH} width={W} height={isH} fill="#2563eb" opacity={0.85} />
              {/* OOS bar */}
              <rect x={x0 + W + 2} y={PAD.top + H - oosH} width={W} height={oosH} fill="#f97316" opacity={0.85} />
              {/* X label */}
              <text x={x0 + W} y={PAD.top + H + 16} textAnchor="middle" fill="#888" fontSize={9}>{w.window_num}</text>
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: '#888', marginTop: 4 }}>
        <span><span style={{ color: '#2563eb' }}>■</span> IS Win Rate</span>
        <span><span style={{ color: '#f97316' }}>■</span> OOS Win Rate</span>
      </div>
    </div>
  )
}


function WFOHeatmap({ windows, setupTypes }) {
  const CELL_W = 32, CELL_H = 24

  function expectancyToColor(v) {
    if (v >= 0.5)  return '#166534'   // strong green
    if (v >= 0.2)  return '#15803d'
    if (v >= 0.0)  return '#4ade80'   // light green
    if (v >= -0.2) return '#fbbf24'   // yellow
    if (v >= -0.5) return '#ef4444'   // red
    return '#7f1d1d'                  // deep red
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>OOS Expectancy by Setup × Window (green=positive, red=negative)</div>
      <div style={{ display: 'flex' }}>
        {/* Y-axis labels */}
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-around', paddingRight: 8, paddingTop: 20 }}>
          {setupTypes.map(s => (
            <div key={s} style={{ height: CELL_H, lineHeight: `${CELL_H}px`, fontSize: 10, color: '#888', whiteSpace: 'nowrap' }}>{s}</div>
          ))}
        </div>
        <div>
          {/* X-axis labels */}
          <div style={{ display: 'flex' }}>
            {windows.map(w => (
              <div key={w.window_num} style={{ width: CELL_W, textAlign: 'center', fontSize: 9, color: '#666' }}>{w.window_num}</div>
            ))}
          </div>
          {/* Grid */}
          {setupTypes.map(stype => (
            <div key={stype} style={{ display: 'flex' }}>
              {windows.map(w => {
                const exp = w.per_setup?.[stype]?.oos?.expectancy ?? 0
                return (
                  <div key={w.window_num} title={`${stype} W${w.window_num}: ${exp.toFixed(3)}`}
                    style={{
                      width: CELL_W, height: CELL_H,
                      background: expectancyToColor(exp),
                      border: '1px solid #111',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 8, color: '#fff',
                    }}>
                    {Math.abs(exp) > 0.05 ? exp.toFixed(2) : ''}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
```

**Step 3: Add tab navigation to `BacktestPanel`**

At the top of the `BacktestPanel` component (after the existing state declarations), add:

```jsx
const [activeTab, setActiveTab] = useState('replay')
```

Wrap the existing return JSX in:

```jsx
return (
  <div>
    {/* Tab navigation */}
    <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #333', marginBottom: 12 }}>
      {[['replay','Replay'],['wfo','Walk-Forward']].map(([id, label]) => (
        <button key={id} onClick={() => setActiveTab(id)}
          style={{
            background: activeTab === id ? '#1a2040' : 'transparent',
            color: activeTab === id ? '#60a5fa' : '#888',
            border: 'none', borderBottom: activeTab === id ? '2px solid #2563eb' : '2px solid transparent',
            padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontFamily: 'monospace',
          }}>
          {label}
        </button>
      ))}
    </div>

    {activeTab === 'replay' && (
      <div>
        {/* ← paste all of the original BacktestPanel return content here */}
      </div>
    )}

    {activeTab === 'wfo' && <WalkForwardTab />}
  </div>
)
```

**Step 4: Verify the frontend builds**

```bash
cd frontend
npm run build
```

Expected: build succeeds with no errors.

**Step 5: Run backend test suite one final time**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: 293 tests pass.

**Step 6: Commit**

```bash
git add frontend/src/api.js frontend/src/components/BacktestPanel.jsx
git commit -m "feat(wfo): add Walk-Forward tab to BacktestPanel with table, chart, and heatmap views"
```

---

## Summary

| Task | New Files | Modified Files | Tests Added |
|------|-----------|---------------|-------------|
| 1 — Cache layer | `wfo_cache.py`, `data/price_cache/.gitkeep` | `requirements.txt`, `constants.py`, `.gitignore` | 8 |
| 2 — Preloaded DF | — | `backtest_engine.py` | 3 |
| 3 — WFO engine | `wfo_engine.py` | — | 7 |
| 4 — API + DB | — | `database.py`, `main.py` | 0 |
| 5 — Frontend | — | `BacktestPanel.jsx`, `api.js` | 0 |

**Total new tests: 18** (293 total expected after all tasks)
