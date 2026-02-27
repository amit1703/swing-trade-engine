#!/usr/bin/env python
"""
Sniper Debug Mode
=================
Single-ticker engine trace. Fetches live data and runs all scanner engines
with verbose rejection reasons printed at each gate.

Usage:
    cd backend
    python debug_ticker.py NVDA
    python debug_ticker.py AAPL
"""

import os
import sys

# Ensure backend/ is on the path regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
import pandas as pd

from constants import DATA_FETCH_PERIOD, DAYS_3_MONTHS, VITALITY_LOOKBACK_DAYS, VITALITY_MIN_RANGE_PCT
from validation import is_price_vital
from engines.engine1 import calculate_sr_zones
from engines.engine2 import scan_vcp, detect_trendline
from engines.engine3 import scan_pullback, scan_relaxed_pullback
from engines.engine4 import calculate_rs_score, detect_rs_blue_dot, calculate_rs_line
from engines.engine5 import scan_base_pattern
from engines.engine6 import scan_resistance_breakout

_DIV = "─" * 62


def _fetch(ticker: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(
        period=DATA_FETCH_PERIOD,
        interval="1d",
        auto_adjust=False,
    )
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    return df


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python debug_ticker.py <TICKER>")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    passes = 0
    total  = 0

    print(f"\n{'═' * 62}")
    print(f"  SNIPER DEBUG: {ticker}")
    print(f"{'═' * 62}\n")

    # ── Fetch ticker ──────────────────────────────────────────────
    print("Fetching ticker data from yfinance...")
    df = _fetch(ticker)
    if df is None or df.empty:
        print(f"✗ ERROR: No data for {ticker}. Check the symbol and try again.")
        sys.exit(1)
    print(f"  ✓ {len(df)} trading days\n")

    # ── Fetch SPY for RS ──────────────────────────────────────────
    spy_df        = None
    spy_3m_return = 0.0
    try:
        spy_df = _fetch("SPY")
        if spy_df is not None:
            adj = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
            if len(spy_df) >= DAYS_3_MONTHS:
                spy_3m_return = float(
                    spy_df[adj].iloc[-1] / spy_df[adj].iloc[-DAYS_3_MONTHS] - 1
                )
    except Exception as exc:
        print(f"  ⚠ SPY fetch failed ({exc}) — RS calculations will be zero\n")

    # ── VITALITY ──────────────────────────────────────────────────
    print(_DIV)
    print("  VITALITY FILTER")
    print(_DIV)
    total += 1
    vital = is_price_vital(df, debug=True)
    if vital:
        print(f"✓ PASS — Stock is actively traded ({VITALITY_LOOKBACK_DAYS}-day range ≥ {VITALITY_MIN_RANGE_PCT:.0%})")
        passes += 1
    if not vital:
        print("\n⚠ Failed vitality — engine results below may be unreliable.\n")

    # ── ENGINE 1: S/R zones ───────────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 1 — KDE S/R ZONES")
    print(_DIV)
    zones = []
    try:
        zones = calculate_sr_zones(ticker, df)
        r = [z for z in zones if z.get("type") == "RESISTANCE"]
        s = [z for z in zones if z.get("type") == "SUPPORT"]
        print(f"  {len(zones)} zones computed — {len(r)} resistance, {len(s)} support")
        for z in zones:
            print(f"    {z['type']:12s}  {z['level']:.2f}  [{z['lower']:.2f} – {z['upper']:.2f}]")
    except Exception as exc:
        print(f"  ⚠ Engine 1 error: {exc}")

    # ── RS calculations ───────────────────────────────────────────
    rs_ratio    = 0.0
    rs_52w_high = 0.0
    rs_blue_dot = False
    rs_score    = 0.0
    if spy_df is not None:
        try:
            rs_line = calculate_rs_line(df, spy_df)
            if rs_line and len(rs_line) >= 252:
                rs_ratio    = float(rs_line[-1])
                rs_52w_high = float(max(rs_line))
                rs_blue_dot = detect_rs_blue_dot(rs_line)
            rs_score = calculate_rs_score(df, spy_df)
        except Exception as exc:
            print(f"  ⚠ RS calc error: {exc}")

    print(f"\n  RS score: {rs_score:+.4f}   Blue dot: {rs_blue_dot}   SPY 3m: {spy_3m_return:+.2%}")

    # ── Trendline ─────────────────────────────────────────────────
    tl = None
    try:
        tl = detect_trendline(ticker, df)
        parts = []
        if tl and tl.get("descending"):
            parts.append("descending")
        if tl and tl.get("ascending"):
            parts.append("ascending")
        print(f"  Trendlines: {', '.join(parts) if parts else 'none'}")
    except Exception as exc:
        print(f"  ⚠ Trendline error: {exc}")

    # ── ENGINE 2: VCP ─────────────────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 2 — VCP BREAKOUT")
    print(_DIV)
    total += 1
    try:
        res = scan_vcp(
            ticker, df, zones, spy_3m_return,
            rs_ratio, rs_52w_high, rs_blue_dot, rs_score,
            debug=True,
        )
        if res:
            sig = ("LEAD" if res.get("is_rs_lead") else
                   "BRK"  if res.get("is_breakout") else "DRY")
            print(f"✓ PASS [{sig}]  entry={res['entry']:.2f}  "
                  f"stop={res['stop_loss']:.2f}  target={res['take_profit']:.2f}  "
                  f"R:R={res['rr']:.1f}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 2 error: {exc}")

    # ── ENGINE 3: Strict Pullback ──────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 3 — STRICT TACTICAL PULLBACK")
    print(_DIV)
    total += 1
    try:
        res = scan_pullback(ticker, df, zones, tl, debug=True)
        if res:
            print(f"✓ PASS  entry={res['entry']:.2f}  stop={res['stop_loss']:.2f}  "
                  f"target={res['take_profit']:.2f}  CCI={res.get('cci_today', 0):.1f}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 3 (strict) error: {exc}")

    # ── ENGINE 3: Relaxed Pullback ────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 3 — RELAXED PULLBACK (RLX)")
    print(_DIV)
    total += 1
    try:
        res = scan_relaxed_pullback(ticker, df, zones, tl, debug=True)
        if res:
            print(f"✓ PASS [RLX]  entry={res['entry']:.2f}  stop={res['stop_loss']:.2f}  "
                  f"target={res['take_profit']:.2f}  CCI={res.get('cci_today', 0):.1f}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 3 (relaxed) error: {exc}")

    # ── ENGINE 5: Base Patterns ───────────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 5 — BASE PATTERNS (Cup & Handle / Flat Base)")
    print(_DIV)
    total += 1
    try:
        res = scan_base_pattern(
            ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score
        )
        if res:
            print(f"✓ PASS [{res.get('base_type', '')}]  "
                  f"Q={res.get('quality_score', 0)}  entry={res['entry']:.2f}")
            passes += 1
        else:
            print("✗ No qualifying base pattern")
    except Exception as exc:
        print(f"  ✗ Engine 5 error: {exc}")

    # ── ENGINE 6: Resistance Breakout ─────────────────────────────
    print(f"\n{_DIV}")
    print("  ENGINE 6 — RESISTANCE BREAKOUT")
    print(_DIV)
    total += 1
    try:
        res = scan_resistance_breakout(ticker, df, zones, debug=True)
        if res:
            print(f"✓ PASS  level={res.get('resistance_level', 0):.2f}  "
                  f"vol={res.get('volume_ratio', 0):.1f}x  "
                  f"days_ago={res.get('days_since_breakout', 0)}")
            passes += 1
    except Exception as exc:
        print(f"  ✗ Engine 6 error: {exc}")

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'═' * 62}")
    status = "✓" if passes > 0 else "✗"
    print(f"  {status} RESULT: {passes}/{total} engines found a setup for {ticker}")
    print(f"{'═' * 62}\n")


if __name__ == "__main__":
    main()
