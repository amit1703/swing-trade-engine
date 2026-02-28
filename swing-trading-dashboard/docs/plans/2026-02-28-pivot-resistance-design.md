# Pivot High Resistance — Design Doc

**Date:** 2026-02-28

## Problem

The KDE algorithm finds institutional price clusters but misses sharp Minervini-style base highs (V-tops, tight wick pivots) because those levels lack "mass" — only one or two candles reject at the same price. Engine 6 never fires on these levels, and the chart doesn't show them.

## Solution

Add a parallel pivot-high detection pass to Engine 1. Any two wick highs that top out within 1.5% of each other, separated by at least 7 trading days, form a validated resistance zone. These zones are appended to the existing `sr_zones` list, stored in the DB under a new `source` column, and rendered visually distinct from KDE bands on the chart.

---

## Backend — Engine 1

### New function: `_find_pivot_resistance(df, daily_atr, current_price)`

```
1. Slice last PIVOT_LOOKBACK_DAYS (120) rows of df["High"]
2. argrelextrema(highs, np.greater, order=3)
     → local maxima strictly higher than ±3 surrounding bars
3. For each pair (i, j) of found pivots:
     - |i - j| >= PIVOT_MIN_SEPARATION_DAYS (7)
     - |h_i - h_j| / max(h_i, h_j) <= PIVOT_TOUCH_MARGIN_PCT (0.015)
     → they match
4. Cluster transitively (A matches B, B matches C → one cluster)
5. Discard clusters with < PIVOT_MIN_TOUCHES (2) pivots
6. Per cluster:
     level = mean(cluster_highs)
     upper = max(cluster_highs) + 0.1 * daily_atr
     lower = min(cluster_highs) - 0.1 * daily_atr
     type  = "RESISTANCE" if level > current_price else "SUPPORT"
     source = "pivot"
```

Called at the end of `calculate_sr_zones()`, result appended to the final `zones` list.

### New constants (`constants.py`)

```python
PIVOT_LOOKBACK_DAYS       = 120    # ~6 months of trading days
PIVOT_TOUCH_MARGIN_PCT    = 0.015  # 1.5% — highs must cluster within this
PIVOT_MIN_SEPARATION_DAYS = 7      # minimum bars between two matching highs
PIVOT_MIN_TOUCHES         = 2      # minimum pivots to form a valid zone
```

---

## Backend — Database

### Schema migration (`database.py`)

Add `source TEXT DEFAULT 'kde'` column to `sr_zones`:

```python
# In init_db(), after CREATE TABLE statements:
try:
    await db.execute("ALTER TABLE sr_zones ADD COLUMN source TEXT DEFAULT 'kde'")
    await db.commit()
except Exception:
    pass  # already exists on subsequent startups
```

Existing rows automatically read back as `source = 'kde'`. No data loss, no DB wipe.

### `save_sr_zones` — add source to INSERT

```python
(scan_ts, ticker, z["level"], z["upper"], z["lower"], z["type"], z.get("source", "kde"))
```

### `get_sr_zones_for_ticker_from_db` — add source to SELECT + return dict

```python
{"level": r[0], "upper": r[1], "lower": r[2], "type": r[3], "source": r[4] or "kde"}
```

---

## Frontend — Visual

### `sr-band-primitive.js`

**KDE zones** (enhanced visibility):
- Fill: `rgba(255, 45, 85, 0.18)` resistance / `rgba(0, 200, 122, 0.16)` support (was 0.10/0.09)
- Stroke: opacity 0.75 (was 0.55), lineWidth 1.2 (was 0.8)
- Dash: `[5, 4]` unchanged

**Pivot zones** (`zone.source === 'pivot'`):
- Resistance color: amber `#FF8C00`; support color: cyan `#00E5FF`
- Fill: `rgba(255, 140, 0, 0.13)` / `rgba(0, 229, 255, 0.10)`
- Stroke: `rgba(255, 140, 0, 0.90)` / `rgba(0, 229, 255, 0.85)`
- Solid lines (`setLineDash([])`) — instantly distinguishable from KDE dashes
- lineWidth: `1.8`

### `TradingChart.jsx` — fallback price-line path

In the `catch` block, use amber/cyan for pivot zones instead of red/green.

---

## Engine 6

Zero changes required. Engine 6 only reads `type`, `upper`, `lower`, `level` from zone dicts. Pivot zones have all four fields and `type: "RESISTANCE"` — they pass the existing filter and flow through the Launchpad → Decisive Close → Institutional Volume rules automatically.

---

## What Does NOT Change

- KDE algorithm — entirely unchanged
- Engine 2, 3, 4, 5 — no changes
- Frontend table components — no changes
- DB schema migration is backward-compatible (DEFAULT 'kde')
