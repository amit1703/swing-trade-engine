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
