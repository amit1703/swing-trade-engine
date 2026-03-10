# Optuna RS Expansion & Hardcoded Parameter Audit

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ENGINE3_RS_THRESHOLD to Optuna search space, document RS architecture constraints, and identify the highest-value hardcoded parameters for v4 optimization.

**Architecture:** ENGINE3_RS_THRESHOLD is extracted from engine3.py's inline -0.05 literal to a named module-level constant, then added to _MODULE_PATCHES. RS_RANK_MIN_PERCENTILE cannot be meaningfully added without BacktestEngine changes (documented as future work). A separate hardcoded-params audit identifies CCI floors and MAX_OPEN_POSITIONS as high-value v4 candidates.

**Tech Stack:** Python, Optuna, pytest

---

## Architecture Reference: How _patch_constants Works

`_patch_constants` (lines 96–115 of `scripts/optimize_parameters.py`) temporarily overrides module-level attributes via `setattr`. It reads the `_MODULE_PATCHES` dict at context entry time and restores all originals in the `finally` block.

**Critical constraint — import-time binding:** When Python executes `from constants import RS_RANK_MIN_PERCENTILE` in `main.py`, it binds the *value* (not a reference) to the local name in `main.py`'s namespace. Patching `constants.RS_RANK_MIN_PERCENTILE` at runtime via `setattr` has NO effect on the already-bound name in `main.py`. The same applies to `DISCOVERY_RS_MIN` and `DISCOVERY_RS_MAX`.

**Why ENGINE3_RS_THRESHOLD is patchable:** Once extracted to a module-level constant `RS_REJECT_THRESHOLD`, calls to `scan_pullback` and `scan_relaxed_pullback` will read `engine3.RS_REJECT_THRESHOLD` from the module dict at call time — making it patchable by `setattr(engine3_mod, "RS_REJECT_THRESHOLD", val)`.

**RS_RANK_MIN_PERCENTILE is scanner-only:** Used exclusively in `main.py`'s `_build_discovery_tickers()` and `run_scan()` — neither of which is called during WFO. Even if patching worked, it would have zero effect on the Optuna objective.

---

## Task 1: Extract ENGINE3_RS_THRESHOLD constant

**Files:**
- Modify: `backend/engines/engine3.py`
- Modify: `backend/tests/test_engine3_rlx.py`

### Context

`engine3.py` has two hardcoded `-0.05` RS gate literals:
- ~Line 217: `if rs_score < -0.05:` (inside `scan_pullback`)
- ~Line 355: `if rs_score < -0.05:` (inside `scan_relaxed_pullback`)

Imports end at line 33: `from zone_utils import nearest_resistance_target`
The constant goes after line 33, before the `# ---` separator.

### Step 1: Write the failing test

Add to `backend/tests/test_engine3_rlx.py`:

```python
def test_rs_reject_threshold_is_patchable():
    """RS_REJECT_THRESHOLD is a module constant patchable at runtime."""
    import engines.engine3 as engine3

    # Confirm default value
    assert engine3.RS_REJECT_THRESHOLD == -0.05

    # Tighten the threshold: stocks with rs_score=-0.03 should now be rejected
    engine3.RS_REJECT_THRESHOLD = -0.02
    try:
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            scan_relaxed_pullback("TEST", make_pullback_df(), [make_support_zone(99.0)],
                                  rs_score=-0.03, debug=True)
        debug_output = f.getvalue()
        assert "RS score too weak" in debug_output, (
            "With RS_REJECT_THRESHOLD=-0.02 and rs_score=-0.03, RS gate must fire"
        )
    finally:
        engine3.RS_REJECT_THRESHOLD = -0.05

    # Confirm restored: rs_score=-0.03 passes RS gate (threshold back at -0.05)
    f2 = io.StringIO()
    with redirect_stdout(f2):
        scan_relaxed_pullback("TEST", make_pullback_df(), [make_support_zone(99.0)],
                              rs_score=-0.03, debug=True)
    assert "RS score too weak" not in f2.getvalue(), (
        "After restoring threshold to -0.05, rs_score=-0.03 must pass the RS gate"
    )
```

### Step 2: Run to confirm RED

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python3 -m pytest tests/test_engine3_rlx.py::test_rs_reject_threshold_is_patchable -v
```

Expected: FAIL with `AttributeError: module 'engines.engine3' has no attribute 'RS_REJECT_THRESHOLD'`

### Step 3: Add module-level constant to engine3.py

After the last import line (`from zone_utils import nearest_resistance_target`), insert:

```python

# RS gate: reject stocks that persistently underperform SPY.
# Loose floor allows flat-vs-SPY stocks to qualify. Patchable by Optuna.
RS_REJECT_THRESHOLD = -0.05
```

### Step 4: Replace both -0.05 literals

In `scan_pullback` (~line 217):
```python
# Before:
        if rs_score < -0.05:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < -0.05 — persistent underperformer)"
                )

# After:
        if rs_score < RS_REJECT_THRESHOLD:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < {RS_REJECT_THRESHOLD:.2f} — persistent underperformer)"
                )
```

In `scan_relaxed_pullback` (~line 355):
```python
# Before:
        if rs_score < -0.05:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < -0.05 — persistent underperformer)"
                )

# After:
        if rs_score < RS_REJECT_THRESHOLD:
            if debug:
                print(
                    f"Engine 3 RLX Pullback: REJECTED - RS score too weak "
                    f"({rs_score:.3f} < {RS_REJECT_THRESHOLD:.2f} — persistent underperformer)"
                )
```

### Step 5: Run to confirm GREEN

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python3 -m pytest tests/test_engine3_rlx.py -v 2>&1 | tail -15
```

Expected: all tests pass including `test_rs_reject_threshold_is_patchable`.

### Step 6: Commit

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard
git add backend/engines/engine3.py backend/tests/test_engine3_rlx.py
git commit -m "refactor(engine3): extract RS_REJECT_THRESHOLD constant"
```

---

## Task 2: Add ENGINE3_RS_THRESHOLD to Optuna

**Files:**
- Modify: `scripts/optimize_parameters.py`
- Modify: `backend/tests/test_optimizer_integration.py`

### Context

Current state of `scripts/optimize_parameters.py`:
- `_MODULE_PATCHES` ends at line ~85 with `"REGIME_BULL_THRESHOLD"` entry
- `objective()` has 8 params (7 existing + REGIME_BULL_THRESHOLD via suggest_int)
- `_log_trial()` has 9 fieldnames: `trial_number, value` + 7 param keys

`test_optimizer_integration.py`:
- `expected_keys` has 7 items (lines 102–107)
- `test_regime_patch_mutates_and_restores` has a `full_params` dict with all 7 keys (must be updated to include `ENGINE3_RS_THRESHOLD` or `_patch_constants` will error)

### Step 1: Write failing tests

In `backend/tests/test_optimizer_integration.py`:

**Update `expected_keys`** (add `"ENGINE3_RS_THRESHOLD"` — now 8 total):
```python
    expected_keys = {
        "ATR_MULTIPLIER", "VCP_TIGHTNESS_RANGE", "BREAKOUT_BUFFER_ATR",
        "BREAKOUT_VOL_MULT", "TARGET_RR", "TRAIL_ATR_MULT",
        "REGIME_BULL_THRESHOLD", "ENGINE3_RS_THRESHOLD",
    }
```

**Add bound assertion** inside `test_main_creates_best_parameters_json`:
```python
    assert -0.10 <= params["ENGINE3_RS_THRESHOLD"] <= 0.00, \
        f"ENGINE3_RS_THRESHOLD out of range: {params['ENGINE3_RS_THRESHOLD']}"
```

**Update `full_params`** in `test_regime_patch_mutates_and_restores` to add the new key:
```python
    full_params = {
        "ATR_MULTIPLIER":         1.40,
        "VCP_TIGHTNESS_RANGE":    0.05,
        "BREAKOUT_BUFFER_ATR":    0.40,
        "BREAKOUT_VOL_MULT":      1.00,
        "TARGET_RR":              2.50,
        "TRAIL_ATR_MULT":         2.00,
        "REGIME_BULL_THRESHOLD":  patched_value,
        "ENGINE3_RS_THRESHOLD":   -0.05,
    }
```

**Add new test** at end of file:
```python
def test_engine3_rs_threshold_patch_works():
    """_patch_constants must patch engines.engine3.RS_REJECT_THRESHOLD and restore it."""
    import importlib
    import optimize_parameters as optimizer
    importlib.reload(optimizer)
    import engines.engine3 as engine3

    original = engine3.RS_REJECT_THRESHOLD
    assert original == -0.05, f"Expected default -0.05, got {original}"

    full_params = {
        "ATR_MULTIPLIER":         1.40,
        "VCP_TIGHTNESS_RANGE":    0.05,
        "BREAKOUT_BUFFER_ATR":    0.40,
        "BREAKOUT_VOL_MULT":      1.00,
        "TARGET_RR":              2.50,
        "TRAIL_ATR_MULT":         2.00,
        "REGIME_BULL_THRESHOLD":  30,
        "ENGINE3_RS_THRESHOLD":   -0.02,
    }

    with optimizer._patch_constants(full_params):
        assert engine3.RS_REJECT_THRESHOLD == -0.02, \
            f"Expected -0.02 during patch, got {engine3.RS_REJECT_THRESHOLD}"

    assert engine3.RS_REJECT_THRESHOLD == original, \
        f"Expected restore to {original}, got {engine3.RS_REJECT_THRESHOLD}"
```

### Step 2: Run to confirm RED

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python3 -m pytest tests/test_optimizer_integration.py -v 2>&1 | tail -20
```

Expected: `test_main_creates_best_parameters_json` FAILS with `Missing/extra keys: {'ENGINE3_RS_THRESHOLD'}`.

### Step 3: Add ENGINE3_RS_THRESHOLD to _MODULE_PATCHES

In `scripts/optimize_parameters.py`, add after the `"REGIME_BULL_THRESHOLD"` entry:

```python
    "ENGINE3_RS_THRESHOLD": [
        ("engines.engine3", "RS_REJECT_THRESHOLD"),
    ],
```

### Step 4: Add ENGINE3_RS_THRESHOLD to objective()

In the `params` dict inside `objective()`, add after `REGIME_BULL_THRESHOLD`:

```python
        "ENGINE3_RS_THRESHOLD":    trial.suggest_float("ENGINE3_RS_THRESHOLD", -0.10, 0.00),
```

### Step 5: Update _log_trial fieldnames

In `_log_trial()`, add `"ENGINE3_RS_THRESHOLD"` to the `fieldnames` list:

```python
    fieldnames = [
        "trial_number", "value",
        "ATR_MULTIPLIER", "VCP_TIGHTNESS_RANGE", "BREAKOUT_BUFFER_ATR",
        "BREAKOUT_VOL_MULT", "TARGET_RR", "TRAIL_ATR_MULT",
        "REGIME_BULL_THRESHOLD", "ENGINE3_RS_THRESHOLD",
    ]
```

### Step 6: Run to confirm GREEN

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python3 -m pytest tests/test_optimizer_integration.py tests/test_engine3_rlx.py -v 2>&1 | tail -25
```

Expected: all tests pass.

### Step 7: Commit

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard
git add scripts/optimize_parameters.py backend/tests/test_optimizer_integration.py
git commit -m "feat(optimizer): add ENGINE3_RS_THRESHOLD to v3 search space"
```

---

## Task 3: Write v4 proposal doc

**Files:**
- Create: `docs/optuna-v4-proposal-2026-03-08.md`

No tests required. Write the file directly using Write tool.

Content:

```markdown
# Optuna v4 Proposal — Hardcoded Parameter Audit

**Date:** 2026-03-08

## Section 1: RS Architecture Constraint

### Why RS_RANK_MIN_PERCENTILE Cannot Be Added to Optuna Yet

`RS_RANK_MIN_PERCENTILE` (value: 70) is defined in `constants.py` but imported via `from constants import RS_RANK_MIN_PERCENTILE` in `main.py`. Python binds the integer value `70` to the local name at import time. Patching `constants.RS_RANK_MIN_PERCENTILE` at runtime only changes the `constants` module dict — the name in `main.py` still resolves to `70`.

Furthermore, `RS_RANK_MIN_PERCENTILE` is used exclusively in `main.py`'s `_build_discovery_tickers()` and `run_scan()` — **neither of which is called during WFO backtest**. Adding it to Optuna would optimize a parameter with zero effect on the WFO objective.

### What BacktestEngine Changes Would Be Needed (v5)

To make RS rank meaningful in Optuna, `BacktestEngine` would need a per-signal RS score filter that rejects signals where the ticker's RS score is below a threshold, with that threshold stored as a patchable module-level variable. This is a non-trivial change requiring modifications to `wfo_engine.py` and `backtest_engine.py`.

### ENGINE3_RS_THRESHOLD Is the Only Patchable RS Parameter (Added in v3)

`engine3.py` reads the RS gate as `if rs_score < RS_REJECT_THRESHOLD` — a bare module attribute read at call time. After Task 1 extracts the literal, `setattr(engine3_mod, "RS_REJECT_THRESHOLD", val)` is effective for every subsequent engine3 call.

---

## Section 2: Hardcoded Parameter Audit

| Parameter | Current value | File | Affects backtest? | Priority | Suggested range |
|---|---|---|---|---|---|
| `CCI_STRICT_FLOOR` | -50.0 | `constants.py` → `engine3.py` | YES | HIGH | -80 to -20 |
| `CCI_RLX_FLOOR` | -20.0 | `constants.py` → `engine3.py` | YES | HIGH | -40 to 0 |
| `MAX_OPEN_POSITIONS` | 5 | `constants.py` → `optimize_parameters.py` | YES | HIGH | 3 to 8 (int) |
| `LIQUIDITY_MIN_AVG_VOLUME` | 750_000 | `filters.py` | YES | MEDIUM | 500K to 1.5M |
| `LIQUIDITY_MIN_DOLLAR_VOLUME` | 25_000_000 | `filters.py` | YES | MEDIUM | 15M to 40M |
| `VCP_ATR_CONTRACTION_THRESHOLD` | 0.6 | `constants.py` | YES | MEDIUM | 0.4 to 0.8 |
| `TRENDLINE_TOUCH_TOLERANCE_PCT` | 0.015 | `constants.py` → `engine3.py` | YES | MEDIUM | 0.01 to 0.03 |
| `RS_RANK_MIN_PERCENTILE` | 70 | `main.py` (scanner-only, import-time bound) | NO | LOW (v5) | 55 to 80 |
| `DISCOVERY_RS_MIN` | 60 | `main.py` (scanner-only, import-time bound) | NO | LOW (v5) | 50 to 70 |

### Patchability Notes

**CCI floors:** Imported into `engine3.py` via `from constants import CCI_STRICT_FLOOR, CCI_RLX_FLOOR`. Engine3 functions read these from engine3's own module dict at call time, so patch target is `("engines.engine3", "CCI_STRICT_FLOOR")` and `("engines.engine3", "CCI_RLX_FLOOR")` — same mechanism as ATR_STOP_MULTIPLIER.

**MAX_OPEN_POSITIONS:** Used in `optimize_parameters.py` module scope (`from constants import MAX_OPEN_POSITIONS`, used in `_aggregate_oos_metrics`). Patch target: `("optimize_parameters", "MAX_OPEN_POSITIONS")`.

**LIQUIDITY thresholds:** `filters.py` defines `passes_liquidity(df, min_avg_volume=750_000, ...)` — default parameter values are evaluated once at function definition time, NOT at call time. Patching the module attribute won't affect the default. Would need to either make BacktestEngine pass explicit values, or refactor `passes_liquidity` to read from module globals.

---

## Section 3: v4 Proposal

### HIGH priority — add to v4

| Optuna key | Type | Range | Patch target |
|---|---|---|---|
| `ENGINE3_RS_THRESHOLD` | float | -0.10 to 0.00 | `engines.engine3.RS_REJECT_THRESHOLD` *(done in v3)* |
| `CCI_STRICT_FLOOR` | float | -80 to -20 | `engines.engine3.CCI_STRICT_FLOOR` |
| `CCI_RLX_FLOOR` | float | -40 to 0 | `engines.engine3.CCI_RLX_FLOOR` |
| `MAX_OPEN_POSITIONS` | int | 3 to 8 | `optimize_parameters.MAX_OPEN_POSITIONS` |

### MEDIUM priority — require pre-work

- `LIQUIDITY_MIN_AVG_VOLUME`: Refactor `passes_liquidity` to read module globals instead of function defaults.
- `TRENDLINE_TOUCH_TOLERANCE_PCT`: Verify patch target is `("engines.engine3", "TRENDLINE_TOUCH_TOLERANCE_PCT")`.
- `VCP_ATR_CONTRACTION_THRESHOLD`: Identify which engine uses it and verify import pattern.

### Already in v3 (do not re-add)

ATR_MULTIPLIER, TARGET_RR, TRAIL_ATR_MULT, REGIME_BULL_THRESHOLD, VCP_TIGHTNESS_RANGE, BREAKOUT_BUFFER_ATR, BREAKOUT_VOL_MULT, ENGINE3_RS_THRESHOLD

### Future v5 — requires BacktestEngine RS gate first

RS_RANK_MIN_PERCENTILE, DISCOVERY_RS_MIN, DISCOVERY_RS_MAX
```

### Step 1: Write the file

Use the Write tool to create `docs/optuna-v4-proposal-2026-03-08.md` with the content above.

### Step 2: Commit

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard
git add docs/optuna-v4-proposal-2026-03-08.md
git commit -m "docs: add hardcoded param audit and Optuna v4 proposal"
```

---

## Task 4: Kill v3 run and restart with ENGINE3_RS_THRESHOLD

**No files modified — operational steps only.**

### Step 1: Kill running process

```bash
kill $(pgrep -f "optimize_parameters")
sleep 3
pgrep -f "optimize_parameters" || echo "All optimizer processes stopped"
```

### Step 2: Verify code changes in place

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python3 -m pytest tests/test_optimizer_integration.py tests/test_engine3_rlx.py -v 2>&1 | tail -15
```

Expected: all tests pass.

### Step 3: Start new v3 run

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
nohup python3 ../scripts/optimize_parameters.py --trials 300 > ../optuna_v3.log 2>&1 &
echo "Started PID: $!"
```

### Step 4: Verify after 5 minutes

```bash
# Check process alive
ps -p $NEW_PID -o pid,etime,%cpu

# Check CSV header includes ENGINE3_RS_THRESHOLD
head -1 /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/optuna_trial_log.csv

# Check study name and trial count in log
tail -5 /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/optuna_v3.log
```

Expected: CSV header has 10 columns (trial_number, value, 8 params), study is `trading_optimizer_v3`.

### Step 5: Commit confirmation

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard
git commit --allow-empty -m "chore: restart v3 run with ENGINE3_RS_THRESHOLD (8 params)"
```

---

## Backward Compatibility Notes

- Existing 99+ v3 trials remain valid — Optuna TPE treats missing `ENGINE3_RS_THRESHOLD` in historical trials as unobserved, using the prior (uniform over -0.10 to 0.00) for those slots. No data migration needed.
- Study name stays `trading_optimizer_v3` — we are extending, not restarting.
- The `optuna_trial_log.csv` will have a new header row when the process restarts — `extrasaction="ignore"` in `DictWriter` handles this gracefully.

## Full Test Command

```bash
cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
python3 -m pytest tests/test_optimizer_integration.py tests/test_engine3_rlx.py -v
```
