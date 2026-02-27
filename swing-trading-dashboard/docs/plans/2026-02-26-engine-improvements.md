# Engine Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Loosen engine thresholds to produce more VCP/Base/ResBreakout signals, tighten RLX pullbacks, and route TDL breakouts from watchlist to VCP table.

**Architecture:** Pure backend changes to 4 engine files. Each task is self-contained — one engine per task. No schema changes, no frontend changes.

**Tech Stack:** Python, pandas, numpy, scipy. Tests run with `pytest` from `swing-trading-dashboard/backend/`.

---

### Task 1: Engine 6 — Simplify Stage 2 + Lower Volume Threshold

**Files:**
- Modify: `backend/engines/engine6.py:31,67-81`
- Modify (tests): `backend/tests/test_engine6.py`

**Context:** Engine 6 currently has a strict Stage 2 filter that eliminates many breakouts: it requires close > 200 SMA, close > 50 SMA, 30% above 52w-low, AND rising 200 SMA. Volume threshold is 150%. New requirements: just close > 50 SMA + volume ≥ 100%.

---

**Step 1: Update `test_ignores_low_volume_breakout` — it will PASS now, not fail**

The test at line 123 uses 120% volume and expects `None`. With our new 100% threshold, 120% qualifies. Update the test to verify it now returns a result, and add a new test for the true failure case (volume < 100%).

In `backend/tests/test_engine6.py`, replace:

```python
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
```

with:

```python
def test_ignores_low_volume_breakout():
    """Breakout without volume (< 100% of avg) must be ignored."""
    n = 300
    df = make_stage2_df(n=n, base_price=105.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 800_000.0  # only 80% of avg — not enough

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is None, "Volume < 100% of avg should not qualify"


def test_detects_breakout_with_moderate_volume():
    """Breakout with 110% volume (above new 100% threshold) should be detected."""
    n = 300
    df = make_stage2_df(n=n, base_price=105.0)

    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_100_000.0  # 110% of 1M avg

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "110% volume should qualify with new 100% threshold"
    assert result["volume_ratio"] == pytest.approx(1.1, rel=0.05)
```

Also add a test showing Stage 2 is no longer required (stock below 200 SMA still gets detected):

```python
def test_detects_breakout_below_200sma():
    """Stage 2 filter removed — stock below 200 SMA but above 50 SMA should qualify."""
    n = 300
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # Declining price: below 200 SMA but above 50 SMA at the end
    close = np.linspace(120.0, 85.0, n)   # downtrend — 200 SMA > current price
    close[-50:] = np.linspace(85.0, 95.0, 50)  # recent recovery above 50 SMA
    high   = close * 1.01
    low    = close * 0.99
    volume = np.full(n, 1_000_000.0)
    df = pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    zone = make_resistance_zone(90.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.99
    df.iloc[-1, df.columns.get_loc("Close")]  = zone_upper * 1.01
    df.iloc[-1, df.columns.get_loc("High")]   = zone_upper * 1.013
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_100_000.0

    # Confirm this df has close < 200 SMA (so old Stage 2 would have rejected it)
    sma200 = pd.Series(close).rolling(200).mean().iloc[-1]
    assert close[-1] < sma200, "Precondition: close must be below 200 SMA"

    result = scan_resistance_breakout("TEST", df, [zone])
    assert result is not None, "Should detect breakout even when below 200 SMA"
```

**Step 2: Run tests to confirm they fail (before implementation)**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine6.py -v 2>&1 | tail -20
```

Expected: `test_detects_breakout_with_moderate_volume` FAILS, `test_detects_breakout_below_200sma` FAILS (old engine rejects them), `test_ignores_low_volume_breakout` FAILS (passes 120% now but test expects None).

**Step 3: Implement changes in `engine6.py`**

Change the module-level constant:

```python
# Line 31 — change:
_VOL_SURGE_THRESHOLD = 1.50
# to:
_VOL_SURGE_THRESHOLD = 1.00
```

Replace the entire Stage 2 filter block (lines 57–81) with a simpler uptrend check:

```python
        # Uptrend filter: price must be above 50 SMA
        sma50 = close_s.rolling(50).mean()
        l50_val = sma50.iloc[-1]
        l50 = float(l50_val.item() if hasattr(l50_val, 'item') else l50_val) if pd.notna(l50_val) else 0.0
        if l50 > 0 and lc < l50:
            return None
```

Delete these blocks entirely (they are the old Stage 2 checks):
- `sma200 = close_s.rolling(200).mean()` and related l200 variables
- `if l200 > 0 and lc < l200: return None`
- `yr_low` calculation and `if yr_low > 0 and lc < yr_low * 1.30: return None`
- The entire `if l200 > 0 and len(sma200) >= 21:` rising-SMA block

**Step 4: Run tests to confirm they pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine6.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine6.py swing-trading-dashboard/backend/tests/test_engine6.py
git commit -m "feat(engine6): simplify to KDE zone cross + 100% volume; remove Stage 2 filter"
```

---

### Task 2: Engine 2 — Loosen RS Filter + Fix TDL Routing

**Files:**
- Modify: `backend/engines/engine2.py` — lines 616 (Path B RS check) and 681 (Path C vol + range), and lines 364–376 (`scan_near_breakout` TDL-BRK block)
- Create: `backend/tests/test_engine2_rs_tdl.py`

**Context:** Path B (BRK) currently requires `rs_vs_spy > 0`. Change to `> -0.05`. Path C (TDL breakout) volume gate is 120%, change to 100%, and extend the price cap from 2% to 3% above trendline. In `scan_near_breakout`, remove the TDL-BRK detection block — those setups now surface via Path C.

---

**Step 1: Write failing tests in new file `backend/tests/test_engine2_rs_tdl.py`**

```python
"""Tests for Engine 2 RS threshold and TDL routing changes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine2 import scan_vcp, scan_near_breakout


def make_trending_df(n=300, base_price=100.0):
    """Uptrending stock: 8 EMA > 20 EMA, close > 50 SMA, close > 200 SMA."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(60.0, base_price, n)
    high  = close * 1.005
    low   = close * 0.995
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_resistance_zone(level: float, atr: float = 1.0):
    return {
        "level": level, "upper": level + 0.2 * atr,
        "lower": level - 0.2 * atr, "type": "RESISTANCE",
        "atr": atr, "is_primary": True,
    }


# ── RS threshold tests ─────────────────────────────────────────────────────────

def test_brk_rejects_stock_lagging_spy_by_more_than_5pct():
    """BRK path must reject stock with rs_vs_spy < -0.05."""
    df = make_trending_df(base_price=105.0)
    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    # Price just broke above zone with volume surge
    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.995
    df.iloc[-2, df.columns.get_loc("Adj Close")] = zone_upper * 0.995
    df.iloc[-1, df.columns.get_loc("Close")] = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("Adj Close")] = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("High")] = zone_upper * 1.015
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0

    result = scan_vcp("TEST", df, [zone], spy_3m_return=0.15, rs_blue_dot=False)
    # Stock 3m return ≈ (105/60)^(1/1) — but we need to set up spy_3m so rs_vs_spy < -0.05
    # With spy_3m_return=0.15 and stock_3m ≈ 0.08 → rs_vs_spy ≈ -0.07 < -0.05 → should reject
    if result is not None:
        assert result.get("is_breakout") is not True or result.get("rs_vs_spy", 0) > -0.05, \
            "BRK path should not fire when rs_vs_spy < -0.05"


def test_brk_accepts_stock_lagging_spy_by_less_than_5pct():
    """BRK path must accept stock with rs_vs_spy between -0.05 and 0."""
    df = make_trending_df(base_price=105.0)
    zone = make_resistance_zone(100.0, atr=1.0)
    zone_upper = zone["upper"]

    df.iloc[-2, df.columns.get_loc("Close")] = zone_upper * 0.995
    df.iloc[-2, df.columns.get_loc("Adj Close")] = zone_upper * 0.995
    df.iloc[-1, df.columns.get_loc("Close")] = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("Adj Close")] = zone_upper * 1.012
    df.iloc[-1, df.columns.get_loc("High")] = zone_upper * 1.015
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0

    # spy_3m_return small enough that rs_vs_spy > -0.05
    result = scan_vcp("TEST", df, [zone], spy_3m_return=0.02, rs_blue_dot=False)
    # With spy at +2% and stock returning ~+75% over 300 bars, rs_vs_spy >> 0
    assert result is not None, "Should detect BRK with rs_vs_spy > -0.05"


# ── TDL-BRK routing test ──────────────────────────────────────────────────────

def test_near_breakout_does_not_return_tdl_brk():
    """scan_near_breakout must NOT produce TDL-BRK pattern_type anymore."""
    df = make_trending_df(base_price=100.0)

    # Create a fake trendline whose current value is 2% below current price
    # (simulating a stock 1.5% above its descending trendline)
    trendline_value = 100.0 * 0.985  # trendline is below current price
    trendline = {
        "descending": {
            "series": [{"time": "2025-01-01", "value": trendline_value}],
            "slope": -0.1,
            "touches": 3,
        },
        "ascending": None,
    }

    result = scan_near_breakout("TEST", df, [], trendline=trendline)
    if result is not None:
        assert result.get("pattern_type") != "TDL-BRK", \
            "TDL-BRK should no longer appear in watchlist"
```

**Step 2: Run tests to confirm they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine2_rs_tdl.py -v 2>&1 | tail -20
```

Expected: `test_brk_accepts_stock_lagging_spy_by_less_than_5pct` and `test_near_breakout_does_not_return_tdl_brk` may fail on current code.

**Step 3: Implement changes in `engine2.py`**

**Change A — Path B RS filter (line ~616):**
```python
# Find this condition:
if resistance_zones and is_vol_surge and rs_vs_spy > 0:
# Change to:
if resistance_zones and is_vol_surge and rs_vs_spy > -0.05:
```

**Change B — Path C TDL volume gate and price cap (lines ~679–682):**
```python
# Find this block:
            if tl_today > 0:
                pct_above_tl = (lc - tl_today) / tl_today
                if 0 < pct_above_tl <= 0.02 and lvol >= 1.2 * avg_vol:
                    is_trendline_breakout = True
                    trendline_data = trendline_result
# Change to:
            if tl_today > 0:
                pct_above_tl = (lc - tl_today) / tl_today
                if 0 < pct_above_tl <= 0.03 and lvol >= 1.0 * avg_vol:
                    is_trendline_breakout = True
                    trendline_data = trendline_result
```

**Change C — Remove TDL-BRK from `scan_near_breakout` (lines ~364–376):**

Remove the entire block that checks for TDL breakout above the trendline. It starts with:
```python
        # ── Check confirmed TDL breakout (price 0.1-3% ABOVE descending trendline) ──
```
and ends with:
```python
                        best_type = "TDL-BRK"
```
Delete those ~12 lines entirely. TDL breakouts now route through `scan_vcp` Path C.

**Step 4: Run tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine2_rs_tdl.py tests/test_engine2_tightening.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine2.py swing-trading-dashboard/backend/tests/test_engine2_rs_tdl.py
git commit -m "feat(engine2): loosen RS filter to -5%; route TDL breakouts to VCP via Path C"
```

---

### Task 3: Engine 3 — Tighten Relaxed Pullback

**Files:**
- Modify: `backend/engines/engine3.py` — `scan_relaxed_pullback` function
- Create: `backend/tests/test_engine3_rlx.py`

**Context:** The relaxed pullback triggers on CCI going from any negative value to slightly less negative, with no support zone required. Tighten to: CCI previous must be below -30, AND a KDE support zone must be present.

---

**Step 1: Write failing tests in `backend/tests/test_engine3_rlx.py`**

```python
"""Tests for Engine 3 tightened relaxed pullback."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine3 import scan_relaxed_pullback


def make_pullback_df(n=200, ema_drift=0.0):
    """
    Stock in uptrend: 8 EMA > 20 EMA, close > 50 SMA.
    Close is near EMA20 (within 2%).
    Low volume last 3 days.
    CCI is negative and turning.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(70.0, 100.0, n)
    high  = close * 1.01
    low   = close * 0.99
    volume = np.full(n, 1_000_000.0)
    volume[-3:] = 700_000.0  # low volume last 3 days
    return pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_support_zone(level: float):
    return {
        "level": level, "upper": level * 1.005,
        "lower": level * 0.995, "type": "SUPPORT",
        "is_primary": True,
    }


def test_rlx_rejects_cci_above_minus_30():
    """RLX must reject when CCI[yesterday] is between -30 and 0 (too mild)."""
    # We can't easily control CCI directly in the df, so this is a structural test.
    # The test confirms the threshold is at -30, not 0.
    # We verify: with cci_prev = -10 (very mild dip), relaxed should NOT fire.
    # This is tested indirectly via a df that produces mild CCI values.
    # A flat price series near its mean produces CCI near 0.
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # Uptrend followed by flat → CCI near 0
    close = np.linspace(70.0, 100.0, n)
    close[-20:] = 99.5 + np.sin(np.linspace(0, np.pi, 20)) * 0.3  # tiny oscillation
    high   = close * 1.003
    low    = close * 0.997
    volume = np.full(n, 1_000_000.0)
    volume[-3:] = 700_000.0
    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )
    support = make_support_zone(99.0)
    result = scan_relaxed_pullback("TEST", df, [support])
    # CCI here should be very near 0 — should not trigger RLX
    # If it does trigger, cci_yesterday must be < -30 per new rule
    if result is not None:
        assert result.get("cci_yesterday", 0) < -30, \
            "RLX should only fire when CCI[yesterday] < -30"


def test_rlx_rejects_when_no_support_zone():
    """RLX must reject when no KDE support zone is present."""
    df = make_pullback_df()
    # Pass empty zone list — no support zones available
    result = scan_relaxed_pullback("TEST", df, [])
    assert result is None, "RLX must not fire without a support zone"


def test_rlx_rejects_resistance_zones_only():
    """RLX must reject when only resistance zones are present (no support)."""
    df = make_pullback_df()
    resistance_only = [
        {"level": 110.0, "upper": 110.5, "lower": 109.5,
         "type": "RESISTANCE", "is_primary": True}
    ]
    result = scan_relaxed_pullback("TEST", df, resistance_only)
    assert result is None, "RLX must not fire with only resistance zones"
```

**Step 2: Run tests to confirm the no-zone tests fail (since current code doesn't require a zone)**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine3_rlx.py -v 2>&1 | tail -20
```

Expected: `test_rlx_rejects_when_no_support_zone` and `test_rlx_rejects_resistance_zones_only` likely FAIL.

**Step 3: Implement changes in `engine3.py` — `scan_relaxed_pullback`**

**Change A — CCI floor (line ~274):**
```python
# Find:
        cci_turning = cci_today > cci_prev and cci_prev < 0
# Change to:
        cci_turning = cci_today > cci_prev and cci_prev < -30.0
```

**Change B — Add mandatory support zone check (after the low-volume check, before risk math):**

Add this block right before the `# ── Risk Math ──` comment:

```python
        # ── Mandatory support zone touch ─────────────────────────────────
        # Relaxed pullback requires a nearby KDE support zone (same as strict).
        support_zones = [z for z in sr_zones if z["type"] == "SUPPORT"]
        nearest_sup = None
        for z in support_zones:
            low_in_zone = z["lower"] * 0.995 <= ll <= z["upper"] * 1.005
            close_in_zone = z["lower"] <= lc <= z["upper"]
            if low_in_zone or close_in_zone:
                nearest_sup = z
                break
        if nearest_sup is None:
            return None
```

Also update the `support_level` calculation that follows to use `nearest_sup` where available:
```python
        # Use nearest confirmed zone level for stop math (not lowest zone)
        support_level = nearest_sup["level"]
```
(Replace the existing `support_level = min([z["level"] for z in support_zones]) if support_zones else l50` line.)

**Step 4: Run tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine3_rlx.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine3.py swing-trading-dashboard/backend/tests/test_engine3_rlx.py
git commit -m "feat(engine3): tighten RLX pullback — CCI floor -30 + mandatory support zone"
```

---

### Task 4: Engine 5 — Loosen Base Pattern Bottlenecks

**Files:**
- Modify: `backend/engines/engine5.py` — both `scan_cup_handle` and `scan_flat_base`
- Modify (tests): `backend/tests/test_engine5.py`

**Context:** Three bottlenecks to loosen:
1. Both patterns: remove "rising 200 SMA" check (keep close > 200 SMA)
2. C&H: right rim recovery loosened from 10% → 15%
3. Flat Base: volume dry-up loosened from 75% → 90%

---

**Step 1: Read the existing test to understand what helper functions are available**

Check `backend/tests/test_engine5.py` for any existing Stage 2 / rising SMA tests that will need updating.

**Step 2: Add a failing test for the rising-SMA removal**

Add to `backend/tests/test_engine5.py`:

```python
def test_flat_base_detects_when_200sma_not_rising():
    """Flat base must be found even when 200 SMA is flat/declining, as long as close > 200 SMA."""
    from engines.engine5 import scan_flat_base
    import numpy as np, pandas as pd

    n = 300
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # Price flat near 100 — 200 SMA will be ≈ 100 (flat, not rising)
    close = np.full(n, 100.0)
    close[:100] = np.linspace(80.0, 100.0, 100)   # prior advance (above 52w-low × 1.30)
    close[100:] = 100.0 + np.random.default_rng(42).uniform(-0.5, 0.5, n - 100)  # flat base
    high   = close * 1.002
    low    = close * 0.998
    volume = np.full(n, 500_000.0)   # low volume (well below 50-day avg of 1M)
    volume[:200] = 1_000_000.0       # higher earlier volume for 50-day avg baseline

    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Verify precondition: 200 SMA is NOT rising (today ≤ 20 bars ago)
    sma200 = pd.Series(close).rolling(200).mean()
    assert sma200.iloc[-1] <= sma200.iloc[-21] + 0.1, "Precondition: 200 SMA must not be rising"

    result = scan_flat_base("TEST", df)
    assert result is not None, "Should find flat base even when 200 SMA is flat"
```

**Step 3: Run tests to confirm it fails**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine5.py -v -k "200sma" 2>&1 | tail -10
```

Expected: FAIL (current code rejects flat 200 SMA).

**Step 4: Implement all three changes in `engine5.py`**

**Change A — Remove rising 200 SMA check from `scan_cup_handle` (lines ~107–111):**

```python
# REMOVE this entire block from scan_cup_handle:
        if l200 > 0 and len(sma200) >= 21:
            l200_prev_val = sma200.iloc[-21]
            l200_prev = float(l200_prev_val.item() if hasattr(l200_prev_val, 'item') else l200_prev_val) if pd.notna(l200_prev_val) else 0.0
            if l200_prev > 0 and l200 <= l200_prev:
                return None
```

**Change B — Remove rising 200 SMA check from `scan_flat_base` (lines ~274–278):**

Same block — remove it from `scan_flat_base` as well.

**Change C — Loosen C&H right rim recovery (line ~443):**

```python
# Find in _find_cup():
    if (left_peak - right_rim) / left_peak > 0.10:
        return None
# Change to:
    if (left_peak - right_rim) / left_peak > 0.15:
        return None
```

**Change D — Loosen flat base volume dry-up (line ~329):**

```python
# Find in scan_flat_base():
        if vol_ratio_10_50 > 0.75:
            return None
# Change to:
        if vol_ratio_10_50 > 0.90:
            return None
```

**Step 5: Run all engine5 tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine5.py tests/test_engine5_rs.py -v
```

Expected: All PASS.

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine5.py swing-trading-dashboard/backend/tests/test_engine5.py
git commit -m "feat(engine5): remove rising-200SMA gate; loosen C&H rim to 15%, flat base vol to 90%"
```

---

### Task 5: Run Full Test Suite + Update CLAUDE.md

**Step 1: Run all backend tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v
```

Expected: All tests PASS. If any fail, investigate before proceeding.

**Step 2: Update CLAUDE.md thresholds section**

In `.claude/CLAUDE.md`, update the constants reference for Engine 2 (RS filter), Engine 5 (C&H rim, flat base vol), and Engine 6 (volume threshold + Stage 2 removed).

**Step 3: Final commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: update CLAUDE.md with loosened engine thresholds"
```

---

## Testing Summary

| Test File | New Tests Added | What They Cover |
|-----------|----------------|-----------------|
| `test_engine6.py` | 2 | 100% vol threshold, no Stage 2 required |
| `test_engine2_rs_tdl.py` | 3 | RS -5% threshold, TDL-BRK removed from watchlist |
| `test_engine3_rlx.py` | 3 | No support zone = reject, CCI floor -30 |
| `test_engine5.py` | 1 | Flat 200 SMA still produces base patterns |

## Key Invariants (Must Still Pass)

- Engine 6: 4-day-old breakouts still rejected
- Engine 6: Overextended price (>5% above zone) still rejected
- Engine 2: `_count_contractions` tests unchanged
- Engine 5: Quality score minimum 25 still enforced
