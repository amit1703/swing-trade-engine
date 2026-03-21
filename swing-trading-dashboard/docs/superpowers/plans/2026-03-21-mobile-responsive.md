# Mobile Responsive Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken phone layout with a bottom tab bar (replacing the sidebar on mobile) and a slide-up signal sheet (replacing the side panel when tapping a ticker row).

**Architecture:** Two new components (`BottomTabBar`, `MobileSignalSheet`) are added; four existing files are modified. The sidebar is hidden on mobile via Tailwind's `hidden sm:flex`. The signal sheet is conditionally rendered from App.jsx when `mobileSheetOpen` is true, triggered by `handleTickerClick` when `window.innerWidth <= 640`.

**Tech Stack:** React 18, Tailwind CSS (v3 with `sm:` breakpoint = 640px), lucide-react icons, CSS custom properties defined in `index.css` `:root`.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `frontend/src/index.css` | CSS for sheet animation, `.intel-panel-desktop`, updated mobile media query, `.bottom-tab-bar` visibility |
| Create | `frontend/src/components/BottomTabBar.jsx` | Fixed 5-tab bottom nav bar — Scanner, WL, Favs, Port, More |
| Create | `frontend/src/components/MobileSignalSheet.jsx` | Slide-up overlay wrapping StockIntelPanel |
| Modify | `frontend/src/components/Sidebar.jsx` | Add `hidden sm:flex` — hides sidebar on mobile |
| Modify | `frontend/src/components/TopBar.jsx` | Add `more: 'More'` to PAGE_TITLES |
| Modify | `frontend/src/App.jsx` | Wire state, components, 'more' page, handleTickerClick, StockIntelPanel wrapper |

---

## Context You Need Before Starting

**CSS variables in use** (all defined in `index.css :root`):
- `--panel: #111111` — tab bar background
- `--border: #1e1e1e` — borders
- `--border-light: #2a2a2a` — sheet handle, top border
- `--card: #131313` — sheet background
- `--accent: #50d8f0` — active tab color
- `--muted: #555555` — inactive tab color
- `--text: #e0e0e0` — default text

**Key App.jsx variables** (already exist, no need to create):
- `allSetups` — derived constant, lines 104–112
- `selectedSetup` — derived constant, line 114: `allSetups.find(s => s.ticker === selectedTicker) ?? null`
- `selectedTicker` — state, line 69
- `analysis`, `analysisLoading` — state, lines 88–89
- `livePrices` — state, line 80

**StockIntelPanel props** (confirmed from current code):
```jsx
<StockIntelPanel setup={...} livePrices={...} analysis={...} analysisLoading={...} />
```
It handles `setup=null` gracefully (shows shimmer or placeholder).

**Sidebar.jsx root element** (current, line 23):
```jsx
<nav className="w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex flex-col h-full">
```

**TopBar.jsx PAGE_TITLES** (current, lines 4–12) — missing `'more'` key; fallback `?? activePage` would show lowercase `"more"`.

**Current mobile CSS block** location: `index.css` lines 204–241 — the entire `@media (max-width: 640px)` block gets replaced.

---

## Task 1: CSS Foundation

**Files:**
- Modify: `frontend/src/index.css`

This task adds all new CSS classes and replaces the old mobile media query. No visible change until components are wired in Task 5.

- [ ] **Step 1: Open `frontend/src/index.css` and locate the mobile block**

Find the comment `/* ── Mobile responsive (≤ 640px) ────────────────────── */` at line 204.

- [ ] **Step 2: Replace the entire `@media (max-width: 640px)` block**

Replace from `/* ── Mobile responsive */` through the closing `}` (currently lines 204–241) with:

```css
/* ── Intel panel — desktop only ──────────────────── */
.intel-panel-desktop { display: contents; }

/* ── Bottom tab bar — mobile only ────────────────── */
.bottom-tab-bar { display: flex; }
@media (min-width: 641px) { .bottom-tab-bar { display: none !important; } }

/* ── Mobile responsive (≤ 640px) ────────────────── */
@media (max-width: 640px) {

  /* Hide desktop-only intel panel */
  .intel-panel-desktop { display: none !important; }

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

  /* Scanner section — fill remaining space */
  .scanner-section {
    flex: 1 !important;
    min-height: 0;
  }

  /* Tables — don't shrink below content width */
  .terminal-table { min-width: 520px; }
}

/* ── Mobile signal sheet ──────────────────────────── */
.mobile-sheet-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 200;
  display: flex;
  align-items: flex-end;
}

.mobile-sheet {
  position: relative;
  width: 100%;
  max-height: 88vh;
  background: var(--card);
  border-radius: 16px 16px 0 0;
  border-top: 1px solid var(--border-light);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding-bottom: env(safe-area-inset-bottom);
  animation: sheet-slide-up 0.25s ease;
}

@keyframes sheet-slide-up {
  from { transform: translateY(100%); }
  to   { transform: translateY(0); }
}

.mobile-sheet-handle {
  width: 36px;
  height: 4px;
  background: var(--border-light);
  border-radius: 2px;
  margin: 10px auto 0;
  flex-shrink: 0;
}

.mobile-sheet-close {
  position: absolute;
  top: 8px;
  right: 14px;
  color: var(--muted);
  font-size: 18px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px 6px;
  line-height: 1;
}
.mobile-sheet-close:hover { color: var(--text); }

.mobile-sheet-content {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
```

- [ ] **Step 3: Verify the file looks correct**

Check that the old `nav { width: 48px !important; }` and `.mobile-hidden { display: none !important; }` lines are gone and the new blocks are present.

- [ ] **Step 4: Commit**

```bash
cd swing-trading-dashboard
git add frontend/src/index.css
git commit -m "style: replace mobile CSS — sheet styles, intel-panel-desktop, remove sidebar shrink"
```

---

## Task 2: BottomTabBar Component

**Files:**
- Create: `frontend/src/components/BottomTabBar.jsx`

**Props:** `activePage` (string), `onNavigate` (function)

- [ ] **Step 1: Create `frontend/src/components/BottomTabBar.jsx`**

```jsx
import { ScanLine, Star, Heart, Briefcase, MoreHorizontal } from 'lucide-react'

const TABS = [
  { id: 'scanner',   icon: ScanLine,       label: 'Scanner' },
  { id: 'watchlist', icon: Star,           label: 'WL'      },
  { id: 'favorites', icon: Heart,          label: 'Favs'    },
  { id: 'portfolio', icon: Briefcase,      label: 'Port'    },
  { id: 'more',      icon: MoreHorizontal, label: 'More'    },
]

export default function BottomTabBar({ activePage, onNavigate }) {
  return (
    <nav
      className="bottom-tab-bar"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: 56,
        background: 'var(--panel)',
        borderTop: '1px solid var(--border)',
        alignItems: 'stretch',
        zIndex: 100,
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
    >
      {TABS.map(({ id, icon: Icon, label }) => {
        const isActive = activePage === id || (id === 'more' && ['analytics', 'diagnostics', 'settings'].includes(activePage))
        return (
          <button
            key={id}
            onClick={() => onNavigate(id)}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 2,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: isActive ? 'var(--accent)' : 'var(--muted)',
              padding: '6px 0',
            }}
          >
            <Icon size={20} strokeWidth={1.75} />
            <span style={{
              fontSize: 9,
              fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: 700,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              lineHeight: 1,
            }}>
              {label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
```

- [ ] **Step 2: Verify the file was created**

```bash
ls frontend/src/components/BottomTabBar.jsx
```
Expected: file exists.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BottomTabBar.jsx
git commit -m "feat: add BottomTabBar component for mobile navigation"
```

---

## Task 3: MobileSignalSheet Component

**Files:**
- Create: `frontend/src/components/MobileSignalSheet.jsx`

**Props:** `onClose` (function), `setup` (object|null), `livePrices` (object), `analysis` (object|null), `analysisLoading` (boolean)

- [ ] **Step 1: Create `frontend/src/components/MobileSignalSheet.jsx`**

```jsx
import StockIntelPanel from './StockIntelPanel.jsx'

export default function MobileSignalSheet({ onClose, setup, livePrices, analysis, analysisLoading }) {
  return (
    <div
      className="mobile-sheet-overlay"
      onClick={onClose}
    >
      <div
        className="mobile-sheet"
        onClick={e => e.stopPropagation()}
      >
        <div className="mobile-sheet-handle" />
        <button className="mobile-sheet-close" onClick={onClose}>✕</button>
        <div className="mobile-sheet-content">
          <StockIntelPanel
            setup={setup}
            livePrices={livePrices}
            analysis={analysis}
            analysisLoading={analysisLoading}
          />
        </div>
      </div>
    </div>
  )
}
```

**Important:** The backdrop `div` has `onClick={onClose}`. The inner sheet `div` stops propagation with `e.stopPropagation()` so clicks inside the sheet don't close it.

- [ ] **Step 2: Verify the file was created**

```bash
ls frontend/src/components/MobileSignalSheet.jsx
```
Expected: file exists.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MobileSignalSheet.jsx
git commit -m "feat: add MobileSignalSheet slide-up overlay for mobile signal viewing"
```

---

## Task 4: Sidebar and TopBar Updates

**Files:**
- Modify: `frontend/src/components/Sidebar.jsx` (1 line change)
- Modify: `frontend/src/components/TopBar.jsx` (1 line change)

### Part A — Sidebar

- [ ] **Step 1: Open `frontend/src/components/Sidebar.jsx`**

Find line 23 (the root `<nav>` element):
```jsx
<nav className="w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex flex-col h-full">
```

- [ ] **Step 2: Add `hidden sm:flex` and remove standalone `flex`**

Change to:
```jsx
<nav className="hidden sm:flex w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex-col h-full">
```

Key: `flex` is removed (it was standalone), replaced by `sm:flex`. `flex-col` stays. `hidden` makes it `display:none` below 640px. `sm:flex` makes it `display:flex` at ≥640px.

### Part B — TopBar

- [ ] **Step 3: Open `frontend/src/components/TopBar.jsx`**

Find lines 4–12 (the `PAGE_TITLES` object):
```js
const PAGE_TITLES = {
  scanner:     'Scanner',
  watchlist:   'Watchlist',
  favorites:   'Favorites',
  portfolio:   'Portfolio',
  analytics:   'Analytics',
  diagnostics: 'Diagnostics',
  settings:    'Settings',
}
```

- [ ] **Step 4: Add `more` entry**

```js
const PAGE_TITLES = {
  scanner:     'Scanner',
  watchlist:   'Watchlist',
  favorites:   'Favorites',
  portfolio:   'Portfolio',
  analytics:   'Analytics',
  diagnostics: 'Diagnostics',
  settings:    'Settings',
  more:        'More',
}
```

- [ ] **Step 5: Commit both changes**

```bash
git add frontend/src/components/Sidebar.jsx frontend/src/components/TopBar.jsx
git commit -m "feat: hide sidebar on mobile, add More to TopBar page titles"
```

---

## Task 5: App.jsx Wiring

**Files:**
- Modify: `frontend/src/App.jsx`

This task wires everything together. Read the current `App.jsx` carefully before making changes — all existing logic stays intact.

### Part A — Imports and state

- [ ] **Step 1: Add imports at the top of App.jsx**

After the existing import block (near line 44), add:
```jsx
import BottomTabBar       from './components/BottomTabBar.jsx'
import MobileSignalSheet  from './components/MobileSignalSheet.jsx'
```

- [ ] **Step 2: Add `mobileSheetOpen` state**

After the `favorites` state declaration (around line 92), add:
```jsx
const [mobileSheetOpen, setMobileSheetOpen] = useState(false)
```

### Part B — handleTickerClick

- [ ] **Step 3: Update `handleTickerClick` (around lines 148–164)**

Find:
```jsx
const handleTickerClick = useCallback(async (ticker, switchTab = true) => {
  if (switchTab) setActivePage('scanner')
  setSelectedTicker(ticker)
  setChartData(null)
  setLoadingChart(true)
  setAnalysis(null)
  setAnalysisLoading(true)
```

Replace with:
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
```

Leave the rest of the function body (the `Promise.allSettled` call and state setters after it) **unchanged**.

### Part C — Render: main content wrapper

- [ ] **Step 4: Add bottom padding to main content wrapper**

Find the main content div (around line 311):
```jsx
<div className="flex-1 flex flex-col overflow-hidden min-w-0">
```

Change to:
```jsx
<div className="flex-1 flex flex-col overflow-hidden min-w-0 pb-[56px] sm:pb-0">
```

The `pb-[56px]` clears the 56px tab bar on mobile. `sm:pb-0` removes that padding on desktop.

### Part D — StockIntelPanel wrapper

- [ ] **Step 5: Fix the StockIntelPanel wrapper in the scanner layout**

Find (around lines 371–381):
```jsx
{!chartFocus && (
  <div className="mobile-hidden" style={{ display: 'contents' }}>
    <StockIntelPanel
      setup={selectedSetup}
      livePrices={livePrices}
      analysis={analysis?.ticker === selectedTicker ? analysis : null}
      analysisLoading={analysisLoading}
    />
  </div>
)}
```

Replace with:
```jsx
{!chartFocus && (
  <div className="intel-panel-desktop">
    <StockIntelPanel
      setup={selectedSetup}
      livePrices={livePrices}
      analysis={analysis?.ticker === selectedTicker ? analysis : null}
      analysisLoading={analysisLoading}
    />
  </div>
)}
```

`intel-panel-desktop` is the CSS class added in Task 1: `display: contents` on desktop (transparent to flex layout), `display: none` on mobile.

### Part E — 'more' page render

- [ ] **Step 6: Add the 'more' virtual page render block**

First, add `BarChart2, Activity, Settings` to the lucide-react import at the top of App.jsx. The existing import (around line 17) already imports from lucide-react indirectly via components — but App.jsx itself may not import from lucide-react directly. Add a new import line near the top (after the existing imports):
```jsx
import { BarChart2, Activity, Settings as SettingsIcon } from 'lucide-react'
```
Use `Settings as SettingsIcon` to avoid a name clash with any future Settings component import.

Note: `--card-border` is confirmed defined in `index.css :root` as `#222222` — use it without concern.

Find the settings stub (around line 467):
```jsx
{['settings'].includes(activePage) && (
```
*(leave settings stub unchanged)*

Add a new block **before** the settings stub:
```jsx
{/* ── MORE PAGE (mobile only — desktop sidebar never sets this) ── */}
{activePage === 'more' && (
  <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
    {[
      { id: 'analytics',   label: 'Analytics',   Icon: BarChart2 },
      { id: 'diagnostics', label: 'Diagnostics', Icon: Activity  },
      { id: 'settings',    label: 'Settings',    Icon: SettingsIcon },
    ].map(({ id, label, Icon }) => (
      <button
        key={id}
        onClick={() => setActivePage(id)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'var(--card)', border: '1px solid var(--card-border)',
          borderRadius: 10, padding: '14px 16px', cursor: 'pointer',
          color: 'var(--text)', fontFamily: '"IBM Plex Mono", monospace',
          fontSize: 13, textAlign: 'left',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon size={16} strokeWidth={1.75} />
          <span>{label}</span>
        </span>
        <span style={{ color: 'var(--muted)', fontSize: 18 }}>›</span>
      </button>
    ))}
  </div>
)}
```

### Part F — BottomTabBar render

- [ ] **Step 7: Render BottomTabBar**

Find the closing of the main content div (just before the overlays comment, around line 481):
```jsx
      </div>

      {/* ── Overlays (all pages) ─────────────────────────────── */}
```

Add `BottomTabBar` between the closing `</div>` and the overlays comment:
```jsx
      </div>

      {/* ── Bottom tab bar (mobile only) ─────────────────────── */}
      <BottomTabBar
        activePage={activePage}
        onNavigate={(page) => { setActivePage(page); setMobileSheetOpen(false) }}
      />

      {/* ── Overlays (all pages) ─────────────────────────────── */}
```

Note: `onNavigate` closes the sheet whenever the user switches pages.

### Part G — MobileSignalSheet render

- [ ] **Step 8: Render MobileSignalSheet in the overlays section**

Find the existing overlays section (around lines 481–491):
```jsx
      {/* ── Overlays (all pages) ─────────────────────────────── */}
      <SystemGuideModal isOpen={showGuide} onClose={() => setShowGuide(false)} />
      {devMode && debugTicker && (
```

Add MobileSignalSheet after `SystemGuideModal`:
```jsx
      {/* ── Overlays (all pages) ─────────────────────────────── */}
      <SystemGuideModal isOpen={showGuide} onClose={() => setShowGuide(false)} />
      {mobileSheetOpen && (
        <MobileSignalSheet
          onClose={() => setMobileSheetOpen(false)}
          setup={selectedSetup}
          livePrices={livePrices}
          analysis={analysis?.ticker === selectedTicker ? analysis : null}
          analysisLoading={analysisLoading}
        />
      )}
      {devMode && debugTicker && (
```

### Part H — Commit

- [ ] **Step 9: Start the dev server and verify visually**

```bash
# Terminal 1 — backend (if not already running)
cd swing-trading-dashboard/backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
cd swing-trading-dashboard/frontend
npm run dev
```

Open `http://localhost:5173` and open DevTools → Toggle Device Toolbar (Ctrl+Shift+M / Cmd+Shift+M) → set to iPhone 12 Pro (390px wide).

**Check:**
- [ ] Sidebar is gone (no left column)
- [ ] Bottom tab bar visible with 5 tabs
- [ ] Tapping Scanner/WL/Favs/Port switches pages
- [ ] Tapping More shows Analytics/Diagnostics/Settings list
- [ ] Tapping Analytics from More page opens it
- [ ] Tapping a row in any table opens the slide-up sheet
- [ ] Sheet shows ticker info, entry, stop, R:R, AI verdict
- [ ] Tapping backdrop closes sheet
- [ ] Tapping ✕ closes sheet
- [ ] Sheet slides up (not a jump)
- [ ] TopBar shows "More" when on the More page
- [ ] Switch back to desktop view (no device toolbar) — sidebar back, no tab bar, StockIntelPanel in right panel

- [ ] **Step 10: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: wire mobile bottom tab bar and signal sheet into App"
```

---

## Visual Verification Checklist (final)

After all tasks complete, run through this on mobile (DevTools ≤640px):

**Navigation:**
- [ ] All 5 tabs respond to tap
- [ ] Active tab highlighted in cyan (`#50d8f0`)
- [ ] More → Analytics, Diagnostics, Settings links work
- [ ] Tab switch closes any open sheet

**Signal sheet:**
- [ ] Opens when tapping row from Scanner, WL, Favs, Portfolio tables
- [ ] Shows ticker name, score, entry/stop/R:R, signals, verdict
- [ ] Close via backdrop tap
- [ ] Close via ✕ button
- [ ] Slide-up animation plays

**Content:**
- [ ] Stat cards scroll horizontally
- [ ] Scanner table scrolls horizontally
- [ ] Chart takes full width

**Desktop regression (≥641px):**
- [ ] Sidebar visible and all 7 nav items work
- [ ] No tab bar visible
- [ ] Right panel (StockIntelPanel) shows in scanner layout
- [ ] Clicking a ticker row does NOT open sheet, loads panel normally
