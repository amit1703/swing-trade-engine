"""
analytics.py — Pure strategy diagnostics functions.

All functions accept a list of trade dicts and return computed metrics.
No imports from database.py, main.py, or FastAPI — this module is
intentionally decoupled so a future backtest engine can pass simulated
trade records into the same interface.

Trade dict shape (minimum required keys):
    ticker        : str
    setup_type    : str   ("VCP" | "PULLBACK" | "RES_BREAKOUT" | "BASE" | ...)
    entry_price   : float
    stop_loss     : float
    close_price   : float | None   (None for open trades; use exit_price mapped to close_price)
    status        : str   ("closed" | "active" | "CLOSED" | "OPEN")
    regime_score  : int | None
"""

from constants import LOW_SAMPLE_THRESHOLD


def _is_closed(trade: dict) -> bool:
    """Return True for any trade status that means realized P/L is available."""
    s = str(trade.get("status", "")).lower()
    return s == "closed" and trade.get("close_price") is not None


def _r_multiple(trade: dict) -> float | None:
    """
    Compute the realized R-multiple for a closed trade.
    R = (exit - entry) / (entry - stop)
    Returns None if risk is zero or data is missing.
    """
    try:
        entry = float(trade["entry_price"])
        stop  = float(trade["stop_loss"])
        exit_ = float(trade["close_price"])
        risk  = entry - stop
        if risk <= 0:
            return None
        return (exit_ - entry) / risk
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _max_drawdown(cumulative_rs: list) -> float:
    """Peak-to-trough drawdown in the cumulative R sequence. Returns 0.0 if empty."""
    if not cumulative_rs:
        return 0.0
    peak = cumulative_rs[0]
    max_dd = 0.0
    for v in cumulative_rs:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def compute_live_diagnostics(trades: list) -> dict:
    """
    Compute summary performance metrics from a list of trade dicts.
    Open trades (status != 'closed') are silently excluded.

    Returns
    -------
    {
        total_trades   : int,
        profit_factor  : float | None,   # None if no losing trades
        win_rate       : float,
        avg_R          : float,
        expectancy     : float,
        max_drawdown   : float,          # <= 0
        equity_curve_R : list[float],    # cumulative R for charting
    }
    """
    closed_r = []
    for t in trades:
        if _is_closed(t):
            r = _r_multiple(t)
            if r is not None:
                closed_r.append(r)

    if not closed_r:
        return {
            "total_trades":   0,
            "profit_factor":  None,
            "win_rate":       0.0,
            "avg_R":          0.0,
            "expectancy":     0.0,
            "max_drawdown":   0.0,
            "equity_curve_R": [],
        }

    wins   = [r for r in closed_r if r > 0]
    losses = [r for r in closed_r if r <= 0]

    win_rate      = len(wins) / len(closed_r)
    avg_R         = sum(closed_r) / len(closed_r)
    avg_win_R     = sum(wins)   / len(wins)   if wins   else 0.0
    avg_loss_R    = sum(losses) / len(losses) if losses else 0.0
    expectancy    = win_rate * avg_win_R + (1 - win_rate) * avg_loss_R
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else None

    cumulative = 0.0
    equity_curve = []
    for r in closed_r:
        cumulative += r
        equity_curve.append(round(cumulative, 4))

    return {
        "total_trades":   len(closed_r),
        "profit_factor":  round(profit_factor, 3) if profit_factor is not None else None,
        "win_rate":       round(win_rate, 4),
        "avg_R":          round(avg_R, 4),
        "expectancy":     round(expectancy, 4),
        "max_drawdown":   round(_max_drawdown(equity_curve), 4),
        "equity_curve_R": equity_curve,
    }


def compute_setup_breakdown(trades: list) -> dict:
    """
    Break down performance metrics by setup_type.
    Returns a dict keyed by setup_type, each value matching compute_live_diagnostics
    plus a 'low_sample' bool flag.
    """
    by_type: dict = {}
    for t in trades:
        if not _is_closed(t):
            continue
        stype = str(t.get("setup_type", "UNKNOWN")).upper()
        by_type.setdefault(stype, []).append(t)

    result = {}
    for stype, group in by_type.items():
        metrics = compute_live_diagnostics(group)
        metrics["low_sample"] = len(group) < LOW_SAMPLE_THRESHOLD
        result[stype] = metrics

    return result


def compute_ticker_distribution(trades: list) -> list:
    """
    Aggregate realized R-multiples by ticker.
    Returns a list sorted descending by abs(total_pnl).
    """
    by_ticker: dict = {}
    for t in trades:
        if not _is_closed(t):
            continue
        r = _r_multiple(t)
        if r is None:
            continue
        ticker = str(t.get("ticker", "UNKNOWN")).upper()
        by_ticker.setdefault(ticker, []).append(r)

    total_abs = sum(abs(sum(rs)) for rs in by_ticker.values()) or 1.0

    rows = []
    for ticker, rs in by_ticker.items():
        total_pnl = sum(rs)
        rows.append({
            "ticker":           ticker,
            "trade_count":      len(rs),
            "total_pnl":        round(total_pnl, 4),
            "pct_contribution": round(total_pnl / total_abs * 100, 2),
        })

    rows.sort(key=lambda x: abs(x["total_pnl"]), reverse=True)
    return rows


def compute_regime_performance(trades: list) -> dict:
    """
    Performance metrics bucketed by market regime at trade entry.
    Buckets: AGGRESSIVE, SELECTIVE, DEFENSIVE, UNKNOWN — matched from trade's 'regime' field.
    """
    buckets: dict = {
        "AGGRESSIVE": [],
        "SELECTIVE":  [],
        "DEFENSIVE":  [],
        "UNKNOWN":    [],
    }

    for t in trades:
        label = str(t.get("regime", "UNKNOWN")).upper()
        if label not in buckets:
            label = "UNKNOWN"
        buckets[label].append(t)

    result = {}
    for label, group in buckets.items():
        if not group:
            result[label] = None   # empty bucket — no trades in this regime tier
            continue
        m = compute_live_diagnostics(group)
        result[label] = {
            "trades":     m["total_trades"],
            "win_rate":   m["win_rate"],
            "avg_R":      m["avg_R"],
            "expectancy": m["expectancy"],
        }

    return result


def _suggest_weight(expectancy: float, count: int, min_sample: int) -> float:
    """
    Suggest a SELECTIVE_SETUP_WEIGHTS value based on expectancy and sample size.
    Returns 1.0 for insufficient data (don't penalise what you can't measure).
    """
    if count < min_sample:
        return 1.0   # insufficient data — no penalty
    if expectancy >= 0.25:
        return 1.0   # strong edge — no penalty
    if expectancy >= 0.10:
        return 0.8   # moderate edge — light penalty
    if expectancy >= 0.0:
        return 0.5   # near-breakeven — meaningful penalty
    return 0.2       # negative expectancy — heavy penalty (hard-block if SELECTIVE_HARD_FILTER)


def compute_selective_breakdown(trades: list) -> dict:
    """
    Analyse performance by setup type within the SELECTIVE regime only.

    Classifies each setup as STRONG / WEAK / INSUFFICIENT_DATA and provides:
      - per-setup metrics table
      - before/after simulation (all vs STRONG-only SELECTIVE trades)
      - suggested SELECTIVE_SETUP_WEIGHTS values for constants.py

    Parameters
    ----------
    trades : list of trade dicts with keys regime, setup_type, close_price,
             entry_price, stop_loss, status (analytics.py contract)

    Returns
    -------
    dict with keys:
        total_selective_trades   : int
        setup_breakdown          : dict[setup_type → metrics + classification]
        before                   : overall SELECTIVE metrics (no filter)
        after_simulated          : SELECTIVE metrics for STRONG setups only
        strong_setups            : list[str]
        weak_setups              : list[str]
        insufficient_data_setups : list[str]
        suggested_weights        : dict[setup_type → float]  — paste into constants.py
    """
    from constants import SELECTIVE_MIN_SAMPLE, SELECTIVE_EXPECTANCY_FLOOR

    selective = [
        t for t in trades
        if str(t.get("regime", "")).upper() == "SELECTIVE" and _is_closed(t)
    ]

    _empty = {
        "total_selective_trades":   0,
        "setup_breakdown":          {},
        "before":                   None,
        "after_simulated":          None,
        "strong_setups":            [],
        "weak_setups":              [],
        "insufficient_data_setups": [],
        "suggested_weights":        {},
    }

    if not selective:
        return _empty

    # Group by setup_type
    by_setup: dict = {}
    for t in selective:
        stype = str(t.get("setup_type", "UNKNOWN")).upper()
        by_setup.setdefault(stype, []).append(t)

    breakdown: dict = {}
    for stype, group in by_setup.items():
        m = compute_live_diagnostics(group)
        count = m["total_trades"]
        exp   = m["expectancy"]

        if count < SELECTIVE_MIN_SAMPLE:
            classification = "INSUFFICIENT_DATA"
        elif exp > SELECTIVE_EXPECTANCY_FLOOR:
            classification = "STRONG"
        else:
            classification = "WEAK"

        breakdown[stype] = {
            **m,
            "count":          count,
            "classification": classification,
            "suggested_weight": _suggest_weight(exp, count, SELECTIVE_MIN_SAMPLE),
        }

    # Classify buckets
    strong     = sorted(k for k, v in breakdown.items() if v["classification"] == "STRONG")
    weak       = sorted(k for k, v in breakdown.items() if v["classification"] == "WEAK")
    insuf      = sorted(k for k, v in breakdown.items() if v["classification"] == "INSUFFICIENT_DATA")

    # Before: all SELECTIVE trades (no filter)
    before = compute_live_diagnostics(selective)

    # After (simulated): only STRONG setups
    after_trades = [t for t in selective if str(t.get("setup_type", "")).upper() in set(strong)]
    after = compute_live_diagnostics(after_trades) if after_trades else None

    # Suggested weights: STRONG=weight, WEAK=weight, INSUFFICIENT_DATA=1.0
    suggested_weights = {
        k: v["suggested_weight"] for k, v in breakdown.items()
    }

    return {
        "total_selective_trades":   len(selective),
        "setup_breakdown":          breakdown,
        "before":                   before,
        "after_simulated":          after,
        "strong_setups":            strong,
        "weak_setups":              weak,
        "insufficient_data_setups": insuf,
        "suggested_weights":        suggested_weights,
    }


def compute_regime_stability(regime_history: list) -> dict:
    """
    Measure regime stability from a list of {scan_timestamp, regime} dicts
    ordered ascending by scan_timestamp (as returned by get_regime_history).

    A flip is counted only when a new regime persists for >= 2 consecutive
    scans — single-scan interludes are treated as noise and not counted.

    Parameters
    ----------
    regime_history : list of dicts with keys scan_timestamp (str), regime (str)

    Returns
    -------
    dict with keys:
        total_scans              : int
        flip_count               : int   — meaningful regime changes
        flip_rate_per_month      : float — flips per 30-day period
        avg_regime_duration_days : float — mean days per stable regime period
        distribution             : dict  — {AGGRESSIVE, SELECTIVE, DEFENSIVE} counts
        date_range_days          : int   — days from first to last scan
    """
    from datetime import datetime as _dt

    _empty = {
        "total_scans":               0,
        "flip_count":                0,
        "flip_rate_per_month":       0.0,
        "avg_regime_duration_days":  0.0,
        "distribution":              {"AGGRESSIVE": 0, "SELECTIVE": 0, "DEFENSIVE": 0},
        "date_range_days":           0,
    }

    if not regime_history:
        return _empty

    labels     = [r.get("regime", "UNKNOWN") for r in regime_history]
    timestamps = [r.get("scan_timestamp", "")[:10] for r in regime_history]

    # Distribution count (only the three meaningful labels)
    dist = {"AGGRESSIVE": 0, "SELECTIVE": 0, "DEFENSIVE": 0}
    for label in labels:
        if label in dist:
            dist[label] += 1

    # Date range: first scan → last scan
    date_range_days = 0
    try:
        t0 = _dt.fromisoformat(timestamps[0])
        t1 = _dt.fromisoformat(timestamps[-1])
        date_range_days = max(1, (t1 - t0).days)
    except Exception:
        date_range_days = len(labels)

    # Build run-length encoding: [(regime, start_idx, end_idx), ...]
    runs: list = []
    i = 0
    while i < len(labels):
        j = i + 1
        while j < len(labels) and labels[j] == labels[i]:
            j += 1
        runs.append((labels[i], i, j - 1))
        i = j

    # Count flips: transition run[k] → run[k+1] is a flip only if run[k+1]
    # has length >= 2 (ignores single-scan noise blips).
    flip_count = sum(
        1 for k in range(1, len(runs))
        if (runs[k][2] - runs[k][1] + 1) >= 2
    )

    # Compute duration for each run in calendar days.
    # Duration of run k = start of run k+1 − start of run k.
    # Last run: last timestamp − start of last run (or 1 day minimum).
    durations: list = []
    for k, (_regime, start, end) in enumerate(runs):
        try:
            d_start = _dt.fromisoformat(timestamps[start])
            if k + 1 < len(runs):
                d_next = _dt.fromisoformat(timestamps[runs[k + 1][1]])
                dur = max(1, (d_next - d_start).days)
            else:
                d_end = _dt.fromisoformat(timestamps[end])
                dur = max(1, (d_end - d_start).days) if start != end else 1
            durations.append(dur)
        except Exception:
            durations.append(1)

    avg_regime_duration_days = (
        round(sum(durations) / len(durations), 1) if durations else 0.0
    )
    flip_rate_per_month = (
        round(flip_count / date_range_days * 30, 2) if date_range_days > 0 else 0.0
    )

    return {
        "total_scans":               len(regime_history),
        "flip_count":                flip_count,
        "flip_rate_per_month":       flip_rate_per_month,
        "avg_regime_duration_days":  avg_regime_duration_days,
        "distribution":              dist,
        "date_range_days":           date_range_days,
    }


def print_backtest_diagnostics(trades: list) -> str:
    """
    Format a human-readable diagnostics summary for a completed backtest run.

    Accepts a flat list of TradeRecord.to_dict() dicts (as returned by
    run_backtest_universe). Returns a multi-line string suitable for logging.

    Sections:
    - Overall: trade count, win rate, expectancy (avg R), profit factor
    - Per setup_type breakdown
    - Score distribution (only when final_score is populated — scored mode)
    """
    sep = "═" * 44

    if not trades:
        return f"{sep}\n BACKTEST DIAGNOSTICS\n{sep}\n No trades generated.\n{sep}"

    wins        = [t for t in trades if t.get("is_win")]
    win_rate    = len(wins) / len(trades) * 100
    rr_values   = [t["rr_achieved"] for t in trades if t.get("rr_achieved") is not None]
    avg_rr      = sum(rr_values) / len(rr_values) if rr_values else 0.0

    gross_pos   = sum(r for r in rr_values if r > 0)
    gross_neg   = sum(r for r in rr_values if r <= 0)
    profit_factor = (gross_pos / abs(gross_neg)) if gross_neg != 0 else float("inf")

    lines = [
        sep,
        " BACKTEST DIAGNOSTICS",
        sep,
        f" Total trades        : {len(trades):>7,}",
        f" Win rate            : {win_rate:>7.1f}%",
        f" Expectancy (avg R)  : {avg_rr:>+7.2f} R",
        f" Profit factor       : {profit_factor:>7.2f}",
        "",
        " Signal type breakdown:",
    ]

    by_type: dict = {}
    for t in trades:
        st = str(t.get("setup_type", "UNKNOWN")).upper()
        by_type.setdefault(st, []).append(t)

    for st in sorted(by_type):
        group   = by_type[st]
        g_wins  = [t for t in group if t.get("is_win")]
        g_rr    = [t["rr_achieved"] for t in group if t.get("rr_achieved") is not None]
        g_wr    = len(g_wins) / len(group) * 100 if group else 0.0
        g_avg_r = sum(g_rr) / len(g_rr) if g_rr else 0.0
        pct     = len(group) / len(trades) * 100
        lines.append(
            f"   {st:<14} : {len(group):>5,}  ({pct:4.1f}%)  "
            f"win {g_wr:.1f}%  avg R {g_avg_r:+.2f}"
        )

    # Score section — only when final_score is populated (scored mode)
    scores = [t["final_score"] for t in trades if t.get("final_score") is not None]
    if scores:
        lines += [
            "",
            " Score distribution (scored mode):",
            f"   avg final score   : {sum(scores)/len(scores):>6.2f}",
            f"   min / max score   : {min(scores):.1f} / {max(scores):.1f}",
        ]

    lines.append(sep)
    return "\n".join(lines)
