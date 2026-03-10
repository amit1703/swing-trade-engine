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

from typing import Any

LOW_SAMPLE_THRESHOLD = 20   # warn when a setup type has fewer than this many trades


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
    Buckets: AGGRESSIVE (>=70), SELECTIVE (40-69), DEFENSIVE (<40), UNKNOWN (None).
    """
    buckets: dict = {
        "AGGRESSIVE": [],
        "SELECTIVE":  [],
        "DEFENSIVE":  [],
        "UNKNOWN":    [],
    }

    for t in trades:
        rs = t.get("regime_score")
        if rs is None:
            buckets["UNKNOWN"].append(t)
        elif rs >= 70:
            buckets["AGGRESSIVE"].append(t)
        elif rs >= 40:
            buckets["SELECTIVE"].append(t)
        else:
            buckets["DEFENSIVE"].append(t)

    result = {}
    for label, group in buckets.items():
        if not group:
            continue
        m = compute_live_diagnostics(group)
        result[label] = {
            "trades":     m["total_trades"],
            "win_rate":   m["win_rate"],
            "avg_R":      m["avg_R"],
            "expectancy": m["expectancy"],
        }

    return result
