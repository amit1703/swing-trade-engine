"""
optimize_brk.py — Optuna breakout-engine parameter search.
═══════════════════════════════════════════════════════════
Dedicated optimization phase for the RES_BREAKOUT engine only.
All pullback parameters are frozen at V5 best (trial #286, score=1.7948).

Usage:
    cd backend

    # Step 1: build the full universe cache (skip if already done)
    python3 optimize_brk.py --download

    # Step 2: run optimization
    python3 optimize_brk.py [--trials 200] [--resume]

    # Step 3: resume a previous run
    python3 optimize_brk.py --resume --trials 100

Notes:
    - All pullback params are frozen from V5 Optuna best.
    - Only brk_* params are tuned (vol_mult, stop_atr, min_pct, gap_pct,
      trail_mult, regime_factor) plus breakout_weight and score_threshold.
    - Penalty applies if RES_BREAKOUT trades < MIN_BRK_TRADES (50).
    - Study stored at data/optuna_brk.db (separate from V5 study).
    - Full universe: SCAN_UNIVERSE from tickers.py (~800 tickers).
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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── Path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import BacktestEngine, BacktestParams, TradeRecord
from constants import (
    BACKTEST_DIAG_START_DATE,
    BACKTEST_DIAG_END_DATE,
    CONCURRENCY_LIMIT,
    WFO_CACHE_DIR,
)
from tickers import SCAN_UNIVERSE
from wfo_cache import download_and_cache, get_cache_path, load_ticker

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("optimize_brk")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).parent
_DATA_DIR    = _BACKEND_DIR / "data"
_DATA_DIR.mkdir(exist_ok=True)

_STUDY_DB    = str(_DATA_DIR / "optuna_brk.db")
_OUTPUT_PATH = _DATA_DIR / "best_params_brk.json"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIN_BRK_TRADES  = 50      # penalty if RES_BREAKOUT trades fall below this
PENALTY_SCORE   = -99.0
STUDY_NAME      = "brk_optimizer"

# ── Frozen pullback params from V5 Optuna best (trial #286, score=1.7948) ────
_FROZEN = dict(
    rs_threshold    = 0.066,
    cci_threshold   = -54.5,
    ema_distance    = 1.651,
    pullback_weight = 1.842,
    tdl_bonus       = 1.016,
    vcp_bonus       = 1.370,
    cooldown_days   = 4,
    tp_multiple     = 4.562,
)

# ── Frozen breakout params from BRK run 1 (trial #190, score=6.8181) ─────────
# Converged (CV < 0.10): gap, consolidation, pivot_strength, regime_factor,
# trail_mult, score_threshold. brk_min_pct fixed at 0.0 (noisy, CV=2.05).
_FROZEN_BRK_CONVERGED = dict(
    brk_gap_pct           = 0.042,
    brk_min_consolidation = 10,
    brk_pivot_strength    = 2,
    brk_regime_factor     = 0.861,
    brk_trail_mult        = 5.928,
    score_threshold       = 5.791,
    brk_min_pct           = 0.0,    # fixed — noisy, best trials clustered here
)


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_cache(cache_dir: Path) -> None:
    """Download missing tickers from SCAN_UNIVERSE into the parquet cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    missing = [t for t in SCAN_UNIVERSE if not (cache_dir / f"{t}.parquet").exists()]

    if not missing:
        print("Cache is complete — all SCAN_UNIVERSE tickers already present.")
        return

    print(f"Downloading {len(missing)} missing tickers into cache…", flush=True)

    progress: dict = {}
    download_and_cache(
        tickers=missing,
        job_id="brk_cache",
        progress=progress,
    )
    cached = sum(1 for t in missing if (cache_dir / f"{t}.parquet").exists())
    print(f"  Done — {cached}/{len(missing)} tickers cached successfully.")


def _load_universe_cache(cache_dir: Path) -> Tuple[Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """Load all parquet files from the cache dir."""
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
    """Run full universe backtest, return list of trade dicts."""
    tickers = [t for t in ticker_cache if t != "SPY"]
    if not tickers:
        return []

    sem  = asyncio.Semaphore(CONCURRENCY_LIMIT)
    all_trades: List[dict] = []

    async def _run_one(ticker: str) -> List[dict]:
        async with sem:
            try:
                # Trim to end_date: prevents future resistance levels (2025-2026
                # price peaks) from polluting KDE zones during 2023-2024 replay.
                # setup_types=["RES_BREAKOUT"]: isolate breakout engine so Optuna
                # gets a clean signal — avoids BASE/VCP stealing bars before
                # the breakout check runs (first-match-wins ordering issue).
                df = ticker_cache[ticker].loc[:end_date]
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    ticker_df=df,
                    spy_df=spy_df,
                    params=params,
                    setup_types=["RES_BREAKOUT"],
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                logger.debug("Trial ticker %s failed: %s", ticker, exc)
                return []

    results = await asyncio.gather(*[_run_one(t) for t in tickers])
    for batch in results:
        all_trades.extend(batch)

    return all_trades


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def _compute_metrics(trades: List[dict]) -> dict:
    """Compute per-trade metrics, split by setup type."""
    if not trades:
        return {
            "total_trades": 0, "brk_trades": 0, "win_rate": 0.0,
            "expectancy": 0.0, "profit_factor": 0.0,
            "brk_expectancy": 0.0, "brk_profit_factor": 0.0,
            "max_drawdown_r": 0.0, "by_setup": {},
        }

    all_rr  = [t["rr_achieved"] for t in trades if "rr_achieved" in t]
    brk_rr  = [t["rr_achieved"] for t in trades
               if t.get("setup_type") == "RES_BREAKOUT" and "rr_achieved" in t]

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

    ex,  pf,  wr  = _stats(all_rr)
    bex, bpf, bwr = _stats(brk_rr)

    # Max drawdown (full equity curve)
    peak, max_dd, running = 0.0, 0.0, 0.0
    for r in all_rr:
        running += r
        if running > peak:
            peak = running
        dd = running - peak
        if dd < max_dd:
            max_dd = dd

    by_setup: Dict[str, int] = defaultdict(int)
    for t in trades:
        by_setup[t.get("setup_type", "UNKNOWN")] += 1

    return {
        "total_trades":      len(all_rr),
        "brk_trades":        len(brk_rr),
        "win_rate":          round(wr * 100, 1),
        "expectancy":        round(ex, 4),
        "profit_factor":     round(pf, 3),
        "brk_expectancy":    round(bex, 4),
        "brk_profit_factor": round(min(bpf, 99.0), 3),
        "brk_win_rate":      round(bwr * 100, 1),
        "max_drawdown_r":    round(max_dd, 2),
        "by_setup":          dict(by_setup),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Objective
# ─────────────────────────────────────────────────────────────────────────────

def _objective_score(metrics: dict) -> float:
    """
    Breakout-focused objective.

    Primary: breakout trades quality — expectancy × PF × log(brk_trades + 1)
    Penalty: brk_trades < MIN_BRK_TRADES → PENALTY_SCORE
    """
    n   = metrics["brk_trades"]
    ex  = metrics["brk_expectancy"]
    pf  = min(metrics["brk_profit_factor"], 10.0)

    if n < MIN_BRK_TRADES:
        return PENALTY_SCORE

    if ex <= 0 or pf <= 0:
        return ex

    return ex * pf * math.log(n + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Optuna trial builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_params(trial) -> BacktestParams:
    """
    Breakout-only search space — run 2 (moderate params only).
    Converged params frozen from BRK run 1 (trial #190, score=6.8181).
    All pullback params frozen at V5 best (trial #286, score=1.7948).
    """
    return BacktestParams(
        # ── FROZEN: pullback params ──────────────────────────────────────────
        **_FROZEN,

        # ── FROZEN: converged breakout params ────────────────────────────────
        **_FROZEN_BRK_CONVERGED,

        # ── TUNABLE: signal weight ───────────────────────────────────────────
        breakout_weight = trial.suggest_float("breakout_weight", 0.5,  4.0),

        # ── TUNABLE: moderate params — refine these ───────────────────────────
        brk_vol_mult      = trial.suggest_float("brk_vol_mult",      1.0,  3.5),
        brk_stop_atr      = trial.suggest_float("brk_stop_atr",      0.3,  2.5),
        brk_donchian_n    = trial.suggest_int(  "brk_donchian_n",    20,   126),
        brk_atr_expansion = trial.suggest_float("brk_atr_expansion", 0.0,  1.5),
    )


def _build_params_from_values(values: dict) -> BacktestParams:
    """Reconstruct BacktestParams from a dict of best trial values."""
    return BacktestParams(
        **_FROZEN,
        **_FROZEN_BRK_CONVERGED,
        breakout_weight   = values["breakout_weight"],
        brk_vol_mult      = values["brk_vol_mult"],
        brk_stop_atr      = values["brk_stop_atr"],
        brk_donchian_n    = int(values["brk_donchian_n"]),
        brk_atr_expansion = values["brk_atr_expansion"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(best_params: BacktestParams, metrics: dict, trial_number: int) -> None:
    line = "─" * 62
    print(f"\n{'═' * 62}")
    print(f"  BRK OPTUNA BEST RESULT  (trial #{trial_number})")
    print(f"{'═' * 62}")

    print(f"\n  PERFORMANCE (ALL TRADES)")
    print(f"    Total Trades   : {metrics['total_trades']}")
    print(f"    Win Rate       : {metrics['win_rate']:.1f}%")
    print(f"    Expectancy     : {metrics['expectancy']:+.4f} R")
    print(f"    Profit Factor  : {metrics['profit_factor']:.3f}")
    print(f"    Max Drawdown   : {metrics['max_drawdown_r']:.2f} R")

    print(f"\n  PERFORMANCE (RES_BREAKOUT ONLY)")
    print(f"    BRK Trades     : {metrics['brk_trades']}")
    print(f"    BRK Win Rate   : {metrics.get('brk_win_rate', 0):.1f}%")
    print(f"    BRK Expectancy : {metrics['brk_expectancy']:+.4f} R")
    print(f"    BRK Prof Factor: {metrics['brk_profit_factor']:.3f}")

    print(f"\n  By Setup:")
    for setup, count in sorted(metrics["by_setup"].items(), key=lambda x: -x[1]):
        pct = count / metrics["total_trades"] * 100 if metrics["total_trades"] else 0
        print(f"    {setup:<16} {count:>5}  ({pct:.1f}%)")

    print(f"\n{line}")
    print(f"  BEST PARAMETERS  (tuned)")
    print(line)
    p = best_params
    rows = [
        ("score_threshold",        f"{p.score_threshold:.2f}"),
        ("breakout_weight",        f"{p.breakout_weight:.3f}"),
        ("brk_vol_mult",           f"{p.brk_vol_mult:.3f}"),
        ("brk_min_pct (buffer)",   f"{p.brk_min_pct:.4f}"),
        ("brk_stop_atr",           f"{p.brk_stop_atr:.3f}"),
        ("brk_gap_pct",            f"{p.brk_gap_pct:.4f}"),
        ("brk_trail_mult",         f"{p.brk_trail_mult:.3f}"),
        ("brk_regime_factor",      f"{p.brk_regime_factor:.3f}"),
        ("brk_donchian_n",         f"{p.brk_donchian_n}"),
        ("brk_pivot_strength",     f"{p.brk_pivot_strength}"),
        ("brk_atr_expansion",      f"{p.brk_atr_expansion:.3f}"),
        ("brk_min_consolidation",  f"{p.brk_min_consolidation}"),
    ]
    for name, val in rows:
        print(f"  {name:<22} {val}")

    print(f"\n{line}")
    print(f"  FROZEN PULLBACK PARAMS")
    print(line)
    frozen_rows = [
        ("rs_threshold",    f"{p.rs_threshold:.5f}"),
        ("cci_threshold",   f"{p.cci_threshold:.1f}"),
        ("ema_distance",    f"{p.ema_distance:.3f}"),
        ("pullback_weight", f"{p.pullback_weight:.3f}"),
        ("cooldown_days",   f"{p.cooldown_days}"),
        ("tp_multiple",     f"{p.tp_multiple:.3f}"),
    ]
    for name, val in frozen_rows:
        print(f"  {name:<22} {val}")
    print(f"{'═' * 62}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BRK Optuna optimizer")
    parser.add_argument("--trials",   type=int,  default=200)
    parser.add_argument("--jobs",     type=int,  default=1)
    parser.add_argument("--start",    type=str,  default=BACKTEST_DIAG_START_DATE)
    parser.add_argument("--end",      type=str,  default=BACKTEST_DIAG_END_DATE)
    parser.add_argument("--storage",  type=str,  default=f"sqlite:///{_STUDY_DB}")
    parser.add_argument("--resume",   action="store_true")
    parser.add_argument("--download", action="store_true",
                        help="Download missing SCAN_UNIVERSE tickers into cache, then exit")
    args = parser.parse_args()

    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR

    # ── Optional cache build step ─────────────────────────────────────────────
    if args.download:
        _build_cache(cache_dir)
        sys.exit(0)

    # ── Load cache ────────────────────────────────────────────────────────────
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
    print(f"BRK min  : {MIN_BRK_TRADES} trades (penalty below this)")
    print()

    # ── Optuna study ──────────────────────────────────────────────────────────
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

        completed = len(study.trials)
        remaining = args.trials - completed
        eta_min   = remaining * avg / 60

        print(
            f"Trial {trial.number:>4}  score={score:>8.4f}  "
            f"brk={metrics['brk_trades']:>4}  total={metrics['total_trades']:>5}  "
            f"brkE={metrics['brk_expectancy']:>+.4f}  brkPF={metrics['brk_profit_factor']:.3f}  "
            f"elapsed={elapsed/60:.1f}min  ETA≈{eta_min:.0f}min",
            flush=True,
        )
        return score

    print(f"Starting optimisation at {datetime.now().strftime('%H:%M:%S')} …\n")
    study.optimize(objective, n_trials=args.trials, n_jobs=args.jobs, show_progress_bar=False)

    # ── Best result ───────────────────────────────────────────────────────────
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
        "frozen":       _FROZEN,
        "generated_at": datetime.now().isoformat(),
    }
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Best params saved to {_OUTPUT_PATH}")

    _print_report(best_params, best_metrics, best_trial.number)


if __name__ == "__main__":
    main()
