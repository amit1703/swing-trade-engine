# Watchlist Panel Table Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the card-style rows in WatchlistPanel with a compact sortable table (Score, Entry, SL, R:R columns) and per-section sort controls.

**Architecture:** Single file rewrite of `WatchlistPanel.jsx`. Add `brkSort`/`pbSort` state, a pure `sortItems()` helper, a `SortHeader` component for clickable column headers, and a `WatchRow` component for data rows. No backend changes.

**Tech Stack:** React 18, inline styles (project convention), IBM Plex Mono font.

---

## Codebase facts (read before editing)

| File | What to know |
|------|-------------|
| `frontend/src/components/WatchlistPanel.jsx` | Full rewrite. Current component: two sections (BRK/PB), card rows, no sort. |
| `frontend/src/App.jsx` | Passes `items`, `selectedTicker`, `onSelectTicker`, `loading`, `favorites`, `onToggleFavorite` to WatchlistPanel. Props interface unchanged. |

**Data fields available on each watchlist item** (from `GET /api/watchlist`):
- `ticker`, `entry`, `stop_loss`, `rr`, `setup_score` (may be 0 for engine2 items)
- `atr`, `distance_pct`, `watchlist_source` (`'RES_BREAKOUT'` or `'PULLBACK'`)
- `rs_blue_dot` (bool), `rs_score`

**Zero guards:** engine2-sourced items have `rr = 0`, `stop_loss = 0`, `setup_score` may be 0. Treat `=== 0` same as null → display `—`.

---

## File Map

| File | Action |
|------|--------|
| `frontend/src/components/WatchlistPanel.jsx` | Full rewrite |

---

## Task 1: Rewrite WatchlistPanel.jsx

**Files:**
- Modify: `frontend/src/components/WatchlistPanel.jsx` (full replacement)

- [ ] **Step 1: Read the current file**

Read `frontend/src/components/WatchlistPanel.jsx` in full so you understand what you are replacing.

- [ ] **Step 2: Replace the entire file** with the following implementation:

```jsx
import { useState, useMemo } from 'react'

// ── Pure sort helper ──────────────────────────────────────────────────────────

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

function sortItems(items, sort) {
  return [...items].sort((a, b) => {
    let av, bv
    if (sort.col === 'dist') {
      av = atrDist(a)
      bv = atrDist(b)
    } else {
      // scr
      av = a.setup_score ?? 0
      bv = b.setup_score ?? 0
    }
    return sort.dir === 'asc' ? av - bv : bv - av
  })
}

// ── Sub-components ────────────────────────────────────────────────────────────

const MONO = '"IBM Plex Mono", monospace'

function SectionHeader({ label, count }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '6px 12px',
      borderBottom: '1px solid var(--border)',
      background: 'rgba(255,255,255,0.02)',
    }}>
      <span style={{ fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--muted)', fontFamily: MONO, fontWeight: 700 }}>
        {label}
      </span>
      <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 4, background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)', color: 'var(--muted)', fontFamily: MONO, fontWeight: 700 }}>
        {count}
      </span>
    </div>
  )
}

function SortHeader({ sort, onSort, isBrk }) {
  const th = (label, col) => {
    const active = sort.col === col
    const arrow  = active ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''
    return (
      <th
        onClick={col ? () => onSort(col) : undefined}
        style={{
          padding: '4px 6px',
          textAlign: col === 'ticker' ? 'left' : 'right',
          fontSize: 8,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          fontFamily: MONO,
          color: active ? 'var(--accent)' : 'var(--muted)',
          cursor: col ? 'pointer' : 'default',
          userSelect: 'none',
          whiteSpace: 'nowrap',
          borderBottom: '1px solid var(--border)',
          background: 'rgba(255,255,255,0.02)',
        }}
      >
        {label}{arrow}
      </th>
    )
  }

  return (
    <thead>
      <tr>
        {th('Ticker', 'ticker')}
        {th('Dist',   'dist')}
        {th('Scr',    'scr')}
        {th('Entry',  null)}
        {th('SL',     null)}
        {th('R:R',    null)}
        {th('',       null)}
      </tr>
    </thead>
  )
}

function WatchRow({ item, isBrk, isSelected, isFavorited, onSelect, onToggleFavorite }) {
  const dist    = atrDist(item)
  const hasBlueDot  = !!item.rs_blue_dot

  // DIST display
  const distLabel  = dist < 99
    ? `${dist.toFixed(1)}${isBrk ? 'atr↓' : 'atr↑'}`
    : `${(item.distance_pct ?? 0).toFixed(1)}%`
  const distColor  = dist < 0.5 ? 'var(--go)' : dist < 1.5 ? 'var(--accent)' : 'var(--muted)'

  // SCR
  const scr      = item.setup_score
  const scrStr   = (scr && scr > 0) ? String(Math.round(scr)) : '—'
  const scrColor = scr >= 80 ? 'var(--go)' : scr >= 65 ? 'var(--accent)' : 'var(--muted)'

  // ENTRY / SL
  const entryStr = (item.entry  && item.entry  > 0) ? `$${item.entry.toFixed(2)}`    : '—'
  const slStr    = (item.stop_loss && item.stop_loss > 0) ? `$${item.stop_loss.toFixed(2)}` : '—'

  // R:R
  const rr       = item.rr
  const rrStr    = (rr && rr > 0) ? `${Number(rr).toFixed(1)}×` : '—'
  const rrColor  = rr >= 2 ? 'var(--go)' : 'var(--muted)'

  const borderColor = isSelected
    ? 'var(--accent)'
    : isBrk
    ? 'rgba(0,200,122,0.4)'
    : 'rgba(100,180,255,0.4)'

  const td = (content, opts = {}) => (
    <td style={{
      padding: '5px 6px',
      textAlign: opts.align ?? 'right',
      fontSize: opts.size ?? 10,
      fontFamily: MONO,
      color: opts.color ?? 'var(--text)',
      fontWeight: opts.bold ? 700 : 400,
      borderBottom: '1px solid var(--border)',
      whiteSpace: 'nowrap',
    }}>
      {content}
    </td>
  )

  return (
    <tr
      onClick={onSelect}
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background: isSelected ? 'rgba(245,166,35,0.06)' : 'transparent',
        cursor: 'pointer',
        transition: 'background 0.1s',
      }}
      onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
      onMouseLeave={e => { e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.06)' : 'transparent' }}
    >
      {/* Ticker */}
      <td style={{
        padding: '5px 6px',
        textAlign: 'left',
        borderBottom: '1px solid var(--border)',
        whiteSpace: 'nowrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 11, fontWeight: 700, fontFamily: MONO, color: isSelected ? 'var(--accent)' : 'var(--go)', letterSpacing: '0.03em' }}>
            {item.ticker}
          </span>
          {hasBlueDot && <span style={{ color: 'var(--blue)', fontSize: 8 }}>●</span>}
          <button
            onClick={e => { e.stopPropagation(); onToggleFavorite?.(item.ticker) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 10, color: isFavorited ? 'var(--accent)' : 'var(--muted)', opacity: isFavorited ? 1 : 0.4, transition: 'color 0.15s, opacity 0.15s' }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--accent)' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = isFavorited ? '1' : '0.4'; e.currentTarget.style.color = isFavorited ? 'var(--accent)' : 'var(--muted)' }}
          >
            {isFavorited ? '★' : '☆'}
          </button>
        </div>
      </td>

      {td(distLabel, { color: distColor })}
      {td(scrStr,    { color: scrColor })}
      {td(entryStr,  { size: 10 })}
      {td(slStr,     { color: 'var(--halt)' })}
      {td(rrStr,     { color: rrColor })}

      {/* TV link */}
      <td style={{ padding: '5px 6px', textAlign: 'right', borderBottom: '1px solid var(--border)' }}>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${item.ticker}&interval=D`}
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          style={{ fontSize: 8, padding: '1px 3px', borderRadius: 2, border: '1px solid rgba(245,166,35,0.25)', color: 'rgba(245,166,35,0.5)', fontFamily: MONO, fontWeight: 700, textDecoration: 'none', whiteSpace: 'nowrap' }}
        >
          TV
        </a>
      </td>
    </tr>
  )
}

function ShowMoreBtn({ allItems, showAll, onToggle }) {
  if (allItems.length <= 15) return null
  return (
    <button
      onClick={() => onToggle(v => !v)}
      style={{ width: '100%', padding: '6px', background: 'transparent', border: 'none', borderTop: '1px solid var(--border)', color: 'var(--muted)', cursor: 'pointer', fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase', fontFamily: MONO }}
    >
      {showAll ? `▲ Show top 15` : `▼ Show all ${allItems.length}`}
    </button>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function WatchlistPanel({ items, selectedTicker, onSelectTicker, loading, favorites = [], onToggleFavorite }) {
  const [brkSort, setBrkSort] = useState({ col: 'dist', dir: 'asc' })
  const [pbSort,  setPbSort]  = useState({ col: 'dist', dir: 'asc' })
  const [showAllBrk, setShowAllBrk] = useState(false)
  const [showAllPb,  setShowAllPb]  = useState(false)

  const handleSort = (setSort, currentSort, col) => {
    if (currentSort.col === col) {
      setSort(s => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))
    } else {
      // dist always starts asc (closest first); scr starts desc (highest first)
      setSort({ col, dir: col === 'dist' ? 'asc' : 'desc' })
    }
  }

  const brkItems = useMemo(() =>
    sortItems(items.filter(i => i.watchlist_source === 'RES_BREAKOUT'), brkSort),
    [items, brkSort]
  )
  const pbItems = useMemo(() =>
    sortItems(items.filter(i => i.watchlist_source === 'PULLBACK'), pbSort),
    [items, pbSort]
  )

  const visibleBrk = showAllBrk ? brkItems : brkItems.slice(0, 15)
  const visiblePb  = showAllPb  ? pbItems  : pbItems.slice(0, 15)
  const totalCount = brkItems.length + pbItems.length

  const renderSection = (label, sectionItems, visibleItems, isBrk, sort, setSort, showAll, setShowAll) => {
    if (sectionItems.length === 0) return null
    return (
      <>
        <SectionHeader label={label} count={sectionItems.length} />
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <SortHeader sort={sort} onSort={col => handleSort(setSort, sort, col)} isBrk={isBrk} />
          <tbody>
            {visibleItems.map(item => (
              <WatchRow
                key={item.ticker}
                item={item}
                isBrk={isBrk}
                isSelected={selectedTicker === item.ticker}
                isFavorited={favorites.includes(item.ticker)}
                onSelect={() => onSelectTicker(item.ticker)}
                onToggleFavorite={onToggleFavorite}
              />
            ))}
          </tbody>
        </table>
        <ShowMoreBtn allItems={sectionItems} showAll={showAll} onToggle={setShowAll} />
      </>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-t-panel">

      {/* Panel header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-t-border flex-shrink-0">
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--muted)', fontFamily: MONO }}>
          Watchlist
        </span>
        <span style={{ fontSize: 9, padding: '1px 7px', borderRadius: 4, background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)', color: 'var(--accent)', fontFamily: MONO, fontWeight: 700 }}>
          {totalCount}
        </span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 12 }}>
            {[...Array(4)].map((_, i) => (
              <div key={i} style={{ height: 34, borderRadius: 6, background: 'rgba(255,255,255,0.04)', opacity: 1 - i * 0.2 }} />
            ))}
          </div>
        ) : totalCount === 0 ? (
          <div className="py-8 px-4 text-center text-[10px] font-mono tracking-widest uppercase text-t-muted">
            No items — run a scan
          </div>
        ) : (
          <>
            {renderSection('Near Breakout', brkItems, visibleBrk, true,  brkSort, setBrkSort, showAllBrk, setShowAllBrk)}
            {renderSection('Pullback Setup', pbItems,  visiblePb,  false, pbSort,  setPbSort,  showAllPb,  setShowAllPb)}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify the dev server compiles without errors**

```bash
cd swing-trading-dashboard/frontend
npm run dev
```

Open the browser at `http://localhost:5173`, navigate to the Watchlist page. Expected:
- Table renders with TICKER / DIST / SCR / ENTRY / SL / R:R / TV columns
- DIST and SCR headers are clickable and sort each section independently
- Clicking DIST toggles asc/desc; default is asc (closest first)
- Clicking SCR sorts desc first (highest score first)
- Selected ticker highlights with amber border-left
- Star button still works
- TV link opens TradingView
- Show more / Show top 15 works
- Items with `rr = 0` show `—` in R:R and SL cells

- [ ] **Step 4: Commit**

```bash
cd swing-trading-dashboard
git add frontend/src/components/WatchlistPanel.jsx
git commit -m "feat: watchlist table with sortable columns (dist/score) and entry/SL/R:R data"
```

---

## Post-implementation deploy

After commit, push and deploy:

```bash
git push origin main

# On VPS:
ssh root@89.167.25.25
cd /opt/dashboard && git pull origin main
cd swing-trading-dashboard/frontend && npm install && npm run build
systemctl restart dashboard.service
```
