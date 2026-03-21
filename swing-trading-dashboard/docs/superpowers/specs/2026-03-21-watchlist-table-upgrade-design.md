# Watchlist Panel Table Upgrade — Design Spec

**Date:** 2026-03-21
**Status:** Approved by user

---

## Goal

Replace the card-style rows in `WatchlistPanel.jsx` with a compact sortable table for each section (BRK / PB). Add columns: Score, Entry, Stop Loss, R:R. Add per-section sort controls via clickable column headers.

---

## Scope

Single file change: `frontend/src/components/WatchlistPanel.jsx`

No backend changes needed — all required fields (`entry`, `stop_loss`, `rr`, `setup_score`) are already returned by `GET /api/watchlist`.

---

## Columns

| Col | Key | Align | Width | Color logic |
|-----|-----|-------|-------|-------------|
| TICKER | `ticker` | left | flex | green, bold; blue dot inline; ★ star button |
| DIST | computed ATR dist | right | 52px | green <0.5 ATR, amber <1.5 ATR, muted otherwise |
| SCR | `setup_score` | right | 36px | green ≥80, amber ≥65, muted otherwise |
| ENTRY | `entry` | right | 52px | default text color |
| SL | `stop_loss` | right | 52px | `var(--halt)` red |
| R:R | `rr` | right | 36px | green ≥2, muted otherwise |
| TV | link | right | 24px | small amber `TV` badge link |

---

## Sort behaviour

- Each section (BRK, PB) has **independent** sort state: `{ col, dir }`.
- Default: `col = 'dist'`, `dir = 'asc'` (closest to entry first).
- Clicking the active column header toggles `asc` ↔ `desc`.
- Clicking an inactive column sets it as active with `desc` (except `dist` which starts `asc`).
- Sortable columns: `dist` and `scr`. Other columns are display-only.
- Active sort column header shown in `var(--accent)` with ▲/▼ arrow. Inactive headers in `var(--muted)`.

---

## ATR distance computation

```js
const atrDist = (item.atr > 0 && item.entry > 0)
  ? item.distance_pct / (item.atr / item.entry * 100)
  : item.distance_pct  // fallback to raw %
```

Used for both display in DIST column and for sorting when `col === 'dist'`.

---

## Layout structure

```
┌─────────────────────────────────────────────────────────────┐
│ WATCHLIST                                          [total]  │  ← panel header (unchanged)
├─────────────────────────────────────────────────────────────┤
│ NEAR BREAKOUT                                   [count]    │  ← section header
├──────────┬──────┬─────┬───────┬───────┬─────┬────┤
│ TICKER   │ DIST │ SCR │ ENTRY │  SL   │ R:R │ TV │  ← sort header row (clickable DIST, SCR)
├──────────┼──────┼─────┼───────┼───────┼─────┼────┤
│ AAPL  ●  │0.3atr│  82 │114.50 │111.20 │ 2.4×│ TV │
│ MSFT     │0.8atr│  74 │415.00 │408.00 │ 1.9×│ TV │
│ ...                                                         │
├─────────────────────────────────────────────────────────────┤
│               ▼ Show all 23                                 │  ← show more (unchanged)
├─────────────────────────────────────────────────────────────┤
│ PULLBACK SETUP                                  [count]    │  ← second section, own sort state
│ ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Component structure

`WatchlistPanel` manages:
- `brkSort: { col: 'dist', dir: 'asc' }` — BRK section sort state
- `pbSort:  { col: 'dist', dir: 'asc' }` — PB section sort state
- `showAllBrk`, `showAllPb` — show-more toggles (unchanged)

Helper `sortItems(items, sort)` — pure sort function, returns sorted copy.

`SortHeader` component — renders the clickable header row, takes `sort` state + `onSort` callback.

`WatchRow` component — renders one data row from the table columns above.

---

## Visual style

- Follows existing terminal aesthetic: `IBM Plex Mono`, tiny uppercase headers, `var(--border)` separators.
- Header row: `background: rgba(255,255,255,0.02)`, same as current `SectionHeader`.
- Data rows: transparent background, hover `rgba(255,255,255,0.03)`.
- Selected ticker row: `background: rgba(245,166,35,0.06)`, `border-left: 3px solid var(--accent)`.
- BRK left border: `3px solid rgba(0,200,122,0.4)`. PB: `3px solid rgba(100,180,255,0.4)`.
- Font sizes: header labels 8px, data rows 10–11px mono.

---

## What does NOT change

- Panel header (Watchlist + total count)
- Section headers (Near Breakout / Pullback Setup + count badge)
- Show more / show top 15 button
- Favorites star button behaviour
- `onSelectTicker` click handler
- Loading skeleton and empty state
