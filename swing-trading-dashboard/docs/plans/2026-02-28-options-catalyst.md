# Options Catalyst Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Engine 7 — an Options Catalyst scanner that detects unusual near-term call activity on liquid tickers and surfaces results in a dedicated OPTIONS tab with the existing TradingChart.

**Architecture:** A new `engine7.py` runs after Engine 6 in the per-ticker pipeline, applies a liquidity pre-filter (50-day ADV > 1M, price > $10), fetches 7–45 DTE call chains from yfinance, computes a composite OPTIONS_SCORE from four signals (vol/OI ratio, absolute call volume, call/put skew, IV term structure), and flags tickers with score ≥ 60 that pass a two-condition technical filter. Results are stored in the existing `scan_setups` table as `setup_type = "OPTIONS_CATALYST"`. A new OPTIONS tab in App.jsx reuses SetupTable and TradingChart.

**Tech Stack:** Python, yfinance option_chain, pandas, asyncio executor, FastAPI, React 18, Tailwind

---

### Task 1: Add OPTIONS_* constants to `constants.py`

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py` (after line 76, `PIVOT_MIN_TOUCHES`)

---

**Step 1: Add 11 constants**

File: `constants.py`. After the block ending with `PIVOT_MIN_TOUCHES = 2`, add:

```python
# Engine 7 — Options Catalyst
OPTIONS_MIN_ADV            = 1_000_000   # Min 50-day avg daily volume (liquidity gate)
OPTIONS_MIN_PRICE          = 10.0        # Min share price (no penny stocks)
OPTIONS_DTE_MIN            = 7           # Min days to expiry
OPTIONS_DTE_MAX            = 45          # Max days to expiry
OPTIONS_OTM_MAX_PCT        = 0.10        # Max OTM % for strike filter (10%)
OPTIONS_MIN_SCORE          = 60          # Minimum OPTIONS_SCORE to flag
OPTIONS_VOL_OI_TARGET      = 1.0         # Vol/OI ratio at which component maxes out
OPTIONS_CALL_VOL_TARGET    = 2000        # Absolute call volume at which component maxes out
OPTIONS_SKEW_NEUTRAL       = 0.5         # Call/Put skew at neutral (50/50)
OPTIONS_SKEW_MAX           = 0.9         # Call/Put skew at which component maxes out
OPTIONS_IV_SLOPE_TARGET    = 0.30        # IV term slope delta at which component maxes out
```

**Step 2: Run existing tests — confirm 158 pass**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: **158 passed**.

**Step 3: Commit**

```bash
git add swing-trading-dashboard/backend/constants.py
git commit -m "feat(engine7): add options catalyst constants"
```

---

### Task 2: Create `engine7.py` with TDD

**Files:**
- Create: `swing-trading-dashboard/backend/engines/engine7.py`
- Create: `swing-trading-dashboard/backend/tests/test_options_catalyst.py`

---

**Step 1: Write 10 failing tests**

Create `swing-trading-dashboard/backend/tests/test_options_catalyst.py`:

```python
"""
TDD tests for Engine 7 — Options Catalyst scanner.

Tests cover the three helper functions independently, then validate the
top-level scan_options_catalyst() with mocked options data.
"""

import numpy as np
import pandas as pd
import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engines.engine7 import (
    _passes_liquidity_filter,
    _passes_technical_filter,
    _compute_score,
    scan_options_catalyst,
)
from constants import OPTIONS_MIN_SCORE


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def _make_flat_df(n: int = 200, avg_vol: int = 2_000_000, price: float = 50.0) -> pd.DataFrame:
    """Flat prices at `price` for `n` bars — good for liquidity filter tests."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [price - 0.2] * n,
        "High":      [price + 0.5] * n,
        "Low":       [price - 0.5] * n,
        "Close":     [price] * n,
        "Adj Close": [price] * n,
        "Volume":    [avg_vol] * n,
    }, index=dates)


def _make_trending_df(
    n: int = 200, avg_vol: int = 2_000_000, start: float = 50.0, step: float = 0.1
) -> pd.DataFrame:
    """Linearly trending prices — for technical filter and integration tests."""
    prices = [start + i * step for i in range(n)]
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [p - 0.5 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [avg_vol] * n,
    }, index=dates)


def _make_downtrending_df(
    n: int = 200, avg_vol: int = 2_000_000, start: float = 100.0, step: float = 0.1
) -> pd.DataFrame:
    """Linearly declining prices — for technical filter failure tests."""
    prices = [max(start - i * step, 0.01) for i in range(n)]
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [p - 0.2 for p in prices],
        "High":      [p + 0.5 for p in prices],
        "Low":       [max(p - 0.5, 0.01) for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [avg_vol] * n,
    }, index=dates)


# ── _passes_liquidity_filter ──────────────────────────────────────────────────

def test_liquidity_passes_high_volume_and_price():
    df = _make_flat_df(avg_vol=2_000_000, price=50.0)
    assert _passes_liquidity_filter(df) is True


def test_liquidity_fails_low_volume():
    df = _make_flat_df(avg_vol=500_000, price=50.0)
    assert _passes_liquidity_filter(df) is False


def test_liquidity_fails_low_price():
    df = _make_flat_df(avg_vol=2_000_000, price=8.0)
    assert _passes_liquidity_filter(df) is False


# ── _passes_technical_filter ──────────────────────────────────────────────────

def test_technical_passes_uptrending_stock():
    # start=50, step=0.1, n=200 → last close ≈ 69.9, SMA50 ≈ 67.5 → close > SMA50 ✓
    # close[-1]=69.9 > close[-11]=68.9 ✓
    df = _make_trending_df(n=200, start=50.0, step=0.1)
    assert _passes_technical_filter(df) is True


def test_technical_fails_downtrending_stock():
    # start=100, step=0.1, n=200 → last close ≈ 80.1, SMA50 ≈ 82.6 → close < SMA50 ✗
    df = _make_downtrending_df(n=200, start=100.0, step=0.1)
    assert _passes_technical_filter(df) is False


# ── _compute_score ────────────────────────────────────────────────────────────

def test_compute_score_max_inputs_returns_100():
    metrics = {
        "avg_vol_oi_ratio":  2.0,   # capped → 30 pts
        "total_call_volume": 5000,  # capped → 25 pts
        "call_put_ratio":    0.95,  # capped → 25 pts
        "iv_term_slope":     1.40,  # capped → 20 pts
    }
    assert _compute_score(metrics) == pytest.approx(100.0, abs=0.1)


def test_compute_score_neutral_inputs_returns_zero():
    metrics = {
        "avg_vol_oi_ratio":  0.0,
        "total_call_volume": 0,
        "call_put_ratio":    0.5,   # neutral → 0 pts
        "iv_term_slope":     1.0,   # flat → 0 pts
    }
    assert _compute_score(metrics) == pytest.approx(0.0, abs=0.1)


def test_compute_score_partial_inputs_below_threshold():
    # vol/oi=1.0 (30pts) + call_vol=2000 (25pts) = 55pts < OPTIONS_MIN_SCORE=60
    metrics = {
        "avg_vol_oi_ratio":  1.0,
        "total_call_volume": 2000,
        "call_put_ratio":    0.5,   # neutral → 0 pts
        "iv_term_slope":     1.0,   # flat → 0 pts
    }
    assert _compute_score(metrics) < OPTIONS_MIN_SCORE


# ── scan_options_catalyst integration ────────────────────────────────────────

def test_scan_returns_none_for_illiquid_ticker():
    df = _make_flat_df(avg_vol=100_000, price=50.0)
    # No yfinance call should be made — pre-filter rejects immediately
    result = scan_options_catalyst("ILLIQ", df)
    assert result is None


def test_scan_returns_setup_when_all_conditions_met():
    # Trending stock: avg_vol=5M, price 50→70 over 200 bars → passes both filters
    df = _make_trending_df(n=200, avg_vol=5_000_000, start=50.0, step=0.1)

    high_score_metrics = {
        "total_call_volume": 5000,
        "call_put_ratio":    0.90,
        "avg_vol_oi_ratio":  1.5,
        "iv_near":           0.50,
        "iv_next":           0.38,
        "iv_term_slope":     1.32,
        "dominant_strike":   72.0,
        "dominant_expiry":   "2026-03-21",
        "dte":               21,
    }
    # Score: 30 + 25 + 25 + min(0.32/0.30, 1)*20 = 100 → well above threshold

    with patch("engines.engine7._fetch_options_data", return_value=high_score_metrics):
        result = scan_options_catalyst("STRONG", df)

    assert result is not None
    assert result["setup_type"] == "OPTIONS_CATALYST"
    assert result["ticker"] == "STRONG"
    assert result["options_score"] >= OPTIONS_MIN_SCORE
    assert result["take_profit"] > result["entry"] > result["stop_loss"]
    assert result["rr"] == 2.0
```

**Step 2: Run to confirm 10 failures**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_options_catalyst.py -v
```

Expected: **ImportError** — `cannot import name '_passes_liquidity_filter' from 'engines.engine7'` (file doesn't exist yet).

---

**Step 3: Create `engine7.py`**

Create `swing-trading-dashboard/backend/engines/engine7.py` with this exact content:

```python
"""
Engine 7: Options Catalyst Scanner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detects unusual near-term (7-45 DTE) call options activity on liquid tickers.

Signal: Smart Money aggressively buying OTM calls = potential catalyst.
Technical confirmation is intentionally relaxed (close > SMA50, not a
falling knife) because the options flow itself is the primary signal.
"""

import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from constants import (
    OPTIONS_CALL_VOL_TARGET,
    OPTIONS_DTE_MAX,
    OPTIONS_DTE_MIN,
    OPTIONS_IV_SLOPE_TARGET,
    OPTIONS_MIN_ADV,
    OPTIONS_MIN_PRICE,
    OPTIONS_MIN_SCORE,
    OPTIONS_OTM_MAX_PCT,
    OPTIONS_SKEW_MAX,
    OPTIONS_SKEW_NEUTRAL,
    OPTIONS_VOL_OI_TARGET,
)


def _days_to_expiry(expiry_str: str) -> int:
    """Return calendar days from today to expiry_str (YYYY-MM-DD)."""
    expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    return (expiry - date.today()).days


def _passes_liquidity_filter(df: pd.DataFrame) -> bool:
    """50-day avg volume > OPTIONS_MIN_ADV AND last close > OPTIONS_MIN_PRICE."""
    avg_vol = df["Volume"].tail(50).mean()
    close = float(df["Close"].iloc[-1])
    return avg_vol >= OPTIONS_MIN_ADV and close >= OPTIONS_MIN_PRICE


def _passes_technical_filter(df: pd.DataFrame) -> bool:
    """
    Relaxed technical confirmation — two conditions, both required:
      1. close > SMA50  (basic uptrend, not a broken chart)
      2. close > close[-10]  (not a falling knife over last 2 weeks)
    """
    if len(df) < 50:
        return False
    close = float(df["Close"].iloc[-1])
    sma50 = float(df["Close"].tail(50).mean())
    close_10d_ago = float(df["Close"].iloc[-11]) if len(df) >= 11 else float(df["Close"].iloc[0])
    return close > sma50 and close > close_10d_ago


def _fetch_options_data(ticker: str, current_close: float) -> Optional[Dict]:
    """
    Fetch near-term (OPTIONS_DTE_MIN to OPTIONS_DTE_MAX) call option chains
    from yfinance and compute aggregated metrics.

    Returns a metrics dict or None if insufficient/no options data.
    Exceptions are caught and return None (illiquid or no options listed).
    """
    try:
        t = yf.Ticker(ticker)
        all_expiries = t.options
        if not all_expiries:
            return None

        near_expiries = [
            e for e in all_expiries
            if OPTIONS_DTE_MIN <= _days_to_expiry(e) <= OPTIONS_DTE_MAX
        ]
        if not near_expiries:
            return None

        min_strike = current_close * 1.00
        max_strike = current_close * (1.0 + OPTIONS_OTM_MAX_PCT)

        otm_calls_list: List[pd.DataFrame] = []
        put_vol_total = 0

        for expiry in near_expiries:
            chain = t.option_chain(expiry)
            calls = chain.calls
            puts = chain.puts

            # 0–10% OTM calls with real volume and open interest
            mask = (
                (calls["strike"] >= min_strike)
                & (calls["strike"] <= max_strike)
                & (calls["volume"].fillna(0) > 0)
                & (calls["openInterest"].fillna(0) > 0)
            )
            otm_calls_list.append(calls[mask])
            put_vol_total += float(puts["volume"].fillna(0).sum())

        if not otm_calls_list:
            return None

        combined = pd.concat(otm_calls_list, ignore_index=True)
        if combined.empty:
            return None

        total_call_vol = float(combined["volume"].fillna(0).sum())
        if total_call_vol == 0:
            return None

        # Vol/OI ratio (new positioning signal)
        valid = combined[combined["openInterest"] > 0].copy()
        if valid.empty:
            return None
        avg_vol_oi = float((valid["volume"] / valid["openInterest"]).mean())

        # Call/Put skew
        denom = total_call_vol + put_vol_total
        call_put_ratio = total_call_vol / denom if denom > 0 else 0.5

        # IV near-term
        iv_vals = combined[combined["impliedVolatility"] > 0]["impliedVolatility"]
        iv_near = float(iv_vals.mean()) if not iv_vals.empty else 0.0

        # IV term structure (front vs next expiry)
        iv_next = iv_near
        iv_term_slope = 1.0
        if len(near_expiries) >= 2:
            next_calls_list = []
            for expiry in near_expiries[1:]:
                chain = t.option_chain(expiry)
                mask = (
                    (chain.calls["strike"] >= min_strike)
                    & (chain.calls["strike"] <= max_strike)
                    & (chain.calls["impliedVolatility"].fillna(0) > 0)
                )
                next_calls_list.append(chain.calls[mask])
            if next_calls_list:
                next_combined = pd.concat(next_calls_list, ignore_index=True)
                if not next_combined.empty:
                    iv_next_vals = next_combined["impliedVolatility"]
                    iv_next = float(iv_next_vals.mean())
                    if iv_next > 0:
                        iv_term_slope = iv_near / iv_next

        # Dominant strike (highest volume)
        dominant_idx = combined["volume"].idxmax()
        dominant_strike = float(combined.loc[dominant_idx, "strike"])
        dte = _days_to_expiry(near_expiries[0])

        return {
            "total_call_volume": int(total_call_vol),
            "call_put_ratio":    round(call_put_ratio, 3),
            "avg_vol_oi_ratio":  round(avg_vol_oi, 3),
            "iv_near":           round(iv_near, 3),
            "iv_next":           round(iv_next, 3),
            "iv_term_slope":     round(iv_term_slope, 3),
            "dominant_strike":   dominant_strike,
            "dominant_expiry":   near_expiries[0],
            "dte":               dte,
        }

    except Exception:  # noqa: BLE001
        return None


def _compute_score(metrics: Dict) -> float:
    """
    Composite OPTIONS_SCORE (0–100) from four components:
      30 pts  Vol/OI ratio     — new positioning vs rolling
      25 pts  Absolute volume  — raw size of the bet
      25 pts  Call/Put skew    — directional conviction
      20 pts  IV term slope    — near-term urgency
    """
    score = 0.0
    score += min(metrics["avg_vol_oi_ratio"] / OPTIONS_VOL_OI_TARGET, 1.0) * 30
    score += min(metrics["total_call_volume"] / OPTIONS_CALL_VOL_TARGET, 1.0) * 25
    skew_component = (metrics["call_put_ratio"] - OPTIONS_SKEW_NEUTRAL) / (
        OPTIONS_SKEW_MAX - OPTIONS_SKEW_NEUTRAL
    )
    score += min(max(skew_component, 0.0), 1.0) * 25
    slope_component = (metrics["iv_term_slope"] - 1.0) / OPTIONS_IV_SLOPE_TARGET
    score += min(max(slope_component, 0.0), 1.0) * 20
    return round(score, 1)


def scan_options_catalyst(ticker: str, df: pd.DataFrame) -> Optional[Dict]:
    """
    Engine 7 entry point.

    Returns an OPTIONS_CATALYST setup dict or None.
    Runs in loop.run_in_executor() — must remain synchronous.
    """
    if not _passes_liquidity_filter(df):
        return None

    if not _passes_technical_filter(df):
        return None

    current_close = float(df["Close"].iloc[-1])

    metrics = _fetch_options_data(ticker, current_close)
    if metrics is None:
        return None

    options_score = _compute_score(metrics)
    if options_score < OPTIONS_MIN_SCORE:
        return None

    return {
        "ticker":      ticker,
        "setup_type":  "OPTIONS_CATALYST",
        "entry":       round(current_close, 2),
        "stop_loss":   round(current_close * 0.95, 2),
        "take_profit": round(current_close * 1.10, 2),
        "rr":          2.0,
        "setup_date":  date.today().isoformat(),
        "options_score": options_score,
        **metrics,
    }
```

**Step 4: Run tests — confirm 10 pass**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_options_catalyst.py -v
```

Expected: **10 passed**.

**Step 5: Run full suite — confirm no regressions**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: **168 passed** (158 existing + 10 new).

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine7.py \
        swing-trading-dashboard/backend/tests/test_options_catalyst.py
git commit -m "feat(engine7): add options catalyst scanner with TDD"
```

---

### Task 3: Wire Engine 7 into `main.py` + add API endpoint

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py`

---

**Step 1: Import `scan_options_catalyst`**

File: `main.py`, line 86. Currently:

```python
from engines.engine6 import scan_resistance_breakout
```

Change to:

```python
from engines.engine6 import scan_resistance_breakout
from engines.engine7 import scan_options_catalyst
```

---

**Step 2: Add `e7` to `_scan_state` engine_stats**

File: `main.py`, lines 139–148 (`_scan_state` dict). Currently:

```python
    "engine_stats": {
        "e0": {},
        "e1": {"zones_saved": 0},
        "e2": {"vcp": 0, "watchlist": 0},
        "e3": {"pullback": 0, "relaxed": 0},
        "e5": {"cup_handle": 0, "flat_base": 0},
        "e6": {"res_breakout": 0},
        "total_tickers": 0,
        "total_duration_s": 0.0,
        "forced": False,
        "dry_run": False,
```

Change to:

```python
    "engine_stats": {
        "e0": {},
        "e1": {"zones_saved": 0},
        "e2": {"vcp": 0, "watchlist": 0},
        "e3": {"pullback": 0, "relaxed": 0},
        "e5": {"cup_handle": 0, "flat_base": 0},
        "e6": {"res_breakout": 0},
        "e7": {"options_catalyst": 0},
        "total_tickers": 0,
        "total_duration_s": 0.0,
        "forced": False,
        "dry_run": False,
```

---

**Step 3: Add Engine 7 call after Engine 6 in `_process()`**

File: `main.py`, lines 631–633. Currently:

```python
                    except Exception as res_exc:
                        log.warning("ResBreakout check failed for %s: %s", ticker, res_exc)

            except Exception as exc:
```

Change to:

```python
                    except Exception as res_exc:
                        log.warning("ResBreakout check failed for %s: %s", ticker, res_exc)

                # Engine 7: Options Catalyst (not gated by market regime)
                try:
                    opt = await loop.run_in_executor(
                        None, scan_options_catalyst, ticker, df
                    )
                    if opt:
                        try:
                            opt["entry"]      = float(opt.get("entry", 0.0))
                            opt["stop_loss"]  = float(opt.get("stop_loss", 0.0))
                            opt["take_profit"]= float(opt.get("take_profit", 0.0))
                            opt["rr"]         = float(opt.get("rr", 2.0))
                        except (ValueError, TypeError) as conv_err:
                            log.warning("Options conversion failed for %s: %s", ticker, conv_err)
                        else:
                            opt["sector"] = SECTORS.get(ticker, "Unknown")
                            collected_setups.append(opt)
                            _scan_state["engine_stats"]["e7"]["options_catalyst"] += 1
                            log.info("  OPTIONS  %-6s  score=%.0f  vol=%d  C/P=%.2f  DTE=%d",
                                     ticker, opt.get("options_score", 0),
                                     opt.get("total_call_volume", 0),
                                     opt.get("call_put_ratio", 0),
                                     opt.get("dte", 0))
                except Exception as opt_exc:
                    log.warning("Options check failed for %s: %s", ticker, opt_exc)

            except Exception as exc:
```

---

**Step 4: Add `GET /api/setups/options-catalyst` endpoint**

File: `main.py`, lines 874–875 (after `get_res_breakout_setups`). Currently:

```python
@app.get("/api/watchlist")
async def get_watchlist():
```

Change to:

```python
@app.get("/api/setups/options-catalyst")
async def get_options_catalyst_setups():
    """Options Catalyst setups — unusual near-term call activity (Engine 7)."""
    setups = await get_latest_setups(DB_PATH, setup_type="OPTIONS_CATALYST")
    setups.sort(key=lambda x: x.get("options_score", 0), reverse=True)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/watchlist")
async def get_watchlist():
```

---

**Step 5: Run full suite — confirm 168 pass**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: **168 passed**.

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/main.py
git commit -m "feat(engine7): wire options catalyst into scan pipeline and add API endpoint"
```

---

### Task 4: Frontend — OPTIONS tab

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/api.js`
- Modify: `swing-trading-dashboard/frontend/src/App.jsx`
- Modify: `swing-trading-dashboard/frontend/src/components/SetupTable.jsx`

---

**Step 1: Add `fetchOptionsSetups` to `api.js`**

File: `api.js`, line 43 (after `fetchScanStatus`). Currently:

```javascript
export const fetchScanStatus = () =>
  fetch('/api/scan-status').then(handleResponse)

// ── Trades ────────────────────────────────────────────────────────────────
```

Change to:

```javascript
export const fetchScanStatus = () =>
  fetch('/api/scan-status').then(handleResponse)

export const fetchOptionsSetups = () =>
  fetch('/api/setups/options-catalyst').then(handleResponse)

// ── Trades ────────────────────────────────────────────────────────────────
```

---

**Step 2: Add `optionsSetups` state and wire `fetchOptionsSetups` into `loadAllData`**

File: `App.jsx`.

**2a — Import `fetchOptionsSetups`** (line ~21, the existing import block). Currently:

```javascript
  fetchSetups,
```

Change to:

```javascript
  fetchSetups,
  fetchOptionsSetups,
```

**2b — Add state** (line ~56, after `resBreakoutSetups`). Currently:

```javascript
  const [resBreakoutSetups, setResBreakoutSetups] = useState([])
```

Change to:

```javascript
  const [resBreakoutSetups, setResBreakoutSetups] = useState([])
  const [optionsSetups,     setOptionsSetups     ] = useState([])
```

**2c — Add to `loadAllData`** (line ~76). Currently:

```javascript
      const [reg, vcp, pb, base, wl, res] = await Promise.allSettled([
        fetchRegime(),
        fetchSetups('vcp'),
        fetchSetups('pullback'),
        fetchSetups('base'),
        fetchWatchlist(),
        fetchSetups('res-breakout'),
      ])
      if (reg.status === 'fulfilled')  setRegime(reg.value)
      if (vcp.status === 'fulfilled')  setVcpSetups(vcp.value.setups ?? [])
      if (pb.status === 'fulfilled')   setPullbackSetups(pb.value.setups ?? [])
      if (base.status === 'fulfilled') setBaseSetups(base.value.setups ?? [])
      if (wl.status === 'fulfilled')   setWatchlistItems(wl.value.items ?? [])
      if (res.status === 'fulfilled')  setResBreakoutSetups(res.value.setups ?? [])
```

Change to:

```javascript
      const [reg, vcp, pb, base, wl, res, opt] = await Promise.allSettled([
        fetchRegime(),
        fetchSetups('vcp'),
        fetchSetups('pullback'),
        fetchSetups('base'),
        fetchWatchlist(),
        fetchSetups('res-breakout'),
        fetchOptionsSetups(),
      ])
      if (reg.status === 'fulfilled')  setRegime(reg.value)
      if (vcp.status === 'fulfilled')  setVcpSetups(vcp.value.setups ?? [])
      if (pb.status === 'fulfilled')   setPullbackSetups(pb.value.setups ?? [])
      if (base.status === 'fulfilled') setBaseSetups(base.value.setups ?? [])
      if (wl.status === 'fulfilled')   setWatchlistItems(wl.value.items ?? [])
      if (res.status === 'fulfilled')  setResBreakoutSetups(res.value.setups ?? [])
      if (opt.status === 'fulfilled')  setOptionsSetups(opt.value.setups ?? [])
```

---

**Step 3: Add OPTIONS tab button**

File: `App.jsx`, line ~231. Currently:

```javascript
        {['scanner', 'portfolio'].map((tab) => {
          const active = activeTab === tab
          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.15em',
                textTransform: 'uppercase',
                padding: '0 18px',
                background: 'transparent',
                border: 'none',
                borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
                cursor: 'pointer',
                transition: 'color 0.12s, border-color 0.12s',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {tab === 'scanner' ? 'SCANNER' : 'PORTFOLIO'}
              {tab === 'portfolio' && (
```

Change to:

```javascript
        {['scanner', 'options', 'portfolio'].map((tab) => {
          const active = activeTab === tab
          const tabColor = tab === 'options'
            ? (active ? '#a855f7' : 'var(--muted)')
            : (active ? 'var(--accent)' : 'var(--muted)')
          const tabBorder = tab === 'options'
            ? (active ? '2px solid #a855f7' : '2px solid transparent')
            : (active ? '2px solid var(--accent)' : '2px solid transparent')
          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.15em',
                textTransform: 'uppercase',
                padding: '0 18px',
                background: 'transparent',
                border: 'none',
                borderBottom: tabBorder,
                color: tabColor,
                cursor: 'pointer',
                transition: 'color 0.12s, border-color 0.12s',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {tab === 'scanner' ? 'SCANNER' : tab === 'options' ? 'OPTIONS' : 'PORTFOLIO'}
              {tab === 'portfolio' && (
```

---

**Step 4: Add OPTIONS panel body**

File: `App.jsx`, lines ~365–370. Currently:

```javascript
        ) : (
          /* Portfolio tab — full width */
          <div className="flex-1 min-w-0 overflow-hidden">
            <PortfolioTab onTickerClick={handleTickerClick} />
          </div>
        )}
```

Change to:

```javascript
        ) : activeTab === 'options' ? (
          /* Options tab — same split as scanner */
          <>
            <aside
              className="flex flex-col overflow-y-auto flex-shrink-0"
              style={{ width: 400, borderRight: '1px solid var(--border)', background: 'var(--panel)' }}
            >
              <SetupTable
                title="Options Catalyst"
                accentColor="purple"
                setups={optionsSetups}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                loading={loadingSetups}
              />
            </aside>
            <main className="flex-1 min-w-0 overflow-hidden" style={{ background: 'var(--bg)' }}>
              <TradingChart
                ticker={selectedTicker}
                chartData={chartData}
                loading={loadingChart}
              />
            </main>
          </>
        ) : (
          /* Portfolio tab — full width */
          <div className="flex-1 min-w-0 overflow-hidden">
            <PortfolioTab onTickerClick={handleTickerClick} />
          </div>
        )}
```

---

**Step 5: Add `purple` accent color + OPTIONS_CATALYST badges to `SetupTable.jsx`**

File: `SetupTable.jsx`, lines 19–23. Currently:

```javascript
  const color = accentColor === 'blue'
    ? { badge: 'bg-t-blueDim text-t-blue border border-t-blue/30', dot: '#00C8FF', sectionDot: 'bg-t-blue' }
    : accentColor === 'green'
    ? { badge: 'bg-t-goDim text-t-go border border-t-go/30', dot: '#00c87a', sectionDot: 'bg-t-go' }
    : { badge: 'bg-t-accentDim text-t-accent border border-t-accent/30', dot: '#F5A623', sectionDot: 'bg-t-accent' }
```

Change to:

```javascript
  const color = accentColor === 'blue'
    ? { badge: 'bg-t-blueDim text-t-blue border border-t-blue/30', dot: '#00C8FF', sectionDot: 'bg-t-blue' }
    : accentColor === 'green'
    ? { badge: 'bg-t-goDim text-t-go border border-t-go/30', dot: '#00c87a', sectionDot: 'bg-t-go' }
    : accentColor === 'purple'
    ? { badge: 'bg-purple-900/20 text-purple-400 border border-purple-500/30', dot: '#a855f7', sectionDot: 'bg-purple-500' }
    : { badge: 'bg-t-accentDim text-t-accent border border-t-accent/30', dot: '#F5A623', sectionDot: 'bg-t-accent' }
```

Now add OPTIONS_CATALYST badges. File: `SetupTable.jsx`, lines ~247–248. Currently:

```javascript
                      ) : (
                        /* BASE: C&H / FLAT pattern badge + BRK/DRY signal + quality score + RS+ */
```

Change to:

```javascript
                      ) : s.setup_type === 'OPTIONS_CATALYST' ? (
                        /* Options Catalyst: score, volume, call/put ratio, DTE */
                        <div className="flex items-center gap-1 flex-wrap">
                          {s.options_score != null && (
                            <span
                              className="badge"
                              style={{ background: 'rgba(168,85,247,0.18)', color: '#a855f7',
                                       border: '1px solid rgba(168,85,247,0.4)', fontWeight: 700 }}
                            >
                              {s.options_score}
                            </span>
                          )}
                          {s.total_call_volume != null && (
                            <span className="font-mono text-[8px] tabular-nums" style={{ color: '#a855f7' }}>
                              VOL {s.total_call_volume >= 1000
                                ? `${(s.total_call_volume / 1000).toFixed(1)}K`
                                : s.total_call_volume}
                            </span>
                          )}
                          {s.call_put_ratio != null && (
                            <span className="font-mono text-[8px] tabular-nums text-t-muted">
                              C/P {s.call_put_ratio.toFixed(2)}
                            </span>
                          )}
                          {s.dte != null && (
                            <span className="font-mono text-[8px] tabular-nums text-t-muted">
                              {s.dte}d
                            </span>
                          )}
                        </div>
                      ) : (
                        /* BASE: C&H / FLAT pattern badge + BRK/DRY signal + quality score + RS+ */
```

---

**Step 6: Run the frontend build**

```bash
cd swing-trading-dashboard/frontend
npm run build
```

Expected: build succeeds with no errors.

**Step 7: Commit**

```bash
git add swing-trading-dashboard/frontend/src/api.js \
        swing-trading-dashboard/frontend/src/App.jsx \
        swing-trading-dashboard/frontend/src/components/SetupTable.jsx
git commit -m "feat(frontend): add OPTIONS tab with options catalyst scanner UI"
```

---

## Manual Verification (after all tasks)

1. Start backend: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
2. Start frontend: `npm run dev` (from `frontend/`)
3. Confirm three tabs visible: SCANNER / OPTIONS / PORTFOLIO
4. Run a scan
5. Click OPTIONS tab → SetupTable appears on left (purple accent)
6. If any tickers flagged, click one → TradingChart loads with KDE zones on right
7. Check backend logs for `OPTIONS  TICKER  score=XX  vol=XXXX  C/P=X.XX  DTE=XX` lines
