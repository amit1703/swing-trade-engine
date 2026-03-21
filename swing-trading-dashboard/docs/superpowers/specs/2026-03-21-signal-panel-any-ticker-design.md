# Signal Panel — Any-Ticker Design Spec

**Date:** 2026-03-21
**Status:** Approved by user

---

## Goal

Make `StockIntelPanel` render for any selected ticker — not just tickers that appear in the current scan results. Currently the panel shows an empty placeholder whenever `selectedSetup` is null. This affects tickers chosen from the watchlist, favorites, and the search box.

---

## Root Cause

`selectedSetup = allSetups.find(s => s.ticker === selectedTicker) ?? null`

`allSetups` contains only the current scan's results. Tickers from the watchlist, favorites, or the search bar that are not in the current scan produce `selectedSetup = null`, which causes `StockIntelPanel` to show its empty placeholder — even though `analysis` data is successfully fetched for the ticker.

---

## Scope

Two files:

| File | Change |
|------|--------|
| `frontend/src/components/StockIntelPanel.jsx` | Use `analysis` as fallback when `setup` is null; fix amber values; update placeholder text |
| `frontend/src/App.jsx` | Change search `switchTab` from `false` → `true` |

No backend changes. No new API endpoints. No changes to props interfaces.

---

## StockIntelPanel.jsx Changes

### Fallback logic

When `setup` is null, the component currently renders a placeholder immediately. Change to:

1. If `setup` is null AND `analysisLoading` is true → render loading shimmer (same shimmer used in the analysis section), not the placeholder
2. If `setup` is null AND `analysis` is available → synthesize a `displaySetup` object from `analysis` fields and render the full panel using `displaySetup`
3. If `setup` is null AND neither loading nor analysis → render placeholder (unchanged)

When `setup` is not null, use it as-is (existing behavior unchanged).

### Synthesis mapping

Build `displaySetup` from `analysis` when `setup` is null:

```js
const displaySetup = setup ?? (analysis ? {
  ticker:       analysis.ticker,
  setup_score:  analysis.score,
  setup_type:   analysis.setup_type ?? analysis.detected_setup ?? null,
  entry:        analysis.entry        ?? 0,
  stop_loss:    analysis.stop_loss    ?? 0,
  take_profit:  analysis.take_profit  ?? 0,
  rr:           analysis.rr           ?? 0,
  rs_score:     analysis.signals?.rs_score  ?? null,
  vol_ratio:    analysis.signals?.vol_ratio ?? null,
  is_vol_surge: (analysis.signals?.vol_ratio ?? 0) > 1.5,
  rs_blue_dot:  false,
} : null)
```

All downstream rendering uses `displaySetup` instead of `setup` — no other logic changes.

`rs_blue_dot: false` is intentional: the analysis endpoint does not return this field. The blue dot simply won't appear for analysis-only selections, which is acceptable.

### Loading state when setup is null

Replace the placeholder with a shimmer while `analysisLoading && !setup`:

```jsx
if (!displaySetup) {
  if (analysisLoading) {
    return (
      <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col p-4 gap-3">
        <div className="shimmer-row" style={{ height: 64 }} />
        <div className="shimmer-row" style={{ height: 40 }} />
        <div className="shimmer-row" style={{ height: 80 }} />
      </div>
    )
  }
  return (
    <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col items-center justify-center gap-2 text-t-muted p-5">
      <Target size={28} strokeWidth={1} color="var(--border-light)" />
      <span style={{ fontSize: 11, textAlign: 'center', lineHeight: 1.5 }}>
        Select a stock to view signals
      </span>
    </div>
  )
}
```

### Amber color fixes

Two hardcoded amber rgba values in the verdict badge must be updated:

| Location | Old | New |
|----------|-----|-----|
| `background` when `verdict_color === 'accent'` | `rgba(245,166,35,0.15)` | `rgba(80,216,240,0.15)` |
| `border` when `verdict_color === 'accent'` | `rgba(245,166,35,0.35)` | `rgba(80,216,240,0.35)` |

---

## App.jsx Changes

### Search always navigates to scanner

In the TopBar render, change:

```jsx
onSearchTicker={(t) => handleTickerClick(t, false)}
```

to:

```jsx
onSearchTicker={(t) => handleTickerClick(t, true)}
```

`switchTab = true` causes `handleTickerClick` to call `setActivePage('scanner')`, so the user lands on the scanner page where `StockIntelPanel` is rendered.

---

## Behavior After Fix

| Action | Before | After |
|--------|--------|-------|
| Click scanner row (in allSetups) | ✅ Full panel | ✅ Full panel (unchanged) |
| Click WL item (not in scan) | ❌ Empty placeholder | ✅ Full panel from analysis |
| Click Favorites item (not in scan) | ❌ Empty placeholder | ✅ Full panel from analysis |
| Search ticker (any page) | ❌ Stays on current page; empty if not in scan | ✅ Navigates to scanner; full panel from analysis |
| No ticker selected | ✅ Placeholder | ✅ Placeholder (unchanged) |
| Analysis loading, no setup | ❌ Placeholder shown immediately | ✅ Loading shimmer shown |

---

## What Does NOT Change

- Props interface of `StockIntelPanel`: `{ setup, livePrices, analysis, analysisLoading }` — unchanged
- `handleTickerClick` function signature — unchanged
- WL item click behavior (already navigates to scanner via `switchTab=true` default) — no change needed
- Backend endpoints — no changes
- All other pages — no changes
