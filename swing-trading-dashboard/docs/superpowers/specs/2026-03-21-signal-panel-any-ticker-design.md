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
| `frontend/src/App.jsx` | Stale-analysis guard on `analysis` prop; change search `switchTab` false → true |

No backend changes. No new API endpoints. No new component props.

---

## StockIntelPanel.jsx Changes

### Rename `setup` → `displaySetup` throughout

The component currently references `setup.xxx` directly in the render body. The full replacement requires renaming every `setup.xxx` reference in the render body to `displaySetup.xxx`. This does **NOT** include the prop parameter in the function signature — `setup` must remain as the destructured prop name so the synthesis expression `setup ?? (analysis ? {...} : null)` can read the incoming prop. Only usages after the synthesis line are renamed. Fields to rename:

- `setup.ticker` — in the header, TradingView `<a href>` link, and `livePrices` lookup
- `setup.setup_type` — in the subtitle line
- `setup.setup_score` — in `<ScoreBadge>`
- `setup.entry`, `setup.stop_loss`, `setup.take_profit` — in `livePrice` dist computation, `risk` computation, and TRADE PLAN rows
- `setup.rr` — in the `rr` computation
- `setup.rs_score`, `setup.is_vol_surge`, `setup.vol_ratio`, `setup.rs_blue_dot` — in SIGNALS rows

### Fallback logic

At the top of the component (after the synthesis block), the early-return logic becomes:

1. If `displaySetup` is null AND `analysisLoading` is true → render loading shimmer
2. If `displaySetup` is null AND neither loading nor analysis → render placeholder
3. Otherwise → render full panel using `displaySetup`

When `setup` (the prop) is not null, `displaySetup = setup` and behavior is identical to today.

### Synthesis mapping

`rs_score` field: `analysis.signals.rs_score` is a decimal value (e.g., `0.12`), same unit as `setup.rs_score`. The component multiplies by 100 for display (`Math.round(rs_score * 100)`), so no normalization needed.

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

`rs_blue_dot: false` is intentional — the analysis endpoint does not return this field. The blue dot won't appear for analysis-only selections, which is acceptable.

### Loading shimmer when setup is null

Place the synthesis expression and early-return block **immediately inside the `StockIntelPanel` function body, before the existing `if (!setup)` guard**. Replace the existing `if (!setup) { return ... }` block entirely with the following (do not leave both guards in place):

```jsx
const displaySetup = setup ?? (analysis ? { ...synthFields } : null)

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

### Amber color fixes — 4 locations

All hardcoded amber `rgba(245,166,35,...)` values in the file:

| Location | Old | New |
|----------|-----|-----|
| AI VERDICT badge `background` when `verdict_color === 'accent'` | `rgba(245,166,35,0.15)` | `rgba(80,216,240,0.15)` |
| AI VERDICT badge `border` when `verdict_color === 'accent'` | `rgba(245,166,35,0.35)` | `rgba(80,216,240,0.35)` |
| TradingView button `background` | `rgba(245,166,35,0.08)` | `rgba(80,216,240,0.08)` |
| TradingView button `border` | `rgba(245,166,35,0.2)` | `rgba(80,216,240,0.2)` |

---

## App.jsx Changes

### Stale-analysis guard

A race condition exists: if the user rapidly clicks two different tickers, a slow analysis fetch from the first click can resolve after the user has moved to the second ticker. To prevent a stale analysis from populating the synthesis, guard the `analysis` prop passed to `StockIntelPanel`:

```jsx
<StockIntelPanel
  setup={selectedSetup}
  livePrices={livePrices}
  analysis={analysis?.ticker === selectedTicker ? analysis : null}
  analysisLoading={analysisLoading}
/>
```

`selectedTicker` is available in App.jsx scope. `analysis.ticker` is always present in the response from `/api/analyze/{ticker}`.

### Search always navigates to scanner

In the TopBar render, change:

```jsx
onSearchTicker={(t) => handleTickerClick(t, false)}
```

to:

```jsx
onSearchTicker={(t) => handleTickerClick(t, true)}
```

`switchTab = true` causes `handleTickerClick` to call `setActivePage('scanner')`, landing the user on the scanner page where `StockIntelPanel` is rendered.

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
| Rapid ticker switching (race) | ⚠️ Stale analysis could appear | ✅ Stale analysis filtered in App.jsx |

---

## What Does NOT Change

- Props interface of `StockIntelPanel`: `{ setup, livePrices, analysis, analysisLoading }` — unchanged (stale guard is in App.jsx, not the component)
- `handleTickerClick` function signature — unchanged
- WL item click behavior (already navigates to scanner via `switchTab=true` default) — no change needed
- Backend endpoints — no changes
- All other pages — no changes
