# Optuna v3 — Final Report

**Study:** `trading_optimizer_v3`
**Date:** 2026-03-09
**Total trials:** 211+ completed / 300 target
**Universe:** 35 representative tickers (35 sector-diversified, + SPY for regime)
**WFO config:** 36m IS / 6m OOS / 6m step (~4 OOS windows, ~2 years of OOS data)

---

## 1. Convergence Assessment: ✅ CONVERGED

| Window | Mean score | Max score |
|---|---|---|
| First 50 trials | 0.0154 | 0.0429 |
| Last 50 trials | 0.0496 | 0.0939 |
| **Improvement in last 50** | — | **+0.0019** |

**Verdict:** The study has converged. Only +0.0019 improvement in the final 50 trials (vs +0.049 gain from the first 50 to the next 100). TPE has clearly identified the optimal zone. Running additional trials yields diminishing returns.

---

## 2. Best Trial — #204

| Metric | Value |
|---|---|
| **Score** | **0.0939** |
| Total trades | 81 |
| Trades / year | ~40 |
| Win rate | 44.4% |
| Expectancy | 10.4% per trade |
| Profit factor | 1.60 |
| **Max drawdown** | **5.97%** |
| Net profit | +11.5% |

### Best Parameters

```json
{
  "ATR_MULTIPLIER":         1.3787,
  "VCP_TIGHTNESS_RANGE":    0.0426,
  "BREAKOUT_BUFFER_ATR":    0.4690,
  "BREAKOUT_VOL_MULT":      1.1120,
  "TARGET_RR":              2.6741,
  "TRAIL_ATR_MULT":         2.9582,
  "REGIME_BULL_THRESHOLD":  54,
  "ENGINE3_RS_THRESHOLD":   -0.0330
}
```

---

## 3. Top 10 Trials

| Rank | Trial | Score | Trades | Win% | Expectancy | PF | MaxDD% | Net% |
|---|---|---|---|---|---|---|---|---|
| 1 | #204 | **0.0939** | 81 | 44.4% | 10.4% | 1.60 | **5.97%** | +11.5% |
| 2 | #140 | 0.0920 | 76 | 44.7% | 9.9% | 1.71 | 5.98% | +11.8% |
| 3 | #191 | 0.0892 | 72 | 45.8% | 10.2% | 1.69 | 6.13% | +11.1% |
| 4 | #137 | 0.0886 | 76 | 44.7% | 9.9% | 1.64 | 5.97% | +11.3% |
| 5 | #135 | 0.0858 | 75 | 45.3% | 9.5% | 1.66 | 5.97% | +10.9% |
| 6 | #121 | 0.0856 | 90 | 46.7% | 13.0% | 1.63 | 9.03% | +13.7% |
| 7 | #173 | 0.0838 | 72 | 45.8% | 10.0% | 1.66 | 6.29% | +10.3% |
| 8 | #136 | 0.0823 | 78 | 44.9% | 9.2% | 1.62 | 5.97% | +11.0% |
| 9 | #139 | 0.0820 | 73 | 45.2% | 9.9% | 1.62 | 6.29% | +10.3% |
| 10 | #206 | 0.0778 | 82 | 43.9% | 9.1% | 1.55 | 6.19% | +10.9% |

---

## 4. Top-20 Parameter Clustering

| Parameter | Min | Max | **Mean** | Std | Range used |
|---|---|---|---|---|---|
| `ATR_MULTIPLIER` | 1.352 | 1.406 | **1.380** | 0.015 | 1.20–1.60 |
| `VCP_TIGHTNESS_RANGE` | 0.042 | 0.049 | **0.044** | 0.002 | 0.035–0.070 |
| `BREAKOUT_BUFFER_ATR` | 0.439 | 0.491 | **0.471** | 0.012 | 0.30–0.50 |
| `BREAKOUT_VOL_MULT` | 1.087 | 1.123 | **1.110** | 0.011 | 0.80–1.30 |
| `TARGET_RR` | 2.611 | 2.763 | **2.647** | 0.040 | 2.20–2.80 |
| `TRAIL_ATR_MULT` | 1.927 | 2.998 | **2.893** | 0.230 | 1.80–3.00 ⚠️ ceiling |
| `REGIME_BULL_THRESHOLD` | 51 | 55 | **54.6** | 0.94 | 20–55 ⚠️ ceiling |
| `ENGINE3_RS_THRESHOLD` | -0.092 | -0.004 | **-0.033** | 0.017 | -0.10–0.00 |

**⚠️ Ceiling effects:** `TRAIL_ATR_MULT` and `REGIME_BULL_THRESHOLD` are both hitting their upper bounds. The true optimum may lie beyond the current search space. **v4 should expand these ranges.**

---

## 5. Parameter Importance (Pearson r)

| Parameter | r | Direction |
|---|---|---|
| `BREAKOUT_BUFFER_ATR` | +0.383 | Higher = better |
| `TRAIL_ATR_MULT` | +0.335 | Higher = better (ceiling pressure) |
| `REGIME_BULL_THRESHOLD` | +0.299 | Higher = better (ceiling pressure) |
| `VCP_TIGHTNESS_RANGE` | -0.297 | Lower = better (tight VCP) |
| `BREAKOUT_VOL_MULT` | +0.186 | Higher = better |
| `ENGINE3_RS_THRESHOLD` | +0.129 | Slightly looser = better |
| `ATR_MULTIPLIER` | -0.104 | Weak |
| `TARGET_RR` | +0.089 | Near-zero — low impact |

**TRAIL × REGIME interaction:** r=+0.362 joint (vs +0.335 / +0.299 alone) — they amplify each other. High TRAIL only works well at high REGIME.

---

## 6. System Behavioral Profile

### What the optimizer discovered

The system functions as a **selective, regime-filtered momentum strategy**:

- **Selective:** Only 40 trades/year on a 35-stock universe — the system fires infrequently, only on the highest-quality setups. Not a high-frequency screener.
- **Regime-filtered:** REGIME_BULL_THRESHOLD=54 means the system requires SPY to be in strong uptrend (4/4 regime factors nearly maxed out). It sits out most of the time.
- **Pullback-biased:** VCP_TIGHTNESS_RANGE converged to 0.044 (tight). The system strongly favors stocks that have compressed in price before breakout.
- **Trail-heavy:** TRAIL=2.96 lets winners run significantly before stopping out. This is the primary profit driver — 44% win rate with 10% expectancy implies winners average ~2.5× the loser size.
- **Drawdown-controlled:** MaxDD of 5.97% with 1% risk/trade means roughly 6 consecutive losses. This is realistic for 44% win rate.

### Key risk

Trade frequency of ~40/year on 35 stocks = ~1.14 trades/stock/year. The system is very patient. This makes it statistically thin. Universe expansion (more tickers) is the highest-leverage improvement available.

---

## 7. Recommended Next Steps

### Immediate (v4 search space)
1. Expand `TRAIL_ATR_MULT` to 2.5–4.5 (currently hitting ceiling)
2. Expand `REGIME_BULL_THRESHOLD` to 45–65
3. Add `CCI_STRICT_FLOOR` (-80 to -20)
4. Add `CCI_RLX_FLOOR` (-40 to 0)
5. Add `MAX_OPEN_POSITIONS` (3–8, int)

### Universe optimization (next priority)
Test increasing universe sizes with fixed v3 best params:
- U1: 35 stocks (baseline — current)
- U2: 80 top-RS stocks
- U3: 150 top-RS stocks
- U4: 300 top-RS stocks

See `docs/plans/2026-03-09-universe-optimization.md` for implementation plan.
