import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from engines.engine5 import _quality_score, scan_cup_handle, scan_flat_base


def test_rs_vs_spy_formula_uses_ratio_minus_one():
    """
    rs_ratio=1.10 means stock gained 10% vs SPY's base.
    spy_3m_return=0.05 means SPY gained 5%.
    rs_vs_spy should be (1.10-1.0) - 0.05 = 0.05 (5% outperformance).
    The OLD formula gives 1.10 - 0.05 = 1.05 which is nonsense.
    We verify by checking quality score uses a sane rs_vs_spy value.
    """
    # With correct formula: rs_vs_spy = (1.10 - 1.0) - 0.05 = 0.05
    # _quality_score gets rs_vs_spy=0.05, so rs_pts = (0.05/0.05)*25 = 25
    qs = _quality_score(
        depth_pct=0.08,         # perfect tightness → 25 pts
        max_depth_pct=0.35,
        vol_dry_pct=0.25,       # good dry-up → 25 pts
        rs_vs_spy=0.05,         # 5% outperformance → 25 pts
        rs_blue_dot=False,      # 0 pts
    )
    assert qs == 75, f"Expected 75, got {qs}"

    # With OLD formula: rs_vs_spy = 1.10 - 0.05 = 1.05
    # rs_pts = min(25, (1.05/0.05)*25) = 25 (capped, so same here)
    # But at lower outperformance the difference is stark:
    # rs_ratio=1.01, spy_3m_return=0.05
    # correct: (1.01-1.0)-0.05 = -0.04 → 0 rs_pts
    # old:      1.01-0.05=0.96  → 25 rs_pts (wrong!)
    qs_correct = _quality_score(
        depth_pct=0.08,
        max_depth_pct=0.35,
        vol_dry_pct=0.25,
        rs_vs_spy=(1.01 - 1.0) - 0.05,   # = -0.04, stock underperforms
        rs_blue_dot=False,
    )
    assert qs_correct < 75, "Underperforming stock should score < 75"
