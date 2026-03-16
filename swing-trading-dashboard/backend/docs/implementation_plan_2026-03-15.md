# Implementation Plan — Architecture Changes — 2026-03-15

Final confirmation of architectural decisions and ordered implementation plan.
References: `architecture_opinion_2026-03-15.md`, `architecture_review_followup_2026-03-15.md`

---

## Confirmed Architecture Decisions

### Engine Roles — Single Responsibility

Correct long-term architecture. One engine, one job:

| Engine | Role |
|---|---|
| E2 (VCP) | Compression / coil detector near resistance only |
| E3 (Pullback) | Value-zone pullbacks to structural support |
| E5 (Base) | Multi-week base formations (Flat Base, Cup & Handle) |
| E6 (Breakout) | Single authoritative volume-confirmed resistance breakout detector |
| E8 / E9 | HTF and Low Cheat Entry patterns |

The only violation of this principle in the current system is the overlap between E2 Path B and E6. After Path B removal the architecture is clean — no engine is doing another engine's job.

---

### Pullback Proximity — Edge Cases

The existing gates fully protect against low-quality setups. The only scenario where looser proximity could create a false positive requires a stock with high ATR, broken trend, weak RS, and no CCI hook — all of which are rejected by upstream gates before proximity is ever checked. No unprotected edge case exists.

---

### Base Stop and Scoring Interaction

Expected and desirable. The current situation is architecturally broken in a specific way: BASE setups show artificially high R:R from the 0.2×ATR stop, which inflates their score above what their actual 35% win rate deserves. After Optuna widens the stop, R:R drops, scores drop, fewer BASE setups clear the 70-point gate — and the ones that do appear are genuinely higher-conviction. Scanner surface shrinks, quality improves. Correct trade-off.

---

### tp_multiple and Parameter Interaction

Run `tp_multiple` search before freezing other parameters. The interaction is real and directional: a higher `tp_multiple` shifts which setups reach minimum R:R threshold, which interacts with `score_threshold`. Freezing `score_threshold` at its current unconverged value (CV=0.326) before optimizing `tp_multiple` means optimizing into a wrong constraint.

Correct freeze order:
1. Expand ceiling → resume study → let `tp_multiple` and `score_threshold` converge together
2. Freeze `tp_multiple` and `score_threshold`
3. Then freeze `pullback_weight` and `cci_threshold`

Do not freeze in reverse order.

---

### Breakout → Retest → Continuation

The synthetic zone injection approach is correct. E3's Layer 1 already handles KDE support zones — retest detection comes for free once the breakout level is in the zones list. No changes needed to E3's internal logic.

**Key architectural decision: use the DB's most recent E6 signal, not the current scan's result.**

Reason: A retest on day 1 post-breakout is rare and often signals a failing breakout. The high-quality retest is day 2–5. DB lookup enables cross-scan detection. The current scan's E6 result only enables same-scan detection, which is the less valuable case.

Implementation sketch:
```python
# In _process_ticker, after zones are computed, before E3 is called:
recent_brk = await get_recent_breakout(DB_PATH, ticker, days=5)
if recent_brk:
    synthetic_zone = {
        "level":  recent_brk["resistance_level"],
        "upper":  recent_brk["resistance_level"] * 1.005,
        "lower":  recent_brk["resistance_level"] * 0.995,
        "type":   "SUPPORT",
        "source": "BRK_RETEST",
    }
    zones = zones + [synthetic_zone]
# Pass enriched zones list to E3
```

This is a new feature. Requires backtest validation before production. Do not bundle with current changes.

---

### R:R Scoring Cap

Raising from 3.0× to 5.0× is correct. Current cap was calibrated to `TARGET_RR = 2.785`. With Optuna pushing `tp_multiple` toward 4–6, setups routinely produce R:R of 3.5–5.0 and the scoring cannot distinguish them from 3.0× setups. Raising the cap restores discriminating power.

Code change — one number in `scoring.py`:
```python
# Current:
rr_pts = min(float(SCORE_WEIGHT_RR), rr / 3.0 * SCORE_WEIGHT_RR)

# After:
rr_pts = min(float(SCORE_WEIGHT_RR), rr / 5.0 * SCORE_WEIGHT_RR)
```

---

## Implementation Order

### Phase 1 — Deploy now (safe, no Optuna interaction)

All four changes are independent and can be done in a single session.

**1. Remove E2 Path B**

File: `engines/engine2.py`
Action: Delete the BRK breakout-detection path from `scan_vcp()`. Keep Path A (DRY/coiling) and the near-breakout/watchlist path.
Risk: Zero.

**2. ATR-relative proximity in E3**

File: `engines/engine3.py` → `_find_structural_support()`, layers 2 and 3.

```python
# Replace in both Layer 2 (consolidation low) and Layer 3 (demand zone):

# Current:
if abs(ll - candidate) / candidate > 0.03:
    continue

# Replace with:
_prox_pct = max(0.03, 1.2 * latr / ll) if ll > 0 else 0.03
if abs(ll - candidate) / candidate > _prox_pct:
    continue
```

Risk: Minimal. Existing RS, trend, CCI, and pin-bar gates protect against false positives.

**3. Add `base_stop_atr` to BacktestParams and engine5**

Files: `backtest_engine.py` (add field), `engines/engine5.py` (use it).

```python
# backtest_engine.py — BacktestParams dataclass:
base_stop_atr: float = 0.2   # default preserves current behavior

# engines/engine5.py — scan_flat_base and scan_cup_handle:
_stop_atr = getattr(params, "base_stop_atr", 0.2) if params else 0.2
stop_loss = round(floor_v - _stop_atr * latr, 2)
```

Risk: Zero. No behavioral change until Optuna tunes it.

**4. Raise R:R scoring cap from 3.0× to 5.0×**

File: `scoring.py` → `compute_setup_score()`

```python
# Current:
rr_pts = min(float(SCORE_WEIGHT_RR), rr / 3.0 * SCORE_WEIGHT_RR)

# After:
rr_pts = min(float(SCORE_WEIGHT_RR), rr / 5.0 * SCORE_WEIGHT_RR)
```

Risk: Minimal. Only changes relative ranking of setups already above 3.0R.

---

### Phase 2 — Next Optuna run (before changing live params)

**5. Expand `tp_multiple` to [1.5, 6.0]**

File: `optimize_v5.py`
Action: Change search range for `tp_multiple`. Run 100+ trials. Let `tp_multiple` and `score_threshold` converge together.
Gate: Do not update `TARGET_RR` in `constants.py` until CV < 0.10.

**6. Add `brk_regime_factor` to BacktestParams**

File: `backtest_engine.py`
Action: Add field with `default=0.80` (matches current `RES_SELECTIVE_REGIME_FACTOR`). Wire into backtest engine. Tune in dedicated BRK Optuna phase after full universe cache is built.

---

### Phase 3 — Separate design phase (after current Optuna run completes)

**7. Breakout → retest → continuation**

Action: Design the DB-based zone injection in `_process_ticker`. Requires implementing `get_recent_breakout()` DB query, injecting synthetic SUPPORT zone into the zones list before E3 runs, and validating the resulting PULLBACK signals produce positive expectancy on held-out backtest data.

Do not bundle with Phase 1. This is a new feature, not a bug fix, and requires its own backtest validation cycle.

---

### Do Not Change

| Item | Reason |
|---|---|
| Targeting logic (KDE-dominant) | Correct. Pivot zones already included. Donchian should not be a target. |
| Detection / targeting asymmetry | Intentional. Detection needs many signals; targeting needs supply zones only. |
| Per-engine scoring weights | Type-agnostic scoring is the correct design. |
| E3 stop at 1.278×ATR | Optuna-discovered. Do not touch without a new dedicated run. |
| `TARGET_RR` in `constants.py` | Stays at 2.785 until new `tp_multiple` study converges. |
