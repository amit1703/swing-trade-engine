# Risk Optimizer V5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-phase Optuna optimizer focused exclusively on risk/execution parameters (trail mult, position sizing, entry quality thresholds) using WFO validation against an expanded ~80-ticker universe.

**Architecture:** Standalone script `scripts/optimize_risk_v5.py` with a context-manager patch system (same pattern as v4). A one-line gap-fix in `backtest_engine.py` makes stop fills realistic for all callers. Phase 1 does wide exploration; Phase 2 auto-narrows ranges from Phase 1 results.

**Tech Stack:** Python, Optuna (TPE sampler + MedianPruner), asyncio WFO engine, SQLite study storage, numpy, csv, json.

**Spec:** `docs/superpowers/specs/2026-03-21-risk-optimizer-v5-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/backtest_engine.py:410-411` | Gap-realistic stop fill (`min(open, stop)`) |
| Create | `scripts/representative_tickers_v2.py` | Expanded ~80-ticker universe |
| Create | `scripts/optimize_risk_v5.py` | Full optimizer: patches, helpers, objective, output, CLI |
| Auto-written | `config/best_parameters_risk_v5_phase1.json` | Phase 1 top-30 + distribution + sensitivity |
| Auto-written | `config/best_parameters_risk_v5_phase2.json` | Phase 2 top-30 + recommended block |
| Auto-written | `backend/optuna_trial_log_risk_v5.csv` | Per-trial CSV log (run from backend/) |

---

## Task 1: Gap-Realistic Stop Fill in `backtest_engine.py`

**Files:**
- Modify: `backend/backtest_engine.py:410-411`

- [ ] **Step 1: Locate the exact line**

Open `backend/backtest_engine.py`. Find `_manage_open_trade()`. The stop-check block is at approximately line 409:
```python
# 1. Stop hit first (low ≤ stop → filled at stop price)
if low <= stop:
    return True, stop, "STOP"
```

- [ ] **Step 2: Apply the fix**

Replace those two lines with:
```python
# 1. Stop hit first (low ≤ stop → filled at worst of open vs stop — gap-realistic)
if low <= stop:
    exit_price = min(bar["open"], stop)
    return True, exit_price, "STOP"
```

- [ ] **Step 3: Verify manually**

Confirm `bar["open"]` is always populated. Check `_manage_open_trade` signature — `bar` dict is constructed at line ~755 with key `"open"` explicitly set. ✓

- [ ] **Step 4: Smoke test the change**

Run from `backend/`:
```bash
cd swing-trading-dashboard/backend
python -c "
import asyncio
from backtest_engine import BacktestEngine
async def t():
    e = BacktestEngine('AAPL', '2024-01-01', '2024-06-30')
    s = await e.run()
    print('trades:', s.total_trades, 'ok')
asyncio.run(t())
"
```
Expected: prints trade count with no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/backtest_engine.py
git commit -m "fix: gap-realistic stop fill — exit at min(open, stop) not stop price"
```

---

## Task 2: Expanded Ticker Universe

**Files:**
- Create: `scripts/representative_tickers_v2.py`

- [ ] **Step 1: Create the file**

```python
# scripts/representative_tickers_v2.py
"""
Expanded representative ticker basket for v5 risk optimizer.

~80 tickers: all 35 from v1 plus mid/small-cap additions across sectors.
Raises AssertionError at import time if duplicates exist.
"""

_RAW = [
    # ── All 35 from v1 ────────────────────────────────────────────────────────
    # Large-cap tech / mega-cap
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    # Momentum / high-growth
    "TSLA", "META", "CRWD", "PANW", "SNOW",
    # Mid-cap growth
    "CELH", "ENPH", "MELI", "SQ", "DXCM",
    # Industrials / cyclicals
    "CAT", "DE", "URI", "GWW", "PCAR",
    # Financials
    "JPM", "GS", "V", "MA", "PYPL",
    # Healthcare
    "UNH", "ISRG", "IDXX", "VEEV",
    # Energy / materials
    "XOM", "CVX", "FCX",
    # Consumer discretionary
    "HD", "NKE", "SBUX",

    # ── v2 additions ──────────────────────────────────────────────────────────
    # Mid-cap growth / momentum
    "SMCI", "DUOL", "APP", "AXON", "MNDY",
    # Small/mid momentum
    "CAVA", "HIMS", "RKT", "NTRA",
    # Cyclicals / energy
    "SLB", "MPC", "FANG", "NUE",
    # Healthcare
    "PODD", "RVMD", "ALNY",
    # Financials
    "COIN", "HOOD", "IBKR",
    # Additional large-cap diversification
    "LLY", "ABBV", "NOW", "ADBE", "QCOM",
    "AMD", "MU", "AMAT", "LRCX",
    # Consumer / retail
    "COST", "TGT", "LULU",
    # Industrials add-ons
    "GNRC", "ENVA", "LFUS",
]

assert len(_RAW) == len(set(_RAW)), (
    f"Duplicate tickers in _RAW: "
    f"{[t for t in set(_RAW) if _RAW.count(t) > 1]}"
)

REPRESENTATIVE_TICKERS_V2: list[str] = list(_RAW)
```

- [ ] **Step 2: Verify no duplicates**

```bash
cd swing-trading-dashboard/backend
python -c "
import sys; sys.path.insert(0, '../scripts')
from representative_tickers_v2 import REPRESENTATIVE_TICKERS_V2
print('tickers:', len(REPRESENTATIVE_TICKERS_V2))
"
```
Expected: prints count ~80, no AssertionError.

- [ ] **Step 3: Commit**

```bash
git add scripts/representative_tickers_v2.py
git commit -m "feat: add representative_tickers_v2 — expanded ~80-ticker universe for v5 optimizer"
```

---

## Task 3: Core Infrastructure of `optimize_risk_v5.py`

Build the file skeleton: path setup, imports, module patch map, `_preload_modules`, `_patch_constants`.

**Files:**
- Create: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Write the file skeleton with patch infrastructure**

```python
# scripts/optimize_risk_v5.py
"""
Risk Optimizer V5 — Optuna optimization of risk/execution parameters only.

Optimizes: trail_mult, risk_per_trade, max_position_pct,
           atr_entry_early, atr_entry_extended

Entry logic, setup detection, regime logic, and core filters are FROZEN.

Usage (run from backend/ directory):
    python ../scripts/optimize_risk_v5.py --phase 1 --trials 300
    python ../scripts/optimize_risk_v5.py --phase 2 --trials 200
    python ../scripts/optimize_risk_v5.py --phase 1 --trials 5   # smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib
import json
import math
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

from wfo_engine import run_wfo
from representative_tickers_v2 import REPRESENTATIVE_TICKERS_V2

# ── WFO configuration ─────────────────────────────────────────────────────────
WFO_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF"]
WFO_IS_MONTHS   = 36
WFO_OOS_MONTHS  = 6
WFO_STEP_MONTHS = 6
# Note: run_wfo derives its date range from the price cache contents directly
# (data_start = max of all tickers' index.min(), data_end = min of index.max()).
# There is no start/end_date argument. The 2020-2024 range in the spec is met by
# the fact that the price cache was built over that period. Do NOT define dead
# WFO_START_DATE / WFO_END_DATE constants — they would give false date control.

# ── Study / output ────────────────────────────────────────────────────────────
_STUDY_DB         = str(_PROJECT_DIR / "optuna_study.db")
_STUDY_NAME_P1    = "trading_risk_v5_phase1"
_STUDY_NAME_P2    = "trading_risk_v5_phase2"
_OUTPUT_P1        = _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase1.json"
_OUTPUT_P2        = _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase2.json"
_CSV_LOG          = "optuna_trial_log_risk_v5.csv"    # written to cwd (backend/)
_DEFAULT_TRIALS_P1 = 300
_DEFAULT_TRIALS_P2 = 200

# ── Parameter bounds — Phase 1 (wide) ─────────────────────────────────────────
BOUNDS_P1: dict[str, tuple] = {
    "trail_mult":         (2.0,  8.5),
    "risk_per_trade":     (0.5,  1.5),
    "max_position_pct":   (10.0, 30.0),
    "atr_entry_early":    (0.03, 0.20),
    "atr_entry_extended": (0.30, 0.90),
}

# ── Module patch map ──────────────────────────────────────────────────────────
# trail_mult: patches all 5 trail constants via constants module only.
# _TRAIL_ATR_BY_SETUP uses lambdas that dereference _constants.* at call-time,
# so patching constants module is sufficient (no backtest_engine entry needed).
#
# risk_per_trade / max_position_pct: imported by value in backtest_engine.py
# via `from constants import`. Must patch BOTH modules or backtest_engine
# will silently use the original value.
_MODULE_PATCHES: dict[str, list[tuple[str, str]]] = {
    "trail_mult": [
        ("constants", "TRAIL_ATR_MULT"),
        ("constants", "VCP_TRAIL_ATR_MULT"),
        ("constants", "PULLBACK_TRAIL_ATR_MULT"),
        ("constants", "RES_BREAKOUT_TRAIL_ATR_MULT"),
        ("constants", "BASE_TRAIL_ATR_MULT"),
    ],
    "risk_per_trade": [
        ("constants",       "RISK_PER_TRADE_PCT"),
        ("backtest_engine", "RISK_PER_TRADE_PCT"),
    ],
    "max_position_pct": [
        ("constants",       "MAX_POSITION_SIZE_PCT"),
        ("backtest_engine", "MAX_POSITION_SIZE_PCT"),
    ],
    # atr_entry_early / atr_entry_extended: post-WFO filter, no module patch.
}


def _preload_modules() -> None:
    """Force-import all modules that will be patched so they exist in sys.modules."""
    for patches in _MODULE_PATCHES.values():
        for mod_name, _ in patches:
            importlib.import_module(mod_name)


@contextmanager
def _patch_constants(params: dict[str, Any]):
    """
    Temporarily override module-level constants for one Optuna trial.
    Restores originals in finally-block even if the trial raises.
    Thread-safe for serial Optuna trials (default).
    """
    _preload_modules()
    saved: list[tuple[Any, str, Any]] = []
    for param_key, patches in _MODULE_PATCHES.items():
        if param_key not in params:
            continue
        val = params[param_key]
        for mod_name, attr in patches:
            mod = sys.modules[mod_name]
            saved.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, val)
    try:
        yield
    finally:
        for mod, attr, orig in saved:
            setattr(mod, attr, orig)
```

- [ ] **Step 2: Verify imports resolve**

```bash
cd swing-trading-dashboard/backend
python -c "
import sys; sys.path.insert(0, '../scripts')
exec(open('../scripts/optimize_risk_v5.py').read().split('def _preload')[0])
print('imports ok, BOUNDS_P1:', list(BOUNDS_P1.keys()))
"
```
Expected: prints param names, no ImportError.

---

## Task 4: Helper Functions — `_entry_quality` and `_window_max_dd`

Add to `optimize_risk_v5.py` (append after Task 3 code).

**Files:**
- Modify: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Write `_entry_quality`**

```python
def _entry_quality(trade: dict, early_thresh: float, extended_thresh: float) -> str:
    """Classify a trade dict by entry quality relative to signal price.

    Returns "EARLY", "OPTIMAL", "EXTENDED", or "UNKNOWN".
    Uses setup_meta["atr"] and setup_meta["entry"] written by each engine.
    """
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

- [ ] **Step 2: Write `_window_max_dd`**

```python
def _window_max_dd(
    window,
    atr_early: float,
    atr_extended: float,
) -> Optional[float]:
    """Compute peak-to-trough max drawdown for a single WFO window's OOS trades.

    Applies entry-quality filter first.
    Returns None if no trades remain after filtering (window excluded from
    dd_volatility calculation — not treated as 0% DD).

    window.oos_trades is a List[dict] (serialized by wfo_engine).
    """
    filtered = [
        t for t in window.oos_trades
        if _entry_quality(t, atr_early, atr_extended) in ("EARLY", "OPTIMAL")
    ]
    if not filtered:
        return None
    sorted_t = sorted(filtered, key=lambda t: t["exit_date"])
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted_t:
        equity *= 1.0 + t["portfolio_pnl_pct"] / 100.0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return max_dd
```

- [ ] **Step 3: Create the tests directory**

```bash
mkdir -p swing-trading-dashboard/scripts/tests
touch swing-trading-dashboard/scripts/tests/__init__.py
```

- [ ] **Step 4: Write unit tests**

Create `scripts/tests/test_optimize_risk_v5_helpers.py`:

```python
"""Unit tests for optimize_risk_v5 helper functions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optimize_risk_v5 import _entry_quality, _window_max_dd


# ── _entry_quality ─────────────────────────────────────────────────────────────

def _make_trade(fill, sig_entry, atr):
    return {
        "entry_price": fill,
        "setup_meta": {"entry": sig_entry, "atr": atr},
        "is_win": True,
        "rr_achieved": 1.0,
        "portfolio_pnl_pct": 1.0,
        "exit_date": "2024-01-10",
    }


def test_entry_quality_early():
    t = _make_trade(fill=100.05, sig_entry=100.0, atr=1.0)   # dist=0.05 < 0.1
    assert _entry_quality(t, 0.1, 0.5) == "EARLY"


def test_entry_quality_optimal():
    t = _make_trade(fill=100.3, sig_entry=100.0, atr=1.0)    # dist=0.3, 0.1≤dist<0.5
    assert _entry_quality(t, 0.1, 0.5) == "OPTIMAL"


def test_entry_quality_extended():
    t = _make_trade(fill=100.6, sig_entry=100.0, atr=1.0)    # dist=0.6 ≥ 0.5
    assert _entry_quality(t, 0.1, 0.5) == "EXTENDED"


def test_entry_quality_unknown_no_atr():
    t = {"entry_price": 100.0, "setup_meta": {"entry": 100.0, "atr": 0}}
    assert _entry_quality(t, 0.1, 0.5) == "UNKNOWN"


def test_entry_quality_unknown_missing_meta():
    t = {"entry_price": 100.0, "setup_meta": {}}
    assert _entry_quality(t, 0.1, 0.5) == "UNKNOWN"


# ── _window_max_dd ─────────────────────────────────────────────────────────────

class _FakeWindow:
    def __init__(self, trades):
        self.oos_trades = trades


def test_window_max_dd_empty_returns_none():
    w = _FakeWindow([])
    assert _window_max_dd(w, 0.1, 0.5) is None


def test_window_max_dd_all_extended_returns_none():
    t = _make_trade(fill=100.6, sig_entry=100.0, atr=1.0)
    t["exit_date"] = "2024-01-10"
    w = _FakeWindow([t])
    assert _window_max_dd(w, 0.1, 0.5) is None


def test_window_max_dd_single_losing_trade():
    t = _make_trade(fill=100.05, sig_entry=100.0, atr=1.0)
    t["is_win"] = False
    t["portfolio_pnl_pct"] = -1.0
    t["exit_date"] = "2024-01-10"
    w = _FakeWindow([t])
    dd = _window_max_dd(w, 0.1, 0.5)
    assert dd is not None
    assert abs(dd - 0.99) < 0.01    # equity 1.0 → 0.99 → DD ≈ 0.99%


def test_window_max_dd_recovery_no_drawdown():
    trades = [
        {**_make_trade(100.05, 100.0, 1.0), "portfolio_pnl_pct": 2.0, "exit_date": "2024-01-10"},
        {**_make_trade(100.05, 100.0, 1.0), "portfolio_pnl_pct": 3.0, "exit_date": "2024-01-11"},
    ]
    w = _FakeWindow(trades)
    dd = _window_max_dd(w, 0.1, 0.5)
    assert dd == 0.0
```

- [ ] **Step 5: Run tests**

```bash
cd swing-trading-dashboard
python -m pytest scripts/tests/test_optimize_risk_v5_helpers.py -v
```
Expected: 9 tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add scripts/optimize_risk_v5.py scripts/tests/test_optimize_risk_v5_helpers.py scripts/tests/__init__.py
git commit -m "feat: add _entry_quality and _window_max_dd helpers with tests"
```

---

## Task 5: Objective Score Function `_compute_score`

Append to `optimize_risk_v5.py`.

**Files:**
- Modify: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Write `_compute_per_setup_stats`**

```python
_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF"]


def _compute_per_setup_stats(trades: list) -> dict:
    """Compute per-setup expectancy/PF/winrate for diagnostic logging.
    Not used in scoring — purely informational.
    """
    result = {}
    for stype in _SETUP_TYPES:
        subset = [t for t in trades if t.get("setup_type") == stype]
        n = len(subset)
        if n == 0:
            result[stype] = {"n": 0, "win_rate": 0.0, "expectancy": 0.0, "profit_factor": 0.0}
            continue
        wins   = [t for t in subset if t["is_win"]]
        losses = [t for t in subset if not t["is_win"]]
        wr  = len(wins) / n
        lr  = len(losses) / n
        awr = sum(t["rr_achieved"] for t in wins)   / len(wins)   if wins   else 0.0
        alr = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
        exp = wr * awr - lr * alr
        gp  = sum(t["portfolio_pnl_pct"] for t in wins)
        gl  = abs(sum(t["portfolio_pnl_pct"] for t in losses))
        pf  = gp / gl if gl > 0 else (gp if gp > 0 else 0.0)
        result[stype] = {
            "n":            n,
            "win_rate":     round(wr * 100, 2),
            "expectancy":   round(exp, 4),
            "profit_factor": round(min(pf, 9999.0), 4),
        }
    return result
```

- [ ] **Step 2: Write `_compute_score`**

> **Note — intentional deviations from spec signature:** The spec shows `_compute_score(oos_trades, oos_windows, ...)` returning `float`. This plan drops `oos_trades` (reconstructed internally from `oos_windows` — removes a redundant parameter) and returns `tuple[float, dict]` (metrics dict needed for CSV logging). The prose behavior from the spec is fully preserved.

```python
def _compute_score(
    oos_windows: list,
    atr_early: float,
    atr_extended: float,
) -> tuple[float, dict]:
    """Compute robustness score and metrics dict from WFO OOS windows.

    Returns (score, metrics_dict).
    metrics_dict is always populated (even on hard rejection) for logging.
    """
    # Collect all OOS trades across windows (already portfolio-capped by WFO engine)
    all_trades = [t for w in oos_windows for t in w.oos_trades]

    # Apply entry quality filter
    filtered = [
        t for t in all_trades
        if _entry_quality(t, atr_early, atr_extended) in ("EARLY", "OPTIMAL")
    ]
    n_trades = len(filtered)

    # Baseline metrics dict for logging even on hard rejection
    base_metrics = {"n_trades": n_trades, "expectancy": 0.0, "profit_factor": 0.0,
                    "avg_r": 0.0, "max_dd": 0.0, "dd_volatility": 0.0}

    # Hard rejection: trade count only — metrics not yet computed
    if n_trades < 200:
        return -10.0, base_metrics

    # Compute all metrics from filtered trades
    wins   = [t for t in filtered if t["is_win"]]
    losses = [t for t in filtered if not t["is_win"]]

    win_rate  = len(wins) / n_trades
    loss_rate = len(losses) / n_trades
    avg_win_r  = sum(t["rr_achieved"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_r = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win_r - loss_rate * avg_loss_r
    avg_r      = float(np.mean([t["rr_achieved"] for t in filtered]))

    gross_profit  = sum(t["portfolio_pnl_pct"] for t in wins)
    gross_loss    = abs(sum(t["portfolio_pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

    sorted_t = sorted(filtered, key=lambda t: t["exit_date"])
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted_t:
        equity *= 1.0 + t["portfolio_pnl_pct"] / 100.0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    # Per-window DD for volatility (stability metric)
    per_window_dd = [_window_max_dd(w, atr_early, atr_extended) for w in oos_windows]
    active_dds    = [d for d in per_window_dd if d is not None]
    dd_volatility = float(np.std(active_dds)) if len(active_dds) >= 2 else 0.0

    metrics = {
        "n_trades":     n_trades,
        "expectancy":   round(expectancy, 4),
        "profit_factor": round(min(profit_factor, 9999.0), 4),
        "avg_r":        round(avg_r, 4),
        "max_dd":       round(max_dd, 2),
        "dd_volatility": round(dd_volatility, 2),
    }

    # Hard rejections on computed metrics
    if expectancy <= 0:      return -8.0,  metrics
    if profit_factor < 1.2:  return -5.0,  metrics
    if max_dd > 50.0:        return -10.0, metrics

    # Soft low-trade penalty (ramps 0→2 below 300 trades)
    trade_penalty = max(0.0, (300 - n_trades) / 300) * 2.0

    score = (
        0.35 * expectancy
      + 0.25 * profit_factor
      + 0.15 * avg_r
      - 0.15 * (max_dd / 10.0)
      - 0.10 * (dd_volatility / 10.0)
      - trade_penalty
    )
    return round(score, 6), metrics
```

- [ ] **Step 3: Write unit tests for `_compute_score`**

Add to `scripts/tests/test_optimize_risk_v5_helpers.py`:

```python
from optimize_risk_v5 import _compute_score


def _make_window(trades):
    class W:
        oos_trades = trades
    return W()


def _early_trade(pnl: float, rr: float, is_win: bool, date="2024-01-10"):
    return {
        "entry_price": 100.05,
        "setup_meta": {"entry": 100.0, "atr": 1.0},
        "is_win": is_win,
        "rr_achieved": rr,
        "portfolio_pnl_pct": pnl,
        "exit_date": date,
        "setup_type": "PULLBACK",
    }


def test_score_hard_reject_low_trades():
    w = _make_window([_early_trade(1.0, 1.0, True, f"2024-01-{i+1:02d}") for i in range(10)])
    score, _ = _compute_score([w], 0.1, 0.5)
    assert score == -10.0


def test_score_hard_reject_negative_expectancy():
    trades = (
        [_early_trade(-1.0, -1.0, False, f"2024-01-{i+1:02d}") for i in range(200)]
    )
    w = _make_window(trades)
    score, metrics = _compute_score([w], 0.1, 0.5)
    assert score == -8.0
    assert metrics["expectancy"] <= 0


def test_score_positive_system():
    # 120 wins (+1R each), 80 losses (-0.5R each) → expectancy = 0.6×1 - 0.4×0.5 = 0.4R
    trades = (
        [_early_trade(1.0,  1.0, True,  f"2023-{(i//30)+1:02d}-{(i%30)+1:02d}") for i in range(120)] +
        [_early_trade(-0.5, -0.5, False, f"2023-{(i//30)+1:02d}-{(i%30)+1:02d}") for i in range(80)]
    )
    w = _make_window(trades)
    score, metrics = _compute_score([w], 0.1, 0.5)
    assert score > 0
    assert metrics["expectancy"] > 0
    assert metrics["profit_factor"] > 1.2
```

- [ ] **Step 4: Run tests**

```bash
cd swing-trading-dashboard
python -m pytest scripts/tests/test_optimize_risk_v5_helpers.py -v
```
Expected: all tests PASSED (12+ tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/optimize_risk_v5.py scripts/tests/test_optimize_risk_v5_helpers.py
git commit -m "feat: add _compute_score and _compute_per_setup_stats with tests"
```

---

## Task 6: Objective Function and CSV Logger

Append to `optimize_risk_v5.py`.

**Files:**
- Modify: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Write `_log_trial`**

```python
_CSV_FIELDNAMES = [
    "trial_number", "score",
    "trail_mult", "risk_per_trade", "max_position_pct",
    "atr_entry_early", "atr_entry_extended",
    "expectancy", "profit_factor", "avg_r", "max_dd", "dd_volatility", "n_trades",
] + [f"{s}_{m}" for s in _SETUP_TYPES for m in ("n", "expectancy", "pf", "winrate")]


def _log_trial(trial, metrics: dict, setup_stats: dict, log_path: str = _CSV_LOG) -> None:
    """Append one row per completed trial to CSV for live monitoring."""
    file_exists = os.path.exists(log_path)
    row: dict = {"trial_number": trial.number, "score": trial.value}
    row.update(trial.params)
    row.update(metrics)
    for stype, stats in setup_stats.items():
        row[f"{stype}_n"]          = stats["n"]
        row[f"{stype}_expectancy"] = stats["expectancy"]
        row[f"{stype}_pf"]         = stats["profit_factor"]
        row[f"{stype}_winrate"]    = stats["win_rate"]
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
```

- [ ] **Step 2: Write `objective`**

```python
def objective(trial, bounds: dict) -> float:
    """Optuna objective: patch constants → run WFO → compute v5 robustness score."""
    import optuna

    # Sample parameters
    trail_mult         = trial.suggest_float("trail_mult",         *bounds["trail_mult"])
    risk_per_trade     = trial.suggest_float("risk_per_trade",     *bounds["risk_per_trade"])
    max_position_pct   = trial.suggest_float("max_position_pct",   *bounds["max_position_pct"])
    atr_entry_early    = trial.suggest_float("atr_entry_early",    *bounds["atr_entry_early"])
    atr_entry_extended = trial.suggest_float("atr_entry_extended", *bounds["atr_entry_extended"])

    # Enforce ordering constraint
    if atr_entry_early >= atr_entry_extended:
        raise optuna.TrialPruned()

    params = {
        "trail_mult":       trail_mult,
        "risk_per_trade":   risk_per_trade,
        "max_position_pct": max_position_pct,
    }

    with _patch_constants(params):
        result = asyncio.run(run_wfo(
            tickers=["SPY"] + REPRESENTATIVE_TICKERS_V2,
            setup_types=WFO_SETUP_TYPES,
            is_months=WFO_IS_MONTHS,
            oos_months=WFO_OOS_MONTHS,
            step_months=WFO_STEP_MONTHS,
            run_id=f"v5_trial_{trial.number}",
        ))

    score, metrics = _compute_score(result.windows, atr_entry_early, atr_entry_extended)

    # Collect per-setup stats for logging (from filtered trades)
    all_filtered = [
        t for w in result.windows for t in w.oos_trades
        if _entry_quality(t, atr_entry_early, atr_entry_extended) in ("EARLY", "OPTIMAL")
    ]
    setup_stats = _compute_per_setup_stats(all_filtered)

    trial.set_user_attr("metrics",     metrics)
    trial.set_user_attr("setup_stats", setup_stats)

    trial.report(score, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return score
```

- [ ] **Step 3: Commit**

```bash
git add scripts/optimize_risk_v5.py
git commit -m "feat: add objective function and CSV logger for risk optimizer v5"
```

---

## Task 7: Phase Output Functions

Append to `optimize_risk_v5.py`.

**Files:**
- Modify: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Write `_compute_distribution`**

```python
def _compute_distribution(trials: list, bounds: dict) -> dict:
    """Mean/std/min/max of each param across the given trials."""
    dist = {}
    for param, (lo, hi) in bounds.items():
        vals = [t.params[param] for t in trials if param in t.params]
        if not vals:
            dist[param] = {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
            continue
        dist[param] = {
            "mean": round(float(np.mean(vals)), 4),
            "std":  round(float(np.std(vals)),  4),
            "min":  round(float(min(vals)),      4),
            "max":  round(float(max(vals)),      4),
        }
    return dist


def _compute_stability(dist: dict, bounds: dict) -> dict:
    """Flag whether top-30 param range is narrow (std < 15% of search range)."""
    stability = {}
    for param, (lo, hi) in bounds.items():
        search_range = hi - lo
        std = dist[param]["std"]
        std_pct = round(std / search_range * 100, 1) if search_range > 0 else 0.0
        stability[param] = {
            "narrow":            std_pct < 15.0,
            "std_pct_of_range":  std_pct,
        }
    return stability


def _compute_sensitivity(completed_trials: list) -> dict:
    """Bucket trail_mult across 4 ranges and report avg score per bucket."""
    buckets = [
        ("[2.0-3.5]", 2.0, 3.5),
        ("[3.5-5.0]", 3.5, 5.0),
        ("[5.0-6.5]", 5.0, 6.5),
        ("[6.5-8.5]", 6.5, 8.5),
    ]
    result = {}
    for label, lo, hi in buckets:
        bucket_trials = [
            t for t in completed_trials
            if lo <= t.params.get("trail_mult", -1) < hi
        ]
        result[label] = {
            "n_trials":  len(bucket_trials),
            "avg_score": round(float(np.mean([t.value for t in bucket_trials])), 4)
                         if bucket_trials else 0.0,
        }
    return result


def _compute_phase2_ranges(top_trials: list, bounds_p1: dict) -> dict:
    """Narrow ranges for Phase 2: [best - 1.5×std, best + 1.5×std] clipped to P1 bounds.
    Special case: clamp atr_entry_early upper bound below atr_entry_extended lower bound.
    """
    best   = top_trials[0]
    ranges = {}
    for param, (lo_orig, hi_orig) in bounds_p1.items():
        vals = [t.params[param] for t in top_trials if param in t.params]
        std  = float(np.std(vals)) if len(vals) > 1 else (hi_orig - lo_orig) * 0.1
        best_val = best.params.get(param, (lo_orig + hi_orig) / 2)
        new_lo = max(lo_orig, best_val - 1.5 * std)
        new_hi = min(hi_orig, best_val + 1.5 * std)
        # Ensure lo < hi (fallback to original if collapsed)
        if new_lo >= new_hi:
            new_lo, new_hi = lo_orig, hi_orig
        ranges[param] = [round(new_lo, 4), round(new_hi, 4)]

    # Enforce ATR ordering: atr_entry_early_hi must be < atr_entry_extended_lo
    if ranges["atr_entry_early"][1] >= ranges["atr_entry_extended"][0]:
        ranges["atr_entry_early"][1] = round(ranges["atr_entry_extended"][0] - 0.05, 4)
        # Safety: if this makes lo >= hi, reset early range to original
        if ranges["atr_entry_early"][0] >= ranges["atr_entry_early"][1]:
            ranges["atr_entry_early"] = list(bounds_p1["atr_entry_early"])

    return ranges
```

- [ ] **Step 2: Write `_export_phase1` and `_export_phase2`**

```python
def _export_phase1(study, suppress_output: bool = False) -> None:
    """Write Phase 1 JSON output with top-30, distribution, stability, sensitivity."""
    completed = [t for t in study.trials if t.state.name == "COMPLETE" and t.value is not None]
    if not completed:
        print("No completed trials to export.")
        return

    top_30 = sorted(completed, key=lambda t: t.value, reverse=True)[:30]

    dist        = _compute_distribution(top_30, BOUNDS_P1)
    stability   = _compute_stability(dist, BOUNDS_P1)
    sensitivity = _compute_sensitivity(completed)
    p2_ranges   = _compute_phase2_ranges(top_30, BOUNDS_P1)

    output = {
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "study":                 study.study_name,
        "total_completed_trials": len(completed),
        "top_30_trials": [
            {
                "trial":          t.number,
                "score":          round(t.value, 6),
                "params":         {k: round(v, 4) if isinstance(v, float) else v
                                   for k, v in t.params.items()},
                "metrics":        t.user_attrs.get("metrics", {}),
                "setup_stats":    t.user_attrs.get("setup_stats", {}),
            }
            for t in top_30
        ],
        "distribution":           dist,
        "stability":              stability,
        "sensitivity":            {"trail_mult_buckets": sensitivity},
        "phase2_suggested_ranges": p2_ranges,
    }

    _OUTPUT_P1.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_P1.write_text(json.dumps(output, indent=2))

    if not suppress_output:
        print(f"\n{'='*60}")
        print("  PHASE 1 RESULTS")
        print(f"{'='*60}")
        best = top_30[0]
        print(f"  Best score: {best.value:.4f}  (trial #{best.number})")
        for k, v in best.params.items():
            narrow = stability.get(k, {}).get("narrow", False)
            flag   = " ✅ stable" if narrow else " ⚠️  spread"
            print(f"  {k:<25} {round(v, 4) if isinstance(v, float) else v}{flag}")
        print(f"\n  Trail mult sensitivity:")
        for bucket, info in sensitivity.items():
            print(f"    {bucket:<12} avg={info['avg_score']:+.4f}  n={info['n_trials']}")
        print(f"\n  Phase 2 suggested ranges: {p2_ranges}")
        print(f"  Exported to: {_OUTPUT_P1}")


def _export_phase2(study, suppress_output: bool = False) -> None:
    """Write Phase 2 JSON output with top-30 and recommended block."""
    completed = [t for t in study.trials if t.state.name == "COMPLETE" and t.value is not None]
    if not completed:
        print("No completed trials to export.")
        return

    top_30 = sorted(completed, key=lambda t: t.value, reverse=True)[:30]
    best   = top_30[0]

    # Load Phase 2 bounds from Phase 1 output for distribution comparison
    bounds_p2 = _load_phase2_bounds()

    dist      = _compute_distribution(top_30, bounds_p2)
    stability = _compute_stability(dist, bounds_p2)
    sensitivity = _compute_sensitivity(completed)

    recommended = {
        "trail_mult":         round(best.params.get("trail_mult", 0), 4),
        "risk_per_trade":     round(best.params.get("risk_per_trade", 0), 4),
        "max_position_pct":   round(best.params.get("max_position_pct", 0), 4),
        "atr_entry_early":    round(best.params.get("atr_entry_early", 0), 4),
        "atr_entry_extended": round(best.params.get("atr_entry_extended", 0), 4),
        "score":              round(best.value, 6),
        "rationale": (
            f"Top trial #{best.number} by score; "
            f"expectancy={best.user_attrs.get('metrics', {}).get('expectancy', 'n/a')}, "
            f"max_dd={best.user_attrs.get('metrics', {}).get('max_dd', 'n/a')}%."
        ),
    }

    output = {
        "generated_at":           datetime.now(timezone.utc).isoformat(),
        "study":                  study.study_name,
        "total_completed_trials": len(completed),
        "top_30_trials": [
            {
                "trial":       t.number,
                "score":       round(t.value, 6),
                "params":      {k: round(v, 4) if isinstance(v, float) else v
                                for k, v in t.params.items()},
                "metrics":     t.user_attrs.get("metrics", {}),
                "setup_stats": t.user_attrs.get("setup_stats", {}),
            }
            for t in top_30
        ],
        "distribution":  dist,
        "stability":     stability,
        "sensitivity":   {"trail_mult_buckets": sensitivity},
        "recommended":   recommended,
    }

    _OUTPUT_P2.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_P2.write_text(json.dumps(output, indent=2))

    if not suppress_output:
        print(f"\n{'='*60}")
        print("  PHASE 2 RESULTS — RECOMMENDED PARAMETERS")
        print(f"{'='*60}")
        for k, v in recommended.items():
            if k == "rationale":
                continue
            print(f"  {k:<25} {v}")
        print(f"\n  Rationale: {recommended['rationale']}")
        print(f"  Exported to: {_OUTPUT_P2}")
```

- [ ] **Step 3: Write `_load_phase2_bounds`**

```python
def _load_phase2_bounds() -> dict:
    """Load Phase 2 suggested ranges from Phase 1 JSON output.
    Falls back to Phase 1 wide bounds if file not found.
    """
    if not _OUTPUT_P1.exists():
        print(f"  Warning: Phase 1 output not found at {_OUTPUT_P1}. Using P1 bounds.")
        return BOUNDS_P1
    data   = json.loads(_OUTPUT_P1.read_text())
    ranges = data.get("phase2_suggested_ranges", {})
    bounds = {}
    for param, (lo_orig, hi_orig) in BOUNDS_P1.items():
        if param in ranges and len(ranges[param]) == 2:
            bounds[param] = tuple(ranges[param])
        else:
            bounds[param] = (lo_orig, hi_orig)
    return bounds
```

- [ ] **Step 4: Commit**

```bash
git add scripts/optimize_risk_v5.py
git commit -m "feat: add phase output functions — distribution, stability, sensitivity, phase2 ranges"
```

---

## Task 8: `main()` and CLI

Append to `optimize_risk_v5.py`.

**Files:**
- Modify: `scripts/optimize_risk_v5.py`

- [ ] **Step 1: Write `main()`**

```python
def main(phase: int, n_trials: int, suppress_output: bool = False) -> None:
    import optuna
    from optuna.samplers import TPESampler
    from optuna.pruners import MedianPruner
    try:
        from tqdm import tqdm
        _has_tqdm = True
    except ImportError:
        _has_tqdm = False

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _preload_modules()

    if phase == 1:
        study_name = _STUDY_NAME_P1
        bounds     = BOUNDS_P1
    else:
        study_name = _STUDY_NAME_P2
        bounds     = _load_phase2_bounds()
        if not suppress_output:
            print(f"  Phase 2 bounds loaded: {bounds}")

    study = optuna.create_study(
        study_name=study_name,
        storage=f"sqlite:///{_STUDY_DB}",
        direction="maximize",
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=15, n_warmup_steps=2),
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials if t.state.name == "COMPLETE"])
    remaining = max(0, n_trials - completed_before)
    if not suppress_output:
        print(f"\n  Study: {study_name}")
        print(f"  Trials: {completed_before} done, running {remaining} more (target {n_trials})")

    if remaining == 0:
        if not suppress_output:
            print("  Target already reached — exporting results.")
    else:
        def _cb(study, trial):
            if trial.state.name == "COMPLETE" and trial.value is not None:
                metrics     = trial.user_attrs.get("metrics", {})
                setup_stats = trial.user_attrs.get("setup_stats", {})
                _log_trial(trial, metrics, setup_stats)
                if not suppress_output:
                    print(
                        f"  Trial {trial.number:4d} | score={trial.value:+.4f} | "
                        f"exp={metrics.get('expectancy', 0):+.3f} | "
                        f"PF={metrics.get('profit_factor', 0):.2f} | "
                        f"DD={metrics.get('max_dd', 0):.1f}% | "
                        f"n={metrics.get('n_trades', 0)}"
                    )

        study.optimize(
            lambda trial: objective(trial, bounds),
            n_trials=remaining,
            callbacks=[_cb],
        )

    if phase == 1:
        _export_phase1(study, suppress_output=suppress_output)
    else:
        _export_phase2(study, suppress_output=suppress_output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Risk Optimizer V5")
    parser.add_argument("--phase",  type=int, default=1, choices=[1, 2],
                        help="Optimization phase (1=wide, 2=refined)")
    parser.add_argument("--trials", type=int, default=None,
                        help="Number of trials (default: 300 for phase 1, 200 for phase 2)")
    args   = parser.parse_args()
    n      = args.trials or (_DEFAULT_TRIALS_P1 if args.phase == 1 else _DEFAULT_TRIALS_P2)
    main(phase=args.phase, n_trials=n)
```

- [ ] **Step 2: Commit**

```bash
git add scripts/optimize_risk_v5.py
git commit -m "feat: add main() and CLI entrypoint for risk optimizer v5"
```

---

## Task 9: Smoke Test

End-to-end validation with 5 trials.

- [ ] **Step 1: Run Phase 1 smoke test**

```bash
cd swing-trading-dashboard/backend
python ../scripts/optimize_risk_v5.py --phase 1 --trials 5
```
Expected output (approximate):
```
  Study: trading_risk_v5_phase1
  Trials: 0 done, running 5 more (target 5)
  Trial    0 | score=+X.XXXX | exp=+X.XXX | PF=X.XX | DD=XX.X% | n=XXX
  ...
  ============================================================
    PHASE 1 RESULTS
  ============================================================
  Best score: X.XXXX  (trial #X)
  trail_mult         X.XXXX  ...
  ...
  Exported to: .../config/best_parameters_risk_v5_phase1.json
```

- [ ] **Step 2: Verify CSV log written**

```bash
python -c "
import csv
with open('optuna_trial_log_risk_v5.csv') as f:
    rows = list(csv.DictReader(f))
print(f'CSV rows: {len(rows)}')
print('Columns:', list(rows[0].keys())[:8], '...')
"
```
Expected: 5 rows, columns include `trial_number`, `score`, `trail_mult`, `expectancy`, etc.

- [ ] **Step 3: Verify Phase 1 JSON**

```bash
python -c "
import json
from pathlib import Path
data = json.loads(Path('../config/best_parameters_risk_v5_phase1.json').read_text())
assert 'top_30_trials' in data
assert 'distribution' in data
assert 'sensitivity' in data
assert 'phase2_suggested_ranges' in data
print('Phase 1 JSON keys:', list(data.keys()))
print('Top trial score:', data['top_30_trials'][0]['score'])
print('Phase 2 ranges:', data['phase2_suggested_ranges'])
"
```
Expected: all assertions pass.

- [ ] **Step 4: Run Phase 2 smoke test**

```bash
python ../scripts/optimize_risk_v5.py --phase 2 --trials 5
```
Expected: prints Phase 2 bounds (narrowed from Phase 1), runs 5 trials, writes `best_parameters_risk_v5_phase2.json` with `recommended` block.

- [ ] **Step 5: Verify v4 study untouched**

```bash
python -c "
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)
s = optuna.load_study(study_name='trading_optimizer_v4', storage='sqlite:///$(python -c \"from pathlib import Path; print(Path.cwd().parent / \\\"optuna_study.db\\\")\")')
print('v4 study trials unchanged:', len(s.trials))
"
```
Expected: v4 trial count matches what was there before (no new trials added).

- [ ] **Step 6: Final commit**

```bash
git add scripts/optimize_risk_v5.py scripts/tests/
git commit -m "feat: complete risk optimizer v5 — smoke tested, all acceptance criteria met"
```

---

## Acceptance Criteria Checklist

- [ ] `backtest_engine.py` gap fix: stop-out with open below stop exits at `open`, not `stop`
- [ ] `RISK_PER_TRADE_PCT` and `MAX_POSITION_SIZE_PCT` patched in both `constants` and `backtest_engine`
- [ ] `trail_mult` patches all 5 trail constants; HTF uses `TRAIL_ATR_MULT` fallback
- [ ] ATR entry quality filter uses `setup_meta.atr` + `setup_meta.entry`
- [ ] `_apply_portfolio_cap` called once (inside WFO engine only)
- [ ] `dd_volatility` normalized by /10 in score; falls back to 0.0 for <2 active windows
- [ ] Phase 2 range narrowing clamps `atr_entry_early` hi below `atr_entry_extended` lo
- [ ] `--phase 1 --trials 5` completes without errors
- [ ] CSV log written with correct columns
- [ ] Phase 1 JSON has `top_30_trials`, `distribution`, `sensitivity`, `phase2_suggested_ranges`
- [ ] `--phase 2` reads Phase 1 JSON and narrows ranges correctly
- [ ] Phase 2 JSON has `recommended` block
- [ ] v4 study in SQLite unmodified after running v5
