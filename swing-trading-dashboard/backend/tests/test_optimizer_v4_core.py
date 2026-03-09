"""Tests for v4 score function and _patch_constants in optimize_parameters_v4."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))


# ── Score function tests ───────────────────────────────────────────────────────

def test_v4_score_penalizes_few_trades():
    from optimize_parameters_v4 import _compute_robustness_score_v4
    assert _compute_robustness_score_v4(0.5, 1.8, 30, 5.0, 10.0) == -5.0

def test_v4_score_penalizes_high_drawdown():
    from optimize_parameters_v4 import _compute_robustness_score_v4
    # > 20% DD → -10.0
    assert _compute_robustness_score_v4(0.5, 1.8, 80, 21.0, 15.0) == -10.0

def test_v4_score_penalizes_losing_system():
    from optimize_parameters_v4 import _compute_robustness_score_v4
    # profit_factor < 1.0 → -3.0
    assert _compute_robustness_score_v4(0.1, 0.9, 80, 5.0, 2.0) == -3.0

def test_v4_score_exactly_20pct_dd_is_allowed():
    from optimize_parameters_v4 import _compute_robustness_score_v4
    # exactly 20.0% DD: NOT penalized (> 20.0 triggers, not >=)
    score = _compute_robustness_score_v4(0.3, 1.5, 60, 20.0, 10.0)
    assert score > 0

def test_v4_score_formula_correct():
    from optimize_parameters_v4 import _compute_robustness_score_v4
    e, pf, n, dd, net = 0.4, 1.6, 100, 10.0, 13.0
    expected = (e * pf * math.sqrt(n)) / (1.0 + dd * 4.0)
    score = _compute_robustness_score_v4(e, pf, n, dd, net)
    assert abs(score - expected) < 1e-9

def test_v4_score_stronger_dd_penalty_than_v3():
    """v4 must penalise DD more aggressively than v3 for same inputs."""
    from optimize_parameters_v4 import _compute_robustness_score_v4
    from optimize_parameters import _compute_robustness_score as v3_score
    args = dict(expectancy=0.3, profit_factor=1.5, total_trades=80, max_drawdown_pct=15.0)
    v4 = _compute_robustness_score_v4(**args, net_profit_pct=10.0)
    v3 = v3_score(**args)
    assert v4 < v3, f"v4 score ({v4:.4f}) should be lower than v3 ({v3:.4f}) at high DD"

def test_v4_score_boundary_exactly_40_trades():
    from optimize_parameters_v4 import _compute_robustness_score_v4
    score = _compute_robustness_score_v4(0.3, 1.5, 40, 8.0, 5.0)
    assert score > 0  # not penalized

def test_v4_score_low_dd_preferred():
    """Lower DD should produce higher score (all else equal)."""
    from optimize_parameters_v4 import _compute_robustness_score_v4
    score_low_dd  = _compute_robustness_score_v4(0.3, 1.5, 80, 5.0, 8.0)
    score_high_dd = _compute_robustness_score_v4(0.3, 1.5, 80, 10.0, 8.0)
    assert score_low_dd > score_high_dd


# ── Patch mechanism tests ──────────────────────────────────────────────────────

def _v4_params(**overrides):
    """Return a complete v4 params dict with all 11 keys."""
    base = {
        "ATR_MULTIPLIER":        1.40,
        "VCP_TIGHTNESS_RANGE":   0.045,
        "BREAKOUT_BUFFER_ATR":   0.45,
        "BREAKOUT_VOL_MULT":     1.10,
        "TARGET_RR":             2.50,
        "TRAIL_ATR_MULT":        3.00,
        "REGIME_BULL_THRESHOLD": 55,
        "ENGINE3_RS_THRESHOLD":  -0.03,
        "MAX_OPEN_POSITIONS":    4,
        "CCI_STRICT_FLOOR":      -60.0,
        "CCI_RLX_FLOOR":         -15.0,
    }
    base.update(overrides)
    return base


def test_patch_cci_strict_floor_constants_and_engine3():
    """_patch_constants must update both constants.CCI_STRICT_FLOOR and engine3.CCI_STRICT_FLOOR."""
    import constants
    import engines.engine3 as e3
    from optimize_parameters_v4 import _patch_constants

    orig_const = constants.CCI_STRICT_FLOOR
    orig_e3    = e3.CCI_STRICT_FLOOR
    new_val    = -65.0

    with _patch_constants(_v4_params(CCI_STRICT_FLOOR=new_val)):
        assert constants.CCI_STRICT_FLOOR == new_val, \
            f"constants.CCI_STRICT_FLOOR not patched: {constants.CCI_STRICT_FLOOR}"
        assert e3.CCI_STRICT_FLOOR == new_val, \
            f"engine3.CCI_STRICT_FLOOR not patched: {e3.CCI_STRICT_FLOOR}"

    assert constants.CCI_STRICT_FLOOR == orig_const
    assert e3.CCI_STRICT_FLOOR == orig_e3


def test_patch_cci_rlx_floor_constants_and_engine3():
    """_patch_constants must update both constants.CCI_RLX_FLOOR and engine3.CCI_RLX_FLOOR."""
    import constants
    import engines.engine3 as e3
    from optimize_parameters_v4 import _patch_constants

    orig_const = constants.CCI_RLX_FLOOR
    orig_e3    = e3.CCI_RLX_FLOOR
    new_val    = -30.0

    with _patch_constants(_v4_params(CCI_RLX_FLOOR=new_val)):
        assert constants.CCI_RLX_FLOOR == new_val
        assert e3.CCI_RLX_FLOOR == new_val

    assert constants.CCI_RLX_FLOOR == orig_const
    assert e3.CCI_RLX_FLOOR == orig_e3


def test_patch_max_open_positions_constants_and_wfo_engine():
    """_patch_constants must update constants.MAX_OPEN_POSITIONS and wfo_engine.MAX_OPEN_POSITIONS."""
    import constants
    import wfo_engine
    from optimize_parameters_v4 import _patch_constants

    orig_const = constants.MAX_OPEN_POSITIONS
    orig_wfo   = wfo_engine.MAX_OPEN_POSITIONS
    new_val    = 3

    with _patch_constants(_v4_params(MAX_OPEN_POSITIONS=new_val)):
        assert constants.MAX_OPEN_POSITIONS == new_val
        assert wfo_engine.MAX_OPEN_POSITIONS == new_val

    assert constants.MAX_OPEN_POSITIONS == orig_const
    assert wfo_engine.MAX_OPEN_POSITIONS == orig_wfo


def test_patch_restores_all_on_exception():
    """_patch_constants restores all values even when an exception is raised."""
    import constants
    from optimize_parameters_v4 import _patch_constants

    orig_cci_strict = constants.CCI_STRICT_FLOOR
    orig_cci_rlx    = constants.CCI_RLX_FLOOR
    orig_max_pos    = constants.MAX_OPEN_POSITIONS

    try:
        with _patch_constants(_v4_params(CCI_STRICT_FLOOR=-70.0, CCI_RLX_FLOOR=-25.0, MAX_OPEN_POSITIONS=3)):
            raise RuntimeError("simulated failure")
    except RuntimeError:
        pass

    assert constants.CCI_STRICT_FLOOR   == orig_cci_strict
    assert constants.CCI_RLX_FLOOR      == orig_cci_rlx
    assert constants.MAX_OPEN_POSITIONS == orig_max_pos
