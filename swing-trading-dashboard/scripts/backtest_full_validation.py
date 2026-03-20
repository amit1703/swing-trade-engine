"""
backtest_full_validation.py — Full System Validation (2020-2024)
================================================================
Runs the complete strategy across all market regimes and setup types.
Outputs regime segmentation, setup breakdown, entry quality analysis,
and capital curve vs SPY.

Usage:
    cd backend
    python ../scripts/backtest_full_validation.py               # default: exclude EXTENDED
    python ../scripts/backtest_full_validation.py --show-extended

Requirements:
    - Parquet cache at backend/data/price_cache/
    - SPY.parquet must be present in the cache
    - Run from backend/ directory (or cache path will fail)
"""

from __future__ import annotations

import argparse
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

from backtest_engine import BacktestEngine
from indicators import ema as _ema, sma as _sma, atr as _atr, cci as _cci
from constants import CONCURRENCY_LIMIT, ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD

# ── Config ────────────────────────────────────────────────────────────────────
START_DATE  = "2020-01-01"
END_DATE    = "2024-12-31"
CACHE_DIR   = os.path.join(BACKEND_DIR, "data", "price_cache")
ALL_REGIMES = ("AGGRESSIVE", "SELECTIVE", "DEFENSIVE", "UNKNOWN")
SETUP_ORDER = ("VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE")


# ── Entry quality classification ──────────────────────────────────────────────

def _entry_quality(trade: dict) -> str:
    meta      = trade.get("setup_meta", {})
    atr       = meta.get("atr", 0)
    sig_entry = meta.get("entry", None)
    fill      = trade.get("entry_price")
    if not atr or atr <= 0 or sig_entry is None or fill is None:
        return "UNKNOWN"
    dist = (fill - sig_entry) / atr
    if dist < ATR_ENTRY_EARLY_THRESHOLD:
        return "EARLY"
    elif dist < ATR_ENTRY_EXTENDED_THRESHOLD:
        return "OPTIMAL"
    else:
        return "EXTENDED"


# ── Stats ─────────────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy": 0.0,
                "profit_factor": 0.0, "max_dd": 0.0, "avg_hold": 0.0}
    # Sort by exit_date for deterministic, chronologically-correct drawdown
    sorted_t = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    rr   = [t["rr_achieved"] for t in sorted_t]
    wins = [r for r in rr if r > 0]
    loss = [r for r in rr if r <= 0]
    pnl  = [t.get("portfolio_pnl_pct", 0.0) for t in sorted_t]
    hold = [t.get("holding_days", 0) for t in sorted_t]

    win_rate   = len(wins) / len(rr) * 100
    avg_r      = float(np.mean(rr))
    avg_win    = float(np.mean(wins)) if wins else 0.0
    avg_loss   = float(np.mean(loss)) if loss else 0.0
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss

    gp = sum(p for p in pnl if p > 0)
    gl = abs(sum(p for p in pnl if p < 0))
    pf = (gp / gl) if gl > 0 else float("inf")

    eq, peak, max_dd = 1.0, 1.0, 0.0
    for p in pnl:
        eq *= (1 + p / 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "n":             len(trades),
        "win_rate":      win_rate,
        "avg_r":         avg_r,
        "expectancy":    expectancy,
        "profit_factor": pf,
        "max_dd":        max_dd,
        "avg_hold":      float(np.mean(hold)),
    }


# ── Capital curve ─────────────────────────────────────────────────────────────

def _capital_curve(trades: list, start_year: int = 2020, end_year: int = 2024) -> dict:
    """Year-end equity starting at 1.0. Sorted by exit_date (P&L realized at exit)."""
    if not trades:
        return {y: 1.0 for y in range(start_year, end_year + 1)}
    sorted_trades = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    equity, idx, n = 1.0, 0, len(sorted_trades)
    result = {}
    for year in range(start_year, end_year + 1):
        cutoff = f"{year}-12-31"
        while idx < n and sorted_trades[idx].get("exit_date", sorted_trades[idx].get("entry_date", "")) <= cutoff:
            equity *= (1 + sorted_trades[idx].get("portfolio_pnl_pct", 0.0) / 100)
            idx += 1
        result[year] = round(equity, 4)
    return result


def _spy_curve(spy_df: pd.DataFrame, start_year: int = 2020, end_year: int = 2024) -> dict:
    """Year-end SPY buy-and-hold equity starting at 1.0."""
    adj = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    spy = spy_df[adj].copy()
    spy = spy[(spy.index >= f"{start_year}-01-01") & (spy.index <= f"{end_year}-12-31")]
    if spy.empty:
        return {y: 1.0 for y in range(start_year, end_year + 1)}
    base = float(spy.iloc[0])
    result = {}
    for year in range(start_year, end_year + 1):
        end_slice = spy[spy.index <= f"{year}-12-31"]
        if end_slice.empty:
            result[year] = result.get(year - 1, 1.0)
        else:
            result[year] = round(float(end_slice.iloc[-1]) / base, 4)
    return result


def _cagr(start_equity: float, end_equity: float, years: int) -> float:
    if start_equity <= 0 or years <= 0:
        return 0.0
    return round(((end_equity / start_equity) ** (1 / years) - 1) * 100, 2)


# ── Printing helpers ──────────────────────────────────────────────────────────

def _double_hr(width: int = 78) -> None:
    print("═" * width)


def _print_summary_table(label: str, sections: dict) -> None:
    keys = list(sections.keys())
    col_w = 22
    metrics = [
        ("Trade count",    "n",             "{:.0f}"),
        ("Win rate",       "win_rate",      "{:.1f}%"),
        ("Avg R",          "avg_r",         "{:.3f}R"),
        ("Expectancy",     "expectancy",    "{:.3f}R"),
        ("Profit factor",  "profit_factor", "{:.2f}"),
        ("Max drawdown",   "max_dd",        "{:.1f}%"),
        ("Avg hold days",  "avg_hold",      "{:.1f}d"),
    ]
    width = 20 + col_w * len(keys)
    print(f"\n{label}")
    print("─" * width)
    header = f"{'Metric':<20}" + "".join(f"{k:<{col_w}}" for k in keys)
    print(header)
    print("─" * width)
    for name, key, fmt in metrics:
        row = f"{name:<20}"
        for k in keys:
            val = sections[k].get(key, 0)
            if val == float("inf"):
                row += f"{'inf':<{col_w}}"
            else:
                row += f"{fmt.format(val):<{col_w}}"
        print(row)
    print("─" * width)


def _print_regime_breakdown(trades: list) -> None:
    if not trades:
        print("  (no trades)")
        return
    col_widths = [12, 6, 7, 9, 9, 7, 8, 7]
    headers    = ["Setup", "N", "Win%", "AvgR", "Exp", "PF", "MaxDD%", "Hold"]
    header_row = "".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
    sep = "─" * sum(col_widths)
    print(f"  {header_row}")
    print(f"  {sep}")

    all_setups = list(SETUP_ORDER) + [
        s for s in {t["setup_type"] for t in trades} if s not in SETUP_ORDER
    ]
    for stype in all_setups:
        subset = [t for t in trades if t["setup_type"] == stype]
        if not subset:
            continue
        s = _stats(subset)
        pf_str = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        row = (
            f"{stype:<12}"
            f"{s['n']:<6}"
            f"{s['win_rate']:.1f}%  "
            f"{s['avg_r']:+.3f}   "
            f"{s['expectancy']:+.3f}   "
            f"{pf_str:<7}"
            f"{s['max_dd']:.1f}%    "
            f"{s['avg_hold']:.1f}d"
        )
        print(f"  {row}")

    tot = _stats(trades)
    pf_str = "inf" if tot["profit_factor"] == float("inf") else f"{tot['profit_factor']:.2f}"
    print(f"  {sep}")
    total_row = (
        f"{'TOTAL':<12}"
        f"{tot['n']:<6}"
        f"{tot['win_rate']:.1f}%  "
        f"{tot['avg_r']:+.3f}   "
        f"{tot['expectancy']:+.3f}   "
        f"{pf_str:<7}"
        f"{tot['max_dd']:.1f}%    "
        f"{tot['avg_hold']:.1f}d"
    )
    print(f"  {total_row}")


# ── Parquet loader ────────────────────────────────────────────────────────────

def _load_all_cached(cache_dir: str):
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
            print(f"  WARN: {fpath.name}: {exc}")
            continue
        if ticker == "SPY":
            spy_df = df
        loaded_dfs[ticker] = df
    if spy_df is None:
        raise RuntimeError(f"SPY.parquet not found in {cache_dir}.")
    print(f"Loaded {len(loaded_dfs)} tickers (including SPY)")
    for ticker, df in loaded_dfs.items():
        if ticker == "SPY" or "_EMA8" in df.columns:
            continue
        _adj = "Adj Close" if "Adj Close" in df.columns else "Close"
        _c, _h, _l = df[_adj], df["High"], df["Low"]
        df["_EMA8"]    = _ema(_c, 8)
        df["_EMA20"]   = _ema(_c, 20)
        df["_SMA50"]   = _sma(_c, 50)
        df["_SMA200"]  = _sma(_c, 200)
        df["_ATR14"]   = _atr(_h, _l, _c, 14)
        df["_CCI20"]   = _cci(_h, _l, _c, 20)
        if "Volume" in df.columns:
            df["_VOLSMA50"] = df["Volume"].rolling(50, min_periods=10).mean()
    return loaded_dfs, spy_df


# ── Backtest runner ───────────────────────────────────────────────────────────

async def _run_all(loaded_dfs: dict, spy_df) -> list:
    sem        = asyncio.Semaphore(CONCURRENCY_LIMIT)
    all_trades = []
    lock       = asyncio.Lock()
    done       = [0]
    total      = sum(1 for t in loaded_dfs if t != "SPY")

    async def _run_one(ticker: str, ticker_df) -> list:
        async with sem:
            try:
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    params=None,        # LEGACY MODE — same as live scanner
                    ticker_df=ticker_df,
                    spy_df=spy_df,
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                print(f"  WARN {ticker}: {exc}", flush=True)
                return []
            finally:
                async with lock:
                    done[0] += 1
                    if done[0] % 100 == 0 or done[0] == total:
                        print(f"  Progress: {done[0]}/{total} tickers", flush=True)

    results = await asyncio.gather(*[
        _run_one(ticker, df)
        for ticker, df in loaded_dfs.items()
        if ticker != "SPY"
    ])
    for batch in results:
        all_trades.extend(batch)
    return all_trades


# ── Report ────────────────────────────────────────────────────────────────────

def _print_report(all_trades: list, spy_df, show_extended: bool) -> None:
    n_years = int(END_DATE[:4]) - int(START_DATE[:4]) + 1

    for t in all_trades:
        t["_quality"] = _entry_quality(t)

    if show_extended:
        filt = all_trades
        filter_label = "ALL (including EXTENDED)"
    else:
        filt = [t for t in all_trades if t["_quality"] != "EXTENDED"]
        filter_label = "EARLY + OPTIMAL (EXTENDED excluded)"

    _double_hr()
    print(f"  FULL SYSTEM VALIDATION — {START_DATE[:4]}–{END_DATE[:4]}")
    print(f"  Mode:     Legacy (params=None) — identical to live scanner")
    print(f"  Filter:   {filter_label}")
    print(f"  Universe: {len({t['ticker'] for t in all_trades})} tickers")
    _double_hr()

    # ── [1] Entry quality breakdown ───────────────────────────────────────────
    print("\n[1] ENTRY QUALITY BREAKDOWN (all trades before filtering)")
    for q in ("EARLY", "OPTIMAL", "EXTENDED", "UNKNOWN"):
        subset = [t for t in all_trades if t["_quality"] == q]
        if not subset:
            continue
        s = _stats(subset)
        pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        print(f"  {q:<10} n={s['n']:>5}  win={s['win_rate']:.1f}%  "
              f"exp={s['expectancy']:+.3f}R  pf={pf}  dd={s['max_dd']:.1f}%")

    # ── [2] Combined summary ──────────────────────────────────────────────────
    early  = [t for t in all_trades if t["_quality"] == "EARLY"]
    optim  = [t for t in all_trades if t["_quality"] == "OPTIMAL"]
    sections = {
        f"ALL ({len(all_trades)})":          _stats(all_trades),
        f"EARLY+OPT ({len(filt)})":          _stats(filt),
        f"EARLY ({len(early)})":             _stats(early),
        f"OPTIMAL ({len(optim)})":           _stats(optim),
    }
    _print_summary_table("\n[2] COMBINED SUMMARY", sections)

    # ── [3] By regime ─────────────────────────────────────────────────────────
    print("\n[3] REGIME BREAKDOWN (filtered trades)")
    _double_hr()
    for regime in ALL_REGIMES:
        regime_trades = [t for t in filt if t.get("regime") == regime]
        if not regime_trades and regime == "DEFENSIVE":
            print(f"\n  ── DEFENSIVE — 0 trades (all blocked by regime gate, as expected)")
            continue
        if not regime_trades:
            continue
        pct = len(regime_trades) / len(filt) * 100 if filt else 0
        print(f"\n  ── {regime}  ({len(regime_trades)} trades, {pct:.1f}% of filtered)")
        _print_regime_breakdown(regime_trades)

    # ── [4] Capital curve ─────────────────────────────────────────────────────
    print("\n[4] CAPITAL CURVE SIMULATION")
    _double_hr()
    sys_curve = _capital_curve(filt)
    spy_curve = _spy_curve(spy_df)
    print(f"\n  {'Year':<8} {'System':>10} {'SPY':>10} {'vs SPY':>10} {'YoY Sys':>10}")
    print(f"  {'────':<8} {'──────':>10} {'───':>10} {'──────':>10} {'───────':>10}")
    prev_sys = 1.0
    for year in range(int(START_DATE[:4]), int(END_DATE[:4]) + 1):
        sys_eq = sys_curve.get(year, 1.0)
        spy_eq = spy_curve.get(year, 1.0)
        vs_spy = sys_eq - spy_eq
        yoy    = (sys_eq / prev_sys - 1) * 100 if prev_sys > 0 else 0.0
        prev_sys = sys_eq
        print(f"  {year:<8} {sys_eq:>9.3f}x {spy_eq:>9.3f}x {vs_spy:>+9.3f}x {yoy:>+9.1f}%")

    sys_final = sys_curve.get(int(END_DATE[:4]), 1.0)
    spy_final = spy_curve.get(int(END_DATE[:4]), 1.0)
    s_all     = _stats(filt)
    print(f"\n  System CAGR:    {_cagr(1.0, sys_final, n_years):+.1f}%")
    print(f"  SPY CAGR:       {_cagr(1.0, spy_final, n_years):+.1f}%")
    print(f"  Alpha (CAGR):   {_cagr(1.0, sys_final, n_years) - _cagr(1.0, spy_final, n_years):+.1f}%")
    print(f"  System max DD:  -{s_all['max_dd']:.1f}%")

    # ── [5] Key insights ──────────────────────────────────────────────────────
    print("\n[5] KEY INSIGHTS")
    _double_hr()

    combos = []
    for regime in ("AGGRESSIVE", "SELECTIVE"):
        for stype in SETUP_ORDER:
            subset = [t for t in filt if t.get("regime") == regime and t["setup_type"] == stype]
            if len(subset) >= 10:
                s = _stats(subset)
                combos.append((regime, stype, s["n"], s["expectancy"], s["win_rate"]))
    combos.sort(key=lambda x: x[3], reverse=True)

    print("\n  Best expectancy (regime × setup, min 10 trades):")
    for regime, stype, n, exp, wr in combos[:5]:
        print(f"    {regime:<12} {stype:<14} n={n:<5} exp={exp:+.3f}R  win={wr:.1f}%")

    print("\n  Worst expectancy:")
    for regime, stype, n, exp, wr in combos[-3:]:
        print(f"    {regime:<12} {stype:<14} n={n:<5} exp={exp:+.3f}R  win={wr:.1f}%")

    sel_all = [t for t in filt if t.get("regime") == "SELECTIVE"]
    agg_all = [t for t in filt if t.get("regime") == "AGGRESSIVE"]
    sel_s   = _stats(sel_all)
    agg_s   = _stats(agg_all)
    print(f"\n  SELECTIVE contribution:")
    print(f"    Trades: {sel_s['n']}  ({sel_s['n']/len(filt)*100:.1f}% of filtered)" if filt else "    (no trades)")
    print(f"    Expectancy: {sel_s['expectancy']:+.3f}R  vs AGGRESSIVE: {agg_s['expectancy']:+.3f}R")

    sel_brk = [t for t in sel_all if t["setup_type"] == "RES_BREAKOUT"]
    sel_pb  = [t for t in sel_all if t["setup_type"] == "PULLBACK"]
    if sel_brk:
        b = _stats(sel_brk)
        print(f"    SELECTIVE RES_BREAKOUT: n={b['n']}  exp={b['expectancy']:+.3f}R  win={b['win_rate']:.1f}%")
    if sel_pb:
        p = _stats(sel_pb)
        print(f"    SELECTIVE PULLBACK:     n={p['n']}  exp={p['expectancy']:+.3f}R  win={p['win_rate']:.1f}%")

    _double_hr()
    print(f"\n  Run complete. Raw: {len(all_trades)} trades | Filtered: {len(filt)} trades")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Full system backtest validation 2020-2024")
    parser.add_argument("--show-extended", action="store_true",
                        help="Include EXTENDED entries (default: exclude them)")
    args = parser.parse_args()

    print(f"\nFull System Backtest Validation")
    print(f"Period:   {START_DATE} → {END_DATE}")
    print(f"Cache:    {CACHE_DIR}")
    print(f"Mode:     legacy (params=None) — matches live scanner")
    print(f"Filter:   {'--show-extended active' if args.show_extended else 'EARLY+OPTIMAL only (pass --show-extended to include EXTENDED)'}")
    print()

    loaded_dfs, spy_df = _load_all_cached(CACHE_DIR)
    print(f"\nRunning backtest {START_DATE} → {END_DATE}...")
    all_trades = asyncio.run(_run_all(loaded_dfs, spy_df))
    print(f"Total raw trades: {len(all_trades)}\n")
    _print_report(all_trades, spy_df, show_extended=args.show_extended)


if __name__ == "__main__":
    main()
