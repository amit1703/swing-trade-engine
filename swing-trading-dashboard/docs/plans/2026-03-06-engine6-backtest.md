# Engine 6 Backtest Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire Engine 6 (Resistance Breakout — KDE + pivot zones) into the backtest replay loop alongside VCP, Pullback, and Base.

**Architecture:** `_detect_signals()` in `backtest_engine.py` already has an `elif stype` dispatch pattern for each engine. We add one new `elif stype == "RES_BREAKOUT":` branch calling `scan_resistance_breakout(ticker, df_slice, sr_zones)`. The `sr_zones` list already comes from `calculate_sr_zones()` which returns both KDE and pivot zones. No changes to Engine 6 itself. We also update the UI and API defaults so RES_BREAKOUT is checked by default.

**Tech Stack:** Python 3.11, FastAPI, backtest_engine.py, engine6.py, React 18, BacktestPanel.jsx

---

### Task 1: Wire Engine 6 into `_detect_signals()` + tests

**Files:**
- Modify: `backend/backtest_engine.py` (lines 306–390)
- Create: `backend/tests/test_backtest_res_breakout.py`

**Context for implementer:**
- `_detect_signals()` is in `backend/backtest_engine.py` around line 306
- It already imports `scan_vcp`, `scan_pullback`, `scan_base_pattern` inside the loop
- `sr_zones` is already computed on line 349 from `calculate_sr_zones(ticker, df_slice)`
- `scan_resistance_breakout(ticker, df, zones)` lives in `engines/engine6.py`
- The engine requires: uptrend (close > 50 SMA), launchpad (3 tight bars under resistance), decisive close (>0.5% above zone, top 30% of range), institutional volume (≥150% of 50d average)
- Existing test helpers in `tests/test_engine6.py`: `make_uptrend_df(n, base_price)` and `setup_full_breakout(df, zone_upper, days_ago, vol_mult)` — copy these helpers into the new test file rather than importing, to avoid coupling

**Step 1: Write failing tests**

Create `backend/tests/test_backtest_res_breakout.py`:

```python
"""Tests for RES_BREAKOUT signal detection in the backtest engine."""
import sys
import os
import types
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest_engine import _detect_signals


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_uptrend_df(n=300, base_price=100.0):
    """Uptrend DataFrame: close > 50 SMA throughout."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close  = np.linspace(70.0, base_price, n)
    high   = close * 1.01
    low    = close * 0.99
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6):
    """Configure a valid Minervini-style breakout in df (modifies in place)."""
    n       = len(df)
    brk_idx = n - 1 - days_ago

    # Launchpad bars: 3 bars before breakout — tight under resistance
    for offset in range(1, 4):
        lp_idx = brk_idx - offset
        if lp_idx >= 0:
            df.iloc[lp_idx, df.columns.get_loc("High")]   = zone_upper * 1.005
            df.iloc[lp_idx, df.columns.get_loc("Low")]    = zone_upper * 0.990
            df.iloc[lp_idx, df.columns.get_loc("Close")]  = zone_upper * 0.995

    # Breakout bar: close 1.2% above zone, top of range, surge volume
    brk_close  = zone_upper * 1.012
    brk_high   = brk_close  * 1.003
    brk_low    = brk_close  * 0.990
    avg_vol    = float(df["Volume"].iloc[max(0, brk_idx - 50):brk_idx].mean())
    brk_vol    = avg_vol * vol_mult

    df.iloc[brk_idx, df.columns.get_loc("Close")]  = brk_close
    df.iloc[brk_idx, df.columns.get_loc("High")]   = brk_high
    df.iloc[brk_idx, df.columns.get_loc("Low")]    = brk_low
    df.iloc[brk_idx, df.columns.get_loc("Volume")] = brk_vol

    return brk_high


def make_spy_df(n=300):
    """Minimal SPY DataFrame for indicator computation."""
    dates  = pd.date_range("2024-01-01", periods=n, freq="B")
    close  = np.linspace(400.0, 500.0, n)
    return pd.DataFrame(
        {"Close": close, "High": close*1.01, "Low": close*0.99,
         "Open": close, "Volume": np.full(n, 50_000_000.0)},
        index=dates,
    )


def make_dummy_indicators():
    """Minimal Indicators namespace for mocking compute_indicators."""
    ns = types.SimpleNamespace()
    ns.rs_ratio   = 1.05
    ns.rs_52w_high= 1.10
    ns.rs_blue_dot= False
    ns.rs_score   = 0.05
    return ns


def make_resistance_zone(level, atr=1.0):
    return {
        "level":      level,
        "upper":      level + 0.2 * atr,
        "lower":      level - 0.2 * atr,
        "type":       "RESISTANCE",
        "atr":        atr,
        "is_primary": True,
        "source":     "kde",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_detect_signals_res_breakout_fires_when_all_rules_pass():
    """_detect_signals returns a setup dict when all Minervini rules pass."""
    zone_level = 100.0
    zone_upper = zone_level + 0.2  # atr=1.0 → upper=100.2
    df  = make_uptrend_df(n=300, base_price=99.0)
    spy = make_spy_df(n=300)
    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    zones = [make_resistance_zone(zone_level, atr=1.0)]

    with patch("backtest_engine.compute_indicators", return_value=make_dummy_indicators()), \
         patch("backtest_engine.calculate_sr_zones", return_value=zones):
        result = _detect_signals("TEST", df, spy, ["RES_BREAKOUT"])

    assert result is not None, "Expected a setup dict, got None"
    assert result["setup_type"] == "RES_BREAKOUT"
    assert result["signal"] == "BRK"
    assert result["entry"] > 0
    assert result["stop_loss"] > 0
    assert result["stop_loss"] < result["entry"]


def test_detect_signals_res_breakout_none_on_low_volume():
    """_detect_signals returns None when breakout volume is below threshold."""
    zone_level = 100.0
    zone_upper = zone_level + 0.2
    df  = make_uptrend_df(n=300, base_price=99.0)
    spy = make_spy_df(n=300)
    # vol_mult=1.0 → only 100% of avg, below the 150% threshold
    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.0)

    zones = [make_resistance_zone(zone_level, atr=1.0)]

    with patch("backtest_engine.compute_indicators", return_value=make_dummy_indicators()), \
         patch("backtest_engine.calculate_sr_zones", return_value=zones):
        result = _detect_signals("TEST", df, spy, ["RES_BREAKOUT"])

    assert result is None, "Expected None when volume is insufficient"


def test_detect_signals_res_breakout_uses_pivot_zones():
    """_detect_signals accepts pivot-sourced zones (source='pivot') for RES_BREAKOUT."""
    zone_level = 100.0
    zone_upper = zone_level + 0.2
    df  = make_uptrend_df(n=300, base_price=99.0)
    spy = make_spy_df(n=300)
    setup_full_breakout(df, zone_upper, days_ago=0, vol_mult=1.6)

    # Pivot zone (source='pivot') — engine6 should treat it identically to kde
    pivot_zone = {
        "level":      zone_level,
        "upper":      zone_upper,
        "lower":      zone_level - 0.2,
        "type":       "RESISTANCE",
        "atr":        1.0,
        "is_primary": True,
        "source":     "pivot",
    }

    with patch("backtest_engine.compute_indicators", return_value=make_dummy_indicators()), \
         patch("backtest_engine.calculate_sr_zones", return_value=[pivot_zone]):
        result = _detect_signals("TEST", df, spy, ["RES_BREAKOUT"])

    assert result is not None, "Pivot-zone breakout should fire"
    assert result["setup_type"] == "RES_BREAKOUT"
```

**Step 2: Run tests to confirm they fail**

```bash
cd backend
python -m pytest tests/test_backtest_res_breakout.py -v
```

Expected: `FAILED` — `ImportError` or `AttributeError` because `_detect_signals` doesn't handle `"RES_BREAKOUT"` yet and the patches on `backtest_engine.compute_indicators` / `backtest_engine.calculate_sr_zones` may not be set up correctly yet.

**Step 3: Wire Engine 6 into `_detect_signals()`**

Open `backend/backtest_engine.py`. Find the section around line 372–382 (the `elif stype == "BASE":` block). Add after it:

```python
            elif stype == "RES_BREAKOUT":
                from engines.engine6 import scan_resistance_breakout
                setup = scan_resistance_breakout(ticker, df_slice, sr_zones)
```

Also update the docstring at line 323 — change:
```python
    setup_types : list of "VCP" | "PULLBACK" | "BASE"
```
to:
```python
    setup_types : list of "VCP" | "PULLBACK" | "BASE" | "RES_BREAKOUT"
```

**Important note on mocking:** The patches in the tests use `backtest_engine.compute_indicators` and `backtest_engine.calculate_sr_zones`. Check the top of `_detect_signals` — these are imported inside the function body with `from ... import ...`. The correct patch targets are the module paths where the names are used, which is inside `backtest_engine`:
- `backtest_engine.compute_indicators` → needs to patch `backtest_engine` to expose these as module-level names, OR patch the sub-module paths directly.

If the patches fail, switch to patching the source modules:
```python
with patch("indicators.indicator_engine.compute_indicators", return_value=make_dummy_indicators()), \
     patch("engines.engine1.calculate_sr_zones", return_value=zones):
```

**Step 4: Run tests to confirm they pass**

```bash
cd backend
python -m pytest tests/test_backtest_res_breakout.py -v
```

Expected: `3 passed`

**Step 5: Run full suite**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: All 249 tests pass (246 existing + 3 new)

**Step 6: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_res_breakout.py
git commit -m "feat(backtest): wire Engine 6 RES_BREAKOUT into _detect_signals"
```

---

### Task 2: Update API default and frontend UI

**Files:**
- Modify: `backend/main.py` (line ~1399)
- Modify: `frontend/src/components/BacktestPanel.jsx` (lines 12, 24)

**Context for implementer:**
- `BacktestRequest` in `main.py` around line 1395–1399 has a `setup_types` field defaulting to `["VCP", "PULLBACK", "BASE"]`
- `BacktestPanel.jsx` has `SETUP_OPTIONS` const on line 12 and `useState` default on line 24
- Both must be updated to include `"RES_BREAKOUT"` as a default-on option
- No tests needed for the UI change (it's a trivial constant update); the API default change is covered by running the full suite

**Step 1: Update `BacktestRequest` default in `main.py`**

Find line ~1399:
```python
    setup_types: List[str] = Field(default_factory=lambda: ["VCP", "PULLBACK", "BASE"])
```

Change to:
```python
    setup_types: List[str] = Field(default_factory=lambda: ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"])
```

**Step 2: Update `BacktestRunner` default in `backtest_engine.py`**

Find line ~462:
```python
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE"]
```

Change to:
```python
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
```

**Step 3: Update `BacktestPanel.jsx`**

Line 12 — change:
```javascript
const SETUP_OPTIONS = ['VCP', 'PULLBACK', 'BASE']
```
to:
```javascript
const SETUP_OPTIONS = ['VCP', 'PULLBACK', 'BASE', 'RES_BREAKOUT']
```

Line 24 — change:
```javascript
  const [setupTypes,  setSetupTypes ] = useState(['VCP', 'PULLBACK', 'BASE'])
```
to:
```javascript
  const [setupTypes,  setSetupTypes ] = useState(['VCP', 'PULLBACK', 'BASE', 'RES_BREAKOUT'])
```

**Step 4: Run full suite to confirm no regressions**

```bash
cd backend
python -m pytest -q --tb=short
```

Expected: 249 passed

**Step 5: Commit**

```bash
git add backend/main.py backend/backtest_engine.py frontend/src/components/BacktestPanel.jsx
git commit -m "feat(backtest): add RES_BREAKOUT as default setup type in API and UI"
```
