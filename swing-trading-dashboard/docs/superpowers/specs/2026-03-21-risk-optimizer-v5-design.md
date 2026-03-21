# Risk Optimizer V5 — Design Spec
**Date:** 2026-03-21
**Status:** Approved
**Scope:** Risk management & trade execution parameter optimization only. Entry logic, setup detection, regime logic, and core filters are frozen.

---

## 1. Goal

Find robust, stable risk/execution parameters for the swing trading system using Walk-Forward Optimization + Optuna. Prefer a narrow, clustered optimum over a single peak value. Avoid overfitting at all costs.

**Parameters in scope:**
- Global trailing stop multiplier
- Position sizing (risk % and max position cap)
- Entry quality ATR thresholds (early/extended filter)

**Parameters frozen (not touched):**
- Entry logic, signal detection, engine parameters
- Market regime thresholds
- CCI floors, RS thresholds, volume multipliers

---

## 2. Changes to Existing Code

### 2a. `backend/backtest_engine.py` — Gap-Realistic Stop Fill

**One line change** in `_manage_open_trade()`:

```python
# BEFORE (optimistic — always fills at stop price)
if low <= stop:
    return True, stop, "STOP"

# AFTER (realistic — gap-down exits at open, not stop)
if low <= stop:
    exit_price = min(bar["open"], stop)
    return True, exit_price, "STOP"
```

This fix applies globally to all callers: live diagnostics endpoint, WFO engine, all validation scripts. `TradeRecord.portfolio_pnl_pct` already uses `exit_price` so position-sizing math flows through correctly.

---

## 3. New Files

```
scripts/
  optimize_risk_v5.py           ← new optimizer script
  representative_tickers_v2.py  ← expanded ~80-ticker universe

config/
  best_parameters_risk_v5_phase1.json   ← Phase 1 output (auto-written)
  best_parameters_risk_v5_phase2.json   ← Phase 2 output (auto-written)
```

---

## 4. Expanded Ticker Universe (`representative_tickers_v2.py`)

~80 tickers. Keeps all 35 from v1, adds:
- Mid-cap growth: SMCI, DUOL, APP, AXON, MNDY
- Small/mid momentum: CAVA, HIMS, NTRA, RKT
- Cyclicals/energy: SLB, MPC, FANG, NUE
- Healthcare: PODD, RVMD, ALNY
- Financials: COIN, HOOD, IBKR

Rationale: covers more of the actual 425-ticker universe behavior while keeping per-trial runtime manageable for 300+ trials.

---

## 5. Parameter Space

| Parameter | Type | Range | What it patches |
|-----------|------|--------|----------------|
| `trail_mult` | float | [2.0, 8.5] | All trail constants (see note below) |
| `risk_per_trade` | float | [0.5, 1.5] | `constants.RISK_PER_TRADE_PCT` + `backtest_engine.RISK_PER_TRADE_PCT` |
| `max_position_pct` | float | [10.0, 30.0] | `constants.MAX_POSITION_SIZE_PCT` + `backtest_engine.MAX_POSITION_SIZE_PCT` |
| `atr_entry_early` | float | [0.03, 0.20] | Post-WFO filter only (no module patch needed) |
| `atr_entry_extended` | float | [0.30, 0.90] | Post-WFO filter only (no module patch needed) |

### Patching notes

**`risk_per_trade` and `max_position_pct`:** Both constants are imported by value (`from constants import RISK_PER_TRADE_PCT`) in `backtest_engine.py`. Patching only the `constants` module leaves the already-bound local name in `backtest_engine` unchanged. The patch map must therefore include both the `constants` module entry AND the `backtest_engine` module entry for each constant:
```python
"risk_per_trade": [
    ("constants",       "RISK_PER_TRADE_PCT"),
    ("backtest_engine", "RISK_PER_TRADE_PCT"),
],
"max_position_pct": [
    ("constants",       "MAX_POSITION_SIZE_PCT"),
    ("backtest_engine", "MAX_POSITION_SIZE_PCT"),
],
```

**`trail_mult`:** `_TRAIL_ATR_BY_SETUP` in `backtest_engine.py` uses lambdas that call `_constants.VCP_TRAIL_ATR_MULT` etc. at call-time (not at import-time). Patching the `constants` module is therefore sufficient — the lambdas will see the updated value when invoked. HTF is not in `_TRAIL_ATR_BY_SETUP` and falls through to the `_constants.TRAIL_ATR_MULT` fallback, which is also patched. All setup types including HTF use the single global value consistently.

The full patch list for `trail_mult`:
```python
"trail_mult": [
    ("constants", "TRAIL_ATR_MULT"),
    ("constants", "VCP_TRAIL_ATR_MULT"),
    ("constants", "PULLBACK_TRAIL_ATR_MULT"),
    ("constants", "RES_BREAKOUT_TRAIL_ATR_MULT"),
    ("constants", "BASE_TRAIL_ATR_MULT"),
],
```

**`atr_entry_early` / `atr_entry_extended`:** These thresholds are not consumed by `backtest_engine.py` — entry quality is a post-hoc classification, not a gate inside the engine. The filter is applied in the optimizer's objective function after WFO returns the flat trade list, using the same logic as the validation script's `_entry_quality()`:
```python
def _entry_quality(trade: dict, early_thresh: float, extended_thresh: float) -> str:
    meta      = trade.get("setup_meta", {})
    atr       = meta.get("atr", 0)
    sig_entry = meta.get("entry", None)
    fill      = trade.get("entry_price")
    if not atr or atr <= 0 or sig_entry is None or fill is None:
        return "UNKNOWN"
    dist = (fill - sig_entry) / atr
    if dist < early_thresh:
        return "EARLY"
    elif dist < extended_thresh:
        return "OPTIMAL"
    return "EXTENDED"
```
Trades classified as `EXTENDED` or `UNKNOWN` are dropped before metric computation. No module patching required.

**Constraint:** `atr_entry_early < atr_entry_extended` enforced at trial start. If violated, `raise optuna.TrialPruned()` immediately.

---

## 6. WFO Configuration

Same structure as v4 optimizer (directly comparable):

| Setting | Value |
|---------|-------|
| IS window | 36 months |
| OOS window | 6 months |
| Step | 6 months |
| Date range | 2020-01-01 → 2024-12-31 |
| OOS windows | 4 |
| Setup types | VCP, PULLBACK, BASE, RES_BREAKOUT, HTF |
| Tickers | `["SPY"] + REPRESENTATIVE_TICKERS_V2` (~81 total) |

---

## 7. Objective Function

The WFO engine already applies `_apply_portfolio_cap` internally before returning `WFOWindow.oos_trades`. Do NOT apply a second cap in the objective — this would double-remove trades. Use the trades as returned by WFO directly.

```python
def _compute_score(oos_trades: list, oos_windows: list, atr_early: float, atr_extended: float) -> float:

    # Apply entry quality filter
    filtered = [t for t in oos_trades
                if _entry_quality(t, atr_early, atr_extended) in ("EARLY", "OPTIMAL")]
    n_trades = len(filtered)

    # Early exit: n_trades check ONLY — all other metrics require computed values
    if n_trades < 200:
        return -10.0

    # Compute all metrics from filtered trades BEFORE any further hard rejections
    wins   = [t for t in filtered if t["is_win"]]
    losses = [t for t in filtered if not t["is_win"]]

    win_rate  = len(wins) / n_trades
    loss_rate = len(losses) / n_trades
    avg_win_r  = sum(t["rr_achieved"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_r = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win_r - loss_rate * avg_loss_r
    avg_r      = float(np.mean([t["rr_achieved"] for t in filtered]))

    gross_profit = sum(t["portfolio_pnl_pct"] for t in wins)
    gross_loss   = abs(sum(t["portfolio_pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    sorted_t = sorted(filtered, key=lambda t: t["exit_date"])
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted_t:
        equity *= (1.0 + t["portfolio_pnl_pct"] / 100.0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    # Hard rejections — all computed from filtered trades above
    if expectancy <= 0:      return -8.0
    if profit_factor < 1.2:  return -5.0
    if max_dd > 50.0:        return -10.0

    # Soft low-trade penalty: ramps 0→2 as n_trades falls from 300 to 0
    trade_penalty = max(0.0, (300 - n_trades) / 300) * 2.0

    # dd_volatility: std of per-window max DD (in %, e.g. 8.0 = 8%)
    # Normalized by /10 to match scale of max_dd/10 term
    # Fallback: 0.0 if fewer than 2 windows have trades
    per_window_dd = [_window_max_dd(w, atr_early, atr_extended) for w in oos_windows]
    active = [d for d in per_window_dd if d is not None]
    dd_volatility_raw = float(np.std(active)) if len(active) >= 2 else 0.0

# _window_max_dd definition:
# Takes a WFOWindowResult w, applies the entry-quality filter to w.oos_trades (list of dicts),
# computes the peak-to-trough drawdown of the compound equity curve (sorted by exit_date).
# Returns None if filtered trade count == 0 (window excluded from dd_volatility calculation).
# Note: w.oos_trades contains serialized dicts (not TradeRecord objects) — use dict access.

    score = (
        0.35 * expectancy                    # primary: R-based edge
      + 0.25 * profit_factor                 # system profitability
      + 0.15 * avg_r                         # R per trade
      - 0.15 * (max_dd / 10.0)              # drawdown penalty (10% DD = -0.15)
      - 0.10 * (dd_volatility_raw / 10.0)   # stability penalty (10% std = -0.10)
      - trade_penalty
    )
    return score
```

### Metric definitions

| Metric | Definition | Typical range |
|--------|------------|---------------|
| `expectancy` | `win_rate × avg_win_R − loss_rate × avg_loss_R` | 0.05 – 0.50 |
| `profit_factor` | `sum(portfolio_pnl_pct for wins) / abs(sum(...for losses))` | 1.0 – 3.0 |
| `avg_r` | `mean(rr_achieved)` across filtered OOS trades | 0.1 – 1.5 |
| `max_dd` | Peak-to-trough of compound equity curve, sorted by `exit_date` (%) | 5 – 50% |
| `dd_volatility_raw` | `std` of per-window max DD across 4 OOS windows (%) | 0 – 15% |

Both `max_dd/10` and `dd_volatility_raw/10` are divided by 10 so they operate on the same 0–5 scale as `expectancy` and `avg_r`. This prevents the raw DD percentage from dominating the linear sum.

---

## 8. Per-Setup Logging (Diagnostic Only)

Not used in the objective score. Stored as trial user attributes and written to CSV for post-analysis — to decide after Phase 2 whether per-setup tuning is warranted.

For each setup type `{VCP, PULLBACK, BASE, RES_BREAKOUT, HTF}`:
```python
{
    "n": int,
    "win_rate": float,
    "expectancy": float,
    "profit_factor": float,
}
```

---

## 9. Output

### CSV log — `optuna_trial_log_risk_v5.csv`
One row per completed trial:
- `trial_number`, `score`, `trail_mult`, `risk_per_trade`, `max_position_pct`, `atr_entry_early`, `atr_entry_extended`
- `expectancy`, `profit_factor`, `avg_r`, `max_dd`, `dd_volatility`, `n_trades`
- Per-setup: `{setup}_expectancy`, `{setup}_pf`, `{setup}_winrate`, `{setup}_n` for each setup type

### Phase 1 JSON — `config/best_parameters_risk_v5_phase1.json`
```json
{
  "study": "trading_risk_v5_phase1",
  "top_30_trials": [...],
  "distribution": {
    "trail_mult":       {"mean": X, "std": X, "min": X, "max": X},
    "risk_per_trade":   {...},
    "max_position_pct": {...},
    "atr_entry_early":  {...},
    "atr_entry_extended": {...}
  },
  "stability": {
    "trail_mult":       {"narrow": bool, "std_pct_of_range": float},
    ...
  },
  "sensitivity": {
    "trail_mult_buckets": {
      "[2.0-3.5]":  {"n_trials": int, "avg_score": float},
      "[3.5-5.0]":  {"n_trials": int, "avg_score": float},
      "[5.0-6.5]":  {"n_trials": int, "avg_score": float},
      "[6.5-8.5]":  {"n_trials": int, "avg_score": float}
    }
  },
  "phase2_suggested_ranges": {
    "trail_mult":         [lo, hi],
    "risk_per_trade":     [lo, hi],
    "max_position_pct":   [lo, hi],
    "atr_entry_early":    [lo, hi],
    "atr_entry_extended": [lo, hi]
  }
}
```

**`phase2_suggested_ranges`** computed as `[best - 1.5×std, best + 1.5×std]` clipped to original bounds. Special case for the ATR threshold pair: after computing both ranges independently, if `atr_entry_early_hi >= atr_entry_extended_lo`, clamp `atr_entry_early_hi = atr_entry_extended_lo - 0.05` to preserve the required ordering constraint.

### Phase 2 JSON — `config/best_parameters_risk_v5_phase2.json`
Same structure as Phase 1, plus a `"recommended"` block:
```json
"recommended": {
    "trail_mult": X,
    "risk_per_trade": X,
    "max_position_pct": X,
    "atr_entry_early": X,
    "atr_entry_extended": X,
    "rationale": "Top trial by score; stable across N of 4 OOS windows."
}
```

---

## 10. CLI Usage

```bash
# Run from backend/ directory
cd swing-trading-dashboard/backend

# Phase 1 — wide exploration (300 trials recommended)
python ../scripts/optimize_risk_v5.py --phase 1 --trials 300

# Phase 2 — refined (200 trials), auto-reads phase1 JSON for ranges
python ../scripts/optimize_risk_v5.py --phase 2 --trials 200

# Smoke test (fast — 3 tickers, short IS/OOS windows)
python ../scripts/optimize_risk_v5.py --phase 1 --trials 5 --smoke
```

---

## 11. Study Isolation

Separate SQLite study names — v4 study is never touched:

| Study | Name |
|-------|------|
| v4 (existing) | `trading_optimizer_v4` |
| v5 Phase 1 | `trading_risk_v5_phase1` |
| v5 Phase 2 | `trading_risk_v5_phase2` |

All stored in the same `optuna_study.db` file.

---

## 12. Acceptance Criteria

- [ ] `backtest_engine.py` gap fix: stop-out with open below stop exits at `open`, not `stop`
- [ ] `RISK_PER_TRADE_PCT` and `MAX_POSITION_SIZE_PCT` patches applied to both `constants` and `backtest_engine` modules
- [ ] `trail_mult` patches all 5 trail constants; HTF falls through to `TRAIL_ATR_MULT` fallback (consistent single-global behavior)
- [ ] ATR entry quality filter uses `setup_meta.atr` + `setup_meta.entry` fields (same as validation script)
- [ ] `_apply_portfolio_cap` called once (inside WFO engine only) — not duplicated in objective
- [ ] `dd_volatility` normalized by /10 in score formula; falls back to 0.0 when <2 OOS windows have trades
- [ ] Phase 2 range auto-narrowing clamps `atr_entry_early` upper bound below `atr_entry_extended` lower bound
- [ ] `optimize_risk_v5.py --phase 1 --trials 5 --smoke` completes without errors
- [ ] CSV log written with correct columns after Phase 1
- [ ] Phase 1 JSON contains `top_30_trials`, `distribution`, `sensitivity`, `phase2_suggested_ranges`
- [ ] `--phase 2` reads Phase 1 JSON and narrows ranges correctly
- [ ] Phase 2 JSON contains `recommended` block
- [ ] v4 study in SQLite is unmodified after running v5
