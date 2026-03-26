"""
audit_setup_scores.py -- Setup score distribution audit over 2023.

Runs the portfolio backtest engine over a 120-ticker random sample with:
  - min_score = 0.0  (bypass the 70-point gate -- score everything detected)
  - max_positions = 999  (no cap -- every signal that passes regime+liquidity
    gates becomes a trade record with its pre-gate final_score stored)

Uses the EXACT same compute_setup_score() + regime pipeline as the live
scanner. Results answer: "Is min_score=70 starving us of trades?"

Usage:
    cd swing-trading-dashboard/backend
    python audit_setup_scores.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
import random
from collections import defaultdict

from tickers import SCAN_UNIVERSE
from portfolio_backtest import run_portfolio_backtest_universe, BacktestConfig
from constants import MIN_SETUP_SCORE

AUDIT_START = "2023-01-01"
AUDIT_END   = "2023-12-31"
SAMPLE_SIZE = 120
SEED        = 42

ALL_SETUP_TYPES = ["PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE", "VCP"]

BUCKETS = [
    ("<40",    0,   40),
    ("40-49", 40,   50),
    ("50-59", 50,   60),
    ("60-69", 60,   70),
    ("70-79", 70,   80),
    ("80-89", 80,   90),
    ("90-100",90,  101),
]


def main():
    random.seed(SEED)
    sample = random.sample(SCAN_UNIVERSE, SAMPLE_SIZE)

    print(f"Sampled {SAMPLE_SIZE} tickers from universe of {len(SCAN_UNIVERSE)}")
    print(f"Audit period : {AUDIT_START} to {AUDIT_END}")
    print(f"Setup types  : {', '.join(ALL_SETUP_TYPES)}")
    print(f"min_score=0 (gate bypassed), max_positions=999 (no cap)")
    print("Downloading data and running backtest ...")
    print()

    config = BacktestConfig(
        start_date    = AUDIT_START,
        end_date      = AUDIT_END,
        max_positions = 999,
        min_score     = 0.0,
        setup_types   = ALL_SETUP_TYPES,
    )

    trades = asyncio.run(run_portfolio_backtest_universe(sample, config))

    scores = [t["final_score"] for t in trades if t.get("final_score") is not None]

    if not scores:
        print("ERROR: No scored signals found. Verify backtest ran correctly.")
        return

    scores_sorted = sorted(scores)
    total  = len(scores)
    median = scores_sorted[total // 2]

    print("=" * 62)
    print(f"  Setup Score Distribution  --  2023  ({SAMPLE_SIZE} tickers)")
    print("=" * 62)
    print(f"  Total scored signals : {total}")
    print(f"  Min  : {min(scores):.1f}   Median : {median:.1f}   Max : {max(scores):.1f}")
    print(f"  Gate : min_score = {MIN_SETUP_SCORE}")
    print("-" * 62)
    print(f"  {'Bucket':<10}  {'Count':>6}  {'% of All':>9}  {'Cumul%':>8}  Bar")
    print(f"  {'-'*9}  {'-'*6}  {'-'*9}  {'-'*8}  {'-'*20}")

    cumul = 0.0
    for label, lo, hi in BUCKETS:
        n   = sum(1 for s in scores if lo <= s < hi)
        pct = n / total * 100
        cumul += pct
        bar = "#" * int(pct / 2)
        gate_marker = "  << GATE" if hi == 70 else ""
        print(f"  {label:<10}  {n:>6}  {pct:>8.1f}%  {cumul:>7.1f}%  {bar}{gate_marker}")

    print("-" * 62)
    below = sum(1 for s in scores if s < MIN_SETUP_SCORE)
    above = total - below
    print(f"\n  FILTERED OUT by min_score={MIN_SETUP_SCORE} : {below:>4}  ({below/total*100:.1f}%)")
    print(f"  PASSED  the {MIN_SETUP_SCORE} gate           : {above:>4}  ({above/total*100:.1f}%)")

    # ── Per-setup-type breakdown ───────────────────────────────────────────────
    by_type = defaultdict(list)
    for t in trades:
        fs = t.get("final_score")
        if fs is not None:
            by_type[t["setup_type"]].append(fs)

    print()
    print("  Per-setup-type breakdown:")
    print(f"  {'Type':<14}  {'Count':>5}  {'Avg':>5}  {'Median':>7}  {'Pass%':>7}")
    print(f"  {'-'*13}  {'-'*5}  {'-'*5}  {'-'*7}  {'-'*7}")
    for stype in ALL_SETUP_TYPES:
        slist = sorted(by_type.get(stype, []))
        if not slist:
            print(f"  {stype:<14}  {'0':>5}  {'n/a':>5}  {'n/a':>7}  {'n/a':>7}")
            continue
        avg       = sum(slist) / len(slist)
        med       = slist[len(slist) // 2]
        pass_rate = sum(1 for s in slist if s >= MIN_SETUP_SCORE) / len(slist) * 100
        print(f"  {stype:<14}  {len(slist):>5}  {avg:>5.1f}  {med:>7.1f}  {pass_rate:>6.1f}%")

    # ── Per-regime breakdown ───────────────────────────────────────────────────
    by_regime = defaultdict(list)
    for t in trades:
        fs = t.get("final_score")
        if fs is not None:
            by_regime[t.get("regime", "UNKNOWN")].append(fs)

    print()
    print("  Per-regime breakdown:")
    print(f"  {'Regime':<14}  {'Count':>5}  {'Avg':>5}  {'Pass%':>7}")
    print(f"  {'-'*13}  {'-'*5}  {'-'*5}  {'-'*7}")
    for regime in ("AGGRESSIVE", "SELECTIVE", "DEFENSIVE", "UNKNOWN"):
        slist = by_regime.get(regime, [])
        if not slist:
            continue
        avg       = sum(slist) / len(slist)
        pass_rate = sum(1 for s in slist if s >= MIN_SETUP_SCORE) / len(slist) * 100
        print(f"  {regime:<14}  {len(slist):>5}  {avg:>5.1f}  {pass_rate:>6.1f}%")

    print("=" * 62)


if __name__ == "__main__":
    main()
