# Optuna Backtest Scoring — Design Doc 2026-03-11

## Overview

Prepare the backtest engine for Optuna optimization by converting the pullback engine to a score-based system (backtest-only), adding a tunable RS filter, applying signal-type weights, and emitting diagnostics before each Optuna trial. The live scanner is completely unaffected.

---

## Decisions

| Question | Decision |
|---|---|
| RS metric | Option A — O'Neil `rs_score` (relative return vs SPY); no cross-sectional ranking |
| Scope | Backtest-only (scored mode); live scanner strict/relaxed logic untouched |
| Architecture | Approach B — `BacktestParams` dataclass + new `scan_pullback_scored()` in engine3.py |
| Legacy compatibility | `params=None` → identical to today's behavior |

---

## 1. `BacktestParams` dataclass (`backend/backtest_engine.py`)

New dataclass at top of file. Default values match V4 Optuna best so legacy callers are unaffected.

```python
@dataclass
class BacktestParams:
    # RS filter
    rs_threshold:    float = -0.01219  # O'Neil RS floor (Optuna: -0.05 → +0.10)

    # Pullback scoring
    cci_threshold:   float = -20.0     # relaxed CCI floor (Optuna: -150 → -10)
    ema_distance:    float = 0.04      # value-zone proximity pct (Optuna: 0.01 → 0.08)
    score_threshold: float = 5.0       # min score to open any trade (Optuna: 2 → 9)

    # Signal-type weights
    breakout_weight: float = 1.0       # VCP / RES_BREAKOUT (Optuna: 0.5 → 3.0)
    pullback_weight: float = 1.0       # PULLBACK (Optuna: 0.5 → 3.0)
    tdl_bonus:       float = 1.0       # ascending TDL support (Optuna: 0.0 → 2.0)
```

`BacktestEngine.__init__` gains: `params: Optional[BacktestParams] = None`

---

## 2. RS gate in replay loop (`BacktestEngine.run()`)

In scored mode only, inserted after liquidity gate, before `_detect_signals`:

```python
if self.params is not None:
    rs_t = precomputed_rs["rs_score"]
    if rs_t < self.params.rs_threshold:
        continue
```

In legacy mode (params=None), engine3's internal `RS_REJECT_THRESHOLD` check remains unchanged.

---

## 3. `scan_pullback_scored()` (`backend/engines/engine3.py`)

New function appended after `scan_relaxed_pullback`. Existing functions untouched.

**Signature:**
```python
def scan_pullback_scored(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    params,                        # BacktestParams
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
) -> tuple:                        # (setup_dict | None, score: float)
```

**Scoring table:**

| Condition | Points |
|---|---|
| 8 EMA > 20 EMA AND close > SMA50 | +2 |
| 8 EMA > 20 EMA AND close > SMA50×0.97 | +1 |
| Low penetrates EMA8 or EMA20 | +2 |
| Close within `params.ema_distance` of EMA8 or EMA20 | +1 |
| CCI_prev < −100 (deep oversold) | +2 |
| CCI_prev < `params.cci_threshold` AND CCI turning up | +1 |
| Structural support found (any source) | +2 |
| Support source == `"ASCENDING_TDL"` | +`params.tdl_bonus` |

**Hard gates (return `(None, 0.0)`):**
- Indicators NaN / insufficient bars (`_prepare_indicators` returns None)
- Trend score == 0 (neither trend condition met)
- No structural support found
- Risk math invalid (risk ≤ 0 or > 15% of entry)

**Setup dict:** identical shape to `scan_pullback()`, plus:
```python
"pullback_score":  score,   # raw score before weight applied
"is_scored_mode":  True,
```

---

## 4. Signal routing + trade gate (`BacktestEngine.run()`)

**Signal routing:** `_detect_signals` gains an optional `params` argument. For `PULLBACK` in scored mode, calls `scan_pullback_scored()` instead of strict/relaxed:

```python
if stype == "PULLBACK" and params is not None:
    setup, score = scan_pullback_scored(ticker, df_slice, sr_zones, params, ...)
    if setup is not None:
        setup["_raw_score"] = score
        return setup
```

All other engines fire unchanged. Base scores for non-pullback signals:

```python
SIGNAL_BASE_SCORES = {
    "VCP":          6.0,
    "RES_BREAKOUT": 6.0,
    "BASE":         5.0,
    "HTF":          5.0,
    "LCE":          4.0,
}
```

**Post-signal weight + threshold gate:**

```python
if self.params is not None:
    raw_score  = signal.get("_raw_score", SIGNAL_BASE_SCORES.get(setup_type, 5.0))
    is_breakout = setup_type in ("VCP", "RES_BREAKOUT", "HTF", "LCE")
    weight     = self.params.breakout_weight if is_breakout else self.params.pullback_weight
    final_score = raw_score * weight
    if final_score < self.params.score_threshold:
        continue
    signal["_final_score"] = final_score
```

---

## 5. `TradeRecord` update

New optional field:
```python
final_score: Optional[float] = None   # None in legacy mode
```

Populated from trade state dict in `__post_init__`. Included in `to_dict()`.

---

## 6. Diagnostics (`backend/analytics.py`)

New function `print_backtest_diagnostics(trades: List[dict])`. Called by `run_backtest_universe` after `asyncio.gather`, before returning results. Output via `logger.info`.

```
════════════════════════════════════════
 BACKTEST DIAGNOSTICS
════════════════════════════════════════
 Total trades        :   2,341
 Win rate            :   54.2%
 Expectancy (avg R)  :  +0.38 R
 Profit factor       :   1.61

 Signal type breakdown:
   VCP               :   812  (34.7%)  win 58.1%  avg R +0.51
   PULLBACK          :   703  (30.0%)  win 51.2%  avg R +0.29
   RES_BREAKOUT      :   489  (20.9%)  win 53.8%  avg R +0.41
   BASE              :   201   (8.6%)  win 49.8%  avg R +0.22
   HTF               :    89   (3.8%)  win 61.8%  avg R +0.72
   LCE               :    47   (2.0%)  win 46.8%  avg R +0.18

 Score distribution (scored mode only):
   avg final score   :   6.3
   min / max score   :   3.0 / 12.4
════════════════════════════════════════
```

Score section omitted when all `final_score` values are `None` (legacy mode).

---

## 7. Files Changed

| File | Change |
|---|---|
| `backend/backtest_engine.py` | `BacktestParams` dataclass; `BacktestEngine` accepts `params`; RS gate in replay loop; signal routing + score gate; `TradeRecord.final_score` field |
| `backend/engines/engine3.py` | New `scan_pullback_scored()` appended (existing functions untouched) |
| `backend/analytics.py` | New `print_backtest_diagnostics()` function |

## 8. Files NOT Changed

- `backend/main.py` — live scanner untouched
- `backend/engines/engine3.py` — `scan_pullback()` and `scan_relaxed_pullback()` untouched
- All other engines — untouched
- Frontend — untouched
- Database — untouched
