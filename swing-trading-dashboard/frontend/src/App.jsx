/**
 * App.jsx — root layout and state orchestrator
 *
 * Layout:
 *  ┌─ Sidebar (60px) ─┬─────────────── Main content ───────────────────┐
 *  │  nav icons        │  TopBar (regime + scan controls)                │
 *  │                   │  ── SCANNER PAGE ───────────────────────────── │
 *  │                   │   StatCards row                                 │
 *  │                   │   [ Chart ] [ StockIntelPanel ]                 │
 *  │                   │   [ ScannerFilters + ScannerTable ]             │
 *  │                   │  ── WATCHLIST / PORTFOLIO / ANALYTICS ──────── │
 *  └───────────────────┴─────────────────────────────────────────────────┘
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchRegime,
  fetchSetups,
  fetchChartData,
  triggerScan,
  fetchScanStatus,
  fetchWatchlist,
  fetchDebugTicker,
  fetchOptionsSetups,
  fetchPrices,
  fetchAnalysis,
} from './api.js'

import Sidebar          from './components/Sidebar.jsx'
import TopBar           from './components/TopBar.jsx'
import StatCards        from './components/StatCards.jsx'
import StockIntelPanel  from './components/StockIntelPanel.jsx'
import ScannerTable     from './components/ScannerTable.jsx'
import ScannerFilters   from './components/ScannerFilters.jsx'
import TradingChart     from './components/TradingChart.jsx'
import PortfolioTab     from './components/PortfolioTab.jsx'
import WatchlistPanel   from './components/WatchlistPanel.jsx'
import SystemGuideModal from './components/SystemGuideModal.jsx'
import EngineHealthPanel from './components/EngineHealthPanel.jsx'
import DebugDrawer      from './components/DebugDrawer.jsx'
import BacktestPanel    from './components/BacktestPanel.jsx'
import DiagnosticsTab   from './components/DiagnosticsTab.jsx'

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
  const [activePage,      setActivePage     ] = useState('scanner')
  const [regime,         setRegime        ] = useState(null)
  const [vcpSetups,      setVcpSetups     ] = useState([])
  const [pullbackSetups, setPullbackSetups] = useState([])
  const [baseSetups,        setBaseSetups       ] = useState([])
  const [resBreakoutSetups, setResBreakoutSetups] = useState([])
  const [htfSetups,         setHtfSetups        ] = useState([])
  const [lceSetups,         setLceSetups        ] = useState([])
  const [optionsSetups,     setOptionsSetups    ] = useState([])
  const [watchlistItems, setWatchlistItems] = useState([])
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [chartData,      setChartData     ] = useState(null)
  const [loadingSetups,  setLoadingSetups ] = useState(false)
  const [loadingChart,   setLoadingChart  ] = useState(false)
  const [scanStatus,     setScanStatus    ] = useState(DEFAULT_SCAN_STATUS)
  const [showGuide,      setShowGuide     ] = useState(false)
  const [devMode,        setDevMode       ] = useState(false)
  const [dryRun,         setDryRun        ] = useState(false)
  const [debugTicker,    setDebugTicker   ] = useState(null)
  const [debugData,      setDebugData     ] = useState(null)
  const [debugLoading,   setDebugLoading  ] = useState(false)
  const [livePrices,     setLivePrices    ] = useState({})
  const [chartFocus,     setChartFocus    ] = useState(false)
  const [filters,        setFilters       ] = useState({
    minScore: 0,
    setupType: 'ALL',
    hotOnly: false,
    searchQuery: '',
  })
  const [analysis,        setAnalysis       ] = useState(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)

  const pollTimerRef = useRef(null)

  // ── Computed values ───────────────────────────────────────────────────────
  const allSetups = [
    ...vcpSetups,
    ...pullbackSetups,
    ...baseSetups,
    ...resBreakoutSetups,
    ...htfSetups,
    ...lceSetups,
  ]

  const selectedSetup = allSetups.find(s => s.ticker === selectedTicker) ?? null

  // ── Load regime + setups from DB ─────────────────────────────────────────
  const loadAllData = useCallback(async () => {
    setLoadingSetups(true)
    try {
      const [reg, vcp, pb, base, wl, res, opts, htf, lce] = await Promise.allSettled([
        fetchRegime(),
        fetchSetups('vcp'),
        fetchSetups('pullback'),
        fetchSetups('base'),
        fetchWatchlist(),
        fetchSetups('res-breakout'),
        fetchOptionsSetups(),
        fetchSetups('htf'),
        fetchSetups('lce'),
      ])
      if (reg.status === 'fulfilled')  setRegime(reg.value)
      if (vcp.status === 'fulfilled')  setVcpSetups(vcp.value.setups ?? [])
      if (pb.status === 'fulfilled')   setPullbackSetups(pb.value.setups ?? [])
      if (base.status === 'fulfilled') setBaseSetups(base.value.setups ?? [])
      if (wl.status === 'fulfilled')   setWatchlistItems(wl.value.items ?? [])
      if (res.status === 'fulfilled')  setResBreakoutSetups(res.value.setups ?? [])
      if (opts.status === 'fulfilled') setOptionsSetups(opts.value.setups ?? [])
      if (htf.status === 'fulfilled')  setHtfSetups(htf.value.setups ?? [])
      if (lce.status === 'fulfilled')  setLceSetups(lce.value.setups ?? [])
    } catch (err) {
      console.error('[App] loadAllData:', err)
    } finally {
      setLoadingSetups(false)
    }
  }, [])

  // ── Ticker click → load chart data + analysis; optionally switch to scanner
  const handleTickerClick = useCallback(async (ticker, switchTab = true) => {
    if (switchTab) setActivePage('scanner')
    setSelectedTicker(ticker)
    setChartData(null)
    setLoadingChart(true)
    setAnalysis(null)
    setAnalysisLoading(true)

    const [chartResult, analysisResult] = await Promise.allSettled([
      fetchChartData(ticker),
      fetchAnalysis(ticker),
    ])
    if (chartResult.status === 'fulfilled') setChartData(chartResult.value)
    if (analysisResult.status === 'fulfilled') setAnalysis(analysisResult.value)
    setLoadingChart(false)
    setAnalysisLoading(false)
  }, [])

  // ── Run scan ──────────────────────────────────────────────────────────────
  const handleRunScan = useCallback(async () => {
    try {
      await triggerScan(devMode, dryRun)
      setScanStatus((s) => ({ ...s, in_progress: true, progress: 0 }))
    } catch (err) {
      console.error('[App] triggerScan:', err)
    }
  }, [devMode, dryRun])

  const handleScanTicker = useCallback(async (ticker) => {
    try {
      await triggerScan(devMode, dryRun, ticker)
      setScanStatus((s) => ({ ...s, in_progress: true, progress: 0 }))
    } catch (err) {
      console.error('[App] triggerScan (single):', err)
    }
  }, [devMode, dryRun])

  // ── Debug drill-down ──────────────────────────────────────────────────────
  const handleDebug = useCallback(async (ticker) => {
    setDebugTicker(ticker)
    setDebugData(null)
    setDebugLoading(true)
    try {
      const data = await fetchDebugTicker(ticker)
      setDebugData(data)
    } catch (err) {
      console.error('[App] fetchDebugTicker:', err)
    } finally {
      setDebugLoading(false)
    }
  }, [])

  // ── Live price polling ────────────────────────────────────────────────────
  const fetchLivePrices = useCallback(async () => {
    const allTickers = [
      ...vcpSetups,
      ...pullbackSetups,
      ...baseSetups,
      ...resBreakoutSetups,
      ...htfSetups,
      ...lceSetups,
    ].map((s) => s.ticker)

    const unique = [...new Set(allTickers)]
    if (unique.length === 0) return

    try {
      const prices = await fetchPrices(unique)
      setLivePrices(prices)
    } catch (err) {
      console.warn('[App] fetchLivePrices:', err)
    }
  }, [vcpSetups, pullbackSetups, baseSetups, resBreakoutSetups, htfSetups, lceSetups])

  useEffect(() => {
    fetchLivePrices()
    const id = setInterval(fetchLivePrices, 60_000)
    return () => clearInterval(id)
  }, [fetchLivePrices])

  // ── Poll scan status while running ────────────────────────────────────────
  useEffect(() => {
    if (!scanStatus.in_progress) return

    pollTimerRef.current = setInterval(async () => {
      try {
        const status = await fetchScanStatus()
        setScanStatus(status)

        if (!status.in_progress) {
          clearInterval(pollTimerRef.current)
          // dry run: populate tables from in-memory results, not DB
          if (status.engine_stats?.dry_run && status.dry_run_setups) {
            const dr = status.dry_run_setups
            setVcpSetups(dr.vcp ?? [])
            setPullbackSetups(dr.pullback ?? [])
            setBaseSetups(dr.base ?? [])
            setResBreakoutSetups(dr.res_breakout ?? [])
            setWatchlistItems(dr.watchlist ?? [])
            setOptionsSetups(dr.options_catalyst ?? [])
            setHtfSetups(dr.htf ?? [])
            setLceSetups(dr.lce ?? [])
            const e0 = status.engine_stats.e0
            if (e0 && e0.is_bullish != null) {
              setRegime({
                spy_close:  e0.spy_close,
                spy_20ema:  e0.spy_ema20,
                is_bullish: e0.is_bullish,
                regime:     e0.is_bullish ? 'GO' : 'HALT',
              })
            }
          } else {
            loadAllData()
          }
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

  // ── Keyboard shortcuts ────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement.tagName === 'INPUT') return
      if (e.key === '?') setShowGuide(v => !v)
      if (e.key === 'f' || e.key === 'F') setChartFocus(v => !v)
      if (e.key === 'Escape') setDebugTicker(null)
      if (e.key === 'd' || e.key === 'D') {
        setDevMode(v => {
          const next = !v
          if (!next) { setDryRun(false); setDebugTicker(null) }
          return next
        })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* ── Sidebar ──────────────────────────────────────────── */}
      <Sidebar activePage={activePage} onNavigate={setActivePage} />

      {/* ── Main content ─────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

        {/* Top bar */}
        <TopBar
          activePage={activePage}
          regime={regime}
          scanStatus={scanStatus}
          onRunScan={handleRunScan}
          onSearchTicker={(t) => handleTickerClick(t, false)}
          devMode={devMode}
          dryRun={dryRun}
          onToggleDev={() => {
            setDevMode(v => {
              const next = !v
              if (!next) { setDryRun(false); setDebugTicker(null) }
              return next
            })
          }}
          onToggleDryRun={() => setDryRun(v => !v)}
          onOpenGuide={() => setShowGuide(true)}
        />

        {/* ── SCANNER PAGE ──────────────────────────────────── */}
        {activePage === 'scanner' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

            {/* Stat cards row */}
            {!chartFocus && (
              <StatCards regime={regime} />
            )}

            {/* Middle: Chart + Intel Panel */}
            <div style={{
              flex: chartFocus ? 1 : '0 0 420px',
              display: 'flex', gap: 12,
              padding: '0 16px 12px',
              minHeight: 0,
              position: 'relative',
            }}>
              {/* Chart focus hint */}
              {chartFocus && (
                <div style={{
                  position: 'absolute', top: 8, right: 28, zIndex: 10,
                  fontSize: 8, color: 'rgba(245,166,35,0.5)',
                  fontFamily: '"IBM Plex Mono", monospace', letterSpacing: '0.08em',
                  pointerEvents: 'none',
                }}>
                  F — EXIT FOCUS
                </div>
              )}

              {/* Chart card */}
              <div
                className="card"
                style={{ flex: 1, minWidth: 0, overflow: 'hidden', padding: 0, position: 'relative' }}
              >
                <TradingChart
                  ticker={selectedTicker}
                  chartData={chartData}
                  loading={loadingChart}
                  setups={selectedTicker ? allSetups.filter(s => s.ticker === selectedTicker) : []}
                />
              </div>

              {/* Right panel — hidden in focus mode */}
              {!chartFocus && (
                <StockIntelPanel
                  setup={selectedSetup}
                  livePrices={livePrices}
                  analysis={analysis}
                  analysisLoading={analysisLoading}
                />
              )}
            </div>

            {/* Bottom: Filter bar + Scanner table */}
            {!chartFocus && (
              <div style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                margin: '0 16px 16px',
                background: 'var(--card)',
                border: '1px solid var(--card-border)',
                borderRadius: 12,
                overflow: 'hidden',
                minHeight: 0,
              }}>
                <ScannerFilters filters={filters} onFiltersChange={setFilters} />
                <ScannerTable
                  allSetups={allSetups}
                  filters={filters}
                  selectedTicker={selectedTicker}
                  onSelectTicker={handleTickerClick}
                  livePrices={livePrices}
                  devMode={devMode}
                  onDebug={handleDebug}
                />
              </div>
            )}
          </div>
        )}

        {/* ── WATCHLIST PAGE ────────────────────────────────── */}
        {activePage === 'watchlist' && (
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <WatchlistPanel
              items={watchlistItems}
              selectedTicker={selectedTicker}
              onSelectTicker={handleTickerClick}
              loading={loadingSetups}
            />
          </div>
        )}

        {/* ── PORTFOLIO PAGE ────────────────────────────────── */}
        {activePage === 'portfolio' && (
          <div style={{ flex: 1, overflow: 'auto' }}>
            <PortfolioTab
              regime={regime}
              scanStatus={scanStatus}
              onTickerClick={handleTickerClick}
              devMode={devMode}
            />
          </div>
        )}

        {/* ── ANALYTICS PAGE ───────────────────────────────── */}
        {activePage === 'analytics' && (
          <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
            <BacktestPanel />
          </div>
        )}

        {/* ── DIAGNOSTICS PAGE ─────────────────────────────── */}
        {activePage === 'diagnostics' && (
          <div style={{ flex: 1, overflow: 'auto' }}>
            <DiagnosticsTab />
          </div>
        )}

        {/* ── SETTINGS — stub ───────────────────────────────── */}
        {['settings'].includes(activePage) && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--muted)', flexDirection: 'column', gap: 8,
          }}>
            <span style={{ fontSize: 32 }}>🚧</span>
            <span style={{ fontSize: 13, fontFamily: '"IBM Plex Mono", monospace' }}>
              {activePage.toUpperCase()} — coming soon
            </span>
          </div>
        )}
      </div>

      {/* ── Overlays (all pages) ─────────────────────────────── */}
      <SystemGuideModal isOpen={showGuide} onClose={() => setShowGuide(false)} />
      {devMode && debugTicker && (
        <DebugDrawer
          ticker={debugTicker}
          data={debugData}
          loading={debugLoading}
          onClose={() => { setDebugTicker(null); setDebugData(null) }}
        />
      )}
    </div>
  )
}
