# Optuna Parameter Optimizer — Design

**Date:** 2026-03-08
**Status:** Approved

## Goal

Create a standalone script that uses Bayesian optimization (Optuna) to tune 6 trading system
parameters against a 2016–2025 walk-forward backtest on a representative 35-ticker basket.
Engine files (engine0–engine6) and scanning logic are not modified.

---

## Files

| File | Action |
|---|---|
| `scripts/optimize_parameters.py` | Create — main optimizer script |
| `scripts/representative_tickers.py` | Create — 35-ticker basket |
| `config/best_parameters.json` | Create (output) — best params after run |
| `optuna_study.db` | Created at runtime in project root |
| `backend/constants.py` | Modify — add `TRAIL_ATR_MULT = 1.5` |
| `backend/backtest_engine.py` | Modify — add `atr14` to bar dict; use `TRAIL_ATR_MULT` in `_manage_open_trade` |

---

## Section 1: Representative Ticker Basket (~35 tickers)

File: `scripts/representative_tickers.py`

```python
REPRESENTATIVE_TICKERS = [
    # Large-cap tech / mega-cap
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    # Momentum leaders
    "TSLA", "META", "CRWD", "PANW", "SNOW",
    # Mid-cap growth
    "DXCM", "CELH", "ENPH", "MELI", "SQ",
    # Cyclicals / industrials
    "CAT", "DE", "URI", "GWW", "PCAR",
    # Financials
    "JPM", "GS", "V", "MA", "PYPL",
    # Healthcare
    "UNH", "ISRG", "DXCM", "IDXX",
    # Energy / materials
    "XOM", "CVX", "FCX",
    # Consumer discretionary
    "HD", "NKE", "SBUX",
]
```

Duplicates removed at runtime; final count ~35 unique tickers.

---

## Section 2: Hyperparameter Search Space

| Parameter | Type | Range | Internal constant | Modules patched |
|---|---|---|---|---|
| `ATR_MULTIPLIER` | float | [0.5, 1.5] | `ATR_STOP_MULTIPLIER` | engine2, engine3, engine8_htf, engine9_low_cheat |
| `VCP_TIGHTNESS_RANGE` | float | [0.015, 0.05] | `VCP_TIGHT_RANGE_5D_PCT` | engine2, engine8_htf |
| `BREAKOUT_BUFFER_ATR` | float | [0.1, 0.5] | `RES_DECISIVE_ATR_FACTOR` | engine6 |
| `BREAKOUT_VOL_MULT` | float | [1.0, 2.0] | `VOL_SURGE_MULTIPLIER`, `_VOL_SURGE_THRESHOLD` | engine6, engine8_htf |
| `TARGET_RR` | float | [1.5, 3.5] | `TARGET_RR` | engine2, engine3, engine5, engine6, engine8_htf, zone_utils |
| `TRAIL_ATR_MULT` | float | [1.0, 3.0] | `TRAIL_ATR_MULT` | backtest_engine (new) |

---

## Section 3: TRAIL_ATR_MULT — New Constant + Backtest Integration

### constants.py change

```python
TRAIL_ATR_MULT = 1.5   # ATR multiplier for trailing stop (optimizable)
```

### backtest_engine.py — bar dict (in replay loop, ~line 604)

Add `atr14` to the bar dict that is already computed as `ticker_df["_ATR14"]`:

```python
atr14_T = float(ticker_df["_ATR14"].iloc[full_idx])
bar = {
    "date":  T_date.strftime("%Y-%m-%d"),
    "open":  ...,
    "high":  ...,
    "low":   ...,
    "close": ...,
    "ema20": ema20_T if not np.isnan(ema20_T) else open_trade["trailing_stop"],
    "atr14": atr14_T if not np.isnan(atr14_T) else 0.0,   # NEW
}
```

### backtest_engine.py — _manage_open_trade (trailing stop logic)

Replace EMA20-only ratchet with EMA20-or-ATR hybrid:

```python
# Before:
if close > entry and ema20 > stop:
    state["trailing_stop"] = ema20

# After:
if close > entry:
    import constants as _c
    atr14 = bar.get("atr14", 0.0)
    atr_trail = (close - _c.TRAIL_ATR_MULT * atr14) if atr14 > 0 else ema20
    new_trail = max(ema20, atr_trail)
    if new_trail > stop:
        state["trailing_stop"] = new_trail
```

The optimizer patches `constants.TRAIL_ATR_MULT` per trial. Using `import constants as _c`
(module-level reference, not `from constants import`) makes the patch visible at call time.
This is the only runtime import added to `_manage_open_trade`.

---

## Section 4: Constant Patching Context Manager

`sys.modules` patching overrides already-bound names in engine modules without touching files.
Modules are force-imported before patching to guarantee they exist in `sys.modules`.

```python
import importlib, sys
from contextlib import contextmanager

_MODULE_PATCHES = {
    "ATR_MULTIPLIER": [
        ("engines.engine2",          "ATR_STOP_MULTIPLIER"),
        ("engines.engine3",          "ATR_STOP_MULTIPLIER"),
        ("engines.engine8_htf",      "ATR_STOP_MULTIPLIER"),
        ("engines.engine9_low_cheat","ATR_STOP_MULTIPLIER"),
    ],
    "VCP_TIGHTNESS_RANGE": [
        ("engines.engine2",     "VCP_TIGHT_RANGE_5D_PCT"),
        ("engines.engine8_htf", "VCP_TIGHT_RANGE_5D_PCT"),
    ],
    "BREAKOUT_BUFFER_ATR": [
        ("engines.engine6", "RES_DECISIVE_ATR_FACTOR"),
    ],
    "BREAKOUT_VOL_MULT": [
        ("engines.engine6",     "VOL_SURGE_MULTIPLIER"),
        ("engines.engine6",     "_VOL_SURGE_THRESHOLD"),
        ("engines.engine8_htf", "VOL_SURGE_MULTIPLIER"),
    ],
    "TARGET_RR": [
        ("engines.engine2",     "TARGET_RR"),
        ("engines.engine3",     "TARGET_RR"),
        ("engines.engine5",     "TARGET_RR"),
        ("engines.engine6",     "TARGET_RR"),
        ("engines.engine8_htf", "TARGET_RR"),
        ("zone_utils",          "TARGET_RR"),
    ],
    "TRAIL_ATR_MULT": [
        ("constants", "TRAIL_ATR_MULT"),
    ],
}

def _preload_modules():
    for patches in _MODULE_PATCHES.values():
        for mod_name, _ in patches:
            importlib.import_module(mod_name)

@contextmanager
def _patch_constants(params: dict):
    saved = []
    for param_key, patches in _MODULE_PATCHES.items():
        val = params[param_key]
        for mod_name, attr in patches:
            mod = sys.modules[mod_name]
            saved.append((mod, attr, getattr(mod, attr, None)))
            setattr(mod, attr, val)
    try:
        yield
    finally:
        for mod, attr, orig in saved:
            if orig is None:
                pass
            else:
                setattr(mod, attr, orig)
```

---

## Section 5: Objective Function

```python
import asyncio, math
from wfo_engine import run_wfo
from representative_tickers import REPRESENTATIVE_TICKERS

WFO_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
WFO_IS_MONTHS   = 36
WFO_OOS_MONTHS  = 6
WFO_STEP_MONTHS = 6
WFO_START       = "2016-01-01"
WFO_END         = "2025-12-31"

def objective(trial: optuna.Trial) -> float:
    params = {
        "ATR_MULTIPLIER":      trial.suggest_float("ATR_MULTIPLIER",      0.5,  1.5),
        "VCP_TIGHTNESS_RANGE": trial.suggest_float("VCP_TIGHTNESS_RANGE", 0.015, 0.05),
        "BREAKOUT_BUFFER_ATR": trial.suggest_float("BREAKOUT_BUFFER_ATR", 0.1,  0.5),
        "BREAKOUT_VOL_MULT":   trial.suggest_float("BREAKOUT_VOL_MULT",   1.0,  2.0),
        "TARGET_RR":           trial.suggest_float("TARGET_RR",           1.5,  3.5),
        "TRAIL_ATR_MULT":      trial.suggest_float("TRAIL_ATR_MULT",      1.0,  3.0),
    }

    with _patch_constants(params):
        result = asyncio.run(run_wfo(
            tickers=REPRESENTATIVE_TICKERS,
            setup_types=WFO_SETUP_TYPES,
            is_months=WFO_IS_MONTHS,
            oos_months=WFO_OOS_MONTHS,
            step_months=WFO_STEP_MONTHS,
            run_id=f"optuna_trial_{trial.number}",
        ))

    # Aggregate OOS trades across all windows
    oos_trades = [t for w in result.windows for t in w.oos_trades]

    total_trades = len(oos_trades)
    if total_trades < 30:
        return -5.0

    wins   = [t for t in oos_trades if t["is_win"]]
    losses = [t for t in oos_trades if not t["is_win"]]

    win_rate   = len(wins) / total_trades
    loss_rate  = len(losses) / total_trades
    avg_win_r  = float(sum(t["rr_achieved"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss_r = float(sum(abs(t["rr_achieved"]) for t in losses) / len(losses)) if losses else 0.0
    expectancy = win_rate * avg_win_r - loss_rate * avg_loss_r

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss   = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    # Max drawdown from compound equity curve
    equity = 1.0; peak = 1.0; max_dd = 0.0
    for t in oos_trades:
        equity *= (1.0 + t["pnl_pct"] / 100.0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    if max_dd > 20.0:
        return -10.0

    # Pruning intermediate value (after first window)
    trial.report(expectancy, step=1)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return (expectancy * profit_factor * math.sqrt(total_trades)) / (1.0 + max_dd * 2.5)
```

---

## Section 6: Study Configuration & Progress Bar

```python
import optuna
from optuna.samplers import TPESampler
from optuna.pruners import MedianPruner
from tqdm import tqdm

def _tqdm_callback(study, trial):
    pbar.update(1)
    pbar.set_postfix({"best": round(study.best_value, 4)})

study = optuna.create_study(
    study_name="trading_optimizer",
    storage="sqlite:///optuna_study.db",
    direction="maximize",
    sampler=TPESampler(seed=42),
    pruner=MedianPruner(n_startup_trials=10, n_warmup_steps=2),
    load_if_exists=True,
)

n_trials = int(args.trials)   # CLI --trials N, default 200
with tqdm(total=n_trials, desc="Optimizing") as pbar:
    study.optimize(objective, n_trials=n_trials, callbacks=[_tqdm_callback])
```

---

## Section 7: Output

### Terminal summary (after optimization)

```
Best Parameters:
  ATR_MULTIPLIER:      0.72
  VCP_TIGHTNESS_RANGE: 0.031
  BREAKOUT_BUFFER_ATR: 0.24
  BREAKOUT_VOL_MULT:   1.38
  TARGET_RR:           2.61
  TRAIL_ATR_MULT:      1.84

Performance (OOS aggregate):
  Net Profit:          +34.2%
  Win Rate:            52.4%
  Expectancy:          0.31 R
  Profit Factor:       1.74
  Max Drawdown:        11.3%
  Total Trades:        287
```

### config/best_parameters.json

```json
{
  "generated_at": "2026-03-08T...",
  "study_name": "trading_optimizer",
  "best_trial": 47,
  "best_score": 2.341,
  "parameters": {
    "ATR_MULTIPLIER": 0.72,
    "VCP_TIGHTNESS_RANGE": 0.031,
    "BREAKOUT_BUFFER_ATR": 0.24,
    "BREAKOUT_VOL_MULT": 1.38,
    "TARGET_RR": 2.61,
    "TRAIL_ATR_MULT": 1.84
  },
  "oos_metrics": {
    "total_trades": 287,
    "win_rate": 52.4,
    "expectancy": 0.31,
    "profit_factor": 1.74,
    "max_drawdown_pct": 11.3,
    "net_profit_pct": 34.2
  }
}
```

---

## CLI Usage

```bash
cd swing-trading-dashboard/backend
python ../scripts/optimize_parameters.py --trials 200
python ../scripts/optimize_parameters.py --trials 50   # quick test
```

Resume interrupted run (study loads from SQLite automatically):
```bash
python ../scripts/optimize_parameters.py --trials 200
```

---

## Files Changed Summary

| File | Change |
|---|---|
| `backend/constants.py` | Add `TRAIL_ATR_MULT = 1.5` |
| `backend/backtest_engine.py` | Add `atr14` to bar dict; hybrid trailing stop using `TRAIL_ATR_MULT` |
| `scripts/optimize_parameters.py` | Create — full optimizer |
| `scripts/representative_tickers.py` | Create — 35-ticker basket |
| `config/best_parameters.json` | Created at runtime |

No engine files (engine0–engine6) modified. No scanning logic changed.
