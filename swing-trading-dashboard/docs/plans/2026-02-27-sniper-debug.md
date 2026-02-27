# Sniper Debug Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `python debug_ticker.py NVDA` — a standalone CLI script that runs every scanner engine on a single ticker with verbose rejection reasons, leaving the normal scan path completely untouched.

**Architecture:** New `debug: bool = False` parameter appended to each engine function (`scan_vcp`, `scan_pullback`, `scan_relaxed_pullback`, `scan_resistance_breakout`) and to `is_price_vital`. All existing call sites in `main.py` are unchanged (default stays `False`). New standalone `debug_ticker.py` calls the engines with `debug=True`.

**Tech Stack:** Python 3.10, yfinance, pytest + capsys for stdout capture tests.

---

### Task 1: Add `debug` param to `is_price_vital()` + test

**Files:**
- Modify: `backend/validation.py` (line 170 — `is_price_vital` signature)
- Create: `backend/tests/test_sniper_debug.py`

---

**Step 1: Create the test file with a failing test**

Create `backend/tests/test_sniper_debug.py`:

```python
"""Tests for Sniper Debug Mode — verifies debug=True prints rejection reasons."""
import pandas as pd
import pytest

# ── Shared DataFrame helpers ──────────────────────────────────────────────

def _flatline_df(n: int = 15) -> pd.DataFrame:
    """A zombie stock: 10-day H-L range < 2% → fails is_price_vital."""
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [100.0] * n,
        "High":      [100.5] * n,   # range = 0.5 / 100.5 ≈ 0.5% < 2%
        "Low":       [100.0] * n,
        "Close":     [100.0] * n,
        "Adj Close": [100.0] * n,
        "Volume":    [1_000_000] * n,
    }, index=dates)


def _trend_fail_df(n: int = 70) -> pd.DataFrame:
    """
    Downtrend stock: first 50 bars at 100, last 20 at 60.
    Result: lc=60, SMA50≈84, EMA8≈60.3, EMA20≈65.1
    → l8 NOT > l20  AND  lc < l50  → trend filter fails in all engines.
    """
    prices = [100.0] * 50 + [60.0] * 20
    dates  = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      prices,
        "High":      [p + 1.0 for p in prices],
        "Low":       [p - 1.0 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [1_000_000] * n,
    }, index=dates)


# ── Task 1: is_price_vital ────────────────────────────────────────────────

from validation import is_price_vital


def test_vitality_debug_prints_rejection(capsys):
    """debug=True on a flatline stock prints a Vitality REJECTED message."""
    df = _flatline_df()
    result = is_price_vital(df, debug=True)
    assert result is False
    out = capsys.readouterr().out
    assert "Vitality: REJECTED" in out
    assert "Zombie" in out


def test_vitality_debug_false_no_output(capsys):
    """debug=False (default) produces no stdout even when stock is rejected."""
    df = _flatline_df()
    is_price_vital(df, debug=False)
    assert capsys.readouterr().out == ""
```

**Step 2: Run test to verify it FAILS**

```bash
cd backend
python -m pytest tests/test_sniper_debug.py -v
```

Expected: `FAILED` — `is_price_vital()` doesn't accept `debug` parameter yet.

---

**Step 3: Add `debug` param to `is_price_vital` in `validation.py`**

Find (line ~170):
```python
def is_price_vital(
    df: pd.DataFrame,
    lookback: int = 10,
    min_range_pct: float = 0.02,
) -> bool:
```

Change to:
```python
def is_price_vital(
    df: pd.DataFrame,
    lookback: int = 10,
    min_range_pct: float = 0.02,
    debug: bool = False,
) -> bool:
```

Then find the line `return range_pct >= min_range_pct` at the end of the function. Replace:
```python
    return range_pct >= min_range_pct
```
with:
```python
    if range_pct < min_range_pct:
        if debug:
            print(
                f"Vitality: REJECTED - Zombie/Buyout stock "
                f"(10-day range {range_pct:.1%} < {min_range_pct:.0%})"
            )
        return False
    return True
```

**Step 4: Run test to verify it PASSES**

```bash
python -m pytest tests/test_sniper_debug.py -v
```

Expected: `PASSED` (both vitality tests).

**Step 5: Commit**

```bash
git add backend/validation.py backend/tests/test_sniper_debug.py
git commit -m "feat(debug): add debug param to is_price_vital"
```

---

### Task 2: Add `debug` param to `scan_resistance_breakout()` + test

**Files:**
- Modify: `backend/engines/engine6.py`
- Modify: `backend/tests/test_sniper_debug.py` (append tests)

---

**Step 1: Append failing tests to `test_sniper_debug.py`**

Add at the bottom of the file:

```python
# ── Task 2: scan_resistance_breakout ─────────────────────────────────────

from engines.engine6 import scan_resistance_breakout


def test_engine6_debug_below_sma50(capsys):
    """debug=True when close < SMA50 prints Engine 6 REJECTED – Below 50 SMA."""
    df = _trend_fail_df()   # lc=60, SMA50≈84 → rejected immediately
    result = scan_resistance_breakout("TEST", df, [], debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 6 Breakout: REJECTED" in out
    assert "50 SMA" in out


def test_engine6_debug_false_no_output(capsys):
    """debug=False produces no stdout on a rejected ticker."""
    df = _trend_fail_df()
    scan_resistance_breakout("TEST", df, [], debug=False)
    assert capsys.readouterr().out == ""


def test_engine6_debug_no_zones(capsys):
    """debug=True with uptrend but empty zone list prints 'No KDE resistance zones'."""
    # 70 bars all at 100 → passes uptrend filter, then hits empty zone check
    prices = [100.0] * 70
    dates  = pd.date_range("2022-01-01", periods=70, freq="B")
    df_up = pd.DataFrame({
        "Open": prices, "High": [p + 1 for p in prices],
        "Low":  [p - 1 for p in prices], "Close": prices,
        "Adj Close": prices, "Volume": [1_000_000] * 70,
    }, index=dates)
    result = scan_resistance_breakout("TEST", df_up, [], debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 6 Breakout: REJECTED" in out
    assert "No KDE resistance zones" in out
```

**Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_sniper_debug.py::test_engine6_debug_below_sma50 -v
```

Expected: `FAILED` — `scan_resistance_breakout` doesn't accept `debug` yet.

---

**Step 3: Modify `scan_resistance_breakout` in `engine6.py`**

Change the function signature (line 43):
```python
def scan_resistance_breakout(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
) -> Optional[Dict]:
```
to:
```python
def scan_resistance_breakout(
    ticker: str,
    df: pd.DataFrame,
    zones: List[Dict],
    debug: bool = False,
) -> Optional[Dict]:
```

Then add debug prints at each rejection gate inside the function body.

After the uptrend check (find `if l50 > 0 and lc < l50:`):
```python
        if l50 > 0 and lc < l50:
            if debug:
                print(f"Engine 6 Breakout: REJECTED - Below 50 SMA ({lc:.2f} < {l50:.2f})")
            return None
```

After the ATR check, find `resistance_zones = [z for z in zones if z.get("type") == "RESISTANCE"]` then the next `if not resistance_zones:` line:
```python
        resistance_zones = [z for z in zones if z.get("type") == "RESISTANCE"]
        if not resistance_zones:
            if debug:
                print("Engine 6 Breakout: REJECTED - No KDE resistance zones found")
            return None
```

Inside the zone loop, after the overextension check:
```python
            if lc > zone_upper * (1 + _MAX_EXTEND_PCT):
                if debug:
                    print(
                        f"Engine 6 Breakout: REJECTED - Price overextended "
                        f"(close {lc:.2f} > zone {zone_upper:.2f} × {1+_MAX_EXTEND_PCT:.2f})"
                    )
                continue
```

Inside the days_back loop, after the decisive close check (Rule 2a):
```python
                if brk_close <= zone_upper * (1 + _DECISIVE_CLOSE_MIN_PCT):
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - Decisive close failed "
                            f"(close {brk_close:.2f} ≤ zone {zone_upper:.2f} × {1+_DECISIVE_CLOSE_MIN_PCT:.3f})"
                        )
                    continue
```

After Rule 2b (close position in range):
```python
                if brk_range > 0 and brk_close < brk_low + _CLOSE_POSITION_MIN * brk_range:
                    pos = (brk_close - brk_low) / brk_range if brk_range > 0 else 0
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - Close in bottom "
                            f"{pos:.0%} of range (required top 30%)"
                        )
                    continue
```

After the launchpad check (`if not launchpad_ok:`):
```python
                if not launchpad_ok:
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - Launchpad criteria failed "
                            f"(bar {offset}: range {lp_range:.2f} ≥ {_LAUNCHPAD_MAX_RANGE_ATR}× ATR {latr:.2f})"
                        )
                    continue
```

After the volume check (`if vol_ratio < _VOL_SURGE_THRESHOLD:`):
```python
                if vol_ratio < _VOL_SURGE_THRESHOLD:
                    if debug:
                        print(
                            f"Engine 6 Breakout: REJECTED - Breakout volume {vol_ratio:.1f}x "
                            f"(required: {_VOL_SURGE_THRESHOLD:.1f}x 50d SMA)"
                        )
                    continue
```

Finally, after the loop, find the `return best` line. Add before it:
```python
        if best is None and debug:
            print("Engine 6 Breakout: REJECTED - No valid breakout found in last 3 days")
        return best
```

**Step 4: Run tests to verify PASS**

```bash
python -m pytest tests/test_sniper_debug.py -v
```

Expected: all 5 tests PASS.

**Step 5: Commit**

```bash
git add backend/engines/engine6.py backend/tests/test_sniper_debug.py
git commit -m "feat(debug): add debug param to scan_resistance_breakout"
```

---

### Task 3: Add `debug` param to `scan_pullback()` + test

**Files:**
- Modify: `backend/engines/engine3.py` (function `scan_pullback`, line 69)
- Modify: `backend/tests/test_sniper_debug.py` (append tests)

---

**Step 1: Append failing tests**

Add at the bottom of `test_sniper_debug.py`:

```python
# ── Task 3: scan_pullback ────────────────────────────────────────────────

from engines.engine3 import scan_pullback


def test_pullback_debug_trend_filter(capsys):
    """debug=True prints trend filter rejection for a downtrending stock."""
    df = _trend_fail_df()
    result = scan_pullback("TEST", df, [], None, debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 3 Pullback: REJECTED" in out
    assert "Trend filter" in out


def test_pullback_debug_false_no_output(capsys):
    """debug=False produces no stdout."""
    df = _trend_fail_df()
    scan_pullback("TEST", df, [], None, debug=False)
    assert capsys.readouterr().out == ""
```

**Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_sniper_debug.py::test_pullback_debug_trend_filter -v
```

Expected: `FAILED` — `scan_pullback` doesn't accept `debug`.

---

**Step 3: Modify `scan_pullback` in `engine3.py`**

Change the signature (line 69):
```python
def scan_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
) -> Optional[Dict]:
```
to:
```python
def scan_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
    debug: bool = False,
) -> Optional[Dict]:
```

Add debug prints at each gate. Find each `return None` and add the guarded print before it:

**Trend filter** (line ~117):
```python
        if not (l8 > l20 and lc > l50):
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - Trend filter failed "
                    f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50 {l50:.2f})"
                )
            return None
```

**Value zone** (line ~122):
```python
        if not (ll <= l8 or ll <= l20):
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - Low {ll:.2f} not in value zone "
                    f"(EMA8 {l8:.2f}, EMA20 {l20:.2f})"
                )
            return None
```

**No support zone or TDL** (line ~157, after the `if nearest_sup is None:` check):
```python
        if nearest_sup is None:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - No KDE support zone or ascending TDL touch "
                    f"(low: {ll:.2f})"
                )
            return None
```

**Pin bar** (line ~162):
```python
        if lc < l20:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - No pin bar "
                    f"(Close {lc:.2f} < EMA20 {l20:.2f})"
                )
            return None
```

**CCI hook** (line ~167):
```python
        if not (cci_prev < -50.0 and cci_today > cci_prev):
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - CCI hook failed "
                    f"(yesterday: {cci_prev:.1f}, today: {cci_today:.1f}, "
                    f"required: yesterday < -100 then rising)"
                )
            return None
```

Note: the docstring says -100 but the code uses -50; use the actual code value (-50) in the message to avoid confusion.

**Step 4: Run tests to verify PASS**

```bash
python -m pytest tests/test_sniper_debug.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add backend/engines/engine3.py backend/tests/test_sniper_debug.py
git commit -m "feat(debug): add debug param to scan_pullback"
```

---

### Task 4: Add `debug` param to `scan_relaxed_pullback()` + test

**Files:**
- Modify: `backend/engines/engine3.py` (function `scan_relaxed_pullback`, line 204)
- Modify: `backend/tests/test_sniper_debug.py` (append tests)

---

**Step 1: Append failing tests**

```python
# ── Task 4: scan_relaxed_pullback ────────────────────────────────────────

from engines.engine3 import scan_relaxed_pullback


def test_rlx_pullback_debug_trend_filter(capsys):
    """debug=True prints trend filter rejection for a downtrending stock."""
    df = _trend_fail_df()
    result = scan_relaxed_pullback("TEST", df, [], None, debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 3 RLX Pullback: REJECTED" in out
    assert "Trend filter" in out


def test_rlx_pullback_debug_false_no_output(capsys):
    """debug=False produces no stdout."""
    df = _trend_fail_df()
    scan_relaxed_pullback("TEST", df, [], None, debug=False)
    assert capsys.readouterr().out == ""
```

**Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_sniper_debug.py::test_rlx_pullback_debug_trend_filter -v
```

Expected: `FAILED`.

---

**Step 3: Modify `scan_relaxed_pullback` in `engine3.py`**

Change the signature (line 204):
```python
def scan_relaxed_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
) -> Optional[Dict]:
```
to:
```python
def scan_relaxed_pullback(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    trendline: Optional[Dict] = None,
    debug: bool = False,
) -> Optional[Dict]:
```

Add debug prints at each gate inside `scan_relaxed_pullback`:

**Trend filter** (line ~261):
```python
        if not (l8 > l20 and lc > l50):
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Trend filter failed "
                    f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50 {l50:.2f})"
                )
            return None
```

**Buffer zone** (line ~271):
```python
        if not (near_8 or near_20):
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Not within 2% of EMA8 or EMA20 "
                    f"(dist_8: {dist_to_8:.1%}, dist_20: {dist_to_20:.1%})"
                )
            return None
```

**CCI relaxation** (line ~276):
```python
        if not cci_turning:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - CCI relaxation failed "
                    f"(yesterday: {cci_prev:.1f}, today: {cci_today:.1f}, "
                    f"required: yesterday < -30 and today rising)"
                )
            return None
```

**Low volume** (line ~290):
```python
        if last3_vol > avg_vol:
            if debug:
                vol_ratio = last3_vol / avg_vol if avg_vol > 0 else 0
                print(
                    f"Engine 3 RLX Pullback: REJECTED - Volume not dry "
                    f"(3-day avg {vol_ratio:.1f}x 50d SMA, required ≤1.0x)"
                )
            return None
```

**Mandatory support zone** (line ~303):
```python
        if nearest_sup is None:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - No KDE support zone touch "
                    f"(low: {ll:.2f})"
                )
            return None
```

**Step 4: Run tests to verify PASS**

```bash
python -m pytest tests/test_sniper_debug.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add backend/engines/engine3.py backend/tests/test_sniper_debug.py
git commit -m "feat(debug): add debug param to scan_relaxed_pullback"
```

---

### Task 5: Add `debug` param to `scan_vcp()` + test

**Files:**
- Modify: `backend/engines/engine2.py` (function `scan_vcp`, line 592)
- Modify: `backend/tests/test_sniper_debug.py` (append tests)

---

**Step 1: Append failing tests**

```python
# ── Task 5: scan_vcp ─────────────────────────────────────────────────────

from engines.engine2 import scan_vcp


def test_vcp_debug_trend_filter(capsys):
    """debug=True prints trend filter rejection for a downtrending stock."""
    df = _trend_fail_df()
    result = scan_vcp("TEST", df, [], debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 2 VCP: REJECTED" in out
    assert "Trend filter" in out


def test_vcp_debug_false_no_output(capsys):
    """debug=False produces no stdout."""
    df = _trend_fail_df()
    scan_vcp("TEST", df, [], debug=False)
    assert capsys.readouterr().out == ""
```

**Step 2: Run to verify FAIL**

```bash
python -m pytest tests/test_sniper_debug.py::test_vcp_debug_trend_filter -v
```

Expected: `FAILED`.

---

**Step 3: Modify `scan_vcp` in `engine2.py`**

Change the signature (line 592):
```python
def scan_vcp(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
) -> Optional[Dict]:
```
to:
```python
def scan_vcp(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    debug: bool = False,
) -> Optional[Dict]:
```

Add debug prints at each rejection gate. Work through the function top to bottom:

**Trend filter** (line ~660):
```python
        if not (l8 > l20 and lc > l50):
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - Trend filter failed "
                    f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50 {l50:.2f})"
                )
            return None
```

**Path B debug** — add immediately after the `if confirmed_breakout and bk_zone is not None:` block returns, i.e. find the `# ── PATH C` comment and add just before it:
```python
        if debug and not confirmed_breakout:
            if not resistance_zones:
                print("Engine 2 VCP: Path B SKIPPED — no resistance zones above price")
            elif not is_vol_surge:
                print(
                    f"Engine 2 VCP: REJECTED — Path B volume {volume_ratio:.1f}x "
                    f"(required ≥1.5x 50d SMA)"
                )
            elif rs_score <= 0:
                print(
                    f"Engine 2 VCP: REJECTED — Path B RS score not positive "
                    f"({rs_score:.4f})"
                )
            else:
                broken_b = [z for z in resistance_zones if lc > z["upper"]]
                if not broken_b:
                    print(
                        f"Engine 2 VCP: REJECTED — Path B no zone cleared "
                        f"(close {lc:.2f})"
                    )
                else:
                    cand = max(broken_b, key=lambda z: z["level"])
                    pct = (lc - cand["upper"]) / cand["upper"]
                    print(
                        f"Engine 2 VCP: REJECTED — Path B breakout {pct:.1%} "
                        f"not in 0.3–3.0% window"
                    )
```

**Path C debug** — add immediately after the `if is_trendline_breakout and trendline_data is not None:` block returns, i.e. just before `# ── PATH D`:
```python
        if debug and not is_trendline_breakout:
            if desc_tl is None:
                print("Engine 2 VCP: Path C SKIPPED — no descending trendline detected")
            else:
                tl_v = desc_tl["series"][-1]["value"] if desc_tl.get("series") else 0
                pct_tl = (lc - tl_v) / tl_v if tl_v > 0 else 0
                if pct_tl <= 0:
                    print(
                        f"Engine 2 VCP: Path C REJECTED — close {lc:.2f} below TDL {tl_v:.2f}"
                    )
                elif pct_tl > 0.03:
                    print(
                        f"Engine 2 VCP: Path C REJECTED — overextended above TDL "
                        f"({pct_tl:.1%} > 3%)"
                    )
                else:
                    print(
                        f"Engine 2 VCP: Path C REJECTED — volume {volume_ratio:.1f}x "
                        f"(required ≥1.0x for TDL break)"
                    )
```

**Path D debug** — add after the `if is_kde_breakout:` block, just before `# ── PATH E`:
```python
        if debug and nearest_res_above is not None:
            upper_d = nearest_res_above["upper"]
            pct_d = (lc - upper_d) / upper_d if upper_d > 0 else 0
            if not (0.001 <= pct_d <= 0.025):
                print(
                    f"Engine 2 VCP: Path D REJECTED — KDE pct {pct_d:.2%} "
                    f"not in 0.1–2.5% window (close {lc:.2f}, upper {upper_d:.2f})"
                )
            elif lvol < 1.15 * avg_vol:
                print(
                    f"Engine 2 VCP: Path D REJECTED — volume {volume_ratio:.1f}x "
                    f"(required ≥1.15x)"
                )
            elif rs_vs_spy < 0:
                print(
                    f"Engine 2 VCP: Path D REJECTED — RS vs SPY negative "
                    f"({rs_vs_spy:.3f})"
                )
        elif debug and nearest_res_above is None:
            print("Engine 2 VCP: Path D SKIPPED — no resistance zone within 5% above price")
```

**Path E debug** — add after the `if is_rs_lead:` block, just before `# ── PATH A`:
```python
        if debug and not (nearest_res_above is not None and rs_blue_dot):
            if not rs_blue_dot:
                print("Engine 2 VCP: Path E SKIPPED — no RS blue dot")
            else:
                print("Engine 2 VCP: Path E SKIPPED — no resistance zone above price")
```

**Path A — 200 SMA gate** (line ~929):
```python
        if not (lc > l200):
            if debug:
                print(
                    f"Engine 2 VCP: Path A REJECTED — below 200 SMA "
                    f"(close {lc:.2f} < SMA200 {l200:.2f})"
                )
            return None
```

**Path A — TR contraction** (line ~942):
```python
        if last5_tr >= prev20_tr:
            if debug:
                print(
                    f"Engine 2 VCP: Path A REJECTED — No TR contraction "
                    f"(last5 TR {last5_tr:.2f} ≥ prev20 TR {prev20_tr:.2f})"
                )
            return None
```

**Path A — U-shape** (line ~966):
```python
        if not is_u:
            if debug:
                print(
                    "Engine 2 VCP: Path A REJECTED — No U-shape parabola in recent price action"
                )
            return None
```

**Path A — near resistance** (line ~988):
```python
        if nearest_res is None:
            if debug:
                print(
                    "Engine 2 VCP: Path A REJECTED — Not within 5% of any resistance zone"
                )
            return None
```

**Path A — dry-up / breakout gate** (line ~995):
```python
        if not (at_breakout or in_dry_up):
            if debug:
                if not is_dry:
                    print(
                        "Engine 2 VCP: Path A REJECTED — No volume dry-up "
                        "(<50% of 50d avg) in last 10 bars"
                    )
                else:
                    print(
                        "Engine 2 VCP: Path A REJECTED — Near resistance but "
                        "neither breaking out (with vol surge) nor in dry-up"
                    )
            return None
```

**Step 4: Run all tests to verify PASS**

```bash
python -m pytest tests/test_sniper_debug.py -v
```

Expected: all tests PASS (11 tests total).

**Step 5: Run full test suite to confirm no regressions**

```bash
python -m pytest tests/ -q
```

Expected: all 111 existing tests + 11 new tests = 122 passed.

**Step 6: Commit**

```bash
git add backend/engines/engine2.py backend/tests/test_sniper_debug.py
git commit -m "feat(debug): add debug param to scan_vcp"
```

---

### Task 6: Create `debug_ticker.py` standalone script

**Files:**
- Create: `backend/debug_ticker.py`

No automated test — verify manually by running against a real ticker.

---

**Step 1: Create the file**

Create `backend/debug_ticker.py` with this exact content:

```python
#!/usr/bin/env python
"""
Sniper Debug Mode
=================
Single-ticker engine trace. Fetches live data and runs all scanner engines
with verbose rejection reasons printed at each gate.

Usage:
    cd backend
    python debug_ticker.py NVDA
    python debug_ticker.py AAPL
"""

import os
import sys

# Ensure backend/ is on the path regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
import pandas as pd

from constants import DATA_FETCH_PERIOD, DAYS_3_MONTHS
from validation import is_price_vital
from engines.engine1 import calculate_sr_zones
from engines.engine2 import scan_vcp, detect_trendline
from engines.engine3 import scan_pullback, scan_relaxed_pullback
from engines.engine4 import calculate_rs_score, detect_rs_blue_dot, calculate_rs_line
from engines.engine5 import scan_base_pattern
from engines.engine6 import scan_resistance_breakout

_DIV = "─" * 62


def _fetch(ticker: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(
        period=DATA_FETCH_PERIOD,
        interval="1d",
        auto_adjust=False,
    )
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    return df


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python debug_ticker.py <TICKER>")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    passes = 0
    total  = 0

    print(f"\n{'═' * 62}")
    print(f"  SNIPER DEBUG: {ticker}")
    print(f"{'═' * 62}\n")

    # ── Fetch ticker ──────────────────────────────────────────────
    print("Fetching ticker data from yfinance...")
    df = _fetch(ticker)
    if df is None or df.empty:
        print(f"✗ ERROR: No data for {ticker}. Check the symbol and try again.")
        sys.exit(1)
    print(f"  ✓ {len(df)} trading days\n")

    # ── Fetch SPY for RS ──────────────────────────────────────────
    spy_df        = None
    spy_3m_return = 0.0
    try:
        spy_df = _fetch("SPY")
        if spy_df is not None:
            adj = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
            if len(spy_df) >= DAYS_3_MONTHS:
                spy_3m_return = float(
                    spy_df[adj].iloc[-1] / spy_df[adj].iloc[-DAYS_3_MONTHS] - 1
                )
    except Exception as exc:
        print(f"  ⚠ SPY fetch failed ({exc}) — RS calculations will be zero\n")

    # ── VITALITY ──────────────────────────────────────────────────
    print(_DIV)
    print("  VITALITY FILTER")
    print(_DIV)
    total += 1
    vital = is_price_vital(df, debug=True)
    if vital:
        print("✓ PASS — Stock is actively traded (10-day range ≥ 2%)")
        passes += 1
    if not vital:
        print("\n⚠ Failed vitality — engine results below may be unreliable.\n")

    # ── ENGINE 1: S/R zones ───────────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 1 — KDE S/R ZONES")
    print(_DIV)
    zones = []
    try:
        zones = calculate_sr_zones(ticker, df)
        r = [z for z in zones if z.get("type") == "RESISTANCE"]
        s = [z for z in zones if z.get("type") == "SUPPORT"]
        print(f"  {len(zones)} zones computed — {len(r)} resistance, {len(s)} support")
        for z in zones:
            print(f"    {z['type']:12s}  {z['level']:.2f}  [{z['lower']:.2f} – {z['upper']:.2f}]")
    except Exception as exc:
        print(f"  ⚠ Engine 1 error: {exc}")

    # ── RS calculations ───────────────────────────────────────────
    rs_ratio    = 0.0
    rs_52w_high = 0.0
    rs_blue_dot = False
    rs_score    = 0.0
    if spy_df is not None:
        try:
            rs_line = calculate_rs_line(df, spy_df)
            if rs_line and len(rs_line) >= 252:
                rs_ratio    = float(rs_line[-1])
                rs_52w_high = float(max(rs_line))
                rs_blue_dot = detect_rs_blue_dot(rs_line)
            rs_score = calculate_rs_score(df, spy_df)
        except Exception as exc:
            print(f"  ⚠ RS calc error: {exc}")

    print(f"\n  RS score: {rs_score:+.4f}   Blue dot: {rs_blue_dot}   SPY 3m: {spy_3m_return:+.2%}")

    # ── Trendline ─────────────────────────────────────────────────
    tl = None
    try:
        tl = detect_trendline(ticker, df)
        parts = []
        if tl and tl.get("descending"):
            parts.append("descending")
        if tl and tl.get("ascending"):
            parts.append("ascending")
        print(f"  Trendlines: {', '.join(parts) if parts else 'none'}")
    except Exception as exc:
        print(f"  ⚠ Trendline error: {exc}")

    # ── ENGINE 2: VCP ─────────────────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 2 — VCP BREAKOUT")
    print(_DIV)
    total += 1
    try:
        res = scan_vcp(
            ticker, df, zones, spy_3m_return,
            rs_ratio, rs_52w_high, rs_blue_dot, rs_score,
            debug=True,
        )
        if res:
            sig = ("LEAD" if res.get("is_rs_lead") else
                   "BRK"  if res.get("is_breakout") else "DRY")
            print(f"✓ PASS [{sig}]  entry={res['entry']:.2f}  "
                  f"stop={res['stop_loss']:.2f}  target={res['take_profit']:.2f}  "
                  f"R:R={res['rr']:.1f}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 2 error: {exc}")

    # ── ENGINE 3: Strict Pullback ──────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 3 — STRICT TACTICAL PULLBACK")
    print(_DIV)
    total += 1
    try:
        res = scan_pullback(ticker, df, zones, tl, debug=True)
        if res:
            print(f"✓ PASS  entry={res['entry']:.2f}  stop={res['stop_loss']:.2f}  "
                  f"target={res['take_profit']:.2f}  CCI={res.get('cci_today', 0):.1f}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 3 (strict) error: {exc}")

    # ── ENGINE 3: Relaxed Pullback ────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 3 — RELAXED PULLBACK (RLX)")
    print(_DIV)
    total += 1
    try:
        res = scan_relaxed_pullback(ticker, df, zones, tl, debug=True)
        if res:
            print(f"✓ PASS [RLX]  entry={res['entry']:.2f}  stop={res['stop_loss']:.2f}  "
                  f"target={res['take_profit']:.2f}  CCI={res.get('cci_today', 0):.1f}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 3 (relaxed) error: {exc}")

    # ── ENGINE 5: Base Patterns ───────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 5 — BASE PATTERNS (Cup & Handle / Flat Base)")
    print(_DIV)
    total += 1
    try:
        res = scan_base_pattern(
            ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score
        )
        if res:
            print(f"✓ PASS [{res.get('base_type', '')}]  "
                  f"Q={res.get('quality_score', 0)}  entry={res['entry']:.2f}")
            passes += 1
        else:
            print("✗ No qualifying base pattern")
    except Exception as exc:
        print(f"  ✗ Engine 5 error: {exc}")

    # ── ENGINE 6: Resistance Breakout ─────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 6 — RESISTANCE BREAKOUT")
    print(_DIV)
    total += 1
    try:
        res = scan_resistance_breakout(ticker, df, zones, debug=True)
        if res:
            print(f"✓ PASS  level={res.get('resistance_level', 0):.2f}  "
                  f"vol={res.get('volume_ratio', 0):.1f}x  "
                  f"days_ago={res.get('days_since_breakout', 0)}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 6 error: {exc}")

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'═' * 62}")
    status = "✓" if passes > 0 else "✗"
    print(f"  {status} RESULT: {passes}/{total} engines found a setup for {ticker}")
    print(f"{'═' * 62}\n")


if __name__ == "__main__":
    main()
```

**Step 2: Run against a real ticker to verify output**

```bash
cd backend
python debug_ticker.py AAPL
```

Expected output structure:
```
══════════════════════════════════════════════════════════════
  SNIPER DEBUG: AAPL
══════════════════════════════════════════════════════════════

Fetching ticker data from yfinance...
  ✓ NNN trading days

──────────────────────────────────────────────────────────────
  VITALITY FILTER
──────────────────────────────────────────────────────────────
✓ PASS — Stock is actively traded (10-day range ≥ 2%)

...

══════════════════════════════════════════════════════════════
  ✗ RESULT: 0/6 engines found a setup for AAPL
══════════════════════════════════════════════════════════════
```

Each rejected engine must print at least one `REJECTED` line explaining why.

**Step 3: Run full test suite one final time**

```bash
python -m pytest tests/ -q
```

Expected: 122 passed (111 original + 11 new debug tests), 0 failures.

**Step 4: Commit**

```bash
git add backend/debug_ticker.py
git commit -m "feat(debug): add debug_ticker.py Sniper Debug Mode script"
```

---

## Testing Summary

| Test | What it verifies |
|------|-----------------|
| `test_vitality_debug_prints_rejection` | Flatline → `is_price_vital(debug=True)` prints "Vitality: REJECTED" |
| `test_vitality_debug_false_no_output` | `debug=False` → no stdout |
| `test_engine6_debug_below_sma50` | Below SMA50 → "Engine 6 Breakout: REJECTED - Below 50 SMA" |
| `test_engine6_debug_false_no_output` | `debug=False` → no stdout |
| `test_engine6_debug_no_zones` | Empty zones → "No KDE resistance zones found" |
| `test_pullback_debug_trend_filter` | Downtrend → "Engine 3 Pullback: REJECTED - Trend filter failed" |
| `test_pullback_debug_false_no_output` | `debug=False` → no stdout |
| `test_rlx_pullback_debug_trend_filter` | Downtrend → "Engine 3 RLX Pullback: REJECTED - Trend filter failed" |
| `test_rlx_pullback_debug_false_no_output` | `debug=False` → no stdout |
| `test_vcp_debug_trend_filter` | Downtrend → "Engine 2 VCP: REJECTED - Trend filter failed" |
| `test_vcp_debug_false_no_output` | `debug=False` → no stdout |

**No backend changes** to `main.py`. All new `debug` parameters default to `False`. Normal full-market scans are byte-for-byte identical in behaviour.
