import { Target, ChevronRight } from 'lucide-react'

function SignalRow({ label, value, color }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '6px 0',
      borderBottom: '1px solid rgba(26,37,53,0.5)',
    }}>
      <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: '"Inter", sans-serif' }}>
        {label}
      </span>
      <span style={{
        fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
        color: color ?? 'var(--text)',
      }}>
        {value}
      </span>
    </div>
  )
}

function ScoreBadge({ score }) {
  const s     = Math.round(score ?? 0)
  const color = s >= 80 ? 'var(--go)' : s >= 60 ? 'var(--accent)' : 'var(--muted)'
  const pct   = s / 100

  return (
    <div style={{ position: 'relative', width: 64, height: 64, flexShrink: 0 }}>
      <div style={{
        width: 64, height: 64, borderRadius: '50%',
        background: `conic-gradient(${color} ${pct * 360}deg, var(--border) 0deg)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: '50%',
          background: 'var(--card)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{
            fontFamily: '"Barlow Condensed", sans-serif',
            fontSize: 18, fontWeight: 700, color, lineHeight: 1,
          }}>
            {s}
          </span>
        </div>
      </div>
    </div>
  )
}

function RankBadge({ rank }) {
  const r = Math.round(rank ?? 0)
  const color = r >= 85 ? 'var(--go)' : r >= 70 ? 'var(--accent)' : 'var(--halt)'
  return (
    <span style={{
      padding: '2px 7px', borderRadius: 4,
      fontFamily: '"IBM Plex Mono", monospace', fontSize: 10, fontWeight: 700,
      background: `${color}22`, color, border: `1px solid ${color}55`,
    }}>
      RS {r}
    </span>
  )
}

function AlignmentChip({ alignment }) {
  const map = { STRONG: 'var(--go)', MODERATE: 'var(--accent)', WEAK: 'var(--halt)' }
  const c = map[alignment] ?? 'var(--muted)'
  return (
    <span style={{
      padding: '2px 7px', borderRadius: 4, fontSize: 9,
      fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
      background: `${c}22`, color: c, border: `1px solid ${c}44`,
      letterSpacing: '0.06em',
    }}>
      {alignment ?? '—'}
    </span>
  )
}

function V5AnalysisSection({ analysis }) {
  if (!analysis) return null

  const {
    rs_rank, regime_alignment, entry_quality,
    price_risk_pct, risk_level, reject_reasons,
  } = analysis

  const safeRejectReasons = Array.isArray(reject_reasons) ? reject_reasons : []
  const riskColor = { LOW: 'var(--go)', MODERATE: 'var(--accent)', HIGH: 'var(--halt)' }[risk_level] ?? 'var(--muted)'

  return (
    <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 8 }}>
        V5 ANALYSIS
      </div>

      {/* RS Rank + Regime + Entry Quality chips */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        {rs_rank != null && <RankBadge rank={rs_rank} />}
        {regime_alignment && <AlignmentChip alignment={regime_alignment} />}
        {entry_quality && (
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
            {entry_quality}
          </span>
        )}
      </div>

      {/* Price risk */}
      {price_risk_pct != null && (
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 10 }}>
          <span style={{ color: 'var(--muted)' }}>Price Risk</span>
          <span style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, color: riskColor }}>
            {price_risk_pct.toFixed(1)}% — {risk_level}
          </span>
        </div>
      )}

      {/* Reject reasons */}
      {safeRejectReasons.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {safeRejectReasons.map((reason, i) => (
            <div key={i} style={{
              fontSize: 9, lineHeight: 1.5, color: 'var(--halt)',
              fontFamily: '"Inter", sans-serif',
              borderLeft: '2px solid var(--halt)',
              paddingLeft: 6, marginBottom: 3,
            }}>
              {reason}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function StockIntelPanel({ setup, livePrices, analysis, analysisLoading }) {
  if (!setup) {
    return (
      <div style={{
        width: 280, flexShrink: 0,
        background: 'var(--card)',
        border: '1px solid var(--card-border)',
        borderRadius: 12,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 8, color: 'var(--muted)',
        padding: 20,
      }}>
        <Target size={28} strokeWidth={1} color="var(--border-light)" />
        <span style={{ fontSize: 11, textAlign: 'center', lineHeight: 1.5 }}>
          Select a stock from the<br />scanner to view signals
        </span>
      </div>
    )
  }

  const livePrice    = livePrices?.[setup.ticker]
  const dist         = (livePrice && setup.entry > 0)
    ? ((livePrice - setup.entry) / setup.entry) * 100
    : null
  const isAboveEntry = dist !== null && dist >= 0

  const risk = setup.entry > 0 && setup.stop_loss > 0
    ? ((setup.entry - setup.stop_loss) / setup.entry * 100).toFixed(1)
    : null

  const rr = setup.rr ? Number(setup.rr).toFixed(2) : null

  return (
    <div style={{
      width: 280, flexShrink: 0,
      background: 'var(--card)',
      border: '1px solid var(--card-border)',
      borderRadius: 12,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid var(--card-border)',
        background: 'rgba(255,255,255,0.02)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div>
            <div style={{
              fontFamily: '"Barlow Condensed", sans-serif',
              fontSize: 24, fontWeight: 700, lineHeight: 1,
              color: 'var(--text)', letterSpacing: '-0.01em',
            }}>
              {setup.ticker}
            </div>
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3, fontFamily: '"IBM Plex Mono", monospace' }}>
              {setup.setup_type ?? '—'}
            </div>
          </div>
          <ScoreBadge score={setup.setup_score} />
        </div>

        {livePrice && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontFamily: '"IBM Plex Mono", monospace', fontSize: 16, fontWeight: 700,
              color: isAboveEntry ? 'var(--go)' : dist !== null && dist > -3 ? 'var(--accent)' : 'var(--text)',
            }}>
              ${livePrice.toFixed(2)}
            </span>
            {dist !== null && (
              <span style={{
                fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700,
                color: isAboveEntry ? 'var(--go)' : 'var(--muted)',
              }}>
                {isAboveEntry ? `▲${Math.abs(dist).toFixed(1)}%` : `${Math.abs(dist).toFixed(1)}%↓`}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Signals */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--card-border)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>SIGNALS</div>
        <SignalRow
          label="Relative Strength"
          value={setup.rs_score != null ? `RS${setup.rs_score >= 0 ? '+' : ''}${Math.round(setup.rs_score * 100)}` : '—'}
          color={setup.rs_score > 0.05 ? 'var(--go)' : 'var(--muted)'}
        />
        <SignalRow
          label="Volume Surge"
          value={setup.is_vol_surge ? 'YES' : setup.vol_ratio ? `×${Number(setup.vol_ratio).toFixed(1)}` : '—'}
          color={setup.is_vol_surge ? 'var(--go)' : undefined}
        />
        <SignalRow
          label="RS Blue Dot"
          value={setup.rs_blue_dot ? 'YES — 52W HIGH' : 'NO'}
          color={setup.rs_blue_dot ? 'var(--blue)' : 'var(--muted)'}
        />
        <SignalRow
          label="Distance to Entry"
          value={dist !== null ? `${Math.abs(dist).toFixed(1)}%${isAboveEntry ? ' above' : ' below'}` : '—'}
          color={dist !== null && dist > -3 && !isAboveEntry ? 'var(--accent)' : undefined}
        />
      </div>

      {/* Trade Plan */}
      <div style={{ padding: '10px 16px', flex: 1, overflow: 'auto' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>TRADE PLAN</div>
        {[
          { label: 'Entry',  value: setup.entry       ? `$${setup.entry.toFixed(2)}`       : '—', color: 'var(--text)'   },
          { label: 'Stop',   value: setup.stop_loss   ? `$${setup.stop_loss.toFixed(2)}`   : '—', color: 'var(--halt)'   },
          { label: 'Target', value: setup.take_profit ? `$${setup.take_profit.toFixed(2)}` : '—', color: 'var(--go)'     },
          { label: 'Risk',   value: risk ? `${risk}%` : '—',                                       color: 'var(--accent)' },
          { label: 'R:R',    value: rr ?? '—',
            color: rr && Number(rr) >= 2 ? 'var(--go)' : 'var(--text)' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '5px 0', borderBottom: '1px solid rgba(26,37,53,0.4)',
          }}>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</span>
            <span style={{ fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, color }}>
              {value}
            </span>
          </div>
        ))}
      </div>

      {/* Analysis section */}
      {analysis && (
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)' }}>AI VERDICT</span>
            <span style={{
              padding: '3px 8px', borderRadius: 5,
              fontSize: 9, fontWeight: 700, letterSpacing: '0.06em',
              fontFamily: '"IBM Plex Mono", monospace',
              background: analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.15)'
                        : analysis.verdict_color === 'accent' ? 'rgba(245,166,35,0.15)'
                        : 'rgba(255,45,85,0.12)',
              color: analysis.verdict_color === 'go'     ? 'var(--go)'
                   : analysis.verdict_color === 'accent' ? 'var(--accent)'
                   : 'var(--halt)',
              border: `1px solid ${
                analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.35)'
              : analysis.verdict_color === 'accent' ? 'rgba(245,166,35,0.35)'
              : 'rgba(255,45,85,0.3)'}`,
            }}>
              {analysis.verdict}
            </span>
          </div>
          <p style={{ fontSize: 10, lineHeight: 1.6, color: 'var(--muted)', fontFamily: '"Inter", sans-serif', margin: 0 }}>
            {analysis.narrative}
          </p>
          <div style={{ marginTop: 6, fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
            Setup Quality: <span style={{ color: 'var(--text)' }}>{analysis.quality}</span>
          </div>
        </div>
      )}

      {analysisLoading && (
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
          <div className="shimmer-row" style={{ height: 50 }} />
        </div>
      )}

      {/* V5 Analysis section — hidden while loading to prevent stale-data bleed */}
      {!analysisLoading && analysis && <V5AnalysisSection analysis={analysis} />}

      {/* TradingView link */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${setup.ticker}&interval=D`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            padding: '7px', borderRadius: 8,
            background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)',
            color: 'var(--accent)', fontSize: 10, fontWeight: 700,
            fontFamily: '"IBM Plex Mono", monospace', textDecoration: 'none',
            letterSpacing: '0.06em',
          }}
        >
          OPEN IN TRADINGVIEW <ChevronRight size={10} />
        </a>
      </div>
    </div>
  )
}
