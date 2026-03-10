# Scanner UI Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove redundant pages (Dashboard, Setups), simplify the StatCards row, filter options tickers from the scanner, redesign the WatchlistPanel, restore dev mode, and generally reduce visual noise.

**Architecture:** All changes are purely frontend (React JSX). No backend changes. Components touched: `Sidebar.jsx`, `StatCards.jsx`, `App.jsx`, `ScannerFilters.jsx`, `ScannerTable.jsx`, `WatchlistPanel.jsx`, `TopBar.jsx`. The DebugDrawer already exists and works — dev mode just needs a secret activation mechanism.

**Tech Stack:** React 18, Vite, lucide-react, IBM Plex Mono / Barlow Condensed / Inter fonts, CSS custom properties (`var(--go)`, `var(--halt)`, `var(--accent)`, `var(--muted)`, `var(--card)`, `var(--border)`, etc.)

---

## Context You Must Know

### Current pages in the sidebar (Sidebar.jsx NAV_ITEMS):
```
dashboard → Scanner → setups → watchlist → portfolio → analytics
```
`dashboard` and `setups` are stubs (show 🚧). Remove both from the nav.

### StatCards currently renders 4 cards (StatCards.jsx):
1. `RegimeCard` — Market Regime ✅ KEEP
2. `SetupsCard` — Active Setups count ❌ REMOVE
3. `TopScoreCard` — Top Score Today ❌ REMOVE
4. `SpyCard` — SPY Trend ✅ KEEP

### Options tickers filter:
In `App.jsx`, `allSetups` array includes `optionsSetups`. These appear in `ScannerTable` with `setup_type = 'OPTIONS-CATALYST'`. They should be excluded from `allSetups` that feeds the scanner (but state can still be fetched for future use).

### Dev mode toggle — current behavior:
`devMode` state in App.jsx. Currently no UI toggle to turn it on/off — it defaults to `false`. It used to be a button in an older Header component. The `DebugDrawer` works when `devMode=true && debugTicker != null`. We need a way to activate it — a secret keyboard shortcut `d` or `D` (when not in an input).

### Watchlist is used as a standalone page:
`activePage === 'watchlist'` renders `<WatchlistPanel>`. The WatchlistPanel is 190px wide and uses Tailwind className strings mixed with inline styles. The redesign should improve it while keeping the same data structure (items have: `ticker, pattern_type, distance_pct, rs_score, rs_blue_dot`).

### Key CSS variables available:
```css
--bg, --surface, --panel, --card, --border, --card-border
--text, --muted
--go (#00C87A), --halt (#FF2D55), --accent (#F5A623), --blue (#00C8FF)
--radius-card (12px), --shadow-card
```

---

## Task 1: Remove Dashboard and Setups from Sidebar

**Files:**
- Modify: `frontend/src/components/Sidebar.jsx`
- Modify: `frontend/src/App.jsx` (remove stub renderer for 'dashboard' and 'setups')

**Step 1: Edit Sidebar.jsx — remove Dashboard and Setups from NAV_ITEMS**

Remove the `LayoutDashboard` and `ListFilter` imports and their entries.

New `NAV_ITEMS`:
```js
import { ScanLine, Star, Briefcase, BarChart2 } from 'lucide-react'

const NAV_ITEMS = [
  { id: 'scanner',   icon: ScanLine,  label: 'Scanner'   },
  { id: 'watchlist', icon: Star,      label: 'Watchlist' },
  { id: 'portfolio', icon: Briefcase, label: 'Portfolio' },
  { id: 'analytics', icon: BarChart2, label: 'Analytics' },
]
```

**Step 2: Edit App.jsx — update the stub page check**

Find this block:
```js
{['dashboard', 'setups', 'settings'].includes(activePage) && (
```

Replace with:
```js
{['settings'].includes(activePage) && (
```

Also update `activePage` initial state — since `dashboard` is removed, change default to `'scanner'` (it's already `'scanner'`, so this is a no-op — just verify).

**Step 3: Update PAGE_TITLES in TopBar.jsx**

Remove `dashboard` and `setups` entries:
```js
const PAGE_TITLES = {
  scanner:   'Scanner',
  watchlist: 'Watchlist',
  portfolio: 'Portfolio',
  analytics: 'Analytics',
  settings:  'Settings',
}
```

**Step 4: Manual verification**

Open the app. Confirm sidebar shows only 4 icons (Scanner, Watchlist, Portfolio, Analytics). No Dashboard or Setups.

**Step 5: Commit**
```bash
git add frontend/src/components/Sidebar.jsx frontend/src/components/TopBar.jsx frontend/src/App.jsx
git commit -m "feat(ui): remove Dashboard and Setups pages from navigation"
```

---

## Task 2: Slim Down StatCards — Remove Active Setups and Top Score

**Files:**
- Modify: `frontend/src/components/StatCards.jsx`

**Step 1: Edit StatCards.jsx — delete SetupsCard and TopScoreCard components**

Delete the entire `SetupsCard` function (lines 64–81) and `TopScoreCard` function (lines 83–115).

Also remove unused imports: `Zap` and `Target` from lucide-react.

**Step 2: Update the export function to only render 2 cards**

Change:
```js
export default function StatCards({ regime, allSetups }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '12px 16px', flexShrink: 0 }}>
      <RegimeCard regime={regime} />
      <SetupsCard allSetups={allSetups} />
      <TopScoreCard allSetups={allSetups} />
      <SpyCard regime={regime} />
    </div>
  )
}
```

To:
```js
export default function StatCards({ regime }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '12px 16px', flexShrink: 0 }}>
      <RegimeCard regime={regime} />
      <SpyCard regime={regime} />
    </div>
  )
}
```

**Step 3: Update App.jsx call site**

Find `<StatCards regime={regime} allSetups={allSetups} />` and change to `<StatCards regime={regime} />`.

**Step 4: Manual verification**

Check scanner page — only Regime card and SPY Trend card appear in the top row.

**Step 5: Commit**
```bash
git add frontend/src/components/StatCards.jsx frontend/src/App.jsx
git commit -m "feat(ui): simplify StatCards — keep only Regime and SPY Trend"
```

---

## Task 3: Filter Options Tickers from Scanner

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/ScannerFilters.jsx`

**Step 1: Edit App.jsx — exclude optionsSetups from allSetups**

Find:
```js
const allSetups = [
  ...vcpSetups,
  ...pullbackSetups,
  ...baseSetups,
  ...resBreakoutSetups,
  ...htfSetups,
  ...lceSetups,
  ...optionsSetups,
]
```

Change to (remove `...optionsSetups`):
```js
const allSetups = [
  ...vcpSetups,
  ...pullbackSetups,
  ...baseSetups,
  ...resBreakoutSetups,
  ...htfSetups,
  ...lceSetups,
]
```

Keep `optionsSetups` state and `fetchOptionsSetups()` call — just exclude from the main scanner feed.

**Step 2: Edit ScannerFilters.jsx — remove OPTIONS from filter buttons**

Find:
```js
const SETUP_TYPES = ['ALL', 'VCP', 'PULLBACK', 'BASE', 'RES-BRK', 'HTF', 'LCE', 'OPTIONS']
```

Change to:
```js
const SETUP_TYPES = ['ALL', 'VCP', 'PULLBACK', 'BASE', 'RES-BRK', 'HTF', 'LCE']
```

**Step 3: Edit ScannerTable.jsx — remove OPTIONS-CATALYST from type maps**

Remove from `SETUP_TYPE_LABEL`:
```js
'OPTIONS-CATALYST': 'OPT',
```

Remove from `TYPE_COLOR`:
```js
'OPTIONS-CATALYST': '#00C8FF',
```

Remove from the filter logic in `rows` useMemo:
```js
if (f === 'OPTIONS')  return t === 'OPTIONS-CATALYST'
```

**Step 4: Also update live price polling in App.jsx**

In `fetchLivePrices`, remove `...optionsSetups` from the tickers array:
```js
const allTickers = [
  ...vcpSetups,
  ...pullbackSetups,
  ...baseSetups,
  ...resBreakoutSetups,
  ...htfSetups,
  ...lceSetups,
].map((s) => s.ticker)
```

**Step 5: Manual verification**

Run a scan. Verify no OPTIONS-CATALYST setups appear in the scanner table.

**Step 6: Commit**
```bash
git add frontend/src/App.jsx frontend/src/components/ScannerFilters.jsx frontend/src/components/ScannerTable.jsx
git commit -m "feat(ui): exclude options-catalyst setups from scanner and price polling"
```

---

## Task 4: Restore Dev Mode via Secret Keyboard Shortcut

**Files:**
- Modify: `frontend/src/App.jsx`

**Step 1: Edit the keyboard handler in App.jsx**

Find the existing keyboard handler:
```js
const handler = (e) => {
  if (document.activeElement.tagName === 'INPUT') return
  if (e.key === '?') setShowGuide(v => !v)
  if (e.key === 'f' || e.key === 'F') setChartFocus(v => !v)
  if (e.key === 'Escape') setDebugTicker(null)
}
```

Add dev mode toggle on `d` or `D`:
```js
const handler = (e) => {
  if (document.activeElement.tagName === 'INPUT') return
  if (e.key === '?') setShowGuide(v => !v)
  if (e.key === 'f' || e.key === 'F') setChartFocus(v => !v)
  if (e.key === 'Escape') setDebugTicker(null)
  if (e.key === 'd' || e.key === 'D') {
    setDevMode(v => {
      const next = !v
      if (!next) { setDryRun(false); setDebugTicker(null) }
      return next
    })
  }
}
```

**Step 2: Add subtle dev mode indicator to TopBar**

In TopBar.jsx, the `devMode` prop is already passed. Currently it only shows the DRY button when devMode is true. Add a small indicator that shows when dev mode is active — place it near the guide button:

```jsx
{devMode && (
  <div style={{
    fontSize: 8, padding: '2px 6px', borderRadius: 4,
    background: 'rgba(155,110,255,0.15)',
    border: '1px solid rgba(155,110,255,0.35)',
    color: '#9B6EFF',
    fontFamily: '"IBM Plex Mono", monospace',
    fontWeight: 700,
    letterSpacing: '0.08em',
    cursor: 'pointer',
  }}
  onClick={onToggleDev}
  title="Press D to disable Dev Mode"
  >
    DEV
  </div>
)}
```

Place this BEFORE the guide button `?`. Remove the old `onToggleDev` button reference since we're using the keyboard now (keep the prop for the DEV badge click).

**Step 3: Wire debug click from ScannerTable to App**

The DebugDrawer is opened by setting `debugTicker`. But currently there's no way to trigger it from a row without a dedicated debug button. Add a double-click (dblclick) on the table row to trigger debug when devMode is active.

In `ScannerTable.jsx`, add an `onDebug` prop:
```js
export default function ScannerTable({ allSetups, filters, selectedTicker, onSelectTicker, livePrices = {}, devMode = false, onDebug }) {
```

On each `<tr>`, add:
```jsx
onDoubleClick={devMode && onDebug ? () => onDebug(s.ticker) : undefined}
```

In `App.jsx`, pass to ScannerTable:
```jsx
<ScannerTable
  allSetups={allSetups}
  filters={filters}
  selectedTicker={selectedTicker}
  onSelectTicker={handleTickerClick}
  livePrices={livePrices}
  devMode={devMode}
  onDebug={handleDebug}
/>
```

**Step 4: Manual verification**

1. Open app → press `D` → TopBar shows purple DEV badge
2. Double-click any row in scanner → DebugDrawer opens showing engine scores
3. Press `D` again → DEV mode off, drawer closes
4. Pressing `D` while in an input field should NOT toggle dev mode (already handled)

**Step 5: Commit**
```bash
git add frontend/src/App.jsx frontend/src/components/TopBar.jsx frontend/src/components/ScannerTable.jsx
git commit -m "feat(ui): restore dev mode via D shortcut + double-click debug drill-down"
```

---

## Task 5: Redesign WatchlistPanel

**Files:**
- Modify: `frontend/src/components/WatchlistPanel.jsx`

The current panel is 190px, uses a mix of Tailwind classes and inline styles, has small (7–10px) text, and looks cramped. Goal: cleaner rows, better spacing, larger readable text, aligned columns.

**Step 1: Rewrite WatchlistPanel.jsx**

Replace the entire file content with:

```jsx
import { useState } from 'react'

export default function WatchlistPanel({ items, selectedTicker, onSelectTicker, loading }) {
  const [showAll, setShowAll] = useState(false)

  // Filter: hide KDE-BRK items that are >1% above breakout (too extended)
  const filtered = items.filter(item =>
    !(item.pattern_type === 'KDE-BRK' && (item.distance_pct ?? 0) > 1.0)
  )

  const scoreItem = (item) => {
    const distScore = Math.max(0, 1 - (item.distance_pct ?? 5) / 5.0) * 0.5
    const rsRaw = item.rs_score ?? 0
    const rsScore = Math.max(0, Math.min(1, (rsRaw + 1) / 2)) * 0.3
    const blueDot = (item.rs_blue_dot ? 1 : 0) * 0.2
    return distScore + rsScore + blueDot
  }

  const nearItems = filtered
    .filter(item => item.pattern_type === 'KDE' || item.pattern_type === 'TDL')
    .sort((a, b) => scoreItem(b) - scoreItem(a))

  const confirmedItems = filtered
    .filter(item => item.pattern_type === 'KDE-BRK' || item.pattern_type === 'TDL-BRK')
    .sort((a, b) => (a.distance_pct ?? 999) - (b.distance_pct ?? 999))

  const visibleNearItems = showAll ? nearItems : nearItems.slice(0, 15)

  const SectionHeader = ({ label, count }) => (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '6px 12px',
      borderBottom: '1px solid var(--border)',
      background: 'rgba(255,255,255,0.02)',
    }}>
      <span style={{
        fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase',
        color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 9, padding: '1px 6px', borderRadius: 4,
        background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
        color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
      }}>
        {count}
      </span>
    </div>
  )

  const WatchRow = ({ item }) => {
    const isSelected      = selectedTicker === item.ticker
    const isConfirmedBrk  = item.pattern_type === 'KDE-BRK' || item.pattern_type === 'TDL-BRK'
    const hasRsBlueDot    = !!item.rs_blue_dot
    const rsRaw           = item.rs_score ?? 0
    const rsInt           = Math.round(rsRaw * 100)
    const rsLabel         = rsInt === 0 ? '±0' : rsInt > 0 ? `+${rsInt}` : `${rsInt}`
    const rsColor         = rsInt >= 5 ? 'var(--go)' : rsInt <= -5 ? 'var(--halt)' : 'var(--muted)'
    const distLabel       = isConfirmedBrk
      ? `▲${item.distance_pct?.toFixed(1)}%`
      : `${item.distance_pct?.toFixed(1)}%`
    const distColor       = isConfirmedBrk ? 'var(--go)'
      : (item.distance_pct ?? 99) < 0.8 ? 'var(--go)' : 'var(--accent)'

    return (
      <div
        onClick={() => onSelectTicker(item.ticker)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid var(--border)',
          borderLeft: isSelected
            ? '3px solid var(--accent)'
            : isConfirmedBrk
            ? '3px solid rgba(0,200,122,0.5)'
            : '3px solid transparent',
          background: isSelected
            ? 'rgba(245,166,35,0.06)'
            : isConfirmedBrk
            ? 'rgba(0,200,122,0.03)'
            : 'transparent',
          cursor: 'pointer',
          transition: 'background 0.1s',
          gap: 8,
        }}
        onMouseEnter={e => {
          if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = isSelected
            ? 'rgba(245,166,35,0.06)'
            : isConfirmedBrk ? 'rgba(0,200,122,0.03)' : 'transparent'
        }}
      >
        {/* Left: ticker + RS */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
            <span style={{
              fontSize: 12, fontWeight: 700, letterSpacing: '0.03em',
              color: isSelected ? 'var(--accent)' : isConfirmedBrk ? 'var(--go)' : 'var(--text)',
              fontFamily: '"IBM Plex Mono", monospace',
            }}>
              {item.ticker}
            </span>
            {hasRsBlueDot && (
              <span style={{ color: 'var(--blue)', fontSize: 9 }}>●</span>
            )}
          </div>
          <span style={{
            fontSize: 9, color: rsColor,
            fontFamily: '"IBM Plex Mono", monospace',
          }}>
            RS {rsLabel}
          </span>
        </div>

        {/* Right: distance + pattern badge + TV link */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, color: distColor,
            fontFamily: '"IBM Plex Mono", monospace',
          }}>
            {distLabel}
          </span>
          <span style={{
            fontSize: 8, padding: '2px 5px', borderRadius: 4,
            fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
            letterSpacing: '0.04em',
            background: isConfirmedBrk ? 'rgba(0,200,122,0.15)' : 'rgba(0,200,255,0.08)',
            color: isConfirmedBrk ? 'var(--go)' : 'var(--blue)',
            border: isConfirmedBrk ? '1px solid rgba(0,200,122,0.35)' : '1px solid rgba(0,200,255,0.25)',
          }}>
            {item.pattern_type}
          </span>
          <a
            href={`https://www.tradingview.com/chart/?symbol=${item.ticker}&interval=D`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{
              fontSize: 8, padding: '2px 4px', borderRadius: 3,
              border: '1px solid rgba(245,166,35,0.25)',
              color: 'rgba(245,166,35,0.5)',
              fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
              textDecoration: 'none',
            }}
          >
            TV
          </a>
        </div>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', overflow: 'hidden',
      background: 'var(--panel)',
    }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 12px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
          textTransform: 'uppercase', color: 'var(--muted)',
          fontFamily: '"IBM Plex Mono", monospace',
        }}>
          Watchlist
        </span>
        <span style={{
          fontSize: 9, padding: '1px 7px', borderRadius: 4,
          background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
          color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
        }}>
          {filtered.length}
        </span>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 12 }}>
            {[...Array(4)].map((_, i) => (
              <div key={i} style={{
                height: 48, borderRadius: 6,
                background: 'rgba(255,255,255,0.04)',
                opacity: 1 - i * 0.2,
                animation: 'pulse 1.5s ease-in-out infinite',
              }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{
            padding: '32px 16px', textAlign: 'center',
            color: 'var(--muted)', fontSize: 10,
            fontFamily: '"IBM Plex Mono", monospace',
            letterSpacing: '0.1em', textTransform: 'uppercase',
          }}>
            No items
          </div>
        ) : (
          <>
            {nearItems.length > 0 && (
              <>
                <SectionHeader label="Near Breakout" count={nearItems.length} />
                {visibleNearItems.map(item => <WatchRow key={item.ticker} item={item} />)}
                {nearItems.length > 15 && (
                  <button
                    onClick={() => setShowAll(v => !v)}
                    style={{
                      width: '100%', padding: '6px',
                      background: 'transparent', border: 'none',
                      borderTop: '1px solid var(--border)',
                      color: 'var(--muted)', cursor: 'pointer',
                      fontSize: 9, letterSpacing: '0.1em',
                      textTransform: 'uppercase',
                      fontFamily: '"IBM Plex Mono", monospace',
                    }}
                  >
                    {showAll ? '▲ Show top 15' : `▼ Show all ${nearItems.length}`}
                  </button>
                )}
              </>
            )}
            {confirmedItems.length > 0 && (
              <>
                <SectionHeader label="Confirmed Break" count={confirmedItems.length} />
                {confirmedItems.map(item => <WatchRow key={item.ticker} item={item} />)}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
```

**Step 2: Update App.jsx — Watchlist page wrapper**

The watchlist page currently has fixed `padding: 16` wrapper. The new panel needs full height. Change:
```jsx
{activePage === 'watchlist' && (
  <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
    <WatchlistPanel ...
```

To:
```jsx
{activePage === 'watchlist' && (
  <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
    <WatchlistPanel ...
```

**Step 3: Manual verification**

Navigate to Watchlist page. Rows should be taller (48px-ish), ticker text at 12px, RS and distance visible without squinting. Select a ticker — left accent border appears.

**Step 4: Commit**
```bash
git add frontend/src/components/WatchlistPanel.jsx frontend/src/App.jsx
git commit -m "feat(ui): redesign WatchlistPanel with improved spacing and typography"
```

---

## Task 6: General Visual Polish

**Files:**
- Modify: `frontend/src/index.css` (if spacing/token fixes needed)
- Modify: `frontend/src/App.jsx` (layout tweaks)

**Step 1: Check chart/panel gap in scanner**

In `App.jsx`, the middle section (chart + StockIntelPanel) has `gap: 12` and `padding: '0 16px 12px'`. The bottom table has `margin: '0 16px 16px'`. This is consistent — no change needed.

**Step 2: Reduce visual noise in TopBar**

The TopBar currently shows: title | search | [spacer] | market status | RUN SCAN | [DEV in dev mode] | DRY | ? | TR avatar.

Remove the user avatar placeholder (TR) — it serves no purpose and adds clutter:

In `TopBar.jsx`, delete:
```jsx
{/* User avatar placeholder */}
<div style={{
  width: 30, height: 30, borderRadius: '50%',
  background: 'linear-gradient(135deg, var(--go), var(--blue))',
  ...
}}>
  TR
</div>
```

**Step 3: Verify ScannerFilters layout**

The ScannerFilters bar uses `flexWrap: 'wrap'` which can cause wrapping on narrow screens. Keep as-is but verify there are no visual breaks on 1280px wide window.

**Step 4: Ensure scanner table empty state is clean**

In ScannerTable when no rows match: the message "No setups match current filters" already exists. Verify it's visible and not overlapping.

**Step 5: Commit**
```bash
git add frontend/src/components/TopBar.jsx
git commit -m "feat(ui): general polish — remove avatar placeholder, reduce visual noise"
```

---

## Final Verification Checklist

Run these checks before calling the work complete:

- [ ] Sidebar shows exactly 4 icons: Scanner, Watchlist, Portfolio, Analytics
- [ ] No Dashboard or Setups page accessible
- [ ] StatCards row shows only Regime + SPY Trend (2 cards)
- [ ] Scanner table contains no OPTIONS-CATALYST rows
- [ ] OPTIONS filter button gone from ScannerFilters
- [ ] Press `D` key → purple DEV badge appears in TopBar
- [ ] With DEV on, double-click a scanner row → DebugDrawer opens
- [ ] Press `D` again → DEV off, drawer closes
- [ ] Watchlist page: rows are clean, ticker 12px, RS label visible, distance aligned
- [ ] TopBar: no TR avatar in top right
- [ ] No JS console errors
