import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'

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
function EquityCurve({ data }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !data || data.length === 0) return

    const chart = createChart(ref.current, {
      width:  ref.current.clientWidth,
      height: 160,
      layout:      { background: { color: 'transparent' }, textColor: '#64748b' },
      grid:        { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      timeScale:   { visible: false },
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

    // Generate synthetic ISO dates starting from 2020-01-01 (one per trade)
    const startMs = new Date('2020-01-01').getTime()
    const DAY_MS  = 86400 * 1000
    series.setData(data.map((v, i) => ({
      time:  new Date(startMs + i * DAY_MS).toISOString().slice(0, 10),
      value: v,
    })))
    chart.timeScale().fitContent()

    return () => chart.remove()
  }, [data])

  if (!data || data.length === 0) return <EmptyState message="No equity curve data — close some trades first" />
  return <div ref={ref} style={{ width: '100%', height: 160 }} />
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
    minScore:     0,
    setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
  })
  const [ioConfig, setIoConfig] = useState({
    isStartYear:  2017,
    isEndYear:    2021,
    oosStartYear: 2022,
    oosEndYear:   2024,
    maxPositions: 4,
    minScore:     0,
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
          setBtRunning(false)
          clearInterval(pollRef.current)
          if (s.status === 'completed') {
            const r = await fetch('/api/diagnostics/backtest', { cache: 'no-store' })
            if (r.ok) setData(await r.json())
          }
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
            {src === 'live' ? 'Live Trades' : src === 'backtest' ? 'Full System Backtest' : 'IS / OOS Split'}
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
              {btRunning ? 'Running…' : 'RUN BACKTEST'}
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
              No backtest data. Configure above and run to generate a strategy audit.
            </div>
          )}

          {/* Backtest first-run loading state (no existing data) */}
          {source === 'backtest' && !data && btRunning && (
            <div style={{ padding: '24px 20px' }}>
              <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 6 }}>
                Running backtest — {backtestStatus?.done ?? 0} / {backtestStatus?.total ?? '…'}…
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
              <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 6 }}>
                Re-running backtest — {backtestStatus?.done ?? 0} / {backtestStatus?.total ?? '…'}…
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
            <MetricCard label="TOTAL TRADES"  value={s.total_trades ?? 0} />
            <MetricCard label="PROFIT FACTOR" value={s.profit_factor != null ? s.profit_factor.toFixed(2) : '—'} />
            <MetricCard label="WIN RATE"      value={s.win_rate != null ? `${(s.win_rate * 100).toFixed(1)}%` : '—'} />
            <MetricCard label="AVG R"         value={s.avg_R != null ? `${s.avg_R >= 0 ? '+' : ''}${s.avg_R.toFixed(2)}R` : '—'} />
            <MetricCard label="EXPECTANCY"    value={s.expectancy != null ? `${s.expectancy >= 0 ? '+' : ''}${s.expectancy.toFixed(2)}R` : '—'} />
            <MetricCard label="MAX DRAWDOWN"  value={s.max_drawdown != null ? `${s.max_drawdown.toFixed(2)}R` : '—'} sub="peak-to-trough" />
          </div>

          {/* Equity curve */}
          <SectionHeader title="EQUITY CURVE (CUMULATIVE R)" />
          <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
            <EquityCurve data={s.equity_curve_R} />
          </div>

          {/* Setup breakdown */}
          <SectionHeader title="PERFORMANCE BY SETUP TYPE" />
          <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
            <SetupBreakdownTable breakdown={data?.setup_breakdown} />
          </div>

          {/* Ticker distribution */}
          <SectionHeader title="TRADE CONCENTRATION BY TICKER" />
          <div style={{ background: 'var(--card)', border: '1px solid var(--card-border)', borderRadius: 10, padding: 16 }}>
            <TickerDistribution rows={data?.ticker_distribution} />
          </div>

          {/* Regime performance */}
          <SectionHeader title="PERFORMANCE BY MARKET REGIME" />
          <RegimePerformance perf={data?.regime_performance} />
        </>
      )}

      {/* IS/OOS running progress */}
      {source === 'isoos' && ioRunning && (
        <div style={{ padding: '24px 20px' }}>
          <div style={{ fontSize: 10, color: 'var(--accent)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 6 }}>
            {ioStatus?.phase === 'oos' ? 'Running OOS period' : 'Running IS period'} — {ioStatus?.current ?? 0} / {ioStatus?.total ?? '…'}…
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
