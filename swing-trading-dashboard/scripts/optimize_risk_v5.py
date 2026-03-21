"""
Risk Optimizer V5 — Optuna optimization of risk/execution parameters only.

Optimizes: trail_mult, risk_per_trade, max_position_pct,
           atr_entry_early, atr_entry_extended

Entry logic, setup detection, regime logic, and core filters are FROZEN.

Usage (run from backend/ directory):
    python ../scripts/optimize_risk_v5.py --phase 1 --trials 300
    python ../scripts/optimize_risk_v5.py --phase 2 --trials 200
    python ../scripts/optimize_risk_v5.py --phase 1 --trials 5   # smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib
import json
import math
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

from wfo_engine import run_wfo
from representative_tickers_v2 import REPRESENTATIVE_TICKERS_V2

WFO_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF"]
WFO_IS_MONTHS   = 36
WFO_OOS_MONTHS  = 6
WFO_STEP_MONTHS = 6
# Note: run_wfo derives its date range from the price cache contents directly.
# There is no start/end_date argument. Do NOT define dead WFO_START/END_DATE constants.

# Smoke-test overrides (activated by --smoke flag).
# Uses minimal tickers + short windows so each trial completes in <30s.
# Correctness check only — not representative of production volumes.
_SMOKE_IS_MONTHS    = 12
_SMOKE_OOS_MONTHS   = 3
_SMOKE_STEP_MONTHS  = 6
_SMOKE_SETUP_TYPES  = ["VCP", "PULLBACK"]  # reduced set to keep trial time under 30s
# 3 large-cap tickers with guaranteed WFO cache.
_SMOKE_TICKERS = ["SPY", "AAPL", "MSFT"]

_STUDY_DB               = str(_PROJECT_DIR / "optuna_study.db")
_STUDY_NAME_P1          = "trading_risk_v5_phase1"
_STUDY_NAME_P2          = "trading_risk_v5_phase2"
# Smoke mode uses separate study names so smoke trials don't pollute production studies.
_STUDY_NAME_P1_SMOKE    = "trading_risk_v5_phase1_smoke"
_STUDY_NAME_P2_SMOKE    = "trading_risk_v5_phase2_smoke"
_OUTPUT_P1         = _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase1.json"
_OUTPUT_P2         = _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase2.json"
_CSV_LOG           = "optuna_trial_log_risk_v5.csv"
_DEFAULT_TRIALS_P1 = 300
_DEFAULT_TRIALS_P2 = 200

BOUNDS_P1: dict[str, tuple] = {
    "trail_mult":         (2.0,  8.5),
    "risk_per_trade":     (0.5,  1.5),
    "max_position_pct":   (10.0, 30.0),
    "atr_entry_early":    (0.03, 0.20),
    "atr_entry_extended": (0.30, 0.90),
}

_MODULE_PATCHES: dict[str, list[tuple[str, str]]] = {
    "trail_mult": [
        ("constants", "TRAIL_ATR_MULT"),
        ("constants", "VCP_TRAIL_ATR_MULT"),
        ("constants", "PULLBACK_TRAIL_ATR_MULT"),
        ("constants", "RES_BREAKOUT_TRAIL_ATR_MULT"),
        ("constants", "BASE_TRAIL_ATR_MULT"),
    ],
    "risk_per_trade": [
        ("constants",       "RISK_PER_TRADE_PCT"),
        ("backtest_engine", "RISK_PER_TRADE_PCT"),
    ],
    "max_position_pct": [
        ("constants",       "MAX_POSITION_SIZE_PCT"),
        ("backtest_engine", "MAX_POSITION_SIZE_PCT"),
    ],
    # atr_entry_early / atr_entry_extended: post-WFO filter, no module patch.
}


# ---------------------------------------------------------------------------
# Section 2: _preload_modules and _patch_constants
# ---------------------------------------------------------------------------

def _preload_modules() -> None:
    for patches in _MODULE_PATCHES.values():
        for mod_name, _ in patches:
            importlib.import_module(mod_name)


@contextmanager
def _patch_constants(params: dict[str, Any]):
    _preload_modules()
    saved: list[tuple[Any, str, Any]] = []
    for param_key, patches in _MODULE_PATCHES.items():
        if param_key not in params:
            continue
        val = params[param_key]
        for mod_name, attr in patches:
            mod = sys.modules[mod_name]
            saved.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, val)
    try:
        yield
    finally:
        for mod, attr, orig in saved:
            setattr(mod, attr, orig)


# ---------------------------------------------------------------------------
# Section 3: _entry_quality and _window_max_dd
# ---------------------------------------------------------------------------

def _entry_quality(trade: dict, early_thresh: float, extended_thresh: float) -> str:
    meta      = trade.get("setup_meta", {})
    atr       = meta.get("atr", 0)
    sig_entry = meta.get("entry", None)
    fill      = trade.get("entry_price")
    if not atr or atr <= 0 or sig_entry is None or fill is None:
        return "UNKNOWN"
    dist = (fill - sig_entry) / atr
    if dist < early_thresh:
        return "EARLY"
    elif dist < extended_thresh:
        return "OPTIMAL"
    return "EXTENDED"


def _window_max_dd(window, atr_early: float, atr_extended: float) -> Optional[float]:
    filtered = [
        t for t in window.oos_trades
        if _entry_quality(t, atr_early, atr_extended) in ("EARLY", "OPTIMAL")
    ]
    if not filtered:
        return None
    sorted_t = sorted(filtered, key=lambda t: t["exit_date"])
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted_t:
        equity *= 1.0 + t["portfolio_pnl_pct"] / 100.0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# Section 4: _SETUP_TYPES, _compute_per_setup_stats, _compute_score
# ---------------------------------------------------------------------------

_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF"]


def _compute_per_setup_stats(trades: list) -> dict:
    result = {}
    for stype in _SETUP_TYPES:
        subset = [t for t in trades if t.get("setup_type") == stype]
        n = len(subset)
        if n == 0:
            result[stype] = {"n": 0, "win_rate": 0.0, "expectancy": 0.0, "profit_factor": 0.0}
            continue
        wins   = [t for t in subset if t["is_win"]]
        losses = [t for t in subset if not t["is_win"]]
        wr  = len(wins) / n
        lr  = len(losses) / n
        awr = sum(t["rr_achieved"] for t in wins)   / len(wins)   if wins   else 0.0
        alr = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
        exp = wr * awr - lr * alr
        gp  = sum(t["portfolio_pnl_pct"] for t in wins)
        gl  = abs(sum(t["portfolio_pnl_pct"] for t in losses))
        pf  = gp / gl if gl > 0 else (gp if gp > 0 else 0.0)
        result[stype] = {
            "n":             n,
            "win_rate":      round(wr * 100, 2),
            "expectancy":    round(exp, 4),
            "profit_factor": round(min(pf, 9999.0), 4),
        }
    return result


def _compute_score(oos_windows: list, atr_early: float, atr_extended: float) -> tuple[float, dict]:
    # Note: signature differs from spec (oos_trades removed — reconstructed here;
    # return type extended to tuple for logging).
    all_trades = [t for w in oos_windows for t in w.oos_trades]
    filtered = [
        t for t in all_trades
        if _entry_quality(t, atr_early, atr_extended) in ("EARLY", "OPTIMAL")
    ]
    n_trades = len(filtered)

    base_metrics = {"n_trades": n_trades, "expectancy": 0.0, "profit_factor": 0.0,
                    "avg_r": 0.0, "max_dd": 0.0, "dd_volatility": 0.0}

    if n_trades < 200:
        return -10.0, base_metrics

    wins   = [t for t in filtered if t["is_win"]]
    losses = [t for t in filtered if not t["is_win"]]

    win_rate  = len(wins) / n_trades
    loss_rate = len(losses) / n_trades
    avg_win_r  = sum(t["rr_achieved"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_r = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win_r - loss_rate * avg_loss_r
    avg_r      = float(np.mean([t["rr_achieved"] for t in filtered]))

    gross_profit  = sum(t["portfolio_pnl_pct"] for t in wins)
    gross_loss    = abs(sum(t["portfolio_pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

    sorted_t = sorted(filtered, key=lambda t: t["exit_date"])
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted_t:
        equity *= 1.0 + t["portfolio_pnl_pct"] / 100.0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    per_window_dd = [_window_max_dd(w, atr_early, atr_extended) for w in oos_windows]
    active_dds    = [d for d in per_window_dd if d is not None]
    dd_volatility = float(np.std(active_dds)) if len(active_dds) >= 2 else 0.0

    metrics = {
        "n_trades":      n_trades,
        "expectancy":    round(expectancy, 4),
        "profit_factor": round(min(profit_factor, 9999.0), 4),
        "avg_r":         round(avg_r, 4),
        "max_dd":        round(max_dd, 2),
        "dd_volatility": round(dd_volatility, 2),
    }

    if expectancy <= 0:      return -8.0,  metrics
    if profit_factor < 1.2:  return -5.0,  metrics
    if max_dd > 50.0:        return -10.0, metrics

    trade_penalty = max(0.0, (300 - n_trades) / 300) * 2.0

    score = (
        0.35 * expectancy
      + 0.25 * profit_factor
      + 0.15 * avg_r
      - 0.15 * (max_dd / 10.0)
      - 0.10 * (dd_volatility / 10.0)
      - trade_penalty
    )
    return round(score, 6), metrics


# ---------------------------------------------------------------------------
# Section 5: CSV logger and objective
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES = [
    "trial_number", "score",
    "trail_mult", "risk_per_trade", "max_position_pct",
    "atr_entry_early", "atr_entry_extended",
    "expectancy", "profit_factor", "avg_r", "max_dd", "dd_volatility", "n_trades",
] + [f"{s}_{m}" for s in _SETUP_TYPES for m in ("expectancy", "pf", "winrate", "n")]


def _log_trial(trial, metrics: dict, setup_stats: dict, log_path: str = _CSV_LOG) -> None:
    file_exists = os.path.exists(log_path)
    row: dict = {"trial_number": trial.number, "score": trial.value}
    row.update(trial.params)
    row.update(metrics)
    for stype, stats in setup_stats.items():
        row[f"{stype}_n"]          = stats["n"]
        row[f"{stype}_expectancy"] = stats["expectancy"]
        row[f"{stype}_pf"]         = stats["profit_factor"]
        row[f"{stype}_winrate"]    = stats["win_rate"]
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def objective(trial, bounds: dict, is_months: int = WFO_IS_MONTHS,
              oos_months: int = WFO_OOS_MONTHS,
              step_months: int = WFO_STEP_MONTHS,
              tickers: list = None,
              setup_types: list = None) -> float:
    import optuna

    trail_mult         = trial.suggest_float("trail_mult",         *bounds["trail_mult"])
    risk_per_trade     = trial.suggest_float("risk_per_trade",     *bounds["risk_per_trade"])
    max_position_pct   = trial.suggest_float("max_position_pct",   *bounds["max_position_pct"])
    atr_entry_early    = trial.suggest_float("atr_entry_early",    *bounds["atr_entry_early"])
    atr_entry_extended = trial.suggest_float("atr_entry_extended", *bounds["atr_entry_extended"])

    if atr_entry_early >= atr_entry_extended:
        raise optuna.TrialPruned()

    params = {
        "trail_mult":       trail_mult,
        "risk_per_trade":   risk_per_trade,
        "max_position_pct": max_position_pct,
    }

    _tickers     = tickers     if tickers     is not None else (["SPY"] + REPRESENTATIVE_TICKERS_V2)
    _setup_types = setup_types if setup_types is not None else WFO_SETUP_TYPES
    with _patch_constants(params):
        result = asyncio.run(run_wfo(
            tickers=_tickers,
            setup_types=_setup_types,
            is_months=is_months,
            oos_months=oos_months,
            step_months=step_months,
            run_id=f"v5_trial_{trial.number}",
        ))

    score, metrics = _compute_score(result.windows, atr_entry_early, atr_entry_extended)

    all_filtered = [
        t for w in result.windows for t in w.oos_trades
        if _entry_quality(t, atr_entry_early, atr_entry_extended) in ("EARLY", "OPTIMAL")
    ]
    setup_stats = _compute_per_setup_stats(all_filtered)

    trial.set_user_attr("metrics",     metrics)
    trial.set_user_attr("setup_stats", setup_stats)

    trial.report(score, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return score


# ---------------------------------------------------------------------------
# Section 6: Phase output functions
# ---------------------------------------------------------------------------

def _compute_distribution(trials: list, bounds: dict) -> dict:
    dist = {}
    for param in bounds:
        vals = [t.params[param] for t in trials if param in t.params]
        if not vals:
            dist[param] = {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
            continue
        dist[param] = {
            "mean": round(float(np.mean(vals)), 4),
            "std":  round(float(np.std(vals)),  4),
            "min":  round(float(min(vals)),      4),
            "max":  round(float(max(vals)),      4),
        }
    return dist


def _compute_stability(dist: dict, bounds: dict) -> dict:
    stability = {}
    for param, (lo, hi) in bounds.items():
        search_range = hi - lo
        std = dist[param]["std"]
        std_pct = round(std / search_range * 100, 1) if search_range > 0 else 0.0
        stability[param] = {
            "narrow":           std_pct < 15.0,
            "std_pct_of_range": std_pct,
        }
    return stability


def _compute_sensitivity(completed_trials: list) -> dict:
    buckets = [
        ("[2.0-3.5]", 2.0, 3.5),
        ("[3.5-5.0]", 3.5, 5.0),
        ("[5.0-6.5]", 5.0, 6.5),
        ("[6.5-8.5]", 6.5, 8.5),
    ]
    result = {}
    for label, lo, hi in buckets:
        bt = [t for t in completed_trials if lo <= t.params.get("trail_mult", -1) < hi]
        result[label] = {
            "n_trials":  len(bt),
            "avg_score": round(float(np.mean([t.value for t in bt])), 4) if bt else 0.0,
        }
    return result


def _compute_phase2_ranges(top_trials: list, bounds_p1: dict) -> dict:
    best   = top_trials[0]
    ranges = {}
    for param, (lo_orig, hi_orig) in bounds_p1.items():
        vals = [t.params[param] for t in top_trials if param in t.params]
        std  = float(np.std(vals)) if len(vals) > 1 else (hi_orig - lo_orig) * 0.1
        best_val = best.params.get(param, (lo_orig + hi_orig) / 2)
        new_lo = max(lo_orig, best_val - 1.5 * std)
        new_hi = min(hi_orig, best_val + 1.5 * std)
        if new_lo >= new_hi:
            new_lo, new_hi = lo_orig, hi_orig
        ranges[param] = [round(new_lo, 4), round(new_hi, 4)]

    if ranges["atr_entry_early"][1] >= ranges["atr_entry_extended"][0]:
        ranges["atr_entry_early"][1] = round(ranges["atr_entry_extended"][0] - 0.05, 4)
        if ranges["atr_entry_early"][0] >= ranges["atr_entry_early"][1]:
            ranges["atr_entry_early"] = list(bounds_p1["atr_entry_early"])

    # Also validate atr_entry_extended didn't narrow to zero-width
    if ranges["atr_entry_extended"][0] >= ranges["atr_entry_extended"][1]:
        ranges["atr_entry_extended"] = list(bounds_p1["atr_entry_extended"])

    return ranges


def _load_phase2_bounds(smoke: bool = False) -> dict:
    p1_path = (
        _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase1_smoke.json"
        if smoke else _OUTPUT_P1
    )
    if not p1_path.exists():
        print(f"  Warning: Phase 1 output not found at {p1_path}. Using P1 bounds.")
        return BOUNDS_P1
    data   = json.loads(p1_path.read_text())
    ranges = data.get("phase2_suggested_ranges", {})
    bounds = {}
    for param, (lo_orig, hi_orig) in BOUNDS_P1.items():
        if param in ranges and len(ranges[param]) == 2:
            bounds[param] = tuple(ranges[param])
        else:
            bounds[param] = (lo_orig, hi_orig)
    return bounds


def _export_phase1(study, suppress_output: bool = False,
                   output_path: Path = None) -> None:
    if output_path is None:
        output_path = _OUTPUT_P1
    completed = [t for t in study.trials if t.state.name == "COMPLETE" and t.value is not None]
    if not completed:
        print("No completed trials to export.")
        return

    top_30 = sorted(completed, key=lambda t: t.value, reverse=True)[:30]

    dist        = _compute_distribution(top_30, BOUNDS_P1)
    stability   = _compute_stability(dist, BOUNDS_P1)
    sensitivity = _compute_sensitivity(completed)
    p2_ranges   = _compute_phase2_ranges(top_30, BOUNDS_P1)

    output = {
        "generated_at":           datetime.now(timezone.utc).isoformat(),
        "study":                  study.study_name,
        "total_completed_trials": len(completed),
        "top_30_trials": [
            {
                "trial":       t.number,
                "score":       round(t.value, 6),
                "params":      {k: round(v, 4) if isinstance(v, float) else v
                                for k, v in t.params.items()},
                "metrics":     t.user_attrs.get("metrics", {}),
                "setup_stats": t.user_attrs.get("setup_stats", {}),
            }
            for t in top_30
        ],
        "distribution":           dist,
        "stability":              stability,
        "sensitivity":            {"trail_mult_buckets": sensitivity},
        "phase2_suggested_ranges": p2_ranges,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(output, indent=2))
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    if not suppress_output:
        print(f"\n{'='*60}")
        print("  PHASE 1 RESULTS")
        print(f"{'='*60}")
        best = top_30[0]
        print(f"  Best score: {best.value:.4f}  (trial #{best.number})")
        for k, v in best.params.items():
            narrow = stability.get(k, {}).get("narrow", False)
            flag   = " stable" if narrow else "  spread"
            print(f"  {k:<25} {round(v, 4) if isinstance(v, float) else v}{flag}")
        print(f"\n  Trail mult sensitivity:")
        for bucket, info in sensitivity.items():
            print(f"    {bucket:<12} avg={info['avg_score']:+.4f}  n={info['n_trials']}")
        print(f"\n  Phase 2 suggested ranges: {p2_ranges}")
        print(f"  Exported to: {output_path}")


def _export_phase2(study, suppress_output: bool = False,
                   output_path: Path = None, bounds_p2: dict = None) -> None:
    if output_path is None:
        output_path = _OUTPUT_P2
    completed = [t for t in study.trials if t.state.name == "COMPLETE" and t.value is not None]
    if not completed:
        print("No completed trials to export.")
        return

    top_30 = sorted(completed, key=lambda t: t.value, reverse=True)[:30]
    best   = top_30[0]
    if bounds_p2 is None:
        bounds_p2 = _load_phase2_bounds()

    dist      = _compute_distribution(top_30, bounds_p2)
    stability = _compute_stability(dist, bounds_p2)
    sensitivity = _compute_sensitivity(completed)

    recommended = {
        "trail_mult":         round(best.params.get("trail_mult", 0), 4),
        "risk_per_trade":     round(best.params.get("risk_per_trade", 0), 4),
        "max_position_pct":   round(best.params.get("max_position_pct", 0), 4),
        "atr_entry_early":    round(best.params.get("atr_entry_early", 0), 4),
        "atr_entry_extended": round(best.params.get("atr_entry_extended", 0), 4),
        "score":              round(best.value, 6),
        "rationale": (
            f"Top trial #{best.number} by score; "
            f"expectancy={best.user_attrs.get('metrics', {}).get('expectancy', 'n/a')}, "
            f"max_dd={best.user_attrs.get('metrics', {}).get('max_dd', 'n/a')}%."
        ),
    }

    output = {
        "generated_at":           datetime.now(timezone.utc).isoformat(),
        "study":                  study.study_name,
        "total_completed_trials": len(completed),
        "top_30_trials": [
            {
                "trial":       t.number,
                "score":       round(t.value, 6),
                "params":      {k: round(v, 4) if isinstance(v, float) else v
                                for k, v in t.params.items()},
                "metrics":     t.user_attrs.get("metrics", {}),
                "setup_stats": t.user_attrs.get("setup_stats", {}),
            }
            for t in top_30
        ],
        "distribution":  dist,
        "stability":     stability,
        "sensitivity":   {"trail_mult_buckets": sensitivity},
        "recommended":   recommended,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(output, indent=2))
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    if not suppress_output:
        print(f"\n{'='*60}")
        print("  PHASE 2 RESULTS — RECOMMENDED PARAMETERS")
        print(f"{'='*60}")
        for k, v in recommended.items():
            if k == "rationale":
                continue
            print(f"  {k:<25} {v}")
        print(f"\n  Rationale: {recommended['rationale']}")
        print(f"  Exported to: {output_path}")


# ---------------------------------------------------------------------------
# Section 7: main() and CLI
# ---------------------------------------------------------------------------

def main(phase: int, n_trials: int, suppress_output: bool = False,
         smoke: bool = False) -> None:
    import optuna
    from optuna.samplers import TPESampler
    from optuna.pruners import MedianPruner

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _preload_modules()

    is_months   = _SMOKE_IS_MONTHS    if smoke else WFO_IS_MONTHS
    oos_months  = _SMOKE_OOS_MONTHS   if smoke else WFO_OOS_MONTHS
    step_months = _SMOKE_STEP_MONTHS  if smoke else WFO_STEP_MONTHS
    tickers     = _SMOKE_TICKERS      if smoke else None   # None → full representative list
    setup_types = _SMOKE_SETUP_TYPES  if smoke else None   # None → WFO_SETUP_TYPES

    if phase == 1:
        study_name = _STUDY_NAME_P1_SMOKE if smoke else _STUDY_NAME_P1
        output_p1  = _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase1_smoke.json" if smoke else _OUTPUT_P1
        bounds     = BOUNDS_P1
    else:
        study_name = _STUDY_NAME_P2_SMOKE if smoke else _STUDY_NAME_P2
        output_p2  = _PROJECT_DIR / "config" / "best_parameters_risk_v5_phase2_smoke.json" if smoke else _OUTPUT_P2
        bounds     = _load_phase2_bounds(smoke=smoke)
        if not suppress_output:
            print(f"  Phase 2 bounds loaded: {bounds}")

    if smoke and not suppress_output:
        _ntickers = len(tickers) if tickers else len(REPRESENTATIVE_TICKERS_V2) + 1
        print(f"  [SMOKE MODE] IS={is_months}m  OOS={oos_months}m  step={step_months}m  "
              f"tickers={_ntickers}  setup_types={setup_types}")

    study = optuna.create_study(
        study_name=study_name,
        storage=f"sqlite:///{_STUDY_DB}",
        direction="maximize",
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=15, n_warmup_steps=2),
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials if t.state.name == "COMPLETE"])
    remaining = max(0, n_trials - completed_before)
    if not suppress_output:
        print(f"\n  Study: {study_name}")
        print(f"  Trials: {completed_before} done, running {remaining} more (target {n_trials})")

    if remaining > 0:
        def _cb(study, trial):
            if trial.state.name == "COMPLETE" and trial.value is not None:
                metrics     = trial.user_attrs.get("metrics", {})
                setup_stats = trial.user_attrs.get("setup_stats", {})
                _log_trial(trial, metrics, setup_stats)
                if not suppress_output:
                    print(
                        f"  Trial {trial.number:4d} | score={trial.value:+.4f} | "
                        f"exp={metrics.get('expectancy', 0):+.3f} | "
                        f"PF={metrics.get('profit_factor', 0):.2f} | "
                        f"DD={metrics.get('max_dd', 0):.1f}% | "
                        f"n={metrics.get('n_trades', 0)}"
                    )

        # n_jobs=1 required: _patch_constants() mutates sys.modules globals and is not thread-safe
        study.optimize(
            lambda trial: objective(trial, bounds,
                                    is_months=is_months,
                                    oos_months=oos_months,
                                    step_months=step_months,
                                    tickers=tickers,
                                    setup_types=setup_types),
            n_trials=remaining,
            callbacks=[_cb],
            n_jobs=1,
        )

    if phase == 1:
        _export_phase1(study, suppress_output=suppress_output,
                       output_path=output_p1)
    else:
        _export_phase2(study, suppress_output=suppress_output,
                       output_path=output_p2, bounds_p2=bounds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Risk Optimizer V5")
    parser.add_argument("--phase",  type=int, default=1, choices=[1, 2])
    parser.add_argument("--trials", type=int, default=None)
    parser.add_argument(
        "--smoke", action="store_true",
        help=(
            f"Smoke-test mode: shorten WFO windows to IS={_SMOKE_IS_MONTHS}m "
            f"OOS={_SMOKE_OOS_MONTHS}m step={_SMOKE_STEP_MONTHS}m for fast iteration. "
            "Does NOT affect production runs."
        ),
    )
    args = parser.parse_args()
    n    = args.trials or (_DEFAULT_TRIALS_P1 if args.phase == 1 else _DEFAULT_TRIALS_P2)
    main(phase=args.phase, n_trials=n, smoke=args.smoke)
