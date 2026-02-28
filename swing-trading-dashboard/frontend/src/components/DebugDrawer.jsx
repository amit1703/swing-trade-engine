import { useEffect } from 'react'

const GO    = 'var(--go)'
const HALT  = 'var(--halt)'
const MUTED = 'var(--muted)'
const TEXT  = 'var(--text)'
const ACC   = 'var(--accent)'

function EngRow({ label, data }) {
  if (!data) return null
  const ok = data.triggered
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '8px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: ok ? 4 : 0 }}>
        <span style={{
          fontSize: 8,
          fontWeight: 700,
          padding: '2px 5px',
          background: ok ? 'rgba(0,200,122,0.15)' : 'rgba(255,45,85,0.12)',
          color: ok ? GO : HALT,
          border: `1px solid ${ok ? 'rgba(0,200,122,0.4)' : 'rgba(255,45,85,0.35)'}`,
          fontFamily: 'IBM Plex Mono, monospace',
          letterSpacing: '0.08em',
        }}>
          {ok ? '✓ PASS' : '✗ SKIP'}
        </span>
        <span style={{ fontSize: 10, color: TEXT, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600 }}>
          {label}
        </span>
        {data.result && (
          <span style={{ fontSize: 9, color: ACC, fontFamily: 'IBM Plex Mono, monospace' }}>
            → {data.result}
          </span>
        )}
      </div>
      {ok && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', paddingLeft: 4 }}>
          {Object.entries(data)
            .filter(([k]) => !['triggered', 'result', 'rejection'].includes(k))
            .map(([k, v]) => (
              <span key={k} style={{ fontSize: 8, color: MUTED, fontFamily: 'IBM Plex Mono, monospace' }}>
                {k}: <span style={{ color: TEXT }}>{String(v)}</span>
              </span>
            ))
          }
        </div>
      )}
    </div>
  )
}

function IndRow({ label, value, highlight }) {
  if (value == null) return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
      <span style={{ fontSize: 8, color: MUTED, fontFamily: 'IBM Plex Mono, monospace' }}>{label}</span>
      <span style={{ fontSize: 9, color: highlight || TEXT, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600 }}>
        {typeof value === 'boolean' ? (value ? 'YES' : 'NO') : value}
      </span>
    </div>
  )
}

export default function DebugDrawer({ ticker, data, loading, onClose }) {
  // Escape key closes
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, zIndex: 40, background: 'rgba(0,0,0,0.4)' }}
      />

      {/* Drawer */}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 340, zIndex: 50,
        background: 'var(--surface)', borderLeft: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        boxShadow: '-8px 0 32px rgba(0,0,0,0.6)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: '1px solid var(--border)', flexShrink: 0,
        }}>
          <div>
            <span style={{
              fontSize: 9, color: ACC, letterSpacing: '0.15em', textTransform: 'uppercase',
              fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700,
            }}>
              ⚙ ENGINE DEBUG
            </span>
            <span style={{ marginLeft: 8, fontSize: 13, color: '#fff', fontWeight: 700, letterSpacing: 1 }}>
              {ticker}
            </span>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: '0 4px' }}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
          {loading && (
            <div style={{ color: MUTED, fontSize: 10, fontFamily: 'IBM Plex Mono, monospace', textAlign: 'center', marginTop: 40 }}>
              Loading…
            </div>
          )}

          {!loading && data && (
            <>
              {/* Regime */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 8, color: MUTED, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 4 }}>
                  Regime
                </div>
                <IndRow label="Market"  value={data.regime?.is_bullish ? 'GO ✓' : 'HALT ✗'} highlight={data.regime?.is_bullish ? GO : HALT} />
                <IndRow label="SPY"     value={data.regime?.spy_close?.toFixed(2)} />
                <IndRow label="EMA 20"  value={data.regime?.spy_20ema?.toFixed(2)} />
              </div>

              {/* RS */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 8, color: MUTED, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 4 }}>
                  Relative Strength
                </div>
                <IndRow label="RS Ratio"   value={data.rs?.ratio?.toFixed(3)}  highlight={data.rs?.ratio > 0 ? GO : HALT} />
                <IndRow label="RS Score"   value={data.rs?.rs_score}            highlight={data.rs?.rs_score >= 70 ? GO : data.rs?.rs_score >= 50 ? ACC : HALT} />
                <IndRow label="Blue Dot"   value={data.rs?.blue_dot}            highlight={data.rs?.blue_dot ? '#9b6eff' : MUTED} />
              </div>

              {/* Indicators */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 8, color: MUTED, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 4 }}>
                  Indicators
                </div>
                <IndRow label="Close"       value={data.indicators?.close?.toFixed(2)} highlight={TEXT} />
                <IndRow label="EMA 8"       value={data.indicators?.ema8?.toFixed(2)} />
                <IndRow label="EMA 20"      value={data.indicators?.ema20?.toFixed(2)} />
                <IndRow label="SMA 50"      value={data.indicators?.sma50?.toFixed(2)} />
                <IndRow label="CCI"         value={data.indicators?.cci?.toFixed(1)} highlight={data.indicators?.cci > 0 ? GO : HALT} />
                <IndRow label="Above EMA20" value={data.indicators?.above_ema20} highlight={data.indicators?.above_ema20 ? GO : HALT} />
                <IndRow label="Above SMA50" value={data.indicators?.above_sma50} highlight={data.indicators?.above_sma50 ? GO : HALT} />
              </div>

              {/* S/R Zones */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 8, color: MUTED, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 4 }}>
                  KDE Zones ({data.zones?.length ?? 0})
                </div>
                {(data.zones || []).map((z, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                    <span style={{ fontSize: 8, color: z.zone_type === 'RESISTANCE' ? HALT : GO, fontFamily: 'IBM Plex Mono, monospace' }}>
                      {z.zone_type?.[0] ?? '?'}
                    </span>
                    <span style={{ fontSize: 9, color: z.zone_type === 'RESISTANCE' ? HALT : GO, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600 }}>
                      {z.zone_lower?.toFixed(2)} – {z.zone_upper?.toFixed(2)}
                    </span>
                  </div>
                ))}
                {(!data.zones || data.zones.length === 0) && (
                  <span style={{ fontSize: 8, color: MUTED }}>No zones</span>
                )}
              </div>

              {/* Engine results */}
              <div style={{ fontSize: 8, color: MUTED, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 4 }}>
                Engine Results
              </div>
              <EngRow label="Engine 2 — VCP"        data={data.engine2} />
              <EngRow label="Engine 3 — Pullback"   data={data.engine3} />
              <EngRow label="Engine 5 — Base"       data={data.engine5} />
              <EngRow label="Engine 6 — ResBreak"   data={data.engine6} />
            </>
          )}
        </div>
      </div>
    </>
  )
}
