"""
oos_validation.py — Out-of-sample validation across 3 time windows.
════════════════════════════════════════════════════════════════════
Loads frozen params from best_params_pb.json, best_params_brk.json,
and best_params_base.json, then runs the full combined backtest
(PULLBACK + RES_BREAKOUT + BASE) on three separate time windows.

Usage:
    cd backend
    python3 oos_validation.py

Windows:
    In-sample : 2023-01-01 → 2024-12-31  (what Optuna trained on)
    OOS 1     : 2020-01-01 → 2021-12-31  (COVID crash + recovery)
    OOS 2     : 2017-01-01 → 2019-12-31  (pre-COVID normal market)

Output:
    Prints a comparison table per window + per engine breakdown.
    Saves results to data/oos_validation.json.
"""

from __future__ import annotations

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

sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import BacktestEngine, BacktestParams
from constants import CONCURRENCY_LIMIT, WFO_CACHE_DIR

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("oos_validation")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).parent
_DATA_DIR    = _BACKEND_DIR / "data"
_OUTPUT_PATH = _DATA_DIR / "oos_validation.json"

# ─────────────────────────────────────────────────────────────────────────────
# Windows
# ─────────────────────────────────────────────────────────────────────────────

WINDOWS = [
    ("In-sample",  "2023-01-01", "2024-12-31"),
    ("OOS-1",      "2020-01-01", "2021-12-31"),
    ("OOS-2",      "2017-01-01", "2019-12-31"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Param loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_params() -> BacktestParams:
    """
    Build frozen BacktestParams from the three optimizer JSON outputs.
    Falls back to BacktestParams defaults if a JSON is missing
    (e.g. best_params_base.json not yet generated).
    """
    def _read(path: Path) -> dict:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            print(f"  Loaded {path.name}  (trial #{data['trial_number']}, score={data['score']:.4f})")
            return data["params"]
        print(f"  WARNING: {path.name} not found — using BacktestParams defaults for those fields.")
        return {}

    print("Loading optimizer results…")
    pb  = _read(_DATA_DIR / "best_params_pb.json")
    brk = _read(_DATA_DIR / "best_params_brk.json")
    base= _read(_DATA_DIR / "best_params_base.json")
    print()

    # PB fields
    rs_threshold    = pb.get("rs_threshold",    0.088)
    cci_threshold   = pb.get("cci_threshold",  -107.6)
    ema_distance    = pb.get("ema_distance",    2.094)
    pullback_weight = pb.get("pullback_weight", 2.536)
    tdl_bonus       = pb.get("tdl_bonus",       0.573)
    vcp_bonus       = pb.get("vcp_bonus",       0.738)
    cooldown_days   = int(pb.get("cooldown_days", 5))
    tp_multiple     = pb.get("tp_multiple",     5.161)

    # BRK fields (run 2 values take precedence if present)
    score_threshold     = brk.get("score_threshold",    5.791)
    breakout_weight     = brk.get("breakout_weight",    2.009)
    brk_vol_mult        = brk.get("brk_vol_mult",       2.310)
    brk_min_pct         = brk.get("brk_min_pct",        0.0)
    brk_stop_atr        = brk.get("brk_stop_atr",       0.953)
    brk_gap_pct         = brk.get("brk_gap_pct",        0.042)
    brk_trail_mult      = brk.get("brk_trail_mult",     5.928)
    brk_regime_factor   = brk.get("brk_regime_factor",  0.861)
    brk_donchian_n      = int(brk.get("brk_donchian_n", 68))
    brk_pivot_strength  = int(brk.get("brk_pivot_strength", 2))
    brk_atr_expansion   = brk.get("brk_atr_expansion",  0.0)
    brk_min_consolidation = int(brk.get("brk_min_consolidation", 10))

    # BASE fields
    base_weight      = base.get("base_weight",      1.0)
    base_trail_mult  = base.get("base_trail_mult",  4.162)
    base_vol_ratio   = base.get("base_vol_ratio",   1.5)
    base_quality_min = int(base.get("base_quality_min", 25))
    # score_threshold from base optimizer takes precedence if available
    if "score_threshold" in base:
        score_threshold = base["score_threshold"]

    return BacktestParams(
        rs_threshold         = rs_threshold,
        cci_threshold        = cci_threshold,
        ema_distance         = ema_distance,
        pullback_weight      = pullback_weight,
        tdl_bonus            = tdl_bonus,
        vcp_bonus            = vcp_bonus,
        cooldown_days        = cooldown_days,
        tp_multiple          = tp_multiple,
        score_threshold      = score_threshold,
        breakout_weight      = breakout_weight,
        brk_vol_mult         = brk_vol_mult,
        brk_min_pct          = brk_min_pct,
        brk_stop_atr         = brk_stop_atr,
        brk_gap_pct          = brk_gap_pct,
        brk_trail_mult       = brk_trail_mult,
        brk_regime_factor    = brk_regime_factor,
        brk_donchian_n       = brk_donchian_n,
        brk_pivot_strength   = brk_pivot_strength,
        brk_atr_expansion    = brk_atr_expansion,
        brk_min_consolidation= brk_min_consolidation,
        base_weight          = base_weight,
        base_trail_mult      = base_trail_mult,
        base_vol_ratio       = base_vol_ratio,
        base_quality_min     = base_quality_min,
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

    print(f"Loading {len(parquet_files)} parquet files…", flush=True)
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
    print(f"  {len(ticker_cache)} tickers ({non_spy} non-SPY)\n", flush=True)
    return ticker_cache, spy_df


# ─────────────────────────────────────────────────────────────────────────────
# Backtest runner
# ─────────────────────────────────────────────────────────────────────────────

async def _run_window(
    ticker_cache: Dict[str, pd.DataFrame],
    spy_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
    params: BacktestParams,
) -> List[dict]:
    """Full universe, all engines, single time window."""
    tickers = [t for t in ticker_cache if t != "SPY"]
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def _run_one(ticker: str) -> List[dict]:
        async with sem:
            try:
                df = ticker_cache[ticker].loc[:end_date]
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    ticker_df=df,
                    spy_df=spy_df,
                    params=params,
                    setup_types=["PULLBACK", "RES_BREAKOUT", "BASE"],
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                logger.debug("Ticker %s failed: %s", ticker, exc)
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
            "total_trades": 0, "win_rate": 0.0, "expectancy": 0.0,
            "profit_factor": 0.0, "max_drawdown_r": 0.0,
            "by_setup": {}, "expectancy_by_setup": {},
            "win_rate_by_setup": {}, "pf_by_setup": {},
        }

    all_rr = [t["rr_achieved"] for t in trades if "rr_achieved" in t]

    def _stats(rr_list):
        if not rr_list:
            return 0.0, 0.0, 0.0
        wins   = [r for r in rr_list if r > 0]
        losses = [r for r in rr_list if r <= 0]
        wr     = len(wins) / len(rr_list)
        ex     = sum(rr_list) / len(rr_list)
        gl     = abs(sum(losses))
        pf     = sum(wins) / gl if gl > 0 else float("inf")
        return round(ex, 4), round(min(pf, 99.0), 3), round(wr * 100, 1)

    ex, pf, wr = _stats(all_rr)

    # Max drawdown
    peak, max_dd, running = 0.0, 0.0, 0.0
    for r in all_rr:
        running += r
        if running > peak:
            peak = running
        dd = running - peak
        if dd < max_dd:
            max_dd = dd

    # Per-setup breakdown
    by_setup: Dict[str, list] = defaultdict(list)
    for t in trades:
        if "rr_achieved" in t:
            by_setup[t.get("setup_type", "UNKNOWN")].append(t["rr_achieved"])

    ex_by  = {s: _stats(rr)[0] for s, rr in by_setup.items()}
    pf_by  = {s: _stats(rr)[1] for s, rr in by_setup.items()}
    wr_by  = {s: _stats(rr)[2] for s, rr in by_setup.items()}
    cnt_by = {s: len(rr)       for s, rr in by_setup.items()}

    return {
        "total_trades":         len(all_rr),
        "win_rate":             wr,
        "expectancy":           ex,
        "profit_factor":        pf,
        "max_drawdown_r":       round(max_dd, 2),
        "by_setup":             cnt_by,
        "expectancy_by_setup":  ex_by,
        "win_rate_by_setup":    wr_by,
        "pf_by_setup":          pf_by,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def _print_report(results: List[dict]) -> None:
    W = 68
    print(f"\n{'═' * W}")
    print(f"  OUT-OF-SAMPLE VALIDATION")
    print(f"{'═' * W}")

    # ── Overall summary table ─────────────────────────────────────────────────
    print(f"\n  {'Window':<14} {'Period':<24} {'N':>5} {'WR%':>6} {'E(R)':>8} {'PF':>6} {'MaxDD':>7}")
    print(f"  {'─'*14} {'─'*24} {'─'*5} {'─'*6} {'─'*8} {'─'*6} {'─'*7}")
    for r in results:
        m = r["metrics"]
        label  = r["label"]
        period = f"{r['start']} → {r['end']}"
        flag   = "  ◄ in-sample" if "In-sample" in label else ""
        print(
            f"  {label:<14} {period:<24} {m['total_trades']:>5} "
            f"{m['win_rate']:>6.1f} {m['expectancy']:>+8.4f} "
            f"{m['profit_factor']:>6.3f} {m['max_drawdown_r']:>7.2f}"
            f"{flag}"
        )

    # ── Per-engine breakdown ──────────────────────────────────────────────────
    setups = ["PULLBACK", "RES_BREAKOUT", "BASE"]
    print(f"\n{'─' * W}")
    print(f"  PER-ENGINE BREAKDOWN")
    print(f"{'─' * W}")

    for setup in setups:
        print(f"\n  [{setup}]")
        print(f"  {'Window':<14} {'N':>5} {'WR%':>6} {'E(R)':>8} {'PF':>6}")
        print(f"  {'─'*14} {'─'*5} {'─'*6} {'─'*8} {'─'*6}")
        for r in results:
            m   = r["metrics"]
            n   = m["by_setup"].get(setup, 0)
            ex  = m["expectancy_by_setup"].get(setup, 0.0)
            pf  = m["pf_by_setup"].get(setup, 0.0)
            wr  = m["win_rate_by_setup"].get(setup, 0.0)
            flag = "  ◄ in-sample" if "In-sample" in r["label"] else ""
            print(f"  {r['label']:<14} {n:>5} {wr:>6.1f} {ex:>+8.4f} {pf:>6.3f}{flag}")

    # ── Robustness verdict ────────────────────────────────────────────────────
    print(f"\n{'─' * W}")
    print(f"  ROBUSTNESS CHECK")
    print(f"{'─' * W}")

    oos_results = [r for r in results if "In-sample" not in r["label"]]
    all_positive = all(r["metrics"]["expectancy"] > 0 for r in oos_results)
    all_pf_above1 = all(r["metrics"]["profit_factor"] > 1.0 for r in oos_results)

    is_metrics   = next(r["metrics"] for r in results if "In-sample" in r["label"])
    oos_exp_vals = [r["metrics"]["expectancy"] for r in oos_results]
    oos_avg_exp  = sum(oos_exp_vals) / len(oos_exp_vals) if oos_exp_vals else 0
    degradation  = (is_metrics["expectancy"] - oos_avg_exp) / abs(is_metrics["expectancy"]) * 100 if is_metrics["expectancy"] != 0 else 0

    print(f"\n  In-sample expectancy   : {is_metrics['expectancy']:>+.4f} R")
    print(f"  OOS avg expectancy     : {oos_avg_exp:>+.4f} R")
    print(f"  Degradation            : {degradation:>+.1f}%")
    print()

    if all_positive and all_pf_above1:
        if degradation < 30:
            verdict = "ROBUST — params generalise well across regimes"
        elif degradation < 60:
            verdict = "MODERATE — some regime sensitivity, monitor live"
        else:
            verdict = "OVERFIT — large OOS degradation, re-examine params"
    else:
        verdict = "FRAGILE — OOS expectancy negative, do not trade live"

    print(f"  Verdict: {verdict}")
    print(f"\n{'═' * W}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    cache_dir = _BACKEND_DIR / WFO_CACHE_DIR
    ticker_cache, spy_df = _load_universe_cache(cache_dir)

    if len(ticker_cache) < 10:
        print("ERROR: fewer than 10 tickers in cache.")
        print("  Run:  python3 optimize_brk.py --download")
        sys.exit(1)

    params = _load_params()

    print("Frozen params summary:")
    print(f"  tp_multiple      = {params.tp_multiple:.3f}")
    print(f"  score_threshold  = {params.score_threshold:.3f}")
    print(f"  pullback_weight  = {params.pullback_weight:.3f}")
    print(f"  breakout_weight  = {params.breakout_weight:.3f}")
    print(f"  base_weight      = {params.base_weight:.3f}")
    print(f"  cci_threshold    = {params.cci_threshold:.1f}")
    print(f"  ema_distance     = {params.ema_distance:.3f}")
    print(f"  brk_trail_mult   = {params.brk_trail_mult:.3f}")
    print(f"  base_trail_mult  = {params.base_trail_mult:.3f}")
    print()

    all_results = []
    for label, start, end in WINDOWS:
        print(f"Running {label}: {start} → {end} …", flush=True)
        import time
        t0 = time.perf_counter()
        trades  = asyncio.run(_run_window(ticker_cache, spy_df, start, end, params))
        elapsed = time.perf_counter() - t0
        metrics = _compute_metrics(trades)
        print(
            f"  Done in {elapsed/60:.1f}min — "
            f"{metrics['total_trades']} trades, "
            f"E={metrics['expectancy']:+.4f}R, "
            f"PF={metrics['profit_factor']:.3f}, "
            f"WR={metrics['win_rate']:.1f}%",
            flush=True,
        )
        all_results.append({
            "label":   label,
            "start":   start,
            "end":     end,
            "metrics": metrics,
        })

    _print_report(all_results)

    output = {
        "generated_at": datetime.now().isoformat(),
        "params": {
            "tp_multiple":     params.tp_multiple,
            "score_threshold": params.score_threshold,
            "pullback_weight": params.pullback_weight,
            "breakout_weight": params.breakout_weight,
            "base_weight":     params.base_weight,
            "cci_threshold":   params.cci_threshold,
            "ema_distance":    params.ema_distance,
            "brk_trail_mult":  params.brk_trail_mult,
            "base_trail_mult": params.base_trail_mult,
        },
        "windows": all_results,
    }
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
