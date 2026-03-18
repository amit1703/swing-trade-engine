import { Search, Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'

const PAGE_TITLES = {
  scanner:   'Scanner',
  watchlist: 'Watchlist',
  portfolio: 'Portfolio',
  analytics: 'Analytics',
  settings:  'Settings',
}

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
  const [searchVal, setSearchVal] = useState('')

  const isScanning  = scanStatus?.in_progress
  const progressPct = scanStatus?.progress_pct ?? 0
  const title       = PAGE_TITLES[activePage] ?? activePage

  // Market open check (US hours Mon-Fri 9:30–16:00 ET)
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
    <header style={{
      height: 52,
      background: 'var(--surface)',
      borderBottom: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      paddingLeft: 16,
      paddingRight: 16,
      gap: 16,
      flexShrink: 0,
      position: 'relative',
      zIndex: 20,
    }}>

      {/* Progress bar at very top */}
      {isScanning && (
        <div style={{
          position: 'absolute',
          top: 0, left: 0, right: 0,
          height: 2,
          background: 'var(--border)',
        }}>
          <div style={{
            height: '100%',
            width: `${progressPct}%`,
            background: 'var(--go)',
            transition: 'width 0.5s ease',
          }} />
        </div>
      )}

      {/* Page title */}
      <span style={{
        fontFamily: '"Barlow Condensed", sans-serif',
        fontWeight: 700,
        fontSize: 18,
        letterSpacing: '-0.01em',
        color: 'var(--text)',
        flexShrink: 0,
        width: 100,
      }}>
        {title}
      </span>

      {/* Search */}
      <form onSubmit={handleSearch} style={{ flex: 1, maxWidth: 320 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: 'var(--panel)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '5px 10px',
        }}>
          <Search size={13} color="var(--muted)" />
          <input
            value={searchVal}
            onChange={e => setSearchVal(e.target.value.toUpperCase())}
            placeholder="Search ticker..."
            style={{
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text)',
              fontFamily: '"IBM Plex Mono", monospace',
              fontSize: 11,
              width: '100%',
            }}
          />
        </div>
      </form>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Market status */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 8px',
        borderRadius: 6,
        background: isOpen ? 'rgba(0,200,122,0.1)' : 'rgba(255,45,85,0.08)',
        border: `1px solid ${isOpen ? 'rgba(0,200,122,0.3)' : 'rgba(255,45,85,0.25)'}`,
      }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%',
          background: isOpen ? 'var(--go)' : 'var(--halt)',
          boxShadow: isOpen ? '0 0 6px var(--go)' : 'none',
        }} />
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: '0.08em',
          fontFamily: '"IBM Plex Mono", monospace',
          color: isOpen ? 'var(--go)' : 'var(--halt)',
        }}>
          {isOpen ? 'MARKET OPEN' : 'MARKET CLOSED'}
        </span>
      </div>

      {/* Run Scan button + status line */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
      <button
        onClick={onRunScan}
        disabled={isScanning}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 14px',
          borderRadius: 8,
          background: isScanning ? 'var(--border)' : 'var(--go)',
          color: isScanning ? 'var(--muted)' : '#000',
          fontWeight: 700,
          fontSize: 11,
          letterSpacing: '0.04em',
          border: 'none',
          cursor: isScanning ? 'default' : 'pointer',
          fontFamily: '"IBM Plex Mono", monospace',
          transition: 'background 0.15s',
          flexShrink: 0,
        }}
      >
        {isScanning
          ? <><RefreshCw size={12} className="animate-spin" /> {Math.round(progressPct)}%</>
          : <><Play size={11} fill="currentColor" /> RUN SCAN</>
        }
      </button>
      {isScanning && (
        <span style={{
          fontSize: 9,
          fontFamily: '"IBM Plex Mono", monospace',
          fontWeight: 600,
          letterSpacing: '0.08em',
          color: 'var(--muted)',
        }}>
          {scanStatus?.rebuilding_universe
            ? 'REBUILDING UNIVERSE…'
            : scanStatus?.prefetching
            ? 'PREFETCHING DATA…'
            : 'SCANNING TICKERS…'}
        </span>
      )}
      </div>

      {/* Dev mode toggles */}
      {devMode && (
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={onToggleDryRun}
            style={{
              fontSize: 9, padding: '3px 7px', borderRadius: 4,
              background: dryRun ? 'rgba(245,166,35,0.15)' : 'var(--border)',
              color: dryRun ? 'var(--accent)' : 'var(--muted)',
              border: `1px solid ${dryRun ? 'rgba(245,166,35,0.4)' : 'transparent'}`,
              cursor: 'pointer', fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: 700,
            }}
          >
            DRY
          </button>
        </div>
      )}

      {devMode && (
        <div
          onClick={onToggleDev}
          title="Press D to toggle Dev Mode"
          style={{
            fontSize: 8, padding: '2px 6px', borderRadius: 4,
            background: 'rgba(155,110,255,0.15)',
            border: '1px solid rgba(155,110,255,0.35)',
            color: '#9B6EFF',
            fontFamily: '"IBM Plex Mono", monospace',
            fontWeight: 700,
            letterSpacing: '0.08em',
            cursor: 'pointer',
          }}
        >
          DEV
        </div>
      )}

      {/* Guide button */}
      <button
        onClick={onOpenGuide}
        style={{
          width: 28, height: 28, borderRadius: 8,
          background: 'var(--panel)', border: '1px solid var(--border)',
          color: 'var(--muted)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 700, fontFamily: '"IBM Plex Mono", monospace',
        }}
        title="Help (?)"
      >
        ?
      </button>
    </header>
  )
}
