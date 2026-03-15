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
    Tunable params use .get(key, trial_433_default) so this works
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
        load_if_exists=True,
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
        print(
            f"  W{window_num}: Already has {len(completed)} trials — skipping optimization.",
            flush=True,
        )
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

    best        = study.best_trial
    best_params = _build_params_from_values(best.params)

    # Re-evaluate IS period with best params to get full metrics
    print(f"  W{window_num}: Re-evaluating IS with best params (trial #{best.number})…", flush=True)
    is_trades  = asyncio.run(_run_trial(ticker_cache, spy_df, is_start, is_end, best_params))
    is_metrics = _compute_metrics(is_trades)

    return best_params, is_metrics, best.number, best.value
