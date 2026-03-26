# Technical Architecture Baseline Report
## Multi-Engine Swing Trading Scanner

> **Purpose:** Pre-refactor baseline covering scoring normalisation, market regime detection,
> and backtest metrics. Reference this before modifying `scoring.py`, `engine0.py`, or `wfo_optuna.py`.

---

## 1. Data & Indicators Layer

### DataFrame Structure

All price data comes from yfinance. Canonical columns:
- `Adj Close` — used for all indicator math
- `Close` — raw price, charting only

`compute_indicators()` caches output keyed on `(ticker, last_date, row_count)` and writes results as `_`-prefixed columns:

| Column | Calculation |
|--------|-------------|
| `_EMA8`, `_EMA20` | `series.ewm(span=N, adjust=False, min_periods=N).mean()` |
| `_SMA50`, `_SMA200` | `series.rolling(window=N, min_periods=N).mean()` |
| `_ATR14` | Wilder smoothing: `TR.ewm(alpha=1/14, adjust=False, min_periods=14).mean()` |
| `_VOLSMA50` | `Volume.rolling(50).mean()` — in engine6 applied with `.shift(1)` to prevent current-bar leakage |
| `_CCI` | See formula below |

### CCI Exact Formula (`indicators.py`)

```python
tp      = (high + low + close) / 3.0
tp_sma  = tp.rolling(window=20, min_periods=20).mean()
mean_dev = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
CCI     = (tp - tp_sma) / (0.015 * mean_dev)
```

CCI is **unbounded** — values range freely above/below ±100, ±200, etc.
This is a critical point for normalisation: it is NOT bounded like RSI.

### ATR True Range Construction

```python
TR = max(
    high - low,
    |high - prev_close|,
    |low  - prev_close|
)
# Then Wilder-smoothed with alpha = 1/14
```

### Volume Breakout Detection

Each engine computes `vol_ratio = current_bar_volume / vol_sma50` inline.
There is no pre-computed column for this ratio — it is calculated on the fly and stored in
the setup dict as `volume_ratio`. The SMA50 in engine6 uses `.shift(1)` (excludes current
bar from its own average) to prevent lookahead bias.

---

## 2. Engines & Trade Logic (Entry / Exit)

### Entry Conditions — Separation of Trend vs. Trigger

The system maintains a strict **two-layer gate**: macro trend filters must pass before
bar-level execution triggers are evaluated.

#### Engine 3 (Tactical Pullback) — Clearest Example

```
LAYER 1 — Trend context (required before any trigger):
  8 EMA > 20 EMA  AND  Close > 50 SMA

LAYER 2 — Value zone contact (price enters the band):
  Daily Low penetrates 8 EMA or 20 EMA

LAYER 3 — Structural support (Engine 1 KDE zone / pivot low / SMA200):
  Low within zone_lower / zone_upper

LAYER 4 — Bar-level execution trigger (pin bar):
  Daily Close >= 20 EMA  (rejection candle closed back above)

LAYER 5 — Momentum trigger:
  CCI[t-1] < CCI_STRICT_FLOOR (-50)  AND  CCI[t] > CCI[t-1]
```

The CCI hook is the **execution trigger**, not a trend filter.
It fires only when CCI is turning from oversold (< −50), not merely below zero.

#### Engine 6 (RES_BREAKOUT) Entry Gate

```
Trend filter:  Close > SMA50
Trigger:
  pre_close <= resistance < brk_close      (zone cross)
  AND  brk_close >= resistance × (1 + brk_min_pct)   (buffer)
  AND  vol_ratio >= brk_vol_mult           (institutional volume)
  AND  consolidation: >= N bars near resistance within 8%
```

#### Engine 2 (VCP) Trigger — BRK Path

```
Close above KDE resistance zone
+ vol >= 150% SMA50
+ O'Neil RS score > 0
```

### Exit Logic

The system uses an **EMA20 trailing stop** as the primary exit. There are **no time-based stops**.

```python
# trailing_engine.py — advance_ema20_trail()

Phase 1 (before trigger):
  stop = initial_stop  (fixed; defined at entry)

Phase 2 trigger (requires bars_since_entry >= 2):
  IF ref_level is None:                        trigger immediately on bar 2
  ELIF close > ref_level + 1.5 × ATR14:        trigger

Phase 2 trail logic per bar:
  IF close > EMA20 + 2.5 × ATR14:              # extended move
    new_trail = EMA20 + 1.5 × ATR14            # lock in gains above EMA20
  ELSE:                                         # normal trailing
    new_trail = prev_bar_EMA20 × (1 − ema_break_buffer)   # Optuna-tunable buffer

stop = max(stop, new_trail)     # ratchet — never moves down
```

**Stop placement at entry** (Pullback example):

```python
stop_loss = min(Low, zone_lower) − ATR_STOP_MULTIPLIER × ATR14
# ATR_STOP_MULTIPLIER = 0.8 (constants.py)
```

**Take Profit:** `nearest_resistance_target(entry, zones, risk)` — finds the next KDE
resistance level above entry. Fallback: `Entry + TARGET_RR × Risk` (TARGET_RR = 2.0).
In the current Optuna setup, **TARGET exits are disabled** — exit model is pure EMA20 trail.

---

## 3. Scoring System — Critical Deep Dive

### Component Weights (constants.py)

```
SCORE_WEIGHT_RS_RANK      = 25   cross-sectional RS percentile
SCORE_WEIGHT_RR           = 15   reward-to-risk ratio
SCORE_WEIGHT_VOL          = 20   volume / momentum
SCORE_WEIGHT_REGIME       = 10   market regime alignment
SCORE_WEIGHT_SECTOR       = 10   sector RS strength tier
SCORE_WEIGHT_QUALITY      =  5   pattern quality flags
SCORE_WEIGHT_RS_QUALITY   = 15   RS momentum signals
SCORE_WEIGHT_TREND_DUR    = 10   PULLBACK only: trend duration
SCORE_WEIGHT_SUPPORT_TIER = 10   PULLBACK only: support quality tier
SCORE_WEIGHT_COILING      =  5   WATCHLIST only: coiling tightness
```

> Note: weights sum > 100 because type-specific components do not all fire together.
> Final score is clamped: `min(100, max(0, int(round(raw))))`.

### Exact Formula (`scoring.py`)

```python
# 1. RS Rank — cross-sectional percentile
rs_pts = rs_rank / 100.0 * SCORE_WEIGHT_RS_RANK
if rs_rank >= RS_TIER1_THRESHOLD:
    rs_pts *= RS_TIER1_MULTIPLIER      # bonus multiplier for elite RS tier
rs_pts = min(SCORE_WEIGHT_RS_RANK, rs_pts)

# 2. Reward-to-Risk
rr_pts = min(SCORE_WEIGHT_RR, rr / 5.0 * SCORE_WEIGHT_RR)   # 5:1 R:R = full score

# 3. Volume (type-aware):
#    VCP / BASE / RES_BREAKOUT:
#      vol_ratio >= 2.0  →  full weight
#      vol_ratio >= 1.5  →  60% of weight
#      vol_ratio >= 1.2  →  30% of weight
#    PULLBACK:
#      no vol surge required; 30% baseline if support_source present
#    OPTIONS_CATALYST:
#      options_score / 100 × weight

# 4. Regime alignment
if AGGRESSIVE:  reg_pts = SCORE_WEIGHT_REGIME
if SELECTIVE:   reg_pts = SCORE_WEIGHT_REGIME × 0.53
if DEFENSIVE:   reg_pts = 0.0

# 5. Sector strength (3-tier)
if sector in top_sectors[:SECTOR_TIER1_N]:  pts = SCORE_WEIGHT_SECTOR        # full
elif sector in top_sectors:                 pts = SCORE_WEIGHT_SECTOR × 0.8  # tier 2
else:                                       pts = SCORE_WEIGHT_SECTOR × 0.4  # out of top

# 6. Pattern quality: linear map of quality_score (0–100) → 0..5 pts
# 7. RS Quality: additive flags — rs_vs_spy, rs_improving, rs_near_high,
#               rs_acceleration, tight_range_5d → capped at SCORE_WEIGHT_RS_QUALITY
# 8. Trend duration (PULLBACK only):
#    trend_bars >= 30 → 10pts; >= 20 → 7; >= 15 → 5; >= 10 → 2 → scaled to weight
# 9. Support tier (PULLBACK only):
#    KDE=5pts, PIVOT_LOW=4, SMA200=3, EMA50=2, EMA20=1 → scaled to weight
# 10. Extension penalty (PULLBACK only):
#    extension_atr > 1.5 → -4pts; > 0.75 → -2pts

raw = (rs_pts + rr_pts + vol_pts + reg_pts + sector_pts + qual_pts
       + rs_qual_pts + trend_dur_pts + support_tier_pts + coiling_pts
       - ext_penalty)
score = min(100, max(0, int(round(raw))))
```

### O'Neil RS Score Formula

```python
_RS_PERIODS = (63, 126, 189, 252)     # 3m, 6m, 9m, 12m
_RS_WEIGHTS = (0.40, 0.20, 0.20, 0.20)

rs_score = sum(
    weight × (ticker_return(period) - spy_return(period))
    for period, weight in zip(_RS_PERIODS, _RS_WEIGHTS)
) / total_weight
```

Cross-sectional percentile rank: each ticker's raw RS score is compared against the
full universe; `rank = count(scores < this_score) / N × 100`.

### Current Normalisation — The Weak Point

**There is no Z-score, no Min-Max scaling, no dynamic weighting.**
All components are hand-crafted linear mappings to fixed point bands.

| Feature | Current handling | Problem |
|---------|-----------------|---------|
| `volume_ratio` | 3-step function: ≥2.0/1.5/1.2 | Cliff edges; 4.0x = 2.0x; no continuous scale |
| `rr` | Linear, saturates at 5:1 | RR=6 scores same as RR=5 |
| `rs_rank` | Linear + tier-1 multiplier kink | Non-smooth boost at 90th pct |
| CCI value | **Never used in scoring** | Entry gate only; magnitude ignored |
| Volume absolute | Never in score | Only ratio appears (good) |
| RS quality flags | Binary True/False → fixed pts | No gradient for partial signals |

---

## 4. Market Regime

### Engine 0 — 7-Factor Scoring (Live Scanner)

```python
f1 = 20 pts   if  SPY.Close > EMA20(SPY)
f2 = 15 pts   if  SPY.Close > SMA50(SPY)
f3 = 15 pts   if  SMA50(SPY) > SMA200(SPY)       # Stage 2 MA stack
f4 = 0..10    # EMA20 slope over 5 bars:
              # pct_slope  = (ema20[-1] - ema20[-6]) / ema20[-6]
              # slope_score = (pct_slope + 0.005) / 0.01 × 10  (clamped 0–10)
              # +0.5% over 5 bars → full 10pts; −0.5% → 0pts
f5 = 0..20    # breadth_pct × 20    (fraction of universe above SMA50)
f6 = 0..10    # hl_ratio × 10       (new_highs / (new_highs + new_lows + 1))
f7 = 10 pts   if  VIX.Close < VIX.SMA20

regime_score = f1 + f2 + f3 + f4 + f5 + f6 + f7   # 0–100
AGGRESSIVE   if score >= 70
SELECTIVE    if 40 <= score < 70
DEFENSIVE    if score < 40
```

### Backtest / WFO Regime (4/7 factors, `filters.py`)

f5, f6, f7 require live universe data and cannot be replicated historically.
The backtest uses only f1–f4 (max 60 pts) with proportionally scaled thresholds:

```python
_BACKTEST_REGIME_MAX        = 60
_BACKTEST_REGIME_AGGRESSIVE = round(70 / 100 * 60) = 42
_BACKTEST_REGIME_SELECTIVE  = round(40 / 100 * 60) = 24

score  = f1 + f2 + f3 + f4    # 0–60 max
regime = AGGRESSIVE if score >= 42 else SELECTIVE if score >= 24 else DEFENSIVE
```

This makes the backtest regime **softer** than the live regime — more bars classified as
AGGRESSIVE/SELECTIVE, leading to higher signal counts in backtest vs live.

### Regime → Engine / Score Influence

```
DEFENSIVE:
  ├─ Engines 2 (VCP) and 3 (PULLBACK) SKIPPED entirely
  ├─ Regime score component = 0 pts
  └─ SELECTIVE_SETUP_WEIGHTS can hard-block specific setups (currently empty)

SELECTIVE:
  ├─ All engines run
  ├─ Regime score component = 0.53 × SCORE_WEIGHT_REGIME (~8 pts instead of 15)
  ├─ WATCHLIST: minimum coiling_score >= 2 required
  └─ RS floor: RS_RANK_MIN_PERCENTILE_SELECTIVE (higher bar than AGGRESSIVE)

AGGRESSIVE:
  ├─ All engines run, no restrictions
  ├─ Regime score component = full SCORE_WEIGHT_REGIME (15 pts)
  └─ RS floor: RS_RANK_MIN_PERCENTILE_AGGRESSIVE (65th percentile)
```

---

## 5. Backtesting & Optimization

### Tracked Metrics (`wfo_optuna._compute_metrics`)

Every trade carries `rr_achieved = (exit_price − entry_price) / (entry_price − initial_stop)`.

| Metric | Exact Calculation |
|--------|-------------------|
| `win_rate` | `len(rr > 0) / total × 100` |
| `expectancy` | `mean(rr_achieved)` — R-multiples, not % |
| `profit_factor` | `sum(positive_rr) / abs(sum(negative_rr))`, capped at 99 |
| `max_drawdown_r` | Peak-to-trough of cumulative R curve |
| `portfolio_return_pct` | Compounded equity `∏(1 + pnl_pct/100)`, assuming 1% risk/trade |
| `by_setup` | Count per engine type |
| `stop_stats` | avg / min / median / max stop distance as % of entry |
| `hold_stats` | avg holding days |

> **No Sharpe ratio, no Sortino, no Calmar of % returns** — only Calmar of R-multiples.
> `portfolio_return_pct` exists but assumes constant 1% position sizing throughout.

### Objective Function (Optuna)

```python
def _objective_score(metrics):
    n        = metrics["total_trades"]
    ex       = metrics["expectancy"]          # mean R-multiple
    pf       = min(metrics["profit_factor"], 10.0)
    mdd      = abs(metrics["max_drawdown_r"]) # peak-to-trough R drawdown
    win_rate = metrics["win_rate"]            # in %

    # Hard penalties:
    if n < 100:
        return -9.0 - (100 - n) * 0.01       # forces minimum sample size
    if win_rate > 80%:
        return -5.0                           # overfit signal

    if ex <= 0 or pf <= 0:
        return float(ex)                      # negative; Optuna routes away

    calmar      = ex / max(0.1, mdd)          # expectancy-to-drawdown ratio
    raw         = calmar × pf × log(N + 1)   # base score
    trade_scale = min(1.0, sqrt(N / 200))    # smooth scaling; avoids cliff at 200

    # Engine diversity penalty (soft):
    # max_engine_pct > 70% → score × max(0.4, 1.0 − (pct − 0.70) × 2.0)

    return raw × trade_scale
```

The objective **maximises Calmar-adjusted expectancy × PF × log(N)**, scaled by
square-root trade-count. Rewards consistent gains with low R-drawdowns over
high-PF strategies from small samples.

**Known limitation:** `mdd` is in R-multiples, not portfolio %. No time-sensitivity —
a single -2R loss scores the same drawdown as 4 sequential -0.5R losses.

### WFO Window Structure

```
IS = 24 months    OOS = 12 months    Step = 12 months    Anchor = 2019-01-01

W1: IS [2019-01-01 → 2021-01-01]   OOS [2021-01-01 → 2022-01-01]
W2: IS [2020-01-01 → 2022-01-01]   OOS [2022-01-01 → 2023-01-01]
W3: IS [2021-01-01 → 2023-01-01]   OOS [2023-01-01 → 2024-01-01]
W4: IS [2022-01-01 → 2024-01-01]   OOS [2024-01-01 → 2025-01-01]
```

Windows overlap: consecutive IS windows share 12 months of data (rolling anchored design,
not expanding window). Each window has an independent Optuna study at `data/wfo_final_w{N}.db`.
Frozen baseline params (`#433`) evaluated on all 4 OOS windows as comparison point.

### Tunable Parameters (14 active)

```
score_threshold          [1.0, 4.0]    signal quality gate
brk_vol_mult             [1.1, 1.6]    RES_BREAKOUT volume threshold
brk_stop_atr             [0.8, 1.5]    stop distance in ATR units
brk_min_pct              [0.01, 0.05]  minimum close above resistance
brk_gap_pct              [0.01, 0.08]  max gap above resistance on entry
brk_donchian_n           [20, 60]      rolling-high lookback bars
brk_atr_expansion        [0.0, 0.5]    bar range expansion filter
brk_min_consolidation    [3, 8]        min bars consolidating near resistance
rs_threshold             [-0.02, 0.03] bar-level RS gate for PULLBACK
cci_threshold            [-45, -20]    CCI hook floor for PULLBACK
ema_distance             [0.5, 1.2]    EMA proximity gate for PULLBACK
base_quality_min         [15, 30]      BASE pattern minimum quality score
base_vol_ratio           [1.1, 1.5]    BASE pattern volume requirement
ema_break_buffer         [0.0, 0.01]   EMA20 trail buffer (Optuna-tunable)
```

---

## 6. Summary of Identified Weaknesses for Refactor

| Area | Current State | Problem |
|------|--------------|---------|
| **Scoring normalisation** | Hand-coded step functions | Volume step-cliffs; no Z-score; no continuous scaling |
| **Volume scoring** | 3-step thresholds (1.2/1.5/2.0) | Ratio=4 scores same as ratio=2; extreme events get no premium |
| **RR scoring** | Linear, saturates at 5:1 | Trades with 6:1 RR don't outscore 5:1 |
| **RS rank scoring** | Linear + tier-1 kink at 90th pct | Non-smooth boost; not documented as non-linear |
| **CCI in scoring** | Entry gate only; value never scored | Continuous momentum strength is never quantified |
| **RS quality flags** | Binary True/False → fixed pts | No gradient for partial signal strength |
| **Regime detection** | 7-factor binary/linear sum | f4 slope is linear; f5/f6 are fractions; no non-linear regime states |
| **Backtest metrics** | R-multiple Calmar only | No time-adjusted Sharpe/Sortino; drawdown in R not equity %; no MAR ratio on % returns |
| **WFO objective** | Calmar × PF × log(N) | No IS/OOS degradation penalty; no sequential drawdown weighting |
| **Regime asymmetry** | Live=7 factors, backtest=4 | Backtest consistently softer → overstated signal counts vs live |
