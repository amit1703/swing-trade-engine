# Scanner Engine Architecture Review — 2026-03-15

Deep design-level audit against current code, Optuna v5 results, and backtest statistics.
Covers: target logic, detection/targeting asymmetry, engine overlap, stop sizing, pullback support constraints, VCP role, stop consistency, and ranking system interaction.

---

## 1. Target Logic (KDE-only targeting)

### What the code actually does

**Confirmed — but partially inaccurate framing.** `nearest_resistance_target()` searches `zones` for entries where `type == "RESISTANCE"` and `zone["lower"] > entry`. The zones list passed to all engines comes from Engine 1, which includes **both** KDE-derived zones and pivot resistance zones (from `_find_pivot_resistance()`). So pivot highs ARE valid targets — they already appear in the zones list.

What is genuinely missing: **Donchian highs** used in E6 detection are never written into the zones list. They are ephemeral — computed per breakout bar — and not stored as persistent zones.

### Is KDE-dominant targeting optimal?

Yes, for two reasons:

1. **Pivot zones are already included.** The concern is already addressed. `_find_pivot_resistance()` returns up to 2 overhead pivot resistance zones per ticker, and they propagate through the full zones list to `nearest_resistance_target()`.

2. **Donchian should not be a target.** The Donchian resistance is the rolling max of the last 63 bars of highs — by definition, price just broke through it. Using it as a take-profit target would be setting the target behind entry (since `brk_high × 1.001 > Donchian` after the cross). It makes no physical sense as a supply zone.

### What could be improved

The fallback target (`TARGET_RR = 2.785 × risk`) activates whenever no KDE resistance zone is found above entry, or when the nearest zone yields R:R < 1.0. On a strongly trending ticker with no historical overhead resistance, this fallback fires and sets a fixed-R target. The problem: a stock trending at all-time-highs with no supply zones above has no natural target — and setting 2.785× is arbitrary. **This is structurally unavoidable**, not a bug. Document it and accept it.

**One real gap:** The Optuna v5 study shows `tp_multiple` converging at 3.999, hitting the ceiling of [1.5, 4.0]. The current fallback target of 2.785× is the live scanner value, but Optuna wants higher. **Expand `tp_multiple` to [1.5, 6.0] in the next run before freezing this value.** The live scanner uses `TARGET_RR = 2.785`, which may be leaving profit on the table on trending setups.

---

## 2. Structural Asymmetry: Detection vs Targeting

### Confirmed — and intentional by design

Detection uses: KDE zones, Donchian, EMA value zones, consolidation lows, demand zones, ascending trendlines, CCI, volume — six different signals.

Targeting uses: KDE + pivot resistance zones (one call to `nearest_resistance_target()`).

### Why this asymmetry is correct

Detection answers: "Is this stock in a valid setup right now?" That requires many confirming signals — structural support, momentum, trend, volume. Multiple signals reduce false positives.

Targeting answers: "Where will selling pressure emerge above entry?" That requires supply zones. KDE density peaks are precisely supply-zone estimates (historical clustering of institutional selling). EMA levels, consolidation lows, and demand zones are *support* concepts — they are not supply. Donchian is a lookback window metric. None of these add information about where supply will hit above entry.

### Verdict

The asymmetry is architecturally correct. Expanding targeting to use more signals would introduce noise, not signal. **Do not change.**

---

## 3. Engine Overlap (VCP Path B vs BRK)

### What actually happens in main.py

**There is no deduplication between engines.** Looking at `_process_ticker`:

```
E2 (VCP, Path A/B)  → appends to collected_setups if fires
E3 (Pullback)        → appends to collected_setups independently
E5 (Base)            → appends to collected_setups independently
E6 (BRK)             → appends to collected_setups independently
```

If a ticker triggers both E2 and E3, **both appear in the scanner** as separate rows with different `setup_type` labels (VCP vs PULLBACK). This is **by design** — they represent different thesis: VCP is about coiling near KDE resistance, PB is about bouncing from a MA value zone.

The specific VCP Path B / E6 overlap: E2 Path B produces `setup_type="VCP"`, E6 produces `setup_type="RES_BREAKOUT"`. They can both fire on the same ticker on the same day. Both appear in the scanner. They will have different resistance sources, different entry prices (E2 uses KDE zone upper, E6 uses best of Donchian/pivot/KDE), and will receive different scores.

### Is this behavior deterministic?

Yes. The scoring system then sorts all setups by `setup_score` descending. The "winner" on the scanner is whichever setup has the higher unified score — determined by RS rank, R:R, volume, and regime. Neither engine has a structural score advantage; it depends on the specific setup parameters.

### Should overlapping signals be merged?

**No — but E2 PATH B is effectively redundant with E6.** E6 is more sophisticated: it uses three resistance sources, has a gap gate, consolidation filter, and Optuna-tunable parameters. E2 PATH B uses only KDE zones and a simpler filter. The Optuna study never tuned E2's breakout path.

**Recommendation:** Consider removing E2 PATH B entirely and letting E6 handle all resistance breakout detection. E2 should keep only PATH A (DRY / coiling below KDE) which has no equivalent in E6. This would eliminate the overlap, simplify the codebase, and consolidate breakout optimization into a single engine. This is a meaningful architectural cleanup — but it requires validating that no important breakout signals are missed by doing so.

---

## 4. Base Engine Stop Size

### Was 0.2×ATR discovered by Optuna?

**No. It is hardcoded in engine5.py and has never been exposed to Optuna.** There is no `base_stop_atr` field in BacktestParams. Compare to E6 which has `brk_stop_atr` (Optuna v5 converged at 0.42, though the analysis flags this as unreliable due to zero BRK trades in optimization).

### What do the backtest stats say?

- 54 trades, WR=35.2%, E=+0.282R, PF=2.63 (cache baseline)
- Best Optuna trial: 24 BASE trades, 9% of portfolio

35.2% win rate is notably low for a pattern marketed as high-quality base formations. This is consistent with a very tight stop: 0.2×ATR below the base floor is mechanically small — on a $200 stock with $4 ATR, the stop is $0.80 below the box floor. Normal noise in a tight consolidation will often punch through this.

However, the positive expectancy (+0.282R) and PF (2.63) suggest the wins are large enough to compensate for frequent stop-outs. This is the trade-off: tight stop = high R:R on winners, but frequent stops.

### Should the stop be widened?

The honest answer: **we don't know yet.** The Base engine has never been Optuna-tuned for stop placement. The 0.2×ATR is likely too tight on average but may be appropriate for the specific flat-base geometry (box floor = validated support).

**Recommendation:** Add `base_stop_atr` (range [0.2, 1.0]) to BacktestParams and include it in the next optimization run. Do not change the hardcoded value until Optuna gives a direction. With only 54 trades in the baseline, confidence intervals are too wide to eyeball the optimum.

---

## 5. Pullback Structural Support Constraint

### Was the 3% threshold chosen by Optuna?

**No.** The 3% proximity check in `_find_structural_support()` (layers 2 and 3 — consolidation low and demand zone) is hardcoded. Layer 1 (KDE) uses a separate 2.5% tolerance. Layer 4 (ascending TDL) uses 0.8%.

### Does it cause valid supports to be ignored?

**Yes, systematically, on high-ATR stocks.** On a stock with 3% ATR (e.g., a $100 stock moving $3/day), a valid consolidation low that is 3.5% below today's low is functionally 1.17 ATR away — entirely reasonable support. The fixed 3% check rejects it.

Compare to how the Relaxed Pullback already handles this: it uses `abs(lc - l8) / latr <= 0.75` for EMA proximity — an ATR-normalized distance. That's the right approach.

The irony: the strict pullback uses a fixed-percentage proximity gate for structural support, while the relaxed pullback uses ATR-normalized proximity for EMA distance. They should use the same normalization methodology.

### Proposed fix

Replace the fixed 3% with an ATR-relative threshold:

```python
# Current (layers 2 and 3):
if abs(ll - candidate) / candidate > 0.03:
    continue

# Proposed:
_prox_pct = max(0.03, 1.2 * latr / ll)  # ATR-adaptive, floor at 3%
if abs(ll - candidate) / candidate > _prox_pct:
    continue
```

This preserves the 3% floor for low-volatility stocks while allowing ATR-proportional lookback for high-volatility stocks. The `latr` value is already available in the calling context. **This is a low-risk improvement that would increase pullback detection on high-ATR leaders — which are precisely the stocks most worth trading.**

---

## 6. VCP Engine Role

### Is VCP contributing meaningful edge?

VCP is not directly measurable from the Optuna v5 study because it was not tuned separately. In the best trial (scored mode), pullback dominates 91% of trades (244/268). VCP was not explicitly counted.

However, VCP serves a distinct purpose that Pullback cannot replace:

- **VCP PATH A (DRY):** Detects coiling below a KDE resistance zone before breakout. This is a structural compression signal that neither E3 nor E6 detect in their current form. E3 looks at EMA pullbacks; E6 looks at breakouts that already happened. VCP PATH A is the *pre-breakout coiling* signal.

- **VCP in the WATCHLIST context:** `scan_near_breakout()` (near-breakout detection for watchlist) is also E2. Watchlist items don't go through the scoring gate. They bypass the 70-point threshold. This makes E2 the only engine contributing watchlist candidates.

### Should VCP remain?

**Yes, but only PATH A.** PATH B (confirmed breakout through KDE) overlaps with E6 and should be removed (see point 3 above). PATH A (DRY coiling) is unique, provides the pre-breakout watchlist signal, and is the correct use case for VCP compression detection.

VCP's contribution is as a **leading indicator** — it surfaces stocks before they break out, giving you a DRY entry signal or a watchlist entry. Its backtest contribution is probably obscured by E6 winning the breakout detection race when the actual break occurs.

---

## 7. Engine Stop Logic Consistency

### Current stop structure (from code)

| Engine | Pattern | Stop Formula | ATR Multiple |
|--------|---------|--------------|--------------|
| E2 | VCP | `min(low, zone_lower) − ATR_STOP_MULTIPLIER × ATR` | 1.278× (Optuna v4) |
| E3 | Pullback | `min(low, zone_lower) − ATR_STOP_MULTIPLIER × ATR` | 1.278× (Optuna v4) |
| E5 | Base | `floor − 0.2 × ATR` | 0.2× (hardcoded, never optimized) |
| E6 | BRK | `resistance − brk_stop_atr × ATR` | 0.42× (Optuna v5, but fitting noise) or 0.8× (legacy) |

Note: `RES_STOP_ATR_FACTOR = 0.8` in constants.py is the legacy/backtest default for E6. The Optuna v5 value of 0.42 is labeled as unreliable in the analysis (0 BRK trades in optimization → no real signal to learn from).

### Does the asymmetry affect ranking?

**Yes, in a structural way.** The R:R scoring component is `min(20, rr / 3.0 × 20)`. R:R = (target − entry) / (entry − stop). With 0.2×ATR stop, BASE produces very high apparent R:R — the denominator is small. A BASE setup targeting $10 above entry with a $0.80 stop produces R:R = 12.5, which gets capped at the same score as R:R = 3.0.

The scoring cap at 3.0× means **all engines above 3.0R are scored identically on the R:R component**. This neutralizes the artificial R:R inflation from tight BASE stops. It also means the scoring correctly treats any ≥3R setup as equally good regardless of how the stop was calculated.

However: a BASE setup with R:R = 8 scoring the same as a PB setup with R:R = 3 is misleading to the user. The BASE setup has a much tighter stop that will be hit more often, but the scanner shows the same R:R points.

**Recommendation:** Either raise the R:R cap from 3.0× to 5.0–6.0× (consistent with the Optuna push toward tp_multiple=4+), or add a per-engine R:R normalization that accounts for stop reliability. The first option is simpler.

### Was the asymmetry intentional?

Partially. E3's 1.278× was Optuna-discovered. E6's 0.8× is a conservative empirical default (the 0.42 from v5 Optuna is unreliable). E5's 0.2× is inherited from the original Darvas Box concept where the box floor is the stop. The three values reflect different philosophical choices:

- E3: ATR buffer below the structural low (breathing room)
- E5: Minimal buffer below the consolidation floor (tight is the thesis)
- E6: Fixed distance below the broken resistance level (where buyers should return)

These are all defensible. **The problem is not the asymmetry itself but that E5 has never been tuned.**

---

## 8. Ranking System Interaction

### Score component breakdown

From `compute_setup_score()`, the 7 components and their caps (raw sum = 120, capped at 100):

| Component | Max pts | Notes |
|-----------|---------|-------|
| RS Rank | 30 | Scales linearly with percentile; ×1.15 multiplier for RS ≥ 85 |
| R:R | 20 | Caps at R:R = 3.0; above 3.0 adds nothing |
| Volume | 20 | Full for vol_ratio ≥ 2.0 or is_vol_surge; Pullback gets 6 pts baseline for structural support |
| RS Quality | 20 | rs_vs_spy, rs_improving, rs_near_high, rs_acceleration, tight_range_5d |
| Regime | 15 | AGGRESSIVE=15, SELECTIVE≈8 (53%), DEFENSIVE=0 |
| Sector | 10 | Top-5 sectors=10, 6–8=8, outside=4 |
| Quality | 5 | BASE uses quality_score (0–100). Others: rs_blue_dot, weekly_confirmed, atr_compressed |

**The RS components dominate: RS Rank (30) + RS Quality (20) = 50 of 120 raw points, 50 of the effective 100.** A ticker with RS rank = 90 starts with ~26 RS rank pts + up to 20 RS quality pts before any pattern-specific scoring. This is intentional and correct: high RS tickers are the ones worth trading regardless of pattern type.

### Does any engine dominate the ranking?

**No engine dominates structurally.** The scoring is setup-type agnostic — it rewards RS quality, R:R, and volume regardless of which engine fired. However, there are de facto advantages:

- **BRK in AGGRESSIVE:** Gets full 15 regime pts + typically high vol (2×+ required to fire) = ~35 pts from regime+vol alone. BRK favors AGGRESSIVE regimes.
- **Pullback in SELECTIVE:** Gets only 8 regime pts, but gets the 6-pt volume baseline (structural support counts) instead of 0. Partially offsets the regime penalty. Pullback is designed to survive in SELECTIVE.
- **BASE:** Low volume component in DRY mode (vol dry-up means vol_ratio < 1.0 → 0 pts from volume). Quality component (5 pts max) is the only place quality_score (0–100) contributes. BASE is the lowest-scoring pattern type by design, which matches its low trade count in optimization.
- **HTF:** If the setup has a large vol_surge (common for high-tight-flag patterns), it gets full 20 vol pts. High RS by definition (stock ran 80%+). HTF likely scores highest of all patterns on average — consistent with E=+0.408R in backtests.

### Is the ranking system cross-engine fair?

**Mostly, with one structural gap.** The Quality component (5 pts) is the only setup-type-aware part of the scoring:
- BASE uses `quality_score (0–100)` → maps linearly to 0–5 pts
- VCP/PB/BRK uses `rs_blue_dot + weekly_confirmed + atr_compressed` → binary bonuses

BASE's quality_score encodes pattern tightness, volume dry-up, RS vs SPY, and RS blue dot. These same factors also score separately in the Volume and RS Quality components. This means **BASE quality signals are double-counted** — once in quality_score, once in volume/RS quality. This slightly inflates BASE scores for high-quality formations.

---

## Architectural Evaluation

### System is already optimal — do not change

1. **Detection/targeting asymmetry.** KDE resistance is the correct concept for supply-zone targeting. The current design is sound.
2. **Regime gating.** BRK in AGGRESSIVE only, PB/VCP in SELECTIVE/AGGRESSIVE, BASE/HTF/LCE always. Validated by Optuna and real trading logic.
3. **E3 stop at 1.278×ATR.** Optuna-discovered value. Do not touch without a dedicated Optuna run.
4. **RS scoring dominance (50 of 100 pts).** Correct architecture. The highest-RS stocks are the right stocks to trade.
5. **Pullback volume baseline.** The 6/20 pts awarded for structural support contact (even without vol surge) is correctly intentional — pullbacks don't need a volume event, they need a support touch.

### Improvements likely to produce the largest gains

**High confidence:**

1. **Expand `tp_multiple` ceiling to [1.5, 6.0]** and re-run Optuna for 100+ trials. The current ceiling of 4.0 is a hard constraint on optimization. The live scanner TARGET_RR=2.785 may be meaningfully suboptimal. This single change could increase expectancy across all engines.

2. **ATR-relative pullback support proximity** (replacing fixed 3% with `max(3%, 1.2 × ATR%)`). Low implementation risk, improves detection quality on high-ATR leaders. The code change is ~4 lines in `_find_structural_support()` for layers 2 and 3.

3. **Add `base_stop_atr` to BacktestParams.** Currently hardcoded at 0.2×ATR. With 54-trade baseline and promising E=+0.282R, the BASE engine has real signal. Running Optuna over stop size for this engine will improve its contribution. Range suggestion: [0.1, 0.8].

**Medium confidence:**

4. **Remove E2 PATH B (VCP confirmed breakout).** Keep only E2 PATH A (DRY/coiling) and the near-breakout/watchlist path. Let E6 own all breakout detection. This eliminates the PATH B / E6 overlap, simplifies optimization, and consolidates breakout parameters into one engine.

5. **Raise R:R scoring cap from 3.0× to 5.0×.** Optuna is pushing tp_multiple toward 4–6×. If real R:R is 4–5×, the scoring should distinguish it from 3×. Higher cap more faithfully rewards high-R:R setups in the ranking.

6. **Add `brk_regime_factor` to BacktestParams** (already in Optuna v5 recommendation §6c). `RES_SELECTIVE_REGIME_FACTOR=0.80` is a hardcoded 20% penalty in SELECTIVE regime that Optuna cannot see. Making it tunable is consistent with the overall parameter strategy.

### Structural weaknesses not mentioned in the review request

**A. Scored-mode parameter mismatch between live scanner and backtest**

`_LIVE_PARAMS = BacktestParams()` uses the dataclass defaults, which are Optuna v4 values. The v5 study found `cci_threshold = −54`, `ema_distance = 1.48`, `pullback_weight = 2.52`. These are partially wired in but the analysis flags that `score_threshold` and `rs_threshold` are not converged (CV=0.326 and 0.476). The live scanner is operating with parameters that are not final. Until the study completes 350+ trials, treat live results as "Optuna v4 + partial v5 updates."

**B. BASE double-counting in scoring**

BASE's `quality_score` encodes volume dry-up and RS signals that are also captured in the Volume and RS Quality scoring components. The same dry-up signal contributes to `quality_score` (→ 5 pts) and to `vol_dry_pct` scoring (→ 0 vol pts from the scoring because vol < 1× triggers 0 in `_vol_component`). Actually these partially cancel — base dry-up correctly yields 0 volume points in `_vol_component` while the quality_score component captures it. The system is mostly self-consistent. Minor issue, not urgent.

**C. The BRK Optuna problem is structural, not just sample-size**

The Optuna v5 analysis notes BRK produced 0 trades in the best trial because `pullback_weight=2.52` crowds out breakout signals. This is a deeper problem: the current scored-mode architecture cannot simultaneously optimize pullback and breakout engines. The `score_threshold` acts on both, and `pullback_weight` is only a pullback multiplier. There is no `breakout_weight` equivalent that can be tuned independently without changing how the objective function works. A dedicated breakout Optuna phase (freezing pullback params, searching only `brk_*` params) is the correct fix — but requires the full 1572-ticker cache first.

**D. The 1-year data window `DATA_FETCH_PERIOD = "1y"` limits BASE detection**

The Cup & Handle engine uses a 120-bar lookback (roughly 6 months). The 1-year data window gives 252 bars. This is adequate. However, the Stage 2 requirement in Flat Base needs `SMA200` — which requires 200+ bars. A 252-bar window with data quality issues (gaps, earnings, etc.) may leave less than 200 clean bars. Base setups on stocks with slightly less than 1 year of clean data will be silently rejected. This is a real but low-priority issue.
