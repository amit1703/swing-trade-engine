"""Tests for wfo_optuna.py pure functions."""
import os
import sys
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Window constants ──────────────────────────────────────────────────────────

def test_wfo_windows_count():
    from wfo_optuna import WFO_WINDOWS
    assert len(WFO_WINDOWS) == 4


def test_wfo_windows_structure():
    from wfo_optuna import WFO_WINDOWS
    for win_num, is_start, is_end, oos_start, oos_end in WFO_WINDOWS:
        # IS ends where OOS begins
        assert is_end == oos_start
        # OOS is 12 months
        is_s = pd.Timestamp(oos_start)
        is_e = pd.Timestamp(oos_end)
        months = (is_e.year - is_s.year) * 12 + (is_e.month - is_s.month)
        assert months == 12, f"OOS window {win_num} should be 12 months"


def test_wfo_windows_oos_non_overlapping():
    from wfo_optuna import WFO_WINDOWS
    for i in range(len(WFO_WINDOWS) - 1):
        _, _, _, _, oos_end_i = WFO_WINDOWS[i]
        _, _, _, oos_start_next, _ = WFO_WINDOWS[i + 1]
        assert pd.Timestamp(oos_end_i) == pd.Timestamp(oos_start_next), \
            f"Gap between OOS windows {i} and {i+1}"


def test_wfo_windows_starts_2019():
    from wfo_optuna import WFO_WINDOWS
    assert WFO_WINDOWS[0][1] == "2019-01-01"


# ── Objective score ───────────────────────────────────────────────────────────

def test_objective_score_positive():
    from wfo_optuna import _objective_score, MIN_TRADES
    metrics = {
        "total_trades": MIN_TRADES + 50,
        "expectancy": 0.25,
        "profit_factor": 1.8,
    }
    score = _objective_score(metrics)
    assert score > 0


def test_objective_score_penalty_low_trades():
    from wfo_optuna import _objective_score, MIN_TRADES, PENALTY_SCORE
    metrics = {
        "total_trades": MIN_TRADES - 1,
        "expectancy": 0.5,
        "profit_factor": 2.0,
    }
    assert _objective_score(metrics) == PENALTY_SCORE


def test_objective_score_negative_expectancy():
    from wfo_optuna import _objective_score, MIN_TRADES
    metrics = {
        "total_trades": MIN_TRADES + 50,
        "expectancy": -0.1,
        "profit_factor": 0.9,
    }
    score = _objective_score(metrics)
    assert score < 0


# ── Build params from values ──────────────────────────────────────────────────

def test_build_params_from_values_uses_provided():
    from wfo_optuna import _build_params_from_values
    values = {
        "tp_multiple":   3.5,
        "brk_vol_mult":  2.0,
        "brk_stop_atr":  1.0,
        "brk_min_pct":   0.02,
        "brk_gap_pct":   0.03,
        "brk_trail_mult": 4.0,
    }
    p = _build_params_from_values(values)
    assert abs(p.tp_multiple - 3.5) < 1e-9
    assert abs(p.brk_vol_mult - 2.0) < 1e-9
    assert abs(p.brk_trail_mult - 4.0) < 1e-9


def test_build_params_from_values_frozen_defaults():
    from wfo_optuna import _build_params_from_values
    values = {
        "tp_multiple":   4.0,
        "brk_vol_mult":  2.5,
        "brk_stop_atr":  1.0,
        "brk_min_pct":   0.03,
        "brk_gap_pct":   0.02,
        "brk_trail_mult": 5.0,
    }
    p = _build_params_from_values(values)
    assert abs(p.rs_threshold - 0.066) < 1e-9
    assert abs(p.cci_threshold - (-54.5)) < 1e-9
    assert abs(p.ema_distance - 1.651) < 1e-9
    assert p.cooldown_days == 4


def test_frozen_params_equals_defaults():
    from wfo_optuna import _frozen_params
    from backtest_engine import BacktestParams
    frozen = _frozen_params()
    defaults = BacktestParams()
    assert frozen.tp_multiple == defaults.tp_multiple
    assert frozen.brk_vol_mult == defaults.brk_vol_mult
    assert frozen.rs_threshold == defaults.rs_threshold


# ── Sparkline ─────────────────────────────────────────────────────────────────

def test_sparkline_length_matches_input():
    from wfo_optuna import _sparkline
    values = [1.0, 2.5, 0.5, 3.0, 1.5]
    result = _sparkline(values)
    assert len(result) == len(values)


def test_sparkline_empty():
    from wfo_optuna import _sparkline
    assert _sparkline([]) == ""


def test_sparkline_constant_values():
    from wfo_optuna import _sparkline
    result = _sparkline([5.0, 5.0, 5.0])
    assert len(result) == 3
    assert len(set(result)) == 1


# ── SPY return ────────────────────────────────────────────────────────────────

def test_spy_return_none_when_spy_none():
    from wfo_optuna import _spy_return
    assert _spy_return(None, "2023-01-01", "2023-12-31") is None


def test_spy_return_computes_correctly():
    from wfo_optuna import _spy_return
    dates = pd.date_range("2023-01-01", "2023-12-31", freq="B")
    close = pd.Series([100.0] + [110.0] * (len(dates) - 1), index=dates)
    df = pd.DataFrame({"Close": close, "Adj Close": close})
    result = _spy_return(df, "2023-01-01", "2023-12-31")
    assert result is not None
    assert abs(result - 0.10) < 1e-6


# ── Compute metrics ───────────────────────────────────────────────────────────

def test_compute_metrics_empty():
    from wfo_optuna import _compute_metrics
    m = _compute_metrics([])
    assert m["total_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["expectancy"] == 0.0


def test_compute_metrics_basic():
    from wfo_optuna import _compute_metrics
    trades = [
        {"rr_achieved": 2.0, "setup_type": "PULLBACK", "portfolio_pnl_pct": 2.0, "exit_date": "2023-01-10"},
        {"rr_achieved": 2.0, "setup_type": "PULLBACK", "portfolio_pnl_pct": 2.0, "exit_date": "2023-01-15"},
        {"rr_achieved": -1.0, "setup_type": "PULLBACK", "portfolio_pnl_pct": -1.0, "exit_date": "2023-01-20"},
    ]
    m = _compute_metrics(trades)
    assert m["total_trades"] == 3
    assert abs(m["win_rate"] - 66.7) < 0.1
    assert m["profit_factor"] > 1.0
    assert m["expectancy"] > 0
    assert m["max_drawdown_r"] <= 0
    assert abs(m["profit_factor"] - 4.0) < 0.01   # gross_win=4.0, gross_loss=1.0
    assert abs(m["expectancy"] - 1.0) < 0.01       # (2+2-1)/3 = 1.0
    assert abs(m["max_drawdown_r"] - (-1.0)) < 0.01  # runs to -1 after 2+2 then hit -1
