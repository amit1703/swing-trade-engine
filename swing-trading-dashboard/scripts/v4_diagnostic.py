"""
v4_diagnostic.py — Deep diagnostic analysis for Strategy V4.

Re-runs the WFO with the current constants (v4 best params already applied)
and generates 11 diagnostic sections without modifying any strategy logic.

Usage:
    cd /Users/amit/Documents/GitHub/superpowers/swing-trading-dashboard/backend
    python ../scripts/v4_diagnostic.py

Output:
    ../docs/optuna-v4-diagnostic-report.md
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

# ── Path setup ───────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..", "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPT_DIR)

from representative_tickers import REPRESENTATIVE_TICKERS
from wfo_engine import run_wfo

# ── WFO config (same as v4 optimizer) ────────────────────────────────────────
TICKERS     = ["SPY"] + REPRESENTATIVE_TICKERS
SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
IS_MONTHS   = 36
OOS_MONTHS  = 6
STEP_MONTHS = 6

# ── Output ────────────────────────────────────────────────────────────────────
DOCS_DIR    = os.path.join(SCRIPT_DIR, "..", "docs")
REPORT_PATH = os.path.join(DOCS_DIR, "optuna-v4-diagnostic-report.md")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def pf(wins, losses):
    gp = sum(w for w in wins if w > 0)
    gl = abs(sum(l for l in losses if l < 0))
    return gp / gl if gl > 0 else float("inf")


def streak_stats(is_win_list):
    if not is_win_list:
        return 0, 0, 0.0, 0.0
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    win_streaks, loss_streaks = [], []
    for w in is_win_list:
        if w:
            cur_win += 1
            if cur_loss > 0:
                loss_streaks.append(cur_loss)
            cur_loss = 0
        else:
            cur_loss += 1
            if cur_win > 0:
                win_streaks.append(cur_win)
            cur_win = 0
        max_win_streak  = max(max_win_streak, cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)
    if cur_win > 0:  win_streaks.append(cur_win)
    if cur_loss > 0: loss_streaks.append(cur_loss)
    avg_win  = np.mean(win_streaks)  if win_streaks  else 0.0
    avg_loss = np.mean(loss_streaks) if loss_streaks else 0.0
    return max_win_streak, max_loss_streak, avg_win, avg_loss


def equity_curve(trades_sorted):
    """Returns list of (date, cumulative_portfolio_pnl_pct) pairs."""
    eq = 0.0
    curve = [("START", 0.0)]
    for t in trades_sorted:
        eq += t["portfolio_pnl_pct"]
        curve.append((t["exit_date"], round(eq, 4)))
    return curve


def max_drawdown_from_curve(curve):
    peak = -float("inf")
    max_dd = 0.0
    peak_date = dd_start = dd_end = ""
    for date, val in curve:
        if val > peak:
            peak = val
            peak_date = date
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
            dd_start = peak_date
            dd_end = date
    return max_dd, dd_start, dd_end


def r_bucket(r):
    if r <= -0.5:    return "-1R (stop)"
    if r < 0:        return "0 to -0.5R (partial stop)"
    if r < 1.0:      return "0 to 1R (small win/scratch)"
    if r < 2.0:      return "1R to 2R"
    if r < 5.0:      return "2R to 5R"
    return "5R+ (runner)"


def bar(count, total, width=30):
    filled = int(width * count / total) if total > 0 else 0
    return "█" * filled + "░" * (width - filled)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print("Running WFO with v4 parameters...")
    print(f"  Tickers: {len(TICKERS)} ({len(REPRESENTATIVE_TICKERS)} + SPY)")
    print(f"  Setups:  {SETUP_TYPES}")
    print(f"  Windows: IS={IS_MONTHS}m / OOS={OOS_MONTHS}m / step={STEP_MONTHS}m")
    print()

    result = await run_wfo(
        tickers=TICKERS,
        setup_types=SETUP_TYPES,
        is_months=IS_MONTHS,
        oos_months=OOS_MONTHS,
        step_months=STEP_MONTHS,
    )

    # ── Collect all OOS trades ───────────────────────────────────────────────
    all_oos_trades = []
    for window in result.windows:
        all_oos_trades.extend(window.oos_trades)

    # Sort by exit date
    all_oos_trades.sort(key=lambda t: t["exit_date"])

    n = len(all_oos_trades)
    print(f"  OOS trades collected: {n}")
    print(f"  Windows:              {len(result.windows)}")
    print()

    if n == 0:
        print("ERROR: No OOS trades found. Exiting.")
        return

    # ── Pre-compute arrays ────────────────────────────────────────────────────
    wins   = [t for t in all_oos_trades if t["is_win"]]
    losses = [t for t in all_oos_trades if not t["is_win"]]
    all_r  = [t["rr_achieved"] for t in all_oos_trades]
    win_r  = [t["rr_achieved"] for t in wins]
    loss_r = [t["rr_achieved"] for t in losses]
    all_pnl_pct = [t["pnl_pct"] for t in all_oos_trades]
    win_pnl  = [t["pnl_pct"] for t in wins]
    loss_pnl = [t["pnl_pct"] for t in losses]
    port_pnl = [t["portfolio_pnl_pct"] for t in all_oos_trades]
    hold_days = [t["holding_days"] for t in all_oos_trades]

    win_rate   = len(wins) / n * 100
    avg_win_r  = np.mean(win_r)  if win_r  else 0.0
    avg_loss_r = np.mean(loss_r) if loss_r else 0.0
    avg_r      = np.mean(all_r)
    expectancy = np.mean(all_pnl_pct)
    gross_profit = sum(win_pnl)
    gross_loss   = abs(sum(loss_pnl))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_pnl_pct  = sum(port_pnl)

    # Equity curve & drawdown
    curve   = equity_curve(all_oos_trades)
    max_dd, dd_start, dd_end = max_drawdown_from_curve(curve)

    # ── Date range ────────────────────────────────────────────────────────────
    first_trade = all_oos_trades[0]["entry_date"]
    last_trade  = all_oos_trades[-1]["exit_date"]

    # ── OOS total calendar days (approx exposure calc) ─────────────────────
    # Sum of all OOS windows
    oos_total_calendar_days = sum(
        (datetime.strptime(w.oos_end, "%Y-%m-%d") - datetime.strptime(w.oos_start, "%Y-%m-%d")).days
        for w in result.windows
    )
    # Total days in trades
    total_hold_days = sum(hold_days)
    # Exposure: total holding days across all simultaneous positions / total OOS days
    # (rough: not accounting for overlap, so divide by universe count)
    exposure_pct = (total_hold_days / oos_total_calendar_days * 100) if oos_total_calendar_days > 0 else 0

    # ── Setup breakdown ───────────────────────────────────────────────────────
    setup_trades = defaultdict(list)
    for t in all_oos_trades:
        setup_trades[t["setup_type"]].append(t)

    # ── Ticker concentration ──────────────────────────────────────────────────
    ticker_trades = defaultdict(list)
    for t in all_oos_trades:
        ticker_trades[t["ticker"]].append(t)

    # ── Time distribution ─────────────────────────────────────────────────────
    year_trades  = defaultdict(list)
    qtr_trades   = defaultdict(list)
    for t in all_oos_trades:
        d = t["exit_date"]
        yr = d[:4]
        mo = int(d[5:7])
        q  = f"{yr}-Q{(mo - 1) // 3 + 1}"
        year_trades[yr].append(t)
        qtr_trades[q].append(t)

    # ── Streaks ───────────────────────────────────────────────────────────────
    is_win_seq = [t["is_win"] for t in all_oos_trades]
    max_ws, max_ls, avg_ws, avg_ls = streak_stats(is_win_seq)

    # ── R-multiple buckets ────────────────────────────────────────────────────
    r_buckets = defaultdict(int)
    for r in all_r:
        r_buckets[r_bucket(r)] += 1

    # ── Holding time ─────────────────────────────────────────────────────────
    hold_buckets = defaultdict(int)
    for h in hold_days:
        if h <= 3:    hold_buckets["1–3 days"] += 1
        elif h <= 7:  hold_buckets["4–7 days"] += 1
        elif h <= 14: hold_buckets["8–14 days"] += 1
        elif h <= 30: hold_buckets["15–30 days"] += 1
        else:         hold_buckets["31+ days"] += 1

    # ── Exit reason breakdown ─────────────────────────────────────────────────
    exit_counts = defaultdict(int)
    for t in all_oos_trades:
        exit_counts[t["exit_reason"]] += 1

    # ── Window OOS periods for regime proxy ───────────────────────────────────
    window_summaries = []
    for w in result.windows:
        wt = w.oos_trades
        if not wt:
            continue
        wr   = len([t for t in wt if t["is_win"]]) / len(wt) * 100
        pnls = [t["pnl_pct"] for t in wt]
        wp   = sum(p for p in pnls if p > 0)
        wl   = abs(sum(p for p in pnls if p < 0))
        wpf  = wp / wl if wl > 0 else float("inf")
        wnet = sum(t["portfolio_pnl_pct"] for t in wt)
        window_summaries.append({
            "window": w.window_num,
            "period": f"{w.oos_start} → {w.oos_end}",
            "trades": len(wt),
            "win_rate": round(wr, 1),
            "pf": round(wpf, 2),
            "net_pct": round(wnet, 2),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Report assembly
    # ─────────────────────────────────────────────────────────────────────────
    lines = []
    def L(s=""): lines.append(s)

    L("# Optuna v4 — Deep Diagnostic Report")
    L()
    L(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L(f"**Universe:** {len(REPRESENTATIVE_TICKERS)} tickers + SPY")
    L(f"**WFO Config:** IS={IS_MONTHS}m / OOS={OOS_MONTHS}m / step={STEP_MONTHS}m ({len(result.windows)} windows)")
    L(f"**OOS Period:** {first_trade} → {last_trade}")
    L(f"**Parameters:** v4 best (trial #951, score=0.5932)")
    L()
    L("---")
    L()

    # ── 1. Trade Breakdown by Setup ──────────────────────────────────────────
    L("## 1. Trade Breakdown by Setup")
    L()
    L("| Setup | Trades | Win Rate | Avg Win R | Avg Loss R | Expectancy | PF |")
    L("|---|---|---|---|---|---|---|")
    for stype in sorted(setup_trades.keys()):
        st = setup_trades[stype]
        sw = [t for t in st if t["is_win"]]
        sl = [t for t in st if not t["is_win"]]
        swr  = len(sw) / len(st) * 100 if st else 0
        sawr = np.mean([t["rr_achieved"] for t in sw]) if sw else 0
        salr = np.mean([t["rr_achieved"] for t in sl]) if sl else 0
        sexp = np.mean([t["pnl_pct"] for t in st]) if st else 0
        sgp  = sum(t["pnl_pct"] for t in sw)
        sgl  = abs(sum(t["pnl_pct"] for t in sl))
        spf  = sgp / sgl if sgl > 0 else float("inf")
        L(f"| {stype} | {len(st)} | {swr:.1f}% | +{sawr:.2f}R | {salr:.2f}R | {sexp:.2f}% | {spf:.2f} |")
    L(f"| **TOTAL** | **{n}** | **{win_rate:.1f}%** | **+{avg_win_r:.2f}R** | **{avg_loss_r:.2f}R** | **{expectancy:.2f}%** | **{profit_factor:.2f}** |")
    L()

    # ── 2. Win/Loss Statistics ───────────────────────────────────────────────
    L("## 2. Win/Loss Statistics")
    L()
    L(f"| Metric | Value |")
    L(f"|---|---|")
    L(f"| Total trades | {n} |")
    L(f"| Wins | {len(wins)} ({win_rate:.1f}%) |")
    L(f"| Losses | {len(losses)} ({100 - win_rate:.1f}%) |")
    L(f"| Average win (pnl%) | +{np.mean(win_pnl):.2f}% |")
    L(f"| Average loss (pnl%) | {np.mean(loss_pnl):.2f}% |")
    L(f"| Largest win | +{max(win_pnl):.2f}% |")
    L(f"| Largest loss | {min(loss_pnl):.2f}% |")
    L(f"| Average win R-multiple | +{avg_win_r:.3f}R |")
    L(f"| Average loss R-multiple | {avg_loss_r:.3f}R |")
    L(f"| Average R-multiple (all) | {avg_r:.3f}R |")
    L(f"| Expectancy (per trade) | {expectancy:.3f}% |")
    L(f"| Gross profit | +{gross_profit:.2f}% |")
    L(f"| Gross loss | -{gross_loss:.2f}% |")
    L(f"| Profit factor | {profit_factor:.3f} |")
    L(f"| Net portfolio P&L | {net_pnl_pct:+.2f}% |")
    L(f"| Max drawdown | {max_dd:.2f}% ({dd_start} → {dd_end}) |")
    L()
    L("**Exit reason breakdown:**")
    L()
    L("| Exit Reason | Count | % |")
    L("|---|---|---|")
    for reason, cnt in sorted(exit_counts.items(), key=lambda x: -x[1]):
        L(f"| {reason} | {cnt} | {cnt/n*100:.1f}% |")
    L()

    # ── 3. Trade Distribution Over Time ──────────────────────────────────────
    L("## 3. Trade Distribution Over Time")
    L()
    L("### By Year")
    L()
    L("| Year | Trades | Win Rate | Net P&L | PF |")
    L("|---|---|---|---|---|")
    for yr in sorted(year_trades.keys()):
        yt = year_trades[yr]
        yw  = [t for t in yt if t["is_win"]]
        ywr = len(yw) / len(yt) * 100 if yt else 0
        ynet = sum(t["portfolio_pnl_pct"] for t in yt)
        ygp  = sum(t["pnl_pct"] for t in yw)
        ygl  = abs(sum(t["pnl_pct"] for t in [t for t in yt if not t["is_win"]]))
        ypf  = ygp / ygl if ygl > 0 else float("inf")
        L(f"| {yr} | {len(yt)} | {ywr:.1f}% | {ynet:+.2f}% | {ypf:.2f} |")
    L()
    L("### By Quarter")
    L()
    L("| Quarter | Trades | Win Rate | Net P&L |")
    L("|---|---|---|---|")
    for qtr in sorted(qtr_trades.keys()):
        qt = qtr_trades[qtr]
        qw  = len([t for t in qt if t["is_win"]])
        qwr = qw / len(qt) * 100 if qt else 0
        qnet = sum(t["portfolio_pnl_pct"] for t in qt)
        L(f"| {qtr} | {len(qt)} | {qwr:.1f}% | {qnet:+.2f}% |")
    L()

    # ── 4. Equity Curve ───────────────────────────────────────────────────────
    L("## 4. Equity Curve")
    L()
    L(f"Portfolio starts at 0%. Each trade adds `portfolio_pnl_pct` (1% risk model).")
    L()
    L("| Exit Date | Trade # | Ticker | R | Cum. P&L |")
    L("|---|---|---|---|---|")
    cum = 0.0
    for i, t in enumerate(all_oos_trades, 1):
        cum += t["portfolio_pnl_pct"]
        marker = " ▲" if t["is_win"] else " ▼"
        L(f"| {t['exit_date']} | {i} | {t['ticker']} ({t['setup_type']}) | {t['rr_achieved']:+.2f}R{marker} | {cum:+.2f}% |")
    L()
    L(f"**Final equity:** {cum:+.2f}%")
    L(f"**Max drawdown:** {max_dd:.2f}% (peak {dd_start} → trough {dd_end})")
    L()

    # ── 5. Consecutive Loss Statistics ───────────────────────────────────────
    L("## 5. Consecutive Loss / Win Statistics")
    L()
    L(f"| Metric | Value |")
    L(f"|---|---|")
    L(f"| Max winning streak | {max_ws} trades |")
    L(f"| Max losing streak | {max_ls} trades |")
    L(f"| Avg winning streak | {avg_ws:.1f} trades |")
    L(f"| Avg losing streak | {avg_ls:.1f} trades |")
    L()
    L("**Win/Loss sequence (W=win, L=loss):**")
    L()
    seq_str = "".join("W" if t["is_win"] else "L" for t in all_oos_trades)
    # Break into 60-char lines
    for i in range(0, len(seq_str), 60):
        L(f"`{seq_str[i:i+60]}`")
    L()

    # ── 6. R-Multiple Distribution ────────────────────────────────────────────
    L("## 6. R-Multiple Distribution")
    L()
    BUCKET_ORDER = [
        "-1R (stop)",
        "0 to -0.5R (partial stop)",
        "0 to 1R (small win/scratch)",
        "1R to 2R",
        "2R to 5R",
        "5R+ (runner)",
    ]
    L("| R Bucket | Count | % | Distribution |")
    L("|---|---|---|---|")
    for b in BUCKET_ORDER:
        cnt = r_buckets.get(b, 0)
        pct = cnt / n * 100
        L(f"| {b} | {cnt} | {pct:.1f}% | {bar(cnt, n)} |")
    L()
    L(f"**All R values:** min={min(all_r):.2f} | median={np.median(all_r):.2f} | mean={np.mean(all_r):.2f} | max={max(all_r):.2f}")
    L()

    # ── 7. Holding Time Analysis ──────────────────────────────────────────────
    L("## 7. Holding Time Analysis")
    L()
    L(f"| Metric | Value |")
    L(f"|---|---|")
    L(f"| Average hold | {np.mean(hold_days):.1f} days |")
    L(f"| Median hold | {np.median(hold_days):.0f} days |")
    L(f"| Shortest hold | {min(hold_days)} days |")
    L(f"| Longest hold | {max(hold_days)} days |")
    L()
    L("**Hold duration distribution:**")
    L()
    L("| Duration | Count | % | Distribution |")
    L("|---|---|---|---|")
    HOLD_ORDER = ["1–3 days", "4–7 days", "8–14 days", "15–30 days", "31+ days"]
    for b in HOLD_ORDER:
        cnt = hold_buckets.get(b, 0)
        pct = cnt / n * 100
        L(f"| {b} | {cnt} | {pct:.1f}% | {bar(cnt, n)} |")
    L()

    # ── 8. Exposure ───────────────────────────────────────────────────────────
    L("## 8. Market Exposure")
    L()
    L(f"| Metric | Value |")
    L(f"|---|---|")
    L(f"| Total OOS calendar days | {oos_total_calendar_days} |")
    L(f"| Total hold-days (all trades) | {total_hold_days} |")
    L(f"| Avg trades open simultaneously | {total_hold_days / oos_total_calendar_days:.2f} |")
    L(f"| Rough exposure (hold-days / OOS days) | {exposure_pct:.1f}% |")
    L()
    L("> Note: Exposure calculation counts each trade's holding period independently.")
    L("> With MAX_OPEN_POSITIONS=5, maximum theoretical exposure is 5×1%=5% equity at risk at any time.")
    L()

    # ── 9. Per-Window Performance (Regime Proxy) ──────────────────────────────
    L("## 9. Per-Window Performance (Regime Analysis)")
    L()
    L("Each OOS window represents 6 months. Performance variation across windows")
    L("reveals regime sensitivity — good windows correspond to trending markets.")
    L()
    L("| Window | OOS Period | Trades | Win Rate | PF | Net P&L |")
    L("|---|---|---|---|---|---|")
    for ws in window_summaries:
        quality = "✅" if ws["pf"] >= 2.0 else "⚠️" if ws["pf"] >= 1.0 else "❌"
        L(f"| W{ws['window']} {quality} | {ws['period']} | {ws['trades']} | {ws['win_rate']:.1f}% | {ws['pf']:.2f} | {ws['net_pct']:+.2f}% |")
    L()
    L("Legend: ✅ PF ≥ 2.0 (strong) | ⚠️ PF 1.0–2.0 (marginal) | ❌ PF < 1.0 (losing window)")
    L()

    # ── 10. Ticker Concentration ──────────────────────────────────────────────
    L("## 10. Ticker Concentration")
    L()
    L("| Ticker | Trades | Win Rate | Net Contribution | % of Total Trades |")
    L("|---|---|---|---|---|")
    sorted_tickers = sorted(ticker_trades.items(), key=lambda x: -len(x[1]))
    for ticker, tt in sorted_tickers:
        tw   = len([t for t in tt if t["is_win"]])
        twr  = tw / len(tt) * 100 if tt else 0
        tnet = sum(t["portfolio_pnl_pct"] for t in tt)
        tpct = len(tt) / n * 100
        L(f"| {ticker} | {len(tt)} | {twr:.0f}% | {tnet:+.2f}% | {tpct:.1f}% |")

    # Concentration metric
    top5_trades = sum(len(tt) for _, tt in sorted_tickers[:5])
    top5_pct    = top5_trades / n * 100
    L()
    L(f"**Top 5 tickers:** {top5_trades} trades ({top5_pct:.1f}% of total)")
    L()
    herfindahl = sum((len(tt)/n)**2 for _, tt in sorted_tickers)
    L(f"**Herfindahl concentration index:** {herfindahl:.4f}")
    L(f"(0 = perfectly distributed, 1 = all trades in one ticker; <0.10 = well diversified)")
    L()

    # ── 11. Summary Diagnostics ───────────────────────────────────────────────
    L("## 11. Summary Diagnostics")
    L()

    # Statistical thinness
    import math
    if n < 30:
        thin_verdict = "🔴 **VERY THIN** — fewer than 30 OOS trades. Results are statistically unreliable."
    elif n < 50:
        thin_verdict = "🟡 **THIN** — fewer than 50 OOS trades. Confidence intervals are wide. Treat with caution."
    elif n < 100:
        thin_verdict = "🟠 **MODERATE** — 50–100 trades. Directionally meaningful but not statistically robust."
    else:
        thin_verdict = "🟢 **ADEQUATE** — 100+ OOS trades. Results carry reasonable statistical weight."

    # Standard error of win rate
    se_wr = math.sqrt(win_rate/100 * (1 - win_rate/100) / n) * 100
    ci_lo = max(0, win_rate - 1.96 * se_wr)
    ci_hi = min(100, win_rate + 1.96 * se_wr)

    # Concentration check
    top1_trades = len(sorted_tickers[0][1]) if sorted_tickers else 0
    top1_pct    = top1_trades / n * 100
    if top1_pct > 25:
        conc_verdict = f"🔴 **HIGH CONCENTRATION** — top ticker ({sorted_tickers[0][0]}) contributes {top1_pct:.1f}% of trades."
    elif top5_pct > 60:
        conc_verdict = f"🟡 **MODERATE CONCENTRATION** — top 5 tickers = {top5_pct:.1f}% of trades."
    else:
        conc_verdict = f"🟢 **WELL DISTRIBUTED** — top 5 tickers = {top5_pct:.1f}% of trades."

    # Universe recommendation
    if n < 50:
        universe_rec = "🔴 **EXPAND UNIVERSE** — critical. Current sample is too thin for live deployment confidence."
    elif n < 100:
        universe_rec = "🟡 **CONSIDER EXPANSION** — target 100+ OOS trades via larger ticker universe."
    else:
        universe_rec = "🟢 **UNIVERSE SIZE ADEQUATE** — sufficient OOS trades for initial confidence."

    # Drawdown assessment
    if max_dd < 3.0:
        dd_verdict = f"🟢 **LOW DRAWDOWN** — {max_dd:.2f}%. System demonstrates strong drawdown control."
    elif max_dd < 8.0:
        dd_verdict = f"🟡 **MODERATE DRAWDOWN** — {max_dd:.2f}%. Acceptable for a 1% risk-per-trade strategy."
    else:
        dd_verdict = f"🔴 **HIGH DRAWDOWN** — {max_dd:.2f}%. Review position sizing or regime gates."

    # Profit factor assessment
    if profit_factor >= 2.5:
        pf_verdict = f"🟢 **EXCELLENT PROFIT FACTOR** — {profit_factor:.2f}. Winners meaningfully outweigh losers."
    elif profit_factor >= 1.5:
        pf_verdict = f"🟡 **GOOD PROFIT FACTOR** — {profit_factor:.2f}. Solid edge."
    elif profit_factor >= 1.0:
        pf_verdict = f"🟠 **MARGINAL PROFIT FACTOR** — {profit_factor:.2f}. Monitor closely in live trading."
    else:
        pf_verdict = f"🔴 **NEGATIVE EDGE** — {profit_factor:.2f}. Strategy is losing money."

    # Window consistency
    winning_windows = sum(1 for ws in window_summaries if ws["pf"] >= 1.0)
    total_windows   = len(window_summaries)
    if winning_windows == total_windows:
        win_window_verdict = f"🟢 **ALL WINDOWS PROFITABLE** — {winning_windows}/{total_windows}. No losing periods."
    elif winning_windows >= total_windows * 0.75:
        win_window_verdict = f"🟡 **MOSTLY CONSISTENT** — {winning_windows}/{total_windows} windows profitable."
    else:
        win_window_verdict = f"🔴 **INCONSISTENT** — only {winning_windows}/{total_windows} windows profitable."

    L("### Statistical Reliability")
    L()
    L(f"- {thin_verdict}")
    L(f"- **OOS trades:** {n} | **Win rate 95% CI:** {ci_lo:.1f}% – {ci_hi:.1f}% (point estimate: {win_rate:.1f}%)")
    L(f"- **Recommended minimum:** 100 OOS trades for live deployment confidence")
    L()
    L("### Concentration Risk")
    L()
    L(f"- {conc_verdict}")
    L(f"- Herfindahl index: {herfindahl:.4f}")
    L()
    L("### Performance Quality")
    L()
    L(f"- {dd_verdict}")
    L(f"- {pf_verdict}")
    L(f"- {win_window_verdict}")
    L()
    L("### Universe Recommendation")
    L()
    L(f"- {universe_rec}")
    L(f"- Current: {len(REPRESENTATIVE_TICKERS)} tickers → generates ~{n} OOS trades over ~{oos_total_calendar_days//365}y")
    L(f"- To reach 100 OOS trades: estimate ~{int(100 * len(REPRESENTATIVE_TICKERS) / max(n, 1))} tickers needed")
    L()
    L("### Key Risks for Live Trading")
    L()
    L(f"1. **Statistical thinness:** {n} trades → confidence intervals wide. Single bad month can look like strategy failure.")
    L(f"2. **Regime dependency:** System requires REGIME_SELECTIVE_THRESHOLD=59. If SPY weakens, the system goes dark for months.")
    L(f"3. **TRAIL=4.16 ATR sensitivity:** Wide trailing stops can give back significant open profit in a sharp market reversal.")
    L(f"4. **yfinance data quality:** Live scanner uses yfinance; backtests use cached adjusted prices. Small discrepancies may exist.")
    L(f"5. **OOS ≠ Live:** Walk-forward avoids lookahead but cannot replicate slippage, partial fills, or regime breaks between windows.")
    L()

    L("---")
    L()
    L(f"*Generated by v4_diagnostic.py on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    # ── Write report ──────────────────────────────────────────────────────────
    report = "\n".join(lines)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(f"\nReport written to: {REPORT_PATH}")
    print(f"\nKey metrics:")
    print(f"  Trades:        {n}")
    print(f"  Win rate:      {win_rate:.1f}%")
    print(f"  Expectancy:    {expectancy:.3f}%")
    print(f"  Profit factor: {profit_factor:.3f}")
    print(f"  Net P&L:       {net_pnl_pct:+.2f}%")
    print(f"  Max drawdown:  {max_dd:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
