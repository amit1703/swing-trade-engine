import { useState } from 'react'

export default function WatchlistPanel({ items, selectedTicker, onSelectTicker, loading, favorites = [], onToggleFavorite }) {
  const [showAllBrk, setShowAllBrk] = useState(false)
  const [showAllPb,  setShowAllPb]  = useState(false)

  const brkItems = items
    .filter(item => item.watchlist_source === 'RES_BREAKOUT')

  const pbItems = items
    .filter(item => item.watchlist_source === 'PULLBACK')

  const visibleBrk = showAllBrk ? brkItems : brkItems.slice(0, 15)
  const visiblePb  = showAllPb  ? pbItems  : pbItems.slice(0, 15)

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

  const ShowMoreBtn = ({ allItems, visible, onToggle }) => {
    if (allItems.length <= 15) return null
    return (
      <button
        onClick={() => onToggle(v => !v)}
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
        {visible ? `▲ Show top 15` : `▼ Show all ${allItems.length}`}
      </button>
    )
  }

  const WatchRow = ({ item }) => {
    const isSelected  = selectedTicker === item.ticker
    const isBrk       = item.watchlist_source === 'RES_BREAKOUT'
    const hasBlueDot  = !!item.rs_blue_dot
    const isFavorited = favorites.includes(item.ticker)

    const dist      = item.distance_pct ?? 0
    const atrDist   = (item.atr > 0 && item.entry > 0)
      ? (dist / (item.atr / item.entry * 100))
      : null
    const distLabel = isBrk
      ? `${dist.toFixed(1)}%${atrDist !== null ? ` (${atrDist.toFixed(1)}atr)` : ''} away`
      : `${dist.toFixed(1)}%${atrDist !== null ? ` (${atrDist.toFixed(1)}atr)` : ''} to sup`
    const distColor = atrDist !== null
      ? (atrDist < 0.5 ? 'var(--go)' : atrDist < 1.5 ? 'var(--accent)' : 'var(--muted)')
      : (dist < 1.5 ? 'var(--go)' : dist < 3 ? 'var(--accent)' : 'var(--muted)')

    const sourceLabel = isBrk
      ? (item.zone_source ?? 'BRK').toUpperCase().slice(0, 6)
      : (item.support_source ?? 'SUP').replace('_', ' ').slice(0, 6)

    const badgeBg    = isBrk ? 'rgba(0,200,122,0.10)' : 'rgba(100,180,255,0.10)'
    const badgeBord  = isBrk ? 'rgba(0,200,122,0.30)' : 'rgba(100,180,255,0.30)'
    const badgeColor = isBrk ? 'var(--go)' : '#64b4ff'

    return (
      <div
        onClick={() => onSelectTicker(item.ticker)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid var(--border)',
          borderLeft: isSelected
            ? '3px solid var(--accent)'
            : isBrk
            ? '3px solid rgba(0,200,122,0.4)'
            : '3px solid rgba(100,180,255,0.4)',
          background: isSelected ? 'rgba(245,166,35,0.06)' : 'transparent',
          cursor: 'pointer',
          transition: 'background 0.1s',
          gap: 8,
        }}
        onMouseEnter={e => {
          if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.06)' : 'transparent'
        }}
      >
        {/* Left: ticker + blue dot */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
            <span style={{
              fontSize: 12, fontWeight: 700, letterSpacing: '0.03em',
              color: isSelected ? 'var(--accent)' : 'var(--text)',
              fontFamily: '"IBM Plex Mono", monospace',
            }}>
              {item.ticker}
            </span>
            {hasBlueDot && (
              <span style={{ color: 'var(--blue)', fontSize: 9 }}>●</span>
            )}
          </div>
          <span style={{
            fontSize: 9, color: distColor,
            fontFamily: '"IBM Plex Mono", monospace',
          }}>
            {distLabel}
          </span>
        </div>

        {/* Right: source badge + star + TV link */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{
            fontSize: 8, padding: '2px 5px', borderRadius: 4,
            fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
            letterSpacing: '0.04em',
            background: badgeBg, color: badgeColor, border: `1px solid ${badgeBord}`,
          }}>
            {sourceLabel}
          </span>
          <button
            onClick={e => { e.stopPropagation(); onToggleFavorite?.(item.ticker) }}
            title={isFavorited ? 'Remove from favorites' : 'Add to favorites'}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              padding: '1px 2px', fontSize: 11, lineHeight: 1,
              color: isFavorited ? 'var(--accent)' : 'var(--muted)',
              opacity: isFavorited ? 1 : 0.4,
              transition: 'color 0.15s, opacity 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--accent)' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = isFavorited ? '1' : '0.4'; e.currentTarget.style.color = isFavorited ? 'var(--accent)' : 'var(--muted)' }}
          >
            {isFavorited ? '★' : '☆'}
          </button>
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

  const totalCount = brkItems.length + pbItems.length

  return (
    <div className="flex flex-col h-full overflow-hidden bg-t-panel">

      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-t-border flex-shrink-0">
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
          {totalCount}
        </span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 12 }}>
            {[...Array(4)].map((_, i) => (
              <div key={i} style={{
                height: 48, borderRadius: 6,
                background: 'rgba(255,255,255,0.04)',
                opacity: 1 - i * 0.2,
              }} />
            ))}
          </div>
        ) : totalCount === 0 ? (
          <div className="py-8 px-4 text-center text-[10px] font-mono tracking-widest uppercase text-t-muted">
            No items — run a scan
          </div>
        ) : (
          <>
            {brkItems.length > 0 && (
              <>
                <SectionHeader label="Near Breakout" count={brkItems.length} />
                {visibleBrk.map(item => <WatchRow key={item.ticker} item={item} />)}
                <ShowMoreBtn allItems={brkItems} visible={showAllBrk} onToggle={setShowAllBrk} />
              </>
            )}
            {pbItems.length > 0 && (
              <>
                <SectionHeader label="Pullback Setup" count={pbItems.length} />
                {visiblePb.map(item => <WatchRow key={item.ticker} item={item} />)}
                <ShowMoreBtn allItems={pbItems} visible={showAllPb} onToggle={setShowAllPb} />
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
