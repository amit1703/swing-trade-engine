/**
 * Header — Market Regime Banner
 *
 * GO    → solid green bar, large label, SPY data
 * HALT  → solid red bar, pulsing, SPY data
 * NO_DATA / loading → neutral state
 */
import { useRef, useState } from 'react'
import { useAppSettings } from '../contexts/AppSettingsContext'

export default function Header({ regime, scanStatus, onRunScan, onSearchTicker, onOpenGuide, devMode, dryRun, onToggleDev, onToggleDryRun }) {
  const { tr, lang } = useAppSettings()
  const regimeType = regime?.regime  // "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE" | undefined
  const isNoData   = !regime || !regimeType || regimeType === 'NO_DATA'
  const isAggressive = regimeType === 'AGGRESSIVE'
  const isSelective  = regimeType === 'SELECTIVE'
  const isDefensive  = regimeType === 'DEFENSIVE' || (regime && !regime.is_bullish && !isNoData)

  // Colors for 3 states
  let bgClass   = ''
  let textClass = ''
  if (isAggressive) { bgClass = 'bg-t-goDim';     textClass = 'text-t-go'    }
  if (isSelective)  { bgClass = 'bg-t-accentDim';  textClass = 'text-t-accent' }
  if (isDefensive)  { bgClass = 'bg-t-haltDim';    textClass = 'text-t-halt'   }

  const regimeLabel = isAggressive ? 'BULL'
    : isSelective ? 'NEUTRAL'
    : isDefensive ? 'HALT'
    : 'NO DATA'

  const isBullish = regime?.is_bullish
  const engines = [
    { id: 2, label: 'VCP',  active: !!isBullish },
    { id: 3, label: 'PB',   active: !!isBullish },
    { id: 5, label: 'BASE', active: true },
    { id: 6, label: 'BRK',  active: true },
  ]

  // Determine stripe color for the left indicator
  let stripeClass = 'bg-t-muted'
  if (isAggressive) { stripeClass = 'bg-t-go'   }
  if (isSelective)  { stripeClass = 'bg-t-accent' }
  if (isDefensive)  { stripeClass = 'bg-t-halt'   }

  const fmtTime = (iso) => {
    if (!iso) return '—'
    const d = new Date(iso + 'Z')
    return d.toLocaleTimeString('en-US', { hour12: false })
  }

  return (
    <header className="relative flex flex-col border-b border-t-border select-none bg-t-surface">

      {/* Progress bar — sits at very top, 0px height when idle */}
      <div className="progress-bar w-full" style={{ opacity: scanStatus.in_progress ? 1 : 0, transition: 'opacity 0.3s' }}>
        <div
          className="progress-bar-fill"
          style={{ width: `${scanStatus.progress_pct ?? 0}%`, transition: 'width 0.6s ease-out' }}
        />
      </div>

      {/* Main row */}
      <div className="flex items-stretch h-[62px]">

        {/* Left stripe (regime colour indicator) */}
        <div className={`w-1 flex-shrink-0 ${stripeClass} ${isDefensive ? 'animate-pulse_halt' : ''}`} />

        {/* REGIME STATUS — left block */}
        <div
          className={`flex flex-col justify-center px-4 border-r border-t-border ${bgClass}`}
          style={{ minWidth: 380, gap: 2 }}
        >
          {isNoData ? (
            <span className="font-condensed text-[22px] font-700 tracking-tight text-t-muted">NO DATA</span>
          ) : (
            <>
              {/* Row 1: label + score badge */}
              <div className="flex items-center gap-3">
                <span className="font-condensed text-[9px] font-700 tracking-widest uppercase text-t-muted opacity-60">REGIME</span>
                <span className={`font-condensed text-[22px] font-700 tracking-tight leading-none ${textClass}`}>
                  {regimeLabel}
                </span>
                {regime.regime_score != null && (
                  <span className="font-mono tabular-nums" style={{
                    fontSize: 10,
                    padding: '1px 6px',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid var(--border-light)',
                    color: isAggressive ? 'var(--go)' : isSelective ? 'var(--accent)' : 'var(--halt)',
                    borderRadius: 2,
                    letterSpacing: '0.04em',
                  }}>
                    {regime.regime_score.toFixed(1)}/100
                  </span>
                )}
              </div>

              {/* Row 2: SPY + SMA50 + VIX + Breadth */}
              <div className="flex items-center gap-3">
                <span className={`tabular-nums text-[10px] ${lang === 'he' ? 'font-sans' : 'font-mono'}`}>
                  <span className="text-t-muted text-[8px] mr-1">{tr('regime.spyClose')}</span>
                  <span className={textClass}>${regime.spy_close?.toFixed(2)}</span>
                </span>
                {(regime.spy_sma50 ?? 0) > 0 && (
                  <span className={`text-[9px] tabular-nums ${lang === 'he' ? 'font-sans' : 'font-mono'}`}>
                    <span className="text-t-muted text-[8px] mr-0.5">{tr('regime.sma50')}</span>
                    <span style={{ color: regime.spy_close > regime.spy_sma50 ? 'var(--go)' : 'var(--halt)' }}>
                      {regime.spy_close > regime.spy_sma50 ? '✔' : '✖'}
                    </span>
                  </span>
                )}
                {(regime.vix ?? 0) > 0 && (
                  <span className={`text-[9px] tabular-nums ${lang === 'he' ? 'font-sans' : 'font-mono'}`}>
                    <span className="text-t-muted text-[8px] mr-0.5">{tr('regime.vix')}</span>
                    <span style={{ color: 'var(--muted)' }}>{regime.vix.toFixed(1)}</span>
                  </span>
                )}
                {regime.breadth_pct != null && (
                  <span className={`text-[9px] tabular-nums ${lang === 'he' ? 'font-sans' : 'font-mono'}`}>
                    <span className="text-t-muted text-[8px] mr-0.5">{tr('regime.breadth')}</span>
                    <span style={{ color: regime.breadth_pct > 0.6 ? 'var(--go)' : regime.breadth_pct > 0.4 ? 'var(--accent)' : 'var(--halt)' }}>
                      {Math.round(regime.breadth_pct * 100)}%
                    </span>
                  </span>
                )}
              </div>

              {/* Row 3: Engine status */}
              <div className="flex items-center gap-2">
                <span className="text-[8px] tracking-widest uppercase text-t-muted">ENG</span>
                {engines.map(({ id, label, active }) => (
                  <span key={id} className="font-mono text-[8px]"
                    style={{ color: active ? 'var(--go)' : 'rgba(255,45,85,0.6)' }}
                    title={`Engine ${id}: ${active ? 'active' : 'disabled'}`}>
                    {label}{active ? '✔' : '✖'}
                  </span>
                ))}
              </div>
            </>
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
                  {scanStatus.rebuilding_universe ? 'REBUILDING UNIVERSE…' : scanStatus.prefetching ? 'LOADING DATA…' : 'SCANNING…'}
                </span>
                <span className="text-[11px] text-t-text font-mono tabular-nums">
                  {scanStatus.rebuilding_universe
                    ? <span className="text-t-muted">updating ticker list (10–15 min)</span>
                    : scanStatus.prefetching
                    ? <span className="text-t-muted">downloading price history…</span>
                    : <>{scanStatus.progress} / {scanStatus.total}<span className="text-t-muted"> tickers</span></>
                  }
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

          {/* Dev mode toggle */}
          <button
            onClick={onToggleDev}
            style={{
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.08em',
              padding: '5px 10px',
              background: devMode ? 'rgba(245,166,35,0.12)' : 'transparent',
              border: `1px solid ${devMode ? 'var(--accent)' : 'var(--border-light)'}`,
              color: devMode ? 'var(--accent)' : 'var(--muted)',
              cursor: 'pointer',
              textTransform: 'uppercase',
              transition: 'all 0.15s',
              boxShadow: devMode ? '0 0 8px rgba(245,166,35,0.2)' : 'none',
            }}
            title="Toggle Dev Mode"
          >
            {devMode ? '⚠ DEV' : 'DEV'}
          </button>

          {/* Dry-run sub-toggle — only visible when devMode active */}
          {devMode && (
            <button
              onClick={onToggleDryRun}
              style={{
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.06em',
                padding: '4px 8px',
                background: dryRun ? 'rgba(155,110,255,0.12)' : 'transparent',
                border: `1px solid ${dryRun ? '#9b6eff' : 'var(--border-light)'}`,
                color: dryRun ? '#9b6eff' : 'var(--muted)',
                cursor: 'pointer',
                textTransform: 'uppercase',
                transition: 'all 0.15s',
              }}
              title="Dry Run — scan without saving to DB"
            >
              DRY RUN
            </button>
          )}

          {/* Email digest button */}
          <EmailDigest />

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

function TickerScan({ onScan, disabled }) {
  const [value, setValue] = useState('')
  const inputRef = useRef(null)

  const commit = () => {
    const sym = value.trim().toUpperCase()
    if (!sym || disabled) return
    onScan?.(sym)
    setValue('')
    inputRef.current?.blur()
  }

  const handleKey = (e) => {
    if (e.key === 'Enter') commit()
    if (e.key === 'Escape') { setValue(''); inputRef.current?.blur() }
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        border: '1px solid rgba(245,166,35,0.35)',
        background: 'rgba(245,166,35,0.04)',
        opacity: disabled ? 0.4 : 1,
        transition: 'opacity 0.15s',
      }}
      title="Scan a single ticker (dev)"
    >
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        onKeyDown={handleKey}
        placeholder="TICKER"
        maxLength={6}
        spellCheck={false}
        autoComplete="off"
        disabled={disabled}
        style={{
          width: 72,
          background: 'transparent',
          border: 'none',
          outline: 'none',
          color: 'var(--accent)',
          fontFamily: 'IBM Plex Mono, monospace',
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '0.1em',
          padding: '4px 8px',
          caretColor: 'var(--accent)',
        }}
      />
      <button
        onClick={commit}
        disabled={disabled || !value}
        style={{
          background: value && !disabled ? 'rgba(245,166,35,0.20)' : 'transparent',
          border: 'none',
          borderLeft: '1px solid rgba(245,166,35,0.25)',
          color: value && !disabled ? 'var(--accent)' : 'var(--muted)',
          fontFamily: 'IBM Plex Mono, monospace',
          fontSize: 9,
          fontWeight: 700,
          padding: '0 8px',
          height: '100%',
          cursor: value && !disabled ? 'pointer' : 'default',
          transition: 'background 0.12s, color 0.12s',
          letterSpacing: '0.1em',
          alignSelf: 'stretch',
          display: 'flex',
          alignItems: 'center',
          textTransform: 'uppercase',
        }}
      >
        SCAN
      </button>
    </div>
  )
}

function EmailDigest() {
  const [open, setOpen]     = useState(false)
  const [email, setEmail]   = useState('')
  const [status, setStatus] = useState(null) // null | 'sending' | 'ok' | 'error'
  const [msg, setMsg]       = useState('')
  const inputRef = useRef(null)

  const toggle = () => {
    setOpen(v => !v)
    setStatus(null)
    setMsg('')
  }

  const send = async () => {
    const addr = email.trim()
    if (!addr) return
    setStatus('sending')
    setMsg('')
    try {
      const res = await fetch(`/api/send-digest?email=${encodeURIComponent(addr)}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        setStatus('error')
        setMsg(data.detail ?? 'Failed')
      } else {
        setStatus('ok')
        setMsg(`Sent ${data.setups} setups to ${data.email}`)
        setTimeout(() => { setOpen(false); setStatus(null); setEmail('') }, 3000)
      }
    } catch {
      setStatus('error')
      setMsg('Network error')
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter') send()
    if (e.key === 'Escape') toggle()
  }

  const accentColor = '#4fc3f7'

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={toggle}
        style={{
          fontFamily: 'IBM Plex Mono, monospace',
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '0.08em',
          padding: '5px 12px',
          background: open ? `rgba(79,195,247,0.10)` : 'transparent',
          border: `1px solid ${open ? accentColor : 'var(--border-light)'}`,
          color: open ? accentColor : 'var(--muted)',
          cursor: 'pointer',
          textTransform: 'uppercase',
          transition: 'all 0.15s',
        }}
        title="Send digest to email"
      >
        ✉ DIGEST
      </button>

      {open && (
        <div style={{
          position: 'absolute',
          top: '110%',
          right: 0,
          zIndex: 200,
          background: 'var(--surface)',
          border: `1px solid ${accentColor}`,
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          minWidth: 280,
          boxShadow: `0 4px 20px rgba(0,0,0,0.5)`,
        }}>
          <span style={{ fontSize: 9, letterSpacing: '0.15em', color: 'var(--muted)', textTransform: 'uppercase' }}>
            Send digest to
          </span>
          <div style={{ display: 'flex', gap: 0, border: `1px solid ${accentColor}` }}>
            <input
              ref={inputRef}
              autoFocus
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onKeyDown={handleKey}
              placeholder="you@example.com"
              disabled={status === 'sending'}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                outline: 'none',
                color: accentColor,
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 11,
                padding: '5px 8px',
                caretColor: accentColor,
              }}
            />
            <button
              onClick={send}
              disabled={!email.trim() || status === 'sending'}
              style={{
                background: email.trim() && status !== 'sending' ? `rgba(79,195,247,0.20)` : 'transparent',
                border: 'none',
                borderLeft: `1px solid ${accentColor}`,
                color: email.trim() && status !== 'sending' ? accentColor : 'var(--muted)',
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 10,
                fontWeight: 700,
                padding: '0 10px',
                cursor: email.trim() && status !== 'sending' ? 'pointer' : 'default',
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
              }}
            >
              {status === 'sending' ? '…' : 'SEND'}
            </button>
          </div>
          {msg && (
            <span style={{
              fontSize: 10,
              color: status === 'ok' ? 'var(--go)' : 'var(--halt)',
              fontFamily: 'IBM Plex Mono, monospace',
            }}>
              {status === 'ok' ? '✓ ' : '✗ '}{msg}
            </span>
          )}
        </div>
      )}
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
