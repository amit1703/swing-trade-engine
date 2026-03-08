"""
Optuna-based parameter optimizer for the swing trading system.

Usage
-----
    cd swing-trading-dashboard/backend
    python ../scripts/optimize_parameters.py --trials 300
    python ../scripts/optimize_parameters.py --trials 50    # quick test

The study persists in optuna_study.db (project root) and resumes automatically.
Best parameters are exported to config/best_parameters.json.
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

# ── Path setup (script may run from any cwd) ──────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

# run_wfo and REPRESENTATIVE_TICKERS are imported lazily in __main__ to avoid
# startup cost during unit tests — but exposed here for mockability in tests.
try:
    from wfo_engine import run_wfo
    from representative_tickers import REPRESENTATIVE_TICKERS
except ImportError:
    run_wfo = None              # type: ignore[assignment]
    REPRESENTATIVE_TICKERS = [] # type: ignore[assignment]

# Import portfolio sizing constants (available regardless of wfo_engine import)
sys.path.insert(0, str(_BACKEND_DIR))
from constants import MAX_OPEN_POSITIONS

# ── Module patch map ──────────────────────────────────────────────────────────
# Each entry: param_key → list of (module_name, attribute_name) to override.
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


def _compute_robustness_score(
    expectancy: float,
    profit_factor: float,
    total_trades: int,
    max_drawdown_pct: float,
) -> float:
    """
    Robustness score for one Optuna trial.

    Penalises:
      - total_trades < 30  → -5.0  (too few trades; not statistically meaningful)
      - max_drawdown > 20% → -10.0 (unacceptable risk)

    Otherwise:
      score = (expectancy * profit_factor * sqrt(total_trades)) / (1 + drawdown * 2.5)
    """
    if total_trades < 40:
        return -5.0
    if max_drawdown_pct > 35.0:
        return -10.0
    return (
        (expectancy * profit_factor * math.sqrt(total_trades))
        / (1.0 + max_drawdown_pct * 2.5)
    )


def _log_trial(trial: "optuna.trial.FrozenTrial", log_path: str = "optuna_trial_log.csv") -> None:
    """Append per-trial diagnostics to CSV for live monitoring."""
    fieldnames = [
        "trial_number", "value",
        "ATR_MULTIPLIER", "VCP_TIGHTNESS_RANGE", "BREAKOUT_BUFFER_ATR",
        "BREAKOUT_VOL_MULT", "TARGET_RR", "TRAIL_ATR_MULT", "REGIME_BULL_THRESHOLD",
        "ENGINE3_RS_THRESHOLD",
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

# ── Study defaults ────────────────────────────────────────────────────────────
_STUDY_NAME     = "trading_optimizer_v3"
_DEFAULT_TRIALS = 300

# ── Paths (overridable in tests) ──────────────────────────────────────────────
_OUTPUT_PATH = _PROJECT_DIR / "config" / "best_parameters.json"
_STUDY_DB    = str(_PROJECT_DIR / "optuna_study.db")


def _apply_portfolio_cap_dicts(trades: list, max_positions: int) -> list:
    """
    Portfolio-wide position cap for dict-based trade lists (from WFOWindowResult.oos_trades).
    Mirrors wfo_engine._apply_portfolio_cap but operates on to_dict() output.
    """
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


def _aggregate_oos_metrics(windows: list) -> dict:
    """Compute aggregate metrics from OOS trades across all WFO windows."""
    raw_trades = [t for w in windows for t in w.oos_trades]
    # Enforce portfolio-wide position cap on combined OOS trade list
    oos_trades = _apply_portfolio_cap_dicts(raw_trades, MAX_OPEN_POSITIONS)
    total = len(oos_trades)
    if total == 0:
        return {
            "total_trades": 0, "expectancy": 0.0, "profit_factor": 0.0,
            "max_drawdown_pct": 0.0, "win_rate": 0.0, "net_profit_pct": 0.0,
        }

    wins   = [t for t in oos_trades if t["is_win"]]
    losses = [t for t in oos_trades if not t["is_win"]]

    win_rate   = len(wins) / total
    loss_rate  = len(losses) / total
    avg_win_r  = sum(t["rr_achieved"] for t in wins) / len(wins)     if wins   else 0.0
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

    return {
        "total_trades":     total,
        "win_rate":         round(win_rate * 100, 2),
        "expectancy":       round(expectancy, 4),
        "profit_factor":    round(min(profit_factor, 9999.0), 4),
        "max_drawdown_pct": round(max_dd, 2),
        "net_profit_pct":   round(net_profit, 2),
    }


def objective(trial) -> float:
    """Optuna objective: patch constants → run WFO → compute robustness score."""
    import optuna

    params = {
        "ATR_MULTIPLIER":      trial.suggest_float("ATR_MULTIPLIER",      1.20, 1.60),
        "VCP_TIGHTNESS_RANGE": trial.suggest_float("VCP_TIGHTNESS_RANGE", 0.035, 0.070),
        "BREAKOUT_BUFFER_ATR": trial.suggest_float("BREAKOUT_BUFFER_ATR", 0.30, 0.50),
        "BREAKOUT_VOL_MULT":   trial.suggest_float("BREAKOUT_VOL_MULT",   0.80, 1.30),
        "TARGET_RR":           trial.suggest_float("TARGET_RR",           2.20, 2.80),
        "TRAIL_ATR_MULT":      trial.suggest_float("TRAIL_ATR_MULT",      1.80, 3.00),
        "REGIME_BULL_THRESHOLD": trial.suggest_int("REGIME_BULL_THRESHOLD", 20, 55),
        "ENGINE3_RS_THRESHOLD":    trial.suggest_float("ENGINE3_RS_THRESHOLD", -0.10, 0.00),
    }

    with _patch_constants(params):
        result = asyncio.run(run_wfo(
            tickers=["SPY"] + REPRESENTATIVE_TICKERS,
            setup_types=WFO_SETUP_TYPES,
            is_months=WFO_IS_MONTHS,
            oos_months=WFO_OOS_MONTHS,
            step_months=WFO_STEP_MONTHS,
            run_id=f"optuna_trial_{trial.number}",
        ))

    metrics = _aggregate_oos_metrics(result.windows)

    score = _compute_robustness_score(
        expectancy=metrics["expectancy"],
        profit_factor=metrics["profit_factor"],
        total_trades=metrics["total_trades"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
    )

    # Cache metrics on trial for export
    trial.set_user_attr("metrics", metrics)

    # Report for pruning
    trial.report(score, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return score


def _export_best(study, suppress_output: bool = False) -> None:
    """Print summary and write config/best_parameters.json."""
    best = study.best_trial
    metrics = best.user_attrs.get("metrics", {})

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "study_name":   study.study_name,
        "best_trial":   best.number,
        "best_score":   round(best.value, 6),
        "parameters":   {
            k: round(v, 6) if isinstance(v, float) else v
            for k, v in best.params.items()
        },
        "oos_metrics": metrics,
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
        print("\n" + "="*55)
        print("  BEST PARAMETERS")
        print("="*55)
        for k, v in best.params.items():
            print(f"  {k:<25} {round(v, 4) if isinstance(v, float) else v}")
        print("\n  OOS Performance:")
        for k, v in metrics.items():
            print(f"  {k:<25} {v}")
        print(f"\n  Robustness Score:  {best.value:.4f}")
        print(f"  Exported to:       {_OUTPUT_PATH}")
        print("="*55)


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
        pruner=MedianPruner(n_startup_trials=10, n_warmup_steps=2),
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials if t.state.name == "COMPLETE"])
    remaining = max(0, n_trials - completed_before)

    if not suppress_output:
        print(f"Study: {study.study_name}  |  Completed: {completed_before}  |  Running: {remaining}")

    if remaining > 0:
        with tqdm(total=remaining, desc="Optimizing", unit="trial", disable=suppress_output) as pbar:
            def _cb(study, trial):
                pbar.update(1)
                try:
                    pbar.set_postfix({"best": round(study.best_value, 4)})
                except Exception:
                    pass
                _log_trial(trial)
                print(f"Trial {trial.number}: score={trial.value:.4f}")
            study.optimize(objective, n_trials=remaining, callbacks=[_cb])

    try:
        _ = study.best_trial
        _export_best(study, suppress_output=suppress_output)
    except ValueError:
        if not suppress_output:
            print("No completed trials yet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optuna parameter optimizer for swing trading system")
    parser.add_argument(
        "--trials", type=int, default=_DEFAULT_TRIALS,
        help="Total trials to run (default: 300). Study resumes automatically if DB exists.",
    )
    args = parser.parse_args()

    # Late imports (avoids startup cost in unit tests that import only the helpers)
    from wfo_engine import run_wfo                          # noqa: F811
    from representative_tickers import REPRESENTATIVE_TICKERS  # noqa: F811

    main(n_trials=args.trials)
