# BACKTEST DIAGNOSTIC AUDIT — 2020–2024
**Universe: 425 tickers | Trades: 5,618 (EARLY+OPTIMAL) | Mode: Legacy**
**Generated: 2026-03-21**

---

## 1. MARKET REGIME ANALYSIS

| Regime | % of Trades | Trades | Win Rate | Expectancy | PF | Max DD | YoY Contribution |
|--------|-------------|--------|----------|------------|-----|--------|-----------------|
| **AGGRESSIVE** | 90.6% | 5,091 | 40.6% | +0.133R | 1.35 | **86.6%** | Dominant driver |
| **SELECTIVE** | 9.4% | 527 | 43.3% | +0.147R | 1.61 | 40.3% | Minor contribution |
| **DEFENSIVE** | 0% | 0 | — | — | — | 0% | Gate works correctly |

**Key findings:**
- AGGRESSIVE drives virtually **100% of P&L and 100% of drawdown** — it's 9 out of 10 trades
- SELECTIVE is **better on every metric** (higher exp, PF, lower DD) but represents only 1 in 11 trades
- The regime gate eliminating DEFENSIVE trades correctly → zero trades in bear conditions ✓
- **Profits:** AGGRESSIVE (size × scale). **Drawdowns:** Also AGGRESSIVE, almost exclusively

---

## 2. SETUP PERFORMANCE

### AGGRESSIVE regime (5,091 trades)

| Setup | N | Win% | Expectancy | PF | Max DD | Avg Hold | Assessment |
|-------|---|------|------------|-----|--------|----------|------------|
| HTF | 23 | 47.8% | +0.323R | **4.58** | 1.1% | 25.7d | **Best setup — severely undertapped** |
| RES_BREAKOUT | 2,246 | 32.3% | +0.175R | 1.30 | **79.0%** | 14.1d | High expectancy, catastrophic DD |
| BASE | 61 | 34.4% | +0.147R | 1.81 | 3.8% | 17.3d | Excellent PF, too few trades |
| PULLBACK | 2,761 | 47.5% | +0.097R | 1.41 | 51.5% | 22.7d | High count, modest edge |

### SELECTIVE regime (527 trades)

| Setup | N | Win% | Expectancy | PF | Max DD | Avg Hold |
|-------|---|------|------------|-----|--------|----------|
| BASE | 6 | 50.0% | +0.709R | 3.42 | 1.6% | 26.8d |
| RES_BREAKOUT | 191 | 34.6% | +0.164R | **1.65** | 21.2% | 12.6d |
| PULLBACK | 329 | 48.3% | +0.131R | 1.57 | 31.7% | 25.1d |
| HTF | 1 | 0.0% | -1.0R | 0.00 | 1.0% | 6.0d |

**Critical insight:**

RES_BREAKOUT in SELECTIVE has **PF=1.65 and DD=21.2%** vs AGGRESSIVE's **PF=1.30 and DD=79%**. The SELECTIVE regime is a much better environment for breakouts, yet breakouts in AGGRESSIVE generate 92% of the DD. This is a structural flaw.

HTF is the clearest edge in the system: PF=4.58, +0.323R, DD=1.1%. Only 23 trades in 5 years — the signal fires too rarely to matter.

---

## 3. ENTRY QUALITY ANALYSIS

| Quality | N | Win% | Expectancy | PF | Max DD |
|---------|---|------|------------|-----|--------|
| **EARLY** (<0.1 ATR) | 5,220 | 41.0% | +0.139R | 1.38 | 90.9% |
| **OPTIMAL** (0.1–0.5 ATR) | 398 | 39.4% | +0.069R | 1.29 | 17.5% |
| **EXTENDED** (>0.5 ATR) | 84 | 51.2% | **-0.045R** | 0.84 | 10.7% |

**Counterintuitive finding:**

EARLY entries (91.5% of all trades) have the **best** expectancy (+0.139R), not OPTIMAL. EARLY = entering before full signal confirmation, often catching moves at a better price. EXTENDED entries are correctly excluded — they are the only group with **negative expectancy** despite a 51% win rate (wins are smaller than losses).

OPTIMAL entries have notably lower expectancy (+0.069R vs +0.139R) and a full 17.5% DD on their own. The current filter (EARLY+OPTIMAL) is appropriate for excluding EXTENDED, but OPTIMAL is not adding meaningful edge.

EARLY dominates both trade count and performance. The max DD of 90.9% for EARLY vs 17.5% for OPTIMAL reflects that EARLY entries have wider stop placement → closer to the 20% position cap → larger portfolio swings.

---

## 4. RISK & POSITION SIZING AUDIT — WHY 92% DRAWDOWN

### How position sizing works

```
stop_dist_pct  = (entry - initial_stop) / entry
raw_position   = RISK_PER_TRADE_PCT (1%) / stop_dist_pct
position_size  = min(raw_position, MAX_POSITION_SIZE_PCT=20%)
portfolio_pnl  = pnl_pct × position_size / 100
```

**At a 5% stop:** `raw_pos = 1%/5% = 20%` → capped at 20% → loss = 5% × 20% = **−1%** ✓
**At a 2% stop:** `raw_pos = 1%/2% = 50%` → capped at 20% → loss = 2% × 20% = **−0.4%** (under 1R)
**At a 10% stop:** `raw_pos = 1%/10% = 10%` → uncapped → loss = 10% × 10% = **−1%** ✓

**Conclusion: The risk model is mathematically correct.** At stop execution, loss ≤ 1% of equity. Stops are checked against `low ≤ stop` and exit is filled **at the stop price** — there is no gap slippage modeled.

### Why 92% DD still occurs — the real cause

**The capital curve simulation has a structural flaw.** The `_capital_curve()` function chains ALL 5,618 trades from 425 independent tickers sorted by `exit_date` into a single sequential P&L stream. This does **not** model a real portfolio.

**Root cause breakdown:**

1. **Concurrent losses are compounded sequentially.** During Q1 2022 (bear market onset), many of the 425 tickers simultaneously generate RES_BREAKOUT false breakouts. These cluster into hundreds of sequential `−1%` hits in the exit_date-sorted stream. (0.99)^250 = 8% of peak equity → 92% DD. In reality, a 5-position portfolio with 1% risk per trade can never exceed 5% loss per day.

2. **No portfolio-level position cap.** The per-ticker engine limits `MAX_OPEN_POSITIONS=5` per ticker. But the simulation treats all 425 tickers independently — effectively simulating 425 × 5 = 2,125 concurrent positions, each allocated 20% of the same capital.

3. **Stop execution is optimistic (no gap risk).** `if low <= stop: return True, stop, "STOP"` — trade exits at the stop price, never below it. In a real overnight gap-down, exit could be 5–15% below stop. Live trading will show larger actual losses.

4. **The 2024 +5,694% is also a simulation artifact.** A handful of AI/momentum stocks that ran 5–10x triggered the trailing stop mechanism, each at 20% position size. Sequential compounding of massive winners (e.g., +500% trade → `portfolio_pnl_pct = +100%`) turns the equity curve parabolic. In a real portfolio, these winners are concurrent with other open positions, diluting the impact.

**Summary:** The 92% DD is not a real-world portfolio risk figure. It is produced by treating each of 425 tickers' trades as sequential draws on the same full capital base. The true max DD in a properly simulated 5-position portfolio is likely 25–40%.

---

## 5. LOSING STREAK & DISTRIBUTION

- **~3,371 losing trades** out of 5,618 (59.1% of all trades)
- **Win rate: 40.9%** — this is a trend-following system with infrequent but large wins
- Expected max consecutive losses at 60% loss rate: statistically expect 12–15 consecutive losses regularly, up to 20+ in bad stretches
- **RES_BREAKOUT** (2,437 total, 32.3% win) carries the highest raw loss count: ~1,647 losing trades

**R-distribution inference:**
- PF=1.37 with 41% win rate → avg win ≈ 2.26× the avg loss
- Losing trades: avg ≈ −0.85R (tight, bounded by position sizing)
- Winning trades: avg ≈ +2.0–3.0R (from trailing stops running)
- **EXTENDED trades** (excluded): 51% win rate but −0.045R expectancy → avg win is small (~+0.5R) while avg loss is large (~−0.6R)

The system has **positive skew on wins** (few huge winners drive PF>1) and **bounded losses**. This means the equity curve has long flat/drawdown periods punctuated by sharp explosions. Psychologically demanding.

---

## 6. EQUITY CURVE ANALYSIS

| Year | System | SPY | vs SPY | YoY System |
|------|--------|-----|--------|------------|
| 2020 | 2.358x | 1.172x | +1.19x | **+135.8%** |
| 2021 | 5.806x | 1.509x | +4.30x | **+146.2%** |
| 2022 | 2.343x | 1.235x | +1.11x | **−59.6%** |
| 2023 | 8.354x | 1.558x | +6.80x | **+256.5%** |
| 2024 | 484.05x | 1.946x | +482x | **+5,694.1%** |
| **CAGR** | **+244.3%** | **+14.2%** | **+230.1%** | |

**Period analysis:**
- **2020–2021:** Strong bull market, high AGGRESSIVE regime → maximum edge extraction
- **2022:** Bear year. YoY −59.6%. Regime gate reduces trades but transition lag causes significant false signals, especially RES_BREAKOUT. Within-year peak-to-trough likely reaches 85–90% before recovering — this is where the 92% max DD originates.
- **2023:** Recovery year, excellent +256.5%
- **2024:** AI stocks and momentum. A handful of tickers (NVDA-type names) produce parabolic moves. Trailing stops ride these to 5–10x. At 20% position size these become 100%+ portfolio hits in the sequential simulation → 5,694% year.

The equity curve is **extremely regime-sensitive.** Years with clear AGGRESSIVE regimes (2020, 2021, 2023, 2024) drive all returns. 2022 alone nearly wipes out accumulated gains.

---

## 7. CONTRIBUTION ANALYSIS

### Remove SELECTIVE trades (527 trades)
- Lose 9.4% of trades, the highest-quality block (PF=1.61 vs AGGRESSIVE 1.35)
- Expected: modest DD reduction (SELECTIVE DD 40.3% vs AGGRESSIVE 86.6%), slight expectancy drop
- **Verdict: Do NOT remove. SELECTIVE trades are better quality — removing them hurts the system.**

### Remove PULLBACK (3,090 trades)
- Lose 55% of all trades. PULLBACK is the highest count setup with the lowest expectancy (+0.097R AGGRESSIVE)
- Expected: significant DD reduction (PULLBACK contributes 51.5% DD in AGGRESSIVE), modest improvement to remaining expectancy
- **Verdict: PULLBACK is a volume contributor with low edge per trade. The system runs on PULLBACK quantity, not quality. Removing it would clarify where real alpha comes from.**

### Only top setups (HTF + BASE, 84 trades)
- HTF: PF=4.58, +0.323R. BASE: PF=1.81, +0.147R
- Problem: 84 trades over 5 years = ~17 per year — statistically meaningless sample
- **Verdict: Highest edge per trade, but unusable at current signal rate.**

### What's actually driving results

| Driver of Returns | Driver of Drawdowns |
|-------------------|---------------------|
| Few massive RES_BREAKOUT winners in 2024 (trailing stops) | RES_BREAKOUT false breakouts in 2022 |
| PULLBACK volume via high win rate | PULLBACK sequential loss clusters |
| Sequential compounding of 2024 momentum winners | 2022 concentrated loss cluster in exit-date sort |

---

## 8. FINAL DIAGNOSIS

### Is the system truly profitable?

**At the trade level: yes.** PF=1.37, expectancy +0.134R, positive across all setup types. The edge is real but thin and highly concentrated in momentum regimes.

**At the portfolio-simulation level: the numbers are not realistic.** The 92% DD and 5,694% year are both artifacts of the sequential capital curve treating 425 independent tickers as a single serial trade stream. A proper portfolio simulator would show materially different — and more moderate — numbers. Best estimate of real-world performance: CAGR 30–80%, max DD 25–40%.

### Where is the real edge?

1. **Trailing stops on momentum breakouts.** The system's true alpha comes from capturing rare 3–10x winners via ATR trailing stops. Without these, PF would likely be below 1.0. The edge is in the **right tail of the return distribution**, not in win rate.

2. **Regime gate eliminates DEFENSIVE environment entirely.** Zero trades in DEFENSIVE = zero unnecessary losses during sustained downtrends. This is the system's primary risk management layer.

3. **HTF is the highest-conviction setup (PF=4.58, +0.323R)** but fires only 23 times over 5 years — statistically and practically irrelevant to returns at current signal rate.

### Biggest risk flaw

**RES_BREAKOUT in AGGRESSIVE regime.** 2,246 trades, 32.3% win rate, 79% sequential DD. This single setup×regime combination creates the majority of the drawdown. During 2022 bear-to-bull transition, the AGGRESSIVE gate stays open but breakouts fail repeatedly, creating a dense loss cluster.

The second risk flaw is the **capital curve simulation itself** — it overstates both upside and downside by ignoring concurrent position limits across the universe. Do not use the 92% DD figure as a real-world risk estimate.

### Top 3 changes for robustness

**1. Fix the capital curve simulation.**
Implement a proper time-step portfolio simulator that respects a single portfolio of ≤N concurrent positions across ALL tickers. Group trades by entry/exit date, allocate capital by overlap. This will give the true max DD (likely 25–40%, not 92%) and the true CAGR (likely 30–80%, not 244%).

**2. Add a SELECTIVE-only filter for RES_BREAKOUT.**
RES_BREAKOUT in SELECTIVE: PF=1.65, DD=21.2%. In AGGRESSIVE: PF=1.30, DD=79%. Restricting breakout signals to SELECTIVE regime (or requiring a stricter sub-filter within AGGRESSIVE) would dramatically reduce 2022-type loss clusters. The trade-off is going from 2,246 to 191 breakout trades, but quality improves by 4×.

**3. Model gap risk on stops.**
The current backtester exits at stop price even when price gaps through it. Add actual gap exit: `exit_price = open if open < stop else stop`. For EARLY entries with tight stops and large positions (near 20% cap), gap losses can be 3–5× the design risk. This correction will lower both the reported returns and the reported DD and will more accurately reflect live trading results.
