export default function WatchlistPanel({ items, selectedTicker, onSelectTicker, loading }) {
  return (
    <div className="flex flex-col flex-shrink-0 overflow-y-auto border-r border-t-border"
         style={{ width: 190, background: 'var(--panel)' }}>

      {/* Header */}
      <div className="section-label">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-t-accent" />
        WATCHLIST
        <span className="badge bg-t-accentDim text-t-accent border border-t-accent/30 ml-auto">
          {items.length}
        </span>
      </div>
      <div className="px-2 pb-1 text-[8px] text-t-muted tracking-widest uppercase">
        NEAR BRK + CONFIRMED
      </div>

      {loading ? (
        <div className="p-2 flex flex-col gap-1">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="shimmer-row" style={{ opacity: 1 - i * 0.25 }} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="py-5 text-center text-t-muted text-[9px] tracking-widest uppercase">
          None <span className="terminal-cursor" />
        </div>
      ) : (
        <div className="flex flex-col gap-0">
          {items.map((item) => {
            const isSelected = selectedTicker === item.ticker
            const isTdl = item.pattern_type === 'TDL'
            const isKdeBrk = item.pattern_type === 'KDE-BRK'
            const isTdlBrk = item.pattern_type === 'TDL-BRK'
            const isConfirmedBrk = isKdeBrk || isTdlBrk
            const hasRsBlueDot = !!item.rs_blue_dot

            // Badge style: green for confirmed breaks, white for TDL approach, cyan for KDE approach
            const badgeStyle = isConfirmedBrk
              ? { background: 'rgba(0,200,122,0.18)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }
              : isTdl
              ? { background: 'rgba(255,255,255,0.08)', color: '#FFF', border: '1px solid rgba(255,255,255,0.25)' }
              : { background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)' }

            // Distance label: "▲ 1.2%" for confirmed breaks, "1.2%" for approaching
            const distLabel = isConfirmedBrk
              ? `▲ ${item.distance_pct?.toFixed(1)}%`
              : `${item.distance_pct?.toFixed(1)}%`

            // Distance color: green for confirmed breaks; green/amber for approaching
            const distColor = isConfirmedBrk
              ? 'var(--go)'
              : item.distance_pct < 0.8 ? 'var(--go)' : 'var(--accent)'

            return (
              <div
                key={item.ticker}
                onClick={() => onSelectTicker(item.ticker)}
                className="flex items-center justify-between px-2 py-1.5 cursor-pointer"
                style={{
                  borderLeft: isSelected ? '2px solid var(--accent)' : isConfirmedBrk ? '2px solid rgba(0,200,122,0.5)' : '2px solid transparent',
                  background: isSelected ? 'rgba(245,166,35,0.06)' : isConfirmedBrk ? 'rgba(0,200,122,0.04)' : 'transparent',
                  borderBottom: '1px solid var(--border)',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.03)'}
                onMouseLeave={e => e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.06)' : isConfirmedBrk ? 'rgba(0,200,122,0.04)' : 'transparent'}
              >
                {/* Ticker with RS Blue Dot indicator */}
                <div className="flex items-center gap-1">
                  <span className="font-600 text-[10px] tracking-wide"
                        style={{ color: isSelected ? 'var(--accent)' : isConfirmedBrk ? 'var(--go)' : 'var(--text)' }}>
                    {item.ticker}
                  </span>
                  {hasRsBlueDot && (
                    <span
                      style={{ color: 'var(--blue)', fontSize: '8px' }}
                      aria-label="RS Blue Dot - institutional accumulation signal">
                      ⭐
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  {/* Distance / breakout % */}
                  <span className="font-mono text-[9px] tabular-nums"
                        style={{ color: distColor }}>
                    {distLabel}
                  </span>

                  {/* Pattern badge */}
                  <span className="badge text-[7px]" style={badgeStyle}>
                    {item.pattern_type}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
