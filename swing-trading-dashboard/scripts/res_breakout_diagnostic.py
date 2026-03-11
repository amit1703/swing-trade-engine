"""
RES_BREAKOUT Diagnostic Report
================================
Reads trades from the backtest diagnostics cache and produces a full
breakdown of why breakout trades are underperforming.

Usage (from repo root):
    cd backend
    python3 ../scripts/res_breakout_diagnostic.py

Or with a custom cache path:
    python3 ../scripts/res_breakout_diagnostic.py --cache path/to/cache.json

Output:
    res_breakout_diagnostic.pdf  (charts)
    res_breakout_diagnostic.txt  (table summary)
"""

import argparse
import json
import os
import sys
import textwrap
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# ─── Load trades ──────────────────────────────────────────────────────────────

DEFAULT_CACHE = os.path.join(
    os.path.dirname(__file__), "..", "backend", "cache", "backtest_diagnostics.json"
)


def load_trades(cache_path: str):
    with open(cache_path) as f:
        data = json.load(f)
    trades = data.get("trades", [])
    if not trades:
        print("ERROR: cache has no 'trades' key. Re-run the backtest diagnostics first.")
        print("  POST /api/diagnostics/backtest/run  (backend must be running)")
        sys.exit(1)
    brk = [t for t in trades if t.get("setup_type") == "RES_BREAKOUT"]
    print(f"Loaded {len(trades)} total trades → {len(brk)} RES_BREAKOUT trades")
    print(f"Cache generated: {data.get('generated_at', 'unknown')}")
    print(f"Period: {data.get('start_date')} → {data.get('end_date')}")
    print(f"Tickers run: {data.get('tickers_run')}")
    return brk


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _bucket_stats(trades, key_fn, buckets):
    """
    Group trades into named buckets using key_fn(trade) → bucket_name.
    Returns list of (label, n, wr, avg_r, pf, expectancy).
    """
    groups = defaultdict(list)
    for t in trades:
        b = key_fn(t)
        if b in buckets:
            groups[b].append(t)

    rows = []
    for label in buckets:
        g = groups[label]
        if not g:
            rows.append((label, 0, 0.0, 0.0, 0.0, 0.0))
            continue
        n      = len(g)
        wins   = [t for t in g if t.get("is_win")]
        losses = [t for t in g if not t.get("is_win")]
        wr     = len(wins) / n * 100
        avg_r  = np.mean([t.get("rr_achieved", 0.0) for t in g])
        gross_w = sum(t.get("rr_achieved", 0.0) for t in wins)
        gross_l = abs(sum(t.get("rr_achieved", 0.0) for t in losses))
        pf      = gross_w / gross_l if gross_l > 0 else (float("inf") if gross_w > 0 else 0.0)
        expect  = avg_r
        rows.append((label, n, wr, round(avg_r, 3), round(pf, 2), round(expect, 3)))
    return rows


def _print_table(title, headers, rows, file=None):
    col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
                  for i, h in enumerate(headers)]
    sep = "  ".join("-" * w for w in col_widths)
    hdr = "  ".join(str(h).ljust(w) for h, w in zip(headers, col_widths))
    lines = [f"\n{'━'*60}", f"  {title}", f"{'━'*60}", hdr, sep]
    for row in rows:
        lines.append("  ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
    lines.append("")
    text = "\n".join(lines)
    print(text)
    if file:
        file.write(text + "\n")


def _bar_chart(ax, labels, values, title, ylabel, color="steelblue", zero_line=True):
    colors = ["tomato" if v < 0 else color for v in values]
    bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.5)
    if zero_line:
        ax.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.5)
    ax.set_title(title, color="white", fontsize=9, pad=6)
    ax.set_ylabel(ylabel, color="#aaaaaa", fontsize=7)
    ax.tick_params(colors="#aaaaaa", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")
    ax.set_facecolor("#1e1e2e")
    # value labels
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + (max(values) - min(values)) * 0.02 if v >= 0
            else bar.get_height() - (max(values) - min(values)) * 0.06,
            f"{v:.2f}", ha="center", va="bottom" if v >= 0 else "top",
            fontsize=6.5, color="white",
        )


# ─── Section builders ─────────────────────────────────────────────────────────

def sec1_regime(trades):
    """Performance by market regime."""
    buckets = ["AGGRESSIVE", "SELECTIVE", "DEFENSIVE", "UNKNOWN"]
    def key(t): return t.get("regime", "UNKNOWN")
    rows = _bucket_stats(trades, key, buckets)
    headers = ["Regime", "N", "WR%", "Avg R", "PF", "Expectancy"]
    return rows, headers


def sec2_rs(trades):
    """Performance by RS strength."""
    def key(t):
        rs = t.get("rs_score", 0.0)
        if rs < 0:      return "RS < 0"
        if rs <= 0.05:  return "RS 0–0.05"
        return "RS > 0.05"
    buckets = ["RS < 0", "RS 0–0.05", "RS > 0.05"]
    rows = _bucket_stats(trades, key, buckets)
    headers = ["RS Bucket", "N", "WR%", "Avg R", "PF", "Expectancy"]
    return rows, headers


def sec3_quality(trades):
    """Breakout quality — volume_ratio and breakout_pct buckets."""
    # Volume ratio
    def vol_key(t):
        vr = t.get("setup_meta", {}).get("volume_ratio", 0.0)
        if vr == 0.0: return "N/A"
        if vr < 1.5:  return "< 1.5×"
        if vr < 2.0:  return "1.5–2.0×"
        if vr < 3.0:  return "2.0–3.0×"
        return "≥ 3.0×"
    vol_buckets = ["< 1.5×", "1.5–2.0×", "2.0–3.0×", "≥ 3.0×", "N/A"]
    vol_rows = _bucket_stats(trades, vol_key, vol_buckets)

    # Breakout pct above resistance
    def pct_key(t):
        bp = t.get("setup_meta", {}).get("breakout_pct", None)
        if bp is None: return "N/A"
        if bp < 0.5:   return "< 0.5%"
        if bp < 1.0:   return "0.5–1.0%"
        if bp < 2.0:   return "1.0–2.0%"
        return "≥ 2.0%"
    pct_buckets = ["< 0.5%", "0.5–1.0%", "1.0–2.0%", "≥ 2.0%", "N/A"]
    pct_rows = _bucket_stats(trades, pct_key, pct_buckets)

    return vol_rows, pct_rows


def sec4_time_to_failure(trades):
    """Time-to-failure: holding days by exit reason."""
    for_stops  = [t.get("holding_days", 0) for t in trades if t.get("exit_reason") == "STOP"]
    for_target = [t.get("holding_days", 0) for t in trades if t.get("exit_reason") == "TARGET"]
    for_eod    = [t.get("holding_days", 0) for t in trades if t.get("exit_reason") == "EOD"]
    all_days   = [t.get("holding_days", 0) for t in trades]

    rows = []
    for label, group in [("STOP", for_stops), ("TARGET", for_target), ("EOD", for_eod), ("ALL", all_days)]:
        if not group:
            rows.append((label, 0, 0.0, 0.0, 0.0, 0.0))
            continue
        rows.append((
            label,
            len(group),
            round(np.mean(group), 1),
            round(np.median(group), 1),
            int(np.percentile(group, 25)),
            int(np.percentile(group, 75)),
        ))
    headers = ["Exit Reason", "N", "Avg Days", "Median", "P25", "P75"]
    return rows, headers, for_stops, for_target, for_eod


def sec5_score(trades):
    """Score distribution."""
    def key(t):
        s = t.get("final_score")
        if s is None: return "N/A"
        if s < 6:     return "5–5.9"
        if s < 7:     return "6–6.9"
        if s < 8:     return "7–7.9"
        if s < 9:     return "8–8.9"
        return "9+"
    buckets = ["5–5.9", "6–6.9", "7–7.9", "8–8.9", "9+", "N/A"]
    rows = _bucket_stats(trades, key, buckets)
    headers = ["Score Bucket", "N", "WR%", "Avg R", "PF", "Expectancy"]
    return rows, headers


def sec6_volatility(trades):
    """Volatility context — risk% as ATR proxy."""
    def key(t):
        e = t.get("entry_price", 0)
        s = t.get("initial_stop", 0) if "initial_stop" in t else t.get("stop_loss", 0)
        if e <= 0 or s <= 0: return "N/A"
        pct = (e - s) / e * 100
        if pct < 3:   return "< 3% risk"
        if pct < 5:   return "3–5% risk"
        if pct < 8:   return "5–8% risk"
        return "≥ 8% risk"
    buckets = ["< 3% risk", "3–5% risk", "5–8% risk", "≥ 8% risk", "N/A"]
    rows = _bucket_stats(trades, key, buckets)
    headers = ["Risk% Bucket", "N", "WR%", "Avg R", "PF", "Expectancy"]
    return rows, headers


def sec7_equity_curve(trades):
    """Cumulative R equity curve — chronological order."""
    sorted_trades = sorted(trades, key=lambda t: t.get("entry_date", ""))
    cum_r = np.cumsum([t.get("rr_achieved", 0.0) for t in sorted_trades])
    dates = [t.get("entry_date", "") for t in sorted_trades]
    return cum_r, dates


def sec8_entry_distance(trades):
    """Entry distance above resistance."""
    def key(t):
        bp = t.get("setup_meta", {}).get("breakout_pct", None)
        if bp is None: return "N/A"
        if bp < 0.3:   return "< 0.3%"
        if bp < 0.7:   return "0.3–0.7%"
        if bp < 1.5:   return "0.7–1.5%"
        return "≥ 1.5%"
    buckets = ["< 0.3%", "0.3–0.7%", "0.7–1.5%", "≥ 1.5%", "N/A"]
    rows = _bucket_stats(trades, key, buckets)
    headers = ["Entry Distance", "N", "WR%", "Avg R", "PF", "Expectancy"]
    return rows, headers


# ─── Main report ──────────────────────────────────────────────────────────────

def build_report(trades, out_dir="."):
    if not trades:
        print("No RES_BREAKOUT trades found.")
        return

    # Overall stats
    n        = len(trades)
    wins     = [t for t in trades if t.get("is_win")]
    losses   = [t for t in trades if not t.get("is_win")]
    wr       = len(wins) / n * 100
    avg_r    = np.mean([t.get("rr_achieved", 0.0) for t in trades])
    gross_w  = sum(t.get("rr_achieved", 0.0) for t in wins)
    gross_l  = abs(sum(t.get("rr_achieved", 0.0) for t in losses))
    pf       = gross_w / gross_l if gross_l > 0 else 0.0
    stop_pct = len([t for t in trades if t.get("exit_reason") == "STOP"]) / n * 100

    txt_path = os.path.join(out_dir, "res_breakout_diagnostic.txt")
    pdf_path = os.path.join(out_dir, "res_breakout_diagnostic.pdf")

    with open(txt_path, "w") as f:
        header = textwrap.dedent(f"""
        ╔══════════════════════════════════════════════════════════════╗
        ║          RES_BREAKOUT DIAGNOSTIC REPORT                     ║
        ╚══════════════════════════════════════════════════════════════╝

        Overall:  {n} trades  |  WR {wr:.1f}%  |  Avg R {avg_r:.3f}  |  PF {pf:.2f}
        Stops:    {stop_pct:.1f}% of trades hit stop loss
        """)
        print(header)
        f.write(header)

        # Section 1
        rows, hdrs = sec1_regime(trades)
        _print_table("§1 Performance by Market Regime", hdrs, rows, f)

        # Section 2
        rows, hdrs = sec2_rs(trades)
        _print_table("§2 Performance by RS Strength", hdrs, rows, f)

        # Section 3
        vol_rows, pct_rows = sec3_quality(trades)
        _print_table("§3a Breakout Quality — Volume Ratio", ["Vol Ratio", "N", "WR%", "Avg R", "PF", "Expectancy"], vol_rows, f)
        _print_table("§3b Breakout Quality — Close above Resistance", ["Brk Pct", "N", "WR%", "Avg R", "PF", "Expectancy"], pct_rows, f)

        # Section 4
        rows, hdrs, s, tgt, eod = sec4_time_to_failure(trades)
        _print_table("§4 Time-to-Failure Analysis", hdrs, rows, f)

        # Section 5
        rows, hdrs = sec5_score(trades)
        _print_table("§5 Score Distribution", hdrs, rows, f)

        # Section 6
        rows, hdrs = sec6_volatility(trades)
        _print_table("§6 Volatility Context (Risk% Proxy for ATR)", hdrs, rows, f)

        # Section 8
        rows, hdrs = sec8_entry_distance(trades)
        _print_table("§8 Entry Distance Above Resistance", hdrs, rows, f)

        # Section 9: Hypotheses
        sec9_text = textwrap.dedent(f"""
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          §9 Hypotheses & Parameter Suggestions
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        H1: STOP RATE TOO HIGH
            {stop_pct:.1f}% of breakout trades hit the stop.
            Stop is placed at zone_lower - 0.2×ATR — very close to resistance.
            After a breakout, price often pulls back to retest the breakout level
            before continuing. The 0.2 ATR stop allows no room for a retest.
            → SUGGESTION: Widen stop to zone_lower - 1.0×ATR or add a breakout
              retest filter (allow one day below breakout level without stopping).

        H2: ENTRY ABOVE RESISTANCE IS TOO LATE (chasing)
            Entry = breakout_bar_high × 1.001 — executed on T+1 open.
            If breakout bar was large (high volume expansion), T+1 open is
            already 2-5% above resistance. Stop is still near zone_lower.
            Risk expands while reward shrinks → R:R degrades.
            → SUGGESTION: Gate entry if T+1 open > zone_upper × 1.03
              (skip if stock gapped up too far above resistance).

        H3: LAUNCHPAD FILTER PASSES DURING MARKET PULLBACKS
            3% range tolerance in launchpad allows setups near resistance
            in declining markets. During SELECTIVE regime, breakouts fail more
            often because the broader market lacks buying support.
            → SUGGESTION: Require AGGRESSIVE regime for all RES_BREAKOUT trades
              (hard gate, not just weight — breakouts need market tailwind).

        H4: TRAILING STOP TOO WIDE (4.25 ATR)
            RES_BREAKOUT_TRAIL_ATR_MULT = 4.25 was set to "give room".
            But 205 breakout trades in a 2yr backtest suggests the setup
            fires infrequently — winners need to be captured tightly.
            For stocks that break out with high volume, 2.5–3.0 ATR trail
            is sufficient to ride the initial thrust before mean reversion.
            → SUGGESTION: Test RES_BREAKOUT_TRAIL_ATR_MULT in range 2.0–3.5.

        H5: VOLUME RATIO FLOOR TOO LOW (1.5×)
            1.5× 50-day SMA is the minimum institutional volume gate.
            In practice, high-conviction breakouts show 2–3× average volume.
            Setups at exactly 1.5× are marginal — market makers covering
            shorts, not genuine accumulation.
            → SUGGESTION: Raise BREAKOUT_VOL_MULT floor to 1.8× or make
              it Optuna-tunable between 1.5–2.5×.

        H6: breakout_weight = 1.0 MEANS BREAKOUTS GET NO SCORE BOOST
            Breakout signals get base_score × breakout_weight (=1.0).
            If score_threshold filters out only weak pullbacks, breakouts
            that just barely pass (score=5.0) still enter.
            → SUGGESTION: Raise score_threshold for breakouts specifically,
              or raise breakout_weight above 1.0 to require higher quality.
        """)
        print(sec9_text)
        f.write(sec9_text)

    print(f"\nText report saved → {txt_path}")

    # ── Charts ────────────────────────────────────────────────────────────────
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(16, 22), facecolor="#12121f")
    fig.suptitle(
        f"RES_BREAKOUT Diagnostic  |  {n} trades  |  WR {wr:.1f}%  |  Avg R {avg_r:.3f}  |  PF {pf:.2f}",
        color="white", fontsize=11, y=0.98
    )
    gs = gridspec.GridSpec(4, 3, figure=fig, hspace=0.55, wspace=0.35,
                           top=0.94, bottom=0.04, left=0.07, right=0.97)

    # §1 Regime
    r1, _ = sec1_regime(trades)
    ax1 = fig.add_subplot(gs[0, 0])
    labels = [r[0] for r in r1 if r[1] > 0]
    vals   = [r[3] for r in r1 if r[1] > 0]
    _bar_chart(ax1, labels, vals, "§1 Avg R by Regime", "Avg R")

    # §2 RS
    r2, _ = sec2_rs(trades)
    ax2 = fig.add_subplot(gs[0, 1])
    labels = [r[0] for r in r2 if r[1] > 0]
    vals   = [r[3] for r in r2 if r[1] > 0]
    _bar_chart(ax2, labels, vals, "§2 Avg R by RS Bucket", "Avg R")

    # §3 Volume
    vol_rows, pct_rows = sec3_quality(trades)
    ax3 = fig.add_subplot(gs[0, 2])
    labels = [r[0] for r in vol_rows if r[1] > 0]
    vals   = [r[3] for r in vol_rows if r[1] > 0]
    _bar_chart(ax3, labels, vals, "§3a Avg R by Volume Ratio", "Avg R")

    # §3b Breakout pct
    ax3b = fig.add_subplot(gs[1, 0])
    labels = [r[0] for r in pct_rows if r[1] > 0]
    vals   = [r[3] for r in pct_rows if r[1] > 0]
    _bar_chart(ax3b, labels, vals, "§3b Avg R by Breakout Distance", "Avg R")

    # §4 Holding days histogram
    ax4 = fig.add_subplot(gs[1, 1])
    _, _, s_days, t_days, e_days = sec4_time_to_failure(trades)
    ax4.set_facecolor("#1e1e2e")
    ax4.set_title("§4 Holding Days by Exit", color="white", fontsize=9, pad=6)
    if s_days:  ax4.hist(s_days, bins=20, alpha=0.7, color="tomato",    label=f"STOP ({len(s_days)})")
    if t_days:  ax4.hist(t_days, bins=20, alpha=0.7, color="limegreen", label=f"TARGET ({len(t_days)})")
    if e_days:  ax4.hist(e_days, bins=20, alpha=0.7, color="skyblue",   label=f"EOD ({len(e_days)})")
    ax4.legend(fontsize=7, facecolor="#1e1e2e", labelcolor="white")
    ax4.tick_params(colors="#aaaaaa", labelsize=7)
    for spine in ax4.spines.values(): spine.set_edgecolor("#444444")

    # §5 Score
    r5, _ = sec5_score(trades)
    ax5 = fig.add_subplot(gs[1, 2])
    labels = [r[0] for r in r5 if r[1] > 0]
    vals   = [r[3] for r in r5 if r[1] > 0]
    _bar_chart(ax5, labels, vals, "§5 Avg R by Score Bucket", "Avg R")

    # §6 Volatility
    r6, _ = sec6_volatility(trades)
    ax6 = fig.add_subplot(gs[2, 0])
    labels = [r[0] for r in r6 if r[1] > 0]
    vals   = [r[3] for r in r6 if r[1] > 0]
    _bar_chart(ax6, labels, vals, "§6 Avg R by Risk% (Volatility Proxy)", "Avg R")

    # §8 Entry distance
    r8, _ = sec8_entry_distance(trades)
    ax8 = fig.add_subplot(gs[2, 1])
    labels = [r[0] for r in r8 if r[1] > 0]
    vals   = [r[3] for r in r8 if r[1] > 0]
    _bar_chart(ax8, labels, vals, "§8 Avg R by Entry Distance", "Avg R")

    # Win rate companion
    ax8b = fig.add_subplot(gs[2, 2])
    labels = [r[0] for r in r8 if r[1] > 0]
    vals   = [r[2] for r in r8 if r[1] > 0]  # WR%
    _bar_chart(ax8b, labels, vals, "§8b WR% by Entry Distance", "WR%", color="#7ec8e3", zero_line=False)

    # §7 Equity curve
    ax7 = fig.add_subplot(gs[3, :])
    cum_r, dates = sec7_equity_curve(trades)
    ax7.set_facecolor("#1e1e2e")
    ax7.plot(range(len(cum_r)), cum_r, color="steelblue", linewidth=1.2, label="Cumulative R")
    ax7.fill_between(range(len(cum_r)), cum_r, 0,
                     where=cum_r >= 0, alpha=0.15, color="limegreen")
    ax7.fill_between(range(len(cum_r)), cum_r, 0,
                     where=cum_r < 0, alpha=0.25, color="tomato")
    ax7.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.5)
    ax7.set_title(f"§7 RES_BREAKOUT Equity Curve ({n} trades, cumulative R)",
                  color="white", fontsize=9, pad=6)
    ax7.set_xlabel("Trade #", color="#aaaaaa", fontsize=8)
    ax7.set_ylabel("Cumulative R", color="#aaaaaa", fontsize=8)
    ax7.tick_params(colors="#aaaaaa", labelsize=7)
    for spine in ax7.spines.values(): spine.set_edgecolor("#444444")

    # x-axis: sample date labels
    if dates:
        step = max(1, len(dates) // 8)
        ticks = list(range(0, len(dates), step))
        ax7.set_xticks(ticks)
        ax7.set_xticklabels([dates[i] for i in ticks], rotation=30, ha="right", fontsize=6)

    plt.savefig(pdf_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"Chart report saved  → {pdf_path}")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RES_BREAKOUT diagnostic report")
    parser.add_argument("--cache", default=DEFAULT_CACHE,
                        help="Path to backtest_diagnostics.json cache file")
    parser.add_argument("--out", default=".",
                        help="Output directory for report files")
    args = parser.parse_args()

    trades = load_trades(os.path.normpath(args.cache))
    build_report(trades, out_dir=args.out)
