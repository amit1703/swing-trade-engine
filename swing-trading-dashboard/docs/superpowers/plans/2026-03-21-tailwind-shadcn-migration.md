# Tailwind + shadcn/ui Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all 18 frontend JSX components from inline CSS to Tailwind utility classes + shadcn/ui primitives, applying a polished dark terminal aesthetic with amber accent.

**Architecture:** Layered migration (Layer 0 → 1 → 2 → 3) — app stays functional after every task. No props/state/logic changes anywhere. Tailwind is already installed; shadcn/ui is the only new dependency. All CSS variables keep hex format; shadcn color entries in tailwind.config.js use `var(--xxx)` not `hsl(var(--xxx))`.

**Tech Stack:** React 18, Vite 5, Tailwind CSS v3 (already installed), shadcn/ui (new), lucide-react (already installed), IBM Plex Mono (already loaded via Google Fonts)

**Spec:** `docs/superpowers/specs/2026-03-21-tailwind-shadcn-migration-design.md`

---

## File Map

| File | Action | Task |
|------|--------|------|
| `frontend/vite.config.js` | Modify — add ESM-safe `@/` alias | 0 |
| `frontend/jsconfig.json` | Create — VS Code alias support | 0 |
| `frontend/tailwind.config.js` | Modify — add darkMode, shadcn colors | 0 |
| `frontend/src/index.css` | Modify — add shadcn CSS variables | 0 |
| `frontend/src/components/ui/` | Create (shadcn generates) | 0 |
| `frontend/src/lib/utils.js` | Create (shadcn generates) | 0 |
| `frontend/src/App.jsx` | Modify — outer shell Tailwind | 1 |
| `frontend/src/components/Sidebar.jsx` | Rewrite — wide sidebar, icon+label, amber active | 1 |
| `frontend/src/components/TopBar.jsx` | Rewrite — full Tailwind replacement | 1 |
| `frontend/src/components/Header.jsx` | Modify — Tailwind card wrapper | 2 |
| `frontend/src/components/MarketOverview.jsx` | Modify — shadcn Card | 2 |
| `frontend/src/components/StatCards.jsx` | Modify — shadcn Card | 2 |
| `frontend/src/components/ScannerFilters.jsx` | Modify — Tailwind (plain `<button>`, no shadcn) | 2 |
| `frontend/src/components/ScannerTable.jsx` | Modify — Tailwind + terminal-table update | 3 |
| `frontend/src/components/WatchlistPanel.jsx` | Modify — Tailwind | 4 |
| `frontend/src/components/FavoritesPage.jsx` | Modify — Tailwind | 4 |
| `frontend/src/components/SetupTable.jsx` | Modify — Tailwind | 5 |
| `frontend/src/components/StockIntelPanel.jsx` | Modify — Tailwind + shadcn Card/Badge | 6 |
| `frontend/src/components/PortfolioTab.jsx` | Modify — Tailwind | 7 |
| `frontend/src/components/DiagnosticsTab.jsx` | Modify — Tailwind + shadcn Card | 8 |
| `frontend/src/components/BacktestPanel.jsx` | Modify — Tailwind + shadcn Card | 8 |
| `frontend/src/components/EngineHealthPanel.jsx` | Modify — Tailwind + shadcn Card | 8 |
| `frontend/src/components/DebugDrawer.jsx` | Modify — Tailwind | 9 |
| `frontend/src/components/SystemGuideModal.jsx` | Modify — Tailwind | 9 |
| `frontend/src/components/TradingChart.jsx` | Modify — Tailwind wrapper only | 10 |

---

## Task 0: shadcn/ui Setup — Config Files + CSS Variables

**Files:**
- Modify: `frontend/vite.config.js`
- Create: `frontend/jsconfig.json`
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/index.css`
- Generate: `frontend/src/components/ui/` + `frontend/src/lib/utils.js`

**Before starting:** Verify `frontend/package.json` contains `"type": "module"` — this confirms the project is ESM and `__dirname` is not natively available (the vite.config fix below is required).

- [ ] **Step 1: Update `vite.config.js` with ESM-safe path alias**

Replace the **entire file** at `frontend/vite.config.js`:

```js
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 2: Create `jsconfig.json`**

Create `frontend/jsconfig.json`:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  }
}
```

- [ ] **Step 3: Add `darkMode` to `tailwind.config.js`**

Open `frontend/tailwind.config.js`. Add `darkMode: 'class'` as the first key in the exported object (before `content`):

```js
export default {
  darkMode: 'class',   // ← add this line
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  // ... rest unchanged
}
```

- [ ] **Step 4: Run shadcn init** (Steps 1–3 must be applied and saved first)

```bash
cd swing-trading-dashboard/frontend
npx shadcn@latest init
```

Answer the wizard **exactly** as follows:
- Style → **Default**
- Base color → **Neutral**
- **TypeScript → No** (CRITICAL — project is plain JS; Yes generates `.tsx` which Vite won't process)
- CSS variables → **Yes**
- Global CSS file → `src/index.css`
- Tailwind config → `tailwind.config.js`
- Components alias → `@/components`
- Utils alias → `@/lib/utils`
- Add `tailwindcss-animate` → **Yes**

This installs `clsx`, `tailwind-merge`, `class-variance-authority`, and `tailwindcss-animate`. It generates `src/components/ui/` (`.jsx` files) and `src/lib/utils.js`. New packages in `package.json` are expected.

- [ ] **Step 5: Reconcile CSS variables in `src/index.css`**

shadcn's init appended its own `:root` block with HSL-format values. **Delete the entire shadcn-generated `:root` block** (at the bottom of `index.css`, starts with something like `@layer base { :root {`). Then add these new variables to the **existing** `:root` block (the one with `--accent: #F5A623`, `--go`, etc.):

```css
/* shadcn/ui required variables — hex format, matching our palette */
--background:            #000000;
--foreground:            #c8cdd6;
--card-foreground:       #c8cdd6;
--primary:               #F5A623;
--primary-foreground:    #000000;
--secondary:             #1a2535;
--secondary-foreground:  #c8cdd6;
--muted-foreground:      #4a5a72;
--accent-foreground:     #c8cdd6;
--destructive:           #ff2d55;
--destructive-foreground:#ffffff;
--popover:               #0f1520;
--popover-foreground:    #c8cdd6;
--ring:                  #F5A623;
--input:                 #1a2535;
--radius:                0.5rem;
```

Do NOT redefine `--card`, `--border`, `--accent`, `--muted` — existing hex values are already correct.

- [ ] **Step 6: Fix shadcn color entries in `tailwind.config.js`**

shadcn's init added a `colors` block using `hsl(var(--xxx))`. Since our variables are hex, this is invalid CSS. Find and replace every `"hsl(var(--xxx))"` entry with `"var(--xxx)"`. Merge these into the existing `colors:` section alongside (not replacing) the `t: {}` block:

```js
// Inside colors: { t: {...}, ...add below: }
background: 'var(--background)',
foreground: 'var(--foreground)',
card: {
  DEFAULT: 'var(--card)',
  foreground: 'var(--card-foreground)',
},
primary: {
  DEFAULT: 'var(--primary)',
  foreground: 'var(--primary-foreground)',
},
secondary: {
  DEFAULT: 'var(--secondary)',
  foreground: 'var(--secondary-foreground)',
},
muted: {
  DEFAULT: 'var(--muted)',
  foreground: 'var(--muted-foreground)',
},
accent: {
  DEFAULT: 'var(--accent)',
  foreground: 'var(--accent-foreground)',
},
destructive: {
  DEFAULT: 'var(--destructive)',
  foreground: 'var(--destructive-foreground)',
},
border: 'var(--border)',
input: 'var(--input)',
ring: 'var(--ring)',
```

- [ ] **Step 7: Install shadcn component primitives**

```bash
npx shadcn@latest add button card input badge separator
```

Do NOT add `dialog` — SystemGuideModal uses a custom overlay that we'll restyle in Task 9.

- [ ] **Step 8: Verify Layer 0**

```bash
npm run dev
```

Open http://localhost:5173. App should load exactly as before with no console errors. Inline-CSS components haven't changed yet — this is expected.

- [ ] **Step 9: Commit Layer 0** (run from repo root, not from `frontend/`)

```bash
cd ..   # back to swing-trading-dashboard/
git add frontend/vite.config.js frontend/jsconfig.json frontend/tailwind.config.js frontend/src/index.css frontend/src/components/ui frontend/src/lib frontend/package.json frontend/package-lock.json
git commit -m "chore: install shadcn/ui, configure @/ alias, reconcile CSS variables"
```

---

## Task 1: Layer 1 — App.jsx + Sidebar.jsx + TopBar.jsx

**Files:**
- Modify: `frontend/src/App.jsx`
- Rewrite: `frontend/src/components/Sidebar.jsx`
- Rewrite: `frontend/src/components/TopBar.jsx`

These three files are committed together because `App.jsx` and `Sidebar.jsx` are coupled by the sidebar width change (main content `flex-1` depends on sidebar width), and `TopBar.jsx` is the remaining shell component.

**Active nav colour note:** The current sidebar uses green (`var(--go)`) for active items. The new sidebar uses amber (`text-t-accent`). This is an intentional design change.

### Step 1: Update App.jsx outer shell

- [ ] **Step 1a: Replace the root render div** (line ~305 in App.jsx)

```jsx
// BEFORE:
<div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--bg)' }}>

// AFTER:
<div className="flex h-screen overflow-hidden bg-t-bg">
```

- [ ] **Step 1b: Replace the main content wrapper** (line ~311)

```jsx
// BEFORE:
<div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

// AFTER:
<div className="flex-1 flex flex-col overflow-hidden min-w-0">
```

All other JSX inside App.jsx (page-specific content, overlays, state, callbacks) is **unchanged**.

### Step 2: Replace Sidebar.jsx entirely

- [ ] **Step 2: Replace the full contents of `frontend/src/components/Sidebar.jsx`**

The sidebar changes from 60px icon-only to 224px (`w-56`) with icon + label. The root element stays `<nav>` — `index.css` has a mobile media query `nav { width: 48px !important }` that auto-collapses it on small screens; keeping `<nav>` preserves this behaviour with no CSS change needed.

```jsx
import {
  ScanLine,
  Star,
  Heart,
  Briefcase,
  BarChart2,
  Activity,
  Settings,
  TrendingUp,
} from 'lucide-react'

const NAV_ITEMS = [
  { id: 'scanner',     icon: ScanLine,  label: 'Scanner'     },
  { id: 'watchlist',   icon: Star,      label: 'Watchlist'   },
  { id: 'favorites',   icon: Heart,     label: 'Favorites'   },
  { id: 'portfolio',   icon: Briefcase, label: 'Portfolio'   },
  { id: 'analytics',   icon: BarChart2, label: 'Analytics'   },
  { id: 'diagnostics', icon: Activity,  label: 'Diagnostics' },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <nav className="w-56 flex-shrink-0 bg-t-panel border-r border-t-border flex flex-col h-full">

      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-t-border flex-shrink-0">
        <div className="size-8 rounded-lg bg-gradient-to-br from-t-accent to-t-go flex items-center justify-center flex-shrink-0">
          <TrendingUp size={16} className="text-black" strokeWidth={2.5} />
        </div>
        <span className="font-mono font-bold text-base text-t-accent tracking-wider">SCANR</span>
      </div>

      {/* Main nav */}
      <div className="flex-1 flex flex-col gap-1 px-2 py-3">
        {NAV_ITEMS.map(({ id, icon: Icon, label }) => {
          const isActive = activePage === id
          return (
            <button
              key={id}
              onClick={() => onNavigate(id)}
              title={label}
              className={[
                'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-mono font-medium transition-colors duration-150 border',
                isActive
                  ? 'bg-t-accent/10 text-t-accent border-t-accent/20'
                  : 'text-t-muted hover:bg-white/5 hover:text-t-text border-transparent',
              ].join(' ')}
            >
              <Icon size={17} strokeWidth={1.75} />
              {label}
            </button>
          )
        })}
      </div>

      {/* Bottom: Settings */}
      <div className="px-2 py-3 border-t border-t-border flex-shrink-0">
        <button
          onClick={() => onNavigate('settings')}
          title="Settings"
          className={[
            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-mono font-medium transition-colors duration-150 border',
            activePage === 'settings'
              ? 'bg-t-accent/10 text-t-accent border-t-accent/20'
              : 'text-t-muted hover:bg-white/5 hover:text-t-text border-transparent',
          ].join(' ')}
        >
          <Settings size={17} strokeWidth={1.75} />
          Settings
        </button>
      </div>
    </nav>
  )
}
```

### Step 3: Replace TopBar.jsx entirely

- [ ] **Step 3: Replace the full contents of `frontend/src/components/TopBar.jsx`**

The root element stays `<header>` (same as now — keeps z-index semantics). All existing logic (market open check, search form, scan status, dev toggles) is preserved. No `regime` prop is added — regime display lives in `Header.jsx`, not here.

```jsx
import { Search, Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'

const PAGE_TITLES = {
  scanner:     'Scanner',
  watchlist:   'Watchlist',
  favorites:   'Favorites',
  portfolio:   'Portfolio',
  analytics:   'Analytics',
  diagnostics: 'Diagnostics',
  settings:    'Settings',
}

export default function TopBar({
  activePage,
  scanStatus,
  onRunScan,
  onSearchTicker,
  devMode,
  dryRun,
  onToggleDev,
  onToggleDryRun,
  onOpenGuide,
}) {
  const [searchVal, setSearchVal] = useState('')

  // Keep all local derived variables unchanged
  const isScanning  = scanStatus?.in_progress
  const progressPct = scanStatus?.progress_pct ?? 0
  const title       = PAGE_TITLES[activePage] ?? activePage

  // Market open check (US hours Mon-Fri 9:30–16:00 ET) — logic unchanged
  const now   = new Date()
  const etNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const dow   = etNow.getDay()
  const hr    = etNow.getHours() + etNow.getMinutes() / 60
  const isOpen = dow >= 1 && dow <= 5 && hr >= 9.5 && hr < 16

  const handleSearch = (e) => {
    e.preventDefault()
    if (searchVal.trim()) {
      onSearchTicker(searchVal.trim().toUpperCase())
      setSearchVal('')
    }
  }

  return (
    <header className="h-[52px] bg-t-panel border-b border-t-border flex items-center px-4 gap-4 flex-shrink-0 relative z-20">

      {/* Progress bar at very top */}
      {isScanning && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-t-border">
          <div
            className="h-full bg-t-go transition-[width] duration-500 ease-linear"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}

      {/* Page title */}
      <span className="font-condensed font-bold text-lg text-t-text flex-shrink-0 w-24 tracking-tight">
        {title}
      </span>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex-1 max-w-xs">
        <div className="flex items-center gap-2 bg-t-card border border-t-border rounded-lg px-2.5 py-1.5">
          <Search size={13} className="text-t-muted flex-shrink-0" />
          <input
            value={searchVal}
            onChange={e => setSearchVal(e.target.value.toUpperCase())}
            placeholder="Search ticker..."
            className="bg-transparent border-none outline-none text-t-text font-mono text-[11px] w-full placeholder:text-t-muted"
          />
        </div>
      </form>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Market status pill */}
      <div className={`flex items-center gap-1.5 px-2 py-1 rounded-md border font-mono text-[9px] font-bold tracking-widest flex-shrink-0 ${
        isOpen
          ? 'bg-t-go/10 border-t-go/30 text-t-go'
          : 'bg-t-halt/10 border-t-halt/25 text-t-halt'
      }`}>
        <div className={`size-1.5 rounded-full flex-shrink-0 ${
          isOpen ? 'bg-t-go shadow-[0_0_6px_var(--go)]' : 'bg-t-halt'
        }`} />
        {isOpen ? 'MARKET OPEN' : 'MARKET CLOSED'}
      </div>

      {/* Run Scan button + scanning status label */}
      <div className="flex flex-col items-center gap-1 flex-shrink-0">
        <button
          onClick={onRunScan}
          disabled={isScanning}
          className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg font-mono text-[11px] font-bold tracking-wider transition-colors border-none ${
            isScanning
              ? 'bg-t-border text-t-muted cursor-default'
              : 'bg-t-go text-black cursor-pointer hover:bg-t-go/90'
          }`}
        >
          {isScanning
            ? <><RefreshCw size={12} className="animate-spin" /> {Math.round(progressPct)}%</>
            : <><Play size={11} fill="currentColor" /> RUN SCAN</>
          }
        </button>
        {/* Status sub-label — keep this span, it shows scan phase */}
        {isScanning && (
          <span className="font-mono text-[9px] font-semibold tracking-widest text-t-muted">
            {scanStatus?.rebuilding_universe
              ? 'REBUILDING UNIVERSE…'
              : scanStatus?.prefetching
              ? 'PREFETCHING DATA…'
              : 'SCANNING TICKERS…'}
          </span>
        )}
      </div>

      {/* Dev mode toggles — only visible when devMode is true */}
      {devMode && (
        <div className="flex gap-1.5">
          <button
            onClick={onToggleDryRun}
            className={`font-mono text-[9px] font-bold px-1.5 py-0.5 rounded border transition-colors ${
              dryRun
                ? 'bg-t-accent/15 text-t-accent border-t-accent/40'
                : 'bg-t-border text-t-muted border-transparent'
            }`}
          >
            DRY
          </button>
        </div>
      )}

      {devMode && (
        <div
          onClick={onToggleDev}
          title="Press D to toggle Dev Mode"
          className="font-mono text-[8px] font-bold px-1.5 py-0.5 rounded border bg-t-purple/15 border-t-purple/35 text-t-purple tracking-widest cursor-pointer"
        >
          DEV
        </div>
      )}

      {/* Guide button */}
      <button
        onClick={onOpenGuide}
        title="Help (?)"
        className="size-7 rounded-lg bg-t-card border border-t-border text-t-muted hover:text-t-text flex items-center justify-center font-mono text-[11px] font-bold flex-shrink-0"
      >
        ?
      </button>
    </header>
  )
}
```

- [ ] **Step 4: Verify visually**

```bash
cd frontend && npm run dev
```

Check:
- Sidebar is now 224px wide with icon + label nav items
- Active page item has amber background + border
- TopBar shows page title, search, market status pill, scan button
- Progress bar appears at top of header during scan
- Scanning status label ("SCANNING TICKERS…") appears below button during scan
- Dev mode toggles (press `d`) show DRY + DEV labels
- `?` button opens guide modal
- Page switching still works
- No console errors

- [ ] **Step 5: Commit** (run from repo root `swing-trading-dashboard/`)

```bash
git add frontend/src/App.jsx frontend/src/components/Sidebar.jsx frontend/src/components/TopBar.jsx
git commit -m "feat(ui): migrate shell — App, Sidebar, TopBar"
```

---

## Task 2: Layer 2 — Header, MarketOverview, StatCards, ScannerFilters

**Files:**
- Modify: `frontend/src/components/Header.jsx`
- Modify: `frontend/src/components/MarketOverview.jsx`
- Modify: `frontend/src/components/StatCards.jsx`
- Modify: `frontend/src/components/ScannerFilters.jsx`

Read each file before editing. Replace `style={{}}` with Tailwind. Use shadcn `Card` for stat/overview cards.

- [ ] **Step 1: Read all four files**

```bash
cat frontend/src/components/Header.jsx
cat frontend/src/components/MarketOverview.jsx
cat frontend/src/components/StatCards.jsx
cat frontend/src/components/ScannerFilters.jsx
```

- [ ] **Step 2: Add shadcn Card imports**

Add to both `MarketOverview.jsx` and `StatCards.jsx`:
```jsx
import { Card, CardContent } from '@/components/ui/card'
```

- [ ] **Step 3: Migrate Header.jsx**

Replace wrapper div style with:
```jsx
<div className="flex items-center gap-4 px-5 py-3 bg-t-card border-b border-t-cardBorder flex-shrink-0">
```

Regime tier badge pattern (replace existing style on the badge span):
```jsx
<span className={`font-mono text-xs font-bold px-2 py-0.5 rounded border ${
  tier === 'AGGRESSIVE' ? 'text-t-go border-t-go/30 bg-t-go/10' :
  tier === 'SELECTIVE'  ? 'text-yellow-400 border-yellow-400/30 bg-yellow-400/10' :
                          'text-t-halt border-t-halt/30 bg-t-halt/10'
}`}>
  {tier}
</span>
```

All existing props and callbacks unchanged.

- [ ] **Step 4: Migrate StatCards.jsx**

Wrap each stat card in shadcn `Card`. Outer row:
```jsx
<div className="flex gap-3 px-4 py-3 flex-shrink-0">
```

Each stat:
```jsx
<Card className="bg-t-card border-t-cardBorder shadow-card flex-1 min-w-0">
  <CardContent className="p-4">
    <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-t-muted mb-1">{label}</div>
    <div className="font-condensed text-2xl font-bold" style={{ color: valueColor }}>{value}</div>
    <div className="font-mono text-[10px] text-t-muted mt-1">{sub}</div>
  </CardContent>
</Card>
```

Keep `valueColor` as inline style — it's a dynamic signal color.

- [ ] **Step 5: Migrate MarketOverview.jsx**

Same Card pattern as StatCards. Grid wrapper:
```jsx
<div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3 flex-shrink-0">
```

Each overview card:
```jsx
<Card className="bg-t-card border-t-cardBorder shadow-card">
  <CardContent className="p-3">
    {/* existing content with style={{}} replaced by Tailwind */}
  </CardContent>
</Card>
```

- [ ] **Step 6: Migrate ScannerFilters.jsx**

Wrapper:
```jsx
<div className="flex items-center gap-1.5 flex-wrap px-3 py-2 border-b border-t-border bg-t-panel flex-shrink-0">
```

Filter button pattern (replace each styled `<button>`):
```jsx
<button
  onClick={() => onFiltersChange({ ...filters, setupType: type })}
  className={`font-mono text-[10px] font-bold px-2.5 py-1 rounded border transition-colors ${
    filters.setupType === type
      ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
      : 'text-t-muted border-t-border hover:text-t-text hover:border-t-borderLight'
  }`}
>
  {label}
</button>
```

Hot-only toggle, min score input: same Tailwind class approach.

- [ ] **Step 7: Verify visually**

```bash
npm run dev
```

Check:
- Stat cards display with visible borders and card backgrounds
- Filter buttons highlight amber when active
- Regime badge colours correct (green/yellow/red)
- No console errors

- [ ] **Step 8: Commit** (from repo root)

```bash
git add frontend/src/components/Header.jsx frontend/src/components/MarketOverview.jsx frontend/src/components/StatCards.jsx frontend/src/components/ScannerFilters.jsx
git commit -m "feat(ui): migrate page containers — Header, StatCards, MarketOverview, ScannerFilters"
```

---

## Task 3: Layer 3 — ScannerTable.jsx

**Files:**
- Modify: `frontend/src/components/ScannerTable.jsx`
- Modify: `frontend/src/index.css` (update `.terminal-table` block)

- [ ] **Step 1: Remove old `.terminal-table` rules from `index.css` first**

Open `frontend/src/index.css`. Find and **delete** the following blocks (they will be replaced by the `@layer components` version in Step 2):
- `.terminal-table { ... }`
- `.terminal-table th { ... }`
- `.terminal-table td { ... }`
- `.terminal-table tr { ... }`
- `.terminal-table tr:hover td { ... }`
- `.terminal-table tr.selected td { ... }`
- `.terminal-table tr.selected td:first-child { ... }`
- `.row-near-entry td { ... }`
- `.row-near-entry td:first-child { ... }`

Delete all of these. Do not delete any other rules.

- [ ] **Step 2: Add new `@layer components` block to `index.css`**

After the deletions, add this block (it can go right before `/* ── Mobile responsive ──`):

```css
/* ── Terminal table (Tailwind layer) ──────────────────── */
@layer components {
  .terminal-table {
    @apply w-full border-collapse font-mono text-xs;
  }
  .terminal-table th {
    @apply px-2 py-1.5 text-left text-[8px] font-bold uppercase tracking-widest
           text-t-muted border-b border-t-border bg-t-card sticky top-0 z-10;
  }
  .terminal-table td {
    @apply px-2 py-[5px] border-b border-t-border/50 align-middle;
  }
  .terminal-table tr {
    @apply cursor-pointer transition-colors duration-100;
  }
  .terminal-table tr:hover td {
    @apply bg-white/[0.025];
  }
  .terminal-table tr.selected td {
    @apply bg-t-accent/[0.06];
  }
  .terminal-table tr.selected td:first-child {
    @apply border-l-2 border-t-accent;
  }
  .row-near-entry td {
    background: rgba(245,166,35,0.035) !important;
  }
  .row-near-entry td:first-child {
    border-left: 3px solid rgba(245,166,35,0.65) !important;
    padding-left: 5px !important;
  }
}
```

- [ ] **Step 3: Add Badge import to ScannerTable.jsx**

```jsx
import { Badge } from '@/components/ui/badge'
```

- [ ] **Step 4: Replace outermost wrapper div**

```jsx
// BEFORE:
<div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>

// AFTER:
<div className="flex flex-col flex-1 min-h-0">
```

- [ ] **Step 5: Replace toolbar div (show extended button row)**

```jsx
// BEFORE:
<div style={{ padding: '4px 10px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end', flexShrink: 0, background: 'var(--card)' }}>

// AFTER:
<div className="px-2.5 py-1.5 border-b border-t-border flex justify-end flex-shrink-0 bg-t-card">
```

- [ ] **Step 6: Replace show/hide extended button**

```jsx
<button
  onClick={() => setShowExtended(v => !v)}
  className={`font-mono text-[8px] font-bold tracking-widest uppercase px-2 py-1 rounded border transition-all ${
    showExtended
      ? 'bg-t-halt/10 border-t-halt/30 text-t-halt'
      : 'border-t-border text-t-muted hover:text-t-text'
  }`}
>
  {showExtended ? '✕ hide extended' : '+ show extended'}
</button>
```

- [ ] **Step 7: Replace scroll wrapper div**

```jsx
// BEFORE:
<div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>

// AFTER:
<div className="flex-1 overflow-auto min-h-0">
```

- [ ] **Step 8: Remove inline style from `<table>`**

```jsx
// BEFORE:
<table className="terminal-table" style={{ background: 'var(--card)' }}>

// AFTER:
<table className="terminal-table">
```

Background is now applied via `@apply bg-t-card` on `th` in the layer block.

- [ ] **Step 9: Replace EARLY/OPTIMAL/EXTENDED badge with shadcn Badge**

Find the `{entryQuality && (<span ...>)}` block. Replace with:

```jsx
{entryQuality && (
  <Badge
    variant="outline"
    className={`text-[7px] px-1 py-0 font-mono font-bold h-auto ${
      entryQuality === 'EARLY'   ? 'border-t-go/30 text-t-go bg-t-go/15' :
      entryQuality === 'OPTIMAL' ? 'border-t-accent/30 text-t-accent bg-t-accent/15' :
                                   'border-t-halt/30 text-t-halt bg-t-halt/15'
    }`}
  >
    {entryQuality}
  </Badge>
)}
```

- [ ] **Step 10: Verify visually**

```bash
npm run dev
```

Run a scan or check existing data:
- Table headers: dark background, sticky, small uppercase text
- Row hover: subtle white/transparent highlight
- Selected row: amber left border + amber tint
- EARLY/OPTIMAL/EXTENDED badges: coloured outline
- Vol surge rows: green background (CSS var still used in `rowBg` inline style — keep it)
- Show/hide extended button: red when active, muted when inactive

- [ ] **Step 11: Commit** (from repo root)

```bash
git add frontend/src/components/ScannerTable.jsx frontend/src/index.css
git commit -m "feat(ui): migrate ScannerTable to Tailwind, update terminal-table CSS"
```

---

## Task 4: Layer 3 — WatchlistPanel.jsx + FavoritesPage.jsx

**Files:**
- Modify: `frontend/src/components/WatchlistPanel.jsx`
- Modify: `frontend/src/components/FavoritesPage.jsx`

- [ ] **Step 1: Read both files**

```bash
cat frontend/src/components/WatchlistPanel.jsx
cat frontend/src/components/FavoritesPage.jsx
```

- [ ] **Step 2: Migrate WatchlistPanel.jsx**

Outer panel:
```jsx
<div className="flex flex-col h-full overflow-hidden bg-t-panel">
```

Header:
```jsx
<div className="flex items-center justify-between px-3 py-2.5 border-b border-t-border flex-shrink-0">
  <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-t-muted">Watchlist</span>
  <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-t-accent/10 border border-t-accent/20 text-t-accent font-bold">{totalCount}</span>
</div>
```

Body scroll area:
```jsx
<div className="flex-1 overflow-y-auto">
```

`SectionHeader` inner component:
```jsx
<div className="flex items-center justify-between px-3 py-1.5 border-b border-t-border bg-white/[0.02]">
  <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-t-muted">{label}</span>
  <span className="font-mono text-[9px] px-1.5 py-0.5 rounded bg-t-accent/10 border border-t-accent/20 text-t-muted font-bold">{count}</span>
</div>
```

`WatchRow` outer div — the `borderLeft` keeps as inline style since it's a dynamic ternary:
```jsx
<div
  onClick={() => onSelectTicker(item.ticker)}
  className={`flex items-center justify-between px-3 py-2 border-b border-t-border cursor-pointer transition-colors duration-100 gap-2 ${
    isSelected ? 'bg-t-accent/[0.06]' : 'hover:bg-white/[0.04]'
  }`}
  style={{ borderLeft: isSelected ? '3px solid var(--accent)' : isBrk ? '3px solid rgba(0,200,122,0.4)' : '3px solid rgba(100,180,255,0.4)' }}
>
```

Ticker text:
```jsx
<span className={`font-mono text-xs font-bold ${isSelected ? 'text-t-accent' : 'text-t-text'}`}>
  {item.ticker}
</span>
```

Distance label: keep inline `style={{ color: distColor }}` — `distColor` is computed dynamically.

Source badge, star button, TV link: replace `style={{}}` with equivalent Tailwind padding/sizing.

- [ ] **Step 3: Migrate FavoritesPage.jsx**

Empty state:
```jsx
<div className="flex-1 flex flex-col items-center justify-center gap-3 text-t-muted">
  <Heart size={32} strokeWidth={1.5} className="opacity-30" />
  <div className="font-mono text-[11px] uppercase tracking-widest">No favorites yet</div>
  <div className="font-mono text-[9px] opacity-50 text-center max-w-xs leading-relaxed">
    Star any setup or watchlist item to add it here
  </div>
</div>
```

For the populated list: setup rows follow the same pattern as ScannerTable rows. Replace all `style={{}}` layout props with Tailwind. Keep dynamic signal colors (type badge colors, P/L colors) as inline `style`.

- [ ] **Step 4: Verify visually**

```bash
npm run dev
```

Check Watchlist page: BRK green border / PB blue border, selected amber, hover works. Check Favorites: empty state centered, populated items match scanner table style.

- [ ] **Step 5: Commit** (from repo root)

```bash
git add frontend/src/components/WatchlistPanel.jsx frontend/src/components/FavoritesPage.jsx
git commit -m "feat(ui): migrate WatchlistPanel and FavoritesPage to Tailwind"
```

---

## Task 5: Layer 3 — SetupTable.jsx

**Files:**
- Modify: `frontend/src/components/SetupTable.jsx`

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/SetupTable.jsx
```

- [ ] **Step 2: Migrate SetupTable.jsx**

SetupTable is structurally identical to ScannerTable. Apply the same migration pattern:

Outer wrapper: `className="flex flex-col flex-1 min-h-0"`

Table uses `.terminal-table` (already updated in Task 3 — no CSS change needed).

Header with `accentColor` prop — keep as inline style since it's a dynamic prop value:
```jsx
<div className="px-3 py-2 border-b flex-shrink-0 font-mono text-[9px] font-bold uppercase tracking-widest text-t-muted"
  style={{ borderBottom: `2px solid ${accentColor}` }}>
  {headerLabel}
</div>
```

Hot sector fire emoji rows: these use `is_vol_surge` and `hot_sector` flags for the row background. Same pattern as ScannerTable — keep the `rowBg` computed value as `style={{ background: rowBg }}`.

Scroll container: `className="flex-1 overflow-auto min-h-0"`

Selected row: inline `style={{ borderLeft: '2px solid var(--accent)' }}` for the dynamic left border on the first `td` — or use `border-l-2 border-t-accent` Tailwind class directly on the `<tr>`.

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

SetupTable appears in the scanner page (VCP/Pullback/Base/ResBreakout/HTF/LCE subsections if they exist there) or in pages that use it. Verify the header coloured border matches `accentColor` and rows render correctly.

- [ ] **Step 4: Commit** (from repo root)

```bash
git add frontend/src/components/SetupTable.jsx
git commit -m "feat(ui): migrate SetupTable to Tailwind"
```

---

## Task 6: Layer 3 — StockIntelPanel.jsx

**Files:**
- Modify: `frontend/src/components/StockIntelPanel.jsx`

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/StockIntelPanel.jsx
```

- [ ] **Step 2: Add imports**

```jsx
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
```

- [ ] **Step 3: Migrate StockIntelPanel.jsx**

Outer panel:
```jsx
<div className="w-72 flex-shrink-0 bg-t-panel border-l border-t-border flex flex-col overflow-y-auto">
```

Section cards:
```jsx
<Card className="bg-t-card border-t-cardBorder mx-3 my-2">
  <CardContent className="p-3">
    {/* section content */}
  </CardContent>
</Card>
```

Section label:
```jsx
<div className="font-mono text-[9px] font-bold uppercase tracking-widest text-t-muted mb-2">{label}</div>
```

Trade plan grid:
```jsx
<div className="grid grid-cols-2 gap-2">
```

Entry/stop/target values: keep inline style for dynamic signal colors.

Signal badge (HOLD/CAUTION/EXIT):
```jsx
<Badge variant="outline" className={`font-mono text-[9px] font-bold ${
  signal === 'HOLD'    ? 'text-t-go border-t-go/30 bg-t-go/10' :
  signal === 'CAUTION' ? 'text-t-accent border-t-accent/30 bg-t-accent/10' :
                         'text-t-halt border-t-halt/30 bg-t-halt/10'
}`}>
  {signal}
</Badge>
```

- [ ] **Step 4: Verify visually**

```bash
npm run dev
```

Click any ticker. Right panel should show card sections with values, signal badge, trade plan.

- [ ] **Step 5: Commit** (from repo root)

```bash
git add frontend/src/components/StockIntelPanel.jsx
git commit -m "feat(ui): migrate StockIntelPanel to Tailwind + shadcn Card/Badge"
```

---

## Task 7: Layer 3 — PortfolioTab.jsx

**Files:**
- Modify: `frontend/src/components/PortfolioTab.jsx`

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/PortfolioTab.jsx
```

- [ ] **Step 2: Migrate PortfolioTab.jsx**

Outer wrapper:
```jsx
<div className="p-4 space-y-4 overflow-auto flex-1">
```

Table wrapper (positions table):
```jsx
<div className="bg-t-card border border-t-cardBorder rounded-card shadow-card overflow-hidden">
  <table className="terminal-table">
```

Form inputs (add trade form):
```jsx
className="bg-t-surface border border-t-border rounded px-2 py-1 font-mono text-xs text-t-text focus:outline-none focus:border-t-accent w-full"
```

Submit button:
```jsx
className="font-mono text-xs px-3 py-1.5 rounded bg-t-accent text-black font-bold hover:bg-t-accent/90 disabled:opacity-50 transition-colors"
```

P/L values: keep inline `style={{ color: 'var(--go)' }}` / `style={{ color: 'var(--halt)' }}` — these are dynamic per-row.

Signal badges (HOLD/CAUTION/EXIT): same `Badge` pattern as StockIntelPanel. Add `import { Badge } from '@/components/ui/badge'` at the top.

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

Navigate to Portfolio. Positions table renders, add-trade form inputs visible, P/L coloring works.

- [ ] **Step 4: Commit** (from repo root)

```bash
git add frontend/src/components/PortfolioTab.jsx
git commit -m "feat(ui): migrate PortfolioTab to Tailwind"
```

---

## Task 8: Layer 3 — DiagnosticsTab, BacktestPanel, EngineHealthPanel

**Files:**
- Modify: `frontend/src/components/DiagnosticsTab.jsx`
- Modify: `frontend/src/components/BacktestPanel.jsx`
- Modify: `frontend/src/components/EngineHealthPanel.jsx`

- [ ] **Step 1: Read all three files**

```bash
cat frontend/src/components/DiagnosticsTab.jsx
cat frontend/src/components/BacktestPanel.jsx
cat frontend/src/components/EngineHealthPanel.jsx
```

- [ ] **Step 2: Add Card imports to all three**

```jsx
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
```

- [ ] **Step 3: Migrate DiagnosticsTab.jsx**

Outer wrapper: `<div className="p-4 space-y-4 overflow-auto">`

Source toggle buttons (Live/Backtest): amber-active pattern (same as ScannerFilters).

Each metric section card:
```jsx
<Card className="bg-t-card border-t-cardBorder shadow-card">
  <CardHeader className="pb-2 pt-4 px-4">
    <CardTitle className="font-mono text-xs uppercase tracking-widest text-t-muted">{title}</CardTitle>
  </CardHeader>
  <CardContent className="px-4 pb-4">
    {/* content */}
  </CardContent>
</Card>
```

Stats grid: `<div className="grid grid-cols-2 md:grid-cols-4 gap-3">`

Stat value: `<div className="font-condensed text-2xl font-bold" style={{ color: valueColor }}>` — keep inline style.

- [ ] **Step 4: Migrate BacktestPanel.jsx**

Same Card pattern. Date range inputs:
```jsx
className="bg-t-surface border border-t-border rounded px-2 py-1 font-mono text-xs text-t-text focus:outline-none focus:border-t-accent"
```

Run backtest button:
```jsx
className="font-mono text-xs px-3 py-1.5 rounded bg-t-accent text-black font-bold hover:bg-t-accent/90 disabled:opacity-50 transition-colors"
```

- [ ] **Step 5: Migrate EngineHealthPanel.jsx**

Engine status rows — healthy dot:
```jsx
<span className={`size-2 rounded-full flex-shrink-0 ${isHealthy ? 'bg-t-go' : 'bg-t-halt'}`} />
```

Row text: `<span className="font-mono text-xs text-t-text">{engineName}</span>`

- [ ] **Step 6: Verify visually**

```bash
npm run dev
```

Navigate to Diagnostics and Analytics pages. Stats cards render, run button visible, engine health dots show green/red.

- [ ] **Step 7: Commit** (from repo root)

```bash
git add frontend/src/components/DiagnosticsTab.jsx frontend/src/components/BacktestPanel.jsx frontend/src/components/EngineHealthPanel.jsx
git commit -m "feat(ui): migrate DiagnosticsTab, BacktestPanel, EngineHealthPanel to Tailwind"
```

---

## Task 9: Layer 3 — DebugDrawer.jsx + SystemGuideModal.jsx

**Files:**
- Modify: `frontend/src/components/DebugDrawer.jsx`
- Modify: `frontend/src/components/SystemGuideModal.jsx`

- [ ] **Step 1: Read both files**

```bash
cat frontend/src/components/DebugDrawer.jsx
cat frontend/src/components/SystemGuideModal.jsx
```

- [ ] **Step 2: Migrate DebugDrawer.jsx**

DebugDrawer is a fixed right-side overlay (dev mode only). Root panel:
```jsx
<div className="fixed inset-y-0 right-0 w-[420px] bg-t-panel border-l border-t-border shadow-2xl z-50 flex flex-col overflow-hidden">
```

Header:
```jsx
<div className="flex items-center justify-between px-4 py-3 border-b border-t-border flex-shrink-0">
  <span className="font-mono text-xs font-bold text-t-accent uppercase tracking-widest">{ticker} // DEBUG</span>
  <button onClick={onClose} className="text-t-muted hover:text-t-text font-mono text-xs px-1">✕</button>
</div>
```

Content area:
```jsx
<div className="flex-1 overflow-y-auto p-4 space-y-3 font-mono text-xs text-t-text">
```

Section labels:
```jsx
<div className="text-[9px] uppercase tracking-widest text-t-muted mb-1 font-bold">{label}</div>
```

Data values: keep inline style for dynamic signal colors.

- [ ] **Step 3: Migrate SystemGuideModal.jsx**

Do NOT add shadcn Dialog — use the existing overlay pattern restyled with Tailwind.

Backdrop:
```jsx
<div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
```

Modal panel:
```jsx
<div className="bg-t-card border border-t-cardBorder rounded-card shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col overflow-hidden">
```

Modal header:
```jsx
<div className="flex items-center justify-between px-6 py-4 border-b border-t-border flex-shrink-0">
  <span className="font-mono text-sm font-bold text-t-accent uppercase tracking-widest">System Guide</span>
  <button onClick={onClose} className="text-t-muted hover:text-t-text font-mono">✕</button>
</div>
```

Content:
```jsx
<div className="overflow-y-auto p-6 space-y-4 font-mono text-xs text-t-text">
```

Section headers within guide:
```jsx
<div className="text-t-accent font-bold uppercase tracking-widest text-[10px] mb-2">{heading}</div>
```

- [ ] **Step 4: Verify visually**

```bash
npm run dev
```

- Press `?` → SystemGuideModal opens with backdrop blur, dark panel, close button works
- Press `d` to enable dev mode → `DEV` label appears in TopBar
- Double-click a setup row → DebugDrawer slides in from right with dark panel style

- [ ] **Step 5: Commit** (from repo root)

```bash
git add frontend/src/components/DebugDrawer.jsx frontend/src/components/SystemGuideModal.jsx
git commit -m "feat(ui): migrate DebugDrawer and SystemGuideModal to Tailwind"
```

---

## Task 10: Layer 3 — TradingChart.jsx (Wrapper Only)

**Files:**
- Modify: `frontend/src/components/TradingChart.jsx`

The lightweight-charts canvas is **untouched**. Only the wrapper div and toolbar buttons change.

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/TradingChart.jsx
```

- [ ] **Step 2: Replace outer wrapper**

Find the root div that wraps the chart. Replace its `style={{}}` with:
```jsx
<div className="relative bg-t-panel rounded-card border border-t-cardBorder overflow-hidden h-full w-full">
```

- [ ] **Step 3: Replace interval/indicator toolbar buttons**

Replace each styled interval button (e.g., `1D`, `1W`, `1M`):
```jsx
<button
  onClick={() => setInterval(iv)}
  className={`font-mono text-[10px] px-2 py-0.5 rounded transition-colors ${
    interval === iv
      ? 'text-t-accent bg-t-accent/10 border border-t-accent/20'
      : 'text-t-muted hover:text-t-text border border-transparent'
  }`}
>
  {iv}
</button>
```

- [ ] **Step 4: Replace focus toggle button**

```jsx
<button
  onClick={onToggleFocus}
  className="font-mono text-[10px] px-2 py-0.5 rounded text-t-muted hover:text-t-text border border-t-border transition-colors"
>
  {chartFocus ? '⊠ exit' : '⊞ focus'}
</button>
```

- [ ] **Step 5: Verify visually**

```bash
npm run dev
```

Click any ticker:
- Chart renders in dark panel with border
- Interval buttons highlight amber when active
- Press `f` or click focus button — chart expands to fullscreen, `escape` returns
- Candlesticks render correctly (canvas untouched)

- [ ] **Step 6: Commit** (from repo root)

```bash
git add frontend/src/components/TradingChart.jsx
git commit -m "feat(ui): migrate TradingChart wrapper to Tailwind"
```

---

## Task 11: Final Verification + VPS Deploy

- [ ] **Step 1: Full smoke test**

```bash
cd frontend && npm run dev
```

Go through every page:
- [ ] Scanner: table sorts, row selection, chart loads, intel panel, filter toggles
- [ ] Watchlist: BRK/PB sections, star buttons, TV links work
- [ ] Favorites: empty state or populated items
- [ ] Portfolio: positions table, add-trade form
- [ ] Analytics: backtest panel, run button, results cards
- [ ] Diagnostics: stats cards, setup breakdown table
- [ ] SystemGuideModal: `?` key opens, `✕` closes
- [ ] DebugDrawer: press `d` (dev mode), double-click a row — drawer opens and closes with `Escape`
- [ ] Scan trigger: progress bar appears in TopBar, status label shows, table updates after
- [ ] No console errors on any page

- [ ] **Step 2: Production build**

```bash
npm run build
```

Expected: `✓ built in X.XXs` with no warnings or errors.

- [ ] **Step 3: Push to GitHub** (from repo root)

```bash
cd .. && git push origin main
```

- [ ] **Step 4: Deploy to VPS**

```bash
ssh root@89.167.25.25 "cd /opt/dashboard/swing-trading-dashboard && git pull && cd frontend && npm run build && systemctl restart dashboard && echo DONE"
```

Expected output ends with `DONE`.
