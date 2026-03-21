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
  // Synthesize a display object from analysis when setup (scan result) is not available.
  // The `setup` prop parameter is NOT renamed — it stays as-is so the ?? expression can read it.
  const displaySetup = setup ?? (analysis ? {
    ticker:       analysis.ticker,
    setup_score:  analysis.score,
    setup_type:   analysis.setup_type ?? analysis.detected_setup ?? null,
    entry:        analysis.entry        ?? 0,
    stop_loss:    analysis.stop_loss    ?? 0,
    take_profit:  analysis.take_profit  ?? 0,
    rr:           analysis.rr           ?? 0,
    rs_score:     analysis.signals?.rs_score  ?? null,
    vol_ratio:    analysis.signals?.vol_ratio ?? null,
    is_vol_surge: (analysis.signals?.vol_ratio ?? 0) > 1.5,
    rs_blue_dot:  false,
  } : null)

  // Replace the old `if (!setup)` block entirely with this:
  if (!displaySetup) {
    if (analysisLoading) {
      return (
        <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col p-4 gap-3">
          <div className="shimmer-row" style={{ height: 64 }} />
          <div className="shimmer-row" style={{ height: 40 }} />
          <div className="shimmer-row" style={{ height: 80 }} />
        </div>
      )
    }
    return (
      <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col items-center justify-center gap-2 text-t-muted p-5">
        <Target size={28} strokeWidth={1} color="var(--border-light)" />
        <span style={{ fontSize: 11, textAlign: 'center', lineHeight: 1.5 }}>
          Select a stock to view signals
        </span>
      </div>
    )
  }

  // All references below use `displaySetup` (not `setup`)
  const livePrice    = livePrices?.[displaySetup.ticker]
  const dist         = (livePrice && displaySetup.entry > 0)
    ? ((livePrice - displaySetup.entry) / displaySetup.entry) * 100
    : null
  const isAboveEntry = dist !== null && dist >= 0

  const risk = displaySetup.entry > 0 && displaySetup.stop_loss > 0
    ? ((displaySetup.entry - displaySetup.stop_loss) / displaySetup.entry * 100).toFixed(1)
    : null

  const rr = displaySetup.rr ? Number(displaySetup.rr).toFixed(2) : null

  return (
    <div className="w-[320px] flex-shrink-0 bg-t-card border border-t-cardBorder rounded-xl flex flex-col overflow-y-auto overflow-x-hidden">
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
              {displaySetup.ticker}
            </div>
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3, fontFamily: '"IBM Plex Mono", monospace' }}>
              {displaySetup.setup_type ?? '—'}
            </div>
          </div>
          <ScoreBadge score={displaySetup.setup_score} />
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
          value={displaySetup.rs_score != null ? `RS${displaySetup.rs_score >= 0 ? '+' : ''}${Math.round(displaySetup.rs_score * 100)}` : '—'}
          color={displaySetup.rs_score > 0.05 ? 'var(--go)' : 'var(--muted)'}
        />
        <SignalRow
          label="Volume Surge"
          value={displaySetup.is_vol_surge ? 'YES' : displaySetup.vol_ratio ? `×${Number(displaySetup.vol_ratio).toFixed(1)}` : '—'}
          color={displaySetup.is_vol_surge ? 'var(--go)' : undefined}
        />
        <SignalRow
          label="RS Blue Dot"
          value={displaySetup.rs_blue_dot ? 'YES — 52W HIGH' : 'NO'}
          color={displaySetup.rs_blue_dot ? 'var(--blue)' : 'var(--muted)'}
        />
        <SignalRow
          label="Distance to Entry"
          value={dist !== null ? `${Math.abs(dist).toFixed(1)}%${isAboveEntry ? ' above' : ' below'}` : '—'}
          color={dist !== null && dist > -3 && !isAboveEntry ? 'var(--accent)' : undefined}
        />
      </div>

      {/* Trade Plan */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--card-border)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>TRADE PLAN</div>
        {[
          { label: 'Entry',  value: displaySetup.entry       ? `$${displaySetup.entry.toFixed(2)}`       : '—', color: 'var(--text)'   },
          { label: 'Stop',   value: displaySetup.stop_loss   ? `$${displaySetup.stop_loss.toFixed(2)}`   : '—', color: 'var(--halt)'   },
          { label: 'Target', value: displaySetup.take_profit ? `$${displaySetup.take_profit.toFixed(2)}` : '—', color: 'var(--go)'     },
          { label: 'Risk',   value: risk ? `${risk}%` : '—',                                                     color: 'var(--accent)' },
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

      {/* AI Verdict — amber values updated to cyan */}
      {analysis && (
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)' }}>AI VERDICT</span>
            <span style={{
              padding: '3px 8px', borderRadius: 5,
              fontSize: 9, fontWeight: 700, letterSpacing: '0.06em',
              fontFamily: '"IBM Plex Mono", monospace',
              background: analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.15)'
                        : analysis.verdict_color === 'accent' ? 'rgba(80,216,240,0.15)'
                        : 'rgba(255,45,85,0.12)',
              color: analysis.verdict_color === 'go'     ? 'var(--go)'
                   : analysis.verdict_color === 'accent' ? 'var(--accent)'
                   : 'var(--halt)',
              border: `1px solid ${
                analysis.verdict_color === 'go'     ? 'rgba(0,200,122,0.35)'
              : analysis.verdict_color === 'accent' ? 'rgba(80,216,240,0.35)'
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

      {/* TradingView link — amber values updated to cyan */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--card-border)' }}>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${displaySetup.ticker}&interval=D`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            padding: '7px', borderRadius: 8,
            background: 'rgba(80,216,240,0.08)', border: '1px solid rgba(80,216,240,0.2)',
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
