# Full System Audit — 2026-03-16

> Performed after WFO validation, live params injection, and tp_multiple update.
> Assumes real-money trading. Brutally honest. No cosmetic issues included.

---

## 1. Critical Issues (must fix)

---

### CRITICAL-1: Gap-chase filter exists in backtest but not in live scanner

In `backtest_engine.py` (~line 936):
```python
if open_price > zone_upper * (1 + brk_gap_pct):
    continue  # skip entry — gap too wide
```
This filter skips RES_BREAKOUT entries where the next morning's open is already too extended.
In the live scanner, the signal is generated and shown to the trader. If the stock gaps up 5% overnight, the trader still sees the signal and may enter — at a price the backtest would have rejected.

WFO OOS windows W3 (147 RES_BRK trades) and W4 (279 trades) include this filter. Live scanner does not.
**The backtest is systematically better than live trading would be for all breakout signals.**

**Fix:** Show a `gap_risk` flag on the signal. At morning scan, re-check whether entry is still valid
under `brk_gap_pct`. Mark as "EXTENDED — do not chase" if threshold exceeded.

---

### CRITICAL-2: `tp_multiple` upper bound (6.0) is at the ceiling — search space too narrow

WFO found optimal TP consistently ~5.8 across all 4 windows. The Optuna search space is `[1.5, 6.0]`.
Optuna was bumping against the ceiling and could not explore higher values. The real optimal may be 6.5–7.0.
The default was raised to 5.80 but the search space was not widened. Any future re-optimization will still be capped.

**Fix:** Widen `tp_multiple` search space in `optimize_v5.py` and `wfo_optuna.py` to `[1.5, 9.0]`.

---

### CRITICAL-3: Live regime (7 factors) vs backtest regime (4 factors) — systematic divergence

The live scanner uses VIX, breadth, and H/L ratio (factors 5–7) in addition to the 4 SPY-only factors.
The backtest uses only F1–F4. In 2022, VIX was extreme and breadth was devastated — the live 7-factor
system would have produced near-zero regime scores and blocked almost all trading. The backtest 4-factor
system still allowed trades in brief AGGRESSIVE windows.

This means WFO W2 (2022) results are **pessimistic** relative to real live performance — the live regime
filter is stronger during bear markets than the backtest represents.

**Fix:** Either add VIX/breadth proxies to backtest regime calculation, or document that WFO W2 is a
pessimistic lower bound.

---

### CRITICAL-4: MAX_OPEN_POSITIONS (5) — unclear if enforced during backtest replay

The WFO OOS ran 502 trades in W4 over 12 months (~2 per trading day), implying many concurrent open
positions. If `BacktestEngine` does not enforce `MAX_OPEN_POSITIONS=5`, it simulates a portfolio
with unlimited capacity — far more than the live scanner's actual 5-position cap.

**Fix:** Verify that `BacktestEngine` enforces the position cap during replay. If not, add the cap
and re-run WFO to get realistic trade counts and portfolio returns.

---

### CRITICAL-5: Earnings blackout not applied in WFO/backtest

`filters.py:in_earnings_blackout()` blocks trades within 7 days of earnings in the live scanner.
The WFO backtest runs without historical earnings data — no earnings DB is passed to `BacktestEngine`.
The backtest takes trades the live scanner would block: earnings-driven gaps and reversals are included
as normal signals, inflating trade quality metrics.

**Fix:** Source historical earnings dates (yfinance provides them) and inject into `BacktestEngine`
during WFO. At minimum, document this divergence and treat WFO trade counts as upper bounds.

---

## 2. Structural Weaknesses

---

### STRUCTURAL-1: `_LIVE_PARAMS` cannot be hot-reloaded

`_LIVE_PARAMS = BacktestParams()` is a module-level singleton created once at server startup.
Changing any parameter requires a full server restart. No admin endpoint, no config file reload,
no runtime mutation.

---

### STRUCTURAL-2: Cooldown days not enforced in live scanner

`BacktestParams.cooldown_days=4` prevents re-entry on the same ticker within 4 bars of closing
a position. The live scanner has no position state and no trade history check. A ticker that just
stopped out will immediately re-appear if it generates a new signal.

---

### STRUCTURAL-3: `_SIGNAL_BASE_SCORES` are hardcoded, not tunable

```python
"VCP": 6.0, "RES_BREAKOUT": 6.0, "BASE": 5.0, "HTF": 5.0, "LCE": 4.0
```
These determine relative signal priority but were never Optuna-optimized. If LCE empirically
outperforms VCP in OOS testing, it still gets the lowest base score. Should be derived from
per-setup OOS performance data.

---

### STRUCTURAL-4: `nearest_resistance_target()` uses `zone["lower"]` as TP target

TP is set at the **floor** of the nearest resistance zone, not the ceiling. A stock entering the
zone triggers the TP before clearing resistance. `zone["upper"]` would be more appropriate for
breakout-style trades where the goal is to profit from the stock clearing the resistance zone.

---

### STRUCTURAL-5: Signal deduplication not handled

A ticker can generate a PULLBACK and a BASE signal simultaneously. Both appear in the live scan.
A trader sees the same ticker twice with different entry/stop/TP levels and no guidance on which
to prioritize. There is no "best signal for this ticker" consolidation in the output.

---

### STRUCTURAL-6: `_scan_state` is a mutable global with no concurrency protection

If two scan requests hit the server simultaneously, both write to `_scan_state`. No locking,
no isolation. Engine stats, timing data, and setup counts will corrupt each other silently.

---

## 3. Strategy Misalignments

---

### MISALIGNMENT-1: `tp_multiple=5.80` applied uniformly to ALL signal types including LCE and HTF

LCE (Low Cheat Entry) is designed to enter just below resistance and exit when price clears it.
Its natural TP IS the resistance zone — typically 1–3R. Applying 5.80R forces a target well beyond
the resistance zone the pattern was designed to trade through.

HTF (High Tight Flag) entries off a tight consolidation after an 80%+ move also have natural
extension targets that may not be 5.80R. The `_apply_tp_multiple` override is architecturally
wrong for zone-defined exit patterns.

**Fix:** Add a `use_zone_tp` flag per setup type. LCE and HTF use zone-based TP. PULLBACK and
RES_BREAKOUT use `tp_multiple`. VCP uses trailing stop (TP is rarely reached).

---

### MISALIGNMENT-2: VCP trail mult = 2.0 ATR makes `tp_multiple=5.80` decorative for VCP trades

VCP trades trail at 2.0 ATR — tight. A 2-ATR pullback on a volatile breakout stock is common.
The trade almost always exits via trailing stop long before reaching 5.80R. The TP displayed to
the trader (5.80R above entry) is misleading — the real expected exit is 1.5–3R via trailing stop.

---

### MISALIGNMENT-3: RS rank gate (top 70%) in live scanner not in backtest

The live scanner shows only top-30% RS stocks (plus discovery tier 60–70%). The WFO ran on the
full cached universe. Top-RS stocks historically outperform the median — the live scanner is
showing a higher-quality subset than the WFO tested. WFO E(R) is likely a conservative estimate
for the live scanner's actual output, but this has never been validated.

---

### MISALIGNMENT-4: Backtest uses T+1 open; no mechanism in UI to enforce this

The backtest is precise: enter at T+1 open. Signals are generated EOD. A trader who acts intraday
or mid-morning instead of at the open takes a different entry than the backtest assumes. There is
no "act at tomorrow's open" instruction surfaced to the trader in the dashboard.

---

## 4. Optimization Problems

---

### OPTUNA-1: `score_threshold=2.50` frozen — never optimized

This gates all pullback signals. It directly controls how many signals fire and their quality.
As important as `rs_threshold` but has never been Optuna-optimized. The 2.50 value came from an
earlier round and was frozen without principled justification.

**Fix:** Add `score_threshold` to the Optuna search space: `[1.0, 4.0]`.

---

### OPTUNA-2: Objective function has no drawdown penalty

`E × PF × log(N+1)` maximizes profitability and trade count but ignores MaxDD.
WFO W4 optimized had MaxDD=-25.39R vs frozen #433's -4.53R. Optuna found a higher-return,
higher-risk param set because nothing penalized drawdown.

**Suggested objective:**
```python
calmar = expectancy / max(0.1, abs(max_drawdown_r))
score = calmar * pf * math.log(n + 1)
```

---

### OPTUNA-3: MIN_TRADES=200 creates a hard cliff at exactly 200 trades

A trial with 199 trades scores -99. A trial with 201 trades scores normally. This creates
optimization pressure to pad trade count rather than improve edge quality. Trials barely over
200 with weak edge beat genuinely good trials under 200.

**Fix:** Smooth penalty: `score × min(1.0, (N/200) ** 0.5)` — scales gracefully from 0 to full score.

---

### OPTUNA-4: `brk_stop_atr` and `brk_min_pct` in search space despite WFO showing CV > 0.30

WFO proved these are regime-sensitive (CV=0.310 and CV=0.465). Optimizing them to a global average
means they are suboptimal in every specific regime. They should be removed from the search space
and frozen at a moderate value until a regime-adaptive system is built.

---

### OPTUNA-5: `brk_aggressive_only` and `brk_regime_factor` never tested by Optuna

`brk_aggressive_only=True` means `brk_regime_factor=0.861` is dead code — it is never applied.
Optuna has never been allowed to test whether SELECTIVE breakouts with a scoring penalty are
profitable. This is an unexplored dimension of the strategy.

---

### OPTUNA-6: Fixed seed=42 across all windows creates correlated exploration

All W1–W4 Optuna studies used seed=42. The same initial Latin hypercube samples bias all windows
toward the same region of the search space. Independent seeds per window would give more
structurally independent param solutions.

---

## 5. Scanner Quality Evaluation

---

### QUALITY-1: LCE volume filter is effectively no filter

`LCE_BREAKOUT_VOL_RATIO = 1.0` — volume must be >= 1× 20-day average. Almost every trading day
meets this condition. Combined with 3% proximity tolerance, LCE signals fire frequently with
minimal quality gating. The 4.0 base score (lowest of all setups) is the only protection.

---

### QUALITY-2: HTF 35% risk cap generates near-zero position sizes

At 1% risk per trade and 35% stop distance: position = 1% / 35% = 2.86% of portfolio.
An HTF signal appears high-conviction but the actual capital deployed is trivial.
Either tighten HTF risk cap to 15–20% or document that HTF positions are token-sized.

---

### QUALITY-3: VCP PATH B (confirmed breakout) shows signals that have already moved

PATH B fires when price is already 0.5–3% above resistance with high volume. The T+1 entry
(next morning open) could be 2–5% beyond the original breakout level. The further from the
breakout the trader enters, the worse the stop-to-entry risk. The signal quality degrades
rapidly with time.

---

### QUALITY-4: No signal expiry or staleness tracking

Signals don't expire. A PULLBACK signal from 3 days ago that never triggered may still be
visible. The stock may have moved significantly. The scanner generates fresh signals per run
but there is no automatic re-validation or expiry of stale candidates.

---

## 6. Hidden Logic Risks

---

### HIDDEN-1: ATR_STOP_MULTIPLIER constant discrepancy — 1.278 vs 0.8

`constants.py` defines `ATR_STOP_MULTIPLIER = 1.278`. Engine 3 documentation and some test
references cite 0.8. If engine3 imports from constants and uses 1.278, pullback stops are 60%
wider than the documented strategy description implies. This directly affects R:R calculation,
position sizing, and whether backtest stop levels match what a trader would manually set.

**Verify immediately:** `grep -n "ATR_STOP_MULTIPLIER" engines/engine3.py`

---

### HIDDEN-2: Trailing stop EMA20 floor can override ATR trail in choppy markets

`new_trail = max(ema20, atr_trail)` — if EMA20 > ATR-based trail, EMA20 sets the floor.
In choppy markets, EMA20 lags significantly and may keep the stop wider than the ATR calculation
intends. The stop width becomes regime-dependent in a way that is not explicitly controlled or
documented.

---

### HIDDEN-3: Portfolio return calculation may mishandle capped positions

WFO reports port=+449.6% for W4. If stops are 0.5% away from entry, theoretical position =
200% of portfolio — capped at 20%. If `portfolio_pnl_pct` in TradeRecord uses the theoretical
uncapped position instead of the actual capped size, portfolio returns are overstated for
tight-stop signals.

**Fix:** Verify `TradeRecord.portfolio_pnl_pct` uses `min(theoretical_size, MAX_POSITION_SIZE_PCT)`.

---

### HIDDEN-4: Discovery tier signals (RS 60–70%) have no OOS validation

Discovery-tier stocks appear in live scanning but were never isolated in WFO testing. There is
no evidence their signal quality matches the main universe. They could significantly outperform
or underperform — currently unknown.

---

### HIDDEN-5: `brk_gap_pct` (BacktestParams) vs `RES_MAX_GAP_PCT` (constants) — two gap constants

`BacktestParams.brk_gap_pct = 0.01021` and `RES_MAX_GAP_PCT = 0.03` both exist.
If any code path reads `RES_MAX_GAP_PCT` instead of `params.brk_gap_pct`, the gap filter
uses 3% instead of 1%, allowing more gap-chase entries than the Optuna-tuned param intends.
Grep for all usages of `RES_MAX_GAP_PCT` to confirm it is not used where `brk_gap_pct` should be.

---

### HIDDEN-6: No time-based exit — stale positions tie up capital indefinitely

A trade can stay open for 60+ days without hitting stop or target, tying up a full position slot.
With MAX_OPEN_POSITIONS=5, one zombie trade blocks 20% of the portfolio indefinitely.
The WFO results include these long-duration trades — holding period distributions are not reported.

---

## 7. Top 10 Improvements (ranked by impact)

| # | Improvement | Impact | Effort |
|---|---|---|---|
| 1 | Morning re-validation of breakout signals — flag "EXTENDED" if stock gapped beyond `brk_gap_pct` | Closes biggest live/backtest gap | Medium |
| 2 | Widen `tp_multiple` search space to `[1.5, 9.0]` | Allows Optuna to find true optimum | Trivial |
| 3 | Add drawdown penalty to Optuna objective (Calmar-adjusted) | Finds smoother, more tradeable equity curves | Small |
| 4 | Per-signal-type TP logic — LCE/HTF use zone-based TP, PB/BRK use `tp_multiple` | Correct architectural alignment for each pattern | Medium |
| 5 | Smooth MIN_TRADES cliff: `score × min(1.0, sqrt(N/200))` | Removes perverse optimization incentive | Trivial |
| 6 | Verify and fix ATR_STOP_MULTIPLIER discrepancy (1.278 vs 0.8 in engine3) | Potentially fixes significant R:R miscalculation | Trivial to verify, small to fix |
| 7 | Add `score_threshold` to Optuna search space `[1.0, 4.0]` | The primary quality gate, never optimized | Small |
| 8 | Add historical earnings dates to WFO/backtest replay | Closes live/backtest divergence on ~15–20% of signals | Medium |
| 9 | Add sector concentration cap/warning in live scanner output | Prevents hidden correlated risk in portfolio | Small |
| 10 | Add `max_holding_days` (e.g., 30 bars) as time-based exit | Improves portfolio velocity, removes zombie positions | Small |

---

## Summary Assessment

The strategy edge is real — +0.219R combined OOS expectancy on 1,048 trades across 4 different
market regimes is statistically meaningful. The system architecture is sound.

The primary risk for real-money trading is the **execution gap**: the backtest assumes cleaner
entries (T+1 open, gap filter applied) than a human trader operating from dashboard signals will
achieve. CRITICAL-1 (gap filter) and MISALIGNMENT-4 (T+1 open discipline) are the most
important issues before going live with real capital.

The most impactful parameter change that can be made today is widening the `tp_multiple` search
space (2 minutes of work) before the next re-optimization run.
