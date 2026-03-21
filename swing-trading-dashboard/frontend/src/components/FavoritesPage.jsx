import { useState, useMemo } from 'react'
import { Heart } from 'lucide-react'

// ── Type config ───────────────────────────────────────────────────────────────

const TYPE_CONFIG = {
  VCP:          { label: 'VCP',  color: '#50d8f0', border: 'rgba(80,216,240,0.35)'  },
  PULLBACK:     { label: 'PB',   color: '#64b4ff', border: 'rgba(100,180,255,0.4)'  },
  RES_BREAKOUT: { label: 'BRK',  color: '#00c87a', border: 'rgba(0,200,122,0.4)'    },
  BASE:         { label: 'BASE', color: '#9B6EFF', border: 'rgba(155,110,255,0.4)'  },
  HTF:          { label: 'HTF',  color: '#FF6EC7', border: 'rgba(255,110,199,0.4)'  },
  LCE:          { label: 'LCE',  color: '#9B6EFF', border: 'rgba(155,110,255,0.4)'  },
  WATCHLIST:    { label: 'WL',   color: '#50d8f0', border: 'rgba(80,216,240,0.35)'  },
}

function getTypeConfig(setupType) {
  return TYPE_CONFIG[setupType] ?? { label: setupType ?? '?', color: '#555555', border: 'transparent' }
}

function getWlConfig(watchlistSource) {
  return watchlistSource === 'RES_BREAKOUT'
    ? { label: 'WL↓', color: '#00c87a', border: 'rgba(0,200,122,0.4)'   }
    : { label: 'WL↑', color: '#64b4ff', border: 'rgba(100,180,255,0.4)' }
}

// ── Pure helpers ──────────────────────────────────────────────────────────────

function atrDist(row) {
  const dist  = row.distance_pct ?? 0
  const atr   = row.atr   ?? 0
  const entry = row.entry  ?? 0
  if (atr > 0 && entry > 0) {
    const atrPct = atr / entry * 100
    return atrPct > 0 ? dist / atrPct : 99
  }
  return dist
}

function buildRows(favorites, allSetups, watchlistItems) {
  const rows = []
  const seen = new Set()

  for (const s of allSetups) {
    if (!favorites.includes(s.ticker)) continue
    const tc = getTypeConfig(s.setup_type)
    rows.push({
      key: `${s.ticker}-${s.setup_type}-${s.entry}`,
      ticker: s.ticker, typeLabel: tc.label, typeColor: tc.color, borderColor: tc.border,
      entry: s.entry, stop_loss: s.stop_loss, rr: s.rr, setup_score: s.setup_score,
      atr: s.atr, distance_pct: s.distance_pct, rs_blue_dot: s.rs_blue_dot,
      isNotInScan: false,
    })
    seen.add(s.ticker)
  }

  for (const w of watchlistItems) {
    if (!favorites.includes(w.ticker)) continue
    const tc = getWlConfig(w.watchlist_source)
    rows.push({
      key: `${w.ticker}-wl-${w.watchlist_source}`,
      ticker: w.ticker, typeLabel: tc.label, typeColor: tc.color, borderColor: tc.border,
      entry: w.entry, stop_loss: w.stop_loss, rr: w.rr, setup_score: w.setup_score,
      atr: w.atr, distance_pct: w.distance_pct, rs_blue_dot: w.rs_blue_dot,
      isNotInScan: false,
    })
    seen.add(w.ticker)
  }

  for (const ticker of favorites) {
    if (!seen.has(ticker)) {
      rows.push({
        key: `${ticker}-notinscan`,
        ticker, typeLabel: null, typeColor: null, borderColor: 'transparent',
        entry: 0, stop_loss: 0, rr: 0, setup_score: 0,
        atr: 0, distance_pct: 0, rs_blue_dot: false,
        isNotInScan: true,
      })
    }
  }

  return rows
}

function sortRows(rows, sort) {
  const real = rows.filter(r => !r.isNotInScan)
  const tail = rows.filter(r =>  r.isNotInScan)
  real.sort((a, b) => {
    const av = sort.col === 'dist' ? atrDist(a) : (a.setup_score ?? 0)
    const bv = sort.col === 'dist' ? atrDist(b) : (b.setup_score ?? 0)
    return sort.dir === 'asc' ? av - bv : bv - av
  })
  return [...real, ...tail]
}

// ── Sub-components ────────────────────────────────────────────────────────────

const MONO = '"IBM Plex Mono", monospace'

function SortHeader({ sort, onSort }) {
  const th = (label, col) => {
    const active = sort.col === col
    const arrow  = active ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''
    return (
      <th
        onClick={col ? () => onSort(col) : undefined}
        style={{
          padding: '4px 6px',
          textAlign: label === 'Ticker' || label === 'Type' ? 'left' : 'right',
          fontSize: 8, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
          fontFamily: MONO,
          color: active ? 'var(--accent)' : 'var(--muted)',
          cursor: col ? 'pointer' : 'default',
          userSelect: 'none', whiteSpace: 'nowrap',
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
        {th('Ticker', null)}
        {th('Type',   null)}
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

function FavRow({ row, isSelected, onSelect, onToggleFavorite }) {
  const dist = atrDist(row)

  // DIST
  let distStr = '—', distColor = 'var(--muted)'
  if (!row.isNotInScan) {
    if (row.atr > 0 && row.entry > 0) {
      distStr   = `${dist.toFixed(1)}atr`
      distColor = dist < 0.5 ? 'var(--go)' : dist < 1.5 ? 'var(--accent)' : 'var(--muted)'
    } else if ((row.distance_pct ?? 0) > 0) {
      distStr = `${row.distance_pct.toFixed(1)}%`
    }
  }

  const scr    = row.setup_score
  const scrStr   = (!row.isNotInScan && scr && scr > 0) ? String(Math.round(scr)) : '—'
  const scrColor = scr >= 80 ? 'var(--go)' : scr >= 65 ? 'var(--accent)' : 'var(--muted)'

  const entryStr = (!row.isNotInScan && row.entry     > 0) ? `$${row.entry.toFixed(2)}`      : '—'
  const slStr    = (!row.isNotInScan && row.stop_loss > 0) ? `$${row.stop_loss.toFixed(2)}`  : '—'

  const rr     = row.rr
  const rrStr  = (!row.isNotInScan && rr > 0) ? `${Number(rr).toFixed(1)}×` : '—'
  const rrColor = rr >= 2 ? 'var(--go)' : 'var(--muted)'

  const borderColor = isSelected ? 'var(--accent)' : row.borderColor

  const td = (content, opts = {}) => (
    <td style={{
      padding: '5px 6px', textAlign: opts.align ?? 'right',
      fontSize: opts.size ?? 10, fontFamily: MONO,
      color: opts.color ?? 'var(--text)', fontWeight: opts.bold ? 700 : 400,
      borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
    }}>
      {content}
    </td>
  )

  return (
    <tr
      onClick={onSelect}
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background: isSelected ? 'rgba(80,216,240,0.05)' : 'transparent',
        cursor: 'pointer', transition: 'background 0.1s',
      }}
      onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
      onMouseLeave={e => { e.currentTarget.style.background = isSelected ? 'rgba(80,216,240,0.05)' : 'transparent' }}
    >
      {/* Ticker */}
      <td style={{ padding: '5px 6px', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button
            onClick={e => { e.stopPropagation(); onToggleFavorite?.(row.ticker) }}
            title="Remove from favorites"
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 10, color: 'var(--accent)', lineHeight: 1, flexShrink: 0 }}
          >★</button>
          <span style={{ fontSize: 11, fontWeight: 700, fontFamily: MONO, letterSpacing: '0.03em', color: isSelected ? 'var(--accent)' : row.isNotInScan ? 'var(--muted)' : 'var(--text)' }}>
            {row.ticker}
          </span>
          {row.rs_blue_dot && <span style={{ color: '#4a9eff', fontSize: 8 }}>●</span>}
        </div>
      </td>

      {/* TYPE badge */}
      <td style={{ padding: '5px 6px', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>
        {row.typeLabel ? (
          <span style={{
            padding: '1px 5px', borderRadius: 3, fontSize: 8, fontWeight: 700,
            letterSpacing: '0.06em', fontFamily: MONO,
            background: `${row.typeColor}18`, color: row.typeColor, border: `1px solid ${row.typeColor}30`,
          }}>
            {row.typeLabel}
          </span>
        ) : (
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: MONO }}>not in scan</span>
        )}
      </td>

      {td(distStr,  { color: distColor })}
      {td(scrStr,   { color: scrColor  })}
      {td(entryStr)}
      {td(slStr,    { color: 'var(--halt)' })}
      {td(rrStr,    { color: rrColor })}

      {/* TV */}
      <td style={{ padding: '5px 6px', textAlign: 'right', borderBottom: '1px solid var(--border)' }}>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${row.ticker}&interval=D`}
          target="_blank" rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          style={{ fontSize: 8, padding: '1px 3px', borderRadius: 2, border: '1px solid rgba(80,216,240,0.25)', color: 'rgba(80,216,240,0.5)', fontFamily: MONO, fontWeight: 700, textDecoration: 'none', whiteSpace: 'nowrap' }}
        >
          TV
        </a>
      </td>
    </tr>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function FavoritesPage({ favorites = [], onToggleFavorite, allSetups = [], watchlistItems = [], selectedTicker, onSelectTicker, livePrices = {} }) {
  const [sort, setSort] = useState({ col: 'dist', dir: 'asc' })

  const handleSort = (col) => {
    setSort(s => s.col === col
      ? { ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { col, dir: col === 'dist' ? 'asc' : 'desc' }
    )
  }

  const rows = useMemo(
    () => sortRows(buildRows(favorites, allSetups, watchlistItems), sort),
    [favorites, allSetups, watchlistItems, sort]
  )

  if (favorites.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-t-muted">
        <Heart size={32} strokeWidth={1.5} style={{ opacity: 0.3 }} />
        <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
          No favorites yet
        </div>
        <div style={{ fontFamily: MONO, fontSize: 9, opacity: 0.5, textAlign: 'center', maxWidth: 280, lineHeight: 1.6 }}>
          Star any ticker in the scanner or watchlist to add it here
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-t-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-t-border flex-shrink-0">
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <Heart size={13} strokeWidth={1.75} style={{ color: 'var(--accent)' }} />
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--muted)', fontFamily: MONO }}>
            Favorites
          </span>
        </div>
        <span style={{ fontSize: 9, padding: '1px 7px', borderRadius: 4, background: 'rgba(80,216,240,0.08)', border: '1px solid rgba(80,216,240,0.2)', color: 'var(--accent)', fontFamily: MONO, fontWeight: 700 }}>
          {favorites.length}
        </span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <SortHeader sort={sort} onSort={handleSort} />
          <tbody>
            {rows.map(row => (
              <FavRow
                key={row.key}
                row={row}
                isSelected={selectedTicker === row.ticker}
                onSelect={() => onSelectTicker?.(row.ticker)}
                onToggleFavorite={onToggleFavorite}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
