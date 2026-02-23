import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
from engines.engine2 import _count_contractions


def test_equal_tr_values_not_progressive():
    """Equal TR values must NOT count as progressively tighter."""
    # Three contractions with equal TR — should NOT be progressive
    tr = pd.Series([2.0] * 25 + [1.0, 1.0, 1.0, 0.5, 0.5])
    count, pattern, is_progressive = _count_contractions(tr, lookback=25)
    assert count >= 3
    assert is_progressive is False, "Equal TR values should not be progressive"


def test_strictly_decreasing_tr_is_progressive():
    """Strictly decreasing TR values must be progressive."""
    tr = pd.Series([2.0] * 25 + [1.0, 0.9, 0.8, 0.7, 0.6])
    count, pattern, is_progressive = _count_contractions(tr, lookback=25)
    assert count >= 3
    assert is_progressive is True
