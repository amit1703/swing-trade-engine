# Engine Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce premature entries and fake breakouts across VCP, LCE, RES_BREAKOUT, and BASE engines by adding volatility-structure gates, a mini-breakout trigger, and tighter volume/decisive-close thresholds.

**Architecture:** All new thresholds are added to `constants.py` first, then each engine is modified to import and apply them. Tests are written before implementation (TDD). No changes to Engine 3 (PULLBACK) or the scan pipeline (main.py).

**Tech Stack:** Python 3.11, pandas, numpy, pytest. Backend only — no frontend changes.

---

## Task 1: Add new constants to `constants.py`

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py`

**Step 1: Add the six new constants and update MIN_ATR_PCT**

Open `constants.py`. Change line 172:
```python
MIN_ATR_PCT = 2.5           # ATR(14)/Close×100 minimum — filters low-vol stocks
```

Then add a new section at the bottom of the file:

```python
# ──────────────────────────────────────────────────────────────────────────
# Engine Hardening (2026-03-07)
# ──────────────────────────────────────────────────────────────────────────

# VCP contraction gates
VCP_MIN_CONTRACTIONS_STRICT  = 3   # Path A (DRY): ≥3 progressive contractions required
VCP_MIN_CONTRACTIONS_RELAXED = 2   # Paths B/C/D (breakout): ≥2 contractions required

# LCE mini-breakout trigger
LCE_BREAKOUT_VOL_RATIO = 1.0       # LCE: volume must be ≥ 1× 20-day avg on breakout bar

# BASE breakout filter
BASE_BRK_MIN_VOL_RATIO = 1.5       # BASE BRK signal: raised from 1.2× to 1.5×

# RES_BREAKOUT tighter filters
RES_LAUNCHPAD_BARS         = 5     # Pre-breakout consolidation bars (was 3)
RES_DECISIVE_MIN_PCT       = 0.007 # Decisive close minimum = 0.7% above zone
RES_DECISIVE_ATR_FACTOR    = 0.25  # Decisive close = max(0.7%, 0.25 × ATR)
```

**Step 2: Commit**
```bash
cd swing-trading-dashboard/backend
git add constants.py
git commit -m "feat(constants): add engine-hardening thresholds — ATR 2.5, VCP contractions, LCE vol, BASE vol, RES launchpad/decisive"
```

---

## Task 2: Harden VCP engine — contraction structure gates

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine2.py`
- Test: `swing-trading-dashboard/backend/tests/test_engine2_tightening.py` (add to existing)

**Background**
`_count_contractions()` is already called on every `scan_vcp` invocation and returns `(contraction_count, contraction_pattern, is_progressive)`. These values are in scope as local variables before any path check. We gate each path on the count without re-computing anything.

**Step 1: Write the failing tests**

Add these two test functions to `tests/test_engine2_tightening.py`:

```python
def test_path_b_rejected_without_contractions():
    """Path B (confirmed KDE breakout) must have >= 2 contractions or it falls through."""
    from engines.engine2 import scan_vcp

    # Build a DataFrame where:
    #   - trend is up (EMA8 > EMA20, close > SMA50)
    #   - price has just crossed above a resistance zone with high volume
    #   - but TR is flat (no contractions)
    n = 200
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.linspace(80.0, 100.5, n)   # clean uptrend
    high  = close * 1.01
    low   = close * 0.99
    # Flat volume — no contraction in TR
    volume = np.full(n, 2_000_000.0)      # always high → vol surge, no dry-up
    df = pd.DataFrame({"Close": close, "High": high, "Low": low,
                       "Open": close, "Volume": volume}, index=dates)

    resistance = 100.0
    zones = [{"level": resistance, "upper": resistance * 1.002,
               "lower": resistance * 0.998, "type": "RESISTANCE"}]

    # With flat TR, contraction_count will be 0 → Path B must be skipped
    result = scan_vcp("TEST", df, sr_zones=zones)
    assert result is None, (
        "VCP Path B must be rejected when contraction_count < 2; "
        f"got {result}"
    )


def test_path_a_rejected_without_progressive_contractions():
    """Path A (DRY coiled spring) needs >= 3 progressive contractions."""
    from engines.engine2 import scan_vcp
    import pandas as pd, numpy as np

    n = 200
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    # Uptrend above 200 SMA with narrowing range in last 5 bars
    # but TR alternates (not progressive) → is_progressive=False
    close = np.linspace(70.0, 98.0, n)
    high  = close.copy()
    low   = close.copy()
    volume = np.full(n, 500_000.0)

    # Make last 5 bars oscillate ATR (not progressively tighter)
    for i in range(-5, 0):
        factor = 1.02 if i % 2 == 0 else 1.005
        high[i]  = close[i] * factor
        low[i]   = close[i] / factor
        volume[i] = 100_000.0          # dry-up volume

    df = pd.DataFrame({"Close": close, "High": high, "Low": low,
                       "Open": close, "Volume": volume}, index=dates)
    resistance = 100.0
    zones = [{"level": resistance, "upper": resistance * 1.005,
               "lower": resistance * 0.995, "type": "RESISTANCE"}]

    result = scan_vcp("TEST", df, sr_zones=zones)
    # Path A requires contraction_count >= 3 AND is_progressive=True
    # With alternating ATR the is_progressive flag will be False
    assert result is None or result.get("setup_type") != "VCP" or not result.get("is_progressive_tightening"), \
        "Path A should not pass without progressive contractions"
```

**Step 2: Run tests to verify they fail**
```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine2_tightening.py::test_path_b_rejected_without_contractions tests/test_engine2_tightening.py::test_path_a_rejected_without_progressive_contractions -v
```
Expected: FAIL (tests may pass trivially before the gate — that is fine; the gate test becomes meaningful after implementation).

**Step 3: Update the import in engine2.py**

Find the existing import line (line 39):
```python
from constants import TARGET_RR, ATR_STOP_MULTIPLIER, VCP_ATR_CONTRACTION_THRESHOLD, VCP_TIGHT_RANGE_5D_PCT
```

Replace with:
```python
from constants import (
    TARGET_RR, ATR_STOP_MULTIPLIER, VCP_ATR_CONTRACTION_THRESHOLD,
    VCP_TIGHT_RANGE_5D_PCT, VCP_MIN_CONTRACTIONS_STRICT, VCP_MIN_CONTRACTIONS_RELAXED,
)
```

**Step 4: Add contraction gate to Path B**

Find the line (around line 833):
```python
if confirmed_breakout and bk_zone is not None:
```

Change to:
```python
if confirmed_breakout and bk_zone is not None and contraction_count >= VCP_MIN_CONTRACTIONS_RELAXED:
```

**Step 5: Add contraction gate to Path C**

Find (around line 916):
```python
if is_trendline_breakout and trendline_data is not None:
```

Change to:
```python
if is_trendline_breakout and trendline_data is not None and contraction_count >= VCP_MIN_CONTRACTIONS_RELAXED:
```

**Step 6: Add contraction gate to Path D**

Find (around line 990):
```python
            if is_kde_breakout:
```

Change to:
```python
            if is_kde_breakout and contraction_count >= VCP_MIN_CONTRACTIONS_RELAXED:
```

**Step 7: Add progressive contraction gate to Path A**

Find the block that ends the ATR compression check (around line 1151):
```python
        # Note: atr20_clean always has ≥46 values when len(data)≥60, so the else
        # branch is unreachable in production — atr_compressed is always set above.
```

Immediately after that comment, add:
```python
        # Progressive contraction structure gate (Path A)
        if not (contraction_count >= VCP_MIN_CONTRACTIONS_STRICT and is_progressive):
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - Path A requires {VCP_MIN_CONTRACTIONS_STRICT} "
                    f"progressive contractions "
                    f"(got {contraction_count}, is_progressive={is_progressive})"
                )
            return None
```

**Step 8: Run tests**
```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_engine2_tightening.py -v
python -m pytest tests/ -v --tb=short -q   # full suite — confirm no regressions
```

**Step 9: Commit**
```bash
git add engines/engine2.py tests/test_engine2_tightening.py
git commit -m "feat(engine2): gate VCP Paths B/C/D on contraction_count>=2, Path A on >=3 progressive"
```

---

## Task 3: Convert LCE engine to mini-breakout trigger

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine9_low_cheat.py`
- Modify: `swing-trading-dashboard/backend/tests/test_engine9_lce.py`

**Background**
The existing LCE detects quiet coiling *below* resistance and enters pre-breakout. We convert it to trigger only when the current bar's close is **above the prior bar's high** (micro-resistance break) **with at-average volume**. Trend filter upgrades from EMA20 → SMA50. Range contraction condition (step 3) is removed — an expanding range is expected on a breakout bar.

**Step 1: Rewrite the test helper and update failing tests**

Replace the entire `inject_lce_conditions` helper and affected tests in `tests/test_engine9_lce.py`:

```python
def inject_lce_conditions(df, resistance_level, vol_breakout=True):
    """
    Configure last bars for mini-breakout LCE conditions:
    - Price below resistance but within 3%
    - Higher low (recent 3-bar low > prior 5-bar low)
    - Close > prior bar's high (micro-resistance break)
    - Volume >= 20-day average
    """
    n = len(df)
    close = df["Close"].values.copy()
    high  = df["High"].values.copy()
    low   = df["Low"].values.copy()
    vol   = df["Volume"].values.copy()

    avg_vol = 1_000_000.0  # baseline (matches make_uptrend_df)

    # Prior 5 bars — lower lows (structural setup)
    for i in range(-8, -3):
        p = resistance_level * 0.972
        close[i] = p
        high[i]  = p * 1.008
        low[i]   = p * 0.992
        vol[i]   = avg_vol * 0.7  # quiet

    # Bar t-1: prior bar whose high we must exceed
    prior_high = resistance_level * 0.985
    close[-2] = prior_high * 0.998   # close just below its own high
    high[-2]  = prior_high           # this is the micro-resistance level
    low[-2]   = prior_high * 0.992
    vol[-2]   = avg_vol * 0.8

    # Bar t (today): breakout bar — close above prior_high with volume
    p = prior_high * 1.005            # close above yesterday's high
    close[-1] = p
    high[-1]  = p * 1.003
    low[-1]   = p * 0.997
    vol[-1]   = avg_vol * 1.1 if vol_breakout else avg_vol * 0.5

    df["Close"]  = close
    df["High"]   = high
    df["Low"]    = low
    df["Volume"] = vol


def test_valid_lce_returns_setup():
    """Valid mini-breakout LCE conditions return a setup dict."""
    df = make_uptrend_df(n=120, end_price=98.0)
    resistance = 100.0
    inject_lce_conditions(df, resistance, vol_breakout=True)
    zones = [make_resistance_zone(resistance)]

    result = scan_lce("TEST", df, zones=zones)
    assert result is not None, "Expected setup dict, got None"
    assert result["setup_type"] == "LCE"
    assert result["entry"] > 0
    assert result["stop_loss"] < result["entry"]
    assert result["take_profit"] > result["entry"]
    assert result["rr"] >= 1.0


def test_volume_below_average_rejected():
    """Volume below 1× 20-day average returns None (breakout needs volume)."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_breakout=False)
    zones = [make_resistance_zone(100.0)]
    assert scan_lce("TEST", df, zones=zones) is None


def test_close_below_prior_high_rejected():
    """If close does not exceed prior bar's high, LCE returns None."""
    df = make_uptrend_df(n=120, end_price=98.0)
    inject_lce_conditions(df, 100.0, vol_breakout=True)
    # Force today's close below prior bar's high
    prior_high = float(df["High"].iloc[-2])
    df.iloc[-1, df.columns.get_loc("Close")] = prior_high * 0.997
    zones = [make_resistance_zone(100.0)]
    assert scan_lce("TEST", df, zones=zones) is None


# Remove test_volume_expansion_rejected — that test verified old (inverted) logic.
# It is replaced by test_volume_below_average_rejected above.
```

**Step 2: Run tests to confirm they fail**
```bash
python -m pytest tests/test_engine9_lce.py -v
```
Expected: several FAIL (helpers updated, implementation not yet changed).

**Step 3: Rewrite engine9_low_cheat.py**

Replace the imports block at the top:
```python
from indicators import atr as _atr, ema as _ema, sma as _sma
from constants import (
    ATR_STOP_MULTIPLIER,
    TR_WINDOW,
    SMA_LONG,          # 50
    LCE_MAX_DISTANCE_PCT,
    LCE_MAX_RISK_PCT,
    LCE_BREAKOUT_VOL_RATIO,   # new — replaces LCE_VOL_CONTRACTION_RATIO
)
```

Replace conditions **3** (range contraction) and **5+6** (trend + volume) in `scan_lce()`:

Remove the range contraction block (conditions 3, lines ~97-107 in original). The new body after the proximity check becomes:

```python
        # ── 3. Higher low ─────────────────────────────────────────────────────
        if n < 11:
            return None
        recent_low = float(np.min(low_arr[-3:]))
        prior_low  = float(np.min(low_arr[-8:-3]))
        if recent_low <= prior_low:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — no higher low ({recent_low:.2f} ≤ {prior_low:.2f})")
            return None

        # ── 4. Trend: close >= SMA50 ──────────────────────────────────────────
        sma50_s   = _sma(close_s, SMA_LONG)
        sma50_val = sma50_s.iloc[-1]
        sma50     = float(sma50_val.item() if hasattr(sma50_val, "item") else sma50_val)
        if np.isnan(sma50) or lc < sma50:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — below SMA50 ({lc:.2f} < {sma50:.2f})")
            return None

        # ── 5. Mini-breakout: close > prior bar's high ────────────────────────
        if n < 2:
            return None
        prev_bar_high = float(high_arr[-2])
        if lc <= prev_bar_high:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — close {lc:.2f} not above prior high {prev_bar_high:.2f}")
            return None

        # ── 6. Volume: >= 1× 20-day average (momentum confirmation) ──────────
        vol_lookback = min(21, n - 1)
        vol_avg_20   = float(np.mean(volume_arr[-vol_lookback - 1:-1])) if vol_lookback > 0 else 0.0
        if vol_avg_20 <= 0:
            return None
        lvol_today = float(volume_arr[-1])
        vol_ratio  = lvol_today / vol_avg_20
        if vol_ratio < LCE_BREAKOUT_VOL_RATIO:
            if debug:
                print(f"Engine 9 LCE {ticker}: REJECTED — vol ratio {vol_ratio:.2f} < {LCE_BREAKOUT_VOL_RATIO:.2f}")
            return None
```

Also update the return dict (replace old vol fields):
```python
            "is_vol_surge":               vol_ratio >= 1.5,
            "volume_ratio":               round(vol_ratio, 2),
            # remove "tight_range_5d" — no longer checked
```

Remove `tight_range_5d` from the return dict. Change `signal` from `"CHEAT"` to `"BRK"`.

**Step 4: Run tests**
```bash
python -m pytest tests/test_engine9_lce.py -v
python -m pytest tests/ -v --tb=short -q
```
Expected: all pass.

**Step 5: Commit**
```bash
git add engines/engine9_low_cheat.py tests/test_engine9_lce.py
git commit -m "feat(engine9): convert LCE to mini-breakout trigger — close>prev_high, vol>=avg, SMA50 trend"
```

---

## Task 4: Harden RES_BREAKOUT — volatility-aware decisive close + 5-bar launchpad

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine6.py`
- Modify: `swing-trading-dashboard/backend/tests/test_engine6.py`

**Background**
Two changes:
1. `_LAUNCHPAD_BARS`: 3 → 5. Pre-breakout consolidation must span 5 tight bars, not 3.
2. Decisive close threshold: from `zone_upper × 1.005` (fixed 0.5%) to `zone_upper + max(0.007 × zone_upper, 0.25 × ATR)`. This adapts to volatility — high-ATR stocks need a bigger close above the zone.

**Step 1: Update the test helper to set up 5 launchpad bars**

In `tests/test_engine6.py`, find `setup_full_breakout`. The launchpad section sets bars at `brk_idx-3, -2, -1`. Extend it to cover `brk_idx-5, -4, -3, -2, -1`:

```python
    # ── Launchpad bars (brk_idx-5 through brk_idx-1) ─────────────────────
    for offset in range(1, 6):   # was range(1, 4)
        lp_idx = brk_idx - offset
        if lp_idx < 0:
            continue
        df.iloc[lp_idx, df.columns.get_loc("High")]   = zone_upper * 0.999
        df.iloc[lp_idx, df.columns.get_loc("Low")]    = zone_upper * 0.985
        df.iloc[lp_idx, df.columns.get_loc("Close")]  = zone_upper * 0.993
        df.iloc[lp_idx, df.columns.get_loc("Volume")] = 1_000_000.0
```

Also update the breakout bar's close to clear the new decisive threshold. ATR for `make_uptrend_df(n=300, base_price=100)` is roughly 2.0, so `0.25 × ATR ≈ 0.5`. Max of 0.7% and 0.5 on a $100 stock → `0.7` points. Set close to `zone_upper + 1.0` to safely clear:

```python
    # Breakout bar close must clear max(0.7%, 0.25×ATR) above zone_upper
    brk_close = zone_upper + max(0.007 * zone_upper, 0.25 * 2.0) + 0.20
```

**Step 2: Write a new failing test for the decisive close threshold**

```python
def test_decisive_close_below_atr_threshold_rejected():
    """Breakout close that clears 0.5% but not max(0.7%, 0.25×ATR) is rejected."""
    df = make_uptrend_df(n=300, base_price=100.0)
    zone = make_resistance_zone(100.0, atr=2.0)
    zone_upper = zone["upper"]   # ≈ 100.2

    n      = len(df)
    brk_idx = n - 1
    # Launchpad: 5 bars
    for offset in range(1, 6):
        lp = brk_idx - offset
        df.iloc[lp, df.columns.get_loc("High")]   = zone_upper * 0.999
        df.iloc[lp, df.columns.get_loc("Low")]    = zone_upper * 0.985
        df.iloc[lp, df.columns.get_loc("Close")]  = zone_upper * 0.993
        df.iloc[lp, df.columns.get_loc("Volume")] = 1_000_000.0

    # Breakout close: 0.6% above zone_upper (clears old 0.5% but not new max(0.7%,0.25×ATR)=0.7%)
    brk_close = zone_upper * 1.006
    brk_high  = brk_close * 1.005
    df.iloc[brk_idx, df.columns.get_loc("Close")]  = brk_close
    df.iloc[brk_idx, df.columns.get_loc("High")]   = brk_high
    df.iloc[brk_idx, df.columns.get_loc("Low")]    = zone_upper * 0.995
    df.iloc[brk_idx, df.columns.get_loc("Volume")] = 2_000_000.0  # surge

    result = scan_resistance_breakout("TEST", df, zones=[zone])
    assert result is None, f"Expected rejection for weak decisive close, got {result}"
```

**Step 3: Run tests to confirm failure**
```bash
python -m pytest tests/test_engine6.py -v
```

**Step 4: Update engine6.py**

Update the module-level constants block:
```python
# Remove:
_DECISIVE_CLOSE_MIN_PCT  = 0.005
_LAUNCHPAD_BARS          = 3

# Add (import from constants instead):
from constants import (
    TARGET_RR, VOL_SURGE_MULTIPLIER,
    RES_LAUNCHPAD_BARS, RES_DECISIVE_MIN_PCT, RES_DECISIVE_ATR_FACTOR,
)

_VOL_SURGE_THRESHOLD     = VOL_SURGE_MULTIPLIER
_MAX_DAYS_LOOKBACK       = 3
_MAX_EXTEND_PCT          = 0.05
_CLOSE_POSITION_MIN      = 0.70
_LAUNCHPAD_BARS          = RES_LAUNCHPAD_BARS        # 5
_LAUNCHPAD_MAX_HIGH_PCT  = 1.03
_LAUNCHPAD_MAX_RANGE_ATR = 1.5
```

Replace the decisive close check (Rule 2a) in the loop body:

Old:
```python
                # Rule 2a — Decisive close: ≥ 0.5% above zone
                if brk_close <= zone_upper * (1 + _DECISIVE_CLOSE_MIN_PCT):
```

New:
```python
                # Rule 2a — Volatility-aware decisive close: max(0.7%, 0.25×ATR) above zone
                decisive_min = max(RES_DECISIVE_MIN_PCT * zone_upper, RES_DECISIVE_ATR_FACTOR * latr)
                if brk_close <= zone_upper + decisive_min:
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - Decisive close failed "
                            f"({brk_close:.2f} <= {zone_upper + decisive_min:.2f}, "
                            f"need >{decisive_min:.2f} above zone [{RES_DECISIVE_MIN_PCT:.1%} or "
                            f"{RES_DECISIVE_ATR_FACTOR}×ATR={RES_DECISIVE_ATR_FACTOR*latr:.2f}])"
                        )
                    continue
```

**Step 5: Run tests**
```bash
python -m pytest tests/test_engine6.py -v
python -m pytest tests/ --tb=short -q
```

**Step 6: Commit**
```bash
git add engines/engine6.py tests/test_engine6.py
git commit -m "feat(engine6): volatility-aware decisive close max(0.7%,0.25xATR), extend launchpad to 5 bars"
```

---

## Task 5: Harden BASE engine — vol threshold + prior range contraction

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine5.py`
- Modify: `swing-trading-dashboard/backend/tests/test_engine5.py`

**Background**
Two changes in both `scan_flat_base` and `scan_cup_handle`:
1. BRK signal vol threshold: `vol_ratio >= 1.2` → `vol_ratio >= BASE_BRK_MIN_VOL_RATIO` (1.5).
2. BRK signal now also requires prior range contraction: the last 5 bars' avg range must be below the prior 20 bars' avg range. This filters noisy breakouts that spike out of an erratic box.

**Step 1: Write failing tests**

Add to `tests/test_engine5.py`:

```python
def test_flat_base_brk_rejected_weak_volume():
    """BRK signal in flat base requires vol_ratio >= 1.5, not 1.2."""
    from engines.engine5 import scan_flat_base
    n = 200
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    # Stage 2 uptrend — SMA50 > SMA200
    close  = np.linspace(60.0, 100.0, n)
    high   = close * 1.015
    low    = close * 0.985
    volume = np.full(n, 1_000_000.0)
    df = pd.DataFrame({"Close": close, "High": high, "Low": low,
                       "Open": close, "Volume": volume}, index=dates)

    # Box ceiling = max of last 30 bars = ~100; set today to 1.3× avg (above old 1.2 threshold)
    ceiling = float(high[-30:].max())
    df.iloc[-1, df.columns.get_loc("Close")]  = ceiling * 1.003
    df.iloc[-1, df.columns.get_loc("High")]   = ceiling * 1.005
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_300_000.0  # 1.3× avg — old pass, new fail

    result = scan_flat_base("TEST", df)
    assert result is None or result.get("signal") != "BRK", \
        "BRK should be rejected with vol_ratio 1.3 (new threshold is 1.5)"


def test_flat_base_brk_rejected_noisy_range():
    """BRK signal in flat base requires prior range contraction."""
    from engines.engine5 import scan_flat_base
    n = 200
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close  = np.linspace(60.0, 100.0, n)
    # Make last 5 bars WIDER range than prior 20 (noisy breakout)
    high   = close * 1.015
    low    = close * 0.985
    for i in range(-5, 0):
        high[i] = close[i] * 1.04   # wider range → no contraction
        low[i]  = close[i] * 0.96
    volume = np.full(n, 1_000_000.0)
    df = pd.DataFrame({"Close": close, "High": high, "Low": low,
                       "Open": close, "Volume": volume}, index=dates)

    ceiling = float(df["High"].values[-30:].max())
    df.iloc[-1, df.columns.get_loc("Close")]  = ceiling * 1.003
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0  # passes vol threshold

    result = scan_flat_base("TEST", df)
    assert result is None or result.get("signal") != "BRK", \
        "BRK should be rejected when range is expanding (noisy base breakout)"
```

**Step 2: Run tests to confirm failure**
```bash
python -m pytest tests/test_engine5.py::test_flat_base_brk_rejected_weak_volume tests/test_engine5.py::test_flat_base_brk_rejected_noisy_range -v
```

**Step 3: Update engine5.py import**

Add to the top-level import from constants:
```python
from constants import TARGET_RR, BASE_BRK_MIN_VOL_RATIO
```

**Step 4: Update `scan_flat_base` — BRK signal block**

Find in `scan_flat_base` (around line 180):
```python
        if lc > ceiling and vol_ratio >= 1.2:
            signal = "BRK"
```

Replace with:
```python
        # Prior range contraction: last 5-bar avg range < prior 20-bar avg range
        recent_ranges = (high_arr[-5:]  - low_arr[-5:]).mean()
        prior_ranges  = (high_arr[-25:-5] - low_arr[-25:-5]).mean() if len(high_arr) >= 25 else recent_ranges
        base_range_contraction = prior_ranges > 0 and recent_ranges < prior_ranges

        if lc > ceiling and vol_ratio >= BASE_BRK_MIN_VOL_RATIO and base_range_contraction:
            signal = "BRK"
```

**Step 5: Update `scan_cup_handle` — BRK signal block**

Find (around line 366):
```python
        if lc > handle_high_price and vol_ratio >= 1.2:
            signal = "BRK"
```

Replace with:
```python
        # Prior range contraction: last 5-bar handle range < handle average range
        cup_high_arr = high_arr[-(handle_bars + 20):-handle_bars] if handle_bars + 20 < n else high_arr[:-handle_bars]
        cup_low_arr  = low_arr[-(handle_bars + 20):-handle_bars]  if handle_bars + 20 < n else low_arr[:-handle_bars]
        pre_handle_range = (cup_high_arr - cup_low_arr).mean() if len(cup_high_arr) > 0 else 0.0
        handle_high_arr  = high_arr[-handle_bars:] if handle_bars > 0 else high_arr[-1:]
        handle_low_arr   = low_arr[-handle_bars:]  if handle_bars > 0 else low_arr[-1:]
        handle_avg_range = (handle_high_arr - handle_low_arr).mean()
        base_range_contraction = pre_handle_range > 0 and handle_avg_range < pre_handle_range

        if lc > handle_high_price and vol_ratio >= BASE_BRK_MIN_VOL_RATIO and base_range_contraction:
            signal = "BRK"
```

**Step 6: Run tests**
```bash
python -m pytest tests/test_engine5.py -v
python -m pytest tests/ --tb=short -q
```

**Step 7: Commit**
```bash
git add engines/engine5.py tests/test_engine5.py
git commit -m "feat(engine5): raise BRK vol to 1.5x, require prior range contraction before BRK signal"
```

---

## Task 6: Full regression run and final validation

**Step 1: Run the complete test suite**
```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all tests pass. If any pre-existing test breaks, read the error — it will point to a threshold that the test was hard-coding (e.g., `vol_ratio >= 1.2`). Update the test helper to match the new threshold.

**Step 2: Smoke-test the engines directly**
```bash
python -c "
import pandas as pd, numpy as np
from engines.engine2 import scan_vcp
from engines.engine9_low_cheat import scan_lce
from engines.engine5 import scan_base_pattern
from engines.engine6 import scan_resistance_breakout
print('All engines import cleanly')
"
```
Expected: no ImportError or NameError.

**Step 3: Verify constants are exported**
```bash
python -c "
from constants import (
    MIN_ATR_PCT, VCP_MIN_CONTRACTIONS_STRICT, VCP_MIN_CONTRACTIONS_RELAXED,
    LCE_BREAKOUT_VOL_RATIO, BASE_BRK_MIN_VOL_RATIO,
    RES_LAUNCHPAD_BARS, RES_DECISIVE_MIN_PCT, RES_DECISIVE_ATR_FACTOR,
)
print(f'MIN_ATR_PCT={MIN_ATR_PCT}  VCP_STRICT={VCP_MIN_CONTRACTIONS_STRICT}  '
      f'VCP_RLX={VCP_MIN_CONTRACTIONS_RELAXED}  LCE_VOL={LCE_BREAKOUT_VOL_RATIO}  '
      f'BASE_VOL={BASE_BRK_MIN_VOL_RATIO}  RES_LP={RES_LAUNCHPAD_BARS}')
"
```
Expected: `MIN_ATR_PCT=2.5  VCP_STRICT=3  VCP_RLX=2  LCE_VOL=1.0  BASE_VOL=1.5  RES_LP=5`

**Step 4: Final commit**
```bash
git add -A
git commit -m "test(hardening): full regression — all engines import cleanly, suite green"
```
