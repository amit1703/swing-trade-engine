import { Search, Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useAppSettings } from '../contexts/AppSettingsContext'

export default function TopBar({
  activePage,
  scanStatus,
  onRunScan,
  onSearchTicker,
  devMode,
  dryRun,
  onToggleDev,
  onToggleDryRun,
  onOpenGuide,
}) {
  const { tr, lang } = useAppSettings()
  const [searchVal, setSearchVal] = useState('')

  const PAGE_TITLE_KEYS = {
    scanner:     'nav.scanner',
    watchlist:   'nav.watchlist',
    favorites:   'nav.favorites',
    portfolio:   'nav.portfolio',
    analytics:   'nav.analytics',
    diagnostics: 'nav.diagnostics',
    settings:    'nav.settings',
    more:        'nav.more',
  }

  // Keep all local derived variables unchanged
  const isScanning  = scanStatus?.in_progress
  const progressPct = scanStatus?.progress_pct ?? 0
  const titleKey = PAGE_TITLE_KEYS[activePage]
  const title = titleKey ? tr(titleKey) : activePage

  // Market open check (US hours Mon-Fri 9:30–16:00 ET) — logic unchanged
  const now   = new Date()
  const etNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const dow   = etNow.getDay()
  const hr    = etNow.getHours() + etNow.getMinutes() / 60
  const isOpen = dow >= 1 && dow <= 5 && hr >= 9.5 && hr < 16

  const handleSearch = (e) => {
    e.preventDefault()
    if (searchVal.trim()) {
      onSearchTicker(searchVal.trim().toUpperCase())
      setSearchVal('')
    }
  }

  return (
    <header className="h-[52px] bg-t-panel border-b border-t-border flex items-center px-4 gap-4 flex-shrink-0 relative z-20">

      {/* Progress bar at very top */}
      {isScanning && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-t-border">
          <div
            className="h-full bg-t-go transition-[width] duration-500 ease-linear"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}

      {/* Page title */}
      <span className={`font-condensed font-bold text-lg text-t-text flex-shrink-0 w-24 tracking-tight ${lang === 'he' ? 'font-sans' : 'font-mono'}`}>
        {title}
      </span>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex-1 max-w-xs">
        <div className="flex items-center gap-2 bg-t-card border border-t-border rounded-lg px-2.5 py-1.5">
          <Search size={13} className="text-t-muted flex-shrink-0" />
          <input
            value={searchVal}
            onChange={e => setSearchVal(e.target.value.toUpperCase())}
            placeholder={tr('search.placeholder')}
            className="bg-transparent border-none outline-none text-t-text font-mono text-[11px] w-full placeholder:text-t-muted"
          />
        </div>
      </form>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Market status pill */}
      <div className={`flex items-center gap-1.5 px-2 py-1 rounded-md border font-mono text-[9px] font-bold tracking-widest flex-shrink-0 ${
        isOpen
          ? 'bg-t-go/10 border-t-go/30 text-t-go'
          : 'bg-t-halt/10 border-t-halt/25 text-t-halt'
      }`}>
        <div className={`size-1.5 rounded-full flex-shrink-0 ${
          isOpen ? 'bg-t-go shadow-[0_0_6px_var(--go)]' : 'bg-t-halt'
        }`} />
        {isOpen ? 'MARKET OPEN' : 'MARKET CLOSED'}
      </div>

      {/* Run Scan button + scanning status label */}
      <div className="flex flex-col items-center gap-1 flex-shrink-0">
        <button
          onClick={onRunScan}
          disabled={isScanning}
          className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg font-mono text-[11px] font-bold tracking-wider transition-colors border-none ${
            isScanning
              ? 'bg-t-border text-t-muted cursor-default'
              : 'bg-t-go text-black cursor-pointer hover:bg-t-go/90'
          }`}
        >
          {isScanning
            ? <><RefreshCw size={12} className="animate-spin" /> {Math.round(progressPct)}%</>
            : <><Play size={11} fill="currentColor" /> {tr('btn.runScan')}</>
          }
        </button>
        {/* Status sub-label — keep this span, it shows scan phase */}
        {isScanning && (
          <span className="font-mono text-[9px] font-semibold tracking-widest text-t-muted">
            {scanStatus?.rebuilding_universe
              ? 'REBUILDING UNIVERSE…'
              : scanStatus?.prefetching
              ? 'PREFETCHING DATA…'
              : 'SCANNING TICKERS…'}
          </span>
        )}
      </div>

      {/* Dev mode toggles — only visible when devMode is true */}
      {devMode && (
        <div className="flex gap-1.5">
          <button
            onClick={onToggleDryRun}
            className={`font-mono text-[9px] font-bold px-1.5 py-0.5 rounded border transition-colors ${
              dryRun
                ? 'bg-t-accent/15 text-t-accent border-t-accent/40'
                : 'bg-t-border text-t-muted border-transparent'
            }`}
          >
            DRY
          </button>
        </div>
      )}

      {devMode && (
        <div
          onClick={onToggleDev}
          title="Press D to toggle Dev Mode"
          className="font-mono text-[8px] font-bold px-1.5 py-0.5 rounded border bg-t-purple/15 border-t-purple/35 text-t-purple tracking-widest cursor-pointer"
        >
          DEV
        </div>
      )}

      {/* Guide button */}
      <button
        onClick={onOpenGuide}
        title="Help (?)"
        className="size-7 rounded-lg bg-t-card border border-t-border text-t-muted hover:text-t-text flex items-center justify-center font-mono text-[11px] font-bold flex-shrink-0"
      >
        ?
      </button>
    </header>
  )
}
