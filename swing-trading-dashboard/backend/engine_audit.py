"""
engine_audit.py — Per-engine diagnostic audit of WFO trade records.

Pure analytics: accepts a flat list of raw trade dicts (from WFO result JSON)
and produces a structured audit report covering engine-level metrics, quality
diagnostics, structural diagnostics, failure analysis, and pattern quality
per setup_type.

No strategy logic is modified. This is a read-only diagnostic layer.

Entry point
-----------
  run_audit(trades, period_label) -> dict
"""

import math
import statistics
from typing import Dict, List, Optional

ALL_ENGINES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]

# Minimum trades for a report section to be considered statistically reliable.
_MIN_RELIABLE = 15

# Classification thresholds
_ROBUST_WIN_RATE   = 50.0   # %
_ROBUST_EXPECTANCY = 0.20   # R
_ROBUST_AVG_R      = 0.10   # R
_WEAK_WIN_RATE     = 38.0   # %
_UNDER_TRIG_RATIO  = 0.25   # engine trade count < 25% of median → under-triggered
_OVER_STOP_RATE    = 62.0   # % stop exits → suggests under-filtering


# ─────────────────────────────────────────────────────────────────────────────
# Numeric helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mean(values: List[float]) -> float:
    return statistics.mean(values) if values else 0.0

def _median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0

def _safe(v: float, digits: int = 3) -> float:
    """Round, converting nan/inf to 0.0."""
    if v is None or math.isnan(v) or math.isinf(v):
        return 0.0
    return round(v, digits)

def _pct(num: int, denom: int) -> float:
    return _safe(num / denom * 100, 1) if denom > 0 else 0.0

def _r_buckets(rr_vals: List[float]) -> Dict[str, int]:
    """Count trades falling in each R-multiple bucket."""
    b = {"lt_neg1": 0, "neg1_to_0": 0, "zero_to_1": 0, "one_to_2": 0, "gt_2": 0}
    for r in rr_vals:
        if   r < -1.0: b["lt_neg1"]   += 1
        elif r <  0.0: b["neg1_to_0"] += 1
        elif r <  1.0: b["zero_to_1"] += 1
        elif r <  2.0: b["one_to_2"]  += 1
        else:          b["gt_2"]       += 1
    return b


# ─────────────────────────────────────────────────────────────────────────────
# Per-engine audit
# ─────────────────────────────────────────────────────────────────────────────

def _audit_engine(engine: str, trades: List[Dict]) -> Dict:
    n = len(trades)

    if n == 0:
        return {
            "engine": engine, "sufficient_data": False,
            "engine_level": {"trades_executed": 0, "win_count": 0, "loss_count": 0,
                             "win_rate": 0.0, "avg_R": 0.0, "expectancy": 0.0,
                             "avg_trade_return_pct": 0.0, "net_profit_pct": 0.0,
                             "profit_factor": 0.0},
            "quality": {"avg_R_winners": 0.0, "avg_R_losers": 0.0,
                        "largest_winner_R": 0.0, "largest_loser_R": 0.0,
                        "median_R": 0.0, "r_distribution": _r_buckets([])},
            "structural": {"avg_holding_days": 0.0, "avg_holding_winners": 0.0,
                           "avg_holding_losers": 0.0, "avg_risk_pct": 0.0,
                           "avg_planned_rr": 0.0},
            "exit_breakdown": {"pct_stop_exits": 0.0, "pct_target_hits": 0.0,
                               "pct_eod_exits": 0.0, "count_stops": 0,
                               "count_targets": 0, "count_eod": 0},
            "failure_analysis": {"pct_failed_breakouts": 0.0,
                                 "pct_immediate_reversals": 0.0,
                                 "pct_quick_stops_5d": 0.0,
                                 "count_failed_breakouts": 0,
                                 "count_immediate_reversals": 0},
            "pattern_quality": {"target_hit_rate": 0.0, "avg_risk_pct": 0.0,
                                "avg_planned_rr": 0.0, "wins_via_target": 0,
                                "wins_via_eod": 0},
        }

    wins   = [t for t in trades if t.get("is_win")]
    losses = [t for t in trades if not t.get("is_win")]

    rr_all  = [t["rr_achieved"] for t in trades]
    rr_win  = [t["rr_achieved"] for t in wins]
    rr_loss = [t["rr_achieved"] for t in losses]
    pnl     = [t["pnl_pct"]    for t in trades]

    win_rate   = _pct(len(wins), n)
    avg_r      = _safe(_mean(rr_all))
    avg_win_r  = _safe(_mean(rr_win))
    avg_loss_r = _safe(_mean(rr_loss))

    # Expectancy = weighted avg R (loss_r already negative)
    wr_frac = len(wins)   / n
    lr_frac = len(losses) / n
    expectancy = _safe(wr_frac * avg_win_r + lr_frac * avg_loss_r)

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss   = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = _safe(
        min(gross_profit / gross_loss, 9999.0) if gross_loss > 0
        else (9999.0 if gross_profit > 0 else 0.0)
    )

    # ── Structural ────────────────────────────────────────────────────────────
    hold_all    = [t["holding_days"] for t in trades]
    hold_wins   = [t["holding_days"] for t in wins]
    hold_losses = [t["holding_days"] for t in losses]

    risk_pcts: List[float] = []
    planned_rrs: List[float] = []
    for t in trades:
        entry = t.get("entry_price", 0)
        stop  = t.get("initial_stop", 0)
        tp    = t.get("take_profit", 0)
        if entry > 0 and entry > stop > 0:
            risk = entry - stop
            risk_pcts.append(risk / entry * 100)
            if risk > 0:
                planned_rrs.append((tp - entry) / risk)

    avg_risk_pct  = _safe(_mean(risk_pcts), 2)
    avg_planned_rr = _safe(_mean(planned_rrs), 2)

    # ── Exit reason breakdown ─────────────────────────────────────────────────
    stops   = [t for t in trades if t.get("exit_reason") == "STOP"]
    targets = [t for t in trades if t.get("exit_reason") == "TARGET"]
    eods    = [t for t in trades if t.get("exit_reason") == "EOD"]

    # ── Failure analysis (on losing trades) ───────────────────────────────────
    # Failed breakouts: stopped out (reversed after entry)
    failed_bkts = [t for t in losses if t.get("exit_reason") == "STOP"]
    # Immediate reversals: loss closed within 3 bars
    immediate   = [t for t in losses if t.get("holding_days", 999) <= 3]
    # Quick stops: loss closed within 5 bars
    quick_stops = [t for t in losses if t.get("holding_days", 999) <= 5]

    # ── Pattern quality ───────────────────────────────────────────────────────
    wins_via_target = [t for t in targets if t.get("is_win")]
    wins_via_eod    = [t for t in eods    if t.get("is_win")]

    return {
        "engine":          engine,
        "sufficient_data": n >= _MIN_RELIABLE,

        # ── ENGINE LEVEL ──────────────────────────────────────────────────────
        "engine_level": {
            "trades_executed":       n,
            "win_count":             len(wins),
            "loss_count":            len(losses),
            "win_rate":              win_rate,
            "avg_R":                 avg_r,
            "expectancy":            expectancy,
            "avg_trade_return_pct":  _safe(_mean(pnl), 2),
            "net_profit_pct":        _safe(sum(pnl), 2),
            "profit_factor":         profit_factor,
        },

        # ── QUALITY DIAGNOSTICS ───────────────────────────────────────────────
        "quality": {
            "avg_R_winners":    avg_win_r,
            "avg_R_losers":     avg_loss_r,
            "largest_winner_R": _safe(max(rr_win)  if rr_win  else 0.0),
            "largest_loser_R":  _safe(min(rr_loss) if rr_loss else 0.0),
            "median_R":         _safe(_median(rr_all)),
            "r_distribution":   _r_buckets(rr_all),
        },

        # ── STRUCTURAL DIAGNOSTICS ────────────────────────────────────────────
        "structural": {
            "avg_holding_days":     _safe(_mean(hold_all), 1),
            "avg_holding_winners":  _safe(_mean(hold_wins), 1),
            "avg_holding_losers":   _safe(_mean(hold_losses), 1),
            "avg_risk_pct":         avg_risk_pct,
            "avg_planned_rr":       avg_planned_rr,
        },

        # ── EXIT BREAKDOWN ────────────────────────────────────────────────────
        "exit_breakdown": {
            "pct_stop_exits":  _pct(len(stops),   n),
            "pct_target_hits": _pct(len(targets), n),
            "pct_eod_exits":   _pct(len(eods),    n),
            "count_stops":     len(stops),
            "count_targets":   len(targets),
            "count_eod":       len(eods),
        },

        # ── FAILURE ANALYSIS ──────────────────────────────────────────────────
        "failure_analysis": {
            "pct_failed_breakouts":    _pct(len(failed_bkts), len(losses)),
            "pct_immediate_reversals": _pct(len(immediate),   len(losses)),
            "pct_quick_stops_5d":      _pct(len(quick_stops), len(losses)),
            "count_failed_breakouts":   len(failed_bkts),
            "count_immediate_reversals": len(immediate),
        },

        # ── PATTERN QUALITY ───────────────────────────────────────────────────
        "pattern_quality": {
            "target_hit_rate":  _pct(len(targets),        n),
            "avg_risk_pct":     avg_risk_pct,
            "avg_planned_rr":   avg_planned_rr,
            "wins_via_target":  len(wins_via_target),
            "wins_via_eod":     len(wins_via_eod),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────────────────────────────────────

def _classify_engines(reports: Dict[str, Dict]) -> Dict[str, str]:
    """
    Assign one of: robust | neutral | weak | under-filtered |
                   under-triggered | insufficient_data | no_data
    """
    trade_counts = [r["engine_level"]["trades_executed"] for r in reports.values()]
    median_count = _median([c for c in trade_counts if c > 0]) if any(c > 0 for c in trade_counts) else 1

    result: Dict[str, str] = {}
    for engine, r in reports.items():
        n = r["engine_level"]["trades_executed"]

        if n == 0:
            result[engine] = "no_data"
            continue
        if n < _MIN_RELIABLE:
            result[engine] = "insufficient_data"
            continue

        wr        = r["engine_level"]["win_rate"]
        exp       = r["engine_level"]["expectancy"]
        avg_r     = r["engine_level"]["avg_R"]
        pct_stops = r["exit_breakdown"]["pct_stop_exits"]

        if wr >= _ROBUST_WIN_RATE and exp >= _ROBUST_EXPECTANCY and avg_r >= _ROBUST_AVG_R:
            label = "robust"
        elif exp < 0 or wr < _WEAK_WIN_RATE:
            label = "weak"
        elif n < median_count * _UNDER_TRIG_RATIO:
            label = "under-triggered"
        elif wr < 45 and pct_stops > _OVER_STOP_RATE:
            label = "under-filtered"
        else:
            label = "neutral"

        result[engine] = label

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic summaries
# ─────────────────────────────────────────────────────────────────────────────

def _engine_diagnosis(engine: str, r: Dict, cls: str) -> str:
    n   = r["engine_level"]["trades_executed"]
    wr  = r["engine_level"]["win_rate"]
    exp = r["engine_level"]["expectancy"]
    avg_r = r["engine_level"]["avg_R"]
    pct_imm  = r["failure_analysis"]["pct_immediate_reversals"]
    pct_fail = r["failure_analysis"]["pct_failed_breakouts"]
    pct_stop = r["exit_breakdown"]["pct_stop_exits"]
    pct_tgt  = r["exit_breakdown"]["pct_target_hits"]
    hold     = r["structural"]["avg_holding_days"]
    risk_pct = r["structural"]["avg_risk_pct"]
    planned  = r["structural"]["avg_planned_rr"]

    if cls == "no_data":
        return f"{engine}: No trades generated. Engine produced zero signals — check data coverage or entry filters."

    if cls == "insufficient_data":
        return f"{engine}: Only {n} trade(s) — below {_MIN_RELIABLE} needed for reliable conclusions. Expand test window or add more tickers."

    if cls == "robust":
        return (
            f"{engine}: Performing well ({wr:.0f}% WR, {exp:+.2f}R expectancy). "
            f"Target hit rate {pct_tgt:.0f}%, avg hold {hold:.0f}d. "
            f"Parameters appear well-calibrated."
        )

    parts = [f"{engine}: "]

    if exp < 0:
        parts.append(f"Negative expectancy ({exp:+.2f}R) — edge is absent.")
    elif exp < 0.10:
        parts.append(f"Near-zero expectancy ({exp:+.2f}R) — edge is weak.")

    if wr < _WEAK_WIN_RATE:
        parts.append(f"Win rate low at {wr:.0f}%.")

    if pct_imm > 30:
        parts.append(
            f"{pct_imm:.0f}% of losses reverse within 3 bars — entries may be premature "
            f"(chasing vs. waiting for confirmation)."
        )
    elif pct_fail > 60:
        parts.append(
            f"{pct_fail:.0f}% of losses are straight stop-outs — "
            f"breakout quality is weak or stop is too tight (avg risk {risk_pct:.1f}%)."
        )

    if pct_stop > _OVER_STOP_RATE and wr < 45:
        parts.append(
            f"High stop-out rate ({pct_stop:.0f}%) with sub-50% win rate "
            f"suggests entry filter is too loose."
        )

    if pct_tgt < 20 and n >= _MIN_RELIABLE:
        parts.append(
            f"Only {pct_tgt:.0f}% of trades hit target — "
            f"take-profit may be too aggressive or trend continuation is weak."
        )

    if hold > 30:
        parts.append(f"Avg holding {hold:.0f}d is long — consider tighter trailing stop criteria.")
    elif hold < 5 and n >= _MIN_RELIABLE:
        parts.append(f"Avg holding only {hold:.0f}d — trades are being cut very quickly.")

    if planned > 0 and planned < 1.5:
        parts.append(f"Planned R:R is only {planned:.1f}:1 — structural edge is limited before filters.")

    if cls == "under-triggered":
        parts.append(f"Signal count ({n}) is far below other engines — entry conditions may be over-restrictive.")

    if len(parts) == 1:
        parts.append(f"Win rate {wr:.0f}%, expectancy {exp:+.2f}R. No critical issues detected.")

    return " ".join(parts)


def _generate_summary(reports: Dict[str, Dict], classifications: Dict[str, str]) -> Dict[str, str]:
    return {
        engine: _engine_diagnosis(engine, r, classifications.get(engine, "insufficient_data"))
        for engine, r in reports.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_audit(trades: List[Dict], period_label: str = "OOS") -> Dict:
    """
    Run full per-engine diagnostic audit.

    Parameters
    ----------
    trades       : flat list of TradeRecord.to_dict() dicts
    period_label : "IS", "OOS", or "ALL" — label only, affects no logic

    Returns
    -------
    {
      "period"          : str,
      "total_trades"    : int,
      "by_engine"       : { engine: AuditReport },
      "classifications" : { engine: label_str },
      "summary"         : { engine: diagnosis_str },
      "engine_order"    : [engines sorted by trade count desc],
      "overall"         : { win_rate, expectancy, avg_R, ... }
    }
    """
    # Group trades by setup_type
    by_engine: Dict[str, List[Dict]] = {}
    for t in trades:
        st = t.get("setup_type", "UNKNOWN")
        by_engine.setdefault(st, []).append(t)

    # Audit every known engine (even if no trades)
    engine_reports: Dict[str, Dict] = {}
    for eng in ALL_ENGINES:
        engine_reports[eng] = _audit_engine(eng, by_engine.get(eng, []))

    # Catch any non-standard setup_types present in the data
    for st, tlist in by_engine.items():
        if st not in engine_reports:
            engine_reports[st] = _audit_engine(st, tlist)

    classifications = _classify_engines(engine_reports)
    summary         = _generate_summary(engine_reports, classifications)

    # Sort engines by trade count descending for display
    engine_order = sorted(
        engine_reports.keys(),
        key=lambda e: engine_reports[e]["engine_level"]["trades_executed"],
        reverse=True,
    )

    # Overall combined metrics across all trades
    n = len(trades)
    if n > 0:
        all_rr  = [t["rr_achieved"] for t in trades]
        all_pnl = [t["pnl_pct"]     for t in trades]
        w_count = sum(1 for t in trades if t.get("is_win"))
        overall = {
            "total_trades":   n,
            "win_rate":       _pct(w_count, n),
            "avg_R":          _safe(_mean(all_rr)),
            "median_R":       _safe(_median(all_rr)),
            "expectancy":     _safe(
                w_count / n * _mean([t["rr_achieved"] for t in trades if t.get("is_win")] or [0])
                + (n - w_count) / n * _mean([t["rr_achieved"] for t in trades if not t.get("is_win")] or [0])
            ),
            "net_profit_pct": _safe(sum(all_pnl), 2),
            "r_distribution": _r_buckets(all_rr),
        }
    else:
        overall = {
            "total_trades": 0, "win_rate": 0.0, "avg_R": 0.0,
            "median_R": 0.0, "expectancy": 0.0, "net_profit_pct": 0.0,
            "r_distribution": _r_buckets([]),
        }

    return {
        "period":          period_label,
        "total_trades":    n,
        "by_engine":       engine_reports,
        "classifications": classifications,
        "summary":         summary,
        "engine_order":    engine_order,
        "overall":         overall,
    }
