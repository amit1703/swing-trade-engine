"""
Integration smoke test for optimize_parameters.py.

Mocks run_wfo so no real yfinance calls are made.
Verifies that main() runs end-to-end and exports a valid best_parameters.json.
"""
from __future__ import annotations

import json
import sys
import types
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))


def _make_fake_windows(n_wins: int = 25, n_losses: int = 20) -> list:
    """Build fake WFO windows with enough OOS trades to pass the 40-trade gate.

    Trades are sequential (non-overlapping) so the portfolio position cap
    does not filter any of them out. Each dict matches TradeRecord.to_dict().
    """
    from datetime import date, timedelta
    trades = []
    # Alternate wins and losses; assign sequential non-overlapping dates
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


def _fake_wfo_result(n_wins: int = 20, n_losses: int = 15):
    result = MagicMock()
    result.windows = _make_fake_windows(n_wins, n_losses)
    return result


@pytest.fixture()
def tmp_output(tmp_path):
    """Redirect _OUTPUT_PATH and _STUDY_DB to temp directory."""
    import optimize_parameters as opt
    orig_output = opt._OUTPUT_PATH
    orig_db     = opt._STUDY_DB
    opt._OUTPUT_PATH = tmp_path / "best_parameters.json"
    opt._STUDY_DB    = str(tmp_path / "optuna_study.db")
    yield tmp_path
    opt._OUTPUT_PATH = orig_output
    opt._STUDY_DB    = orig_db


def test_main_creates_best_parameters_json(tmp_output):
    """main(n_trials=2) with mocked WFO should produce a valid JSON output file."""
    import optimize_parameters as opt

    fake_result = _fake_wfo_result()

    async def fake_run_wfo(**kwargs):
        return fake_result

    with patch.object(opt, "run_wfo", side_effect=fake_run_wfo), \
         patch.object(opt, "REPRESENTATIVE_TICKERS", ["AAPL", "MSFT"]):
        opt.main(n_trials=2, suppress_output=True)

    out_path = tmp_output / "best_parameters.json"
    assert out_path.exists(), "best_parameters.json was not created"

    data = json.loads(out_path.read_text())
    assert "parameters"  in data
    assert "oos_metrics" in data
    assert "best_score"  in data
    assert "generated_at" in data

    params = data["parameters"]
    expected_keys = {
        "ATR_MULTIPLIER", "VCP_TIGHTNESS_RANGE", "BREAKOUT_BUFFER_ATR",
        "BREAKOUT_VOL_MULT", "TARGET_RR", "TRAIL_ATR_MULT",
        "REGIME_BULL_THRESHOLD",
    }
    assert set(params.keys()) == expected_keys, f"Missing/extra keys: {set(params.keys()) ^ expected_keys}"

    # v3: verify parameter values fall within the new narrower search bounds
    assert 1.20 <= params["ATR_MULTIPLIER"]       <= 1.60, f"ATR_MULTIPLIER out of v3 range: {params['ATR_MULTIPLIER']}"
    assert 1.80 <= params["TRAIL_ATR_MULT"]       <= 3.00, f"TRAIL_ATR_MULT out of v3 range: {params['TRAIL_ATR_MULT']}"
    assert 0.80 <= params["BREAKOUT_VOL_MULT"]    <= 1.30, f"BREAKOUT_VOL_MULT out of v3 range: {params['BREAKOUT_VOL_MULT']}"
    assert 0.035 <= params["VCP_TIGHTNESS_RANGE"] <= 0.070, f"VCP_TIGHTNESS_RANGE out of v3 range: {params['VCP_TIGHTNESS_RANGE']}"
    assert 0.30 <= params["BREAKOUT_BUFFER_ATR"]  <= 0.50, f"BREAKOUT_BUFFER_ATR out of v3 range: {params['BREAKOUT_BUFFER_ATR']}"
    assert 2.20 <= params["TARGET_RR"]            <= 2.80, f"TARGET_RR out of v3 range: {params['TARGET_RR']}"
    assert 20 <= params["REGIME_BULL_THRESHOLD"] <= 55, f"REGIME_BULL_THRESHOLD out of range: {params['REGIME_BULL_THRESHOLD']}"


def test_main_zero_trials_no_crash(tmp_output):
    """main(n_trials=0) should not crash when study has no completed trials."""
    import optimize_parameters as opt

    async def fake_run_wfo(**kwargs):
        return _fake_wfo_result()

    with patch.object(opt, "run_wfo", side_effect=fake_run_wfo), \
         patch.object(opt, "REPRESENTATIVE_TICKERS", ["AAPL"]):
        # 0 trials → no optimization → no best trial → should exit cleanly
        opt.main(n_trials=0, suppress_output=True)

    # No JSON written (no trials completed)
    assert not (tmp_output / "best_parameters.json").exists()


def test_oos_metrics_keys():
    """_aggregate_oos_metrics should return all expected metric keys."""
    from optimize_parameters import _aggregate_oos_metrics
    windows = _make_fake_windows(n_wins=20, n_losses=15)
    metrics = _aggregate_oos_metrics(windows)
    expected = {"total_trades", "win_rate", "expectancy", "profit_factor",
                "max_drawdown_pct", "net_profit_pct"}
    assert set(metrics.keys()) == expected


def test_oos_metrics_empty_windows():
    """_aggregate_oos_metrics with no trades returns zeros, not errors."""
    from optimize_parameters import _aggregate_oos_metrics
    window = MagicMock()
    window.oos_trades = []
    metrics = _aggregate_oos_metrics([window])
    assert metrics["total_trades"] == 0
    assert metrics["expectancy"] == 0.0
