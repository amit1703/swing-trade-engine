# Optuna Constrained Search Space — RES_BREAKOUT
Generated: 2026-03-25

## Motivation

The previous unconstrained Optuna run (v5 trial #433) produced RES_BREAKOUT parameters
at or near the upper edge of the search range — a classic sign of boundary overfitting.
Parameters that are mathematically optimal on historical data but impossible to reproduce
in live markets degrade live performance without any backtest warning.

## Old vs New Search Space

| Parameter | Old Range | Old Best | New Range | Rationale |
|-----------|-----------|----------|-----------|-----------|
| `brk_vol_mult` | [1.5, 3.5] | **3.016** | **[1.2, 2.0]** | 300% volume is rarely sustained; 120–200% is the institutional breakout norm (O'Neil standard is 1.5×) |
| `brk_stop_atr` | [0.3, 2.0] | **1.668** | **[0.8, 1.5]** | <0.8 stops get hit by normal intraday noise; >1.5 creates oversized risk relative to setup size |
| `brk_atr_expansion` | **not tuned** (frozen at 1.474) | 1.474 | **[0.0, 1.0]** | 1.474× ATR required as bar range is too strict; live default is 0.0 (disabled). Range lets Optuna decide if it adds value |
| `brk_min_consolidation` | **not tuned** (frozen at 10) | 10 | **[5, 20]** | 10 bars is in the middle of the range — worth searching; live default is 3 (too loose) |
| `brk_min_pct` | [0.01, 0.05] | 0.043 | [0.01, 0.05] | Unchanged — range is already reasonable |
| `brk_gap_pct` | [0.01, 0.08] | 0.010 | [0.01, 0.08] | Unchanged |
| `brk_trail_mult` | [1.5, 8.0] | 6.906 | [1.5, 8.0] | Unchanged — trail mult is setup-specific; wide range acceptable |
| `score_threshold` | [1.0, 4.0] | 2.50 | [1.0, 4.0] | Unchanged |
| `tp_multiple` | [1.5, 9.0] | 5.80 | [1.5, 9.0] | Unchanged |

## Overfitting Evidence for Constrained Params

### `brk_vol_mult = 3.016`
- Old range was [1.5, 3.5]. Best value landed at 3.016 — 86% of the way to the upper bound.
- In practice, 300% volume on a breakout occurs on ~5% of breakout days.
- Requiring 3× volume eliminates the vast majority of valid institutional breakouts.
- This inflates historical win rate by extreme selectivity that doesn't generalise OOS.

### `brk_stop_atr = 1.668`
- Old range was [0.3, 2.0]. Best value landed at 1.668 — 84% of the way to the upper bound.
- At 1.668× ATR below the resistance zone, the stop is placed well inside the base,
  meaning a routine retest of the breakout level would not stop the trade.
- However, the live scanner uses `RES_STOP_ATR_FACTOR = 0.8` — the backtest was trading
  a fundamentally different risk profile. The gap makes live performance unpredictable.

### `brk_atr_expansion = 1.474` (previously not in search space)
- Was hardcoded in BacktestParams at 1.474. The live scanner has this disabled (0.0).
- Requiring 1.474× ATR bar range filters out all low-volatility breakouts, which often
  outperform high-range breakouts (less exhaustion). This parameter was never tested
  at 0.0 vs non-zero in an Optuna run — it was simply inherited from a prior run.
- New range [0.0, 1.0] lets Optuna determine if any expansion filter is warranted.

## Parameters NOT Changed (and why)

| Parameter | Value | Reason kept |
|-----------|-------|-------------|
| `rs_threshold` | 0.066 | Frozen from v5 #433; controls pullback RS gate; separate optimization needed |
| `cci_threshold` | -54.5 | Frozen from v5 #433; interacts with score_threshold |
| `brk_donchian_n` | 87 | Out of scope this run; notable that live default=63 differs — add to next run |
| `brk_trail_mult` | [1.5, 8.0] | No live equivalent to compare against; leave range open |

## Files Changed

| File | Change |
|------|--------|
| `wfo_optuna.py` | `_build_params`: narrowed `brk_vol_mult` to [1.2,2.0], `brk_stop_atr` to [0.8,1.5]; added `brk_atr_expansion` [0.0,1.0] and `brk_min_consolidation` [5,20] to search |
| `wfo_optuna.py` | `TUNABLE_PARAMS`: added `brk_atr_expansion`, `brk_min_consolidation` |
| `wfo_optuna.py` | `_build_params_from_values`: fallbacks updated to constrained-range midpoints for `brk_vol_mult` (1.6) and `brk_stop_atr` (1.15); added new param fallbacks |
| `backtest_engine.py` | `BacktestParams`: annotated unconstrained values as pending re-run |

## How to Run the Constrained Optimization

```bash
cd swing-trading-dashboard/backend

# Fresh run (recommended — old DBs used unconstrained space)
python wfo_optuna.py --trials 500

# Or resume with pruned study (drops old trials outside new bounds)
python wfo_optuna.py --trials 500 --resume
```

> **Warning:** Do NOT use `--resume` if the old SQLite DB (data/wfo_final_w*.db) exists
> from the unconstrained run. Optuna will attempt to continue a study with incompatible
> parameter bounds and will mix old out-of-range samples with new constrained ones.
> Delete or rename the old `.db` files before running.

## Expected Impact (Qualitative)

| Metric | Expected Direction | Reasoning |
|--------|--------------------|-----------|
| Total trades | **↑ increase** | Lower vol threshold (2.0 vs 3.0) admits more breakouts |
| Win rate | **↓ slight decrease** | Less extreme selectivity → some lower-quality breakouts included |
| Expectancy | **stable or slight ↓** | More trades, slightly lower avg quality — net similar expectancy |
| Max drawdown | **↓ lower** | Tighter stop (1.5 vs 1.668 ATR) = smaller per-trade loss |
| Live alignment | **↑ significant improvement** | Parameters within range of live scanner defaults |

## When to Update Live Constants

After the constrained run completes:
1. Review OOS metrics across all 4 windows — look for **consistency**, not just peak IS score
2. If constrained OOS expectancy ≥ unconstrained OOS expectancy: sync to live constants
3. Update in `constants.py`: `RES_BREAKOUT_VOL_MULT`, `RES_STOP_ATR_FACTOR`
4. Update in `engine6.py`: `_MIN_CONSOL_DEFAULT`, `_ATR_EXP_DEFAULT`
5. Update `BacktestParams` defaults to new constrained best values
