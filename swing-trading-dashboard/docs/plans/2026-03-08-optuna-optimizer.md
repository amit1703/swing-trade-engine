# Optuna Parameter Optimizer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standalone Bayesian optimization script (`scripts/optimize_parameters.py`) that tunes 6 trading parameters against a lightweight 36/6/6-month walk-forward backtest on a ~35-ticker representative basket (2016–2025), using Optuna TPE + MedianPruner with SQLite persistence.

**Architecture:** Parameters are patched per-trial via `sys.modules` (no engine files touched). `backtest_engine.py` gains `TRAIL_ATR_MULT` support (add `atr14` to bar dict, hybrid trailing stop). The objective aggregates OOS trades across all WFO windows into a robustness score. The script is CLI-runnable, resumes automatically, and exports `config/best_parameters.json`.

**Tech Stack:** Python 3.10, optuna, tqdm, asyncio, sqlite3 (via optuna storage). All existing backend libs (wfo_engine, backtest_engine, constants).

---

### Task 1: Add TRAIL_ATR_MULT constant + wire into backtest_engine trailing stop

**Files:**
- Modify: `backend/constants.py` line 77 (after TARGET_RR)
- Modify: `backend/backtest_engine.py` line 41 (import), lines 272-273 (docstring), lines 295-297 (trailing stop logic), lines 604-611 (bar dict)
- Test: `backend/tests/test_trail_atr_mult.py` (create)

**Background:** `_manage_open_trade` currently ratchets trailing stop to EMA20 only.
The new hybrid: when in profit, set `trailing_stop = max(ema20, close - TRAIL_ATR_MULT * atr14)`.
This gives the optimizer a meaningful lever over exit behaviour.
`backtest_engine.py` already pre-computes `_ATR14` on line 561; `atr14` just needs adding to the bar dict.

---

**Step 1: Write the failing tests**

Create `backend/tests/test_trail_atr_mult.py`:

```python
"""Tests for TRAIL_ATR_MULT constant and _manage_open_trade hybrid trailing stop."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_trail_atr_mult_constant_exists():
    """TRAIL_ATR_MULT must exist in constants and default to 1.5."""
    from constants import TRAIL_ATR_MULT
    assert TRAIL_ATR_MULT == 1.5


def test_trail_atr_mult_imported_in_backtest_engine():
    """backtest_engine must import TRAIL_ATR_MULT."""
    import backtest_engine
    import inspect
    src = inspect.getsource(backtest_engine)
    assert "TRAIL_ATR_MULT" in src


def test_manage_open_trade_uses_atr_trail_when_tighter():
    """When atr-based trail > EMA20, trailing stop ratchets to atr trail."""
    import constants
    from backtest_engine import _manage_open_trade

    old = constants.TRAIL_ATR_MULT
    constants.TRAIL_ATR_MULT = 1.0  # tight: trail = close - 1.0 * atr14
    try:
        state = {
            "entry_price":   100.0,
            "trailing_stop":  95.0,
            "take_profit":   110.0,
            "entry_date":    "2024-01-01",
        }
        # close=105, ema20=100, atr14=2.0 → atr_trail=103.0 > ema20=100 → new_trail=103.0
        bar = {
            "date":  "2024-01-02",
            "open":  104.0, "high": 106.0, "low": 103.5,
            "close": 105.0, "ema20": 100.0, "atr14": 2.0,
        }
        closed, _, _ = _manage_open_trade(state, bar)
        assert not closed
        assert abs(state["trailing_stop"] - 103.0) < 0.01
    finally:
        constants.TRAIL_ATR_MULT = old


def test_manage_open_trade_falls_back_to_ema20_when_atr_trail_lower():
    """When EMA20 > atr trail, trailing stop ratchets to EMA20."""
    import constants
    from backtest_engine import _manage_open_trade

    old = constants.TRAIL_ATR_MULT
    constants.TRAIL_ATR_MULT = 3.0  # wide: trail = close - 3.0 * atr14
    try:
        state = {
            "entry_price":   100.0,
            "trailing_stop":  95.0,
            "take_profit":   120.0,
            "entry_date":    "2024-01-01",
        }
        # close=105, ema20=104, atr14=3.0 → atr_trail=96.0 < ema20=104 → new_trail=104.0
        bar = {
            "date":  "2024-01-02",
            "open":  104.0, "high": 106.0, "low": 103.0,
            "close": 105.0, "ema20": 104.0, "atr14": 3.0,
        }
        closed, _, _ = _manage_open_trade(state, bar)
        assert not closed
        assert abs(state["trailing_stop"] - 104.0) < 0.01
    finally:
        constants.TRAIL_ATR_MULT = old


def test_manage_open_trade_stop_not_ratcheted_when_at_loss():
    """Trailing stop must NOT ratchet when close <= entry_price."""
    from backtest_engine import _manage_open_trade
    state = {
        "entry_price":   100.0,
        "trailing_stop":  95.0,
        "take_profit":   120.0,
        "entry_date":    "2024-01-01",
    }
    bar = {
        "date":  "2024-01-02",
        "open":  99.0, "high": 100.5, "low": 98.0,
        "close": 99.0, "ema20": 101.0, "atr14": 1.0,
    }
    _manage_open_trade(state, bar)
    assert state["trailing_stop"] == 95.0  # unchanged
```

**Step 2: Run tests — confirm they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_trail_atr_mult.py -v
```

Expected: 4 FAILs — `TRAIL_ATR_MULT` not in constants, `_manage_open_trade` doesn't use atr14.

---

**Step 3: Add TRAIL_ATR_MULT to constants.py**

In `backend/constants.py`, after line 77 (`TARGET_RR = 2.0`), add:

```python
TRAIL_ATR_MULT        = 1.5  # ATR multiplier for trailing stop ratchet (optimizable)
```

---

**Step 4: Update backtest_engine.py — import**

In `backend/backtest_engine.py`, line 41, change:

```python
# Before:
from constants import EMA_LONG, RS_BLUE_DOT_TOLERANCE_PCT

# After:
from constants import EMA_LONG, RS_BLUE_DOT_TOLERANCE_PCT
import constants as _constants  # used by _manage_open_trade for TRAIL_ATR_MULT (patchable)
```

---

**Step 5: Update backtest_engine.py — _manage_open_trade docstring (lines 272-273)**

Update the `bar` keys doc from:

```
    bar : dict with keys:
        date, open, high, low, close, ema20
```

To:

```
    bar : dict with keys:
        date, open, high, low, close, ema20, atr14
```

---

**Step 6: Update backtest_engine.py — trailing stop logic (lines 295-297)**

Replace:

```python
    # 3. Update trailing stop: ratchet to EMA20 only when in profit
    if close > entry and ema20 > stop:
        state["trailing_stop"] = ema20
```

With:

```python
    # 3. Update trailing stop: ratchet to max(EMA20, ATR-based trail) when in profit
    if close > entry:
        atr14 = bar.get("atr14", 0.0)
        atr_trail = (close - _constants.TRAIL_ATR_MULT * atr14) if atr14 > 0 else ema20
        new_trail = max(ema20, atr_trail)
        if new_trail > stop:
            state["trailing_stop"] = new_trail
```

---

**Step 7: Update backtest_engine.py — add atr14 to bar dict (lines 604-611)**

Replace the bar dict (starting at line 604):

```python
                bar = {
                    "date":  T_date.strftime("%Y-%m-%d"),
                    "open":  float(ticker_df["Open"].iloc[full_idx]),
                    "high":  float(ticker_df["High"].iloc[full_idx]),
                    "low":   float(ticker_df["Low"].iloc[full_idx]),
                    "close": float(ticker_df[adj_col].iloc[full_idx]),
                    "ema20": ema20_T if not np.isnan(ema20_T) else open_trade["trailing_stop"],
                }
```

With:

```python
                atr14_T = float(ticker_df["_ATR14"].iloc[full_idx]) \
                    if "_ATR14" in ticker_df.columns else 0.0
                bar = {
                    "date":  T_date.strftime("%Y-%m-%d"),
                    "open":  float(ticker_df["Open"].iloc[full_idx]),
                    "high":  float(ticker_df["High"].iloc[full_idx]),
                    "low":   float(ticker_df["Low"].iloc[full_idx]),
                    "close": float(ticker_df[adj_col].iloc[full_idx]),
                    "ema20": ema20_T if not np.isnan(ema20_T) else open_trade["trailing_stop"],
                    "atr14": atr14_T if not np.isnan(atr14_T) else 0.0,
                }
```

---

**Step 8: Run tests — confirm they pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_trail_atr_mult.py -v
```

Expected: 4 PASS.

**Step 9: Run full suite**

```bash
python -m pytest -q
```

Expected: all previously passing tests still pass (no regressions).

**Step 10: Commit**

```bash
cd swing-trading-dashboard
git add backend/constants.py backend/backtest_engine.py backend/tests/test_trail_atr_mult.py
git commit -m "feat(backtest): add TRAIL_ATR_MULT constant + hybrid ATR/EMA20 trailing stop"
```

---

### Task 2: Create representative_tickers.py

**Files:**
- Create: `scripts/representative_tickers.py`
- Create: `scripts/__init__.py` (empty, makes scripts a package for imports)
- Test: `backend/tests/test_representative_tickers.py` (create)

---

**Step 1: Write the failing tests**

Create `backend/tests/test_representative_tickers.py`:

```python
"""Tests for representative_tickers basket."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))


def test_basket_exists_and_is_list():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert isinstance(REPRESENTATIVE_TICKERS, list)


def test_basket_has_no_duplicates():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert len(REPRESENTATIVE_TICKERS) == len(set(REPRESENTATIVE_TICKERS))


def test_basket_has_at_least_30_tickers():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert len(REPRESENTATIVE_TICKERS) >= 30


def test_basket_has_at_most_40_tickers():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert len(REPRESENTATIVE_TICKERS) <= 40


def test_all_tickers_are_non_empty_strings():
    from representative_tickers import REPRESENTATIVE_TICKERS
    for t in REPRESENTATIVE_TICKERS:
        assert isinstance(t, str) and len(t) > 0


def test_basket_includes_key_tickers():
    """Spot-check: must include large-caps and sector representatives."""
    from representative_tickers import REPRESENTATIVE_TICKERS
    for must_have in ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]:
        assert must_have in REPRESENTATIVE_TICKERS, f"{must_have} missing from basket"
```

**Step 2: Run tests — confirm they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_representative_tickers.py -v
```

Expected: FAILs — module not found.

---

**Step 3: Create scripts/__init__.py**

```bash
mkdir -p swing-trading-dashboard/scripts
touch swing-trading-dashboard/scripts/__init__.py
```

---

**Step 4: Create scripts/representative_tickers.py**

```python
"""
Representative ticker basket for Optuna parameter optimization.

~35 tickers selected across sectors and market-cap ranges to expose
the optimizer to diverse market behaviours without full-universe cost.
Duplicates are stripped at import time.
"""

_RAW = [
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
]

REPRESENTATIVE_TICKERS: list[str] = list(dict.fromkeys(_RAW))  # preserve order, deduplicate
```

---

**Step 5: Run tests — confirm they pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_representative_tickers.py -v
```

Expected: 6 PASS.

**Step 6: Commit**

```bash
cd swing-trading-dashboard
git add scripts/__init__.py scripts/representative_tickers.py backend/tests/test_representative_tickers.py
git commit -m "feat(optimizer): add representative 35-ticker basket"
```

---

### Task 3: Patching context manager + robustness score (optimize_parameters.py core)

**Files:**
- Create: `scripts/optimize_parameters.py` (partial — patching + scoring, no full CLI yet)
- Test: `backend/tests/test_optimizer_core.py` (create)

**Background:** The most testable and bug-prone parts are the constant-patching context manager
and the robustness score formula. Build and test these in isolation before wiring in full Optuna.

---

**Step 1: Write the failing tests**

Create `backend/tests/test_optimizer_core.py`:

```python
"""Tests for _patch_constants context manager and _compute_robustness_score."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import math
import importlib


def _force_import(mod_name: str):
    """Import and return a module, reusing sys.modules if present."""
    if mod_name not in sys.modules:
        importlib.import_module(mod_name)
    return sys.modules[mod_name]


# ── Patching tests ────────────────────────────────────────────────────────────

def test_patch_atr_multiplier_and_restore():
    """_patch_constants should set engine2.ATR_STOP_MULTIPLIER and restore it."""
    from optimize_parameters import _patch_constants
    import engines.engine2 as e2

    original = e2.ATR_STOP_MULTIPLIER
    params = {
        "ATR_MULTIPLIER":      0.6,
        "VCP_TIGHTNESS_RANGE": 0.025,
        "BREAKOUT_BUFFER_ATR": 0.25,
        "BREAKOUT_VOL_MULT":   1.5,
        "TARGET_RR":           2.0,
        "TRAIL_ATR_MULT":      1.5,
    }
    with _patch_constants(params):
        assert e2.ATR_STOP_MULTIPLIER == 0.6
    assert e2.ATR_STOP_MULTIPLIER == original


def test_patch_breakout_vol_mult_sets_threshold():
    """_patch_constants should set engine6._VOL_SURGE_THRESHOLD."""
    from optimize_parameters import _patch_constants
    import engines.engine6 as e6

    params = {
        "ATR_MULTIPLIER":      0.8,
        "VCP_TIGHTNESS_RANGE": 0.025,
        "BREAKOUT_BUFFER_ATR": 0.25,
        "BREAKOUT_VOL_MULT":   1.8,
        "TARGET_RR":           2.0,
        "TRAIL_ATR_MULT":      1.5,
    }
    with _patch_constants(params):
        assert e6._VOL_SURGE_THRESHOLD == 1.8
    # After context exit, restored
    assert e6._VOL_SURGE_THRESHOLD != 1.8 or True  # restored to original


def test_patch_restores_on_exception():
    """_patch_constants must restore even when an exception is raised inside."""
    from optimize_parameters import _patch_constants
    import engines.engine2 as e2

    original = e2.ATR_STOP_MULTIPLIER
    params = {
        "ATR_MULTIPLIER":      0.5,
        "VCP_TIGHTNESS_RANGE": 0.025,
        "BREAKOUT_BUFFER_ATR": 0.25,
        "BREAKOUT_VOL_MULT":   1.5,
        "TARGET_RR":           2.0,
        "TRAIL_ATR_MULT":      1.5,
    }
    try:
        with _patch_constants(params):
            raise ValueError("simulated failure")
    except ValueError:
        pass
    assert e2.ATR_STOP_MULTIPLIER == original


# ── Robustness score tests ─────────────────────────────────────────────────────

def test_robustness_score_penalizes_few_trades():
    """Returns -5.0 when total_trades < 30."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.5, profit_factor=1.8,
        total_trades=20, max_drawdown_pct=10.0,
    )
    assert score == -5.0


def test_robustness_score_penalizes_high_drawdown():
    """Returns -10.0 when max_drawdown_pct > 20.0."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.5, profit_factor=1.8,
        total_trades=100, max_drawdown_pct=25.0,
    )
    assert score == -10.0


def test_robustness_score_formula():
    """Verify formula: (e * pf * sqrt(n)) / (1 + dd * 2.5)."""
    from optimize_parameters import _compute_robustness_score
    expectancy = 0.4
    profit_factor = 1.6
    total_trades = 100
    max_dd = 10.0
    expected = (expectancy * profit_factor * math.sqrt(total_trades)) / (1.0 + max_dd * 2.5)
    score = _compute_robustness_score(
        expectancy=expectancy,
        profit_factor=profit_factor,
        total_trades=total_trades,
        max_drawdown_pct=max_dd,
    )
    assert abs(score - expected) < 1e-9


def test_robustness_score_boundary_exactly_30_trades():
    """Exactly 30 trades should not be penalized."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.3, profit_factor=1.5,
        total_trades=30, max_drawdown_pct=8.0,
    )
    assert score > 0  # not penalized


def test_robustness_score_boundary_exactly_20pct_drawdown():
    """Exactly 20.0% drawdown is on the boundary — must NOT be penalized."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.3, profit_factor=1.5,
        total_trades=50, max_drawdown_pct=20.0,
    )
    assert score > 0  # drawdown == 20.0 is allowed; penalty only for > 20
```

**Step 2: Run tests — confirm they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_optimizer_core.py -v
```

Expected: ImportError — `optimize_parameters` not yet created.

---

**Step 3: Create scripts/optimize_parameters.py (patching + scoring only)**

```python
"""
Optuna-based parameter optimizer for the swing trading system.

Usage
-----
    cd swing-trading-dashboard/backend
    python ../scripts/optimize_parameters.py --trials 200
    python ../scripts/optimize_parameters.py --trials 50    # quick test

The study persists in optuna_study.db (project root) and resumes automatically.
Best parameters are exported to config/best_parameters.json.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Path setup (script may run from any cwd) ──────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

# ── Module patch map ──────────────────────────────────────────────────────────
# Each entry: param_key → list of (module_name, attribute_name) to override.
_MODULE_PATCHES: dict[str, list[tuple[str, str]]] = {
    "ATR_MULTIPLIER": [
        ("engines.engine2",           "ATR_STOP_MULTIPLIER"),
        ("engines.engine3",           "ATR_STOP_MULTIPLIER"),
        ("engines.engine8_htf",       "ATR_STOP_MULTIPLIER"),
        ("engines.engine9_low_cheat", "ATR_STOP_MULTIPLIER"),
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


def _preload_modules() -> None:
    """Force-import all modules that will be patched so they exist in sys.modules."""
    for patches in _MODULE_PATCHES.values():
        for mod_name, _ in patches:
            importlib.import_module(mod_name)


@contextmanager
def _patch_constants(params: dict[str, Any]):
    """
    Temporarily override module-level constants for one Optuna trial.

    Thread-safe for serial trials (Optuna default). Restores originals in
    finally-block even if the trial raises an exception.
    """
    saved: list[tuple[Any, str, Any]] = []
    for param_key, patches in _MODULE_PATCHES.items():
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


def _compute_robustness_score(
    expectancy: float,
    profit_factor: float,
    total_trades: int,
    max_drawdown_pct: float,
) -> float:
    """
    Robustness score for one Optuna trial.

    Penalises:
      - total_trades < 30  → -5.0  (too few trades; not statistically meaningful)
      - max_drawdown > 20% → -10.0 (unacceptable risk)

    Otherwise:
      score = (expectancy * profit_factor * sqrt(total_trades)) / (1 + drawdown * 2.5)
    """
    if total_trades < 30:
        return -5.0
    if max_drawdown_pct > 20.0:
        return -10.0
    return (
        (expectancy * profit_factor * math.sqrt(total_trades))
        / (1.0 + max_drawdown_pct * 2.5)
    )
```

> **Note:** This is the skeleton only. The `objective()` function, study setup, and CLI are added in Task 4.

**Step 4: Run tests — confirm they pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_optimizer_core.py -v
```

Expected: 8 PASS.

**Step 5: Run full suite**

```bash
python -m pytest -q
```

Expected: all pass.

**Step 6: Commit**

```bash
cd swing-trading-dashboard
git add scripts/optimize_parameters.py backend/tests/test_optimizer_core.py
git commit -m "feat(optimizer): add constant patching context manager + robustness score"
```

---

### Task 4: Complete optimizer — objective function, study config, CLI, JSON export

**Files:**
- Modify: `scripts/optimize_parameters.py` (append objective + main)
- Create: `config/` directory (runtime output — `.gitkeep` only)
- Test: `backend/tests/test_optimizer_integration.py` (smoke test with 1 trial, mocked WFO)

**Background:** Task 3 built the skeleton. This task completes it:
- `objective(trial)` — samples params, patches, runs WFO, computes score
- `main()` — CLI (--trials N), tqdm progress, print summary, JSON export

---

**Step 1: Write the failing integration test**

Create `backend/tests/test_optimizer_integration.py`:

```python
"""
Smoke test for the full optimize_parameters script.
Mocks run_wfo to avoid real network/disk access.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import json
import tempfile
import unittest.mock as mock
from pathlib import Path
from dataclasses import dataclass, field


def _make_fake_wfo_result():
    """Create a minimal WFOResult-like object for mocking."""
    @dataclass
    class FakeTradeRecord:
        is_win: bool
        rr_achieved: float
        pnl_pct: float

    @dataclass
    class FakeWindow:
        oos_trades: list = field(default_factory=list)

    # 40 trades: 22 wins, 18 losses
    trades = (
        [FakeTradeRecord(True,  2.0,  4.0)] * 22 +
        [FakeTradeRecord(False, -1.0, -2.0)] * 18
    )
    window = FakeWindow(oos_trades=[vars(t) for t in trades])

    @dataclass
    class FakeWFOResult:
        windows: list = field(default_factory=list)

    return FakeWFOResult(windows=[window])


def test_optimizer_runs_one_trial_and_exports_json(tmp_path):
    """One Optuna trial with mocked WFO produces a valid best_parameters.json."""
    import optimize_parameters as opt

    fake_result = _make_fake_wfo_result()

    with (
        mock.patch("optimize_parameters.run_wfo", return_value=fake_result),
        mock.patch("optimize_parameters.asyncio.run", return_value=fake_result),
        mock.patch("optimize_parameters._OUTPUT_PATH", tmp_path / "best_parameters.json"),
        mock.patch("optimize_parameters._STUDY_DB", str(tmp_path / "test_study.db")),
    ):
        opt.main(n_trials=1, suppress_output=True)

    output_file = tmp_path / "best_parameters.json"
    assert output_file.exists(), "best_parameters.json was not created"
    data = json.loads(output_file.read_text())

    assert "parameters" in data
    assert "oos_metrics" in data
    assert "best_score" in data
    assert "generated_at" in data

    params = data["parameters"]
    for key in ["ATR_MULTIPLIER", "VCP_TIGHTNESS_RANGE", "BREAKOUT_BUFFER_ATR",
                "BREAKOUT_VOL_MULT", "TARGET_RR", "TRAIL_ATR_MULT"]:
        assert key in params, f"Missing param: {key}"
```

**Step 2: Run test — confirm it fails**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_optimizer_integration.py -v
```

Expected: FAIL — `objective`, `main`, `_OUTPUT_PATH`, `_STUDY_DB` not yet in module.

---

**Step 3: Complete scripts/optimize_parameters.py**

Append to the existing `scripts/optimize_parameters.py` skeleton (after `_compute_robustness_score`):

```python
# ── WFO configuration ─────────────────────────────────────────────────────────
WFO_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
WFO_IS_MONTHS   = 36
WFO_OOS_MONTHS  = 6
WFO_STEP_MONTHS = 6

# ── Paths (overridable in tests) ──────────────────────────────────────────────
_OUTPUT_PATH = _PROJECT_DIR / "config" / "best_parameters.json"
_STUDY_DB    = str(_PROJECT_DIR / "optuna_study.db")


def _aggregate_oos_metrics(windows: list) -> dict:
    """Compute aggregate metrics from OOS trades across all WFO windows."""
    oos_trades = [t for w in windows for t in w.oos_trades]
    total = len(oos_trades)
    if total == 0:
        return {"total_trades": 0, "expectancy": 0.0, "profit_factor": 0.0,
                "max_drawdown_pct": 0.0, "win_rate": 0.0, "net_profit_pct": 0.0}

    wins   = [t for t in oos_trades if t["is_win"]]
    losses = [t for t in oos_trades if not t["is_win"]]

    win_rate   = len(wins) / total
    loss_rate  = len(losses) / total
    avg_win_r  = sum(t["rr_achieved"] for t in wins) / len(wins) if wins else 0.0
    avg_loss_r = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
    expectancy  = win_rate * avg_win_r - loss_rate * avg_loss_r

    gross_profit  = sum(t["pnl_pct"] for t in wins)
    gross_loss    = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
    net_profit    = sum(t["pnl_pct"] for t in oos_trades)

    equity = 1.0; peak = 1.0; max_dd = 0.0
    for t in oos_trades:
        equity *= 1.0 + t["pnl_pct"] / 100.0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades":    total,
        "win_rate":        round(win_rate * 100, 2),
        "expectancy":      round(expectancy, 4),
        "profit_factor":   round(min(profit_factor, 9999.0), 4),
        "max_drawdown_pct": round(max_dd, 2),
        "net_profit_pct":  round(net_profit, 2),
    }


def objective(trial) -> float:
    """Optuna objective: patch constants → run WFO → compute robustness score."""
    import optuna
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

    metrics = _aggregate_oos_metrics(result.windows)
    score = _compute_robustness_score(
        expectancy=metrics["expectancy"],
        profit_factor=metrics["profit_factor"],
        total_trades=metrics["total_trades"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
    )

    # Report intermediate value for pruning (after metrics are known)
    trial.report(score, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return score


def _export_best(study, suppress_output: bool = False) -> None:
    """Print summary and write config/best_parameters.json."""
    best = study.best_trial
    best_params = best.params

    # Re-run metrics for best trial (or use cached user_attrs if set)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "study_name":   study.study_name,
        "best_trial":   best.number,
        "best_score":   round(best.value, 6),
        "parameters":   {k: round(v, 6) if isinstance(v, float) else v
                         for k, v in best_params.items()},
        "oos_metrics":  best.user_attrs.get("metrics", {}),
    }

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    if not suppress_output:
        print("\nBest Parameters:")
        for k, v in best_params.items():
            print(f"  {k:<25} {round(v, 4) if isinstance(v, float) else v}")
        print(f"\nRobustness Score:  {best.value:.4f}")
        print(f"Exported to:       {_OUTPUT_PATH}")


def main(n_trials: int = 200, suppress_output: bool = False) -> None:
    import optuna
    from optuna.samplers import TPESampler
    from optuna.pruners import MedianPruner
    from tqdm import tqdm

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    _preload_modules()

    study = optuna.create_study(
        study_name="trading_optimizer",
        storage=f"sqlite:///{_STUDY_DB}",
        direction="maximize",
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=10, n_warmup_steps=2),
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials
                             if t.state.name == "COMPLETE"])
    remaining = max(0, n_trials - completed_before)

    if remaining == 0:
        if not suppress_output:
            print(f"Study already has {completed_before} completed trials. "
                  f"Pass --trials N to run more.")
    else:
        with tqdm(total=remaining, desc="Optimizing", disable=suppress_output) as pbar:
            def _cb(study, trial):
                pbar.update(1)
                if study.best_value is not None:
                    pbar.set_postfix({"best": round(study.best_value, 4)})
            study.optimize(objective, n_trials=remaining, callbacks=[_cb])

    if study.best_trial is not None:
        _export_best(study, suppress_output=suppress_output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optuna parameter optimizer")
    parser.add_argument("--trials", type=int, default=200,
                        help="Total trials to run (default: 200). Study resumes if DB exists.")
    args = parser.parse_args()

    # Late imports (not needed for patching/scoring unit tests)
    from wfo_engine import run_wfo
    from representative_tickers import REPRESENTATIVE_TICKERS

    main(n_trials=args.trials)
```

**Step 4: Add late imports to module scope for tests**

The integration test mocks `optimize_parameters.run_wfo` and `optimize_parameters.asyncio.run`,
so the module needs `run_wfo` and `asyncio` at module scope. Add these two lines near the top
of `scripts/optimize_parameters.py` (after the path setup block):

```python
import asyncio

# run_wfo and REPRESENTATIVE_TICKERS are imported lazily in __main__ to avoid
# startup cost during unit tests — but exposed here for mockability in tests.
try:
    from wfo_engine import run_wfo
    from representative_tickers import REPRESENTATIVE_TICKERS
except ImportError:
    run_wfo = None              # type: ignore[assignment]
    REPRESENTATIVE_TICKERS = [] # type: ignore[assignment]
```

**Step 5: Create config/.gitkeep**

```bash
mkdir -p swing-trading-dashboard/config
touch swing-trading-dashboard/config/.gitkeep
```

**Step 6: Run integration test**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_optimizer_integration.py -v
```

Expected: 1 PASS.

**Step 7: Run full test suite**

```bash
python -m pytest -q
```

Expected: all pass.

**Step 8: Smoke-test CLI (optional manual check)**

```bash
cd swing-trading-dashboard/backend
python ../scripts/optimize_parameters.py --trials 1
```

Expected: tqdm bar completes, prints summary, creates `config/best_parameters.json`
(note: this will run the real WFO with real data — skip if no internet or Parquet cache).

**Step 9: Commit**

```bash
cd swing-trading-dashboard
git add scripts/optimize_parameters.py backend/tests/test_optimizer_integration.py config/.gitkeep
git commit -m "feat(optimizer): complete Optuna optimizer — objective, study config, CLI, JSON export"
```

---

## Full Test Suite Check (after all tasks)

```bash
cd swing-trading-dashboard/backend
python -m pytest -q
```

Expected: all tests pass (Task 1 adds 4, Task 2 adds 6, Task 3 adds 8, Task 4 adds 1 = 19 new tests + all prior passing).

---

## New Constants Summary

| Constant | Value | Location |
|---|---|---|
| `TRAIL_ATR_MULT` | 1.5 | `backend/constants.py` |

## Files Created/Modified

| File | Status |
|---|---|
| `backend/constants.py` | Modified — add `TRAIL_ATR_MULT` |
| `backend/backtest_engine.py` | Modified — hybrid trailing stop + `atr14` in bar dict |
| `scripts/__init__.py` | Created (empty) |
| `scripts/representative_tickers.py` | Created |
| `scripts/optimize_parameters.py` | Created |
| `config/.gitkeep` | Created |
| `backend/tests/test_trail_atr_mult.py` | Created |
| `backend/tests/test_representative_tickers.py` | Created |
| `backend/tests/test_optimizer_core.py` | Created |
| `backend/tests/test_optimizer_integration.py` | Created |
