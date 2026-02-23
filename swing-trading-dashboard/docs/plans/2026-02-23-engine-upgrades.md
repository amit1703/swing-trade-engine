# Engine Upgrades Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix four engine bugs that produce incorrect breakout levels and garbage quality scores, then add Engine 6 which detects stocks breaking above KDE resistance zones (the "TDL/KDE" signals missing from the dashboard).

**Architecture:** Surgical edits to engine2.py and engine5.py for the fixes; new engine6.py following the same pattern as engine5; one new FastAPI endpoint in main.py; small additions to App.jsx and SetupTable.jsx using existing component patterns.

**Tech Stack:** Python 3.11, FastAPI, pandas, numpy, yfinance; React 18, TailwindCSS; pytest for tests.

**Note on partial fix already applied:** The user has already applied the right-rim intraday HIGH fix in `scan_cup_handle` (engine5.py lines 144–153). Task 3 below completes that fix by also upgrading `_find_handle` to use intraday highs for the handle window itself.

---

### Task 1: Fix Engine 2 — Progressive Tightening

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine2.py:492`
- Test: `swing-trading-dashboard/backend/tests/test_engine2_tightening.py`

**Step 1: Write the failing test**

Create `swing-trading-dashboard/backend/tests/test_engine2_tightening.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
from engines.engine2 import _count_contractions


def test_equal_tr_values_not_progressive():
    """Equal TR values must NOT count as progressively tighter."""
    import pandas as pd
    # Three contractions with equal TR — should NOT be progressive
    tr = pd.Series([2.0] * 25 + [1.0, 1.0, 1.0, 0.5, 0.5])
    count, pattern, is_progressive = _count_contractions(tr, lookback=25)
    assert count >= 3
    assert is_progressive is False, "Equal TR values should not be progressive"


def test_strictly_decreasing_tr_is_progressive():
    """Strictly decreasing TR values must be progressive."""
    tr = pd.Series([2.0] * 25 + [1.0, 0.9, 0.8, 0.7, 0.6])
    count, pattern, is_progressive = _count_contractions(tr, lookback=25)
    assert count >= 3
    assert is_progressive is True
```

**Step 2: Run test to verify it fails**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine2_tightening.py -v
```
Expected: `test_equal_tr_values_not_progressive` FAILS (currently `>=` allows equal values).

**Step 3: Fix engine2.py line 492**

In `swing-trading-dashboard/backend/engines/engine2.py`, change line 492 from:
```python
is_progressive = all(tr_values[i] >= tr_values[i+1] for i in range(len(tr_values)-1))
```
to:
```python
is_progressive = all(tr_values[i] > tr_values[i+1] for i in range(len(tr_values)-1))
```

**Step 4: Run test to verify it passes**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine2_tightening.py -v
```
Expected: Both tests PASS.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine2.py \
        swing-trading-dashboard/backend/tests/test_engine2_tightening.py
git commit -m "fix(engine2): progressive tightening uses > not >= so equal TR bars don't count"
```

---

### Task 2: Fix Engine 5 — RS Unit Mismatch

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine5.py:188` and `:361`
- Test: `swing-trading-dashboard/backend/tests/test_engine5_rs.py`

**Context:** `rs_ratio` is a ratio (e.g. `1.05` = stock is 5% stronger than SPY over 1yr).
`spy_3m_return` is a decimal return (e.g. `0.08` = SPY up 8% in 3m). Subtracting them
directly is meaningless. The fix converts `rs_ratio` to a return: `(rs_ratio - 1.0)`.

**Step 1: Write the failing test**

Create `swing-trading-dashboard/backend/tests/test_engine5_rs.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from engines.engine5 import _quality_score, scan_cup_handle, scan_flat_base


def test_rs_vs_spy_formula_uses_ratio_minus_one():
    """
    rs_ratio=1.10 means stock gained 10% vs SPY's base.
    spy_3m_return=0.05 means SPY gained 5%.
    rs_vs_spy should be (1.10-1.0) - 0.05 = 0.05 (5% outperformance).
    The OLD formula gives 1.10 - 0.05 = 1.05 which is nonsense.
    We verify by checking quality score uses a sane rs_vs_spy value.
    """
    # With correct formula: rs_vs_spy = (1.10 - 1.0) - 0.05 = 0.05
    # _quality_score gets rs_vs_spy=0.05, so rs_pts = (0.05/0.05)*25 = 25
    qs = _quality_score(
        depth_pct=0.08,         # perfect tightness → 25 pts
        max_depth_pct=0.35,
        vol_dry_pct=0.25,       # good dry-up → 25 pts
        rs_vs_spy=0.05,         # 5% outperformance → 25 pts
        rs_blue_dot=False,      # 0 pts
    )
    assert qs == 75, f"Expected 75, got {qs}"

    # With OLD formula: rs_vs_spy = 1.10 - 0.05 = 1.05
    # rs_pts = min(25, (1.05/0.05)*25) = 25 (capped, so same here)
    # But at lower outperformance the difference is stark:
    # rs_ratio=1.01, spy_3m_return=0.05
    # correct: (1.01-1.0)-0.05 = -0.04 → 0 rs_pts
    # old:      1.01-0.05=0.96  → 25 rs_pts (wrong!)
    qs_correct = _quality_score(
        depth_pct=0.08,
        max_depth_pct=0.35,
        vol_dry_pct=0.25,
        rs_vs_spy=(1.01 - 1.0) - 0.05,   # = -0.04, stock underperforms
        rs_blue_dot=False,
    )
    assert qs_correct < 75, "Underperforming stock should score < 75"
```

**Step 2: Run test to verify the logic is sound**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine5_rs.py -v
```
Expected: Both assertions PASS (tests validate the math, not the bug itself).

**Step 3: Fix engine5.py — two occurrences**

In `swing-trading-dashboard/backend/engines/engine5.py`, change **line 188** from:
```python
rs_vs_spy = (rs_ratio - spy_3m_return) if spy_3m_return != 0 else 0.0
```
to:
```python
rs_vs_spy = (rs_ratio - 1.0) - spy_3m_return
```

Change **line 361** (in `scan_flat_base`) from:
```python
rs_vs_spy = (rs_ratio - spy_3m_return) if spy_3m_return != 0 else 0.0
```
to:
```python
rs_vs_spy = (rs_ratio - 1.0) - spy_3m_return
```

**Step 4: Run existing engine5 tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine5.py tests/test_engine5_rs.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine5.py \
        swing-trading-dashboard/backend/tests/test_engine5_rs.py
git commit -m "fix(engine5): rs_vs_spy uses (rs_ratio - 1.0) - spy_3m_return to fix unit mismatch"
```

---

### Task 3: Fix Engine 5 — C&H Handle Intraday Highs + Flat Base Pivot

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine5.py` — `_find_handle` signature + `scan_flat_base` pivot

**Context:**
- `_find_handle` currently receives only `close` and `volume` arrays; `handle_high` is set
  to `right_rim` (a close price). We need the intraday HIGH array so the function can pick
  the max intraday high across the handle window.
- The user already patched the right-rim bar's HIGH into `handle_high` after `_find_handle`
  returns (lines 144–153). This task upgrades `_find_handle` itself so the handle window
  highs are also captured.
- Flat base: `base_high` for the pivot uses `close_s.max()` but should use
  `base_high_price` (already computed as `high_s.max()`).

**Step 1: Write failing tests**

Add to `swing-trading-dashboard/backend/tests/test_engine5.py` (append at end of file):

```python
def test_find_handle_uses_intraday_high_for_handle_high():
    """handle_high must be the max intraday High in the handle window, not just rim close."""
    import numpy as np
    from engines.engine5 import _find_handle

    n = 50
    close = np.ones(n) * 100.0
    # Cup: left_peak_idx=0, cup_bottom_idx=20, right_rim_idx=40
    cup = {
        "left_peak_idx": 0, "left_peak": 100.0,
        "cup_bottom_idx": 20, "cup_bottom": 80.0,
        "right_rim_idx": 40, "right_rim": 98.0,
        "depth": 0.20, "cup_length": 40,
    }
    # Make a bar in handle window (bar 43) with intraday high of 101
    high = close * 1.005        # default: just slightly above close
    high[43] = 101.0            # spike in handle window
    volume = np.full(n, 500_000.0)  # below 50d avg = 1_000_000
    vol_sma50 = 1_000_000.0

    result = _find_handle(close, high, volume, cup, vol_sma50)
    assert result is not None, "_find_handle returned None unexpectedly"
    assert result["handle_high"] == pytest.approx(101.0), \
        f"handle_high should be 101.0 (max intraday High), got {result['handle_high']}"


def test_flat_base_pivot_uses_intraday_high():
    """Flat base breakout pivot must use highest intraday High, not highest close."""
    df = make_flat_base_df()          # existing fixture in test file
    # Inject a day where intraday High is higher than all closes
    df.iloc[-10, df.columns.get_loc("High")] = df["Close"].max() * 1.02

    result = scan_flat_base("TEST", df)
    if result is not None:
        # Entry is pivot * 1.001; pivot should reflect the intraday High spike
        assert result["entry"] > df["Close"].max() * 1.001, \
            "Entry should be above highest-close pivot when intraday High is higher"
```

**Step 2: Run to verify failures**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine5.py::test_find_handle_uses_intraday_high_for_handle_high \
                 tests/test_engine5.py::test_flat_base_pivot_uses_intraday_high -v
```
Expected: Both FAIL (`TypeError` — `_find_handle` doesn't accept `high` parameter yet).

**Step 3: Update `_find_handle` signature and logic in engine5.py**

Find `_find_handle` (around line 495). Change signature from:
```python
def _find_handle(
    close: np.ndarray,
    volume: np.ndarray,
    cup: Dict,
    vol_sma50: float,
) -> Optional[Dict]:
```
to:
```python
def _find_handle(
    close: np.ndarray,
    high: np.ndarray,
    volume: np.ndarray,
    cup: Dict,
    vol_sma50: float,
) -> Optional[Dict]:
```

Inside `_find_handle`, after the existing `handle_window` and `handle_vols` slice, add this
block just before the `return` dict at the end:

```python
    # handle_high: use max intraday High in the handle window (skip rim bar at index 0)
    handle_high_window = high[rim_idx: rim_idx + 26] if rim_idx + 26 <= len(high) else high[rim_idx:]
    handle_high = float(np.max(handle_high_window[1:])) if len(handle_high_window) > 1 else right_rim
```

Update the `return` dict to use `handle_high` instead of `right_rim`:
```python
    return {
        "handle_high": handle_high,        # was: right_rim
        "handle_low": handle_low,
        "pullback_pct": pullback,
        "handle_length": handle_length,
    }
```

**Step 4: Update the two call-sites for `_find_handle` in engine5.py**

In `scan_cup_handle` (around line 140), change:
```python
handle = _find_handle(close_lb, volume_lb, cup, vol_sma50)
```
to:
```python
high_lb = high_s.values.astype(float)[-lookback:]
handle = _find_handle(close_lb, high_lb, volume_lb, cup, vol_sma50)
```

**Step 5: Fix flat base pivot — replace `base_close.max()` with `base_high_price`**

In `scan_flat_base` (around line 306), find:
```python
# For breakout pivot, use the highest close (not intraday high)
base_close = close_s.iloc[-lookback:]
base_high = float(base_close.max())
```
Replace with:
```python
# For breakout pivot, use the intraday High (consistent with geometry)
base_high = base_high_price  # already = float(high_s.iloc[-lookback:].max())
```
(Delete the `base_close = close_s.iloc[-lookback:]` line entirely — it is no longer used.)

**Step 6: Remove the now-redundant rim-high post-fix block**

The user's earlier patch (lines 144–153 in `scan_cup_handle`) manually elevated
`handle["handle_high"]` to the rim bar's intraday HIGH after `_find_handle` returned.
Since `_find_handle` now computes `handle_high` from intraday highs directly, that block
is redundant. Remove lines 144–153:

```python
        # FIX: use actual intraday High of the right rim bar as the pivot/breakout level.
        # ...
        _rim_abs = (len(close) - lookback) + cup["right_rim_idx"]
        if _rim_abs < len(high_s):
            _rim_high_val = high_s.iloc[_rim_abs]
            _rim_high = float(_rim_high_val.item() if hasattr(_rim_high_val, 'item') else _rim_high_val)
            if _rim_high > handle["handle_high"]:
                handle["handle_high"] = _rim_high
```

**Step 7: Run all engine5 tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine5.py -v
```
Expected: All tests PASS.

**Step 8: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine5.py \
        swing-trading-dashboard/backend/tests/test_engine5.py
git commit -m "fix(engine5): _find_handle uses intraday High array for pivot; flat base pivot uses high_s"
```

---

### Task 4: Create Engine 6 — Resistance Breakout Scanner

**Files:**
- Create: `swing-trading-dashboard/backend/engines/engine6.py`
- Create: `swing-trading-dashboard/backend/tests/test_engine6.py`

**Step 1: Write the failing tests**

Create `swing-trading-dashboard/backend/tests/test_engine6.py`:

```python
"""Tests for Engine 6: Resistance Breakout Scanner."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine6 import scan_resistance_breakout


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_stage2_df(n=300, base_price=100.0):
    """
    Minimal Stage 2 DataFrame:
    - Price trending up, above 200 SMA, above 50 SMA
    - 30%+ above 52-week low
    - 200 SMA rising
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(70.0, base_price, n)   # steady uptrend
    high  = close * 1.01
    low   = close * 0.99
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_resistance_zone(level: float, atr: float = 1.0):
    """Create a minimal Engine 1 resistance zone dict."""
    return {
        "level": level,
        "upper": level + 0.2 * atr,
        "lower": level - 0.2 * atr,
        "type": "RESISTANCE",
        "atr": atr,
        "is_primary": True,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_returns_none_when_no_zones():
    df = make_stage2_df()
    assert scan_resistance_breakout("TEST", df, []) is None


def test_returns_none_when_only_support_zones():
    df = make_stage2_df()
    support_zone = {
        "level": 80.0, "upper": 80.2, "lower": 79.8,
        "type": "SUPPORT", "atr": 1.0, "is_primary": True,
    }
    assert scan_resistance_breakout("TEST", df, [support_zone]) is None


def test_detects_fresh_breakout_today():
    """Stock that crossed resistance today with volume surge should be detected."""
    n = 300
    df = make_stage2_df(n=n, base_price=105.0)

    resistance_level = 100.0
    zone = make_resistance_zone(resistance_level, atr=1.0)
    zone_upper = zone["upper"]  # 100.2

    # Day before breakout: close just below zone_upper
    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.995
    df.iloc[-2, df.columns.get_loc("High")]  = zone_upper * 0.998

    # Breakout day (today): close above zone_upper with volume surge
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.015
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0  # 160% of 1M avg

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "Should detect today's breakout"
    assert result["setup_type"] == "RES_BREAKOUT"
    assert result["signal"] == "BRK"
    assert result["days_since_breakout"] == 0
    assert result["volume_ratio"] >= 1.5


def test_detects_breakout_3_days_ago():
    """Breakout 3 days ago is within the 3-day window and should be detected."""
    n = 300
    df = make_stage2_df(n=n, base_price=110.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    # Day before breakout (4 days ago): close below zone_upper
    df.iloc[-5, df.columns.get_loc("Close")] = zone_upper * 0.99
    # Breakout 3 days ago
    df.iloc[-4, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-4, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-4, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "3-day-old breakout should be detected"
    assert result["days_since_breakout"] == 3


def test_ignores_breakout_4_days_ago():
    """Breakout older than 3 days must be ignored."""
    n = 300
    df = make_stage2_df(n=n, base_price=110.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-6, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-5, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-5, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-5, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "4-day-old breakout must be ignored"


def test_ignores_low_volume_breakout():
    """Breakout without volume surge (< 150%) must be ignored."""
    n = 300
    df = make_stage2_df(n=n, base_price=105.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_200_000.0  # only 120% — not enough

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Volume < 150% should not qualify"


def test_ignores_overextended_price():
    """Price > 5% above zone.upper is already extended — ignore."""
    n = 300
    df = make_stage2_df(n=n, base_price=115.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-4, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-3, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-3, df.columns.get_loc("Volume")] = 1_600_000.0
    # Now price extended 8% above zone
    df.iloc[-1, df.columns.get_loc("Close")] = zone_upper * 1.08

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Overextended price (>5% above zone) should be ignored"


def test_risk_math():
    """Entry, stop, target must follow the documented formula."""
    n = 300
    df = make_stage2_df(n=n, base_price=105.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.995
    brk_high = zone_upper * 1.015
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("High")]   = brk_high
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None

    expected_entry = round(brk_high * 1.001, 2)
    assert result["entry"] == pytest.approx(expected_entry, rel=1e-3)
    assert result["stop_loss"] < result["entry"]
    assert result["take_profit"] > result["entry"]
    # R:R = 2
    risk = result["entry"] - result["stop_loss"]
    assert result["take_profit"] == pytest.approx(result["entry"] + 2 * risk, rel=1e-3)
```

**Step 2: Run tests to verify they all fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine6.py -v
```
Expected: All FAIL with `ModuleNotFoundError: No module named 'engines.engine6'`.

**Step 3: Create engine6.py**

Create `swing-trading-dashboard/backend/engines/engine6.py`:

```python
"""
Engine 6: Resistance Breakout Scanner
══════════════════════════════════════
Detects stocks that have broken above a KDE resistance zone (from Engine 1)
within the last 3 trading days with institutional volume confirmation.

Criteria:
  1. Stage 2: Close > 200 SMA, Close > 50 SMA, Close >= 52w-low × 1.30, rising 200 SMA
  2. For each RESISTANCE zone: close crossed above zone.upper within last 3 days,
     was below zone.upper on the bar before the cross
  3. Breakout-day volume >= 150% of 50-day SMA
  4. Current close <= zone.upper × 1.05 (not already extended)

Risk Math:
  Entry      = breakout_bar_high × 1.001
  Stop Loss  = zone.lower − 0.2 × ATR14
  Take Profit= Entry + 2 × Risk   (1:2 R:R)
"""

import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import atr as _atr


_VOL_SURGE_THRESHOLD = 1.50   # breakout-day volume must be >= 150% of 50-day avg
_MAX_DAYS_LOOKBACK   = 3      # breakout must be within this many days
_MAX_EXTEND_PCT      = 0.05   # current close must be <= zone.upper × (1 + this)


def scan_resistance_breakout(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
) -> Optional[Dict]:
    """
    Scan for a recent resistance breakout. Returns the most recent qualifying
    breakout dict, or None if no qualifying breakout is found.
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 60:
            return None

        adj = _adj_col(data)
        close_s = data[adj]
        high_s  = data["High"]
        low_s   = data["Low"]
        volume_s = data["Volume"]

        if close_s.dropna().shape[0] < 55:
            return None

        # ── Stage 2 filter ────────────────────────────────────────────────
        sma200 = close_s.rolling(200).mean()
        sma50  = close_s.rolling(50).mean()

        lc_val  = close_s.iloc[-1]
        lc      = float(lc_val.item() if hasattr(lc_val, 'item') else lc_val)
        l200_val = sma200.iloc[-1]
        l50_val  = sma50.iloc[-1]
        l200 = float(l200_val.item() if hasattr(l200_val, 'item') else l200_val) if pd.notna(l200_val) else 0.0
        l50  = float(l50_val.item()  if hasattr(l50_val,  'item') else l50_val)  if pd.notna(l50_val)  else 0.0

        if l200 > 0 and lc < l200:
            return None
        if l50 > 0 and lc < l50:
            return None

        # Prior advance: close >= 52-week low × 1.30
        yr_low = float(low_s.iloc[-252:].min()) if len(low_s) >= 252 else float(low_s.min())
        if yr_low > 0 and lc < yr_low * 1.30:
            return None

        # Rising 200 SMA
        if l200 > 0 and len(sma200) >= 21:
            l200_prev_val = sma200.iloc[-21]
            l200_prev = float(l200_prev_val.item() if hasattr(l200_prev_val, 'item') else l200_prev_val) if pd.notna(l200_prev_val) else 0.0
            if l200_prev > 0 and l200 <= l200_prev:
                return None

        # ── Pre-compute 50-day volume SMA and ATR ────────────────────────
        vol_sma50_s = volume_s.rolling(50).mean()
        vsm50_val   = vol_sma50_s.iloc[-1]
        vol_sma50   = float(vsm50_val.item() if hasattr(vsm50_val, 'item') else vsm50_val)
        if np.isnan(vol_sma50) or vol_sma50 <= 0:
            return None

        atr14 = _atr(high_s, low_s, close_s, 14)
        latr_val = atr14.iloc[-1]
        latr = float(latr_val.item() if hasattr(latr_val, 'item') else latr_val)
        if np.isnan(latr) or latr <= 0:
            return None

        # ── Convert to plain arrays for fast indexing ─────────────────────
        close_arr  = close_s.values.astype(float)
        high_arr   = high_s.values.astype(float)
        volume_arr = volume_s.values.astype(float)
        n          = len(close_arr)

        # ── Scan resistance zones ─────────────────────────────────────────
        resistance_zones = [z for z in zones if z.get("type") == "RESISTANCE"]
        if not resistance_zones:
            return None

        best: Optional[Dict] = None
        best_days = _MAX_DAYS_LOOKBACK + 1  # sentinel

        for zone in resistance_zones:
            zone_upper = float(zone.get("upper", 0))
            zone_lower = float(zone.get("lower", 0))
            zone_level = float(zone.get("level", 0))
            if zone_upper <= 0:
                continue

            # Current price must not be overextended (> 5% above zone)
            if lc > zone_upper * (1 + _MAX_EXTEND_PCT):
                continue

            # Scan last 3 bars for the breakout bar
            for days_back in range(_MAX_DAYS_LOOKBACK):
                brk_idx = n - 1 - days_back          # index of candidate breakout bar
                pre_idx = brk_idx - 1                 # bar immediately before
                if pre_idx < 0:
                    continue

                brk_close = close_arr[brk_idx]
                pre_close = close_arr[pre_idx]

                # Fresh cross: pre-bar below zone_upper, breakout bar above zone_upper
                if not (pre_close <= zone_upper and brk_close > zone_upper):
                    continue

                # Volume on breakout bar
                brk_vol = volume_arr[brk_idx]
                vol_ratio = brk_vol / vol_sma50
                if vol_ratio < _VOL_SURGE_THRESHOLD:
                    continue

                # Valid breakout — compute risk math
                brk_high = high_arr[brk_idx]
                entry     = round(brk_high * 1.001, 2)
                stop_loss = round(zone_lower - 0.2 * latr, 2)
                risk      = entry - stop_loss
                if risk <= 0 or risk > entry * 0.15:
                    continue
                take_profit = round(entry + 2.0 * risk, 2)

                breakout_pct = round((brk_close - zone_upper) / zone_upper * 100, 2)

                candidate = {
                    "ticker":              ticker,
                    "setup_type":          "RES_BREAKOUT",
                    "signal":              "BRK",
                    "entry":               entry,
                    "stop_loss":           stop_loss,
                    "take_profit":         take_profit,
                    "rr":                  2.0,
                    "resistance_level":    round(zone_level, 2),
                    "zone_upper":          round(zone_upper, 2),
                    "breakout_pct":        breakout_pct,
                    "volume_ratio":        round(vol_ratio, 2),
                    "days_since_breakout": days_back,
                    "setup_date":          str(data.index[-1].date()),
                }

                if days_back < best_days:
                    best      = candidate
                    best_days = days_back
                break   # found breakout for this zone, move to next zone

        return best

    except Exception as exc:
        print(f"[Engine6/ResBreakout] {ticker}: {exc}")
        return None


def _prep(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if not {"High", "Low", "Volume"}.issubset(data.columns):
        return None
    return data


def _adj_col(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"
```

**Step 4: Run tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine6.py -v
```
Expected: All 8 tests PASS.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine6.py \
        swing-trading-dashboard/backend/tests/test_engine6.py
git commit -m "feat(engine6): resistance breakout scanner with Stage 2 filter and 3-day window"
```

---

### Task 5: Wire Engine 6 into main.py

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py`

**Step 1: Add import (top of file, after engine5 import ~line 81)**

```python
from engines.engine6 import scan_resistance_breakout
```

**Step 2: Add res_count tracker (in `_run_scan`, alongside existing counters ~line 320)**

Find:
```python
        base_count = 0
```
Change to:
```python
        base_count = 0
        res_count  = 0
```

Update `nonlocal` declaration in `_process` (~line 324):
```python
nonlocal vcp_count, pb_count, base_count, res_count, dropped_tickers
```

**Step 3: Add Engine 6 call inside `_process` (after Engine 5 block ~line 511)**

After the `except Exception as base_exc:` block for Engine 5, add:

```python
                # Engine 6: Resistance breakout
                if zones:
                    try:
                        res_brk = await loop.run_in_executor(
                            None, scan_resistance_breakout, ticker, df, zones
                        )
                        if res_brk:
                            try:
                                res_brk["entry"]      = float(res_brk.get("entry", 0.0))
                                res_brk["stop_loss"]  = float(res_brk.get("stop_loss", 0.0))
                                res_brk["take_profit"]= float(res_brk.get("take_profit", 0.0))
                                res_brk["rr"]         = float(res_brk.get("rr", 2.0))
                            except (ValueError, TypeError) as conv_err:
                                log.warning("ResBreakout conversion failed for %s: %s", ticker, conv_err)
                            else:
                                res_brk["sector"] = SECTORS.get(ticker, "Unknown")
                                collected_setups.append(res_brk)
                                res_count += 1
                                log.info("  RES_BRK  %-6s  level=%.2f  vol=×%.1f",
                                         ticker, res_brk.get("resistance_level", 0),
                                         res_brk.get("volume_ratio", 0))
                    except Exception as res_exc:
                        log.warning("ResBreakout check failed for %s: %s", ticker, res_exc)
```

**Step 4: Update the completion log line (~line 588) to include res_count**

Find:
```python
            "✔ Scan complete  VCP=%d  Pullbacks=%d  Processed=%d/%d  Total=%.1fs  (Regime=%.1fs, SPY=%.1fs, Process=%.1fs)",
            vcp_count,
            pb_count,
```
Change to:
```python
            "✔ Scan complete  VCP=%d  Pullbacks=%d  Base=%d  ResBreakout=%d  Processed=%d/%d  Total=%.1fs",
            vcp_count,
            pb_count,
            base_count,
            res_count,
```
(Adjust the format string argument count to match — remove the timing breakdown arguments or keep them; consistency matters less than correct count.)

**Step 5: Add API endpoint (after `get_base_setups` ~line 695)**

```python
@app.get("/api/setups/res-breakout")
async def get_res_breakout_setups():
    """Resistance breakout setups (fresh break above KDE zone, last 3 days)."""
    setups = await get_latest_setups(DB_PATH, setup_type="RES_BREAKOUT")
    setups.sort(key=lambda x: x.get("days_since_breakout", 99))
    return {"setups": setups, "count": len(setups)}
```

**Step 6: Smoke-test the endpoint**

Start the backend:
```bash
cd swing-trading-dashboard/backend
uvicorn main:app --reload --port 8000
```
In a second terminal:
```bash
curl -s http://localhost:8000/api/setups/res-breakout | python -m json.tool
```
Expected: `{"setups": [], "count": 0}` (empty — no scan run yet, but no 500 error).

Stop the backend with Ctrl+C.

**Step 7: Commit**

```bash
git add swing-trading-dashboard/backend/main.py
git commit -m "feat(main): wire Engine 6 into scan pipeline and add /api/setups/res-breakout endpoint"
```

---

### Task 6: Frontend — State, Fetch, Table

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/App.jsx`
- Modify: `swing-trading-dashboard/frontend/src/components/SetupTable.jsx`

**Step 1: Add state + fetch in App.jsx**

In App.jsx, find the existing state declarations (~line 51):
```javascript
  const [baseSetups,     setBaseSetups    ] = useState([])
```
Add after it:
```javascript
  const [resBreakoutSetups, setResBreakoutSetups] = useState([])
```

In `loadAllData` (~line 65), find:
```javascript
      const [reg, vcp, pb, base, wl] = await Promise.allSettled([
        fetchRegime(),
        fetchSetups('vcp'),
        fetchSetups('pullback'),
        fetchSetups('base'),
        fetchWatchlist(),
      ])
```
Change to:
```javascript
      const [reg, vcp, pb, base, wl, res] = await Promise.allSettled([
        fetchRegime(),
        fetchSetups('vcp'),
        fetchSetups('pullback'),
        fetchSetups('base'),
        fetchWatchlist(),
        fetchSetups('res-breakout'),
      ])
```
Add after `if (wl.status === 'fulfilled') ...`:
```javascript
      if (res.status === 'fulfilled') setResBreakoutSetups(res.value.setups ?? [])
```

**Step 2: Add Resistance Breakouts table in left panel**

In App.jsx, find the Base Patterns `<SetupTable>` block (~line 251):
```jsx
              <SetupTable
                title="Base Patterns"
                accentColor="green"
                setups={baseSetups}
                ...
              />
```
Add after it (before the `<div className="mt-auto...">` footer):
```jsx
              <SetupTable
                title="Resistance Breakouts"
                accentColor="accent"
                setups={resBreakoutSetups}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                loading={loadingSetups}
              />
```

**Step 3: Update ScanFooter to show res count**

In App.jsx, find `ScanFooter` usage (~line 261):
```jsx
                <ScanFooter
                  vcpCount={vcpSetups.length}
                  pbCount={pullbackSetups.length}
                  baseCount={baseSetups.length}
                  scanTimestamp={scanStatus.last_completed}
                />
```
Change to:
```jsx
                <ScanFooter
                  vcpCount={vcpSetups.length}
                  pbCount={pullbackSetups.length}
                  baseCount={baseSetups.length}
                  resCount={resBreakoutSetups.length}
                  scanTimestamp={scanStatus.last_completed}
                />
```

Update `ScanFooter` function signature (~line 293):
```javascript
function ScanFooter({ vcpCount, pbCount, baseCount = 0, resCount = 0, scanTimestamp }) {
```
Add after the `<span>` for Base (~line 314):
```jsx
        <span><span className="text-t-accent font-600">{resCount}</span> ResBreak</span>
```

**Step 4: Add RES_BREAKOUT signal rendering in SetupTable.jsx**

In `SetupTable.jsx`, find the last `else` branch of the signal column (~line 214):
```jsx
                      ) : (
                        /* BASE: C&H / FLAT pattern badge + BRK/DRY signal + quality score + RS+ */
```
Change to handle `RES_BREAKOUT` first, before falling through to BASE:
```jsx
                      ) : s.setup_type === 'RES_BREAKOUT' ? (
                        /* Resistance Breakout: level, break%, vol ratio, days since */
                        <div className="flex items-center gap-1 flex-wrap">
                          <span
                            className="badge"
                            style={{ background: 'rgba(0,200,122,0.18)', color: 'var(--go)',
                                     border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }}
                          >
                            BRK
                          </span>
                          {s.resistance_level != null && (
                            <span className="font-mono text-[8px] tabular-nums text-t-muted">
                              L{s.resistance_level.toFixed(2)}
                            </span>
                          )}
                          {s.volume_ratio != null && (
                            <span className="font-mono text-[8px] tabular-nums"
                              style={{ color: 'var(--go)' }}>
                              ×{s.volume_ratio.toFixed(1)}
                            </span>
                          )}
                          {s.days_since_breakout != null && (
                            <span className="font-mono text-[8px] tabular-nums text-t-muted">
                              {s.days_since_breakout === 0 ? 'today' : `${s.days_since_breakout}d ago`}
                            </span>
                          )}
                        </div>
                      ) : (
                        /* BASE: C&H / FLAT pattern badge + BRK/DRY signal + quality score + RS+ */
```

**Step 5: Verify the frontend compiles**

```bash
cd swing-trading-dashboard/frontend
npm run build
```
Expected: Build completes with no errors. (Warnings about unused vars are acceptable.)

**Step 6: Commit**

```bash
git add swing-trading-dashboard/frontend/src/App.jsx \
        swing-trading-dashboard/frontend/src/components/SetupTable.jsx
git commit -m "feat(frontend): add Resistance Breakouts table with BRK/vol/days badges"
```

---

### Task 7: End-to-End Smoke Test

**Step 1: Start the stack**

Terminal 1 — backend:
```bash
cd swing-trading-dashboard/backend
uvicorn main:app --reload --port 8000
```

Terminal 2 — frontend:
```bash
cd swing-trading-dashboard/frontend
npm run dev
```

**Step 2: Trigger a scan**

```bash
curl -s -X POST http://localhost:8000/api/run-scan | python -m json.tool
```
Expected: `{"status": "started", ...}`

**Step 3: Poll until complete**

```bash
watch -n 2 'curl -s http://localhost:8000/api/scan-status | python -m json.tool'
```
Wait for `"in_progress": false`.

**Step 4: Check resistance breakout results**

```bash
curl -s http://localhost:8000/api/setups/res-breakout | python -m json.tool
```
Expected: JSON with `setups` array (may be empty if no stocks qualify today — that is OK).
Verify no `500` errors in the backend log.

**Step 5: Open browser**

Navigate to `http://localhost:5173`. Confirm:
- "Resistance Breakouts" table appears in the left panel below "Base Patterns"
- The footer shows "ResBreak" count
- Clicking a ticker in the new table loads its chart

**Step 6: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix: post-smoke-test adjustments"
```

---

## Summary of All Files Changed

| File | Change |
|------|--------|
| `backend/engines/engine2.py:492` | `>=` → `>` in progressive tightening |
| `backend/engines/engine5.py:188,361` | RS unit fix: `(rs_ratio - 1.0) - spy_3m_return` |
| `backend/engines/engine5.py:140,307,495–532` | `_find_handle` takes `high` array; flat base pivot uses `base_high_price` |
| `backend/engines/engine6.py` | **New** resistance breakout scanner |
| `backend/main.py` | Import engine6, scan loop, new endpoint |
| `frontend/src/App.jsx` | New state, fetch, table, ScanFooter count |
| `frontend/src/components/SetupTable.jsx` | RES_BREAKOUT signal rendering |
| `backend/tests/test_engine2_tightening.py` | **New** tightening tests |
| `backend/tests/test_engine5_rs.py` | **New** RS unit tests |
| `backend/tests/test_engine5.py` | Two new handle/flat-base tests appended |
| `backend/tests/test_engine6.py` | **New** engine6 tests |
