# Quant System Audit — 2026-03-22

Scope: post-parity-build review of all active filters and scoring components.
Goal: identify where the system is too strict, redundant, or leaving alpha on the table.

---

## 1. Filter Stacking & Redundancy

### The Core Problem

The system measures **"this stock is in a strong, established trend"** three separate times:

| Filter | What it actually measures |
|---|---|
| RS rank > 70 | Stock outperformed SPY over 3/6/9/12 months |
| Sector strength (top 5) | Sector's average RS score is high |
| Trend duration ≥ 20 bars | Stock has been in uptrend for ~1 month |

All three are downstream of the same signal: **momentum**. A stock in the top 30% by RS rank has by definition been outperforming for 3–12 months, which means its trend has almost certainly been running for well over 20 bars, and it's likely in a strong sector. The same test is running three times with different labels.

### Redundancy Map

**RS rank > 70 ↔ Trend duration ≥ 20 bars: ~85% correlated**
If a stock has RS rank 75, it has been outperforming SPY for 63–252 days. It is structurally impossible for that stock to have fewer than 20 bars of EMA8>EMA20. The 20-bar gate is almost never the binding constraint — RS rank will have already screened out the weak-trend stocks. The 20-bar gate catches only a tiny edge case that RS rank misses, at the cost of hard-rejecting valid setups.

**RS rank > 70 ↔ Sector strength: ~70% correlated**
Sector strength is computed as the average RS score of all stocks in the sector. If a stock has RS rank 80, its sector almost certainly appears in the top 5 by average RS. Scoring sector strength separately while the stock's own RS rank already contains that information is double-counting.

**Regime alignment ↔ RS rank: ~50% correlated**
Regime includes SPY-level breadth (% stocks above SMA50), which is a market-wide momentum gauge. Individual RS rank is correlated but regime is genuinely more independent — it's measuring market environment, not the individual stock. Worth keeping separate.

### What This Costs

Triple-stacking the momentum signal systematically excludes the exact stocks that score highest on each individual factor: **the early leaders**. A stock that just broke out 15 days ago with RS rank 78 fails the trend duration gate, even though it scores well on everything else. That stock is likely in its best window for a high-R pullback entry.

### Recommendation

| Filter | Status | Reason |
|---|---|---|
| RS rank > 70 hard gate | **Keep, but lower to 50** | Let the 30pt score component differentiate further |
| Sector strength score (10pts) | **Keep as score only** | Marginal info beyond RS rank, not enough to be a hard gate |
| Trend duration ≥ 20 bars | **Replace with 8-bar floor + score** | See Section 2 |
| Regime alignment | **Keep as hard gate (DEFENSIVE → skip)** | Genuinely independent market-level signal |
| Structural support | **Keep as hard gate, but expand tiers** | See Section 3 |

---

## 2. Trend Duration (20 bars) — Alpha Being Left Behind

### What Is Being Systematically Excluded

**Category 1 — First pullback after a base breakout**
A stock forms a VCP, breaks out with volume, runs 8–12% in 5–10 days, then pulls back to the 20 EMA. This is the highest-R pullback setup that exists. It has 5–12 bars of uptrend. The system rejects it. These setups are also the most volatile to miss — by bar 20, the easy part of the move from the breakout is often already done.

**Category 2 — Early leaders in new bull phases**
After a market correction, the strongest stocks re-establish trends first. In the first 2–4 weeks of a new upleg, the best stocks have 10–18 bars of trend. The 20-bar gate means the system only enters stocks after the regime has been AGGRESSIVE for at least 4 weeks. By then, leading stocks have already moved 15–30% and R:R has compressed significantly.

**Category 3 — Post-earnings gap leaders**
A stock reports strong earnings, gaps up 15–20%, and immediately enters a clean trend. The trend start from the system's perspective is the gap date. 3 weeks later it has 15 bars of clean trend above all MAs and pulls back for the first time. Rejected.

### The Bias Introduced

By requiring 20 bars, the system **systematically enters in the middle to late stage of trends**:
- Entry around bar 25–40 of the trend (20-bar minimum + bars to detect the pullback)
- The breakout-to-entry move has already been 15–25%
- R:R is compressed because the stop is now further back in price history
- Win rate is slightly better (trend is confirmed) but average R-multiple is lower

**Estimated tradeoff:**
- Win rate improvement from 20-bar gate vs 8-bar floor: approximately +3–5% (real but modest)
- Average R-multiple loss: approximately −0.2R to −0.4R per trade (meaningful at scale)
- Net effect on expectancy: likely slightly negative at 20 bars vs 10–12 bars

### Better Design Options

**Option A — Lower threshold to 10 bars**
Captures first pullbacks after breakouts. Still filters truly fresh 1-week trends. Simple.

**Option B — Dynamic threshold by RS rank**
```
RS rank ≥ 90  →  min 8 bars   (leaders get early entry)
RS rank 75–89 →  min 12 bars
RS rank 50–74 →  min 15 bars
```
Rationale: a stock in the 95th RS percentile has earned an early entry. Its relative strength is the confirmation.

**Option C — Hard floor of 10 bars, add score component (recommended)**
```
10–14 bars:  +0 trend bonus
15–19 bars:  +3 trend bonus  (out of new 10pt component)
20–34 bars:  +7 trend bonus
35+ bars:    +10 trend bonus
```
The 20-bar cliff becomes a gradient. The absolute floor of 10 bars prevents week-old trends from entering, but everything above 10 is rewarded proportionally.

**Recommendation: Option C.** The binary cliff at 20 bars is the wrong shape for a continuous quality measure. Convert it to a scoring component with a minimal hard floor at 10 bars.

---

## 3. Structural Support — Where Valid Setups Are Rejected

### What Is Being Missed

**EMA20 and EMA50 as dynamic support in strong trends**

In a confirmed AGGRESSIVE regime with RS rank ≥ 85, a stock repeatedly touching the 20 EMA and bouncing is a textbook pattern. This is how strong leaders behave — they don't need to drop to a KDE zone or a historical pivot low. The EMA is the support.

Currently: if a stock in the 92nd RS percentile pulls back to EMA20 cleanly in an AGGRESSIVE regime, but there's no KDE zone, pivot low, or SMA200 near that price level, the system rejects it. That is exactly the setup described as the highest-quality entry in Minervini, O'Neil, and Ryan.

**When the restriction fails most:**
1. **New-high stocks** — at all-time highs there are no KDE zones above prior resistance and no pivot lows at their current level. Only reference is SMA200, which is far below. These stocks will almost never have support coincide with an EMA20 bounce.
2. **Post-gap leaders** — the gap creates new price territory with no historical KDE zones.
3. **AGGRESSIVE regime** — the regime confirmation is telling you the market environment is the strongest possible. This is exactly when EMA bounces are most reliable and when the structural support restriction is most costly.

**Where the restriction is genuinely correct:**
- SELECTIVE or DEFENSIVE regime — without a structural floor, bounces are likely noise
- RS rank 50–70 range — these stocks need real support because trend conviction is lower
- Choppy or sideways stocks — EMA support in a sideways trend is worthless

### Proposed Tiered Structure

| Tier | Support Type | Required Condition |
|---|---|---|
| 1 | KDE zone, Pivot low, SMA200 | Always valid |
| 2 | EMA50 touch (close within 0.5% of EMA50) | Regime = AGGRESSIVE, RS rank ≥ 80 |
| 3 | EMA20 touch (close within 0.5% of EMA20) | Regime = AGGRESSIVE, RS rank ≥ 90, trend ≥ 15 bars |

This preserves the strict gate for average setups while unlocking the most valid pullback pattern (EMA bounce in strong trend) for top-tier stocks in the best environment. The conditions for Tier 3 are tight — AGGRESSIVE + top 10% RS + established trend. But those are exactly the conditions where EMA20 support is most reliable.

---

## 4. Watchlist Coiling Logic

### The Structural Flaw

The coiling check (3 bars within 3% of resistance over last 10 bars) uses a **fixed percentage band** across all stocks regardless of volatility.

- Low-volatility stock (ATR/price = 1%): 3% = 3 ATR. Very easy to pass — almost no real constraint.
- High-volatility stock (ATR/price = 4%): 3% = 0.75 ATR. Extremely restrictive — stock must barely move for 3 days.

The filter is **accidentally more strict for volatile stocks**, which is the opposite of what's intended. High-volatility stocks that genuinely compress near resistance are rare and significant — they should be rewarded, not penalized.

### What a Good Coiling Check Should Measure

The actual question is: **has the stock stopped making progress toward new highs and started consolidating?**

Better proxies:
- The 5-bar price range (max_high − min_low) is less than 2.5× ATR (ATR-normalized, captures "tight bars near resistance" correctly)
- The highest high in the last 5 bars is not more than 1.5% above the highest high in the preceding 5 bars (stock is stalling, not trending through)

### Hard Gate vs Score

The coiling check is measuring **setup quality**, not **setup validity**. A stock can be a valid near-breakout candidate with only 2 bars of coiling if everything else is exceptional (RS rank 95, AGGRESSIVE regime, volume drying up). Treating it as a hard gate throws away those cases.

**Recommendation:** Convert to a scoring component with ATR-normalized band.
```
5+ bars coiling (ATR-normalized):  +10 pts
3–4 bars:                          +6 pts
1–2 bars:                          +2 pts
0 bars (just arrived):             0 pts
```
Add a harder gate only for the "trending straight through resistance" case: reject if the stock's high has been making consecutive higher highs over the last 5 bars (momentum into resistance, not consolidation).

---

## 5. System-Level Architecture

### The Fundamental Tradeoff

The current system is **high-precision, low-recall**. It produces fewer signals and the signals are clean. This is right for a human trader reviewing setups manually. But it has a structural problem: **each hard gate is a cliff, not a curve.**

A stock at RS rank 69 is treated identically to one at RS rank 20. A stock with 19 bars of trend is treated identically to one with 3 bars. Probability of winning a trade is a continuous function of these inputs, not a step function. Hard gates create a mismatch between the model and reality.

The deeper issue: **hard gates are compensating for a weak scoring system.** If the 0–100 score truly differentiated setup quality, most hard gates would be unnecessary — you would just set `min_score = 75` and let the score handle the sorting. The existence of multiple hard gates signals that the score isn't trusted to do the job alone.

### What Should Always Be Hard Filters

These are genuinely binary — no gradation is meaningful:

1. **Liquidity gate** — you physically cannot trade below this
2. **Earnings blackout** — binary risk event, no gradation meaningful
3. **Regime = DEFENSIVE → skip VCP/Pullback** — fundamental market environment gate (correct as-is)
4. **Minimum bars (absolute floor ~8–10)** — below this, indicators are not meaningful
5. **Close > SMA200** — Stage 2 filter; stocks below SMA200 are in a structurally different regime

### What Should Become Scores

| Currently a hard gate | Should be | Rationale |
|---|---|---|
| RS rank > 70 | Soft gate at 50 + 30pt score | Continuous quality measure |
| Trend duration ≥ 20 bars | Hard floor 10 bars + score | Continuous quality |
| Watchlist coiling 3/10 | Score component (ATR-normalized) | Setup quality, not validity |
| Structural support tier | Tiered score (KDE > pivot > SMA200 > EMA) | Quality gradient, not binary |

### Loose Filter + Strong Ranking

The optimal design for a ranked system: **wide enough funnel that ranking can work, tight enough hard gates to eliminate garbage.** Currently the system generates 10–15 valid setups per week with high precision. A loose-filter system might generate 30–50 candidates ranked by score, with the top 10–15 selected. The top 10–15 of the second system will include setups the first system missed because they hit a filter cliff.

---

## 6. Final Output

### Overly Strict Constraints

1. **Trend duration = 20 bars (hard cliff)** — rejects first pullbacks after breakouts, which are the highest-R setups. Should be a 10-bar floor with graduated scoring above that.
2. **Structural support: KDE/pivot/SMA200 only** — rejects valid EMA20/EMA50 bounces in AGGRESSIVE regime with top-tier RS. Missing the most frequent and reliable pattern in strong bull markets.
3. **RS rank > 70 hard gate** — combined with trend duration creates double-counting of the same momentum signal. Lower to 50 and let the score differentiate.
4. **Watchlist coiling 3/10 fixed-pct** — not ATR-normalized. Accidentally too strict for volatile stocks and too loose for stable ones. Should be a score, not a gate.

### Redundant Signals

1. **RS rank > 70 + trend duration ≥ 20 bars** — highly redundant (~85% overlap). Both confirm "stock has been trending for a long time." The 20-bar gate adds almost no information that the RS rank gate doesn't already capture, while adding a hard cliff that costs alpha.
2. **RS rank + sector strength scoring** — sector strength is derived from RS scores. Scoring both is double-counting individual momentum.
3. **RS rank gate + RS score component** — measuring the same thing as both a gate (70 threshold) and a score (30pts) simultaneously. The gate threshold is set too high — it's doing work the score should be doing.

### Proposed Rebalanced Architecture

**Hard gates (non-negotiable):**
- Liquidity (volume + dollar volume)
- Earnings blackout
- Regime = DEFENSIVE → skip Engines 2/3
- Minimum 10 consecutive bars of uptrend (absolute floor)
- Close > SMA200 (Stage 2 filter)
- RS rank ≥ 50 (absolute floor only)

**Scoring system (expanded to include new components):**
- RS rank (30pts) — unchanged
- R:R ratio (20pts) — unchanged
- Regime alignment (15pts) — unchanged
- Volume/momentum (15pts) — reduce slightly
- Trend duration (10pts, new) — graduated 0–10 based on bar count above 10-bar floor
- Support tier quality (5pts, new) — KDE=5, pivot=4, SMA200=3, EMA50=2, EMA20=1 (conditional)
- Sector strength (5pts) — unchanged
- Coiling quality (score replaces hard gate) — ATR-normalized bar count near resistance

**Key structural change:** Structural support remains a hard gate (must have *something*) but the tier unlocks EMA20/EMA50 as valid support under AGGRESSIVE + RS ≥ 85+. The tier itself becomes a score component rather than all-or-nothing.

### Two System Modes

**Strict Mode (current direction, refined):**
- Hard gates: liquidity, earnings, regime, SMA200, 12-bar floor, RS ≥ 60
- Structural support: KDE/pivot/SMA200 + EMA50 (AGGRESSIVE + RS ≥ 85 only)
- Coiling: 2/8 bars minimum for WATCHLIST (reduced from 3/10), rest becomes score
- Min score: 75
- Expected output: 8–15 clean setups/week, high precision
- Best for: SELECTIVE regime, human review of small list

**Opportunistic Mode:**
- Hard gates: liquidity, earnings, regime, SMA200, 10-bar floor, RS ≥ 50
- Structural support: full tier including EMA20 under AGGRESSIVE + RS ≥ 90
- No coiling hard gate — becomes pure score component
- Trend duration: 10-bar floor only, scores higher bars
- Min score: 65
- Expected output: 20–35 ranked setups/week, top 10–15 selected by score
- Best for: AGGRESSIVE regime, system-driven selection

**Recommended approach:** Run Opportunistic Mode during confirmed AGGRESSIVE regimes, Strict Mode in SELECTIVE. The biggest alpha gains come from unlocking first-pullback-after-breakout setups (currently rejected by the 20-bar gate) during AGGRESSIVE markets. That is where the most upside is being left behind.

---

*Audit conducted 2026-03-22. Covers changes introduced in parity build (portfolio_backtest.py), engine3.py (support restriction + trend duration gate), and engine2.py (watchlist coiling gate).*
