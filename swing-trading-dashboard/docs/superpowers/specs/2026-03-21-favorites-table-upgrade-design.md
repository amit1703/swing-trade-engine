# Favorites Page Table Upgrade — Design Spec

**Date:** 2026-03-21
**Status:** Approved by user

---

## Goal

Replace the card-style rows in `FavoritesPage.jsx` with a compact sortable table. One row per setup (a ticker with VCP + PB signals shows as two rows). Single flat table — no sections. Matches the WatchlistPanel table aesthetic.

---

## Scope

Single file change: `frontend/src/components/FavoritesPage.jsx`

No backend changes. All required fields are already available via props (`allSetups`, `watchlistItems`, `livePrices`).

---

## Columns

| Col | Source | Align | Color logic |
|-----|--------|-------|-------------|
| TICKER | `ticker` | left | cyan if selected, bold; blue dot if `rs_blue_dot`; ★ remove button |
| TYPE | `setup_type` / `watchlist_source` | left | colored badge per type |
| DIST | computed ATR dist | right | green <0.5 ATR, amber <1.5 ATR, muted otherwise |
| SCR | `setup_score` | right | green ≥80, amber ≥65, muted otherwise |
| ENTRY | `entry` | right | default text color |
| SL | `stop_loss` | right | `var(--halt)` red |
| R:R | `rr` | right | green ≥2, muted otherwise |
| TV | link | right | small cyan `TV` badge link |

---

## Data Sources

Each row comes from one of two sources:

**Scanner setup row** (from `allSetups` prop, filtered to `favorites`):
- Fields: `ticker`, `setup_type`, `entry`, `stop_loss`, `rr`, `setup_score`, `atr`, `distance_pct`, `rs_blue_dot`

**Watchlist row** (from `watchlistItems` prop, filtered to `favorites`):
- Fields: `ticker`, `watchlist_source` (`'RES_BREAKOUT'` or `'PULLBACK'`), `entry`, `stop_loss`, `rr`, `setup_score`, `atr`, `distance_pct`, `rs_blue_dot`
- TYPE displayed as `WL↓` (RES_BREAKOUT) or `WL↑` (PULLBACK)

**"Not in scan" rows**: tickers in `favorites` with no matching setup or watchlist entry. Show TICKER + ★ only; all other cells display `—`. Always sorted to the bottom regardless of sort state.

---

## TYPE Badge Colors

| `setup_type` / source | Label | Color |
|-----------|-------|-------|
| `VCP` | VCP | `#50d8f0` |
| `PULLBACK` | PB | `#64b4ff` |
| `RES_BREAKOUT` | BRK | `#00c87a` |
| `BASE` | BASE | `#9B6EFF` |
| `HTF` | HTF | `#FF6EC7` |
| `LCE` | LCE | `#9B6EFF` |
| `WATCHLIST` (Engine2 fallback in allSetups) | WL | `#50d8f0` |
| watchlistItems `RES_BREAKOUT` | WL↓ | `#00c87a` |
| watchlistItems `PULLBACK` | WL↑ | `#64b4ff` |
| any unknown type | type string | `#555555` muted |

Use hex values directly — do not rely on CSS vars for badge colors.

---

## Left Border Colors

| Setup type | Border |
|-----------|--------|
| `RES_BREAKOUT` / WL↓ | `rgba(0,200,122,0.4)` |
| `PULLBACK` / WL↑ | `rgba(100,180,255,0.4)` |
| `VCP` / `WATCHLIST` | `rgba(80,216,240,0.35)` |
| `BASE` / `LCE` | `rgba(155,110,255,0.4)` |
| `HTF` | `rgba(255,110,199,0.4)` |
| Not in scan / unknown | `transparent` |

Selected row overrides border to `var(--accent)`.

---

## ATR Distance Computation

```js
function atrDist(item) {
  const dist  = item.distance_pct ?? 0
  const atr   = item.atr ?? 0
  const entry = item.entry ?? 0
  if (atr > 0 && entry > 0) {
    const atrPct = atr / entry * 100
    return atrPct > 0 ? dist / atrPct : 99
  }
  return dist
}
```

Returns `99` for items with no valid ATR/entry. "Not in scan" rows use `Infinity` as their sort key so they always sort below even atrDist=99 rows.

**DIST cell display:** No directional suffix (unlike WatchlistPanel). The TYPE column already communicates setup direction.
- ATR format: `${atrDist(row).toFixed(1)}atr` (e.g. `0.3atr`)
- Fallback when `atr=0` or `entry=0`: `${(item.distance_pct ?? 0).toFixed(1)}%` — `distance_pct` is already stored as a percentage value (e.g. `1.2` → display `1.2%`), no multiplication needed.
- If both `atr=0` and `distance_pct=0`: show `—`.

**Field availability on watchlist items:** `atr`, `distance_pct`, and `rs_blue_dot` are all returned by `GET /api/watchlist` (confirmed by the WatchlistPanel implementation which uses all three). If `atr=0` or `entry=0`, DIST shows `—`.

---

## Sort Behaviour

- Single sort state: `{ col: 'dist', dir: 'asc' }` — default closest to entry first.
- Sortable columns: `dist` and `scr` only. Other headers are display-only.
- Clicking inactive `dist` → `asc`. Clicking inactive `scr` → `desc`. Clicking active column → toggle.
- Active header shown in `var(--accent)` with ▲/▼. Inactive in `var(--muted)`.
- **"Not in scan" rows always sort to the bottom** regardless of sort direction or column. Implement by using `Infinity` as their sort key in `sortRows()`, distinct from the `99` sentinel used for rows with `atr=0`.

---

## Zero Guards

Engine2-sourced items may have `rr = 0`, `stop_loss = 0`, `setup_score = 0`. Treat `=== 0` same as null → display `—`.

---

## Visual Style

- Matches WatchlistPanel table: `IBM Plex Mono`, 8px uppercase headers, `var(--border)` separators.
- Header row: `background: rgba(255,255,255,0.02)`.
- Data rows: transparent background, hover `rgba(255,255,255,0.03)`.
- Selected row: `background: rgba(80,216,240,0.05)`, `border-left: 3px solid var(--accent)`.
- Font sizes: header labels 8px, data rows 10–11px mono.

---

## Hardcoded Amber Color Fixes

The existing file contains hardcoded old amber values that must be updated:
- Count badge: `rgba(245,166,35,0.08)` → `rgba(80,216,240,0.08)`
- Count badge border: `rgba(245,166,35,0.2)` → `rgba(80,216,240,0.2)`
- Selected row background: `rgba(245,166,35,0.05)` → `rgba(80,216,240,0.05)`
- TV link color: `rgba(245,166,35,0.5)` → `rgba(80,216,240,0.5)` (or `var(--accent)`)
- TV link border: `rgba(245,166,35,0.25)` → `rgba(80,216,240,0.25)`
- VCP TYPE_COLOR entry: `'#F5A623'` → `'var(--accent)'` (resolved inline as `#50d8f0`)

---

## Component Structure

`FavoritesPage` manages:
- `sort: { col: 'dist', dir: 'asc' }` — single sort state
- `rows` — derived list of `{ ticker, type, label, typeColor, borderColor, entry, stop_loss, rr, setup_score, atr, distance_pct, rs_blue_dot, isNotInScan }` objects, built from `allSetups` + `watchlistItems` + bare `favorites` entries

Helper `buildRows(favorites, allSetups, watchlistItems)` — pure function, returns flat array.

**Deduplication rule:** A ticker may appear in both `allSetups` and `watchlistItems` simultaneously. Emit both rows — they represent different signals (e.g., AAPL as a VCP scanner setup AND as a WL↓ watchlist entry). Do not suppress either.

A ticker may also appear multiple times in `watchlistItems` (e.g., once as `RES_BREAKOUT` and once as `PULLBACK`). Emit one row per watchlist item — do not deduplicate.

Tickers in `favorites` with no matching row in either source get one "not in scan" row.

Helper `sortRows(rows, sort)` — pure sort, implemented as two steps:
1. Partition rows into `real` (not isNotInScan) and `tail` (isNotInScan).
2. Sort `real` rows by: `dist` → `atrDist(row)` asc/desc; `scr` → `(row.setup_score ?? 0)` asc/desc.
3. Return `[...sortedReal, ...tail]`.

This guarantees "not in scan" rows are always last regardless of sort direction or column — no sentinel arithmetic needed.

`FavRow` component — renders one data row.

`SortHeader` component — renders clickable header row (same pattern as WatchlistPanel, but with TYPE column added as display-only).

---

## What Does NOT Change

- Panel header (Favorites + count)
- Empty state (no favorites yet)
- `onToggleFavorite` behavior (★ removes from favorites)
- `onSelectTicker` click handler
- Props interface: `{ favorites, onToggleFavorite, allSetups, watchlistItems, selectedTicker, onSelectTicker, livePrices }` — `livePrices` is retained in the signature for forward compatibility but is not used in the new table design (live price column is removed).

---

## Intentional Removals

- Live price column — removed (not in WatchlistPanel, keep consistent)
- Setup detail sub-rows (entry/SL/R:R below each row) — removed (now inline columns)
- Source badge (`WL-BRK` / `WL-PB` old labels) — replaced by TYPE column
- Live-price-relative DIST computation (old: `((livePrice - entry) / entry) * 100`) — replaced by the static `distance_pct`/ATR formula from `atrDist()`. This is a deliberate semantic change: DIST now reflects the scan-time proximity to entry, not the current live offset.
