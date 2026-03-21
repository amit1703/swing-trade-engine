"""
Trail ATR Diagnostic -- answers Q1-Q6.

Runs the 26-ticker 2020-2024 backtest at trail_mult = 3.0 / 4.25 / 5.5
and analyzes exit reasons, giveback (via rr_achieved), per-setup breakdown,
and RS threshold sensitivity.

Usage (run from backend/ directory):
    python ../scripts/trail_diagnostic.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_SCRIPTS))

from backtest_engine import run_backtest_universe
from representative_tickers_v2 import REPRESENTATIVE_TICKERS_V2

START  = "2020-01-01"
END    = "2024-12-31"
SETUPS = ["PULLBACK", "BASE", "RES_BREAKOUT", "HTF"]
TICKERS = REPRESENTATIVE_TICKERS_V2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def profit_r(t: dict) -> float | None:
    ep = t.get("entry_price", 0)
    sl = t.get("initial_stop", 0)
    xp = t.get("exit_price", 0)
    if ep and sl and ep != sl:
        return (xp - ep) / (ep - sl)
    return None


def summary(trades: list[dict], label: str = "") -> str:
    rs = [r for t in trades if (r := profit_r(t)) is not None]
    if not rs:
        return f"{label}: n={len(trades)} (no R data)"
    wins   = [r for r in rs if r > 0]
    losses = [abs(r) for r in rs if r <= 0]
    exp    = sum(rs) / len(rs)
    pf     = sum(wins) / sum(losses) if losses else float("inf")
    prefix = f"{label}: " if label else ""
    return (f"{prefix}n={len(rs)}  win={len(wins)/len(rs)*100:.1f}%  "
            f"exp={exp:+.3f}R  PF={pf:.2f}")


def exit_pcts(trades: list[dict]) -> str:
    c = Counter(t.get("exit_reason", "?") for t in trades)
    n = len(trades)
    return (f"TARGET={c.get('TARGET',0)} ({c.get('TARGET',0)/n*100:.0f}%)  "
            f"TRAIL-STOP={c.get('STOP',0)} ({c.get('STOP',0)/n*100:.0f}%)  "
            f"EOD={c.get('EOD',0)} ({c.get('EOD',0)/n*100:.0f}%)")


def rr_dist(rs: list[float]) -> str:
    if not rs:
        return "no data"
    buckets = [("<0", 0), ("0-0.5", 0), ("0.5-1", 0), ("1-2", 0), ("2-3", 0), ("3+", 0)]
    for r in rs:
        if r < 0:     buckets[0] = (buckets[0][0], buckets[0][1]+1)
        elif r < 0.5: buckets[1] = (buckets[1][0], buckets[1][1]+1)
        elif r < 1.0: buckets[2] = (buckets[2][0], buckets[2][1]+1)
        elif r < 2.0: buckets[3] = (buckets[3][0], buckets[3][1]+1)
        elif r < 3.0: buckets[4] = (buckets[4][0], buckets[4][1]+1)
        else:         buckets[5] = (buckets[5][0], buckets[5][1]+1)
    n = len(rs)
    return "  ".join(f"{k}:{v}({v/n*100:.0f}%)" for k, v in buckets)


def run(trail_mult: float) -> list[dict]:
    return asyncio.run(run_backtest_universe(
        tickers=TICKERS,
        start_date=START,
        end_date=END,
        trail_mult_override=trail_mult,
        params=None,
        setup_types=SETUPS,
    ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sep = "=" * 64

    # ── Run all three trail levels ────────────────────────────────────────────
    print(f"\nRunning backtest at 3 trail levels ({START} to {END})...")
    results: dict[float, list[dict]] = {}
    for mult in (3.0, 4.25, 5.5):
        print(f"  trail_mult={mult}...", end=" ", flush=True)
        results[mult] = run(mult)
        print("done")

    trades_425 = results[4.25]
    sep_line = "-" * 64

    # ── Q2 + Q5: Exit reasons ─────────────────────────────────────────────────
    print(f"\n{sep}")
    print("Q2 / Q5 -- EXIT REASONS  (trail_mult=4.25)")
    print(sep)
    print(f"  All setups:  {exit_pcts(trades_425)}")
    for stype in ["PULLBACK", "RES_BREAKOUT", "BASE", "HTF"]:
        grp = [t for t in trades_425 if t.get("setup_type") == stype]
        if grp:
            print(f"  {stype:<14} {exit_pcts(grp)}  (n={len(grp)})")

    targets_hit = sum(1 for t in trades_425 if t.get("exit_reason") == "TARGET")
    print(f"\n  TARGET_RR=4.346 reached by {targets_hit}/{len(trades_425)} trades "
          f"({targets_hit/len(trades_425)*100:.1f}%).")
    if targets_hit < len(trades_425) * 0.05:
        print("  -> TARGET is hit <5% of the time. It acts as a safety cap, not a real exit.")
    print(f"  Trailing stop is the PRIMARY exit ({results[4.25].count if False else sum(1 for t in trades_425 if t.get('exit_reason')=='STOP')}/{len(trades_425)} trades).")

    # ── Q1: Giveback (rr_achieved distribution on stopped winners) ────────────
    print(f"\n{sep}")
    print("Q1 -- GIVEBACK ANALYSIS  (trail_mult=4.25)")
    print("Stopped winners = exit_reason=STOP and rr_achieved > 0")
    print(sep)
    stopped_w = [t for t in trades_425 if t.get("exit_reason") == "STOP" and (profit_r(t) or 0) > 0]
    all_wins   = [t for t in trades_425 if (profit_r(t) or 0) > 0]
    sw_rs = [profit_r(t) for t in stopped_w if profit_r(t) is not None]
    print(f"  Winners total:          {len(all_wins)}")
    print(f"  Stopped winners:        {len(stopped_w)} ({len(stopped_w)/len(all_wins)*100:.0f}% of winners)")
    print(f"  Avg R captured:         {sum(sw_rs)/len(sw_rs):+.3f}R" if sw_rs else "  No data")
    print(f"  R distribution:         {rr_dist(sw_rs)}")
    print()

    # Giveback estimate: trail distance at exit = trail_mult * ATR
    # At 4.25x trail, the trail gap is about 4.25 * avg_ATR_pct of price
    # We can estimate: if stopped winner exits at rr_achieved R, it was at peak ~
    # rr_achieved + trail_gap. Gap in R terms = trail_mult * ATR / initial_risk
    # Use avg stop distance to estimate
    avg_stop_pct = []
    for t in stopped_w:
        ep = t.get("entry_price", 0)
        sl = t.get("initial_stop", 0)
        if ep and sl and ep > sl:
            avg_stop_pct.append((ep - sl) / ep * 100)
    if avg_stop_pct:
        avg_stop = sum(avg_stop_pct) / len(avg_stop_pct)
        # trail gap in R: (trail_mult * ATR) / initial_risk
        # initial_risk = avg_stop_pct*ep; ATR ≈ initial_risk/ATR_STOP_MULT
        # so trail_gap_R ≈ trail_mult / ATR_STOP_MULT
        trail_gap_r = 4.25 / 1.278
        print(f"  Avg initial stop distance: {avg_stop:.1f}% of entry")
        print(f"  Trail gap in R terms (4.25/1.278): ~{trail_gap_r:.2f}R")
        print(f"  -> Stopped winners gave back ~{trail_gap_r:.1f}R from peak before exit.")
        print(f"  -> A winner that exited at +1.5R likely peaked at ~{1.5+trail_gap_r:.1f}R.")

    # ── Q3 + Q4: Trail comparison ─────────────────────────────────────────────
    print(f"\n{sep}")
    print("Q3 / Q4 -- TRAIL COMPARISON:  3.0  vs  4.25  vs  5.5")
    print(sep)
    print(f"  {'Trail':>6}  {'n':>5}  {'win%':>6}  {'exp':>8}  {'PF':>6}  {'AVG winner R':>14}  {'AVG loser R':>12}")
    print(f"  {sep_line}")
    for mult in (3.0, 4.25, 5.5):
        trades = results[mult]
        rs = [r for t in trades if (r := profit_r(t)) is not None]
        if not rs:
            continue
        wins   = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        exp    = sum(rs) / len(rs)
        pf     = sum(wins) / abs(sum(losses)) if losses else float("inf")
        avg_w  = sum(wins) / len(wins) if wins else 0
        avg_l  = sum(losses) / len(losses) if losses else 0
        marker = " <-- current" if mult == 4.25 else ""
        print(f"  {mult:>6}  {len(rs):>5}  {len(wins)/len(rs)*100:>5.1f}%  "
              f"{exp:>+8.3f}R  {pf:>6.2f}  {avg_w:>+14.3f}R  {avg_l:>+12.3f}R{marker}")

    print()
    print("  Per-setup breakdown:")
    for stype in ["PULLBACK", "RES_BREAKOUT"]:
        print(f"  {stype}:")
        for mult in (3.0, 4.25, 5.5):
            grp = [t for t in results[mult] if t.get("setup_type") == stype]
            sw  = [t for t in grp if t.get("exit_reason") == "STOP" and (profit_r(t) or 0) > 0]
            sw_rs2 = [profit_r(t) for t in sw if profit_r(t) is not None]
            avg_sw = sum(sw_rs2)/len(sw_rs2) if sw_rs2 else 0
            print(f"    trail={mult}: {summary(grp)}  "
                  f"| stopped-wins n={len(sw)} avg={avg_sw:+.3f}R")

    print()
    print("  Stopped-winner R distribution at each trail:")
    for mult in (3.0, 4.25, 5.5):
        trades = results[mult]
        sw = [t for t in trades if t.get("exit_reason") == "STOP" and (profit_r(t) or 0) > 0]
        sw_rs2 = [profit_r(t) for t in sw if profit_r(t) is not None]
        avg = sum(sw_rs2)/len(sw_rs2) if sw_rs2 else 0
        print(f"    trail={mult}: n={len(sw_rs2)} avg={avg:+.3f}R  [{rr_dist(sw_rs2)}]")

    # ── Q6: RS threshold sensitivity ──────────────────────────────────────────
    print(f"\n{sep}")
    print("Q6 -- RS_REJECT_THRESHOLD sensitivity (engine3 PULLBACK filter)")
    print(sep)

    import engines.engine3 as eng3
    original_thresh = eng3.RS_REJECT_THRESHOLD
    print(f"  Current: RS_REJECT_THRESHOLD = {original_thresh}  (from V4 on 43 trades)")
    print()
    print(f"  {'Threshold':>12}  {'note':>18}  {'PB n':>6}  {'PB exp':>8}  {'PB PF':>7}  {'total':>7}")
    print(f"  {sep_line}")

    for thresh, note in [
        (-0.03,   "wider  (old v3)"),
        (-0.02,   "moderate"),
        (-0.01219,"current v4"),
        (0.0,     "neutral (0)"),
        (0.02,    "strict +2%"),
    ]:
        eng3.RS_REJECT_THRESHOLD = thresh
        trades = asyncio.run(run_backtest_universe(
            tickers=TICKERS,
            start_date=START,
            end_date=END,
            trail_mult_override=4.25,
            params=None,
            setup_types=["PULLBACK", "RES_BREAKOUT", "BASE", "HTF"],
        ))
        pb = [t for t in trades if t.get("setup_type") == "PULLBACK"]
        rs = [r for t in pb if (r := profit_r(t)) is not None]
        wins   = [r for r in rs if r > 0]
        losses = [abs(r) for r in rs if r <= 0]
        pb_exp = sum(rs)/len(rs) if rs else 0
        pb_pf  = sum(wins)/sum(losses) if losses else float("inf")
        print(f"  {thresh:>12.5f}  {note:>18}  {len(pb):>6}  "
              f"{pb_exp:>+8.3f}R  {pb_pf:>7.2f}  {len(trades):>7}")

    eng3.RS_REJECT_THRESHOLD = original_thresh

    print()
    print("  Interpretation: does tightening the threshold improve expectancy?")
    print("  A flat expectancy curve = threshold has minimal filtering effect.")


if __name__ == "__main__":
    main()
