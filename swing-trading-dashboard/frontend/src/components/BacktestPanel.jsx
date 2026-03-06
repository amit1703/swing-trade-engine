import { useState } from 'react'
import { runBacktest, fetchBacktestResults } from '../api.js'

const SETUP_OPTIONS = ['VCP', 'PULLBACK', 'BASE']

function defaultStartDate() {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 1)
  return d.toISOString().slice(0, 10)
}

export default function BacktestPanel() {
  const [tickerInput, setTickerInput] = useState('')
  const [startDate,   setStartDate  ] = useState(defaultStartDate)
  const [endDate,     setEndDate    ] = useState(() => new Date().toISOString().slice(0, 10))
  const [setupTypes,  setSetupTypes ] = useState(['VCP', 'PULLBACK', 'BASE'])
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

    // Poll for results using local accumulator (avoids stale closure)
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

      // Stop when all tickers have at least one result
      const tickersWithResults = new Set(allResults.map(r => r.ticker))
      if (tickers.every(t => tickersWithResults.has(t))) break
    }

    setResults(allResults)
    setStatus(allResults.length > 0 ? `Done — ${allResults.length} result(s)` : 'No results yet. Check backend logs.')
    setRunning(false)
  }

  return (
    <div style={{ fontFamily: 'Barlow Condensed, sans-serif' }}>
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
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--muted)',
            width: 56,
            flexShrink: 0,
          }}>
            Tickers
          </label>
          <input
            type="text"
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value)}
            placeholder="NVDA, PLTR, TSLA"
            disabled={running}
            style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 11,
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              padding: '4px 8px',
              width: 280,
              outline: 'none',
              opacity: running ? 0.5 : 1,
            }}
          />
        </div>

        {/* Date range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label style={{
            fontFamily: 'Barlow Condensed, sans-serif',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--muted)',
            width: 56,
            flexShrink: 0,
          }}>
            Start
          </label>
          <input
            type="date"
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            disabled={running}
            style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 11,
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              padding: '4px 8px',
              outline: 'none',
              opacity: running ? 0.5 : 1,
            }}
          />
          <label style={{
            fontFamily: 'Barlow Condensed, sans-serif',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--muted)',
            marginLeft: 8,
          }}>
            End
          </label>
          <input
            type="date"
            value={endDate}
            onChange={e => setEndDate(e.target.value)}
            disabled={running}
            style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 11,
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              padding: '4px 8px',
              outline: 'none',
              opacity: running ? 0.5 : 1,
            }}
          />
        </div>

        {/* Setup type checkboxes */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label style={{
            fontFamily: 'Barlow Condensed, sans-serif',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--muted)',
            width: 56,
            flexShrink: 0,
          }}>
            Setup
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            {SETUP_OPTIONS.map(s => {
              const checked = setupTypes.includes(s)
              return (
                <label
                  key={s}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 5,
                    cursor: running ? 'default' : 'pointer',
                    opacity: running ? 0.5 : 1,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => !running && toggleSetup(s)}
                    disabled={running}
                    style={{ cursor: running ? 'default' : 'pointer', accentColor: 'var(--accent)' }}
                  />
                  <span style={{
                    fontFamily: 'IBM Plex Mono, monospace',
                    fontSize: 10,
                    color: checked ? 'var(--text)' : 'var(--muted)',
                    letterSpacing: '0.06em',
                  }}>
                    {s}
                  </span>
                </label>
              )
            })}
          </div>
        </div>

        {/* Run button + status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={handleRun}
            disabled={running}
            style={{
              fontFamily: 'Barlow Condensed, sans-serif',
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '0.15em',
              textTransform: 'uppercase',
              padding: '6px 18px',
              background: running ? 'var(--border)' : 'var(--accent)',
              color: running ? 'var(--muted)' : '#000',
              border: 'none',
              cursor: running ? 'not-allowed' : 'pointer',
              transition: 'background 0.12s, color 0.12s',
            }}
          >
            {running ? '⏳ Running…' : '▶ Run Replay'}
          </button>
          {status && (
            <span style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 10,
              color: 'var(--muted)',
              letterSpacing: '0.04em',
            }}>
              {status}
            </span>
          )}
        </div>
      </div>

      {/* Results table */}
      {results.length > 0 && (
        <div style={{
          border: '1px solid var(--border)',
          overflow: 'hidden',
        }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontFamily: 'IBM Plex Mono, monospace',
          }}>
            <thead>
              <tr style={{ background: 'var(--surface)' }}>
                {['Ticker', 'Setup', 'Trades', 'Win %', 'P.Factor', 'Avg R:R', 'Max DD%'].map(col => (
                  <th
                    key={col}
                    style={{
                      fontFamily: 'Barlow Condensed, sans-serif',
                      fontSize: 9,
                      fontWeight: 700,
                      letterSpacing: '0.12em',
                      textTransform: 'uppercase',
                      color: 'var(--muted)',
                      padding: '6px 10px',
                      textAlign: 'left',
                      borderBottom: '1px solid var(--border)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((row, i) => {
                const winRateColor = row.win_rate >= 50 ? 'var(--go)' : 'var(--halt)'
                const pfColor = row.profit_factor >= 1.0 ? 'var(--go)' : 'var(--halt)'
                const pfDisplay = row.profit_factor === Infinity || row.profit_factor === 'Infinity' || Number(row.profit_factor) > 9999
                  ? '∞'
                  : Number(row.profit_factor).toFixed(2)

                return (
                  <tr
                    key={row.run_id ?? i}
                    style={{
                      background: i % 2 === 0 ? 'var(--bg)' : 'var(--surface)',
                    }}
                  >
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: 'var(--text)',
                      fontWeight: 700,
                      letterSpacing: '0.06em',
                    }}>
                      {String(row.ticker).toUpperCase()}
                    </td>
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: 'var(--muted)',
                      letterSpacing: '0.04em',
                    }}>
                      {row.setup_type}
                    </td>
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: 'var(--text)',
                    }}>
                      {row.total_trades}
                    </td>
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: winRateColor,
                      fontWeight: 600,
                    }}>
                      {Number(row.win_rate).toFixed(1)}
                    </td>
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: pfColor,
                      fontWeight: 600,
                    }}>
                      {pfDisplay}
                    </td>
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: 'var(--text)',
                    }}>
                      {Number(row.avg_rr).toFixed(2)}
                    </td>
                    <td style={{
                      fontSize: 10,
                      padding: '5px 10px',
                      color: 'var(--halt)',
                    }}>
                      {Number(row.max_drawdown_pct).toFixed(1)}%
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Empty state (after a completed run with no results) */}
      {!running && status && results.length === 0 && status.startsWith('No results') && (
        <div style={{
          fontFamily: 'IBM Plex Mono, monospace',
          fontSize: 10,
          color: 'var(--muted)',
          padding: '12px 0',
          letterSpacing: '0.06em',
        }}>
          No results returned. Ensure the backend /api/run-backtest and /api/backtest-results endpoints are implemented.
        </div>
      )}
    </div>
  )
}
