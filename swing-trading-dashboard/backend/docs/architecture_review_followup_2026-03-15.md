# Architecture Review — Follow-up Q&A — 2026-03-15

Confirmation of audit conclusions and implementation guidance.
References: `architecture_review_2026-03-15.md`, `engine_audit_2026-03-15.md`

---

## 1. Target Logic — Confirmed

Interpretation is accurate.

**Important implementation constraint:** Do not update `TARGET_RR` in the live scanner until Optuna confirms the new optimum after ceiling expansion. The correct sequence is:

1. Expand `tp_multiple` range to [1.5, 6.0] in `optimize_v5.py`
2. Run 100+ additional trials
3. Only after the value converges (CV < 0.10) — update `TARGET_RR` in `constants.py`

The current study's value of 3.999 is ceiling-bounded, not converged. The live scanner stays at `TARGET_RR = 2.785` until the new run proves otherwise.

---

## 2. Detection / Targeting Asymmetry — Confirmed

Correct reasoning. No change needed to targeting logic.

---

## 3. VCP Path B Removal

### Does removing Path B affect ranking signals?

No. `compute_setup_score()` in `scoring.py` has no `setup_type`-specific weighting. A `VCP` setup and a `RES_BREAKOUT` setup run through the exact same 7 scoring components. After Path B removal, a breakout event that E2 previously labeled `VCP/BRK` becomes an E6 `RES_BREAKOUT` instead. The score it receives is identical.

### Does VCP still contribute value after Path B removal?

Yes — through two paths that remain:

- **Path A (DRY):** Price coiling within 5% below a KDE resistance zone with MTR contraction + U-shape + volume dry-up. This is unique — no other engine detects pre-breakout coiling.
- **Near-breakout / Watchlist:** `scan_near_breakout()` produces WATCHLIST entries for stocks pressing against resistance. These bypass the 70-point score gate and surface in the watchlist panel.

After Path B removal, VCP's role becomes purely what it should be: a **compression and coil detector**, not a breakout detector. E6 owns breakouts. This is a cleaner architectural separation.

---

## 4. Base Engine Stop — Confirmed

Adding `base_stop_atr` to BacktestParams is the correct next step.

Implementation template:

```python
# In BacktestParams dataclass:
base_stop_atr: float = 0.2   # default preserves current behavior
```

```python
# In engine5.py scan_flat_base and scan_cup_handle:
_stop_atr = getattr(params, "base_stop_atr", 0.2) if params else 0.2
stop_loss = round(floor_v - _stop_atr * latr, 2)
```

The default of 0.2 means no behavioral change until Optuna tunes it. Adding the parameter is safe — it unlocks optimization without changing anything in production.

---

## 5. ATR-Relative Proximity

### Does it preserve behavior on low-ATR stocks?

Yes. The floor of 3% applies exactly as today. If ATR% = 1.5%, `max(3%, 1.2 × 1.5%) = max(3%, 1.8%) = 3%`. Behavior is identical to current.

### Does it improve detection on high-ATR leaders?

Yes, meaningfully:

- NVDA (~4% ATR): `max(3%, 1.2 × 4%) = 4.8%`. A consolidation low 4% below today's low — previously rejected — now qualifies. This is correct; for NVDA, 4% is within normal noise range.
- TSLA (~5% ATR): `max(3%, 6%) = 6%`. A support level 5.5% below qualifies. Appropriate — TSLA pullbacks to real support can span 5%+ intraday.

**Risk note:** On high-ATR stocks with weak RS (volatility from weakness, not strength), the looser proximity could match spurious "support." However, the other gates — CCI hook, EMA value zone, trend filter, RS gate — still all have to pass. A weak, volatile stock never reaches the proximity check. The change is safe.

---

## 6. Ranking System — The Remaining 50 Points

Full score breakdown (raw max = 120, capped at 100):

| Component | Max pts | Who benefits |
|---|---|---|
| RS Rank | 30 | All setups equally — highest RS percentile wins |
| RS Quality | 20 | rs_vs_spy, rs_improving, rs_near_high, rs_acceleration, tight_range_5d |
| R:R | 20 | Capped at R:R = 3.0×. All engines equal above that. |
| Volume | 20 | Full for vol_ratio ≥ 2.0. PB gets 6/20 baseline for structural support contact. |
| Regime | 15 | AGGRESSIVE=15, SELECTIVE≈8 (53%), DEFENSIVE=0 |
| Sector | 10 | Top-5 sectors=10, rank 6–8=8, outside top 8=4 |
| Quality | 5 | BASE maps quality_score (0–100) linearly. Others: binary bonuses. |

The remaining 50 points beyond RS = R:R (20) + Volume (20) + Regime (15) + Sector (10) + Quality (5) = 70 raw, partially offset by the 100-point cap.

### Do some engines naturally score higher?

Yes — structurally:

- **HTF in AGGRESSIVE** is likely the highest-scoring setup on average. It requires ≥80% runup (very high RS by definition), produces large volume surges (full 20 vol pts), gets full regime (15 pts), and high RS quality follows from the prior runup. Consistent with E=+0.408R in backtests.
- **BRK in AGGRESSIVE** gets full vol (≥2× required to fire) + full regime = 35 pts from those two components. Competitive but not structurally dominant — RS rank depends on the specific ticker.
- **PB in SELECTIVE** gets ~8 regime + 6 volume baseline = 14 pts from those two. Survives in the scanner via RS components.
- **BASE (DRY signal)** gets 0 volume pts (dry-up means vol_ratio < 1× = 0) + up to 5 quality pts. Lowest structural scoring. Appears only when RS rank and RS quality are high enough to compensate.

### Does the ranking normalize R:R differences between engines?

The R:R cap at 3.0× normalizes the artificial R:R inflation from tight BASE stops. A BASE setup with R:R = 10 (from a 0.2×ATR stop) scores identically on R:R to a PB with R:R = 3.0. This prevents the tight stop from gaming the score.

What the cap does not normalize is stop *reliability*. BASE's 35% win rate vs PB's ~50% means the identical R:R score overstates BASE quality. Adding `base_stop_atr` to Optuna would address this indirectly — a wider stop produces lower R:R, which lowers the score, which self-corrects the ranking.

---

## Implementation Order

### Implement immediately — no backtest needed, no Optuna risk

**1. ATR-relative pullback proximity**

File: `backend/engines/engine3.py` → `_find_structural_support()`, layers 2 and 3.

```python
# Current (layers 2 and 3):
if abs(ll - candidate) / candidate > 0.03:
    continue

# Replace with:
_prox_pct = max(0.03, 1.2 * latr / ll) if ll > 0 else 0.03
if abs(ll - candidate) / candidate > _prox_pct:
    continue
```

Behavior-preserving on low-ATR. No Optuna parameters touched. Cannot degrade existing edge.

**2. Remove E2 Path B**

File: `backend/engines/engine2.py` → `scan_vcp()`. Delete the BRK breakout-detection path, keep Path A (DRY/coiling) and the near-breakout watchlist path. No scoring change. No Optuna parameters touched.

**3. Add `base_stop_atr` to BacktestParams with default=0.2**

File: `backend/backtest_engine.py` → `BacktestParams` dataclass. Zero behavioral change until Optuna tunes it. Just unlocks the parameter for future optimization.

### Run Optuna first — then update live scanner

**4. Expand `tp_multiple` to [1.5, 6.0]**

In `optimize_v5.py`, change the `tp_multiple` search range. Run the study. Do NOT update `TARGET_RR` in `constants.py` until the new study converges at a stable value with CV < 0.10. The current `TARGET_RR = 2.785` stays frozen until then.

**5. Add `brk_regime_factor` to BacktestParams**

Same pattern as `base_stop_atr`: add with a default that preserves current behavior (`default=0.80`, matching the current `RES_SELECTIVE_REGIME_FACTOR` constant), then let Optuna tune it during the dedicated breakout optimization phase.

---

## What Could Invalidate Existing Optuna Edge

| Change | Risk | Verdict |
|---|---|---|
| Changing `TARGET_RR` without a new converged study | Directly shifts take-profit of every fallback target | **Do not do this** until new Optuna run converges |
| Widening base stop before Optuna confirms direction | 35% win rate could worsen if direction is wrong | Add the parameter, do not set a manual value |
| ATR-relative proximity change | Other gates (CCI, trend, RS, pin-bar) still apply | **Safe to deploy immediately** |
| Removing E2 Path B | E6 handles the same breakout events with better logic | **Safe to deploy immediately** |
| Adding `base_stop_atr` with default=0.2 | No behavioral change | **Safe to deploy immediately** |
