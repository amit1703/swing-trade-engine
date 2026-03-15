"""
optimize_base.py — Optuna BASE-engine parameter search.
════════════════════════════════════════════════════════
Dedicated optimization phase for the BASE engine only (flat base + cup & handle).
All pullback and breakout parameters are frozen at their best known values.

Usage:
    cd backend
    python3 optimize_base.py [--trials 200] [--resume]
    python3 optimize_base.py --resume --trials 100

Notes:
    - Only BASE params are tuned: base_weight, base_trail_mult,
      base_vol_ratio, base_quality_min, plus tp_multiple and score_threshold.
    - All pullback/brk params frozen at best known values.
    - setup_types=["BASE"] isolates the engine — no competition
      from PULLBACK/BRK stealing bars (first-match-wins ordering).
    - Penalty if base_trades < MIN_BASE_TRADES (30).
    - Study stored at data/optuna_base.db (separate from pb / brk).
    - Full cache universe used (data/price_cache/).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import BacktestEngine, BacktestParams
from constants import (
    BACKTEST_DIAG_START_DATE,
    BACKTEST_DIAG_END_DATE,
    CONCURRENCY_LIMIT,
    WFO_CACHE_DIR,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("optimize_base")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).parent
_DATA_DIR    = _BACKEND_DIR / "data"
_DATA_DIR.mkdir(exist_ok=True)

_STUDY_DB    = str(_DATA_DIR / "optuna_base.db")
_OUTPUT_PATH = _DATA_DIR / "best_params_base.json"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIN_BASE_TRADES = 30       # penalty if BASE trades fall below this
PENALTY_SCORE   = -99.0
STUDY_NAME      = "base_optimizer"

# ── Frozen: pullback params (pb_optimizer best, trial #183) ──────────────────
_FROZEN_PB = dict(
    rs_threshold    = 0.088,
    cci_threshold   = -107.6,
    ema_distance    = 2.094,
    pullback_weight = 2.536,
    tdl_bonus       = 0.573,
    vcp_bonus       = 0.738,
    cooldown_days   = 5,
    tp_multiple     = 5.161,
)

# ── Frozen: breakout params (brk_optimizer run 1 best, trial #190) ───────────
_FROZEN_BRK = dict(
    breakout_weight       = 1.724,   # V5 default (brk run 2 still running)
    brk_vol_mult          = 2.0,
    brk_stop_atr          = 1.0,
    brk_min_pct           = 0.0,
    brk_gap_pct           = 0.042,
    brk_trail_mult        = 5.928,
    brk_regime_factor     = 0.861,
    brk_donchian_n        = 63,
    brk_pivot_strength    = 2,
    brk_atr_expansion     = 0.0,
    brk_min_consolidation = 10,
)


# ─────────────────────────────────────────────────────────────────────────────
# Cache loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_universe_cache(
    cache_dir: Path,
) -> Tuple[Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    if not cache_dir.exists():
        return {}, None

    parquet_files = list(cache_dir.glob("*.parquet"))
    if not parquet_files:
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
        print("  WARNING: SPY not found — regime filter inactive.", flush=True)
    return ticker_cache, spy_df


# ─────────────────────────────────────────────────────────────────────────────
# Backtest runner
# ─────────────────────────────────────────────────────────────────────────────

async def _run_trial(
    ticker_cache: Dict[str, pd.DataFrame],
    spy_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
    params: BacktestParams,
) -> List[dict]:
    tickers = [t for t in ticker_cache if t != "SPY"]
    if not tickers:
        return []

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def _run_one(ticker: str) -> List[dict]:
        async with sem:
            try:
                # Trim to end_date: no future data leakage.
                # setup_types=["BASE"]: isolate BASE engine for clean Optuna signal.
                df = ticker_cache[ticker].loc[:end_date]
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    ticker_df=df,
                    spy_df=spy_df,
                    params=params,
                    setup_types=["BASE"],
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
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def _compute_metrics(trades: List[dict]) -> dict:
    if not trades:
        return {
            "total_trades": 0, "base_trades": 0,
            "win_rate": 0.0, "expectancy": 0.0,
            "profit_factor": 0.0, "max_drawdown_r": 0.0,
        }

    base_rr = [t["rr_achieved"] for t in trades
               if t.get("setup_type") == "BASE" and "rr_achieved" in t]
    all_rr  = [t["rr_achieved"] for t in trades if "rr_achieved" in t]

    def _stats(rr_list):
        if not rr_list:
            return 0.0, 0.0, 0.0
        wins   = [r for r in rr_list if r > 0]
        losses = [r for r in rr_list if r <= 0]
        wr     = len(wins) / len(rr_list)
        ex     = sum(rr_list) / len(rr_list)
        gl     = abs(sum(losses))
        pf     = sum(wins) / gl if gl > 0 else float("inf")
        return ex, min(pf, 99.0), wr

    ex, pf, wr = _stats(base_rr)

    peak, max_dd, running = 0.0, 0.0, 0.0
    for r in all_rr:
        running += r
        if running > peak:
            peak = running
        dd = running - peak
        if dd < max_dd:
            max_dd = dd

    return {
        "total_trades":  len(all_rr),
        "base_trades":   len(base_rr),
        "win_rate":      round(wr * 100, 1),
        "expectancy":    round(ex, 4),
        "profit_factor": round(pf, 3),
        "max_drawdown_r": round(max_dd, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Objective
# ─────────────────────────────────────────────────────────────────────────────

def _objective_score(metrics: dict) -> float:
    """
    BASE-focused objective.
    Primary: expectancy × PF × log(base_trades + 1)
    Penalty: base_trades < MIN_BASE_TRADES → PENALTY_SCORE
    """
    n  = metrics["base_trades"]
    ex = metrics["expectancy"]
    pf = min(metrics["profit_factor"], 10.0)

    if n < MIN_BASE_TRADES:
        return PENALTY_SCORE

    if ex <= 0 or pf <= 0:
        return ex

    return ex * pf * math.log(n + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Optuna trial builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_params(trial) -> BacktestParams:
    """
    BASE-only search space.
    Pullback and breakout params frozen at best known values.
    """
    return BacktestParams(
        # ── FROZEN: pullback params ──────────────────────────────────────────
        **_FROZEN_PB,

        # ── FROZEN: breakout params ──────────────────────────────────────────
        **_FROZEN_BRK,

        # ── TUNABLE: score gate (shared across all setups) ───────────────────
        score_threshold = trial.suggest_float("score_threshold", 1.0,  8.0),

        # ── TUNABLE: BASE engine params ──────────────────────────────────────
        base_weight      = trial.suggest_float("base_weight",      0.5,  4.0),
        base_trail_mult  = trial.suggest_float("base_trail_mult",  2.0,  8.0),
        base_vol_ratio   = trial.suggest_float("base_vol_ratio",   1.0,  3.0),
        base_quality_min = trial.suggest_int(  "base_quality_min", 10,   60),
    )


def _build_params_from_values(values: dict) -> BacktestParams:
    return BacktestParams(
        **_FROZEN_PB,
        **_FROZEN_BRK,
        score_threshold  = values["score_threshold"],
        base_weight      = values["base_weight"],
        base_trail_mult  = values["base_trail_mult"],
        base_vol_ratio   = values["base_vol_ratio"],
        base_quality_min = int(values["base_quality_min"]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(best_params: BacktestParams, metrics: dict, trial_number: int) -> None:
    line = "─" * 62
    print(f"\n{'═' * 62}")
    print(f"  BASE OPTUNA BEST RESULT  (trial #{trial_number})")
    print(f"{'═' * 62}")

    print(f"\n  PERFORMANCE (BASE)")
    print(f"    BASE Trades    : {metrics['base_trades']}")
    print(f"    Win Rate       : {metrics['win_rate']:.1f}%")
    print(f"    Expectancy     : {metrics['expectancy']:+.4f} R")
    print(f"    Profit Factor  : {metrics['profit_factor']:.3f}")
    print(f"    Max Drawdown   : {metrics['max_drawdown_r']:.2f} R")

    print(f"\n{line}")
    print(f"  BEST PARAMETERS  (tuned)")
    print(line)
    p = best_params
    rows = [
        ("score_threshold",  f"{p.score_threshold:.2f}"),
        ("base_weight",      f"{p.base_weight:.3f}"),
        ("base_trail_mult",  f"{p.base_trail_mult:.3f}"),
        ("base_vol_ratio",   f"{p.base_vol_ratio:.3f}"),
        ("base_quality_min", f"{p.base_quality_min}"),
    ]
    for name, val in rows:
        print(f"  {name:<22} {val}")
    print(f"{'═' * 62}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BASE Optuna optimizer")
    parser.add_argument("--trials",  type=int, default=200)
    parser.add_argument("--jobs",    type=int, default=1)
    parser.add_argument("--start",   type=str, default=BACKTEST_DIAG_START_DATE)
    parser.add_argument("--end",     type=str, default=BACKTEST_DIAG_END_DATE)
    parser.add_argument("--storage", type=str, default=f"sqlite:///{_STUDY_DB}")
    parser.add_argument("--resume",  action="store_true")
    args = parser.parse_args()

    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR
    ticker_cache, spy_df = _load_universe_cache(cache_dir)

    if len(ticker_cache) < 10:
        print("ERROR: fewer than 10 tickers in cache.")
        print("  Run:  python3 optimize_brk.py --download")
        sys.exit(1)

    start_date = args.start
    end_date   = args.end
    print(f"Universe : {len(ticker_cache)} tickers")
    print(f"Window   : {start_date} → {end_date}")
    print(f"Trials   : {args.trials}")
    print(f"Storage  : {args.storage}")
    print(f"BASE min : {MIN_BASE_TRADES} trades (penalty below this)")
    print()

    try:
        import optuna
    except ImportError:
        print("ERROR: optuna not installed. Run: pip install optuna")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    if args.resume:
        study = optuna.load_study(study_name=STUDY_NAME, storage=args.storage)
        print(f"Resumed study '{STUDY_NAME}' with {len(study.trials)} completed trials.")
    else:
        study = optuna.create_study(
            study_name=STUDY_NAME,
            storage=args.storage,
            direction="maximize",
            load_if_exists=True,
            sampler=optuna.samplers.TPESampler(seed=42),
        )

    trial_times: list = []

    def objective(trial) -> float:
        import time
        t0 = time.perf_counter()

        params  = _build_params(trial)
        trades  = asyncio.run(_run_trial(ticker_cache, spy_df, start_date, end_date, params))
        metrics = _compute_metrics(trades)
        score   = _objective_score(metrics)

        elapsed = time.perf_counter() - t0
        trial_times.append(elapsed)
        avg = sum(trial_times) / len(trial_times)
        eta_min = (args.trials - len(study.trials)) * avg / 60

        print(
            f"Trial {trial.number:>4}  score={score:>8.4f}  "
            f"base={metrics['base_trades']:>4}  "
            f"E={metrics['expectancy']:>+.4f}  PF={metrics['profit_factor']:.3f}  "
            f"WR={metrics['win_rate']:.1f}%  "
            f"elapsed={elapsed/60:.1f}min  ETA≈{eta_min:.0f}min",
            flush=True,
        )
        return score

    print(f"Starting optimisation at {datetime.now().strftime('%H:%M:%S')} …\n")
    study.optimize(objective, n_trials=args.trials, n_jobs=args.jobs, show_progress_bar=False)

    best_trial  = study.best_trial
    best_params = _build_params_from_values(best_trial.params)

    print("\nRe-running best parameters for final metrics…", flush=True)
    best_trades  = asyncio.run(_run_trial(ticker_cache, spy_df, start_date, end_date, best_params))
    best_metrics = _compute_metrics(best_trades)

    output = {
        "trial_number": best_trial.number,
        "score":        best_trial.value,
        "metrics":      best_metrics,
        "params":       best_trial.params,
        "frozen_pb":    _FROZEN_PB,
        "frozen_brk":   _FROZEN_BRK,
        "generated_at": datetime.now().isoformat(),
    }
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Best params saved to {_OUTPUT_PATH}")

    _print_report(best_params, best_metrics, best_trial.number)


if __name__ == "__main__":
    main()
