/**
 * SystemGuideModal — System Guide & Legend overlay
 *
 * Props:
 *   isOpen  {bool}  — controls visibility
 *   onClose {func}  — called on Escape, × button, or backdrop click
 *
 * Keyboard shortcuts (wired in App.jsx):
 *   Escape → close
 *   ?      → open (when no input is focused)
 */
import { useEffect } from 'react'

export default function SystemGuideModal({ isOpen, onClose }) {
  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    /* Backdrop — click outside to close */
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 50,
        background: 'rgba(0,0,0,0.88)',
        backdropFilter: 'blur(2px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20,
      }}
    >
      {/* Panel — stop clicks propagating to backdrop */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 820,
          maxHeight: '85vh',
          background: 'var(--surface)',
          border: '1px solid var(--border-light)',
          display: 'flex', flexDirection: 'column',
        }}
      >
        {/* Amber accent bar */}
        <div style={{ height: 3, background: 'var(--accent)', flexShrink: 0 }} />

        {/* Title row */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px 10px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <span style={{
            fontFamily: 'Barlow Condensed, sans-serif',
            fontSize: 14, fontWeight: 700, letterSpacing: '0.2em',
            textTransform: 'uppercase', color: 'var(--text)',
          }}>
            System Guide &amp; Legend
          </span>
          <button
            onClick={onClose}
            title="Close (Esc)"
            style={{
              background: 'transparent', border: 'none',
              color: 'var(--muted)', cursor: 'pointer',
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 18, padding: '0 4px', lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Scrollable body */}
        <div style={{ overflowY: 'auto', paddingBottom: 16 }}>
          <MetricsSection />
          <IndicatorsSection />
          <SetupTypesSection />
          <ChartLegendSection />
          <PortfolioHealthSection />
          <KeyboardSection />
        </div>
      </div>
    </div>
  )
}

/* ── Section 1: Core Metrics ──────────────────────────────────────────────── */

function MetricsSection() {
  const metrics = [
    {
      label: 'Entry $',
      value: '$182.40',
      color: 'var(--text)',
      desc: 'Exact trigger price to enter the trade.',
    },
    {
      label: 'Stop $',
      value: '$174.20',
      color: 'var(--halt)',
      desc: 'Invalidation level — hard stop-loss. Exit immediately if price closes below this.',
    },
    {
      label: 'Target $',
      value: '$198.80',
      color: 'var(--go)',
      desc: 'Initial take-profit based on ATR or the next KDE resistance zone.',
    },
    {
      label: 'R:R',
      value: '2.0×',
      color: 'var(--accent)',
      desc: 'Risk-to-Reward ratio. 2.0 means you stand to make twice what you risk.',
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--accent)">Core Metrics</SectionLabel>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 8, padding: '12px 12px 4px',
      }}>
        {metrics.map((m) => (
          <div
            key={m.label}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              padding: '12px 14px',
              display: 'flex', flexDirection: 'column', gap: 6,
            }}
          >
            <span style={{
              fontFamily: 'Barlow Condensed, sans-serif',
              fontSize: 9, fontWeight: 700, letterSpacing: '0.18em',
              textTransform: 'uppercase', color: 'var(--muted)',
            }}>
              {m.label}
            </span>
            <span style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 20, fontWeight: 700, color: m.color, lineHeight: 1,
            }}>
              {m.value}
            </span>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.5 }}>
              {m.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 2: Alpha Indicators ──────────────────────────────────────────── */

function IndicatorsSection() {
  const rows = [
    {
      badge: <span style={{ fontSize: 14, lineHeight: 1 }}>🔥</span>,
      name: 'Hot Sector',
      desc: 'Sector Clustering — appears when ≥3 setups fire in the same sector during a single scan. Signals institutional order flow and sector rotation in progress.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontWeight: 700 }}>LEAD</GBadge>,
      name: 'RS Lead',
      desc: "Highest-conviction breakout: stock's 3-month return beats SPY AND the RS Line is at a 52-week high (blue dot). Institutional accumulation at peak relative strength.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,122,0.18)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700 }}>BRK</GBadge>,
      name: 'Confirmed Breakout',
      desc: "Price closed above a KDE resistance zone with ≥150% average volume and positive composite RS score (O'Neil formula). Demand is overwhelming supply.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)' }}>DRY</GBadge>,
      name: 'Volume Dry-Up',
      desc: 'Volume contracted to <50% of the 50-day average during consolidation. Sellers are exhausted — the stock is coiling for the next explosive move.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(255,255,255,0.08)', color: '#FFFFFF', border: '1px solid rgba(255,255,255,0.25)' }}>TDL</GBadge>,
      name: 'Trendline',
      desc: 'Setup is respecting or breaking a strictly validated geometric trendline. Enforced with no-slice rule (no candle body may cross the line) and macro anchor (global high/low).',
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.3)', fontWeight: 700 }}>KDE</GBadge>,
      name: 'KDE Breakout',
      desc: 'Horizontal breakout above a Gaussian KDE density peak — a statistically significant price cluster where heavy institutional volume was traded historically.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(0,200,255,0.10)', color: '#00C8FF', border: '1px solid rgba(0,200,255,0.2)', fontSize: 8 }}>RS+</GBadge>,
      name: 'RS Positive',
      desc: "Stock's O'Neil composite RS score is positive: weighted 63-day (40%) + 126-day (20%) + 189-day (20%) + 252-day (20%) return vs. SPY. Outperforming the market.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)', fontSize: 7 }}>RLX</GBadge>,
      name: 'CCI Relaxation',
      desc: 'CCI reset below −30 (oversold) while the primary trend (8 EMA > 20 EMA, close > 50 SMA) remains intact. Relaxed pullback entry for strong ongoing trends.',
    },
    {
      badge: <GBadge style={{ background: '#FF6B35', color: 'white', border: 'none', fontSize: 7, fontWeight: 700, letterSpacing: '0.5px', padding: '2px 4px' }}>ASC-TDL</GBadge>,
      name: 'Ascending TDL',
      desc: '3rd-touch bounce off a validated ascending trendline (higher-lows sequence). Geometric no-slice rule enforced — no bar has ever closed below the line.',
    },
    {
      badge: <GBadge style={{ fontFamily: 'monospace', fontSize: 9, background: 'rgba(255,255,255,0.04)', color: 'var(--muted)', border: '1px solid var(--border)' }}>Q72</GBadge>,
      name: 'Quality Score (0–100)',
      desc: "O'Neil composite for Base patterns: RS vs SPY (25pts) + base tightness/depth (25pts) + volume dry-up (25pts) + RS blue dot at 52-week high (25pts).",
    },
    {
      badge: <GBadge style={{ background: 'rgba(168,85,247,0.15)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.35)', fontWeight: 700 }}>SCORE</GBadge>,
      name: 'Options Score (0–100)',
      desc: 'Composite options flow signal: Vol/OI ratio (30pts) + absolute call volume (25pts) + call/put skew (25pts) + IV term structure slope (20pts). ≥60 required.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(168,85,247,0.10)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.25)' }}>VOL 42K</GBadge>,
      name: 'Call Volume',
      desc: 'Total call contract volume traded on the dominant expiry date. Higher absolute volume = greater conviction from options traders. Minimum 500 contracts required.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(168,85,247,0.10)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.25)' }}>C/P 3.20</GBadge>,
      name: 'Call/Put Ratio',
      desc: 'Ratio of call volume to put volume. Values >1.5 signal net bullish options flow. Extreme skew (>5) often means institutional directional positioning ahead of a catalyst.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(168,85,247,0.10)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.25)' }}>DTE 21</GBadge>,
      name: 'Days to Expiry',
      desc: 'Days remaining on the dominant options expiry. Short DTE (≤30) reflects high urgency — traders expect the move before expiry. Long DTE suggests a larger positioning play.',
    },
  ]

  return (
    <div>
      <SectionLabel color="#00C8FF">Alpha Indicators</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {rows.map((row, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '8px 8px',
              borderBottom: i < rows.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            {/* Left: badge + name */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ minWidth: 40, display: 'flex', justifyContent: 'flex-start' }}>
                {row.badge}
              </div>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
                {row.name}
              </span>
            </div>
            {/* Right: description */}
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {row.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 3: Setup Types ───────────────────────────────────────────────── */

function SetupTypesSection() {
  const setups = [
    {
      name: 'VCP Breakouts',
      accent: 'var(--blue)',
      desc: "Minervini's Volatility Contraction Pattern. The stock is in a Stage 2 uptrend, contracting from left to right with decreasing volume, ready to explode out of a tight pivot.",
    },
    {
      name: 'Tactical Pullbacks',
      accent: 'var(--accent)',
      desc: 'A strong stock pulling back to a key moving average (20 EMA or 50 SMA) to shake out weak hands before resuming the uptrend. CCI resets to oversold then hooks up.',
    },
    {
      name: 'Base Patterns',
      accent: 'var(--go)',
      desc: 'Flat or deep consolidations (Cup & Handle, Flat Base) where the stock catches its breath and builds a foundation for the next leg up. Quality-scored 0–100.',
    },
    {
      name: 'Resistance Breakouts',
      accent: 'var(--go)',
      desc: 'Stock built a tight 3-bar launchpad just below a heavy resistance level and is now breaking through with decisive close (top 30% of range) and >150% average volume.',
    },
    {
      name: 'Options Catalyst',
      accent: '#a855f7',
      desc: 'Unusual bullish options flow detected: high call volume relative to open interest, skewed call/put ratio, and positive IV term structure slope. Institutions are positioning for an upside catalyst. Score ≥60/100 required.',
      fullWidth: true,
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--go)">Setup Types</SectionLabel>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr',
        gap: 8, padding: '12px',
      }}>
        {setups.map((s) => (
          <div
            key={s.name}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              borderLeft: `3px solid ${s.accent}`,
              padding: '12px 14px',
              display: 'flex', flexDirection: 'column', gap: 6,
              ...(s.fullWidth ? { gridColumn: '1 / -1' } : {}),
            }}
          >
            <span style={{
              fontFamily: 'Barlow Condensed, sans-serif',
              fontSize: 12, fontWeight: 700, letterSpacing: '0.12em',
              textTransform: 'uppercase', color: 'var(--text)',
            }}>
              {s.name}
            </span>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {s.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 4: Chart Legend ──────────────────────────────────────────────── */

function ChartLegendSection() {
  const items = [
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <rect x="0" y="4" width="48" height="12" fill="rgba(255,45,85,0.18)" />
          <line x1="0" y1="4.5" x2="48" y2="4.5" stroke="rgba(255,45,85,0.75)" strokeWidth="1.2" strokeDasharray="5,4" />
          <line x1="0" y1="15.5" x2="48" y2="15.5" stroke="rgba(255,45,85,0.75)" strokeWidth="1.2" strokeDasharray="5,4" />
        </svg>
      ),
      name: 'KDE Resistance Band',
      desc: 'Gaussian KDE density peak above current price — a statistically heavy supply zone where institutional sellers previously absorbed demand. Red dashed borders.',
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <rect x="0" y="4" width="48" height="12" fill="rgba(0,200,122,0.16)" />
          <line x1="0" y1="4.5" x2="48" y2="4.5" stroke="rgba(0,200,122,0.75)" strokeWidth="1.2" strokeDasharray="5,4" />
          <line x1="0" y1="15.5" x2="48" y2="15.5" stroke="rgba(0,200,122,0.75)" strokeWidth="1.2" strokeDasharray="5,4" />
        </svg>
      ),
      name: 'KDE Support Band',
      desc: 'KDE density peak below current price — a historically significant demand zone where buyers consistently step in. Green dashed borders.',
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <line x1="0" y1="10.5" x2="48" y2="10.5" stroke="rgba(255,140,0,0.90)" strokeWidth="1.5" />
        </svg>
      ),
      name: 'Pivot Resistance Line',
      desc: 'Two or more major swing highs clustered within 1.5% of each other and ≥7 bars apart. A tested overhead ceiling. Rendered as a thin solid amber line (no fill).',
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--muted)">Chart Legend</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {items.map((item, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '8px 8px',
              borderBottom: i < items.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ minWidth: 48, display: 'flex', justifyContent: 'flex-start' }}>
                {item.visual}
              </div>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
                {item.name}
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {item.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 5: Portfolio Health ─────────────────────────────────────────── */

function PortfolioHealthSection() {
  const signals = [
    {
      badge: <GBadge style={{ background: 'rgba(0,200,122,0.15)', color: 'var(--go)', border: '1px solid rgba(0,200,122,0.4)', fontWeight: 700, minWidth: 46, textAlign: 'center' }}>HOLD</GBadge>,
      name: 'Hold',
      desc: 'Close is above the 20 EMA. The trend is intact. Consider trailing your stop up to max(original stop, 20 EMA) once you are in profit.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(245,166,35,0.15)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.4)', fontWeight: 700, minWidth: 46, textAlign: 'center' }}>CAUTION</GBadge>,
      name: 'Caution',
      desc: 'Close slipped below the 8 EMA. Momentum is fading. Reduce size or tighten your stop — do not add to the position.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(255,45,85,0.15)', color: 'var(--halt)', border: '1px solid rgba(255,45,85,0.4)', fontWeight: 700, minWidth: 46, textAlign: 'center' }}>EXIT</GBadge>,
      name: 'Exit Signal',
      desc: 'Close broke below the 20 EMA OR CCI dropped below −100. The thesis is invalidated. Exit at open unless the stock is gapping up through the EMA on high volume.',
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--go)">Portfolio Health Signals</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {signals.map((row, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '8px 8px',
              borderBottom: i < signals.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ minWidth: 40, display: 'flex', justifyContent: 'flex-start' }}>
                {row.badge}
              </div>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
                {row.name}
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {row.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Section 6: Keyboard Shortcuts ───────────────────────────────────────── */

function KeyboardSection() {
  const shortcuts = [
    { key: '?', desc: 'Open this guide' },
    { key: 'Esc', desc: 'Close this guide' },
  ]

  return (
    <div>
      <SectionLabel color="var(--muted)">Keyboard Shortcuts</SectionLabel>
      <div style={{ padding: '8px 20px 4px', display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        {shortcuts.map((s) => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <kbd style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 10, fontWeight: 700,
              background: 'var(--panel)',
              border: '1px solid var(--border-light)',
              color: 'var(--text)',
              padding: '2px 8px',
              borderRadius: 2,
              letterSpacing: '0.05em',
            }}>
              {s.key}
            </kbd>
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>{s.desc}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Shared primitives ────────────────────────────────────────────────────── */

function SectionLabel({ children, color }) {
  return (
    <div
      className="section-label"
      style={{ borderTop: '1px solid var(--border)' }}
    >
      <span style={{
        display: 'inline-block', width: 6, height: 6,
        borderRadius: '50%', background: color, flexShrink: 0,
      }} />
      {children}
    </div>
  )
}

function GBadge({ children, style }) {
  return (
    <span className="badge" style={style}>
      {children}
    </span>
  )
}
