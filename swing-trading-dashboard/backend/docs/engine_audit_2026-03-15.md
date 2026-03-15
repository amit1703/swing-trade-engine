# Engine Audit — 2026-03-15

Full audit of how each engine finds its setups: where KDE zones, pivot levels, and price geometry are used, and what each engine depends on to fire.

---

## Foundation: Engine 1 — How KDE Zones Are Built

Every engine relies on zones from E1. Understanding them is a prerequisite for auditing everything else.

**Process:**
1. Daily OHLCV → resampled to **weekly**
2. Collects: weekly closes + weekly pivot highs (`argrelextrema`, order = len/20) + weekly pivot lows
3. Runs **recency-weighted Gaussian KDE** on that price-point cloud — points ≤90 days old get 2× weight, ≥365 days get 1×
4. Finds density peaks → each peak becomes a zone of **level ± 0.2×ATR14**
5. Merges peaks within 1 ATR of each other
6. Separately builds **pivot resistance zones** from daily High prices:
   - `argrelextrema(highs, order=15)` — must be the max in a 30-bar window (~6 weeks), very filtered
   - Clusters similar pivots via Union-Find (within `PIVOT_TOUCH_MARGIN_PCT`, at least `PIVOT_MIN_SEPARATION_DAYS` apart, requires `PIVOT_MIN_TOUCHES`)
   - Returns at most 2 zones above current price with **±0.1×ATR** width (narrower than KDE bands)
7. Combines both lists, classifies each zone as SUPPORT (below price) or RESISTANCE (above price)

**Key implication:** KDE zones are statistically derived from where institutional volume clustered historically. They don't correspond to specific candle highs — they're probability density peaks. A "KDE resistance zone" at $150 means a lot of price action occurred near that level, not that a specific candle had a high of exactly $150.

---

## Engine 2 — VCP

**VCP is 100% KDE-zone dependent. No zones = no signal.**

### Path A — DRY (Coiled Spring)
1. EMA8 > EMA20 AND close > SMA50
2. MTR of last 5 bars < MTR of prior 20 bars (range shrinking)
3. scipy `curve_fit` parabola over last 15 bars must have `a > 0` — U-shape accumulation, V-shapes rejected
4. Volume dry-up: 3-day avg < 50-day avg
5. **Location gate (KDE-required):** price must be within 5% below a KDE resistance zone upper boundary. If no zone is found nearby, the signal does not fire.

### Path B — BRK (Confirmed Breakout through KDE)
1. EMA8 > EMA20 AND close > SMA50
2. Close strictly above a KDE zone's upper boundary, within 0.5%–3% of that upper
3. Volume ≥ 150% of 50-day avg
4. RS filter: 3-month stock return > SPY 3-month − 5%

**Stop:** `min(candle Low, zone_lower) − 0.8×ATR14`
**Take-profit:** nearest KDE RESISTANCE zone above entry (fallback: entry + 2.785×risk)

**Conclusion:** VCP is conceptually the cleanest but the most brittle. It only triggers when (a) a KDE zone exists at the right price level AND (b) price has been coiling below it. On strongly trending tickers where price gapped through all historical resistance, or on new listings without sufficient history, VCP is silent. There is no fallback resistance source.

---

## Engine 3 — Pullback

**Pullback does NOT require a KDE zone for detection.** KDE is one of 4 possible structural support layers, checked in priority order.

### Strict Pullback (`scan_pullback`)
1. RS gate: `rs_score ≥ −0.012` (reject persistent underperformers)
2. Trend: EMA8 > EMA20 AND close > SMA50
3. Value zone: candle Low penetrates EMA8 or EMA20
4. **Structural support — cascading search (first match wins):**
   - **Layer 1 — KDE:** low or close touches a KDE SUPPORT zone (within 2.5% tolerance)
   - **Layer 2 — Consolidation low:** 3-bar pivot low in last 60 bars where price bounced (3 of next 5 bars closed above it), within 3% of today's low
   - **Layer 3 — Demand zone:** a bar in the last 30 with ≥150% avg volume, bullish, price held above since, within 3% of today's low
   - **Layer 4 — Ascending TDL:** low touches a validated ascending trendline within 0.8%
5. Pin bar: close ≥ EMA20 (closed back above the value zone)
6. CCI hook: CCI yesterday < −50 AND today > yesterday

### Relaxed Pullback (`scan_relaxed_pullback`)
- Same 4 structural support layers
- Trend relaxed: close > SMA50×0.97 (allows SMA50 test setups)
- Value zone: low penetrates EMA8/20 OR close within 0.75 ATR of either EMA
- CCI floor: −20 instead of −50 (earlier signal)
- No pin-bar hard gate (volume computed for scoring only, no rejection)

**Stop:** `min(candle Low, zone_lower) − 0.8×ATR14`
**Take-profit:** nearest KDE RESISTANCE zone above entry

**Conclusion:** Pullback is the most robust structurally — it fires without KDE support if price bounced off a consolidation low or demand zone. But it is still anchored to the EMA8/20 value zone, not an arbitrary price level. KDE is the preferred support source but not the required one.

---

## Engine 5 — Base Patterns (Flat Base + Cup & Handle)

**Base has zero KDE dependence for detection.** Everything is pure price geometry.

### Flat Base (ATR-Adjusted Darvas Box)
1. Stage 2 required: SMA50 > SMA200 AND close > SMA50 (prior uptrend mandatory)
2. Scans 40→20 day windows (widest passing window wins):
   - Box height (ceiling − floor) ≤ 3.5×ATR14
   - Ceiling touched ≥ 2× (high within 0.5×ATR of ceiling)
   - Close in upper 25% of box (coiled near breakout)
3. Volume dry-up: 5-day avg < 50-day avg (hard gate)
4. Signal:
   - **BRK:** close > ceiling AND volume ≥ threshold AND range contracting
   - **DRY:** close within 1% of ceiling (still in base, approaching breakout)

### Cup & Handle
1. close > SMA200 only (looser than Darvas — no SMA50 > SMA200 requirement)
2. Identifies structure over last 120 bars:
   - Left peak: highest close in first 2/3 of window
   - Cup bottom: lowest close after left peak
   - Right rim: highest close after bottom
3. ATR-proportional depth gate: `15% ≤ depth ≤ (ATR% × 10)` — volatile stocks allowed deeper cups
4. Duration: peak to bottom ≥ 25 bars (no V-shapes)
5. Recovery: right rim must recover ≥ 50% of cup depth
6. Handle: ≥ 5 bars; handle ATR < decline-phase ATR (volatility must contract in handle)
7. Price: current close in upper 50% of cup depth
8. Signal: same BRK/DRY logic as Darvas

**Stop:** `floor − 0.2×ATR14` — extremely tight, only 0.2 ATR below the base floor
**Take-profit:** nearest KDE RESISTANCE zone above entry

**Conclusion:** BASE is entirely self-contained and immune to KDE failures. The tradeoff is that the 0.2×ATR stop is mechanically very small — on a $200 stock with $4 ATR, the stop is only $0.80 below the base floor. Any noise spike through the floor triggers it before real thesis invalidation.

---

## Engine 6 — BRK (Resistance Breakout)

**BRK uses THREE resistance sources. KDE is the lowest priority.**

### Resistance Candidate Collection (per breakout bar)
1. **Donchian high** (primary) — rolling max of prior ~63 bars. Always produces a level. This is the backbone — eliminates the "no zones found" failure of KDE-only approaches.
2. **Pivot highs** (secondary) — structural turning points: `high[i] ≥ max(high[i±s])` for s=1..strength. Applied to all confirmed bars. All pivot levels above pre-close are candidates.
3. **KDE zones** (supplement) — both RESISTANCE zones and SUPPORT zones above price (flipped support can still act as resistance)

All candidates are deduplicated (within 0.5%), sorted ascending. The **nearest** resistance above the previous bar's close is tested first.

### Breakout Requirements
- `pre_close ≤ resistance < brk_close` (must actually cross the level)
- `brk_close ≥ resistance × (1 + brk_min_pct)` — close decisively confirms the break
- `(brk_close − resistance) / resistance ≤ 4.2%` — gap gate, not already overextended
- `brk_vol ≥ vol_mult × 50-day avg` — volume expansion required
- Consolidation: at least `min_consol` bars in the prior window must have closed ≥ 92% of resistance (was building up to it)
- Overextension: if signal is aged (days_back > 0), current close ≤ resistance × 1.05

**Entry:** `brk_high × 1.001`
**Stop:** `resistance − 2.264×ATR14` — anchored to the resistance level, not the candle low
**Take-profit:** nearest KDE RESISTANCE zone above entry

**Conclusion:** BRK is the most engineered and most prolific (702 backtest trades). The Donchian-first approach means it fires even when KDE produces nothing — explaining why it far outnumbers VCP. Pivot and KDE are supplements that improve quality when available.

---

## Comparison Table

| | VCP | Pullback | Base | BRK |
|---|---|---|---|---|
| **Requires KDE zone to fire** | **Yes — fully** | No (4-layer fallback) | No | No (Donchian first) |
| **Uses pivot levels** | No | No | No | Yes (2nd priority) |
| **KDE zone role** | Entry anchor (coiling below resistance) | Support confirmation (1st layer) | Take-profit only | 3rd priority resistance source |
| **Stop basis** | candle low + zone lower | candle low + zone lower | base floor | resistance level |
| **Stop ATR factor** | 0.8× | 0.8× | 0.2× | 2.264× |
| **Value zone** | KDE resistance (coiling below) | EMA8/20 (pullback to MAs) | Darvas box / C&H geometry | None (Donchian/pivot breakout) |
| **Backtest trades** | — | 111 | 37 | 702 |

---

## Issues and Findings

### 1. VCP Brittle on Poor KDE Coverage
If a ticker has no KDE resistance zone within 5% above price (strongly trending, split-adjusted, new listing, or price gapped through all historical levels), VCP is silent. BRK handles this via Donchian. VCP has no equivalent fallback.

### 2. Engine 2 PATH B and Engine 6 Overlap
Both detect breakouts through resistance zones but use different resistance sources (KDE-only vs. Donchian/pivot/KDE) and different consolidation rules. On the same ticker/day they could produce different entries. De-duplication in `main.py` prevents both from appearing in the scanner, but the signal logic structurally overlaps. Worth knowing which one "wins" — currently whichever fires first in the processing order.

### 3. BASE Stop Too Tight by Design
`floor − 0.2×ATR` is mechanically very small. On a $200 stock with $4 ATR, stop is $0.80 below the base floor. Any noise spike through the floor triggers the stop before any real thesis invalidation. This likely explains the low backtest trade count (37 trades) — many setups get stopped out before the base fully resolves.

### 4. Pullback Consolidation Low Detector Fragile at Range Extremes
The 3% proximity check (`abs(ll - candidate) / candidate > 0.03`) rejects consolidation lows that are further away. On high-ATR stocks a 3% swing is easily 1 ATR, so valid support levels 3.5% below are ignored. In that case the pullback must fall back to KDE or demand zone — if neither is found, the setup is rejected even though the stock is touching a valid structural level.

### 5. KDE Zone Width Asymmetry (±0.2 ATR vs ±0.1 ATR for Pivots)
KDE zones: ±0.2 ATR half-width. Pivot resistance zones: ±0.1 ATR (half as wide). Engine 6 uses the `resistance` level itself (not zone bounds) for detection, so width doesn't affect detection. But `zone_utils.nearest_resistance_target()` uses `zone["lower"]` for take-profit targeting — a narrower pivot zone means a lower (more conservative) take-profit when pivot-source zones are used.

### 6. Take-Profit is Universally KDE-Dependent
All four engines call `nearest_resistance_target()`, which finds the nearest KDE RESISTANCE zone above entry. If no zone is found, or the nearest yields R:R < 1.0, it falls back to `entry + TARGET_RR × risk` where `TARGET_RR = 2.785` (Optuna-tuned). Pivot resistance zones from E1 are included in the zone list and do qualify — but only 2 are ever returned (nearest overhead), so they may not always cover the relevant target range.

### 7. Structural Asymmetry: Detection vs. Targeting
Detection uses geometry and price structure (KDE, Donchian, EMAs, pivot lows). Targeting universally uses KDE RESISTANCE. This means a stock can produce a valid pullback signal using only a demand zone for support — but the target is still set by KDE resistance. If the KDE resistance is very far above (or falls back to 2.785× risk), the R:R on the scanner may look unrealistic for actual trading.
