/**
 * Header — Market Regime Banner
 *
 * GO    → solid green bar, large label, SPY data
 * HALT  → solid red bar, pulsing, SPY data
 * NO_DATA / loading → neutral state
 */
import { useRef, useState } from 'react'

export default function Header({ regime, scanStatus, onRunScan, onSearchTicker, onOpenGuide }) {
  const isBullish = regime?.is_bullish
  const isNoData  = !regime || regime.regime === 'NO_DATA'
  const isHalt    = regime && !isBullish && regime.regime !== 'NO_DATA'
  const isError   = regime?.regime?.startsWith('ERROR')

  const fmtTime = (iso) => {
    if (!iso) return '—'
    const d = new Date(iso + 'Z')
    return d.toLocaleTimeString('en-US', { hour12: false })
  }

  // Determine accent color for the left stripe and labels
  let stripeClass = 'bg-t-muted'
  let bgClass     = 'bg-t-surface'
  let textClass   = 'text-t-muted'
  if (isBullish) { stripeClass = 'bg-t-go';   bgClass = 'bg-t-goDim';  textClass = 'text-t-go'  }
  if (isHalt)    { stripeClass = 'bg-t-halt';  bgClass = 'bg-t-haltDim'; textClass = 'text-t-halt' }

  return (
    <header className="relative flex flex-col border-b border-t-border select-none" style={{ background: 'var(--surface)' }}>

      {/* Progress bar — sits at very top, 0px height when idle */}
      <div className="progress-bar w-full" style={{ opacity: scanStatus.in_progress ? 1 : 0, transition: 'opacity 0.3s' }}>
        <div
          className="progress-bar-fill"
          style={{ width: `${scanStatus.progress_pct ?? 0}%` }}
        />
      </div>

      {/* Main row */}
      <div className="flex items-stretch h-[62px]">

        {/* Left stripe (regime colour indicator) */}
        <div className={`w-1 flex-shrink-0 ${stripeClass} ${isHalt ? 'animate-pulse_halt' : ''}`} />

        {/* REGIME STATUS — left block */}
        <div className={`flex items-center gap-4 px-5 border-r border-t-border ${bgClass}`} style={{ minWidth: 340 }}>
          {isNoData ? (
            <div className="flex flex-col gap-0.5">
              <span className="font-condensed text-[11px] font-700 tracking-widest uppercase text-t-muted">Market Status</span>
              <span className="font-condensed text-[22px] font-700 tracking-tight text-t-muted">NO DATA</span>
            </div>
          ) : isError ? (
            <div className="flex flex-col gap-0.5">
              <span className="font-condensed text-[11px] font-700 tracking-widest uppercase text-t-halt">Engine 0 Error</span>
              <span className="font-condensed text-[14px] font-600 text-t-muted truncate max-w-[280px]">{regime.regime}</span>
            </div>
          ) : (
            <div className="flex flex-col gap-0.5">
              <span className={`font-condensed text-[11px] font-700 tracking-widest uppercase ${textClass} opacity-70`}>
                {isBullish ? 'REGIME STATUS' : 'REGIME STATUS'}
              </span>
              <span className={`font-condensed text-[26px] font-700 tracking-tight leading-none ${textClass} ${isHalt ? 'animate-pulse_halt' : ''} ${isBullish ? 'regime-go' : isHalt ? 'regime-halt' : ''}`}>
                {isBullish ? 'MARKET GO' : 'MARKET HALT'}
              </span>
              {isHalt && (
                <span className="text-[9px] font-400 tracking-widest text-t-halt uppercase opacity-80">
                  SPY &lt; 20 EMA — ENGINES 2 &amp; 3 DISABLED
                </span>
              )}
            </div>
          )}

          {/* SPY metrics */}
          {regime && !isNoData && !isError && (
            <div className="flex gap-4 pl-2">
              <MetricCell label="SPY" value={`$${regime.spy_close.toFixed(2)}`} color={textClass} />
              <MetricCell label="EMA-20" value={`$${regime.spy_20ema.toFixed(2)}`} color="text-t-muted" />
              <MetricCell
                label="Δ"
                value={`${regime.spy_close > regime.spy_20ema ? '+' : ''}${(regime.spy_close - regime.spy_20ema).toFixed(2)}`}
                color={isBullish ? 'text-t-go' : 'text-t-halt'}
              />
            </div>
          )}
        </div>

        {/* Centre — Manual Ticker Search */}
        <div className="flex-1 flex items-center justify-center px-6">
          <TickerSearch onSearch={onSearchTicker} />
        </div>

        {/* Right block — scan controls */}
        <div className="flex items-center gap-5 px-5 border-l border-t-border">
          {/* Scan metadata */}
          <div className="flex flex-col gap-0.5 text-right">
            {scanStatus.in_progress ? (
              <>
                <span className="text-[9px] tracking-widest uppercase text-t-accent animate-pulse">
                  SCANNING…
                </span>
                <span className="text-[11px] text-t-text font-mono tabular-nums">
                  {scanStatus.progress} / {scanStatus.total}
                  <span className="text-t-muted"> tickers</span>
                </span>
              </>
            ) : (
              <>
                <span className="text-[9px] tracking-widest uppercase text-t-muted">Last Scan</span>
                <span className="text-[11px] text-t-text font-mono">
                  {scanStatus.last_completed
                    ? fmtTime(scanStatus.last_completed)
                    : <span className="text-t-muted">waiting</span>
                  }
                </span>
              </>
            )}
          </div>

          {/* Guide button */}
          <button
            onClick={onOpenGuide}
            style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.08em',
              padding: '5px 12px',
              background: 'transparent',
              border: '1px solid var(--border-light)',
              color: 'var(--muted)',
              cursor: 'pointer',
              textTransform: 'uppercase',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent)'
              e.currentTarget.style.color = 'var(--accent)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-light)'
              e.currentTarget.style.color = 'var(--muted)'
            }}
            title="System Guide & Legend (?)"
          >
            ? GUIDE
          </button>

          {/* Run scan button */}
          <button
            className={`btn-scan${scanStatus.in_progress ? ' scanning' : ''}`}
            onClick={onRunScan}
            disabled={scanStatus.in_progress}
          >
            {scanStatus.in_progress ? (
              <span>{Math.round(scanStatus.progress_pct ?? 0)}%</span>
            ) : (
              'RUN SCAN'
            )}
          </button>
        </div>

      </div>
    </header>
  )
}

function MetricCell({ label, value, color }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9px] tracking-widest uppercase text-t-muted">{label}</span>
      <span className={`text-[13px] font-600 font-mono tabular-nums leading-none ${color}`}>{value}</span>
    </div>
  )
}

function TickerSearch({ onSearch }) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const inputRef = useRef(null)

  const commit = () => {
    const sym = value.trim().toUpperCase()
    if (!sym) return
    onSearch?.(sym)
    setValue('')
    inputRef.current?.blur()
  }

  const handleKey = (e) => {
    if (e.key === 'Enter') commit()
    if (e.key === 'Escape') { setValue(''); inputRef.current?.blur() }
  }

  return (
    <div className="flex flex-col items-center gap-1">
      {/* Label */}
      <span className="text-[9px] tracking-[0.2em] uppercase text-t-muted">
        CHART LOOKUP
      </span>

      {/* Input row */}
      <div
        className="flex items-center gap-0"
        style={{
          border: `1px solid ${focused ? 'var(--accent)' : 'var(--border-light)'}`,
          background: 'var(--surface)',
          transition: 'border-color 0.15s',
          boxShadow: focused ? '0 0 8px rgba(245,166,35,0.15)' : 'none',
        }}
      >
        {/* Prompt glyph */}
        <span
          className="px-2 text-[12px] select-none"
          style={{ color: focused ? 'var(--accent)' : 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}
        >
          &gt;_
        </span>

        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          onKeyDown={handleKey}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="AAPL, NVDA…"
          maxLength={6}
          spellCheck={false}
          autoComplete="off"
          autoFocus
          style={{
            width: 100,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: 'var(--accent)',
            fontFamily: 'IBM Plex Mono, monospace',
            fontSize: 13,
            fontWeight: 600,
            letterSpacing: '0.12em',
            padding: '4px 0',
            caretColor: 'var(--accent)',
          }}
        />

        {/* Enter button */}
        <button
          onClick={commit}
          title="Load chart (Enter)"
          style={{
            background: value ? 'var(--accent)' : 'transparent',
            border: 'none',
            borderLeft: `1px solid ${value ? 'transparent' : 'var(--border)'}`,
            color: value ? '#000' : 'var(--muted)',
            fontFamily: 'IBM Plex Mono, monospace',
            fontSize: 10,
            fontWeight: 700,
            padding: '0 8px',
            height: '100%',
            cursor: value ? 'pointer' : 'default',
            transition: 'background 0.12s, color 0.12s',
            letterSpacing: '0.08em',
            alignSelf: 'stretch',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          GO
        </button>
      </div>

      {/* Hint */}
      <span className="text-[8px] tracking-widest text-t-muted opacity-50">
        Press Enter to render chart
      </span>
    </div>
  )
}
