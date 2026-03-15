# Optuna V5 Analysis — 242 Trials
**Date:** 2026-03-11
**Study:** data/optuna_v5.db
**Trials:** 242 total, 217 valid (10% penalty rate for <200 trades)
**Best trial:** #225, score=1.6423

---

## 1. Convergence Assessment

| Parameter | Best Trial | CV | Status |
|---|---|---|---|
| `tp_multiple` | 3.999 | 0.016 | **Converged** (near ceiling 4.0) |
| `brk_vol_mult` | 2.49 | 0.023 | **Converged** |
| `ema_distance` | 1.48 | 0.061 | **Converged** |
| `pullback_weight` | 2.52 | 0.067 | **Converged** |
| `cci_threshold` | −54 | 0.092 | **Converged** |
| `brk_trail_mult` | — | ~0.15 | Moderate |
| `cooldown_days` | — | ~0.15 | Moderate |
| `breakout_weight` | — | ~0.17 | Moderate |
| `brk_stop_atr` | 0.42 | ~0.18 | Moderate (fitting noise — see §3) |
| `brk_min_pct` | — | ~0.18 | Moderate |
| `score_threshold` | 2.55 | 0.326 | **Not converged** |
| `rs_threshold` | — | 0.476 | **Not converged** |

Score progression: 0.96 (trial 0) → 1.64 (trial 225), still climbing at end.
The study needs ~100 more trials before calling it done.

**Warning:** `tp_multiple` converged at 3.999, which is the ceiling of the [1.5, 4.0] range.
Optuna is asking for more room. Expand to [1.5, 6.0] in the next run.

---

## 2. Pullback Engine — Strong Performer

**Cache baseline (289-ticker, non-scored defaults):**

| Metric | Value |
|---|---|
| Trades | 1,146 |
| Win Rate | 49.5% |
| Expectancy | +0.110R |
| Profit Factor | 1.60 |

In the best trial (scored mode): **244 of 268 trades (91%)** — PULLBACK dominates.

Optuna correctly intensified:
- `pullback_weight`: 1.0 → 2.52
- `cci_threshold`: −20 → −54 (requires deeper oversold)
- `ema_distance`: 0.75 → 1.48 (requires stronger trend)

**Conclusion:** Pullback is working. The main lever still unexplored is `score_threshold`
(CV=0.326, not converged) — the engine may be accepting marginal setups that dilute expectancy.

---

## 3. Why Breakout Produces Zero Trades

RES_BREAKOUT: **0 trades in the best trial** despite all engine refactoring.
Root causes in priority order:

### a) Universe too small for simultaneous gate satisfaction
The 289-ticker parquet cache is a partial universe. The breakout engine requires ALL of:
- 5 tight launchpad bars under resistance
- ≥2% decisive close above zone
- ≥2.5× volume (converged value)
- Close in top 30% of bar range
- Price ≤5% above zone upper
- Above 50 SMA

On 289 stocks over a 2-year WFO window, this combination fires rarely.
The 30 trades seen in the cache baseline came from default (non-scored) mode —
scored mode's `score_threshold=2.55` then filtered them to 0.

### b) `brk_stop_atr` converging at 0.42 is suspect
Tighter stops → more premature exits → lower PF → optimizer fitting noise, not signal.
With 0 breakout trades, Optuna has no real breakout surface to learn from.
The 0.42 value should be treated as unreliable until the full universe cache exists.

### c) `pullback_weight=2.52` crowds out breakouts
In scored mode, PULLBACK fills all capacity before any breakout signal gets taken.
`breakout_weight` has no leverage when the relative pullback weight is 2.5×.

**Fix plan:** Build full 1572-ticker cache. Only then run a dedicated breakout Optuna phase.
Current breakout param optimization is fitting noise on an empty signal.

---

## 4. Base Engine — Small Sample, High Quality

**Cache baseline:**

| Metric | Value |
|---|---|
| Trades | 54 |
| Win Rate | 35.2% |
| Expectancy | +0.282R |
| Profit Factor | 2.63 |

Best trial shows **24 BASE trades (9%)** — consistent with baseline ratio.
High E and PF are promising but n=54 has wide confidence intervals.
Not contributing enough volume to drive the objective function meaningfully.

HTF: E=+0.408R, PF=3.41 on n=12 — too small to conclude anything.

---

## 5. Parameters to Freeze for Next Pullback Phase

**Freeze these (converged, stable):**
```
tp_multiple    = 3.999   # ⚠ raise ceiling to 6.0 first, re-run to confirm true optimum
ema_distance   = 1.48
pullback_weight = 2.52
cci_threshold  = -54
```

**Do NOT freeze yet (not converged or fitting noise):**
```
score_threshold   # CV=0.326, needs 100+ more trials
rs_threshold      # CV=0.476, wildly noisy
brk_stop_atr      # fitting noise (0 breakout trades in optimization)
brk_min_pct       # same
brk_gap_pct       # same
```

---

## 6. Structural Improvements Before Dedicated Breakout Phase

In priority order:

### a) Build full 1572-ticker WFO cache
Prerequisite for everything else. Without it, breakout optimization is impossible.
Current 289-ticker cache is too sparse for the multi-gate breakout filter.

### b) Expand `tp_multiple` ceiling to 6.0
Currently wall-bounded at 4.0. Run 50 trials with the wider range to confirm the true
optimum before freezing.

### c) Add `brk_regime_factor` to BacktestParams
`RES_SELECTIVE_REGIME_FACTOR=0.80` is hard-coded. In SELECTIVE regime, breakout scores
get a 20% penalty that Optuna cannot see or tune.
Make it tunable: range [0.5, 1.0].

### d) Run 100 more trials on current study
Resume with `python3 optimize_v5.py --resume --trials 100`.
`score_threshold` and `rs_threshold` are the biggest unknowns.
Study was still improving at trial 225 — don't freeze params yet.

### e) Dedicated breakout Optuna (after a–d)
Freeze all pullback params. Search only `brk_*` params over the full ticker universe.
This is the correct way to characterize the breakout engine independently.

---

## Recommended Next Actions (ordered)

1. `python3 optimize_v5.py --resume --trials 100` with `tp_multiple` range expanded to [1.5, 6.0]
2. Build 1572-ticker WFO parquet cache in parallel
3. After 350 trials: freeze `tp_multiple`, `ema_distance`, `pullback_weight`, `cci_threshold`
4. Add `brk_regime_factor` to BacktestParams
5. Dedicated breakout Optuna run on full universe
