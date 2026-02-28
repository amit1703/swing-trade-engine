import { useState } from 'react'

export default function EngineHealthPanel({ stats }) {
  const [collapsed, setCollapsed] = useState(false)

  if (!stats || Object.keys(stats).length === 0) return null

  const fmt  = (n) => (n != null ? n : '—')
  const fmtS = (n) => (n != null ? `${n}s` : '—')

  const rows = [
    {
      label: 'E0 — Regime',
      value: stats.e0?.is_bullish != null
        ? `${stats.e0.is_bullish ? 'GO' : 'HALT'}  SPY ${fmt(stats.e0.spy_close)}`
        : '—',
      color: stats.e0?.is_bullish ? 'var(--go)' : stats.e0?.is_bullish === false ? 'var(--halt)' : 'var(--muted)',
    },
    {
      label: 'E1 — Zones',
      value: `${fmt(stats.e1?.zones_saved)} tickers`,
      color: 'var(--text)',
    },
    {
      label: 'E2 — VCP',
      value: `${fmt(stats.e2?.vcp)} VCP  /  ${fmt(stats.e2?.watchlist)} WL`,
      color: 'var(--blue, #4e9af1)',
    },
    {
      label: 'E3 — Pullback',
      value: `${fmt(stats.e3?.pullback)} strict  /  ${fmt(stats.e3?.relaxed)} rlx`,
      color: 'var(--accent)',
    },
    {
      label: 'E5 — Base',
      value: `C&H:${fmt(stats.e5?.cup_handle)}  FB:${fmt(stats.e5?.flat_base)}`,
      color: 'var(--go)',
    },
    {
      label: 'E6 — ResBreak',
      value: `${fmt(stats.e6?.res_breakout)} breaks`,
      color: 'var(--go)',
    },
  ]

  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '8px 12px', background: 'var(--panel)' }}>
      {/* Header row */}
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setCollapsed(v => !v)}
        style={{ marginBottom: collapsed ? 0 : 6 }}
      >
        <span style={{
          fontSize: 9,
          fontFamily: 'IBM Plex Mono, monospace',
          color: 'var(--accent)',
          letterSpacing: '0.15em',
          textTransform: 'uppercase',
          fontWeight: 700,
        }}>
          ⚙ ENGINE HEALTH
        </span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {stats.forced && (
            <span style={{ fontSize: 7, color: 'var(--accent)', border: '1px solid var(--accent)', padding: '1px 4px', letterSpacing: '0.1em', fontFamily: 'IBM Plex Mono, monospace' }}>
              FORCED
            </span>
          )}
          {stats.dry_run && (
            <span style={{ fontSize: 7, color: '#9b6eff', border: '1px solid #9b6eff', padding: '1px 4px', letterSpacing: '0.1em', fontFamily: 'IBM Plex Mono, monospace' }}>
              DRY
            </span>
          )}
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>
            {collapsed ? '▶' : '▼'}
          </span>
        </div>
      </div>

      {!collapsed && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {rows.map((r) => (
            <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{
                fontSize: 8,
                color: 'var(--muted)',
                fontFamily: 'IBM Plex Mono, monospace',
                letterSpacing: '0.05em',
                minWidth: 90,
              }}>
                {r.label}
              </span>
              <span style={{
                fontSize: 9,
                color: r.color,
                fontFamily: 'IBM Plex Mono, monospace',
                fontWeight: 600,
              }}>
                {r.value}
              </span>
            </div>
          ))}
          {/* Totals row */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 2,
            paddingTop: 4,
            borderTop: '1px solid var(--border)',
          }}>
            <span style={{ fontSize: 8, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>
              {fmt(stats.total_tickers)} tickers
            </span>
            <span style={{ fontSize: 8, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>
              {fmtS(stats.total_duration_s)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
