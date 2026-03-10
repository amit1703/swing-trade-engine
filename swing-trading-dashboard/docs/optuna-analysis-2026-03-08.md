# Optuna Study Analysis — trading_optimizer_v2
**Date:** 2026-03-08
**Trials completed:** 76 / 100 (optimizer still running, PID 30041)
**Best score:** 0.0309
**Study DB:** `swing-trading-dashboard/optuna_study.db`

---

## Top 20 Trials

| Rank | Trial | Score  | ATR_M | VCP_T  | BRK_B | BRK_V | RR   | TRAIL | Trades | Win%  | Exp    | PF    | DD%   | Net%  |
|------|-------|--------|-------|--------|-------|-------|------|-------|--------|-------|--------|-------|-------|-------|
| 1    | 74    | 0.0309 | 1.364 | 0.0466 | 0.410 | 1.141 | 2.43 | 2.454 | 163    | 42.9  | 0.0649 | 1.353 | 14.11 | 14.46 |
| 2    | 73    | 0.0309 | 1.367 | 0.0471 | 0.384 | 1.144 | 2.44 | 2.360 | 164    | 42.7  | 0.0647 | 1.353 | 14.12 | 14.50 |
| 3    | 61    | 0.0306 | 1.334 | 0.0423 | 0.409 | 1.008 | 2.47 | 2.326 | 169    | 43.2  | 0.0599 | 1.350 | 13.36 | 14.37 |
| 4    | 72    | 0.0298 | 1.354 | 0.0470 | 0.412 | 1.135 | 2.52 | 2.364 | 167    | 42.5  | 0.0620 | 1.348 | 14.09 | 15.08 |
| 5    | 51    | 0.0277 | 1.331 | 0.0443 | 0.403 | 1.107 | 2.53 | 2.253 | 166    | 43.4  | 0.0590 | 1.340 | 14.29 | 14.18 |
| 6    | 62    | 0.0274 | 1.335 | 0.0421 | 0.405 | 1.084 | 2.46 | 2.317 | 167    | 43.1  | 0.0579 | 1.345 | 14.30 | 14.10 |
| 7    | 65    | 0.0230 | 1.382 | 0.0477 | 0.401 | 1.076 | 2.40 | 2.324 | 166    | 42.8  | 0.0499 | 1.300 | 14.14 | 12.47 |
| 8    | 63    | 0.0225 | 1.336 | 0.0458 | 0.400 | 1.068 | 2.45 | 2.305 | 169    | 43.2  | 0.0490 | 1.299 | 14.31 | 12.71 |
| 9    | 31    | 0.0197 | 1.299 | 0.0433 | 0.398 | 1.091 | 2.48 | 2.440 | 165    | 43.0  | 0.0441 | 1.274 | 14.25 | 11.32 |
| 10   | 66    | 0.0194 | 1.398 | 0.0476 | 0.394 | 1.070 | 2.40 | 2.199 | 167    | 42.5  | 0.0435 | 1.279 | 14.43 | 11.79 |
| 11   | 49    | 0.0183 | 1.286 | 0.0454 | 0.444 | 1.109 | 2.54 | 2.150 | 163    | 42.3  | 0.0394 | 1.260 | 13.47 | 10.76 |
| 12   | 25    | 0.0180 | 1.315 | 0.0359 | 0.410 | 1.004 | 2.48 | 2.377 | 168    | 42.9  | 0.0388 | 1.255 | 13.59 | 10.72 |
| 13   | 28    | 0.0178 | 1.301 | 0.0434 | 0.327 | 1.101 | 2.49 | 2.420 | 164    | 43.3  | 0.0405 | 1.254 | 14.24 | 10.67 |
| 14   | 53    | 0.0175 | 1.363 | 0.0419 | 0.435 | 1.108 | 2.57 | 1.857 | 163    | 42.3  | 0.0400 | 1.264 | 14.32 | 10.97 |
| 15   | 26    | 0.0175 | 1.315 | 0.0422 | 0.418 | 1.000 | 2.48 | 2.343 | 169    | 42.6  | 0.0377 | 1.251 | 13.59 | 10.60 |
| 16   | 27    | 0.0172 | 1.310 | 0.0357 | 0.404 | 1.087 | 2.51 | 2.422 | 165    | 43.0  | 0.0392 | 1.249 | 14.25 | 10.52 |
| 17   | 52    | 0.0172 | 1.397 | 0.0445 | 0.456 | 1.117 | 2.61 | 2.037 | 161    | 42.2  | 0.0397 | 1.263 | 14.43 | 10.87 |
| 18   | 41    | 0.0169 | 1.310 | 0.0356 | 0.408 | 1.092 | 2.49 | 2.396 | 165    | 43.0  | 0.0386 | 1.247 | 14.27 | 10.42 |
| 19   | 34    | 0.0147 | 1.316 | 0.0403 | 0.321 | 1.140 | 2.55 | 2.409 | 167    | 41.9  | 0.0337 | 1.233 | 14.21 | 10.47 |
| 20   | 22    | 0.0136 | 1.331 | 0.0313 | 0.474 | 1.004 | 2.68 | 2.119 | 166    | 42.2  | 0.0300 | 1.229 | 13.60 |  9.55 |

**Column key:** ATR_M = ATR_MULTIPLIER, VCP_T = VCP_TIGHTNESS_RANGE, BRK_B = BREAKOUT_BUFFER_ATR,
BRK_V = BREAKOUT_VOL_MULT, RR = TARGET_RR, TRAIL = TRAIL_ATR_MULT,
Exp = expectancy, PF = profit_factor, DD% = max_drawdown_pct, Net% = net_profit_pct

---

## Score Distribution

| Stat        | Value  |
|-------------|--------|
| Maximum     | 0.0309 |
| Top-10 avg  | 0.0262 |
| Top-25 avg  | 0.0195 |
| Median      | 0.0043 |
| Bottom      | -0.0223|
| Negative scores | 30 / 76 (40%) |

The wide spread between median (0.004) and top (0.031) shows that parameter choice matters significantly. 40% of trials are net-negative, meaning random parameters destroy value.

---

## 1. Parameters That Matter Most

### ATR_MULTIPLIER — Primary Driver
- **Correlation with score: r = +0.659** (strongest of all 6 parameters)
- **Sensitivity delta: +0.018** (high-half avg vs low-half avg)
- Top-10 avg: **1.350** vs all-trial avg: **1.261** — a clear directional pull upward
- Low ATR values (0.82–1.10) produce mostly negative scores; tight stops get noise-triggered
- All top-10 trials fall in **1.30–1.40**
- **Interpretation:** Stop placement is the most consequential decision. Too tight = constant whipsaw. The system needs 1.3–1.4× ATR below the swing low to survive intraday noise.

### TRAIL_ATR_MULT — Second Driver
- **Correlation: r = +0.624**
- **Sensitivity delta: +0.012**
- Top-10 avg: **2.33** vs all avg: **2.11**
- Trailing stops tighter than 2.0× ATR cut winners prematurely; 2.2–2.45 is the sweet spot
- **Interpretation:** Letting winners run is as important as avoiding whipsaw on entries. The system's edge is right-skewed returns (few big winners) — a tight trail destroys that asymmetry.

### BREAKOUT_VOL_MULT — Third Driver (Inverse)
- **Correlation: r = −0.420** (negative — lower is better)
- **Sensitivity delta: −0.017**
- Top-10 avg: **1.09** vs all avg: **1.29** — strong pull toward the lower bound
- High volume requirements (>1.5×) miss valid breakouts without quality improvement
- All top-10 have BREAKOUT_VOL_MULT **< 1.15**
- **Interpretation:** Volume confirmation at 1.0–1.1× is sufficient. Requiring 1.5–2.0× volume surge is too restrictive and filters out profitable setups that break out on average volume.

### BREAKOUT_BUFFER_ATR — Moderate Driver
- **Correlation: r = +0.388**
- **Sensitivity delta: +0.013**
- Tightest convergence: top-10 spans only **7% of the search space** (0.384–0.412)
- **Interpretation:** Entry must be slightly above resistance (0.38–0.42× ATR), not at it. Too close = false breakout risk; too far = chasing.

---

## 2. Parameters That Barely Affect Results

### TARGET_RR — Weak Effect
- **Correlation: r = +0.300** — weakest positive relationship
- **Sensitivity delta: +0.005** — smallest of all parameters
- Top-10 range: 2.40–2.53 but trials with RR=1.82 and RR=2.97 aren't dramatically different
- **Reason:** The trailing stop (TRAIL_ATR_MULT) is the actual exit mechanism for winning trades. Most profitable trades hit the trail before the fixed target. The target mainly caps runaway winners.

### VCP_TIGHTNESS_RANGE — Weak-Moderate Effect
- **Correlation: r = +0.308**
- **Sensitivity delta: +0.005**
- Higher values (tighter VCP qualification) slightly improve results, but the effect is small relative to ATR parameters
- **Reason:** The RS filter (≥70th percentile) and regime gate already screen out most low-quality setups before VCP tightness is checked.

---

## 3. Sensitivity Ranges (Optimal Zones)

| Parameter           | Optimal Zone    | Search Space  | Coverage | Notes                          |
|---------------------|----------------|---------------|----------|-------------------------------|
| ATR_MULTIPLIER      | 1.30 – 1.40    | 0.80 – 1.40   | 17%      | Strong convergence, near ceiling |
| TRAIL_ATR_MULT      | 2.20 – 2.45    | 1.00 – 2.50   | 17%      | Strong convergence, near ceiling |
| BREAKOUT_BUFFER_ATR | 0.38 – 0.42    | 0.10 – 0.50   | 7%       | Very tight, mid-range          |
| BREAKOUT_VOL_MULT   | 1.00 – 1.15    | 1.00 – 2.00   | 14%      | Floor effect — may go lower    |
| TARGET_RR           | 2.40 – 2.55    | 1.80 – 3.00   | 12%      | Moderate convergence, mid-range |
| VCP_TIGHTNESS_RANGE | 0.042 – 0.048  | 0.015 – 0.050 | 14%      | Ceiling effect — may go higher |

**Boundary effects to investigate:**
- `ATR_MULTIPLIER` and `TRAIL_ATR_MULT` converge near the **upper bounds** of search space — consider extending to 1.6 and 3.0 respectively in v3
- `BREAKOUT_VOL_MULT` clusters at the **lower bound** — consider extending range down to 0.8 (any volume expansion)
- `VCP_TIGHTNESS_RANGE` clusters at the **upper bound** — consider extending to 0.06–0.07

---

## 4. Signs of Overfitting

### Low Overfitting Risk (positive signals)

| Signal | Observation | Interpretation |
|--------|-------------|----------------|
| Trade count | Mean 165, stdev 7 | High sample size per trial; no lucky sparse results |
| Win rate range | 34.7% – 43.4%, stdev 2.4% | Compressed — no anomalous outliers |
| Best score | 0.031 (modest) | Not suspiciously high; real edge is small |
| Score convergence | Slow, diminishing returns | No sharp overfit spike |
| Top-10 parameter spread | 17% of ATR search space | Gradual convergence, not point collapse |
| Negative trials | 40% of trials negative | Optimizer cannot easily fool itself |

**Score improvement trajectory:**
```
Trials  0–09:  best = -0.0020  (random exploration)
Trials 10–19:  best =  0.0054
Trials 20–29:  best =  0.0180  (first good region found)
Trials 30–39:  best =  0.0197
Trials 40–49:  best =  0.0197  (plateau)
Trials 50–59:  best =  0.0277
Trials 60–69:  best =  0.0306  (refinement)
```
Slow, stepwise improvement is a healthy sign. An overfit study would jump to high scores and never improve.

### Mild Concern

**BREAKOUT_BUFFER_ATR convergence to 7% of search space** is unusually tight. When one parameter locks in this precisely on WFO OOS data, it may reflect the specific structure of the 2015–2025 dataset more than a timeless edge. Worth monitoring in live performance.

**All top trials use similar ATR + TRAIL combinations.** The parameter space may have one narrow ridge rather than a broad plateau — meaning small deviations from optimal could hurt more than the WFO metrics suggest. Run sensitivity tests around the best parameters in isolation.

---

## 5. Trade Frequency Patterns

### Distribution
```
150–159 trades:  ████████████▌  13 trials
160–169 trades:  ████████████████████████████████████████████████  48 trials  ← modal bin
170–179 trades:  ████████████  12 trials
180–189 trades:  █  1 trial
190–199 trades:  █  1 trial
```

| Stat   | Value |
|--------|-------|
| Min    | 153   |
| Max    | 195   |
| Mean   | 165   |
| Stdev  | 7.0   |

### Key Findings

**Parameters barely affect trade count.** Stdev of 7 across 75 diverse parameter combinations means the entry/exit logic generates a consistent ~165 trades per WFO period regardless of tuning. The regime gate, liquidity filter, and RS rank filter (all fixed, not optimized) are controlling frequency. This is a healthy architectural sign — the optimizer is improving quality, not just changing trade count.

**Worse trials generate *more* trades.** Bottom-20 avg: 169.9 trades vs top-20 avg: 165.7. When stops are too tight (low ATR_MULTIPLIER), more false entries occur and get stopped out quickly, slightly inflating trade count while destroying expectancy.

**Win rate is the real differentiator:**

| Group    | Win Rate | Expectancy | Profit Factor | Net Profit |
|----------|----------|------------|---------------|------------|
| Top-20   | 42.8%    | +0.047     | 1.287         | +12.0%     |
| Bottom-20| 37.4%    | −0.066     | 0.866         | −6.8%      |

A 5.4 percentage point win rate difference separates profitable from unprofitable. The optimizer is essentially finding stop/trail configurations that prevent good setups from being exited prematurely before the trade works.

---

## Recommended Best Parameters (current best)

Based on trial #74 (score 0.0309):

```json
{
  "ATR_MULTIPLIER":      1.364,
  "VCP_TIGHTNESS_RANGE": 0.0466,
  "BREAKOUT_BUFFER_ATR": 0.410,
  "BREAKOUT_VOL_MULT":   1.141,
  "TARGET_RR":           2.43,
  "TRAIL_ATR_MULT":      2.454
}
```

**OOS performance at best parameters:**
- Total trades: 163
- Win rate: 42.9%
- Expectancy: 0.065R per trade
- Profit factor: 1.353
- Max drawdown: 14.1%
- Net profit: 14.5%

---

## Suggested v3 Search Space Adjustments

| Parameter           | Current Range  | Suggested v3 Range | Reason                              |
|---------------------|---------------|-------------------|-------------------------------------|
| ATR_MULTIPLIER      | 0.80 – 1.40   | 1.20 – 1.60       | Extend ceiling; low end never wins  |
| TRAIL_ATR_MULT      | 1.00 – 2.50   | 1.80 – 3.00       | Extend ceiling; tighter never wins  |
| BREAKOUT_VOL_MULT   | 1.00 – 2.00   | 0.80 – 1.30       | Extend floor; high values hurt      |
| VCP_TIGHTNESS_RANGE | 0.015 – 0.050 | 0.035 – 0.070     | Extend ceiling; low end never wins  |
| BREAKOUT_BUFFER_ATR | 0.10 – 0.50   | 0.30 – 0.50       | Narrow to confirmed zone            |
| TARGET_RR           | 1.80 – 3.00   | 2.20 – 2.80       | Narrow to confirmed zone            |

---

*Generated by Claude Code | 2026-03-08 | 76/100 trials completed*
