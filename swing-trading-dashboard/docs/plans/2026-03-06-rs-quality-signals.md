# RS Quality Signals Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Relax RS hard-reject filters in VCP engine and add RS momentum/quality signals as soft scoring components, surfacing early leaders that were previously rejected.

**Architecture:** Four-layer change — (1) new `get_rs_signals()` function in engine4.py computes three RS quality flags; (2) engine2.py removes three hard RS gates and accepts the new flags + computes `tight_range_5d` internally; (3) main.py wires the new flags into the scan_vcp call; (4) scoring.py adds a new `_rs_quality_component()` scoring bucket (max 20 pts) and a new constant in constants.py.

**Tech Stack:** Python, pandas, numpy. No new dependencies.

---

## Key facts about the existing codebase

- `backend/engines/engine4.py` — RS computation authority. `get_rs_stats()` ends at line ~221.
- `backend/engines/engine2.py` — Three hard RS gates to remove:
  - **Line 777**: `if resistance_zones and is_vol_surge and rs_score > 0:` — remove `and rs_score > 0`
  - **Line 940**: `rs_vs_spy >= 0` inside `is_kde_breakout` tuple — remove that condition
  - **Lines 1064–1070**: `if rs_score < 0: return None` block — delete entirely
- `backend/main.py` — scan_vcp called at line 1747. rs_line computed at line 1717.
- `backend/scoring.py` — `compute_setup_score()` at line 313. `_quality_component()` at line 291.
- `backend/constants.py` — Scoring weights at lines 78–83. `SCORE_WEIGHT_QUALITY = 5`.

---

## Task 1: Add `get_rs_signals()` to engine4.py

**Files:**
- Modify: `backend/engines/engine4.py` (after line 221, i.e. after `get_rs_stats()`)
- Test: `backend/tests/test_rs_signals.py` (new)

**Step 1: Write the failing test**

Create `backend/tests/test_rs_signals.py`:

```python
"""Tests for engine4.get_rs_signals() — run with: pytest backend/tests/test_rs_signals.py -v"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engines.engine4 import get_rs_signals


def _flat_line(n=100, value=1.0):
    return [value] * n


def test_rs_improving_true_when_trending_up():
    rs_line = list(range(1, 101))   # rs[-1]=100 > rs[-10]=91 → improving
    result = get_rs_signals(rs_line)
    assert result["rs_improving"] is True


def test_rs_improving_false_when_flat():
    result = get_rs_signals(_flat_line())
    assert result["rs_improving"] is False


def test_rs_improving_false_when_declining():
    rs_line = list(range(100, 0, -1))  # rs[-1]=1 < rs[-10]=10
    result = get_rs_signals(rs_line)
    assert result["rs_improving"] is False


def test_rs_near_high_true_when_at_peak():
    rs_line = [1.0] * 59 + [1.5]   # last value = max = near high
    result = get_rs_signals(rs_line)
    assert result["rs_near_high"] is True


def test_rs_near_high_false_when_far_from_peak():
    rs_line = [1.5] * 59 + [1.0]   # current 1.0 < 0.9 * 1.5 = 1.35
    result = get_rs_signals(rs_line)
    assert result["rs_near_high"] is False


def test_rs_acceleration_positive_on_strong_rise():
    # rs[-10]=1.0, rs[-1]=1.15 → accel = (1.15-1.0)/1.0 = 0.15 > 0.10
    rs_line = [1.0] * 90 + [1.0] * 9 + [1.15]
    result = get_rs_signals(rs_line)
    assert result["rs_acceleration"] > 0.10


def test_rs_acceleration_negative_on_decline():
    rs_line = [1.1] * 90 + [1.1] * 9 + [1.0]
    result = get_rs_signals(rs_line)
    assert result["rs_acceleration"] < 0


def test_short_line_returns_safe_defaults():
    result = get_rs_signals([1.0, 1.1])   # too short for 10-bar lookback
    assert result["rs_improving"] is False
    assert result["rs_near_high"] is False
    assert result["rs_acceleration"] == 0.0


def test_empty_line_returns_safe_defaults():
    result = get_rs_signals([])
    assert result["rs_improving"] is False
    assert result["rs_near_high"] is False
    assert result["rs_acceleration"] == 0.0
```

**Step 2: Run test to verify it fails**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard\backend
python -m pytest tests/test_rs_signals.py -v
```
Expected: ImportError or AttributeError — `get_rs_signals` does not exist yet.

**Step 3: Implement `get_rs_signals()` in engine4.py**

Add this function at the END of `backend/engines/engine4.py` (after the `get_rs_stats()` function, around line 222):

```python
def get_rs_signals(rs_line: List[float]) -> dict:
    """
    Compute RS momentum and quality signals for scoring.

    Does NOT modify any existing RS logic — purely additive signals.
    Safe defaults returned for short or empty rs_line.

    Parameters
    ----------
    rs_line : list of floats (from calculate_rs_line)

    Returns
    -------
    dict with keys:
        rs_improving    bool   — RS ratio trending up over last 10 bars
        rs_near_high    bool   — RS within 10% of 60-bar peak
        rs_acceleration float  — (rs[-1] - rs[-10]) / abs(rs[-10])
    """
    _default = {"rs_improving": False, "rs_near_high": False, "rs_acceleration": 0.0}
    try:
        if not rs_line or len(rs_line) < 11:
            return _default

        rs_now = float(rs_line[-1])
        rs_10  = float(rs_line[-10])

        # RS Improving: trending up vs 10 bars ago
        rs_improving = rs_now > rs_10

        # RS Near High: within 90% of 60-bar (or full line) peak
        lookback    = rs_line[-60:] if len(rs_line) >= 60 else rs_line
        max_rs      = max(lookback)
        rs_near_high = rs_now >= 0.90 * max_rs if max_rs > 0 else False

        # RS Acceleration: normalised rate of change over 10 bars
        rs_acceleration = round((rs_now - rs_10) / abs(rs_10), 4) if rs_10 != 0 else 0.0

        return {
            "rs_improving":    rs_improving,
            "rs_near_high":    rs_near_high,
            "rs_acceleration": rs_acceleration,
        }
    except Exception:
        return _default
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_rs_signals.py -v
```
Expected: 9 PASSED.

**Step 5: Commit**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard
git add backend/engines/engine4.py backend/tests/test_rs_signals.py
git commit -m "feat(engine4): add get_rs_signals() — rs_improving, rs_near_high, rs_acceleration

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Remove RS hard gates + add new fields in engine2.py

**Files:**
- Modify: `backend/engines/engine2.py` (lines 777, 940, 1064–1070)

No new tests for this task — removing code; existing tests should still pass.

**Step 1: Remove `and rs_score > 0` from Path B (line 777)**

Find:
```python
        if resistance_zones and is_vol_surge and rs_score > 0:
```
Replace with:
```python
        if resistance_zones and is_vol_surge:
```

**Step 2: Remove `rs_vs_spy >= 0` from KDE breakout condition (line 937–941)**

Find:
```python
            is_kde_breakout = (
                0.001 <= pct_above_upper <= 0.025 and
                lvol >= 1.15 * avg_vol and
                rs_vs_spy >= 0
            )
```
Replace with:
```python
            is_kde_breakout = (
                0.001 <= pct_above_upper <= 0.025 and
                lvol >= 1.15 * avg_vol
            )
```

**Step 3: Remove RS hard reject from Path A (lines 1060–1070)**

Find and delete this entire block:
```python
        # ── A1b. RS quality gate ──────────────────────────────────────────
        # DRY setups require stock to be at least neutral vs SPY (rs_score ≥ 0),
        # matching the same bar as BRK (Path B). Coiling on a weak RS stock
        # has significantly lower follow-through probability.
        if rs_score < 0:
            if debug:
                print(
                    f"Engine 2 VCP: REJECTED - RS score negative "
                    f"({rs_score:.3f} < 0 — Path A requires rs_score ≥ 0)"
                )
            return None
```

**Step 4: Add `rs_improving`, `rs_near_high`, `rs_acceleration` params to `scan_vcp()` signature**

Find the current signature (around line 660):
```python
def scan_vcp(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    debug: bool = False,
) -> Optional[Dict]:
```
Replace with:
```python
def scan_vcp(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    spy_3m_return: float = 0.0,
    rs_ratio: float = 0.0,
    rs_52w_high: float = 0.0,
    rs_blue_dot: bool = False,
    rs_score: float = 0.0,
    rs_improving: bool = False,
    rs_near_high: bool = False,
    rs_acceleration: float = 0.0,
    debug: bool = False,
) -> Optional[Dict]:
```

**Step 5: Compute `tight_range_5d` early in `scan_vcp()` body**

The `data` variable (prepared df) is set up early in scan_vcp. After the block where `lc` (last close) is defined, add:

```python
        # ── Tight Price Action: 5-day close range / last close ────────────
        _adj = _adj_col(data)
        _closes_5 = data[_adj].iloc[-5:].values if len(data) >= 5 else data[_adj].values
        _c5_range = (float(_closes_5.max()) - float(_closes_5.min())) / float(lc) if lc > 0 else 1.0
        tight_range_5d = _c5_range <= 0.025
```

Add this right after the line where `lc = ...` is defined (search for `lc = float(data[_adj].iloc[-1])` or equivalent).

**Step 6: Add new fields to ALL return dicts in scan_vcp**

There are 5 return paths (A, B, C, D, E). Each returns a dict. Add these 4 fields to every return dict:

```python
            "rs_improving":    rs_improving,
            "rs_near_high":    rs_near_high,
            "rs_acceleration": rs_acceleration,
            "tight_range_5d":  tight_range_5d,
```

Find each `return {` block in scan_vcp (there are exactly 5) and add the four lines before the closing `}`.

**Step 7: Run existing tests to confirm nothing is broken**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard\backend
python -m pytest tests/test_backtest_engine.py tests/test_macro_service.py -v
```
Expected: all pass.

**Step 8: Commit**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard
git add backend/engines/engine2.py
git commit -m "feat(engine2): relax RS hard gates + add rs_improving/rs_near_high/rs_acceleration/tight_range_5d fields

- Remove rs_score > 0 gate from Path B (BRK)
- Remove rs_vs_spy >= 0 gate from Path D (KDE)
- Remove rs_score < 0 early return from Path A (DRY)
- New optional params: rs_improving, rs_near_high, rs_acceleration
- New computed field: tight_range_5d (5-day close range ≤ 2.5%)
- All 5 return paths include the 4 new fields

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Wire new signals through main.py

**Files:**
- Modify: `backend/main.py` (around line 1717–1748)

**Step 1: Import `get_rs_signals` from engine4**

Find line 110:
```python
from engines.engine4 import calculate_rs_line, detect_rs_blue_dot, get_rs_stats, calculate_rs_score
```
Replace with:
```python
from engines.engine4 import calculate_rs_line, detect_rs_blue_dot, get_rs_stats, calculate_rs_score, get_rs_signals
```

**Step 2: Compute rs_signals after rs_line is available**

Find lines 1717–1723 (the rs_line block):
```python
            rs_line = await loop.run_in_executor(None, calculate_rs_line, df, spy_df)
            if rs_line is not None and len(rs_line) >= MIN_CANDLES_FOR_RS:
                rs_stats    = get_rs_stats(rs_line)
                rs_ratio    = round(float(rs_stats.get("rs_ratio", 0.0)), 4)
                rs_52w_high = float(rs_stats.get("rs_52w_high", 0.0))
                rs_blue_dot = bool(detect_rs_blue_dot(rs_line))
                rs_score    = int(await loop.run_in_executor(None, calculate_rs_score, df, spy_df))
```

Add `rs_signals` initialization before the try block (around line 1710, with the other defaults):
```python
    rs_signals  = {"rs_improving": False, "rs_near_high": False, "rs_acceleration": 0.0}
```

Inside the `if rs_line is not None` block, after the existing lines, add:
```python
                rs_signals  = get_rs_signals(rs_line)
```

**Step 3: Pass new signals to scan_vcp call**

Find line 1747–1748:
```python
    e2 = await loop.run_in_executor(
        None, _run_engine, scan_vcp,
        sym, df, zones, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score
    )
```
Replace with:
```python
    e2 = await loop.run_in_executor(
        None, _run_engine, scan_vcp,
        sym, df, zones, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score,
        rs_signals["rs_improving"], rs_signals["rs_near_high"], rs_signals["rs_acceleration"]
    )
```

**Step 4: Run full test suite**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard\backend
python -m pytest tests/ -v --tb=short
```
Expected: all existing tests pass (no regressions).

**Step 5: Commit**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard
git add backend/main.py
git commit -m "feat(main): wire rs_signals into scan_vcp pipeline

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Add RS quality scoring in constants.py + scoring.py

**Files:**
- Modify: `backend/constants.py` (add `SCORE_WEIGHT_RS_QUALITY`)
- Modify: `backend/scoring.py` (new `_rs_quality_component()` + update `compute_setup_score()`)
- Test: `backend/tests/test_scoring.py` (new)

**Step 1: Add constant to constants.py**

In `backend/constants.py`, find the scoring weight block (around lines 78–83):
```python
SCORE_WEIGHT_RS_RANK    = 30    # RS percentile rank
SCORE_WEIGHT_RR         = 20    # Reward-to-Risk ratio
SCORE_WEIGHT_VOL        = 20    # Volume surge / momentum
SCORE_WEIGHT_REGIME     = 15    # Market regime alignment
SCORE_WEIGHT_SECTOR     = 10    # Sector in top-5 by RS
SCORE_WEIGHT_QUALITY    = 5     # Pattern quality / confirmation signals
```
Add one line after `SCORE_WEIGHT_QUALITY`:
```python
SCORE_WEIGHT_RS_QUALITY = 20    # RS momentum signals (improving, near-high, acceleration, tight range)
```

**Step 2: Write the failing test**

Create `backend/tests/test_scoring_rs_quality.py`:

```python
"""Tests for _rs_quality_component scoring — pytest backend/tests/test_scoring_rs_quality.py -v"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scoring import _rs_quality_component


def _setup(**kwargs):
    base = {
        "setup_type": "VCP",
        "rs_vs_spy": 0.0,
        "rs_score": 0.0,
        "rs_improving": False,
        "rs_near_high": False,
        "rs_acceleration": 0.0,
        "tight_range_5d": False,
    }
    base.update(kwargs)
    return base


def test_zero_score_when_all_signals_absent():
    assert _rs_quality_component(_setup()) == 0.0


def test_rs_vs_spy_positive_adds_points():
    pts = _rs_quality_component(_setup(rs_vs_spy=0.02))
    assert pts > 0


def test_rs_vs_spy_above_threshold_adds_more_points():
    pts_low  = _rs_quality_component(_setup(rs_vs_spy=0.02))
    pts_high = _rs_quality_component(_setup(rs_vs_spy=0.06))
    assert pts_high > pts_low


def test_rs_improving_adds_points():
    pts = _rs_quality_component(_setup(rs_improving=True))
    assert pts > 0


def test_rs_near_high_adds_points():
    pts = _rs_quality_component(_setup(rs_near_high=True))
    assert pts > 0


def test_rs_acceleration_low_threshold():
    pts = _rs_quality_component(_setup(rs_acceleration=0.06))
    assert pts > 0


def test_rs_acceleration_high_threshold_more_points():
    pts_low  = _rs_quality_component(_setup(rs_acceleration=0.06))
    pts_high = _rs_quality_component(_setup(rs_acceleration=0.12))
    assert pts_high > pts_low


def test_tight_range_adds_points():
    pts = _rs_quality_component(_setup(tight_range_5d=True))
    assert pts > 0


def test_all_signals_capped_at_max_weight():
    from constants import SCORE_WEIGHT_RS_QUALITY
    pts = _rs_quality_component(_setup(
        rs_vs_spy=0.10, rs_improving=True, rs_near_high=True,
        rs_acceleration=0.15, tight_range_5d=True
    ))
    assert pts <= float(SCORE_WEIGHT_RS_QUALITY)


def test_negative_rs_vs_spy_contributes_zero():
    pts = _rs_quality_component(_setup(rs_vs_spy=-0.05))
    assert pts == 0.0
```

**Step 3: Run test to verify it fails**

```bash
python -m pytest tests/test_scoring_rs_quality.py -v
```
Expected: ImportError — `_rs_quality_component` not yet public.

**Step 4: Implement `_rs_quality_component()` in scoring.py**

In `backend/scoring.py`, first add `SCORE_WEIGHT_RS_QUALITY` to the constants import (find the import block):
```python
from constants import (
    ...
    SCORE_WEIGHT_QUALITY,
    ...
)
```
Add `SCORE_WEIGHT_RS_QUALITY` to the same import.

Then add this function after `_quality_component()` (around line 311):

```python
def _rs_quality_component(setup: Dict) -> float:
    """
    RS momentum quality component (0 – SCORE_WEIGHT_RS_QUALITY pts).

    Scoring contributions (additive, capped at max):
      rs_vs_spy > 0.00  → +6 pts  (stock outperforming SPY 3-month)
      rs_vs_spy > 0.05  → +8 pts  (strong outperformance, additive with above = +14)
      rs_improving      → +4 pts  (RS line trending up over 10 bars)
      rs_near_high      → +4 pts  (RS within 90% of 60-bar peak)
      rs_acceleration > 0.05  → +4 pts  (accelerating RS)
      rs_acceleration > 0.10  → +6 pts  (replaces the 0.05 bonus, not additive)
      tight_range_5d    → +4 pts  (5-day price range ≤ 2.5% — coiling)

    Total max before cap: 6+8+4+4+6+4 = 32 → capped at SCORE_WEIGHT_RS_QUALITY (20).
    """
    max_pts = float(SCORE_WEIGHT_RS_QUALITY)
    pts = 0.0

    # ── RS vs SPY outperformance ──────────────────────────────────────────────
    rs_vs_spy = float(setup.get("rs_vs_spy") or 0.0)
    if rs_vs_spy > 0.0:
        pts += 6.0
    if rs_vs_spy > 0.05:
        pts += 8.0

    # ── RS Improving (10-bar uptrend) ─────────────────────────────────────────
    if setup.get("rs_improving"):
        pts += 4.0

    # ── RS Near High (within 90% of 60-bar peak) ──────────────────────────────
    if setup.get("rs_near_high"):
        pts += 4.0

    # ── RS Acceleration (rate of change over 10 bars) ─────────────────────────
    rs_accel = float(setup.get("rs_acceleration") or 0.0)
    if rs_accel > 0.10:
        pts += 6.0
    elif rs_accel > 0.05:
        pts += 4.0

    # ── Tight Price Action (5-day range ≤ 2.5%) ───────────────────────────────
    if setup.get("tight_range_5d"):
        pts += 4.0

    return min(max_pts, pts)
```

**Step 5: Update `compute_setup_score()` to call the new component**

In `compute_setup_score()`, find lines 357–360:
```python
    # ── 6. Pattern Quality (0 – SCORE_WEIGHT_QUALITY pts) ────────────────────
    qual_pts = _quality_component(setup)

    raw = rs_pts + rr_pts + vol_pts + reg_pts + sector_pts + qual_pts
    return min(100, max(0, int(round(raw))))
```
Replace with:
```python
    # ── 6. Pattern Quality (0 – SCORE_WEIGHT_QUALITY pts) ────────────────────
    qual_pts = _quality_component(setup)

    # ── 7. RS Quality Signals (0 – SCORE_WEIGHT_RS_QUALITY pts) ──────────────
    rs_qual_pts = _rs_quality_component(setup)

    raw = rs_pts + rr_pts + vol_pts + reg_pts + sector_pts + qual_pts + rs_qual_pts
    return min(100, max(0, int(round(raw))))
```

**Step 6: Run tests**

```bash
python -m pytest tests/test_scoring_rs_quality.py tests/test_rs_signals.py -v
```
Expected: all pass.

**Step 7: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```
Expected: all pass.

**Step 8: Commit**

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard
git add backend/constants.py backend/scoring.py backend/tests/test_scoring_rs_quality.py
git commit -m "feat(scoring): RS quality scoring component — rs_improving, rs_near_high, rs_acceleration, tight_range_5d

- SCORE_WEIGHT_RS_QUALITY = 20 (new constant, does not reduce existing weights)
- _rs_quality_component() scores 6 RS signals up to 20 pts
- compute_setup_score() adds component 7 (RS quality)
- MIN_SETUP_SCORE unchanged at 70
- RS is now ONLY a scoring factor, never a hard reject

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Integration verification

After all tasks are committed, run:

```bash
cd C:\Users\1\OneDrive\Desktop\claudeSkillsTest\swing-trading-dashboard\backend
python -m pytest tests/ -v --tb=short
```

All tests must pass. Engines 0, 1, 3, 5, 6 are untouched.
