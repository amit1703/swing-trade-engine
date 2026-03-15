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
          <ScannerColumnsSection />
          <IndicatorsSection />
          <SetupTypesSection />
          <MarketRegimeSection />
          <SignalGatesSection />
          <ChartLegendSection />
          <ChartControlsSection />
          <PortfolioHealthSection />
          <KeyboardSection />
        </div>
      </div>
    </div>
  )
}

/* ── Section 0: Scanner Table Columns ────────────────────────────────────── */

function ScannerColumnsSection() {
  const cols = [
    {
      label: 'SCR',
      color: 'var(--accent)',
      desc: 'Unified quality score 0–100. Color: ≥80 green (high conviction), 60–79 amber (borderline), <60 grey (shown in dev mode only). Each setup type has its own scoring formula combining trend, momentum, volume, and RS factors.',
    },
    {
      label: 'TICKER',
      color: 'var(--text)',
      desc: 'Symbol. Amber = currently selected. 🔥 = hot sector. Blue dot = RS Line at 52-week high. Age badge shows days since detection; red at ≥5 days.',
    },
    {
      label: 'TYPE',
      color: '#F5A623',
      desc: 'Setup classification: VCP, PB (Pullback), PB-RLX (Relaxed Pullback), BASE, BRK (Resistance Breakout), HTF (High Tight Flag), LCE (Low Cheat Entry).',
    },
    {
      label: 'PRICE',
      color: 'var(--text)',
      desc: 'Live price (streamed). Color: green = above entry, amber = within 3% below entry (near trigger), grey = further below. Sub-label shows % distance from entry.',
    },
    {
      label: 'VOL ×',
      color: 'var(--go)',
      desc: 'Volume today vs 20-day average. ×1.5+ shown in green — a volume surge confirms institutional participation. Grey = normal volume.',
    },
    {
      label: 'RS',
      color: 'var(--go)',
      desc: "O'Neil composite RS score (weighted 3–12 month return vs SPY, scaled to ±100). Green = ≥+5 (outperforming). Stocks below 0 are underperforming the market.",
    },
    {
      label: 'DIST',
      color: 'var(--muted)',
      desc: 'Distance from live price to entry trigger. Negative = price is below entry (not yet triggered). Amber and ↓ when within −3% (approaching). Positive = already above entry.',
    },
    {
      label: 'ENTRY',
      color: 'var(--text)',
      desc: 'The exact price level that triggers the trade. For breakouts this is the pivot high; for pullbacks it is the moving average or trendline touch point.',
    },
    {
      label: 'STOP',
      color: 'var(--halt)',
      desc: 'Hard stop-loss in dollars. Based on the swing low or KDE support zone minus an ATR buffer. Exit immediately if price closes below this level.',
    },
    {
      label: 'R:R',
      color: 'var(--go)',
      desc: 'Risk-to-reward ratio. Green = ≥2.0 (target is at least twice the risk). Calculated as (target − entry) ÷ (entry − stop).',
    },
    {
      label: 'SECTOR',
      color: 'var(--muted)',
      desc: 'Industry sector (truncated to 12 chars). Use the 🔥 hot sector filter to isolate setups where ≥3 stocks from the same sector fired in one scan.',
    },
  ]

  return (
    <div>
      <SectionLabel color="var(--accent)">Scanner Table Columns</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {cols.map((c, i) => (
          <div
            key={c.label}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '7px 8px',
              borderBottom: i < cols.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 9, fontWeight: 700,
                color: c.color,
                minWidth: 40,
              }}>
                {c.label}
              </span>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>{c.desc}</span>
          </div>
        ))}
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
      desc: "Price closed above a KDE resistance zone with ≥150% average volume AND a positive O'Neil composite RS score (stock outperforming SPY over 3–12 months). All three conditions required — volume, price location, and relative strength.",
    },
    {
      badge: <GBadge style={{ background: 'rgba(245,166,35,0.12)', color: 'var(--accent)', border: '1px solid rgba(245,166,35,0.3)' }}>DRY</GBadge>,
      name: 'Volume Dry-Up',
      desc: 'Stock is in an uptrend and within 3% of resistance, with volume contracted to <50% of 50-day average (at least one bar in the last 10). A U-shape curve fit confirms the contraction pattern. The coil is tightening before the next breakout attempt.',
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
      badge: <GBadge style={{ fontSize: 7, background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)', padding: '2px 5px' }}>5d</GBadge>,
      name: 'Setup Age',
      desc: 'Days since the setup was first detected. Turns red-bordered at ≥5 days — older setups have had more time for the thesis to play out or fail. Fresh setups (no badge) were detected in the current scan.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(38,166,154,0.12)', color: '#26a69a', border: '1px solid rgba(38,166,154,0.35)', fontWeight: 700 }}>C&amp;H</GBadge>,
      name: 'Cup & Handle',
      desc: 'Base pattern type: U-shaped cup with a shallow handle. Cup depth 12–35%, right rim within 15% of left peak, handle 5–25 days and 3–15% deep. One of the highest-probability continuation setups.',
    },
    {
      badge: <GBadge style={{ background: 'rgba(66,165,245,0.12)', color: '#42a5f5', border: '1px solid rgba(66,165,245,0.35)', fontWeight: 700 }}>FLAT</GBadge>,
      name: 'Flat Base',
      desc: 'Base pattern type: tight horizontal consolidation ≥25 days, depth ≤12%, close in upper 75% of range, volume drying to ≤90% of 50-day average. Indicates controlled selling — institutions holding.',
    },
    {
      badge: <GBadge style={{ fontFamily: 'monospace', fontSize: 9, background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)' }}>2d ago</GBadge>,
      name: 'Breakout Freshness',
      desc: "Days since the resistance breakout bar. Shows 'today' for same-day breaks, '1d ago'–'3d ago' for recent ones. Fresher breakouts carry less risk of being overextended or fading.",
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

/* ── Section 3b: Market Regime ────────────────────────────────────────────── */

function MarketRegimeSection() {
  const regimes = [
    {
      label: 'AGGRESSIVE',
      score: '70 – 100',
      color: 'var(--go)',
      bg: 'rgba(0,200,122,0.07)',
      border: 'rgba(0,200,122,0.35)',
      desc: 'Full offense. All setup types active. Highest signal frequency — BRK dominates (702 backtest trades).',
      active: ['VCP', 'PB', 'BASE', 'BRK', 'HTF', 'LCE'],
    },
    {
      label: 'SELECTIVE',
      score: '40 – 69',
      color: 'var(--accent)',
      bg: 'rgba(245,166,35,0.07)',
      border: 'rgba(245,166,35,0.35)',
      desc: 'Defensive offense. BRK disabled — breakouts fail more in mixed markets. Pullbacks and bases dominate.',
      active: ['VCP', 'PB', 'BASE', 'HTF', 'LCE'],
    },
    {
      label: 'DEFENSIVE',
      score: '0 – 39',
      color: 'var(--halt)',
      bg: 'rgba(255,45,85,0.07)',
      border: 'rgba(255,45,85,0.3)',
      desc: 'Capital preservation. Only structural setups (base building, HTF, LCE) run. VCP and Pullback signals suppressed.',
      active: ['BASE', 'HTF', 'LCE'],
    },
  ]

  const ALL_SETUPS = ['VCP', 'PB', 'BASE', 'BRK', 'HTF', 'LCE']

  const factors = [
    'SPY above 20 EMA',
    'SPY above 50 SMA',
    'EMA20 > SMA50 > SMA200 stack',
    'SPY short-term slope (5-day momentum)',
    'Market breadth — % of stocks above 200-day',
    'New highs vs new lows ratio',
    'VIX fear index level',
  ]

  return (
    <div>
      <SectionLabel color="var(--halt)">Market Regime</SectionLabel>

      {/* Regime cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, padding: '12px 12px 4px' }}>
        {regimes.map((r) => (
          <div
            key={r.label}
            style={{
              background: r.bg,
              border: `1px solid ${r.border}`,
              borderTop: `3px solid ${r.color}`,
              padding: '10px 12px',
              display: 'flex', flexDirection: 'column', gap: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 12, fontWeight: 700, letterSpacing: '0.14em',
                textTransform: 'uppercase', color: r.color,
              }}>
                {r.label}
              </span>
              <span style={{
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 9, color: 'var(--muted)',
              }}>
                {r.score}
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.5 }}>{r.desc}</span>
            {/* Active setups */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {ALL_SETUPS.map((s) => {
                const on = r.active.includes(s)
                return (
                  <span
                    key={s}
                    style={{
                      fontFamily: 'IBM Plex Mono, monospace',
                      fontSize: 8, fontWeight: 700,
                      padding: '1px 5px',
                      background: on ? `${r.color}18` : 'rgba(0,0,0,0)',
                      color: on ? r.color : 'rgba(255,255,255,0.15)',
                      border: `1px solid ${on ? r.color + '40' : 'rgba(255,255,255,0.08)'}`,
                      textDecoration: on ? 'none' : 'line-through',
                    }}
                  >
                    {s}
                  </span>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Scoring factors */}
      <div style={{ padding: '8px 20px 12px' }}>
        <span style={{
          fontFamily: 'Barlow Condensed, sans-serif',
          fontSize: 9, fontWeight: 700, letterSpacing: '0.16em',
          textTransform: 'uppercase', color: 'var(--muted)',
          display: 'block', marginBottom: 6,
        }}>
          Score Components (7 factors, equal weight)
        </span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px' }}>
          {factors.map((f, i) => (
            <span key={i} style={{ fontSize: 10, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--muted)', flexShrink: 0, display: 'inline-block' }} />
              {f}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ── Section 3c: Signal Gates & Dev Mode ─────────────────────────────────── */

function SignalGatesSection() {
  const gates = [
    {
      num: '1',
      label: 'RS Rank',
      color: '#00C8FF',
      desc: 'Stock must be in the top 30% of the scanned universe by relative strength score. Weak stocks — even with valid chart patterns — are filtered out.',
    },
    {
      num: '2',
      label: 'RS Score',
      color: '#00C8FF',
      desc: "O'Neil composite RS score must be ≥0.088 (positive outperformance vs SPY). Ensures you're only trading stocks actually leading the market.",
    },
    {
      num: '3',
      label: 'Unified Score',
      color: 'var(--accent)',
      desc: 'Setup quality score must be ≥70 to appear. Scores are setup-specific — a Pullback score of 70 means something different from a BRK score of 70. All passed this bar.',
    },
  ]

  return (
    <div>
      <SectionLabel color="#00C8FF">Signal Gates &amp; Dev Mode</SectionLabel>

      {/* Gates */}
      <div style={{ padding: '8px 12px 4px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{
          fontFamily: 'Barlow Condensed, sans-serif',
          fontSize: 9, fontWeight: 700, letterSpacing: '0.16em',
          textTransform: 'uppercase', color: 'var(--muted)',
          padding: '0 8px',
        }}>
          3-Layer Quality Filter — all must pass to appear in scanner
        </span>
        {gates.map((g) => (
          <div
            key={g.num}
            style={{
              display: 'grid', gridTemplateColumns: '148px 1fr',
              alignItems: 'center', gap: 12, padding: '6px 8px',
              background: 'var(--panel)', border: '1px solid var(--border)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 9, fontWeight: 700,
                color: 'var(--muted)',
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid var(--border)',
                padding: '1px 6px',
                minWidth: 16, textAlign: 'center',
              }}>
                {g.num}
              </span>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: g.color,
                whiteSpace: 'nowrap',
              }}>
                {g.label}
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>{g.desc}</span>
          </div>
        ))}
      </div>

      {/* Dev Mode */}
      <div style={{ margin: '8px 12px 8px', padding: '10px 14px', background: 'rgba(245,166,35,0.06)', border: '1px solid rgba(245,166,35,0.25)', borderLeft: '3px solid var(--accent)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{
            fontFamily: 'IBM Plex Mono, monospace',
            fontSize: 9, fontWeight: 700,
            background: 'rgba(245,166,35,0.15)',
            color: 'var(--accent)',
            border: '1px solid rgba(245,166,35,0.4)',
            padding: '2px 8px',
          }}>
            DEV
          </span>
          <span style={{
            fontFamily: 'Barlow Condensed, sans-serif',
            fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
            textTransform: 'uppercase', color: 'var(--text)',
          }}>
            Dev Mode
          </span>
        </div>
        <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.6 }}>
          Bypasses all quality gates for research and exploration. RS rank gate is skipped. RS score gate is skipped. Score threshold drops from 70 → 50. Regime restriction on VCP and Pullback (normally blocked in DEFENSIVE) is lifted. Produces more signals — not all are tradeable, but useful for monitoring setups before they hit full score.
        </span>
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
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <line x1="0" y1="10.5" x2="48" y2="10.5" stroke="#FF5C8A" strokeWidth="2" />
        </svg>
      ),
      name: 'SMA 200',
      desc: 'The 200-day simple moving average — the long-term trend divider. Stocks above this line are in a Stage 2 uptrend. Rendered as a thick red-pink line. All scanner setups require price above SMA 200.',
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <line x1="0" y1="4" x2="48" y2="16" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5" />
        </svg>
      ),
      name: 'Descending TDL',
      desc: "Resistance trendline drawn from the stock's macro high through validated lower highs. White solid line labelled TDL-R. A close above this line — confirmed by the engine — produces a Trendline Breakout (TDL) signal.",
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <line x1="0" y1="16" x2="48" y2="4" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5" />
        </svg>
      ),
      name: 'Ascending TDL',
      desc: 'Support trendline drawn through a sequence of validated higher lows. White solid line labelled TDL-S. A third confirmed touch generates an ASC-TDL pullback signal — price bouncing off rising support.',
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <rect x="4"  y="8"  width="6" height="12" fill="rgba(0,200,122,0.35)" />
          <rect x="13" y="4"  width="6" height="16" fill="rgba(0,200,122,0.35)" />
          <rect x="22" y="10" width="6" height="10" fill="rgba(255,45,85,0.28)" />
          <rect x="31" y="6"  width="6" height="14" fill="rgba(255,45,85,0.28)" />
          <rect x="40" y="9"  width="6" height="11" fill="rgba(0,200,122,0.35)" />
          <line x1="0" y1="9" x2="48" y2="11" stroke="rgba(245,166,35,0.55)" strokeWidth="1" strokeDasharray="3,3" />
        </svg>
      ),
      name: 'Volume Bars',
      desc: 'Per-bar volume histogram in the lower 25% of the chart. Green = up bar, red = down bar. The amber dashed line is the 50-bar volume SMA — bars above it indicate above-average participation.',
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <polyline points="0,14 12,12 24,8 36,10 48,5" fill="none" stroke="#F5A623" strokeWidth="1.5" />
        </svg>
      ),
      name: 'RS Line',
      desc: "Sub-chart below the main price panel. Plots ticker close ÷ SPY close daily — rising line means the stock is outperforming the market. A new 52-week high on the RS Line (green dashed reference) is the strongest leading indicator.",
    },
    {
      visual: (
        <svg width="48" height="20" style={{ display: 'block' }}>
          <polyline points="0,14 12,12 24,8 36,10 48,5" fill="none" stroke="#F5A623" strokeWidth="1.5" />
          <circle cx="48" cy="5" r="4" fill="#00c87a" />
        </svg>
      ),
      name: 'RS Blue Dot',
      desc: "Green dot marker on the RS Line when the current RS ratio is within 0.5% of its 52-week high. Signals peak relative strength — the stock is leading the market right now. Highest conviction entry signal.",
    },
    {
      visual: (
        <span style={{
          fontSize: 8, padding: '2px 5px',
          background: 'rgba(255,165,0,0.15)',
          color: '#FFA500',
          border: '1px solid rgba(255,165,0,0.4)',
          fontWeight: 700,
          fontFamily: 'IBM Plex Mono, monospace',
          whiteSpace: 'nowrap',
        }}>⚠ EARNINGS 7d</span>
      ),
      name: 'Earnings Warning',
      desc: "Appears in the chart legend when earnings are ≤14 days away. Shows 'TODAY' on the report date. Holding a breakout trade through earnings introduces binary gap risk — consider reducing size or waiting for the print.",
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

/* ── Section 4b: Chart Visibility Toggles ─────────────────────────────────── */

function ChartControlsSection() {
  const toggles = [
    { label: 'EMA', color: '#9B6EFF', desc: 'Show/hide EMA 8 (purple) and EMA 20 (yellow) overlays.' },
    { label: 'SMA', color: '#4CAF50', desc: 'Show/hide SMA 50 (green) and SMA 200 (red-pink) overlays.' },
    { label: 'TDL', color: 'rgba(255,255,255,0.8)', desc: 'Show/hide descending resistance trendline and ascending support trendline.' },
    { label: 'S/R', color: 'rgba(255,255,255,0.6)', desc: 'Show/hide all KDE support and resistance bands.' },
    { label: 'RS',  color: '#F5A623', desc: 'Show/hide the RS Line sub-panel (only appears when RS data is available).' },
    { label: 'VOL', color: 'rgba(0,200,122,0.8)', desc: 'Show/hide the volume histogram and 50-bar volume SMA.' },
  ]

  return (
    <div>
      <SectionLabel color="var(--muted)">Chart Visibility Toggles</SectionLabel>
      <div style={{ padding: '4px 12px 4px' }}>
        {toggles.map((t, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '148px 1fr',
              alignItems: 'center',
              gap: 12,
              padding: '8px 8px',
              borderBottom: i < toggles.length - 1 ? '1px solid rgba(26,37,53,0.6)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ minWidth: 40, display: 'flex', justifyContent: 'flex-start' }}>
                <span style={{
                  fontFamily: 'IBM Plex Mono, monospace',
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.08em',
                  padding: '2px 7px',
                  background: 'rgba(0,0,0,0.75)',
                  border: `1px solid ${t.color}`,
                  color: t.color,
                  userSelect: 'none',
                }}>
                  {t.label}
                </span>
              </div>
              <span style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}>
                {t.label}
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.55 }}>
              {t.desc}
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
