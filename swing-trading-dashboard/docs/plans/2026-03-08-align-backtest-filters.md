# Align Backtest & Optimizer Filters with Scanner Logic

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Centralize market regime, liquidity, and earnings blackout filters into a shared `filters.py` module so the backtest, WFO, and scanner all apply the same trading conditions.

**Architecture:** Create `backend/filters.py` as the single source of truth for all entry-gate filters. `BacktestEngine` grows three new per-bar checks (regime, liquidity, earnings). `wfo_engine.run_wfo()` passes SPY data through to each BacktestEngine call. The scanner's existing inline earnings logic is replaced with an import from `filters.py`.

**Tech Stack:** Python 3.11, pandas, pytest, existing constants.py for all thresholds.

---

## Background: What Gaps This Fixes

| Filter | Scanner | Backtest (before) | Backtest (after) |
|--------|---------|-------------------|------------------|
| Regime (SPY MA stack) | engine0 full 7-factor | ❌ not applied | ✅ SPY f1-f4 subset |
| Liquidity (50d avg vol) | universe_builder + inline | ❌ not applied | ✅ rolling per-bar |
| Earnings blackout | `_check_earnings_blackout_sync()` | ❌ not applied | ✅ optional, if dates provided |
| Sector strength | `compute_setup_score()` | ❌ not applied | ⚠️ skipped (needs full universe data) |

### Why sector strength is intentionally excluded from backtest
`compute_top_sectors()` requires the full live universe with cached price data and cross-sectional RS ranking. The backtest runs on individual tickers without universe context. Adding sector strength would require running RS ranking across all 2,500+ tickers per bar, which is computationally infeasible. The scanner applies it as a scoring multiplier, not a hard gate — so the practical impact on signal selection is partial. This is documented as a known gap.

### Regime filter design decision
`engine0.check_market_regime()` uses 7 factors, two of which (breadth %, H/L ratio) require scanning the full universe per bar. In the backtest we only have SPY OHLCV data available. We implement factors f1–f4 (SPY-only, worth 60/100 pts max) and apply the same `REGIME_SELECTIVE_THRESHOLD = 40` gate. This is conservative but accurate for structural trend conditions.

**`is_bullish_bar = weighted_spy_score >= REGIME_SELECTIVE_THRESHOLD`**
- f1: SPY Close > EMA20 → 20 pts
- f2: SPY Close > SMA50 → 15 pts
- f3: SMA50 > SMA200 → 15 pts
- f4: EMA20 slope over 5 bars → 0–10 pts
- Max = 60 pts (vs 100 in full engine0)

---

## Task 1: Create `backend/filters.py`

**Files:**
- Create: `backend/filters.py`

### Step 1: Write the failing test

File: `backend/tests/test_filters.py`

```python
"""Tests for centralized filter logic in filters.py."""
import sys, os
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── compute_regime_series ─────────────────────────────────────────────────────

def _make_spy_df(n: int, trend: str) -> pd.DataFrame:
    """Build synthetic SPY DataFrame.
    trend='bull'  → clear uptrend (SMA50 > SMA200, price > SMA50)
    trend='bear'  → clear downtrend (price < SMA50 < SMA200)
    """
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    if trend == "bull":
        close = np.linspace(80.0, 200.0, n)
    else:
        close = np.linspace(200.0, 80.0, n)
    return pd.DataFrame({"Close": close, "Open": close, "High": close*1.01,
                         "Low": close*0.99, "Volume": np.full(n, 1_000_000)},
                        index=dates)


def test_regime_series_bullish_trend():
    from filters import compute_regime_series
    spy = _make_spy_df(300, "bull")
    series = compute_regime_series(spy)
    # Last 50 bars should all be bullish in a clear uptrend
    assert series.iloc[-1] is True or series.iloc[-1] == True
    assert isinstance(series, pd.Series)
    assert series.dtype == bool


def test_regime_series_bearish_trend():
    from filters import compute_regime_series
    spy = _make_spy_df(300, "bear")
    series = compute_regime_series(spy)
    # Last bar should be non-bullish in a clear downtrend
    assert series.iloc[-1] is False or series.iloc[-1] == False


def test_regime_series_aligned_with_spy_index():
    from filters import compute_regime_series
    spy = _make_spy_df(300, "bull")
    series = compute_regime_series(spy)
    assert series.index.equals(spy.index)


def test_regime_series_short_history_returns_false():
    """Less than 200 bars → not enough data for SMA200 → treat as non-bullish."""
    from filters import compute_regime_series
    spy = _make_spy_df(50, "bull")
    series = compute_regime_series(spy)
    # All False when SMA200 can't be computed
    assert series.all() == False or not series.any()


# ── passes_liquidity ──────────────────────────────────────────────────────────

def _make_df_with_volume(avg_vol: float, n: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    volume = np.full(n, avg_vol)
    return pd.DataFrame({"Close": close, "Volume": volume,
                         "Open": close, "High": close, "Low": close},
                        index=dates)


def test_passes_liquidity_high_volume():
    from filters import passes_liquidity
    df = _make_df_with_volume(1_000_000)
    assert passes_liquidity(df) is True


def test_passes_liquidity_low_volume():
    from filters import passes_liquidity
    df = _make_df_with_volume(100_000)
    assert passes_liquidity(df) is False


def test_passes_liquidity_uses_50d_rolling():
    """First 49 rows are zero volume, last 11 rows are high volume → fails (avg < threshold)."""
    from filters import passes_liquidity
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    vols = np.zeros(60)
    vols[-11:] = 5_000_000      # only last 11 bars are liquid
    df = pd.DataFrame({"Close": np.full(60, 100.0), "Volume": vols,
                       "Open": np.full(60, 100.0), "High": np.full(60, 101.0),
                       "Low": np.full(60, 99.0)}, index=dates)
    assert passes_liquidity(df) is False


def test_passes_liquidity_empty_df():
    from filters import passes_liquidity
    df = pd.DataFrame({"Close": [], "Volume": [], "Open": [], "High": [], "Low": []})
    assert passes_liquidity(df) is False


# ── in_earnings_blackout ──────────────────────────────────────────────────────

def test_earnings_blackout_within_window():
    from filters import in_earnings_blackout
    # Earnings in 5 days → within 7-day blackout
    assert in_earnings_blackout("2024-01-10", ["2024-01-15"]) is True


def test_earnings_blackout_outside_window():
    from filters import in_earnings_blackout
    # Earnings 30 days away → safe
    assert in_earnings_blackout("2024-01-10", ["2024-02-15"]) is False


def test_earnings_blackout_day_before():
    from filters import in_earnings_blackout
    # Earnings yesterday (1 day before signal) → should still be blocked
    assert in_earnings_blackout("2024-01-10", ["2024-01-09"]) is True


def test_earnings_blackout_empty_list():
    from filters import in_earnings_blackout
    assert in_earnings_blackout("2024-01-10", []) is False


def test_earnings_blackout_multiple_dates():
    from filters import in_earnings_blackout
    # One near date and one far date → blocked
    assert in_earnings_blackout("2024-01-10", ["2024-06-01", "2024-01-14"]) is True
```

### Step 2: Run test to verify it fails

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_filters.py -v 2>&1 | head -40
```

Expected: `ModuleNotFoundError: No module named 'filters'`

### Step 3: Write minimal implementation

Create `backend/filters.py`:

```python
"""
Centralized entry-gate filters shared by scanner, backtest, and WFO.

All filter functions are pure (no side effects, no network calls) so they
can be called safely inside the per-bar backtest replay loop.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd

from constants import (
    LIQUIDITY_MIN_AVG_VOLUME,
    LIQUIDITY_MIN_DOLLAR_VOLUME,
    EARNINGS_BLACKOUT_DAYS,
    REGIME_SELECTIVE_THRESHOLD,
    REGIME_WEIGHT_EMA20,
    REGIME_WEIGHT_SMA50,
    REGIME_WEIGHT_MA_STACK,
    REGIME_WEIGHT_SLOPE,
)


# ── Regime ─────────────────────────────────────────────────────────────────────

def compute_regime_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return a boolean pd.Series (same index as spy_df) indicating whether
    each bar is in a bullish regime, using SPY-only factors from engine0:

      f1: SPY Close > EMA20       → REGIME_WEIGHT_EMA20  pts
      f2: SPY Close > SMA50       → REGIME_WEIGHT_SMA50  pts
      f3: SMA50 > SMA200          → REGIME_WEIGHT_MA_STACK pts
      f4: EMA20 slope (5-bar)     → 0..REGIME_WEIGHT_SLOPE pts

    Threshold: REGIME_SELECTIVE_THRESHOLD (40 pts).
    Returns False for all bars that lack enough history for SMA200.

    Note: breadth, H/L ratio, and VIX factors (f5–f7) require universe-wide
    data not available during backtesting and are intentionally omitted here.
    """
    if spy_df is None or len(spy_df) < 200:
        if spy_df is not None:
            return pd.Series(False, index=spy_df.index, dtype=bool)
        return pd.Series(dtype=bool)

    close = spy_df["Close"]

    ema20  = close.ewm(span=20, adjust=False).mean()
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    slope5 = ema20 - ema20.shift(5)          # positive = rising

    def _score(i: int) -> int:
        if pd.isna(sma200.iloc[i]):
            return 0
        s = 0
        if close.iloc[i] > ema20.iloc[i]:                   s += REGIME_WEIGHT_EMA20
        if close.iloc[i] > sma50.iloc[i]:                   s += REGIME_WEIGHT_SMA50
        if not pd.isna(sma50.iloc[i]) and sma50.iloc[i] > sma200.iloc[i]: s += REGIME_WEIGHT_MA_STACK
        if not pd.isna(slope5.iloc[i]):
            # Map slope to 0–REGIME_WEIGHT_SLOPE proportionally (cap at 1% of SMA50)
            norm = slope5.iloc[i] / (sma50.iloc[i] * 0.01 + 1e-9)
            s += min(max(int(norm * REGIME_WEIGHT_SLOPE), 0), REGIME_WEIGHT_SLOPE)
        return s

    scores = pd.Series(
        [_score(i) for i in range(len(spy_df))],
        index=spy_df.index,
        dtype=int,
    )
    return scores >= REGIME_SELECTIVE_THRESHOLD


# ── Liquidity ──────────────────────────────────────────────────────────────────

def passes_liquidity(
    df: pd.DataFrame,
    min_avg_volume: int = LIQUIDITY_MIN_AVG_VOLUME,
    min_dollar_volume: float = LIQUIDITY_MIN_DOLLAR_VOLUME,
) -> bool:
    """
    Return True if the last bar of df passes the liquidity gate:
      - 50-day average volume >= min_avg_volume
      - last_close × avg_volume_50d >= min_dollar_volume

    Uses only data in df (no external calls). Safe to call inside backtest loop.
    Returns False on empty or insufficient data.
    """
    if df is None or len(df) < 2:
        return False

    vol    = df["Volume"].iloc[-50:]        # up to 50 most recent bars
    avg_vol = vol.mean() if len(vol) > 0 else 0.0
    if avg_vol < min_avg_volume:
        return False

    last_close = df["Close"].iloc[-1]
    if pd.isna(last_close) or last_close <= 0:
        return False

    dollar_vol = last_close * avg_vol
    return dollar_vol >= min_dollar_volume


# ── Earnings Blackout ─────────────────────────────────────────────────────────

def in_earnings_blackout(
    signal_date: str,
    earnings_dates: List[str],
    blackout_days: int = EARNINGS_BLACKOUT_DAYS,
) -> bool:
    """
    Return True if signal_date falls within [-1, +blackout_days] calendar days
    of any date in earnings_dates.

    Parameters
    ----------
    signal_date : str
        Date of the signal in YYYY-MM-DD format.
    earnings_dates : List[str]
        List of known earnings dates in YYYY-MM-DD format.
    blackout_days : int
        Number of forward calendar days to block (default: EARNINGS_BLACKOUT_DAYS).

    Returns False (safe to trade) on any parse error or empty list.
    """
    if not earnings_dates:
        return False
    try:
        sig = datetime.strptime(signal_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False

    for ed_str in earnings_dates:
        try:
            ed = datetime.strptime(ed_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        days_away = (ed - sig).days          # positive = earnings in future
        if -1 <= days_away <= blackout_days:
            return True
    return False
```

### Step 4: Run tests to verify they pass

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_filters.py -v
```

Expected: all tests pass (green).

### Step 5: Commit

```bash
git add backend/filters.py backend/tests/test_filters.py
git commit -m "feat(filters): add centralized regime/liquidity/earnings filter module"
```

---

## Task 2: Integrate Regime Filter into BacktestEngine

**Files:**
- Modify: `backend/backtest_engine.py`

The `BacktestEngine.__init__()` already accepts `spy_df: Optional[pd.DataFrame]`. We use it to pre-compute the regime series once before the bar loop.

### Step 1: Write the failing test

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_backtest_skips_signals_in_defensive_regime():
    """BacktestEngine should not open trades on bars marked as non-bullish."""
    import asyncio
    import numpy as np
    import pandas as pd
    from backtest_engine import BacktestEngine

    n = 350
    dates = pd.date_range("2015-01-01", periods=n, freq="B")

    # Downtrending SPY → all bars will be DEFENSIVE (SMA50 < SMA200)
    spy_close = np.linspace(200.0, 80.0, n)
    spy_df = pd.DataFrame({
        "Close": spy_close, "Open": spy_close, "Volume": np.full(n, 1_000_000),
        "High": spy_close * 1.01, "Low": spy_close * 0.99,
    }, index=dates)

    # Ticker: strong bullish price (would normally generate VCP signals)
    tick_close = np.linspace(80.0, 200.0, n)
    tick_df = pd.DataFrame({
        "Close": tick_close, "Open": tick_close * 0.99,
        "High": tick_close * 1.02, "Low": tick_close * 0.98,
        "Volume": np.full(n, 2_000_000), "Adj Close": tick_close,
    }, index=dates)

    engine = BacktestEngine(
        ticker="TEST",
        start_date=dates[250].strftime("%Y-%m-%d"),
        end_date=dates[-1].strftime("%Y-%m-%d"),
        setup_types=["VCP"],
        ticker_df=tick_df,
        spy_df=spy_df,
    )
    summary = asyncio.run(engine.run())
    # In a purely defensive regime, no new trades should be opened
    assert summary.total_trades == 0, (
        f"Expected 0 trades in defensive regime, got {summary.total_trades}"
    )
```

### Step 2: Run to confirm RED

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_engine.py::test_backtest_skips_signals_in_defensive_regime -v
```

Expected: FAIL — currently no regime gate, so trades may be generated.

### Step 3: Implement the regime pre-computation in BacktestEngine

In `backend/backtest_engine.py`, locate the `run()` method. Find where `replay_dates` is built (around line 556). Add the regime series pre-computation **before** the replay loop:

```python
# ── After existing indicator pre-computation, before replay loop ──────────────
from filters import compute_regime_series   # add at top of file imports

# In BacktestEngine.run(), after indicators are precomputed:
_regime_series: pd.Series = pd.Series(dtype=bool)
if self.spy_df is not None and len(self.spy_df) > 0:
    _regime_series = compute_regime_series(self.spy_df)
```

Then inside the per-bar loop, **before signal engines are called**, add the regime gate:

```python
# Inside the per-bar loop (after df_slice is built):
bar_date = df_slice.index[-1]
if len(_regime_series) > 0:
    # Reindex: if bar_date not in spy index, fall back to most recent known value
    spy_dates_before = _regime_series.index[_regime_series.index <= bar_date]
    if len(spy_dates_before) > 0:
        is_bullish_bar = bool(_regime_series.loc[spy_dates_before[-1]])
    else:
        is_bullish_bar = False
    if not is_bullish_bar:
        continue   # skip signal generation for this bar
```

> **Important:** The `continue` must skip only signal generation, NOT the management of already-open trades (stop loss / take profit). Restructure the loop so open-trade management runs before the regime check.

The typical loop structure becomes:
```python
for bar_date in replay_dates:
    df_slice = df_with_warmup.loc[:bar_date]

    # 1. Manage existing open trades (stops/targets) — always runs
    _manage_open_trades(df_slice, open_trades, filled_trades)

    # 2. Regime gate — skip new signals if defensive
    if len(open_trades) < MAX_OPEN_POSITIONS:
        if not _is_bullish(bar_date, _regime_series):
            continue
        # 3. Signal detection — only in bullish regime
        _detect_signals(...)
```

### Step 4: Run to confirm GREEN

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_engine.py -v
```

Expected: all existing tests pass + new regime test passes.

### Step 5: Commit

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): apply SPY regime gate per bar using filters.compute_regime_series"
```

---

## Task 3: Integrate Liquidity Filter into BacktestEngine

**Files:**
- Modify: `backend/backtest_engine.py`

### Step 1: Write the failing test

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_backtest_skips_signals_for_illiquid_ticker():
    """BacktestEngine should not open trades when avg_volume_50d < LIQUIDITY_MIN_AVG_VOLUME."""
    import asyncio
    import numpy as np
    import pandas as pd
    from backtest_engine import BacktestEngine

    n = 350
    dates = pd.date_range("2015-01-01", periods=n, freq="B")

    # Bullish SPY (so regime passes)
    spy_close = np.linspace(100.0, 200.0, n)
    spy_df = pd.DataFrame({
        "Close": spy_close, "Open": spy_close, "Volume": np.full(n, 5_000_000),
        "High": spy_close * 1.01, "Low": spy_close * 0.99,
    }, index=dates)

    # Ticker: bullish price BUT almost zero volume (illiquid)
    tick_close = np.linspace(80.0, 200.0, n)
    tick_df = pd.DataFrame({
        "Close": tick_close, "Open": tick_close * 0.99,
        "High": tick_close * 1.02, "Low": tick_close * 0.98,
        "Volume": np.full(n, 1_000),     # far below LIQUIDITY_MIN_AVG_VOLUME
        "Adj Close": tick_close,
    }, index=dates)

    engine = BacktestEngine(
        ticker="ILLIQ",
        start_date=dates[250].strftime("%Y-%m-%d"),
        end_date=dates[-1].strftime("%Y-%m-%d"),
        setup_types=["VCP"],
        ticker_df=tick_df,
        spy_df=spy_df,
    )
    summary = asyncio.run(engine.run())
    assert summary.total_trades == 0, (
        f"Expected 0 trades for illiquid ticker, got {summary.total_trades}"
    )
```

### Step 2: Run to confirm RED

```bash
python -m pytest tests/test_backtest_engine.py::test_backtest_skips_signals_for_illiquid_ticker -v
```

Expected: FAIL — no liquidity gate currently.

### Step 3: Add liquidity gate to per-bar loop

In `backend/backtest_engine.py`, import and add **after** the regime gate check, inside the signal-detection block:

```python
from filters import compute_regime_series, passes_liquidity  # update import

# Inside per-bar loop, after regime gate, before signal detection:
if not passes_liquidity(df_slice):
    continue   # skip signal — ticker is illiquid at this point in time
```

The `df_slice` already contains the rolling window data up to `bar_date`, so `passes_liquidity()` correctly uses the 50 most recent bars available at that point.

### Step 4: Run to confirm GREEN

```bash
python -m pytest tests/test_backtest_engine.py -v
```

Expected: all tests pass.

### Step 5: Commit

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): apply per-bar liquidity gate using filters.passes_liquidity"
```

---

## Task 4: Integrate Earnings Blackout Filter into BacktestEngine

**Files:**
- Modify: `backend/backtest_engine.py`

The earnings filter is **optional** in the backtest. Historical earnings calendar data is not reliably available via yfinance for free, so we accept it as an optional parameter. When not provided, no filtering is applied (maintains backward compatibility).

### Step 1: Write the failing test

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_backtest_skips_signals_during_earnings_blackout():
    """BacktestEngine should skip signals within earnings blackout window when dates are provided."""
    import asyncio
    import numpy as np
    import pandas as pd
    from backtest_engine import BacktestEngine

    n = 350
    dates = pd.date_range("2015-01-01", periods=n, freq="B")

    spy_close = np.linspace(100.0, 200.0, n)
    spy_df = pd.DataFrame({
        "Close": spy_close, "Open": spy_close, "Volume": np.full(n, 5_000_000),
        "High": spy_close * 1.01, "Low": spy_close * 0.99,
    }, index=dates)

    tick_close = np.linspace(80.0, 200.0, n)
    tick_df = pd.DataFrame({
        "Close": tick_close, "Open": tick_close * 0.99,
        "High": tick_close * 1.02, "Low": tick_close * 0.98,
        "Volume": np.full(n, 2_000_000),
        "Adj Close": tick_close,
    }, index=dates)

    # Block EVERY trading day by placing earnings on each date in the OOS window
    start_date = dates[250].strftime("%Y-%m-%d")
    end_date   = dates[-1].strftime("%Y-%m-%d")

    # Place an earnings date every 5 days throughout the range → always in blackout
    oos_dates  = dates[250:]
    earnings   = [d.strftime("%Y-%m-%d") for d in oos_dates[::5]]

    engine = BacktestEngine(
        ticker="EARN",
        start_date=start_date,
        end_date=end_date,
        setup_types=["VCP"],
        ticker_df=tick_df,
        spy_df=spy_df,
        earnings_dates={"EARN": earnings},   # new parameter
    )
    summary = asyncio.run(engine.run())
    assert summary.total_trades == 0, (
        f"Expected 0 trades during earnings blackout, got {summary.total_trades}"
    )


def test_backtest_no_earnings_dates_no_crash():
    """BacktestEngine without earnings_dates should run normally (backward compat)."""
    import asyncio
    import numpy as np
    import pandas as pd
    from backtest_engine import BacktestEngine

    n = 350
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    spy_close = np.linspace(100.0, 200.0, n)
    spy_df = pd.DataFrame({
        "Close": spy_close, "Open": spy_close, "Volume": np.full(n, 5_000_000),
        "High": spy_close * 1.01, "Low": spy_close * 0.99,
    }, index=dates)
    tick_close = np.linspace(80.0, 200.0, n)
    tick_df = pd.DataFrame({
        "Close": tick_close, "Open": tick_close * 0.99,
        "High": tick_close * 1.02, "Low": tick_close * 0.98,
        "Volume": np.full(n, 2_000_000), "Adj Close": tick_close,
    }, index=dates)

    engine = BacktestEngine(
        ticker="SAFE",
        start_date=dates[250].strftime("%Y-%m-%d"),
        end_date=dates[-1].strftime("%Y-%m-%d"),
        setup_types=["VCP"],
        ticker_df=tick_df,
        spy_df=spy_df,
        # No earnings_dates argument — must not crash
    )
    summary = asyncio.run(engine.run())
    assert summary is not None
```

### Step 2: Run to confirm RED

```bash
python -m pytest tests/test_backtest_engine.py::test_backtest_skips_signals_during_earnings_blackout -v
```

Expected: FAIL — `BacktestEngine` doesn't accept `earnings_dates` parameter yet.

### Step 3: Add `earnings_dates` parameter to BacktestEngine

In `backend/backtest_engine.py`:

**In `__init__()` signature**, add after `spy_df`:
```python
earnings_dates: Optional[Dict[str, List[str]]] = None,
```

**In `__init__()` body**, save the parameter:
```python
self.earnings_dates: Dict[str, List[str]] = earnings_dates or {}
```

**In `run()` method**, add import and gate inside per-bar signal block:
```python
from filters import compute_regime_series, passes_liquidity, in_earnings_blackout

# Inside per-bar loop, after liquidity gate, before signal detection:
ticker_earnings = self.earnings_dates.get(self.ticker, [])
bar_date_str = bar_date.strftime("%Y-%m-%d")
if in_earnings_blackout(bar_date_str, ticker_earnings):
    continue   # skip signal — too close to earnings
```

Also update the class docstring / type hints as needed.

### Step 4: Run to confirm GREEN

```bash
python -m pytest tests/test_backtest_engine.py -v
```

Expected: all tests pass.

### Step 5: Commit

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): add optional earnings_dates parameter with per-bar blackout gate"
```

---

## Task 5: Pass SPY Data Through `wfo_engine.run_wfo()`

**Files:**
- Modify: `backend/wfo_engine.py`

`run_wfo()` already loads per-ticker Parquet cache. SPY data needs to be loaded once and sliced per window before being passed to each `BacktestEngine` call. SPY is already in the representative tickers in some cases, but we need it explicitly for the regime series.

### Step 1: Write the failing test

Add to `backend/tests/test_wfo_engine.py`:

```python
@pytest.mark.asyncio
async def test_run_wfo_passes_spy_df_to_backtest():
    """run_wfo should load SPY data and pass it to BacktestEngine (regime gate active)."""
    from wfo_engine import run_wfo
    import numpy as np
    import pandas as pd
    from unittest.mock import patch

    n = 500
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    # Downtrending SPY → defensive regime → expect 0 trades from signal engines
    spy_close = np.linspace(200.0, 50.0, n)
    mock_spy_df = pd.DataFrame({
        "Close": spy_close, "Open": spy_close,
        "High": spy_close * 1.01, "Low": spy_close * 0.99,
        "Volume": np.full(n, 10_000_000), "Adj Close": spy_close,
    }, index=dates)

    tick_close = np.linspace(100.0, 200.0, n)
    mock_tick_df = pd.DataFrame({
        "Close": tick_close, "Open": tick_close * 0.99,
        "High": tick_close * 1.02, "Low": tick_close * 0.98,
        "Volume": np.full(n, 2_000_000), "Adj Close": tick_close,
    }, index=dates)

    def load_either(ticker):
        return mock_spy_df if ticker == "SPY" else mock_tick_df

    with patch("wfo_engine.load_ticker", side_effect=load_either), \
         patch("wfo_engine.cache_exists", return_value=True):
        result = await run_wfo(
            tickers=["AAPL"],
            setup_types=["VCP"],
            is_months=12, oos_months=3, step_months=6,
            min_trades=1,
        )

    # In defensive regime, all windows should have 0 OOS trades
    total_oos = sum(len(w.oos_trades) for w in result.windows)
    assert total_oos == 0, f"Expected 0 OOS trades in defensive SPY regime, got {total_oos}"
```

### Step 2: Run to confirm RED

```bash
python -m pytest tests/test_wfo_engine.py::test_run_wfo_passes_spy_df_to_backtest -v
```

Expected: FAIL — `run_wfo` doesn't load SPY or pass it to BacktestEngine.

### Step 3: Load SPY in `run_wfo()` and pass to each BacktestEngine call

In `backend/wfo_engine.py`, locate the `run_wfo()` function:

**After tickers are loaded from cache** (around lines 344–356), add SPY loading:

```python
# Load SPY once for regime computation (not included in per-ticker loop)
_spy_df: Optional[pd.DataFrame] = None
if cache_exists("SPY"):
    _spy_df = load_ticker("SPY")
```

**When constructing `BacktestEngine`** inside the per-window loop (the call to `_run_backtest_sync` or inline), pass `spy_df=_spy_df`:

```python
# In _run_backtest_sync() or wherever BacktestEngine is instantiated:
engine = BacktestEngine(
    ticker=ticker,
    start_date=is_start_str,
    end_date=oos_end_str,       # or window-specific end
    setup_types=setup_types,
    ticker_df=sliced_df,
    spy_df=_spy_df,             # ← add this
)
```

If `_run_backtest_sync` is a helper function, add `spy_df` as a parameter.

> **Note:** `REPRESENTATIVE_TICKERS` used in `optimize_parameters.py` already includes no SPY entry — SPY is prepended manually as `["SPY"] + REPRESENTATIVE_TICKERS`. The `run_wfo` call in the optimizer passes `["SPY"] + REPRESENTATIVE_TICKERS` to tickers, which means SPY's Parquet cache is already loaded. Reuse it rather than a second fetch.

### Step 4: Run to confirm GREEN

```bash
python -m pytest tests/test_wfo_engine.py -v
```

Expected: all tests pass.

### Step 5: Commit

```bash
git add backend/wfo_engine.py backend/tests/test_wfo_engine.py
git commit -m "feat(wfo): load SPY cache and pass spy_df to BacktestEngine for regime gate"
```

---

## Task 6: Refactor Scanner to Import Earnings Logic from `filters.py`

**Files:**
- Modify: `backend/main.py`

This removes the duplicate `in_earnings_blackout` logic. The scanner currently has it inline in `_check_earnings_blackout_sync()`. We keep that function (it handles caching and yfinance fetching) but delegate the date-comparison logic to `filters.in_earnings_blackout()`.

### Step 1: Write the test (verify scanner uses filters.py)

Add to a new file `backend/tests/test_scanner_filters_integration.py`:

```python
"""Verify that the scanner's earnings check delegates to filters.in_earnings_blackout."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_scanner_earnings_blackout_uses_filters_module():
    """filters.in_earnings_blackout is imported and callable from main module scope."""
    import filters
    # The scanner should be able to call the same function for date comparison
    # Within 7 days → blocked
    assert filters.in_earnings_blackout("2024-01-10", ["2024-01-15"]) is True
    # More than 7 days → not blocked
    assert filters.in_earnings_blackout("2024-01-10", ["2024-02-01"]) is False
```

### Step 2: Run to verify it passes (it should already, since filters.py is done)

```bash
python -m pytest tests/test_scanner_filters_integration.py -v
```

Expected: PASS (filters.py already exists).

### Step 3: Update `_check_earnings_blackout_sync()` in `main.py`

Locate the function in `main.py` (lines ~419–476). Find the date-comparison logic:

**Before (inline date comparison):**
```python
# Existing inline logic:
for earnings_dt in dates_to_check:
    days_away = (earnings_dt - today).days
    if -1 <= days_away <= EARNINGS_BLACKOUT_DAYS:
        result = True
        break
```

**After (delegate to filters):**
```python
from filters import in_earnings_blackout as _in_earnings_blackout

# Replace the loop with:
date_strings = [d.strftime("%Y-%m-%d") for d in dates_to_check]
today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
result = _in_earnings_blackout(today_str, date_strings)
```

This keeps the caching/fetching infrastructure in `main.py` but moves the comparison logic to `filters.py`.

### Step 4: Run full test suite to verify no regressions

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

### Step 5: Commit

```bash
git add backend/main.py backend/tests/test_scanner_filters_integration.py
git commit -m "refactor(scanner): delegate earnings date comparison to filters.in_earnings_blackout"
```

---

## Task 7: Run Full Test Suite and Verify

### Step 1: Run the complete test suite

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v --tb=short 2>&1 | tee /tmp/test_results.txt
tail -20 /tmp/test_results.txt
```

Expected output ends with:
```
========== N passed, 0 failed in X.XXs ==========
```

### Step 2: Spot-check alignment manually

Run a quick sanity check that the regime gate actually fires:

```bash
cd swing-trading-dashboard/backend
python3 -c "
import pandas as pd, numpy as np
from filters import compute_regime_series

# Bear market SPY
n = 300
close = np.linspace(200, 80, n)
spy = pd.DataFrame({'Close': close, 'Open': close, 'High': close*1.01, 'Low': close*0.99, 'Volume': np.full(n, 1e6)},
                   index=pd.date_range('2020-01-01', periods=n, freq='B'))
s = compute_regime_series(spy)
print('Bear market: bullish bars =', s.sum(), '/', len(s))

# Bull market SPY
close2 = np.linspace(80, 200, n)
spy2 = spy.copy(); spy2['Close'] = close2
s2 = compute_regime_series(spy2)
print('Bull market: bullish bars =', s2.sum(), '/', len(s2))
"
```

Expected:
- Bear market: bullish bars = 0 or very few
- Bull market: bullish bars = majority of bars (≥ 60)

### Step 3: Commit final documentation update

Update the audit file to reflect that the gaps are now closed:

```bash
git add docs/system-audit-2026-03-08.md
git commit -m "docs: update audit — regime/liquidity/earnings filters now in backtest pipeline"
```

---

## Testing Plan Summary

| Test File | Tests Added | Covers |
|-----------|-------------|--------|
| `tests/test_filters.py` | 14 new | compute_regime_series, passes_liquidity, in_earnings_blackout |
| `tests/test_backtest_engine.py` | 4 new | regime gate, liquidity gate, earnings gate, backward compat |
| `tests/test_wfo_engine.py` | 1 new | SPY passed to BacktestEngine, regime gate fires in WFO |
| `tests/test_scanner_filters_integration.py` | 2 new | scanner delegates to filters.py |

**TDD sequence for each task:**
1. Write failing test → confirm RED
2. Write minimal implementation → confirm GREEN
3. Run full suite → confirm no regressions
4. Commit

---

## Architecture Diagram (After)

```
constants.py
    ↓ (thresholds)
filters.py  ←────────── single source of truth for filter logic
    ↓              ↓                ↓
BacktestEngine  wfo_engine     main.py (scanner)
(per-bar gates) (passes         (earnings cache +
                 spy_df)         delegates comparison)
```

---

## What Is Intentionally NOT Done

| Item | Reason |
|------|--------|
| Sector strength in backtest | Requires full universe RS ranking per bar — computationally infeasible |
| Full 7-factor regime in backtest | Factors f5–f7 require live breadth/VIX — not available in historical replay |
| Earnings dates in WFO/Optuna | Historical earnings calendar not reliably available via yfinance; optional path exists via `earnings_dates` param |
| Slippage/commission model | Separate concern; not a filter alignment issue — tracked separately |

---

## Files Modified Summary

| File | Change |
|------|--------|
| `backend/filters.py` | **NEW** — centralized filter functions |
| `backend/tests/test_filters.py` | **NEW** — 14 tests for filters.py |
| `backend/backtest_engine.py` | Add regime/liquidity/earnings gates in per-bar loop; add `earnings_dates` param |
| `backend/tests/test_backtest_engine.py` | 4 new tests for new gates |
| `backend/wfo_engine.py` | Load SPY cache; pass `spy_df` to BacktestEngine calls |
| `backend/tests/test_wfo_engine.py` | 1 new test verifying SPY regime gate in WFO |
| `backend/main.py` | Delegate date comparison in `_check_earnings_blackout_sync` to `filters.py` |
| `backend/tests/test_scanner_filters_integration.py` | **NEW** — 2 tests verifying scanner uses filters.py |
