# SELECTIVE RES_BREAKOUT Diagnostic — Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Scope:** Pure diagnostic — no decisions, no weight changes, no live scanner impact

---

## Context

The 2020-2024 backtest (668 trades) confirmed AGGRESSIVE regime has a clear edge. SELECTIVE regime
is near breakeven, with PULLBACK in SELECTIVE at +0.039R expectancy (WEAK). RES_BREAKOUT in
SELECTIVE has been completely blocked by `brk_aggressive_only: bool = True` in `BacktestParams`
since an earlier OOS finding. No performance data exists for RES_BREAKOUT in SELECTIVE.

The goal of this work is to collect unbiased raw performance data for SELECTIVE RES_BREAKOUT before
making any decisions about enabling, filtering, or tuning it.

---

## Constraint: Diagnostic Only

- Do NOT call `_suggest_weight()`
- Do NOT modify `constants.py`
- Do NOT connect anything to the live scanner
- No weights, no decisions — only data

---

## Design

### Change 1 — `backtest_engine.py`

Single line change to `BacktestParams`:

```python
brk_aggressive_only: bool = False   # was True
```

This is the only code change. With `brk_aggressive_only=False`, the existing `brk_regime_factor`
score discount (0.861) is applied automatically in SELECTIVE. The AGGRESSIVE path is completely
untouched.

### Change 2 — `scripts/backtest_selective_brk.py`

One-off disposable diagnostic script. Does not write to cache, does not touch any endpoint.

**Inputs:**
- WFO parquet cache (`data/price_cache/`, 2020-2024, ~828 tickers, no network calls)
- `BacktestParams()` defaults (now with `brk_aggressive_only=False`)

**Output — side-by-side comparison table:**

| Metric           | AGGRESSIVE RES_BREAKOUT | SELECTIVE RES_BREAKOUT | SELECTIVE PULLBACK (ref) |
|------------------|-------------------------|------------------------|--------------------------|
| Trade count      | n                       | n                      | n                        |
| Win rate         | %                       | %                      | %                        |
| Avg R            | x.xx                    | x.xx                   | x.xx                     |
| Expectancy       | x.xx R                  | x.xx R                 | x.xx R                   |
| Avg hold days    | n                       | n                      | n                        |

SELECTIVE PULLBACK is included as a known reference (+0.039R confirmed) to validate the backtest
run is consistent with previous results.

---

## Deliverables

| File | Change |
|------|--------|
| `backend/backtest_engine.py` | `brk_aggressive_only: bool = False` |
| `scripts/backtest_selective_brk.py` | One-off diagnostic runner — prints table, no cache write |

Two files. The script is disposable.

---

## What Happens After

The diagnostic output is reviewed by the user. A separate design spec will cover any follow-on
decisions (weight setting, filtering, Optuna tuning) based on what the data shows.
