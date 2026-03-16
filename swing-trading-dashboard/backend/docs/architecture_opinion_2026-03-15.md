# Architecture Opinion — Pre-Implementation Review — 2026-03-15

Architectural opinion on each proposed change before implementation.
References: `architecture_review_2026-03-15.md`, `architecture_review_followup_2026-03-15.md`

---

## 1. VCP — Path B Removal

**Verdict: Correct. Remove it.**

Right now two engines independently detect the same event (resistance breakout) using different logic and different resistance sources. That is redundant and creates ambiguity about which signal is authoritative.

After removal: E2 = compression detector. E6 = breakout detector. Each has one job.

**One real downside worth acknowledging:** E2 Path B uses a lower volume threshold (~1.5×) than E6 (≥2.0× required by Optuna). Some breakouts with 1.6–1.7× volume are caught by E2 today but would be dropped after removal because E6 rejects them. That is the correct behavior. E6's higher volume requirement is Optuna-validated. The "lost" signals are marginal-quality breakouts that backtesting showed are not worth taking.

**Should VCP score differently as a pure compression detector?**

No. The scoring system is intentionally setup-type agnostic, and that is the right design. A compressed VCP near a high-quality KDE resistance will naturally produce good R:R and show high RS — those attributes carry the score. Introducing type-specific scoring weights would create a new optimization surface that Optuna has not explored. Leave scoring unchanged.

---

## 2. Pullback Engine — ATR-Relative Proximity

**Verdict: Correct approach. Implement immediately.**

The existing fixed-3% rule uses a price-percentage measure to estimate what should be a volatility-relative concept. The relaxed pullback already does this correctly for EMA proximity (`abs(lc - l8) / latr ≤ 0.75`). Applying the same normalization to structural support proximity is internally consistent.

**False positive risk on weak volatile stocks:**

The existing gates already handle this before the proximity check is ever reached. To reach the structural support check, a stock must have already passed:
- RS score ≥ −0.012
- RS rank in top 30%
- EMA8 > EMA20 and close > SMA50×0.97 (trend intact)
- Low penetrating EMA8/20 (value zone entered)
- CCI turning from below floor

A weak stock with high ATR from weakness — not strength — will fail the RS gate or trend filter before proximity matters.

**Should RS be added inside the proximity logic?**

No. Keeping gates orthogonal is what makes the system debuggable. If RS is embedded into proximity you can never tell which condition rejected a setup. The existing gates are already sufficient.

---

## 3. Base Engine — base_stop_atr

**Verdict: Correct fix. Add the parameter now, let Optuna find the value.**

The 35% win rate combined with positive expectancy (+0.282R) is the signature of a system taking frequent small losses and occasional large wins — exactly what a 0.2×ATR stop produces geometrically. Whether that is optimal is an empirical question only Optuna can answer with enough trades.

**Would Optuna widen it?**

Almost certainly yes, but with a caveat. With only 54 trades in the full cache baseline, the optimization surface is noisy. Optuna may find a value around 0.4–0.6×ATR but with low confidence. The base stop needs the full universe cache (1572 tickers) before trusting the result.

**Side effect to watch:** A wider BASE stop reduces R:R directly (same target, bigger denominator). The scoring's R:R component would score those setups lower. Wider stop → lower R:R → lower score → fewer BASE setups passing the 70-point gate. After stop widening, fewer BASE setups may appear in the live scanner even if each one is individually higher quality. This is expected and correct behavior.

---

## 4. tp_multiple Ceiling Expansion

**Verdict: The proposed sequence is exactly correct. Do not shortcut it.**

The ceiling-bounded value of 3.999 is not a converged result — it is Optuna telling you the search space is too small. Updating `TARGET_RR` from a wall-bounded study would be acting on an artifact of the constraint, not the signal.

**Additional recommendation:** Run additional trials with `tp_multiple` unconstrained in [1.5, 6.0] **before** freezing other parameters. `tp_multiple` interacts with `score_threshold` (higher targets shift which setups reach threshold R:R) and with `pullback_weight`. These interactions mean the optimal `tp_multiple` is not independent of other params. Freezing `pullback_weight=2.52` and `cci_threshold=−54` first and then running `tp_multiple` in isolation will give a cleaner signal.

`TARGET_RR` in `constants.py` stays at 2.785 until a new study converges with CV < 0.10.

---

## 5. Pivot-Based Pullback — Breakout → Retest → Continuation

**Verdict: Genuine architectural gap. Worth implementing — but as a separate design phase, not bundled with current changes.**

The breakout → retest → continuation pattern (also called "first pullback" or "launchpad retest") is one of the most statistically reliable patterns in momentum trading. Entry on the retest of broken resistance provides a low-risk entry after breakout is confirmed. Your original design intent was correct.

**Is this currently captured?**

Partially — with a structural hole depending on the breakout source:

| Breakout source | Retest captured by E3? | Reason |
|---|---|---|
| KDE zone | Yes (usually) | After break, KDE zone flips from RESISTANCE to SUPPORT. Layer 1 catches retest. |
| Pivot high (E6) | Partially | Pivot zones stay in the list but may not reclassify correctly depending on timing. |
| Donchian high (E6 primary) | **No** | Donchian level is never written into the zones list. It exists only ephemerally during E6's detection loop. Retests are invisible to E3. |

The gap is real: Donchian-based breakouts — E6's most common source — leave no record that E3 can use for retest detection.

**Recommended implementation approach:**

Inject the most recent confirmed breakout level into the zones list in `_process_ticker` before passing to E3:

```python
# After E6 fires on this scan, or if a recent E6 signal exists for this ticker:
if res_brk:
    synthetic_retest_zone = {
        "level":  res_brk["resistance_level"],
        "upper":  res_brk["resistance_level"] * 1.005,
        "lower":  res_brk["resistance_level"] * 0.995,
        "type":   "SUPPORT",    # broken resistance = new support
        "source": "BRK_RETEST",
    }
    zones = zones + [synthetic_retest_zone]
    # Pass this enriched zones list to E3
```

This lets E3's existing Layer 1 catch the retest without any changes to `_find_structural_support()`. The resulting setup would be a PULLBACK signal at the breakout level — exactly the breakout → retest → continuation pattern.

**Why not implement now:** This is a new feature, not a bug fix. It requires:
1. Deciding whether to use the current scan's E6 result or the DB's most recent E6 signal (persisting state between scans)
2. Backtest validation before production

Do not bundle with the current change set.

---

## 6. Ranking System Bias

**Verdict: The apparent bias is not a bug. It is the system correctly reflecting what works in each regime.**

HTF scoring high is correct: a stock that ran 80%+ in 40 days has by definition the strongest RS in the universe. It should score highest. BRK scoring high in AGGRESSIVE is correct: confirmed volume breakouts in favorable markets are the highest-probability setups. BASE scoring low is correct: dry-volume consolidations offer lower win rates and need to earn their spot through RS quality, not by gaming volume or regime components.

**Should scoring weights be adjusted per setup type?**

No. Introducing per-engine weighting would create a new optimization surface with no backtest grounding. The current setup-type-agnostic scoring forces every engine to compete on universal quality metrics (RS strength, R:R, volume confirmation). That is the correct design. Manual preferences for certain engines over what the data would say is the wrong direction.

**One legitimate improvement independent of engine bias:**

Raise the R:R scoring cap from 3.0× to 5.0×. Currently R:R = 3.5 and R:R = 6.0 score identically on the R:R component. With Optuna pushing `tp_multiple` toward 4+, genuine 5× setups exist in the live scanner but cannot express that quality in the score. This change is small, type-agnostic, and aligns the scoring cap with where Optuna says targets should be. Implementation: one number change in `compute_setup_score()` — `rr / 3.0 * 20` → `rr / 5.0 * 20`.

---

## Implementation Plan

### Implement immediately — no Optuna dependency, no behavioral risk

| Change | File(s) | Risk |
|---|---|---|
| ATR-relative proximity in E3 | `engines/engine3.py` → `_find_structural_support()` layers 2 and 3 | Minimal. Existing gates protect against false positives. |
| Remove E2 Path B | `engines/engine2.py` → `scan_vcp()` | None. E6 handles those breakouts with better validated logic. |
| Add `base_stop_atr` to BacktestParams (default=0.2) | `backtest_engine.py`, `engines/engine5.py` | Zero. No behavioral change until Optuna tunes it. |
| Raise R:R cap from 3.0× to 5.0× | `scoring.py` → `compute_setup_score()` | Minimal. Only changes ranking of setups already above 3.0R. |

### Wait for Optuna data before changing live behavior

| Change | Do now | Wait for |
|---|---|---|
| `tp_multiple` ceiling to [1.5, 6.0] | Update search range in `optimize_v5.py` | Convergence (CV < 0.10), then update `TARGET_RR` in `constants.py` |
| `base_stop_atr` actual value | Add parameter with default=0.2 | Full 1572-ticker cache + dedicated Optuna run |
| `brk_regime_factor` | Add to BacktestParams (default=0.80) | Dedicated BRK Optuna phase after full cache is built |

### Separate design phase — do not bundle with current changes

| Change | Why separate |
|---|---|
| Breakout → retest → continuation | New feature. Requires cross-scan state design and backtest validation before production. |

### Do not change

| Item | Reason |
|---|---|
| Targeting logic (KDE-dominant) | Correct. Pivot zones already included. Donchian should not be a target. |
| Detection / targeting asymmetry | Intentional. Detection needs many signals; targeting needs supply zones only. |
| Per-engine scoring weights | Type-agnostic scoring is the correct design. |
| E3 stop at 1.278×ATR | Optuna-discovered. Do not touch without a new dedicated Optuna run. |
| `TARGET_RR` in constants.py | Stays at 2.785 until new `tp_multiple` study converges. |
