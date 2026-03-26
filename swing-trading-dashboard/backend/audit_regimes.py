"""
audit_regimes.py — Regime distribution audit, Jan 1 2017 – Dec 31 2024.

Fetches SPY daily OHLCV from Jan 2015 (extra warmup for SMA200) through
Dec 2024, runs compute_regime_score_series() (the exact same function the
live scanner and backtest use), then slices to the 2017-2024 window and
prints a breakdown of days in each regime tier.

Usage:
    cd swing-trading-dashboard/backend
    python audit_regimes.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import yfinance as yf
import pandas as pd

from engines.engine0 import compute_regime_score_series, _score_to_regime
from constants import REGIME_AGGRESSIVE_THRESHOLD, REGIME_SELECTIVE_THRESHOLD

AUDIT_START = "2017-01-01"
AUDIT_END   = "2024-12-31"
FETCH_START = "2015-01-01"   # ~500 extra bars for SMA200 warmup


def main():
    print("Fetching SPY daily OHLCV …")
    spy = yf.download(
        "SPY",
        start=FETCH_START,
        end="2025-01-02",   # inclusive of 2024-12-31
        interval="1d",
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=False,
    )

    if spy is None or spy.empty:
        print("ERROR: No SPY data returned.")
        sys.exit(1)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    print(f"Downloaded {len(spy)} bars  ({spy.index[0].date()} to {spy.index[-1].date()})\n")

    # Compute regime score for the full fetched history
    scores = compute_regime_score_series(spy)

    # Slice to audit window
    mask   = (scores.index >= AUDIT_START) & (scores.index <= AUDIT_END)
    window = scores[mask]

    if window.empty:
        print("ERROR: No bars in the audit window after slicing.")
        sys.exit(1)

    # Label each bar
    labels = window.apply(_score_to_regime)

    total  = len(window)
    counts = labels.value_counts()

    # Ensure all three tiers appear even if count = 0
    for tier in ("AGGRESSIVE", "SELECTIVE", "DEFENSIVE"):
        if tier not in counts:
            counts[tier] = 0

    print("=" * 52)
    print(f"  Market Regime Audit  --  {AUDIT_START} to {AUDIT_END}")
    print("=" * 52)
    print(f"  Total trading days : {total}")
    print(f"  Score thresholds   : AGGRESSIVE >= {REGIME_AGGRESSIVE_THRESHOLD:.2f}  |  "
          f"SELECTIVE >= {REGIME_SELECTIVE_THRESHOLD:.2f}  |  DEFENSIVE < {REGIME_SELECTIVE_THRESHOLD:.2f}")
    print("-" * 52)

    for tier in ("AGGRESSIVE", "SELECTIVE", "DEFENSIVE"):
        n   = counts.get(tier, 0)
        pct = n / total * 100
        bar = "#" * int(pct / 2)
        print(f"  {tier:<12}  {n:>4} days  ({pct:5.1f}%)  {bar}")

    print("-" * 52)

    # Score distribution percentiles
    pctiles = window.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    print("\n  Score distribution (0.0-1.0 scale):")
    for q, v in pctiles.items():
        print(f"    p{int(q*100):>2}  =  {v:.3f}")

    # Year-by-year breakdown
    print("\n  Year-by-year regime split:")
    print(f"  {'Year':<6}  {'AGG':>5}  {'SEL':>5}  {'DEF':>5}  {'Total':>6}")
    print(f"  {'-'*4}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}")
    for yr in range(2017, 2025):
        yr_mask   = labels.index.year == yr
        yr_labels = labels[yr_mask]
        yr_n      = len(yr_labels)
        if yr_n == 0:
            continue
        agg = (yr_labels == "AGGRESSIVE").sum()
        sel = (yr_labels == "SELECTIVE").sum()
        dfn = (yr_labels == "DEFENSIVE").sum()
        print(
            f"  {yr:<6}  "
            f"{agg/yr_n*100:4.0f}%  "
            f"{sel/yr_n*100:4.0f}%  "
            f"{dfn/yr_n*100:4.0f}%  "
            f"{yr_n:>6}"
        )

    print("=" * 52)


if __name__ == "__main__":
    main()
