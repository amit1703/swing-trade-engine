# Full UI Redesign — Professional Trading Dashboard

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current terminal-style layout with a modern card-based trading workstation UI — dark, minimal, professional — while preserving all existing backend wiring, state, and functionality.

**Architecture:** New layout uses a fixed 60px left sidebar (icon nav), a top bar, and a main content area that swaps between pages. The Scanner page (default) shows stat cards → chart + right panel → unified scanner table. All existing API calls, chart logic, and state in `App.jsx` are preserved — only the visual shell and component composition change.

**Tech Stack:** React 18, Tailwind CSS 3, lightweight-charts (existing), lucide-react (new — icons), IBM Plex Mono + Inter fonts.

**Design Reference:** Dark cards with rounded corners (12px), subtle box-shadows, neon green (#00c87a) for bullish, red (#ff2d55) for halt, amber (#F5A623) for neutral. Inspired by NobleFinance / Koyfin style.

---

## Key Facts For All Tasks

- Working directory for all frontend commands: `frontend/`
- Build check: `npm run build 2>&1 | tail -10` — must exit with `✓ built`
- Dev server (if needed for visual check): `npm run dev` → http://localhost:5174
- All existing API calls live in `frontend/src/api.js` — do not touch
- All existing backend state lives in `frontend/src/App.jsx` — preserve all `useState`, `useCallback`, `useEffect` logic
- Existing components to **keep unchanged**: `TradingChart.jsx`, `PortfolioTab.jsx`, `BacktestPanel.jsx`, `SystemGuideModal.jsx`, `EngineHealthPanel.jsx`, `DebugDrawer.jsx`, `SetupTable.jsx` (used as fallback), `WatchlistPanel.jsx`
- CSS variables defined in `index.css` `:root` — always use `var(--name)` not hardcoded hex
- Tailwind colors prefixed `t-` (e.g. `text-t-go`, `bg-t-panel`)
- New Tailwind color token added in this plan: `t-card` = `#0f1520`, `t-cardBorder` = `#1e2d42`

---

## Task 1: Install Dependencies + Design System Update

**Files:**
- Modify: `frontend/package.json` (add lucide-react)
- Modify: `frontend/index.html` (add Inter font)
- Modify: `frontend/tailwind.config.js` (new tokens)
- Modify: `frontend/src/index.css` (new CSS variables, card utilities, remove scanline)

**Step 1: Install lucide-react**

```bash
cd frontend && npm install lucide-react
```

Expected output: `added 1 package` (lucide-react is zero-dependency)

**Step 2: Add Inter font to `frontend/index.html`**

Replace the existing Google Fonts `<link>`:
```html
<link
  href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=Barlow+Condensed:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap"
  rel="stylesheet"
/>
```

Also update the title:
```html
<title>SCANR // Trading Workstation</title>
```

**Step 3: Update `frontend/tailwind.config.js`**

Replace the full file with:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans:      ['"Inter"', 'system-ui', 'sans-serif'],
        mono:      ['"IBM Plex Mono"', 'monospace'],
        condensed: ['"Barlow Condensed"', 'sans-serif'],
      },
      borderRadius: {
        card: '12px',
        pill: '999px',
      },
      boxShadow: {
        card:    '0 4px 24px rgba(0,0,0,0.5)',
        cardHov: '0 6px 32px rgba(0,0,0,0.7)',
        glow:    '0 0 16px rgba(0,200,122,0.25)',
        glowRed: '0 0 16px rgba(255,45,85,0.25)',
      },
      colors: {
        t: {
          bg:          '#000000',
          surface:     '#080c12',
          panel:       '#0c111a',
          card:        '#0f1520',
          cardBorder:  '#1e2d42',
          border:      '#1a2535',
          borderLight: '#253347',
          text:        '#c8cdd6',
          muted:       '#4a5a72',
          accent:      '#F5A623',
          accentDim:   '#7a5010',
          go:          '#00c87a',
          goDim:       '#003d25',
          halt:        '#ff2d55',
          haltDim:     '#4a0015',
          blue:        '#00C8FF',
          blueDim:     '#003a50',
          purple:      '#9B6EFF',
          pink:        '#FF6EC7',
        },
      },
      keyframes: {
        pulse_halt: {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0.7' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0' },
        },
        scanIn: {
          '0%':   { transform: 'translateY(-4px)', opacity: '0' },
          '100%': { transform: 'translateY(0)',    opacity: '1' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        fadeUp: {
          '0%':   { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)',   opacity: '1' },
        },
      },
      animation: {
        pulse_halt: 'pulse_halt 1.4s ease-in-out infinite',
        blink:      'blink 1s step-end infinite',
        scanIn:     'scanIn 0.18s ease-out forwards',
        shimmer:    'shimmer 1.8s linear infinite',
        fadeUp:     'fadeUp 0.2s ease-out forwards',
      },
    },
  },
  plugins: [],
}
```

**Step 4: Update `frontend/src/index.css`**

Replace the full file with:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* ── Root variables ──────────────────────────────────── */
:root {
  --bg:           #000000;
  --surface:      #080c12;
  --panel:        #0c111a;
  --card:         #0f1520;
  --card-border:  #1e2d42;
  --border:       #1a2535;
  --border-light: #253347;
  --text:         #c8cdd6;
  --muted:        #4a5a72;
  --accent:       #F5A623;
  --go:           #00c87a;
  --halt:         #ff2d55;
  --blue:         #00C8FF;
  --purple:       #9B6EFF;
  --radius-card:  12px;
  --shadow-card:  0 4px 24px rgba(0,0,0,0.5);
}

/* ── Base ────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #root {
  height: 100%;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Monospace for data/numbers */
.font-mono, .tabular-nums { font-family: 'IBM Plex Mono', monospace; }

/* ── Custom scrollbar ────────────────────────────────── */
::-webkit-scrollbar            { width: 4px; height: 4px; }
::-webkit-scrollbar-track      { background: var(--surface); }
::-webkit-scrollbar-thumb      { background: var(--border-light); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover{ background: var(--accent); }

/* ── Selection ───────────────────────────────────────── */
::selection { background: rgba(245,166,35,0.25); color: #fff; }

/* ── Card utility ────────────────────────────────────── */
.card {
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

/* ── Badge ───────────────────────────────────────────── */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-family: 'IBM Plex Mono', monospace;
}

/* ── Section label ───────────────────────────────────── */
.section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
}

/* ── Progress bar ────────────────────────────────────── */
.progress-bar      { height: 2px; background: var(--border); position: relative; overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--go); transition: width 0.5s ease; }

/* ── Shimmer skeleton ────────────────────────────────── */
.shimmer-row {
  height: 22px;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--border) 25%, var(--border-light) 50%, var(--border) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.8s linear infinite;
}

/* ── Terminal table ──────────────────────────────────── */
.terminal-table {
  width: 100%;
  border-collapse: collapse;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
}
.terminal-table th {
  padding: 4px 8px;
  text-align: left;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  background: var(--card);
  z-index: 1;
}
.terminal-table td {
  padding: 5px 8px;
  border-bottom: 1px solid rgba(26,37,53,0.5);
  vertical-align: middle;
}
.terminal-table tr { cursor: pointer; transition: background 0.1s; }
.terminal-table tr:hover td { background: rgba(255,255,255,0.025); }
.terminal-table tr.selected td { background: rgba(245,166,35,0.06); }
.terminal-table tr.selected td:first-child { border-left: 2px solid var(--accent); }

/* ── Near-entry row glow ─────────────────────────────── */
.row-near-entry td { background: rgba(245,166,35,0.035) !important; }
.row-near-entry td:first-child {
  border-left: 3px solid rgba(245,166,35,0.65) !important;
  padding-left: 5px;
}

/* ── Sidebar nav button ──────────────────────────────── */
.nav-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  color: var(--muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  border: none;
  background: transparent;
}
.nav-btn:hover  { background: rgba(255,255,255,0.06); color: var(--text); }
.nav-btn.active { background: rgba(0,200,122,0.12);   color: var(--go);  }

/* ── Stat card ───────────────────────────────────────── */
.stat-card {
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-card);
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: var(--shadow-card);
  flex: 1;
  min-width: 0;
}
.stat-card-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}
.stat-card-value {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.01em;
}
.stat-card-sub {
  font-size: 10px;
  color: var(--muted);
  font-family: 'IBM Plex Mono', monospace;
}
```

**Step 5: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: `✓ built`

**Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/index.html frontend/tailwind.config.js frontend/src/index.css
git commit -m "feat(ui): install lucide-react, add Inter font, update design tokens and CSS foundation"
```

---

## Task 2: Sidebar Component

**Files:**
- Create: `frontend/src/components/Sidebar.jsx`

**What it does:** Fixed 60px left navigation with icon buttons. Highlights the active page. Emits `onNavigate(page)` when clicked. Bottom section has Settings icon.

**Step 1: Create `frontend/src/components/Sidebar.jsx`**

```jsx
import {
  LayoutDashboard,
  ScanLine,
  ListFilter,
  Star,
  Briefcase,
  BarChart2,
  Settings,
} from 'lucide-react'

const NAV_ITEMS = [
  { id: 'dashboard',  icon: LayoutDashboard, label: 'Dashboard' },
  { id: 'scanner',    icon: ScanLine,        label: 'Scanner'   },
  { id: 'setups',     icon: ListFilter,      label: 'Setups'    },
  { id: 'watchlist',  icon: Star,            label: 'Watchlist' },
  { id: 'portfolio',  icon: Briefcase,       label: 'Portfolio' },
  { id: 'analytics',  icon: BarChart2,       label: 'Analytics' },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <nav
      style={{
        width: 60,
        flexShrink: 0,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 12,
        paddingBottom: 12,
        gap: 4,
      }}
    >
      {/* Logo mark */}
      <div style={{
        width: 36,
        height: 36,
        borderRadius: 8,
        background: 'var(--go)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 12,
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: '"Barlow Condensed", sans-serif',
          fontWeight: 700,
          fontSize: 14,
          color: '#000',
          letterSpacing: '-0.03em',
        }}>SC</span>
      </div>

      {/* Main nav */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, width: '100%', alignItems: 'center' }}>
        {NAV_ITEMS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            className={`nav-btn ${activePage === id ? 'active' : ''}`}
            onClick={() => onNavigate(id)}
            title={label}
          >
            <Icon size={18} strokeWidth={1.75} />
          </button>
        ))}
      </div>

      {/* Settings at bottom */}
      <button
        className={`nav-btn ${activePage === 'settings' ? 'active' : ''}`}
        onClick={() => onNavigate('settings')}
        title="Settings"
      >
        <Settings size={18} strokeWidth={1.75} />
      </button>
    </nav>
  )
}
```

**Step 2: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: `✓ built`

**Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.jsx
git commit -m "feat(ui): add Sidebar component with icon navigation"
```

---

## Task 3: TopBar Component

**Files:**
- Create: `frontend/src/components/TopBar.jsx`

**What it does:** Full-width top bar (48px) with:
- Left: Page title (dynamic by active page)
- Center: Ticker search input (calls `onSearchTicker`)
- Right: Market status pill (OPEN/CLOSED), Run Scan button, timeframe selector, scan progress

This replaces `Header.jsx` as the top chrome. The existing regime banner from `Header.jsx` moves to the stat cards (Task 4).

**Step 1: Read `frontend/src/components/Header.jsx` lines 1–100** to understand what props it receives and what we need to preserve (run scan logic, progress bar, dev mode toggles).

The props are: `{ regime, scanStatus, onRunScan, onSearchTicker, onOpenGuide, devMode, dryRun, onToggleDev, onToggleDryRun }`

**Step 2: Create `frontend/src/components/TopBar.jsx`**

```jsx
import { Search, Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'

const PAGE_TITLES = {
  dashboard: 'Dashboard',
  scanner:   'Scanner',
  setups:    'Setups',
  watchlist: 'Watchlist',
  portfolio: 'Portfolio',
  analytics: 'Analytics',
  settings:  'Settings',
}

export default function TopBar({
  activePage,
  regime,
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

  const isScanning  = scanStatus?.in_progress
  const progressPct = scanStatus?.progress_pct ?? 0
  const title       = PAGE_TITLES[activePage] ?? activePage

  // Market open check (US hours Mon-Fri 9:30–16:00 ET)
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
    <header style={{
      height: 52,
      background: 'var(--surface)',
      borderBottom: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      paddingLeft: 16,
      paddingRight: 16,
      gap: 16,
      flexShrink: 0,
      position: 'relative',
      zIndex: 20,
    }}>

      {/* Progress bar at very top */}
      {isScanning && (
        <div style={{
          position: 'absolute',
          top: 0, left: 0, right: 0,
          height: 2,
          background: 'var(--border)',
        }}>
          <div style={{
            height: '100%',
            width: `${progressPct}%`,
            background: 'var(--go)',
            transition: 'width 0.5s ease',
          }} />
        </div>
      )}

      {/* Page title */}
      <span style={{
        fontFamily: '"Barlow Condensed", sans-serif',
        fontWeight: 700,
        fontSize: 18,
        letterSpacing: '-0.01em',
        color: 'var(--text)',
        flexShrink: 0,
        width: 100,
      }}>
        {title}
      </span>

      {/* Search */}
      <form onSubmit={handleSearch} style={{ flex: 1, maxWidth: 320 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: 'var(--panel)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '5px 10px',
        }}>
          <Search size={13} color="var(--muted)" />
          <input
            value={searchVal}
            onChange={e => setSearchVal(e.target.value.toUpperCase())}
            placeholder="Search ticker..."
            style={{
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text)',
              fontFamily: '"IBM Plex Mono", monospace',
              fontSize: 11,
              width: '100%',
            }}
          />
        </div>
      </form>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Market status */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 8px',
        borderRadius: 6,
        background: isOpen ? 'rgba(0,200,122,0.1)' : 'rgba(255,45,85,0.08)',
        border: `1px solid ${isOpen ? 'rgba(0,200,122,0.3)' : 'rgba(255,45,85,0.25)'}`,
      }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%',
          background: isOpen ? 'var(--go)' : 'var(--halt)',
          boxShadow: isOpen ? '0 0 6px var(--go)' : 'none',
        }} />
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: '0.08em',
          fontFamily: '"IBM Plex Mono", monospace',
          color: isOpen ? 'var(--go)' : 'var(--halt)',
        }}>
          {isOpen ? 'MARKET OPEN' : 'MARKET CLOSED'}
        </span>
      </div>

      {/* Run Scan button */}
      <button
        onClick={onRunScan}
        disabled={isScanning}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 14px',
          borderRadius: 8,
          background: isScanning ? 'var(--border)' : 'var(--go)',
          color: isScanning ? 'var(--muted)' : '#000',
          fontWeight: 700,
          fontSize: 11,
          letterSpacing: '0.04em',
          border: 'none',
          cursor: isScanning ? 'default' : 'pointer',
          fontFamily: '"IBM Plex Mono", monospace',
          transition: 'background 0.15s',
          flexShrink: 0,
        }}
      >
        {isScanning
          ? <><RefreshCw size={12} className="animate-spin" /> {Math.round(progressPct)}%</>
          : <><Play size={11} fill="currentColor" /> RUN SCAN</>
        }
      </button>

      {/* Dev mode toggles (only in dev mode) */}
      {devMode && (
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={onToggleDryRun}
            style={{
              fontSize: 9, padding: '3px 7px', borderRadius: 4,
              background: dryRun ? 'rgba(245,166,35,0.15)' : 'var(--border)',
              color: dryRun ? 'var(--accent)' : 'var(--muted)',
              border: `1px solid ${dryRun ? 'rgba(245,166,35,0.4)' : 'transparent'}`,
              cursor: 'pointer', fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: 700,
            }}
          >
            DRY
          </button>
        </div>
      )}

      {/* Guide button */}
      <button
        onClick={onOpenGuide}
        style={{
          width: 28, height: 28, borderRadius: 8,
          background: 'var(--panel)', border: '1px solid var(--border)',
          color: 'var(--muted)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 700, fontFamily: '"IBM Plex Mono", monospace',
        }}
        title="Help (?)"
      >
        ?
      </button>

      {/* User avatar placeholder */}
      <div style={{
        width: 30, height: 30, borderRadius: '50%',
        background: 'linear-gradient(135deg, var(--go), var(--blue))',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
        fontWeight: 700, fontSize: 11, color: '#000',
        fontFamily: '"Barlow Condensed", sans-serif',
      }}>
        TR
      </div>
    </header>
  )
}
```

**Step 3: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: `✓ built`

**Step 4: Commit**

```bash
git add frontend/src/components/TopBar.jsx
git commit -m "feat(ui): add TopBar component with search, market status, run scan button"
```

---

## Task 4: Stat Cards + Regime Panel

**Files:**
- Create: `frontend/src/components/StatCards.jsx`

**What it does:** 4 metric cards displayed in a row below the TopBar on the Scanner page:
1. **Market Regime** — BULL/NEUTRAL/HALT + score badge
2. **Active Setups** — total count across all engines
3. **Top Score** — highest `setup_score` in current scan
4. **SPY Trend** — spy_close vs spy_20ema vs spy_sma50

Also shows the 3-row regime detail (SPY metrics, engine status) from the existing `Header.jsx` regime block, but inside the card.

**Step 1: Create `frontend/src/components/StatCards.jsx`**

```jsx
import { TrendingUp, TrendingDown, Minus, Zap, Target, Activity } from 'lucide-react'

function RegimeCard({ regime }) {
  const regimeType  = regime?.regime
  const isNoData    = !regime || !regimeType
  const isAggr      = regimeType === 'AGGRESSIVE'
  const isSel       = regimeType === 'SELECTIVE'
  const isDef       = regimeType === 'DEFENSIVE' || (regime && !regime.is_bullish && !isNoData)

  const label = isAggr ? 'BULL' : isSel ? 'NEUTRAL' : isDef ? 'HALT' : 'NO DATA'
  const color = isAggr ? 'var(--go)' : isSel ? 'var(--accent)' : isDef ? 'var(--halt)' : 'var(--muted)'
  const bg    = isAggr ? 'rgba(0,200,122,0.08)'  : isSel ? 'rgba(245,166,35,0.08)' : isDef ? 'rgba(255,45,85,0.08)' : 'transparent'
  const isBullish = regime?.is_bullish

  return (
    <div className="stat-card" style={{ background: `var(--card)`, minWidth: 220 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="stat-card-label">Market Regime</span>
        <Activity size={14} color="var(--muted)" />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="stat-card-value" style={{ color }}>{label}</span>
        {regime?.regime_score != null && (
          <span style={{
            fontSize: 10, padding: '2px 7px', borderRadius: 5,
            background: bg, border: `1px solid ${color}40`,
            color, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
          }}>
            {regime.regime_score}/100
          </span>
        )}
      </div>

      {regime && !isNoData && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {regime.spy_close > 0 && (
            <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
              SPY <span style={{ color: 'var(--text)' }}>${regime.spy_close?.toFixed(2)}</span>
            </span>
          )}
          {regime.vix > 0 && (
            <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
              VIX <span style={{ color: 'var(--text)' }}>{regime.vix?.toFixed(1)}</span>
            </span>
          )}
          {regime.breadth_pct != null && (
            <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
              BRD <span style={{ color: regime.breadth_pct > 0.6 ? 'var(--go)' : regime.breadth_pct > 0.4 ? 'var(--accent)' : 'var(--halt)' }}>
                {Math.round(regime.breadth_pct * 100)}%
              </span>
            </span>
          )}
          <span style={{ fontSize: 9, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)' }}>
            VCP<span style={{ color: isBullish ? 'var(--go)' : 'var(--halt)', marginLeft: 1 }}>{isBullish ? '✔' : '✖'}</span>
            {' '}PB<span style={{ color: isBullish ? 'var(--go)' : 'var(--halt)', marginLeft: 1 }}>{isBullish ? '✔' : '✖'}</span>
          </span>
        </div>
      )}
    </div>
  )
}

function SetupsCard({ allSetups }) {
  const total = allSetups.length
  const topScore = total > 0
    ? Math.max(...allSetups.map(s => s.setup_score ?? 0).filter(n => n > 0))
    : null

  return (
    <div className="stat-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="stat-card-label">Active Setups</span>
        <Zap size={14} color="var(--muted)" />
      </div>
      <span className="stat-card-value" style={{ color: total > 0 ? 'var(--go)' : 'var(--muted)' }}>
        {total}
      </span>
      <span className="stat-card-sub">
        {total === 0 ? 'Run a scan to populate' : `across all engines`}
      </span>
    </div>
  )
}

function TopScoreCard({ allSetups }) {
  if (allSetups.length === 0) {
    return (
      <div className="stat-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span className="stat-card-label">Top Score Today</span>
          <Target size={14} color="var(--muted)" />
        </div>
        <span className="stat-card-value" style={{ color: 'var(--muted)' }}>—</span>
        <span className="stat-card-sub">No setups yet</span>
      </div>
    )
  }
  const best = allSetups.reduce((a, b) => (b.setup_score ?? 0) > (a.setup_score ?? 0) ? b : a)
  const score = Math.round(best.setup_score ?? 0)
  const scoreColor = score >= 80 ? 'var(--go)' : score >= 60 ? 'var(--accent)' : 'var(--muted)'

  return (
    <div className="stat-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="stat-card-label">Top Score Today</span>
        <Target size={14} color="var(--muted)" />
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span className="stat-card-value" style={{ color: scoreColor }}>{score}</span>
        <span style={{
          fontFamily: '"IBM Plex Mono", monospace', fontSize: 11,
          fontWeight: 700, color: 'var(--text)',
        }}>
          {best.ticker}
        </span>
      </div>
      <span className="stat-card-sub">{best.setup_type ?? '—'}</span>
    </div>
  )
}

function SpyCard({ regime }) {
  const close  = regime?.spy_close  ?? 0
  const ema20  = regime?.spy_20ema  ?? 0
  const sma50  = regime?.spy_sma50  ?? 0

  const aboveEma = close > 0 && ema20 > 0 && close > ema20
  const aboveSma = close > 0 && sma50 > 0 && close > sma50

  let trend = 'NO DATA'
  let trendColor = 'var(--muted)'
  let TrendIcon = Minus

  if (close > 0 && ema20 > 0) {
    if (aboveEma && aboveSma) { trend = 'UPTREND'; trendColor = 'var(--go)';   TrendIcon = TrendingUp   }
    else if (!aboveEma)       { trend = 'DOWNTREND'; trendColor = 'var(--halt)'; TrendIcon = TrendingDown }
    else                      { trend = 'MIXED';    trendColor = 'var(--accent)'; TrendIcon = Minus       }
  }

  return (
    <div className="stat-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="stat-card-label">SPY Trend</span>
        <TrendIcon size={14} color={trendColor} />
      </div>
      <span className="stat-card-value" style={{ color: trendColor }}>{trend}</span>
      {close > 0 && (
        <span className="stat-card-sub">
          ${close.toFixed(2)}
          {ema20 > 0 && <> · EMA20 <span style={{ color: aboveEma ? 'var(--go)' : 'var(--halt)' }}>{aboveEma ? '↑' : '↓'}</span></>}
          {sma50 > 0 && <> · SMA50 <span style={{ color: aboveSma ? 'var(--go)' : 'var(--halt)' }}>{aboveSma ? '↑' : '↓'}</span></>}
        </span>
      )}
    </div>
  )
}

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

**Step 2: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: `✓ built`

**Step 3: Commit**

```bash
git add frontend/src/components/StatCards.jsx
git commit -m "feat(ui): add StatCards component (regime, active setups, top score, SPY trend)"
```

---

## Task 5: Stock Intelligence Right Panel

**Files:**
- Create: `frontend/src/components/StockIntelPanel.jsx`

**What it does:** Right-side panel (300px) shown when a ticker is selected. Displays: ticker header, score ring, setup signals, entry/stop/risk, trade plan. Empty state when no ticker selected.

**Step 1: Create `frontend/src/components/StockIntelPanel.jsx`**

```jsx
import { TrendingUp, Volume2, Zap, Target, Shield, ChevronRight } from 'lucide-react'

function SignalRow({ label, value, active, color }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '6px 0',
      borderBottom: '1px solid rgba(26,37,53,0.5)',
    }}>
      <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: '"Inter", sans-serif' }}>
        {label}
      </span>
      <span style={{
        fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
        color: color ?? (active ? 'var(--go)' : 'var(--muted)'),
      }}>
        {value}
      </span>
    </div>
  )
}

function ScoreBadge({ score }) {
  const s     = Math.round(score ?? 0)
  const color = s >= 80 ? 'var(--go)' : s >= 60 ? 'var(--accent)' : 'var(--muted)'
  const pct   = s / 100

  // Simple circular progress using conic-gradient
  return (
    <div style={{ position: 'relative', width: 64, height: 64, flexShrink: 0 }}>
      <div style={{
        width: 64, height: 64, borderRadius: '50%',
        background: `conic-gradient(${color} ${pct * 360}deg, var(--border) 0deg)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: '50%',
          background: 'var(--card)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{
            fontFamily: '"Barlow Condensed", sans-serif',
            fontSize: 18, fontWeight: 700, color, lineHeight: 1,
          }}>
            {s}
          </span>
        </div>
      </div>
    </div>
  )
}

export default function StockIntelPanel({ setup, livePrices }) {
  if (!setup) {
    return (
      <div style={{
        width: 280, flexShrink: 0,
        background: 'var(--card)',
        border: '1px solid var(--card-border)',
        borderRadius: 12,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 8, color: 'var(--muted)',
        padding: 20,
      }}>
        <Target size={28} strokeWidth={1} color="var(--border-light)" />
        <span style={{ fontSize: 11, textAlign: 'center', lineHeight: 1.5 }}>
          Select a stock from the<br />scanner to view signals
        </span>
      </div>
    )
  }

  const livePrice    = livePrices?.[setup.ticker]
  const dist         = (livePrice && setup.entry > 0)
    ? ((livePrice - setup.entry) / setup.entry) * 100
    : null
  const isAboveEntry = dist !== null && dist >= 0

  const risk = setup.entry > 0 && setup.stop_loss > 0
    ? ((setup.entry - setup.stop_loss) / setup.entry * 100).toFixed(1)
    : null

  const rr = setup.rr ? Number(setup.rr).toFixed(2) : null

  return (
    <div style={{
      width: 280, flexShrink: 0,
      background: 'var(--card)',
      border: '1px solid var(--card-border)',
      borderRadius: 12,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid var(--card-border)',
        background: 'rgba(255,255,255,0.02)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div>
            <div style={{
              fontFamily: '"Barlow Condensed", sans-serif',
              fontSize: 24, fontWeight: 700, lineHeight: 1,
              color: 'var(--text)', letterSpacing: '-0.01em',
            }}>
              {setup.ticker}
            </div>
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3, fontFamily: '"IBM Plex Mono", monospace' }}>
              {setup.setup_type ?? '—'}
            </div>
          </div>
          <ScoreBadge score={setup.setup_score} />
        </div>

        {/* Live price */}
        {livePrice && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontFamily: '"IBM Plex Mono", monospace', fontSize: 16, fontWeight: 700,
              color: isAboveEntry ? 'var(--go)' : dist !== null && dist > -3 ? 'var(--accent)' : 'var(--text)',
            }}>
              ${livePrice.toFixed(2)}
            </span>
            {dist !== null && (
              <span style={{
                fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
                color: isAboveEntry ? 'var(--go)' : 'var(--muted)',
              }}>
                {isAboveEntry ? `▲${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Signals */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--card-border)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>
          SIGNALS
        </div>
        <SignalRow
          label="Relative Strength"
          value={setup.rs_score != null
            ? `RS${setup.rs_score >= 0 ? '+' : ''}${Math.round(setup.rs_score * 100)}`
            : '—'
          }
          color={setup.rs_score > 0.05 ? 'var(--go)' : 'var(--muted)'}
        />
        <SignalRow
          label="Volume Surge"
          value={setup.is_vol_surge ? 'YES' : setup.vol_ratio ? `×${Number(setup.vol_ratio).toFixed(1)}` : '—'}
          active={setup.is_vol_surge}
        />
        <SignalRow
          label="RS Blue Dot"
          value={setup.rs_blue_dot ? 'YES — 52W HIGH' : 'NO'}
          active={setup.rs_blue_dot}
        />
        <SignalRow
          label="Distance to Entry"
          value={dist !== null ? `${Math.abs(dist).toFixed(1)}%${isAboveEntry ? ' above' : ' below'}` : '—'}
          color={dist !== null && dist > -3 && !isAboveEntry ? 'var(--accent)' : undefined}
        />
      </div>

      {/* Trade Plan */}
      <div style={{ padding: '10px 16px', flex: 1 }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>
          TRADE PLAN
        </div>

        {[
          { label: 'Entry',  value: setup.entry      ? `$${setup.entry.toFixed(2)}`      : '—', color: 'var(--text)'   },
          { label: 'Stop',   value: setup.stop_loss  ? `$${setup.stop_loss.toFixed(2)}`  : '—', color: 'var(--halt)'   },
          { label: 'Target', value: setup.take_profit ? `$${setup.take_profit.toFixed(2)}` : '—', color: 'var(--go)'   },
          { label: 'Risk',   value: risk ? `${risk}%` : '—', color: 'var(--accent)' },
          { label: 'R:R',    value: rr ?? '—', color: rr && Number(rr) >= 2 ? 'var(--go)' : 'var(--text)' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '5px 0', borderBottom: '1px solid rgba(26,37,53,0.4)',
          }}>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</span>
            <span style={{ fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, color }}>
              {value}
            </span>
          </div>
        ))}
      </div>

      {/* TradingView link */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${setup.ticker}&interval=D`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            padding: '7px', borderRadius: 8,
            background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
            color: 'var(--accent)', fontSize: 10, fontWeight: 700,
            fontFamily: '"IBM Plex Mono", monospace', textDecoration: 'none',
            letterSpacing: '0.06em',
          }}
        >
          OPEN IN TRADINGVIEW <ChevronRight size={10} />
        </a>
      </div>
    </div>
  )
}
```

**Step 2: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add frontend/src/components/StockIntelPanel.jsx
git commit -m "feat(ui): add StockIntelPanel with score ring, signals, trade plan"
```

---

## Task 6: Unified Scanner Table + Filter Bar

**Files:**
- Create: `frontend/src/components/ScannerTable.jsx`
- Create: `frontend/src/components/ScannerFilters.jsx`

**What it does:**
- `ScannerFilters.jsx` — filter bar with: min score slider, setup type multi-select, sector select, vol filter, "hot only" toggle
- `ScannerTable.jsx` — unified sortable table of ALL setup types merged and sorted by score. Columns: Score | Ticker | Setup Type | Price | Volume | RS | Distance | Entry | Stop | Sector

**Key:** All setup types (vcp, pullback, base, res-breakout, htf, lce, options) are merged into a single array, deduplicated by ticker (keep highest score), sorted by score desc.

**Step 1: Create `frontend/src/components/ScannerFilters.jsx`**

```jsx
import { Filter, Flame } from 'lucide-react'

const SETUP_TYPES = ['ALL', 'VCP', 'PULLBACK', 'BASE', 'RES-BRK', 'HTF', 'LCE', 'OPTIONS']

export default function ScannerFilters({ filters, onFiltersChange }) {
  const { minScore, setupType, hotOnly, searchQuery } = filters

  const update = (key, val) => onFiltersChange({ ...filters, [key]: val })

  const inputStyle = {
    background: 'var(--panel)',
    border: '1px solid var(--border)',
    borderRadius: 6,
    padding: '4px 8px',
    color: 'var(--text)',
    fontSize: 11,
    fontFamily: '"IBM Plex Mono", monospace',
    outline: 'none',
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 16px',
      background: 'var(--card)',
      borderBottom: '1px solid var(--card-border)',
      flexShrink: 0,
      flexWrap: 'wrap',
    }}>
      <Filter size={13} color="var(--muted)" />
      <span style={{ fontSize: 10, color: 'var(--muted)', letterSpacing: '0.08em', fontWeight: 600 }}>
        FILTER
      </span>

      {/* Min score */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>Score ≥</span>
        <input
          type="number"
          min={0} max={100} step={5}
          value={minScore}
          onChange={e => update('minScore', Number(e.target.value))}
          style={{ ...inputStyle, width: 50, textAlign: 'center' }}
        />
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 16, background: 'var(--border)' }} />

      {/* Setup type */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {SETUP_TYPES.map(t => (
          <button
            key={t}
            onClick={() => update('setupType', t)}
            style={{
              padding: '3px 7px', borderRadius: 5, fontSize: 9,
              fontWeight: 700, fontFamily: '"IBM Plex Mono", monospace',
              letterSpacing: '0.06em', border: 'none', cursor: 'pointer',
              background: setupType === t ? 'rgba(0,200,122,0.15)' : 'var(--panel)',
              color: setupType === t ? 'var(--go)' : 'var(--muted)',
              outline: setupType === t ? '1px solid rgba(0,200,122,0.35)' : 'none',
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 16, background: 'var(--border)' }} />

      {/* Search */}
      <input
        value={searchQuery}
        onChange={e => update('searchQuery', e.target.value.toUpperCase())}
        placeholder="TICKER..."
        style={{ ...inputStyle, width: 80 }}
      />

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Hot only */}
      <button
        onClick={() => update('hotOnly', !hotOnly)}
        style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: '4px 10px', borderRadius: 6, fontSize: 10, fontWeight: 700,
          fontFamily: '"IBM Plex Mono", monospace',
          background: hotOnly ? 'rgba(245,166,35,0.12)' : 'var(--panel)',
          color: hotOnly ? 'var(--accent)' : 'var(--muted)',
          border: `1px solid ${hotOnly ? 'rgba(245,166,35,0.35)' : 'var(--border)'}`,
          cursor: 'pointer',
        }}
      >
        <Flame size={11} /> HOT
      </button>
    </div>
  )
}
```

**Step 2: Create `frontend/src/components/ScannerTable.jsx`**

```jsx
import { useState, useMemo } from 'react'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'

const SETUP_TYPE_LABEL = {
  VCP:               'VCP',
  PULLBACK:          'PB',
  'PULLBACK-RLX':    'PB-RLX',
  BASE:              'BASE',
  'RES-BREAKOUT':    'BRK',
  'HTF':             'HTF',
  'LCE':             'LCE',
  'OPTIONS-CATALYST':'OPT',
}

const TYPE_COLOR = {
  VCP:               '#F5A623',
  PULLBACK:          '#00C8FF',
  'PULLBACK-RLX':    '#00C8FF',
  BASE:              '#9B6EFF',
  'RES-BREAKOUT':    '#00c87a',
  HTF:               '#FF6EC7',
  LCE:               '#9B6EFF',
  'OPTIONS-CATALYST':'#00C8FF',
}

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <ArrowUpDown size={9} color="var(--muted)" />
  return sortDir === 'desc'
    ? <ArrowDown size={9} color="var(--accent)" />
    : <ArrowUp size={9} color="var(--accent)" />
}

export default function ScannerTable({
  allSetups,
  filters,
  selectedTicker,
  onSelectTicker,
  livePrices = {},
}) {
  const [sortCol, setSortCol] = useState('score')
  const [sortDir, setSortDir] = useState('desc')

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortCol(col); setSortDir('desc') }
  }

  // Apply filters + sort
  const rows = useMemo(() => {
    let data = [...allSetups]

    // Setup type filter
    if (filters.setupType !== 'ALL') {
      data = data.filter(s => {
        const t = (s.setup_type ?? '').toUpperCase()
        const f = filters.setupType
        if (f === 'VCP')      return t === 'VCP'
        if (f === 'PULLBACK') return t.startsWith('PULLBACK')
        if (f === 'BASE')     return t === 'BASE'
        if (f === 'RES-BRK')  return t === 'RES-BREAKOUT'
        if (f === 'HTF')      return t === 'HTF'
        if (f === 'LCE')      return t === 'LCE'
        if (f === 'OPTIONS')  return t === 'OPTIONS-CATALYST'
        return true
      })
    }

    // Min score
    if (filters.minScore > 0) {
      data = data.filter(s => (s.setup_score ?? 0) >= filters.minScore)
    }

    // Hot only
    if (filters.hotOnly) {
      data = data.filter(s => s.hot_sector)
    }

    // Ticker search
    if (filters.searchQuery) {
      data = data.filter(s => s.ticker?.includes(filters.searchQuery))
    }

    // Sort
    data.sort((a, b) => {
      let av, bv
      if (sortCol === 'score')    { av = a.setup_score ?? 0;    bv = b.setup_score ?? 0    }
      else if (sortCol === 'rs')  { av = a.rs_score ?? -99;     bv = b.rs_score ?? -99     }
      else if (sortCol === 'rr')  { av = a.rr ?? 0;             bv = b.rr ?? 0             }
      else if (sortCol === 'vol') { av = a.vol_ratio ?? 0;      bv = b.vol_ratio ?? 0      }
      else if (sortCol === 'ticker') { av = a.ticker ?? '';     bv = b.ticker ?? ''        }
      else { av = a.setup_score ?? 0; bv = b.setup_score ?? 0 }

      return sortDir === 'desc'
        ? (typeof av === 'string' ? bv.localeCompare(av) : bv - av)
        : (typeof av === 'string' ? av.localeCompare(bv) : av - bv)
    })

    return data
  }, [allSetups, filters, sortCol, sortDir])

  const thStyle = (col) => ({
    cursor: 'pointer',
    userSelect: 'none',
    whiteSpace: 'nowrap',
  })

  return (
    <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
      <table className="terminal-table" style={{ background: 'var(--card)' }}>
        <thead>
          <tr>
            {[
              { col: 'score',  label: 'SCR' },
              { col: 'ticker', label: 'TICKER' },
              { col: null,     label: 'TYPE' },
              { col: null,     label: 'PRICE' },
              { col: 'vol',    label: 'VOL ×' },
              { col: 'rs',     label: 'RS' },
              { col: null,     label: 'DIST' },
              { col: null,     label: 'ENTRY' },
              { col: null,     label: 'STOP' },
              { col: 'rr',     label: 'R:R' },
              { col: null,     label: 'SECTOR' },
            ].map(({ col, label }) => (
              <th
                key={label}
                style={{ ...thStyle(col), textAlign: label === 'SECTOR' ? 'left' : 'right' }}
                onClick={col ? () => handleSort(col) : undefined}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                  {label !== 'TICKER' && label !== 'TYPE' && label !== 'SECTOR' ? null : null}
                  {label}
                  {col && <SortIcon col={col} sortCol={sortCol} sortDir={sortDir} />}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={11} style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontSize: 11 }}>
                No setups match current filters
              </td>
            </tr>
          )}
          {rows.map((s, i) => {
            const isSelected  = selectedTicker === s.ticker
            const livePrice   = livePrices[s.ticker]
            const dist        = (livePrice && s.entry > 0)
              ? ((livePrice - s.entry) / s.entry) * 100
              : null
            const isNearEntry = dist !== null && dist > -3 && dist < 0
            const isVolSurge  = s.is_vol_surge

            const score = typeof s.setup_score === 'number' ? Math.round(s.setup_score) : null
            const scoreColor = score === null ? 'var(--muted)'
              : score >= 80 ? 'var(--go)'
              : score >= 60 ? 'var(--accent)'
              : 'var(--muted)'

            const typeKey   = (s.setup_type ?? '').toUpperCase()
            const typeLabel = SETUP_TYPE_LABEL[typeKey] ?? typeKey
            const typeColor = TYPE_COLOR[typeKey] ?? 'var(--muted)'

            const rsInt   = s.rs_score != null ? Math.round(s.rs_score * 100) : null
            const rsLabel = rsInt === null ? '—' : rsInt >= 0 ? `+${rsInt}` : `${rsInt}`
            const rsColor = rsInt === null ? 'var(--muted)' : rsInt >= 5 ? 'var(--go)' : 'var(--muted)'

            const rowBg = isVolSurge
              ? 'rgba(0,200,122,0.04)'
              : isSelected ? 'rgba(245,166,35,0.05)' : undefined

            const rowBorderLeft = isSelected
              ? '2px solid var(--accent)'
              : isNearEntry ? '2px solid rgba(245,166,35,0.6)'
              : isVolSurge  ? '2px solid rgba(0,200,122,0.4)'
              : '2px solid transparent'

            // Age
            const daysOld = s.setup_date
              ? Math.floor((Date.now() - new Date(s.setup_date).getTime()) / 86400000)
              : null

            const td = (content, align = 'right', color) => (
              <td style={{ textAlign: align, color: color ?? 'var(--text)' }}>
                {content}
              </td>
            )

            return (
              <tr
                key={`${s.ticker}-${s.setup_type}-${i}`}
                className={`${isSelected ? 'selected' : ''} ${isNearEntry ? 'row-near-entry' : ''}`}
                style={{ background: rowBg, borderLeft: rowBorderLeft }}
                onClick={() => onSelectTicker(s.ticker)}
              >
                {/* Score */}
                <td style={{ textAlign: 'right', width: 40 }}>
                  <span style={{ color: scoreColor, fontWeight: 700, fontSize: 11 }}>
                    {score ?? '—'}
                  </span>
                </td>

                {/* Ticker + age */}
                <td style={{ textAlign: 'left' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{
                        fontWeight: 700, fontSize: 11,
                        color: isSelected ? 'var(--accent)' : 'var(--text)',
                      }}>
                        {s.ticker}
                      </span>
                      {s.hot_sector && <span style={{ fontSize: 9 }}>🔥</span>}
                      {s.rs_blue_dot && (
                        <span style={{
                          width: 5, height: 5, borderRadius: '50%',
                          background: 'var(--blue)', flexShrink: 0,
                          boxShadow: '0 0 4px var(--blue)',
                        }} />
                      )}
                    </div>
                    {daysOld != null && daysOld >= 1 && (
                      <span style={{
                        fontSize: 8,
                        color: daysOld >= 5 ? 'rgba(255,45,85,0.6)' : 'var(--muted)',
                      }}>
                        {daysOld}d ago
                      </span>
                    )}
                  </div>
                </td>

                {/* Type */}
                <td style={{ textAlign: 'left' }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '1px 5px', borderRadius: 4,
                    fontSize: 8, fontWeight: 700, letterSpacing: '0.06em',
                    background: `${typeColor}18`,
                    color: typeColor,
                    border: `1px solid ${typeColor}30`,
                  }}>
                    {typeLabel}
                  </span>
                </td>

                {/* Live price + dist */}
                <td style={{ textAlign: 'right' }}>
                  {livePrice ? (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 0 }}>
                      <span style={{
                        color: dist === null ? 'var(--text)'
                          : dist >= 0 ? 'var(--go)'
                          : dist > -3 ? 'var(--accent)'
                          : 'var(--muted)',
                        fontWeight: 600,
                      }}>
                        ${livePrice.toFixed(2)}
                      </span>
                      {dist !== null && (
                        <span style={{
                          fontSize: 8,
                          color: dist >= 0 ? 'var(--go)' : dist > -3 ? 'var(--accent)' : 'var(--muted)',
                        }}>
                          {dist >= 0 ? `▲${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`}
                        </span>
                      )}
                    </div>
                  ) : td('—', 'right', 'var(--muted)')}
                </td>

                {/* Vol ratio */}
                {td(
                  s.vol_ratio ? `×${Number(s.vol_ratio).toFixed(1)}` : '—',
                  'right',
                  s.is_vol_surge ? 'var(--go)' : 'var(--muted)'
                )}

                {/* RS */}
                {td(rsLabel, 'right', rsColor)}

                {/* Distance */}
                {td(
                  dist !== null
                    ? (dist >= 0 ? `+${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`)
                    : '—',
                  'right',
                  dist !== null && dist > -3 && dist < 0 ? 'var(--accent)' : 'var(--muted)'
                )}

                {/* Entry */}
                {td(s.entry ? `$${s.entry.toFixed(2)}` : '—', 'right')}

                {/* Stop */}
                {td(s.stop_loss ? `$${s.stop_loss.toFixed(2)}` : '—', 'right', 'var(--halt)')}

                {/* R:R */}
                {td(
                  s.rr ? Number(s.rr).toFixed(1) : '—',
                  'right',
                  s.rr && Number(s.rr) >= 2 ? 'var(--go)' : 'var(--muted)'
                )}

                {/* Sector */}
                <td style={{ textAlign: 'left', color: 'var(--muted)', fontSize: 9 }}>
                  {s.sector ? s.sector.substring(0, 12) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
```

**Step 3: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

**Step 4: Commit**

```bash
git add frontend/src/components/ScannerTable.jsx frontend/src/components/ScannerFilters.jsx
git commit -m "feat(ui): add unified ScannerTable and ScannerFilters components"
```

---

## Task 7: Assemble New App Layout (App.jsx Restructure)

**Files:**
- Modify: `frontend/src/App.jsx` — new shell layout + page routing

**This is the wiring task.** All existing state, API calls, and component imports stay. We replace the layout JSX with the new sidebar + topbar + page content structure.

**Step 1: Read `frontend/src/App.jsx` lines 1–560** to understand the full current structure.

**Step 2: Rewrite `App.jsx`**

The key changes:
1. Replace `activeTab` with `activePage` (string: 'scanner', 'watchlist', 'portfolio', 'analytics', 'settings', 'dashboard')
2. Add `filters` state for the scanner filter bar
3. Add `selectedSetup` computed from `selectedTicker` across all setup arrays
4. Replace layout JSX with: `<div style={rootStyle}> <Sidebar> <div style={contentStyle}> <TopBar> <PageContent> </div> </div>`
5. Scanner page: StatCards + `<div style={mainArea}>` [chart+panel] + [filters+table]
6. Remove the `WatchlistPanel` from sidebar; add it to Watchlist page
7. Remove `Header.jsx` from import (replaced by TopBar)
8. Keep `SystemGuideModal`, `DebugDrawer`, `BacktestPanel` as overlays
9. Keep `chartFocus` F-key behavior — in new layout, `chartFocus` hides stat cards + scanner table, expanding the chart to full height

**Replace the return JSX in App.jsx with:**

```jsx
// New imports to add at top:
import Sidebar         from './components/Sidebar.jsx'
import TopBar          from './components/TopBar.jsx'
import StatCards       from './components/StatCards.jsx'
import StockIntelPanel from './components/StockIntelPanel.jsx'
import ScannerTable    from './components/ScannerTable.jsx'
import ScannerFilters  from './components/ScannerFilters.jsx'

// New state to add alongside existing state:
const [activePage, setActivePage] = useState('scanner')
const [filters, setFilters] = useState({
  minScore: 0,
  setupType: 'ALL',
  hotOnly: false,
  searchQuery: '',
})

// Computed: all setups merged for unified table
const allSetups = [
  ...vcpSetups,
  ...pullbackSetups,
  ...baseSetups,
  ...resBreakoutSetups,
  ...htfSetups,
  ...lceSetups,
  ...optionsSetups,
]

// Computed: find the setup object for the selected ticker
const selectedSetup = allSetups.find(s => s.ticker === selectedTicker) ?? null

// handleTickerClick update: don't switch tabs, just set selectedTicker
// Remove `if (switchTab) setActiveTab('scanner')` — replace with `setActivePage('scanner')`
```

**New return JSX:**

```jsx
return (
  <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--bg)' }}>

    {/* ── Sidebar ──────────────────────────────────────────── */}
    <Sidebar activePage={activePage} onNavigate={setActivePage} />

    {/* ── Main content ─────────────────────────────────────── */}
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

      {/* Top bar */}
      <TopBar
        activePage={activePage}
        regime={regime}
        scanStatus={scanStatus}
        onRunScan={handleRunScan}
        onSearchTicker={(t) => handleTickerClick(t, false)}
        devMode={devMode}
        dryRun={dryRun}
        onToggleDev={() => setDevMode(v => !v)}
        onToggleDryRun={() => setDryRun(v => !v)}
        onOpenGuide={() => setShowGuide(true)}
      />

      {/* ── SCANNER PAGE ──────────────────────────────────── */}
      {activePage === 'scanner' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

          {/* Stat cards row */}
          {!chartFocus && (
            <StatCards regime={regime} allSetups={allSetups} />
          )}

          {/* Middle: Chart + Intel Panel */}
          <div style={{
            flex: chartFocus ? 1 : '0 0 420px',
            display: 'flex', gap: 12,
            padding: '0 16px 12px',
            minHeight: 0,
            position: 'relative',
          }}>
            {/* Chart focus hint */}
            {chartFocus && (
              <div style={{
                position: 'absolute', top: 8, right: 28, zIndex: 10,
                fontSize: 8, color: 'rgba(245,166,35,0.5)',
                fontFamily: '"IBM Plex Mono", monospace', letterSpacing: '0.08em',
                pointerEvents: 'none',
              }}>
                F — EXIT FOCUS
              </div>
            )}

            {/* Chart card */}
            <div
              className="card"
              style={{ flex: 1, minWidth: 0, overflow: 'hidden', padding: 0, position: 'relative' }}
            >
              <TradingChart
                ticker={selectedTicker}
                data={chartData}
                loading={loadingChart}
                regime={regime}
              />
            </div>

            {/* Right panel — hidden in focus mode */}
            {!chartFocus && (
              <StockIntelPanel setup={selectedSetup} livePrices={livePrices} />
            )}
          </div>

          {/* Bottom: Filter bar + Scanner table */}
          {!chartFocus && (
            <div style={{
              flex: 1, display: 'flex', flexDirection: 'column',
              margin: '0 16px 16px',
              background: 'var(--card)',
              border: '1px solid var(--card-border)',
              borderRadius: 12,
              overflow: 'hidden',
              minHeight: 0,
            }}>
              <ScannerFilters filters={filters} onFiltersChange={setFilters} />
              <ScannerTable
                allSetups={allSetups}
                filters={filters}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                livePrices={livePrices}
              />
            </div>
          )}
        </div>
      )}

      {/* ── WATCHLIST PAGE ────────────────────────────────── */}
      {activePage === 'watchlist' && (
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          <WatchlistPanel
            items={watchlistItems}
            selectedTicker={selectedTicker}
            onSelectTicker={handleTickerClick}
            loading={loadingSetups}
          />
        </div>
      )}

      {/* ── PORTFOLIO PAGE ────────────────────────────────── */}
      {activePage === 'portfolio' && (
        <div style={{ flex: 1, overflow: 'auto' }}>
          <PortfolioTab
            regime={regime}
            scanStatus={scanStatus}
            onSelectTicker={handleTickerClick}
            devMode={devMode}
          />
        </div>
      )}

      {/* ── ANALYTICS PAGE ───────────────────────────────── */}
      {activePage === 'analytics' && (
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          <BacktestPanel />
        </div>
      )}

      {/* ── DASHBOARD / SETUPS / SETTINGS — stubs ────────── */}
      {['dashboard', 'setups', 'settings'].includes(activePage) && (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--muted)', flexDirection: 'column', gap: 8,
        }}>
          <span style={{ fontSize: 32 }}>🚧</span>
          <span style={{ fontSize: 13, fontFamily: '"IBM Plex Mono", monospace' }}>
            {activePage.toUpperCase()} — coming soon
          </span>
        </div>
      )}
    </div>

    {/* ── Overlays (all pages) ─────────────────────────────── */}
    {showGuide && <SystemGuideModal onClose={() => setShowGuide(false)} />}
    {devMode && debugTicker && (
      <DebugDrawer
        ticker={debugTicker}
        data={debugData}
        loading={debugLoading}
        onClose={() => setDebugTicker(null)}
      />
    )}
  </div>
)
```

**Step 3: Update the keyboard handler** — update the existing `useEffect` for `?` key to also handle page-level shortcuts. Keep F key for chart focus. Add `Escape` to close debug drawer:

```jsx
useEffect(() => {
  const handler = (e) => {
    if (document.activeElement.tagName === 'INPUT') return
    if (e.key === '?') setShowGuide(v => !v)
    if ((e.key === 'f' || e.key === 'F') && document.activeElement.tagName !== 'INPUT') setChartFocus(v => !v)
    if (e.key === 'Escape') setDebugTicker(null)
  }
  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}, [])
```

**Step 4: Remove old Header import** — delete `import Header from './components/Header.jsx'` (no longer used in App.jsx)

**Step 5: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -15
```
Expected: `✓ built` — if there are import errors for removed props (e.g. `Header` no longer gets `regime` prop), just ensure the import line is removed.

**Step 6: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat(ui): restructure App.jsx with sidebar nav, topbar, new scanner page layout"
```

---

---

## Task 8: Backend — Stock Analysis Endpoint

**Files:**
- Modify: `backend/main.py` (add `/api/analyze/{ticker}` endpoint)

**What it does:** Fetches a single ticker, runs it through all engines, generates a structured analysis: score, setup found, trade plan, and a 3-sentence rule-based narrative. Works for ANY ticker, not just scanner results.

**Step 1: Read `backend/main.py`** — search for the `/api/debug/{ticker}` endpoint (around line 1400–1500) to understand how single-ticker analysis is done. Also read `backend/scoring.py` to understand `compute_setup_score`.

**Step 2: Add the narrative generator function** — add this function near the top of `main.py` (after imports, before route definitions):

```python
def _generate_analysis_narrative(ticker: str, signals: dict, best_setup: dict | None) -> dict:
    """
    Rule-based narrative generator. Returns:
    {
        "verdict":   "TRADE CANDIDATE" | "WATCHLIST" | "AVOID",
        "verdict_color": "go" | "accent" | "halt",
        "quality":   "Strong" | "Moderate" | "Weak" | "No Setup",
        "narrative": str,   # 2-4 sentences
    }
    """
    rs_score   = signals.get("rs_score", 0.0) or 0.0
    vol_ratio  = signals.get("vol_ratio", 1.0) or 1.0
    price      = signals.get("price", 0.0) or 0.0
    above_ema  = signals.get("above_ema20", False)
    above_sma  = signals.get("above_sma50", False)
    score      = best_setup.get("setup_score", 0) if best_setup else 0

    sentences = []

    # RS sentence
    if rs_score > 0.10:
        sentences.append("Relative strength is strong — the stock is meaningfully outperforming the market.")
    elif rs_score > 0.02:
        sentences.append("Relative strength is modestly positive versus the benchmark.")
    elif rs_score > -0.05:
        sentences.append("Relative strength is near-neutral, neither leading nor lagging significantly.")
    else:
        sentences.append("Relative strength is declining — the stock is underperforming the market.")

    # Volume sentence
    if vol_ratio >= 1.5:
        sentences.append(f"Volume is surging at {vol_ratio:.1f}× the 50-day average, showing strong participation.")
    elif vol_ratio >= 1.1:
        sentences.append("Volume is above average, indicating improving buying interest.")
    else:
        sentences.append("Volume participation is below average, limiting conviction in any move.")

    # Trend / structure sentence
    if above_ema and above_sma:
        sentences.append("Price is trading above both the 20-day EMA and 50-day SMA, confirming a healthy uptrend structure.")
    elif above_ema and not above_sma:
        sentences.append("Price is recovering above the 20-day EMA but remains below the 50-day SMA — trend is mixed.")
    else:
        sentences.append("Price is trading below key moving averages — no clear uptrend structure is present.")

    # Setup sentence
    if best_setup:
        st = best_setup.get("setup_type", "setup")
        entry = best_setup.get("entry", 0)
        sentences.append(f"A {st} pattern has been detected with an entry near ${entry:.2f}.")
    else:
        sentences.append("No high-quality breakout pattern has been identified at current price levels.")

    # Verdict
    if score >= 70 and best_setup:
        verdict = "TRADE CANDIDATE"
        verdict_color = "go"
        quality = "Strong"
    elif score >= 50 or (best_setup and score >= 40):
        verdict = "WATCHLIST"
        verdict_color = "accent"
        quality = "Moderate"
    else:
        verdict = "AVOID"
        verdict_color = "halt"
        quality = "Weak" if score > 0 else "No Setup"

    return {
        "verdict":       verdict,
        "verdict_color": verdict_color,
        "quality":       quality,
        "narrative":     " ".join(sentences[:4]),
    }
```

**Step 3: Add the `/api/analyze/{ticker}` endpoint** — add this after the existing `/api/debug/{ticker}` endpoint:

```python
@app.get("/api/analyze/{ticker}")
async def analyze_ticker(ticker: str, db_path: str = DB_PATH):
    """
    Full technical analysis for any ticker.
    Runs all engines on the ticker and returns a structured analysis
    including score, setup, trade plan, and a written narrative.
    """
    ticker = ticker.upper().strip()

    try:
        # ── 1. Fetch price data ───────────────────────────────────────────
        import yfinance as yf
        raw = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
        if raw is None or raw.empty or len(raw) < 60:
            return {
                "ticker":      ticker,
                "score":       0,
                "setup_type":  None,
                "entry":       None,
                "stop_loss":   None,
                "take_profit": None,
                "rr":          None,
                "verdict":     "NO DATA",
                "verdict_color": "halt",
                "quality":     "No Data",
                "narrative":   "Insufficient price history to perform analysis.",
                "signals":     {},
            }

        # Normalize columns
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.rename(columns=str.title).copy()

        # ── 2. Basic signals for narrative ────────────────────────────────
        close   = float(df["Close"].iloc[-1])
        ema20   = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        sma50   = float(df["Close"].rolling(50).mean().iloc[-1])
        vol_50  = float(df["Volume"].rolling(50).mean().iloc[-1]) if "Volume" in df.columns else 1.0
        vol_now = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 1.0
        vol_ratio = vol_now / vol_50 if vol_50 > 0 else 1.0

        # RS vs SPY (simple 63-day return diff)
        try:
            spy_raw = yf.download("SPY", period="6mo", auto_adjust=True, progress=False)
            if isinstance(spy_raw.columns, pd.MultiIndex):
                spy_raw.columns = spy_raw.columns.get_level_values(0)
            spy_close = spy_raw["Close"] if "Close" in spy_raw.columns else spy_raw.iloc[:, 0]
            n = min(63, len(df) - 1, len(spy_close) - 1)
            stock_ret = float(df["Close"].iloc[-1] / df["Close"].iloc[-(n+1)] - 1)
            spy_ret   = float(spy_close.iloc[-1] / spy_close.iloc[-(n+1)] - 1)
            rs_score  = stock_ret - spy_ret
        except Exception:
            rs_score = 0.0

        signals = {
            "price":       close,
            "ema20":       ema20,
            "sma50":       sma50,
            "above_ema20": close > ema20,
            "above_sma50": close > sma50,
            "vol_ratio":   round(vol_ratio, 2),
            "rs_score":    round(rs_score, 4),
        }

        # ── 3. Check if ticker already has a scanner setup ────────────────
        from database import get_setups_by_ticker
        existing = await get_setups_by_ticker(db_path, ticker)
        best_setup = None
        if existing:
            best_setup = max(existing, key=lambda s: s.get("setup_score") or 0)
            signals["vol_ratio"] = best_setup.get("vol_ratio", signals["vol_ratio"])
            signals["rs_score"]  = best_setup.get("rs_score",  signals["rs_score"])

        # ── 4. Generate narrative ─────────────────────────────────────────
        analysis = _generate_analysis_narrative(ticker, signals, best_setup)

        return {
            "ticker":      ticker,
            "score":       int(best_setup.get("setup_score") or 0) if best_setup else 0,
            "setup_type":  best_setup.get("setup_type")  if best_setup else None,
            "entry":       best_setup.get("entry")       if best_setup else None,
            "stop_loss":   best_setup.get("stop_loss")   if best_setup else None,
            "take_profit": best_setup.get("take_profit") if best_setup else None,
            "rr":          best_setup.get("rr")          if best_setup else None,
            **analysis,
            "signals":     signals,
        }

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {
            "ticker":      ticker,
            "score":       0,
            "setup_type":  None,
            "entry":       None,
            "stop_loss":   None,
            "take_profit": None,
            "rr":          None,
            "verdict":     "ERROR",
            "verdict_color": "halt",
            "quality":     "Error",
            "narrative":   f"Analysis failed: {str(exc)[:120]}",
            "signals":     {},
        }
```

**Step 4: Add `get_setups_by_ticker` to `database.py`** — add this helper that fetches all setups for a ticker from the current scan:

```python
async def get_setups_by_ticker(db_path: str, ticker: str) -> list[dict]:
    """Return all setups for a given ticker from the most recent scan."""
    scan_ts = await get_latest_scan_timestamp(db_path)
    if not scan_ts:
        return []
    results = []
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT ticker, setup_type, entry, stop_loss, take_profit, rr, setup_date, metadata
               FROM setups WHERE scan_timestamp = ? AND ticker = ?""",
            (scan_ts, ticker.upper()),
        ) as cur:
            async for row in cur:
                import json as _json
                record = {
                    "ticker": row[0], "setup_type": row[1],
                    "entry": row[2], "stop_loss": row[3],
                    "take_profit": row[4], "rr": row[5], "setup_date": row[6],
                }
                try:
                    record.update(_json.loads(row[7]) if row[7] else {})
                except Exception:
                    pass
                results.append(record)
    return results
```

**Step 5: Add `fetchAnalysis` to `frontend/src/api.js`**

```js
export const fetchAnalysis = (ticker) =>
  fetch(`/api/analyze/${ticker}`).then(handleResponse)
```

**Step 6: Verify backend starts without errors**

```bash
cd backend && python3 -c "import main; print('OK')" 2>&1 | tail -5
```

**Step 7: Commit**

```bash
git add backend/main.py backend/database.py frontend/src/api.js
git commit -m "feat(analysis): add /api/analyze/{ticker} endpoint with rule-based narrative generator"
```

---

## Task 9: Frontend — Analysis Panel in StockIntelPanel

**Files:**
- Modify: `frontend/src/components/StockIntelPanel.jsx` (add analysis section)
- Modify: `frontend/src/App.jsx` (trigger analysis on ticker search/click)

**What it does:** When a ticker is selected (from table or search), fetch `/api/analyze/{ticker}` and display verdict + narrative in the StockIntelPanel below the trade plan.

**Step 1: Read `frontend/src/components/StockIntelPanel.jsx`** (built in Task 5).

**Step 2: Add analysis display to StockIntelPanel**

Add a new prop `analysis` to StockIntelPanel. Show it as a bottom section when present.

Add this section at the bottom of the panel (after the TradingView link, before the closing `</div>`):

```jsx
{/* Analysis section */}
{analysis && (
  <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
    {/* Verdict badge */}
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
      <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)' }}>
        AI VERDICT
      </span>
      <span style={{
        padding: '3px 8px', borderRadius: 5,
        fontSize: 9, fontWeight: 700, letterSpacing: '0.06em',
        fontFamily: '"IBM Plex Mono", monospace',
        background: analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.15)'
                  : analysis.verdict_color === 'accent' ? 'rgba(245,166,35,0.15)'
                  : 'rgba(255,45,85,0.12)',
        color: analysis.verdict_color === 'go'     ? 'var(--go)'
             : analysis.verdict_color === 'accent' ? 'var(--accent)'
             : 'var(--halt)',
        border: `1px solid ${
          analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.35)'
        : analysis.verdict_color === 'accent' ? 'rgba(245,166,35,0.35)'
        : 'rgba(255,45,85,0.3)'
        }`,
      }}>
        {analysis.verdict}
      </span>
    </div>

    {/* Narrative */}
    <p style={{
      fontSize: 10,
      lineHeight: 1.6,
      color: 'var(--muted)',
      fontFamily: '"Inter", sans-serif',
      margin: 0,
    }}>
      {analysis.narrative}
    </p>

    {/* Quality label */}
    <div style={{ marginTop: 6, fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
      Setup Quality: <span style={{ color: 'var(--text)' }}>{analysis.quality}</span>
    </div>
  </div>
)}

{/* Loading state for analysis */}
{analysisLoading && (
  <div style={{
    padding: '10px 16px', borderTop: '1px solid var(--card-border)',
    display: 'flex', alignItems: 'center', gap: 6,
  }}>
    <div className="shimmer-row" style={{ flex: 1, height: 40 }} />
  </div>
)}
```

Update the component signature:
```jsx
export default function StockIntelPanel({ setup, livePrices, analysis, analysisLoading }) {
```

**Step 3: Wire analysis fetching in `App.jsx`**

Add state:
```jsx
const [analysis,        setAnalysis       ] = useState(null)
const [analysisLoading, setAnalysisLoading] = useState(false)
```

Update `handleTickerClick` to also fetch analysis:
```jsx
const handleTickerClick = useCallback(async (ticker, switchTab = true) => {
  if (switchTab) setActivePage('scanner')
  setSelectedTicker(ticker)
  setChartData(null)
  setLoadingChart(true)
  setAnalysis(null)
  setAnalysisLoading(true)

  // Fetch chart and analysis in parallel
  const [chartResult, analysisResult] = await Promise.allSettled([
    fetchChartData(ticker),
    fetchAnalysis(ticker),
  ])
  if (chartResult.status === 'fulfilled') setChartData(chartResult.value)
  if (analysisResult.status === 'fulfilled') setAnalysis(analysisResult.value)
  setLoadingChart(false)
  setAnalysisLoading(false)
}, [])
```

Also wire it for the TopBar search — when user searches a ticker, call `handleTickerClick` so analysis is fetched.

Pass `analysis` and `analysisLoading` to `StockIntelPanel`:
```jsx
<StockIntelPanel
  setup={selectedSetup}
  livePrices={livePrices}
  analysis={analysis}
  analysisLoading={analysisLoading}
/>
```

**Step 4: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

**Step 5: Commit**

```bash
git add frontend/src/components/StockIntelPanel.jsx frontend/src/App.jsx
git commit -m "feat(analysis): integrate stock analysis panel with verdict, narrative, and quality rating"
```

---

## Final Verification

After all 9 tasks are committed, run:

```bash
cd frontend && npm run build
```

Expected: exit code 0.

Visual checklist (open http://localhost:5174):
- [ ] Left sidebar visible (60px, icon nav, SC logo mark at top)
- [ ] TopBar shows page title, search, market status, RUN SCAN button
- [ ] Scanner page: 4 stat cards visible (Regime, Active Setups, Top Score, SPY)
- [ ] Chart fills center with card styling (rounded corners, shadow)
- [ ] Right panel (StockIntelPanel) shows "Select a stock" when none selected
- [ ] Clicking a scanner row → StockIntelPanel populates with score ring + signals
- [ ] Unified scanner table shows ALL setup types merged, sortable by Score
- [ ] Filter bar: min score input, type buttons, ticker search, HOT toggle all work
- [ ] Pressing F → chart expands full height (stat cards + table + intel panel hidden)
- [ ] Pressing F again → restores layout
- [ ] Sidebar nav: Portfolio → PortfolioTab renders, Watchlist → WatchlistPanel, Analytics → BacktestPanel
- [ ] Dashboard/Setups/Settings → "coming soon" stub
- [ ] `?` key → SystemGuideModal opens
- [ ] Run Scan button triggers scan + shows progress bar in TopBar
- [ ] Searching a ticker → StockIntelPanel shows analysis verdict (TRADE CANDIDATE / WATCHLIST / AVOID)
- [ ] Analysis narrative: 3-4 sentences about RS, volume, trend, setup
- [ ] Verdict badge color: green = TRADE CANDIDATE, amber = WATCHLIST, red = AVOID
- [ ] Analysis works for tickers NOT in scanner results (pure search)
