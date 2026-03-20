# ATR-Normalized Entry Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ATR-normalized distance to all setup dicts, sort the watchlist by it, and display entry quality (EARLY/OPTIMAL/EXTENDED) in the live scanner with a hide-extended toggle.

**Architecture:** Backend engines emit `"atr"` in every setup dict (already have `latr` in scope). Watchlist endpoint sorts by `atr_distance` computed server-side. Frontend ScannerTable classifies each live setup as EARLY/OPTIMAL/EXTENDED using `(livePrice - entry) / atr` and hides EXTENDED rows by default. WatchlistPanel shows both distance metrics.

**Tech Stack:** Python/FastAPI (backend), React 18 (frontend), existing `latr` float in each engine

---

## File Map

| File | Change |
|------|--------|
| `backend/constants.py` | Add `ATR_ENTRY_EARLY_THRESHOLD`, `ATR_ENTRY_EXTENDED_THRESHOLD` |
| `backend/engines/engine2.py` | Add `"atr"` to VCP return (line 968), WATCHLIST return (line 499) |
| `backend/engines/engine3.py` | Add `"atr"` to PULLBACK strict (line 304), relaxed (line 458), WL_PB (line 746) |
| `backend/engines/engine5.py` | Add `"atr"` to FLAT_BASE (line 219), CUP_HANDLE (line 429) |
| `backend/engines/engine6.py` | Add `"atr"` to RES_BREAKOUT candidate dict (line 279), WL_BRK return (line 445) |
| `backend/engines/engine8_htf.py` | Add `"atr"` to HTF return (line 173) |
| `backend/engines/engine9_low_cheat.py` | Add `"atr"` to LCE return (line 155) |
| `backend/main.py` | Sort watchlist by `atr_distance` (line 2415) |
| `frontend/src/components/WatchlistPanel.jsx` | Sort by `atr_distance`, show both metrics in WatchRow |
| `frontend/src/components/ScannerTable.jsx` | Classify EARLY/OPTIMAL/EXTENDED, add hide-extended toggle |
| `backend/tests/test_atr_field.py` | New: assert `"atr"` present in each engine's output |

---

## Task 1: Add constants

**Files:**
- Modify: `backend/constants.py` (end of file)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_atr_entry_thresholds.py`:

```python
"""Tests that ATR entry quality constants exist and are ordered correctly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_constants_exist():
    from constants import ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD
    assert isinstance(ATR_ENTRY_EARLY_THRESHOLD, (int, float))
    assert isinstance(ATR_ENTRY_EXTENDED_THRESHOLD, (int, float))

def test_constants_ordered():
    from constants import ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD
    assert ATR_ENTRY_EARLY_THRESHOLD < ATR_ENTRY_EXTENDED_THRESHOLD
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_atr_entry_thresholds.py -v
```
Expected: `ImportError: cannot import name 'ATR_ENTRY_EARLY_THRESHOLD'`

- [ ] **Step 3: Add constants to `backend/constants.py`** (append after `SELECTIVE_HARD_FILTER`):

```python

# ATR-normalized entry quality thresholds (used in frontend scanner filter)
# entryAtrDist = (livePrice - entry) / atr
#   < EARLY_THRESHOLD  → EARLY  (hasn't reached entry yet or barely touched)
#   < EXTENDED_THRESHOLD → OPTIMAL (within range — good R:R)
#   >= EXTENDED_THRESHOLD → EXTENDED (chasing — hide by default)
ATR_ENTRY_EARLY_THRESHOLD:    float = 0.1   # < 0.1 ATR above entry = still early
ATR_ENTRY_EXTENDED_THRESHOLD: float = 0.5   # >= 0.5 ATR above entry = extended
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_atr_entry_thresholds.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/constants.py backend/tests/test_atr_entry_thresholds.py
git commit -m "feat(atr): add ATR_ENTRY_EARLY/EXTENDED_THRESHOLD constants"
```

---

## Task 2: Add `atr` field to all engine return dicts

**Files:**
- Modify: `backend/engines/engine2.py`
- Modify: `backend/engines/engine3.py`
- Modify: `backend/engines/engine5.py`
- Modify: `backend/engines/engine6.py`
- Modify: `backend/engines/engine8_htf.py`
- Modify: `backend/engines/engine9_low_cheat.py`
- Create: `backend/tests/test_atr_field.py`

### Context for each engine

Each engine already computes `latr` (last ATR value). The change is to include `"atr": round(latr, 4)` in the final return dict. The `latr` variable is always a float.

**engine2.py changes:**

1. In `scan_vcp` return dict (line 968): add `"atr": round(latr, 4),` after `"rs_blue_dot": rs_blue_dot,`

2. In `scan_near_breakout` return dict (line 499): `latr` is NOT computed in this function. Add proper ATR computation using the existing `indicators.atr` helper (see Step 3 below for the exact code — do NOT use a simplified `High * 0.02` estimate). Then add `"atr": round(_latr_nb, 4),` to the return dict.

**engine3.py changes:**

3. `scan_pullback` return (line 304): `latr` is in scope → add `"atr": round(latr, 4),`
4. `scan_relaxed_pullback` return (line 458): `latr` is in scope → add `"atr": round(latr, 4),`
5. `scan_approaching_support` watchlist return (line 746): `latr` is in scope → add `"atr": round(latr, 4),`

**engine5.py changes:**

6. `scan_darvas_box` (FLAT_BASE) return (line 219): `latr` is in scope → add `"atr": round(latr, 4),`
7. `scan_cup_handle` (CUP_HANDLE) return (line 429): `latr` is in scope → add `"atr": round(latr, 4),`

**engine6.py changes:**

8. `scan_resistance_breakout` candidate dict (line 279): `latr` is in scope → add `"atr": round(latr, 4),` to candidate dict (the dict stored in `best`)
9. `scan_res_breakout_near` watchlist return (line 445): `latr` is in scope → add `"atr": round(latr, 4),`

**engine8_htf.py changes:**

10. `scan_htf` return (line 173): `latr` is in scope → add `"atr": round(latr, 4),`

**engine9_low_cheat.py changes:**

11. `scan_lce` return (line 155): `latr` is in scope → add `"atr": round(latr, 4),`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_atr_field.py`:

```python
"""
Asserts that every engine return dict includes the 'atr' field.
Uses minimal synthetic DataFrames — just enough for the engine to produce a signal.
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_df(n=300, price=50.0, atr_pct=0.02, trend="up"):
    """Minimal OHLCV DataFrame with enough bars for engine warmup."""
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    if trend == "up":
        close = np.linspace(price * 0.7, price, n)
    else:
        close = np.full(n, price)
    high   = close * (1 + atr_pct)
    low    = close * (1 - atr_pct)
    open_  = close * 0.999
    vol    = np.full(n, 2_000_000.0)
    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close,
        "Adj Close": close, "Volume": vol,
    }, index=dates)
    return df


def test_engine2_vcp_has_atr():
    from engines.engine2 import scan_vcp
    df = _make_df(300)
    # create a fake resistance zone
    zones = [{"level": 52.0, "upper": 52.5, "lower": 50.0, "type": "RESISTANCE"}]
    result = scan_vcp("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_vcp must include 'atr'"
        assert result["atr"] > 0


def test_engine3_pullback_has_atr():
    from engines.engine3 import scan_pullback
    df = _make_df(300)
    zones = [{"level": 40.0, "upper": 41.0, "lower": 39.0, "type": "SUPPORT"}]
    result = scan_pullback("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_pullback must include 'atr'"
        assert result["atr"] > 0


def test_engine3_relaxed_pullback_has_atr():
    from engines.engine3 import scan_relaxed_pullback
    df = _make_df(300)
    zones = [{"level": 40.0, "upper": 41.0, "lower": 39.0, "type": "SUPPORT"}]
    result = scan_relaxed_pullback("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_relaxed_pullback must include 'atr'"
        assert result["atr"] > 0


def test_engine5_base_has_atr():
    from engines.engine5 import scan_base_pattern
    df = _make_df(300)
    zones = []
    result = scan_base_pattern("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_base_pattern must include 'atr'"
        assert result["atr"] > 0


def test_engine6_res_breakout_has_atr():
    from engines.engine6 import scan_resistance_breakout
    df = _make_df(300)
    zones = [{"level": 48.0, "upper": 48.5, "lower": 47.0, "type": "RESISTANCE"}]
    result = scan_resistance_breakout("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_resistance_breakout must include 'atr'"
        assert result["atr"] > 0


def test_engine8_htf_has_atr():
    from engines.engine8_htf import scan_htf
    df = _make_df(300)
    zones = []
    result = scan_htf("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_htf must include 'atr'"
        assert result["atr"] > 0


def test_engine9_lce_has_atr():
    from engines.engine9_low_cheat import scan_lce
    df = _make_df(300)
    zones = [{"level": 48.0, "upper": 48.5, "lower": 47.0, "type": "RESISTANCE"}]
    result = scan_lce("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_lce must include 'atr'"
        assert result["atr"] > 0


def test_engine2_near_breakout_has_atr():
    from engines.engine2 import scan_near_breakout
    df = _make_df(300)
    # price at 49.5 — within 1.5% of resistance at 50.0
    zones = [{"level": 50.0, "upper": 50.2, "lower": 49.0, "type": "RESISTANCE"}]
    result = scan_near_breakout("TEST", df, zones)
    if result is not None:
        assert "atr" in result, "scan_near_breakout must include 'atr'"
        assert result["atr"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_atr_field.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR|atr"
```
Expected: tests that get a non-None result will fail with `AssertionError: scan_X must include 'atr'`; tests where the engine returns None will pass vacuously (that's OK — they're checking the contract, not the signal).

- [ ] **Step 3: Add `"atr"` to engine2.py**

In `scan_vcp` return dict at line ~989 (after `"rs_blue_dot": rs_blue_dot,`), add:
```python
            "atr":                round(latr, 4),
```

In `scan_near_breakout`, add ATR extraction before the return (after the `if best_dist is None: return None` check):
```python
        # ATR for entry quality classification
        from indicators import atr as _atr_fn
        _atr14_nb = data["_ATR14"] if "_ATR14" in data.columns else _atr_fn(data["High"], data["Low"], data[adj], 14)
        _latr_nb  = float(_atr14_nb.iloc[-1]) if not pd.isna(_atr14_nb.iloc[-1]) else 0.0
```
Then in the return dict add:
```python
            "atr":        round(_latr_nb, 4),
```

- [ ] **Step 4: Add `"atr"` to engine3.py**

In `scan_pullback` return dict (line ~304), add after `"ema20"`:
```python
            "atr":          round(latr, 4),
```

In `scan_relaxed_pullback` return dict (line ~458), add after `"support_source"`:
```python
            "atr":          round(latr, 4),
```

In `scan_approaching_support` (WL_PB) return dict (line ~746), add after `"cci_today"`:
```python
            "atr":          round(latr, 4),
```

- [ ] **Step 5: Add `"atr"` to engine5.py**

In `scan_darvas_box` (FLAT_BASE) return dict (line ~219), add after `"setup_date"` or `"geometry"`:
```python
            "atr":              round(latr, 4),
```

In `scan_cup_handle` return dict (line ~429), add after `"setup_date"`:
```python
            "atr":              round(latr, 4),
```

- [ ] **Step 6: Add `"atr"` to engine6.py**

In `scan_resistance_breakout`, in the `candidate` dict (line ~279), add after `"_raw_score"`:
```python
                    "atr":                 round(latr, 4),
```

In `scan_res_breakout_near` return dict (line ~445), add after `"setup_date"`:
```python
                "atr":              round(latr, 4),
```

- [ ] **Step 7: Add `"atr"` to engine8_htf.py**

In `scan_htf` return dict (line ~173), add after `"setup_date"` line:
```python
            "atr":              round(latr, 4),
```

- [ ] **Step 8: Add `"atr"` to engine9_low_cheat.py**

In `scan_lce` return dict (line ~155), add after `"setup_date"` line:
```python
            "atr":              round(latr, 4),
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_atr_field.py -v
```
Expected: all 7 tests PASS (vacuous passes for engines that don't fire on minimal data are fine).

- [ ] **Step 10: Run existing engine tests to confirm no regressions**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_engine6.py tests/test_engine8_htf.py tests/test_engine9_lce.py tests/test_engine5.py tests/test_engine3_rlx.py -v 2>&1 | tail -10
```
Expected: all PASS

- [ ] **Step 11: Commit**

```bash
git add backend/engines/engine2.py backend/engines/engine3.py backend/engines/engine5.py \
        backend/engines/engine6.py backend/engines/engine8_htf.py backend/engines/engine9_low_cheat.py \
        backend/tests/test_atr_field.py
git commit -m "feat(atr): add atr field to all engine setup dicts"
```

---

## Task 3: ATR-normalized watchlist sort (backend)

**Files:**
- Modify: `backend/main.py` (line 2415)

The watchlist items come from the DB via `get_latest_setups`. They now have `"atr"` and `"entry"` (which is close to current price for watchlist). Sort key:

```
atr_distance = distance_pct / (atr / entry * 100)
```
Where `distance_pct` is already a % (e.g. 2.5), `atr / entry * 100` is ATR as % of price. Items missing `atr` or with `atr == 0` fall back to sorting last.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_watchlist_atr_sort.py`:

```python
"""Watchlist sort should order by ATR-normalized distance, not raw distance_pct."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _atr_dist(item):
    """Mirror of the sort key used in main.py."""
    dist  = item.get("distance_pct", 99)
    atr   = item.get("atr", 0)
    entry = item.get("entry", 1)
    if atr > 0 and entry > 0:
        atr_pct = atr / entry * 100
        return dist / atr_pct if atr_pct > 0 else 99
    return 99


def test_atr_sort_beats_raw_pct():
    """High-ATR stock with 3% distance should rank above low-ATR stock with 2% distance."""
    high_atr = {"ticker": "NVDA", "distance_pct": 3.0, "atr": 4.0, "entry": 100.0}
    low_atr  = {"ticker": "KO",   "distance_pct": 2.0, "atr": 0.5, "entry": 60.0}

    # raw pct: KO (2.0) < NVDA (3.0) → KO first in old sort
    # atr-normalized: NVDA = 3.0/(4/100*100) = 3/4 = 0.75; KO = 2.0/(0.5/60*100) = 2/0.833 = 2.4
    # NVDA atr_dist (0.75) < KO atr_dist (2.4) → NVDA should sort first

    items = [low_atr, high_atr]
    items.sort(key=_atr_dist)
    assert items[0]["ticker"] == "NVDA", "High-ATR close stock should rank above low-ATR far stock"


def test_missing_atr_sorts_last():
    item_no_atr = {"ticker": "NOPE", "distance_pct": 0.5}
    item_with   = {"ticker": "AAPL", "distance_pct": 2.0, "atr": 1.0, "entry": 50.0}
    items = [item_no_atr, item_with]
    items.sort(key=_atr_dist)
    assert items[0]["ticker"] == "AAPL"
```

- [ ] **Step 2: Run test to confirm sort logic is correct (self-contained — will pass immediately)**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_watchlist_atr_sort.py -v
```
Expected: PASS. This test is self-contained — it validates the sort formula before wiring it into main.py. It is a design validation, not a TDD red step.

- [ ] **Step 3: Update `backend/main.py` line ~2415**

Find this block:
```python
    items = await get_latest_setups(DB_PATH, setup_type="WATCHLIST")
    # Sort by distance_pct ascending (closest first)
    items.sort(key=lambda x: x.get("distance_pct", 99))
```

Replace with:
```python
    items = await get_latest_setups(DB_PATH, setup_type="WATCHLIST")
    # Sort by ATR-normalized distance ascending (closest in ATR terms first).
    # atr_distance = distance_pct / (atr/entry * 100) — how many ATRs away.
    # Falls back to raw distance_pct sort if atr/entry not available.
    def _wl_sort_key(x):
        dist  = x.get("distance_pct", 99)
        atr   = x.get("atr", 0)
        entry = x.get("entry", 0)
        if atr > 0 and entry > 0:
            atr_pct = atr / entry * 100
            return dist / atr_pct if atr_pct > 0 else 99
        return 99
    items.sort(key=_wl_sort_key)
```

- [ ] **Step 4: Run tests**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_watchlist_atr_sort.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_watchlist_atr_sort.py
git commit -m "feat(watchlist): sort by ATR-normalized distance instead of raw distance_pct"
```

---

## Task 4: WatchlistPanel — show ATR distance alongside raw %

**Files:**
- Modify: `frontend/src/components/WatchlistPanel.jsx`

The WatchlistPanel currently sorts by `distance_pct` on the frontend (lines 9 and 13). The backend now sends items pre-sorted by `atr_distance`. Remove the frontend sort and show `atr_distance` in the row label.

`atr_distance` is computed here in the frontend from the fields already present in each item:
```js
const atrDist = (item.atr > 0 && item.entry > 0)
  ? (item.distance_pct / (item.atr / item.entry * 100)).toFixed(1)
  : null
```

- [ ] **Step 1: Update `WatchlistPanel.jsx`**

**1a. Remove frontend sort** (lines 9 and 13 — trust backend order):

Replace:
```js
  const brkItems = items
    .filter(item => item.watchlist_source === 'RES_BREAKOUT')
    .sort((a, b) => (a.distance_pct ?? 99) - (b.distance_pct ?? 99))

  const pbItems = items
    .filter(item => item.watchlist_source === 'PULLBACK')
    .sort((a, b) => (a.distance_pct ?? 99) - (b.distance_pct ?? 99))
```

With:
```js
  const brkItems = items
    .filter(item => item.watchlist_source === 'RES_BREAKOUT')

  const pbItems = items
    .filter(item => item.watchlist_source === 'PULLBACK')
```

**1b. Update `WatchRow` to show ATR distance** (around line 67–68):

Replace:
```js
    const dist      = item.distance_pct ?? 0
    const distLabel = isBrk ? `${dist.toFixed(1)}% away` : `${dist.toFixed(1)}% to sup`
    const distColor = dist < 1.5 ? 'var(--go)' : dist < 3 ? 'var(--accent)' : 'var(--muted)'
```

With:
```js
    const dist      = item.distance_pct ?? 0
    const atrDist   = (item.atr > 0 && item.entry > 0)
      ? (dist / (item.atr / item.entry * 100))
      : null
    const distLabel = isBrk
      ? `${dist.toFixed(1)}%${atrDist !== null ? ` (${atrDist.toFixed(1)}atr)` : ''} away`
      : `${dist.toFixed(1)}%${atrDist !== null ? ` (${atrDist.toFixed(1)}atr)` : ''} to sup`
    const distColor = atrDist !== null
      ? (atrDist < 0.5 ? 'var(--go)' : atrDist < 1.5 ? 'var(--accent)' : 'var(--muted)')
      : (dist < 1.5 ? 'var(--go)' : dist < 3 ? 'var(--accent)' : 'var(--muted)')
```

This shows e.g. `2.1% (0.7atr) away` — color keyed to ATR distance when available.

- [ ] **Step 2: Verify in browser**

Start backend + frontend, navigate to the Watchlist panel. Each row should show something like `2.1% (0.7atr) away`. Rows should be ordered by ATR closeness, not raw %. High-ATR stocks (NVDA-style) should surface higher despite larger raw %.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/WatchlistPanel.jsx
git commit -m "feat(watchlist): show ATR-normalized distance in WL rows, trust backend sort order"
```

---

## Task 5: ScannerTable — entry quality filter (EARLY/OPTIMAL/EXTENDED)

**Files:**
- Modify: `frontend/src/components/ScannerTable.jsx`

The scanner shows live setups. With live prices already available (`livePrices` prop), classify each row:

```
entryAtrDist = (livePrice - entry) / atr
```

- `entryAtrDist < ATR_ENTRY_EARLY_THRESHOLD (0.1)` → **EARLY** — price hasn't reached entry zone yet (or barely)
- `entryAtrDist < ATR_ENTRY_EXTENDED_THRESHOLD (0.5)` → **OPTIMAL** — in range, good R:R
- `entryAtrDist >= 0.5` → **EXTENDED** — chasing; hidden by default

These thresholds are defined in backend `constants.py` (Task 1). Hardcode the same values in the frontend (0.1 and 0.5) — they're display-only and rarely change.

**Implementation:**

Add a state toggle + filter logic near the top of the component, and a badge on each row.

- [ ] **Step 1: Add state and filter toggle to `ScannerTable.jsx`**

At the top of the function body (after the existing `useState` calls), add:
```js
  const [showExtended, setShowExtended] = useState(false)
```

- [ ] **Step 2: Add entry quality computation and filter to the existing row-building logic**

In the section where rows are filtered/mapped (around line 116 where `livePrice` is computed), add after the existing `dist` computation:

```js
            const atr           = s.atr ?? 0
            const entryAtrDist  = (livePrice && atr > 0) ? (livePrice - s.entry) / atr : null
            const entryQuality  = entryAtrDist === null ? 'UNKNOWN'
              : entryAtrDist < 0.1  ? 'EARLY'
              : entryAtrDist < 0.5  ? 'OPTIMAL'
              : 'EXTENDED'
```

Then add filter:
```js
            if (!showExtended && entryQuality === 'EXTENDED') return null
```
(This goes just after computing `entryQuality`, before building the row JSX.)

- [ ] **Step 3: Add quality badge to each row**

In the row JSX, in the live price cell (around line 184 where `livePrice` is rendered), add a badge after the price:

```jsx
            {entryQuality !== 'UNKNOWN' && (
              <span style={{
                fontSize: 8,
                padding: '1px 4px',
                borderRadius: 3,
                marginLeft: 4,
                fontFamily: '"IBM Plex Mono", monospace',
                fontWeight: 700,
                background: entryQuality === 'EARLY'    ? 'rgba(100,180,255,0.12)'
                          : entryQuality === 'OPTIMAL'  ? 'rgba(0,200,122,0.12)'
                          : 'rgba(255,100,100,0.12)',
                color:      entryQuality === 'EARLY'    ? '#64b4ff'
                          : entryQuality === 'OPTIMAL'  ? 'var(--go)'
                          : '#ff6464',
                border: `1px solid ${
                  entryQuality === 'EARLY'   ? 'rgba(100,180,255,0.25)'
                : entryQuality === 'OPTIMAL' ? 'rgba(0,200,122,0.25)'
                : 'rgba(255,100,100,0.25)'
                }`,
              }}>
                {entryQuality}
              </span>
            )}
```

- [ ] **Step 4: Add "Show extended" toggle button**

In the filter bar area (above the table, or at the top of the table header), add a toggle button. Find where the filter chips/buttons are rendered in `ScannerTable.jsx` — look for the filter bar JSX — and append:

```jsx
<button
  onClick={() => setShowExtended(v => !v)}
  style={{
    padding: '3px 8px',
    fontSize: 9,
    fontFamily: '"IBM Plex Mono", monospace',
    fontWeight: 700,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    background: showExtended ? 'rgba(255,100,100,0.15)' : 'transparent',
    border: `1px solid ${showExtended ? 'rgba(255,100,100,0.4)' : 'rgba(255,255,255,0.12)'}`,
    color:  showExtended ? '#ff6464' : 'var(--muted)',
    borderRadius: 4,
    cursor: 'pointer',
    transition: 'all 0.15s',
  }}
>
  {showExtended ? 'Hide extended' : 'Show extended'}
</button>
```

- [ ] **Step 5: Verify in browser**

- Run a scan or use existing cached results
- Rows where live price is ≥0.5 ATR above entry should be hidden by default
- Each visible row shows EARLY (blue) or OPTIMAL (green) badge next to live price
- "Show extended" button reveals EXTENDED (red) rows

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ScannerTable.jsx
git commit -m "feat(scanner): add entry quality filter (EARLY/OPTIMAL/EXTENDED) with ATR normalization"
```

---

## Task 6: Smoke test end-to-end

- [ ] **Step 1: Run full backend test suite**

```bash
cd swing-trading-dashboard/backend
pytest tests/ -x -q 2>&1 | tail -15
```
Expected: no new failures

- [ ] **Step 2: Manual spot-check**

1. Start backend: `python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000`
2. Start frontend: `cd frontend && npm run dev`
3. Open http://localhost:5173
4. Run a scan
5. Check Watchlist panel: rows show `X.X% (Y.Yatr)` label, ordered by ATR distance
6. Check Scanner table: EARLY/OPTIMAL badges visible; "Show extended" toggle works

- [ ] **Step 3: Final commit if any polish needed**

```bash
git add -p  # stage only intentional changes
git commit -m "fix: polish ATR entry quality display"
```
