# Mobile Responsive Redesign — Design Spec

## Goal

Replace the current broken phone layout with a proper mobile UX:
- Bottom tab bar replaces the sidebar on mobile
- Slide-up signal sheet replaces the side panel when tapping a ticker row
- Full-width content area (no sidebar taking horizontal space)

---

## Breakpoint

`≤ 640px` — mobile. Matches Tailwind's `sm` breakpoint. No changes to desktop layout.

---

## Architecture

Two new components, four modified files:

**New:**
- `frontend/src/components/BottomTabBar.jsx` — fixed 5-tab bottom navigation bar (mobile only)
- `frontend/src/components/MobileSignalSheet.jsx` — slide-up overlay showing StockIntelPanel content

**Modified:**
- `frontend/src/App.jsx` — add `mobileSheetOpen` state, render new components, add bottom padding on mobile
- `frontend/src/components/Sidebar.jsx` — hide entirely on mobile
- `frontend/src/index.css` — clean up old mobile CSS, add sheet animation styles

---

## BottomTabBar.jsx

### Appearance
- Fixed at bottom, full width, 56px height
- Background: `var(--panel)` (`#111111`)
- Top border: `1px solid var(--border)` (`#1e1e1e`)
- 5 tabs evenly spaced (flex, `flex:1` each)
- Bottom safe-area padding: `padding-bottom: env(safe-area-inset-bottom)` (handles iPhone home indicator)

### Tabs
| Tab label | Icon (lucide-react) | `activePage` value |
|-----------|---------------------|--------------------|
| Scanner   | `ScanLine`          | `'scanner'`        |
| WL        | `Star`              | `'watchlist'`      |
| Favs      | `Heart`             | `'favorites'`      |
| Port      | `Briefcase`         | `'portfolio'`      |
| More      | `MoreHorizontal`    | `'more'`           |

Note: `'favorites'` is a verified valid `activePage` value confirmed by reading the current repo. App.jsx lines 426–439:
```jsx
{activePage === 'favorites' && (
  <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
    <FavoritesPage favorites={favorites} onToggleFavorite={toggleFavorite} allSetups={allSetups}
      watchlistItems={watchlistItems} selectedTicker={selectedTicker}
      onSelectTicker={handleTickerClick} livePrices={livePrices} />
  </div>
)}
```
No verification step needed — wire the tab directly.

### Tab appearance
Each tab:
```
flex-col, items-center, justify-center
icon: size=20
label: 9px, font-mono, uppercase, letter-spacing 0.06em
gap: 2px between icon and label
```
Active tab: icon + label color = `var(--accent)` (`#50d8f0`)
Inactive tab: color = `var(--muted)` (`#555555`)

### "More" virtual page
When `activePage === 'more'`, App.jsx renders a simple inline page:
```jsx
{activePage === 'more' && (
  <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 1, padding: 16 }}>
    {/* A list of nav buttons for Analytics, Diagnostics, Settings */}
    {/* Each button calls setActivePage('analytics') etc. */}
  </div>
)}
```
Each more-page item: full-width button, `background: var(--card)`, `border-radius: 10px`, icon + label left-aligned, `padding: 14px 16px`, `font-mono`, `color: var(--text)`. Arrow (`›`) on the right side.

More items: Analytics (`BarChart2`), Diagnostics (`Activity`), Settings (`Settings`).

### Tab navigation and sheet dismissal
When the user taps a tab to switch pages, the mobile sheet should close. Pass a combined handler:
```jsx
// In App.jsx:
<BottomTabBar
  activePage={activePage}
  onNavigate={(page) => { setActivePage(page); setMobileSheetOpen(false) }}
/>
```

### Visibility
```jsx
// In App.jsx render:
<BottomTabBar activePage={activePage} onNavigate={...} />
```
Hidden on desktop via CSS:
```css
.bottom-tab-bar { display: flex; }
@media (min-width: 641px) { .bottom-tab-bar { display: none; } }
```
(Or use Tailwind `sm:hidden` on the component wrapper.)

---

## MobileSignalSheet.jsx

### Props
```jsx
MobileSignalSheet({ open, onClose, setup, livePrices, analysis, analysisLoading })
```

### Structure
```
<div class="mobile-sheet-overlay">       ← backdrop, tap to close
<div class="mobile-sheet">               ← white/dark bottom drawer
  <div class="mobile-sheet-handle" />    ← drag handle bar
  <button class="mobile-sheet-close">✕</button>
  <div class="mobile-sheet-content">
    <StockIntelPanel setup={...} livePrices={...} analysis={...} analysisLoading={...} />
  </div>
</div>
```

### CSS (in index.css)
```css
.mobile-sheet-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.6);
  z-index: 200;
  display: flex; align-items: flex-end;
}

.mobile-sheet {
  position: relative;
  width: 100%;
  max-height: 88vh;
  background: var(--card);
  border-radius: 16px 16px 0 0;
  border-top: 1px solid var(--border-light);
  overflow: hidden;
  display: flex; flex-direction: column;
  padding-bottom: env(safe-area-inset-bottom);

  /* slide-up animation */
  transform: translateY(0);
  animation: sheet-slide-up 0.25s ease;
}

@keyframes sheet-slide-up {
  from { transform: translateY(100%); }
  to   { transform: translateY(0); }
}

.mobile-sheet-handle {
  width: 36px; height: 4px;
  background: var(--border-light);  /* confirmed: #2a2a2a — defined in index.css :root */
  border-radius: 2px;
  margin: 10px auto 0;
  flex-shrink: 0;
}

.mobile-sheet-close {
  position: absolute; top: 8px; right: 14px;
  color: var(--muted); font-size: 16px;
  background: none; border: none; cursor: pointer; padding: 4px;
}

.mobile-sheet-content {
  flex: 1; overflow-y: auto;
  padding: 8px 0;
}
```

### When to render
Use conditional render in App.jsx — component is mounted only when the sheet is open:
```jsx
{mobileSheetOpen && <MobileSignalSheet open={true} onClose={...} ... />}
```
This keeps the DOM clean and means the sheet's enter animation always plays on mount.

---

## App.jsx Changes

### New state
```jsx
const [mobileSheetOpen, setMobileSheetOpen] = useState(false)
```

### Modified handleTickerClick
Two changes: (a) open the sheet on mobile, (b) do NOT navigate to scanner on mobile (users stay on their current page and view signal info in the sheet):
```jsx
const handleTickerClick = useCallback(async (ticker, switchTab = true) => {
  const isMobile = window.innerWidth <= 640
  if (switchTab && !isMobile) setActivePage('scanner')
  if (isMobile) setMobileSheetOpen(true)
  setSelectedTicker(ticker)
  setChartData(null)
  setLoadingChart(true)
  setAnalysis(null)
  setAnalysisLoading(true)
  // ... rest of function unchanged
}, [])
```
On desktop (> 640px): `switchTab` behavior is unchanged — tapping from WL/Favs navigates to scanner.
On mobile (≤ 640px): page stays where it is, sheet opens regardless of which page triggered the tap.

### Render additions

1. Add bottom padding to main content wrapper on mobile (to clear the tab bar):
```jsx
<div className="flex-1 flex flex-col overflow-hidden min-w-0 pb-[56px] sm:pb-0">
```

2. Render BottomTabBar before closing the outer flex div:
```jsx
<BottomTabBar activePage={activePage} onNavigate={setActivePage} />
```

3. Render MobileSignalSheet in the overlays section:
```jsx
{mobileSheetOpen && (
  <MobileSignalSheet
    onClose={() => setMobileSheetOpen(false)}
    setup={selectedSetup}
    livePrices={livePrices}
    analysis={analysis?.ticker === selectedTicker ? analysis : null}
    analysisLoading={analysisLoading}
  />
)}
```

`selectedSetup` is an existing derived variable in App.jsx (line 114):
```jsx
const selectedSetup = allSetups.find(s => s.ticker === selectedTicker) ?? null
```
`allSetups` is also an existing derived constant in App.jsx (lines 104–112):
```jsx
const allSetups = [
  ...vcpSetups, ...pullbackSetups, ...baseSetups,
  ...resBreakoutSetups, ...htfSetups, ...lceSetups,
]
```
Both already exist — no new state is needed.

**StockIntelPanel prop interface (verified from current codebase):**
```jsx
export default function StockIntelPanel({ setup, livePrices, analysis, analysisLoading })
```
Prop names are `setup`, `livePrices`, `analysis`, `analysisLoading` — match the MobileSignalSheet passthrough exactly. StockIntelPanel handles `setup=null` and `analysis=null` gracefully (renders a loading shimmer when `analysisLoading` is true, a placeholder otherwise).

4. Add `'more'` to the settings page stub so tapping More doesn't render nothing on larger screens:
```jsx
{['settings', 'more'].includes(activePage) && ...}
```
(On mobile, `activePage === 'more'` renders the MorePage. On desktop the sidebar never shows 'more', so this is only a fallback safety net.)

---

## Sidebar.jsx Changes

Add `hidden sm:flex` to the root `<nav>` so it disappears on mobile:

**Before:**
```jsx
<nav className="w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex flex-col h-full">
```

**After:**
```jsx
<nav className="hidden sm:flex w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex-col h-full">
```

Note: `flex` from `sm:flex` replaces the standalone `flex` class — do NOT keep both.

---

## index.css Changes

Replace the current `@media (max-width: 640px)` section entirely:

```css
/* ── Mobile responsive (≤ 640px) ────────────────────── */
@media (max-width: 640px) {

  /* Stat cards — horizontal scroll row */
  .stat-cards-row {
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 4px;
  }
  .stat-card {
    min-width: 130px;
    flex-shrink: 0;
    padding: 12px 14px;
  }
  .stat-card-value { font-size: 22px; }

  /* Chart row — stack vertically, chart takes full width */
  .chart-row {
    flex-direction: column !important;
    flex: 0 0 240px !important;
  }

  /* Scanner section — fill remaining space, allow horizontal scroll */
  .scanner-section {
    flex: 1 !important;
    min-height: 0;
  }

  /* Tables — don't shrink below content width */
  .terminal-table { min-width: 520px; }
}
```

**Removed vs. previous version:**
- `nav { width: 48px !important; }` → sidebar is now hidden entirely (no need to shrink it)
- `.mobile-hidden { display: none !important; }` → StockIntelPanel now shows in the sheet
- `.nav-btn { width/height }` → no longer relevant

**Added (new CSS blocks after the media query):**
The `.mobile-sheet-overlay`, `.mobile-sheet`, `.mobile-sheet-handle`, `.mobile-sheet-close`, `.mobile-sheet-content`, and `@keyframes sheet-slide-up` blocks described above.

---

## App.jsx — StockIntelPanel wrapper cleanup

The current wrapper div uses `className="mobile-hidden"` and `style={{ display: 'contents' }}`. Replace with a plain CSS class `.intel-panel-desktop`.

**Before:**
```jsx
{!chartFocus && (
  <div className="mobile-hidden" style={{ display: 'contents' }}>
    <StockIntelPanel ... />
  </div>
)}
```

**After:**
```jsx
{!chartFocus && (
  <div className="intel-panel-desktop">
    <StockIntelPanel ... />
  </div>
)}
```

Add `.intel-panel-desktop` to `index.css`:
```css
/* ── Intel panel — desktop only ──────────────────── */
.intel-panel-desktop { display: contents; }
```

And inside the `@media (max-width: 640px)` block:
```css
.intel-panel-desktop { display: none !important; }
```

`display: contents` on desktop makes the wrapper transparent to the flex layout (StockIntelPanel remains a direct flex child). `display: none` on mobile hides it entirely. No Tailwind utility dependency — pure CSS, deterministic.

---

## Page Title in TopBar

The TopBar already receives `activePage` prop. Add `'more': 'More'` to its page title map (wherever it maps page IDs to display names — typically a `PAGE_TITLES` object or similar). This ensures the TopBar shows "More" instead of a blank or undefined string when the More tab is active.

---

## Testing Checklist

**Mobile (resize browser to ≤ 640px or DevTools iPhone):**
- [ ] Sidebar is invisible (no white space on left)
- [ ] Bottom tab bar is visible at bottom
- [ ] Tapping Scanner/WL/Favs/Port switches pages
- [ ] Tapping "More" shows Analytics/Diagnostics/Settings list
- [ ] Tapping a ticker row opens the slide-up sheet
- [ ] Sheet shows StockIntelPanel content (signals, entry, stop, R:R, verdict)
- [ ] Tapping backdrop closes the sheet
- [ ] Tapping ✕ closes the sheet
- [ ] Sheet animation slides up smoothly (0.25s)
- [ ] iPhone safe area padding at bottom of sheet and tab bar (test in DevTools with notch)
- [ ] Stat cards scroll horizontally
- [ ] Scanner table scrolls horizontally (min-width 520px)

**Desktop (> 640px):**
- [ ] Sidebar still visible and functional (no regression)
- [ ] Bottom tab bar not visible
- [ ] StockIntelPanel shows in scanner layout as before
- [ ] MobileSignalSheet does not appear when clicking tickers

---

## Files Summary

| Action | File |
|--------|------|
| Create | `frontend/src/components/BottomTabBar.jsx` |
| Create | `frontend/src/components/MobileSignalSheet.jsx` |
| Modify | `frontend/src/App.jsx` |
| Modify | `frontend/src/components/Sidebar.jsx` |
| Modify | `frontend/src/index.css` |
