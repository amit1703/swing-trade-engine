"""
Optuna v4 parameter optimizer for the swing trading system.

Changes from v3:
  - TRAIL_ATR_MULT expanded: 1.80–3.00 → 2.50–4.50 (was at ceiling)
  - REGIME_BULL_THRESHOLD expanded: 20–55 → 45–65 (was at ceiling)
  - BREAKOUT_BUFFER_ATR expanded: 0.30–0.50 → 0.30–0.55
  - MAX_OPEN_POSITIONS added: int 3–8 (never optimized before)
  - CCI_STRICT_FLOOR added: −80 to −20 (strict pullback depth)
  - CCI_RLX_FLOOR added: −40 to 0 (relaxed pullback depth)
  - Score formula: DD multiplier raised 2.5 → 4.0; hard DD cutoff 35% → 20%
  - Output: config/best_parameters_v4.json (v3 output is NOT overwritten)
  - Study: trading_optimizer_v4 (separate study in same SQLite DB)

Usage
-----
    cd swing-trading-dashboard/backend
    python ../scripts/optimize_parameters_v4.py --trials 400
    python ../scripts/optimize_parameters_v4.py --trials 10    # quick smoke test
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
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from wfo_engine import run_wfo
    from representative_tickers import REPRESENTATIVE_TICKERS
except ImportError:
    run_wfo = None              # type: ignore[assignment]
    REPRESENTATIVE_TICKERS = [] # type: ignore[assignment]

# ── Module patch map ──────────────────────────────────────────────────────────
# Maps param_key → list of (module_name, attribute_name) to temporarily override.
# IMPORTANT: CCI params are imported into engine3 — both constants AND engine3
# must be patched. MAX_OPEN_POSITIONS is imported into wfo_engine — both must
# be patched. The optimizer's own MAX_OPEN_POSITIONS is NOT patched here because
# _aggregate_oos_metrics_v4 receives max_positions as an explicit argument.
_MODULE_PATCHES: dict[str, list[tuple[str, str]]] = {
    "ATR_MULTIPLIER": [
        ("engines.engine2",           "ATR_STOP_MULTIPLIER"),
        ("engines.engine3",           "ATR_STOP_MULTIPLIER"),
        ("engines.engine8_htf",       "ATR_STOP_MULTIPLIER"),
        ("engines.engine9_low_cheat", "ATR_STOP_MULTIPLIER"),
    ],
    "VCP_TIGHTNESS_RANGE": [
        ("engines.engine2",     "VCP_TIGHT_RANGE_5D_PCT"),
        ("engines.engine8_htf", "VCP_TIGHT_RANGE_5D_PCT"),
    ],
    "BREAKOUT_BUFFER_ATR": [
        ("engines.engine6", "RES_DECISIVE_ATR_FACTOR"),
    ],
    "BREAKOUT_VOL_MULT": [
        ("engines.engine6",     "VOL_SURGE_MULTIPLIER"),
        ("engines.engine6",     "_VOL_SURGE_THRESHOLD"),
        ("engines.engine8_htf", "VOL_SURGE_MULTIPLIER"),
    ],
    "TARGET_RR": [
        ("engines.engine2",     "TARGET_RR"),
        ("engines.engine3",     "TARGET_RR"),
        ("engines.engine5",     "TARGET_RR"),
        ("engines.engine6",     "TARGET_RR"),
        ("engines.engine8_htf", "TARGET_RR"),
        ("zone_utils",          "TARGET_RR"),
    ],
    "TRAIL_ATR_MULT": [
        ("constants", "TRAIL_ATR_MULT"),
    ],
    "REGIME_BULL_THRESHOLD": [
        ("filters", "REGIME_SELECTIVE_THRESHOLD"),
    ],
    "ENGINE3_RS_THRESHOLD": [
        ("engines.engine3", "RS_REJECT_THRESHOLD"),
    ],
    # ── v4 additions ──────────────────────────────────────────────────────────
    "CCI_STRICT_FLOOR": [
        ("constants",       "CCI_STRICT_FLOOR"),
        ("engines.engine3", "CCI_STRICT_FLOOR"),
    ],
    "CCI_RLX_FLOOR": [
        ("constants",       "CCI_RLX_FLOOR"),
        ("engines.engine3", "CCI_RLX_FLOOR"),
    ],
    "MAX_OPEN_POSITIONS": [
        ("constants",   "MAX_OPEN_POSITIONS"),
        ("wfo_engine",  "MAX_OPEN_POSITIONS"),
    ],
}


def _preload_modules() -> None:
    """Force-import all modules that will be patched so they exist in sys.modules."""
    for patches in _MODULE_PATCHES.values():
        for mod_name, _ in patches:
            importlib.import_module(mod_name)


@contextmanager
def _patch_constants(params: dict[str, Any]):
    """
    Temporarily override module-level constants for one Optuna trial.

    Thread-safe for serial trials (Optuna default). Restores originals in
    finally-block even if the trial raises an exception.
    """
    _preload_modules()
    saved: list[tuple[Any, str, Any]] = []
    for param_key, patches in _MODULE_PATCHES.items():
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


def _compute_robustness_score_v4(
    expectancy: float,
    profit_factor: float,
    total_trades: int,
    max_drawdown_pct: float,
    net_profit_pct: float,
) -> float:
    """
    v4 robustness score — stronger drawdown penalty.

    Hard penalties (no formula applied):
      total_trades < 40    → -5.0   (statistically meaningless)
      max_drawdown > 20%   → -10.0  (unacceptable; tightened from v3's 35%)
      profit_factor < 1.0  → -3.0   (losing system)

    Main formula (same structure as v3; DD weight raised 2.5 → 4.0):
      score = (E × PF × √trades) / (1 + DD × 4.0)

    At DD=10%: denominator = 1.4 (v3: 1.25) — 12% stronger penalty
    At DD=15%: denominator = 1.6 (v3: 1.375) — 16% stronger penalty
    """
    if total_trades < 40:
        return -5.0
    if max_drawdown_pct > 20.0:
        return -10.0
    if profit_factor < 1.0:
        return -3.0
    return (
        (expectancy * profit_factor * math.sqrt(total_trades))
        / (1.0 + max_drawdown_pct * 4.0)
    )


def _apply_portfolio_cap_dicts(trades: list, max_positions: int) -> list:
    """Portfolio-wide position cap for dict-based trade lists."""
    if not trades or max_positions <= 0:
        return trades
    sorted_trades = sorted(trades, key=lambda t: (t["entry_date"], t["ticker"]))
    accepted: list = []
    for trade in sorted_trades:
        open_count = sum(
            1 for t in accepted
            if t["entry_date"] <= trade["entry_date"] < t["exit_date"]
        )
        if open_count < max_positions:
            accepted.append(trade)
    return accepted


def _aggregate_oos_metrics_v4(windows: list, max_positions: int) -> dict:
    """
    Compute aggregate OOS metrics across all WFO windows.

    max_positions is passed explicitly (not read from module globals) so that
    it reflects the trial's optimized value even when _patch_constants is active.
    """
    raw_trades = [t for w in windows for t in w.oos_trades]
    oos_trades = _apply_portfolio_cap_dicts(raw_trades, max_positions)
    total = len(oos_trades)
    if total == 0:
        return {
            "total_trades": 0, "expectancy": 0.0, "profit_factor": 0.0,
            "max_drawdown_pct": 0.0, "win_rate": 0.0, "net_profit_pct": 0.0,
            "calmar_ratio": 0.0,
        }

    wins   = [t for t in oos_trades if t["is_win"]]
    losses = [t for t in oos_trades if not t["is_win"]]

    win_rate   = len(wins) / total
    loss_rate  = len(losses) / total
    avg_win_r  = sum(t["rr_achieved"] for t in wins) / len(wins)   if wins   else 0.0
    avg_loss_r = sum(abs(t["rr_achieved"]) for t in losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win_r - loss_rate * avg_loss_r

    gross_profit  = sum(t["portfolio_pnl_pct"] for t in wins)
    gross_loss    = abs(sum(t["portfolio_pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
    net_profit    = sum(t["portfolio_pnl_pct"] for t in oos_trades)

    equity = 1.0; peak = 1.0; max_dd = 0.0
    for t in oos_trades:
        equity *= 1.0 + t["portfolio_pnl_pct"] / 100.0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    # Calmar: annualised return (net_profit / 2yr OOS) / max_drawdown
    calmar = (net_profit / 2.0) / max(max_dd, 0.01)

    return {
        "total_trades":     total,
        "win_rate":         round(win_rate * 100, 2),
        "expectancy":       round(expectancy, 4),
        "profit_factor":    round(min(profit_factor, 9999.0), 4),
        "max_drawdown_pct": round(max_dd, 2),
        "net_profit_pct":   round(net_profit, 2),
        "calmar_ratio":     round(calmar, 3),
    }


def _log_trial_v4(trial: "optuna.trial.FrozenTrial", log_path: str = "optuna_trial_log_v4.csv") -> None:
    """Append per-trial diagnostics to CSV for live monitoring."""
    fieldnames = [
        "trial_number", "value",
        "ATR_MULTIPLIER", "VCP_TIGHTNESS_RANGE", "BREAKOUT_BUFFER_ATR",
        "BREAKOUT_VOL_MULT", "TARGET_RR", "TRAIL_ATR_MULT", "REGIME_BULL_THRESHOLD",
        "ENGINE3_RS_THRESHOLD", "MAX_OPEN_POSITIONS", "CCI_STRICT_FLOOR", "CCI_RLX_FLOOR",
    ]
    file_exists = os.path.exists(log_path)
    with open(log_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        row = {"trial_number": trial.number, "value": trial.value}
        row.update(trial.params)
        writer.writerow(row)


# ── WFO configuration ─────────────────────────────────────────────────────────
WFO_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
WFO_IS_MONTHS   = 36
WFO_OOS_MONTHS  = 6
WFO_STEP_MONTHS = 6

# ── Study / output ────────────────────────────────────────────────────────────
_STUDY_NAME     = "trading_optimizer_v4"
_DEFAULT_TRIALS = 400
_OUTPUT_PATH    = _PROJECT_DIR / "config" / "best_parameters_v4.json"
_STUDY_DB       = str(_PROJECT_DIR / "optuna_study.db")

# ── Search bounds (referenced in tests and objective) ─────────────────────────
V4_BOUNDS: dict[str, tuple] = {
    "ATR_MULTIPLIER":        (1.20, 1.60),
    "VCP_TIGHTNESS_RANGE":   (0.035, 0.070),
    "BREAKOUT_BUFFER_ATR":   (0.30, 0.55),
    "BREAKOUT_VOL_MULT":     (0.80, 1.30),
    "TARGET_RR":             (2.20, 2.80),
    "TRAIL_ATR_MULT":        (2.50, 4.50),
    "REGIME_BULL_THRESHOLD": (45, 65),      # int
    "ENGINE3_RS_THRESHOLD":  (-0.10, 0.00),
    "MAX_OPEN_POSITIONS":    (3, 8),        # int
    "CCI_STRICT_FLOOR":      (-80.0, -20.0),
    "CCI_RLX_FLOOR":         (-40.0, 0.0),
}


def objective(trial) -> float:
    """Optuna objective: patch constants → run WFO → compute v4 robustness score."""
    import optuna

    params = {
        "ATR_MULTIPLIER":        trial.suggest_float("ATR_MULTIPLIER",        1.20,  1.60),
        "VCP_TIGHTNESS_RANGE":   trial.suggest_float("VCP_TIGHTNESS_RANGE",   0.035, 0.070),
        "BREAKOUT_BUFFER_ATR":   trial.suggest_float("BREAKOUT_BUFFER_ATR",   0.30,  0.55),
        "BREAKOUT_VOL_MULT":     trial.suggest_float("BREAKOUT_VOL_MULT",     0.80,  1.30),
        "TARGET_RR":             trial.suggest_float("TARGET_RR",             2.20,  2.80),
        "TRAIL_ATR_MULT":        trial.suggest_float("TRAIL_ATR_MULT",        2.50,  4.50),
        "REGIME_BULL_THRESHOLD": trial.suggest_int(  "REGIME_BULL_THRESHOLD", 45,    65),
        "ENGINE3_RS_THRESHOLD":  trial.suggest_float("ENGINE3_RS_THRESHOLD",  -0.10, 0.00),
        "MAX_OPEN_POSITIONS":    trial.suggest_int(  "MAX_OPEN_POSITIONS",    3,     8),
        "CCI_STRICT_FLOOR":      trial.suggest_float("CCI_STRICT_FLOOR",      -80.0, -20.0),
        "CCI_RLX_FLOOR":         trial.suggest_float("CCI_RLX_FLOOR",         -40.0,  0.0),
    }

    with _patch_constants(params):
        result = asyncio.run(run_wfo(
            tickers=["SPY"] + REPRESENTATIVE_TICKERS,
            setup_types=WFO_SETUP_TYPES,
            is_months=WFO_IS_MONTHS,
            oos_months=WFO_OOS_MONTHS,
            step_months=WFO_STEP_MONTHS,
            run_id=f"v4_trial_{trial.number}",
        ))

    metrics = _aggregate_oos_metrics_v4(result.windows, max_positions=params["MAX_OPEN_POSITIONS"])

    score = _compute_robustness_score_v4(
        expectancy=metrics["expectancy"],
        profit_factor=metrics["profit_factor"],
        total_trades=metrics["total_trades"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        net_profit_pct=metrics["net_profit_pct"],
    )

    trial.set_user_attr("metrics", metrics)

    trial.report(score, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return score


def _compute_plateau_report(study) -> dict:
    """
    Identify the plateau: completed trials scoring >= 80% of best score.

    Returns a dict with:
      - plateau_count: number of trials in plateau
      - threshold: minimum score to qualify
      - per_param: {param: {min, max, mean, std, best, at_boundary}}
      - ceiling_flags: list of param names where best value is within 5% of bound
    """
    import statistics

    completed = [t for t in study.trials if t.state.name == "COMPLETE" and t.value is not None]
    if not completed:
        return {}

    best_score = max(t.value for t in completed)
    threshold = 0.80 * best_score
    plateau_trials = [t for t in completed if t.value >= threshold]

    per_param: dict[str, dict] = {}
    ceiling_flags: list[str] = []
    best_params = study.best_trial.params

    for param, (lo, hi) in V4_BOUNDS.items():
        vals = [t.params.get(param) for t in plateau_trials if param in t.params]
        if not vals:
            continue
        mean = statistics.mean(vals)
        std  = statistics.stdev(vals) if len(vals) > 1 else 0.0
        span = hi - lo if hi != lo else 1.0
        best_val = best_params.get(param, mean)

        at_ceiling = (hi - best_val) / span < 0.05
        at_floor   = (best_val - lo) / span < 0.05
        if at_ceiling or at_floor:
            ceiling_flags.append(param)

        per_param[param] = {
            "min":  round(min(vals), 4),
            "max":  round(max(vals), 4),
            "mean": round(mean, 4),
            "std":  round(std, 4),
            "best": round(best_val, 4),
            "at_boundary": at_ceiling or at_floor,
        }

    return {
        "plateau_count":   len(plateau_trials),
        "total_completed": len(completed),
        "threshold":       round(threshold, 6),
        "best_score":      round(best_score, 6),
        "per_param":       per_param,
        "ceiling_flags":   ceiling_flags,
    }


def _export_best_v4(study, suppress_output: bool = False) -> None:
    """Print summary and write config/best_parameters_v4.json."""
    best    = study.best_trial
    metrics = best.user_attrs.get("metrics", {})
    plateau = _compute_plateau_report(study)

    output = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "study_name":     study.study_name,
        "best_trial":     best.number,
        "best_score":     round(best.value, 6),
        "parameters":     {
            k: round(v, 6) if isinstance(v, float) else v
            for k, v in best.params.items()
        },
        "oos_metrics":    metrics,
        "plateau_report": plateau,
    }

    try:
        import optuna as _optuna
        importance = _optuna.importance.get_param_importances(study)
    except Exception:
        importance = {}
    output["param_importance"] = importance

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    if not suppress_output:
        print("\n" + "="*60)
        print("  v4 BEST PARAMETERS")
        print("="*60)
        for k, v in best.params.items():
            flag = " ⚠️  BOUNDARY" if k in plateau.get("ceiling_flags", []) else ""
            print(f"  {k:<25} {round(v, 4) if isinstance(v, float) else v}{flag}")

        print("\n  OOS Performance:")
        for k, v in metrics.items():
            print(f"  {k:<25} {v}")

        print(f"\n  Robustness Score:  {best.value:.4f}")
        print(f"  Plateau trials:    {plateau.get('plateau_count', 0)} "
              f"/ {plateau.get('total_completed', 0)} "
              f"(score >= {plateau.get('threshold', 0):.4f})")

        if plateau.get("ceiling_flags"):
            print(f"\n  ⚠️  Boundary params: {', '.join(plateau['ceiling_flags'])}")
            print("     → Expand these ranges in v5 optimizer")
        else:
            print("\n  ✅ No boundary effects detected")

        print(f"\n  Exported to: {_OUTPUT_PATH}")
        print("="*60)


def main(n_trials: int = _DEFAULT_TRIALS, suppress_output: bool = False) -> None:
    import optuna
    from optuna.samplers import TPESampler
    from optuna.pruners import MedianPruner
    from tqdm import tqdm

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _preload_modules()

    study = optuna.create_study(
        study_name=_STUDY_NAME,
        storage=f"sqlite:///{_STUDY_DB}",
        direction="maximize",
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=15, n_warmup_steps=2),
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials if t.state.name == "COMPLETE"])
    remaining = max(0, n_trials - completed_before)

    if not suppress_output:
        print(f"Study: {study.study_name}  |  Completed: {completed_before}  |  Running: {remaining}")

    if remaining > 0:
        with tqdm(total=remaining, desc="Optimizing v4", unit="trial", disable=suppress_output) as pbar:
            def _cb(study, trial):
                pbar.update(1)
                try:
                    pbar.set_postfix({"best": round(study.best_value, 4)})
                except Exception:
                    pass
                _log_trial_v4(trial)
                print(f"Trial {trial.number}: score={trial.value:.4f}")
            study.optimize(objective, n_trials=remaining, callbacks=[_cb])

    try:
        _ = study.best_trial
        _export_best_v4(study, suppress_output=suppress_output)
    except ValueError:
        if not suppress_output:
            print("No completed trials yet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optuna v4 parameter optimizer")
    parser.add_argument(
        "--trials", type=int, default=_DEFAULT_TRIALS,
        help=f"Total trials to run (default: {_DEFAULT_TRIALS}). Study resumes if DB exists.",
    )
    args = parser.parse_args()

    from wfo_engine import run_wfo                          # noqa: F811
    from representative_tickers import REPRESENTATIVE_TICKERS  # noqa: F811

    main(n_trials=args.trials)
