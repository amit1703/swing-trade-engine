# Universe & Pre-Scan Filtering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand and improve the stock universe from ~700 to 1200–1500 names with tighter liquidity gates, RS tier scoring, a 3-tier sector gate, and a discovery layer for emerging leaders.

**Architecture:** Four files touched in dependency order — constants first (no imports from other project files), then universe_builder (dollar-volume param), then scoring (RS tier + sector tiers in compute_setup_score), then main (hybrid loader at startup + discovery layer in _run_scan + new /api/build-universe endpoint). Frontend api.js gets one line added. No DB schema changes. No engine files touched.

**Tech Stack:** Python, FastAPI, pandas/numpy (existing). pytest for tests. Design doc: `docs/plans/2026-03-07-universe-prescreening-design.md`.

---

### Task 1: Update constants.py — 2 updated + 12 new constants

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py:90` (TOP_SECTORS_N 5→8)
- Modify: `swing-trading-dashboard/backend/constants.py:178-179` (LIQUIDITY thresholds)
- Modify: `swing-trading-dashboard/backend/constants.py` (add 12 new constants at bottom)
- Create: `swing-trading-dashboard/backend/tests/test_universe_prescreening_constants.py`

**Context:** All tunable thresholds live in constants.py. Downstream tasks (scoring.py, main.py) import from here. `TOP_SECTORS_N` (line 90) controls how many sectors `compute_top_sectors()` returns — raising it from 5 to 8 is required for the 3-tier sector gate (Task 3 slices at SECTOR_TIER1_N=5 for full credit, indices 5-7 for partial). `LIQUIDITY_MIN_AVG_VOLUME` (line 178) and `LIQUIDITY_MIN_DOLLAR_VOLUME` (line 179) are raised. Twelve new constants go in a new section at the bottom.

**Step 1: Write the failing test**

```python
# tests/test_universe_prescreening_constants.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from constants import (
    LIQUIDITY_MIN_AVG_VOLUME,
    LIQUIDITY_MIN_DOLLAR_VOLUME,
    TOP_SECTORS_N,
    UNIVERSE_MAX_AGE_DAYS,
    UNIVERSE_WARN_AGE_DAYS,
    UNIVERSE_MIN_SIZE,
    UNIVERSE_MAX_SIZE,
    RS_TIER1_THRESHOLD,
    RS_TIER1_MULTIPLIER,
    SECTOR_TIER1_N,
    SECTOR_TIER2_FACTOR,
    SECTOR_OUT_OF_TOP_FACTOR,
    DISCOVERY_RS_MIN,
    DISCOVERY_RS_MAX,
    DISCOVERY_52WK_HIGH_PCT,
    DISCOVERY_VOL_RATIO,
    DISCOVERY_MAX_PCT,
)


def test_liquidity_constants_tightened():
    assert LIQUIDITY_MIN_AVG_VOLUME == 750_000
    assert LIQUIDITY_MIN_DOLLAR_VOLUME == 25_000_000


def test_universe_age_size_constants():
    assert UNIVERSE_MAX_AGE_DAYS == 7
    assert UNIVERSE_WARN_AGE_DAYS == 5
    assert UNIVERSE_MIN_SIZE == 800
    assert UNIVERSE_MAX_SIZE == 2_500
    assert UNIVERSE_WARN_AGE_DAYS < UNIVERSE_MAX_AGE_DAYS  # warn fires before hard cutoff


def test_rs_tier_constants():
    assert RS_TIER1_THRESHOLD == 85
    assert RS_TIER1_MULTIPLIER == 1.15
    assert TOP_SECTORS_N == 8          # raised from 5
    assert SECTOR_TIER1_N == 5         # top 5 of 8 get full points
    assert SECTOR_TIER2_FACTOR == 0.8
    assert SECTOR_OUT_OF_TOP_FACTOR == 0.4
    assert SECTOR_TIER1_N < TOP_SECTORS_N  # ensures tier 2 is non-empty


def test_discovery_constants():
    assert DISCOVERY_RS_MIN == 60
    assert DISCOVERY_RS_MAX == 70
    assert DISCOVERY_52WK_HIGH_PCT == 0.03
    assert DISCOVERY_VOL_RATIO == 1.5
    assert DISCOVERY_MAX_PCT == 0.10
    assert DISCOVERY_RS_MIN < DISCOVERY_RS_MAX  # valid range
```

**Step 2: Run test to verify it fails**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_universe_prescreening_constants.py -v
```

Expected: FAIL with `ImportError` (new constants don't exist yet) and `AssertionError` on LIQUIDITY values.

**Step 3: Apply changes to constants.py**

Change line 90:
```python
TOP_SECTORS_N           = 8     # top N sectors by avg RS (raised from 5; scoring uses SECTOR_TIER1_N=5 for tier 1)
```

Change line 178:
```python
LIQUIDITY_MIN_AVG_VOLUME    = 750_000      # raised from 500K — tighter volume gate
```

Change line 179:
```python
LIQUIDITY_MIN_DOLLAR_VOLUME = 25_000_000   # raised from 20M — tighter dollar volume gate
```

Add a new section at the very bottom of constants.py (after the Engine Hardening section, after line 221):

```python
# ──────────────────────────────────────────────────────────────────────────────
# Universe & Pre-Scan Filtering (2026-03-07)
# ──────────────────────────────────────────────────────────────────────────────

# Universe loader aging thresholds
UNIVERSE_MAX_AGE_DAYS  = 7     # hard cutoff: universe older than this → use tickers.py fallback
UNIVERSE_WARN_AGE_DAYS = 5     # soft: log WARNING if universe is aging but still usable

# Universe size sanity checks (logged as warnings, not hard stops)
UNIVERSE_MIN_SIZE      = 800   # warn if universe smaller (filter may be too tight)
UNIVERSE_MAX_SIZE      = 2_500 # warn if universe larger (filter may be too loose)

# RS tier 1 scoring boost
RS_TIER1_THRESHOLD  = 85    # RS rank >= 85 → Tier 1 (market leader)
RS_TIER1_MULTIPLIER = 1.15  # multiply RS score component by 1.15 for Tier 1 tickers

# Sector gate tiers (TOP_SECTORS_N=8 total; top SECTOR_TIER1_N=5 get full points)
SECTOR_TIER1_N           = 5    # top N sectors → full SCORE_WEIGHT_SECTOR pts (10)
SECTOR_TIER2_FACTOR      = 0.8  # sectors ranked 6–8 → 80% of sector points (8 pts)
SECTOR_OUT_OF_TOP_FACTOR = 0.4  # sectors outside top 8 → 40% of sector points (4 pts)

# Discovery layer — RS 60-70 emerging leaders bypass the RS >= 70 gate
DISCOVERY_RS_MIN        = 60    # lower RS bound (inclusive) for discovery candidates
DISCOVERY_RS_MAX        = 70    # upper RS bound (exclusive; 70 = regular gate floor)
DISCOVERY_52WK_HIGH_PCT = 0.03  # close must be within 3% of 52-week high
DISCOVERY_VOL_RATIO     = 1.5   # 5-day avg vol must be >= 1.5x 50-day avg
DISCOVERY_MAX_PCT       = 0.10  # cap discovery candidates at 10% of universe size
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_universe_prescreening_constants.py -v
```

Expected: PASS (4 tests).

**Step 5: Commit**

```bash
git add backend/constants.py backend/tests/test_universe_prescreening_constants.py
git commit -m "feat(constants): tighten liquidity gates, add universe/RS-tier/sector/discovery constants"
```

---

### Task 2: universe_builder.py — add min_dollar_volume param

**Files:**
- Modify: `swing-trading-dashboard/backend/universe_builder.py:177-182` (filter_price_volume signature)
- Modify: `swing-trading-dashboard/backend/universe_builder.py` (add dollar volume check after avg_volume check ~line 264)
- Modify: `swing-trading-dashboard/backend/universe_builder.py:374-378` (build_universe signature)
- Modify: `swing-trading-dashboard/backend/universe_builder.py:403` (filter_price_volume call)
- Modify: `swing-trading-dashboard/backend/universe_builder.py:422-444` (metadata dict)
- Test: `swing-trading-dashboard/backend/tests/test_universe_builder.py` (add new test classes)

**Context:** `filter_price_volume()` (line 177) currently checks price and avg_volume but not dollar volume (price × avg_volume). Add `min_dollar_volume: float = 0.0` as a new optional param — default 0.0 means gate disabled, so existing callers that pass nothing continue to work. `build_universe()` (line 374) needs the same new param forwarded to `filter_price_volume()`. The metadata dict needs two additions: `ticker_count` (so the hybrid loader in Task 4 doesn't have to count tickers itself) and `min_dollar_volume` in the `filters` sub-dict.

**Step 1: Write the failing tests**

Add these two new test classes at the bottom of `tests/test_universe_builder.py` (after all existing classes):

```python
class TestFilterPriceVolumeDollarVolumeGate:
    """min_dollar_volume param should exclude tickers below price*avg_volume threshold."""

    def _make_flat_df(self, price: float, avg_vol: float, days: int = 60) -> pd.DataFrame:
        """Minimal single-ticker DataFrame that filter_price_volume accepts."""
        close = [price] * days
        vol   = [int(avg_vol)] * days
        idx   = pd.date_range(end="2026-03-07", periods=days, freq="B")
        return pd.DataFrame({
            "Open": close, "High": [price * 1.01] * days,
            "Low": [price * 0.99] * days, "Close": close,
            "Adj Close": close, "Volume": vol,
        }, index=idx)

    @patch("universe_builder.yf.download")
    def test_ticker_below_dollar_volume_excluded(self, mock_dl):
        """price=$10, avg_vol=1_000_000 → dollar_vol=$10M < $25M → excluded."""
        mock_dl.return_value = self._make_flat_df(price=10.0, avg_vol=1_000_000)
        result = filter_price_volume(
            ["LOW"], min_avg_volume=500_000, min_dollar_volume=25_000_000
        )
        assert result == []

    @patch("universe_builder.yf.download")
    def test_ticker_above_dollar_volume_passes(self, mock_dl):
        """price=$30, avg_vol=1_000_000 → dollar_vol=$30M >= $25M → passes."""
        mock_dl.return_value = self._make_flat_df(price=30.0, avg_vol=1_000_000)
        result = filter_price_volume(
            ["HIGH"], min_avg_volume=500_000, min_dollar_volume=25_000_000
        )
        assert result == ["HIGH"]

    @patch("universe_builder.yf.download")
    def test_dollar_volume_gate_disabled_when_zero(self, mock_dl):
        """min_dollar_volume=0.0 (default) → gate skipped entirely."""
        mock_dl.return_value = self._make_flat_df(price=10.0, avg_vol=1_000_000)
        result = filter_price_volume(
            ["ANY"], min_avg_volume=500_000, min_dollar_volume=0.0
        )
        assert result == ["ANY"]


class TestBuildUniverseMetadataFields:
    """build_universe() must include ticker_count and min_dollar_volume in metadata."""

    @patch("universe_builder.filter_price_volume", return_value=["AAPL", "MSFT"])
    @patch("universe_builder.build_sector_map",
           return_value={"AAPL": "Technology", "MSFT": "Technology"})
    @patch("universe_builder.fetch_sec_tickers")
    def test_metadata_has_ticker_count_and_dollar_volume(
        self, mock_sec, mock_sector, mock_filter
    ):
        mock_sec.return_value = pd.DataFrame({
            "cik": [1, 2], "name": ["Apple", "Microsoft"],
            "ticker": ["AAPL", "MSFT"], "exchange": ["Nasdaq", "Nasdaq"],
        })
        result = build_universe(min_dollar_volume=25_000_000)
        meta = result["metadata"]

        assert "ticker_count" in meta
        assert meta["ticker_count"] == len(result["tickers"])
        assert "min_dollar_volume" in meta["filters"]
        assert meta["filters"]["min_dollar_volume"] == 25_000_000
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_universe_builder.py -k "DollarVolume or MetadataFields" -v
```

Expected: FAIL — `filter_price_volume` has no `min_dollar_volume` param; metadata missing fields.

**Step 3: Update filter_price_volume signature (line 177)**

```python
def filter_price_volume(
    tickers: List[str],
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
    min_atr_pct: float = 0.0,
    min_dollar_volume: float = 0.0,
) -> List[str]:
```

**Step 4: Add dollar volume check after the avg_volume check**

Find this block (around line 264):
```python
                if avg_volume < min_avg_volume:
                    continue
```

Add immediately after it:
```python
                # --- dollar volume gate (optional — skipped when min_dollar_volume == 0) ---
                if min_dollar_volume > 0:
                    dollar_volume = last_close * avg_volume
                    if dollar_volume < min_dollar_volume:
                        continue
```

**Step 5: Update build_universe signature (line 374)**

```python
def build_universe(
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
    min_atr_pct: float = 0.0,
    min_dollar_volume: float = 0.0,
) -> dict:
```

**Step 6: Update filter_price_volume call inside build_universe (line 403)**

```python
    filtered = filter_price_volume(candidates, min_price, min_avg_volume, min_atr_pct, min_dollar_volume)
```

**Step 7: Update metadata dict in build_universe (around line 422)**

Add `"ticker_count"` as a top-level metadata field and `"min_dollar_volume"` inside `"filters"`:

```python
    return {
        "metadata": {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "ticker_count": len(final_tickers),           # ← ADD
            "version": 1,
            "source": "SEC EDGAR + yfinance",
            "build_time_seconds": build_time,
            "filters": {
                "min_price": min_price,
                "min_avg_volume_50d": min_avg_volume,
                "min_atr_pct": min_atr_pct,
                "min_dollar_volume": min_dollar_volume,   # ← ADD
                "exchanges": ["NYSE", "Nasdaq"],
            },
            "counts": {
                "sec_raw": len(sec_df),
                "after_pattern_filter": len(candidates),
                "after_price_volume_filter": len(filtered_before_etf_removal),
                "etfs_removed": etf_count,
                "final": len(final_tickers),
            },
        },
        "tickers": sorted(final_tickers),
        "sectors": sectors_without_etfs,
    }
```

**Step 8: Run all universe_builder tests**

```bash
python -m pytest tests/test_universe_builder.py -v
```

Expected: PASS (all existing + 4 new tests).

**Step 9: Commit**

```bash
git add backend/universe_builder.py backend/tests/test_universe_builder.py
git commit -m "feat(universe-builder): add min_dollar_volume param, add ticker_count to metadata"
```

---

### Task 3: scoring.py — RS tier multiplier + 3-tier sector scoring

**Files:**
- Modify: `swing-trading-dashboard/backend/scoring.py:31-42` (constants import block)
- Modify: `swing-trading-dashboard/backend/scoring.py:376-378` (RS rank component in compute_setup_score)
- Modify: `swing-trading-dashboard/backend/scoring.py:394-396` (sector component in compute_setup_score)
- Test: `swing-trading-dashboard/backend/tests/test_setup_scoring.py` (add tier tests)

**Context:** Two targeted changes to `compute_setup_score()`.

1. **RS tier 1 multiplier** (line 377): currently `rs_pts = min(30, rs_rank/100*30)`. New: if `rs_rank >= RS_TIER1_THRESHOLD` (85), multiply rs_pts by `RS_TIER1_MULTIPLIER` (1.15), then cap at 30. Effect: RS rank 88 goes from 26.4 → min(30, 30.36) = 30 pts. RS rank 85 goes from 25.5 → min(30, 29.3) = 29.3 pts. RS rank 80 (below threshold) is unchanged at 24.0 pts.

2. **3-tier sector** (lines 394-396): currently binary (in top_sectors → 10 pts, else 0). New: `top_sectors[:SECTOR_TIER1_N]` (top 5) → 10 pts; in `top_sectors` but not top 5 (ranks 6-8) → 8 pts; not in top_sectors at all → 4 pts. `compute_top_sectors()` already returns a sorted list — with `TOP_SECTORS_N=8` it now returns 8. The caller in main.py passes this full list of 8 to `compute_setup_score`. The slicing `top_sectors[:SECTOR_TIER1_N]` handles the tier 1 boundary.

**Step 1: Write the failing tests**

Add to `tests/test_setup_scoring.py` (after all existing tests):

```python
# ── RS tier scoring ────────────────────────────────────────────────────────────

def test_rs_tier1_multiplier_creates_bigger_gap():
    """RS 88 (Tier 1) should gap from RS 80 more than the linear 8-rank diff would give.
    Linear: 88/100*30=26.4 vs 80/100*30=24.0 → diff=2.4
    With multiplier on 88: min(30, 26.4*1.15)=30 vs 24.0 → diff=6.0
    """
    setup = _vcp()
    score_88 = compute_setup_score(setup, 88, 75, "AGGRESSIVE", [])
    score_80 = compute_setup_score(setup, 80, 75, "AGGRESSIVE", [])
    assert score_88 - score_80 > 4   # multiplier makes gap bigger than linear


def test_rs_tier1_capped_at_weight():
    """RS rank=95: 95/100*30*1.15=32.8 → capped at 30. Same score as rank=100."""
    setup = _vcp()
    score_95  = compute_setup_score(setup, 95,  75, "AGGRESSIVE", ["Technology"])
    score_100 = compute_setup_score(setup, 100, 75, "AGGRESSIVE", ["Technology"])
    assert score_95 == score_100   # both hit the 30-pt RS cap


def test_rs_tier2_no_multiplier():
    """RS rank=80 (below threshold 85) gets no multiplier — linear scoring."""
    setup = _vcp()
    # rank=85 is threshold: min(30, 85/100*30*1.15)=29.3; rank=84: 84/100*30=25.2
    # The jump at 85 should be bigger than the 1-rank linear increment of 0.3
    score_84 = compute_setup_score(setup, 84, 75, "AGGRESSIVE", [])
    score_85 = compute_setup_score(setup, 85, 75, "AGGRESSIVE", [])
    assert score_85 - score_84 >= 3   # big jump at tier boundary


# ── Sector tier scoring ────────────────────────────────────────────────────────

def _top8():
    """8 sector names sorted best→worst (as compute_top_sectors returns)."""
    return [
        "Technology", "Healthcare", "Financials", "Energy",
        "Industrials",               # index 4 → tier 1 boundary (SECTOR_TIER1_N=5)
        "Consumer Discretionary",    # index 5 → tier 2
        "Materials",                 # index 6 → tier 2
        "Utilities",                 # index 7 → tier 2
    ]


def test_sector_tier1_gets_full_points():
    """Sectors at ranks 1-5 should all get the same (full) sector pts."""
    top8 = _top8()
    s1 = _vcp(); s1["sector"] = "Technology"   # rank 1
    s5 = _vcp(); s5["sector"] = "Industrials"  # rank 5 (boundary)
    score1 = compute_setup_score(s1, 90, 75, "AGGRESSIVE", top8)
    score5 = compute_setup_score(s5, 90, 75, "AGGRESSIVE", top8)
    assert score1 == score5   # both tier 1 → identical sector pts


def test_sector_tier2_gets_reduced_points():
    """Tier 2 (rank 6-8) → 8 pts vs tier 1 → 10 pts. Diff = 2."""
    top8 = _top8()
    s_t1 = _vcp(); s_t1["sector"] = "Technology"             # tier 1 = 10 pts
    s_t2 = _vcp(); s_t2["sector"] = "Consumer Discretionary" # tier 2 = 8 pts
    score_t1 = compute_setup_score(s_t1, 90, 75, "AGGRESSIVE", top8)
    score_t2 = compute_setup_score(s_t2, 90, 75, "AGGRESSIVE", top8)
    assert score_t1 - score_t2 == 2   # 10 - 8 = 2


def test_sector_outside_top8_gets_minimum():
    """Sector not in top 8 → 4 pts. Diff from tier 1 = 6."""
    top8 = _top8()
    s_t1  = _vcp(); s_t1["sector"]  = "Technology"   # tier 1 = 10 pts
    s_out = _vcp(); s_out["sector"] = "Real Estate"   # outside top 8 = 4 pts
    score_t1  = compute_setup_score(s_t1,  90, 75, "AGGRESSIVE", top8)
    score_out = compute_setup_score(s_out, 90, 75, "AGGRESSIVE", top8)
    assert score_t1 - score_out == 6   # 10 - 4 = 6
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_setup_scoring.py -k "tier" -v
```

Expected: FAIL — no multiplier applied, sector is still binary (0 or 10).

**Step 3: Add new imports to scoring.py**

Find the `from constants import (` block (lines 31-42). Add these names to the import list:

```python
    RS_TIER1_THRESHOLD,
    RS_TIER1_MULTIPLIER,
    SECTOR_TIER1_N,
    SECTOR_TIER2_FACTOR,
    SECTOR_OUT_OF_TOP_FACTOR,
```

**Step 4: Update RS rank component (line 377)**

Replace:
```python
    rs_pts = min(float(SCORE_WEIGHT_RS_RANK), rs_rank / 100.0 * SCORE_WEIGHT_RS_RANK)
```

With:
```python
    rs_pts = rs_rank / 100.0 * SCORE_WEIGHT_RS_RANK
    if rs_rank >= RS_TIER1_THRESHOLD:
        rs_pts *= RS_TIER1_MULTIPLIER
    rs_pts = min(float(SCORE_WEIGHT_RS_RANK), rs_pts)
```

**Step 5: Update sector component (lines 394-396)**

Replace:
```python
    sector     = setup.get("sector", "Unknown")
    sector_pts = float(SCORE_WEIGHT_SECTOR) if sector in top_sectors else 0.0
```

With:
```python
    sector = setup.get("sector", "Unknown")
    if sector in top_sectors[:SECTOR_TIER1_N]:
        sector_pts = float(SCORE_WEIGHT_SECTOR)                            # 10 pts
    elif sector in top_sectors:
        sector_pts = float(SCORE_WEIGHT_SECTOR) * SECTOR_TIER2_FACTOR     # 8 pts
    else:
        sector_pts = float(SCORE_WEIGHT_SECTOR) * SECTOR_OUT_OF_TOP_FACTOR # 4 pts
```

**Step 6: Run all scoring tests**

```bash
python -m pytest tests/test_setup_scoring.py tests/test_scoring_rs_quality.py -v
```

Expected: PASS (all existing + 7 new tests).

**Step 7: Commit**

```bash
git add backend/scoring.py backend/tests/test_setup_scoring.py
git commit -m "feat(scoring): RS tier-1 multiplier (x1.15 >= rank 85) + 3-tier sector gate"
```

---

### Task 4: main.py — hybrid universe loader + discovery layer + /api/build-universe + api.js

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py:72-97` (constants import block)
- Modify: `swing-trading-dashboard/backend/main.py:154-178` (replace universe loader)
- Modify: `swing-trading-dashboard/backend/main.py` (add `_build_discovery_tickers` module-level function)
- Modify: `swing-trading-dashboard/backend/main.py` (in `_run_scan`: add discovery set building after RS rank map)
- Modify: `swing-trading-dashboard/backend/main.py:950-959` (RS gate in `_process`)
- Modify: `swing-trading-dashboard/backend/main.py:1245-1260` (add is_discovery flag after gather)
- Modify: `swing-trading-dashboard/backend/main.py` (add POST /api/build-universe endpoint)
- Modify: `swing-trading-dashboard/frontend/src/api.js` (add buildUniverse function)
- Create: `swing-trading-dashboard/backend/tests/test_discovery_layer.py`

**Context:** Four changes in one file:

1. **Hybrid universe loader** (startup, module-level): The current simple load_universe() call at lines 154-178 is replaced. The new version reads `active_universe.json` directly, checks `metadata["generated_at"]` for age. If age > UNIVERSE_MAX_AGE_DAYS(7) → fall back to SCAN_UNIVERSE + log WARNING. If age > UNIVERSE_WARN_AGE_DAYS(5) but <= 7 → use file + log WARNING. After loading, check `len(tickers)` against UNIVERSE_MIN_SIZE/MAX_SIZE and log WARNING if out of range.

2. **`_build_discovery_tickers(tickers, rs_rank_map, ticker_cache) -> set`**: New module-level function (placed just before the `_scan_state` dict, around line 183). Takes the universe list, the RS rank map, and the ticker cache; returns a set of ticker symbols that: (a) have RS rank in [DISCOVERY_RS_MIN, DISCOVERY_RS_MAX), (b) close within DISCOVERY_52WK_HIGH_PCT of 52wk high, (c) 5-day avg vol >= DISCOVERY_VOL_RATIO × 50-day avg vol. Capped at `int(len(tickers) * DISCOVERY_MAX_PCT)` entries.

3. **Discovery gate integration in `_run_scan`**: After the RS rank map is logged (around line 847), call `_build_discovery_tickers` and store result in `_discovery_tickers`. In `_process`, the RS gate (lines 950-959) gets one additional check: if the ticker is in `_discovery_tickers`, skip the return. After `asyncio.gather()` completes (line 1245), iterate `collected_setups` and add `"is_discovery": True` to any setup whose ticker is in `_discovery_tickers`.

4. **`POST /api/build-universe`**: New FastAPI endpoint after `/api/run-scan`. Triggers `build_universe()` with tightened constants in a background task. Returns `{"job_id": str, "status": "started"}` immediately.

**Step 1: Write the failing tests**

Create `tests/test_discovery_layer.py`:

```python
"""Tests for _build_discovery_tickers in main.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest


def _make_cache_entry(close_arr, vol_arr):
    """Minimal ticker_cache entry: (timestamp_float, DataFrame)."""
    n   = len(close_arr)
    idx = pd.date_range(end="2026-03-07", periods=n, freq="B")
    df  = pd.DataFrame({
        "Open":      close_arr,
        "High":      np.array(close_arr) * 1.005,
        "Low":       np.array(close_arr) * 0.995,
        "Close":     close_arr,
        "Adj Close": close_arr,
        "Volume":    vol_arr,
    }, index=idx)
    return (0.0, df)


def _near_high_prices(n=252, peak_pct=0.01):
    """Price array ending within peak_pct of its own 52wk high."""
    prices = [100.0] * n
    prices[5]  = 102.0           # 52-week high
    prices[-1] = 102.0 * (1 - peak_pct)  # within threshold
    return prices


def _expanding_vol(n=252, base=1_000_000, last5_mult=2.0):
    """Volume array where last 5 bars avg last5_mult× the 50d avg."""
    vol = [base] * n
    for i in range(-5, 0):
        vol[i] = int(base * last5_mult)
    return vol


def test_valid_discovery_candidate_included():
    """RS 65, near high (1%), expanding vol (2x) → should be included."""
    from main import _build_discovery_tickers
    cache  = {"AAPL": _make_cache_entry(_near_high_prices(), _expanding_vol())}
    result = _build_discovery_tickers(["AAPL"], {"AAPL": 65.0}, cache)
    assert "AAPL" in result


def test_rs_above_max_excluded():
    """RS 75 >= DISCOVERY_RS_MAX (70) → not a discovery candidate."""
    from main import _build_discovery_tickers
    cache  = {"AAPL": _make_cache_entry(_near_high_prices(), _expanding_vol())}
    result = _build_discovery_tickers(["AAPL"], {"AAPL": 75.0}, cache)
    assert "AAPL" not in result


def test_rs_below_min_excluded():
    """RS 55 < DISCOVERY_RS_MIN (60) → not a discovery candidate."""
    from main import _build_discovery_tickers
    cache  = {"AAPL": _make_cache_entry(_near_high_prices(), _expanding_vol())}
    result = _build_discovery_tickers(["AAPL"], {"AAPL": 55.0}, cache)
    assert "AAPL" not in result


def test_price_not_near_52wk_high_excluded():
    """RS in range but close is 10% below 52wk high → excluded."""
    from main import _build_discovery_tickers
    prices     = [100.0] * 252
    prices[5]  = 120.0              # 52wk high = 120
    prices[-1] = 108.0              # 10% below high; fails 3% threshold
    cache  = {"MSFT": _make_cache_entry(prices, _expanding_vol())}
    result = _build_discovery_tickers(["MSFT"], {"MSFT": 65.0}, cache)
    assert "MSFT" not in result


def test_volume_not_expanding_excluded():
    """RS in range, near high, but 5d vol = 0.8× 50d avg (contracting) → excluded."""
    from main import _build_discovery_tickers
    vol    = _expanding_vol(last5_mult=0.8)  # contracting
    cache  = {"NVDA": _make_cache_entry(_near_high_prices(), vol)}
    result = _build_discovery_tickers(["NVDA"], {"NVDA": 65.0}, cache)
    assert "NVDA" not in result


def test_discovery_capped_at_max_pct():
    """Discovery set must not exceed DISCOVERY_MAX_PCT (10%) of universe size."""
    from main import _build_discovery_tickers
    n_tickers = 30
    tickers   = [f"T{i}" for i in range(n_tickers)]
    cache     = {t: _make_cache_entry(_near_high_prices(), _expanding_vol()) for t in tickers}
    rs_map    = {t: 65.0 for t in tickers}   # all qualify for RS range
    result    = _build_discovery_tickers(tickers, rs_map, cache)
    assert len(result) <= int(n_tickers * 0.10)  # cap = 3 tickers (10% of 30)
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_discovery_layer.py -v
```

Expected: FAIL — `cannot import name '_build_discovery_tickers' from 'main'`.

**Step 3: Add new constants to main.py imports (lines 72-97)**

In the existing `from constants import (` block, add these names (preserve alphabetical grouping):

```python
    UNIVERSE_MAX_AGE_DAYS,
    UNIVERSE_WARN_AGE_DAYS,
    UNIVERSE_MIN_SIZE,
    UNIVERSE_MAX_SIZE,
    DISCOVERY_RS_MIN,
    DISCOVERY_RS_MAX,
    DISCOVERY_52WK_HIGH_PCT,
    DISCOVERY_VOL_RATIO,
    DISCOVERY_MAX_PCT,
```

**Step 4: Replace the universe loader block (lines 154-178)**

Remove the entire block from the `# ─── Universe & Sector loading ───` comment through the closing `except Exception as e:` block. Replace with:

```python
# ────────────────────────────────────────────────────────────────────────────
# Universe & Sector loading — hybrid loader (active_universe.json → tickers.py fallback)
# ────────────────────────────────────────────────────────────────────────────

ACTIVE_UNIVERSE = SCAN_UNIVERSE   # default fallback
SECTORS         = {}


def _try_load_universe_json(filepath: str):
    """Open active_universe.json and return (tickers, sectors, metadata) or None."""
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("tickers", []), data.get("sectors", {}), data.get("metadata", {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


_raw = _try_load_universe_json(UNIVERSE_FILE)
if _raw is None:
    log.warning("active_universe.json missing or unreadable — using tickers.py fallback")
    try:
        with open("sectors.json", "r") as _f:
            SECTORS = json.load(_f)
    except Exception:
        pass
else:
    _tickers, _sectors, _meta = _raw
    _generated_at_str = _meta.get("generated_at", "")
    _age_days = float("inf")
    if _generated_at_str:
        try:
            _age_days = (datetime.utcnow() - datetime.fromisoformat(_generated_at_str)).days
        except ValueError:
            pass

    if _age_days > UNIVERSE_MAX_AGE_DAYS:
        log.warning(
            "active_universe.json is %d days old (max %d) — using tickers.py fallback",
            _age_days, UNIVERSE_MAX_AGE_DAYS,
        )
        try:
            with open("sectors.json", "r") as _f:
                SECTORS = json.load(_f)
        except Exception:
            pass
    else:
        if _age_days > UNIVERSE_WARN_AGE_DAYS:
            log.warning(
                "active_universe.json is aging (%d days old, warn at %d) — still using it",
                _age_days, UNIVERSE_WARN_AGE_DAYS,
            )
        ACTIVE_UNIVERSE = _tickers
        SECTORS         = _sectors
        if len(ACTIVE_UNIVERSE) < UNIVERSE_MIN_SIZE:
            log.warning(
                "Universe has only %d tickers (min %d) — filter may be too tight",
                len(ACTIVE_UNIVERSE), UNIVERSE_MIN_SIZE,
            )
        if len(ACTIVE_UNIVERSE) > UNIVERSE_MAX_SIZE:
            log.warning(
                "Universe has %d tickers (max %d) — filter may be too loose",
                len(ACTIVE_UNIVERSE), UNIVERSE_MAX_SIZE,
            )
        log.info(
            "Loaded active universe: %d tickers from %s (age %d days)",
            len(ACTIVE_UNIVERSE), UNIVERSE_FILE, _age_days,
        )
```

**Step 5: Add `_build_discovery_tickers` module-level function**

Place this function just before the `_scan_state` dict definition (around line 192, which now follows the loader block):

```python
def _build_discovery_tickers(
    tickers: List[str],
    rs_rank_map: Dict[str, float],
    ticker_cache: dict,
) -> set:
    """
    Find RS 60–70 tickers that are near their 52-week high and show volume expansion.
    These are allowed to bypass the RS >= 70 gate in _process().

    Returns a set of ticker symbols, capped at DISCOVERY_MAX_PCT of universe size.
    """
    discovery: set = set()
    cap = int(len(tickers) * DISCOVERY_MAX_PCT)

    for ticker in tickers:
        if len(discovery) >= cap:
            break
        rs = rs_rank_map.get(ticker, 0.0)
        if not (DISCOVERY_RS_MIN <= rs < DISCOVERY_RS_MAX):
            continue
        entry = ticker_cache.get(ticker)
        if entry is None or entry[1] is None:
            continue
        _, df = entry
        adj = "Adj Close" if "Adj Close" in df.columns else "Close"
        close_arr = df[adj].dropna().values.astype(float)
        if len(close_arr) < 20:
            continue
        high_52w = close_arr[-min(252, len(close_arr)):].max()
        if close_arr[-1] < high_52w * (1 - DISCOVERY_52WK_HIGH_PCT):
            continue
        vol = df["Volume"].dropna().values.astype(float)
        if len(vol) < 50:
            continue
        if vol[-5:].mean() < DISCOVERY_VOL_RATIO * vol[-50:].mean():
            continue
        discovery.add(ticker)

    return discovery
```

**Step 6: Run discovery tests**

```bash
python -m pytest tests/test_discovery_layer.py -v
```

Expected: PASS (6 tests).

**Step 7: Add discovery set building in `_run_scan` (after RS rank map)**

In `_run_scan`, find the block after the RS rank map warning log (around line 847 — the `"RS rank gate will be bypassed"` warning). Add directly after it:

```python
        # ── Discovery layer: RS 60–70 near 52wk high with volume expansion ────
        _discovery_tickers = _build_discovery_tickers(tickers, _rs_rank_map, _ticker_cache)
        if _discovery_tickers:
            log.info(
                "Discovery layer: %d candidate(s) (RS 60-70, near-high, vol expansion)",
                len(_discovery_tickers),
            )
```

**Step 8: Modify RS gate in `_process` to allow discovery candidates**

Find the RS gate block in `_process` (around lines 950-959):

```python
                if _rs_rank_map and regime["is_bullish"] and not force:
                    _ticker_rs_rank = _rs_rank_map.get(ticker)
                    if _ticker_rs_rank is None or _ticker_rs_rank < RS_RANK_MIN_PERCENTILE:
                        log.debug(
                            "Skipped %s: RS rank %.1f < %.0f (threshold)",
                            ticker,
                            _ticker_rs_rank if _ticker_rs_rank is not None else 0.0,
                            RS_RANK_MIN_PERCENTILE,
                        )
                        return
```

Replace with:

```python
                if _rs_rank_map and regime["is_bullish"] and not force:
                    _ticker_rs_rank = _rs_rank_map.get(ticker)
                    if _ticker_rs_rank is None or _ticker_rs_rank < RS_RANK_MIN_PERCENTILE:
                        if ticker not in _discovery_tickers:
                            log.debug(
                                "Skipped %s: RS rank %.1f < %.0f (threshold)",
                                ticker,
                                _ticker_rs_rank if _ticker_rs_rank is not None else 0.0,
                                RS_RANK_MIN_PERCENTILE,
                            )
                            return
                        # discovery candidate — bypass RS gate, fall through to engines
```

**Step 9: Add is_discovery flag after asyncio.gather completes**

Find line 1245: `await asyncio.gather(*[_process(t, i) for i, t in enumerate(tickers)])`

Add immediately after line 1247 (`process_time = time.time() - process_start_time`):

```python
        # Mark setups from discovery candidates
        if _discovery_tickers:
            for _s in collected_setups:
                if _s.get("ticker") in _discovery_tickers:
                    _s["is_discovery"] = True
```

**Step 10: Add POST /api/build-universe endpoint**

Place after the `@app.post("/api/run-scan")` endpoint block (after the closing brace of `trigger_scan`, before `@app.get("/api/scan-status")`):

```python
@app.post("/api/build-universe")
async def trigger_build_universe(background_tasks: BackgroundTasks):
    """
    Trigger a full universe rebuild in the background.
    Operator-facing: rebuilds active_universe.json with tightened liquidity constants.
    Returns immediately with a job_id (no polling endpoint — operator one-shot use).
    """
    job_id = str(uuid.uuid4())[:8]

    async def _run_build():
        loop = asyncio.get_event_loop()
        log.info("[build-universe] Starting (job %s)", job_id)
        try:
            universe = await loop.run_in_executor(
                None,
                lambda: build_universe(
                    min_avg_volume=LIQUIDITY_MIN_AVG_VOLUME,
                    min_dollar_volume=LIQUIDITY_MIN_DOLLAR_VOLUME,
                    min_atr_pct=MIN_ATR_PCT,
                ),
            )
            save_universe(universe, UNIVERSE_FILE)
            log.info(
                "[build-universe] Done (job %s): %d tickers saved to %s",
                job_id, len(universe["tickers"]), UNIVERSE_FILE,
            )
        except Exception as exc:
            log.error("[build-universe] Failed (job %s): %s", job_id, exc)

    background_tasks.add_task(_run_build)
    return {"job_id": job_id, "status": "started"}
```

**Step 11: Add buildUniverse to api.js**

In `swing-trading-dashboard/frontend/src/api.js`, append at the end of the file:

```javascript
export const buildUniverse = () =>
  fetch('/api/build-universe', { method: 'POST' }).then(handleResponse)
```

**Step 12: Run the full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: PASS (all tests, including the 6 new discovery tests).

**Step 13: Commit**

```bash
git add backend/main.py frontend/src/api.js backend/tests/test_discovery_layer.py
git commit -m "feat(main): hybrid universe loader, discovery layer, /api/build-universe endpoint"
```

---

## Verification Checklist

After all 4 tasks:

```bash
# 1. All tests pass
cd swing-trading-dashboard/backend
python -m pytest tests/ -v --tb=short

# 2. Backend starts without error
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# 3. Confirm new endpoint is reachable
curl -X POST http://localhost:8000/api/build-universe
# Expected: {"job_id": "...", "status": "started"}

# 4. Confirm scan-status still works
curl http://localhost:8000/api/scan-status
```
