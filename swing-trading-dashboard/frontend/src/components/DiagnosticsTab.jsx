import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { useAppSettings } from '../contexts/AppSettingsContext'

// ─── MetricCard ───────────────────────────────────────────────────────────────
function MetricCard({ label, value, sub }) {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--card-border)',
      borderRadius: 10, padding: '14px 16px', minWidth: 130,
    }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--muted)', marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontFamily: '"Barlow Condensed", sans-serif', fontSize: 26, fontWeight: 700, color: 'var(--text)', lineHeight: 1 }}>
        {value ?? '—'}
      </div>
      {sub && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// ─── SectionHeader ────────────────────────────────────────────────────────────
function SectionHeader({ title }) {
  return (
    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.12em', color: 'var(--muted)', marginBottom: 10, marginTop: 24 }}>
      {title}
    </div>
  )
}

// ─── EmptyState ───────────────────────────────────────────────────────────────
function EmptyState({ message = 'No closed trade data yet' }) {
  return (
    <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 11 }}>
      {message}
    </div>
  )
}

// ─── EquityCurve ──────────────────────────────────────────────────────────────
function EquityCurve({ data, dates }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !data || data.length === 0) return

    const chart = createChart(ref.current, {
      width:  ref.current.clientWidth,
      height: 160,
      layout:      { background: { color: 'transparent' }, textColor: '#64748b' },
      grid:        { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      timeScale:   { visible: true, borderColor: '#1e293b' },
      rightPriceScale: { borderColor: '#1e293b' },
      crosshair:   { mode: 1 },
      handleScroll: false,
      handleScale:  false,
    })

    const series = chart.addLineSeries({
      color:            data[data.length - 1] >= 0 ? '#00C87A' : '#FF2D55',
      lineWidth:        2,
      priceLineVisible: false,
    })

    // Use actual exit dates when available; fall back to synthetic sequential dates.
    // Deduplicate: if two trades close the same calendar day, advance by one day.
    const startMs = new Date('2020-01-01').getTime()
    const DAY_MS  = 86400 * 1000
    const seen    = new Set()
    const chartData = data.map((v, i) => {
      let dateStr = (Array.isArray(dates) && dates[i])
        ? dates[i].slice(0, 10)
        : new Date(startMs + i * DAY_MS).toISOString().slice(0, 10)
      // Shift forward one day at a time until the date is unique
      while (seen.has(dateStr)) {
        const d = new Date(dateStr)
        d.setUTCDate(d.getUTCDate() + 1)
        dateStr = d.toISOString().slice(0, 10)
      }
      seen.add(dateStr)
      return { time: dateStr, value: v }
    })

    series.setData(chartData)
    chart.timeScale().fitContent()

    return () => chart.remove()
  }, [data, dates])

  if (!data || data.length === 0) return <EmptyState message="No equity curve data — close some trades first" />
  return <div ref={ref} style={{ width: '100%', height: 160 }} />
}

// ─── RMultipleDistribution ────────────────────────────────────────────────────
function RMultipleDistribution({ rows }) {
  if (!rows || rows.length === 0) return <EmptyState />
  const maxPct = Math.max(...rows.map(r => r.pct), 1)
  const BAR_COLORS = {
    '<-1R':  'var(--halt)',
    '-1R–0': '#ff6b6b',
    '0–1R':  '#ffa94d',
    '1R–2R': '#74c0fc',
    '2R–3R': '#51cf66',
    '>3R':   'var(--go)',
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.map(r => (
        <div key={r.bucket} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontFamily: '"IBM Plex Mono", monospace', fontSize: 11, fontWeight: 700,
            width: 60, flexShrink: 0, color: BAR_COLORS[r.bucket] ?? 'var(--text)',
          }}>{r.bucket}</span>
          <div style={{ flex: 1, height: 18, background: 'rgba(255,255,255,0.05)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: `${(r.pct / maxPct) * 100}%`,
              background: BAR_COLORS[r.bucket] ?? 'var(--text)',
              opacity: 0.85,
              transition: 'width 0.3s ease',
            }} />
          </div>
          <span style={{ width: 36, textAlign: 'right', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--text)', flexShrink: 0 }}>
            {r.count}
          </span>
          <span style={{ width: 44, textAlign: 'right', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)', flexShrink: 0 }}>
            {r.pct.toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  )
}

// ─── RegimeDistributionPanel ──────────────────────────────────────────────────
function RegimeDistributionPanel({ dist }) {
  if (!dist || Object.keys(dist).length === 0) return <EmptyState message="Regime distribution not available" />
  const REGIME_COLORS = { AGGRESSIVE: 'var(--go)', SELECTIVE: 'var(--accent)', DEFENSIVE: 'var(--halt)' }
  const maxPct = Math.max(...Object.values(dist).map(v => v.pct ?? 0), 1)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {['AGGRESSIVE', 'SELECTIVE', 'DEFENSIVE'].map(tier => {
        const v = dist[tier]
        if (!v) return null
        return (
          <div key={tier} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{
              fontFamily: '"IBM Plex Mono", monospace', fontSize: 11, fontWeight: 700,
              width: 96, flexShrink: 0, color: REGIME_COLORS[tier],
            }}>{tier}</span>
            <div style={{ flex: 1, height: 18, background: 'rgba(255,255,255,0.05)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: 3,
                width: `${(v.pct / maxPct) * 100}%`,
                background: REGIME_COLORS[tier],
                opacity: 0.75,
                transition: 'width 0.3s ease',
              }} />
            </div>
            <span style={{ width: 40, textAlign: 'right', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--text)', flexShrink: 0 }}>
              {v.days}d
            </span>
            <span style={{ width: 44, textAlign: 'right', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--muted)', flexShrink: 0 }}>
              {v.pct.toFixed(1)}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ─── ScoreDistributionPanel ───────────────────────────────────────────────────
function ScoreDistributionPanel({ rows }) {
  if (!rows || rows.length === 0) return <EmptyState message="Score distribution not available (run backtest first)" />
  const total = rows.reduce((s, r) => s + r.count, 0)
  const maxPct = Math.max(...rows.map(r => r.pct), 1)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 4 }}>
        {total} signals evaluated (pre-gate) · gate at 70
      </div>
      {rows.map(r => (
        <div key={r.bucket} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontFamily: '"IBM Plex Mono", monospace', fontSize: 11, fontWeight: 700,
            width: 52, flexShrink: 0,
            color: r.above_gate ? 'var(--go)' : 'var(--muted)',
          }}>{r.bucket}</span>
          <div style={{ flex: 1, height: 18, background: 'rgba(255,255,255,0.05)', borderRadius: 3, overflow: 'hidden', position: 'relative' }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: `${(r.pct / maxPct) * 100}%`,
              background: r.above_gate ? 'var(--go)' : 'rgba(100,116,139,0.5)',
              transition: 'width 0.3s ease',
            }} />
          </div>
          <span style={{ width: 36, textAlign: 'right', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', color: 'var(--text)', flexShrink: 0 }}>
            {r.count}
          </span>
          <span style={{ width: 44, textAlign: 'right', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace', color: r.above_gate ? 'var(--go)' : 'var(--muted)', flexShrink: 0 }}>
            {r.pct.toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  )
}

// ─── SelectiveAnalysis ────────────────────────────────────────────────────────
const CLASSIFICATION_COLORS = {
  STRONG:            'var(--go)',
  WEAK:              'var(--halt)',
  INSUFFICIENT_DATA: 'var(--muted)',
}

function SelectiveAnalysis({ data }) {
  if (!data || data.total_selective_trades === 0) return null

  const { setup_breakdown, before, after_simulated, strong_setups, weak_setups,
          insufficient_data_setups, suggested_weights, total_selective_trades } = data

  const hasBefore = before && before.total_trades > 0
  const hasAfter  = after_simulated && after_simulated.total_trades > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Summary row */}
      <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
        {total_selective_trades} SELECTIVE-regime trades analysed ·{' '}
        <span style={{ color: 'var(--go)' }}>{strong_setups.length} strong</span>
        {' · '}
        <span style={{ color: 'var(--halt)' }}>{weak_setups.length} weak</span>
        {' · '}
        <span style={{ color: 'var(--muted)' }}>{insufficient_data_setups.length} insufficient data</span>
      </div>

      {/* Before / after simulation */}
      {hasBefore && (
        <div style={{ display: 'flex', gap: 10 }}>
          {[
            { label: 'ALL SELECTIVE (before)', m: before, accent: 'var(--muted)' },
            hasAfter && { label: 'STRONG ONLY (simulated)', m: after_simulated, accent: 'var(--go)' },
          ].filter(Boolean).map(({ label, m, accent }) => (
            <div key={label} style={{
              flex: 1, background: 'var(--card)', border: `1px solid ${accent}33`,
              borderRadius: 8, padding: '10px 14px',
            }}>
              <div style={{ fontSize: 8, fontWeight: 700, letterSpacing: '0.1em',
                color: accent, marginBottom: 8 }}>{label}</div>
              {[
                ['Trades',     m.total_trades],
                ['Win Rate',   m.win_rate   != null ? `${(m.win_rate * 100).toFixed(1)}%`           : '—'],
                ['Avg R',      m.avg_R      != null ? `${m.avg_R >= 0 ? '+' : ''}${m.avg_R.toFixed(2)}R` : '—'],
                ['Expectancy', m.expectancy != null ? `${m.expectancy >= 0 ? '+' : ''}${m.expectancy.toFixed(2)}R` : '—'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between',
                  fontSize: 10, marginBottom: 3 }}>
                  <span style={{ color: 'var(--muted)' }}>{k}</span>
                  <span style={{ fontFamily: '"IBM Plex Mono", monospace',
                    fontWeight: 700, color: 'var(--text)' }}>{v}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Per-setup classification table */}
      {Object.keys(setup_breakdown || {}).length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Setup', 'Class', 'Trades', 'Win %', 'Expectancy', 'Suggested Weight'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Setup' ? 'left' : 'right',
                    padding: '5px 10px', fontSize: 9, fontWeight: 700,
                    letterSpacing: '0.08em', color: 'var(--muted)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(setup_breakdown).map(([stype, m]) => (
                <tr key={stype} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '7px 10px', fontFamily: '"IBM Plex Mono", monospace',
                    fontWeight: 700, fontSize: 11,
                    color: SETUP_COLORS[stype] ?? 'var(--text)' }}>{stype}</td>
                  <td style={{ textAlign: 'right', padding: '7px 10px',
                    color: CLASSIFICATION_COLORS[m.classification] ?? 'var(--muted)',
                    fontFamily: '"IBM Plex Mono", monospace', fontSize: 10,
                    fontWeight: 700 }}>{m.classification}</td>
                  <td style={{ textAlign: 'right', padding: '7px 10px',
                    fontFamily: '"IBM Plex Mono", monospace' }}>{m.count}</td>
                  <td style={{ textAlign: 'right', padding: '7px 10px',
                    fontFamily: '"IBM Plex Mono", monospace',
                    color: (m.win_rate ?? 0) >= 0.5 ? 'var(--go)' : 'var(--halt)' }}>
                    {m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', padding: '7px 10px',
                    fontFamily: '"IBM Plex Mono", monospace',
                    color: (m.expectancy ?? 0) >= 0 ? 'var(--go)' : 'var(--halt)' }}>
                    {m.expectancy != null ? `${m.expectancy >= 0 ? '+' : ''}${m.expectancy.toFixed(2)}R` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', padding: '7px 10px',
                    fontFamily: '"IBM Plex Mono", monospace',
                    color: m.suggested_weight >= 1.0 ? 'var(--go)' : m.suggested_weight >= 0.5 ? 'var(--accent)' : 'var(--halt)',
                    fontWeight: 700 }}>
                    {m.suggested_weight != null ? m.suggested_weight.toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Suggested weights — paste-ready for constants.py */}
      {suggested_weights && Object.keys(suggested_weights).length > 0 && (
        <div style={{ background: 'rgba(0,0,0,0.25)', borderRadius: 6,
          padding: '8px 12px', fontFamily: '"IBM Plex Mono", monospace', fontSize: 10 }}>
          <div style={{ color: 'var(--muted)', marginBottom: 4, fontSize: 9,
            letterSpacing: '0.08em', fontWeight: 700 }}>
            SUGGESTED SELECTIVE_SETUP_WEIGHTS (constants.py)
          </div>
          <div style={{ color: 'var(--text)' }}>
            {'{'}{Object.entries(suggested_weights).map(([k, v]) =>
              `"${k}": ${v.toFixed(1)}`
            ).join(', ')}{'}'}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── SetupBreakdownTable ──────────────────────────────────────────────────────
const SETUP_COLORS = {
  VCP: 'var(--blue)', PULLBACK: 'var(--accent)', RES_BREAKOUT: 'var(--go)', BASE: 'var(--text)',
}

function SetupBreakdownTable({ breakdown }) {
  const rows = Object.entries(breakdown || {})
  if (rows.length === 0) return <EmptyState />

  const headers = ['Setup', 'Trades', 'Win %', 'Prof.Factor', 'Avg R', 'Expectancy', 'Max DD']

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {headers.map(h => (
              <th key={h} style={{
                textAlign: h === 'Setup' ? 'left' : 'right',
                padding: '6px 10px', fontSize: 9, fontWeight: 700,
                letterSpacing: '0.08em', color: 'var(--muted)',
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([type, m]) => (
            <tr key={type} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '8px 10px' }}>
                <span style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, color: SETUP_COLORS[type] ?? 'var(--text)', fontSize: 11 }}>
                  {type}
                </span>
                {m?.low_sample && (
                  <span title="Fewer than 20 trades — interpret with caution"
                        style={{ marginLeft: 6, fontSize: 9, color: 'var(--accent)', cursor: 'help' }}>⚠</span>
                )}
              </td>
              <td style={{ textAlign: 'right', padding: '8px 10px', fontFamily: '"IBM Plex Mono", monospace' }}>
                {m?.total_trades ?? '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '8px 10px', fontFamily: '"IBM Plex Mono", monospace',
                           color: (m?.win_rate ?? 0) >= 0.5 ? 'var(--go)' : 'var(--halt)' }}>
                {m?.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '8px 10px', fontFamily: '"IBM Plex Mono", monospace',
                           color: (m?.profit_factor ?? 0) >= 1.5 ? 'var(--go)' : 'var(--muted)' }}>
                {m?.profit_factor != null ? m.profit_factor.toFixed(2) : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '8px 10px', fontFamily: '"IBM Plex Mono", monospace',
                           color: (m?.avg_R ?? 0) >= 0 ? 'var(--go)' : 'var(--halt)' }}>
                {m?.avg_R != null ? `${m.avg_R >= 0 ? '+' : ''}${m.avg_R.toFixed(2)}R` : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '8px 10px', fontFamily: '"IBM Plex Mono", monospace',
                           color: (m?.expectancy ?? 0) >= 0 ? 'var(--go)' : 'var(--halt)' }}>
                {m?.expectancy != null ? `${m.expectancy >= 0 ? '+' : ''}${m.expectancy.toFixed(2)}R` : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '8px 10px', fontFamily: '"IBM Plex Mono", monospace',
                           color: 'var(--halt)' }}>
                {m?.max_drawdown != null ? `${m.max_drawdown.toFixed(2)}R` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── TickerDistribution ───────────────────────────────────────────────────────
function TickerDistribution({ rows }) {
  if (!rows || rows.length === 0) return <EmptyState />
  const maxAbs = Math.max(...rows.map(r => Math.abs(r.total_pnl)), 0.001)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.slice(0, 20).map(r => (
        <div key={r.ticker} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, fontSize: 11,
            width: 60, flexShrink: 0, color: 'var(--text)',
          }}>{r.ticker}</span>
          <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: `${(Math.abs(r.total_pnl) / maxAbs) * 100}%`,
              background: r.total_pnl >= 0 ? 'var(--go)' : 'var(--halt)',
            }} />
          </div>
          <span style={{
            fontSize: 10, fontFamily: '"IBM Plex Mono", monospace',
            color: r.total_pnl >= 0 ? 'var(--go)' : 'var(--halt)',
            width: 70, textAlign: 'right', flexShrink: 0,
          }}>
            {r.total_pnl >= 0 ? '+' : ''}{r.total_pnl.toFixed(2)}R
          </span>
          <span style={{ fontSize: 9, color: 'var(--muted)', width: 40, textAlign: 'right', flexShrink: 0 }}>
            {r.trade_count}t
          </span>
        </div>
      ))}
    </div>
  )
}

// ─── RegimePerformance ────────────────────────────────────────────────────────
const REGIME_COLORS = {
  AGGRESSIVE: 'var(--go)', SELECTIVE: 'var(--accent)',
  DEFENSIVE: 'var(--halt)', UNKNOWN: 'var(--muted)',
}

function RegimePerformance({ perf }) {
  const entries = Object.entries(perf || {}).filter(([, v]) => v !== null)
  if (entries.length === 0) return <EmptyState />

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      {entries.map(([label, m]) => {
        const c = REGIME_COLORS[label] ?? 'var(--muted)'
        return (
          <div key={label} style={{
            flex: '1 1 160px', background: 'var(--card)',
            border: `1px solid ${c}33`, borderRadius: 10, padding: '12px 14px',
          }}>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: c, marginBottom: 8 }}>
              {label}
            </div>
            {[
              ['Trades',     m.trades],
              ['Win Rate',   m.win_rate   != null ? `${((m.win_rate ?? 0) * 100).toFixed(1)}%`  : '—'],
              ['Avg R',      m.avg_R      != null ? `${(m.avg_R ?? 0) >= 0 ? '+' : ''}${(m.avg_R ?? 0).toFixed(2)}R`      : '—'],
              ['Expectancy', m.expectancy != null ? `${(m.expectancy ?? 0) >= 0 ? '+' : ''}${(m.expectancy ?? 0).toFixed(2)}R` : '—'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 3 }}>
                <span style={{ color: 'var(--muted)' }}>{k}</span>
                <span style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, color: 'var(--text)' }}>{v}</span>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

// ─── DiagnosticsTab (main) ────────────────────────────────────────────────────
export default function DiagnosticsTab() {
  const { tr, lang } = useAppSettings()
  const [data, setData]           = useState(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [source, setSource]       = useState('live')      // 'live' | 'backtest'
  const [backtestStatus, setBacktestStatus] = useState(null)
  const [btRunning, setBtRunning] = useState(false)
  const pollRef                   = useRef(null)
  const [btConfig, setBtConfig] = useState({
    startYear:    2017,
    endYear:      2024,
    maxPositions: 4,
    tickerCount:  null,
    minScore:     70,
    setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
  })
  const [ioConfig, setIoConfig] = useState({
    isStartYear:  2017,
    isEndYear:    2021,
    oosStartYear: 2022,
    oosEndYear:   2024,
    maxPositions: 4,
    minScore:     70,
    setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
  })
  const [ioRunning, setIoRunning]               = useState(false)
  const [ioStatus, setIoStatus]                 = useState(null)
  const [ioData, setIoData]                     = useState(null)
  const [ioError, setIoError]                   = useState(null)
  const ioPollRef                               = useRef(null)
  const [showIsBreakdown, setShowIsBreakdown]   = useState(false)
  const [showOosBreakdown, setShowOosBreakdown] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    async function fetchData() {
      setLoading(true)
      setError(null)
      try {
        const url = source === 'live'
          ? '/api/diagnostics/report'
          : source === 'backtest'
          ? '/api/diagnostics/backtest'
          : '/api/diagnostics/isoos'
        const res = await fetch(url, {
          signal: controller.signal,
          cache: source === 'backtest' ? 'no-store' : 'default',
        })
        if (res.status === 404 && source === 'backtest') {
          setData(null)
          setLoading(false)
          return
        }
        if (res.status === 404 && source === 'isoos') {
          setIoData(null)
          setLoading(false)
          return
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        if (source === 'isoos') {
          setIoData(json)
        } else {
          setData(json)
        }
      } catch (err) {
        if (err.name !== 'AbortError') setError(err.message)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    return () => controller.abort()
  }, [source])   // re-fetches whenever source changes

  useEffect(() => {
    if (!btRunning) return
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch('/api/diagnostics/backtest/status')
        const s = await res.json()
        setBacktestStatus(s)
        if (s.status === 'completed' || s.status === 'failed') {
          clearInterval(pollRef.current)
          if (s.status === 'completed') {
            try {
              const r = await fetch('/api/diagnostics/backtest', { cache: 'no-store' })
              if (r.ok) setData(await r.json())
            } catch (_) {}
          }
          setBtRunning(false)
        }
      } catch (_) {}
    }, 3000)
    return () => clearInterval(pollRef.current)
  }, [btRunning])

  useEffect(() => {
    if (!ioRunning) return
    ioPollRef.current = setInterval(async () => {
      try {
        const s = await fetch('/api/diagnostics/isoos/status').then(r => r.json())
        setIoStatus(s)
        if (s.status === 'completed' || s.status === 'failed') {
          clearInterval(ioPollRef.current)
          setIoRunning(false)
          if (s.status === 'completed') {
            const result = await fetch('/api/diagnostics/isoos').then(r => r.json())
            setIoData(result)
            setIoError(null)
          } else {
            setIoError(s.error || 'IS/OOS backtest failed')
          }
        }
      } catch (err) {
        clearInterval(ioPollRef.current)
        setIoRunning(false)
        setIoError(err.message)
      }
    }, 3000)
    return () => clearInterval(ioPollRef.current)
  }, [ioRunning])

  async function handleRunBacktest() {
    if (btRunning) return
    setBtRunning(true)
    // Don't clear data — keep existing results visible while re-run progresses
    try {
      await fetch('/api/diagnostics/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date:    `${btConfig.startYear}-01-01`,
          end_date:      `${btConfig.endYear}-12-31`,
          max_positions: btConfig.maxPositions,
          ticker_count:  btConfig.tickerCount,
          min_score:     btConfig.minScore,
          setup_types:   btConfig.setupTypes,
        }),
      })
      const s = await fetch('/api/diagnostics/backtest/status').then(r => r.json())
      setBacktestStatus(s)
    } catch (err) {
      setBtRunning(false)
    }
  }

  async function handleRunIsOos() {
    if (ioRunning) return
    setIoRunning(true)
    setIoError(null)
    try {
      await fetch('/api/diagnostics/isoos/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          is_start_date:  `${ioConfig.isStartYear}-01-01`,
          is_end_date:    `${ioConfig.isEndYear}-12-31`,
          oos_start_date: `${ioConfig.oosStartYear}-01-01`,
          oos_end_date:   `${ioConfig.oosEndYear}-12-31`,
          max_positions:  ioConfig.maxPositions,
          min_score:      ioConfig.minScore,
          setup_types:    ioConfig.setupTypes,
        }),
      })
      const s = await fetch('/api/diagnostics/isoos/status').then(r => r.json())
      setIoStatus(s)
    } catch (err) {
      setIoRunning(false)
      setIoError(err.message)
    }
  }

  let ioResultsBlock = null
  if (source === 'isoos' && ioData && !ioRunning) {
    const is  = ioData.is?.summary  ?? {}
    const oos = ioData.oos?.summary ?? {}

    const metrics = [
      {
        key: 'win_rate',
        label: 'WIN RATE',
        fmt: v => v != null ? `${(v * 100).toFixed(1)}%` : '—',
        delta: v => v != null ? `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%` : '—',
      },
      {
        key: 'profit_factor',
        label: 'PROFIT F.',
        fmt: v => v != null ? v.toFixed(2) : '—',
        delta: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}` : '—',
      },
      {
        key: 'avg_R',
        label: 'AVG R',
        fmt: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : '—',
        delta: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : '—',
      },
      {
        key: 'max_drawdown',
        label: 'MAX DD',
        fmt: v => v != null ? `${v.toFixed(2)}R` : '—',
        delta: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : '—',
      },
      {
        key: 'total_trades',
        label: 'TRADES',
        fmt: v => v ?? '—',
        delta: () => '—',
        noColor: true,
      },
    ]

    const colStyle = { padding: '6px 12px', textAlign: 'right', fontSize: 12,
      fontFamily: '"IBM Plex Mono", monospace' }
    const hStyle   = { ...colStyle, fontSize: 9, color: 'var(--muted)',
      letterSpacing: '0.08em', fontWeight: 700 }

    ioResultsBlock = (
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Run metadata */}
        {ioData.config && (
          <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>
            IS: {ioData.config.is_start_date} → {ioData.config.is_end_date}
            {' · '}OOS: {ioData.config.oos_start_date} → {ioData.config.oos_end_date}
            {' · '}max {ioData.config.max_positions} pos
            {' · '}generated {ioData.generated_at
              ? new Date(ioData.generated_at).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
              : '—'}
          </div>
        )}

        {/* Comparison table */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)',
          borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--card-border)' }}>
                <th style={{ ...hStyle, textAlign: 'left' }}></th>
                {metrics.map(m => (
                  <th key={m.key} style={hStyle}>{m.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--card-border)' }}>
                <td style={{ ...colStyle, textAlign: 'left', fontSize: 10,
                  color: '#50d8f0', fontWeight: 700, letterSpacing: '0.06em' }}>
                  IN-SAMPLE
                </td>
                {metrics.map(m => (
                  <td key={m.key} style={{ ...colStyle, color: 'var(--text)' }}>
                    {m.fmt(is[m.key])}
                  </td>
                ))}
              </tr>
              <tr style={{ borderBottom: '1px solid var(--card-border)' }}>
                <td style={{ ...colStyle, textAlign: 'left', fontSize: 10,
                  color: '#f5a623', fontWeight: 700, letterSpacing: '0.06em' }}>
                  OUT-OF-SAMPLE
                </td>
                {metrics.map(m => (
                  <td key={m.key} style={{ ...colStyle, color: 'var(--text)' }}>
                    {m.fmt(oos[m.key])}
                  </td>
                ))}
              </tr>
              <tr>
                <td style={{ ...colStyle, textAlign: 'left', fontSize: 10,
                  color: 'var(--muted)', letterSpacing: '0.06em' }}>
                  DELTA
                </td>
                {metrics.map(m => {
                  const d = (oos[m.key] != null && is[m.key] != null)
                    ? oos[m.key] - is[m.key]
                    : null
                  const color = m.noColor || d == null
                    ? 'var(--muted)'
                    : d < 0 ? 'var(--halt)' : d > 0 ? 'var(--go)' : 'var(--muted)'
                  return (
                    <td key={m.key} style={{ ...colStyle, color, fontWeight: 700 }}>
                      {m.delta(d)}
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>

        {/* IS breakdown (collapsible) */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10 }}>
          <button onClick={() => setShowIsBreakdown(v => !v)}
            style={{ width: '100%', padding: '10px 16px', background: 'none', border: 'none',
              cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              color: 'var(--muted)', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace',
              letterSpacing: '0.08em', fontWeight: 700 }}>
            <span style={{ color: '#50d8f0' }}>IN-SAMPLE BREAKDOWN</span>
            <span>{showIsBreakdown ? '▲' : '▼'}</span>
          </button>
          {showIsBreakdown && (
            <div style={{ padding: '0 16px 16px' }}>
              <SetupBreakdownTable breakdown={ioData.is?.setup_breakdown} />
            </div>
          )}
        </div>

        {/* OOS breakdown (collapsible) */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10 }}>
          <button onClick={() => setShowOosBreakdown(v => !v)}
            style={{ width: '100%', padding: '10px 16px', background: 'none', border: 'none',
              cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              color: 'var(--muted)', fontSize: 10, fontFamily: '"IBM Plex Mono", monospace',
              letterSpacing: '0.08em', fontWeight: 700 }}>
            <span style={{ color: '#f5a623' }}>OUT-OF-SAMPLE BREAKDOWN</span>
            <span>{showOosBreakdown ? '▲' : '▼'}</span>
          </button>
          {showOosBreakdown && (
            <div style={{ padding: '0 16px 16px' }}>
              <SetupBreakdownTable breakdown={ioData.oos?.setup_breakdown} />
            </div>
          )}
        </div>
      </div>
    )
  }

  if (loading) return (
    <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
      Loading diagnostics…
    </div>
  )
  if (error) return (
    <div style={{ padding: 40, textAlign: 'center', color: 'var(--halt)', fontSize: 13 }}>
      Failed to load diagnostics: {error}
    </div>
  )

  const s       = data?.summary ?? {}
  const hasData = (s.total_trades ?? 0) > 0

  return (
    <div className="px-6 py-5 max-w-[1100px] mx-auto">
      {/* Page header */}
      <div style={{ fontFamily: '"Barlow Condensed", sans-serif', fontSize: 22, fontWeight: 700, letterSpacing: '-0.01em', color: 'var(--text)', marginBottom: 4 }}>
        Strategy Diagnostics
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
        {source === 'backtest'
          ? 'Portfolio-coordinated simulation — best params, global position cap.'
          : source === 'isoos'
          ? 'Compare in-sample vs out-of-sample performance to detect overfitting.'
          : 'Live trading performance from closed portfolio trades.'}
        {source === 'live' && !hasData && ' Close trades in the Portfolio tab to populate this report.'}
      </div>
      {source === 'backtest' && data && (
        <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 8 }}>
          {data.start_date} → {data.end_date}
          {' · '}{data.tickers_run} tickers
          {' · '}max {data.max_positions ?? '—'} positions
          {' · '}{Array.isArray(data.setup_types) ? data.setup_types.join(', ') : '—'}
        </div>
      )}

      {/* Source toggle */}
      <div style={{ display: 'flex', gap: 4, padding: '12px 20px 0', borderBottom: '1px solid var(--card-border)' }}>
        {['live', 'backtest', 'isoos'].map(src => (
          <button
            key={src}
            onClick={() => { setSource(src); setData(null); if (src !== 'isoos') setIoData(null) }}
            style={{
              padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: 700,
              fontFamily: '"IBM Plex Mono", monospace', letterSpacing: '0.05em',
              border: source === src ? '1px solid var(--accent)' : '1px solid var(--border)',
              background: source === src ? 'rgba(245,166,35,0.12)' : 'transparent',
              color: source === src ? 'var(--accent)' : 'var(--muted)',
              cursor: 'pointer',
            }}
          >
            {src === 'live' ? tr('diag.liveSource') : src === 'backtest' ? 'Full System Backtest' : 'IS / OOS Split'}
          </button>
        ))}
      </div>

      {/* Config panel — always visible on backtest tab */}
      {source === 'backtest' && (
        <div style={{
          padding: '12px 20px', borderBottom: '1px solid var(--border)',
          background: 'rgba(255,255,255,0.02)',
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <select
              value={btConfig.startYear}
              onChange={e => setBtConfig(c => ({ ...c, startYear: +e.target.value }))}
              style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' }}
            >
              {[2015,2016,2017,2018,2019,2020,2021,2022].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>→</span>
            <select
              value={btConfig.endYear}
              onChange={e => setBtConfig(c => ({ ...c, endYear: +e.target.value }))}
              style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' }}
            >
              {[2021,2022,2023,2024,2025].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
            <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
            <label style={{ fontSize: 10, color: 'var(--muted)' }}>Positions</label>
            <input
              type="number" min={1} max={20} value={btConfig.maxPositions}
              onChange={e => setBtConfig(c => ({ ...c, maxPositions: +e.target.value }))}
              style={{ width: 44, background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 6px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', textAlign: 'center' }}
            />
            <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
            <label style={{ fontSize: 10, color: 'var(--muted)' }}>Min Score</label>
            <input
              type="number" min={0} max={100} step={0.5} value={btConfig.minScore}
              onChange={e => setBtConfig(c => ({ ...c, minScore: +e.target.value }))}
              style={{ width: 44, background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 6px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', textAlign: 'center' }}
            />
            <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
            <select
              value={btConfig.tickerCount ?? ''}
              onChange={e => setBtConfig(c => ({ ...c, tickerCount: e.target.value === '' ? null : +e.target.value }))}
              style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' }}
            >
              <option value="">Full (~700)</option>
              <option value="200">Top 200</option>
              <option value="100">Top 100</option>
              <option value="50">Top 50</option>
            </select>
            <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
            {['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'].map(st => (
              <label key={st} style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 10, color: 'var(--muted)', cursor: 'pointer', fontFamily: '"IBM Plex Mono", monospace' }}>
                <input
                  type="checkbox"
                  checked={btConfig.setupTypes.includes(st)}
                  onChange={e => {
                    if (e.target.checked) {
                      setBtConfig(c => ({ ...c, setupTypes: [...c.setupTypes, st] }))
                    } else {
                      setBtConfig(c => ({ ...c, setupTypes: c.setupTypes.filter(s => s !== st) }))
                    }
                  }}
                  style={{ accentColor: 'var(--accent)' }}
                />
                {st}
              </label>
            ))}
            <span style={{ flex: 1 }} />
            <button
              onClick={handleRunBacktest}
              disabled={btRunning}
              style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: 700,
                fontFamily: '"IBM Plex Mono", monospace',
                background: 'rgba(245,166,35,0.15)', color: btRunning ? 'var(--muted)' : 'var(--accent)',
                border: `1px solid ${btRunning ? 'var(--border)' : 'rgba(245,166,35,0.35)'}`,
                cursor: btRunning ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap',
              }}
            >
              {btRunning ? tr('msg.backtestRunning') : tr('btn.runBacktest').toUpperCase()}
            </button>
          </div>
        </div>
      )}

      {/* IS/OOS config panel */}
      {source === 'isoos' && (
        <div style={{
          padding: '12px 20px', borderBottom: '1px solid var(--border)',
          background: 'rgba(255,255,255,0.02)',
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace' }}>IS</span>
            <input type="number" min={2010} max={2030} value={ioConfig.isStartYear}
              onChange={e => setIoConfig(c => ({ ...c, isStartYear: +e.target.value }))}
              style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
                color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace' }} />
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>→</span>
            <input type="number" min={2010} max={2030} value={ioConfig.isEndYear}
              onChange={e => setIoConfig(c => ({ ...c, isEndYear: +e.target.value }))}
              style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
                color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace' }} />
            <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 8 }}>OOS</span>
            <input type="number" min={2010} max={2030} value={ioConfig.oosStartYear}
              onChange={e => setIoConfig(c => ({ ...c, oosStartYear: +e.target.value }))}
              style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
                color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace' }} />
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>→</span>
            <input type="number" min={2010} max={2030} value={ioConfig.oosEndYear}
              onChange={e => setIoConfig(c => ({ ...c, oosEndYear: +e.target.value }))}
              style={{ width: 60, background: 'var(--card)', border: '1px solid var(--border)',
                color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace' }} />
            <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 8 }}>Pos</span>
            <input type="number" min={1} max={20} value={ioConfig.maxPositions}
              onChange={e => setIoConfig(c => ({ ...c, maxPositions: +e.target.value }))}
              style={{ width: 44, background: 'var(--card)', border: '1px solid var(--border)',
                color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace' }} />
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>MinScore</span>
            <input type="number" min={0} max={100} step={0.5} value={ioConfig.minScore}
              onChange={e => setIoConfig(c => ({ ...c, minScore: +e.target.value }))}
              style={{ width: 44, background: 'var(--card)', border: '1px solid var(--border)',
                color: 'var(--text)', borderRadius: 4, padding: '3px 6px', fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace' }} />
            <div style={{ display: 'flex', gap: 4, marginLeft: 4 }}>
              {['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'].map(st => (
                <label key={st} style={{ display: 'flex', alignItems: 'center', gap: 3,
                  fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace',
                  cursor: 'pointer' }}>
                  <input type="checkbox"
                    checked={ioConfig.setupTypes.includes(st)}
                    onChange={e => setIoConfig(c => ({
                      ...c,
                      setupTypes: e.target.checked
                        ? [...c.setupTypes, st]
                        : c.setupTypes.filter(x => x !== st),
                    }))} />
                  {st}
                </label>
              ))}
            </div>
            <button onClick={handleRunIsOos} disabled={ioRunning}
              style={{
                marginLeft: 'auto', padding: '4px 14px', borderRadius: 5, fontSize: 11,
                fontFamily: '"IBM Plex Mono", monospace', fontWeight: 700, letterSpacing: '0.05em',
                background: 'rgba(245,166,35,0.15)', color: ioRunning ? 'var(--muted)' : 'var(--accent)',
                border: `1px solid ${ioRunning ? 'var(--border)' : 'rgba(245,166,35,0.35)'}`,
                cursor: ioRunning ? 'not-allowed' : 'pointer',
              }}>
              {ioRunning ? 'Running…' : 'RUN IS/OOS'}
            </button>
          </div>
        </div>
      )}

      {source !== 'isoos' && (
        <>
          {/* Backtest empty state — no data yet */}
          {source === 'backtest' && !data && !loading && !btRunning && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
              {tr('msg.noBacktest')}
            </div>
          )}

          {/* Backtest first-run loading state (no existing data) */}
          {source === 'backtest' && !data && btRunning && (
            <div style={{ padding: '24px 20px' }}>
              <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 3 }}>
                {backtestStatus?.phase === 2 ? 'Phase 2/2' : 'Phase 1/2'} — {backtestStatus?.phase_label ?? 'Starting…'} — {backtestStatus?.done ?? 0} / {backtestStatus?.total ?? '…'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 8 }}>
                {backtestStatus?.phase === 2
                  ? 'Sequential day-by-day simulation. Cannot be parallelized — this is the slow part.'
                  : 'Parallel across all tickers. Usually fast.'}
              </div>
              <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, width: '100%' }}>
                <div style={{
                  height: '100%', borderRadius: 2, background: 'var(--accent)',
                  width: backtestStatus?.total > 0
                    ? `${(backtestStatus.done / backtestStatus.total * 100)}%`
                    : '0%',
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
          )}
          {/* Backtest running overlay (when re-running over existing data) */}
          {source === 'backtest' && data && btRunning && (
            <div style={{ padding: '12px 20px', background: 'rgba(245,166,35,0.06)',
                          borderBottom: '1px solid rgba(245,166,35,0.2)' }}>
              <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 3 }}>
                {backtestStatus?.phase === 2 ? 'Phase 2/2' : 'Phase 1/2'} — {backtestStatus?.phase_label ?? 'Starting…'} — {backtestStatus?.done ?? 0} / {backtestStatus?.total ?? '…'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 6 }}>
                {backtestStatus?.phase === 2
                  ? 'Sequential day-by-day simulation. Cannot be parallelized — this is the slow part.'
                  : 'Parallel across all tickers. Usually fast.'}
              </div>
              <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, width: '100%' }}>
                <div style={{
                  height: '100%', borderRadius: 2, background: 'var(--accent)',
                  width: backtestStatus?.total > 0
                    ? `${(backtestStatus.done / backtestStatus.total * 100)}%`
                    : '0%',
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
          )}

          {/* Backtest metadata badge */}
          {source === 'backtest' && data && (
            <div style={{ padding: '6px 20px', fontSize: 10, color: 'var(--muted)',
                          fontFamily: '"IBM Plex Mono", monospace',
                          borderBottom: '1px solid var(--card-border)' }}>
              Last run: {data.start_date} → {data.end_date} · {data.tickers_run} tickers · max {data.max_positions ?? '—'} positions · generated {data.generated_at
                ? new Date(data.generated_at).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
                : '—'}
            </div>
          )}

          {/* Summary cards */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <MetricCard label={tr('diag.totalTrades').toUpperCase()}  value={s.total_trades ?? 0} />
            <MetricCard label={tr('diag.profitFactor').toUpperCase()} value={s.profit_factor != null ? s.profit_factor.toFixed(2) : '—'} />
            <MetricCard label={tr('diag.winRate').toUpperCase()}      value={s.win_rate != null ? `${(s.win_rate * 100).toFixed(1)}%` : '—'} />
            <MetricCard label={tr('diag.avgR').toUpperCase()}         value={s.avg_R != null ? `${s.avg_R >= 0 ? '+' : ''}${s.avg_R.toFixed(2)}R` : '—'} />
            <MetricCard label="EXPECTANCY"    value={s.expectancy != null ? `${s.expectancy >= 0 ? '+' : ''}${s.expectancy.toFixed(2)}R` : '—'} />
            <MetricCard label={tr('diag.maxDrawdown').toUpperCase()}  value={s.max_drawdown != null ? `${s.max_drawdown.toFixed(2)}R` : '—'} sub="peak-to-trough" />
            <MetricCard label="AVG HOLD · WIN"  value={s.avg_hold_win  != null ? `${s.avg_hold_win.toFixed(1)}d`  : '—'} sub="winning trades" />
            <MetricCard label="AVG HOLD · LOSS" value={s.avg_hold_loss != null ? `${s.avg_hold_loss.toFixed(1)}d` : '—'} sub="losing trades" />
          </div>

          {/* Equity curve */}
          <SectionHeader title="EQUITY CURVE (CUMULATIVE R)" />
          <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
            <EquityCurve data={s.equity_curve_R} dates={s.equity_curve_dates} />
          </div>

          {/* Setup breakdown */}
          <SectionHeader title={tr('diag.setupBreakdown').toUpperCase()} />
          <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
            <SetupBreakdownTable breakdown={data?.setup_breakdown} />
          </div>

          {/* Ticker distribution */}
          <SectionHeader title={tr('diag.tickerDist').toUpperCase()} />
          <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
            <TickerDistribution rows={data?.ticker_distribution} />
          </div>

          {/* Regime performance */}
          <SectionHeader title={tr('diag.regimePerf').toUpperCase()} />
          <RegimePerformance perf={data?.regime_performance} />

          {/* Selective analysis — only shown when there is SELECTIVE-regime data */}
          {data?.selective_analysis?.total_selective_trades > 0 && (
            <>
              <SectionHeader title="SELECTIVE REGIME ANALYSIS" />
              <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
                <SelectiveAnalysis data={data.selective_analysis} />
              </div>
            </>
          )}

          {/* R-Multiple Distribution */}
          {data?.r_distribution && (
            <>
              <SectionHeader title="R-MULTIPLE DISTRIBUTION" />
              <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
                <RMultipleDistribution rows={data.r_distribution} />
              </div>
            </>
          )}

          {/* Market Regime Distribution */}
          {data?.regime_distribution && Object.keys(data.regime_distribution).length > 0 && (
            <>
              <SectionHeader title="MARKET REGIME DISTRIBUTION (BACKTEST PERIOD)" />
              <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
                <RegimeDistributionPanel dist={data.regime_distribution} />
              </div>
            </>
          )}

          {/* Setup Score Distribution */}
          {data?.score_distribution && (
            <>
              <SectionHeader title="SETUP SCORE DISTRIBUTION (PRE-GATE)" />
              <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
                <ScoreDistributionPanel rows={data.score_distribution} />
              </div>
            </>
          )}
        </>
      )}

      {/* IS/OOS running progress */}
      {source === 'isoos' && ioRunning && (
        <div style={{ padding: '24px 20px' }}>
          <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 3 }}>
            {ioStatus?.phase === 'oos' ? 'OOS period (2/2)' : 'IS period (1/2)'} — {ioStatus?.step_label ?? 'Starting…'} — {ioStatus?.current ?? 0} / {ioStatus?.total ?? '…'}
          </div>
          <div style={{ fontSize: 9, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 8 }}>
            {ioStatus?.step_label === 'Simulating portfolio day by day'
              ? 'Sequential day-by-day simulation. Cannot be parallelized — this is the slow part.'
              : 'Parallel across all tickers. Usually fast.'}
          </div>
          <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, width: '100%' }}>
            <div style={{
              height: '100%', borderRadius: 2, background: 'var(--accent)',
              width: ioStatus?.total > 0 ? `${(ioStatus.current / ioStatus.total * 100)}%` : '0%',
              transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      )}

      {/* IS/OOS empty state */}
      {source === 'isoos' && !ioData && !ioRunning && !ioError && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
          Configure IS and OOS date ranges above, then click RUN IS/OOS.
        </div>
      )}

      {/* IS/OOS error state */}
      {source === 'isoos' && ioError && (
        <div style={{ padding: '16px 20px', color: 'var(--halt)', fontSize: 12,
          fontFamily: '"IBM Plex Mono", monospace' }}>
          Error: {ioError}
          <button onClick={handleRunIsOos} style={{ marginLeft: 12, fontSize: 11, color: 'var(--accent)',
            background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
            Retry
          </button>
        </div>
      )}

      {/* IS/OOS results */}
      {ioResultsBlock}
    </div>
  )
}
