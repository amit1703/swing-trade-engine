/**
 * App.jsx — root layout and state orchestrator
 *
 * Tabs:
 *  SCANNER   → left panel (VCP + Pullback tables) + right panel (TradingChart)
 *  PORTFOLIO → full-width PortfolioTab (active trades, health signals, P/L)
 *
 * Layout (CSS Grid):
 *  ┌────────────────────────── Header (full-width, 62px) ──────────────────┐
 *  │  [ SCANNER ]  [ PORTFOLIO ]  ← tab bar (28px)                         │
 *  │ Left panel (400px)        │  Right panel (flex-1)                     │
 *  │  VCP SetupTable           │   TradingChart / PortfolioTab             │
 *  │  Pullback SetupTable      │                                           │
 *  └───────────────────────────┴───────────────────────────────────────────┘
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchRegime,
  fetchSetups,
  fetchChartData,
  triggerScan,
  fetchScanStatus,
  fetchWatchlist,
} from './api.js'

import Header        from './components/Header.jsx'
import SetupTable    from './components/SetupTable.jsx'
import TradingChart  from './components/TradingChart.jsx'
import PortfolioTab  from './components/PortfolioTab.jsx'
import WatchlistPanel from './components/WatchlistPanel.jsx'

// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_SCAN_STATUS = {
  in_progress:    false,
  progress:       0,
  total:          0,
  progress_pct:   0,
  started_at:     null,
  last_completed: null,
  last_error:     null,
}

export default function App() {
  const [activeTab,      setActiveTab     ] = useState('scanner')
  const [regime,         setRegime        ] = useState(null)
  const [vcpSetups,      setVcpSetups     ] = useState([])
  const [pullbackSetups, setPullbackSetups] = useState([])
  const [baseSetups,        setBaseSetups       ] = useState([])
  const [resBreakoutSetups, setResBreakoutSetups] = useState([])
  const [watchlistItems, setWatchlistItems] = useState([])
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [chartData,      setChartData     ] = useState(null)
  const [loadingSetups,  setLoadingSetups ] = useState(false)
  const [loadingChart,   setLoadingChart  ] = useState(false)
  const [scanStatus,     setScanStatus    ] = useState(DEFAULT_SCAN_STATUS)

  const pollTimerRef = useRef(null)

  // ── Load regime + setups from DB ─────────────────────────────────────────
  const loadAllData = useCallback(async () => {
    setLoadingSetups(true)
    try {
      const [reg, vcp, pb, base, wl, res] = await Promise.allSettled([
        fetchRegime(),
        fetchSetups('vcp'),
        fetchSetups('pullback'),
        fetchSetups('base'),
        fetchWatchlist(),
        fetchSetups('res-breakout'),
      ])
      if (reg.status === 'fulfilled')  setRegime(reg.value)
      if (vcp.status === 'fulfilled')  setVcpSetups(vcp.value.setups ?? [])
      if (pb.status === 'fulfilled')   setPullbackSetups(pb.value.setups ?? [])
      if (base.status === 'fulfilled') setBaseSetups(base.value.setups ?? [])
      if (wl.status === 'fulfilled')   setWatchlistItems(wl.value.items ?? [])
      if (res.status === 'fulfilled')  setResBreakoutSetups(res.value.setups ?? [])
    } catch (err) {
      console.error('[App] loadAllData:', err)
    } finally {
      setLoadingSetups(false)
    }
  }, [])

  // ── Ticker click → load chart data + switch to scanner tab ───────────────
  const handleTickerClick = useCallback(async (ticker) => {
    setActiveTab('scanner')
    setSelectedTicker(ticker)
    setChartData(null)
    setLoadingChart(true)
    try {
      const data = await fetchChartData(ticker)
      setChartData(data)
    } catch (err) {
      console.error('[App] fetchChartData:', err)
      setChartData(null)
    } finally {
      setLoadingChart(false)
    }
  }, [])

  // ── Run scan ──────────────────────────────────────────────────────────────
  const handleRunScan = useCallback(async () => {
    try {
      await triggerScan()
      setScanStatus((s) => ({ ...s, in_progress: true, progress: 0 }))
    } catch (err) {
      console.error('[App] triggerScan:', err)
    }
  }, [])

  // ── Poll scan status while running ────────────────────────────────────────
  useEffect(() => {
    if (!scanStatus.in_progress) return

    pollTimerRef.current = setInterval(async () => {
      try {
        const status = await fetchScanStatus()
        setScanStatus(status)

        if (!status.in_progress) {
          clearInterval(pollTimerRef.current)
          loadAllData()
        }
      } catch (err) {
        console.warn('[App] poll error:', err)
      }
    }, 2000)

    return () => clearInterval(pollTimerRef.current)
  }, [scanStatus.in_progress, loadAllData])

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    loadAllData()

    const params = new URLSearchParams(window.location.search)
    const t = params.get('ticker')
    if (t) handleTickerClick(t.toUpperCase())

    fetchScanStatus()
      .then((s) => setScanStatus(s))
      .catch(() => {})
  }, [loadAllData])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div
      className="flex flex-col"
      style={{ height: '100vh', background: 'var(--bg)', overflow: 'hidden' }}
    >
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <Header
        regime={regime}
        scanStatus={scanStatus}
        onRunScan={handleRunScan}
        onSearchTicker={handleTickerClick}
      />

      {/* ── Tab bar ────────────────────────────────────────────────────── */}
      <div
        className="flex items-stretch flex-shrink-0"
        style={{
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface)',
          height: 30,
        }}
      >
        {['scanner', 'portfolio'].map((tab) => {
          const active = activeTab === tab
          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                fontFamily: 'Barlow Condensed, sans-serif',
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.15em',
                textTransform: 'uppercase',
                padding: '0 18px',
                background: 'transparent',
                border: 'none',
                borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
                color: active ? 'var(--accent)' : 'var(--muted)',
                cursor: 'pointer',
                transition: 'color 0.12s, border-color 0.12s',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {tab === 'scanner' ? 'SCANNER' : 'PORTFOLIO'}
              {tab === 'portfolio' && (
                <span
                  style={{
                    fontSize: 9,
                    background: active ? 'rgba(245,166,35,0.2)' : 'var(--border)',
                    color: active ? 'var(--accent)' : 'var(--muted)',
                    padding: '1px 5px',
                    borderRadius: 2,
                  }}
                >
                  TRADES
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">

        {activeTab === 'scanner' ? (
          <>
            {/* Watchlist panel (narrow, leftmost) */}
            <WatchlistPanel
              items={watchlistItems}
              selectedTicker={selectedTicker}
              onSelectTicker={handleTickerClick}
              loading={loadingSetups}
            />

            {/* Left panel — setup tables (400px) */}
            <aside
              className="flex flex-col overflow-y-auto flex-shrink-0"
              style={{
                width: 400,
                borderRight: '1px solid var(--border)',
                background: 'var(--panel)',
              }}
            >
              <SetupTable
                title="VCP Breakouts"
                accentColor="blue"
                setups={vcpSetups}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                loading={loadingSetups}
              />

              <SetupTable
                title="Tactical Pullbacks"
                accentColor="accent"
                setups={pullbackSetups}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                loading={loadingSetups}
              />

              <SetupTable
                title="Base Patterns"
                accentColor="green"
                setups={baseSetups}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                loading={loadingSetups}
              />

              <SetupTable
                title="Resistance Breakouts"
                accentColor="green"
                setups={resBreakoutSetups}
                selectedTicker={selectedTicker}
                onSelectTicker={handleTickerClick}
                loading={loadingSetups}
              />

              <div className="mt-auto px-3 py-3 border-t border-t-border">
                <ScanFooter
                  vcpCount={vcpSetups.length}
                  pbCount={pullbackSetups.length}
                  baseCount={baseSetups.length}
                  resCount={resBreakoutSetups.length}
                  scanTimestamp={scanStatus.last_completed}
                />
              </div>
            </aside>

            {/* Right panel — chart */}
            <main className="flex-1 min-w-0 overflow-hidden" style={{ background: 'var(--bg)' }}>
              <TradingChart
                ticker={selectedTicker}
                chartData={chartData}
                loading={loadingChart}
              />
            </main>
          </>
        ) : (
          /* Portfolio tab — full width */
          <div className="flex-1 min-w-0 overflow-hidden">
            <PortfolioTab onTickerClick={handleTickerClick} />
          </div>
        )}

      </div>
    </div>
  )
}

// ── Scan footer ───────────────────────────────────────────────────────────

function ScanFooter({ vcpCount, pbCount, baseCount = 0, resCount = 0, scanTimestamp }) {
  const fmtTs = (ts) => {
    if (!ts) return 'Never'
    try {
      const d = new Date(ts + 'Z')
      return d.toLocaleString('en-US', {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false,
      })
    } catch { return ts }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-[9px] text-t-muted uppercase tracking-widest">
        <span>Last scan</span>
        <span className="text-t-text">{fmtTs(scanTimestamp)}</span>
      </div>
      <div className="flex gap-3 text-[9px] text-t-muted">
        <span><span className="text-t-blue font-600">{vcpCount}</span> VCP</span>
        <span><span className="text-t-accent font-600">{pbCount}</span> Pullback</span>
        <span><span className="text-t-green font-600">{baseCount}</span> Base</span>
        <span><span className="text-[var(--go)] font-600">{resCount}</span> ResBreak</span>
        <span className="ml-auto text-t-border">v1.0</span>
      </div>
    </div>
  )
}
