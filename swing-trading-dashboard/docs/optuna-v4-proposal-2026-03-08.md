# Optuna v4 Proposal — Hardcoded Parameter Audit

**Date:** 2026-03-08

---

## Section 1: RS Architecture Constraint

### Why RS_RANK_MIN_PERCENTILE Cannot Be Added to Optuna Yet

`RS_RANK_MIN_PERCENTILE` (value: 70) is defined in `constants.py` but imported via `from constants import RS_RANK_MIN_PERCENTILE` in `main.py`. Python binds the integer value `70` to the local name at import time. Calling `setattr(constants_module, "RS_RANK_MIN_PERCENTILE", 55)` after this has already happened only changes the `constants` module dict — the name in `main.py` still resolves to `70`.

Furthermore, `RS_RANK_MIN_PERCENTILE` is used exclusively in `main.py`'s `_build_discovery_tickers()` and `run_scan()` — **neither of which is called during WFO backtest**. Adding it to Optuna would optimize a parameter with zero effect on the WFO objective function. The same constraint applies to `DISCOVERY_RS_MIN` and `DISCOVERY_RS_MAX`.

### What BacktestEngine Changes Would Be Needed (v5)

To make RS rank meaningful in Optuna, `BacktestEngine` would need a per-signal RS score filter that:
1. Receives the ticker's RS score at signal time (already computed by the indicator engine)
2. Rejects signals where the raw RS score is below a patchable module-level threshold
3. The threshold is stored as a module attribute (not a function default parameter or `from constants import` binding) so `setattr` can patch it

This is a non-trivial change requiring modifications to `wfo_engine.py` and `backtest_engine.py`, tracked as v5 future work.

### ENGINE3_RS_THRESHOLD: The Only Patchable RS Parameter (Added in v3)

`engine3.py` reads the RS gate as `if rs_score < RS_REJECT_THRESHOLD` — a bare module attribute read at call time. `setattr(engine3_mod, "RS_REJECT_THRESHOLD", val)` is effective for every subsequent `scan_pullback` / `scan_relaxed_pullback` call. This parameter was added to the v3 search space (range: -0.10 to 0.00).

---

## Section 2: Hardcoded Parameter Audit

### Parameters That Affect Backtest

| Parameter | Current value | File | Priority | Suggested range | Notes |
|---|---|---|---|---|---|
| `ENGINE3_RS_THRESHOLD` | -0.05 | `engines/engine3.py` | ✅ Done (v3) | -0.10 to 0.00 | RS quality gate for pullback engine |
| `CCI_STRICT_FLOOR` | -50.0 | `constants.py` → `engine3.py` | **HIGH** | -80 to -20 | CCI oversold floor for strict pullback |
| `CCI_RLX_FLOOR` | -20.0 | `constants.py` → `engine3.py` | **HIGH** | -40 to 0 | CCI floor for relaxed pullback |
| `MAX_OPEN_POSITIONS` | 5 | `constants.py` → `optimize_parameters.py` | **HIGH** | 3 to 8 (int) | Portfolio cap — affects trade frequency and drawdown |
| `LIQUIDITY_MIN_AVG_VOLUME` | 750_000 | `filters.py` (default param) | MEDIUM | 500K to 1.5M | Requires refactoring `passes_liquidity` (see note) |
| `LIQUIDITY_MIN_DOLLAR_VOLUME` | 25_000_000 | `filters.py` (default param) | MEDIUM | 15M to 40M | Same refactor requirement |
| `VCP_ATR_CONTRACTION_THRESHOLD` | 0.6 | `constants.py` | MEDIUM | 0.4 to 0.8 | VCP compression gate |
| `TRENDLINE_TOUCH_TOLERANCE_PCT` | 0.015 | `constants.py` → `engine3.py` | MEDIUM | 0.01 to 0.03 | Trendline proximity tolerance |

### Parameters That Are Scanner-Only (Do NOT Affect WFO)

| Parameter | Current value | Reason excluded |
|---|---|---|
| `RS_RANK_MIN_PERCENTILE` | 70 | `from constants import` in `main.py` at import time; scanner-only |
| `DISCOVERY_RS_MIN` | 60 | Same import-time binding constraint |
| `DISCOVERY_RS_MAX` | 70 | Same import-time binding constraint |
| `MIN_SETUP_SCORE` | 70 | Scanner scoring gate, not called during WFO |
| `TOP_SECTORS_N` | 8 | Sector scoring, scanner-only |

### Patchability Notes

**CCI_STRICT_FLOOR and CCI_RLX_FLOOR:** Imported into `engine3.py` via `from constants import CCI_STRICT_FLOOR, CCI_RLX_FLOOR`. Engine3 functions read these from engine3's own module dict at call time (the `from constants import` binds the name in engine3's namespace, not constants'). Patch target: `("engines.engine3", "CCI_STRICT_FLOOR")` and `("engines.engine3", "CCI_RLX_FLOOR")` — same mechanism as the existing `ATR_STOP_MULTIPLIER` patch.

**MAX_OPEN_POSITIONS:** Used in `optimize_parameters.py` at module scope via `from constants import MAX_OPEN_POSITIONS`. Patch target: `("optimize_parameters", "MAX_OPEN_POSITIONS")`. Since `_aggregate_oos_metrics` reads it as a module attribute, patching is effective.

**LIQUIDITY thresholds:** `filters.py` defines `passes_liquidity(df, min_avg_volume=750_000, min_dollar_volume=25_000_000, ...)`. Default parameter values are evaluated ONCE at function definition time — `setattr(filters_mod, "LIQUIDITY_MIN_AVG_VOLUME", ...)` has no effect on the already-evaluated defaults. To make these patchable, `passes_liquidity` must be refactored to read from module globals instead of function defaults:
```python
LIQUIDITY_MIN_AVG_VOLUME = 750_000
LIQUIDITY_MIN_DOLLAR_VOLUME = 25_000_000

def passes_liquidity(df):
    return (median_vol >= LIQUIDITY_MIN_AVG_VOLUME and
            median_dollar >= LIQUIDITY_MIN_DOLLAR_VOLUME)
```
This refactor is a prerequisite before adding them to Optuna.

---

## Section 3: v4 Proposal

### HIGH priority — add to v4 search space

| Optuna key | Type | Range | Patch target |
|---|---|---|---|
| `CCI_STRICT_FLOOR` | float | -80 to -20 | `("engines.engine3", "CCI_STRICT_FLOOR")` |
| `CCI_RLX_FLOOR` | float | -40 to 0 | `("engines.engine3", "CCI_RLX_FLOOR")` |
| `MAX_OPEN_POSITIONS` | int | 3 to 8 | `("optimize_parameters", "MAX_OPEN_POSITIONS")` |

**Rationale:** CCI floors directly control how oversold a stock must be before the pullback engine fires. The current -50/-20 values are design choices, not empirically optimized. `MAX_OPEN_POSITIONS=5` is the primary portfolio cap — trading it off against drawdown is high-value. All three are patchable today without code changes.

### MEDIUM priority — require pre-work before adding

| Parameter | Pre-work needed |
|---|---|
| `LIQUIDITY_MIN_AVG_VOLUME` | Refactor `passes_liquidity` to use module globals instead of function defaults |
| `LIQUIDITY_MIN_DOLLAR_VOLUME` | Same refactor |
| `TRENDLINE_TOUCH_TOLERANCE_PCT` | Verify it's in engine3's module dict (should be via `from constants import`) |
| `VCP_ATR_CONTRACTION_THRESHOLD` | Identify which engine uses it, verify patchability |

### Already in v3 (do not re-add)

| Parameter | Optuna key |
|---|---|
| ATR stop multiplier | `ATR_MULTIPLIER` |
| VCP tightness | `VCP_TIGHTNESS_RANGE` |
| Breakout buffer | `BREAKOUT_BUFFER_ATR` |
| Volume surge multiplier | `BREAKOUT_VOL_MULT` |
| Take profit R:R | `TARGET_RR` |
| Trailing stop multiplier | `TRAIL_ATR_MULT` |
| Regime threshold | `REGIME_BULL_THRESHOLD` |
| Engine3 RS gate | `ENGINE3_RS_THRESHOLD` |

### Future v5 — requires BacktestEngine RS gate first

`RS_RANK_MIN_PERCENTILE`, `DISCOVERY_RS_MIN`, `DISCOVERY_RS_MAX` — all require adding a per-signal RS filter to `BacktestEngine` before they can meaningfully affect the Optuna objective.

---

## Appendix: How to Verify Patchability Before Adding a Parameter

To confirm a constant is patchable by `_patch_constants`, check:

1. **Is it read as a bare name inside a function body?** (`if rs_score < RS_REJECT_THRESHOLD`) → patchable
2. **Is it only used as a function default argument?** (`def foo(x=MY_CONST)`) → NOT patchable
3. **Which module owns the name?** `from constants import X` in `engine3.py` puts `X` in engine3's namespace → patch `("engines.engine3", "X")`, NOT `("constants", "X")`
4. **Does the calling code (WFO) actually reach that code path?** Scanner-only code is never reached → patching is pointless regardless
