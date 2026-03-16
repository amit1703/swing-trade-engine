"""
wfo_optuna.py — Walk-Forward Optuna Validation  (Final V1 run)
═══════════════════════════════════════════════════════════════
Runs per-window Optuna IS optimization across 4 rolling windows (2019–2024),
applies best IS params to each OOS window, then reruns all OOS windows with
frozen #433 params for comparison. Prints a full WFO report.

Objective (v2, Calmar-adjusted):
    calmar = expectancy / max(0.1, |max_drawdown_r|)
    score  = calmar × PF × log(N+1) × min(1, sqrt(N/200))

vs previous objective (E × PF × log(N+1)):
    + Penalises high-drawdown solutions
    + Smooth trade-count scaling (no hard -99 cliff at 200 trades)

Tunable params (7): score_threshold [1.0,4.0], tp_multiple [1.5,9.0],
    brk_vol_mult, brk_stop_atr, brk_min_pct, brk_gap_pct, brk_trail_mult

Windows (IS=24 months, OOS=12 months, step=12 months, start=2019-01-01):
  W1: IS 2019-01-01→2020-12-31  OOS 2021-01-01→2021-12-31
  W2: IS 2020-01-01→2021-12-31  OOS 2022-01-01→2022-12-31
  W3: IS 2021-01-01→2022-12-31  OOS 2023-01-01→2023-12-31
  W4: IS 2022-01-01→2023-12-31  OOS 2024-01-01→2024-12-31

Usage:
    cd backend
    python3 wfo_optuna.py [--trials 1000] [--resume] [--windows 1,2,3,4]

Output:
    data/wfo_final_w1.db … wfo_final_w4.db   (Optuna SQLite per window)
    data/wfo_final_results.json               (full results)
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
_OUTPUT_PATH = _DATA_DIR / "wfo_final_results.json"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIN_TRADES    = 200

# 4 rolling windows: (window_num, IS_start, IS_end, OOS_start, OOS_end)
# IS=24 months, OOS=12 months, step=12 months, starting 2019-01-01
WFO_WINDOWS: List[Tuple[int, str, str, str, str]] = [
    (1, "2019-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    (2, "2020-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    (3, "2021-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    (4, "2022-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
]

# Tunable parameter names (used for stability table and best_params dict)
TUNABLE_PARAMS = [
    "score_threshold",
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
    """Calmar-adjusted objective with smooth trade-count scaling.

    score = calmar × PF × log(N+1) × min(1.0, sqrt(N / MIN_TRADES))

    calmar = expectancy / max(0.1, |max_drawdown_r|)

    vs old objective (E × PF × log(N+1)):
    - Penalises high-drawdown solutions — prefers smoother equity curves.
    - Smooth MIN_TRADES scaling removes the hard -99 cliff at exactly 200 trades.
      Trials below MIN_TRADES are penalised proportionally, not zeroed out.
    """
    n   = metrics["total_trades"]
    ex  = metrics["expectancy"]
    pf  = min(metrics["profit_factor"], 10.0)
    mdd = abs(metrics.get("max_drawdown_r", 0.0))

    if ex <= 0 or pf <= 0:
        return float(ex)  # negative — Optuna will route away from these

    calmar      = ex / max(0.1, mdd)
    raw         = calmar * pf * math.log(n + 1)
    trade_scale = min(1.0, math.sqrt(n / MIN_TRADES))
    return raw * trade_scale


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
    """Sample BacktestParams from Optuna trial.

    Tunable (7): score_threshold, tp_multiple, brk_vol_mult, brk_stop_atr,
                 brk_min_pct, brk_gap_pct, brk_trail_mult
    Frozen (5):  rs_threshold, cci_threshold, ema_distance,
                 breakout_weight, pullback_weight
    """
    return BacktestParams(
        # ── Frozen at trial #433 ─────────────────────────────────────────────
        rs_threshold    = 0.066,
        cci_threshold   = -54.5,
        ema_distance    = 1.651,
        breakout_weight = 1.724,
        pullback_weight = 1.842,
        tdl_bonus       = 1.016,
        vcp_bonus       = 1.370,
        cooldown_days   = 4,
        # ── Tunable ──────────────────────────────────────────────────────────
        # score_threshold gates ALL pullback signals — never been optimized before
        score_threshold = trial.suggest_float("score_threshold", 1.0,  4.0),
        tp_multiple     = trial.suggest_float("tp_multiple",     1.5,  9.0),
        brk_vol_mult    = trial.suggest_float("brk_vol_mult",    1.5,  3.5),
        brk_stop_atr    = trial.suggest_float("brk_stop_atr",    0.3,  2.0),
        brk_min_pct     = trial.suggest_float("brk_min_pct",     0.01, 0.05),
        brk_gap_pct     = trial.suggest_float("brk_gap_pct",     0.01, 0.08),
        brk_trail_mult  = trial.suggest_float("brk_trail_mult",  1.5,  8.0),
    )


def _build_params_from_values(values: dict) -> BacktestParams:
    """Reconstruct BacktestParams from Optuna best_trial.params dict.

    Frozen params fall back to trial #433 hardcoded values.
    Tunable params use .get(key, fallback) so this works
    when called with a partial dict (e.g. from --resume with missing keys).
    """
    missing = [k for k in TUNABLE_PARAMS if k not in values]
    if missing:
        logger.warning(
            "_build_params_from_values: missing keys %s — falling back to trial #433 defaults",
            missing,
        )
    return BacktestParams(
        # ── Frozen ───────────────────────────────────────────────────────────
        rs_threshold    = 0.066,
        cci_threshold   = -54.5,
        ema_distance    = 1.651,
        breakout_weight = 1.724,
        pullback_weight = 1.842,
        tdl_bonus       = 1.016,
        vcp_bonus       = 1.370,
        cooldown_days   = 4,
        # ── Tunable (fall back to trial #433 / current defaults) ─────────
        score_threshold = values.get("score_threshold", 2.50),
        tp_multiple     = values.get("tp_multiple",     5.80),
        brk_vol_mult    = values.get("brk_vol_mult",    3.0161),
        brk_stop_atr    = values.get("brk_stop_atr",    1.6675),
        brk_min_pct     = values.get("brk_min_pct",     0.04333),
        brk_gap_pct     = values.get("brk_gap_pct",     0.01021),
        brk_trail_mult  = values.get("brk_trail_mult",  6.906),
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
    # Pre-filter universe to tickers with data overlapping [is_start, is_end].
    # Done once per window so every trial runs a clean, smaller universe instead
    # of hitting "no dates in replay window" warnings hundreds of times.
    filtered_cache: Dict[str, pd.DataFrame] = {}
    for ticker, df in ticker_cache.items():
        try:
            idx = df.index
            if len(idx) > 0 and str(idx[0].date()) <= is_end and str(idx[-1].date()) >= is_start:
                filtered_cache[ticker] = df
        except Exception:
            pass
    dropped = len(ticker_cache) - len(filtered_cache)
    if dropped > 0:
        print(
            f"  W{window_num}: Pre-filtered universe — {len(filtered_cache)} tickers "
            f"({dropped} dropped, no data in {is_start}→{is_end}).",
            flush=True,
        )
    ticker_cache = filtered_cache

    try:
        import optuna
    except ImportError:
        print("ERROR: optuna not installed. Run: pip install optuna")
        sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # Per-window seed: gives structurally independent Latin hypercube starts
    # across all four windows instead of correlated exploration from seed=42.
    window_seed = window_num * 100 + 1  # W1→101  W2→201  W3→301  W4→401
    study_name  = f"wfo_final_w{window_num}"
    study = optuna.create_study(
        study_name=study_name,
        direction="maximize",
        storage=storage,
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=window_seed),
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
            done_so_far = trial.number + 1
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


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(results: List[WindowOptResult]) -> None:
    import statistics
    W = 90
    print(f"\n{'═' * W}")
    print(
        f"  WALK-FORWARD OPTUNA VALIDATION REPORT — FINAL V1  "
        f"({len(results)} windows, {datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    print(f"  Objective: Calmar×PF×log(N+1)×scale  |  7 tunable params  |  per-window seeds")
    print(f"{'═' * W}")

    # ── Section A: OOS performance table ─────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION A — OOS PERFORMANCE  (optimized IS params vs frozen #433)")
    print(f"  {'─' * (W - 2)}")
    print(
        f"  {'Win':<4} {'OOS Period':<25} {'Params':<10} "
        f"{'N':>5} {'WR%':>6} {'E(R)':>8} {'PF':>6} "
        f"{'MaxDD':>7} {'Port%':>7} {'SPY%':>7} {'Alpha':>7}"
    )
    print(
        f"  {'─'*4} {'─'*25} {'─'*10} "
        f"{'─'*5} {'─'*6} {'─'*8} {'─'*6} "
        f"{'─'*7} {'─'*7} {'─'*7} {'─'*7}"
    )

    def _row(win_num: int, oos_start: str, oos_end: str,
             label: str, m: dict, spy_pct: Optional[float]) -> None:
        period = f"{oos_start} → {oos_end}"
        n   = m["total_trades"]
        wr  = m["win_rate"]
        ex  = m["expectancy"]
        pf  = m["profit_factor"]
        dd  = m["max_drawdown_r"]
        pr  = m["portfolio_return_pct"]
        spy_str   = f"{spy_pct*100:>+.1f}" if spy_pct is not None else "  N/A"
        alpha_str = f"{pr - spy_pct*100:>+.1f}" if spy_pct is not None else "  N/A"
        print(
            f"  {win_num:<4} {period:<25} {label:<10} {n:>5} {wr:>6.1f} "
            f"{ex:>+8.4f} {pf:>6.3f} {dd:>7.2f} {pr:>+7.1f} "
            f"{spy_str:>7} {alpha_str:>7}"
        )

    for r in results:
        _row(r.window_num, r.oos_start, r.oos_end, "optimized", r.oos_metrics, r.spy_pct)
        _row(r.window_num, r.oos_start, r.oos_end, "frozen#433", r.frozen_metrics, r.spy_pct)
        print()

    # ── Section B: Combined OOS equity sparklines ─────────────────────────────
    print(f"  {'─' * (W - 2)}")
    print(f"  SECTION B — COMBINED OOS EQUITY CURVE  (portfolio return % per window)")
    print(f"  {'─' * (W - 2)}")

    opt_returns    = [r.oos_metrics["portfolio_return_pct"] for r in results]
    frozen_returns = [r.frozen_metrics["portfolio_return_pct"] for r in results]
    labels         = [f"W{r.window_num}({r.oos_start[:4]})" for r in results]

    print(f"\n  Optimized : {_sparkline(opt_returns)}  {opt_returns}")
    print(f"  Frozen#433: {_sparkline(frozen_returns)}  {frozen_returns}")
    print(f"  Windows   : {labels}")

    # Cumulative compounded return across all OOS windows
    opt_cum    = 1.0
    frozen_cum = 1.0
    for r in results:
        opt_cum    *= (1.0 + r.oos_metrics["portfolio_return_pct"] / 100.0)
        frozen_cum *= (1.0 + r.frozen_metrics["portfolio_return_pct"] / 100.0)

    print(f"\n  Cumulative OOS return (optimized) : {(opt_cum - 1)*100:>+.1f}%")
    print(f"  Cumulative OOS return (frozen#433): {(frozen_cum - 1)*100:>+.1f}%")

    spy_vals = [r.spy_pct for r in results if r.spy_pct is not None]
    if spy_vals:
        spy_cum = 1.0
        for s in spy_vals:
            spy_cum *= (1.0 + s)
        print(f"  SPY cumulative (OOS windows only) : {(spy_cum - 1)*100:>+.1f}%")

    # ── Section C: Parameter stability table ─────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION C — PARAMETER STABILITY  (tuned values across IS windows)")
    print(f"  {'─' * (W - 2)}")

    hdr2 = f"\n  {'Param':<20}" + "".join(
        f"{'W'+str(r.window_num)+'-best':>12}" for r in results
    )
    hdr2 += f"{'mean':>10} {'std':>8} {'CV':>6}  {'stable?':>10}"
    print(hdr2)
    print(f"  {'─'*20}" + "─" * (12 * len(results) + 36))

    for param in TUNABLE_PARAMS:
        vals = [r.best_params.get(param, float("nan")) for r in results]
        valid = [v for v in vals if not math.isnan(v)]
        if not valid:
            continue
        mean = statistics.mean(valid)
        std  = statistics.stdev(valid) if len(valid) > 1 else 0.0
        cv   = abs(std / mean) if mean != 0 else 0.0
        if cv < 0.15:
            stable = "✓ stable"
        elif cv < 0.30:
            stable = "⚠ moderate"
        else:
            stable = "✗ SENSITIVE"
        row  = f"  {param:<20}" + "".join(f"{v:>12.4f}" for v in vals)
        row += f"{mean:>10.4f} {std:>8.4f} {cv:>6.3f}  {stable:>10}"
        print(row)

    print(f"\n  CV < 0.15 = stable   CV 0.15–0.30 = moderate   CV > 0.30 = regime-sensitive")

    # ── Section D: Robustness verdict ─────────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION D — ROBUSTNESS VERDICT")
    print(f"  {'─' * (W - 2)}\n")

    oos_exps = [r.oos_metrics["expectancy"]   for r in results]
    is_exps  = [r.is_metrics["expectancy"]    for r in results]
    oos_pfs  = [r.oos_metrics["profit_factor"] for r in results]

    avg_is_exp  = sum(is_exps)  / len(is_exps)  if is_exps  else 0.0
    avg_oos_exp = sum(oos_exps) / len(oos_exps) if oos_exps else 0.0
    avg_oos_pf  = sum(oos_pfs)  / len(oos_pfs)  if oos_pfs  else 0.0
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


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-Forward Optuna Validation")
    parser.add_argument(
        "--trials", type=int, default=1000,
        help="Optuna trials per IS window (default: 1000)",
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

    selected = {int(w.strip()) for w in args.windows.split(",")}
    windows_to_run = [w for w in WFO_WINDOWS if w[0] in selected]

    if not windows_to_run:
        print(f"ERROR: no valid windows in --windows={args.windows!r}  (valid: 1,2,3,4)")
        sys.exit(1)

    # ── 1. Load price data ────────────────────────────────────────────────────
    _DATA_DIR.mkdir(exist_ok=True)
    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR
    ticker_cache, spy_df = _load_universe_cache(cache_dir)

    if len(ticker_cache) < 10:
        print("ERROR: fewer than 10 tickers in cache.")
        print("  Download price data first (see wfo_cache.py).")
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
        storage = f"sqlite:///{_DATA_DIR}/wfo_final_w{window_num}.db"

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
        oos_trades  = asyncio.run(
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
        frozen        = _frozen_params()
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
            is_start=is_start,
            is_end=is_end,
            oos_start=oos_start,
            oos_end=oos_end,
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
        "n_trials":     args.trials,
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
