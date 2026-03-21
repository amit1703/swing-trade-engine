# EMA20 Trail Lockdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock EMA20 trailing stop as the system-wide default by extracting the logic into a shared module, updating the live enrichment function to use it, and removing trail parameters from the Optuna search space.

**Architecture:** A new `backend/config/trailing_config.py` holds the single config dict. A new `backend/execution/trailing_engine.py` provides `advance_ema20_trail()` (bar-by-bar, used by backtest) and `compute_live_trail()` (stateless, used by live portfolio enrichment). All other modules import from these; no module may define its own trail logic.

**Tech Stack:** Python 3.11, pytest. No new dependencies.

---

## Codebase Facts (read before editing)

| File | Relevant section |
|------|-----------------|
| `backend/backtest_engine.py` | `_manage_open_trade()` lines ~412–496; EMA20 branch currently inlined |
| `backend/main.py` | `_LIVE_TRAIL_ATR_BY_TYPE` dict ~lines 472–484; `_enrich_trade()` ~lines 3142–3216 |
| `scripts/optimize_risk_v5.py` | `BOUNDS_P1` line 72; `_MODULE_PATCHES` line 80; `objective()` line 300; `_compute_sensitivity()` line 385 |
| `backend/constants.py` | `TRAIL_MODE = "ema20"` (already set); ATR mult constants still present as fallback |

WFO engine (`backend/wfo_engine.py`) has **no trail logic** — it delegates entirely to `BacktestEngine`. No changes needed there.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/config/__init__.py` | **Create** | Makes config/ a package |
| `backend/config/trailing_config.py` | **Create** | Single source of truth for all trail params |
| `backend/execution/__init__.py` | **Create** | Makes execution/ a package |
| `backend/execution/trailing_engine.py` | **Create** | Shared trail logic: `advance_ema20_trail`, `compute_live_trail`, `log_trail_config` |
| `backend/backtest_engine.py` | **Modify** | EMA20 branch calls `advance_ema20_trail()` instead of inline code |
| `backend/main.py` | **Modify** | `_enrich_trade()` uses `compute_live_trail()`; remove `_LIVE_TRAIL_ATR_BY_TYPE`; add startup log |
| `scripts/optimize_risk_v5.py` | **Modify** | Remove `trail_mult` from search space; remove ATR constant patching |
| `backend/tests/test_ema20_trail.py` | **Modify** | Add tests for new config/engine modules |

---

## Task 1: Create config package and trailing_config.py

**Files:**
- Create: `backend/config/__init__.py`
- Create: `backend/config/trailing_config.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ema20_trail.py`:

```python
def test_trail_config_has_required_keys():
    from config.trailing_config import TRAIL_CONFIG
    assert TRAIL_CONFIG["mode"] == "ema20"
    ema = TRAIL_CONFIG["ema"]
    assert ema["period"] == 20
    assert ema["trigger_atr_mult"] == 1.5
    assert ema["extension_threshold_atr"] == 2.5
    assert ema["extension_offset_atr"] == 1.5
    assert ema["use_previous_bar"] is True
    assert ema["allow_same_bar_trigger"] is False

def test_trail_config_validate_passes():
    from config.trailing_config import validate_trail_config
    validate_trail_config()  # must not raise
```

Run to confirm failure:
```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_ema20_trail.py::test_trail_config_has_required_keys -v
```
Expected: `ModuleNotFoundError: config`

- [ ] **Step 2: Create `backend/config/__init__.py`** (empty file)

- [ ] **Step 3: Create `backend/config/trailing_config.py`**

```python
"""
Single source of truth for trailing stop configuration.

All modules that implement trailing stop logic MUST import from here.
No module may define its own trail parameters.
"""

TRAIL_CONFIG: dict = {
    "mode": "ema20",   # system-wide default — change here to switch globally

    "ema": {
        "period":                    20,
        "trigger_atr_mult":          1.5,   # close must exceed ref_level + N*ATR to trigger Phase 2
        "extension_threshold_atr":   2.5,   # close > EMA20 + N*ATR → use buffer trail
        "extension_offset_atr":      1.5,   # buffer trail = EMA20 + N*ATR
        "use_previous_bar":          True,  # trail anchors to PREVIOUS bar's EMA (no lookahead)
        "allow_same_bar_trigger":    False, # Phase 2 cannot fire on entry bar
    },

    "atr": {
        "multiplier": 4.25,   # legacy fallback only — not used in ema20 mode
    },
}


def validate_trail_config() -> None:
    """
    Assert config is well-formed and mode is ema20.
    Call at system startup.

    Raises AssertionError if any invariant is violated.
    """
    assert TRAIL_CONFIG["mode"] == "ema20", (
        f"TRAIL_CONFIG mode is '{TRAIL_CONFIG['mode']}' — expected 'ema20'. "
        "Edit config/trailing_config.py to restore it."
    )
    ema = TRAIL_CONFIG["ema"]
    required = ("period", "trigger_atr_mult", "extension_threshold_atr",
                "extension_offset_atr", "use_previous_bar", "allow_same_bar_trigger")
    for key in required:
        assert key in ema, f"TRAIL_CONFIG['ema'] missing required key: '{key}'"
```

- [ ] **Step 4: Run the tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_ema20_trail.py::test_trail_config_has_required_keys \
               tests/test_ema20_trail.py::test_trail_config_validate_passes -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add backend/config/__init__.py backend/config/trailing_config.py \
        backend/tests/test_ema20_trail.py
git commit -m "feat: add trailing_config.py as single source of truth for trail params"
```

---

## Task 2: Create execution/trailing_engine.py

This module holds two public functions:
- `advance_ema20_trail(state, bar)` — bar-by-bar trail update, used by backtest engine
- `compute_live_trail(current_stop, entry_price, current_price, prev_ema20, current_ema20)` — stateless, used by live enrichment
- `log_trail_config()` — prints the active config; call at startup

**Files:**
- Create: `backend/execution/__init__.py`
- Create: `backend/execution/trailing_engine.py`
- Modify: `backend/tests/test_ema20_trail.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ema20_trail.py`:

```python
# ── trailing_engine tests ────────────────────────────────────────────────────

def _ema20_state_v2(ref_level=None, trail_triggered=False,
                    bars_since_entry=0, prev_ema20=None,
                    initial_stop=90.0) -> dict:
    return {
        "entry_price":       100.0,
        "trailing_stop":     initial_stop,
        "_trail_triggered":  trail_triggered,
        "_bars_since_entry": bars_since_entry,
        "_ref_level":        ref_level,
        "_prev_ema20":       prev_ema20,
    }

def _bar_v2(close=105.0, low=103.0, high=107.0, ema20=98.0, atr14=2.0):
    return {"open": 104.0, "high": high, "low": low,
            "close": close, "ema20": ema20, "atr14": atr14}


def test_advance_ema20_trail_reads_config_trigger_mult():
    """trigger uses TRAIL_CONFIG['ema']['trigger_atr_mult'], not a hardcoded 1.5."""
    from execution.trailing_engine import advance_ema20_trail
    from config.trailing_config import TRAIL_CONFIG
    mult = TRAIL_CONFIG["ema"]["trigger_atr_mult"]  # 1.5
    # ref=100, atr=2 → threshold = 100 + mult*2 = 103; close=104 → trigger
    state = _ema20_state_v2(ref_level=100.0, bars_since_entry=1)
    advance_ema20_trail(state, _bar_v2(close=104.0, ema20=98.0, atr14=2.0))
    assert state["_trail_triggered"] is True


def test_advance_ema20_trail_phase1_no_move():
    """Phase 1: stop must not move before trigger fires."""
    from execution.trailing_engine import advance_ema20_trail
    state = _ema20_state_v2(ref_level=120.0, bars_since_entry=1, initial_stop=90.0)
    advance_ema20_trail(state, _bar_v2(close=105.0, ema20=98.0, atr14=2.0))
    assert state["trailing_stop"] == 90.0


def test_advance_ema20_trail_phase2_uses_prev_ema20():
    """Phase 2 normal: stop trails to prev_ema20."""
    from execution.trailing_engine import advance_ema20_trail
    state = _ema20_state_v2(trail_triggered=True, bars_since_entry=2,
                             prev_ema20=99.0, initial_stop=90.0)
    advance_ema20_trail(state, _bar_v2(close=105.0, ema20=100.0, atr14=2.0))
    assert state["trailing_stop"] == 99.0


def test_advance_ema20_trail_stop_never_decreases():
    """Stop must never move down."""
    from execution.trailing_engine import advance_ema20_trail
    state = _ema20_state_v2(trail_triggered=True, bars_since_entry=2,
                             prev_ema20=85.0, initial_stop=90.0)
    advance_ema20_trail(state, _bar_v2(close=105.0, ema20=86.0, atr14=2.0))
    assert state["trailing_stop"] == 90.0  # prev_ema20=85 < stop=90 → no change


def test_compute_live_trail_in_profit():
    """In profit: live trail raises stop to prev_ema20 floor."""
    from execution.trailing_engine import compute_live_trail
    # entry=100, current_price=108 (profit), prev_ema20=97, stop=90 → new_stop=97
    result = compute_live_trail(
        current_stop=90.0, entry_price=100.0, current_price=108.0,
        prev_ema20=97.0, current_ema20=98.0)
    assert result == 97.0


def test_compute_live_trail_stop_never_below_initial():
    """Live trail never lowers stop below current_stop."""
    from execution.trailing_engine import compute_live_trail
    # prev_ema20=85 < current_stop=92 → stop stays at 92
    result = compute_live_trail(
        current_stop=92.0, entry_price=100.0, current_price=108.0,
        prev_ema20=85.0, current_ema20=86.0)
    assert result == 92.0


def test_compute_live_trail_not_in_profit():
    """Not in profit: stop is unchanged regardless of EMA20."""
    from execution.trailing_engine import compute_live_trail
    result = compute_live_trail(
        current_stop=90.0, entry_price=100.0, current_price=98.0,
        prev_ema20=101.0, current_ema20=100.0)
    assert result == 90.0
```

Run to confirm failures:
```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_ema20_trail.py -k "advance_ema20_trail or compute_live_trail" -v 2>&1 | tail -15
```
Expected: `ModuleNotFoundError: execution`

- [ ] **Step 2: Create `backend/execution/__init__.py`** (empty file)

- [ ] **Step 3: Create `backend/execution/trailing_engine.py`**

```python
"""
Shared trailing stop logic.

Two public functions:
  advance_ema20_trail(state, bar) — bar-by-bar update; used by backtest engine.
  compute_live_trail(...)         — stateless; used by live portfolio enrichment.

Both read parameters exclusively from TRAIL_CONFIG. No hardcoded multipliers here.
"""
from __future__ import annotations

from typing import Dict, Optional

from config.trailing_config import TRAIL_CONFIG


def advance_ema20_trail(state: Dict, bar: Dict) -> None:
    """
    Apply one bar of EMA20 trail logic to a trade state dict in-place.

    Phase 1 (before trigger): stop stays fixed at initial_stop.
    Phase 2 (after trigger):  stop trails to previous bar's EMA20
                               (or EMA20 + offset when price is extended).

    Trigger condition (requires bars_since_entry >= 2):
      - ref_level is None  → trigger immediately on bar 2 (HTF/LCE)
      - close > ref_level + trigger_atr_mult * ATR → trigger

    State keys mutated: trailing_stop, _trail_triggered,
                        _bars_since_entry, _prev_ema20.
    """
    cfg   = TRAIL_CONFIG["ema"]
    trig  = cfg["trigger_atr_mult"]        # 1.5
    ext_t = cfg["extension_threshold_atr"] # 2.5
    ext_o = cfg["extension_offset_atr"]    # 1.5

    ema20 = bar["ema20"]
    atr14 = bar.get("atr14", 0.0)
    close = bar["close"]
    stop  = state["trailing_stop"]

    bars = state.get("_bars_since_entry", 0) + 1
    state["_bars_since_entry"] = bars

    prev_ema20 = ema20 if state.get("_prev_ema20") is None else state["_prev_ema20"]

    # Phase 2 trigger check (1-bar delay enforced by bars >= 2)
    if not state.get("_trail_triggered", False) and bars >= 2:
        ref_level = state.get("_ref_level")
        if ref_level is None:
            state["_trail_triggered"] = True
        elif atr14 > 0 and close > ref_level + trig * atr14:
            state["_trail_triggered"] = True

    if state.get("_trail_triggered", False):
        if atr14 > 0 and close > ema20 + ext_t * atr14:
            new_trail = ema20 + ext_o * atr14   # extended: lock in gains tighter
        else:
            new_trail = prev_ema20               # normal: trail to previous bar EMA20
        if new_trail > stop:
            state["trailing_stop"] = new_trail

    state["_prev_ema20"] = ema20


def compute_live_trail(
    current_stop: float,
    entry_price: float,
    current_price: float,
    prev_ema20: Optional[float],
    current_ema20: float,
) -> float:
    """
    Compute the live portfolio trailing stop using EMA20 floor.

    Stateless — called once per price refresh (not bar-by-bar replay).
    Phase 1/2 gating is omitted because live enrichment has no per-bar history.

    Rules:
      - Only trails when current_price > entry_price (in profit)
      - Uses PREVIOUS bar's EMA20 as floor (no lookahead)
      - Stop can only move up (ratchet)
    """
    if entry_price <= 0 or current_ema20 <= 0 or current_price <= entry_price:
        return current_stop
    floor = (prev_ema20
             if (prev_ema20 is not None and prev_ema20 > 0)
             else current_ema20)
    return max(current_stop, floor)


def log_trail_config() -> None:
    """Print active trailing configuration. Call once at system startup."""
    cfg = TRAIL_CONFIG
    ema = cfg["ema"]
    print(f"Trailing Mode:  {cfg['mode'].upper()}")
    print(f"EMA Period:     {ema['period']}")
    print(f"Trigger:        {ema['trigger_atr_mult']} ATR above ref level")
    print(f"Extension:      {ema['extension_threshold_atr']} / {ema['extension_offset_atr']} ATR")
    print(f"Prev-bar trail: {ema['use_previous_bar']}")
```

- [ ] **Step 4: Run the new tests**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_ema20_trail.py -k "advance_ema20_trail or compute_live_trail or trail_config" -v
```
Expected: all 9 new tests PASS

- [ ] **Step 5: Run full suite to check no regressions**

```bash
python -m pytest tests/test_ema20_trail.py -v 2>&1 | tail -10
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/execution/__init__.py backend/execution/trailing_engine.py \
        backend/tests/test_ema20_trail.py
git commit -m "feat: add execution/trailing_engine.py with shared advance_ema20_trail and compute_live_trail"
```

---

## Task 3: Update backtest_engine.py to use advance_ema20_trail

Replace the inline EMA20 branch in `_manage_open_trade` with a call to the shared module.

**Files:**
- Modify: `backend/backtest_engine.py` — `_manage_open_trade` EMA20 branch only

- [ ] **Step 1: Find the exact EMA20 branch to replace**

Read `backend/backtest_engine.py` around line 454–485 (the `if trail_mode == "ema20":` block).
The block starts with `if trail_mode == "ema20":` and ends just before `else:`.

- [ ] **Step 2: Replace the inline branch with a call to the shared function**

At the top of `backtest_engine.py` (with other imports), add:
```python
from execution.trailing_engine import advance_ema20_trail as _advance_ema20_trail
```

In `_manage_open_trade`, replace the entire `if trail_mode == "ema20": ... (all inline logic up to else:)` block with:

```python
    if trail_mode == "ema20":
        _advance_ema20_trail(state, bar)
```

The `else:` ATR branch and `return False, None, None` remain unchanged.

- [ ] **Step 3: Run ALL existing EMA20 trail tests to confirm identical behavior**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_ema20_trail.py -v 2>&1 | tail -15
```
Expected: all 29+ tests PASS (the existing 22 tests still exercise `_manage_open_trade`, which now delegates to `advance_ema20_trail`)

- [ ] **Step 4: Commit**

```bash
git add backend/backtest_engine.py
git commit -m "refactor: backtest _manage_open_trade delegates EMA20 branch to execution/trailing_engine"
```

---

## Task 4: Update main.py live enrichment to use compute_live_trail

Replace the ATR-based live trailing in `_enrich_trade()` with the shared EMA20 logic.

**Files:**
- Modify: `backend/main.py` — `_LIVE_TRAIL_ATR_BY_TYPE` dict and `_enrich_trade()` trail block

- [ ] **Step 1: Read the sections to modify**

In `backend/main.py`:
- Find `_LIVE_TRAIL_ATR_BY_TYPE` dict (~line 472) — this will be deleted
- Find `_enrich_trade()` trail block (~lines 3193–3203) — this will be replaced

- [ ] **Step 2: Delete `_LIVE_TRAIL_ATR_BY_TYPE`**

Remove the entire dict (lines ~472–484):
```python
# V5: per-setup ATR trail multipliers for live trade enrichment (matches backtest_engine.py)
_LIVE_TRAIL_ATR_BY_TYPE = {
    "VCP":          VCP_TRAIL_ATR_MULT,
    "PULLBACK":     PULLBACK_TRAIL_ATR_MULT,
    "RES_BREAKOUT": RES_BREAKOUT_TRAIL_ATR_MULT,
    ...
}
```

Also remove the now-unused imports of the per-setup constants if they are only used here:
Check whether `VCP_TRAIL_ATR_MULT`, `PULLBACK_TRAIL_ATR_MULT`, `RES_BREAKOUT_TRAIL_ATR_MULT`, `BASE_TRAIL_ATR_MULT` are imported anywhere else in `main.py`. If only used in `_LIVE_TRAIL_ATR_BY_TYPE`, remove them from the import line too.

- [ ] **Step 3: Add import for shared trail function**

Near the top of `main.py` (with the other local imports), add:
```python
from execution.trailing_engine import compute_live_trail as _compute_live_trail
```

- [ ] **Step 4: Replace the trail block in `_enrich_trade()`**

Current code (~lines 3193–3203):
```python
        # V5 setup-specific trailing stop: max(ATR_trail, EMA20), never loosens.
        setup_type_key = str(trade.get("setup_type", "")).upper()
        atr_mult = _LIVE_TRAIL_ATR_BY_TYPE.get(setup_type_key, TRAIL_ATR_MULT)

        if lc > trade["entry_price"] and current_atr > 0:
            ema20_floor = l20
            atr_trail   = lc - (atr_mult * current_atr)
            raw_trail   = max(atr_trail, ema20_floor)
            trailing_stop = max(float(trade["stop_loss"]), raw_trail)
        else:
            trailing_stop = float(trade["stop_loss"])
```

Replace with:
```python
        # EMA20 trailing stop: floor is previous bar's EMA20 (no lookahead).
        prev_ema20_live = (float(ema20_s.iloc[-2])
                           if len(ema20_s.dropna()) >= 2 else None)
        trailing_stop = _compute_live_trail(
            current_stop  = float(trade["stop_loss"]),
            entry_price   = float(trade["entry_price"]),
            current_price = lc,
            prev_ema20    = prev_ema20_live,
            current_ema20 = l20,
        )
```

- [ ] **Step 5: Write a behavioral test for the live trail extraction**

Append to `backend/tests/test_ema20_trail.py`:

```python
def test_enrich_trade_live_trail_uses_prev_ema20(monkeypatch):
    """
    _enrich_trade must pass prev bar's EMA20 (iloc[-2]) to compute_live_trail
    so the stop moves up to that floor when in profit.
    """
    import asyncio
    import pandas as pd
    import numpy as np

    # Build a minimal 30-bar price DataFrame
    n = 30
    closes = [100.0 + i * 0.5 for i in range(n)]  # steadily rising
    df = pd.DataFrame({
        "Close":     closes,
        "Adj Close": closes,
        "High":      [c + 1 for c in closes],
        "Low":       [c - 1 for c in closes],
        "Volume":    [1_000_000] * n,
    })

    import main as _main
    # Patch _fetch to return our mock DataFrame
    async def mock_fetch(ticker):
        return df
    monkeypatch.setattr(_main, "_fetch", mock_fetch)

    trade = {
        "ticker":       "TEST",
        "entry_price":  100.0,
        "stop_loss":    90.0,
        "quantity":     10,
        "setup_type":   "PULLBACK",
    }

    result = asyncio.run(_main._enrich_trade(trade))

    # Stop must have moved up (current price ~114, EMA20 floor ~108)
    assert result["trailing_stop"] >= trade["stop_loss"]
    assert result["trailing_stop"] > 90.0
    assert result["is_risk_free"] is True  # stop above entry price
```

Run to confirm it passes:
```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_ema20_trail.py::test_enrich_trade_live_trail_uses_prev_ema20 -v
```
Expected: PASS

- [ ] **Step 6: Verify the server imports cleanly**

```bash
cd swing-trading-dashboard/backend
python -c "import main; print('main.py imports OK')"
```
Expected: `main.py imports OK` (no ImportError)

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_ema20_trail.py
git commit -m "feat: live _enrich_trade uses EMA20 trail via execution/trailing_engine"
```

---

## Task 5: Lock trail mode in optimize_risk_v5.py

Remove `trail_mult` from the Optuna search space. EMA20 mode is now fixed — trail parameters are not optimized.

**Files:**
- Modify: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Read the sections to change**

Read lines 1–15 (docstring), 72–97 (BOUNDS_P1, _MODULE_PATCHES), 300–350 (objective), 385–399 (_compute_sensitivity), 446–510 (_export_phase1), 513–577 (_export_phase2).

- [ ] **Step 2: Update BOUNDS_P1 — remove trail_mult**

Change:
```python
BOUNDS_P1: dict[str, tuple] = {
    "trail_mult":         (2.0,  8.5),
    "risk_per_trade":     (0.5,  1.5),
    "max_position_pct":   (10.0, 30.0),
    "atr_entry_early":    (0.03, 0.20),
    "atr_entry_extended": (0.30, 0.90),
}
```

To:
```python
BOUNDS_P1: dict[str, tuple] = {
    # trail_mult removed — EMA20 trail is locked; not part of search space
    "risk_per_trade":     (0.5,  1.5),
    "max_position_pct":   (10.0, 30.0),
    "atr_entry_early":    (0.03, 0.20),
    "atr_entry_extended": (0.30, 0.90),
}
```

- [ ] **Step 3: Update _MODULE_PATCHES — remove trail_mult entry**

Remove the entire `"trail_mult": [...]` entry from `_MODULE_PATCHES`:
```python
_MODULE_PATCHES: dict[str, list[tuple[str, str]]] = {
    # "trail_mult" removed — EMA20 trail is locked, no ATR const patching needed
    "risk_per_trade": [
        ("constants",       "RISK_PER_TRADE_PCT"),
        ("backtest_engine", "RISK_PER_TRADE_PCT"),
    ],
    "max_position_pct": [
        ("constants",       "MAX_POSITION_SIZE_PCT"),
        ("backtest_engine", "MAX_POSITION_SIZE_PCT"),
    ],
    # atr_entry_early / atr_entry_extended: post-WFO filter, no module patch.
}
```

- [ ] **Step 4: Update objective() — remove trail_mult suggest and params**

In `objective()`, remove:
```python
    trail_mult         = trial.suggest_float("trail_mult",         *bounds["trail_mult"])
```

And remove `"trail_mult": trail_mult` from the `params` dict:
```python
    params = {
        # trail_mult removed — EMA20 locked
        "risk_per_trade":   risk_per_trade,
        "max_position_pct": max_position_pct,
    }
```

Add a comment at the top of `objective()`:
```python
    # Trail mode is locked to EMA20 — not part of the search space.
    # BacktestEngine reads TRAIL_MODE from constants, which is set to "ema20".
```

- [ ] **Step 5: Remove _compute_sensitivity and its callers**

Delete the entire `_compute_sensitivity()` function (it's trail_mult-specific).

In `_export_phase1()`:
- Remove: `sensitivity = _compute_sensitivity(completed)`
- Remove: `"sensitivity": {"trail_mult_buckets": sensitivity},` from output dict
- Remove: the `print("Trail mult sensitivity:")` block from the print section

In `_export_phase2()`:
- Remove: `sensitivity = _compute_sensitivity(completed)`
- Remove: `"sensitivity": {"trail_mult_buckets": sensitivity},` from output dict
- Remove: `"trail_mult": round(best.params.get("trail_mult", 0), 4),` from `recommended` dict
- Add: `"trail_mode": "ema20",` to `recommended` dict

- [ ] **Step 6: Update the module docstring**

Change line 4 from:
```
Optimizes: trail_mult, risk_per_trade, max_position_pct,
```
To:
```
Optimizes: risk_per_trade, max_position_pct,
```
And add a line:
```
Trail mode: LOCKED to EMA20 (not in search space).
```

- [ ] **Step 7: Smoke-test the script imports cleanly**

```bash
cd swing-trading-dashboard/backend
python -c "
import sys; sys.path.insert(0, '../scripts')
import optimize_risk_v5
print('optimize_risk_v5 imports OK')
print('BOUNDS_P1 keys:', list(optimize_risk_v5.BOUNDS_P1.keys()))
"
```
Expected: imports OK, BOUNDS_P1 keys do NOT include `trail_mult`

- [ ] **Step 8: Commit**

```bash
git add scripts/optimize_risk_v5.py
git commit -m "feat: remove trail_mult from Optuna search space — EMA20 trail is locked"
```

---

## Task 6: Add startup validation and logging to main.py

- [ ] **Step 1: Add imports near the top of main.py**

Find the existing local imports block. Add:
```python
from config.trailing_config import validate_trail_config
from execution.trailing_engine import log_trail_config as _log_trail_config
```

- [ ] **Step 2: Call validation and logging at startup**

Find the FastAPI app startup block (look for `@app.on_event("startup")` or `lifespan` or the startup section near the bottom of `main.py`).

Add these calls at the beginning of the startup handler (before the scheduler starts):
```python
    # Validate and log trailing stop configuration
    validate_trail_config()   # raises AssertionError if mode != "ema20"
    _log_trail_config()
```

If there is no startup event, add it:
```python
@app.on_event("startup")
async def _on_startup():
    validate_trail_config()
    _log_trail_config()
```

- [ ] **Step 3: Verify imports**

```bash
cd swing-trading-dashboard/backend
python -c "import main; print('startup imports OK')"
```
Expected: `startup imports OK`

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: validate_trail_config and log_trail_config called at FastAPI startup"
```

---

## Task 7: Verification backtest

Confirm the system still produces the expected results after all changes.

**Files:**
- Read only: `scripts/run_backtest_quick.py`

- [ ] **Step 1: Run EMA20 backtest**

```bash
cd swing-trading-dashboard/backend
python ../scripts/run_backtest_quick.py --trail-mode ema20
```

- [ ] **Step 2: Verify results match baseline**

Expected (from previous run, tolerances ±2pp):

| Metric | Expected | Actual |
|--------|----------|--------|
| N trades | ~579 | ? |
| Win rate | ~46.6% | ? |
| Expectancy | ~+0.379R | ? |
| Profit Factor | ~1.94 | ? |
| STOP exit % | ~96% | ? |
| Phase 2 triggered | ~63% | ? |

If any metric is far outside tolerance → STOP and investigate before committing.

- [ ] **Step 3: Run all tests**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -20
```
Expected: all pass (pre-existing failures in test_backtest_diag_constants and test_backtest_engine are unrelated — confirm they were already failing before this task)

- [ ] **Step 4: Commit verification note**

```bash
git commit --allow-empty -m "chore: EMA20 trail lockdown verified — exp≈+0.379R PF≈1.94 win≈46.6%"
```

---

## Acceptance Criteria

- [ ] `backend/config/trailing_config.py` is the only place trail parameters are defined
- [ ] `backend/execution/trailing_engine.py` is the only place trail logic is implemented
- [ ] `backtest_engine._manage_open_trade` EMA20 branch calls `advance_ema20_trail` — no inline logic
- [ ] `main._enrich_trade` uses `compute_live_trail` — no ATR trail block, no `_LIVE_TRAIL_ATR_BY_TYPE`
- [ ] `optimize_risk_v5.BOUNDS_P1` does NOT contain `trail_mult`
- [ ] `validate_trail_config()` called at FastAPI startup — system cannot start with wrong mode
- [ ] Verification backtest matches baseline within tolerance
- [ ] All `test_ema20_trail.py` tests pass (29+ including new ones)

## Safety Check — Legacy Trail References

After all tasks complete, confirm no module has independent trailing logic by running:

```bash
cd swing-trading-dashboard
grep -rn "trail_mult\|ATR trail\|atr_trail\|_LIVE_TRAIL" \
  backend/ scripts/ --include="*.py" \
  | grep -v "test_" | grep -v "constants.py" | grep -v "__pycache__"
```

Expected remaining hits:
- `backtest_engine.py`: `trail_mult_override` in ATR fallback branch (legitimate — A/B testing path)
- `constants.py`: ATR mult constants (legitimate — kept as fallback values)
- `run_backtest_quick.py`: `--trail-mode atr` flag (legitimate — A/B testing)
- `trail_diagnostic.py`: diagnostic script (legitimate)

Any OTHER hits → investigate and remove.
