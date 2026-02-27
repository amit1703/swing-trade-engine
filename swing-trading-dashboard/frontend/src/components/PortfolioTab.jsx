/**
 * PortfolioTab — Full-width active trade manager
 *
 * Columns: TICKER | QTY | ENTRY $ | CURRENT $ | P/L $ | P/L % | STOP $ | TARGET $ | HEALTH | ACT
 *
 * Health badges:
 *   HOLD     → green   (Close > EMA-20)
 *   CAUTION  → amber   (Close < EMA-8 but above EMA-20)
 *   EXIT     → red     (Close < EMA-20 OR CCI hooked below 100)
 *   UNKNOWN  → muted   (live fetch failed)
 *
 * Add Trade modal includes position-sizing calculator:
 *   Risk $200 → quantity = 200 / (entry_price - stop_loss)
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchTrades, addTrade, closeTrade } from '../api.js'

// ─────────────────────────────────────────────────────────────────────────────
// Health config
// ─────────────────────────────────────────────────────────────────────────────

const HEALTH = {
  HOLD:    { label: 'HOLD',    bg: 'rgba(0,200,122,0.15)',  border: 'rgba(0,200,122,0.4)',  color: 'var(--go)'    },
  CAUTION: { label: 'CAUTION', bg: 'rgba(245,166,35,0.15)', border: 'rgba(245,166,35,0.4)', color: 'var(--accent)' },
  EXIT:    { label: 'EXIT',    bg: 'rgba(255,45,85,0.18)',  border: 'rgba(255,45,85,0.45)', color: 'var(--halt)'  },
  UNKNOWN: { label: '—',       bg: 'transparent',           border: 'var(--border)',         color: 'var(--muted)' },
}

// ─────────────────────────────────────────────────────────────────────────────

export default function PortfolioTab({ onTickerClick }) {
  const [trades,      setTrades     ] = useState([])
  const [loading,     setLoading    ] = useState(false)
  const [showModal,   setShowModal  ] = useState(false)
  const refreshTimer                  = useRef(null)

  const loadTrades = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchTrades()
      setTrades(res.trades ?? [])
    } catch (err) {
      console.error('[Portfolio] fetchTrades:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial load + auto-refresh every 60 s
  useEffect(() => {
    loadTrades()
    refreshTimer.current = setInterval(loadTrades, 60_000)
    return () => clearInterval(refreshTimer.current)
  }, [loadTrades])

  const handleClose = useCallback(async (id) => {
    try {
      await closeTrade(id)
      setTrades((prev) => prev.filter((t) => t.id !== id))
    } catch (err) {
      console.error('[Portfolio] closeTrade:', err)
    }
  }, [])

  const handleAdded = useCallback((trade) => {
    setTrades((prev) => [trade, ...prev])
    setShowModal(false)
  }, [])

  // Portfolio summary totals
  const totalPL = trades.reduce((sum, t) => sum + (t.pl_dollar ?? 0), 0)
  const openCount = trades.length

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: 'var(--bg)' }}>

      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-6 px-5 py-3 border-b flex-shrink-0"
        style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
      >
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] tracking-widest uppercase text-t-muted">Open Positions</span>
          <span className="font-condensed text-[22px] font-700 tracking-tight text-t-accent leading-none">
            {openCount}
          </span>
        </div>

        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] tracking-widest uppercase text-t-muted">Unrealised P/L</span>
          <span
            className="font-condensed text-[22px] font-700 tracking-tight leading-none"
            style={{ color: totalPL >= 0 ? 'var(--go)' : 'var(--halt)' }}
          >
            {totalPL >= 0 ? '+' : ''}{fmt$(totalPL)}
          </span>
        </div>

        <div className="ml-auto flex items-center gap-3">
          {/* Refresh indicator */}
          {loading && (
            <span className="text-[9px] uppercase tracking-widest text-t-muted animate-pulse">
              updating…
            </span>
          )}
          <button
            className="btn-scan"
            onClick={() => setShowModal(true)}
          >
            + ADD TRADE
          </button>
        </div>
      </div>

      {/* ── Trade table ──────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        {loading && trades.length === 0 ? (
          <div className="terminal-placeholder">
            <span className="text-t-muted text-[10px] tracking-widest uppercase">
              Loading positions
            </span>
          </div>
        ) : trades.length === 0 ? (
          <div className="terminal-placeholder">
            <pre className="text-t-border text-[10px] leading-tight select-none">{
`  ┌────────────────────────────┐
  │  no active trades          │
  │                            │
  │  click + ADD TRADE to      │
  │  start tracking positions  │
  └────────────────────────────┘`
            }</pre>
            <span className="text-[9px] text-t-muted uppercase tracking-widest">
              Active trades appear here
            </span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="terminal-table" style={{ minWidth: 900 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left' }}>Ticker</th>
                  <th>Qty</th>
                  <th>Entry $</th>
                  <th>Current $</th>
                  <th>P/L $</th>
                  <th>P/L %</th>
                  <th>Stop $</th>
                  <th>Trail $</th>
                  <th>T1 $</th>
                  <th>T2 $</th>
                  <th>T3 $</th>
                  <th style={{ textAlign: 'center' }}>Health</th>
                  <th style={{ textAlign: 'center' }}>Act</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => {
                  const h   = HEALTH[t.health] ?? HEALTH.UNKNOWN
                  const plPos = (t.pl_dollar ?? 0) >= 0
                  const isExit = t.health === 'EXIT'

                  return (
                    <tr
                      key={t.id}
                      style={isExit ? { background: 'rgba(255,45,85,0.04)' } : undefined}
                    >
                      {/* Ticker — clickable to load chart */}
                      <td>
                        <button
                          className="font-600 tracking-wide text-left"
                          style={{ color: 'var(--blue)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: 'inherit' }}
                          onClick={() => onTickerClick?.(t.ticker)}
                          title="Open chart"
                        >
                          {t.ticker}
                        </button>
                      </td>

                      {/* Qty */}
                      <td className="text-t-text">{fmtN(t.quantity)}</td>

                      {/* Entry */}
                      <td className="text-t-muted">{fmt2(t.entry_price)}</td>

                      {/* Current */}
                      <td className="text-t-text font-600">
                        {t.current_price != null ? fmt2(t.current_price) : <Dash />}
                      </td>

                      {/* P/L $ */}
                      <td className={plPos ? 'pl-positive' : 'pl-negative'}
                          style={{ color: plPos ? 'var(--go)' : 'var(--halt)', fontWeight: 600 }}>
                        {t.pl_dollar != null
                          ? `${plPos ? '+' : ''}${fmt$(t.pl_dollar)}`
                          : <Dash />}
                      </td>

                      {/* P/L % */}
                      <td className={plPos ? 'pl-positive' : 'pl-negative'}
                          style={{ color: plPos ? 'var(--go)' : 'var(--halt)' }}>
                        {t.pl_pct != null
                          ? `${plPos ? '+' : ''}${t.pl_pct.toFixed(2)}%`
                          : <Dash />}
                      </td>

                      {/* Stop */}
                      <td style={{ color: 'var(--halt)' }}>{fmt2(t.stop_loss)}</td>

                      {/* Trailing Stop — blue when risk-free */}
                      <td style={{ color: t.is_risk_free ? '#00C8FF' : 'var(--halt)', fontWeight: t.is_risk_free ? 700 : 400 }}>
                        {fmt2(t.trailing_stop)}
                        {t.is_risk_free && (
                          <span style={{ fontSize: 7, marginLeft: 4, color: '#00C8FF', opacity: 0.8 }}>RF</span>
                        )}
                      </td>

                      {/* T1 */}
                      <td style={{ color: 'var(--go)' }}>{fmt2(t.targets?.[0] ?? t.target)}</td>
                      {/* T2 */}
                      <td style={{ color: 'var(--go)' }}>
                          {t.targets?.[1] != null ? fmt2(t.targets[1]) : <Dash />}
                      </td>
                      {/* T3 */}
                      <td style={{ color: 'var(--go)' }}>
                          {t.targets?.[2] != null ? fmt2(t.targets[2]) : <Dash />}
                      </td>

                      {/* Health badge */}
                      <td style={{ textAlign: 'center' }}>
                        <span
                          className="badge"
                          style={{
                            background: h.bg,
                            border:     `1px solid ${h.border}`,
                            color:      h.color,
                            fontWeight: 700,
                          }}
                        >
                          {h.label}
                        </span>
                      </td>

                      {/* Close button */}
                      <td style={{ textAlign: 'center' }}>
                        <button
                          onClick={() => handleClose(t.id)}
                          title="Close trade"
                          style={{
                            background: 'transparent',
                            border: '1px solid var(--border-light)',
                            color: 'var(--muted)',
                            fontFamily: 'IBM Plex Mono, monospace',
                            fontSize: 9,
                            fontWeight: 600,
                            padding: '2px 6px',
                            cursor: 'pointer',
                            letterSpacing: '0.06em',
                            textTransform: 'uppercase',
                            transition: 'border-color 0.12s, color 0.12s',
                          }}
                          onMouseEnter={e => { e.target.style.borderColor = 'var(--halt)'; e.target.style.color = 'var(--halt)' }}
                          onMouseLeave={e => { e.target.style.borderColor = 'var(--border-light)'; e.target.style.color = 'var(--muted)' }}
                        >
                          CLOSE
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Add Trade Modal ───────────────────────────────────────────────── */}
      {showModal && (
        <AddTradeModal
          onAdd={handleAdded}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Add Trade Modal
// ─────────────────────────────────────────────────────────────────────────────

const RISK_AMOUNT = 200   // default risk per trade in $

function AddTradeModal({ onAdd, onClose }) {
  const [form, setForm] = useState({
    ticker:      '',
    entry_price: '',
    stop_loss:   '',
    quantity:    '',
    targets:     ['', '', ''],
    entry_date:  new Date().toISOString().slice(0, 10),
    notes:       '',
  })
  const [targetCount, setTargetCount] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState('')
  const tickerRef                   = useRef(null)

  useEffect(() => { tickerRef.current?.focus() }, [])

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  // Auto-calculate suggested target at 2:1 R:R
  const entry = parseFloat(form.entry_price) || 0
  const stop  = parseFloat(form.stop_loss)   || 0
  const risk  = entry - stop

  const calcPositionSize = () => {
    if (risk <= 0) { setError('Entry must be greater than Stop Loss'); return }
    const qty = Math.floor(RISK_AMOUNT / risk)
    const t1  = +(entry + 2 * risk).toFixed(2)
    setForm((f) => {
        const targets = [...f.targets]
        targets[0] = String(t1)
        return { ...f, quantity: String(qty), targets }
    })
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    const ep  = parseFloat(form.entry_price)
    const sl  = parseFloat(form.stop_loss)
    const qty = parseFloat(form.quantity)
    const t1 = parseFloat(form.targets[0])
    const t2 = form.targets[1] !== '' ? parseFloat(form.targets[1]) : null
    const t3 = form.targets[2] !== '' ? parseFloat(form.targets[2]) : null

    if (!form.ticker.trim())      { setError('Ticker is required'); return }
    if (!ep || ep <= 0)            { setError('Enter a valid entry price'); return }
    if (!sl || sl <= 0)            { setError('Enter a valid stop loss'); return }
    if (sl >= ep)                  { setError('Stop loss must be below entry price'); return }
    if (!qty || qty <= 0)          { setError('Enter a valid quantity'); return }
    if (!t1 || t1 <= ep)                            { setError('T1 must be above entry price'); return }
    if (t2 !== null && t2 <= t1)                    { setError('T2 must be above T1'); return }
    if (t3 !== null && (t2 === null || t3 <= t2))   { setError('T3 must be above T2'); return }

    setSubmitting(true)
    try {
      const targets = [t1, t2, t3].filter((v) => v !== null)
      const result = await addTrade({
        ticker:      form.ticker.trim().toUpperCase(),
        entry_price: ep,
        quantity:    qty,
        stop_loss:   sl,
        targets,
        entry_date:  form.entry_date,
        notes:       form.notes,
      })
      onAdd(result)
    } catch (err) {
      setError(err.message || 'Failed to add trade')
    } finally {
      setSubmitting(false)
    }
  }

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.82)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border-light)',
          width: 420,
          boxShadow: '0 0 0 1px rgba(245,166,35,0.1), 0 0 60px rgba(0,0,0,0.9)',
        }}
      >
        {/* Modal header */}
        <div
          className="flex items-center justify-between px-5 py-3 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <span className="font-condensed text-[14px] font-700 tracking-widest uppercase text-t-accent">
            ADD TRADE
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 16, lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-0">

          {/* Row: Ticker + Date */}
          <div className="grid grid-cols-2 gap-px" style={{ background: 'var(--border)' }}>
            <ModalField label="Ticker" hint="e.g. AAPL">
              <ModalInput
                ref={tickerRef}
                value={form.ticker}
                onChange={(e) => setForm((f) => ({ ...f, ticker: e.target.value.toUpperCase() }))}
                placeholder="AAPL"
                maxLength={6}
              />
            </ModalField>
            <ModalField label="Entry Date">
              <ModalInput
                type="date"
                value={form.entry_date}
                onChange={set('entry_date')}
              />
            </ModalField>
          </div>

          {/* Row: Entry + Stop */}
          <div className="grid grid-cols-2 gap-px" style={{ background: 'var(--border)' }}>
            <ModalField label="Entry Price $">
              <ModalInput
                type="number" step="0.01" min="0"
                value={form.entry_price}
                onChange={set('entry_price')}
                placeholder="0.00"
              />
            </ModalField>
            <ModalField label="Stop Loss $" hint="Engine 1/2 level">
              <ModalInput
                type="number" step="0.01" min="0"
                value={form.stop_loss}
                onChange={set('stop_loss')}
                placeholder="0.00"
              />
            </ModalField>
          </div>

          {/* Position sizer */}
          <div
            className="px-4 py-2.5 border-b flex items-center justify-between"
            style={{ borderColor: 'var(--border)', background: 'var(--panel)' }}
          >
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] uppercase tracking-widest text-t-muted">Position Sizer</span>
              <span className="text-[10px] text-t-muted">
                Risk ${RISK_AMOUNT} →{' '}
                {risk > 0
                  ? <span className="text-t-accent font-600">{Math.floor(RISK_AMOUNT / risk)} shares  ·  T1: ${+(entry + 2*risk).toFixed(2)}</span>
                  : <span className="text-t-border">enter entry & stop first</span>
                }
              </span>
            </div>
            <button
              type="button"
              onClick={calcPositionSize}
              disabled={risk <= 0}
              style={{
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 10, fontWeight: 600,
                padding: '4px 10px',
                background: risk > 0 ? 'rgba(245,166,35,0.15)' : 'transparent',
                border: `1px solid ${risk > 0 ? 'var(--accent)' : 'var(--border)'}`,
                color: risk > 0 ? 'var(--accent)' : 'var(--muted)',
                cursor: risk > 0 ? 'pointer' : 'default',
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                transition: 'all 0.12s',
                flexShrink: 0,
              }}
            >
              RISK ${RISK_AMOUNT}
            </button>
          </div>

          {/* Row: Quantity */}
          <div className="grid grid-cols-1">
            <ModalField label="Quantity (shares)">
              <ModalInput
                type="number" step="1" min="1"
                value={form.quantity}
                onChange={set('quantity')}
                placeholder="0"
              />
            </ModalField>
          </div>

          {/* Targets section */}
          <div style={{ borderBottom: '1px solid var(--border)' }}>
            {/* T1 — always visible */}
            <div style={{ borderBottom: '1px solid var(--border)' }}>
              <ModalField label="T1 $ (required)" hint="2:1 auto-filled">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <ModalInput
                    type="number" step="0.01" min="0"
                    value={form.targets[0]}
                    onChange={(e) => setForm(f => { const t = [...f.targets]; t[0] = e.target.value; return { ...f, targets: t } })}
                    placeholder="0.00"
                    style={{ flex: 1 }}
                  />
                  {risk > 0 && (
                    <button type="button"
                      onClick={() => setForm(f => { const t = [...f.targets]; t[0] = String(+(entry + 2*risk).toFixed(2)); return { ...f, targets: t } })}
                      style={{ fontSize: 9, padding: '2px 6px', background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                      +2R
                    </button>
                  )}
                </div>
              </ModalField>
            </div>

            {/* T2 */}
            {targetCount >= 2 ? (
              <div style={{ borderBottom: '1px solid var(--border)' }}>
                <ModalField label="T2 $">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ModalInput
                      type="number" step="0.01" min="0"
                      value={form.targets[1]}
                      onChange={(e) => setForm(f => { const t = [...f.targets]; t[1] = e.target.value; return { ...f, targets: t } })}
                      placeholder="0.00"
                      style={{ flex: 1 }}
                    />
                    {risk > 0 && (
                      <button type="button"
                        onClick={() => setForm(f => { const t = [...f.targets]; t[1] = String(+(entry + 3*risk).toFixed(2)); return { ...f, targets: t } })}
                        style={{ fontSize: 9, padding: '2px 6px', background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                        +3R
                      </button>
                    )}
                    <button type="button"
                      onClick={() => { setTargetCount(1); setForm(f => { const t = [...f.targets]; t[1] = ''; t[2] = ''; return { ...f, targets: t } }) }}
                      style={{ fontSize: 9, padding: '2px 6px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                      ×
                    </button>
                  </div>
                </ModalField>
              </div>
            ) : (
              <div className="px-4 py-2" style={{ borderBottom: '1px solid var(--border)', background: 'var(--panel)' }}>
                <button type="button" onClick={() => setTargetCount(2)}
                  style={{ fontSize: 9, padding: '2px 8px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                  + T2
                </button>
              </div>
            )}

            {/* T3 — only available after T2 is added */}
            {targetCount >= 2 && (
              targetCount >= 3 ? (
                <ModalField label="T3 $">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ModalInput
                      type="number" step="0.01" min="0"
                      value={form.targets[2]}
                      onChange={(e) => setForm(f => { const t = [...f.targets]; t[2] = e.target.value; return { ...f, targets: t } })}
                      placeholder="0.00"
                      style={{ flex: 1 }}
                    />
                    {risk > 0 && (
                      <button type="button"
                        onClick={() => setForm(f => { const t = [...f.targets]; t[2] = String(+(entry + 4*risk).toFixed(2)); return { ...f, targets: t } })}
                        style={{ fontSize: 9, padding: '2px 6px', background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                        +4R
                      </button>
                    )}
                    <button type="button"
                      onClick={() => { setTargetCount(2); setForm(f => { const t = [...f.targets]; t[2] = ''; return { ...f, targets: t } }) }}
                      style={{ fontSize: 9, padding: '2px 6px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em' }}>
                      ×
                    </button>
                  </div>
                </ModalField>
              ) : (
                <div className="px-4 py-2" style={{ background: 'var(--panel)' }}>
                  <button type="button" onClick={() => setTargetCount(3)}
                    style={{ fontSize: 9, padding: '2px 8px', background: 'transparent', border: '1px solid var(--border-light)', color: 'var(--muted)', cursor: 'pointer', fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                    + T3
                  </button>
                </div>
              )
            )}
          </div>

          {/* Notes */}
          <div className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--border)' }}>
            <label className="text-[9px] uppercase tracking-widest text-t-muted block mb-1">
              Notes (optional)
            </label>
            <input
              type="text"
              value={form.notes}
              onChange={set('notes')}
              placeholder="Setup type, trigger, etc."
              maxLength={120}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                outline: 'none',
                color: 'var(--text)',
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 11,
                padding: '2px 0',
              }}
            />
          </div>

          {/* Error */}
          {error && (
            <div className="px-4 py-2 text-[10px]" style={{ color: 'var(--halt)', background: 'rgba(255,45,85,0.06)' }}>
              {error}
            </div>
          )}

          {/* Actions */}
          <div
            className="flex justify-end gap-3 px-4 py-3"
            style={{ borderTop: '1px solid var(--border)' }}
          >
            <button
              type="button" onClick={onClose}
              style={{
                fontFamily: 'IBM Plex Mono, monospace', fontSize: 11, fontWeight: 600,
                padding: '5px 14px', background: 'transparent',
                border: '1px solid var(--border)', color: 'var(--muted)', cursor: 'pointer',
                letterSpacing: '0.08em', textTransform: 'uppercase',
              }}
            >
              CANCEL
            </button>
            <button
              type="submit" disabled={submitting}
              className="btn-scan"
              style={{ opacity: submitting ? 0.6 : 1 }}
            >
              {submitting ? 'ADDING…' : 'ADD TRADE'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function ModalField({ label, hint, children }) {
  return (
    <div className="px-4 py-2.5" style={{ background: 'var(--panel)', borderBottom: '1px solid var(--border)' }}>
      <label className="text-[9px] uppercase tracking-widest text-t-muted block mb-1">
        {label}{hint && <span className="ml-1 opacity-50">— {hint}</span>}
      </label>
      {children}
    </div>
  )
}

import { forwardRef } from 'react'
const ModalInput = forwardRef(function ModalInput({ ...props }, ref) {
  return (
    <input
      ref={ref}
      {...props}
      style={{
        width: '100%',
        background: 'transparent',
        border: 'none',
        outline: 'none',
        color: 'var(--accent)',
        fontFamily: 'IBM Plex Mono, monospace',
        fontSize: 12,
        fontWeight: 600,
        padding: '2px 0',
        caretColor: 'var(--accent)',
        ...props.style,
      }}
    />
  )
})

function Dash() {
  return <span style={{ color: 'var(--border-light)' }}>—</span>
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const fmt2 = (n) => n == null ? '—' : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmt$ = (n) => Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtN = (n) => n == null ? '—' : Number.isInteger(n) ? n.toLocaleString('en-US') : n.toFixed(1)
