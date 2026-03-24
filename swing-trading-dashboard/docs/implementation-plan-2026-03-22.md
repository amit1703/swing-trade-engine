# System Redesign — Implementation Plan
*Date: 2026-03-22 | Follows: system-audit-2026-03-22.md*

---

## Priority Order

1. Trend duration fix (lowest risk, highest alpha impact)
2. RS gate calibration (one-line constant change)
3. Structural support expansion — Tier 2/3
4. Coiling logic fix (ATR-normalized)
5. Two operating modes (wires everything together)

---

## 1. Trend Duration Fix

### What Changes

Remove the 20-bar hard cliff. Replace with:
- **Hard floor: 10 bars** (absolute minimum — below this, indicators are unreliable)
- **Score component: 0–10 pts** (graduated above 10 bars)

### Scoring Function

```
trend_bars < 10   → reject (hard gate)
10 ≤ bars < 15    → +2 pts
15 ≤ bars < 25    → +5 pts
25+ bars          → +10 pts
```

Simple step function. Monotonic. No edge cases.

### Files to Change

**`constants.py`**
```python
PB_MIN_TREND_BARS = 10   # was 20 — hard floor only, scoring handles the rest
```

**`engine3.py`** — `scan_pullback()`, `scan_relaxed_pullback()`, `scan_pullback_scored()`

The trend duration check already exists. Change the threshold reference from 20 to `PB_MIN_TREND_BARS` (which is now 10). No structural change needed — it's already reading from the constant.

Also: include `trend_bars` in the returned signal dict so `scoring.py` can score it:
```python
# In the return dict of scan_pullback() and scan_relaxed_pullback():
"trend_bars": _trend_bars,
```

**`scoring.py`** — `compute_setup_score()`

Add trend duration component for PULLBACK and BASE setups:
```python
# Trend duration score (only applies to pullback setups)
SCORE_WEIGHT_TREND_DURATION = 10  # new weight

if setup.get("setup_type") in ("PULLBACK",):
    tb = setup.get("trend_bars", 0)
    if tb >= 25:
        trend_score = 10
    elif tb >= 15:
        trend_score = 5
    elif tb >= 10:
        trend_score = 2
    else:
        trend_score = 0
    score += round(trend_score * SCORE_WEIGHT_TREND_DURATION / 10)
```

### Expected Impact

- Unlocks first-pullback-after-breakout setups (10–19 bars)
- Approximately +15–25% more pullback signals
- Those signals score lower on trend duration (2–5 pts vs 10 pts) but can compensate via RS rank, volume, regime
- The highest-scoring first-pullbacks will be ones with RS rank 85+ in AGGRESSIVE regime — exactly where you want early entries

---

## 2. RS Gate Calibration

### What Changes

Lower hard floor from 70 to 65. Everything else unchanged.

**`constants.py`**
```python
RS_RANK_MIN_PERCENTILE = 65   # was 70
```

### Why 65

- Top 35% of universe — still solid relative strength, not noise
- The score component (25–30pts from RS rank) will naturally down-weight stocks at 65–70 vs 85+
- A stock at RS rank 67 with great volume and AGGRESSIVE regime can still score 72+ overall and deserve a signal
- At RS rank < 65, stocks are in the bottom two-thirds of the universe — the probability of a clean trending pullback drops sharply
- Keeps the gate as a quality floor, not a precision instrument (the score is the precision instrument)

### Expected Impact on Trade Distribution

- Trade frequency: approximately +8–12% more signals
- New signals will cluster in the 65–69 RS band
- Most will be filtered by `min_score` anyway — only ones with strong compensating factors (high regime, good volume, clean structure) will survive
- Net new quality signals per week: estimate +2–4

---

## 3. Structural Support Expansion

### Tier System

The `_find_structural_support()` function in `engine3.py` gains two new conditional tiers.

**Tier 1 — Always valid (unchanged)**
1. KDE support zone (Engine 1)
2. Prior pivot low (CONSOLIDATION_LOW)
3. SMA200 touch

**Tier 2 — EMA50, conditional**
- Conditions: `regime == "AGGRESSIVE"` AND `rs_rank >= 85`
- Proximity: `ll <= ema50 * 1.005` (low dipped to within 0.5% above EMA50) AND `lc >= ema50 * 0.985` (close holds within 1.5% below EMA50)
- Source label: `"EMA50"`

**Tier 3 — EMA20, strict conditional**
- Conditions: `regime == "AGGRESSIVE"` AND `rs_rank >= 90` AND `trend_bars >= 15`
- Proximity: `ll <= ema20 * 1.005` (low dipped to within 0.5% above EMA20) AND `lc >= ema20` (close must fully recover to EMA20 — strict pin bar required)
- Source label: `"EMA20"`

### Why These Proximity Rules

EMA50 is a slower average — a 0.5% proximity gives a real "touch" signal without catching bars that are just near it. The 1.5% close tolerance allows for slight undercuts that recover.

EMA20 is faster and more sensitive. The close must fully recover above EMA20 (pin bar rule) because a close below EMA20 in a Tier 3 situation (very strong stock) is a yellow flag, not a support confirmation.

### Function Signature Change

`_find_structural_support()` needs two new parameters:

```python
def _find_structural_support(
    ll, lc, sr_zones, trendline,
    high, low, close, volume, avg_vol,
    latr=0.0, sma200=0.0,
    ema20=0.0, ema50=0.0,         # NEW
    regime="", rs_rank=0.0,        # NEW
    trend_bars=0,                  # NEW
) -> Optional[Dict]:
```

All three are keyword-only with safe defaults — existing call sites without them continue to work, getting only Tier 1 checks.

### Call Sites to Update

Three call sites in `engine3.py`: `scan_pullback()`, `scan_relaxed_pullback()`, `scan_pullback_scored()`.

Each call site needs to pass:
```python
nearest_sup = _find_structural_support(
    ll, lc, sr_zones, trendline,
    ind.high, ind.low, ind.close, ind.volume, avg_vol, latr,
    sma200=ind.l200,
    ema20=float(ind.ema20.iloc[-1]),
    ema50=float(ind.sma50.iloc[-1]),   # sma50 = EMA50 proxy (close enough for support detection)
    regime=regime,          # passed into scan functions from caller
    rs_rank=rs_rank,        # passed into scan functions from caller
    trend_bars=_trend_bars, # already computed in each function
)
```

**Note:** `scan_pullback()` and `scan_relaxed_pullback()` currently don't receive `regime` or `rs_rank` as parameters. These need to be added to their signatures and threaded through from `main.py`. `scan_pullback_scored()` already receives `rs_score` — regime needs to be added.

### Support Tier as Score

In `scoring.py`, map `support_source` to quality points:

```python
SUPPORT_TIER_SCORE = {
    "KDE":              5,
    "CONSOLIDATION_LOW": 4,
    "SMA200":           3,
    "EMA50":            2,
    "EMA20":            1,
}
SCORE_WEIGHT_SUPPORT_TIER = 5  # new weight

support_src = setup.get("support_source", "")
tier_pts = SUPPORT_TIER_SCORE.get(support_src, 0)
score += round(tier_pts * SCORE_WEIGHT_SUPPORT_TIER / 5)
```

Higher Tier 1 sources score more than conditional Tier 2/3. A KDE zone is still the best structural support — the tier expansion just unlocks more setups, it doesn't treat them as equal.

---

## 4. Coiling Logic Fix (WATCHLIST)

### What Changes

Remove the fixed 3% band hard gate. Replace with:
1. ATR-normalized consolidation score
2. Hard rejection for "trending straight into resistance"

### Coiling Score

```python
# In scan_near_breakout(), after finding best_upper:
_high5 = float(data["High"].iloc[-5:].max())
_low5  = float(data["Low"].iloc[-5:].min())
_range5 = _high5 - _low5
_range_ratio = _range5 / _latr_nb if _latr_nb > 0 else 99.0

# Rejection gate: trending momentum into resistance
_highs = data["High"].iloc[-4:].values
_trending_up = all(_highs[i] < _highs[i+1] for i in range(len(_highs)-1))
if _trending_up and _range_ratio > 3.5:
    return None   # consecutive higher highs + wide range = not consolidating

# Coiling score (0–10)
if _range_ratio <= 1.5:
    _coiling_score = 10
elif _range_ratio <= 2.5:
    _coiling_score = 6
elif _range_ratio <= 3.5:
    _coiling_score = 2
else:
    _coiling_score = 0

# Include in return dict:
"coiling_score": _coiling_score,
"range_ratio":   round(_range_ratio, 2),
```

### Why This Is Better Than The Fixed 3% Band

- A volatile stock (ATR/price = 4%) forming a genuine 2-bar tight base gets range_ratio ≈ 1.2 → score 10. Old system rejected it because 3% = 0.75 ATR and it might not have 3 bars there.
- A low-volatility stock (ATR/price = 1%) that drifted up to resistance over 3 days gets range_ratio ≈ 3.8 → score 0. Old system might have passed it (3 bars within 3% = 3 ATR, very easy).
- ATR-normalization is the correct unit for this measurement.

### Rejection Rule Explained

`_trending_up AND _range_ratio > 3.5` catches:
- 4 consecutive higher highs (stock is in active momentum)
- AND the 5-bar range is more than 3.5× ATR (wide directional bars)

This specifically rejects VSAT, BTSG, HP style setups (smooth uptrend arriving at resistance) without needing a coiling bar count.

### In `scoring.py`

```python
SCORE_WEIGHT_COILING = 5  # new weight

if setup.get("setup_type") == "WATCHLIST":
    coiling_pts = setup.get("coiling_score", 0)
    score += round(coiling_pts * SCORE_WEIGHT_COILING / 10)
```

---

## 5. Updated Scoring Formula

### New Weights (sum = 100)

| Component | Old Weight | New Weight | Notes |
|---|---|---|---|
| RS Rank | 30 | 25 | Slightly reduced — new components take some weight |
| R:R Ratio | 20 | 18 | Slight reduction |
| Volume / Momentum | 20 | 17 | Slight reduction |
| Regime Alignment | 15 | 15 | Unchanged — independent signal |
| Trend Duration | — | 10 | New — replaces 20-bar hard gate |
| Sector Strength | 10 | 5 | Reduced — correlated with RS rank |
| Support Tier | — | 5 | New — quality gradient on structural support |
| Coiling Quality | — | 5 | New — replaces WATCHLIST hard gate |
| **Total** | **95\*** | **100** | |

*Old weights summed to 95 because Sector (10) + Quality (5) was partially overlapping; new structure is cleaner.

### Constants to Add to `constants.py`

```python
# Updated score weights
SCORE_WEIGHT_RS_RANK       = 25   # was 30
SCORE_WEIGHT_RR            = 18   # was 20
SCORE_WEIGHT_VOL           = 17   # was 20
SCORE_WEIGHT_REGIME        = 15   # unchanged
SCORE_WEIGHT_TREND_DUR     = 10   # new
SCORE_WEIGHT_SECTOR        = 5    # was 10
SCORE_WEIGHT_SUPPORT_TIER  = 5    # new
SCORE_WEIGHT_COILING       = 5    # new
```

---

## 6. Final Hard Filter List

These are the only things that should cause hard rejection (return None / skip ticker):

| Filter | Value | File |
|---|---|---|
| Liquidity: 50d median volume | ≥ 750K | `filters.py` |
| Liquidity: dollar volume | ≥ $25M | `filters.py` |
| Earnings blackout | [-1, +7] days | `filters.py` |
| Regime = DEFENSIVE | Skip Engines 2/3 entirely | `main.py` |
| Minimum bars of data | 200+ for SMA200 history | `filters.py` |
| RS rank hard floor | ≥ 65 | `main.py` + `portfolio_backtest.py` |
| Minimum trend duration (pullback) | ≥ 10 consecutive bars | `engine3.py` |
| Structural support present | At least one tier (1, 2, or 3) | `engine3.py` |
| WATCHLIST momentum gate | No 4 consecutive higher highs + range > 3.5×ATR | `engine2.py` |

Everything else is score.

---

## 7. Two Operating Modes

### How to Switch

Check `regime` label in `score_and_filter_setups()`. If AGGRESSIVE → Opportunistic params. If SELECTIVE → Strict params. DEFENSIVE already skips Engines 2/3 entirely.

No new user-facing toggle needed — the mode is derived from the regime automatically.

### Strict Mode (SELECTIVE Regime)

| Parameter | Value |
|---|---|
| RS rank floor | 68 |
| Min score | 75 |
| Trend duration floor | 12 bars |
| Support types allowed | Tier 1 only (KDE, pivot, SMA200) |
| WATCHLIST coiling gate | range_ratio ≤ 3.5 AND coiling_score ≥ 2 |
| Expected signals/week | 8–15 |

Rationale: In SELECTIVE, the market environment is uncertain. Tighter filters compensate for reduced regime tailwind. EMA bounces are less reliable when the market is not in full bull mode — require real structural support.

### Opportunistic Mode (AGGRESSIVE Regime)

| Parameter | Value |
|---|---|
| RS rank floor | 65 |
| Min score | 68 |
| Trend duration floor | 10 bars |
| Support types allowed | Tier 1 + Tier 2 (EMA50, RS ≥ 85) + Tier 3 (EMA20, RS ≥ 90, trend ≥ 15) |
| WATCHLIST coiling gate | Momentum rejection only (range_ratio > 3.5 + consecutive higher highs) |
| Expected signals/week | 20–35, top 15 selected by score |

Rationale: In AGGRESSIVE, the market is confirming the trend. EMA bounces are reliable. First pullbacks (10–19 bars) are valid entries. The wider funnel is intentional — let the score do the selection.

### Implementation in `score_and_filter_setups()`

```python
def score_and_filter_setups(setups, rs_rank_map, regime, top_sectors, min_score=None):
    if regime == "AGGRESSIVE":
        _min_score = min_score if min_score is not None else 68
        _rs_floor  = 65
    else:  # SELECTIVE (DEFENSIVE already gated upstream)
        _min_score = min_score if min_score is not None else 75
        _rs_floor  = 68
    # ... apply _rs_floor check and _min_score filter
```

---

## 8. Validation Plan

### Baseline Run (Before Changes)

Run the portfolio backtest on the current system (post-parity build):
```
Tickers: full universe
Period: 2022-01-01 → 2024-12-31  (includes SELECTIVE and AGGRESSIVE periods)
Record: win rate, avg R, expectancy, trade count, profit factor, per-setup breakdown
```

### Comparison Run (After Changes)

Run identical config on new system. Compare:

| Metric | Why It Matters |
|---|---|
| Trade count | If <10% increase, something else is blocking the new setups |
| Win rate | Should drop slightly (more early-stage setups) or stay flat |
| Average R | Should increase slightly (first pullbacks are higher-R) |
| Expectancy | Net of above two — this is the primary metric |
| Profit factor | Gross profit / gross loss — regime-agnostic quality measure |

### Isolation Tests (Most Important)

**Test 1 — Trend duration unlocked setups**

Tag all trades in the new backtest where `trend_bars` was 10–19 at signal time. Pull this subset and compute:
- Win rate vs the ≥20-bar subset
- Avg R vs the ≥20-bar subset
- What regime were they in?

If 10–19 bar trades in AGGRESSIVE have similar win rate to 20+ bar trades → the gate was costing alpha with no benefit.

**Test 2 — EMA-based support trades**

Tag all trades where `support_source` was "EMA50" or "EMA20". Pull this subset:
- Win rate
- Avg R
- Were they in AGGRESSIVE regime? (They should only fire there)

If win rate < 40% or avg R < 0.5 → Tier 2/3 conditions are too loose and need tightening.

**Test 3 — WATCHLIST coiling vs old gate**

Compare WATCHLIST trades that would have passed the old 3/10 gate vs the new ATR-normalized system:
- How many new signals does the ATR approach generate that the old approach missed?
- Do those new signals win at a comparable rate?

### Accept/Reject Criteria

| Result | Conclusion |
|---|---|
| Expectancy ≥ baseline AND trade count up ≥ 5% | Full rollout |
| Expectancy ≥ baseline AND trade count flat | Rollout — the system is equivalent with cleaner logic |
| Expectancy < baseline by < 0.1R | Review isolation tests — likely one specific change is the problem |
| Expectancy < baseline by > 0.1R | Revert the specific change that caused it, keep the others |

The validation is designed so each change can be isolated and reverted independently. Roll them out in the priority order listed — test after each one.

---

## 9. File Change Summary

| File | Changes |
|---|---|
| `constants.py` | `PB_MIN_TREND_BARS=10`, `RS_RANK_MIN_PERCENTILE=65`, updated score weights, new WL constants |
| `engine3.py` | `_find_structural_support()` adds Tier 2/3; function signature gets `ema20`, `ema50`, `regime`, `rs_rank`, `trend_bars`; signal dicts include `trend_bars`; scan function signatures get `regime`, `rs_rank` params |
| `engine2.py` | `scan_near_breakout()` replaces fixed coiling gate with ATR-normalized score + momentum rejection rule; signal dict includes `coiling_score`, `range_ratio` |
| `scoring.py` | Updated weights; new `_score_trend_duration()`, `_score_support_tier()`, `_score_coiling()` helpers; `score_and_filter_setups()` gets mode-switching logic |
| `main.py` | Pass `regime` and `rs_rank` into `scan_pullback()` and `scan_relaxed_pullback()` call sites |
| `portfolio_backtest.py` | Update RS rank floor to 65; pass regime label into pullback scan calls |
