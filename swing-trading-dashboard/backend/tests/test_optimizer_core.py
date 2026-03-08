"""Tests for _patch_constants context manager and _compute_robustness_score."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import math
import importlib


def _force_import(mod_name: str):
    """Import and return a module, reusing sys.modules if present."""
    if mod_name not in sys.modules:
        importlib.import_module(mod_name)
    return sys.modules[mod_name]


# ── Patching tests ────────────────────────────────────────────────────────────

def test_patch_atr_multiplier_and_restore():
    """_patch_constants should set engine2.ATR_STOP_MULTIPLIER and restore it."""
    from optimize_parameters import _patch_constants
    import engines.engine2 as e2

    original = e2.ATR_STOP_MULTIPLIER
    params = {
        "ATR_MULTIPLIER":        0.6,
        "VCP_TIGHTNESS_RANGE":   0.025,
        "BREAKOUT_BUFFER_ATR":   0.25,
        "BREAKOUT_VOL_MULT":     1.5,
        "TARGET_RR":             2.0,
        "TRAIL_ATR_MULT":        1.5,
        "REGIME_BULL_THRESHOLD": 40,
    }
    with _patch_constants(params):
        assert e2.ATR_STOP_MULTIPLIER == 0.6
    assert e2.ATR_STOP_MULTIPLIER == original


def test_patch_breakout_vol_mult_sets_threshold():
    """_patch_constants should set engine6._VOL_SURGE_THRESHOLD."""
    from optimize_parameters import _patch_constants
    import engines.engine6 as e6

    original_threshold = e6._VOL_SURGE_THRESHOLD
    params = {
        "ATR_MULTIPLIER":        0.8,
        "VCP_TIGHTNESS_RANGE":   0.025,
        "BREAKOUT_BUFFER_ATR":   0.25,
        "BREAKOUT_VOL_MULT":     1.8,
        "TARGET_RR":             2.0,
        "TRAIL_ATR_MULT":        1.5,
        "REGIME_BULL_THRESHOLD": 40,
    }
    with _patch_constants(params):
        assert e6._VOL_SURGE_THRESHOLD == 1.8
    assert e6._VOL_SURGE_THRESHOLD == original_threshold


def test_patch_restores_on_exception():
    """_patch_constants must restore even when an exception is raised inside."""
    from optimize_parameters import _patch_constants
    import engines.engine2 as e2

    original = e2.ATR_STOP_MULTIPLIER
    params = {
        "ATR_MULTIPLIER":        0.5,
        "VCP_TIGHTNESS_RANGE":   0.025,
        "BREAKOUT_BUFFER_ATR":   0.25,
        "BREAKOUT_VOL_MULT":     1.5,
        "TARGET_RR":             2.0,
        "TRAIL_ATR_MULT":        1.5,
        "REGIME_BULL_THRESHOLD": 40,
    }
    try:
        with _patch_constants(params):
            raise ValueError("simulated failure")
    except ValueError:
        pass
    assert e2.ATR_STOP_MULTIPLIER == original


# ── Robustness score tests ─────────────────────────────────────────────────────

def test_robustness_score_penalizes_few_trades():
    """Returns -5.0 when total_trades < 30."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.5, profit_factor=1.8,
        total_trades=20, max_drawdown_pct=10.0,
    )
    assert score == -5.0


def test_robustness_score_penalizes_high_drawdown():
    """Returns -10.0 when max_drawdown_pct > 35.0."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.5, profit_factor=1.8,
        total_trades=100, max_drawdown_pct=40.0,
    )
    assert score == -10.0


def test_robustness_score_formula():
    """Verify formula: (e * pf * sqrt(n)) / (1 + dd * 2.5)."""
    from optimize_parameters import _compute_robustness_score
    expectancy = 0.4
    profit_factor = 1.6
    total_trades = 100
    max_dd = 10.0
    expected = (expectancy * profit_factor * math.sqrt(total_trades)) / (1.0 + max_dd * 2.5)
    score = _compute_robustness_score(
        expectancy=expectancy,
        profit_factor=profit_factor,
        total_trades=total_trades,
        max_drawdown_pct=max_dd,
    )
    assert abs(score - expected) < 1e-9


def test_robustness_score_boundary_exactly_40_trades():
    """Exactly 40 trades should not be penalized."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.3, profit_factor=1.5,
        total_trades=40, max_drawdown_pct=8.0,
    )
    assert score > 0  # not penalized


def test_robustness_score_boundary_exactly_35pct_drawdown():
    """Exactly 35.0% drawdown is on the boundary — must NOT be penalized."""
    from optimize_parameters import _compute_robustness_score
    score = _compute_robustness_score(
        expectancy=0.3, profit_factor=1.5,
        total_trades=50, max_drawdown_pct=35.0,
    )
    assert score > 0  # drawdown == 20.0 is allowed; penalty only for > 20
