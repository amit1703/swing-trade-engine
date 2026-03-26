"""
run_10y_mc.py
=============
One-shot runner: 10-year backtest (2016-01-01 → 2025-12-31) using the local
parquet cache, then Monte Carlo stress-test on the resulting trades.

Run from the backend directory:
    python run_10y_mc.py [--iterations N] [--no-plot]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import pandas as pd

# ── config ────────────────────────────────────────────────────────────────────
START_DATE = "2016-01-01"
END_DATE   = "2025-12-31"
OUT_JSON   = Path(__file__).parent / "cache" / "backtest_10y.json"
CACHE_DIR  = Path(__file__).parent / "data" / "price_cache"


def _tickers_with_cache() -> list[str]:
    """Return tickers that have parquet files in the price cache."""
    return [p.stem for p in sorted(CACHE_DIR.glob("*.parquet"))]


async def run_backtest(tickers: list[str]) -> list[dict]:
    from backtest_engine import run_backtest_universe

    total = len(tickers)
    t0 = time.time()

    async def _progress(done: int, _total: int):
        if done % 50 == 0 or done == _total:
            elapsed = time.time() - t0
            eta = elapsed / done * (_total - done) if done else 0
            print(f"  {done}/{_total} tickers  |  {elapsed:.0f}s elapsed  |  ETA {eta:.0f}s",
                  flush=True)

    print(f"Running 10-year backtest: {START_DATE} to {END_DATE}")
    print(f"Tickers: {total}  (from parquet cache)")

    trades = await run_backtest_universe(
        tickers,
        start_date=START_DATE,
        end_date=END_DATE,
        trail_mult_override=None,   # use V5 per-setup multipliers
        params=None,                # legacy mode (same as diagnostic backtest)
        progress_cb=_progress,
    )
    print(f"Backtest complete — {len(trades)} trades in {time.time()-t0:.1f}s")
    return trades


def save_cache(trades: list[dict]) -> None:
    payload = {
        "start_date":    START_DATE,
        "end_date":      END_DATE,
        "tickers_run":   len(_tickers_with_cache()),
        "total_trades":  len(trades),
        "trades":        trades,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    import tempfile, os
    fd, tmp = tempfile.mkstemp(dir=OUT_JSON.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, OUT_JSON)
    except Exception:
        os.unlink(tmp)
        raise
    print(f"Saved → {OUT_JSON}")


def run_monte_carlo(trades: list[dict], n_iter: int, no_plot: bool) -> None:
    import numpy as np
    from monte_carlo_analyzer import (
        prepare_r_series, compute_base_stats, run_bootstrap,
        run_destruction_test, print_base_stats, print_setup_breakdown,
        print_bootstrap_results, print_destruction_results,
        plot_results, DESTRUCTION_DROP_PCT, DIVIDER,
    )

    df  = pd.DataFrame(trades)
    r   = prepare_r_series(df)
    rng = np.random.default_rng(42)

    if len(r) < 20:
        sys.exit(f"ERROR: only {len(r)} trades — too few for Monte Carlo.")

    base = compute_base_stats(r)
    print_base_stats(base)
    print_setup_breakdown(df, r)

    print(f"\nRunning {n_iter:,} bootstrap iterations…", end=" ", flush=True)
    mc = run_bootstrap(r, n_iter, ruin_threshold=-25.0, rng=rng)
    print("done.")
    print_bootstrap_results(mc, n_iter, ruin_threshold=-25.0)

    print("\nRunning trade destruction test…", end=" ", flush=True)
    dest = run_destruction_test(r, DESTRUCTION_DROP_PCT, rng)
    print("done.")
    print_destruction_results(dest)

    if not no_plot:
        # Override output path to 10y-specific file
        import monte_carlo_analyzer as _mca
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(13, 9))
        fig.suptitle(
            f"10-Year Monte Carlo  |  {n_iter:,} iterations  |  "
            f"n={base['n_trades']} trades  |  {START_DATE} to {END_DATE}",
            fontsize=13, fontweight="bold",
        )
        import numpy as np

        def _hist(ax, data, color, label, vline_val=None, vline_label=None):
            ax.hist(data[np.isfinite(data)], bins=80, color=color, edgecolor="none", alpha=0.8)
            if vline_val is not None:
                ax.axvline(vline_val, color="gold", lw=2, label=vline_label)

        _hist(axes[0,0], mc["final_r"], "#4CAF50", "Final R")
        axes[0,0].axvline(base["total_r"], color="gold", lw=2, label=f"Actual {base['total_r']:+.1f}R")
        axes[0,0].axvline(0, color="red", lw=1.5, ls="--", label="Breakeven")
        axes[0,0].set_title("Final Return (R)"); axes[0,0].legend(fontsize=8)

        _hist(axes[0,1], mc["max_dd"], "#F44336", "MDD")
        axes[0,1].axvline(base["max_dd_r"], color="gold", lw=2, label=f"Actual {base['max_dd_r']:.1f}R")
        p95 = float(np.percentile(mc["max_dd"], 5))
        axes[0,1].axvline(p95, color="orange", lw=1.5, ls="--", label=f"95th worst {p95:.1f}R")
        axes[0,1].set_title("Max Drawdown (R)"); axes[0,1].legend(fontsize=8)

        pf_fin = mc["pf"][np.isfinite(mc["pf"])]
        _hist(axes[1,0], pf_fin, "#2196F3", "PF")
        axes[1,0].axvline(1.0, color="red", lw=1.5, ls="--", label="PF=1")
        axes[1,0].axvline(base["profit_factor"], color="gold", lw=2, label=f"Actual PF {base['profit_factor']:.2f}")
        axes[1,0].set_title("Profit Factor"); axes[1,0].legend(fontsize=8)
        axes[1,0].set_xlim(0, min(pf_fin.max(), 8))

        _hist(axes[1,1], mc["exp"], "#9C27B0", "Expectancy")
        axes[1,1].axvline(0, color="red", lw=1.5, ls="--", label="0 R/trade")
        axes[1,1].axvline(base["expectancy_r"], color="gold", lw=2, label=f"Actual {base['expectancy_r']:+.4f}R")
        axes[1,1].set_title("Expectancy (R/trade)"); axes[1,1].legend(fontsize=8)

        plt.tight_layout()
        out = Path(__file__).parent / "cache" / "monte_carlo_10y.png"
        plt.savefig(out, dpi=130, bbox_inches="tight")
        plt.close()
        print(f"\n[charts] Saved → {out}")

    # verdict
    p_ruin   = mc["prob_ruin"]
    med_exp  = float(__import__("numpy").median(mc["exp"]))
    edge_ok  = dest["edge_survives_pct"] >= 80
    print(f"\n{DIVIDER}")
    print("  VERDICT")
    print(DIVIDER)
    if p_ruin < 1 and med_exp > 0 and edge_ok:
        verdict = "ROBUST — edge persists under adverse sequence + outlier removal."
    elif p_ruin < 5 and med_exp > 0:
        verdict = "ACCEPTABLE — positive expectancy but monitor drawdown risk."
    elif p_ruin >= 10 or med_exp <= 0:
        verdict = "FRAGILE — high ruin probability or expectancy collapses."
    else:
        verdict = "MARGINAL — review position sizing and max drawdown limits."
    print(f"  {verdict}")
    print(DIVIDER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", "-n", type=int, default=5000)
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--skip-backtest", action="store_true",
                    help="Reload trades from cache/backtest_10y.json (skip re-running backtest)")
    args = ap.parse_args()

    if args.skip_backtest and OUT_JSON.exists():
        print(f"Loading cached trades from {OUT_JSON}")
        with open(OUT_JSON) as f:
            data = json.load(f)
        trades = data["trades"]
        print(f"Loaded {len(trades)} trades  ({data['start_date']} → {data['end_date']})")
    else:
        tickers = _tickers_with_cache()
        trades  = asyncio.run(run_backtest(tickers))
        save_cache(trades)

    run_monte_carlo(trades, args.iterations, args.no_plot)


if __name__ == "__main__":
    main()
