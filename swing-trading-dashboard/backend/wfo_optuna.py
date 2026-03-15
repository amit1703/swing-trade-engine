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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

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
    (1, "2019-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    (2, "2020-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    (3, "2021-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    (4, "2022-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
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
    best_trial:     int
    best_score:     float
    best_params:    Dict[str, float]
    is_metrics:     dict
    oos_metrics:    dict
    frozen_metrics: dict
    spy_pct:        Optional[float]


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
