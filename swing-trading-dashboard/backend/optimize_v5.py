"""
optimize_v5.py — Optuna V5 parameter search for the swing trading backtest engine.
═══════════════════════════════════════════════════════════════════════════════════

Usage:
    cd backend
    python3 optimize_v5.py [--trials 200] [--jobs 1] [--start 2023-01-01] [--end 2024-12-31]

Performance notes:
    - All price data is pre-loaded from data/price_cache/*.parquet before trials begin.
    - Tickers with no cache file are skipped (run wfo_cache download first if needed).
    - Each trial runs the full universe via asyncio with CONCURRENCY_LIMIT workers.
    - Typical: ~14 min per trial on 1572 stocks. Plan 50–200 trials for overnight runs.
    - Optuna TPE usually converges by trial 100–150; 1000 trials is the search budget cap.

Output:
    - Optuna SQLite study: data/optuna_v5.db  (resumable)
    - Best params JSON:    data/best_params_v5.json
    - Full report printed to stdout at completion.
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
from wfo_cache import get_cache_path, load_ticker

logging.basicConfig(
    level=logging.WARNING,          # suppress per-ticker noise during optimization
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("optimize_v5")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).parent
_DATA_DIR    = _BACKEND_DIR / "data"
_DATA_DIR.mkdir(exist_ok=True)

_STUDY_DB    = str(_DATA_DIR / "optuna_v5.db")
_OUTPUT_PATH = _DATA_DIR / "best_params_v5.json"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIN_TRADES          = 200     # penalty if total trades falls below this
PENALTY_SCORE       = -99.0   # returned when constraint violated
STUDY_NAME          = "v5_swing_optimizer"


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_universe_cache(cache_dir: Path) -> Tuple[Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Load all parquet files from the WFO cache directory.

    Returns
    -------
    ticker_cache : dict  {ticker -> DataFrame}
    spy_df       : DataFrame | None  — SPY data for regime computation
    """
    if not cache_dir.exists():
        logger.error("Cache dir does not exist: %s", cache_dir)
        return {}, None

    parquet_files = list(cache_dir.glob("*.parquet"))
    if not parquet_files:
        logger.error("No parquet files found in %s. Run the WFO cache download first.", cache_dir)
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

    print(f"  Loaded {len(ticker_cache)} tickers ({len(ticker_cache) - (1 if spy_df is not None else 0)} non-SPY).", flush=True)
    if spy_df is None:
        print("  WARNING: SPY not found in cache — regime filter will be inactive.", flush=True)

    return ticker_cache, spy_df


# ─────────────────────────────────────────────────────────────────────────────
# Backtest runner for a single trial
# ─────────────────────────────────────────────────────────────────────────────

async def _run_trial(
    ticker_cache: Dict[str, pd.DataFrame],
    spy_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
    params: BacktestParams,
) -> List[dict]:
    """Run the full universe backtest with given params. Returns list of trade dicts."""
    tickers = [t for t in ticker_cache if t != "SPY"]
    if not tickers:
        return []

    sem   = asyncio.Semaphore(CONCURRENCY_LIMIT)
    lock  = asyncio.Lock()
    all_trades: List[dict] = []

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
    for batch in results:
        all_trades.extend(batch)

    return all_trades


# ─────────────────────────────────────────────────────────────────────────────
# Metrics computation
# ─────────────────────────────────────────────────────────────────────────────

def _compute_metrics(trades: List[dict]) -> dict:
    """Compute expectancy, profit factor, win rate, max drawdown, trade counts."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0,
            "expectancy": 0.0, "profit_factor": 0.0,
            "max_drawdown_r": 0.0, "by_setup": {},
        }

    rr_vals    = [t["rr_achieved"] for t in trades if "rr_achieved" in t]
    wins       = [r for r in rr_vals if r > 0]
    losses     = [r for r in rr_vals if r <= 0]

    total      = len(rr_vals)
    win_rate   = len(wins) / total if total else 0.0
    expectancy = sum(rr_vals) / total if total else 0.0

    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # Max drawdown in R (peak-to-trough of cumulative R curve)
    cumulative = []
    running = 0.0
    for r in rr_vals:
        running += r
        cumulative.append(running)

    peak    = 0.0
    max_dd  = 0.0
    for v in cumulative:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < max_dd:
            max_dd = dd

    # Trade distribution by setup type
    by_setup: Dict[str, int] = defaultdict(int)
    for t in trades:
        by_setup[t.get("setup_type", "UNKNOWN")] += 1

    return {
        "total_trades":  total,
        "win_rate":      round(win_rate * 100, 1),
        "expectancy":    round(expectancy, 4),
        "profit_factor": round(min(profit_factor, 99.0), 3),
        "max_drawdown_r": round(max_dd, 2),
        "by_setup":      dict(by_setup),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Objective function
# ─────────────────────────────────────────────────────────────────────────────

def _objective_score(metrics: dict) -> float:
    """
    Compute a single score Optuna maximises.

    Formula:  expectancy × profit_factor × log(total_trades + 1)

    Constraints:
      - total_trades < MIN_TRADES  → PENALTY_SCORE (avoids overfitting on thin samples)
      - profit_factor == inf (no losses at all) → cap at a reasonable value
      - expectancy ≤ 0  → return score as-is (negative, so Optuna deprioritises)
    """
    n  = metrics["total_trades"]
    ex = metrics["expectancy"]
    pf = min(metrics["profit_factor"], 10.0)   # cap inf

    if n < MIN_TRADES:
        return PENALTY_SCORE

    if ex <= 0 or pf <= 0:
        return ex   # negative score; optimizer will avoid these regions

    return ex * pf * math.log(n + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Optuna trial builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_params(trial) -> BacktestParams:
    """Sample BacktestParams from the Optuna trial's search space.

    Pullback params are FROZEN at V5 best (trial #286, score=1.7948).
    Only brk_* params are tuned here — use this for breakout-only Optuna phase.
    """
    return BacktestParams(
        # ── FROZEN: pullback params (V5 Optuna best #286) ───────────────────
        rs_threshold    = 0.066,
        cci_threshold   = -54.5,
        ema_distance    = 1.651,
        score_threshold = 2.50,
        breakout_weight = 1.724,
        pullback_weight = 1.842,
        tdl_bonus       = 1.016,
        vcp_bonus       = 1.370,
        cooldown_days   = 4,
        tp_multiple     = 4.562,

        # ── TUNABLE: RES_BREAKOUT engine parameters ──────────────────────────
        brk_vol_mult    = trial.suggest_float("brk_vol_mult",    1.5,   3.5),
        brk_stop_atr    = trial.suggest_float("brk_stop_atr",    0.3,   2.0),
        brk_min_pct     = trial.suggest_float("brk_min_pct",     0.01,  0.05),
        brk_gap_pct     = trial.suggest_float("brk_gap_pct",     0.01,  0.08),
        brk_trail_mult  = trial.suggest_float("brk_trail_mult",  1.5,   8.0),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(best_params: BacktestParams, metrics: dict, trial_number: int) -> None:
    line = "─" * 62
    print(f"\n{'═' * 62}")
    print(f"  V5 OPTUNA BEST RESULT  (trial #{trial_number})")
    print(f"{'═' * 62}")

    print(f"\n{'PERFORMANCE':}")
    print(f"  Total Trades   : {metrics['total_trades']}")
    print(f"  Win Rate       : {metrics['win_rate']:.1f}%")
    print(f"  Expectancy     : {metrics['expectancy']:+.4f} R")
    print(f"  Profit Factor  : {metrics['profit_factor']:.3f}")
    print(f"  Max Drawdown   : {metrics['max_drawdown_r']:.2f} R")

    print(f"\n  By Setup:")
    for setup, count in sorted(metrics["by_setup"].items(), key=lambda x: -x[1]):
        pct = count / metrics["total_trades"] * 100 if metrics["total_trades"] else 0
        print(f"    {setup:<16} {count:>5}  ({pct:.1f}%)")

    print(f"\n{line}")
    print(f"  BEST PARAMETERS")
    print(line)
    p = best_params
    rows = [
        ("rs_threshold",    f"{p.rs_threshold:.5f}"),
        ("cci_threshold",   f"{p.cci_threshold:.1f}"),
        ("ema_distance",    f"{p.ema_distance:.3f}"),
        ("score_threshold", f"{p.score_threshold:.2f}"),
        ("breakout_weight", f"{p.breakout_weight:.3f}"),
        ("pullback_weight", f"{p.pullback_weight:.3f}"),
        ("tdl_bonus",       f"{p.tdl_bonus:.3f}"),
        ("vcp_bonus",       f"{p.vcp_bonus:.3f}"),
        ("cooldown_days",   f"{p.cooldown_days}"),
        ("brk_vol_mult",    f"{p.brk_vol_mult:.3f}"),
        ("brk_stop_atr",    f"{p.brk_stop_atr:.3f}"),
        ("brk_min_pct",     f"{p.brk_min_pct:.4f}"),
        ("brk_gap_pct",     f"{p.brk_gap_pct:.4f}"),
        ("brk_trail_mult",  f"{p.brk_trail_mult:.3f}"),
        ("tp_multiple",     f"{p.tp_multiple:.3f}"),
    ]
    for name, val in rows:
        print(f"  {name:<20} {val}")
    print(f"{'═' * 62}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main optimisation loop
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V5 Optuna optimizer")
    parser.add_argument("--trials",  type=int,  default=200,
                        help="Number of Optuna trials (default: 200)")
    parser.add_argument("--jobs",    type=int,  default=1,
                        help="Parallel Optuna workers (default: 1; use 1 for asyncio loop)")
    parser.add_argument("--start",   type=str,  default=BACKTEST_DIAG_START_DATE)
    parser.add_argument("--end",     type=str,  default=BACKTEST_DIAG_END_DATE)
    parser.add_argument("--storage", type=str,  default=f"sqlite:///{_STUDY_DB}",
                        help="Optuna storage URI (default: sqlite in data/)")
    parser.add_argument("--resume",  action="store_true",
                        help="Resume an existing study instead of creating fresh")
    args = parser.parse_args()

    # ── 1. Load all cached price data ────────────────────────────────────────
    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR
    ticker_cache, spy_df = _load_universe_cache(cache_dir)

    if len(ticker_cache) < 10:
        print("ERROR: fewer than 10 tickers in cache. Download price data first:")
        print("  python3 wfo_cache.py --download")
        sys.exit(1)

    start_date = args.start
    end_date   = args.end
    print(f"Universe : {len(ticker_cache)} tickers")
    print(f"Window   : {start_date} → {end_date}")
    print(f"Trials   : {args.trials}")
    print(f"Storage  : {args.storage}")
    print()

    # ── 2. Create / resume Optuna study ──────────────────────────────────────
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
            load_if_exists=True,          # safe to re-run: won't wipe existing trials
            sampler=optuna.samplers.TPESampler(seed=42),
        )

    trial_times: List[float] = []

    # ── 3. Objective closure ──────────────────────────────────────────────────
    def objective(trial) -> float:
        import time
        t0 = time.perf_counter()

        params = _build_params(trial)
        trades = asyncio.run(_run_trial(ticker_cache, spy_df, start_date, end_date, params))
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
            f"trades={metrics['total_trades']:>5}  "
            f"E={metrics['expectancy']:>+.4f}  PF={metrics['profit_factor']:.3f}  "
            f"WR={metrics['win_rate']:.1f}%  "
            f"elapsed={elapsed/60:.1f}min  ETA≈{eta_min:.0f}min",
            flush=True,
        )
        return score

    # ── 4. Run optimisation ───────────────────────────────────────────────────
    print(f"Starting optimisation at {datetime.now().strftime('%H:%M:%S')} …\n")
    study.optimize(objective, n_trials=args.trials, n_jobs=args.jobs, show_progress_bar=False)

    # ── 5. Extract best result ────────────────────────────────────────────────
    best_trial  = study.best_trial
    best_params = _build_params_from_values(best_trial.params)

    # Re-run best params to get full metrics
    print("\nRe-running best parameters for final metrics…", flush=True)
    best_trades  = asyncio.run(_run_trial(ticker_cache, spy_df, start_date, end_date, best_params))
    best_metrics = _compute_metrics(best_trades)

    # ── 6. Save JSON ──────────────────────────────────────────────────────────
    output = {
        "trial_number":  best_trial.number,
        "score":         best_trial.value,
        "metrics":       best_metrics,
        "params":        best_trial.params,
        "generated_at":  datetime.now().isoformat(),
    }
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Best params saved to {_OUTPUT_PATH}")

    # ── 7. Print report ───────────────────────────────────────────────────────
    _print_report(best_params, best_metrics, best_trial.number)


def _build_params_from_values(values: dict) -> BacktestParams:
    """Reconstruct BacktestParams from a dict of Optuna best trial values."""
    return BacktestParams(
        rs_threshold    = values["rs_threshold"],
        cci_threshold   = values["cci_threshold"],
        ema_distance    = values["ema_distance"],
        score_threshold = values["score_threshold"],
        breakout_weight = values["breakout_weight"],
        pullback_weight = values["pullback_weight"],
        tdl_bonus       = values["tdl_bonus"],
        vcp_bonus       = values["vcp_bonus"],
        cooldown_days   = int(values["cooldown_days"]),
        brk_vol_mult    = values["brk_vol_mult"],
        brk_stop_atr    = values["brk_stop_atr"],
        brk_min_pct     = values["brk_min_pct"],
        brk_gap_pct     = values["brk_gap_pct"],
        brk_trail_mult  = values["brk_trail_mult"],
        tp_multiple     = values["tp_multiple"],
    )


if __name__ == "__main__":
    main()
