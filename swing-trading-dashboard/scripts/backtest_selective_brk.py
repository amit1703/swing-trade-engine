"""
backtest_selective_brk.py — SELECTIVE vs AGGRESSIVE RES_BREAKOUT diagnostic.

Runs the 2020-2024 backtest from the parquet cache with brk_aggressive_only=False
(default after diagnostic change) and prints a side-by-side comparison table.

Usage (run from repo root):
    cd backend
    python ../scripts/backtest_selective_brk.py

No cache is written. No production state is changed.
"""

from __future__ import annotations

import asyncio
import os
import sys

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..", "backend")
sys.path.insert(0, BACKEND_DIR)

sys.stdout.reconfigure(encoding="utf-8")

from backtest_engine import BacktestEngine, BacktestParams
from indicators import ema as _ema, sma as _sma, atr as _atr, cci as _cci
from constants import CONCURRENCY_LIMIT

# ── Config ────────────────────────────────────────────────────────────────────
START_DATE = "2020-01-01"
END_DATE   = "2024-12-31"

CACHE_DIR  = os.path.join(BACKEND_DIR, "data", "price_cache")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    """Compute summary stats for a list of trade dicts."""
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy": 0.0,
                "profit_factor": 0.0, "avg_hold": 0.0}

    rr      = [t["rr_achieved"] for t in trades]
    wins    = [r for r in rr if r > 0]
    losses  = [r for r in rr if r <= 0]
    hold    = [t.get("holding_days", 0) for t in trades]

    win_rate     = len(wins) / len(rr) * 100
    avg_r        = float(np.mean(rr))
    avg_win      = float(np.mean(wins))  if wins   else 0.0
    avg_loss     = float(np.mean(losses)) if losses else 0.0
    loss_rate    = 1.0 - win_rate / 100
    expectancy   = (win_rate / 100) * avg_win + loss_rate * avg_loss
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    avg_hold     = float(np.mean(hold))

    return {
        "n":            len(trades),
        "win_rate":     win_rate,
        "avg_r":        avg_r,
        "expectancy":   expectancy,
        "profit_factor": profit_factor,
        "avg_hold":     avg_hold,
    }


def _print_table(sections: dict) -> None:
    """Print comparison table."""
    labels = list(sections.keys())
    metrics = [
        ("Trade count",   "n",             "{:.0f}"),
        ("Win rate",      "win_rate",      "{:.1f}%"),
        ("Avg R",         "avg_r",         "{:.3f}R"),
        ("Expectancy",    "expectancy",    "{:.3f}R"),
        ("Profit factor", "profit_factor", "{:.2f}"),
        ("Avg hold days", "avg_hold",      "{:.1f}"),
    ]

    col_w = 26
    header = f"{'Metric':<22}" + "".join(f"{l:<{col_w}}" for l in labels)
    print("\n" + "=" * (22 + col_w * len(labels)))
    print(header)
    print("-" * (22 + col_w * len(labels)))
    for name, key, fmt in metrics:
        row = f"{name:<22}"
        for label in labels:
            val = sections[label][key]
            if val == float("inf"):
                row += f"{'inf':<{col_w}}"
            else:
                row += f"{fmt.format(val):<{col_w}}"
        print(row)
    print("=" * (22 + col_w * len(labels)))


# ── Parquet cache loader ──────────────────────────────────────────────────────

def _load_all_cached(cache_dir: str):
    """
    Load all parquet files from cache_dir into a dict of DataFrames.
    Pre-computes indicator columns once per ticker (same pattern as wfo_engine.py).
    Returns (loaded_dfs, spy_df).
    """
    from pathlib import Path

    loaded_dfs: dict = {}
    spy_df = None

    parquet_files = sorted(Path(cache_dir).glob("*.parquet"))
    print(f"Found {len(parquet_files)} parquet files in {cache_dir}")

    for fpath in parquet_files:
        ticker = fpath.stem.upper()
        try:
            df = pd.read_parquet(fpath)
        except Exception as exc:
            print(f"  WARN: could not read {fpath.name}: {exc}")
            continue
        if ticker == "SPY":
            spy_df = df
        loaded_dfs[ticker] = df

    if spy_df is None:
        raise RuntimeError(f"SPY.parquet not found in {cache_dir}. Cannot run backtest.")

    print(f"Loaded {len(loaded_dfs)} tickers (including SPY)")

    # Pre-compute indicator columns (avoids recomputation per window)
    for ticker, df in loaded_dfs.items():
        if ticker == "SPY" or "_EMA8" in df.columns:
            continue
        _adj = "Adj Close" if "Adj Close" in df.columns else "Close"
        _c = df[_adj]
        _h = df["High"]
        _l = df["Low"]
        df["_EMA8"]    = _ema(_c, 8)
        df["_EMA20"]   = _ema(_c, 20)
        df["_SMA50"]   = _sma(_c, 50)
        df["_SMA200"]  = _sma(_c, 200)
        df["_ATR14"]   = _atr(_h, _l, _c, 14)
        df["_CCI20"]   = _cci(_h, _l, _c, 20)
        if "Volume" in df.columns:
            df["_VOLSMA50"] = df["Volume"].rolling(50, min_periods=10).mean()

    return loaded_dfs, spy_df


# ── Main ─────────────────────────────────────────────────────────────────────

async def _run_all(loaded_dfs: dict, spy_df) -> list:
    """Fan out BacktestEngine over all cached tickers."""
    sem       = asyncio.Semaphore(CONCURRENCY_LIMIT)
    all_trades = []
    lock      = asyncio.Lock()
    done      = [0]
    total     = len(loaded_dfs)
    # Legacy mode (params=None): uses constants.py values — same as live scanner.
    # This matches the 668-trade baseline and gives a meaningful signal count.

    async def _run_one(ticker: str, ticker_df) -> list:
        async with sem:
            try:
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    params=None,
                    ticker_df=ticker_df,
                    spy_df=spy_df,
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                return []
            finally:
                async with lock:
                    done[0] += 1
                    if done[0] % 50 == 0 or done[0] == total:
                        print(f"  Progress: {done[0]}/{total} tickers")

    results = await asyncio.gather(*[
        _run_one(ticker, df)
        for ticker, df in loaded_dfs.items()
        if ticker != "SPY"
    ])
    for batch in results:
        all_trades.extend(batch)

    return all_trades


def main():
    print(f"\nSELECTIVE RES_BREAKOUT Diagnostic")
    print(f"Period: {START_DATE} -> {END_DATE}")
    print(f"Cache:  {CACHE_DIR}")
    print(f"Mode: legacy (params=None) — uses constants.py, same as live scanner")
    print()

    loaded_dfs, spy_df = _load_all_cached(CACHE_DIR)

    print(f"\nRunning backtest {START_DATE} -> {END_DATE} ...")
    all_trades = asyncio.run(_run_all(loaded_dfs, spy_df))
    print(f"\nTotal trades: {len(all_trades)}")

    # ── Slice into comparison groups ──────────────────────────────────────────
    agg_brk  = [t for t in all_trades if t["setup_type"] == "RES_BREAKOUT" and t.get("regime") == "AGGRESSIVE"]
    sel_brk  = [t for t in all_trades if t["setup_type"] == "RES_BREAKOUT" and t.get("regime") == "SELECTIVE"]
    sel_pb   = [t for t in all_trades if t["setup_type"] == "PULLBACK"     and t.get("regime") == "SELECTIVE"]

    sections = {
        "AGGRESSIVE RES_BRK": _stats(agg_brk),
        "SELECTIVE RES_BRK":  _stats(sel_brk),
        "SELECTIVE PULLBACK":  _stats(sel_pb),
    }

    _print_table(sections)

    # Sanity check: SELECTIVE PULLBACK should be near +0.039R from prior run
    pb_exp = sections["SELECTIVE PULLBACK"]["expectancy"]
    print(f"\nSanity check - SELECTIVE PULLBACK expectancy: {pb_exp:.3f}R")
    print("  Expected: ~+0.039R (from 2020-2024 backtest). If far off, re-check cache.")


if __name__ == "__main__":
    main()
