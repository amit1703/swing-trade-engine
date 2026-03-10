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
      <span style={{ fontSize: 10, color: 'var(--muted)', letterSpacing: '0.08em', fontWeight: 600 }}>FILTER</span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>Score ≥</span>
        <input
          type="number" min={0} max={100} step={5}
          value={minScore}
          onChange={e => update('minScore', Number(e.target.value))}
          style={{ ...inputStyle, width: 50, textAlign: 'center' }}
        />
      </div>

      <div style={{ width: 1, height: 16, background: 'var(--border)' }} />

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

      <div style={{ width: 1, height: 16, background: 'var(--border)' }} />

      <input
        value={searchQuery}
        onChange={e => update('searchQuery', e.target.value.toUpperCase())}
        placeholder="TICKER..."
        style={{ ...inputStyle, width: 80 }}
      />

      <div style={{ flex: 1 }} />

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
