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

# run_wfo and REPRESENTATIVE_TICKERS are imported lazily in __main__ to avoid
# startup cost during unit tests — but exposed here for mockability in tests.
try:
    from wfo_engine import run_wfo
    from representative_tickers import REPRESENTATIVE_TICKERS
except ImportError:
    run_wfo = None              # type: ignore[assignment]
    REPRESENTATIVE_TICKERS = [] # type: ignore[assignment]

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
    _preload_modules()
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
