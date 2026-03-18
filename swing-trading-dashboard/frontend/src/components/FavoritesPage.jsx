import { Heart } from 'lucide-react'

const SETUP_TYPE_LABEL = {
  VCP: 'VCP', PULLBACK: 'PB', BASE: 'BASE',
  RES_BREAKOUT: 'BRK', HTF: 'HTF', LCE: 'LCE',
}
const TYPE_COLOR = {
  VCP: '#F5A623', PULLBACK: '#00C8FF', BASE: '#9B6EFF',
  RES_BREAKOUT: '#00c87a', HTF: '#FF6EC7', LCE: '#9B6EFF',
}

export default function FavoritesPage({ favorites, onToggleFavorite, allSetups, watchlistItems, selectedTicker, onSelectTicker, livePrices = {} }) {
  if (favorites.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', gap: 12 }}>
        <Heart size={32} strokeWidth={1.5} style={{ opacity: 0.3 }} />
        <div style={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
          No favorites yet
        </div>
        <div style={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: 9, opacity: 0.5, textAlign: 'center', maxWidth: 280, lineHeight: 1.6 }}>
          Star any ticker in the scanner or watchlist to add it here
        </div>
      </div>
    )
  }

  // Build a map: ticker → { setups: [], watchlist: [] }
  const setupsByTicker = {}
  for (const s of allSetups) {
    if (!setupsByTicker[s.ticker]) setupsByTicker[s.ticker] = []
    setupsByTicker[s.ticker].push(s)
  }
  const watchlistByTicker = {}
  for (const w of watchlistItems) {
    watchlistByTicker[w.ticker] = w
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', background: 'var(--panel)' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Heart size={14} strokeWidth={1.75} style={{ color: 'var(--accent)' }} />
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
            textTransform: 'uppercase', color: 'var(--muted)',
            fontFamily: '"IBM Plex Mono", monospace',
          }}>
            Favorites
          </span>
        </div>
        <span style={{
          fontSize: 9, padding: '1px 7px', borderRadius: 4,
          background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
          color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
        }}>
          {favorites.length}
        </span>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {favorites.map(ticker => {
          const setups = setupsByTicker[ticker] ?? []
          const wl = watchlistByTicker[ticker] ?? null
          const isSelected = selectedTicker === ticker
          const livePrice = livePrices[ticker]

          return (
            <div
              key={ticker}
              onClick={() => onSelectTicker(ticker)}
              style={{
                borderBottom: '1px solid var(--border)',
                borderLeft: isSelected ? '3px solid var(--accent)' : '3px solid transparent',
                background: isSelected ? 'rgba(245,166,35,0.05)' : 'transparent',
                cursor: 'pointer',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
              onMouseLeave={e => { e.currentTarget.style.background = isSelected ? 'rgba(245,166,35,0.05)' : 'transparent' }}
            >
              {/* Main row */}
              <div style={{ display: 'flex', alignItems: 'center', padding: '8px 12px', gap: 8 }}>
                {/* Star */}
                <button
                  onClick={e => { e.stopPropagation(); onToggleFavorite(ticker) }}
                  title="Remove from favorites"
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    padding: '1px 3px', color: 'var(--accent)', fontSize: 12, lineHeight: 1, flexShrink: 0,
                  }}
                >
                  ★
                </button>

                {/* Ticker */}
                <span style={{
                  fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
                  fontSize: 12, color: isSelected ? 'var(--accent)' : 'var(--text)',
                  letterSpacing: '0.03em', flex: '0 0 60px',
                }}>
                  {ticker}
                </span>

                {/* Live price */}
                {livePrice ? (
                  <span style={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: 10, color: 'var(--text)', flex: '0 0 60px' }}>
                    ${livePrice.toFixed(2)}
                  </span>
                ) : (
                  <span style={{ flex: '0 0 60px' }} />
                )}

                {/* Setup type badges */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flex: 1, flexWrap: 'wrap' }}>
                  {setups.map((s, i) => {
                    const key = (s.setup_type ?? '').toUpperCase()
                    const label = SETUP_TYPE_LABEL[key] ?? key
                    const clr = TYPE_COLOR[key] ?? 'var(--muted)'
                    const sc = typeof s.setup_score === 'number' ? Math.round(s.setup_score) : null
                    return (
                      <span key={i} style={{
                        display: 'inline-flex', alignItems: 'center', gap: 3,
                        padding: '1px 6px', borderRadius: 4, fontSize: 8, fontWeight: 700,
                        letterSpacing: '0.06em',
                        background: `${clr}18`, color: clr, border: `1px solid ${clr}30`,
                        fontFamily: '"IBM Plex Mono", monospace',
                      }}>
                        {label}
                        {sc !== null && <span style={{ opacity: 0.7 }}>{sc}</span>}
                      </span>
                    )
                  })}
                  {wl && (
                    <span style={{
                      padding: '1px 6px', borderRadius: 4, fontSize: 8, fontWeight: 700,
                      letterSpacing: '0.06em',
                      background: wl.watchlist_source === 'RES_BREAKOUT' ? 'rgba(0,200,122,0.10)' : 'rgba(100,180,255,0.10)',
                      color: wl.watchlist_source === 'RES_BREAKOUT' ? 'var(--go)' : '#64b4ff',
                      border: wl.watchlist_source === 'RES_BREAKOUT' ? '1px solid rgba(0,200,122,0.30)' : '1px solid rgba(100,180,255,0.30)',
                      fontFamily: '"IBM Plex Mono", monospace',
                    }}>
                      {wl.watchlist_source === 'RES_BREAKOUT' ? 'WL-BRK' : 'WL-PB'}
                    </span>
                  )}
                  {setups.length === 0 && !wl && (
                    <span style={{ color: 'var(--muted)', fontSize: 8, fontFamily: '"IBM Plex Mono", monospace' }}>not in current scan</span>
                  )}
                </div>

                {/* TV link */}
                <a
                  href={`https://www.tradingview.com/chart/?symbol=${ticker}&interval=D`}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={e => e.stopPropagation()}
                  style={{
                    fontSize: 8, padding: '2px 4px', borderRadius: 3,
                    border: '1px solid rgba(245,166,35,0.25)',
                    color: 'rgba(245,166,35,0.5)',
                    fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
                    textDecoration: 'none', flexShrink: 0,
                  }}
                >
                  TV
                </a>
              </div>

              {/* Setup detail sub-rows */}
              {setups.map((s, i) => {
                const key = (s.setup_type ?? '').toUpperCase()
                const clr = TYPE_COLOR[key] ?? 'var(--muted)'
                const dist = livePrice && s.entry > 0 ? ((livePrice - s.entry) / s.entry) * 100 : null
                return (
                  <div key={i} style={{
                    display: 'flex', gap: 12,
                    padding: '2px 12px 6px 36px',
                    fontFamily: '"IBM Plex Mono", monospace', fontSize: 9,
                    color: 'var(--muted)', borderLeft: `2px solid ${clr}20`, marginLeft: 14,
                  }}>
                    {s.entry > 0 && <span>E ${s.entry.toFixed(2)}</span>}
                    {s.stop_loss > 0 && <span style={{ color: 'rgba(255,82,82,0.7)' }}>SL ${s.stop_loss.toFixed(2)}</span>}
                    {s.rr > 0 && <span style={{ color: s.rr >= 2 ? 'var(--go)' : 'var(--muted)' }}>R:R {Number(s.rr).toFixed(1)}</span>}
                    {dist !== null && <span style={{ color: dist >= 0 ? 'var(--go)' : dist > -3 ? 'var(--accent)' : 'var(--muted)' }}>
                      {dist >= 0 ? `▲${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`}
                    </span>}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}
