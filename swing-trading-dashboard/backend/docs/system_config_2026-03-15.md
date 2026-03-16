# System Configuration — 2026-03-15

## Optuna V5 Best Trial

| Field | Value |
|---|---|
| Trial number | #433 |
| Score | 2.0337 |
| Objective formula | expectancy × profit_factor × log(total_trades + 1) |
| Study name | v5_swing_optimizer |
| Study DB | data/optuna_v5.db |
| Training window | 2023-01-01 → 2024-12-31 |

---

## Full Parameter Table

| Parameter | Optimized value | Previous default | Source |
|---|---|---|---|
| tp_multiple | 4.3458 | 4.346 (pre-edit placeholder) | tuned |
| brk_vol_mult | 3.0161 | 3.016 (pre-edit placeholder) | tuned |
| brk_stop_atr | 1.6675 | 1.668 (pre-edit placeholder) | tuned |
| brk_min_pct | 0.04333 | 0.0433 (pre-edit placeholder) | tuned |
| brk_gap_pct | 0.01021 | 0.0102 (pre-edit placeholder) | tuned |
| brk_trail_mult | 6.9060 | 6.906 (pre-edit placeholder) | tuned |
| rs_threshold | 0.066 | 0.066 | frozen (V5 #286) |
| cci_threshold | -54.5 | -54.5 | frozen (V5 #286) |
| ema_distance | 1.651 | 1.651 | frozen (V5 #286) |
| score_threshold | 2.50 | 2.50 | frozen (not in search space) |
| breakout_weight | 1.724 | 1.724 | frozen (V5 #286) |
| pullback_weight | 1.842 | 1.842 | frozen (V5 #286) |
| tdl_bonus | 1.016 | 1.016 | frozen (V5 #286) |
| vcp_bonus | 1.370 | 1.370 | frozen (V5 #286) |
| cooldown_days | 4 | 4 | frozen (V5 #286) |
| TARGET_RR (constants.py) | 4.346 | 2.785 (Optuna v4 #951) | updated to match tp_multiple |
| brk_donchian_n | 87 | 87 | deferred (converged brk run 1, not re-tuned) |
| brk_pivot_strength | 2 | 2 | deferred |
| brk_atr_expansion | 1.474 | 1.474 | deferred |
| brk_min_consolidation | 10 | 10 | deferred |
| brk_regime_factor | 0.861 | 0.861 | deferred (unused: brk_aggressive_only=True) |
| base_stop_atr | 0.2 | 0.2 | deferred (not yet Optuna-tuned) |
| base_weight | 3.895 | 3.895 | deferred (base Optuna run #2) |
| base_trail_mult | 6.995 | 6.995 | deferred (base Optuna run #2) |
| base_vol_ratio | 1.425 | 1.425 | deferred (base Optuna run #2) |
| base_quality_min | 19 | 19 | deferred (base Optuna run #2) |

---

## Deferred Parameters

### base_stop_atr (BacktestParams field, current value: 0.2)
This field exists in `BacktestParams` with a comment marking it as "Optuna-tunable" but it has not yet been included in the V5 Optuna search space. The default of `0.2` is a placeholder from the initial BASE engine integration. It controls `stop = floor − base_stop_atr × ATR` for BASE breakout signals. A dedicated BASE optimizer pass is needed before this value is considered calibrated.

### brk_regime_factor (BacktestParams field, current value: 0.861)
This field applies a score multiplier to RES_BREAKOUT signals in SELECTIVE regime. However, it is currently inactive because `brk_aggressive_only=True`, which skips BRK entirely in non-AGGRESSIVE regimes rather than applying a partial discount. The value was converged in an earlier Optuna run but the `aggressive_only` flag overrides it based on OOS findings showing SELECTIVE-regime breakouts produce negative expectancy.

---

## Trading Rules Summary

### Entry Thresholds

| Gate | Value | Source |
|---|---|---|
| RS reject threshold (engine3 module) | -0.01219 | `RS_REJECT_THRESHOLD` in engine3.py (Optuna v4 #951) |
| RS threshold (BacktestParams / live scanner) | 0.066 | `BacktestParams.rs_threshold` (frozen V5 #286) |
| CCI strict floor (engine3 strict pullback) | -39.10 | `CCI_STRICT_FLOOR` in constants.py (Optuna v4 #951) |
| CCI relaxed floor (engine3 relaxed pullback) | -1.95 | `CCI_RLX_FLOOR` in constants.py (Optuna v4 #951) |
| CCI threshold (scored pullback gate) | -54.5 | `BacktestParams.cci_threshold` (frozen V5 #286) |
| Score gate (pullback scored mode) | 2.50 | `BacktestParams.score_threshold` (frozen) |
| Pullback weight multiplier | 1.842 | `BacktestParams.pullback_weight` (frozen V5 #286) |
| Min RS rank percentile | 70 | `RS_RANK_MIN_PERCENTILE` in constants.py |
| Min setup score (live scanner) | 70 | `MIN_SETUP_SCORE` in constants.py |
| Regime AGGRESSIVE threshold | 70 | `REGIME_AGGRESSIVE_THRESHOLD` in constants.py |
| Regime SELECTIVE threshold | 59 | `REGIME_SELECTIVE_THRESHOLD` in constants.py (Optuna v4 #951) |
| BRK regime gate | AGGRESSIVE only | `brk_aggressive_only=True` in BacktestParams |
| RES_BREAKOUT volume floor | 3.0161× 50d avg | `BacktestParams.brk_vol_mult` (tuned V5 #433) |
| RES_BREAKOUT min close above resistance | 4.333% | `BacktestParams.brk_min_pct` (tuned V5 #433) |
| RES_BREAKOUT max gap skip | 1.021% | `BacktestParams.brk_gap_pct` (tuned V5 #433) |

### Stop Logic

| Setup | Stop formula | Key constant |
|---|---|---|
| PULLBACK (strict & relaxed) | `min(low, zone_lower) − ATR_STOP_MULTIPLIER × ATR` | `ATR_STOP_MULTIPLIER = 1.278` (Optuna v4 #951) |
| PULLBACK (scored mode) | Same as strict | Same |
| RES_BREAKOUT | `resistance − brk_stop_atr × ATR14` | `brk_stop_atr = 1.6675` (tuned V5 #433) |
| BASE | `floor − base_stop_atr × ATR` | `base_stop_atr = 0.2` (deferred, untuned) |
| VCP / HTF / LCE | Engine-specific; not part of V5 tuning | — |

### Take Profit

- **Primary**: nearest upstream resistance zone above entry (via `nearest_resistance_target()`).
- **Fallback**: `entry + tp_multiple × risk`, where `tp_multiple = 4.3458` (tuned V5 #433).
- **TARGET_RR** in `constants.py` updated to `4.346` to stay aligned with `tp_multiple` (was 2.785 from v4 #951).

### Trailing Stops (per-setup ATR multipliers)

| Setup | Trail ATR mult | Source |
|---|---|---|
| VCP | 2.0 | `VCP_TRAIL_ATR_MULT` in constants.py |
| PULLBACK | 3.0 | `PULLBACK_TRAIL_ATR_MULT` in constants.py |
| RES_BREAKOUT | 6.9060 | `BacktestParams.brk_trail_mult` (tuned V5 #433) |
| BASE | 6.995 | `BacktestParams.base_trail_mult` (BASE Optuna run #2) |
| Fallback / generic | 4.162 | `TRAIL_ATR_MULT` in constants.py (Optuna v4 #951) |

### Scoring (live scanner unified score, 100-point scale)

| Component | Weight | Notes |
|---|---|---|
| RS rank percentile | 30 pts | Tier 1 (RS ≥ 85) gets 1.15× multiplier |
| Reward-to-Risk ratio | 20 pts | |
| Volume surge / momentum | 20 pts | |
| RS quality signals | 20 pts | improving, near-high, acceleration, tight range |
| Market regime alignment | 15 pts | SELECTIVE earns 53% of AGGRESSIVE pts |
| Sector alignment | 10 pts | Tier 1 (top 5 sectors) full; Tier 2 (6–8) 80%; out-of-top 40% |
| Pattern quality | 5 pts | Confirmation signals |
| **Gate** | **≥ 70** | `MIN_SETUP_SCORE` — setups below discarded |

### Regime Filters

- **AGGRESSIVE** (score 70–100): all engines enabled.
- **SELECTIVE** (score 59–69): engines 2 & 3 enabled, RES_BREAKOUT skipped (`brk_aggressive_only=True`).
- **DEFENSIVE** (score 0–39): engines 2 & 3 disabled.
- Regime score derived from: SPY EMA20/SMA50/SMA200 stack, EMA20 slope, breadth (% universe above SMA50), 52-week high/low ratio, VIX vs 20d SMA.

### Position Sizing (Risk Model)

| Parameter | Value | Source |
|---|---|---|
| Risk per trade | 1.0% of equity | `RISK_PER_TRADE_PCT` in constants.py |
| Max position size | 20.0% of equity | `MAX_POSITION_SIZE_PCT` in constants.py |
| Max open positions | 5 | `MAX_OPEN_POSITIONS` in constants.py |
| Position calculation | `position_size = RISK_PER_TRADE_PCT / stop_distance_pct`, capped at `MAX_POSITION_SIZE_PCT` | `TradeRecord.__post_init__` in backtest_engine.py |

---

## Parameter Drift: Optimizer vs Live Scanner

The live scanner uses `_LIVE_PARAMS = BacktestParams()` (main.py line 174), which instantiates the dataclass with its default values. After this update, `_LIVE_PARAMS` will pick up all V5 #433 values automatically — no separate live-scanner configuration file exists.

**Pre-existing drift identified:**

| Parameter | BacktestParams default (before this edit) | Engine3 module-level constant |
|---|---|---|
| RS reject threshold | `rs_threshold = 0.066` (BacktestParams) | `RS_REJECT_THRESHOLD = -0.01219` (engine3.py module level) |

These are two different thresholds with different semantics:
- `RS_REJECT_THRESHOLD = -0.01219` in engine3.py gates the strict and relaxed pullback scan functions (the hard RS quality floor — persistent underperformers rejected).
- `BacktestParams.rs_threshold = 0.066` gates the scored-mode pullback path and the live scanner's pre-engine RS check. It is also patched by Optuna during optimization.

The two coexist intentionally: the module-level constant serves legacy (non-scored) scan paths; the BacktestParams value serves the scored and backtest paths. No drift fix is required — the distinction is by design.

**No other drift found.** `TARGET_RR` in constants.py is now aligned with `BacktestParams.tp_multiple` at 4.346.
