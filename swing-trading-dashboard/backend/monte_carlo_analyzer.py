"""
monte_carlo_analyzer.py
=======================
Monte Carlo stress-test for the swing trading backtest engine.

Loads individual trade records from cache/backtest_diagnostics.json
(produced by the V5 BacktestEngine) and runs:

  1. Bootstrap resampling (1k-10k iterations) → equity curve distribution,
     95th/99th-percentile MDD, probability of ruin.

  2. Trade destruction test → drop 5% most profitable trades, re-measure
     Profit Factor and Expectancy (outlier-dependency check).

  3. Console summary with confidence intervals + optional Matplotlib charts.

Usage
-----
  # Basic (1,000 iterations, default data source):
  python monte_carlo_analyzer.py

  # 5,000 iterations, custom ruin threshold:
  python monte_carlo_analyzer.py --iterations 5000 --ruin-threshold -20

  # Load a custom trade CSV instead of the backtest diagnostics cache:
  python monte_carlo_analyzer.py --csv path/to/trades.csv

  # Fetch trades directly from a running backend API (e.g. VPS):
  python monte_carlo_analyzer.py --url http://<vps-ip>:8000/api/diagnostics/backtest

  # Skip charts (headless / VPS):
  python monte_carlo_analyzer.py --no-plot

CSV column requirements (if using --csv):
  rr_achieved       : R-multiple per trade (e.g. 2.1, -1.0)
  portfolio_pnl_pct : position-sized % portfolio impact (optional; falls back to rr_achieved)
  is_win            : bool
  setup_type        : string label (optional; used for breakdown)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Constants / defaults
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CACHE = Path(__file__).parent / "cache" / "backtest_diagnostics.json"
DEFAULT_ITERATIONS   = 1_000
DEFAULT_RUIN_THRESHOLD = -25.0   # R-units; equity drawdown past this = ruin
DESTRUCTION_DROP_PCT  = 0.05     # fraction of top winners to drop
CONFIDENCE_LEVELS     = (0.90, 0.95, 0.99)


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_from_json(path: Path) -> pd.DataFrame:
    with open(path) as f:
        data = json.load(f)
    trades = data.get("trades", [])
    if not trades:
        sys.exit(f"ERROR: no trades found in {path}")
    df = pd.DataFrame(trades)
    print(f"Loaded {len(df)} trades from {path}")
    print(f"  Period: {data.get('start_date','?')} -> {data.get('end_date','?')}")
    return df


def load_from_url(url: str) -> pd.DataFrame:
    """Fetch trade data from a running backend API endpoint."""
    import urllib.request
    print(f"Fetching trades from {url} ...")
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    trades = data.get("trades", [])
    if not trades:
        sys.exit(f"ERROR: no trades found at {url}")
    df = pd.DataFrame(trades)
    print(f"Loaded {len(df)} trades from API")
    print(f"  Period  : {data.get('start_date','?')} -> {data.get('end_date','?')}")
    print(f"  Tickers : {data.get('tickers_run','?')}")
    if data.get("generated_at"):
        print(f"  Generated: {data['generated_at']}")
    return df


def load_from_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"rr_achieved"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"ERROR: CSV missing columns: {missing}")
    print(f"Loaded {len(df)} trades from {path}")
    return df


def prepare_r_series(df: pd.DataFrame) -> np.ndarray:
    """Return array of R-multiples.  Falls back to rr_achieved if portfolio_pnl_pct absent."""
    if "portfolio_pnl_pct" in df.columns:
        col = "portfolio_pnl_pct"
    else:
        col = "rr_achieved"
    r = df[col].astype(float).values
    # Sanity guard: cap extreme outliers at ±20 R to prevent distortion
    r = np.clip(r, -20.0, 20.0)
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Core statistics helpers
# ─────────────────────────────────────────────────────────────────────────────

def equity_curve(r: np.ndarray) -> np.ndarray:
    """Cumulative sum of R-multiples (starting at 0)."""
    return np.concatenate(([0.0], np.cumsum(r)))


def max_drawdown(curve: np.ndarray) -> float:
    """Maximum peak-to-trough drawdown in R-units (always <= 0)."""
    peak = np.maximum.accumulate(curve)
    dd   = curve - peak
    return float(dd.min())


def profit_factor(r: np.ndarray) -> float:
    wins   = r[r > 0]
    losses = r[r < 0]
    if len(losses) == 0:
        return float("inf")
    gross_profit = wins.sum()
    gross_loss   = abs(losses.sum())
    return round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf")


def expectancy(r: np.ndarray) -> float:
    return round(float(r.mean()), 4)


def win_rate(r: np.ndarray) -> float:
    return round(float((r > 0).mean() * 100), 2)


def compute_base_stats(r: np.ndarray) -> dict:
    curve = equity_curve(r)
    return {
        "n_trades":      len(r),
        "win_rate_pct":  win_rate(r),
        "expectancy_r":  expectancy(r),
        "profit_factor": profit_factor(r),
        "total_r":       round(float(r.sum()), 2),
        "max_dd_r":      round(max_drawdown(curve), 2),
        "avg_win_r":     round(float(r[r > 0].mean()), 3) if (r > 0).any() else 0.0,
        "avg_loss_r":    round(float(r[r < 0].mean()), 3) if (r < 0).any() else 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def run_bootstrap(
    r: np.ndarray,
    n_iter: int,
    ruin_threshold: float,
    rng: np.random.Generator,
) -> dict:
    """
    Bootstrap with replacement over n_iter shuffles.

    Returns dict of arrays (one value per iteration):
      final_r, max_dd, pf, exp
    """
    n = len(r)
    final_r  = np.empty(n_iter)
    mdd_arr  = np.empty(n_iter)
    pf_arr   = np.empty(n_iter)
    exp_arr  = np.empty(n_iter)

    for i in range(n_iter):
        sample   = rng.choice(r, size=n, replace=True)
        curve    = equity_curve(sample)
        final_r[i]  = curve[-1]
        mdd_arr[i]  = max_drawdown(curve)
        pf_arr[i]   = profit_factor(sample)
        exp_arr[i]  = expectancy(sample)

    ruin_mask = mdd_arr <= ruin_threshold
    prob_ruin = float(ruin_mask.mean() * 100)

    return {
        "final_r":   final_r,
        "max_dd":    mdd_arr,
        "pf":        pf_arr,
        "exp":       exp_arr,
        "prob_ruin": prob_ruin,
    }


def percentile_ci(arr: np.ndarray, levels=CONFIDENCE_LEVELS) -> dict:
    """Return low/median/high at each confidence level."""
    lo_pcts  = [(1 - c) / 2 * 100    for c in levels]
    hi_pcts  = [(1 - (1 - c) / 2) * 100 for c in levels]
    out = {"median": round(float(np.median(arr)), 3)}
    for c, lo, hi in zip(levels, lo_pcts, hi_pcts):
        label = f"{int(c*100)}pct"
        out[label] = {
            "lo":  round(float(np.percentile(arr, lo)), 3),
            "hi":  round(float(np.percentile(arr, hi)), 3),
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Trade destruction test
# ─────────────────────────────────────────────────────────────────────────────

def run_destruction_test(r: np.ndarray, drop_pct: float, rng: np.random.Generator, n_iter: int = 500) -> dict:
    """
    Randomly drop `drop_pct` fraction of the top winners per iteration.
    Returns distribution of PF and Expectancy after destruction.
    """
    n_drop = max(1, int(len(r) * drop_pct))
    pf_arr  = np.empty(n_iter)
    exp_arr = np.empty(n_iter)

    # Sort indices by magnitude of win (largest wins first)
    win_idx = np.where(r > 0)[0]
    sorted_wins = win_idx[np.argsort(-r[win_idx])]   # descending by win size

    for i in range(n_iter):
        # Pick n_drop random winners from the TOP 20% largest wins
        pool = sorted_wins[:max(n_drop, len(sorted_wins) // 5)]
        drop_set = set(rng.choice(pool, size=min(n_drop, len(pool)), replace=False).tolist())
        mask     = np.array([j not in drop_set for j in range(len(r))])
        sub      = r[mask]
        pf_arr[i]  = profit_factor(sub)
        exp_arr[i] = expectancy(sub)

    return {
        "n_dropped_per_iter": n_drop,
        "pf":  {"mean": round(float(pf_arr[np.isfinite(pf_arr)].mean()), 3),
                "p5":   round(float(np.percentile(pf_arr[np.isfinite(pf_arr)], 5)), 3),
                "p50":  round(float(np.median(pf_arr[np.isfinite(pf_arr)])), 3)},
        "exp": {"mean": round(float(exp_arr.mean()), 4),
                "p5":   round(float(np.percentile(exp_arr, 5)), 4),
                "p50":  round(float(np.median(exp_arr)), 4)},
        "edge_survives_pct": round(float((exp_arr > 0).mean() * 100), 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Console output
# ─────────────────────────────────────────────────────────────────────────────

DIVIDER = "=" * 62
THIN    = "-" * 62

def print_section(title: str):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)

def print_base_stats(stats: dict):
    print_section("ACTUAL TRADE HISTORY (baseline)")
    print(f"  Trades          : {stats['n_trades']}")
    print(f"  Win Rate        : {stats['win_rate_pct']:.1f}%")
    print(f"  Expectancy      : {stats['expectancy_r']:+.4f} R/trade")
    print(f"  Profit Factor   : {stats['profit_factor']:.3f}")
    print(f"  Total Return    : {stats['total_r']:+.2f} R")
    print(f"  Max Drawdown    : {stats['max_dd_r']:.2f} R")
    print(f"  Avg Win         : {stats['avg_win_r']:+.3f} R")
    print(f"  Avg Loss        : {stats['avg_loss_r']:+.3f} R")

def print_bootstrap_results(mc: dict, n_iter: int, ruin_threshold: float):
    print_section(f"MONTE CARLO BOOTSTRAP  ({n_iter:,} iterations)")

    ci_mdd = percentile_ci(-mc["max_dd"])   # negate so we print positive drawdown
    ci_ret = percentile_ci(mc["final_r"])
    ci_pf  = percentile_ci(mc["pf"][np.isfinite(mc["pf"])])
    ci_exp = percentile_ci(mc["exp"])

    print(f"\n  Max Drawdown (R-units, absolute):")
    print(f"    Median          : {ci_mdd['median']:.2f} R")
    for lvl in ("90pct", "95pct", "99pct"):
        if lvl in ci_mdd:
            print(f"    {lvl} worst-case : {ci_mdd[lvl]['hi']:.2f} R")

    print(f"\n  Final Return (R-units):")
    print(f"    Median          : {ci_ret['median']:+.2f} R")
    print(f"    90% CI          : [{ci_ret['90pct']['lo']:+.2f}, {ci_ret['90pct']['hi']:+.2f}]")
    print(f"    95% CI          : [{ci_ret['95pct']['lo']:+.2f}, {ci_ret['95pct']['hi']:+.2f}]")

    print(f"\n  Profit Factor:")
    print(f"    Median          : {ci_pf['median']:.3f}")
    print(f"    90% CI          : [{ci_pf['90pct']['lo']:.3f}, {ci_pf['90pct']['hi']:.3f}]")

    print(f"\n  Expectancy (R/trade):")
    print(f"    Median          : {ci_exp['median']:+.4f}")
    print(f"    95% CI          : [{ci_exp['95pct']['lo']:+.4f}, {ci_exp['95pct']['hi']:+.4f}]")

    print(f"\n{THIN}")
    print(f"  Ruin threshold  : {ruin_threshold:.1f} R drawdown")
    pct = mc['prob_ruin']
    flag = "  *** HIGH RISK ***" if pct > 10 else ("  ** ELEVATED **" if pct > 2 else "  OK")
    print(f"  P(Ruin)         : {pct:.2f}%{flag}")
    print(THIN)

def print_destruction_results(dest: dict):
    print_section(f"TRADE DESTRUCTION TEST  (drop top {DESTRUCTION_DROP_PCT*100:.0f}% winners)")
    print(f"  Trades dropped per run : {dest['n_dropped_per_iter']}")
    print(f"  Profit Factor  (p50/p5): {dest['pf']['p50']:.3f} / {dest['pf']['p5']:.3f}")
    print(f"  Expectancy     (p50/p5): {dest['exp']['p50']:+.4f} / {dest['exp']['p5']:+.4f}")
    flag = "YES" if dest['edge_survives_pct'] >= 90 else ("MARGINAL" if dest['edge_survives_pct'] >= 70 else "NO")
    print(f"  Edge survives (exp>0)  : {dest['edge_survives_pct']:.1f}%  =>  {flag}")
    print(THIN)

def print_setup_breakdown(df: pd.DataFrame, r: np.ndarray):
    if "setup_type" not in df.columns:
        return
    print_section("BREAKDOWN BY SETUP TYPE")
    df2 = df.copy()
    df2["_r"] = r
    for stype, grp in df2.groupby("setup_type"):
        sub = grp["_r"].values
        if len(sub) < 3:
            continue
        print(f"  {stype:<16} n={len(sub):>4}  WR={win_rate(sub):>5.1f}%  "
              f"Exp={expectancy(sub):+.3f}R  PF={profit_factor(sub):.2f}  "
              f"MDD={max_drawdown(equity_curve(sub)):.2f}R")
    print(THIN)


# ─────────────────────────────────────────────────────────────────────────────
# Matplotlib charts
# ─────────────────────────────────────────────────────────────────────────────

def plot_results(mc: dict, base_stats: dict, n_iter: int):
    try:
        import matplotlib
        matplotlib.use("Agg")          # non-interactive; saves to file
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[charts] matplotlib not installed; skipping plots.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"Monte Carlo Stress-Test  |  {n_iter:,} iterations  |  "
                 f"n={base_stats['n_trades']} trades", fontsize=13, fontweight="bold")

    # 1. Final Return distribution
    ax = axes[0, 0]
    ax.hist(mc["final_r"], bins=80, color="#4CAF50", edgecolor="none", alpha=0.8)
    ax.axvline(base_stats["total_r"], color="gold", lw=2, label=f"Actual {base_stats['total_r']:+.1f}R")
    ax.axvline(0, color="red", lw=1.5, linestyle="--", label="Breakeven")
    ax.set_title("Distribution of Final Return (R)")
    ax.set_xlabel("Total R"); ax.set_ylabel("Frequency")
    ax.legend(fontsize=8)

    # 2. Max Drawdown distribution
    ax = axes[0, 1]
    ax.hist(mc["max_dd"], bins=80, color="#F44336", edgecolor="none", alpha=0.8)
    ax.axvline(base_stats["max_dd_r"], color="gold", lw=2, label=f"Actual {base_stats['max_dd_r']:.1f}R")
    p95 = float(np.percentile(mc["max_dd"], 5))   # 5th percentile of MDD (worst)
    p99 = float(np.percentile(mc["max_dd"], 1))
    ax.axvline(p95, color="orange", lw=1.5, linestyle="--", label=f"95th worst {p95:.1f}R")
    ax.axvline(p99, color="red",    lw=1.5, linestyle=":",  label=f"99th worst {p99:.1f}R")
    ax.set_title("Distribution of Max Drawdown (R)")
    ax.set_xlabel("Max Drawdown R"); ax.set_ylabel("Frequency")
    ax.legend(fontsize=8)

    # 3. Profit Factor distribution
    ax = axes[1, 0]
    pf_finite = mc["pf"][np.isfinite(mc["pf"])]
    ax.hist(pf_finite, bins=80, color="#2196F3", edgecolor="none", alpha=0.8)
    ax.axvline(1.0, color="red", lw=1.5, linestyle="--", label="PF=1 (breakeven)")
    ax.axvline(base_stats["profit_factor"], color="gold", lw=2,
               label=f"Actual PF {base_stats['profit_factor']:.2f}")
    ax.set_title("Distribution of Profit Factor")
    ax.set_xlabel("Profit Factor"); ax.set_ylabel("Frequency")
    ax.legend(fontsize=8)
    ax.set_xlim(0, min(pf_finite.max(), 8))

    # 4. Expectancy distribution
    ax = axes[1, 1]
    ax.hist(mc["exp"], bins=80, color="#9C27B0", edgecolor="none", alpha=0.8)
    ax.axvline(0, color="red", lw=1.5, linestyle="--", label="0 R/trade")
    ax.axvline(base_stats["expectancy_r"], color="gold", lw=2,
               label=f"Actual {base_stats['expectancy_r']:+.4f}R")
    ax.set_title("Distribution of Expectancy (R/trade)")
    ax.set_xlabel("R/trade"); ax.set_ylabel("Frequency")
    ax.legend(fontsize=8)

    plt.tight_layout()
    out = Path(__file__).parent / "cache" / "monte_carlo_results.png"
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"\n[charts] Saved to {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Monte Carlo stress-test for backtest trade history")
    p.add_argument("--iterations", "-n", type=int,   default=DEFAULT_ITERATIONS,
                   help=f"Bootstrap iterations (default {DEFAULT_ITERATIONS})")
    p.add_argument("--ruin-threshold", "-r", type=float, default=DEFAULT_RUIN_THRESHOLD,
                   help=f"Ruin drawdown in R-units, negative (default {DEFAULT_RUIN_THRESHOLD})")
    p.add_argument("--csv",  type=str, default=None,
                   help="Load trades from CSV instead of backtest_diagnostics.json")
    p.add_argument("--url",  type=str, default=None,
                   help="Fetch trades from API URL (e.g. http://<vps>:8000/api/diagnostics/backtest)")
    p.add_argument("--no-plot", action="store_true",
                   help="Skip matplotlib charts (headless / VPS)")
    p.add_argument("--seed", type=int, default=42,
                   help="RNG seed for reproducibility (default 42)")
    return p.parse_args()


def main():
    args = parse_args()
    rng  = np.random.default_rng(args.seed)

    # ── Load data ────────────────────────────────────────────────────────────
    if args.url:
        df = load_from_url(args.url)
    elif args.csv:
        df = load_from_csv(args.csv)
    elif DEFAULT_CACHE.exists():
        df = load_from_json(DEFAULT_CACHE)
    else:
        sys.exit(f"ERROR: {DEFAULT_CACHE} not found. Run a backtest first, or pass --csv / --url.")

    r = prepare_r_series(df)

    if len(r) < 20:
        sys.exit(f"ERROR: only {len(r)} trades — need at least 20 for meaningful Monte Carlo.")

    # ── Baseline stats ───────────────────────────────────────────────────────
    base = compute_base_stats(r)
    print_base_stats(base)
    print_setup_breakdown(df, r)

    # ── Bootstrap ────────────────────────────────────────────────────────────
    print(f"\nRunning {args.iterations:,} bootstrap iterations…", end=" ", flush=True)
    mc = run_bootstrap(r, args.iterations, args.ruin_threshold, rng)
    print("done.")
    print_bootstrap_results(mc, args.iterations, args.ruin_threshold)

    # ── Destruction test ─────────────────────────────────────────────────────
    print("\nRunning trade destruction test…", end=" ", flush=True)
    dest = run_destruction_test(r, DESTRUCTION_DROP_PCT, rng)
    print("done.")
    print_destruction_results(dest)

    # ── Charts ───────────────────────────────────────────────────────────────
    if not args.no_plot:
        plot_results(mc, base, args.iterations)

    print(f"\n{DIVIDER}")
    print("  VERDICT")
    print(DIVIDER)
    p_ruin = mc["prob_ruin"]
    med_exp = float(np.median(mc["exp"]))
    edge_ok = dest["edge_survives_pct"] >= 80
    if p_ruin < 1 and med_exp > 0 and edge_ok:
        verdict = "ROBUST — edge persists under adverse sequence + outlier removal."
    elif p_ruin < 5 and med_exp > 0:
        verdict = "ACCEPTABLE — positive expectancy but monitor drawdown risk."
    elif p_ruin >= 10 or med_exp <= 0:
        verdict = "FRAGILE — high ruin probability or expectancy collapses. Review system."
    else:
        verdict = "MARGINAL — review position sizing and max drawdown limits."
    print(f"  {verdict}")
    print(DIVIDER)


if __name__ == "__main__":
    main()
