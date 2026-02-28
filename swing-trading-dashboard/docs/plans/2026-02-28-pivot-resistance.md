# Pivot High Resistance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add pivot-high resistance zone detection to Engine 1 so it finds Minervini-style sharp base highs that the KDE misses, persists them with a `source` column in the DB, and renders them visually distinct (solid amber/cyan lines) from KDE zones (upgraded to higher opacity dashed lines).

**Architecture:** A new private function `_find_pivot_resistance()` in `engine1.py` uses `argrelextrema` on the last 120 days of daily High prices, clusters matching pivot highs via Union-Find, and appends validated zones (with `source: "pivot"`) to the existing zone list. A `source TEXT DEFAULT 'kde'` column is added to `sr_zones` via a safe `ALTER TABLE` migration. The frontend `sr-band-primitive.js` branches on `zone.source` to pick colors and line style.

**Tech Stack:** Python, scipy.signal.argrelextrema, numpy, aiosqlite ALTER TABLE migration, lightweight-charts v4 canvas primitives, React

---

### Task 1: Add pivot constants to `constants.py`

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py` (after line 72, `CACHE_TTL_FAILURE`)

---

**Step 1: Add 4 pivot constants**

File: `constants.py`, after line 72 (`CACHE_TTL_FAILURE = 900 ...`). Change:

```python
CACHE_TTL_SUCCESS = 14400  # Seconds to cache a successful fetch (4 hours)
CACHE_TTL_FAILURE = 900    # Seconds to cache a failed fetch — retry sooner (15 min)
```

To:

```python
CACHE_TTL_SUCCESS = 14400  # Seconds to cache a successful fetch (4 hours)
CACHE_TTL_FAILURE = 900    # Seconds to cache a failed fetch — retry sooner (15 min)
PIVOT_LOOKBACK_DAYS       = 120    # ~6 months of trading days
PIVOT_TOUCH_MARGIN_PCT    = 0.015  # 1.5% — highs must cluster within this
PIVOT_MIN_SEPARATION_DAYS = 7      # minimum bars between two matching highs
PIVOT_MIN_TOUCHES         = 2      # minimum pivots to form a valid zone
```

**Step 2: Run existing tests to confirm no breakage**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: **147 tests PASS**.

**Step 3: Commit**

```bash
git add swing-trading-dashboard/backend/constants.py
git commit -m "feat(engine1): add pivot resistance constants"
```

---

### Task 2: Add `_find_pivot_resistance()` to `engine1.py`

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine1.py`
- Create: `swing-trading-dashboard/backend/tests/test_pivot_resistance.py`

---

**Step 1: Write 8 failing tests**

Create `swing-trading-dashboard/backend/tests/test_pivot_resistance.py` with this exact content:

```python
"""
TDD tests for engine1._find_pivot_resistance()

Naming conventions used by _spike_at():
  - A "spike" is a local maximum: highs[idx] is set to spike_val,
    and the ±3 neighbours are depressed so argrelextrema(order=3) detects it.
"""

import numpy as np
import pandas as pd
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engines.engine1 import _find_pivot_resistance


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_df(n: int = 150, highs=None, current_close: float = 95.0) -> pd.DataFrame:
    """Build a minimal daily OHLCV DataFrame with controlled High values."""
    if highs is None:
        highs = np.ones(n) * 100.0
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = np.ones(n) * current_close
    return pd.DataFrame(
        {
            "Open":      closes - 1.0,
            "High":      highs.copy(),
            "Low":       closes - 2.0,
            "Close":     closes,
            "Adj Close": closes,
            "Volume":    [1_000_000] * n,
        },
        index=dates,
    )


def _spike_at(highs: np.ndarray, idx: int, spike_val: float, order: int = 3) -> np.ndarray:
    """
    Return a copy of `highs` with a clear local maximum at `idx`.
    Sets highs[idx] = spike_val and depresses ±order neighbours to spike_val - 1.
    """
    h = highs.copy()
    h[idx] = spike_val
    for off in range(1, order + 1):
        if idx - off >= 0:
            h[idx - off] = min(h[idx - off], spike_val - 1.0)
        if idx + off < len(h):
            h[idx + off] = min(h[idx + off], spike_val - 1.0)
    return h


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_no_zone_when_fewer_than_two_pivots():
    """Only one pivot high in the lookback window → no cluster → empty list."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 70, 106.0)
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert zones == []


def test_two_matching_pivots_form_one_zone():
    """Two pivots within 1.5% and ≥7 bars apart → exactly one pivot zone."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 105.5)  # 0.48% diff, 40 bars apart
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert len(zones) == 1
    assert zones[0]["source"] == "pivot"


def test_pivots_too_close_in_bars_not_paired():
    """Pivots separated by fewer than PIVOT_MIN_SEPARATION_DAYS bars → no zone."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 60, 105.0)
    highs = _spike_at(highs, 64, 105.2)  # only 4 bars apart — below threshold
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert zones == []


def test_pivots_too_far_apart_in_price_not_paired():
    """Two pivots > 1.5% apart in price → do not cluster → no zone."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 107.0)  # 1.9% diff — above PIVOT_TOUCH_MARGIN_PCT
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert zones == []


def test_zone_above_current_price_is_resistance():
    """Cluster level > current_price → zone type is 'RESISTANCE'."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 105.3)
    df = _make_df(highs=highs, current_close=95.0)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert len(zones) == 1
    assert zones[0]["type"] == "RESISTANCE"


def test_zone_below_current_price_is_support():
    """Cluster level < current_price → zone type is 'SUPPORT'."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 95.0)
    highs = _spike_at(highs, 80, 95.3)
    df = _make_df(highs=highs, current_close=100.0)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=100.0)
    assert len(zones) == 1
    assert zones[0]["type"] == "SUPPORT"


def test_zone_bounds_use_atr_padding():
    """upper = max_cluster_high + 0.1*ATR  ;  lower = min_cluster_high - 0.1*ATR."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 104.5)
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert len(zones) == 1
    assert zones[0]["upper"] == pytest.approx(105.0 + 0.1 * 2.0, abs=0.01)
    assert zones[0]["lower"] == pytest.approx(104.5 - 0.1 * 2.0, abs=0.01)


def test_source_field_is_always_pivot():
    """Every zone returned by _find_pivot_resistance has source == 'pivot'."""
    highs = np.ones(150) * 100.0
    highs = _spike_at(highs, 40, 105.0)
    highs = _spike_at(highs, 80, 105.3)
    df = _make_df(highs=highs)
    zones = _find_pivot_resistance(df, daily_atr=2.0, current_price=95.0)
    assert all(z["source"] == "pivot" for z in zones)
```

**Step 2: Run to confirm 8 failures**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_pivot_resistance.py -v
```

Expected: **8 FAILED** — `ImportError: cannot import name '_find_pivot_resistance' from 'engines.engine1'`.

---

**Step 3: Add import of pivot constants to `engine1.py`**

File: `engine1.py`, lines 15-27 (the import block). Currently it ends with:

```python
from indicators import atr as _atr
```

Change to:

```python
from indicators import atr as _atr
from constants import (
    PIVOT_LOOKBACK_DAYS,
    PIVOT_MIN_SEPARATION_DAYS,
    PIVOT_MIN_TOUCHES,
    PIVOT_TOUCH_MARGIN_PCT,
)
```

---

**Step 4: Add `_find_pivot_resistance()` to `engine1.py`**

File: `engine1.py`. After the existing `_adj_col()` helper at the bottom of the file (after line 226), add:

```python

def _find_pivot_resistance(
    df: pd.DataFrame, daily_atr: float, current_price: float
) -> List[Dict]:
    """
    Find pivot-high resistance zones from the last PIVOT_LOOKBACK_DAYS trading days.

    Uses argrelextrema on daily High prices (order=3) to find local wick maxima,
    then clusters matching pivots — within PIVOT_TOUCH_MARGIN_PCT of each other AND
    at least PIVOT_MIN_SEPARATION_DAYS bars apart — via Union-Find.  Clusters with
    >= PIVOT_MIN_TOUCHES members become zones.
    """
    lookback = df.tail(PIVOT_LOOKBACK_DAYS)
    if len(lookback) < 10:
        return []

    highs = lookback["High"].values.astype(float)
    pivot_idx_arr = argrelextrema(highs, np.greater, order=3)[0]

    if len(pivot_idx_arr) < PIVOT_MIN_TOUCHES:
        return []

    pivot_highs = highs[pivot_idx_arr]
    n = len(pivot_idx_arr)

    # ── Union-Find ──────────────────────────────────────────────────────────
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        parent[_find(a)] = _find(b)

    for i in range(n):
        for j in range(i + 1, n):
            sep = int(pivot_idx_arr[j]) - int(pivot_idx_arr[i])
            if sep < PIVOT_MIN_SEPARATION_DAYS:
                continue
            h_max = max(pivot_highs[i], pivot_highs[j])
            if h_max == 0:
                continue
            if abs(pivot_highs[i] - pivot_highs[j]) / h_max <= PIVOT_TOUCH_MARGIN_PCT:
                _union(i, j)

    # ── Group by root ───────────────────────────────────────────────────────
    clusters: dict = {}
    for i in range(n):
        root = _find(i)
        clusters.setdefault(root, []).append(i)

    zones: List[Dict] = []
    for members in clusters.values():
        if len(members) < PIVOT_MIN_TOUCHES:
            continue
        cluster_highs = [float(pivot_highs[m]) for m in members]
        level = float(np.mean(cluster_highs))
        upper = float(max(cluster_highs)) + 0.1 * daily_atr
        lower = float(min(cluster_highs)) - 0.1 * daily_atr
        zone_type = "RESISTANCE" if level > current_price else "SUPPORT"
        pct_diff = abs(level - current_price) / current_price if current_price > 0 else 1.0
        zones.append(
            {
                "level": round(level, 2),
                "upper": round(upper, 2),
                "lower": round(lower, 2),
                "type": zone_type,
                "atr": round(daily_atr, 2),
                "is_primary": pct_diff <= 0.03,
                "source": "pivot",
            }
        )

    return zones
```

---

**Step 5: Wire `_find_pivot_resistance()` into `calculate_sr_zones()`**

File: `engine1.py`, lines 190-191. Currently:

```python
        zones.sort(key=lambda z: z["level"])
        return zones
```

Change to:

```python
        zones.sort(key=lambda z: z["level"])
        pivot_zones = _find_pivot_resistance(data, daily_atr, current_price)
        zones.extend(pivot_zones)
        zones.sort(key=lambda z: z["level"])
        return zones
```

---

**Step 6: Run pivot tests — confirm 8 pass**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_pivot_resistance.py -v
```

Expected: **8 PASSED**.

**Step 7: Run full suite — confirm no regressions**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: **155 tests PASS** (147 existing + 8 new).

**Step 8: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine1.py \
        swing-trading-dashboard/backend/tests/test_pivot_resistance.py
git commit -m "feat(engine1): add pivot-high resistance zone detection"
```

---

### Task 3: Add `source` column to `sr_zones` DB table

**Files:**
- Modify: `swing-trading-dashboard/backend/database.py`
- Create: `swing-trading-dashboard/backend/tests/test_sr_zones_source.py`

---

**Step 1: Write 3 failing tests**

Create `swing-trading-dashboard/backend/tests/test_sr_zones_source.py` with this exact content:

```python
"""
TDD tests for the sr_zones `source` column migration.

Uses a temporary SQLite file (via tmp_path + monkeypatch) so the real
trading.db is never touched.  database.py accepts db_path as an explicit
parameter on every function, so we pass the temp path directly.
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import init_db, save_sr_zones, get_sr_zones_for_ticker_from_db


@pytest.fixture
def db(tmp_path):
    """Return a path to a freshly-initialised temp database."""
    path = str(tmp_path / "test.db")
    asyncio.run(init_db(path))
    return path


def test_pivot_zone_source_persisted(db):
    """A zone with source='pivot' round-trips through save/load with source='pivot'."""
    zones = [
        {"level": 105.0, "upper": 106.0, "lower": 104.0, "type": "RESISTANCE", "source": "pivot"}
    ]
    asyncio.run(save_sr_zones(db, "2026-01-01T00:00:00", "AAPL", zones))

    # Simulate a completed scan_run so get_sr_zones_for_ticker_from_db finds the timestamp
    import aiosqlite

    async def _mark_complete():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO scan_runs (scan_timestamp, completed) VALUES (?, 1)",
                ("2026-01-01T00:00:00",),
            )
            await conn.commit()

    asyncio.run(_mark_complete())

    result = asyncio.run(get_sr_zones_for_ticker_from_db(db, "AAPL"))
    assert len(result) == 1
    assert result[0]["source"] == "pivot"


def test_kde_zone_defaults_to_kde_source(db):
    """A zone dict without a 'source' key is saved and retrieved as source='kde'."""
    zones = [{"level": 100.0, "upper": 101.0, "lower": 99.0, "type": "SUPPORT"}]
    asyncio.run(save_sr_zones(db, "2026-01-01T00:00:00", "MSFT", zones))

    import aiosqlite

    async def _mark_complete():
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO scan_runs (scan_timestamp, completed) VALUES (?, 1)",
                ("2026-01-01T00:00:00",),
            )
            await conn.commit()

    asyncio.run(_mark_complete())

    result = asyncio.run(get_sr_zones_for_ticker_from_db(db, "MSFT"))
    assert len(result) == 1
    assert result[0]["source"] == "kde"


def test_init_db_idempotent(db):
    """Calling init_db() twice does not raise (ALTER TABLE migration is safe)."""
    asyncio.run(init_db(db))  # second call — must not raise
```

**Step 2: Run to confirm 3 failures**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_sr_zones_source.py -v
```

Expected: **3 FAILED** — `KeyError: 'source'` (field not yet in SELECT) or `OperationalError: table sr_zones has no column named source`.

---

**Step 3: Add `source` column to `_CREATE_SR_ZONES` schema**

File: `database.py`, lines 55-66 (`_CREATE_SR_ZONES`). Currently:

```python
_CREATE_SR_ZONES = """
CREATE TABLE IF NOT EXISTS sr_zones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    level          REAL NOT NULL,
    zone_upper     REAL NOT NULL,
    zone_lower     REAL NOT NULL,
    zone_type      TEXT NOT NULL,
    FOREIGN KEY (scan_timestamp) REFERENCES scan_runs(scan_timestamp)
);
"""
```

Change to:

```python
_CREATE_SR_ZONES = """
CREATE TABLE IF NOT EXISTS sr_zones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    level          REAL NOT NULL,
    zone_upper     REAL NOT NULL,
    zone_lower     REAL NOT NULL,
    zone_type      TEXT NOT NULL,
    source         TEXT DEFAULT 'kde',
    FOREIGN KEY (scan_timestamp) REFERENCES scan_runs(scan_timestamp)
);
"""
```

---

**Step 4: Add `source` migration to `init_db()`**

File: `database.py`, lines 108-113 (the existing `targets_json` migration block). Currently:

```python
        # Migration: add targets_json column if it does not yet exist
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN targets_json TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore
```

Change to:

```python
        # Migration: add targets_json column if it does not yet exist
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN targets_json TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore
        # Migration: add source column to sr_zones if it does not yet exist
        try:
            await db.execute("ALTER TABLE sr_zones ADD COLUMN source TEXT DEFAULT 'kde'")
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore
```

---

**Step 5: Add `source` to `save_sr_zones` INSERT**

File: `database.py`, lines 230-238 (`save_sr_zones`). Currently:

```python
        await db.executemany(
            """INSERT INTO sr_zones (scan_timestamp, ticker, level, zone_upper, zone_lower, zone_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (scan_timestamp, ticker, z["level"], z["upper"], z["lower"], z["type"])
                for z in zones
            ],
        )
```

Change to:

```python
        await db.executemany(
            """INSERT INTO sr_zones (scan_timestamp, ticker, level, zone_upper, zone_lower, zone_type, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (scan_timestamp, ticker, z["level"], z["upper"], z["lower"], z["type"], z.get("source", "kde"))
                for z in zones
            ],
        )
```

---

**Step 6: Add `source` to `get_sr_zones_for_ticker_from_db` SELECT**

File: `database.py`, lines 384-394 (`get_sr_zones_for_ticker_from_db`). Currently:

```python
        async with db.execute(
            """SELECT level, zone_upper, zone_lower, zone_type
               FROM sr_zones WHERE scan_timestamp = ? AND ticker = ?
               ORDER BY level""",
            (scan_ts, ticker),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {"level": r[0], "upper": r[1], "lower": r[2], "type": r[3]}
                for r in rows
            ]
```

Change to:

```python
        async with db.execute(
            """SELECT level, zone_upper, zone_lower, zone_type, source
               FROM sr_zones WHERE scan_timestamp = ? AND ticker = ?
               ORDER BY level""",
            (scan_ts, ticker),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {"level": r[0], "upper": r[1], "lower": r[2], "type": r[3], "source": r[4] or "kde"}
                for r in rows
            ]
```

---

**Step 7: Run DB tests — confirm 3 pass**

```bash
cd swing-trading-dashboard/backend
pytest tests/test_sr_zones_source.py -v
```

Expected: **3 PASSED**.

**Step 8: Run full suite — confirm no regressions**

```bash
cd swing-trading-dashboard/backend
pytest --tb=short -q
```

Expected: **158 tests PASS** (155 + 3 new).

**Step 9: Commit**

```bash
git add swing-trading-dashboard/backend/database.py \
        swing-trading-dashboard/backend/tests/test_sr_zones_source.py
git commit -m "feat(db): add source column to sr_zones for pivot vs kde distinction"
```

---

### Task 4: Frontend visual changes

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/sr-band-primitive.js`
- Modify: `swing-trading-dashboard/frontend/src/components/TradingChart.jsx`

No new Python tests for this task. Verification is a frontend build check.

---

**Step 1: Update `sr-band-primitive.js` rendering**

File: `sr-band-primitive.js`, lines 17-65 (`BandPaneRenderer.draw()`).

Currently the `draw()` method starts with:

```javascript
  draw(target) {
    const series = this._getSeries()
    if (!series) return

    const { upper, lower, type } = this._zone

    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const y1 = series.priceToCoordinate(upper)
      const y2 = series.priceToCoordinate(lower)

      if (y1 === null || y2 === null) return

      const minY = Math.min(y1, y2)
      const maxY = Math.max(y1, y2)
      const bandH = maxY - minY

      if (bandH < 0.5) return

      const w = mediaSize.width

      const isRes = type === 'RESISTANCE'
      const fillColor   = isRes ? 'rgba(255, 45, 85, 0.10)' : 'rgba(0, 200, 122, 0.09)'
      const strokeColor = isRes ? 'rgba(255, 45, 85, 0.55)' : 'rgba(0, 200, 122, 0.55)'

      ctx.save()

      // Filled band
      ctx.fillStyle = fillColor
      ctx.fillRect(0, minY, w, bandH)

      // Dashed border lines
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = 0.8
      ctx.setLineDash([5, 4])
```

Change to:

```javascript
  draw(target) {
    const series = this._getSeries()
    if (!series) return

    const { upper, lower, type, source } = this._zone

    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const y1 = series.priceToCoordinate(upper)
      const y2 = series.priceToCoordinate(lower)

      if (y1 === null || y2 === null) return

      const minY = Math.min(y1, y2)
      const maxY = Math.max(y1, y2)
      const bandH = maxY - minY

      if (bandH < 0.5) return

      const w = mediaSize.width

      const isPivot = source === 'pivot'
      const isRes   = type === 'RESISTANCE'

      let fillColor, strokeColor, lineWidth, dashPattern
      if (isPivot) {
        fillColor   = isRes ? 'rgba(255, 140, 0, 0.13)' : 'rgba(0, 229, 255, 0.10)'
        strokeColor = isRes ? 'rgba(255, 140, 0, 0.90)' : 'rgba(0, 229, 255, 0.85)'
        lineWidth   = 1.8
        dashPattern = []
      } else {
        fillColor   = isRes ? 'rgba(255, 45, 85, 0.18)' : 'rgba(0, 200, 122, 0.16)'
        strokeColor = isRes ? 'rgba(255, 45, 85, 0.75)' : 'rgba(0, 200, 122, 0.75)'
        lineWidth   = 1.2
        dashPattern = [5, 4]
      }

      ctx.save()

      // Filled band
      ctx.fillStyle = fillColor
      ctx.fillRect(0, minY, w, bandH)

      // Border lines
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = lineWidth
      ctx.setLineDash(dashPattern)
```

---

**Step 2: Update `TradingChart.jsx` fallback catch block**

File: `TradingChart.jsx`, lines 138-143 (the `catch` block). Currently:

```javascript
        } catch (e) {
          // Fallback: draw two price lines if primitive API unavailable
          const c = zone.type === 'RESISTANCE' ? COLORS.halt : COLORS.go
          candleSeries.createPriceLine({ price: zone.upper, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: '' })
          candleSeries.createPriceLine({ price: zone.lower, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: `${zone.type[0]} ${zone.level}` })
        }
```

Change to:

```javascript
        } catch (e) {
          // Fallback: draw two price lines if primitive API unavailable
          const isPivot = zone.source === 'pivot'
          const c = isPivot
            ? (zone.type === 'RESISTANCE' ? '#FF8C00' : '#00E5FF')
            : (zone.type === 'RESISTANCE' ? COLORS.halt : COLORS.go)
          candleSeries.createPriceLine({ price: zone.upper, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: '' })
          candleSeries.createPriceLine({ price: zone.lower, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: `${zone.type[0]} ${zone.level}` })
        }
```

---

**Step 3: Run the frontend build to confirm no JS errors**

```bash
cd swing-trading-dashboard/frontend
npm run build
```

Expected: build succeeds with no errors.

**Step 4: Commit**

```bash
git add swing-trading-dashboard/frontend/src/sr-band-primitive.js \
        swing-trading-dashboard/frontend/src/components/TradingChart.jsx
git commit -m "feat(frontend): pivot zones amber/cyan solid lines; boost KDE zone visibility"
```

---

## Manual Verification (after all tasks)

1. Start backend: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
2. Start frontend: `npm run dev` (from `frontend/`)
3. Run a scan, then click any ticker
4. On the chart: KDE zones appear as **dashed red/green bands** (more visible than before); pivot zones appear as **solid amber/cyan bands**
5. Check the backend logs — pivot zones should be logged under `[Engine1]` with no errors
6. Confirm Engine 6 still fires on pivot resistance zones (they have `type`, `upper`, `lower`, `level`)
