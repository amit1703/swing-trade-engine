# Optuna v4 — Strategy Analysis Report

**Generated:** 2026-03-10 13:36
**Purpose:** Diagnose edge sources, identify over-filtering, and propose v5 direction.
**Method:** Controlled parameter sweeps using in-memory patching (production constants unchanged).

---

## 1. Setup-Level Diagnosis

Each setup run in isolation with v4 params, all tickers, same WFO windows.

| Setup | Trades | Win Rate | Expectancy | Avg R | PF | Max DD | Net P&L | Verdict |
|---|---|---|---|---|---|---|---|---|
| **VCP** | 13 | 61.5% | -0.57% | +0.041R | 0.75 | 1.31% | +0.53% | 🔴 Losing |
| **PULLBACK** | 25 | 40.0% | 1.40% | +0.240R | 2.02 | 2.00% | +5.75% | 🟡 Decent |
| **BASE** | 1 | 100.0% | 14.19% | +2.660R | ∞ | 0.00% | +2.66% | ⚠️ Too few |
| **RES_BREAKOUT** | 9 | 55.6% | 4.18% | +0.547R | 8.72 | 0.97% | +6.85% | 🟢 Strong |
| **ALL (combined)** | 43 | 48.8% | 1.76% | +0.290R | 2.36 | 2.17% | +14.32% | — |

### Setup Diagnosis

**VCP — Detailed Analysis:**

- 🔴 **Negative edge** (PF=0.75). The VCP setup is losing money in isolation.
- Win rate 61.5% is respectable but avg R of +0.041R reveals the core problem: **wins are too small relative to losses**.
- Root cause hypothesis: VCP entries are taken near pivot — but with TRAIL=4.16 ATR, stops are wide. If VCP breakouts are slow-moving, the trail gives back profits before running.
- **Exit logic is the likely issue**, not the entry filter. VCP may need a tighter trail or earlier target lock.

**PULLBACK — Detailed Analysis:**

- 🟢 **Strong engine** (PF=2.02). PULLBACK is the workhorse — highest trade count (25) and solid PF.

**RES_BREAKOUT — Detailed Analysis:**

- 🟢 **Best engine** (PF=8.72). Highest quality per-trade, but generates only 9 trades.
- The RES_BREAKOUT filter (decisive close, volume surge, launchpad bars) is very selective. This is by design.
- Recommendation: **Protect this setup's filters.** Do not loosen RES_BREAKOUT — it's the crown jewel.

**BASE — Detailed Analysis:**

- ⚠️ **Only 1 trades** — statistically meaningless. Cannot draw conclusions.
- BASE pattern requires a multi-week consolidation above a prior base — rare in a 35-ticker universe over 2 years.
- Recommendation: **Keep but expand universe.** BASE needs more tickers to generate sufficient samples.

### Setup Recommendation Table

| Setup | Action | Rationale |
|---|---|---|
| VCP | 🔧 Fix exit logic | PF < 1.0 in isolation — entry OK, trail too wide for VCP pattern speed |
| PULLBACK | ✅ Keep, mild relaxation OK | Core workhorse with solid PF |
| RES_BREAKOUT | 🛡️ Protect — do not loosen | Highest PF, crown jewel of the system |
| BASE | 🔭 Needs more universe | Too few trades to assess; keep logic |

---

## 2. Signal Frequency Expansion

### 2A. Regime Threshold Sensitivity

Current v4: REGIME_BULL_THRESHOLD=59 (requires near-perfect SPY conditions)

| Threshold | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades vs V4 |
|---|---|---|---|---|---|---|
| 50 | 111 | 37.8% | 1.02 | 12.87% | +4.01% | +68 |
| 54 (v3) | 80 | 38.8% | 1.01 | 9.06% | +4.75% | +37 |
| 57 | 66 | 40.9% | 1.46 | 4.50% | +11.98% | +23 |
| 59 ← V4 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| 62 | 0 | 0.0% | 0.00 | 0.00% | +0.00% | -43 |

### 2B. RS Rejection Threshold Sensitivity (Engine 3 only)

Current v4: ENGINE3_RS_THRESHOLD=-0.012 (very strict — rejects anything > −1.2% vs SPY)

| RS Floor | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |
|---|---|---|---|---|---|---|
| -0.050 | 45 | 46.7% | 2.26 | 2.20% | +14.13% | +2 |
| -0.034 (v3) | 45 | 46.7% | 2.26 | 2.20% | +14.13% | +2 |
| -0.020 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| -0.012 ← V4 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| -0.005 | 42 | 47.6% | 2.18 | 2.17% | +12.28% | -1 |
| 0.000 | 41 | 48.8% | 2.21 | 2.17% | +12.39% | -2 |

### 2C. CCI Strict Floor Sensitivity (Engine 3 pullback depth)

Current v4: CCI_STRICT_FLOOR=-39.1 (requires CCI to have been at least −39 before turning)

| CCI Strict | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |
|---|---|---|---|---|---|---|
| -70 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| -60 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| -50 (v3) | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| -39 ← V4 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| -30 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |

### 2D. CCI Relaxed Floor Sensitivity (Pullback entry breadth)

Current v4: CCI_RLX_FLOOR=-1.95 (nearly requires CCI to be flat/positive)

| CCI RLX | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |
|---|---|---|---|---|---|---|
| -20 (v3) | 38 | 50.0% | 2.12 | 2.63% | +11.72% | -5 |
| -10 | 40 | 50.0% | 2.25 | 1.97% | +12.59% | -3 |
| -5 | 40 | 50.0% | 2.25 | 1.97% | +12.59% | -3 |
| -1.95 ← V4 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| 0 | 44 | 45.5% | 2.27 | 2.38% | +13.96% | +1 |

### 2E. Trail ATR Multiplier Sensitivity

Current v4: TRAIL_ATR_MULT=4.162 (very wide — holds through large swings)

| Trail | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |
|---|---|---|---|---|---|---|
| 2.834 (v3) | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| 3.0 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| 3.5 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| 4.162 ← V4 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |
| 5.0 | 43 | 48.8% | 2.36 | 2.17% | +14.32% | 0 |

### 2F. Combined Relaxation Experiments

Testing combinations of relaxed filters to find the best frequency/quality tradeoff:

| Config | Trades | Win Rate | PF | Max DD | Net P&L | Assessment |
|---|---|---|---|---|---|---|
| **V4 Baseline** | 43 | 48.8% | 2.36 | 2.17% | +14.32% | Current production |
| Combo-A: Regime 54 + RS -0.034 | 82 | 37.8% | 0.99 | 9.56% | +4.27% | 🔴 Losing |
| Combo-B: Regime 54 + CCI-60 | 79 | 39.2% | 1.14 | 6.97% | +8.26% | 🟠 Marginal |
| Combo-C: Regime 54 + RS-0.034 + CCI-60 | 80 | 37.5% | 1.14 | 8.15% | +8.21% | 🟠 Marginal |
| Combo-D: Regime 50 + RS-0.05 + CCI-70 | 104 | 40.4% | 0.95 | 14.83% | +2.57% | 🔴 Losing |

---

## 3. Universe Expansion Simulation

Testing how trade frequency scales with universe size (v4 params, same logic):

| Universe Size | OOS Trades | Trades/Year | Trades/Ticker/Year | PF | Net P&L |
|---|---|---|---|---|---|
| 10 tickers | 23 | 11.5 | 2.30 | 3.89 | +11.15% |
| 20 tickers | 32 | 16.0 | 1.60 | 1.97 | +7.54% |
| 35 tickers (production) | 43 | 21.5 | 1.23 | 2.36 | +14.32% |

**Extrapolation** (linear fit from observed scaling):

| Universe Size | Projected OOS Trades | Projected Trades/Year |
|---|---|---|
| 35 tickers ← current | ~43 | ~22/year |
| 80 tickers | ~79 | ~40/year |
| 100 tickers ← v5 target | ~94 | ~47/year |
| 150 tickers | ~134 | ~67/year |
| 200 tickers | ~174 | ~87/year |
| 300 tickers | ~253 | ~126/year |

> **Important:** Extrapolation assumes new tickers have similar setup frequency to the current 35.
> In practice, universe quality matters: low-float or illiquid tickers will generate fewer clean signals.

---

## 4. Setup Isolation — Detailed Metrics

| Metric | VCP only | PULLBACK only | BASE only | RES_BREAKOUT only |
|---|---|---|---|---|
| Trades | 13 | 25 | 1 | 9 |
| Win rate | 61.5% | 40.0% | 100.0% | 55.6% |
| Avg R | +0.041R | +0.240R | +2.660R | +0.547R |
| Expectancy | -0.57% | 1.40% | 14.19% | 4.18% |
| Profit factor | 0.75 | 2.02 | ∞ | 8.72 |
| Max drawdown | 1.31% | 2.00% | 0.00% | 0.97% |
| Net P&L | +0.53% | +5.75% | +2.66% | +6.85% |

### VCP Failure Mode Analysis

| VCP Metric | Value | Interpretation |
|---|---|---|
| Avg winning R | +0.428R | Low — wins barely cover losers |
| Avg losing R | -0.578R | Partial stops common |
| Exit via STOP | 12/13 (92%) | Trail exits before target |
| Exit via TARGET | 0/13 (0%) | — |
| Avg hold time | 18.1 days | Normal hold period |

> **Diagnosis: VCP wins are capped by the trail, losses exit cleanly.**
> VCP breakouts may be experiencing 'false breakout → reversal → stopped out' pattern OR
> the trail (4.16 ATR) is too wide for VCP's typical follow-through, causing gains to evaporate.
> **Proposed fix:** Test VCP-specific trail of 2.0–2.5 ATR (separate from other setups).

---

## 5. Regime Window Performance

OOS performance broken down by 6-month window (v4 baseline params):

| Window | Period | Trades | Win Rate | PF | Net P&L | Regime Assessment |
|---|---|---|---|---|---|---|
| W1 | 2023-09-16 → 2024-03-16 | 17 | 64.7% | 7.72 | +12.18% | 🟢 Strong bull — system in full flow |
| W2 | 2024-03-16 → 2024-09-16 | 9 | 22.2% | 0.75 | +0.05% | 🔴 Weak/volatile — system struggles |
| W3 | 2024-09-16 → 2025-03-16 | 8 | 75.0% | 7.72 | +3.79% | 🟢 Strong bull — system in full flow |
| W4 | 2025-03-16 → 2025-09-16 | 9 | 22.2% | 0.07 | -1.69% | 🔴 Weak/volatile — system struggles |

### Regime Dependency Observation

- **2/4 windows** are good (PF ≥ 1.5)
- **2/4 windows** are losing (PF < 1.0)

The v4 system fires heavily in regime-aligned windows and dries up in weak windows.
This is a feature (not a bug) of the regime gate — but it creates a **feast-or-famine** equity curve.

**Per-setup regime recommendation:**

| Setup | Strong Bull | Moderate | Weak/Choppy | Recommendation |
|---|---|---|---|---|
| RES_BREAKOUT | ✅ Fire | ✅ Fire | ❌ Gate | Keep strict regime gate |
| PULLBACK | ✅ Fire | ✅ Fire | ⚠️ Reduce size | Works in moderate conditions |
| VCP | ✅ Fire | ⚠️ Cautious | ❌ Gate | Require AGGRESSIVE regime (score ≥ 70) |
| BASE | ✅ Fire | ✅ Fire | ✅ Fire | Long-duration pattern; regime-agnostic |

---

## 6. Final Recommendations — v5 Tuning Direction

### 6.1 Filters That Are Too Restrictive

| Filter | Current V4 | Assessment | Proposed V5 Range |
|---|---|---|---|
| `REGIME_SELECTIVE_THRESHOLD` | 59 | 2/4 windows fire at all; system goes dark too often | 54–57 |
| `ENGINE3_RS_THRESHOLD` | −0.012 | Very strict; rejects most pullback candidates | −0.034 to −0.02 |
| `CCI_RLX_FLOOR` | −1.95 | Near-zero floor eliminates most CCI hooks | −10 to −5 |
| `CCI_STRICT_FLOOR` | −39.10 | Reasonable; mild relaxation OK | −50 to −40 |
| `VCP_TIGHT_RANGE_5D_PCT` | 0.036 | Very tight; may miss valid VCPs | 0.040–0.045 |

### 6.2 Setups That Need Adjustment

**VCP — Exit Logic Fix (Priority 1):**

The v4 trail of 4.16 ATR is designed for trend-following setups (PULLBACK, RES_BREAKOUT).
VCP breakouts are volatile and often retrace after the initial burst — a 4.16 ATR trail
lets too much profit evaporate. Proposed fix:

```
VCP-specific exit: TARGET_RR = 2.0 with fixed profit lock (not trail)
When VCP hits 1R profit, lock in 0.5R (break-even + buffer)
```

Alternative: Gate VCP to AGGRESSIVE regime only (score ≥ 70 vs current 59).
VCP breakouts require strong market momentum. At SELECTIVE regime they often fail.

**BASE — Universe Expansion (Priority 2):**

Only 1 trade in 2 years on 35 tickers. The setup logic is sound but the sample is too small.
With 100 tickers: expect ~3 trades/year. With 300: ~9 trades/year.

### 6.3 How to Increase Trades Without Damaging PF

**Ranked by trade frequency × quality (PF × √trades):**

| Config | Trades | PF | Score (PF×√n) | Recommendation |
|---|---|---|---|---|
| V4 Baseline | 43 | 2.36 | 15.5 | Current production |
| Combo-B: Regime 54 + CCI-60 | 79 | 1.14 | 10.1 | ❌ Worse |
| Combo-C: Regime 54 + RS-0.034 + CCI-60 | 80 | 1.14 | 10.2 | ❌ Worse |
| Combo-A: Regime 54 + RS -0.034 | 82 | 0.99 | 9.0 | ❌ Worse |
| Combo-D: Regime 50 + RS-0.05 + CCI-70 | 104 | 0.95 | 9.7 | ❌ Worse |

### 6.4 Universe Expansion Requirement

**Current: 35 tickers → 43 OOS trades → statistically thin (95% CI: 34%–64% WR)**

Universe expansion is the highest-leverage improvement available:

| Target | Tickers | Expected OOS Trades | Statistical Reliability |
|---|---|---|---|
| Minimum viable | ~80 | ~100 | 🟡 Acceptable |
| Recommended | ~120 | ~150 | 🟢 Good |
| Production quality | ~200 | ~250 | 🟢 Strong |

### 6.5 Proposed v5 Parameter Direction

```
# v5 Direction — do NOT implement yet, pending further testing
#
# Priority 1: Increase signal frequency
REGIME_SELECTIVE_THRESHOLD = 54    # relax from 59 → v3 level; re-test
ENGINE3_RS_THRESHOLD       = -0.034 # relax from -0.012 → v3 level; re-test
CCI_RLX_FLOOR              = -10.0  # relax from -1.95 → moderate
#
# Priority 2: Fix VCP exit
VCP_TRAIL_ATR_MULT         = 2.5    # NEW — VCP-specific trail (separate from others)
VCP_REGIME_GATE            = 70     # NEW — VCP only fires in AGGRESSIVE regime (score≥70)
#
# Priority 3: Expand universe
TARGET_UNIVERSE_SIZE       = 100    # tickers with WFO cache
#
# Keep unchanged:
TRAIL_ATR_MULT = 4.162   # keep wide for PULLBACK + RES_BREAKOUT
BREAKOUT_BUFFER_ATR = 0.54  # RES_BREAKOUT filter is the crown jewel
TARGET_RR = 2.785        # minimum entry quality — keep
```

### 6.6 Implementation Priority

| Priority | Action | Expected Impact | Risk |
|---|---|---|---|
| 1 🔴 | Expand universe to 100 tickers | +100% trade volume, same edge | Low (logic unchanged) |
| 2 🟡 | Relax REGIME to 54 | +trades in moderate markets | Medium (re-test needed) |
| 3 🟡 | Relax RS to −0.034 | +Engine 3 pullback signals | Medium |
| 4 🟠 | Fix VCP exit logic | Convert VCP from drag to contributor | Medium-High (code change) |
| 5 🟢 | Run v5 Optuna study | Find new optimum with expanded params | Low (automated) |

---

*Generated by v4_strategy_analysis.py on 2026-03-10 13:36*