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
| `frontend/src/components/TopBar.jsx` | Modify — Tailwind + shadcn Input/Button | 1 |
| `frontend/src/components/Header.jsx` | Modify — Tailwind card wrapper | 2 |
| `frontend/src/components/MarketOverview.jsx` | Modify — shadcn Card | 2 |
| `frontend/src/components/StatCards.jsx` | Modify — shadcn Card | 2 |
| `frontend/src/components/ScannerFilters.jsx` | Modify — Tailwind + shadcn Button | 2 |
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

- [ ] **Step 1: Update `vite.config.js` with ESM-safe path alias**

The project uses `"type": "module"` in package.json — `__dirname` is NOT available in ESM. Use `fileURLToPath` instead.

Replace the entire file at `frontend/vite.config.js`:

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

- [ ] **Step 4: Run shadcn init** (Steps 1-3 must be applied first)

```bash
cd frontend
npx shadcn@latest init
```

Answer the wizard **exactly** as follows:
- Style → **Default**
- Base color → **Neutral**
- TypeScript → **No** (CRITICAL — project is plain JS; Yes generates `.tsx` which Vite won't process)
- CSS variables → **Yes**
- Global CSS file → `src/index.css`
- Tailwind config → `tailwind.config.js`
- Components alias → `@/components`
- Utils alias → `@/lib/utils`
- Add `tailwindcss-animate` → **Yes**

This installs `clsx`, `tailwind-merge`, `class-variance-authority`, generates `src/components/ui/*.jsx` and `src/lib/utils.js`. Seeing these new packages in `package.json` is expected and correct.

- [ ] **Step 5: Reconcile CSS variables in `src/index.css`**

shadcn's init appended its own `:root` block with HSL-format values. **Delete the entire shadcn-generated `:root` block** (it will be at the bottom of index.css, starting with `/* shadcn */` or similar). Then add these new variables to the **existing** `:root` block (the one with `--accent`, `--go`, etc.):

```css
/* shadcn/ui required variables — hex format, no HSL */
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

Do NOT redefine `--card`, `--border`, `--accent`, `--muted` — existing hex values are correct.

- [ ] **Step 6: Fix shadcn color entries in `tailwind.config.js`**

shadcn's init added a `colors` block using `hsl(var(--xxx))` format. Since our CSS variables are hex, `hsl(#F5A623)` is invalid CSS. Find the shadcn-generated color entries and replace every `"hsl(var(--xxx))"` with `"var(--xxx)"`. The result should look like this — **merge into the existing `colors:` section alongside the `t: {}` block**, do not replace it:

```js
// Add these inside colors: { ... } next to the existing t: {} block:
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
cd frontend
npx shadcn@latest add button card input badge separator
```

Do NOT add `dialog` — SystemGuideModal uses a custom overlay.

- [ ] **Step 8: Verify Layer 0**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. App should load exactly as before with no console errors. The inline-CSS components haven't changed yet — this is expected.

- [ ] **Step 9: Commit Layer 0**

```bash
cd frontend
git add vite.config.js jsconfig.json tailwind.config.js src/index.css src/components/ui src/lib package.json package-lock.json
git commit -m "chore: install shadcn/ui, configure @/ alias, reconcile CSS variables"
```

---

## Task 1: Layer 1 — App.jsx (Outer Shell)

**Files:**
- Modify: `frontend/src/App.jsx`

No logic changes. Only the root `<div>` and main content wrapper `<div>` inline styles change. All state, callbacks, and page-specific JSX stays identical.

- [ ] **Step 1: Replace the root render div**

In `App.jsx`, find the return statement's root div (line ~305):

```jsx
// BEFORE:
<div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--bg)' }}>
```

Replace with:
```jsx
<div className="flex h-full overflow-hidden bg-t-bg">
```

- [ ] **Step 2: Replace the main content wrapper**

Find the main content div (line ~311):
```jsx
// BEFORE:
<div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
```

Replace with:
```jsx
<div className="flex-1 flex flex-col overflow-hidden min-w-0">
```

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

Open http://localhost:5173. Layout should look identical to before (Sidebar still renders at 60px with old styles — it hasn't been migrated yet).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat(ui): migrate App.jsx outer shell to Tailwind"
```

---

## Task 2: Layer 1 — Sidebar.jsx (Full Redesign)

**Files:**
- Modify: `frontend/src/components/Sidebar.jsx`

This is the biggest visual change. Current sidebar: 60px, icon-only, green active. New: 224px (`w-56`), icon + label, amber active. **The existing `<nav>` element must be kept** — `index.css` has a mobile media query `nav { width: 48px !important }` that collapses it on small screens.

- [ ] **Step 1: Replace Sidebar.jsx entirely**

Replace the full file content of `frontend/src/components/Sidebar.jsx`:

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
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-t-border">
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
                'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-mono font-medium transition-colors duration-150',
                isActive
                  ? 'bg-t-accent/10 text-t-accent border border-t-accent/20'
                  : 'text-t-muted hover:bg-white/5 hover:text-t-text border border-transparent',
              ].join(' ')}
            >
              <Icon size={17} strokeWidth={1.75} />
              {label}
            </button>
          )
        })}
      </div>

      {/* Bottom: Settings */}
      <div className="px-2 py-3 border-t border-t-border">
        <button
          onClick={() => onNavigate('settings')}
          title="Settings"
          className={[
            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-mono font-medium transition-colors duration-150',
            activePage === 'settings'
              ? 'bg-t-accent/10 text-t-accent border border-t-accent/20'
              : 'text-t-muted hover:bg-white/5 hover:text-t-text border border-transparent',
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

- [ ] **Step 2: Verify visually**

```bash
npm run dev
```

Check:
- Sidebar is now wider (~224px) with icon + label items
- Active page item has amber background + amber text
- Inactive items are grey, hover lightens
- Logo shows gradient icon + "SCANR" text
- Clicking nav items still switches pages correctly
- No console errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.jsx
git commit -m "feat(ui): migrate Sidebar — wide layout, amber active, icon+label nav"
```

---

## Task 3: Layer 1 — TopBar.jsx

**Files:**
- Modify: `frontend/src/components/TopBar.jsx`

Read the current file first. Replace inline `style={{}}` on all divs with Tailwind classes. The search input becomes a shadcn `Input`. The scan button becomes a shadcn `Button`. All existing state (`searchVal`, `setSearchVal`) and callbacks (`onRunScan`, `onSearchTicker`, etc.) are unchanged.

- [ ] **Step 1: Add imports**

At the top of `frontend/src/components/TopBar.jsx`, add:
```jsx
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
```

Keep existing lucide imports.

- [ ] **Step 2: Replace the outer wrapper**

Find the root return div. Replace its `style={{}}` with:
```jsx
<div className="flex items-center justify-between gap-4 px-5 py-2.5 bg-t-panel border-b border-t-border flex-shrink-0">
```

- [ ] **Step 3: Restyle the page title area**

Find the title `<span>` or `<h1>`. Apply:
```jsx
<span className="font-mono text-base font-bold text-t-accent tracking-wide">{title}</span>
```

Add the version tag next to it:
```jsx
<div className="flex items-center gap-1.5">
  <Terminal size={12} className="text-t-muted" />
  <span className="font-mono text-xs text-t-muted">v1.0</span>
</div>
```

- [ ] **Step 4: Replace search input**

Find the existing search `<input>` element. Replace with shadcn Input:
```jsx
<div className="relative flex-1 max-w-xs">
  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-t-muted" />
  <Input
    type="search"
    placeholder="Search ticker..."
    value={searchVal}
    onChange={e => setSearchVal(e.target.value)}
    onKeyDown={e => {
      if (e.key === 'Enter' && searchVal.trim()) {
        onSearchTicker(searchVal.trim().toUpperCase())
        setSearchVal('')
      }
    }}
    className="pl-8 h-8 bg-t-surface border-t-border text-t-text placeholder:text-t-muted font-mono text-xs"
  />
</div>
```

- [ ] **Step 5: Replace scan button**

Find the existing scan `<button>`. Replace with shadcn Button:
```jsx
<Button
  onClick={onRunScan}
  disabled={isScanning}
  size="sm"
  className="font-mono text-xs bg-t-accent text-black hover:bg-t-accent/90 disabled:opacity-50"
>
  {isScanning ? <RefreshCw size={12} className="animate-spin mr-1" /> : <Play size={12} className="mr-1" />}
  {isScanning ? `${Math.round(progressPct)}%` : 'SCAN'}
</Button>
```

- [ ] **Step 6: Replace remaining styled divs**

Convert all remaining `style={{}}` divs (dev mode toggle, dry run toggle, regime indicator, open guide button) to equivalent Tailwind classes. Keep all logic identical. Dev/dry-run toggles:
```jsx
<button
  onClick={onToggleDev}
  className={`font-mono text-xs px-2 py-1 rounded border transition-colors ${
    devMode ? 'bg-t-accent/10 text-t-accent border-t-accent/30' : 'text-t-muted border-t-border hover:text-t-text'
  }`}
>
  DEV
</button>
```

- [ ] **Step 7: Verify visually**

```bash
npm run dev
```

Check:
- TopBar has dark panel background with bottom border
- Search input is styled, functional (type ticker + Enter navigates to chart)
- Scan button works, shows spinner during scan
- Dev mode toggle works (keyboard `d` + button)
- No console errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/TopBar.jsx
git commit -m "feat(ui): migrate TopBar to Tailwind + shadcn Input/Button"
```

---

## Task 4: Layer 2 — Header, MarketOverview, StatCards, ScannerFilters

**Files:**
- Modify: `frontend/src/components/Header.jsx`
- Modify: `frontend/src/components/MarketOverview.jsx`
- Modify: `frontend/src/components/StatCards.jsx`
- Modify: `frontend/src/components/ScannerFilters.jsx`

Read each file before editing. Replace `style={{}}` with Tailwind. Use shadcn `Card`, `CardHeader`, `CardContent` for stat/overview cards.

- [ ] **Step 1: Add shadcn Card imports to MarketOverview.jsx and StatCards.jsx**

```jsx
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
```

- [ ] **Step 2: Migrate Header.jsx**

Read `frontend/src/components/Header.jsx`. Replace its wrapper div with:
```jsx
<div className="flex items-center gap-4 px-5 py-3 bg-t-card border-b border-t-cardBorder flex-shrink-0">
```

Regime tier badge pattern:
```jsx
<span className={`font-mono text-xs font-bold px-2 py-0.5 rounded border ${
  regime === 'AGGRESSIVE' ? 'text-t-go border-t-go/30 bg-t-go/10' :
  regime === 'SELECTIVE'  ? 'text-yellow-400 border-yellow-400/30 bg-yellow-400/10' :
                            'text-t-halt border-t-halt/30 bg-t-halt/10'
}`}>
  {regime}
</span>
```

Keep all existing props, callbacks, and conditional rendering logic unchanged.

- [ ] **Step 3: Migrate StatCards.jsx**

Read `frontend/src/components/StatCards.jsx`. Wrap each stat card in shadcn `Card`:

```jsx
<Card className="bg-t-card border-t-cardBorder shadow-card flex-1 min-w-0">
  <CardContent className="p-4">
    <div className="text-xs font-mono font-bold uppercase tracking-widest text-t-muted mb-1">{label}</div>
    <div className="font-condensed text-2xl font-bold text-t-text">{value}</div>
    <div className="text-xs font-mono text-t-muted mt-1">{sub}</div>
  </CardContent>
</Card>
```

Wrap the row: `<div className="flex gap-3 px-4 py-3 flex-shrink-0">`.

- [ ] **Step 4: Migrate MarketOverview.jsx**

Same Card pattern as StatCards. Replace inline div wrappers with:
```jsx
<div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3">
```

Each card:
```jsx
<Card className="bg-t-card border-t-cardBorder shadow-card">
  <CardContent className="p-3">
    {/* existing content, replace style={{}} with Tailwind */}
  </CardContent>
</Card>
```

- [ ] **Step 5: Migrate ScannerFilters.jsx**

Read `frontend/src/components/ScannerFilters.jsx`. Add import:
```jsx
import { Button } from '@/components/ui/button'
```

Replace wrapper:
```jsx
<div className="flex items-center gap-1.5 flex-wrap px-3 py-2 border-b border-t-border bg-t-panel flex-shrink-0">
```

Active filter button pattern:
```jsx
<button
  onClick={() => onFiltersChange({ ...filters, setupType: type })}
  className={`font-mono text-xs px-2.5 py-1 rounded border transition-colors ${
    filters.setupType === type
      ? 'bg-t-accent/10 text-t-accent border-t-accent/30'
      : 'text-t-muted border-t-border hover:text-t-text hover:border-t-borderLight'
  }`}
>
  {label}
</button>
```

Min score and hot-only filter: keep logic, replace style with Tailwind.

- [ ] **Step 6: Verify visually**

```bash
npm run dev
```

Check:
- Stat cards display values with card borders visible
- Scanner filter buttons highlight amber when active
- Regime badge colors: green=AGGRESSIVE, yellow=SELECTIVE, red=DEFENSIVE
- No console errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Header.jsx frontend/src/components/MarketOverview.jsx frontend/src/components/StatCards.jsx frontend/src/components/ScannerFilters.jsx
git commit -m "feat(ui): migrate page containers — Header, StatCards, MarketOverview, ScannerFilters"
```

---

## Task 5: Layer 3 — ScannerTable.jsx

**Files:**
- Modify: `frontend/src/components/ScannerTable.jsx`
- Modify: `frontend/src/index.css` (update `.terminal-table` in `@layer components`)

- [ ] **Step 1: Update `.terminal-table` in `index.css`**

Find the `.terminal-table` block in `frontend/src/index.css`. Replace the whole block (including `.terminal-table th`, `.terminal-table td`, `.terminal-table tr` rules) with the following inside `@layer components`:

```css
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
  .terminal-table tr { @apply cursor-pointer transition-colors duration-100; }
  .terminal-table tr:hover td { @apply bg-white/[0.025]; }
  .terminal-table tr.selected td { @apply bg-t-accent/[0.06]; }
  .terminal-table tr.selected td:first-child { @apply border-l-2 border-t-accent; }
  .row-near-entry td { @apply bg-t-accent/[0.035] !important; }
  .row-near-entry td:first-child { @apply border-l-[3px] border-t-accent/60 pl-[5px] !important; }
}
```

Remove the old non-`@layer` versions of those same rules from `index.css`.

- [ ] **Step 2: Add shadcn Badge import to ScannerTable.jsx**

```jsx
import { Badge } from '@/components/ui/badge'
```

- [ ] **Step 3: Replace the outer wrapper div**

Find the outermost div in ScannerTable's return (the flex column container). Replace its `style={{}}`:

```jsx
<div className="flex flex-col flex-1 min-h-0">
```

The toolbar div (show extended button row):
```jsx
<div className="px-2.5 py-1.5 border-b border-t-border flex justify-end flex-shrink-0 bg-t-card">
```

Show/hide extended button:
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

- [ ] **Step 4: Replace the scroll wrapper**

```jsx
<div className="flex-1 overflow-auto min-h-0">
  <table className="terminal-table" style={{ background: 'var(--card)' }}>
```

Remove `style={{ background: 'var(--card)' }}` from `<table>` — the `@apply` rule handles it.

- [ ] **Step 5: Replace EARLY/OPTIMAL/EXTENDED badge**

Find the `entryQuality` badge span. Replace with shadcn Badge:

```jsx
{entryQuality && (
  <Badge
    variant="outline"
    className={`text-[7px] px-1 py-0 font-mono font-bold ${
      entryQuality === 'EARLY'   ? 'border-t-go/30 text-t-go bg-t-go/15' :
      entryQuality === 'OPTIMAL' ? 'border-t-accent/30 text-t-accent bg-t-accent/15' :
                                   'border-t-halt/30 text-t-halt bg-t-halt/15'
    }`}
  >
    {entryQuality}
  </Badge>
)}
```

- [ ] **Step 6: Verify visually**

```bash
npm run dev
```

Run a scan or check existing data. Verify:
- Table headers are dark panel colour, sticky
- Row hover shows subtle highlight
- Selected row has amber left border + amber background tint
- EARLY/OPTIMAL/EXTENDED badges show coloured outline
- Vol surge rows still show green background
- Show/hide extended button works

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ScannerTable.jsx frontend/src/index.css
git commit -m "feat(ui): migrate ScannerTable to Tailwind, update terminal-table CSS"
```

---

## Task 6: Layer 3 — WatchlistPanel.jsx + FavoritesPage.jsx

**Files:**
- Modify: `frontend/src/components/WatchlistPanel.jsx`
- Modify: `frontend/src/components/FavoritesPage.jsx`

- [ ] **Step 1: Migrate WatchlistPanel.jsx**

Read the file. Replace all `style={{}}` props with Tailwind equivalents:

Outer panel:
```jsx
<div className="flex flex-col h-full overflow-hidden bg-t-panel">
```

Header:
```jsx
<div className="flex items-center justify-between px-3 py-2.5 border-b border-t-border flex-shrink-0">
  <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-t-muted">Watchlist</span>
  <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-t-accent/8 border border-t-accent/20 text-t-accent font-bold">{totalCount}</span>
</div>
```

Section header (`SectionHeader` component):
```jsx
<div className="flex items-center justify-between px-3 py-1.5 border-b border-t-border bg-white/[0.02]">
  <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-t-muted">{label}</span>
  <span className="font-mono text-[9px] px-1.5 py-0.5 rounded bg-t-accent/8 border border-t-accent/20 text-t-muted font-bold">{count}</span>
</div>
```

Watch row (`WatchRow` component) — outer div:
```jsx
<div
  onClick={() => onSelectTicker(item.ticker)}
  className={`flex items-center justify-between px-3 py-2 border-b border-t-border cursor-pointer transition-colors duration-100
    ${isSelected ? 'bg-t-accent/6' : 'hover:bg-white/[0.04]'}
  `}
  style={{ borderLeft: isSelected ? '3px solid var(--accent)' : isBrk ? '3px solid rgba(0,200,122,0.4)' : '3px solid rgba(100,180,255,0.4)' }}
>
```

Note: keep `borderLeft` as inline style — it uses a conditional dynamic value from JS.

Ticker text:
```jsx
<span className={`font-mono text-xs font-bold ${isSelected ? 'text-t-accent' : 'text-t-text'}`}>{item.ticker}</span>
```

Distance label:
```jsx
<span className="font-mono text-[9px]" style={{ color: distColor }}>{distLabel}</span>
```

Keep `distColor` as inline style since it's computed dynamically.

- [ ] **Step 2: Migrate FavoritesPage.jsx**

Read the file. Apply same migration pattern:

Empty state:
```jsx
<div className="flex-1 flex flex-col items-center justify-center gap-3 text-t-muted">
  <Heart size={32} strokeWidth={1.5} className="opacity-30" />
  <div className="font-mono text-[11px] uppercase tracking-widest">No favorites yet</div>
</div>
```

For setup rows in the favorites list — they mirror ScannerTable rows. Replace `style={{}}` on each row div/span with equivalent Tailwind. Keep dynamic signal colors as inline style.

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

Navigate to Watchlist page. Check:
- BRK items have green left border, PB items have blue left border
- Selected item has amber left border + amber tint
- Hover works
- Navigate to Favorites page, check empty state and populated state

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/WatchlistPanel.jsx frontend/src/components/FavoritesPage.jsx
git commit -m "feat(ui): migrate WatchlistPanel and FavoritesPage to Tailwind"
```

---

## Task 7: Layer 3 — SetupTable.jsx

**Files:**
- Modify: `frontend/src/components/SetupTable.jsx`

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/SetupTable.jsx
```

- [ ] **Step 2: Migrate SetupTable.jsx**

SetupTable has a similar structure to ScannerTable. Apply the same migration pattern:

- Outer wrapper: `className="flex flex-col flex-1 min-h-0"`
- Table uses `.terminal-table` class (already updated in Task 5 — no change needed to CSS)
- Header with accent colour: keep `style={{ borderBottom: `2px solid ${accentColor}` }}` as inline — `accentColor` is a dynamic prop value
- All static layout divs → Tailwind
- Row selection border → same pattern as ScannerTable (inline style for dynamic color, Tailwind for layout)

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

The SetupTable appears in multiple places (Analytics/Diagnostics pages if they use it). Check that tables render with correct header and row styles.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SetupTable.jsx
git commit -m "feat(ui): migrate SetupTable to Tailwind"
```

---

## Task 8: Layer 3 — StockIntelPanel.jsx

**Files:**
- Modify: `frontend/src/components/StockIntelPanel.jsx`

- [ ] **Step 1: Add imports**

```jsx
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
```

- [ ] **Step 2: Read the file, then migrate**

```bash
cat frontend/src/components/StockIntelPanel.jsx
```

Outer panel:
```jsx
<div className="w-72 flex-shrink-0 bg-t-panel border-l border-t-border flex flex-col overflow-y-auto">
```

Each section card:
```jsx
<Card className="bg-t-card border-t-cardBorder mx-3 my-2">
  <CardContent className="p-3">
    {/* section content */}
  </CardContent>
</Card>
```

Section labels:
```jsx
<div className="font-mono text-[9px] font-bold uppercase tracking-widest text-t-muted mb-2">{label}</div>
```

Trade plan grid:
```jsx
<div className="grid grid-cols-2 gap-2">
```

Signal badges (HOLD/CAUTION/EXIT):
```jsx
<Badge variant="outline" className={`font-mono text-[9px] ${
  signal === 'HOLD'    ? 'text-t-go border-t-go/30 bg-t-go/10' :
  signal === 'CAUTION' ? 'text-t-accent border-t-accent/30 bg-t-accent/10' :
                         'text-t-halt border-t-halt/30 bg-t-halt/10'
}`}>
  {signal}
</Badge>
```

All numeric values (entry, stop, target, R:R): keep `style={{ color: 'var(--go)' }}` etc. for dynamic values.

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

Click a ticker. Check:
- Right panel renders with card sections
- Trade plan values (entry/stop/target) visible
- Signal badge colours correct

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/StockIntelPanel.jsx
git commit -m "feat(ui): migrate StockIntelPanel to Tailwind + shadcn Card/Badge"
```

---

## Task 9: Layer 3 — PortfolioTab.jsx

**Files:**
- Modify: `frontend/src/components/PortfolioTab.jsx`

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/PortfolioTab.jsx
```

- [ ] **Step 2: Migrate PortfolioTab.jsx**

The portfolio tab has an add-trade form + a positions table. Migration pattern:

Outer wrapper:
```jsx
<div className="p-4 space-y-4">
```

Table wrapper:
```jsx
<div className="bg-t-card border border-t-cardBorder rounded-card shadow-card overflow-hidden">
  <table className="terminal-table">
```

Add trade form inputs: replace `style={{}}` on `<input>` elements with:
```jsx
className="bg-t-surface border border-t-border rounded px-2 py-1 font-mono text-xs text-t-text focus:outline-none focus:border-t-accent w-full"
```

P/L values: keep inline `style={{ color: 'var(--go)' }}` for dynamic profit/loss colouring.

Signal badges (HOLD/CAUTION/EXIT): same Badge pattern as StockIntelPanel.

- [ ] **Step 3: Verify visually**

```bash
npm run dev
```

Navigate to Portfolio page. Check:
- Positions table renders with terminal-table styles
- P/L colouring works (green profit, red loss)
- Add trade form inputs are visible and functional

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PortfolioTab.jsx
git commit -m "feat(ui): migrate PortfolioTab to Tailwind"
```

---

## Task 10: Layer 3 — DiagnosticsTab, BacktestPanel, EngineHealthPanel

**Files:**
- Modify: `frontend/src/components/DiagnosticsTab.jsx`
- Modify: `frontend/src/components/BacktestPanel.jsx`
- Modify: `frontend/src/components/EngineHealthPanel.jsx`

All three follow the same pattern: outer wrapper → Tailwind, section cards → shadcn Card, data values with dynamic signal colours → keep inline style.

- [ ] **Step 1: Add Card imports to all three files**

```jsx
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
```

- [ ] **Step 2: Read and migrate DiagnosticsTab.jsx**

```bash
cat frontend/src/components/DiagnosticsTab.jsx
```

Outer wrapper: `<div className="p-4 space-y-4 overflow-auto">`

Each metric section:
```jsx
<Card className="bg-t-card border-t-cardBorder shadow-card">
  <CardHeader className="pb-2">
    <CardTitle className="font-mono text-xs uppercase tracking-widest text-t-muted">{title}</CardTitle>
  </CardHeader>
  <CardContent>
    {/* existing content, replace style={{}} with Tailwind */}
  </CardContent>
</Card>
```

Stats grid: `<div className="grid grid-cols-2 md:grid-cols-4 gap-3">`

Stat value: `<div className="font-condensed text-2xl font-bold" style={{ color: valueColor }}>`
— keep inline style for dynamic color.

Source toggle buttons: same amber-active pattern used in ScannerFilters.

- [ ] **Step 3: Read and migrate BacktestPanel.jsx**

```bash
cat frontend/src/components/BacktestPanel.jsx
```

Same Card pattern. Date range inputs:
```jsx
className="bg-t-surface border border-t-border rounded px-2 py-1 font-mono text-xs text-t-text focus:outline-none focus:border-t-accent"
```

Run backtest button:
```jsx
className="font-mono text-xs px-3 py-1.5 rounded bg-t-accent text-black font-bold hover:bg-t-accent/90 disabled:opacity-50 transition-colors"
```

- [ ] **Step 4: Read and migrate EngineHealthPanel.jsx**

```bash
cat frontend/src/components/EngineHealthPanel.jsx
```

Engine status rows: green dot for healthy, red for error:
```jsx
<span className={`size-2 rounded-full flex-shrink-0 ${isHealthy ? 'bg-t-go' : 'bg-t-halt'}`} />
```

- [ ] **Step 5: Verify visually**

```bash
npm run dev
```

Navigate to Diagnostics and Analytics pages. Check cards render, stats display, run backtest button works.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DiagnosticsTab.jsx frontend/src/components/BacktestPanel.jsx frontend/src/components/EngineHealthPanel.jsx
git commit -m "feat(ui): migrate DiagnosticsTab, BacktestPanel, EngineHealthPanel to Tailwind"
```

---

## Task 11: Layer 3 — DebugDrawer.jsx + SystemGuideModal.jsx

**Files:**
- Modify: `frontend/src/components/DebugDrawer.jsx`
- Modify: `frontend/src/components/SystemGuideModal.jsx`

- [ ] **Step 1: Read both files**

```bash
cat frontend/src/components/DebugDrawer.jsx
cat frontend/src/components/SystemGuideModal.jsx
```

- [ ] **Step 2: Migrate DebugDrawer.jsx**

DebugDrawer is a fixed right-side overlay. Replace the outer panel div:

```jsx
<div className="fixed inset-y-0 right-0 w-[420px] bg-t-panel border-l border-t-border shadow-2xl z-50 flex flex-col overflow-hidden">
```

Header:
```jsx
<div className="flex items-center justify-between px-4 py-3 border-b border-t-border flex-shrink-0">
  <span className="font-mono text-xs font-bold text-t-accent uppercase tracking-widest">{ticker} // DEBUG</span>
  <button onClick={onClose} className="text-t-muted hover:text-t-text font-mono text-xs">✕</button>
</div>
```

Content area: `<div className="flex-1 overflow-y-auto p-4 space-y-3 font-mono text-xs">`

Section labels: `<div className="text-[9px] uppercase tracking-widest text-t-muted mb-1">`

Data values: keep inline style for dynamic signal colors.

- [ ] **Step 3: Migrate SystemGuideModal.jsx**

Do NOT add shadcn Dialog — use the existing backdrop+panel approach restyled with Tailwind.

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
  <button onClick={onClose} className="text-t-muted hover:text-t-text">✕</button>
</div>
```

Content: `<div className="overflow-y-auto p-6 space-y-4 font-mono text-xs text-t-text">`

Section headers: `<div className="text-t-accent font-bold uppercase tracking-widest text-[10px] mb-2">`

- [ ] **Step 4: Verify visually**

```bash
npm run dev
```

- Press `?` to open SystemGuideModal — verify backdrop blur, modal panel appearance, close button works
- Enable dev mode (`d`), double-click a setup row — DebugDrawer should slide in from right with dark panel style

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DebugDrawer.jsx frontend/src/components/SystemGuideModal.jsx
git commit -m "feat(ui): migrate DebugDrawer and SystemGuideModal to Tailwind"
```

---

## Task 12: Layer 3 — TradingChart.jsx (Wrapper Only)

**Files:**
- Modify: `frontend/src/components/TradingChart.jsx`

The lightweight-charts canvas is **untouched**. Only the wrapper div and toolbar buttons change.

- [ ] **Step 1: Read the file**

```bash
cat frontend/src/components/TradingChart.jsx
```

- [ ] **Step 2: Add Button import**

```jsx
import { Button } from '@/components/ui/button'
```

- [ ] **Step 3: Replace outer wrapper**

Find the root div. Replace its `style={{}}` with:
```jsx
<div className="relative bg-t-panel rounded-card border border-t-cardBorder overflow-hidden h-full w-full">
```

- [ ] **Step 4: Replace toolbar buttons**

Find interval/indicator toolbar buttons. Replace each with shadcn Button:
```jsx
<Button
  variant="ghost"
  size="sm"
  onClick={() => setInterval(iv)}
  className={`font-mono text-[10px] px-2 h-6 ${
    interval === iv ? 'text-t-accent bg-t-accent/10' : 'text-t-muted hover:text-t-text'
  }`}
>
  {iv}
</Button>
```

- [ ] **Step 5: Replace focus toggle button**

```jsx
<Button
  variant="ghost"
  size="sm"
  onClick={onToggleFocus}
  className="font-mono text-[10px] px-2 h-6 text-t-muted hover:text-t-text"
>
  {chartFocus ? '⊠ exit' : '⊞ focus'}
</Button>
```

- [ ] **Step 6: Verify visually**

```bash
npm run dev
```

Click a ticker. Check:
- Chart renders in its panel with correct dark background
- Interval buttons (1D, 1W etc.) highlight amber when active
- Focus mode (`f` key or button) works — chart expands to fullscreen

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/TradingChart.jsx
git commit -m "feat(ui): migrate TradingChart wrapper to Tailwind + shadcn Button"
```

---

## Task 13: Final Verification + VPS Deploy

- [ ] **Step 1: Full smoke test**

```bash
cd frontend && npm run dev
```

Go through every page and verify:
- [ ] Scanner page: table, chart, intel panel, filters all render
- [ ] Watchlist page: BRK/PB sections, star buttons, TV links
- [ ] Favorites page: empty state or populated list
- [ ] Portfolio page: positions table, add trade form
- [ ] Analytics page: backtest panel, run button
- [ ] Diagnostics page: stats cards, setup breakdown
- [ ] SystemGuideModal (`?` key): opens, closes
- [ ] DebugDrawer (dev mode `d` + double-click): opens, closes
- [ ] Scan trigger: progress indicator works
- [ ] Live prices: displayed in scanner table
- [ ] No console errors on any page

- [ ] **Step 2: Production build**

```bash
cd frontend && npm run build
```

Expected: `✓ built in X.XXs` with no errors.

- [ ] **Step 3: Push to GitHub**

```bash
cd .. && git push origin main
```

- [ ] **Step 4: Deploy to VPS**

```bash
ssh root@89.167.25.25 "cd /opt/dashboard/swing-trading-dashboard && git pull && cd frontend && npm run build && systemctl restart dashboard && echo DONE"
```

Expected output ends with `DONE`.
