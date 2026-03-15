# Walk-Forward Optuna Validation Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Implement `wfo_optuna.py` — a standalone CLI that runs per-window Optuna optimization across 4 rolling IS/OOS windows, then validates the production-frozen params (trial #433) on the same OOS windows for comparison.

**Architecture:** New standalone script following the pattern of `optimize_v5.py` and `oos_validation.py`. Each IS window runs its own Optuna study (resumable SQLite DB). OOS evaluation uses the best IS params frozen. A second pass applies the current `BacktestParams()` defaults (trial #433) to every OOS window. A final report prints both equity curves and a parameter stability table.

**Tech Stack:** Optuna TPE, asyncio + Semaphore (same as optimize_v5.py), parquet cache from `data/price_cache/`, BacktestEngine, BacktestParams.

---

## Windows

4 rolling windows, starting 2019-01-01, IS=24 months, OOS=12 months, step=12 months:

| Window | IS Train                  | OOS Test                  |
|--------|---------------------------|---------------------------|
| 1      | 2019-01-01 → 2020-12-31   | 2021-01-01 → 2021-12-31   |
| 2      | 2020-01-01 → 2021-12-31   | 2022-01-01 → 2022-12-31   |
| 3      | 2021-01-01 → 2022-12-31   | 2023-01-01 → 2023-12-31   |
| 4      | 2022-01-01 → 2023-12-31   | 2024-01-01 → 2024-12-31   |

## Optuna Search Space (same as optimize_v5.py)

6 tunable parameters per IS window:
- `tp_multiple`    [1.5, 6.0]
- `brk_vol_mult`   [1.5, 3.5]
- `brk_stop_atr`   [0.3, 2.0]
- `brk_min_pct`    [0.01, 0.05]
- `brk_gap_pct`    [0.01, 0.08]
- `brk_trail_mult` [1.5, 8.0]

All other params frozen at trial #433 values (current `BacktestParams()` defaults).

Objective: `expectancy × PF × log(trades + 1)` (same as optimize_v5.py).
Minimum trades gate: 200 (returns PENALTY_SCORE = -99.0 if below).

## Per-Window Storage

- Optuna DBs: `data/wfo_w1.db` … `data/wfo_w4.db`
- Results JSON: `data/wfo_optuna_results.json`
- Study names: `wfo_v1` … `wfo_v4`

## Evaluation Flow

For each window:
1. Create/resume Optuna study in `data/wfo_wN.db`
2. Run 100 trials on IS period using `_run_trial()` (reused from optimize_v5 pattern)
3. Extract best trial params → build `BacktestParams`
4. Run single OOS backtest with best IS params → record metrics
5. Store IS best params + OOS metrics in results list

After all windows:
6. Run frozen trial #433 params on each OOS window → second equity curve
7. Stitch all OOS windows chronologically → combined equity curve (both optimized + frozen)
8. Print report (see below)
9. Save `data/wfo_optuna_results.json`

## Final Report Sections

### Section A — OOS Performance Table
Side-by-side optimized vs frozen params per window:
```
Window  IS Period          OOS Period          N    WR%   E(R)    PF    MaxDD   Port%   SPY%   Alpha
  1     2019-01 → 2020-12  2021-01 → 2021-12  ...
  ...
  AVG / WORST
```

### Section B — Combined OOS Equity Curve
Text sparkline of compounded portfolio return (1% risk/trade) stitched across all 4 OOS periods.
Both curves (optimized and frozen #433) printed for visual comparison.

### Section C — Parameter Stability Table
How the 6 tunable params shifted between IS windows:
```
Param           W1-best   W2-best   W3-best   W4-best   mean    std    CV
tp_multiple     ...
brk_vol_mult    ...
...
```
CV < 0.15 = stable. CV > 0.30 = regime-sensitive, flagged.

### Section D — Robustness Verdict
OOS vs IS degradation, stability score, verdict: ROBUST / MODERATE / OVERFIT / FRAGILE.

## CLI Interface

```bash
python3 wfo_optuna.py [--trials 100] [--resume] [--windows 1,2,3,4]
```

- `--trials N`     Optuna trials per IS window (default: 100)
- `--resume`       Resume existing Optuna studies instead of creating fresh
- `--windows 1,3`  Run only specific windows (useful for parallelizing across machines)

## Files Touched

- **Create:** `backend/wfo_optuna.py`
- **No changes** to `wfo_engine.py`, `optimize_v5.py`, `main.py`, or `backtest_engine.py`
