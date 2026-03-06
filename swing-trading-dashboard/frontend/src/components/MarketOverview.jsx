/**
 * MarketOverview — Collapsible macro sentiment strip
 *
 * Collapsed (26px): toggle button + F&G score + SPY/QQQ badges inline
 * Expanded  (70px): F&G gauge row + news headlines row
 *
 * Fetches /api/market-overview on mount; auto-refreshes every 20 min.
 * Collapse state persisted in localStorage key "macro_panel_collapsed".
 */
import { useEffect, useRef, useState } from 'react'
import { fetchMarketOverview } from '../api.js'

const REFRESH_MS = 20 * 60 * 1000  // 20 minutes

// Fear & Greed colour scale
function fgColor(score) {
  if (score == null) return 'var(--muted)'
  if (score <= 24)   return 'var(--halt)'    // Extreme Fear
  if (score <= 44)   return '#f97316'        // Fear
  if (score <= 55)   return '#eab308'        // Neutral
  if (score <= 74)   return 'var(--go)'      // Greed
  return '#00C8FF'                           // Extreme Greed
}

function fmtPct(pct) {
  if (pct == null) return '—'
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

function fmtAge(min) {
  if (min == null || min < 0) return ''
  if (min < 60) return `${min}m`
  return `${Math.floor(min / 60)}h`
}

// Reusable index badge (SPY / QQQ)
function IndexBadge({ sym, info }) {
  const up  = info?.change_pct >= 0
  const nil = info == null
  return (
    <span style={{
      fontFamily: 'IBM Plex Mono, monospace',
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: '0.05em',
      padding: '1px 6px',
      background: nil ? 'rgba(255,255,255,0.04)' : up ? 'rgba(0,200,122,0.10)' : 'rgba(255,45,85,0.10)',
      border: `1px solid ${nil ? 'var(--border)' : up ? 'rgba(0,200,122,0.35)' : 'rgba(255,45,85,0.35)'}`,
      borderRadius: 2,
      color: nil ? 'var(--muted)' : up ? 'var(--go)' : 'var(--halt)',
      whiteSpace: 'nowrap',
    }}>
      {sym} {nil ? '—' : fmtPct(info.change_pct)}
    </span>
  )
}

// Shared toggle button (collapse / expand)
function ToggleBtn({ collapsed, onClick }) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? 'Expand macro overview' : 'Collapse macro overview'}
      style={{
        background: 'none',
        border: '1px solid var(--border-light)',
        color: 'var(--muted)',
        fontFamily: 'IBM Plex Mono, monospace',
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: '0.12em',
        padding: '1px 6px',
        cursor: 'pointer',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}
    >
      MACRO {collapsed ? '▸' : '▾'}
    </button>
  )
}

export default function MarketOverview() {
  const [data,      setData     ] = useState(null)
  const [loading,   setLoading  ] = useState(true)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('macro_panel_collapsed') === 'true'
  )
  const timerRef = useRef(null)

  const load = async () => {
    try {
      const d = await fetchMarketOverview()
      setData(d)
    } catch (err) {
      console.warn('[MarketOverview] fetch failed:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    timerRef.current = setInterval(load, REFRESH_MS)
    return () => clearInterval(timerRef.current)
  }, [])

  const toggle = () => setCollapsed(v => {
    const next = !v
    localStorage.setItem('macro_panel_collapsed', String(next))
    return next
  })

  const fg      = data?.fear_greed
  const spy     = data?.indices?.SPY
  const qqq     = data?.indices?.QQQ
  const news    = data?.news ?? []
  const fgScore = fg?.score ?? null
  const fgLabel = fg?.label ?? '—'
  const fgClr   = fgColor(fgScore)

  const panelBase = {
    flexShrink: 0,
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
  }

  // ── Collapsed strip ────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <div style={{ ...panelBase, height: 26, display: 'flex', alignItems: 'center', gap: 10, padding: '0 12px' }}>
        <ToggleBtn collapsed onClick={toggle} />

        {loading ? (
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>
            loading…
          </span>
        ) : (
          <>
            {fg && (
              <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 10, color: fgClr, fontWeight: 700, whiteSpace: 'nowrap' }}>
                F&G {fgScore?.toFixed(0)} <span style={{ fontWeight: 400, opacity: 0.75 }}>{fgLabel}</span>
              </span>
            )}
            <span style={{ color: 'var(--border)', fontSize: 12, lineHeight: 1 }}>│</span>
            <IndexBadge sym="SPY" info={spy} />
            <IndexBadge sym="QQQ" info={qqq} />
          </>
        )}
      </div>
    )
  }

  // ── Expanded panel ─────────────────────────────────────────────────────────
  return (
    <div style={panelBase}>

      {/* Row 1: toggle + F&G gauge + indices */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '5px 12px', borderBottom: '1px solid var(--border)', height: 42 }}>
        <ToggleBtn collapsed={false} onClick={toggle} />

        {loading ? (
          <div style={{ display: 'flex', gap: 8 }}>
            {[70, 50, 80].map((w, i) => (
              <div key={i} className="shimmer-row" style={{ width: w, height: 12, borderRadius: 2 }} />
            ))}
          </div>
        ) : (
          <>
            {/* F&G score + gauge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 8, letterSpacing: '0.15em', color: 'var(--muted)', textTransform: 'uppercase', fontFamily: 'IBM Plex Mono, monospace', whiteSpace: 'nowrap' }}>
                Fear &amp; Greed
              </span>
              {/* Gauge bar */}
              <div style={{ width: 64, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${fgScore ?? 0}%`, height: '100%', background: fgClr, borderRadius: 3, transition: 'width 0.6s ease' }} />
              </div>
              <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, fontWeight: 700, color: fgClr, lineHeight: 1, minWidth: 22, textAlign: 'right' }}>
                {fgScore != null ? fgScore.toFixed(0) : '—'}
              </span>
              <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 9, color: fgClr, opacity: 0.85, whiteSpace: 'nowrap' }}>
                {fgLabel}
              </span>
            </div>

            <span style={{ color: 'var(--border)', fontSize: 12, lineHeight: 1 }}>│</span>

            {/* Indices */}
            <div style={{ display: 'flex', gap: 5 }}>
              <IndexBadge sym="SPY" info={spy} />
              <IndexBadge sym="QQQ" info={qqq} />
            </div>

            {/* Cache age — shown only when data is stale (>2 min) */}
            {data?.cache_age_s > 120 && (
              <span style={{ fontSize: 8, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace', marginLeft: 'auto' }}>
                cached {Math.floor(data.cache_age_s / 60)}m ago
              </span>
            )}
          </>
        )}
      </div>

      {/* Row 2: news headlines */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '0 12px', height: 26, overflow: 'hidden' }}>
        {loading ? (
          <div className="shimmer-row" style={{ width: '55%', height: 9 }} />
        ) : news.length === 0 ? (
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>No headlines</span>
        ) : (
          <div style={{ display: 'flex', gap: 18, alignItems: 'center', overflow: 'hidden' }}>
            {news.slice(0, 4).map((item, i) => (
              <a
                key={i}
                href={item.url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'flex', alignItems: 'center', gap: 4,
                  textDecoration: 'none', whiteSpace: 'nowrap',
                  overflow: 'hidden', flexShrink: i === 0 ? 0 : 1,
                  maxWidth: i === 0 ? 360 : 280,
                }}
              >
                <span style={{ color: 'var(--accent)', fontSize: 7, fontWeight: 700, flexShrink: 0 }}>▸</span>
                <span style={{ fontSize: 9, color: 'var(--text)', fontFamily: 'IBM Plex Mono, monospace', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {item.title}
                </span>
                {item.age_min != null && (
                  <span style={{ fontSize: 7, color: 'var(--muted)', flexShrink: 0, marginLeft: 2 }}>
                    · {fmtAge(item.age_min)}
                  </span>
                )}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
