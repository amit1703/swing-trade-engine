/**
 * BacktestPanel — Dev-only historical replay UI + Walk-Forward Validation
 *
 * Renders ONLY when devMode === true (gated in App.jsx).
 * Two tabs: "Replay" (existing single-ticker backtest) and "Walk-Forward" (WFO).
 */
import { useState } from 'react'
import { runBacktest, fetchBacktestResults, wfoDownload, wfoDownloadStatus, wfoRun, wfoStatus, wfoResults, wfoExportUrl, wfoAudit } from '../api.js'

const SETUP_OPTIONS = ['VCP', 'PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE']

function defaultStartDate() {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 1)
  return d.toISOString().slice(0, 10)
}

// ─────────────────────────────────────────────────────────────────────────────
// Walk-Forward Tab helpers
// ─────────────────────────────────────────────────────────────────────────────

const WFO_SETUP_OPTIONS = ['VCP', 'PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE']

function WalkForwardTab() {
  const [tickerInput,   setTickerInput  ] = useState('')
  const [setupTypes,    setSetupTypes   ] = useState([...WFO_SETUP_OPTIONS])
  const [isMonths,      setIsMonths     ] = useState(24)
  const [oosMonths,     setOosMonths    ] = useState(3)
  const [stepMonths,    setStepMonths   ] = useState(3)
  const [minTrades,     setMinTrades    ] = useState(20)
  const [downloading,   setDownloading  ] = useState(false)
  const [dlStatus,      setDlStatus     ] = useState('')
  const [running,       setRunning      ] = useState(false)
  const [progressPct,   setProgressPct  ] = useState(0)
  const [status,        setStatus       ] = useState('')
  const [result,        setResult       ] = useState(null)
  const [runId,         setRunId        ] = useState(null)
  const [viewMode,      setViewMode     ] = useState('table')
  const [expanded,      setExpanded     ] = useState({})
  const [auditData,     setAuditData    ] = useState(null)
  const [auditLoading,  setAuditLoading ] = useState(false)
  const [auditPeriod,   setAuditPeriod  ] = useState('oos')

  const parsedTickers = () =>
    tickerInput.split(',').map(t => t.trim().toUpperCase()).filter(Boolean)

  const toggleSetup = (s) => setSetupTypes(prev =>
    prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
  )

  const handleDownload = async () => {
    const tickers = parsedTickers()
    if (tickers.length === 0) return
    setDownloading(true)
    setDlStatus('Starting download…')
    try {
      const { job_id, total_tickers } = await wfoDownload(tickers)
      setDlStatus(`Downloading ${total_tickers} tickers…`)
      const interval = setInterval(async () => {
        const st = await wfoDownloadStatus(job_id)
        setDlStatus(`Downloaded ${st.tickers_completed}/${st.total_tickers}`)
        if (st.status !== 'running') {
          clearInterval(interval)
          setDlStatus(`Download ${st.status === 'done' ? 'complete' : 'failed'} (${st.tickers_completed}/${st.total_tickers})`)
          setDownloading(false)
        }
      }, 2000)
    } catch {
      setDlStatus('Download error')
      setDownloading(false)
    }
  }

  const handleRun = async () => {
    const tickers = parsedTickers()
    if (tickers.length === 0 || setupTypes.length === 0) return
    setRunning(true)
    setProgressPct(0)
    setResult(null)
    setStatus('Starting walk-forward run…')
    try {
      const { run_id } = await wfoRun({
        tickers, setup_types: setupTypes,
        is_months: isMonths, oos_months: oosMonths,
        step_months: stepMonths, min_trades: minTrades,
      })
      setRunId(run_id)
      const interval = setInterval(async () => {
        const st = await wfoStatus(run_id)
        setProgressPct(st.progress_pct || 0)
        setStatus(`Window ${st.windows_completed}/${st.total_windows} (${st.progress_pct || 0}%)`)
        if (st.status === 'done') {
          clearInterval(interval)
          const res = await wfoResults(run_id)
          setResult(res.result)
          setStatus(`Complete — ${res.result?.windows?.length || 0} windows`)
          setRunning(false)
        } else if (st.status === 'error') {
          clearInterval(interval)
          setStatus('Run failed — check server logs')
          setRunning(false)
        }
      }, 3000)
    } catch {
      setStatus('Error starting run')
      setRunning(false)
    }
  }

  const handleAudit = async (period) => {
    if (!runId) return
    setAuditLoading(true)
    setAuditPeriod(period)
    try {
      const res = await wfoAudit(runId, period)
      setAuditData(res.audit)
      setViewMode('audit')
    } catch { /* ignore */ }
    finally { setAuditLoading(false) }
  }

  const inputStyle = {
    background: '#1a1a2e', color: '#e0e0e0', border: '1px solid #333',
    borderRadius: 4, padding: '4px 8px', fontSize: 13,
  }
  const btnStyle = (color = '#2563eb', disabled = false) => ({
    background: disabled ? '#333' : color, color: '#fff', border: 'none',
    borderRadius: 4, padding: '6px 14px', cursor: disabled ? 'not-allowed' : 'pointer',
    fontSize: 13, opacity: disabled ? 0.6 : 1,
  })

  return (
    <div style={{ padding: 16, color: '#e0e0e0', fontFamily: 'monospace' }}>
      {/* Controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>TICKERS</div>
          <input
            style={{ ...inputStyle, width: 280 }}
            placeholder="AAPL, NVDA, MSFT, …"
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value)}
          />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>IS MONTHS</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={isMonths} onChange={e => setIsMonths(+e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>OOS MONTHS</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={oosMonths} onChange={e => setOosMonths(+e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>STEP MONTHS</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={stepMonths} onChange={e => setStepMonths(+e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>MIN TRADES</div>
          <input style={{ ...inputStyle, width: 60 }} type="number"
            value={minTrades} onChange={e => setMinTrades(+e.target.value)} />
        </div>
      </div>

      {/* Setup type checkboxes */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        {WFO_SETUP_OPTIONS.map(s => (
          <label key={s} style={{ fontSize: 12, cursor: 'pointer' }}>
            <input type="checkbox" checked={setupTypes.includes(s)}
              onChange={() => toggleSetup(s)} style={{ marginRight: 4 }} />
            {s}
          </label>
        ))}
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'center' }}>
        <button style={btnStyle('#444', downloading)} onClick={handleDownload} disabled={downloading}>
          {downloading ? 'Downloading…' : 'Download Cache'}
        </button>
        <button style={btnStyle('#2563eb', running)} onClick={handleRun} disabled={running}>
          {running ? 'Running…' : 'Run Walk-Forward'}
        </button>
        {result && runId && (
          <a href={wfoExportUrl(runId)} download style={{ ...btnStyle('#166534'), textDecoration: 'none' }}>
            Export CSV
          </a>
        )}
      </div>

      {/* Status messages */}
      {dlStatus && <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{dlStatus}</div>}
      {status    && <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{status}</div>}

      {/* Progress bar */}
      {running && (
        <div style={{ background: '#1a1a2e', borderRadius: 4, height: 8, marginBottom: 12 }}>
          <div style={{ background: '#2563eb', width: `${progressPct}%`, height: '100%', borderRadius: 4, transition: 'width 0.3s' }} />
        </div>
      )}

      {/* View toggle */}
      {result && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
          {[['table', 'Windows Table'], ['chart', 'IS/OOS Chart'], ['heatmap', 'Heatmap']].map(([v, label]) => (
            <button key={v} onClick={() => setViewMode(v)}
              style={btnStyle(viewMode === v ? '#2563eb' : '#333')}>
              {label}
            </button>
          ))}
          <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
            {[['oos','Audit OOS'],['is','Audit IS'],['all','Audit ALL']].map(([p, label]) => (
              <button key={p} disabled={auditLoading}
                onClick={() => handleAudit(p)}
                style={btnStyle(viewMode === 'audit' && auditPeriod === p ? '#7c3aed' : '#374151', auditLoading)}>
                {auditLoading && auditPeriod === p ? '…' : label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* View: Windows Table */}
      {result && viewMode === 'table' && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#1a1a2e', color: '#888' }}>
                {['#', 'IS Period', 'OOS Period', 'IS WR%', 'OOS WR%', 'IS Avg R', 'OOS Avg R',
                  'IS Expect', 'OOS Expect', 'Stability', 'IS Trades', 'OOS Trades', '✓'].map(h => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #333' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.windows.map(w => {
                const isRel   = w.is_metrics.reliable && w.oos_metrics.reliable
                const stabBad = w.stability_score < 0.6
                const rowBase = { opacity: isRel ? 1 : 0.5, fontStyle: isRel ? 'normal' : 'italic', cursor: 'pointer' }
                return [
                  <tr key={w.window_num}
                    onClick={() => setExpanded(prev => ({ ...prev, [w.window_num]: !prev[w.window_num] }))}
                    onMouseEnter={e => e.currentTarget.style.background = '#1a2040'}
                    onMouseLeave={e => e.currentTarget.style.background = ''}
                    style={rowBase}>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.window_num}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: '#888' }}>{w.is_start.slice(0, 7)}→{w.is_end.slice(0, 7)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: '#888' }}>{w.oos_start.slice(0, 7)}→{w.oos_end.slice(0, 7)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.win_rate.toFixed(1)}%</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.win_rate.toFixed(1)}%</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.avg_r.toFixed(2)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.avg_r.toFixed(2)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.expectancy.toFixed(3)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.expectancy.toFixed(3)}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: stabBad ? '#ef4444' : '#4ade80', fontWeight: stabBad ? 700 : 400 }}>
                      {w.stability_score.toFixed(2)}
                    </td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.is_metrics.trades}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222' }}>{w.oos_metrics.trades}</td>
                    <td style={{ padding: '5px 8px', borderBottom: '1px solid #222', color: isRel ? '#4ade80' : '#f59e0b' }}>{isRel ? '✓' : '!'}</td>
                  </tr>,
                  expanded[w.window_num] && (
                    <tr key={`${w.window_num}-detail`}>
                      <td colSpan={13} style={{ padding: '8px 16px', background: '#111', borderBottom: '1px solid #333' }}>
                        <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ color: '#888' }}>
                              <th style={{ textAlign: 'left', padding: '3px 6px' }}>Setup</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>IS Trades</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>OOS Trades</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>IS WR%</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>OOS WR%</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>IS Expect</th>
                              <th style={{ textAlign: 'right', padding: '3px 6px' }}>OOS Expect</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(w.per_setup).map(([stype, d]) => (
                              <tr key={stype}>
                                <td style={{ padding: '3px 6px', color: '#60a5fa' }}>{stype}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.is.trades}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.oos.trades}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.is.win_rate.toFixed(1)}%</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.oos.win_rate.toFixed(1)}%</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.is.expectancy.toFixed(3)}</td>
                                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{d.oos.expectancy.toFixed(3)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )
                ]
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* View: IS/OOS Bar Chart */}
      {result && viewMode === 'chart' && (
        <WFOBarChart windows={result.windows} />
      )}

      {/* View: Heatmap */}
      {result && viewMode === 'heatmap' && (
        <WFOHeatmap windows={result.windows} setupTypes={result.setup_types} />
      )}

      {/* View: Engine Audit */}
      {viewMode === 'audit' && auditData && (
        <AuditPanel audit={auditData} />
      )}
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// Engine Audit Panel
// ─────────────────────────────────────────────────────────────────────────────

const CLS_COLORS = {
  robust:             { bg: '#14532d', border: '#16a34a', text: '#4ade80' },
  neutral:            { bg: '#1e3a5f', border: '#3b82f6', text: '#93c5fd' },
  weak:               { bg: '#450a0a', border: '#dc2626', text: '#f87171' },
  'under-filtered':   { bg: '#431407', border: '#ea580c', text: '#fb923c' },
  'under-triggered':  { bg: '#3b1c6e', border: '#8b5cf6', text: '#c4b5fd' },
  insufficient_data:  { bg: '#1c1c1c', border: '#555',    text: '#aaa'    },
  no_data:            { bg: '#111',    border: '#333',    text: '#555'    },
}

function ClsBadge({ cls }) {
  const c = CLS_COLORS[cls] || CLS_COLORS.insufficient_data
  return (
    <span style={{
      background: c.bg, border: `1px solid ${c.border}`, color: c.text,
      borderRadius: 3, padding: '2px 7px', fontSize: 10, fontWeight: 700,
      letterSpacing: '0.08em', textTransform: 'uppercase',
    }}>{cls}</span>
  )
}

function MetricRow({ label, value, highlight }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '3px 0', borderBottom: '1px solid #1e1e2e' }}>
      <span style={{ fontSize: 11, color: '#888' }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'monospace',
        color: highlight || '#e0e0e0' }}>{value}</span>
    </div>
  )
}

function RBar({ label, count, total, color }) {
  const pct = total > 0 ? count / total * 100 : 0
  return (
    <div style={{ marginBottom: 3 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#888', marginBottom: 2 }}>
        <span>{label}</span><span>{count} ({pct.toFixed(0)}%)</span>
      </div>
      <div style={{ background: '#1a1a2e', borderRadius: 2, height: 6 }}>
        <div style={{ background: color, width: `${pct}%`, height: '100%', borderRadius: 2, transition: 'width 0.3s' }} />
      </div>
    </div>
  )
}

function EngineCard({ engine, report, cls, diagnosis }) {
  const el  = report.engine_level
  const q   = report.quality
  const str = report.structural
  const ex  = report.exit_breakdown
  const fa  = report.failure_analysis
  const pq  = report.pattern_quality
  const rd  = q.r_distribution
  const total = el.trades_executed

  const rColor = (v) => v > 0 ? '#4ade80' : v < 0 ? '#f87171' : '#888'
  const pctColor = (v, threshold) => v >= threshold ? '#4ade80' : v >= threshold * 0.7 ? '#fbbf24' : '#f87171'

  if (total === 0) return (
    <div style={{ background: '#0d0d1a', border: '1px solid #222', borderRadius: 6, padding: 14, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#555', fontFamily: 'monospace' }}>{engine}</span>
        <ClsBadge cls={cls} />
      </div>
      <div style={{ fontSize: 11, color: '#555' }}>{diagnosis}</div>
    </div>
  )

  return (
    <div style={{ background: '#0d0d1a', border: `1px solid ${CLS_COLORS[cls]?.border || '#333'}`,
      borderRadius: 6, padding: 14, marginBottom: 12 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#e0e0e0', fontFamily: 'monospace' }}>{engine}</span>
        <ClsBadge cls={cls} />
        {!report.sufficient_data && (
          <span style={{ fontSize: 10, color: '#f59e0b' }}>⚠ low sample</span>
        )}
        <span style={{ fontSize: 11, color: '#555', marginLeft: 'auto' }}>{total} trades</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>

        {/* Column 1: Engine Level + Quality */}
        <div>
          <div style={{ fontSize: 10, color: '#60a5fa', fontWeight: 700, letterSpacing: '0.1em',
            marginBottom: 6, textTransform: 'uppercase' }}>Engine Level</div>
          <MetricRow label="Win Rate"       value={`${el.win_rate.toFixed(1)}%`}    highlight={pctColor(el.win_rate, 50)} />
          <MetricRow label="Avg R"          value={el.avg_R.toFixed(3)}              highlight={rColor(el.avg_R)} />
          <MetricRow label="Expectancy"     value={`${el.expectancy >= 0 ? '+' : ''}${el.expectancy.toFixed(3)}R`} highlight={rColor(el.expectancy)} />
          <MetricRow label="Avg Return"     value={`${el.avg_trade_return_pct >= 0 ? '+' : ''}${el.avg_trade_return_pct.toFixed(2)}%`} highlight={rColor(el.avg_trade_return_pct)} />
          <MetricRow label="Net Profit"     value={`${el.net_profit_pct >= 0 ? '+' : ''}${el.net_profit_pct.toFixed(1)}%`} highlight={rColor(el.net_profit_pct)} />
          <MetricRow label="Profit Factor"  value={el.profit_factor >= 9999 ? '∞' : el.profit_factor.toFixed(2)} highlight={el.profit_factor >= 1.5 ? '#4ade80' : el.profit_factor >= 1 ? '#fbbf24' : '#f87171'} />

          <div style={{ fontSize: 10, color: '#60a5fa', fontWeight: 700, letterSpacing: '0.1em',
            marginTop: 10, marginBottom: 6, textTransform: 'uppercase' }}>Quality</div>
          <MetricRow label="Avg R (wins)"   value={`+${q.avg_R_winners.toFixed(3)}R`}  highlight="#4ade80" />
          <MetricRow label="Avg R (losses)" value={`${q.avg_R_losers.toFixed(3)}R`}    highlight="#f87171" />
          <MetricRow label="Median R"       value={q.median_R.toFixed(3)}               highlight={rColor(q.median_R)} />
          <MetricRow label="Largest Win"    value={`+${q.largest_winner_R.toFixed(2)}R`} highlight="#4ade80" />
          <MetricRow label="Largest Loss"   value={`${q.largest_loser_R.toFixed(2)}R`}  highlight="#f87171" />
        </div>

        {/* Column 2: Structural + Exit breakdown */}
        <div>
          <div style={{ fontSize: 10, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.1em',
            marginBottom: 6, textTransform: 'uppercase' }}>Structural</div>
          <MetricRow label="Avg Hold (all)"     value={`${str.avg_holding_days.toFixed(1)}d`} />
          <MetricRow label="Avg Hold (wins)"    value={`${str.avg_holding_winners.toFixed(1)}d`}  highlight="#4ade80" />
          <MetricRow label="Avg Hold (losses)"  value={`${str.avg_holding_losers.toFixed(1)}d`}   highlight="#f87171" />
          <MetricRow label="Avg Risk %"         value={`${str.avg_risk_pct.toFixed(2)}%`} />
          <MetricRow label="Planned R:R"        value={`${str.avg_planned_rr.toFixed(2)}:1`}   highlight={str.avg_planned_rr >= 2 ? '#4ade80' : str.avg_planned_rr >= 1.5 ? '#fbbf24' : '#f87171'} />

          <div style={{ fontSize: 10, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.1em',
            marginTop: 10, marginBottom: 6, textTransform: 'uppercase' }}>Exit Breakdown</div>
          <RBar label="TARGET hits" count={ex.count_targets} total={total} color="#4ade80" />
          <RBar label="STOP outs"   count={ex.count_stops}   total={total} color="#f87171" />
          <RBar label="EOD exits"   count={ex.count_eod}     total={total} color="#fbbf24" />

          <div style={{ fontSize: 10, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.1em',
            marginTop: 10, marginBottom: 6, textTransform: 'uppercase' }}>Pattern Quality</div>
          <MetricRow label="Target Hit Rate"  value={`${pq.target_hit_rate.toFixed(1)}%`}  highlight={pctColor(pq.target_hit_rate, 35)} />
          <MetricRow label="Wins via TARGET"  value={pq.wins_via_target} />
          <MetricRow label="Wins via EOD"     value={pq.wins_via_eod} />
        </div>

        {/* Column 3: Failure Analysis + R Distribution */}
        <div>
          <div style={{ fontSize: 10, color: '#fb923c', fontWeight: 700, letterSpacing: '0.1em',
            marginBottom: 6, textTransform: 'uppercase' }}>Failure Analysis</div>
          {el.loss_count > 0 ? (
            <>
              <MetricRow label="Failed Breakouts"    value={`${fa.pct_failed_breakouts.toFixed(1)}% (${fa.count_failed_breakouts})`}    highlight={fa.pct_failed_breakouts > 70 ? '#f87171' : '#e0e0e0'} />
              <MetricRow label="Immed. Reversals ≤3d" value={`${fa.pct_immediate_reversals.toFixed(1)}% (${fa.count_immediate_reversals})`} highlight={fa.pct_immediate_reversals > 30 ? '#f87171' : '#e0e0e0'} />
              <MetricRow label="Quick Stops ≤5d"     value={`${fa.pct_quick_stops_5d.toFixed(1)}%`}                                       highlight={fa.pct_quick_stops_5d > 50 ? '#fbbf24' : '#e0e0e0'} />
            </>
          ) : (
            <div style={{ fontSize: 11, color: '#555' }}>No losses recorded</div>
          )}

          <div style={{ fontSize: 10, color: '#fb923c', fontWeight: 700, letterSpacing: '0.1em',
            marginTop: 10, marginBottom: 6, textTransform: 'uppercase' }}>R Distribution</div>
          <RBar label="< -1R"    count={rd.lt_neg1}   total={total} color="#7f1d1d" />
          <RBar label="-1R → 0"  count={rd.neg1_to_0} total={total} color="#f87171" />
          <RBar label="0 → 1R"   count={rd.zero_to_1} total={total} color="#fbbf24" />
          <RBar label="1R → 2R"  count={rd.one_to_2}  total={total} color="#86efac" />
          <RBar label="> 2R"     count={rd.gt_2}       total={total} color="#4ade80" />

          <div style={{ fontSize: 10, color: '#fb923c', fontWeight: 700, letterSpacing: '0.1em',
            marginTop: 10, marginBottom: 6, textTransform: 'uppercase' }}>Diagnosis</div>
          <div style={{ fontSize: 11, color: '#aaa', lineHeight: 1.5 }}>{diagnosis}</div>
        </div>
      </div>
    </div>
  )
}

function AuditPanel({ audit }) {
  const { overall, by_engine, classifications, summary, engine_order, period, total_trades } = audit
  const rd = overall.r_distribution || {}

  return (
    <div style={{ fontFamily: 'monospace', color: '#e0e0e0' }}>
      {/* Overall banner */}
      <div style={{ background: '#0d1117', border: '1px solid #333', borderRadius: 6,
        padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 32, flexWrap: 'wrap',
        alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Period</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#60a5fa' }}>{period}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Total Trades</div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{total_trades}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Win Rate</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: overall.win_rate >= 50 ? '#4ade80' : '#f87171' }}>{overall.win_rate.toFixed(1)}%</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Expectancy</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: overall.expectancy >= 0 ? '#4ade80' : '#f87171' }}>{overall.expectancy >= 0 ? '+' : ''}{overall.expectancy.toFixed(3)}R</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Avg R</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: overall.avg_R >= 0 ? '#4ade80' : '#f87171' }}>{overall.avg_R.toFixed(3)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Net Profit</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: overall.net_profit_pct >= 0 ? '#4ade80' : '#f87171' }}>{overall.net_profit_pct >= 0 ? '+' : ''}{overall.net_profit_pct.toFixed(1)}%</div>
        </div>
        {/* Mini R distribution */}
        <div style={{ marginLeft: 'auto' }}>
          <div style={{ fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>R Distribution</div>
          <div style={{ display: 'flex', gap: 3 }}>
            {[['<-1R', rd.lt_neg1, '#7f1d1d'], ['-1→0', rd.neg1_to_0, '#ef4444'],
              ['0→1R', rd.zero_to_1, '#fbbf24'], ['1→2R', rd.one_to_2, '#86efac'], ['>2R', rd.gt_2, '#4ade80']
            ].map(([label, count, color]) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div style={{ width: 36, height: 36, background: color, borderRadius: 4, opacity: 0.85,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 700, color: '#000' }}>{count}</div>
                <div style={{ fontSize: 8, color: '#555', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Per-engine cards (sorted by trade count) */}
      {engine_order.map(engine => (
        <EngineCard
          key={engine}
          engine={engine}
          report={by_engine[engine]}
          cls={classifications[engine] || 'insufficient_data'}
          diagnosis={summary[engine] || ''}
        />
      ))}
    </div>
  )
}


function WFOBarChart({ windows }) {
  const W = 28, GAP = 4, H = 160, PAD = { top: 10, bottom: 30, left: 40, right: 10 }
  const totalW = windows.length * (W * 2 + GAP + 6) + PAD.left + PAD.right

  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>IS Win Rate (blue) vs OOS Win Rate (orange) per window</div>
      <svg width={totalW} height={H + PAD.top + PAD.bottom} style={{ fontFamily: 'monospace' }}>
        {[0, 25, 50, 75, 100].map(pct => {
          const y = PAD.top + H - (pct / 100) * H
          return (
            <g key={pct}>
              <line x1={PAD.left - 4} x2={totalW - PAD.right} y1={y} y2={y}
                stroke="#333" strokeWidth={pct === 0 ? 1 : 0.5} />
              <text x={PAD.left - 8} y={y + 4} textAnchor="end" fill="#888" fontSize={9}>{pct}%</text>
            </g>
          )
        })}
        {windows.map((w, i) => {
          const x0 = PAD.left + i * (W * 2 + GAP + 6)
          const isH  = (w.is_metrics.win_rate / 100) * H
          const oosH = (w.oos_metrics.win_rate / 100) * H
          return (
            <g key={w.window_num}>
              <rect x={x0} y={PAD.top + H - isH} width={W} height={isH} fill="#2563eb" opacity={0.85} />
              <rect x={x0 + W + 2} y={PAD.top + H - oosH} width={W} height={oosH} fill="#f97316" opacity={0.85} />
              <text x={x0 + W} y={PAD.top + H + 16} textAnchor="middle" fill="#888" fontSize={9}>{w.window_num}</text>
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: '#888', marginTop: 4 }}>
        <span><span style={{ color: '#2563eb' }}>■</span> IS Win Rate</span>
        <span><span style={{ color: '#f97316' }}>■</span> OOS Win Rate</span>
      </div>
    </div>
  )
}


function WFOHeatmap({ windows, setupTypes }) {
  const CELL_W = 32, CELL_H = 24

  function expectancyToColor(v) {
    if (v >= 0.5)  return '#166534'
    if (v >= 0.2)  return '#15803d'
    if (v >= 0.0)  return '#4ade80'
    if (v >= -0.2) return '#fbbf24'
    if (v >= -0.5) return '#ef4444'
    return '#7f1d1d'
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>OOS Expectancy by Setup × Window (green=positive, red=negative)</div>
      <div style={{ display: 'flex' }}>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-around', paddingRight: 8, paddingTop: 20 }}>
          {setupTypes.map(s => (
            <div key={s} style={{ height: CELL_H, lineHeight: `${CELL_H}px`, fontSize: 10, color: '#888', whiteSpace: 'nowrap' }}>{s}</div>
          ))}
        </div>
        <div>
          <div style={{ display: 'flex' }}>
            {windows.map(w => (
              <div key={w.window_num} style={{ width: CELL_W, textAlign: 'center', fontSize: 9, color: '#666' }}>{w.window_num}</div>
            ))}
          </div>
          {setupTypes.map(stype => (
            <div key={stype} style={{ display: 'flex' }}>
              {windows.map(w => {
                const exp = w.per_setup?.[stype]?.oos?.expectancy ?? 0
                return (
                  <div key={w.window_num} title={`${stype} W${w.window_num}: ${exp.toFixed(3)}`}
                    style={{
                      width: CELL_W, height: CELL_H,
                      background: expectancyToColor(exp),
                      border: '1px solid #111',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 8, color: '#fff',
                    }}>
                    {Math.abs(exp) > 0.05 ? exp.toFixed(2) : ''}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// Main BacktestPanel (tabbed)
// ─────────────────────────────────────────────────────────────────────────────

export default function BacktestPanel() {
  const [activeTab,   setActiveTab  ] = useState('replay')
  const [tickerInput, setTickerInput] = useState('')
  const [startDate,   setStartDate  ] = useState(defaultStartDate)
  const [endDate,     setEndDate    ] = useState(() => new Date().toISOString().slice(0, 10))
  const [setupTypes,  setSetupTypes ] = useState(['VCP', 'PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'])
  const [running,     setRunning    ] = useState(false)
  const [status,      setStatus     ] = useState('')
  const [results,     setResults    ] = useState([])

  const toggleSetup = (s) => setSetupTypes(prev =>
    prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
  )

  const handleRun = async () => {
    const tickers = tickerInput
      .split(',')
      .map(t => t.trim().toUpperCase())
      .filter(Boolean)

    if (tickers.length === 0 || setupTypes.length === 0) return

    if (startDate >= endDate) {
      setStatus('Error: start date must be before end date')
      return
    }

    setRunning(true)
    setResults([])
    setStatus(`Starting ${tickers.length} backtest(s)…`)

    for (const ticker of tickers) {
      try {
        setStatus(`Queuing ${ticker}…`)
        await runBacktest(ticker, startDate, endDate, setupTypes)
      } catch (err) {
        console.warn('[BacktestPanel] runBacktest failed for', ticker, err)
      }
    }

    setStatus('Waiting for results…')

    const allResults = []
    const seen = new Set()
    const deadline = Date.now() + 90_000

    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 5000))

      for (const ticker of tickers) {
        try {
          const res = await fetchBacktestResults(ticker)
          for (const row of (res.results || [])) {
            if (!seen.has(row.run_id)) {
              seen.add(row.run_id)
              allResults.push(row)
            }
          }
        } catch (err) {
          console.warn('[BacktestPanel] fetch failed for', ticker, err)
        }
      }

      const tickersWithResults = new Set(allResults.map(r => r.ticker))
      if (tickers.every(t => tickersWithResults.has(t))) break
    }

    setResults(allResults)
    setStatus(allResults.length > 0 ? `Done — ${allResults.length} result(s)` : 'No results yet. Check backend logs.')
    setRunning(false)
  }

  return (
    <div style={{ fontFamily: 'Barlow Condensed, sans-serif' }}>
      {/* Tab navigation */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #333', marginBottom: 12 }}>
        {[['replay', 'Replay'], ['wfo', 'Walk-Forward']].map(([id, label]) => (
          <button key={id} onClick={() => setActiveTab(id)}
            style={{
              background: activeTab === id ? '#1a2040' : 'transparent',
              color: activeTab === id ? '#60a5fa' : '#888',
              border: 'none',
              borderBottom: activeTab === id ? '2px solid #2563eb' : '2px solid transparent',
              padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontFamily: 'monospace',
            }}>
            {label}
          </button>
        ))}
      </div>

      {/* Replay tab */}
      {activeTab === 'replay' && (
        <div>
          {/* Panel header */}
          <div style={{ marginBottom: 18 }}>
            <span style={{
              fontFamily: 'Barlow Condensed, sans-serif',
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '0.15em',
              textTransform: 'uppercase',
              color: 'var(--accent)',
            }}>
              <span style={{ color: 'var(--halt)' }}>[DEV]</span>{' '}BACKTESTER
            </span>
          </div>

          {/* Controls */}
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            padding: '14px 16px',
            marginBottom: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}>
            {/* Ticker input */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
                textTransform: 'uppercase', color: 'var(--muted)', width: 56, flexShrink: 0,
              }}>Tickers</label>
              <input
                type="text"
                value={tickerInput}
                onChange={e => setTickerInput(e.target.value)}
                placeholder="NVDA, PLTR, TSLA"
                disabled={running}
                style={{
                  fontFamily: 'IBM Plex Mono, monospace', fontSize: 11,
                  background: 'var(--bg)', border: '1px solid var(--border)',
                  color: 'var(--text)', padding: '4px 8px', width: 280,
                  outline: 'none', opacity: running ? 0.5 : 1,
                }}
              />
            </div>

            {/* Date range */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
                textTransform: 'uppercase', color: 'var(--muted)', width: 56, flexShrink: 0,
              }}>Start</label>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                disabled={running}
                style={{
                  fontFamily: 'IBM Plex Mono, monospace', fontSize: 11,
                  background: 'var(--bg)', border: '1px solid var(--border)',
                  color: 'var(--text)', padding: '4px 8px', outline: 'none',
                  opacity: running ? 0.5 : 1,
                }} />
              <label style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
                textTransform: 'uppercase', color: 'var(--muted)', marginLeft: 8,
              }}>End</label>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                disabled={running}
                style={{
                  fontFamily: 'IBM Plex Mono, monospace', fontSize: 11,
                  background: 'var(--bg)', border: '1px solid var(--border)',
                  color: 'var(--text)', padding: '4px 8px', outline: 'none',
                  opacity: running ? 0.5 : 1,
                }} />
            </div>

            {/* Setup type checkboxes */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
                textTransform: 'uppercase', color: 'var(--muted)', width: 56, flexShrink: 0,
              }}>Setup</label>
              <div style={{ display: 'flex', gap: 8 }}>
                {SETUP_OPTIONS.map(s => {
                  const checked = setupTypes.includes(s)
                  return (
                    <label key={s} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: running ? 'default' : 'pointer', opacity: running ? 0.5 : 1 }}>
                      <input type="checkbox" checked={checked}
                        onChange={() => !running && toggleSetup(s)} disabled={running}
                        style={{ cursor: running ? 'default' : 'pointer', accentColor: 'var(--accent)' }} />
                      <span style={{
                        fontFamily: 'IBM Plex Mono, monospace', fontSize: 10,
                        color: checked ? 'var(--text)' : 'var(--muted)', letterSpacing: '0.06em',
                      }}>{s}</span>
                    </label>
                  )
                })}
              </div>
            </div>

            {/* Run button + status */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button onClick={handleRun} disabled={running} style={{
                fontFamily: 'Barlow Condensed, sans-serif', fontSize: 11, fontWeight: 700,
                letterSpacing: '0.15em', textTransform: 'uppercase', padding: '6px 18px',
                background: running ? 'var(--border)' : 'var(--accent)',
                color: running ? 'var(--muted)' : '#000',
                border: 'none', cursor: running ? 'not-allowed' : 'pointer',
                transition: 'background 0.12s, color 0.12s',
              }}>
                {running ? '⏳ Running…' : '▶ Run Replay'}
              </button>
              {status && (
                <span style={{
                  fontFamily: 'IBM Plex Mono, monospace', fontSize: 10,
                  color: 'var(--muted)', letterSpacing: '0.04em',
                }}>{status}</span>
              )}
            </div>
          </div>

          {/* Results table */}
          {results.length > 0 && (
            <div style={{ border: '1px solid var(--border)', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'IBM Plex Mono, monospace' }}>
                <thead>
                  <tr style={{ background: 'var(--surface)' }}>
                    {['Ticker', 'Setup', 'Trades', 'Win %', 'Avg R', 'Avg Win R', 'Net P%', 'Max DD%'].map(col => (
                      <th key={col} style={{
                        fontFamily: 'Barlow Condensed, sans-serif', fontSize: 9, fontWeight: 700,
                        letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--muted)',
                        padding: '6px 10px', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
                      }}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {results.map((row, i) => {
                    const winRateColor = row.win_rate >= 50 ? 'var(--go)' : 'var(--halt)'
                    return (
                      <tr key={row.run_id ?? i} style={{ background: i % 2 === 0 ? 'var(--bg)' : 'var(--surface)' }}>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: 'var(--text)', fontWeight: 700, letterSpacing: '0.06em' }}>{String(row.ticker).toUpperCase()}</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: 'var(--muted)', letterSpacing: '0.04em' }}>{row.setup_type}</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: 'var(--text)' }}>{row.total_trades}</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: winRateColor, fontWeight: 600 }}>{Number(row.win_rate).toFixed(1)}</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: row.avg_rr > 0 ? 'var(--go)' : row.avg_rr < 0 ? 'var(--halt)' : 'var(--muted)', fontWeight: 600 }}>{Number(row.avg_rr).toFixed(2)}R</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: row.avg_win_r > 0 ? 'var(--go)' : 'var(--muted)' }}>{row.avg_win_r > 0 ? `${Number(row.avg_win_r).toFixed(2)}R` : '—'}</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: row.net_profit_pct > 0 ? 'var(--go)' : row.net_profit_pct < 0 ? 'var(--halt)' : 'var(--muted)', fontWeight: 600 }}>{Number(row.net_profit_pct).toFixed(1)}%</td>
                        <td style={{ fontSize: 10, padding: '5px 10px', color: 'var(--halt)' }}>{Number(row.max_drawdown_pct).toFixed(1)}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Empty state */}
          {!running && status && results.length === 0 && status.startsWith('No results') && (
            <div style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 10, color: 'var(--muted)', padding: '12px 0', letterSpacing: '0.06em' }}>
              No results returned. Ensure the backend /api/run-backtest and /api/backtest-results endpoints are implemented.
            </div>
          )}
        </div>
      )}

      {/* Walk-Forward tab */}
      {activeTab === 'wfo' && <WalkForwardTab />}
    </div>
  )
}
