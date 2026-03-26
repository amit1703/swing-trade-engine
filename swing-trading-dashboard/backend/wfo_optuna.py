"""
wfo_optuna.py — Walk-Forward Optuna Validation  (Clean Re-Optimization v3)
═══════════════════════════════════════════════════════════════════════════
Runs per-window Optuna IS optimization across 4 rolling windows (2019–2024),
applies best IS params to each OOS window, then reruns all OOS windows with
frozen #433 params for comparison. Prints a full WFO report.

Objective (v3, Calmar-adjusted with sanity penalties):
    calmar = expectancy / max(0.1, |max_drawdown_r|)
    score  = calmar × PF × log(N+1) × min(1, sqrt(N/MIN_TRADES))
    penalty: N < 100 → score ≤ -9.0 (strong)
    penalty: win_rate > 80% → score = -5.0 (overfit signal)

Exit logic: EMA20 trail is primary; TARGET exits still fire when
    high >= entry + tp_multiple × risk (tp_multiple is tuned here).
    ATR trail (brk_trail_mult, base_trail_mult) is NOT used — removed from search space.

Tunable params (12): score_threshold [50,85],
    brk_stop_atr [0.8,1.5], brk_min_pct, brk_gap_pct,
    brk_donchian_n [20,60], brk_atr_expansion [0.0,0.5], brk_min_consolidation [3,8],
    rs_threshold [-0.02,0.03], ema_distance [0.5,1.2],
    base_quality_min [15,30], base_vol_ratio [1.1,1.5],
    ema_break_buffer [0.0,0.01]
Frozen (from WFO analysis — stop tuning, use constants):
    cci_threshold = CCI_THRESHOLD (-40.0)   ← WFO converged; no longer in search
    brk_vol_mult  = BRK_VOL_MULT  (1.35)    ← WFO baseline; no longer in search
Removed from search: tp_multiple (TARGET exits disabled — pure EMA/S/R exit model)
                     brk_trail_mult, base_trail_mult (ATR-trail inactive in ema20 mode)

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
import multiprocessing
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from backtest_engine import BacktestEngine, BacktestParams
from constants import CONCURRENCY_LIMIT, WFO_CACHE_DIR, CCI_THRESHOLD, BRK_VOL_MULT
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
# brk_trail_mult / base_trail_mult removed — ATR trail inactive in ema20 mode
# cci_threshold / brk_vol_mult removed — frozen from WFO analysis (CCI_THRESHOLD / BRK_VOL_MULT)
TUNABLE_PARAMS = [
    # General
    "score_threshold",        # unified quality gate [50,85] on 0-100 normalized scale
    # tp_multiple removed — TARGET exits disabled; exit model is pure EMA20/S/R trail
    # RES_BREAKOUT
    "brk_stop_atr",
    "brk_min_pct",
    "brk_gap_pct",
    "brk_donchian_n",         # rolling-high lookback [20,60]; live default=63
    "brk_atr_expansion",      # ATR expansion filter [0.0,0.5]; live default=0.0 (disabled)
    "brk_min_consolidation",  # consolidation bars [3,8]; live default=3
    # PULLBACK (unfrozen from trial #433 values)
    "rs_threshold",           # RS gate [-0.02,0.03]; was frozen at 0.066
    "ema_distance",           # EMA distance [0.5,1.2]; was frozen at 1.651
    # BASE PATTERNS
    "base_quality_min",       # min quality score [15,30]; was frozen at 19
    "base_vol_ratio",         # min vol ratio [1.1,1.5]; was [1.2,1.6]; v4 clamped
    # EXIT BEHAVIOUR
    "ema_break_buffer",       # EMA20 trailing buffer [0.0,0.01]; prevents noise exits
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
# Universe liquidity pre-filter
# ─────────────────────────────────────────────────────────────────────────────

def _prefilter_universe_liquidity(
    ticker_cache: Dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
    min_price: float = 10.0,
    min_avg_vol: float = 500_000,
    max_tickers: int = 350,
) -> Dict[str, pd.DataFrame]:
    """Filter universe to liquid, reasonably-priced tickers before IS optimization.

    Applies filters using data within [start_date, end_date] to avoid forward-looking
    bias. Keeps SPY unconditionally (needed for RS / regime computation).

    Filters:
      1. Price > min_price (last close in window)
      2. 50-day avg volume > min_avg_vol
      3. Top max_tickers by dollar volume (price × avg_vol)
    """
    candidates = []
    for ticker, df in ticker_cache.items():
        if ticker == "SPY":
            continue
        try:
            mask = (df.index >= start_date) & (df.index <= end_date)
            sl = df[mask]
            if len(sl) < 20:
                continue
            adj_col = "Adj Close" if "Adj Close" in sl.columns else "Close"
            last_price = float(sl[adj_col].iloc[-1])
            if last_price < min_price:
                continue
            if "Volume" not in sl.columns:
                continue
            avg_vol = float(sl["Volume"].rolling(50, min_periods=20).mean().iloc[-1])
            if pd.isna(avg_vol) or avg_vol < min_avg_vol:
                continue
            candidates.append((ticker, last_price * avg_vol))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = {t for t, _ in candidates[:max_tickers]}

    # Always keep SPY
    filtered = {t: df for t, df in ticker_cache.items() if t in selected or t == "SPY"}
    return filtered


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

    # ── Stop / exit distance diagnostics ─────────────────────────────────────
    stop_dists  = []
    exit_dists  = []
    hold_days   = []
    for t in trades:
        ep = t.get("entry_price", 0.0)
        if ep > 0:
            sl = t.get("initial_stop", 0.0)
            ex_p = t.get("exit_price", ep)
            if sl > 0:
                stop_dists.append((ep - sl) / ep * 100.0)
            exit_dists.append((ex_p - ep) / ep * 100.0)
        hd = t.get("holding_days")
        if hd is not None:
            hold_days.append(hd)

    def _med(lst):
        if not lst:
            return 0.0
        s = sorted(lst)
        n = len(s)
        return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)

    stop_stats = {
        "avg_pct":    round(sum(stop_dists) / len(stop_dists), 2) if stop_dists else 0.0,
        "min_pct":    round(min(stop_dists), 2) if stop_dists else 0.0,
        "median_pct": round(_med(stop_dists), 2) if stop_dists else 0.0,
        "max_pct":    round(max(stop_dists), 2) if stop_dists else 0.0,
    }
    exit_stats = {
        "avg_pct":    round(sum(exit_dists) / len(exit_dists), 2) if exit_dists else 0.0,
    }
    hold_stats = {
        "avg_bars":    round(sum(hold_days) / len(hold_days), 1) if hold_days else 0.0,
    }

    return {
        "total_trades":         total,
        "win_rate":             round(win_rate * 100, 1),
        "expectancy":           round(expectancy, 4),
        "profit_factor":        round(min(profit_factor, 99.0), 3),
        "max_drawdown_r":       round(max_dd, 2),
        "portfolio_return_pct": portfolio_return_pct,
        "by_setup":             dict(by_setup),
        "stop_stats":           stop_stats,
        "exit_stats":           exit_stats,
        "hold_stats":           hold_stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Objective score (identical to optimize_v5.py)
# ─────────────────────────────────────────────────────────────────────────────

def _objective_score(metrics: dict, trial_num: int = -1) -> float:
    """Calmar-adjusted objective with sanity penalties and smooth trade-count scaling.

    Penalties (applied before the main formula):
      - total_trades < 100  → strong penalty (score ≤ -9.0); too few trades = no signal
      - win_rate > 80%      → score = -5.0; unrealistic selectivity = overfit signal

    score = calmar × PF × log(N+1) × min(1.0, sqrt(N / MIN_TRADES))
    calmar = expectancy / max(0.1, |max_drawdown_r|)

    vs old objective (E × PF × log(N+1)):
    - Penalises high-drawdown solutions — prefers smoother equity curves.
    - Smooth MIN_TRADES scaling removes the hard -99 cliff at exactly 200 trades.
      Trials below MIN_TRADES are penalised proportionally, not zeroed out.
    """
    n        = metrics["total_trades"]
    ex       = metrics["expectancy"]
    pf       = min(metrics["profit_factor"], 10.0)
    mdd      = abs(metrics.get("max_drawdown_r", 0.0))
    win_rate = metrics.get("win_rate", 0.0)   # already in %

    # ── Sanity penalties ─────────────────────────────────────────────────────
    if n < 100:
        # Strong penalty: score never improves above -9.0 regardless of E
        score = -9.0 - (100 - n) * 0.01
        logger.info(
            "trial=%d  PENALTY<100trades  N=%d  WR=%.1f%%  E=%+.4f  score=%.4f",
            trial_num, n, win_rate, ex, score,
        )
        return score

    if win_rate > 80.0:
        logger.info(
            "trial=%d  PENALTY>80%%wr  N=%d  WR=%.1f%%  E=%+.4f  score=-5.0",
            trial_num, n, win_rate, ex,
        )
        return -5.0

    if ex <= 0 or pf <= 0:
        return float(ex)  # negative — Optuna will route away from these

    calmar      = ex / max(0.1, mdd)
    raw         = calmar * pf * math.log(n + 1)
    trade_scale = min(1.0, math.sqrt(n / MIN_TRADES))
    score       = raw * trade_scale

    # ── Engine diversity penalty (soft) ──────────────────────────────────────
    # Penalise trials where a single engine dominates > 70% of trades.
    # Penalty scales linearly: 70% domination → ×1.0; 100% → ×0.4
    by_setup = metrics.get("by_setup", {})
    _n_total = sum(by_setup.values())
    if _n_total > 0:
        _max_pct = max(by_setup.values()) / _n_total
        if _max_pct > 0.70:
            _diversity_factor = max(0.4, 1.0 - (_max_pct - 0.70) * 2.0)
            score *= _diversity_factor
            logger.info(
                "trial=%d  ENGINE_IMBALANCE  max_engine_pct=%.1f%%  diversity_factor=%.3f",
                trial_num, _max_pct * 100, _diversity_factor,
            )

    logger.info(
        "trial=%d  N=%d  WR=%.1f%%  E=%+.4f  MDD=%.2f  score=%.4f",
        trial_num, n, win_rate, ex, mdd, score,
    )
    return score


# ─────────────────────────────────────────────────────────────────────────────
# Backtest runner — ProcessPoolExecutor for true CPU parallelism
# ─────────────────────────────────────────────────────────────────────────────

def _run_ticker_sync(args: tuple) -> dict:
    """
    Top-level worker for ProcessPoolExecutor — runs one ticker synchronously.

    Must be module-level (not nested) so multiprocessing can pickle it on Windows
    (spawn start method). Each worker creates its own asyncio event loop via
    asyncio.run(), avoiding any shared state.

    Returns a dict with keys: trades, signals_evaluated, signals_passed.
    """
    ticker, ticker_df, spy_df, start_date, end_date, params, sr_zones = args
    try:
        engine = BacktestEngine(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            ticker_df=ticker_df,
            spy_df=spy_df,
            params=params,
            sr_zones_override=sr_zones,
        )
        summary = asyncio.run(engine.run())
        return {
            "trades":             [t.to_dict() for t in summary.trades],
            "signals_evaluated":  summary.signals_evaluated,
            "signals_passed":     summary.signals_passed,
        }
    except Exception as exc:
        logger.debug("Trial ticker %s failed: %s", ticker, exc)
        return {"trades": [], "signals_evaluated": 0, "signals_passed": 0}


def _run_trial(
    ticker_cache: Dict[str, pd.DataFrame],
    spy_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
    params: BacktestParams,
    sr_zones_cache: Optional[Dict] = None,
    max_workers: Optional[int] = None,
) -> Tuple[List[dict], int, int]:
    """
    Run full universe backtest with given params.

    Returns (trades, total_signals_evaluated, total_signals_passed).

    Uses ProcessPoolExecutor for true CPU parallelism (bypasses GIL).
    sr_zones_cache: pre-computed per-ticker SR zones dict — skips KDE recomputation
                    per trial (~2× speedup).
    max_workers: cap on subprocess count; defaults to os.cpu_count().
    """
    tickers = [t for t in ticker_cache if t != "SPY"]
    if not tickers:
        return [], 0, 0

    args_list = [
        (
            t,
            ticker_cache[t],
            spy_df,
            start_date,
            end_date,
            params,
            sr_zones_cache.get(t) if sr_zones_cache is not None else None,
        )
        for t in tickers
    ]

    n_workers = min(max_workers or (os.cpu_count() or 4), len(tickers))
    all_trades: List[dict] = []
    total_sig_eval: int = 0
    total_sig_pass: int = 0
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for batch in pool.map(_run_ticker_sync, args_list, chunksize=1):
            all_trades.extend(batch["trades"])
            total_sig_eval += batch.get("signals_evaluated", 0)
            total_sig_pass += batch.get("signals_passed", 0)
    return all_trades, total_sig_eval, total_sig_pass


# ─────────────────────────────────────────────────────────────────────────────
# Param builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_params(trial) -> BacktestParams:
    """Sample BacktestParams from Optuna trial.

    Tunable (12): score_threshold [50,85],
                  brk_stop_atr [0.8,1.5], brk_min_pct, brk_gap_pct,
                  brk_donchian_n [20,60], brk_atr_expansion [0.0,0.5],
                  brk_min_consolidation [3,8],
                  rs_threshold [-0.02,0.03], ema_distance [0.5,1.2],
                  base_quality_min [15,30], base_vol_ratio [1.1,1.5],
                  ema_break_buffer [0.0,0.01]
    Frozen (7):   breakout_weight, pullback_weight, tdl_bonus, vcp_bonus,
                  cooldown_days, cci_threshold (=CCI_THRESHOLD), brk_vol_mult (=BRK_VOL_MULT)
    Removed:      brk_trail_mult, base_trail_mult — ATR trail inactive in ema20 mode
    """
    return BacktestParams(
        # ── Frozen ───────────────────────────────────────────────────────────
        breakout_weight  = 1.724,
        pullback_weight  = 1.842,
        tdl_bonus        = 1.016,
        vcp_bonus        = 1.370,
        cooldown_days    = 4,
        # Frozen from WFO analysis — use constants, stop optimizing
        cci_threshold    = CCI_THRESHOLD,   # -40.0
        brk_vol_mult     = BRK_VOL_MULT,    # 1.35
        # ── General ─────────────────────────────────────────────────────────
        # score_threshold: unified quality gate on normalized 0-100 scale.
        # Backtest normalizes raw_score × weight to 0-100 before comparison.
        # Range [50,85]: 50=lenient (filter bottom quartile), 85=strict (top 15%)
        score_threshold      = trial.suggest_float("score_threshold",      50.0, 85.0),
        # tp_multiple removed — TARGET exits disabled; exit model is pure EMA20/S/R trail
        # ── RES_BREAKOUT ────────────────────────────────────────────────────
        brk_stop_atr         = trial.suggest_float("brk_stop_atr",         0.8,  1.5),
        brk_min_pct          = trial.suggest_float("brk_min_pct",          0.01, 0.05),
        brk_gap_pct          = trial.suggest_float("brk_gap_pct",          0.01, 0.08),
        brk_donchian_n       = trial.suggest_int(  "brk_donchian_n",       20,   60),
        brk_atr_expansion    = trial.suggest_float("brk_atr_expansion",    0.0,  0.5),
        brk_min_consolidation= trial.suggest_int(  "brk_min_consolidation",3,    8),
        # ── PULLBACK ─────────────────────────────────────────────────────────
        rs_threshold         = trial.suggest_float("rs_threshold",         -0.02, 0.03),
        ema_distance         = trial.suggest_float("ema_distance",          0.5,   1.2),
        # ── BASE PATTERNS ───────────────────────────────────────────────────
        base_quality_min     = trial.suggest_int(  "base_quality_min",     15,   30),
        base_vol_ratio       = trial.suggest_float("base_vol_ratio",        1.1,  1.5),
        # ── EXIT BEHAVIOUR ──────────────────────────────────────────────────
        ema_break_buffer     = trial.suggest_float("ema_break_buffer",      0.0,  0.01),
    )


def _build_params_from_values(values: dict) -> BacktestParams:
    """Reconstruct BacktestParams from Optuna best_trial.params dict.

    Frozen params use hardcoded values.
    Tunable params use .get(key, fallback) — fallbacks are range midpoints
    so this works when called with a partial dict (e.g. --resume with missing keys).
    """
    missing = [k for k in TUNABLE_PARAMS if k not in values]
    if missing:
        logger.warning(
            "_build_params_from_values: missing keys %s — falling back to range midpoints",
            missing,
        )
    return BacktestParams(
        # ── Frozen ───────────────────────────────────────────────────────────
        breakout_weight  = 1.724,
        pullback_weight  = 1.842,
        tdl_bonus        = 1.016,
        vcp_bonus        = 1.370,
        cooldown_days    = 4,
        # Frozen from WFO analysis — use constants directly
        cci_threshold    = CCI_THRESHOLD,   # -40.0 (was tunable [-45,-20])
        brk_vol_mult     = BRK_VOL_MULT,    # 1.35  (was tunable [1.1,1.6])
        # ── General ──────────────────────────────────────────────────────────
        score_threshold       = values.get("score_threshold",       67.5),  # midpoint [50,85]
        # tp_multiple removed — TARGET exits disabled
        # ── RES_BREAKOUT ─────────────────────────────────────────────────────
        brk_stop_atr          = values.get("brk_stop_atr",          1.15),  # midpoint [0.8,1.5]
        brk_min_pct           = values.get("brk_min_pct",           0.02),
        brk_gap_pct           = values.get("brk_gap_pct",           0.036),
        brk_donchian_n        = int(values.get("brk_donchian_n",    40)),   # midpoint [20,60]
        brk_atr_expansion     = values.get("brk_atr_expansion",     0.0),  # live default: disabled
        brk_min_consolidation = int(values.get("brk_min_consolidation", 5)),# midpoint [3,8]
        # ── PULLBACK ─────────────────────────────────────────────────────────
        rs_threshold          = values.get("rs_threshold",          0.005), # midpoint [-0.02,0.03]
        ema_distance          = values.get("ema_distance",           0.85), # midpoint [0.5,1.2]
        # ── BASE PATTERNS ────────────────────────────────────────────────────
        base_quality_min      = int(values.get("base_quality_min",  22)),   # midpoint [15,30]
        base_vol_ratio        = values.get("base_vol_ratio",         1.3),  # midpoint [1.1,1.5]
        # ── EXIT BEHAVIOUR ───────────────────────────────────────────────────
        ema_break_buffer      = values.get("ema_break_buffer",       0.0),  # default: exact EMA20
    )


def _frozen_params() -> BacktestParams:
    """Return trial #433 params — current BacktestParams() defaults."""
    return BacktestParams()


# ─────────────────────────────────────────────────────────────────────────────
# Per-window IS optimization
# ─────────────────────────────────────────────────────────────────────────────

def _optimize_window(
    window_num:        int,
    is_start:          str,
    is_end:            str,
    ticker_cache:      Dict[str, pd.DataFrame],
    spy_df:            Optional[pd.DataFrame],
    n_trials:          int,
    storage:           str,
    resume:            bool,
    inner_max_workers: Optional[int] = None,
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

    # ── Liquidity pre-filter: reduce universe to top ~300 liquid tickers ──────
    # Filters: price > $10, avg vol > 500k, top 350 by dollar volume.
    # Applied per-window using only in-sample data to avoid forward bias.
    _pre_liq = _prefilter_universe_liquidity(
        ticker_cache, is_start, is_end,
        min_price=10.0, min_avg_vol=500_000, max_tickers=350,
    )
    _liq_dropped = len(ticker_cache) - len(_pre_liq)
    print(
        f"  W{window_num}: Liquidity filter — {len(_pre_liq)} tickers kept "
        f"({_liq_dropped} dropped, price<$10 or vol<500k or outside top-350).",
        flush=True,
    )
    ticker_cache = _pre_liq

    # Pre-compute SR zones once per window — reused across all Optuna trials.
    # Zones depend only on price data; precomputing here saves ~15-20% per trial.
    from engines.engine1 import calculate_sr_zones as _calc_sr_zones
    print(f"  W{window_num}: Pre-computing SR zones for {len(ticker_cache)} tickers…", flush=True)
    sr_zones_cache: Dict[str, list] = {}
    for _tz, _df in ticker_cache.items():
        try:
            sr_zones_cache[_tz] = _calc_sr_zones(_tz, _df)
        except Exception:
            sr_zones_cache[_tz] = []
    print(f"  W{window_num}: SR zones ready.", flush=True)

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
            trades, _sig_eval, _sig_pass = _run_trial(
                ticker_cache, spy_df, is_start, is_end, params,
                sr_zones_cache=sr_zones_cache,
                max_workers=inner_max_workers,
            )
            metrics = _compute_metrics(trades)
            score   = _objective_score(metrics, trial_num=trial.number)
            elapsed = time.perf_counter() - t0
            trial_times.append(elapsed)
            avg = sum(trial_times) / len(trial_times)
            done_so_far = trial.number + 1
            eta_min = max(0, (n_trials - done_so_far) * avg / 60)
            # Store key metrics on trial for top-10 display later
            trial.set_user_attr("N",              metrics["total_trades"])
            trial.set_user_attr("win_rate",        metrics["win_rate"])
            trial.set_user_attr("expectancy",      metrics["expectancy"])
            trial.set_user_attr("profit_factor",   metrics["profit_factor"])
            trial.set_user_attr("max_drawdown_r",  metrics["max_drawdown_r"])
            _ss = metrics.get("stop_stats", {})
            _hs = metrics.get("hold_stats", {})
            print(
                f"  W{window_num} trial {trial.number:>4}  "
                f"score={score:>8.4f}  E={metrics['expectancy']:>+.4f}  "
                f"WR={metrics['win_rate']:.1f}%  "
                f"PF={metrics['profit_factor']:.3f}  N={metrics['total_trades']}  "
                f"MDD={metrics['max_drawdown_r']:.2f}  "
                f"stop={_ss.get('avg_pct',0):.2f}%  hold={_hs.get('avg_bars',0):.1f}d  "
                f"port={metrics['portfolio_return_pct']:>+.1f}%  "
                f"{elapsed/60:.1f}min  ETA≈{eta_min:.0f}min",
                flush=True,
            )
            # ── Sanity logging (per trial) ────────────────────────────────────
            _by_setup = metrics.get("by_setup", {})
            _n_total_setups = sum(_by_setup.values())
            _setup_pct = "  ".join(
                f"{k}={v}({v/_n_total_setups*100:.0f}%)" if _n_total_setups else f"{k}={v}"
                for k, v in sorted(_by_setup.items())
            ) or "none"
            _vol_ratios = [
                t["setup_meta"]["volume_ratio"]
                for t in trades
                if isinstance(t.get("setup_meta"), dict)
                and t["setup_meta"].get("volume_ratio") is not None
            ]
            _avg_vol  = (sum(_vol_ratios) / len(_vol_ratios)) if _vol_ratios else None
            _min_vol  = min(_vol_ratios) if _vol_ratios else None
            _max_vol  = max(_vol_ratios) if _vol_ratios else None
            _ema_dists = [
                abs(t["entry_price"] - t.get("initial_stop", 0)) / max(t.get("initial_stop", 1), 1)
                for t in trades
                if t.get("setup_type") in ("PULLBACK",) and t.get("entry_price", 0) > 0
            ]
            _avg_ema_dist = (sum(_ema_dists) / len(_ema_dists)) if _ema_dists else None
            _hold_days = [t["holding_days"] for t in trades if t.get("holding_days") is not None]
            _avg_hold = (sum(_hold_days) / len(_hold_days)) if _hold_days else None
            # Rejection rate: signals that reached detection vs those that became trades
            _pct_rejected = (
                (1.0 - _sig_pass / _sig_eval) * 100
                if _sig_eval > 0 else None
            )
            vol_str  = (f"min={_min_vol:.2f} avg={_avg_vol:.2f} max={_max_vol:.2f}"
                        if _avg_vol is not None else "n/a")
            hold_str = f"{_avg_hold:.1f}d" if _avg_hold is not None else "n/a"
            rej_str  = f"{_pct_rejected:.1f}%" if _pct_rejected is not None else "n/a"
            print(
                f"    SANITY  total={metrics['total_trades']}  "
                f"by_engine=[{_setup_pct}]  "
                f"vol_ratio=[{vol_str}]  "
                f"ema_dist={'%.3f' % _avg_ema_dist if _avg_ema_dist is not None else 'n/a'}  "
                f"avg_hold={hold_str}  "
                f"sig_eval={_sig_eval}  sig_pass={_sig_pass}  pct_rejected={rej_str}",
                flush=True,
            )
            # ── Trade quality warnings ─────────────────────────────────────────
            _warnings = []
            if _avg_vol is not None and _avg_vol > 1.8:
                _warnings.append(f"HIGH_VOL_RATIO={_avg_vol:.2f}")
            if _avg_hold is not None and _avg_hold < 2:
                _warnings.append(f"SHORT_HOLD={_avg_hold:.1f}d")
            if _avg_hold is not None and _avg_hold > 20:
                _warnings.append(f"LONG_HOLD={_avg_hold:.1f}d")
            if _n_total_setups > 0:
                _dom_pct = max(_by_setup.values()) / _n_total_setups
                if _dom_pct > 0.70:
                    _dom_engine = max(_by_setup, key=_by_setup.get)
                    _warnings.append(f"ENGINE_SKEW:{_dom_engine}={_dom_pct*100:.0f}%")
            if _pct_rejected is not None and (_pct_rejected < 60 or _pct_rejected > 98):
                _warnings.append(f"REJECTION_OUT_OF_RANGE={rej_str}")
            if _warnings:
                print(f"    ⚠ WARNINGS: {' | '.join(_warnings)}", flush=True)
            return score

        study.optimize(objective, n_trials=remaining, n_jobs=1, show_progress_bar=False)

        # ── Print top 10 IS trials by score ──────────────────────────────────
        completed_trials = [t for t in study.trials if t.state.name == "COMPLETE"]
        top10 = sorted(
            completed_trials,
            key=lambda t: t.value if t.value is not None else float("-inf"),
            reverse=True,
        )[:10]
        print(f"\n  W{window_num} — Top 10 IS trials (by score):")
        print(
            f"  {'rank':>4}  {'#trial':>6}  {'score':>8}  "
            f"{'N':>5}  {'WR%':>6}  {'E(R)':>8}  {'MDD':>6}"
        )
        print(f"  {'─'*4}  {'─'*6}  {'─'*8}  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*6}")
        for rank, t in enumerate(top10, start=1):
            n_t   = t.user_attrs.get("N", "?")
            wr_t  = t.user_attrs.get("win_rate", 0.0)
            ex_t  = t.user_attrs.get("expectancy", 0.0)
            mdd_t = t.user_attrs.get("max_drawdown_r", 0.0)
            print(
                f"  {rank:>4}  #{t.number:<5}  {(t.value or 0.0):>8.4f}  "
                f"{n_t:>5}  {wr_t:>6.1f}  {ex_t:>+8.4f}  {mdd_t:>6.2f}"
            )
        # Parameter distributions across top-10
        print(f"\n  Parameter distributions (top-10 trials):")
        import statistics as _stats
        for param in TUNABLE_PARAMS:
            vals = [t.params[param] for t in top10 if param in t.params]
            if not vals:
                continue
            mn   = min(vals)
            mx   = max(vals)
            mean = _stats.mean(vals)
            fmt  = ".0f" if isinstance(vals[0], int) else ".4f"
            print(f"    {param:<22}  min={mn:{fmt}}  max={mx:{fmt}}  mean={mean:{fmt}}")
        print(flush=True)

    best        = study.best_trial
    best_params = _build_params_from_values(best.params)

    # Re-evaluate IS period with best params to get full metrics
    print(f"  W{window_num}: Re-evaluating IS with best params (trial #{best.number})…", flush=True)
    is_trades, _, _ = _run_trial(
        ticker_cache, spy_df, is_start, is_end, best_params,
        sr_zones_cache=sr_zones_cache,
        max_workers=inner_max_workers,
    )
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
    print(f"  Objective: Calmar×PF×log(N+1)×scale  |  14 tunable params  |  N<100/WR>80% penalized")
    print(f"{'═' * W}")
    print(f"\n  Exit model = ATR initial stop + EMA20 trailing — VERIFIED")
    print(f"  Exit logic is PURE EMA/S/R — no target exits active\n")

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

    # ── Section B2: Exit / stop diagnostics ──────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SECTION B2 — EXIT DIAGNOSTICS  (optimized OOS — stop/exit distances, holding time)")
    print(f"  {'─' * (W - 2)}")
    print(f"\n  {'Win':<4}  {'StopDist avg%':>14}  {'StopDist med%':>14}  "
          f"{'StopDist min/max%':>18}  {'ExitDist avg%':>14}  {'AvgHold(days)':>14}")
    print(f"  {'─'*4}  {'─'*14}  {'─'*14}  {'─'*18}  {'─'*14}  {'─'*14}")
    for r in results:
        ss = r.oos_metrics.get("stop_stats",  {})
        es = r.oos_metrics.get("exit_stats",  {})
        hs = r.oos_metrics.get("hold_stats",  {})
        stop_rng = f"{ss.get('min_pct',0):.2f} / {ss.get('max_pct',0):.2f}"
        print(
            f"  {r.window_num:<4}  {ss.get('avg_pct',0):>14.2f}  {ss.get('median_pct',0):>14.2f}  "
            f"{stop_rng:>18}  {es.get('avg_pct',0):>+14.2f}  {hs.get('avg_bars',0):>14.1f}"
        )

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
    parser.add_argument(
        "--parallel-windows", action="store_true",
        help=(
            "Run IS optimization for all windows concurrently via ThreadPoolExecutor. "
            "Each window's per-trial work still uses ProcessPoolExecutor for tickers. "
            "CPU budget is divided evenly across windows to avoid oversubscription."
        ),
    )
    args = parser.parse_args()

    selected = {int(w.strip()) for w in args.windows.split(",")}
    windows_to_run = [w for w in WFO_WINDOWS if w[0] in selected]

    if not windows_to_run:
        print(f"ERROR: no valid windows in --windows={args.windows!r}  (valid: 1,2,3,4)")
        sys.exit(1)

    # ── System integrity confirmation ─────────────────────────────────────────
    print("=" * 60)
    print("EXIT MODEL: EMA20 + S/R ONLY")
    print("NO TARGET EXITS ACTIVE")
    print("PARAMS ALIGNED WITH OPTUNA RANGES")
    print("=" * 60, flush=True)

    # ── 1. Load price data ────────────────────────────────────────────────────
    _DATA_DIR.mkdir(exist_ok=True)
    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR
    ticker_cache, spy_df = _load_universe_cache(cache_dir)

    if len(ticker_cache) < 10:
        print("ERROR: fewer than 10 tickers in cache.")
        print("  Download price data first (see wfo_cache.py).")
        sys.exit(1)

    n_cpu = os.cpu_count() or 4
    parallel_windows = getattr(args, "parallel_windows", False)
    n_win = len(windows_to_run)
    # When running windows in parallel, divide CPU budget to avoid oversubscription
    inner_workers = max(1, n_cpu // n_win) if parallel_windows else None

    print(f"\nWalk-Forward Optuna Validation")
    print(f"  Windows  : {[w[0] for w in windows_to_run]}")
    print(f"  IS trials: {args.trials} per window")
    print(f"  Universe : {len(ticker_cache)} tickers")
    print(f"  Resume   : {args.resume}")
    print(f"  CPUs     : {n_cpu}  parallel-windows={parallel_windows}"
          + (f"  inner-workers={inner_workers}" if parallel_windows else ""))
    print()

    all_results: List[WindowOptResult] = []

    # ── 2a. IS Optimization phase ─────────────────────────────────────────────
    # Either sequential (default) or parallel across windows (--parallel-windows).
    # Parallel mode uses ThreadPoolExecutor so each window thread can still spawn
    # ProcessPoolExecutor workers for tickers without hitting nested-spawn limits.

    is_phase_results: Dict[int, Tuple[BacktestParams, dict, int, float]] = {}

    def _run_one_window_is(w_args):
        wn, ws, we, _, _ = w_args
        st = f"sqlite:///{_DATA_DIR}/wfo_final_w{wn}.db"
        print(f"\n{'═' * 70}")
        print(f"  Window {wn}: IS {ws}→{we}")
        print(f"{'═' * 70}")
        print(f"\n[IS-W{wn}] Running {args.trials} Optuna trials…", flush=True)
        t0 = datetime.now()
        res = _optimize_window(
            wn, ws, we, ticker_cache, spy_df,
            args.trials, st, args.resume, inner_workers,
        )
        elapsed = (datetime.now() - t0).total_seconds() / 60
        bp, im, btn, bs = res
        print(
            f"\n[IS-W{wn}] Done in {elapsed:.1f}min  "
            f"best trial #{btn}  score={bs:.4f}  "
            f"E={im['expectancy']:+.4f}  PF={im['profit_factor']:.3f}  "
            f"N={im['total_trades']}",
            flush=True,
        )
        return wn, res

    if parallel_windows and n_win > 1:
        print(f"  [parallel-windows] IS phase: {n_win} windows in ThreadPoolExecutor", flush=True)
        with ThreadPoolExecutor(max_workers=n_win) as tpe:
            for wn, res in tpe.map(_run_one_window_is, windows_to_run):
                is_phase_results[wn] = res
    else:
        for w_args in windows_to_run:
            wn, res = _run_one_window_is(w_args)
            is_phase_results[wn] = res

    # ── 2. Per-window OOS evaluation loop ─────────────────────────────────────
    for window_num, is_start, is_end, oos_start, oos_end in windows_to_run:
        storage = f"sqlite:///{_DATA_DIR}/wfo_final_w{window_num}.db"

        print(f"\n{'═' * 70}")
        print(f"  Window {window_num}: OOS {oos_start}→{oos_end}")
        print(f"{'═' * 70}")

        best_params, is_metrics, best_trial_n, best_score = is_phase_results[window_num]
        print(
            f"\n[IS] best trial #{best_trial_n}  score={best_score:.4f}  "
            f"E={is_metrics['expectancy']:+.4f}  PF={is_metrics['profit_factor']:.3f}  "
            f"N={is_metrics['total_trades']}",
            flush=True,
        )

        # ── 2b. OOS with optimized params ─────────────────────────────────────
        print(f"\n[OOS-opt] Evaluating OOS with optimized params…", flush=True)
        oos_trades, _, _ = _run_trial(ticker_cache, spy_df, oos_start, oos_end, best_params)
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
        frozen_trades, _, _ = _run_trial(ticker_cache, spy_df, oos_start, oos_end, frozen)
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
    # Required on Windows: prevents recursive subprocess spawning when
    # ProcessPoolExecutor workers import this module.
    multiprocessing.freeze_support()
    main()
