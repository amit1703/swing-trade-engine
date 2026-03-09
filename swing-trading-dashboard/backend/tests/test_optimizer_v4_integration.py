"""
Integration tests for optimize_parameters_v4.py.

Mocks run_wfo so no real yfinance calls are made.
Verifies aggregate metrics (including calmar_ratio), plateau report structure,
and end-to-end main() execution.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_windows_v4(n_wins: int = 30, n_losses: int = 20) -> list:
    """Build fake WFO windows with enough OOS trades to pass the 40-trade gate.

    Trades are sequential (non-overlapping; 11-day gaps) so the portfolio
    position cap never fires.  Each dict contains every key emitted by
    TradeRecord.to_dict().
    """
    trades = []
    results = [(True, 2.0, 2.0, 0.4)] * n_wins + [(False, -1.0, -1.0, -0.2)] * n_losses
    base = date(2024, 1, 2)
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
    for i, (is_win, rr, pnl, portfolio_pnl) in enumerate(results):
        entry = base + timedelta(days=i * 11)   # 11-day gap → no overlap
        exit_ = entry + timedelta(days=10)
        trades.append({
            "ticker":            tickers[i % len(tickers)],
            "setup_type":        "VCP",
            "signal_date":       entry.isoformat(),
            "entry_date":        entry.isoformat(),
            "exit_date":         exit_.isoformat(),
            "entry_price":       100.0,
            "initial_stop":      95.0,
            "take_profit":       110.0,
            "exit_price":        110.0 if is_win else 95.0,
            "exit_reason":       "TARGET" if is_win else "STOP",
            "holding_days":      10,
            "rr_achieved":       rr,
            "pnl_pct":           pnl,
            "portfolio_pnl_pct": portfolio_pnl,
            "is_win":            is_win,
        })
    window = MagicMock()
    window.oos_trades = trades
    return [window]


def _make_overlapping_windows(n_trades: int = 20) -> list:
    """Build trades that all overlap (same entry/exit dates)."""
    entry = date(2024, 1, 2)
    exit_ = entry + timedelta(days=5)
    trades = [
        {
            "ticker":            f"TICK{i}",
            "setup_type":        "VCP",
            "signal_date":       entry.isoformat(),
            "entry_date":        entry.isoformat(),
            "exit_date":         exit_.isoformat(),
            "entry_price":       100.0,
            "initial_stop":      95.0,
            "take_profit":       110.0,
            "exit_price":        110.0,
            "exit_reason":       "TARGET",
            "holding_days":      5,
            "rr_achieved":       2.0,
            "pnl_pct":           2.0,
            "portfolio_pnl_pct": 0.4,
            "is_win":            True,
        }
        for i in range(n_trades)
    ]
    window = MagicMock()
    window.oos_trades = trades
    return [window]


def _fake_wfo_result(n_wins: int = 30, n_losses: int = 20):
    result = MagicMock()
    result.windows = _make_fake_windows_v4(n_wins, n_losses)
    return result


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_output_v4(tmp_path):
    """Redirect _OUTPUT_PATH and _STUDY_DB to temp directory."""
    import optimize_parameters_v4 as opt
    orig_output = opt._OUTPUT_PATH
    orig_db     = opt._STUDY_DB
    opt._OUTPUT_PATH = tmp_path / "best_parameters_v4.json"
    opt._STUDY_DB    = str(tmp_path / "optuna_study_v4.db")
    yield tmp_path
    opt._OUTPUT_PATH = orig_output
    opt._STUDY_DB    = orig_db


# ---------------------------------------------------------------------------
# 1. test_aggregate_v4_includes_calmar_ratio
# ---------------------------------------------------------------------------

def test_aggregate_v4_includes_calmar_ratio():
    """_aggregate_oos_metrics_v4 must include 'calmar_ratio' key."""
    from optimize_parameters_v4 import _aggregate_oos_metrics_v4

    windows = _make_fake_windows_v4(n_wins=30, n_losses=20)
    metrics = _aggregate_oos_metrics_v4(windows, max_positions=5)

    assert "calmar_ratio" in metrics, (
        f"'calmar_ratio' not found in metrics keys: {list(metrics.keys())}"
    )
    assert isinstance(metrics["calmar_ratio"], float)


# ---------------------------------------------------------------------------
# 2. test_aggregate_v4_respects_max_positions
# ---------------------------------------------------------------------------

def test_aggregate_v4_respects_max_positions():
    """Portfolio cap is enforced: overlapping trades are limited to max_positions."""
    from optimize_parameters_v4 import _aggregate_oos_metrics_v4

    n_overlapping = 20
    max_pos = 3
    windows = _make_overlapping_windows(n_trades=n_overlapping)

    metrics = _aggregate_oos_metrics_v4(windows, max_positions=max_pos)

    assert metrics["total_trades"] == max_pos, (
        f"Expected {max_pos} accepted trades (cap), got {metrics['total_trades']}"
    )


# ---------------------------------------------------------------------------
# 3. test_aggregate_v4_empty_windows
# ---------------------------------------------------------------------------

def test_aggregate_v4_empty_windows():
    """_aggregate_oos_metrics_v4 with no trades returns zeros, calmar_ratio=0.0."""
    from optimize_parameters_v4 import _aggregate_oos_metrics_v4

    window = MagicMock()
    window.oos_trades = []
    metrics = _aggregate_oos_metrics_v4([window], max_positions=5)

    assert metrics["total_trades"] == 0
    assert metrics["expectancy"] == 0.0
    assert metrics["calmar_ratio"] == 0.0


# ---------------------------------------------------------------------------
# 4. test_aggregate_v4_all_metric_keys
# ---------------------------------------------------------------------------

def test_aggregate_v4_all_metric_keys():
    """_aggregate_oos_metrics_v4 returns exactly the expected set of keys."""
    from optimize_parameters_v4 import _aggregate_oos_metrics_v4

    windows = _make_fake_windows_v4(n_wins=25, n_losses=15)
    metrics = _aggregate_oos_metrics_v4(windows, max_positions=5)

    expected = {
        "total_trades",
        "win_rate",
        "expectancy",
        "profit_factor",
        "max_drawdown_pct",
        "net_profit_pct",
        "calmar_ratio",
    }
    assert set(metrics.keys()) == expected, (
        f"Key mismatch: got {set(metrics.keys())}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# 5. test_plateau_report_structure
# ---------------------------------------------------------------------------

def test_plateau_report_structure():
    """_compute_plateau_report returns dict with all required top-level keys."""
    import optuna
    from optimize_parameters_v4 import _compute_plateau_report

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize", storage=None)

    # Add a few trials using a simple objective so we have COMPLETE trials
    def simple_obj(trial):
        x = trial.suggest_float("ATR_MULTIPLIER", 1.20, 1.60)
        trial.suggest_float("VCP_TIGHTNESS_RANGE",   0.035, 0.070)
        trial.suggest_float("BREAKOUT_BUFFER_ATR",   0.30,  0.55)
        trial.suggest_float("BREAKOUT_VOL_MULT",     0.80,  1.30)
        trial.suggest_float("TARGET_RR",             2.20,  2.80)
        trial.suggest_float("TRAIL_ATR_MULT",        2.50,  4.50)
        trial.suggest_int(  "REGIME_BULL_THRESHOLD", 45,    65)
        trial.suggest_float("ENGINE3_RS_THRESHOLD",  -0.10, 0.00)
        trial.suggest_int(  "MAX_OPEN_POSITIONS",    3,     5)
        trial.suggest_float("CCI_STRICT_FLOOR",      -80.0, -20.0)
        trial.suggest_float("CCI_RLX_FLOOR",         -40.0,  0.0)
        return x

    study.optimize(simple_obj, n_trials=5)

    report = _compute_plateau_report(study)

    required_keys = {
        "plateau_count",
        "total_completed",
        "threshold",
        "best_score",
        "per_param",
        "ceiling_flags",
    }
    assert required_keys.issubset(set(report.keys())), (
        f"Missing keys: {required_keys - set(report.keys())}"
    )
    assert isinstance(report["per_param"], dict)
    assert isinstance(report["ceiling_flags"], list)


# ---------------------------------------------------------------------------
# 6. test_plateau_report_threshold_is_80pct_of_best
# ---------------------------------------------------------------------------

def test_plateau_report_threshold_is_80pct_of_best():
    """threshold must be exactly 0.80 * best_score."""
    import optuna
    from optimize_parameters_v4 import _compute_plateau_report

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize", storage=None)

    def simple_obj(trial):
        x = trial.suggest_float("ATR_MULTIPLIER", 1.20, 1.60)
        trial.suggest_float("VCP_TIGHTNESS_RANGE",   0.035, 0.070)
        trial.suggest_float("BREAKOUT_BUFFER_ATR",   0.30,  0.55)
        trial.suggest_float("BREAKOUT_VOL_MULT",     0.80,  1.30)
        trial.suggest_float("TARGET_RR",             2.20,  2.80)
        trial.suggest_float("TRAIL_ATR_MULT",        2.50,  4.50)
        trial.suggest_int(  "REGIME_BULL_THRESHOLD", 45,    65)
        trial.suggest_float("ENGINE3_RS_THRESHOLD",  -0.10, 0.00)
        trial.suggest_int(  "MAX_OPEN_POSITIONS",    3,     5)
        trial.suggest_float("CCI_STRICT_FLOOR",      -80.0, -20.0)
        trial.suggest_float("CCI_RLX_FLOOR",         -40.0,  0.0)
        return x

    study.optimize(simple_obj, n_trials=5)

    report = _compute_plateau_report(study)
    best_score = report["best_score"]
    threshold  = report["threshold"]

    # Both threshold and best_score are rounded to 6 dp in _compute_plateau_report,
    # so allow a tolerance of 1e-6 to absorb rounding artefacts.
    assert abs(threshold - 0.80 * best_score) < 1e-6, (
        f"Expected threshold == 0.80 * {best_score} = {0.80 * best_score}, got {threshold}"
    )


# ---------------------------------------------------------------------------
# 7. test_main_v4_creates_best_parameters_json
# ---------------------------------------------------------------------------

def test_main_v4_creates_best_parameters_json(tmp_output_v4):
    """main(n_trials=2) with mocked WFO creates a valid JSON with all 11 param keys."""
    import optimize_parameters_v4 as opt

    fake_result = _fake_wfo_result(n_wins=30, n_losses=20)

    async def fake_run_wfo(**kwargs):
        return fake_result

    with patch.object(opt, "run_wfo", side_effect=fake_run_wfo), \
         patch.object(opt, "REPRESENTATIVE_TICKERS", ["AAPL", "MSFT"]):
        opt.main(n_trials=2, suppress_output=True)

    out_path = tmp_output_v4 / "best_parameters_v4.json"
    assert out_path.exists(), "best_parameters_v4.json was not created"

    data = json.loads(out_path.read_text())

    # Top-level structure
    assert "parameters"     in data
    assert "oos_metrics"    in data
    assert "best_score"     in data
    assert "generated_at"   in data
    assert "plateau_report" in data

    # calmar_ratio must appear in oos_metrics
    assert "calmar_ratio" in data["oos_metrics"], (
        f"calmar_ratio missing from oos_metrics: {list(data['oos_metrics'].keys())}"
    )

    # All 11 parameter keys
    params = data["parameters"]
    expected_param_keys = {
        "ATR_MULTIPLIER",
        "VCP_TIGHTNESS_RANGE",
        "BREAKOUT_BUFFER_ATR",
        "BREAKOUT_VOL_MULT",
        "TARGET_RR",
        "TRAIL_ATR_MULT",
        "REGIME_BULL_THRESHOLD",
        "ENGINE3_RS_THRESHOLD",
        "MAX_OPEN_POSITIONS",
        "CCI_STRICT_FLOOR",
        "CCI_RLX_FLOOR",
    }
    assert set(params.keys()) == expected_param_keys, (
        f"Param key mismatch: got {set(params.keys())}, expected {expected_param_keys}"
    )

    # v4-specific bounds verification
    assert 2.50 <= params["TRAIL_ATR_MULT"]       <= 4.50, \
        f"TRAIL_ATR_MULT out of v4 range: {params['TRAIL_ATR_MULT']}"
    assert 45 <= params["REGIME_BULL_THRESHOLD"]  <= 65, \
        f"REGIME_BULL_THRESHOLD out of v4 range: {params['REGIME_BULL_THRESHOLD']}"
    assert 3 <= params["MAX_OPEN_POSITIONS"]      <= 5, \
        f"MAX_OPEN_POSITIONS out of v4 range: {params['MAX_OPEN_POSITIONS']}"
    assert -80.0 <= params["CCI_STRICT_FLOOR"]    <= -20.0, \
        f"CCI_STRICT_FLOOR out of v4 range: {params['CCI_STRICT_FLOOR']}"
    assert -40.0 <= params["CCI_RLX_FLOOR"]       <= 0.0, \
        f"CCI_RLX_FLOOR out of v4 range: {params['CCI_RLX_FLOOR']}"


# ---------------------------------------------------------------------------
# 8. test_v4_study_defaults
# ---------------------------------------------------------------------------

def test_v4_study_defaults():
    """Optimizer must default to v4 study name and 400 trials."""
    import importlib
    import optimize_parameters_v4 as opt
    importlib.reload(opt)

    assert opt._STUDY_NAME    == "trading_optimizer_v4", \
        f"Expected 'trading_optimizer_v4', got '{opt._STUDY_NAME}'"
    assert opt._DEFAULT_TRIALS == 400, \
        f"Expected 400, got {opt._DEFAULT_TRIALS}"
