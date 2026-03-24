# Implementation Plan — Refinements
*Date: 2026-03-23 | Amends: implementation-plan-2026-03-22.md*

---

## 1. Trend Duration Scoring — Higher Resolution

Replace the 3-bucket function with 4 buckets:

```
trend_bars < 10   → reject (hard gate, unchanged)
10 ≤ bars < 15    → +2 pts
15 ≤ bars < 20    → +5 pts
20 ≤ bars < 30    → +7 pts
30+ bars          → +10 pts
```

The 20–29 bucket now gets its own tier (7 pts) instead of being merged with 25+. This matters because the original plan treated a 25-bar trend identically to a 60-bar trend. A stock with 30+ bars of clean trend above all MAs is in a materially different position than one at 20 bars — the longer streak signals sustained institutional accumulation, not just a recent turn.

**Code — `scoring.py`:**
```python
tb = setup.get("trend_bars", 0)
if tb >= 30:
    trend_pts = 10
elif tb >= 20:
    trend_pts = 7
elif tb >= 15:
    trend_pts = 5
elif tb >= 10:
    trend_pts = 2
else:
    trend_pts = 0
```

---

## 2. RS Floor by Mode

```
AGGRESSIVE regime  →  RS hard floor: 65
SELECTIVE regime   →  RS hard floor: 70
```

**Why 70 in SELECTIVE:**

In SELECTIVE, the regime score component applies a 0.53 multiplier — a stock earns roughly half the regime points it would in AGGRESSIVE. That 7-point deficit needs to be compensated somewhere. A stock at RS rank 67 in SELECTIVE starts 7 regime-pts behind and has below-average RS — it's unlikely to reach `min_score=75` without something exceptional compensating. The 70 floor in SELECTIVE just makes explicit what the score filter would implicitly reject anyway. It also keeps the signal queue short in uncertain markets, where selectivity has higher value.

At RS 65–69 in SELECTIVE, the expected outcome is weak: below-average relative strength, partial regime credit, uncertain market. Filtering these explicitly is correct, not conservative.

**Effect on trade distribution:**
- AGGRESSIVE: +8–12% signals vs current 70 floor (as estimated in plan)
- SELECTIVE: identical to current system — no change in signal count
- No regression risk in SELECTIVE; upside only in AGGRESSIVE

**`constants.py`:**
```python
RS_RANK_MIN_PERCENTILE_AGGRESSIVE = 65
RS_RANK_MIN_PERCENTILE_SELECTIVE  = 70
```

**`score_and_filter_setups()` and `portfolio_backtest.py`:**
Select the floor based on regime before the RS gate check:
```python
_rs_floor = RS_RANK_MIN_PERCENTILE_AGGRESSIVE if regime == "AGGRESSIVE" else RS_RANK_MIN_PERCENTILE_SELECTIVE
```

---

## 3. Support Tier Scoring Rebalance

Revised tier scores:

```python
SUPPORT_TIER_SCORE = {
    "KDE":               5,
    "CONSOLIDATION_LOW": 4,
    "SMA200":            3,
    "EMA50":             3,   # was 2
    "EMA20":             2,   # was 1
}
```

**Reasoning:**

EMA50 is gated behind `AGGRESSIVE + RS ≥ 85`. Once those conditions are met, EMA50 in an established trend is functionally equivalent to SMA200 as a support level — both are medium-term dynamic supports that institutions watch. The original scoring (EMA50=2, SMA200=3) implied EMA50 support is low-quality, but that conflicts with the tier conditions: you've already required the strongest market environment and top-quintile RS to even reach the EMA50 check. The support quality score should reflect post-condition quality, not pre-condition access difficulty.

EMA20 moves from 1 → 2. It requires `AGGRESSIVE + RS ≥ 90 + trend ≥ 15` — the most restrictive conditions in the system. A score of 1 was underselling what those conditions imply. Still lower than EMA50 (shorter-term average, inherently noisier) but not negligible.

KDE stays at 5. A horizontal density zone with multiple historical touches is still the strongest form of structural support — it has the most evidence behind it.

---

## 4. Coiling Weight

**Increase from 5 → 7.**

**Reasoning:**

Coiling is the only component that directly measures whether the stock is building energy for a breakout vs simply arriving at resistance by momentum. A 5-point weight means the gap between tight consolidation (coiling_score=10 → 5 pts) and no consolidation (0 pts) is only 5 points on a 100-point scale. With `min_score=68` in Opportunistic mode, that 5-point gap is meaningful but not decisive — a poorly-consolidating WATCHLIST setup can still score 68+ if RS and regime are strong.

At weight=7, the gap becomes 7 points. In Opportunistic mode with `min_score=68`, a WATCHLIST setup with zero coiling needs RS rank ≈ 85+ and strong volume just to compensate. That is the correct behavior — the only reason to accept a non-consolidating near-resistance setup is if everything else is exceptional.

The concern about over-weighting is valid for components that apply to all setups. Coiling only applies to WATCHLIST type. It is not competing with regime alignment (15pts) on a universal basis — it's 7 points that only activates for one specific setup type, making it a sharp discriminator exactly where it's needed.

**Updated weights (rebalanced to stay at 100):**

| Component | Weight |
|---|---|
| RS Rank | 25 |
| R:R Ratio | 17 |
| Volume / Momentum | 16 |
| Regime Alignment | 15 |
| Trend Duration | 10 |
| Coiling Quality | 7 |
| Sector Strength | 5 |
| Support Tier | 5 |
| **Total** | **100** |

R:R and Volume each give 1pt to fund the coiling increase. Neither change is meaningful at 1pt scale.

---

## 5. Extension From Support Constraint

**Measure:** Distance from current close to detected support level, in ATR units.

```
extension_atr = (lc - support_level) / latr
```

Where `support_level` is the `level` key in the support dict returned by `_find_structural_support()`.

**Hard gate:** `extension_atr > 2.5` → reject. At 2.5 ATR above support, the initial stop is so far back that R:R math fails for any reasonable target. This is setup-agnostic — a pullback that has already recovered 2.5 ATR from its support is no longer near support.

**Scoring penalty (within 0–2.5 ATR):**

```
0.0 – 0.75 ATR:  0 pts penalty   (sitting at or near support — optimal)
0.75 – 1.5 ATR: −2 pts           (slight extension, still clean)
1.5 – 2.5 ATR:  −4 pts           (extended, valid but sub-optimal)
> 2.5 ATR:       reject           (hard gate)
```

**Where to apply:** `_find_structural_support()` returns the support dict. Immediately after the function call in each scan function, compute extension and apply the gate:

```python
if nearest_sup is not None and latr > 0:
    _ext_atr = (lc - nearest_sup["level"]) / latr
    if _ext_atr > 2.5:
        return None   # too far from support to trade cleanly
    nearest_sup["extension_atr"] = round(_ext_atr, 2)
```

**In `scoring.py`**, apply the penalty:

```python
ext = setup.get("extension_atr", 0.0)
if ext > 1.5:
    score -= 4
elif ext > 0.75:
    score -= 2
```

**Why not a fixed percentage threshold:**
A 2% extension from support means very different things for a $20 stock (ATR ≈ $0.40 → 5 ATR above support) vs a $200 stock (ATR ≈ $8 → 0.5 ATR above support). ATR-normalization is the only correct unit here.

**Why 2.5 ATR as the hard gate:**
The standard ATR stop multiplier in this system is 0.8× ATR below support. If you're 2.5 ATR above support and placing a stop 0.8 ATR below the support level, your total risk is 3.3 ATR. At a 2:1 R:R target, you'd need a 6.6 ATR move to close the trade profitably. That's a meaningful move that almost never comes from a pullback entry — it's a breakout entry at that point. The math breaks down at 2.5 ATR.

**New constant:**
```python
SUPPORT_MAX_EXTENSION_ATR = 2.5   # hard reject if close > support_level + 2.5 × ATR
```
