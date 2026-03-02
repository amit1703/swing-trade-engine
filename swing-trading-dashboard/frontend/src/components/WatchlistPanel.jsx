export default function WatchlistPanel({ items, selectedTicker, onSelectTicker, loading }) {
  // Filter: hide KDE-BRK items that are >1% above breakout (too extended)
  const filtered = items.filter(item =>
    !(item.pattern_type === 'KDE-BRK' && (item.distance_pct ?? 0) > 1.0)
  )

  // Split into approaching (NEAR BRK) and confirmed breaks
  const nearItems = filtered
    .filter(item => item.pattern_type === 'KDE' || item.pattern_type === 'TDL')
    .sort((a, b) => (a.distance_pct ?? 999) - (b.distance_pct ?? 999))

  const confirmedItems = filtered
    .filter(item => item.pattern_type === 'KDE-BRK' || item.pattern_type === 'TDL-BRK')
    .sort((a, b) => (a.distance_pct ?? 999) - (b.distance_pct ?? 999))

  const SectionHeader = ({ label, count }) => (
    <div className="px-2 py-1 flex items-center justify-between"
         style={{ borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)' }}>
      <span className="text-[8px] tracking-widest uppercase text-t-muted">{label}</span>
      <span className="badge bg-t-accentDim text-t-muted border border-t-border">{count}</span>
    </div>
  )

  const WatchRow = ({ item }) => {
    const isSelected = selectedTicker === item.ticker
    const isTdl = item.pattern_type === 'TDL'
    const isKdeBrk = item.pattern_type === 'KDE-BRK'
    const isTdlBrk = item.pattern_type === 'TDL-BRK'
    const isConfirmedBrk = isKdeBrk || isTdlBrk
    const hasRsBlueDot = !!item.rs_blue_dot

    const badgeStyle = isConfirmedBrk
      ? { background: 'rgba(0,200,122,0.18)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }
      : isTdl
      ? { background: 'rgba(255,255,255,0.08)', color: '#FFF', border: '1px solid rgba(255,255,255,0.25)' }
      : { background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)' }

    const distLabel = isConfirmedBrk
      ? `▲ ${item.distance_pct?.toFixed(1)}%`
      : `${item.distance_pct?.toFixed(1)}%`

    const distColor = isConfirmedBrk
      ? 'var(--go)'
      : item.distance_pct < 0.8 ? 'var(--go)' : 'var(--accent)'

    return (
      <div
        onClick={() => onSelectTicker(item.ticker)}
        className="flex items-center justify-between px-2 py-2 cursor-pointer"
        style={{
          borderLeft: isSelected ? '2px solid var(--accent)' : isConfirmedBrk ? '2px solid rgba(0,200,122,0.5)' : '2px solid transparent',
          background: isSelected ? 'rgba(245,166,35,0.06)' : isConfirmedBrk ? 'rgba(0,200,122,0.04)' : 'transparent',
          borderBottom: '1px solid var(--border)',
          transition: 'background 0.1s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.03)'}
        onMouseLeave={e => e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.06)' : isConfirmedBrk ? 'rgba(0,200,122,0.04)' : 'transparent'}
      >
        <div className="flex items-center gap-1">
          <span className="font-600 text-[10px] tracking-wide"
                style={{ color: isSelected ? 'var(--accent)' : isConfirmedBrk ? 'var(--go)' : 'var(--text)' }}>
            {item.ticker}
          </span>
          {hasRsBlueDot && (
            <span style={{ color: 'var(--purple)', fontSize: '8px' }}
                  aria-label="RS Blue Dot">⭐</span>
          )}
          <a
            href={`https://www.tradingview.com/chart/?symbol=${item.ticker}&interval=D`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            title="Open in TradingView"
            style={{
              fontSize: 7,
              padding: '1px 3px',
              border: '1px solid rgba(245,166,35,0.3)',
              color: 'rgba(245,166,35,0.55)',
              borderRadius: 2,
              fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: 700,
              letterSpacing: '0.05em',
              textDecoration: 'none',
              userSelect: 'none',
              flexShrink: 0,
            }}
          >
            TV
          </a>
        </div>

        <div className="flex items-center gap-1">
          <span className="font-mono text-[9px] tabular-nums" style={{ color: distColor }}>
            {distLabel}
          </span>
          <span className="badge text-[7px]" style={badgeStyle}>
            {item.pattern_type}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-shrink-0 overflow-y-auto border-r border-t-border"
         style={{ width: 190, background: 'var(--panel)' }}>

      {/* Header */}
      <div className="section-label">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-t-accent" />
        WATCHLIST
        <span className="badge bg-t-accentDim text-t-accent border border-t-accent/30 ml-auto">
          {filtered.length}
        </span>
      </div>

      {loading ? (
        <div className="p-2 flex flex-col gap-1">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="shimmer-row" style={{ opacity: 1 - i * 0.25 }} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-5 text-center text-t-muted text-[9px] tracking-widest uppercase">
          None
        </div>
      ) : (
        <div className="flex flex-col gap-0">
          {/* NEAR BRK section */}
          {nearItems.length > 0 && (
            <>
              <SectionHeader label="Near BRK" count={nearItems.length} />
              {nearItems.map(item => <WatchRow key={item.ticker} item={item} />)}
            </>
          )}

          {/* CONFIRMED section */}
          {confirmedItems.length > 0 && (
            <>
              <SectionHeader label="Confirmed" count={confirmedItems.length} />
              {confirmedItems.map(item => <WatchRow key={item.ticker} item={item} />)}
            </>
          )}
        </div>
      )}
    </div>
  )
}
