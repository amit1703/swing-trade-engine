# Walk-Forward Optuna Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `wfo_optuna.py` — a standalone CLI that runs per-window Optuna optimization across 4 rolling IS/OOS windows (2019–2024), then validates the production-frozen params (trial #433) on the same OOS windows for comparison, and prints a full WFO report with parameter stability analysis.

**Architecture:** Single new file `backend/wfo_optuna.py` following the pattern of `optimize_v5.py` (data loading, asyncio backtest runner, Optuna loop) and `oos_validation.py` (rolling windows, report printing). Each of the 4 IS windows gets its own resumable Optuna SQLite DB (`data/wfo_w1.db`…`data/wfo_w4.db`). No changes to `wfo_engine.py`, `optimize_v5.py`, or `main.py`.

**Tech Stack:** Python 3.10+, Optuna TPE, asyncio + Semaphore, parquet cache from `data/price_cache/`, `BacktestEngine` / `BacktestParams` from `backtest_engine.py`.

---

## Context for the implementer

### Key existing files to understand

- `backend/optimize_v5.py` — The IS optimization pattern. `wfo_optuna.py` will copy `_load_universe_cache`, `_run_trial`, `_compute_metrics`, `_spy_return`, `_objective_score`, `_build_params`, and `_build_params_from_values` from here verbatim (with minor modifications noted below).
- `backend/oos_validation.py` — The rolling window + report pattern. Study its `_print_report` for formatting conventions.
- `backend/backtest_engine.py` — `BacktestEngine(ticker, start_date, end_date, ticker_df, spy_df, params)`. `params` is a `BacktestParams` dataclass.
- `backend/constants.py` — `CONCURRENCY_LIMIT`, `WFO_CACHE_DIR` are the key imports.
- `backend/wfo_cache.py` — `get_cache_path`, `load_ticker` for parquet access.

### The 4 rolling windows (hardcoded constants in the script)

```
Window 1: IS 2019-01-01→2020-12-31  OOS 2021-01-01→2021-12-31
Window 2: IS 2020-01-01→2021-12-31  OOS 2022-01-01→2022-12-31
Window 3: IS 2021-01-01→2022-12-31  OOS 2023-01-01→2023-12-31
Window 4: IS 2022-01-01→2023-12-31  OOS 2024-01-01→2024-12-31
```

### Search space (identical to optimize_v5.py `_build_params`)

6 tunable params, all others frozen at trial #433 values:
- `tp_multiple`    suggest_float [1.5, 6.0]
- `brk_vol_mult`   suggest_float [1.5, 3.5]
- `brk_stop_atr`   suggest_float [0.3, 2.0]
- `brk_min_pct`    suggest_float [0.01, 0.05]
- `brk_gap_pct`    suggest_float [0.01, 0.08]
- `brk_trail_mult` suggest_float [1.5, 8.0]

### Frozen params (trial #433 = current `BacktestParams()` defaults)

```python
rs_threshold=0.066, cci_threshold=-54.5, ema_distance=1.651,
score_threshold=2.50, breakout_weight=1.724, pullback_weight=1.842,
tdl_bonus=1.016, vcp_bonus=1.370, cooldown_days=4,
tp_multiple=4.3458, brk_vol_mult=3.0161, brk_stop_atr=1.6675,
brk_min_pct=0.04333, brk_gap_pct=0.01021, brk_trail_mult=6.906,
```

---

## Task 1: Tests for pure functions

**Files:**
- Create: `backend/tests/test_wfo_optuna.py`

### Step 1: Write the tests

```python
# backend/tests/test_wfo_optuna.py
"""Tests for wfo_optuna.py pure functions."""
import os
import sys
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Window constants ──────────────────────────────────────────────────────────

def test_wfo_windows_count():
    from wfo_optuna import WFO_WINDOWS
    assert len(WFO_WINDOWS) == 4


def test_wfo_windows_structure():
    from wfo_optuna import WFO_WINDOWS
    for win_num, is_start, is_end, oos_start, oos_end in WFO_WINDOWS:
        # IS ends where OOS begins
        assert is_end == oos_start
        # OOS is 12 months
        is_s = pd.Timestamp(oos_start)
        is_e = pd.Timestamp(oos_end)
        months = (is_e.year - is_s.year) * 12 + (is_e.month - is_s.month)
        assert months == 12, f"OOS window {win_num} should be 12 months"


def test_wfo_windows_oos_non_overlapping():
    from wfo_optuna import WFO_WINDOWS
    for i in range(len(WFO_WINDOWS) - 1):
        _, _, _, _, oos_end_i = WFO_WINDOWS[i]
        _, _, _, oos_start_next, _ = WFO_WINDOWS[i + 1]
        assert pd.Timestamp(oos_end_i) <= pd.Timestamp(oos_start_next)


def test_wfo_windows_starts_2019():
    from wfo_optuna import WFO_WINDOWS
    assert WFO_WINDOWS[0][1] == "2019-01-01"


# ── Objective score ───────────────────────────────────────────────────────────

def test_objective_score_positive():
    from wfo_optuna import _objective_score, MIN_TRADES
    metrics = {
        "total_trades": MIN_TRADES + 50,
        "expectancy": 0.25,
        "profit_factor": 1.8,
    }
    score = _objective_score(metrics)
    assert score > 0


def test_objective_score_penalty_low_trades():
    from wfo_optuna import _objective_score, MIN_TRADES, PENALTY_SCORE
    metrics = {
        "total_trades": MIN_TRADES - 1,
        "expectancy": 0.5,
        "profit_factor": 2.0,
    }
    assert _objective_score(metrics) == PENALTY_SCORE


def test_objective_score_negative_expectancy():
    from wfo_optuna import _objective_score, MIN_TRADES
    metrics = {
        "total_trades": MIN_TRADES + 50,
        "expectancy": -0.1,
        "profit_factor": 0.9,
    }
    score = _objective_score(metrics)
    assert score < 0


# ── Build params from values ──────────────────────────────────────────────────

def test_build_params_from_values_uses_provided():
    from wfo_optuna import _build_params_from_values
    values = {
        "tp_multiple":   3.5,
        "brk_vol_mult":  2.0,
        "brk_stop_atr":  1.0,
        "brk_min_pct":   0.02,
        "brk_gap_pct":   0.03,
        "brk_trail_mult": 4.0,
    }
    p = _build_params_from_values(values)
    assert abs(p.tp_multiple - 3.5) < 1e-9
    assert abs(p.brk_vol_mult - 2.0) < 1e-9
    assert abs(p.brk_trail_mult - 4.0) < 1e-9


def test_build_params_from_values_frozen_defaults():
    from wfo_optuna import _build_params_from_values
    # frozen params should always be the trial #433 values
    values = {
        "tp_multiple":   4.0,
        "brk_vol_mult":  2.5,
        "brk_stop_atr":  1.0,
        "brk_min_pct":   0.03,
        "brk_gap_pct":   0.02,
        "brk_trail_mult": 5.0,
    }
    p = _build_params_from_values(values)
    assert abs(p.rs_threshold - 0.066) < 1e-9
    assert abs(p.cci_threshold - (-54.5)) < 1e-9
    assert abs(p.ema_distance - 1.651) < 1e-9
    assert p.cooldown_days == 4


def test_frozen_params_equals_defaults():
    from wfo_optuna import _frozen_params
    from backtest_engine import BacktestParams
    frozen = _frozen_params()
    defaults = BacktestParams()
    # All fields must match
    assert frozen.tp_multiple == defaults.tp_multiple
    assert frozen.brk_vol_mult == defaults.brk_vol_mult
    assert frozen.rs_threshold == defaults.rs_threshold


# ── Sparkline ─────────────────────────────────────────────────────────────────

def test_sparkline_length_matches_input():
    from wfo_optuna import _sparkline
    values = [1.0, 2.5, 0.5, 3.0, 1.5]
    result = _sparkline(values)
    assert len(result) == len(values)


def test_sparkline_empty():
    from wfo_optuna import _sparkline
    assert _sparkline([]) == ""


def test_sparkline_constant_values():
    from wfo_optuna import _sparkline
    result = _sparkline([5.0, 5.0, 5.0])
    assert len(result) == 3
    # All same char when constant
    assert len(set(result)) == 1


# ── SPY return ────────────────────────────────────────────────────────────────

def test_spy_return_none_when_spy_none():
    from wfo_optuna import _spy_return
    assert _spy_return(None, "2023-01-01", "2023-12-31") is None


def test_spy_return_computes_correctly():
    from wfo_optuna import _spy_return
    dates = pd.date_range("2023-01-01", "2023-12-31", freq="B")
    close = pd.Series([100.0] + [110.0] * (len(dates) - 1), index=dates)
    df = pd.DataFrame({"Close": close, "Adj Close": close})
    result = _spy_return(df, "2023-01-01", "2023-12-31")
    assert result is not None
    assert abs(result - 0.10) < 0.01   # 10% return


# ── Compute metrics ───────────────────────────────────────────────────────────

def test_compute_metrics_empty():
    from wfo_optuna import _compute_metrics
    m = _compute_metrics([])
    assert m["total_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["expectancy"] == 0.0


def test_compute_metrics_basic():
    from wfo_optuna import _compute_metrics
    trades = [
        {"rr_achieved": 2.0, "setup_type": "PULLBACK", "portfolio_pnl_pct": 2.0, "exit_date": "2023-01-10"},
        {"rr_achieved": 2.0, "setup_type": "PULLBACK", "portfolio_pnl_pct": 2.0, "exit_date": "2023-01-15"},
        {"rr_achieved": -1.0, "setup_type": "PULLBACK", "portfolio_pnl_pct": -1.0, "exit_date": "2023-01-20"},
    ]
    m = _compute_metrics(trades)
    assert m["total_trades"] == 3
    assert abs(m["win_rate"] - 66.7) < 0.1
    assert m["profit_factor"] > 1.0
    assert m["expectancy"] > 0
    assert m["max_drawdown_r"] <= 0
```

### Step 2: Run tests — expect ImportError (module doesn't exist yet)

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'wfo_optuna'`

### Step 3: Commit the test file

```bash
cd backend
git add tests/test_wfo_optuna.py
git commit -m "test: add wfo_optuna pure function tests (all failing — module not yet created)"
```

---

## Task 2: Module skeleton + window constants + data structures

**Files:**
- Create: `backend/wfo_optuna.py`

### Step 1: Write the skeleton

Create `backend/wfo_optuna.py` with the following complete content:

```python
"""
wfo_optuna.py — Walk-Forward Optuna Validation
════════════════════════════════════════════════
Runs per-window Optuna IS optimization across 4 rolling windows (2019–2024),
applies best IS params to each OOS window, then reruns all OOS windows with
frozen trial #433 params for comparison. Prints a full WFO report.

Windows (IS=24 months, OOS=12 months, step=12 months, start=2019-01-01):
  W1: IS 2019-01-01→2020-12-31  OOS 2021-01-01→2021-12-31
  W2: IS 2020-01-01→2021-12-31  OOS 2022-01-01→2022-12-31
  W3: IS 2021-01-01→2022-12-31  OOS 2023-01-01→2023-12-31
  W4: IS 2022-01-01→2023-12-31  OOS 2024-01-01→2024-12-31

Usage:
    cd backend
    python3 wfo_optuna.py [--trials 100] [--resume] [--windows 1,2,3,4]

Output:
    data/wfo_w1.db … data/wfo_w4.db   (Optuna SQLite per window, resumable)
    data/wfo_optuna_results.json       (full results)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import BacktestEngine, BacktestParams
from constants import CONCURRENCY_LIMIT, WFO_CACHE_DIR
from wfo_cache import load_ticker

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wfo_optuna")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).parent
_DATA_DIR    = _BACKEND_DIR / "data"
_DATA_DIR.mkdir(exist_ok=True)
_OUTPUT_PATH = _DATA_DIR / "wfo_optuna_results.json"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIN_TRADES    = 200
PENALTY_SCORE = -99.0

# 4 rolling windows: (window_num, IS_start, IS_end, OOS_start, OOS_end)
# IS=24 months, OOS=12 months, step=12 months, starting 2019-01-01
WFO_WINDOWS: List[Tuple[int, str, str, str, str]] = [
    (1, "2019-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
    (2, "2020-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    (3, "2021-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    (4, "2022-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
]

# The 6 tunable parameter names (used for stability table)
TUNABLE_PARAMS = [
    "tp_multiple",
    "brk_vol_mult",
    "brk_stop_atr",
    "brk_min_pct",
    "brk_gap_pct",
    "brk_trail_mult",
]


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WindowOptResult:
    """Results for one rolling window (IS optimization + OOS evaluation)."""
    window_num:     int
    is_start:       str
    is_end:         str
    oos_start:      str
    oos_end:        str
    best_trial:     int          # Optuna trial number
    best_score:     float        # IS objective score
    best_params:    Dict[str, float]   # tunable param values from IS best
    is_metrics:     dict         # IS period metrics with best params
    oos_metrics:    dict         # OOS period metrics with best IS params
    frozen_metrics: dict         # OOS period metrics with frozen #433 params
    spy_pct:        Optional[float]    # SPY return over OOS period


# ─────────────────────────────────────────────────────────────────────────────
# Sparkline helper
# ─────────────────────────────────────────────────────────────────────────────

def _sparkline(values: List[float]) -> str:
    """Return a unicode sparkline string for a list of floats."""
    chars = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    mn, mx = min(values), max(values)
    if mx == mn:
        return chars[3] * len(values)
    return "".join(
        chars[min(7, int((v - mn) / (mx - mn) * 8))]
        for v in values
    )
```

### Step 2: Run the window-constant tests — they should pass now

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py::test_wfo_windows_count \
    tests/test_wfo_optuna.py::test_wfo_windows_structure \
    tests/test_wfo_optuna.py::test_wfo_windows_oos_non_overlapping \
    tests/test_wfo_optuna.py::test_wfo_windows_starts_2019 \
    tests/test_wfo_optuna.py::test_sparkline_length_matches_input \
    tests/test_wfo_optuna.py::test_sparkline_empty \
    tests/test_wfo_optuna.py::test_sparkline_constant_values \
    -v
```

Expected: all 7 PASS.

### Step 3: Commit

```bash
cd backend
git add wfo_optuna.py
git commit -m "feat(wfo): add wfo_optuna.py skeleton with window constants and sparkline"
```

---

## Task 3: Metrics helpers, SPY return, objective score, data loading

**Files:**
- Modify: `backend/wfo_optuna.py` (append after the sparkline helper)

### Step 1: Append to `wfo_optuna.py`

Add these functions **directly after** `_sparkline`. They are copied verbatim from `optimize_v5.py` — do not modify logic.

```python
# ─────────────────────────────────────────────────────────────────────────────
# Data loading (identical to optimize_v5.py)
# ─────────────────────────────────────────────────────────────────────────────

def _load_universe_cache(
    cache_dir: Path,
) -> Tuple[Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """Load all parquet files from the WFO cache directory."""
    if not cache_dir.exists():
        logger.error("Cache dir does not exist: %s", cache_dir)
        return {}, None

    parquet_files = list(cache_dir.glob("*.parquet"))
    if not parquet_files:
        logger.error("No parquet files in %s. Run wfo_cache download first.", cache_dir)
        return {}, None

    ticker_cache: Dict[str, pd.DataFrame] = {}
    spy_df: Optional[pd.DataFrame] = None

    print(f"Loading {len(parquet_files)} parquet files from cache…", flush=True)
    for path in parquet_files:
        ticker = path.stem.upper()
        try:
            df = pd.read_parquet(path)
            if df is None or df.empty:
                continue
            ticker_cache[ticker] = df
            if ticker == "SPY":
                spy_df = df
        except Exception as exc:
            logger.debug("Failed to load %s: %s", path, exc)

    non_spy = len(ticker_cache) - (1 if spy_df is not None else 0)
    print(f"  Loaded {len(ticker_cache)} tickers ({non_spy} non-SPY).", flush=True)
    if spy_df is None:
        print("  WARNING: SPY not found — benchmark unavailable.", flush=True)
    return ticker_cache, spy_df


# ─────────────────────────────────────────────────────────────────────────────
# SPY benchmark (identical to optimize_v5.py)
# ─────────────────────────────────────────────────────────────────────────────

def _spy_return(
    spy_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
) -> Optional[float]:
    """Return SPY's total % return over [start_date, end_date]. None if unavailable."""
    if spy_df is None or spy_df.empty:
        return None
    try:
        adj_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
        sliced  = spy_df.loc[start_date:end_date, adj_col].dropna()
        if len(sliced) < 2:
            return None
        return float(sliced.iloc[-1] / sliced.iloc[0] - 1)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Metrics (identical to optimize_v5.py _compute_metrics)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_metrics(trades: List[dict]) -> dict:
    """Compute expectancy, PF, win rate, max drawdown, portfolio return."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0,
            "expectancy": 0.0, "profit_factor": 0.0,
            "max_drawdown_r": 0.0, "portfolio_return_pct": 0.0, "by_setup": {},
        }

    rr_vals = [t["rr_achieved"] for t in trades if "rr_achieved" in t]
    wins    = [r for r in rr_vals if r > 0]
    losses  = [r for r in rr_vals if r <= 0]

    total      = len(rr_vals)
    win_rate   = len(wins) / total if total else 0.0
    expectancy = sum(rr_vals) / total if total else 0.0

    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # Max drawdown in R (peak-to-trough of cumulative R curve)
    peak, max_dd, running = 0.0, 0.0, 0.0
    for r in rr_vals:
        running += r
        if running > peak:
            peak = running
        dd = running - peak
        if dd < max_dd:
            max_dd = dd

    # Compounded portfolio return (1% risk/trade, sorted by exit_date)
    sorted_trades = sorted(
        [t for t in trades if "portfolio_pnl_pct" in t and "exit_date" in t],
        key=lambda t: t["exit_date"],
    )
    equity = 1.0
    for t in sorted_trades:
        equity *= (1.0 + t["portfolio_pnl_pct"] / 100.0)
    portfolio_return_pct = round((equity - 1.0) * 100.0, 2)

    by_setup: Dict[str, int] = defaultdict(int)
    for t in trades:
        by_setup[t.get("setup_type", "UNKNOWN")] += 1

    return {
        "total_trades":         total,
        "win_rate":             round(win_rate * 100, 1),
        "expectancy":           round(expectancy, 4),
        "profit_factor":        round(min(profit_factor, 99.0), 3),
        "max_drawdown_r":       round(max_dd, 2),
        "portfolio_return_pct": portfolio_return_pct,
        "by_setup":             dict(by_setup),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Objective score (identical to optimize_v5.py)
# ─────────────────────────────────────────────────────────────────────────────

def _objective_score(metrics: dict) -> float:
    """Compute Optuna objective: expectancy × PF × log(trades+1)."""
    n  = metrics["total_trades"]
    ex = metrics["expectancy"]
    pf = min(metrics["profit_factor"], 10.0)

    if n < MIN_TRADES:
        return PENALTY_SCORE
    if ex <= 0 or pf <= 0:
        return ex
    return ex * pf * math.log(n + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Backtest runner (identical to optimize_v5.py _run_trial)
# ─────────────────────────────────────────────────────────────────────────────

async def _run_trial(
    ticker_cache: Dict[str, pd.DataFrame],
    spy_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
    params: BacktestParams,
) -> List[dict]:
    """Run full universe backtest with given params. Returns list of trade dicts."""
    tickers = [t for t in ticker_cache if t != "SPY"]
    if not tickers:
        return []

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def _run_one(ticker: str) -> List[dict]:
        async with sem:
            try:
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    ticker_df=ticker_cache[ticker],
                    spy_df=spy_df,
                    params=params,
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                logger.debug("Trial ticker %s failed: %s", ticker, exc)
                return []

    results = await asyncio.gather(*[_run_one(t) for t in tickers])
    all_trades: List[dict] = []
    for batch in results:
        all_trades.extend(batch)
    return all_trades
```

### Step 2: Run metrics tests

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py::test_objective_score_positive \
    tests/test_wfo_optuna.py::test_objective_score_penalty_low_trades \
    tests/test_wfo_optuna.py::test_objective_score_negative_expectancy \
    tests/test_wfo_optuna.py::test_spy_return_none_when_spy_none \
    tests/test_wfo_optuna.py::test_spy_return_computes_correctly \
    tests/test_wfo_optuna.py::test_compute_metrics_empty \
    tests/test_wfo_optuna.py::test_compute_metrics_basic \
    -v
```

Expected: all 7 PASS.

### Step 3: Commit

```bash
cd backend
git add wfo_optuna.py
git commit -m "feat(wfo): add metrics helpers, SPY return, objective score, data loader"
```

---

## Task 4: Param builders + frozen params

**Files:**
- Modify: `backend/wfo_optuna.py` (append after `_run_trial`)

### Step 1: Append to `wfo_optuna.py`

```python
# ─────────────────────────────────────────────────────────────────────────────
# Param builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_params(trial) -> BacktestParams:
    """Sample BacktestParams from Optuna trial. Search space identical to optimize_v5.py."""
    return BacktestParams(
        # ── Frozen at trial #433 ─────────────────────────────────────────────
        rs_threshold    = 0.066,
        cci_threshold   = -54.5,
        ema_distance    = 1.651,
        score_threshold = 2.50,
        breakout_weight = 1.724,
        pullback_weight = 1.842,
        tdl_bonus       = 1.016,
        vcp_bonus       = 1.370,
        cooldown_days   = 4,
        # ── Tunable ──────────────────────────────────────────────────────────
        tp_multiple     = trial.suggest_float("tp_multiple",     1.5,  6.0),
        brk_vol_mult    = trial.suggest_float("brk_vol_mult",    1.5,  3.5),
        brk_stop_atr    = trial.suggest_float("brk_stop_atr",    0.3,  2.0),
        brk_min_pct     = trial.suggest_float("brk_min_pct",     0.01, 0.05),
        brk_gap_pct     = trial.suggest_float("brk_gap_pct",     0.01, 0.08),
        brk_trail_mult  = trial.suggest_float("brk_trail_mult",  1.5,  8.0),
    )


def _build_params_from_values(values: dict) -> BacktestParams:
    """Reconstruct BacktestParams from Optuna best_trial.params dict.

    Frozen params fall back to trial #433 hardcoded values.
    Tunable params use .get(key, trial_433_default) so this also works
    when called with a partial dict (e.g. from --resume with missing keys).
    """
    return BacktestParams(
        # ── Frozen ───────────────────────────────────────────────────────────
        rs_threshold    = 0.066,
        cci_threshold   = -54.5,
        ema_distance    = 1.651,
        score_threshold = 2.50,
        breakout_weight = 1.724,
        pullback_weight = 1.842,
        tdl_bonus       = 1.016,
        vcp_bonus       = 1.370,
        cooldown_days   = 4,
        # ── Tunable (fall back to trial #433 defaults) ────────────────────
        tp_multiple     = values.get("tp_multiple",    4.3458),
        brk_vol_mult    = values.get("brk_vol_mult",   3.0161),
        brk_stop_atr    = values.get("brk_stop_atr",   1.6675),
        brk_min_pct     = values.get("brk_min_pct",    0.04333),
        brk_gap_pct     = values.get("brk_gap_pct",    0.01021),
        brk_trail_mult  = values.get("brk_trail_mult", 6.906),
    )


def _frozen_params() -> BacktestParams:
    """Return trial #433 params — current BacktestParams() defaults."""
    return BacktestParams()
```

### Step 2: Run param builder tests

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py::test_build_params_from_values_uses_provided \
    tests/test_wfo_optuna.py::test_build_params_from_values_frozen_defaults \
    tests/test_wfo_optuna.py::test_frozen_params_equals_defaults \
    -v
```

Expected: all 3 PASS.

### Step 3: Run full test suite so far

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py -v
```

Expected: all tests PASS (sparkline + windows + metrics + params).

### Step 4: Commit

```bash
cd backend
git add wfo_optuna.py
git commit -m "feat(wfo): add param builders and frozen params helper"
```

---

## Task 5: IS optimization function (`_optimize_window`)

**Files:**
- Modify: `backend/wfo_optuna.py` (append after `_frozen_params`)

### Step 1: Append to `wfo_optuna.py`

```python
# ─────────────────────────────────────────────────────────────────────────────
# Per-window IS optimization
# ─────────────────────────────────────────────────────────────────────────────

def _optimize_window(
    window_num:   int,
    is_start:     str,
    is_end:       str,
    ticker_cache: Dict[str, pd.DataFrame],
    spy_df:       Optional[pd.DataFrame],
    n_trials:     int,
    storage:      str,
    resume:       bool,
) -> Tuple[BacktestParams, dict, int, float]:
    """
    Run Optuna TPE on the IS period for one window.

    Returns
    -------
    best_params  : BacktestParams built from best trial values
    is_metrics   : metrics dict for IS period with best params
    best_trial_n : Optuna trial number of best trial
    best_score   : objective score of best trial
    """
    try:
        import optuna
    except ImportError:
        print("ERROR: optuna not installed. Run: pip install optuna")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study_name = f"wfo_v{window_num}"
    study = optuna.create_study(
        study_name=study_name,
        direction="maximize",
        storage=storage,
        load_if_exists=True,   # always safe — load_if_exists handles both new and resume
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    completed = [t for t in study.trials if t.state.name == "COMPLETE"]
    remaining = n_trials - len(completed)

    if resume and len(completed) > 0:
        print(
            f"  W{window_num}: Resuming — {len(completed)} completed, "
            f"{remaining} remaining.",
            flush=True,
        )

    if remaining <= 0:
        print(f"  W{window_num}: Already has {len(completed)} trials — skipping optimization.", flush=True)
    else:
        import time
        trial_times: List[float] = []

        def objective(trial) -> float:
            t0 = time.perf_counter()
            params  = _build_params(trial)
            trades  = asyncio.run(_run_trial(ticker_cache, spy_df, is_start, is_end, params))
            metrics = _compute_metrics(trades)
            score   = _objective_score(metrics)
            elapsed = time.perf_counter() - t0
            trial_times.append(elapsed)
            avg = sum(trial_times) / len(trial_times)
            done_so_far = len([t for t in study.trials if t.state.name == "COMPLETE"])
            eta_min = max(0, (n_trials - done_so_far) * avg / 60)
            print(
                f"  W{window_num} trial {trial.number:>4}  "
                f"score={score:>8.4f}  E={metrics['expectancy']:>+.4f}  "
                f"PF={metrics['profit_factor']:.3f}  N={metrics['total_trades']}  "
                f"port={metrics['portfolio_return_pct']:>+.1f}%  "
                f"{elapsed/60:.1f}min  ETA≈{eta_min:.0f}min",
                flush=True,
            )
            return score

        study.optimize(objective, n_trials=remaining, n_jobs=1, show_progress_bar=False)

    best       = study.best_trial
    best_params = _build_params_from_values(best.params)

    # Re-evaluate IS period with best params to get full metrics
    print(f"  W{window_num}: Re-evaluating IS with best params (trial #{best.number})…", flush=True)
    is_trades  = asyncio.run(_run_trial(ticker_cache, spy_df, is_start, is_end, best_params))
    is_metrics = _compute_metrics(is_trades)

    return best_params, is_metrics, best.number, best.value
```

### Step 2: Verify the function can be imported (no syntax errors)

```bash
cd backend
python3 -c "from wfo_optuna import _optimize_window; print('OK')"
```

Expected: `OK`

### Step 3: Commit

```bash
cd backend
git add wfo_optuna.py
git commit -m "feat(wfo): add _optimize_window IS Optuna optimization function"
```

---

## Task 6: Report printer

**Files:**
- Modify: `backend/wfo_optuna.py` (append after `_optimize_window`)

### Step 1: Append to `wfo_optuna.py`

```python
# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(results: List[WindowOptResult]) -> None:
    W = 90
    print(f"\n{'═' * W}")
    print(f"  WALK-FORWARD OPTUNA VALIDATION REPORT  "
          f"({len(results)} windows, {datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'═' * W}")

    # ── Section A: OOS performance table ─────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION A — OOS PERFORMANCE  (optimized IS params vs frozen #433)")
    print(f"  {'─' * (W - 2)}")
    hdr = f"  {'Win':<4} {'OOS Period':<25} {'Params':<10} {'N':>5} {'WR%':>6} {'E(R)':>8} {'PF':>6} {'MaxDD':>7} {'Port%':>7} {'SPY%':>7} {'Alpha':>7}"
    print(hdr)
    print(f"  {'─'*4} {'─'*25} {'─'*10} {'─'*5} {'─'*6} {'─'*8} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*7}")

    def _row(win_num, oos_start, oos_end, label, m, spy_pct):
        period = f"{oos_start} → {oos_end}"
        n   = m["total_trades"]
        wr  = m["win_rate"]
        ex  = m["expectancy"]
        pf  = m["profit_factor"]
        dd  = m["max_drawdown_r"]
        pr  = m["portfolio_return_pct"]
        spy = f"{spy_pct*100:>+.1f}" if spy_pct is not None else "  N/A"
        alpha = f"{pr - spy_pct*100:>+.1f}" if spy_pct is not None else "  N/A"
        print(
            f"  {win_num:<4} {period:<25} {label:<10} {n:>5} {wr:>6.1f} "
            f"{ex:>+8.4f} {pf:>6.3f} {dd:>7.2f} {pr:>+7.1f} {spy:>7} {alpha:>7}"
        )

    for r in results:
        _row(r.window_num, r.oos_start, r.oos_end, "optimized", r.oos_metrics, r.spy_pct)
        _row(r.window_num, r.oos_start, r.oos_end, "frozen#433", r.frozen_metrics, r.spy_pct)
        print()

    # ── Section B: Combined OOS equity sparklines ─────────────────────────────
    print(f"  {'─' * (W - 2)}")
    print(f"  SECTION B — COMBINED OOS EQUITY CURVE  (compounded portfolio return per window)")
    print(f"  {'─' * (W - 2)}")

    opt_returns    = [r.oos_metrics["portfolio_return_pct"] for r in results]
    frozen_returns = [r.frozen_metrics["portfolio_return_pct"] for r in results]
    labels = [f"W{r.window_num}({r.oos_start[:4]})" for r in results]

    print(f"\n  Optimized : {_sparkline(opt_returns)}  {opt_returns}")
    print(f"  Frozen#433: {_sparkline(frozen_returns)}  {frozen_returns}")
    print(f"  Windows   : {labels}")

    # Cumulative compounded return (stitch OOS windows chronologically)
    opt_cum    = 1.0
    frozen_cum = 1.0
    for r in results:
        opt_cum    *= (1.0 + r.oos_metrics["portfolio_return_pct"] / 100.0)
        frozen_cum *= (1.0 + r.frozen_metrics["portfolio_return_pct"] / 100.0)

    print(f"\n  Cumulative OOS return (optimized) : {(opt_cum - 1)*100:>+.1f}%")
    print(f"  Cumulative OOS return (frozen#433): {(frozen_cum - 1)*100:>+.1f}%")

    # SPY cumulative
    all_spy = [r.spy_pct for r in results if r.spy_pct is not None]
    if all_spy:
        spy_cum = 1.0
        for s in all_spy:
            spy_cum *= (1.0 + s)
        print(f"  SPY cumulative (OOS windows only) : {(spy_cum - 1)*100:>+.1f}%")

    # ── Section C: Parameter stability table ─────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION C — PARAMETER STABILITY  (tuned values across IS windows)")
    print(f"  {'─' * (W - 2)}")

    import statistics
    hdr2 = f"\n  {'Param':<20}" + "".join(f"{'W'+str(r.window_num)+'-best':>12}" for r in results)
    hdr2 += f"{'mean':>10} {'std':>8} {'CV':>6}  {'stable?':>8}"
    print(hdr2)
    print(f"  {'─'*20}" + "─" * (12 * len(results) + 34))

    for param in TUNABLE_PARAMS:
        vals = [r.best_params.get(param, float("nan")) for r in results]
        valid = [v for v in vals if not math.isnan(v)]
        if not valid:
            continue
        mean = statistics.mean(valid)
        std  = statistics.stdev(valid) if len(valid) > 1 else 0.0
        cv   = abs(std / mean) if mean != 0 else 0.0
        stable = "✓ stable" if cv < 0.15 else ("⚠ moderate" if cv < 0.30 else "✗ SENSITIVE")
        row = f"  {param:<20}" + "".join(f"{v:>12.4f}" for v in vals)
        row += f"{mean:>10.4f} {std:>8.4f} {cv:>6.3f}  {stable:>8}"
        print(row)

    print(f"\n  CV < 0.15 = stable   CV 0.15–0.30 = moderate   CV > 0.30 = regime-sensitive")

    # ── Section D: Robustness verdict ─────────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION D — ROBUSTNESS VERDICT")
    print(f"  {'─' * (W - 2)}\n")

    oos_exps    = [r.oos_metrics["expectancy"] for r in results]
    is_exps     = [r.is_metrics["expectancy"]  for r in results]
    oos_pfs     = [r.oos_metrics["profit_factor"] for r in results]

    avg_is_exp  = sum(is_exps)  / len(is_exps)  if is_exps  else 0
    avg_oos_exp = sum(oos_exps) / len(oos_exps) if oos_exps else 0
    avg_oos_pf  = sum(oos_pfs)  / len(oos_pfs)  if oos_pfs  else 0

    degradation = (
        (avg_is_exp - avg_oos_exp) / abs(avg_is_exp) * 100
        if avg_is_exp != 0 else 0.0
    )

    all_positive = all(e > 0 for e in oos_exps)
    all_pf_gt1   = all(p > 1.0 for p in oos_pfs)
    worst_dd     = min(r.oos_metrics["max_drawdown_r"] for r in results)

    print(f"  Avg IS expectancy           : {avg_is_exp:>+.4f} R")
    print(f"  Avg OOS expectancy          : {avg_oos_exp:>+.4f} R")
    print(f"  Avg OOS profit factor       : {avg_oos_pf:>6.3f}")
    print(f"  OOS degradation vs IS       : {degradation:>+.1f}%")
    print(f"  Worst OOS drawdown          : {worst_dd:>.2f} R")
    print(f"  All OOS windows profitable? : {'YES' if all_positive else 'NO'}")
    print(f"  All OOS windows PF > 1.0?   : {'YES' if all_pf_gt1 else 'NO'}")
    print()

    if all_positive and all_pf_gt1:
        if degradation < 30:
            verdict = "ROBUST — strategy generalises well across regimes"
        elif degradation < 60:
            verdict = "MODERATE — some regime sensitivity; monitor live performance"
        else:
            verdict = "OVERFIT — large OOS degradation; re-examine search space"
    else:
        verdict = "FRAGILE — OOS expectancy negative in ≥1 window; do not trade live"

    print(f"  Verdict: {verdict}")
    print(f"\n{'═' * W}\n")
```

### Step 2: Verify import + no syntax errors

```bash
cd backend
python3 -c "from wfo_optuna import _print_report; print('OK')"
```

Expected: `OK`

### Step 3: Commit

```bash
cd backend
git add wfo_optuna.py
git commit -m "feat(wfo): add _print_report with 4-section WFO report"
```

---

## Task 7: `main()`, CLI, JSON output

**Files:**
- Modify: `backend/wfo_optuna.py` (append at end, followed by `if __name__ == "__main__"`)

### Step 1: Append `main()` to `wfo_optuna.py`

```python
# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-Forward Optuna Validation")
    parser.add_argument(
        "--trials", type=int, default=100,
        help="Optuna trials per IS window (default: 100)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume existing Optuna studies instead of creating fresh",
    )
    parser.add_argument(
        "--windows", type=str, default="1,2,3,4",
        help="Comma-separated window numbers to run (default: 1,2,3,4)",
    )
    args = parser.parse_args()

    selected = {int(w) for w in args.windows.split(",")}
    windows_to_run = [w for w in WFO_WINDOWS if w[0] in selected]

    if not windows_to_run:
        print(f"ERROR: no valid windows in --windows={args.windows!r}  (valid: 1,2,3,4)")
        sys.exit(1)

    # ── 1. Load price data ────────────────────────────────────────────────────
    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR
    ticker_cache, spy_df = _load_universe_cache(cache_dir)

    if len(ticker_cache) < 10:
        print("ERROR: fewer than 10 tickers in cache.")
        print("  Run:  python3 -c \"from wfo_cache import download_and_cache; ...\"")
        sys.exit(1)

    print(f"\nWalk-Forward Optuna Validation")
    print(f"  Windows  : {[w[0] for w in windows_to_run]}")
    print(f"  IS trials: {args.trials} per window")
    print(f"  Universe : {len(ticker_cache)} tickers")
    print(f"  Resume   : {args.resume}")
    print()

    all_results: List[WindowOptResult] = []

    # ── 2. Per-window loop ────────────────────────────────────────────────────
    for window_num, is_start, is_end, oos_start, oos_end in windows_to_run:
        storage = f"sqlite:///{_DATA_DIR}/wfo_w{window_num}.db"

        print(f"\n{'═' * 70}")
        print(f"  Window {window_num}: IS {is_start}→{is_end}  |  OOS {oos_start}→{oos_end}")
        print(f"{'═' * 70}")

        # ── 2a. IS Optuna optimization ────────────────────────────────────────
        print(f"\n[IS] Running {args.trials} Optuna trials…", flush=True)
        t0_is = datetime.now()
        best_params, is_metrics, best_trial_n, best_score = _optimize_window(
            window_num, is_start, is_end,
            ticker_cache, spy_df, args.trials, storage, args.resume,
        )
        elapsed_is = (datetime.now() - t0_is).total_seconds() / 60
        print(
            f"\n[IS] Done in {elapsed_is:.1f}min  "
            f"best trial #{best_trial_n}  score={best_score:.4f}  "
            f"E={is_metrics['expectancy']:+.4f}  PF={is_metrics['profit_factor']:.3f}  "
            f"N={is_metrics['total_trades']}",
            flush=True,
        )

        # ── 2b. OOS with optimized params ─────────────────────────────────────
        print(f"\n[OOS-opt] Evaluating OOS with optimized params…", flush=True)
        oos_trades = asyncio.run(
            _run_trial(ticker_cache, spy_df, oos_start, oos_end, best_params)
        )
        oos_metrics = _compute_metrics(oos_trades)
        print(
            f"[OOS-opt] E={oos_metrics['expectancy']:+.4f}  "
            f"PF={oos_metrics['profit_factor']:.3f}  "
            f"N={oos_metrics['total_trades']}  "
            f"port={oos_metrics['portfolio_return_pct']:+.1f}%",
            flush=True,
        )

        # ── 2c. OOS with frozen #433 params ───────────────────────────────────
        print(f"\n[OOS-frz] Evaluating OOS with frozen #433 params…", flush=True)
        frozen = _frozen_params()
        frozen_trades = asyncio.run(
            _run_trial(ticker_cache, spy_df, oos_start, oos_end, frozen)
        )
        frozen_metrics = _compute_metrics(frozen_trades)
        print(
            f"[OOS-frz] E={frozen_metrics['expectancy']:+.4f}  "
            f"PF={frozen_metrics['profit_factor']:.3f}  "
            f"N={frozen_metrics['total_trades']}  "
            f"port={frozen_metrics['portfolio_return_pct']:+.1f}%",
            flush=True,
        )

        spy_pct = _spy_return(spy_df, oos_start, oos_end)
        if spy_pct is not None:
            print(f"[SPY]     OOS period return: {spy_pct*100:+.1f}%", flush=True)

        # ── 2d. Collect best_params as plain dict ─────────────────────────────
        best_params_dict = {p: getattr(best_params, p) for p in TUNABLE_PARAMS}

        all_results.append(WindowOptResult(
            window_num=window_num,
            is_start=is_start, is_end=is_end,
            oos_start=oos_start, oos_end=oos_end,
            best_trial=best_trial_n,
            best_score=best_score,
            best_params=best_params_dict,
            is_metrics=is_metrics,
            oos_metrics=oos_metrics,
            frozen_metrics=frozen_metrics,
            spy_pct=spy_pct,
        ))

    # ── 3. Final report ───────────────────────────────────────────────────────
    _print_report(all_results)

    # ── 4. Save JSON ──────────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now().isoformat(),
        "n_trials": args.trials,
        "windows": [
            {
                "window_num":     r.window_num,
                "is_start":       r.is_start,
                "is_end":         r.is_end,
                "oos_start":      r.oos_start,
                "oos_end":        r.oos_end,
                "best_trial":     r.best_trial,
                "best_score":     r.best_score,
                "best_params":    r.best_params,
                "is_metrics":     r.is_metrics,
                "oos_metrics":    r.oos_metrics,
                "frozen_metrics": r.frozen_metrics,
                "spy_pct":        r.spy_pct,
            }
            for r in all_results
        ],
    }
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
```

### Step 2: Verify CLI help works (no import errors)

```bash
cd backend
python3 wfo_optuna.py --help
```

Expected output:
```
usage: wfo_optuna.py [-h] [--trials TRIALS] [--resume] [--windows WINDOWS]
...
```

### Step 3: Run full test suite

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py -v
```

Expected: all tests PASS.

### Step 4: Commit

```bash
cd backend
git add wfo_optuna.py
git commit -m "feat(wfo): add main() CLI with per-window optimization, OOS eval, JSON output"
```

---

## Task 8: Final smoke test and integration verification

**Files:**
- No new files. Verify `wfo_optuna.py` end-to-end with a single window subset.

### Step 1: Check parquet cache exists

```bash
ls backend/data/price_cache/*.parquet 2>/dev/null | wc -l
```

Expected: a number > 0 (if 0, the WFO cache hasn't been downloaded yet — this is fine, integration test uses mock below).

### Step 2: Verify the full test suite passes (including existing tests)

```bash
cd backend
python3 -m pytest tests/test_wfo_optuna.py tests/test_wfo_engine.py tests/test_wfo_cache.py -v
```

Expected: all tests PASS.

### Step 3: Smoke-test with `--help` and module import

```bash
cd backend
python3 -c "
import wfo_optuna as w
print('WFO_WINDOWS:', len(w.WFO_WINDOWS))
print('TUNABLE_PARAMS:', w.TUNABLE_PARAMS)
print('sparkline test:', w._sparkline([1.0, 2.0, 3.0, 2.5, 1.5]))
p = w._frozen_params()
print('frozen tp_multiple:', p.tp_multiple)
print('All OK')
"
```

Expected:
```
WFO_WINDOWS: 4
TUNABLE_PARAMS: ['tp_multiple', 'brk_vol_mult', 'brk_stop_atr', 'brk_min_pct', 'brk_gap_pct', 'brk_trail_mult']
sparkline test: ▁▄▇▅▂  (or similar)
frozen tp_multiple: 4.3458
All OK
```

### Step 4: Final commit

```bash
cd backend
git add wfo_optuna.py tests/test_wfo_optuna.py
git commit -m "feat(wfo): complete wfo_optuna.py implementation with full test coverage"
```

---

## Running the full WFO

Once implementation is complete:

```bash
# Run all 4 windows, 100 trials each (~70-94 hrs total)
cd backend
python3 wfo_optuna.py --trials 100

# Resume after interruption
python3 wfo_optuna.py --trials 100 --resume

# Run only specific windows (e.g. to parallelize across machines)
python3 wfo_optuna.py --trials 100 --windows 1,2
python3 wfo_optuna.py --trials 100 --windows 3,4

# Quick smoke test (5 trials, single window)
python3 wfo_optuna.py --trials 5 --windows 1
```

Results saved to `data/wfo_optuna_results.json` and Optuna DBs at `data/wfo_w1.db`…`data/wfo_w4.db`.
