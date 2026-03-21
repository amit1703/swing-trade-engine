"""
Quick standalone backtest for the 26 representative tickers.
Runs in minutes using the local WFO parquet price cache.
No server required.

Usage (run from backend/ directory):
    python ../scripts/run_backtest_quick.py
    python ../scripts/run_backtest_quick.py --start 2020-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_SCRIPTS))

import constants as _c
from backtest_engine import run_backtest_universe
from representative_tickers_v2 import REPRESENTATIVE_TICKERS_V2

SETUP_TYPES = ["PULLBACK", "BASE", "RES_BREAKOUT", "HTF"]


def _summary(trades: list[dict], label: str) -> None:
    if not trades:
        print(f"  {label}: 0 trades")
        return

    wins = [t for t in trades if t.get("exit_reason") not in ("STOP",) and t.get("profit_r", 0) > 0]
    # use profit_r if available, else compute from prices
    rs = []
    for t in trades:
        r = t.get("profit_r")
        if r is None:
            ep = t.get("entry_price") or t.get("entry")
            sl = t.get("initial_stop") or t.get("stop_loss")
            xp = t.get("exit_price") or t.get("close_price")
            if ep and sl and xp and ep != sl:
                r = (xp - ep) / (ep - sl)
        if r is not None:
            rs.append(r)

    if not rs:
        print(f"  {label}: {len(trades)} trades (no R data)")
        return

    wins_r = [r for r in rs if r > 0]
    losses_r = [abs(r) for r in rs if r <= 0]
    win_rate = len(wins_r) / len(rs) * 100
    expectancy = sum(rs) / len(rs)
    gross_profit = sum(wins_r)
    gross_loss = sum(losses_r)
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # drawdown from cumulative R
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    print(
        f"  {label}: n={len(rs)}  win={win_rate:.1f}%  "
        f"exp={expectancy:+.3f}R  PF={pf:.2f}  DD={max_dd:.1f}R"
    )


def _breakdown(trades: list[dict]) -> None:
    by_type: dict[str, list] = defaultdict(list)
    for t in trades:
        by_type[t.get("setup_type", "UNKNOWN")].append(t)

    for stype, group in sorted(by_type.items()):
        _summary(group, stype)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end",   default="2024-12-31")
    ap.add_argument("--trail-mode", default="ema20", choices=["ema20", "atr"],
                    help="Trail stop mode: ema20 (EMA20-based) or atr (fixed ATR multiplier)")
    args = ap.parse_args()

    # Patch the module-level constant so params=None (legacy/unscored) mode picks it up.
    # BacktestEngine reads _constants.TRAIL_MODE when params is None.
    _c.TRAIL_MODE = args.trail_mode

    tickers = REPRESENTATIVE_TICKERS_V2
    print(f"\nBacktest: {args.start} to {args.end}")
    print(f"Tickers:  {len(tickers)} representative")
    print(f"Setups:   {SETUP_TYPES}")
    print(f"Trail:    {args.trail_mode}")
    print()

    trades = asyncio.run(
        run_backtest_universe(
            tickers=tickers,
            start_date=args.start,
            end_date=args.end,
            trail_mult_override=None,   # use per-setup constants from constants.py
            params=None,                # unscored mode — all engines, no RS gate
            setup_types=SETUP_TYPES,
        )
    )

    print("=" * 60)
    print(f"TOTAL")
    _summary(trades, "All setups")
    print()
    print("BY SETUP TYPE")
    _breakdown(trades)
    print()

    # exit reasons
    n = len(trades)
    exit_counts = Counter(t.get("exit_reason", "?") for t in trades)
    if n:
        print(
            f"  Exit reasons: "
            f"STOP={exit_counts.get('STOP', 0)} ({exit_counts.get('STOP', 0) / n * 100:.0f}%)  "
            f"TARGET={exit_counts.get('TARGET', 0)} ({exit_counts.get('TARGET', 0) / n * 100:.0f}%)  "
            f"EOD={exit_counts.get('EOD', 0)} ({exit_counts.get('EOD', 0) / n * 100:.0f}%)"
        )

    # Trail phase breakdown (EMA20 mode only)
    if args.trail_mode == "ema20" and n:
        phase_counts = Counter(t.get("trail_phase", "?") for t in trades)
        triggered = phase_counts.get("ema20", 0)
        initial   = phase_counts.get("initial", 0)
        print(
            f"  Trail phase: ema20={triggered} ({triggered / n * 100:.0f}%)  "
            f"initial={initial} ({initial / n * 100:.0f}%)"
        )
    print()

    # regime breakdown
    by_regime: dict[str, list] = defaultdict(list)
    for t in trades:
        regime = t.get("regime", "UNKNOWN")
        by_regime[regime].append(t)
    if any(k != "UNKNOWN" for k in by_regime):
        print("BY REGIME")
        for regime, group in sorted(by_regime.items()):
            _summary(group, regime)


if __name__ == "__main__":
    main()
